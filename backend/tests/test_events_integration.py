"""真实资金/订单消费者联调；C 动作仅在测试内通过受控网关模拟。"""
import copy
import threading
import time
import unittest
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import delete, func, select, update
from app.common import iso, now
from app.events import publish
from app.events.models import Delivery, OutboxEvent
from app.events.service import Dispatcher, start_processor
from app.events.wiring import register_defaults
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import EventReceipt, handle
from app.modules.finance.models import Account, FinanceReceipt, Ledger, Payment, Refund, Settlement
import test_finance_payment


class EventIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture
        self.dispatcher = Dispatcher(self.fixture.sessions)
        register_defaults()

    def paid_order(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        self.dispatcher.dispatch_once()
        return body, payment

    def order(self, order_id):
        with self.fixture.sessions() as db:
            return OrderGateway.get_snapshot(db, order_id)

    def action(self, order_id, cancelled):
        with self.fixture.sessions.begin() as db:
            order = OrderGateway.get_snapshot(db, order_id)
            if cancelled:
                order = OrderGateway.transition(db, order, order.version, "cancel", "alice",
                    status="cancelled", refund_status="processing")
                payload = {"publisherUid": "alice", "paymentId": order.payment_id,
                    "amount": order.amount, "paid": True, "orderVersion": order.version}
            else:
                order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
                for status in ("picking_up", "delivering", "delivered"):
                    order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=status)
                payload = {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                    "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                    "pricingVersion": order.pricing_version, "orderVersion": order.version}
            event = {"eventId": str(uuid4()), "type": "order.cancelled" if cancelled else "order.completed",
                "occurredAt": iso(now()), "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                "version": order.version, "payload": payload}
            publish(db, event)
        return event

    def retry_now(self, event_id, consumer):
        with self.fixture.sessions.begin() as db:
            db.execute(update(Delivery).where(Delivery.event_id == event_id,
                Delivery.consumer == consumer).values(next_attempt_at=0))

    def test_payment_success_and_failure_automatically_update_orders_without_refreezing(self):
        body = self.helper.order()
        failed = self.helper.pay(body).json()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paying")
        self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual(self.order(body["orderId"]).payment_status, "unpaid")
        self.helper.fund()
        order = self.fixture.get("/api/orders/" + body["orderId"]).json()
        reserved = self.fixture.reserve(order).json()
        success_body = {"orderId": order["orderId"], "paymentRequestId": reserved["paymentRequestId"]}
        success = self.helper.pay(success_body).json()
        self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual((self.order(order["orderId"]).status, self.order(order["orderId"]).payment_status), ("pending", "paid"))
        self.assertEqual(self.helper.pay(success_body).json(), success)
        self.assertEqual(self.helper.pay(body).json(), failed)
        self.assertEqual(self.helper.balances(), (465, 535))
        self.assertEqual(self.dispatcher.dispatch_once(), 0)

    def test_outbox_insert_failure_rolls_back_freeze_payment_ledger_and_http_dedup(self):
        self.helper.fund()
        body = self.helper.order()
        def interrupted(db, event):
            publish(db, event)
            raise RuntimeError("injected after outbox insert")
        with patch("app.modules.finance.services.payment.publish", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.helper.pay(body)
        self.assertEqual(self.helper.balances(), (1000, 0))
        with self.fixture.sessions() as db:
            for model in (OutboxEvent, Delivery, Payment):
                self.assertEqual(db.scalar(select(func.count()).select_from(model)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(Ledger.biz_type == "payment")), 0)
        self.assertEqual(self.helper.pay(body).json()["status"], "succeeded")

    def test_cancel_refund_event_and_order_confirmation_are_delivered_end_to_end(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], True)
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        order = self.order(body["orderId"])
        self.assertEqual((order.payment_status, order.refund_status), ("paid", "succeeded"))
        with self.fixture.sessions.begin() as db:
            publish(db, event)
            publish(db, {**event, "eventId": str(uuid4())})
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status != "succeeded")), 0)

    def test_refund_publish_failure_rolls_back_funds_receipt_and_downstream_outbox(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], True)
        def interrupted(db, data):
            publish(db, data)
            raise RuntimeError("injected before finance consumer ack")
        with patch("app.modules.finance.services.refund.publish", side_effect=interrupted):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(FinanceReceipt)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.type == "refund.succeeded")), 0)
            self.assertEqual(db.get(Delivery, (event["eventId"], "orders")).status, "succeeded")
        self.retry_now(event["eventId"], "finance")
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.order(body["orderId"]).refund_status, "succeeded")

    def test_order_consumer_failure_rolls_back_state_and_receipt_then_retries_same_payment(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        def interrupted(db, event):
            handle(db, event)
            raise RuntimeError("injected after orders receipt")
        with patch.dict("app.events.service._handlers", {("payment.succeeded", "orders"): interrupted}):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paying")
        with self.fixture.sessions() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            self.assertEqual(db.scalar(select(func.count()).select_from(EventReceipt)), 0)
        self.retry_now(event_id, "orders")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_completion_settles_once_while_missing_fulfillment_subscription_remains_pending(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], False)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            self.assertEqual(db.scalar(select(Settlement.commission)), 30)
            self.assertEqual(db.get(Delivery, (event["eventId"], "finance")).status, "succeeded")
            self.assertEqual(db.get(Delivery, (event["eventId"], "fulfillment")).status, "pending")
        self.retry_now(event["eventId"], "fulfillment")
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)
            self.assertEqual(db.get(Delivery, (event["eventId"], "finance")).attempts, 1)

    def test_legacy_payment_backfill_uses_original_id_and_marker_is_atomic(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery))
            db.execute(delete(OutboxEvent))
        with patch("app.events.service.publish", side_effect=RuntimeError("injected")):
            self.assertEqual(self.dispatcher.backfill_once(), 0)
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Payment, payment["paymentId"]).event_status, "pending")
        self.assertEqual(Dispatcher(self.fixture.sessions).backfill_once(), 1)
        self.assertEqual(self.dispatcher.backfill_once(), 0)
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(OutboxEvent.id)), event_id)
            self.assertEqual(db.get(Payment, payment["paymentId"]).event_status, "outbox_saved")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_legacy_refund_backfill_confirms_order_without_refunding_again(self):
        body, _ = self.paid_order()
        self.action(body["orderId"], True)
        # 先只消费取消的 finance 订阅，模拟旧版已退款但未向 B 投递。
        claim = None
        while True:
            current = self.dispatcher._claim(set())
            if current is None:
                break
            self.dispatcher._deliver(*current)
            if current[1] == "finance":
                claim = current
                break
        self.assertIsNotNone(claim)
        with self.fixture.sessions.begin() as db:
            row = db.scalar(select(Refund))
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery).where(Delivery.event_id == event_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.dispatcher.backfill_once(), 1)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).refund_status, "succeeded")
        self.assertEqual(self.helper.balances(), (1000, 0))

    def test_invalid_legacy_page_does_not_block_later_valid_events(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery).where(Delivery.event_id == event_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            for i in range(20):
                db.add(Payment(id=f"!invalid-{i:02}", order_id=f"bad-order-{i}", request_id=f"bad-request-{i}",
                    payer_uid="invalid-legacy", amount=1, status="failed", code="INVALID_LEGACY", funds_status="none", event={}))
        self.assertEqual(self.dispatcher.backfill_once(), 0)
        self.assertEqual(self.dispatcher.backfill_once(), 1)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_status_subscription_validates_facts_and_reads_latest_snapshot_for_old_versions(self):
        body, _ = self.paid_order()
        order = self.order(body["orderId"])
        with self.fixture.sessions.begin() as db:
            accepted = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            data = {"eventId": str(uuid4()), "type": "order.status_changed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": accepted.version,
                "payload": {"fromStatus": "pending", "status": "accepted", "courierUid": "bob", "orderVersion": accepted.version}}
            publish(db, data)
            latest = OrderGateway.transition(db, accepted, accepted.version, "fulfill", "bob", status="picking_up")
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            row = db.get(Delivery, (data["eventId"], "orders"))
            self.assertEqual(row.status, "succeeded")
            self.assertEqual(row.result["version"], latest.version)
            self.assertEqual(row.result["status"], "picking_up")
        future = copy.deepcopy(data)
        future["eventId"] = str(uuid4())
        future["version"] = future["payload"]["orderVersion"] = latest.version + 1
        with self.fixture.sessions.begin() as db:
            publish(db, future)
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            row = db.get(Delivery, (future["eventId"], "orders"))
            self.assertEqual(row.status, "pending")
            self.assertIn("ORDER_CONFLICT", row.last_error)


class RealIdentityWorkerTests(unittest.TestCase):
    def test_real_registration_verification_quote_payment_and_background_delivery(self):
        import test_verification
        import app.main as main
        from app.modules.finance.services.pricing import PricingService
        helper = test_verification.VerificationTests()
        helper.setUp()
        self.addCleanup(helper.tearDown)
        application = helper.submit().json()["applicationId"]
        self.assertEqual(helper.review(application).status_code, 200)
        main.app.state.pricing_service = PricingService()
        headers = lambda: {**helper.owner, "Idempotency-Key": str(uuid4())}
        recharge = helper.client.post("/api/wallet/recharge", json={"amount": 1000}, headers=headers())
        self.assertEqual(recharge.status_code, 201, recharge.text)
        confirmed = helper.client.post(f"/api/wallet/recharge/{recharge.json()['rechargeId']}/confirm", headers=headers())
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        draft = {"company": "中通快递", "code": "1-2-3456", "stationId": "station_cainiao", "deliveryAreaId": "zone_qinyuan",
            "size": "small", "weight": "1", "address": "测试楼101", "tip": 35, "expectedAt": iso(now() + timedelta(hours=2)), "note": ""}
        created = helper.client.post("/api/orders", json=draft, headers=headers())
        self.assertEqual(created.status_code, 201, created.text)
        order = created.json()
        reserved = helper.client.post(f"/api/orders/{order['orderId']}/payment-request", json={"version": order["version"]}, headers=headers())
        self.assertEqual(reserved.status_code, 200, reserved.text)
        paid = helper.client.post("/api/pay/prepay", json={"orderId": order["orderId"],
            "paymentRequestId": reserved.json()["paymentRequestId"]}, headers=headers())
        self.assertEqual(paid.status_code, 200, paid.text)
        processor = start_processor(helper.sessions)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                latest = helper.client.get(f"/api/orders/{order['orderId']}", headers=helper.owner).json()
                if latest["paymentStatus"] == "paid":
                    break
                threading.Event().wait(0.02)
            self.assertEqual((latest["status"], latest["paymentStatus"]), ("pending", "paid"))
            with helper.sessions() as db:
                account = db.get(Account, helper.uid)
                self.assertEqual((account.available_cent, account.frozen_cent), (765, 235))
        finally:
            processor.stop()
        self.assertFalse(processor.thread.is_alive())
