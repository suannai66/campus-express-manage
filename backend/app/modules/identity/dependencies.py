"""团队共用鉴权依赖；读取复用请求会话，不在鉴权层提交或重开事务。"""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ...common import fail
from ...database import get_db


def current_identity(request: Request, db: Session = Depends(get_db)):
    service = getattr(request.app.state, "identity_service", None)
    if service is None:
        if not request.headers.get("Authorization"):
            fail(401, "AUTH_REQUIRED", "请先登录")
        fail(503, "DEPENDENCY_UNAVAILABLE", "身份服务尚未接入")
    return service.current(request, db)


def require_verified(user):
    if user.verified is not True:
        fail(403, "VERIFICATION_REQUIRED", "请先完成学生认证")
