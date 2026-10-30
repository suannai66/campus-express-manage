"""接入层：FastAPI 薄控制器。JWT 鉴权（Q-05）+ 参数校验，业务编排一律下沉 services/。

注册方式（联调时与队长沟通后改 backend/app/main.py）：
    from app.modules.finance.routers import payment, wallet, events
    app.include_router(payment.router)
    app.include_router(wallet.router)
    app.include_router(events.router)
"""
