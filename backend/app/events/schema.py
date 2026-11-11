"""公共事件边界：严格 JSON、已约定类型及必要业务字段，拒绝隐私附加字段。"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, ValidationError
from ..common import Input, fail


SUBSCRIPTIONS = {
    "payment.succeeded": ("orders",),
    "payment.failed": ("orders",),
    "refund.succeeded": ("orders",),
    "order.status_changed": ("orders",),
    "order.cancelled": ("orders", "finance"),
    "order.completed": ("finance", "fulfillment"),
}

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Positive = Annotated[int, Field(strict=True, gt=0)]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Status = Literal["pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "completed", "cancelled"]


class Envelope(Input):
    eventId: str
    type: str
    occurredAt: str
    orderId: Identifier
    aggregateType: Literal["payment", "refund", "order"]
    aggregateId: Identifier
    version: Positive
    payload: dict


class PaymentPayload(Input):
    paymentId: Identifier
    paymentRequestId: Identifier
    payerUid: Identifier
    amount: Positive
    code: str | None = None


class RefundPayload(Input):
    refundId: Identifier
    paymentId: Identifier
    payerUid: Identifier
    amount: Positive


class Cancellation(Input):
    publisherUid: Identifier
    paymentId: Identifier | None
    amount: Positive
    paid: bool = Field(strict=True)
    orderVersion: Positive


class Completion(Input):
    publisherUid: Identifier
    courierUid: Identifier
    amount: Positive
    baseFee: Nonnegative
    tip: Nonnegative
    commissionRateBps: int = Field(strict=True, ge=0, le=10000)
    pricingVersion: Identifier
    orderVersion: Positive


class StatusChange(Input):
    fromStatus: Status
    status: Status
    courierUid: Identifier | None
    orderVersion: Positive


def validate(event):
    try:
        if type(event) is not dict:
            raise ValueError("事件必须为字典")
        data = Envelope.model_validate(event)
        if str(UUID(data.eventId)) != event["eventId"]:
            raise ValueError("事件标识必须为规范 UUID")
        if not event["occurredAt"].endswith("Z"):
            raise ValueError("事件时间必须为 UTC Z 字符串")
        occurred = datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00"))
        if occurred.utcoffset() != timedelta(0):
            raise ValueError("事件时间缺少 UTC 时区")
        if data.type not in SUBSCRIPTIONS:
            raise ValueError("事件类型未约定")
        if data.type.startswith("payment."):
            body = PaymentPayload.model_validate(data.payload)
            if ((data.type == "payment.failed" and not body.code)
                    or (data.type == "payment.succeeded" and body.code is not None)):
                raise ValueError("支付结果与失败代码不一致")
            aggregate_type, aggregate_id = "payment", body.paymentId
        elif data.type == "refund.succeeded":
            body = RefundPayload.model_validate(data.payload)
            aggregate_type, aggregate_id = "refund", body.refundId
        else:
            model = {"order.cancelled": Cancellation, "order.completed": Completion,
                     "order.status_changed": StatusChange}[data.type]
            body = model.model_validate(data.payload)
            aggregate_type, aggregate_id = "order", data.orderId
            if body.orderVersion != data.version:
                raise ValueError("订单版本不一致")
            if isinstance(body, Cancellation) and body.paid != (body.paymentId is not None):
                raise ValueError("支付标识不一致")
            if isinstance(body, Completion) and body.amount != body.baseFee + body.tip:
                raise ValueError("金额不一致")
        if (data.aggregateType, data.aggregateId) != (aggregate_type, aggregate_id):
            raise ValueError("聚合标识不一致")
        encoded = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return json.loads(encoded), hashlib.sha256(encoded.encode()).hexdigest()
    except (ValidationError, ValueError, TypeError, OverflowError):
        fail(422, "VALIDATION_ERROR", "事件格式不符合团队接口约定")
