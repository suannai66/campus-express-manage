"""F3/F4 只依赖共享身份和 D 报价能力，由单体装配入口注入。"""
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ...common import fail, iso
from ...database import get_db


@dataclass(frozen=True)
class Identity:
    uid: str
    role: str = "student"
    verified: bool = False


class IdentityService(Protocol):
    def current(self, request: Request, db: Session) -> Identity: ...


class PricingService(Protocol):
    def quote(self, draft) -> dict: ...


def current_identity(request: Request, db: Session = Depends(get_db)):
    # A 的实现负责同时校验 JWT、sid 和最新认证状态；不信任客户端 uid / Cookie。
    service = getattr(request.app.state, "identity_service", None)
    if service is None:
        if not request.headers.get("Authorization"):
            fail(401, "AUTH_REQUIRED", "请先登录")
        fail(503, "DEPENDENCY_UNAVAILABLE", "身份服务尚未接入")
    return service.current(request, db)


def require_verified(user):
    if user.verified is not True:
        fail(403, "VERIFICATION_REQUIRED", "请先完成学生认证")


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
