"""取消解冻共享事务、幂等、互斥和资金守恒测试。"""
import copy
import unittest
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from sqlalchemy import select, func
import test_finance_payment
from app.common import iso, now
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.finance.models import Payment, Refund, FinanceReceipt, Account, Ledger
from app.modules.finance.services.event_handlers import on_order_cancelled


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture

    def cancellation(self, paid=True):
        body = self.helper.order()
        payment_id = None
        if paid:
            self.helper.fund()
            payment_id = self.helper.pay(body).json()["paymentId"]
        with self.fixture.sessions.begin() as db:
            if paid:
                handle(db, db.get(Payment, payment_id).event)
            else:
                # 没有资金变动的确定失败先经 B 解开预占。
                pass
        if not paid:
            failed = self.helper.pay(body).json()["paymentId"]
            with self.fixture.sessions.begin() as db:
                handle(db, db.get(Payment, failed).event)
        with self.fixture.sessions.begin() as db:
            order = OrderGateway.get_snapshot(db, body["orderId"])
            order = OrderGateway.transition(db, order, order.version, "cancel", "alice",
                status="cancelled", refund_status="processing" if paid else "none")
        return {"eventId": str(uuid4()), "type": "order.cancelled", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                "version": order.version,
                "payload": {"publisherUid": "alice", "paymentId": payment_id,
                            "amount": 535, "paid": paid, "orderVersion": order.version}}

    def consume(self, event):
        with self.fixture.sessions.begin() as db:
            return on_order_cancelled(db, event)

    def test_refund_once_replay_new_event_and_order_notification(self):
        event = self.cancellation()
        first = self.consume(event)
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.consume(event), first)
        other = {**event, "eventId": str(uuid4())}
        self.assertEqual(self.consume(other), first)
        self.assertEqual(self.helper.balances(), (1000, 0))
        with self.fixture.sessions.begin() as db:
            row = db.get(Refund, first["refundId"])
            self.assertEqual(row.event_status, "pending")
            self.assertEqual(db.get(Payment, row.payment_id).funds_status, "refunded")
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            handle(db, row.event)
        order = self.fixture.get("/api/orders/" + event["orderId"]).json()
        self.assertEqual((order["paymentStatus"], order["refundStatus"]), ("paid", "succeeded"))
        self.assertEqual(self.consume(other), first)
        page = self.fixture.get("/api/wallet/transactions?type=refund").json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["orderId"], event["orderId"])

    def test_unpaid_cancellation_no_money_moves(self):
        event = self.cancellation(False)
        self.assertFalse(self.consume(event)["refunded"])
        self.assertEqual(self.helper.balances(), (0, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 0)

    def test_changed_event_and_invalid_amount_rejected(self):
        event = self.cancellation()
        self.consume(event)
        altered = copy.deepcopy(event)
        altered["payload"]["amount"] = 536
        with self.assertRaises(HTTPException) as error:
            self.consume(altered)
        self.assertEqual(error.exception.status_code, 409)
        altered["eventId"] = str(uuid4())
        with self.assertRaises(HTTPException):
            self.consume(altered)
        self.assertEqual(self.helper.balances(), (1000, 0))

    def test_settled_or_insufficient_frozen_cannot_refund(self):
        event = self.cancellation()
        with self.fixture.sessions.begin() as db:
            db.get(Payment, event["payload"]["paymentId"]).funds_status = "settled"
        with self.assertRaises(HTTPException):
            self.consume(event)
        with self.fixture.sessions.begin() as db:
            db.get(Payment, event["payload"]["paymentId"]).funds_status = "frozen"
            db.get(Account, "alice").frozen_cent = 0
        with self.assertRaises(HTTPException):
            self.consume(event)
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Payment, event["payload"]["paymentId"]).funds_status, "frozen")
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 0)

    def test_failure_after_release_rolls_back_and_can_retry(self):
        event = self.cancellation()
        from app.modules.finance.services import refund
        original = refund.release_payment
        def fail(*args):
            original(*args)
            raise RuntimeError("injected after refund ledger")
        with patch.object(refund, "release_payment", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.consume(event)
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Payment, event["payload"]["paymentId"]).funds_status, "frozen")
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(FinanceReceipt)), 0)
        self.consume(event)
        self.assertEqual(self.helper.balances(), (1000, 0))

    def test_caller_rollback_prevents_implicit_commit(self):
        event = self.cancellation()
        with self.fixture.sessions() as db:
            on_order_cancelled(db, event)
            db.rollback()
        self.assertEqual(self.helper.balances(), (465, 535))
        self.consume(event)
        self.assertEqual(self.helper.balances(), (1000, 0))

    def test_concurrent_new_event_ids_refund_once(self):
        event = self.cancellation()
        def consume_one(event_id):
            try:
                return self.consume({**event, "eventId": event_id})
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(consume_one, [str(uuid4()), str(uuid4())]))
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.consume(event)
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
