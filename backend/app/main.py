"""公共应用入口。业务路由由对应模块实现后在此注册。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import engine
from .modules.orders.models import Order, OrderStatusReceipt, PaymentReceipt
from .modules.orders.hall import router as hall_router
from .modules.orders.router import router as orders_router


@asynccontextmanager
async def lifespan(app):
    # 只创建 B 自有表，不接管其他成员模块的建表。
    Order.metadata.create_all(engine, tables=[Order.__table__, PaymentReceipt.__table__, OrderStatusReceipt.__table__])
    yield

app = FastAPI(title="校园快递代取管理系统", version="0.1.0", lifespan=lifespan)
app.include_router(hall_router)
app.include_router(orders_router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
