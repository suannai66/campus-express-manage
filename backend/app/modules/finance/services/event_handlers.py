"""资金消费者，handler(db, event) 共享投递方事务，不提交、不直接回调订单模块。"""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, ValidationError
from sqlalchemy import select
from ....common import Input, fail, fingerprint
from ..models import FinanceReceipt
from ..core.event_acl import cancelled_to_command
from .refund import refund_order


class Cancellation(Input):
    publisherUid: str = Field(min_length=1, max_length=100)
    paymentId: str | None = Field(min_length=1, max_length=100)
    amount: int = Field(strict=True, gt=0)
    paid: bool = Field(strict=True)
    orderVersion: int = Field(strict=True, gt=0)


class CancelEnvelope(Input):
    eventId: UUID
    type: Literal["order.cancelled"]
    occurredAt: datetime
    orderId: str = Field(min_length=1, max_length=100)
    aggregateType: Literal["order"]
    aggregateId: str = Field(min_length=1, max_length=100)
    version: int = Field(strict=True, gt=0)
    payload: Cancellation


def on_order_cancelled(db, event: dict) -> dict:
    try:
        data = CancelEnvelope.model_validate(event)
    except ValidationError:
        fail(422, "VALIDATION_ERROR", "取消事件格式不合法")
    if (data.occurredAt.tzinfo is None or data.aggregateId != data.orderId
            or data.payload.orderVersion != data.version
            or data.payload.paid != (data.payload.paymentId is not None)):
        fail(422, "VALIDATION_ERROR", "取消事件时间、聚合或支付标识不合法")
    event_id = str(data.eventId)
    digest = fingerprint(event)
    receipt = db.scalar(select(FinanceReceipt).where(
        FinanceReceipt.consumer == "finance", FinanceReceipt.event_id == event_id))
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    result = refund_order(db, cancelled_to_command(event))
    db.add(FinanceReceipt(id=f"finance:{event_id}", consumer="finance", event_id=event_id,
                          digest=digest, result=result))
    db.flush()
    return result


def on_order_completed(db, event: dict):
    raise NotImplementedError("TODO(迭代·结算): 消费订单完结事件")
