"""B 的事务内消费者，交由 A 的持久化事件投递器调用；不开放匿名 HTTP。"""
from typing import Literal
from datetime import datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy import JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from ...common import Input, fail, fingerprint
from ...database import Base
from .gateway import OrderGateway


class EventReceipt(Base):
    __tablename__ = "order_event_receipts_v2"
    __table_args__ = (UniqueConstraint("consumer", "event_id"),)
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(100))
    consumer: Mapped[str] = mapped_column(String(30))
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class PaymentPayload(Input):
    paymentId: str = Field(min_length=1, max_length=100)
    paymentRequestId: str = Field(min_length=1, max_length=100)
    payerUid: str = Field(min_length=1, max_length=100)
    amount: int = Field(strict=True, gt=0)
    code: str | None = None


class PaymentFact(Base):
    """订单侧支付事实索引，不代替 D 的支付表或资金账。"""
    __tablename__ = "order_payment_facts_v2"
    request_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(100), unique=True)
    order_id: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(30))
    digest: Mapped[str] = mapped_column(String(64))


class Envelope(Input):
    eventId: UUID
    type: Literal["payment.succeeded", "payment.failed", "refund.succeeded"]
    occurredAt: datetime
    orderId: str = Field(min_length=1, max_length=100)
    aggregateType: Literal["payment", "refund"]
    aggregateId: str = Field(min_length=1, max_length=100)
    version: int = Field(strict=True, gt=0)
    payload: dict


class RefundPayload(Input):
    refundId: str = Field(min_length=1, max_length=100)
    paymentId: str = Field(min_length=1, max_length=100)
    payerUid: str = Field(min_length=1, max_length=100)
    amount: int = Field(strict=True, gt=0)


def handle(db, event):
    """调用方与回执共用事务并统一提交；资金版本不与订单版本比较。"""
    from .api import query_time
    envelope = Envelope.model_validate(event)
    if envelope.occurredAt.tzinfo is None:
        fail(422, "VALIDATION_ERROR", "事件时间必须带时区")
    query_time(event["occurredAt"], "occurredAt")
    consumer = "orders"
    digest = fingerprint(event)
    receipt = db.scalar(select(EventReceipt).where(EventReceipt.consumer == consumer,
                                                   EventReceipt.event_id == event["eventId"]))
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    if event["type"] not in {"payment.succeeded", "payment.failed", "refund.succeeded"}:
        fail(422, "VALIDATION_ERROR", "不支持的订单资金事件")
    body = (RefundPayload if event["type"] == "refund.succeeded" else PaymentPayload).model_validate(event["payload"])
    aggregate_type = "refund" if event["type"] == "refund.succeeded" else "payment"
    aggregate_id = body.refundId if aggregate_type == "refund" else body.paymentId
    if envelope.aggregateType != aggregate_type or envelope.aggregateId != aggregate_id:
        fail(422, "VALIDATION_ERROR", "事件聚合标识与事实不一致")
    order = OrderGateway.get_snapshot(db, event["orderId"])
    if body.payerUid != order.publisher_uid or body.amount != order.amount:
        fail(409, "ORDER_CONFLICT", "资金事件与订单金额或付款人不一致")
    if event["type"] == "refund.succeeded":
        if order.status != "cancelled" or order.payment_status != "paid" or order.payment_id != body.paymentId:
            fail(409, "ORDER_CONFLICT", "退款事件与订单支付事实不一致")
        if order.refund_status == "processing":
            order = OrderGateway.transition(db, order, order.version, "refund", None,
                                            refund_status="succeeded", refund_id=body.refundId)
        elif order.refund_status != "succeeded":
            fail(409, "ORDER_CONFLICT", "订单尚未申请退款")
        elif order.refund_id != body.refundId:
            fail(409, "ORDER_CONFLICT", "订单已由其他退款记录完成退款")
    else:
        success = event["type"] == "payment.succeeded"
        if not success and not body.code:
            fail(422, "VALIDATION_ERROR", "失败支付必须携带原因代码")
        if success and body.code is not None:
            fail(422, "VALIDATION_ERROR", "成功支付不得携带失败代码")
        fact = db.get(PaymentFact, body.paymentRequestId)
        payload_hash = fingerprint(body.model_dump())
        if fact:
            if (fact.order_id, fact.outcome, fact.digest) != (order.id, event["type"], payload_hash):
                fail(409, "ORDER_CONFLICT", "同一支付预占的确定结果发生冲突")
        else:
            if order.payment_request_id != body.paymentRequestId:
                fail(409, "ORDER_CONFLICT", "未知的支付预占")
            db.add(PaymentFact(request_id=body.paymentRequestId, payment_id=body.paymentId,
                               order_id=order.id, outcome=event["type"], digest=payload_hash))
        if order.payment_request_id != body.paymentRequestId:
            # 旧失败事件不能释放新的支付预占；成功事件仍保留冲突诊断。
            if success:
                fail(409, "ORDER_CONFLICT", "支付预占不匹配")
        elif order.payment_status == "paid" and order.payment_id == body.paymentId:
            pass
        elif not success and order.payment_status == "unpaid":
            pass
        elif order.status == "pending_payment" and order.payment_status == "paying":
            order = OrderGateway.transition(db, order, order.version, "payment", None,
                status="pending" if success else "pending_payment",
                payment_status="paid" if success else "unpaid", payment_id=body.paymentId if success else None)
        else:
            fail(409, "ORDER_CONFLICT", "订单支付控制状态不匹配")
    result = {"accepted": True, "orderId": order.id, "version": order.version}
    db.add(EventReceipt(id=f"orders:{event['eventId']}", event_id=event["eventId"],
                        consumer=consumer, digest=digest, result=result))
    db.flush()
    return result
