"""隔离数据库真实 HTTP + JWT/认证 + 后台事件投递资金闭环联调。"""
import tempfile
import time
import unittest
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
import app.main as main
from app.common import iso, now
from app.database import get_db
from app.modules.identity.config import Settings
from app.modules.identity.service import IdentityService
from app.modules.identity.models import User
from app.modules.finance.services.pricing import PricingService
from app.modules.finance.models import Account, Payment, Refund, Settlement
from app.events.models import Delivery


class FullTradeChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/full-chain.db",
            connect_args={"check_same_thread": False, "timeout": 30})
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.engine_patch = patch.object(main, "engine", self.engine)
        self.engine_patch.start()
        from app.events.service import start_processor
        # 其他测试可能保留启动入口替身；本组必须显式使用真实后台线程。
        self.events_patch = patch.object(main, "start_processor", start_processor)
        self.events_patch.start()
        self.withdraw_patch = patch("app.modules.finance.services.withdraw.start_withdraw_processor")
        self.withdraw_patch.start()  # 此联调不操作提现，避免其模块级工厂访问开发库。
        self.old_identity = getattr(main.app.state, "identity_service", None)
        self.old_pricing = getattr(main.app.state, "pricing_service", None)
        main.app.state.identity_service = IdentityService(Settings(secret="integration-test-only-" * 3, demo_code="482917"))
        main.app.state.pricing_service = PricingService()
        def database():
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = database
        self.client = TestClient(main.app).__enter__()
        self.publisher, self.owner = self.user("13900008001")
        self.courier, self.runner = self.user("13900008002")
        admin_uid, self.admin = self.user("13900008003")
        # 首位管理员属于受控初始化，后续审核通过真实权限入口执行。
        with self.sessions.begin() as db:
            db.get(User, admin_uid).role = "admin"
        self.verify(self.owner, "20268001")
        self.verify(self.runner, "20268002")

    def tearDown(self):
        self.client.__exit__(None, None, None)  # 等待真实事件线程停止后再销毁临时库。
        main.app.dependency_overrides.clear()
        for name, old in (("identity_service", self.old_identity), ("pricing_service", self.old_pricing)):
            if old is None:
                if hasattr(main.app.state, name): delattr(main.app.state, name)
            else:
                setattr(main.app.state, name, old)
        self.events_patch.stop()
        self.withdraw_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def post(self, path, body=None, headers=None, expected=200):
        response = self.client.post(path, json=body, headers={**(headers or {}), "Idempotency-Key": str(uuid4())})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def get(self, path, headers=None):
        response = self.client.get(path, headers=headers or self.owner)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def user(self, phone):
        self.post("/api/auth/codes", {"phone": phone, "purpose": "register"})
        uid = self.post("/api/auth/register", {"phone": phone, "code": "482917"}, expected=201)["uid"]
        self.post("/api/auth/codes", {"phone": phone, "purpose": "login"})
        token = self.post("/api/auth/login", {"phone": phone, "code": "482917"})["accessToken"]
        return uid, {"Authorization": "Bearer " + token}

    def verify(self, headers, student_no):
        stream = BytesIO()
        Image.new("RGB", (60, 30), "green").save(stream, format="PNG")
        response = self.client.post("/api/auth/verification-applications", headers=headers,
            data={"realName": "联调同学", "studentNo": student_no},
            files={"photo": ("fictional.png", stream.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 201, response.text)
        self.post("/api/admin/verification-applications/" + response.json()["applicationId"] + "/review",
                  {"decision": "approved", "rejectReason": None, "version": 1}, self.admin)
        self.assertTrue(self.get("/api/auth/verify-status", headers)["verified"])

    def wait_for(self, condition, message):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            value = condition()
            if value: return value
            time.sleep(0.1)
        self.fail(message)

    def order(self):
        recharge = self.post("/api/wallet/recharge", {"amount": 1000}, self.owner, 201)
        self.post("/api/wallet/recharge/" + recharge["rechargeId"] + "/confirm", headers=self.owner)
        draft = {"company": "中通", "code": "test-pickup-0821", "stationId": "station_cainiao",
                 "deliveryAreaId": "zone_qinyuan", "size": "small", "weight": "1.2",
                 "address": "虚构测试地址", "tip": 235, "expectedAt": iso(now() + timedelta(hours=2)), "note": ""}
        quote = self.post("/api/orders/quote", draft, self.owner)
        self.assertEqual((quote["baseFee"], quote["amount"]), (300, 535))
        order = self.post("/api/orders", draft, self.owner, 201)
        reservation = self.post(f"/api/orders/{order['orderId']}/payment-request", {"version": order["version"]}, self.owner)
        payment = self.post("/api/pay/prepay", {"orderId": order["orderId"], "paymentRequestId": reservation["paymentRequestId"]}, self.owner)
        self.assertEqual(payment["status"], "succeeded")
        self.assertEqual(self.get("/api/wallet")["balance"], 465)
        order_id = order["orderId"]
        def ready():
            value = self.get("/api/orders/" + order_id)
            return value if value["status"] == "pending" else None
        order = self.wait_for(ready, "支付事件未自动推进到待接单")
        hall = self.get("/api/orders?scope=hall", self.runner)
        self.assertIn(order_id, [row["orderId"] for row in hall["items"]])
        return order, payment

    def assert_delivered_events(self):
        def done():
            with self.sessions() as db:
                return db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status != "succeeded")) == 0
        self.wait_for(done, "事件存在未完成投递")

    def test_real_auth_recharge_payment_delivery_and_settlement(self):
        order, payment = self.order()
        order = self.post(f"/api/orders/{order['orderId']}/accept", {"version": order["version"]}, self.runner)
        for action in ("start_pickup", "confirm_pickup", "confirm_delivery"):
            body = {"version": order["version"], "action": action}
            if action == "confirm_pickup": body["code"] = "test-pickup-0821"
            order = self.post(f"/api/orders/{order['orderId']}/status", body, self.runner)
        self.assertEqual(order["status"], "delivered")
        self.wait_for(lambda: self.get("/api/wallet", self.runner)["balance"] == 505, "配送后未自动结算")
        self.assert_delivered_events()
        with self.sessions() as db:
            owner, runner = db.get(Account, self.publisher), db.get(Account, self.courier)
            settlement = db.scalar(select(Settlement))
            self.assertEqual((owner.available_cent, owner.frozen_cent, runner.available_cent), (465, 0, 505))
            self.assertEqual(settlement.commission, 30)
            self.assertEqual(owner.available_cent + owner.frozen_cent + runner.available_cent + settlement.commission, 1000)
            self.assertEqual(db.get(Payment, payment["paymentId"]).funds_status, "settled")
        ledger = self.get("/api/wallet/transactions?type=settlement", self.runner)
        self.assertEqual(ledger["items"][0]["orderId"], order["orderId"])
        self.assertEqual(ledger["items"][0]["amount"], 505)

    def test_real_auth_payment_cancel_and_full_refund(self):
        order, payment = self.order()
        cancelled = self.post(f"/api/orders/{order['orderId']}/cancel",
                              {"version": order["version"], "reason": "联调取消"}, self.owner)
        self.assertEqual(cancelled["status"], "cancelled")
        def refunded():
            value = self.get("/api/orders/" + order["orderId"])
            return value if value["refundStatus"] == "succeeded" else None
        final = self.wait_for(refunded, "取消后退款事件未自动完成")
        self.assertEqual(final["paymentStatus"], "paid")
        self.assert_delivered_events()
        self.assertEqual(self.get("/api/wallet")["balance"], 1000)
        with self.sessions() as db:
            self.assertEqual(db.get(Account, self.publisher).frozen_cent, 0)
            self.assertEqual(db.get(Payment, payment["paymentId"]).funds_status, "refunded")
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 0)
        ledger = self.get("/api/wallet/transactions?type=refund")
        self.assertEqual((ledger["total"], ledger["items"][0]["amount"]), (1, 535))
