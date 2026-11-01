"""完结结算共享消费者事务，不直接修改订单，不二次扣可用余额。"""

from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..core.event_acl import SettleCommand
from ....common import fail
from ...orders.gateway import OrderGateway
from ..models import Payment, Settlement
from ..core.wallet_core import settle_payment
from ..core.fee_util import split_settlement


def settle_order(db: Session, command: SettleCommand) -> dict:
    order = OrderGateway.get_snapshot(db, command.order_id)
    if (
        order.status != "delivered"
        or order.payment_status != "paid"
        or order.refund_status != "none"
        or not order.courier_uid
        or order.publisher_uid == order.courier_uid
        or (
            command.publisher_uid,
            command.courier_uid,
            command.amount_cent,
            command.base_fee_cent,
            command.commission_rate_bps,
        )
        != (
            order.publisher_uid,
            order.courier_uid,
            order.amount,
            order.base_fee,
            order.commission_bps,
        )
    ):
        fail(409, "ORDER_CONFLICT", "完结事件与订单状态或金额快照不一致")
    payment = db.get(Payment, order.payment_id) if order.payment_id else None
    if (
        payment is None
        or payment.order_id != order.id
        or payment.payer_uid != order.publisher_uid
        or payment.amount != order.amount
        or payment.status != "succeeded"
    ):
        fail(409, "ORDER_CONFLICT", "订单缺少匹配的成功支付事实")
    existing = db.scalar(select(Settlement).where(Settlement.order_id == order.id))
    if existing:
        if (
            existing.payment_id,
            existing.courier_uid,
            existing.amount,
            existing.base_fee,
            existing.commission_bps,
            existing.pricing_version,
        ) != (
            payment.id,
            order.courier_uid,
            order.amount,
            order.base_fee,
            order.commission_bps,
            order.pricing_version,
        ):
            fail(409, "ORDER_CONFLICT", "原结算事实与请求冲突")
        return result(existing)
    income, commission = split_settlement(order.amount, order.base_fee, order.commission_bps)
    settlement_id = str(uuid4())
    settle_payment(db, payment, order.courier_uid, income, settlement_id)
    row = Settlement(
        id=settlement_id,
        order_id=order.id,
        payment_id=payment.id,
        publisher_uid=order.publisher_uid,
        courier_uid=order.courier_uid,
        amount=order.amount,
        base_fee=order.base_fee,
        commission_bps=order.commission_bps,
        income=income,
        commission=commission,
        pricing_version=order.pricing_version,
    )
    db.add(row)
    db.flush()
    return result(row)


def result(row: Settlement) -> dict:
    return {
        "settlementId": row.id,
        "orderId": row.order_id,
        "income": row.income,
        "commission": row.commission,
        "status": "succeeded",
    }
