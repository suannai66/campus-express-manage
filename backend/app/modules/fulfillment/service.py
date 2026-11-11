"""履约用例：状态、日志、请求幂等与 outbox 使用同一事务。"""
from uuid import uuid4
from sqlalchemy import select

from ...common import Idempotency, fail, fingerprint, iso, now, remember
from ...events import publish
from ..identity.dependencies import require_verified
from ..orders.api import summary
from ..orders.gateway import OrderGateway
from .credit import CreditService
from .models import OperationLog


def emit(db, order, kind, payload):
    publish(db, {"eventId": str(uuid4()), "type": kind, "occurredAt": iso(now()),
                 "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                 "version": order.version, "payload": {**payload, "orderVersion": order.version}})


def record(db, before, after, uid, action, reason=None):
    db.add(OperationLog(id=str(uuid4()), order_id=after.id, actor_uid=uid, action=action,
                        from_status=before.status, status=after.status, order_version=after.version,
                        reason=reason, created_at=iso(now())))
    emit(db, after, "order.status_changed", {"fromStatus": before.status, "status": after.status,
                                             "courierUid": after.courier_uid})


def fulfillment_detail(order, uid):
    """履约动作无需取件码，也不向 C 页面返回该字段。"""
    result = {**summary(order), "publisherUid": order.publisher_uid,
              "courierUid": order.courier_uid, "address": order.address}
    if uid == order.publisher_uid:
        result["paymentRequestId"] = order.payment_request_id
    return result


def replay_fulfillment(db, uid, operation, key, payload):
    """只兼容旧版缺省 code:null 的摘要；不改写旧回执或重做业务。"""
    row = db.scalar(select(Idempotency).where(Idempotency.uid == uid,
                    Idempotency.operation == operation, Idempotency.key == key))
    if row is None:
        return None
    digests = {fingerprint(payload)}
    if payload.get("action") in {"start_pickup", "confirm_pickup", "confirm_delivery"}:
        digests.add(fingerprint({**payload, "code": None}))
    if row.digest not in digests:
        fail(409, "IDEMPOTENCY_CONFLICT", "相同提交标识不能用于不同内容")
    result = row.result
    if result["statusCode"] == 200:
        # 历史成功快照仍可重放，但 C 响应不再暴露取件码及旧锁定字段。
        result = {**result, "body": {name: value for name, value in result["body"].items()
                  if name not in {"code", "locked", "pickupFailureCount"}}}
    return result


def execute(db, user, order_id, operation, body, key):
    name = f"fulfillment:{operation}:{order_id}"
    payload = body.model_dump()
    receipt = operation == "status" and body.action == "confirm_receipt"
    if operation != "cancel" and not receipt:
        require_verified(user)
    previous = replay_fulfillment(db, user.uid, name, key, payload)
    if previous:
        return previous
    before = OrderGateway.get_snapshot(db, order_id)
    if operation == "accept":
        if user.uid == before.publisher_uid:
            fail(403, "FORBIDDEN", "不能接取自己发布的订单")
        if not CreditService.get(db, user.uid)["creditEligible"]:
            fail(403, "CREDIT_TOO_LOW", "信用分低于 3.0，暂时不能接单")
    elif operation == "cancel":
        if user.uid != before.publisher_uid:
            fail(403, "FORBIDDEN", "仅发布者可取消订单")
    elif receipt:
        if user.uid != before.publisher_uid:
            fail(403, "FORBIDDEN", "仅发布者可确认收货")
    elif user.uid != before.courier_uid:
        fail(403, "FORBIDDEN", "仅本单取件员可推进履约")
    if before.version != body.version:
        fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新后重试")
    status_code = 200
    if operation == "accept":
        after = OrderGateway.transition(db, before, body.version, "accept", user.uid,
                                        status="accepted", courier_uid=user.uid)
        record(db, before, after, user.uid, "accept")
        result = fulfillment_detail(after, user.uid)
    elif operation == "cancel":
        after = OrderGateway.transition(db, before, body.version, "cancel", user.uid,
                                        status="cancelled", refund_status="processing" if before.payment_status == "paid" else "none")
        record(db, before, after, user.uid, "cancel", body.reason)
        emit(db, after, "order.cancelled", {"publisherUid": after.publisher_uid, "paymentId": after.payment_id,
                                            "amount": after.amount, "paid": after.payment_status == "paid"})
        result = {"orderId": after.id, "status": after.status, "refundStatus": after.refund_status, "version": after.version}
    else:
        source, target = {"start_pickup": ("accepted", "picking_up"),
                          "confirm_pickup": ("picking_up", "delivering"),
                          "confirm_delivery": ("delivering", "delivered"),
                          "confirm_receipt": ("delivered", "completed")}[body.action]
        if before.status != source:
            fail(409, "ORDER_CONFLICT", "请按取件、配送、送达、确认收货的顺序操作")
        after = OrderGateway.transition(db, before, body.version, "confirm_receipt" if receipt else "fulfill",
                                       user.uid, status=target)
        record(db, before, after, user.uid, body.action)
        if target == "completed":
            emit(db, after, "order.completed", {"publisherUid": after.publisher_uid, "courierUid": after.courier_uid,
                "amount": after.amount, "baseFee": after.base_fee, "tip": after.tip,
                "commissionRateBps": after.commission_bps, "pricingVersion": after.pricing_version})
        result = fulfillment_detail(after, user.uid)
    stored = {"statusCode": status_code, "body": result}
    remember(db, user.uid, name, key, payload, stored)
    db.commit()
    return stored
