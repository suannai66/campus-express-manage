"""顶层支付用例：只读订单快照，持久化支付事实及待投递事件，不改订单状态。"""
from uuid import uuid4
from sqlalchemy import select
from ....common import fail, iso, now, remember, replay
from ...orders.gateway import OrderGateway
from ..models import Payment
from ..core import wallet_core
from .transaction import wallet_transaction


def result(row):
    return {"paymentId": row.id, "orderId": row.order_id, "amount": row.amount,
            "status": row.status, "code": row.code}


def prepay(db, uid, request, key):
    body = request.model_dump()
    with wallet_transaction(db):
        cached = replay(db, uid, "payment-prepay", key, body)
        if cached is not None:
            return cached
        order = OrderGateway.get_snapshot(db, request.orderId)
        if order.publisher_uid != uid:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        existing = db.scalar(select(Payment).where(Payment.request_id == request.paymentRequestId))
        if existing:
            if existing.order_id != order.id or existing.payer_uid != uid:
                fail(409, "ORDER_CONFLICT", "支付预占与订单不一致")
            response = result(existing)
            remember(db, uid, "payment-prepay", key, body, response)
            return response
        if (order.status != "pending_payment" or order.payment_status != "paying"
                or order.payment_request_id != request.paymentRequestId or order.payer_uid != uid):
            fail(409, "ORDER_CONFLICT", "订单没有有效的支付预占")
        if db.scalar(select(Payment.id).where(Payment.order_id == order.id, Payment.status == "succeeded")):
            fail(409, "ORDER_CONFLICT", "订单已支付")
        if type(order.amount) is not int or order.amount <= 0:
            fail(409, "ORDER_CONFLICT", "订单金额无效")
        payment_id = str(uuid4())
        try:
            wallet_core.freeze(db, uid, order.amount, payment_id)
            status, code = "succeeded", None
        except wallet_core.InsufficientBalanceError:
            status, code = "failed", "INSUFFICIENT_BALANCE"
        event = {
            "eventId": str(uuid4()), "type": "payment." + status,
            "occurredAt": iso(now()), "orderId": order.id,
            "aggregateType": "payment", "aggregateId": payment_id, "version": 1,
            "payload": {"paymentId": payment_id, "paymentRequestId": request.paymentRequestId,
                        "payerUid": uid, "amount": order.amount, "code": code},
        }
        row = Payment(id=payment_id, order_id=order.id, request_id=request.paymentRequestId,
                      payer_uid=uid, amount=order.amount, status=status, code=code,
                      funds_status="frozen" if status == "succeeded" else "none", event=event)
        db.add(row)
        response = result(row)
        remember(db, uid, "payment-prepay", key, body, response)
        db.flush()
        return response


def query_payment(db, uid, payment_id):
    row = db.get(Payment, payment_id)
    if row is None or row.payer_uid != uid:
        fail(404, "NOT_FOUND", "支付记录不存在")
    return result(row)
