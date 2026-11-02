"""提现回补与正式模式充值确认限制。"""
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select, func
import app.main as main
import test_wallet
from app.common import now
from app.modules.finance.models import Account, Ledger, WithdrawOrder, RechargeOrder
from app.modules.finance.services import withdraw, recharge


class WithdrawalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.f = test_wallet.WalletTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.fund(1000)
        response = self.f.withdraw(500)
        self.assertEqual(response.status_code, 201)
        self.withdraw_id = response.json()["withdrawId"]

    def due(self):
        with self.f.sessions.begin() as db:
            db.get(WithdrawOrder, self.withdraw_id).created_at = now() - timedelta(seconds=10)

    def finish(self, outcome="failed"):
        with self.f.sessions.begin() as db:
            return withdraw.finish_withdrawal(db, self.withdraw_id, outcome=outcome,
                                             reason="模拟失败" if outcome == "failed" else None)

    def test_fail_refunds_once_and_query_is_scoped(self):
        self.due()
        self.assertTrue(self.finish())
        self.assertFalse(self.finish())
        self.assertFalse(self.finish("succeeded"))
        self.assertEqual(self.f.balance(), 1000)
        with self.f.sessions() as db:
            row = db.get(WithdrawOrder, self.withdraw_id)
            self.assertEqual((row.status, row.fail_reason), ("failed", "模拟失败"))
            count = db.scalar(select(func.count()).select_from(Ledger).where(
                Ledger.idempotency_key == "withdraw-reversal:" + self.withdraw_id))
            self.assertEqual(count, 1)
        path = "/api/wallet/withdrawals/" + self.withdraw_id
        self.assertEqual(self.f.client.get(path, headers=self.f.headers()).json()["status"], "failed")
        self.assertEqual(self.f.client.get(path, headers=self.f.headers("bob")).status_code, 404)

    def test_not_due_and_success_never_refunds(self):
        self.assertFalse(self.finish())
        self.assertEqual(self.f.balance(), 500)
        self.due()
        self.assertTrue(self.finish("succeeded"))
        self.assertFalse(self.finish())
        self.assertEqual(self.f.balance(), 500)

    def test_concurrent_failure_and_success_have_one_terminal_result(self):
        self.due()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.finish, ["failed", "succeeded"]))
        self.assertEqual(sum(results), 1)
        with self.f.sessions() as db:
            status = db.get(WithdrawOrder, self.withdraw_id).status
        self.assertEqual(self.f.balance(), 1000 if status == "failed" else 500)

    def test_concurrent_failures_only_credit_once(self):
        self.due()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.finish(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.f.balance(), 1000)

    def test_failure_after_credit_rolls_back_status_and_ledger(self):
        self.due()
        original = withdraw.wallet_core.credit
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("injected after reversal credit")
        with patch.object(withdraw.wallet_core, "credit", side_effect=interrupted):
            with self.assertRaises(RuntimeError): self.finish()
        self.assertEqual(self.f.balance(), 500)
        with self.f.sessions() as db:
            row = db.get(WithdrawOrder, self.withdraw_id)
            self.assertEqual((row.status, row.fail_reason), ("processing", None))
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(
                Ledger.idempotency_key == "withdraw-reversal:" + self.withdraw_id)), 0)
        self.assertTrue(self.finish())
        self.assertEqual(self.f.balance(), 1000)

    def test_processor_recovers_processing_and_does_not_repeat(self):
        self.due()
        with patch.object(withdraw.config, "WITHDRAW_DEMO_OUTCOME", "failed"):
            self.assertEqual(withdraw.process_due_withdrawals(self.f.sessions), 1)
            self.assertEqual(withdraw.process_due_withdrawals(self.f.sessions), 0)
        self.assertEqual(self.f.balance(), 1000)

    def test_invalid_outcome_and_empty_reason_do_not_move_funds(self):
        self.due()
        with self.f.sessions() as db:
            for outcome, reason in [("unknown", "x"), ("failed", " ")]:
                with self.assertRaises(ValueError):
                    withdraw.finish_withdrawal(db, self.withdraw_id, outcome=outcome, reason=reason)
        self.assertEqual(self.f.balance(), 500)


class RechargeModeTests(unittest.TestCase):
    def test_production_blocks_confirm_and_preserves_pending_order(self):
        f = test_wallet.WalletTests()
        with patch.dict("os.environ", {"CAMPUS_MODE": "production"}):
            f.setUp()  # 正式模式配置 + 受控身份替身；不接短信或真实资金。
        try:
            order = f.recharge(100).json()
            response = f.confirm(order["rechargeId"])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "NOT_FOUND")
            self.assertEqual(f.balance(), 0)
            with f.sessions() as db:
                self.assertEqual(db.get(RechargeOrder, order["rechargeId"]).status, "pending")
                self.assertEqual(db.scalar(select(func.count()).select_from(Ledger)), 0)
        finally:
            f.tearDown()

    def test_mode_cannot_be_changed_by_request_or_runtime_environment(self):
        f = test_wallet.WalletTests()
        with patch.dict("os.environ", {"CAMPUS_MODE": "production"}):
            f.setUp()
        try:
            order = f.recharge(100).json()
            # 运行环境已还原为 demo，但启动时固定的 production 仍生效。
            response = f.client.post(f"/api/wallet/recharge/{order['rechargeId']}/confirm?mode=demo",
                headers={**f.headers(key="controlled-mode-key"), "X-Demo-Mode": "true"})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(f.balance(), 0)
        finally:
            f.tearDown()

    def test_closed_failed_or_non_mock_recharge_cannot_credit(self):
        f = test_wallet.WalletTests()
        f.setUp()
        try:
            for status, channel in [("closed", "mock"), ("failed", "mock"), ("pending", "alipay_sandbox")]:
                order = f.recharge(100).json()
                with f.sessions.begin() as db:
                    row = db.get(RechargeOrder, order["rechargeId"])
                    row.status, row.channel = status, channel
                response = f.confirm(order["rechargeId"])
                self.assertEqual(response.status_code, 409)
                self.assertEqual(f.balance(), 0)
                with f.sessions() as db:
                    self.assertEqual(db.get(RechargeOrder, order["rechargeId"]).status, status)
                    self.assertEqual(db.scalar(select(func.count()).select_from(Ledger)), 0)
        finally:
            f.tearDown()

    def test_demo_remains_available_and_service_default_denies(self):
        f = test_wallet.WalletTests()
        with patch.dict("os.environ", {"CAMPUS_MODE": "demo"}):
            f.setUp()
        try:
            order = f.recharge(100).json()
            from fastapi import HTTPException
            with f.sessions() as db, self.assertRaises(HTTPException) as exc:
                recharge.handle_confirm(db, "alice", order["rechargeId"], "direct-service-key")
            self.assertEqual(exc.exception.status_code, 404)
            self.assertEqual(f.confirm(order["rechargeId"]).status_code, 200)
            self.assertEqual(f.balance(), 100)
        finally:
            f.tearDown()
