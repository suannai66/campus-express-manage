"""完结事件消费者：只开放评价，不写订单和资金，不提交调用方事务。"""
from ...common import fail, fingerprint
from ...events.schema import validate
from ..orders.gateway import OrderGateway
from .models import ConsumerReceipt, ReviewOpening


def on_order_completed(db, event):
    data, digest = validate(event)
    if data["type"] != "order.completed":
        fail(422, "VALIDATION_ERROR", "评价仅订阅订单完结事件")
    receipt = db.get(ConsumerReceipt, data["eventId"])
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    order = OrderGateway.get_snapshot(db, data["orderId"])
    expected = {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
                "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
                "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
                "orderVersion": order.version}
    if order.status != "completed" or data["version"] != order.version or data["payload"] != expected:
        fail(409, "ORDER_CONFLICT", "完结事件与订单事实不一致")
    fact_digest = fingerprint(expected)
    opening = db.get(ReviewOpening, order.id)
    if opening and opening.fact_digest != fact_digest:
        fail(409, "ORDER_CONFLICT", "订单完结事实发生冲突")
    if not opening:
        db.add(ReviewOpening(order_id=order.id, fact_digest=fact_digest, created_at=data["occurredAt"]))
    result = {"accepted": True, "orderId": order.id, "reviewable": True}
    db.add(ConsumerReceipt(event_id=data["eventId"], digest=digest, result=result))
    db.flush()
    return result
