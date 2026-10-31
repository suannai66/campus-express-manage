"""浏览器契约测试专用装配；替代尚未实现的 A/D 接口。禁止用于开发部署。"""
from uuid import uuid4
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.main import app
from app.database import get_db
from app.common import iso, now
from app.modules.orders.integrations import current_identity
from app.modules.orders.handlers import handle
from app.modules.orders.gateway import OrderGateway
from .fixtures import TestIdentity, TestPricing

app.state.identity_service = TestIdentity()
app.state.pricing_service = TestPricing()

@app.get('/api/auth/current')
def current(user=Depends(current_identity)):
    return {"uid": user.uid, "phone": "13900000001", "nickname": "测试同学", "role": "student"}

@app.get('/api/auth/verify-status')
def verify(user=Depends(current_identity)):
    return {"verified": user.verified, "status": "approved" if user.verified else "not_submitted", "rejectReason": None, "applicationId": None, "version": None}

@app.post('/api/pay/prepay')
def pay(body: dict, user=Depends(current_identity), db: Session = Depends(get_db)):
    order = OrderGateway.related(db, body['orderId'], user.uid)
    payment_id = str(uuid4())
    handle(db, {"eventId": str(uuid4()), "type": "payment.succeeded", "occurredAt": iso(now()), "orderId": order.id, "aggregateType": "payment", "aggregateId": payment_id, "version": 1, "payload": {"paymentId": payment_id, "paymentRequestId": body['paymentRequestId'], "payerUid": user.uid, "amount": order.amount}})
    db.commit()
    return {"paymentId": payment_id, "orderId": order.id, "amount": order.amount, "status": "succeeded", "code": None}

# FastAPI 的 include_router 可保留嵌套路由；测试替身端点显式置前，避免命中真实 F1。
# 此模块只由 F3/F4 测试启动，生产入口不导入。
paths = {'/api/auth/current', '/api/auth/verify-status'}
overrides = [route for route in app.router.routes if getattr(route, 'path', '') in paths]
app.router.routes[:] = overrides + [route for route in app.router.routes if route not in overrides]
