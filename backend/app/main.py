"""公共应用入口。业务路由由对应模块实现后在此注册。"""
from fastapi import FastAPI

from app.modules.finance.routers import wallet
from app.modules.finance.services import withdraw as withdraw_service

app = FastAPI(title="校园快递代取管理系统", version="0.1.0")

# 成员 D：F7/F8 钱包（v1 钱包闭环；payment 路由随冻结字段与 OrderGateway 接入后注册）
app.include_router(wallet.router)

# 成员 D：提现后台演示任务（团队接口约定 v1.1：≥3 秒标记 succeeded，重启续处理）
withdraw_service.start_withdraw_processor()


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
