"""资金冻结与 B 支付预占集成，使用临时数据库。"""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import select, func
from app.modules.finance.models import Account, Ledger, Payment
from app.modules.finance.core import wallet_core
from app.modules.orders.handlers import handle
import test_orders


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_orders.OrderTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        # 鉴权必须覆盖共享 Session 查库，不能只测无数据库的替身。
        from fixtures import TestIdentity
        class DatabaseIdentity(TestIdentity):
            def current(self, request, db):
                db.execute(select(Account.uid))
                return super().current(request, db)
        import app.main as main
        main.app.state.identity_service = DatabaseIdentity()

    def order(self):
        order = self.fixture.create().json()
        reservation = self.fixture.reserve(order).json()
        return {"orderId": order["orderId"], "paymentRequestId": reservation["paymentRequestId"]}

    def fund(self, amount=1000):
        with self.fixture.sessions.begin() as db:
            wallet_core.credit(db, "alice", amount, str(uuid4()), "recharge")

    def pay(self, body, key=None, uid="alice"):
        return self.fixture.client.post("/api/pay/prepay", json=body, headers=self.fixture.headers(uid, key))

    def balances(self):
        with self.fixture.sessions() as db:
            row = db.get(Account, "alice")
            return (row.available_cent, row.frozen_cent) if row else (0, 0)

    def test_freeze_replay_query_event_and_ledger(self):
        self.fund()
        body = self.order()
        key = str(uuid4())
        first = self.pay(body, key)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "succeeded")
        self.assertEqual(self.balances(), (465, 535))
        for retry_key in (key, str(uuid4())):
            self.assertEqual(self.pay(body, retry_key).json(), first.json())
        self.assertEqual(self.balances(), (465, 535))
        path = "/api/pay/payments/" + first.json()["paymentId"]
        self.assertEqual(self.fixture.get(path).json(), first.json())
        self.assertEqual(self.fixture.get(path, "bob").status_code, 404)
        page = self.fixture.get("/api/wallet/transactions?type=payment").json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["orderId"], body["orderId"])
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, first.json()["paymentId"])
            self.assertEqual((row.funds_status, row.event_status), ("frozen", "pending"))
            handle(db, row.event)  # 验证 B 能消费真实事件；仅测试直接调用。
        self.assertEqual(self.fixture.get("/api/orders/" + body["orderId"]).json()["status"], "pending")

    def test_insufficient_result_is_permanent_for_reservation(self):
        body = self.order()
        first = self.pay(body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["code"], "INSUFFICIENT_BALANCE")
        self.fund()
        self.assertEqual(self.pay(body).json(), first.json())
        self.assertEqual(self.balances(), (1000, 0))
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, first.json()["paymentId"])
            handle(db, row.event)
        self.assertEqual(self.fixture.get("/api/orders/" + body["orderId"]).json()["paymentStatus"], "unpaid")

    def test_validation_ownership_and_key_conflict(self):
        self.fund()
        body = self.order()
        self.assertEqual(self.pay(body, uid="bob").status_code, 404)
        self.assertEqual(self.pay({**body, "paymentRequestId": "wrong"}).status_code, 409)
        self.assertEqual(self.pay({**body, "amount": 1}).status_code, 422)
        response = self.fixture.client.post("/api/pay/prepay", json=body, headers={"Authorization": "Bearer alice"})
        self.assertEqual(response.status_code, 422)
        key = str(uuid4())
        self.assertEqual(self.pay(body, key).status_code, 200)
        self.assertEqual(self.pay(self.order(), key).status_code, 409)
        self.assertEqual(self.balances(), (465, 535))

    def test_failure_after_freeze_rolls_everything_back(self):
        self.fund()
        body = self.order()
        with patch("app.modules.finance.services.payment.remember", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError):
                self.pay(body)
        self.assertEqual(self.balances(), (1000, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Payment)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(Ledger.biz_type == "payment")), 0)
        self.assertEqual(self.pay(body).status_code, 200)

    def test_concurrent_distinct_orders_cannot_overdraw(self):
        self.fund()
        bodies = [self.order(), self.order()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(self.pay, bodies))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(sorted(r.json()["status"] for r in responses), ["failed", "succeeded"])
        self.assertEqual(self.balances(), (465, 535))

    def test_concurrent_same_reservation_freezes_once(self):
        self.fund()
        body = self.order()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.pay(body), range(2)))
        self.assertTrue(all(r.status_code in (200, 409) for r in responses), [r.text for r in responses])
        self.assertEqual(self.balances(), (465, 535))
        self.assertEqual(self.pay(body).json()["status"], "succeeded")
