"""F4：数据库筛选与 C 状态事件投影。大厅不返回取件码。"""
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...database import get_db
from . import integrations
from .models import Order, OrderStatusReceipt
from .router import accept_payment, fingerprint, view
from .schemas import DemoStatusChange, OrderStatusEvent, PaymentEvent

router = APIRouter(prefix="/api/orders", tags=["task-hall"])


def candidate_conditions(identity):
    return [Order.status == "pending", Order.paid_payment_id.is_not(None),
            Order.publisher_uid != identity.uid,
            Order.pricing_source == integrations.dependency_mode()]


def public_view(order):
    data = view(order)
    # 取件码只在发布者详情或今后 C 授权的履约接口出现。
    del data["code"]
    del data["publisherUid"]
    return data


def utc_filter(value):
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(422, "送达时间筛选必须带时区")
    return value.astimezone(timezone.utc)


@router.get("")
def list_tasks(
    status: Literal["pending"] = "pending",
    station: str = Query(default="", max_length=60),
    address: str = Query(default="", max_length=200),
    tipMinCents: int | None = Query(default=None, ge=0, le=99900),
    tipMaxCents: int | None = Query(default=None, ge=0, le=99900),
    expectedFrom: datetime | None = None, expectedTo: datetime | None = None,
    page: int = Query(default=1, ge=1, le=100000),
    pageSize: int = Query(default=12, ge=1, le=60),
    identity=Depends(integrations.current_identity), db: Session = Depends(get_db),
):
    start, end = utc_filter(expectedFrom), utc_filter(expectedTo)
    if tipMinCents is not None and tipMaxCents is not None and tipMinCents > tipMaxCents:
        raise HTTPException(422, "小费下限不能大于上限")
    if start and end and start > end:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    base = candidate_conditions(identity)
    conditions = list(base)
    if station.strip():
        conditions.append(Order.station == station.strip())
    if address.strip():
        full_address = Order.address + " " + Order.legacy_room
        conditions.append(full_address.contains(address.strip(), autoescape=True))
    if tipMinCents is not None:
        conditions.append(Order.tip_cents >= tipMinCents)
    if tipMaxCents is not None:
        conditions.append(Order.tip_cents <= tipMaxCents)
    if start:
        conditions.append(Order.expected_at >= start)
    if end:
        conditions.append(Order.expected_at <= end)
    total = db.scalar(select(func.count()).select_from(Order).where(*conditions))
    orders = db.scalars(select(Order).where(*conditions)
                        .order_by(Order.expected_at.asc(), Order.created_at.desc(), Order.id.asc())
                        .offset((page - 1) * pageSize).limit(pageSize)).all()
    stations = db.scalars(select(Order.station).where(*base).distinct().order_by(Order.station)).all()
    return {"items": [public_view(order) for order in orders], "total": total,
            "page": page, "pageSize": pageSize, "stations": stations,
            "mode": integrations.dependency_mode(), "refreshAfterSeconds": 10}


def hall_order(db, order_id, identity):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "任务不存在")
    if order.publisher_uid == identity.uid:
        raise HTTPException(403, "自己的需求请在发布页面查看")
    if order.pricing_source != integrations.dependency_mode():
        raise HTTPException(404, "任务不存在")
    if order.status != "pending" or not order.paid_payment_id:
        raise HTTPException(409, "任务已被接单或取消，请查看其他任务")
    return order


@router.get("/hall/{order_id}")
def task_detail(order_id: str, identity=Depends(integrations.current_identity),
                db: Session = Depends(get_db)):
    return public_view(hall_order(db, order_id, identity))


def accept_status(event: OrderStatusEvent, db: Session):
    digest = fingerprint(event.model_dump())
    receipt = db.get(OrderStatusReceipt, event.eventId)
    if receipt:
        if receipt.payload_hash != digest:
            raise HTTPException(409, "状态事件标识与原内容不一致")
        return {"accepted": True, "duplicate": True, "ignored": False}
    same_version = db.scalar(select(OrderStatusReceipt).where(
        OrderStatusReceipt.order_id == event.orderId, OrderStatusReceipt.version == event.version))
    if same_version:
        raise HTTPException(409, "订单状态版本已被其他事件使用")
    order = db.get(Order, event.orderId)
    if not order:
        raise HTTPException(404, "事件对应订单不存在")
    if not order.paid_payment_id or order.status == "awaiting_payment":
        raise HTTPException(409, "未支付订单不能进入履约状态")
    latest = db.scalar(select(func.max(OrderStatusReceipt.version)).where(
        OrderStatusReceipt.order_id == event.orderId)) or 0
    ignored = event.version < latest
    if not ignored and order.status in {"cancelled", "delivered"} and order.status != event.status:
        raise HTTPException(409, "已结束订单不能再次改变履约状态")
    try:
        if not ignored:
            no_newer_event = ~select(OrderStatusReceipt.event_id).where(
                OrderStatusReceipt.order_id == event.orderId,
                OrderStatusReceipt.version >= event.version).exists()
            changed = db.execute(update(Order).where(Order.id == event.orderId, Order.status == order.status, no_newer_event)
                                 .values(status=event.status))
            if changed.rowcount != 1:
                db.rollback()
                raise HTTPException(409, "状态已变化，请重新投递事件")
        db.add(OrderStatusReceipt(event_id=event.eventId, order_id=event.orderId,
                                  version=event.version, status=event.status, payload_hash=digest))
        db.commit()
    except IntegrityError:
        db.rollback()
        receipt = db.get(OrderStatusReceipt, event.eventId)
        if receipt and receipt.payload_hash == digest:
            return {"accepted": True, "duplicate": True, "ignored": False}
        raise HTTPException(409, "状态事件重复或冲突")
    return {"accepted": True, "duplicate": False, "ignored": ignored}


@router.post("/events/status-changed")
def status_event(body: OrderStatusEvent, x_order_status_secret: str = Header(default=""),
                  db: Session = Depends(get_db)):
    secret = os.getenv("F4_STATUS_EVENT_SECRET", "")
    if integrations.dependency_mode() != "external" or not secret or not hmac.compare_digest(secret, x_order_status_secret):
        raise HTTPException(403, "无效的状态事件凭证")
    order = db.get(Order, body.orderId)
    if order and order.pricing_source != "external":
        raise HTTPException(409, "演示订单不接受正式履约事件")
    return accept_status(body, db)


@router.post("/demo/seed-hall")
def seed_demo_tasks(identity=Depends(integrations.current_identity), db: Session = Depends(get_db)):
    if integrations.dependency_mode() != "demo":
        raise HTTPException(404, "此接口不可用")
    now = datetime.now(timezone.utc)
    batch = now.strftime("%Y%m%d")
    # 每日幂等添加，不会将已被模拟接单/取消的任务重新开放。
    samples = [("中通快递", "菜鸟驿站", "实验楼 A 座 302 室", "小件", 300, 2),
               ("顺丰速运", "顺丰服务点", "图书馆正门", "中件", 500, 4),
               ("圆通速递", "菜鸟驿站", "第一饭堂门口", "小件", 250, 6)]
    count = 0
    for index, (company, station, address, size, tip, hours) in enumerate(samples):
        key = f"hall-demo-{batch}-{index}"
        order = db.scalar(select(Order).where(Order.publisher_uid == "demo-hall-publisher", Order.request_key == key))
        if order:
            continue
        base = 200 if size == "小件" else 300
        order = Order(id=str(uuid4()), publisher_uid="demo-hall-publisher", request_key=key,
                      request_hash=fingerprint({"seed": key}), company=company, pickup_code="演示取件码",
                      station=station, size=size, weight_kg="1", address=address,
                      expected_at=now + timedelta(hours=hours), note="演示任务，请勿前往实际取件。",
                      base_fee_cents=base, tip_cents=tip, amount_cents=base + tip, pricing_source="demo")
        db.add(order)
        try:
            db.flush()
            accept_payment(PaymentEvent(eventId=f"seed-event-{order.id}", paymentId=f"seed-pay-{order.id}",
                                        orderId=order.id, uid=order.publisher_uid, amountCents=order.amount_cents), db)
            count += 1
        except IntegrityError:
            db.rollback()
    return {"created": count}


@router.post("/demo/hall/{order_id}/status")
def demo_change_status(order_id: str, body: DemoStatusChange,
                       identity=Depends(integrations.current_identity), db: Session = Depends(get_db)):
    if integrations.dependency_mode() != "demo":
        raise HTTPException(404, "此接口不可用")
    hall_order(db, order_id, identity)
    event = OrderStatusEvent(eventId=str(uuid4()), orderId=order_id, version=1, status=body.status)
    return accept_status(event, db)
