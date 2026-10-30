"""F8 钱包契约测试（团队接口约定 v1.1 第 10/12/13 节，D 的验收责任）。

使用临时 SQLite 和仅测试装配的身份替身（fixtures.TestIdentity），不复用开发数据库。
覆盖：并发充值不丢余额更新、资金幂等（缺键/同键同体/同键改额/重复 confirm）、
严格金额校验、身份入口（不信任 X-User-Id）、余额不足不透支。
"""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.database import get_db
from app.modules.finance.core import wallet_core
from app.modules.finance.models import Account
from app.modules.finance.services import withdraw as withdraw_service
from fixtures import TestIdentity


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.temp.name}/wallet.db",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        self.sessions = sessionmaker(bind=self.engine)
        self.engine_patch = patch.object(main, "engine", self.engine)
        self.engine_patch.start()
        # 测试内不启动提现后台演示任务（避免守护线程触碰真实开发库）
        self.processor_patch = patch.object(withdraw_service, "start_withdraw_processor")
        self.processor_patch.start()

        def session_dependency():
            with self.sessions() as session:
                yield session

        main.app.dependency_overrides[get_db] = session_dependency
        main.app.state.identity_service = TestIdentity()
        self.client = TestClient(main.app).__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        if hasattr(main.app.state, "identity_service"):
            delattr(main.app.state, "identity_service")
        self.processor_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    # ---- 请求工具 ----

    def headers(self, uid="alice", key=None):
        headers = {"Authorization": f"Bearer {uid}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return headers

    def recharge(self, amount, uid="alice", key=None):
        return self.client.post(
            "/api/wallet/recharge",
            json={"amount": amount},
            headers=self.headers(uid, key if key is not None else str(uuid4())),
        )

    def confirm(self, recharge_id, uid="alice"):
        return self.client.post(
            f"/api/wallet/recharge/{recharge_id}/confirm", headers=self.headers(uid)
        )

    def withdraw(self, amount, uid="alice", key=None):
        return self.client.post(
            "/api/wallet/withdraw",
            json={"amount": amount},
            headers=self.headers(uid, key if key is not None else str(uuid4())),
        )

    def balance(self, uid="alice"):
        return self.client.get("/api/wallet", headers=self.headers(uid)).json()["balance"]

    def fund(self, amount, uid="alice"):
        """充值并 confirm，使账户有余额。"""
        order = self.recharge(amount, uid).json()
        self.assertEqual(self.confirm(order["rechargeId"], uid).json()["status"], "succeeded")

    # ---- 余额守恒与并发 ----

    def test_recharge_flow_preserves_total_balance(self):
        for amount in (1000, 2000):
            order = self.recharge(amount).json()
            self.assertEqual(self.confirm(order["rechargeId"]).json()["amount"], amount)
        self.assertEqual(self.balance(), 3000)
        page = self.client.get(
            "/api/wallet/transactions?page=1&pageSize=20", headers=self.headers()
        ).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["items"][0]["balanceAfter"], 3000)

    def test_concurrent_confirms_do_not_lose_balance_updates(self):
        orders = [self.recharge(amount).json() for amount in (1000, 2000)]

        def confirm_one(recharge_id):
            return self.confirm(recharge_id).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm_one, [o["rechargeId"] for o in orders]))
        self.assertEqual(results, [200, 200])
        # 关键断言：并发下余额为两笔之和，而不是后写覆盖先写
        self.assertEqual(self.balance(), 3000)

    def test_concurrent_credit_core_is_atomic(self):
        """领域层直接并发入账：相对更新保证串行叠加。"""

        def credit_one(args):
            key, amount = args
            with self.sessions.begin() as db:
                wallet_core.credit(db, "alice", amount, key, "recharge")

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(credit_one, [("core-1", 1000), ("core-2", 2000)]))
        with self.sessions() as db:
            account = db.get(Account, "alice")
            self.assertEqual(account.available_cent, 3000)

    # ---- 资金幂等（约定第 12 节） ----

    def test_withdraw_requires_idempotency_key(self):
        response = self.client.post(
            "/api/wallet/withdraw", json={"amount": 100}, headers={"Authorization": "Bearer alice"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(self.balance(), 0)

    def test_recharge_requires_idempotency_key(self):
        response = self.client.post(
            "/api/wallet/recharge", json={"amount": 100}, headers={"Authorization": "Bearer alice"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(self.balance(), 0)

    def test_withdraw_same_key_same_body_returns_original_and_deducts_once(self):
        self.fund(3000)
        key = str(uuid4())
        first = self.withdraw(1000, key=key)
        self.assertEqual(first.status_code, 201)
        replay = self.withdraw(1000, key=key)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json()["withdrawId"], first.json()["withdrawId"])
        self.assertEqual(self.balance(), 2000)  # 只扣一次

    def test_withdraw_same_key_different_amount_conflict(self):
        self.fund(3000)
        key = str(uuid4())
        self.assertEqual(self.withdraw(1000, key=key).status_code, 201)
        conflict = self.withdraw(2000, key=key)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.balance(), 2000)

    def test_recharge_same_key_same_body_returns_original(self):
        key = str(uuid4())
        first = self.recharge(1000, key=key)
        self.assertEqual(first.status_code, 201)
        replay = self.recharge(1000, key=key)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json()["rechargeId"], first.json()["rechargeId"])

    def test_recharge_same_key_different_amount_conflict(self):
        key = str(uuid4())
        self.assertEqual(self.recharge(1000, key=key).status_code, 201)
        conflict = self.recharge(2000, key=key)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")

    def test_repeat_confirm_credits_once(self):
        order = self.recharge(500).json()
        for _ in range(2):
            self.assertEqual(self.confirm(order["rechargeId"]).json()["status"], "succeeded")
        self.assertEqual(self.balance(), 500)
        page = self.client.get(
            "/api/wallet/transactions?page=1&pageSize=20", headers=self.headers()
        ).json()
        self.assertEqual(page["total"], 1)

    # ---- 严格金额校验（约定：拒绝字符串、小数、布尔值） ----

    def test_amount_rejects_non_strict_values(self):
        for bad in [True, "100", 100.0, 0, 100001]:
            recharge = self.recharge(bad)
            self.assertEqual(recharge.status_code, 422, f"recharge amount={bad!r}")
            self.assertEqual(recharge.json()["code"], "VALIDATION_ERROR")
            withdraw = self.withdraw(bad)
            self.assertEqual(withdraw.status_code, 422, f"withdraw amount={bad!r}")
            self.assertEqual(withdraw.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(self.balance(), 0)

    # ---- 身份入口（约定第 5/6 节：凭证 Bearer，不信任客户端自报身份） ----

    def test_wallet_requires_login(self):
        response = self.client.get("/api/wallet")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "AUTH_REQUIRED")

    def test_x_user_id_header_is_not_trusted(self):
        response = self.client.get("/api/wallet", headers={"X-User-Id": "alice"})
        self.assertEqual(response.status_code, 401)

    def test_unknown_token_rejected(self):
        response = self.client.get("/api/wallet", headers={"Authorization": "Bearer mallory"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "AUTH_REQUIRED")

    def test_wallet_scoped_to_authenticated_user(self):
        self.fund(1000, uid="alice")
        self.assertEqual(self.balance("alice"), 1000)
        self.assertEqual(self.balance("bob"), 0)

    # ---- 余额不足不透支 ----

    def test_withdraw_insufficient_balance(self):
        response = self.withdraw(100)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(self.balance(), 0)  # 业务失败整体回滚，余额不变


if __name__ == "__main__":
    unittest.main()
