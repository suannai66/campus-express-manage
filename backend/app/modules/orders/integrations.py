"""F3/F4 只依赖共享身份和 D 报价能力，由单体装配入口注入。"""
from typing import Protocol

from fastapi import Request
from sqlalchemy.orm import Session

from ...common import fail, iso
from ..identity.service import Identity
from ..identity.dependencies import current_identity, require_verified


class IdentityService(Protocol):
    def current(self, request: Request, db: Session) -> Identity: ...


class PricingService(Protocol):
    def quote(self, draft) -> dict: ...


def quote(draft, request):
    from .contract import Quote
    from pydantic import ValidationError
    service = getattr(request.app.state, "pricing_service", None)
    if service is None:
        fail(503, "DEPENDENCY_UNAVAILABLE", "报价服务尚未接入")
    try:
        result = Quote.model_validate(service.quote(draft))
    except (ValidationError, TypeError, ValueError):
        fail(503, "DEPENDENCY_UNAVAILABLE", "报价服务返回无效结果")
    if result.tip != draft.tip or result.amount != result.baseFee + result.tip:
        fail(503, "DEPENDENCY_UNAVAILABLE", "报价金额不一致")
    data = result.model_dump(mode="json")
    data["expiresAt"] = iso(result.expiresAt)
    return data
