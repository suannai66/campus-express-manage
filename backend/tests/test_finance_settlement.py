"""结算金额守恒、快照费率、重复事件及退款互斥回归。"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func
import test_finance_payment
from app.common import iso, now
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.orders.entities import Order
from app.modules.finance.models import Account, Payment, Settlement, FinanceReceipt, Ledger
from app.modules.finance.services.event_handlers import on_order_completed
from app.modules.finance.core.fee_util import split_settlement


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture

    def completion(self):
        self.helper.fund()
        body = self.helper.order()
        payment_id = self.helper.pay(body).json()["paymentId"]
        with self.fixture.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
            order = OrderGateway.get_snapshot(db, body["orderId"])
            order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            for status in ("picking_up", "delivering", "delivered"):
                order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=status)
            order = OrderGateway.transition(db, order, order.version, "confirm_receipt", "alice", status="completed")
        return {"eventId": str(uuid4()), "type": "order.completed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                "version": order.version,
                "payload": {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                            "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                            "pricingVersion": order.pricing_version, "orderVersion": order.version}}

    def consume(self, event):
        with self.fixture.sessions.begin() as db:
            return on_order_completed(db, event)

    def assert_balances(self):
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            row = db.scalar(select(Settlement))
            self.assertEqual((row.amount, row.income, row.commission), (535, 505, 30))
            self.assertEqual(465 + 505 + row.commission, 1000)
            self.assertEqual(db.get(Payment, row.payment_id).funds_status, "settled")

    def test_settlement_once_and_ledger(self):
        event = self.completion()
        first = self.consume(event)
        self.assertEqual(self.consume(event), first)
        self.assertEqual(self.consume({**event, "eventId": str(uuid4())}), first)
        self.assert_balances()
        page = self.fixture.get("/api/wallet/transactions?type=settlement", "bob").json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["orderId"], event["orderId"])
        self.assertEqual(self.fixture.get("/api/wallet/transactions?type=settlement").json()["total"], 0)

    def test_uses_snapshot_not_current_rate(self):
        event = self.completion()
        with patch("app.modules.finance.config.COMMISSION_RATE_BPS", 9000):
            result = self.consume(event)
        self.assertEqual(result["commission"], 30)
        self.assert_balances()

    def test_rate_boundaries_and_floor(self):
        for amount, base, rate, expected in [(535, 300, 1000, (505, 30)),
                (101, 101, 1000, (91, 10)), (535, 300, 0, (535, 0)),
                (535, 300, 10000, (235, 300)), (300, 300, 10000, (0, 300))]:
            self.assertEqual(split_settlement(amount, base, rate), expected)

    def test_invalid_and_conflicting_events(self):
        event = self.completion()
        for field, bad in [("amount", True), ("commissionRateBps", "1000"), ("tip", 235.0)]:
            altered = copy.deepcopy(event)
            altered["payload"][field] = bad
            with self.assertRaises(HTTPException) as exc:
                self.consume(altered)
            self.assertEqual(exc.exception.status_code, 422)
        altered = copy.deepcopy(event)
        altered["payload"]["courierUid"] = "mallory"
        with self.assertRaises(HTTPException):
            self.consume(altered)
        self.consume(event)
        altered = copy.deepcopy(event)
        altered["payload"]["pricingVersion"] = "wrong"
        with self.assertRaises(HTTPException) as exc:
            self.consume(altered)
        self.assertEqual(exc.exception.status_code, 409)
        self.assert_balances()

    def test_refunded_funds_cannot_settle(self):
        event = self.completion()
        with self.fixture.sessions.begin() as db:
            db.scalar(select(Payment)).funds_status = "refunded"
        with self.assertRaises(HTTPException):
            self.consume(event)
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 0)

    def test_insufficient_frozen_rolls_payment_state_back(self):
        event = self.completion()
        with self.fixture.sessions.begin() as db:
            db.get(Account, "alice").frozen_cent = 100
        with self.assertRaises(HTTPException):
            self.consume(event)
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(Payment)).funds_status, "frozen")
            self.assertIsNone(db.get(Account, "bob"))

    def test_failure_after_income_rolls_everything_back(self):
        event = self.completion()
        from app.modules.finance.services import settlement
        original = settlement.settle_payment
        def fail(*args):
            original(*args)
            raise RuntimeError("injected after courier income")
        with patch.object(settlement, "settle_payment", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.consume(event)
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(Payment)).funds_status, "frozen")
            self.assertIsNone(db.get(Account, "bob"))
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(FinanceReceipt)), 0)
        self.consume(event)
        self.assert_balances()

    def test_caller_controls_commit(self):
        event = self.completion()
        with self.fixture.sessions() as db:
            on_order_completed(db, event)
            db.rollback()
        self.assertEqual(self.helper.balances(), (465, 535))
        self.consume(event)
        self.assert_balances()

    def test_concurrent_events_settle_once(self):
        event = self.completion()
        def consume_one(event_id):
            try:
                return self.consume({**event, "eventId": event_id})
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(consume_one, [str(uuid4()), str(uuid4())]))
        self.consume(event)
        self.assert_balances()
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)
