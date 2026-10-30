"""F3 订单持久化、发布校验和支付事件入口。"""
import hashlib
import hmac
import json
import os
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...database import get_db
from . import integrations
from .models import Order, PaymentReceipt
from .schemas import DemoSession, OrderDraft, PaymentEvent

router = APIRouter(prefix="/api/orders", tags=["orders"])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def view(order):
    return {
        "orderId": order.id, "publisherUid": order.publisher_uid,
        "company": order.company, "code": order.pickup_code, "station": order.station,
        "size": order.size, "weight": order.weight_kg, "address": order.delivery_address,
        "expectedAt": order.expected_at.isoformat() + ("Z" if order.expected_at.tzinfo is None else ""),
        "note": order.note, "baseFeeCents": order.base_fee_cents, "tipCents": order.tip_cents,
        "amountCents": order.amount_cents, "amount": f"{order.amount_cents / 100:.2f}",
        "status": order.status, "pricingSource": order.pricing_source,
    }


def owned_order(db, order_id, identity):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    if order.publisher_uid != identity.uid:
        raise HTTPException(403, "无权查看或支付此订单")
    return order


def require_verified(identity):
    if not identity.verified:
        raise HTTPException(403, "请先完成学生认证后再发布需求")


@router.get("/integration-context")
def context(request: Request):
    mode = integrations.dependency_mode()
    try:
        identity = integrations.current_identity(request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {"mode": mode, "user": None, "verified": False}
    return {"mode": mode, "user": {"uid": identity.uid, "nickname": identity.nickname},
            "verified": identity.verified}


@router.post("/demo/session")
def demo_session(body: DemoSession, response: Response):
    if integrations.dependency_mode() != "demo":
        raise HTTPException(404, "此接口不可用")
    response.set_cookie("f3_demo_session", body.state, httponly=True, samesite="strict")
    return {"state": body.state}


@router.post("/quote")
def quote(body: OrderDraft, request: Request,
          identity=Depends(integrations.current_identity)):
    require_verified(identity)
    return integrations.quote(body, request)


@router.post("", status_code=201)
def create_order(body: OrderDraft, request: Request,
                 idempotency_key: str = Header(min_length=8, max_length=100),
                 identity=Depends(integrations.current_identity), db: Session = Depends(get_db)):
    require_verified(identity)
    digest = fingerprint(body.model_dump(mode="json"))
    existing_query = select(Order).where(Order.publisher_uid == identity.uid,
                                         Order.request_key == idempotency_key)
    existing = db.scalar(existing_query)
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(409, "本次提交标识已被其他内容使用，请重新提交")
        return view(existing)
    fees = integrations.quote(body, request)
    order = Order(
        id=str(uuid4()), publisher_uid=identity.uid, request_key=idempotency_key,
        request_hash=digest, company=body.company, pickup_code=body.code,
        station=body.station, size=body.size, weight_kg=str(body.weight),
        address=body.address, expected_at=body.expectedAt,
        note=body.note, base_fee_cents=fees["baseFeeCents"], tip_cents=fees["tipCents"],
        amount_cents=fees["amountCents"], pricing_source=fees["pricingSource"],
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(existing_query)
        if existing and existing.request_hash == digest:
            return view(existing)
        raise HTTPException(409, "订单提交冲突，请重试")
    db.refresh(order)
    return view(order)


@router.get("/mine")
def my_orders(identity=Depends(integrations.current_identity), db: Session = Depends(get_db)):
    orders = db.scalars(select(Order).where(Order.publisher_uid == identity.uid)
                        .order_by(Order.created_at.desc()).limit(50)).all()
    return {"items": [view(order) for order in orders]}


def accept_payment(event, db):
    digest = fingerprint(event.model_dump())
    receipt = db.get(PaymentReceipt, event.eventId)
    if receipt:
        if receipt.payload_hash != digest:
            raise HTTPException(409, "支付事件标识与原内容不一致")
        return {"accepted": True, "duplicate": True}
    order = db.get(Order, event.orderId)
    if not order:
        raise HTTPException(404, "支付事件对应订单不存在")
    if order.publisher_uid != event.uid or order.amount_cents != event.amountCents:
        raise HTTPException(409, "支付事件与订单用户或金额不一致")
    if order.status != "awaiting_payment":
        if order.paid_payment_id == event.paymentId:
            return {"accepted": True, "duplicate": True}
        raise HTTPException(409, "订单当前状态不允许支付")
    try:
        changed = db.execute(update(Order).where(Order.id == event.orderId,
                                                Order.status == "awaiting_payment")
                             .values(status="pending", paid_payment_id=event.paymentId))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "订单状态已变化，请重试")
        db.add(PaymentReceipt(event_id=event.eventId, order_id=event.orderId,
                              payment_id=event.paymentId, payload_hash=digest))
        db.commit()
    except IntegrityError:
        db.rollback()
        receipt = db.get(PaymentReceipt, event.eventId)
        if receipt and receipt.payload_hash == digest:
            return {"accepted": True, "duplicate": True}
        order = db.get(Order, event.orderId)
        if order and order.paid_payment_id == event.paymentId:
            return {"accepted": True, "duplicate": True}
        raise HTTPException(409, "支付事件重复或冲突")
    return {"accepted": True, "duplicate": False}


@router.post("/events/payment-succeeded")
def payment_event(body: PaymentEvent, x_order_event_secret: str = Header(default=""),
                  db: Session = Depends(get_db)):
    secret = os.getenv("F3_PAYMENT_EVENT_SECRET", "")
    if integrations.dependency_mode() != "external" or not secret or not hmac.compare_digest(secret, x_order_event_secret):
        raise HTTPException(403, "无效的支付事件凭证")
    order = db.get(Order, body.orderId)
    if order and order.pricing_source != "external":
        raise HTTPException(409, "演示订单不接受正式支付")
    return accept_payment(body, db)


@router.get("/{order_id}")
def detail(order_id: str, identity=Depends(integrations.current_identity),
           db: Session = Depends(get_db)):
    return view(owned_order(db, order_id, identity))


@router.post("/{order_id}/prepay")
def prepay(order_id: str, request: Request, identity=Depends(integrations.current_identity),
           db: Session = Depends(get_db)):
    order = owned_order(db, order_id, identity)
    if order.pricing_source != integrations.dependency_mode():
        raise HTTPException(409, "订单创建模式与当前支付模式不一致")
    if order.status != "awaiting_payment":
        raise HTTPException(409, "订单已支付或不允许继续支付")
    return integrations.prepay(order, request)


@router.post("/{order_id}/demo-pay")
def demo_pay(order_id: str, identity=Depends(integrations.current_identity),
             db: Session = Depends(get_db)):
    if integrations.dependency_mode() != "demo":
        raise HTTPException(404, "此接口不可用")
    order = owned_order(db, order_id, identity)
    if order.pricing_source != "demo":
        raise HTTPException(409, "正式订单不允许演示支付")
    event = PaymentEvent(eventId=f"demo-event-{order.id}", paymentId=f"demo-pay-{order.id}",
                         orderId=order.id, uid=identity.uid, amountCents=order.amount_cents)
    accept_payment(event, db)
    db.expire_all()
    return view(db.get(Order, order_id))
