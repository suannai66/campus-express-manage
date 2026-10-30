from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...common import Key, VersionInput, fail, iso, now, remember, replay
from . import integrations
from ...database import get_db

from .integrations import current_identity as current, require_verified
from .contract import AREAS, STATIONS, OrderDraft
from .entities import Order
from .gateway import OrderGateway

router = APIRouter(prefix="/api/orders", tags=["orders"])
STATUSES = {"pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "cancelled"}


def validate_delivery_time(body):
    if not now() < body.expectedAt <= now() + timedelta(days=7):
        fail(422, "VALIDATION_ERROR", "请选择未来七天内的送达时间", {"expectedAt": "请选择未来七天内的送达时间"})


def summary(order):
    return {"orderId": order.id, "company": order.company, "stationId": order.station_id,
            "stationName": STATIONS[order.station_id], "deliveryAreaId": order.area_id,
            "deliveryAreaName": AREAS[order.area_id], "size": order.size, "weight": order.weight,
            "expectedAt": order.expected_at, "note": order.note, "baseFee": order.base_fee,
            "tip": order.tip, "amount": order.amount, "status": order.status,
            "paymentStatus": order.payment_status, "refundStatus": order.refund_status,
            "version": order.version, "createdAt": order.created_at, "demo": order.demo}


def detail_view(order, uid):
    result = {**summary(order), "publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
              "locked": order.locked, "pickupFailureCount": order.pickup_failures,
              "address": order.address, "code": order.code}
    if uid == order.publisher_uid:
        result["paymentRequestId"] = order.payment_request_id
    return result


@router.get("/locations")
def locations():
    return {"stations": [{"id": key, "name": value} for key, value in STATIONS.items()],
            "deliveryAreas": [{"id": key, "name": value} for key, value in AREAS.items()]}


@router.post("/quote")
def quote(body: OrderDraft, request: Request, user=Depends(current), db: Session = Depends(get_db)):
    require_verified(user)
    validate_delivery_time(body)
    return integrations.quote(body, request)


@router.post("", status_code=201)
def create(body: OrderDraft, request: Request, idempotency_key: Key, user=Depends(current), db: Session = Depends(get_db)):
    require_verified(user)
    payload = body.model_dump(mode="json")
    result = replay(db, user.uid, "create-order", idempotency_key, payload)
    if result:
        return result
    validate_delivery_time(body)
    fees = integrations.quote(body, request)
    order = Order(id=str(uuid4()), publisher_uid=user.uid, company=body.company, code=body.code,
                  station_id=body.stationId, area_id=body.deliveryAreaId, address=body.address,
                  size=body.size, weight=body.weight, expected_at=iso(body.expectedAt), note=body.note,
                  base_fee=fees["baseFee"], tip=fees["tip"], amount=fees["amount"],
                  commission_bps=fees["commissionRateBps"], pricing_version=fees["pricingVersion"],
                  created_at=iso(now()), demo=fees["demo"])
    db.add(order)
    db.flush()
    result = detail_view(order, user.uid)
    remember(db, user.uid, "create-order", idempotency_key, payload, result)
    db.commit()
    return result


def query_time(value, field):
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone")
        return iso(result.astimezone(timezone.utc))
    except ValueError:
        fail(422, "VALIDATION_ERROR", "时间必须是带时区的 ISO 8601 格式", {field: "时间格式不正确"})


@router.get("")
def orders(request: Request, scope: Literal["hall", "mine"] = "hall", status: str | None = None,
           stationId: str | None = None, deliveryAreaId: str | None = None,
           tipMin: int | None = Query(None, ge=0, le=99900), tipMax: int | None = Query(None, ge=0, le=99900),
           expectedFrom: str | None = None, expectedTo: str | None = None,
           role: Literal["publisher", "courier", "all"] = "all", page: int = Query(1, ge=1),
           pageSize: int = Query(20, ge=1, le=100), user=Depends(current), db: Session = Depends(get_db)):
    allowed = {"scope", "status", "stationId", "deliveryAreaId", "tipMin", "tipMax", "expectedFrom", "expectedTo", "role", "page", "pageSize"}
    if set(request.query_params) - allowed:
        fail(422, "VALIDATION_ERROR", "查询包含未声明字段")
    for name in ("tipMin", "tipMax", "page", "pageSize"):
        raw = request.query_params.get(name)
        if raw is not None and (not raw.isascii() or not raw.isdigit()):
            fail(422, "VALIDATION_ERROR", "金额和分页参数必须为整数", {name: "请输入非负整数"})
    if status is not None and (status not in STATUSES or (scope == "hall" and status != "pending")):
        fail(422, "VALIDATION_ERROR", "订单状态筛选值不正确", {"status": "大厅仅允许 pending"})
    if stationId is not None and stationId not in STATIONS or deliveryAreaId is not None and deliveryAreaId not in AREAS:
        fail(422, "VALIDATION_ERROR", "请从地点目录选择取件点和送达区域")
    start, end = query_time(expectedFrom, "expectedFrom"), query_time(expectedTo, "expectedTo")
    if (tipMin is not None and tipMax is not None and tipMin > tipMax) or (start and end and start > end):
        fail(422, "VALIDATION_ERROR", "筛选下限不能大于上限")
    conditions = []
    if scope == "hall":
        conditions += [Order.status == "pending", Order.payment_status == "paid", Order.publisher_uid != user.uid]
    else:
        if role == "publisher":
            conditions.append(Order.publisher_uid == user.uid)
        elif role == "courier":
            conditions.append(Order.courier_uid == user.uid)
        else:
            conditions.append(or_(Order.publisher_uid == user.uid, Order.courier_uid == user.uid))
        if status:
            conditions.append(Order.status == status)
    for column, value in [(Order.station_id, stationId), (Order.area_id, deliveryAreaId)]:
        if value is not None:
            conditions.append(column == value)
    for column, value, lower in [(Order.tip, tipMin, True), (Order.tip, tipMax, False),
                                  (Order.expected_at, start, True), (Order.expected_at, end, False)]:
        if value is not None:
            conditions.append(column >= value if lower else column <= value)
    total = db.scalar(select(func.count()).select_from(Order).where(*conditions))
    sort = [Order.expected_at.asc(), Order.created_at.desc(), Order.id.asc()] if scope == "hall" else [Order.created_at.desc(), Order.id.asc()]
    rows = db.scalars(select(Order).where(*conditions).order_by(*sort).offset((page - 1) * pageSize).limit(pageSize))
    return {"items": [summary(order) for order in rows], "total": total, "page": page, "pageSize": pageSize}


@router.get("/{order_id}")
def detail(order_id: str, user=Depends(current), db: Session = Depends(get_db)):
    return detail_view(OrderGateway.related(db, order_id, user.uid), user.uid)


@router.post("/{order_id}/payment-request")
def payment_request(order_id: str, body: VersionInput, idempotency_key: Key,
                    user=Depends(current), db: Session = Depends(get_db)):
    operation = f"payment-request:{order_id}"
    result = replay(db, user.uid, operation, idempotency_key, body.model_dump())
    if result:
        return result
    order = OrderGateway.related(db, order_id, user.uid)
    if order.publisher_uid != user.uid:
        fail(404, "NOT_FOUND", "订单不存在")
    if order.version != body.version:
        fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新")
    if order.status != "pending_payment" or order.payment_status == "paid":
        fail(409, "ORDER_CONFLICT", "订单不允许支付")
    if order.payment_status == "unpaid":
        order = OrderGateway.transition(db, order, body.version, "reserve", user.uid,
                                payment_status="paying", payment_request_id=str(uuid4()), payer_uid=user.uid)
    result = {"orderId": order.id, "paymentRequestId": order.payment_request_id, "amount": order.amount,
              "paymentStatus": order.payment_status, "version": order.version}
    remember(db, user.uid, operation, idempotency_key, body.model_dump(), result)
    db.commit()
    return result
