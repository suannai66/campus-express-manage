"""v1.1 订单契约与稳定地点目录。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import Field, field_validator

from ...common import Input, Money

STATIONS = {"station_cainiao": "菜鸟驿站", "station_sf": "顺丰服务点"}
AREAS = {"zone_qinyuan": "沁园", "zone_zhuyuan": "竹园", "zone_public": "公共交接点"}


class OrderDraft(Input):
    company: str = Field(min_length=1, max_length=30)
    code: str = Field(min_length=1, max_length=50)
    stationId: Literal["station_cainiao", "station_sf"]
    deliveryAreaId: Literal["zone_qinyuan", "zone_zhuyuan", "zone_public"]
    address: str = Field(min_length=1, max_length=200)
    size: Literal["small", "medium", "large"]
    weight: str = Field(pattern=r"^\d+(\.\d{1,2})?$")
    expectedAt: datetime
    tip: Money
    note: str = Field(default="", max_length=200)

    @field_validator("weight")
    @classmethod
    def valid_weight(cls, value):
        if not 0 < Decimal(value) <= 30:
            raise ValueError("重量须大于 0 且不超过 30 kg")
        return value

    @field_validator("expectedAt")
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("送达时间必须带时区")
        return value.astimezone(timezone.utc)


class Quote(Input):
    quoteId: str = Field(min_length=1, max_length=100)
    pricingVersion: str = Field(min_length=1, max_length=100)
    baseFee: int = Field(strict=True, ge=0)
    tip: Money
    amount: int = Field(strict=True, ge=0)
    commissionRateBps: int = Field(strict=True, ge=0, le=10000)
    expiresAt: datetime
    demo: bool = Field(strict=True)

    @field_validator("expiresAt")
    @classmethod
    def expiry(cls, value):
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError("报价必须尚未过期并带时区")
        return value.astimezone(timezone.utc)
