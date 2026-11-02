"""取消退款编排；不得自行提交，失败由投递方回滚整个消费事务。"""

from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..core.event_acl import RefundCommand
from ....common import fail, iso, now
from ....events import publish
from ...orders.gateway import OrderGateway, OrderSnapshot
from ..models import Payment, Refund
from ..core.wallet_core import release_payment


def refund_order(db: Session, command: RefundCommand) -> dict:
    order = OrderGateway.get_snapshot(db, command.order_id)
    if (
        order.status != "cancelled"
        or order.publisher_uid != command.publisher_uid
        or order.amount != command.amount_cent
    ):
        fail(409, "ORDER_CONFLICT", "取消事件与订单事实不一致")
    if command.payment_id is None:
        _validate_unpaid_cancellation(db, order)
        return {"orderId": order.id, "refunded": False}
    payment = db.get(Payment, command.payment_id)
    _validate_refund_payment(order, payment, command)
    existing = db.scalar(select(Refund).where(Refund.order_id == order.id))
    if existing:
        if (existing.payment_id, existing.payer_uid, existing.amount) != (
            payment.id,
            payment.payer_uid,
            payment.amount,
        ):
            fail(409, "ORDER_CONFLICT", "原退款事实与请求冲突")
        return {"orderId": order.id, "refundId": existing.id, "refunded": True}
    if order.refund_status != "processing":
        fail(409, "ORDER_CONFLICT", "订单没有待处理退款")
    refund_id = str(uuid4())
    release_payment(db, payment, refund_id)
    event = {
        "eventId": str(uuid4()),
        "type": "refund.succeeded",
        "occurredAt": iso(now()),
        "orderId": order.id,
        "aggregateType": "refund",
        "aggregateId": refund_id,
        "version": 1,
        "payload": {
            "refundId": refund_id,
            "paymentId": payment.id,
            "payerUid": payment.payer_uid,
            "amount": payment.amount,
        },
    }
    db.add(
        Refund(
            id=refund_id,
            order_id=order.id,
            payment_id=payment.id,
            payer_uid=payment.payer_uid,
            amount=payment.amount,
            event=event,
            event_status="outbox_saved",
        )
    )
    publish(db, event)
    db.flush()
    return {"orderId": order.id, "refundId": refund_id, "refunded": True}


def _validate_unpaid_cancellation(db: Session, order: OrderSnapshot) -> None:
    """未支付取消必须同时匹配订单状态与实际支付记录。"""
    paid = db.scalar(
        select(Payment.id).where(Payment.order_id == order.id, Payment.status == "succeeded")
    )
    if order.payment_status != "unpaid" or order.payment_id is not None or paid:
        fail(409, "ORDER_CONFLICT", "未支付取消与支付事实冲突")


def _validate_refund_payment(
    order: OrderSnapshot, payment: Payment | None, command: RefundCommand
) -> None:
    """核对退款所依据的订单和成功支付事实。"""
    if (
        payment is None
        or payment.order_id != order.id
        or payment.payer_uid != command.publisher_uid
        or payment.amount != command.amount_cent
        or payment.status != "succeeded"
        or order.payment_status != "paid"
        or order.payment_id != payment.id
        or order.refund_status not in {"processing", "succeeded"}
    ):
        fail(409, "ORDER_CONFLICT", "退款事件与支付事实不一致")
