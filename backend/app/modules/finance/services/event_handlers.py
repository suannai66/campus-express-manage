"""资金消费者，handler(db, event) 共享投递方事务，不提交、不直接回调订单模块。"""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
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


def on_order_cancelled(db: Session, event: dict) -> dict:
    try:
        data = CancelEnvelope.model_validate(event)
    except ValidationError:
        fail(422, "VALIDATION_ERROR", "取消事件格式不合法")
    if (
        data.occurredAt.tzinfo is None
        or data.aggregateId != data.orderId
        or data.payload.orderVersion != data.version
        or data.payload.paid != (data.payload.paymentId is not None)
    ):
        fail(422, "VALIDATION_ERROR", "取消事件时间、聚合或支付标识不合法")
    event_id = str(data.eventId)
    digest = fingerprint(event)
    receipt = _find_receipt(db, event_id, digest)
    if receipt is not None:
        return receipt.result
    from ...orders.gateway import OrderGateway

    order = OrderGateway.get_snapshot(db, data.orderId)
    if data.version > order.version:
        fail(409, "ORDER_CONFLICT", "取消事件版本超前于订单事实")
    result = refund_order(db, cancelled_to_command(event))
    _save_receipt(db, event_id, digest, result)
    return result


class Completion(Input):
    publisherUid: str = Field(min_length=1, max_length=100)
    courierUid: str = Field(min_length=1, max_length=100)
    amount: int = Field(strict=True, gt=0)
    baseFee: int = Field(strict=True, ge=0)
    tip: int = Field(strict=True, ge=0)
    commissionRateBps: int = Field(strict=True, ge=0, le=10000)
    pricingVersion: str = Field(min_length=1, max_length=100)
    orderVersion: int = Field(strict=True, gt=0)


class CompleteEnvelope(Input):
    eventId: UUID
    type: Literal["order.completed"]
    occurredAt: datetime
    orderId: str = Field(min_length=1, max_length=100)
    aggregateType: Literal["order"]
    aggregateId: str = Field(min_length=1, max_length=100)
    version: int = Field(strict=True, gt=0)
    payload: Completion


def on_order_completed(db: Session, event: dict) -> dict:
    from ..core.event_acl import completed_to_command
    from ...orders.gateway import OrderGateway
    from .settlement import settle_order

    try:
        data = CompleteEnvelope.model_validate(event)
    except ValidationError:
        fail(422, "VALIDATION_ERROR", "完结事件格式不合法")
    if (
        data.occurredAt.tzinfo is None
        or data.aggregateId != data.orderId
        or data.version != data.payload.orderVersion
        or data.payload.amount != data.payload.baseFee + data.payload.tip
    ):
        fail(422, "VALIDATION_ERROR", "完结事件时间、聚合或金额不合法")
    event_id, digest = str(data.eventId), fingerprint(event)
    receipt = _find_receipt(db, event_id, digest)
    if receipt is not None:
        return receipt.result
    order = OrderGateway.get_snapshot(db, data.orderId)
    if data.version > order.version:
        fail(409, "ORDER_CONFLICT", "完结事件版本超前于订单事实")
    if data.payload.pricingVersion != order.pricing_version or data.payload.tip != order.tip:
        fail(409, "ORDER_CONFLICT", "完结事件费率版本或小费与订单不一致")
    result = settle_order(db, completed_to_command(event))
    _save_receipt(db, event_id, digest, result)
    return result


def _find_receipt(db: Session, event_id: str, digest: str) -> FinanceReceipt | None:
    """复用已消费结果，同标识不同内容仍拒绝处理。"""
    receipt = db.scalar(
        select(FinanceReceipt).where(
            FinanceReceipt.consumer == "finance", FinanceReceipt.event_id == event_id
        )
    )
    if receipt is not None and receipt.digest != digest:
        fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
    return receipt


def _save_receipt(db: Session, event_id: str, digest: str, result: dict) -> None:
    """回执与资金处理共享调用方事务，不自行提交。"""
    db.add(
        FinanceReceipt(
            id=f"finance:{event_id}",
            consumer="finance",
            event_id=event_id,
            digest=digest,
            result=result,
        )
    )
    db.flush()
