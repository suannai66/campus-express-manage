"""履约用例：状态、日志、通知、请求幂等与 outbox 使用同一事务。"""
import hmac
from uuid import uuid4

from ...common import fail, iso, now, remember, replay
from ...events import publish
from ..identity.dependencies import require_verified
from ..orders.api import detail_view
from ..orders.gateway import OrderGateway
from .credit import CreditService
from .models import Notification, OperationLog


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


def execute(db, user, order_id, operation, body, key):
    name = f"fulfillment:{operation}:{order_id}"
    payload = body.model_dump()
    if operation != "cancel":
        require_verified(user)
    previous = replay(db, user.uid, name, key, payload)
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
    elif user.uid != before.courier_uid:
        fail(403, "FORBIDDEN", "仅本单取件员可推进履约")
    if before.version != body.version:
        fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新后重试")
    if before.locked:
        fail(409, "ORDER_LOCKED", "订单已锁定，请联系维护者处理")
    status_code = 200
    if operation == "accept":
        after = OrderGateway.transition(db, before, body.version, "accept", user.uid,
                                        status="accepted", courier_uid=user.uid)
        record(db, before, after, user.uid, "accept")
        result = detail_view(after, user.uid)
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
                          "confirm_delivery": ("delivering", "delivered")}[body.action]
        if before.status != source:
            fail(409, "ORDER_CONFLICT", "请按取件、配送、送达的顺序操作")
        wrong_code = body.action == "confirm_pickup" and not hmac.compare_digest(body.code.encode(), before.code.encode())
        if wrong_code:
            failures = before.pickup_failures + 1
            locked = failures >= 3
            after = OrderGateway.transition(db, before, body.version, "fulfill", user.uid,
                pickup_failures=failures, locked=locked, lock_reason="取件码连续错误三次" if locked else None)
            record(db, before, after, user.uid, "pickup_code_mismatch")
            if locked:
                for uid in {after.publisher_uid, after.courier_uid}:
                    db.add(Notification(id=str(uuid4()), order_id=after.id, uid=uid, type="pickup_locked",
                        message="取件码连续错误三次，订单已锁定，请联系维护者处理。", created_at=iso(now())))
            status_code = 409 if locked else 422
            result = {"detail": "取件码连续错误三次，订单已锁定" if locked else "取件码不正确，请核对后重试",
                      "code": "ORDER_LOCKED" if locked else "PICKUP_CODE_MISMATCH",
                      "fields": {"pickupFailureCount": failures, "version": after.version, "locked": locked}}
        else:
            changes = {"status": target}
            if body.action == "confirm_pickup":
                changes["pickup_failures"] = 0
            after = OrderGateway.transition(db, before, body.version, "fulfill", user.uid, **changes)
            record(db, before, after, user.uid, body.action)
            if target == "delivered":
                emit(db, after, "order.completed", {"publisherUid": after.publisher_uid, "courierUid": after.courier_uid,
                    "amount": after.amount, "baseFee": after.base_fee, "tip": after.tip,
                    "commissionRateBps": after.commission_bps, "pricingVersion": after.pricing_version})
            result = detail_view(after, user.uid)
    stored = {"statusCode": status_code, "body": result}
    remember(db, user.uid, name, key, payload, stored)
    db.commit()
    return stored
