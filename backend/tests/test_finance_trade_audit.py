"""跨订单资金隔离、退款与结算争用及共享库升级验收。"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func, inspect
import test_finance_payment
from app.common import now, iso
from app.database import Base
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.finance.models import Account, Payment, Settlement, Refund, Ledger
from app.modules.finance.core import wallet_core
from app.modules.finance.services.event_handlers import on_order_completed, on_order_cancelled


class TradeAuditTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture

    def paid_order(self):
        body = self.helper.order()
        response = self.helper.pay(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "succeeded")
        payment_id = response.json()["paymentId"]
        with self.fixture.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
        return body["orderId"], payment_id

    def event(self, order_id, cancel):
        with self.fixture.sessions.begin() as db:
            order = OrderGateway.get_snapshot(db, order_id)
            if cancel:
                order = OrderGateway.transition(db, order, order.version, "cancel", "alice",
                    status="cancelled", refund_status="processing")
                payload = {"publisherUid": "alice", "paymentId": order.payment_id,
                           "amount": order.amount, "paid": True, "orderVersion": order.version}
            else:
                order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
                for state in ("picking_up", "delivering", "delivered"):
                    order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=state)
                payload = {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                           "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                           "pricingVersion": order.pricing_version, "orderVersion": order.version}
        return {"eventId": str(uuid4()), "type": "order.cancelled" if cancel else "order.completed",
                "occurredAt": iso(now()), "orderId": order.id, "aggregateType": "order",
                "aggregateId": order.id, "version": order.version, "payload": payload}

    def consume(self, event):
        with self.fixture.sessions.begin() as db:
            return (on_order_cancelled if event["type"] == "order.cancelled" else on_order_completed)(db, event)

    def test_multi_order_refund_and_settlement_leave_third_order_frozen(self):
        self.helper.fund(3000)
        orders = [self.paid_order() for _ in range(3)]
        cancel = self.event(orders[0][0], True)
        complete = self.event(orders[1][0], False)
        self.consume(cancel)
        self.assertEqual(self.helper.balances(), (1930, 1070))
        self.consume(complete)
        self.assertEqual(self.helper.balances(), (1930, 535))
        for event in (cancel, complete):
            self.consume(event)
            self.consume({**event, "eventId": str(uuid4())})
        with self.fixture.sessions() as db:
            self.assertEqual([db.get(Payment, payment_id).funds_status for _, payment_id in orders],
                             ["refunded", "settled", "frozen"])
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            balances = db.scalar(select(func.sum(Account.available_cent + Account.frozen_cent)))
            commissions = db.scalar(select(func.sum(Settlement.commission)))
            self.assertEqual(balances + commissions, 3000)
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)

    def test_payment_id_of_other_order_cannot_release_its_funds(self):
        self.helper.fund(2000)
        first, second = self.paid_order(), self.paid_order()
        event = self.event(first[0], True)
        event["payload"]["paymentId"] = second[1]
        with self.assertRaises(HTTPException):
            self.consume(event)
        self.assertEqual(self.helper.balances(), (930, 1070))

    def test_future_versions_rejected_without_moving_money(self):
        self.helper.fund(2000)
        for cancel in (True, False):
            order_id, _ = self.paid_order()
            event = self.event(order_id, cancel)
            future = copy.deepcopy(event)
            future["version"] += 100
            future["payload"]["orderVersion"] = future["version"]
            before = self.helper.balances()
            with self.assertRaises(HTTPException) as exc:
                self.consume(future)
            self.assertEqual(exc.exception.status_code, 409)
            self.assertEqual(self.helper.balances(), before)
            self.consume(event)

    def test_refund_and_settlement_compete_for_same_payment_at_core_boundary(self):
        # 订单层终态本身互斥；领域层再验证并发消费者也只能消耗一次。
        self.helper.fund(1000)
        _, payment_id = self.paid_order()
        barrier = Barrier(2)
        def compete(operation):
            try:
                with self.fixture.sessions.begin() as db:
                    payment = db.get(Payment, payment_id)
                    barrier.wait(timeout=10)
                    if operation == "refund":
                        wallet_core.release_payment(db, payment, "race-refund")
                    else:
                        wallet_core.settle_payment(db, payment, "bob", 505, "race-settle")
                return operation
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, ["refund", "settle"]))
        self.assertEqual(results.count("conflict"), 1)
        with self.fixture.sessions() as db:
            state = db.get(Payment, payment_id).funds_status
            self.assertIn(state, ("refunded", "settled"))
            self.assertEqual(db.get(Account, "alice").frozen_cent, 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(
                Ledger.biz_type.in_(["refund", "settlement"]))), 1)
            total = db.scalar(select(func.sum(Account.available_cent + Account.frozen_cent)))
            self.assertEqual(total + (30 if state == "settled" else 0), 1000)

    def test_old_shared_database_upgrade_preserves_all_existing_rows(self):
        from app.modules.finance.migrate_frozen import upgrade
        self.helper.fund(1000)
        self.fixture.create()
        from app.modules.identity.models import User, VerificationState, LoginSession
        with self.fixture.sessions.begin() as db:
            db.add(User(uid="audit-user", phone="13900009999", nickname="upgrade-test", role="student"))
            db.add(VerificationState(uid="audit-user", status="approved", application_id="audit-app", version=2))
            db.add(LoginSession(sid="audit-session", uid="audit-user", expires_at=2000000000, revoked=False))
        # 当前隔离库含订单/身份/钱包表；移除新表和冻结列，模拟本轮升级前的共享库。
        new_tables = [Settlement.__table__, Refund.__table__, Payment.__table__]
        with self.fixture.engine.begin() as db:
            for table in new_tables:
                table.drop(db)
            db.exec_driver_sql("ALTER TABLE account DROP COLUMN frozen_cent")
            tables = inspect(db).get_table_names()
            before = {name: db.exec_driver_sql('SELECT * FROM "' + name + '"').fetchall() for name in tables}
        self.assertTrue(upgrade(self.fixture.engine))
        Base.metadata.create_all(self.fixture.engine)
        self.assertFalse(upgrade(self.fixture.engine))
        with self.fixture.engine.connect() as db:
            for name, rows in before.items():
                query = "SELECT uid, available_cent, version, created_at FROM account" if name == "account" else 'SELECT * FROM "' + name + '"'
                self.assertEqual(db.exec_driver_sql(query).fetchall(), rows, name)
            self.assertEqual(db.exec_driver_sql("SELECT frozen_cent FROM account").scalar_one(), 0)
        # 升级后实际支付、退款，而非仅检查列存在。
        order_id, _ = self.paid_order()
        self.consume(self.event(order_id, True))
        self.assertEqual(self.helper.balances(), (1000, 0))
