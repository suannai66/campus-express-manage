"""旧版完结语义升级：保留原事件、余额和新版待收货订单。"""
import copy
import unittest
from uuid import uuid4
from fastapi import HTTPException

from sqlalchemy import select, update

from app.common import iso, now
from app.events import publish
from app.events.models import Delivery, OutboxEvent
from app.events.service import Dispatcher
from app.modules.finance.models import Settlement
from app.modules.fulfillment.migrate_receipt import upgrade
from app.modules.fulfillment.models import ReviewOpening
from app.modules.orders.entities import Order
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.orders.projections import handle as refresh
import test_finance_payment


class ReceiptMigrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.fixture

    def delivered(self, legacy=False):
        self.helper.fund()
        body = self.helper.order()
        payment_id = self.helper.pay(body).json()["paymentId"]
        from app.modules.finance.models import Payment
        with self.f.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
            order = OrderGateway.get_snapshot(db, body["orderId"])
            order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            for state in ("picking_up", "delivering", "delivered"):
                order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=state)
            event = {"eventId": str(uuid4()), "type": "order.completed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": order.version,
                "payload": {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
                    "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
                    "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
                    "orderVersion": order.version}}
            if legacy:
                publish(db, self.status_event(order))
                publish(db, event)
        return order, event

    def status_event(self, order):
        return {"eventId": str(uuid4()), "type": "order.status_changed", "occurredAt": iso(now()),
            "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": order.version,
            "payload": {"fromStatus": "delivering", "status": "delivered",
                "courierUid": order.courier_uid, "orderVersion": order.version}}

    def test_preserves_waiting_orders_and_retries_old_completion_once(self):
        old, event = self.delivered(legacy=True)
        waiting, _ = self.delivered()
        before = self.helper.balances()
        with self.f.sessions() as db:
            old_status = db.scalar(select(OutboxEvent.body).where(OutboxEvent.order_id == old.id,
                OutboxEvent.type == "order.status_changed"))
        self.assertEqual(upgrade(self.f.engine), 1)
        self.assertEqual(upgrade(self.f.engine), 0)
        self.assertEqual(self.helper.balances(), before)
        with self.f.sessions() as db:
            migrated = OrderGateway.get_snapshot(db, old.id)
            self.assertEqual((migrated.status, migrated.version), ("completed", old.version))
            self.assertEqual(db.get(Order, waiting.id).status, "delivered")
            self.assertEqual(db.get(OutboxEvent, event["eventId"]).body, event)
        dispatcher = Dispatcher(self.f.sessions)
        dispatcher.dispatch_once()
        dispatcher.dispatch_once()
        with self.f.sessions() as db:
            self.assertEqual(len(list(db.scalars(select(Settlement)))), 1)
            self.assertIsNotNone(db.get(ReviewOpening, old.id))
            self.assertIsNone(db.get(ReviewOpening, waiting.id))
            delivery = db.get(Delivery, (old_status["eventId"], "orders"))
            self.assertEqual(delivery.status, "succeeded")
            self.assertEqual(delivery.result["status"], "completed")
            self.assertEqual(delivery.result["version"], old.version)
            self.assertEqual(db.get(OutboxEvent, old_status["eventId"]).body, old_status)

    def test_current_version_conflict_without_completion_is_still_rejected(self):
        order, _ = self.delivered()
        with self.f.sessions.begin() as db:
            db.execute(update(Order).where(Order.id == order.id).values(status="completed"))
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                refresh(db, self.status_event(order))
            self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")

    def test_legacy_compatibility_rejects_different_status_courier_and_completion_facts(self):
        order, completion = self.delivered(legacy=True)
        self.assertEqual(upgrade(self.f.engine), 1)
        for changes in ({"fromStatus": "accepted"}, {"status": "accepted"}, {"courierUid": "carol"}):
            event = self.status_event(order)
            event["payload"].update(changes)
            with self.f.sessions() as db:
                with self.assertRaises(HTTPException) as raised:
                    refresh(db, event)
                self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")
        changed = copy.deepcopy(completion)
        changed["payload"]["courierUid"] = "carol"
        from app.events.schema import validate
        _, digest = validate(changed)
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == completion["eventId"]).values(
                body=changed, digest=digest))
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                refresh(db, self.status_event(order))
            self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")

    def test_conflicting_history_rolls_back_all_changes(self):
        first, _ = self.delivered(legacy=True)
        second, event = self.delivered(legacy=True)
        altered = copy.deepcopy(event)
        altered["payload"]["courierUid"] = "carol"
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == event["eventId"]).values(body=altered))
        with self.assertRaises(ValueError):
            upgrade(self.f.engine)
        with self.f.sessions() as db:
            self.assertEqual([db.get(Order, item.id).status for item in (first, second)], ["delivered", "delivered"])

    def test_changed_completion_metadata_digest_rolls_back_all_changes(self):
        first, _ = self.delivered(legacy=True)
        second, event = self.delivered(legacy=True)
        altered = {**event, "occurredAt": "2020-01-01T00:00:00.000000Z"}
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == event["eventId"]).values(body=altered))
        with self.assertRaises(ValueError):
            upgrade(self.f.engine)
        with self.f.sessions() as db:
            self.assertEqual([db.get(Order, item.id).status for item in (first, second)], ["delivered", "delivered"])
