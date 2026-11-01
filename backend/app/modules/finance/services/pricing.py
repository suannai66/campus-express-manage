"""只读报价能力；不查询或修改钱包、订单，也不接受客户端覆盖正式价格。"""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ....common import iso, now
from .. import config


class PricingInput(BaseModel):
    # OrderDraft 还有地址等非计价字段，本能力只提取计价要素。
    model_config = ConfigDict(from_attributes=True)
    stationId: Literal["station_cainiao", "station_sf"]
    deliveryAreaId: Literal["zone_qinyuan", "zone_zhuyuan", "zone_public"]
    size: Literal["small", "medium", "large"]
    weight: str = Field(strict=True, pattern=r"^\d+(\.\d{1,2})?$")
    tip: int = Field(strict=True, ge=0, le=99900)

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value):
        if not 0 < Decimal(value) <= 30:
            raise ValueError("重量须大于 0 且不超过 30 kg")
        return value


class PricingService:
    @staticmethod
    def quote(draft) -> dict:
        data = PricingInput.model_validate(draft)
        extra_kg = max(0, int(Decimal(data.weight).to_integral_value(rounding=ROUND_CEILING)) - 1)
        base_fee = (
            config.ROUTE_FEES[data.stationId][data.deliveryAreaId]
            + config.SIZE_FEES[data.size]
            + extra_kg * config.EXTRA_KG_FEE
        )
        return {
            "quoteId": str(uuid4()),
            "pricingVersion": config.PRICING_VERSION,
            "baseFee": base_fee,
            "tip": data.tip,
            "amount": base_fee + data.tip,
            "commissionRateBps": config.COMMISSION_RATE_BPS,
            "expiresAt": iso(now() + timedelta(seconds=config.QUOTE_VALID_SECONDS)),
            "demo": True,
        }
