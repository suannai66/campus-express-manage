"""F3/F4 应用入口与统一错误处理；A/C/D 的业务服务由单体装配注入。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .database import Base, engine
from .common import Idempotency
from .modules.identity.api import router as identity_router
from .modules.identity.config import Settings
from .modules.identity.models import User, Challenge, LoginSession, VerificationState
from .modules.identity.service import IdentityService


from .modules.orders.api import router as orders_router
from .modules.orders.entities import Order
from .modules.orders.handlers import EventReceipt, PaymentFact


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine, tables=[Order.__table__, Idempotency.__table__,
                                          EventReceipt.__table__, PaymentFact.__table__,
                                          User.__table__, Challenge.__table__,
                                          LoginSession.__table__, VerificationState.__table__])
    if not hasattr(app.state, "identity_service"):
        app.state.identity_service = IdentityService(Settings.from_environment())
    yield


app = FastAPI(title="校园快递代取管理系统", version="1.1.0", lifespan=lifespan)
for router in (orders_router, identity_router):
    app.include_router(router)


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    body = error.detail if isinstance(error.detail, dict) else {
        "detail": error.detail, "code": {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "ORDER_CONFLICT", 422: "VALIDATION_ERROR", 503: "DEPENDENCY_UNAVAILABLE"}.get(error.status_code, "REQUEST_FAILED"), "fields": {}}
    return JSONResponse(body, status_code=error.status_code, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    fields = {str(item["loc"][-1]): item["msg"] for item in error.errors()}
    return JSONResponse({"detail": "请检查输入内容", "code": "VALIDATION_ERROR", "fields": fields}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, error):
    return JSONResponse({"detail": "请求发生并发冲突，请使用原提交标识重试", "code": "REQUEST_IN_PROGRESS", "fields": {}}, status_code=409)


@app.exception_handler(OperationalError)
async def unavailable(request, error):
    return JSONResponse({"detail": "数据服务繁忙，请稍后重试", "code": "DEPENDENCY_UNAVAILABLE", "fields": {}}, status_code=503)


@app.exception_handler(Exception)
async def internal_error(request, error):
    return JSONResponse({"detail": "服务暂时无法完成请求，请稍后重试", "code": "INTERNAL_ERROR", "fields": {}}, status_code=500)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
