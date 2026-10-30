"""公共应用入口。业务路由由对应模块实现后在此注册。"""
from fastapi import FastAPI

from app.modules.finance.routers import wallet

app = FastAPI(title="校园快递代取管理系统", version="0.1.0")

# 成员 D：F7/F8 钱包（v1 钱包闭环；payment/events 路由随冻结与事件契约接入后注册）
app.include_router(wallet.router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
