"""大厅直接查询订单主表；状态事件校准到最新快照并持久化刷新回执。"""
from sqlalchemy import select
from ...common import fail, fingerprint
from ...events.schema import validate
from .gateway import OrderGateway
from .handlers import EventReceipt


def handle(db, event):
    data, _ = validate(event)
    if data["type"] not in {"order.status_changed", "order.cancelled"}:
        fail(422, "VALIDATION_ERROR", "不支持的大厅刷新事件")
    digest = fingerprint(event)
    receipt = db.scalar(select(EventReceipt).where(EventReceipt.consumer == "orders",
        EventReceipt.event_id == data["eventId"]))
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    order = OrderGateway.get_snapshot(db, data["orderId"])
    if data["version"] > order.version:
        fail(409, "ORDER_CONFLICT", "事件版本超前于订单事实")
    body = data["payload"]
    if data["type"] == "order.cancelled":
        if (order.status != "cancelled" or body["publisherUid"] != order.publisher_uid
                or body["amount"] != order.amount or body["paymentId"] != order.payment_id
                or body["paid"] != (order.payment_status == "paid")):
            fail(409, "ORDER_CONFLICT", "取消事件与订单事实不一致")
    elif data["version"] == order.version and (body["status"], body["courierUid"]) != (order.status, order.courier_uid):
        fail(409, "ORDER_CONFLICT", "状态事件与当前订单快照不一致")
    result = {"accepted": True, "orderId": order.id, "version": order.version, "status": order.status}
    db.add(EventReceipt(id=f"orders:{data['eventId']}", consumer="orders",
        event_id=data["eventId"], digest=digest, result=result))
    db.flush()
    return result
