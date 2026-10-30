from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Money = Annotated[Decimal, Field(ge=0, le=999, decimal_places=2, allow_inf_nan=False)]


class OrderDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    company: str = Field(min_length=1, max_length=30)
    code: str = Field(min_length=1, max_length=50)
    station: str = Field(min_length=1, max_length=60)
    size: Literal["小件", "中件", "大件"]
    weight: Decimal = Field(gt=0, le=30, decimal_places=2, allow_inf_nan=False)
    address: str = Field(min_length=1, max_length=200)
    expectedAt: datetime
    tip: Money
    note: str = Field(default="", max_length=200)

    @field_validator("expectedAt")
    @classmethod
    def future_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("送达时间必须带时区")
        now = datetime.now(timezone.utc)
        if value <= now or value > now + timedelta(days=7):
            raise ValueError("请选择未来七天内的送达时间")
        return value.astimezone(timezone.utc)


class PaymentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    eventId: str = Field(min_length=1, max_length=100)
    paymentId: str = Field(min_length=1, max_length=100)
    orderId: str = Field(min_length=1, max_length=36)
    uid: str = Field(min_length=1, max_length=100)
    amountCents: int = Field(gt=0, strict=True)


class DemoSession(BaseModel):
    state: Literal["verified", "unverified", "guest"]
