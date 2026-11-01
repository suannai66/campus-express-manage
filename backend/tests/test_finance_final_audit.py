"""最终复查：非法内部金额、模糊业务标识、时间过滤和多请求竞争。"""
import unittest
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from sqlalchemy import select, func
import test_wallet
from app.modules.finance.core import wallet_core
from app.modules.finance.schemas import RechargeRequest, WithdrawRequest
from app.modules.finance.services import recharge, withdraw
from app.modules.finance.models import Account, Ledger, WithdrawOrder


class FinanceFinalAuditTests(unittest.TestCase):
    def setUp(self):
        self.f = test_wallet.WalletTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_internal_credit_debit_reject_invalid_amount_before_database_write(self):
        for operation in (wallet_core.credit, wallet_core.debit, wallet_core.freeze):
            for bad in (True, False, 0, -100, 100.0, "100"):
                with self.subTest(operation=operation.__name__, bad=bad):
                    with self.f.sessions.begin() as db:
                        with self.assertRaises(ValueError):
                            if operation is wallet_core.freeze:
                                operation(db, "alice", bad, "audit")
                            else:
                                operation(db, "alice", bad, "audit", "recharge")
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Account)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger)), 0)

    def test_opaque_uid_key_pairs_are_unambiguous_and_scoped(self):
        # 两对 uid/key 在旧派生方式下都得到 "alice:scope:12345678"。
        with self.f.sessions() as db:
            first = recharge.create_recharge(db, "alice", RechargeRequest(amount=100), "scope:12345678")
            second = recharge.create_recharge(db, "alice:scope", RechargeRequest(amount=100), "12345678")
        self.assertNotEqual(first["rechargeId"], second["rechargeId"])
        with self.f.sessions.begin() as db:
            for uid in ("alice", "alice:scope"):
                wallet_core.credit(db, uid, 1000, "seed-" + uid, "recharge")
        with self.f.sessions() as db:
            first = withdraw.apply_withdraw(db, "alice", WithdrawRequest(amount=100), "scope:12345678")
            second = withdraw.apply_withdraw(db, "alice:scope", WithdrawRequest(amount=200), "12345678")
        self.assertNotEqual(first["withdrawId"], second["withdrawId"])
        with self.f.sessions() as db:
            self.assertEqual(db.get(Account, "alice").available_cent, 900)
            self.assertEqual(db.get(Account, "alice:scope").available_cent, 800)

    def test_legacy_idempotency_results_keep_original_resource_ids(self):
        import hashlib
        from app.common import remember
        from app.modules.finance.models import RechargeOrder
        key = "legacy-resource-key"
        old_digest = hashlib.sha256(f"alice:{key}".encode()).hexdigest()[:16]
        recharge_result = {"rechargeId": "RC" + old_digest, "amount": 100, "status": "pending", "demo": True}
        withdrawal_result = {"withdrawId": "WD" + old_digest, "amount": 100, "status": "processing"}
        with self.f.sessions.begin() as db:
            db.add(RechargeOrder(out_trade_no=recharge_result["rechargeId"], uid="alice", amount_cent=100, channel="mock"))
            db.add(WithdrawOrder(withdraw_no=withdrawal_result["withdrawId"], uid="alice", amount_cent=100))
            remember(db, "alice", recharge.OPERATION, key, {"amount": 100}, recharge_result)
            remember(db, "alice", withdraw.OPERATION, key, {"amount": 100}, withdrawal_result)
        with self.f.sessions() as db:
            self.assertEqual(recharge.create_recharge(db, "alice", RechargeRequest(amount=100), key), recharge_result)
            self.assertEqual(withdraw.apply_withdraw(db, "alice", WithdrawRequest(amount=100), key), withdrawal_result)
        self.assertEqual(self.f.confirm(recharge_result["rechargeId"]).status_code, 200)
        self.assertEqual(self.f.balance(), 100)

    def test_date_filter_range_errors(self):
        for query in ("start=2026-11-02&end=2026-11-01", "start=not-a-date", "end=2026-02-30"):
            response = self.f.client.get("/api/wallet/transactions?" + query, headers=self.f.headers())
            self.assertEqual(response.status_code, 422, query)
            self.assertEqual(response.json()["code"], "VALIDATION_ERROR")

    def test_many_concurrent_withdrawals_conserve_money_and_never_overdraw(self):
        self.f.fund(1000)
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.f.withdraw(100), range(16)))
        self.assertEqual(sum(r.status_code == 201 for r in responses), 10)
        self.assertEqual(sum(r.status_code == 422 for r in responses), 6)
        self.assertEqual(self.f.balance(), 0)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(WithdrawOrder)), 10)
            self.assertEqual(db.scalar(select(func.sum(Ledger.delta))), 0)

    def test_same_key_concurrent_withdraw_retries_deduct_once(self):
        self.f.fund(1000)
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: self.f.withdraw(100, key="same-key-audit"), range(12)))
        self.assertTrue(all(r.status_code in (201, 409) for r in responses), [r.text for r in responses])
        self.assertEqual(self.f.withdraw(100, key="same-key-audit").status_code, 201)
        self.assertEqual(self.f.balance(), 900)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(WithdrawOrder)), 1)

    def test_production_blocks_already_succeeded_confirm_replay(self):
        import app.main as main
        from unittest.mock import patch
        order = self.f.recharge(100).json()
        self.assertEqual(self.f.confirm(order["rechargeId"]).status_code, 200)
        with patch.object(main.app.state, "finance_mode", "production"):
            self.assertEqual(self.f.confirm(order["rechargeId"]).status_code, 404)
        self.assertEqual(self.f.balance(), 100)
