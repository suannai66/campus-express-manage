"""F3/F4 契约测试，使用临时 SQLite 和仅测试装配的依赖替身。"""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
import app.main as main
from app.common import iso, now
from app.database import get_db
from app.modules.orders.entities import Order
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import EventReceipt, handle
from fixtures import TestIdentity, TestPricing

class OrderTests(unittest.TestCase):
    def setUp(self):
        self.events_patch = patch("app.main.start_processor")
        self.events_patch.start()
        self.addCleanup(self.events_patch.stop)
        self.processor_patch = patch("app.modules.finance.services.withdraw.start_withdraw_processor")
        self.processor_patch.start()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite+pysqlite:///{self.temp.name}/orders.db", connect_args={"check_same_thread": False})
        self.sessions = sessionmaker(bind=self.engine)
        self.engine_patch = patch.object(main, "engine", self.engine)
        self.engine_patch.start()
        def session_dependency():
            with self.sessions() as session: yield session
        main.app.dependency_overrides[get_db] = session_dependency
        main.app.state.identity_service, main.app.state.pricing_service = TestIdentity(), TestPricing()
        self.client = TestClient(main.app).__enter__()
        self.body = {"company": "中通快递", "code": "1-2-3456", "stationId": "station_cainiao", "deliveryAreaId": "zone_qinyuan", "size": "small", "weight": "1.2", "address": "沁园3栋302", "tip": 235, "expectedAt": iso(now() + timedelta(hours=2)), "note": "轻拿轻放"}
    def tearDown(self):
        self.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for name in ["identity_service", "pricing_service"]:
            if hasattr(main.app.state, name): delattr(main.app.state, name)
        self.engine_patch.stop(); self.engine.dispose(); self.temp.cleanup()
        self.processor_patch.stop()
    def headers(self, uid="alice", key=None):
        return {"Authorization": "Bearer " + uid, "Idempotency-Key": key or str(uuid4())}
    def create(self, body=None, uid="alice", key=None):
        return self.client.post("/api/orders", json=self.body if body is None else body, headers=self.headers(uid, key))
    def get(self, path, uid="alice"):
        return self.client.get(path, headers=self.headers(uid))
    def reserve(self, order, key=None):
        return self.client.post(f"/api/orders/{order['orderId']}/payment-request", json={"version": order["version"]}, headers=self.headers(key=key))
    def event(self, order, reservation, kind="payment.succeeded", **extra):
        payload = {"paymentId": str(uuid4()), "paymentRequestId": reservation["paymentRequestId"], "payerUid": "alice", "amount": order["amount"], **extra}
        return {"eventId": str(uuid4()), "type": kind, "occurredAt": iso(now()), "orderId": order["orderId"], "aggregateType": "payment", "aggregateId": payload["paymentId"], "version": 1, "payload": payload}
    def consume(self, event):
        with self.sessions() as db:
            result = handle(db, event); db.commit(); return result
    def paid(self, body=None):
        order = self.create(body).json()
        event = self.event(order, self.reserve(order).json())
        self.consume(event)
        return self.get(f"/api/orders/{order['orderId']}").json(), event
    def test_creation_snapshot(self):
        response = self.create(); self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual((order["status"], order["paymentStatus"], order["version"]), ("pending_payment", "unpaid", 1))
        self.assertEqual((order["baseFee"], order["tip"], order["amount"]), (300, 235, 535))
        self.assertTrue(order["expectedAt"].endswith("Z")); self.assertTrue(order["createdAt"].endswith("Z"))
        self.assertIsNone(order["paymentRequestId"])
        with self.sessions() as db: self.assertEqual(db.get(Order, order["orderId"]).commission_bps, 1000)
    def test_quote_contract(self):
        result = self.client.post("/api/orders/quote", json=self.body, headers=self.headers()).json()
        self.assertEqual(set(result), {"quoteId", "pricingVersion", "baseFee", "tip", "amount", "commissionRateBps", "expiresAt", "demo"})
        self.assertTrue(result["expiresAt"].endswith("Z"))
    def test_directory_public(self):
        result = self.client.get("/api/orders/locations").json()
        self.assertEqual((len(result["stations"]), len(result["deliveryAreas"])), (2, 3))
    def test_required_fields_trim(self):
        for field in ["company", "code", "address", "stationId", "deliveryAreaId"]:
            response = self.create({**self.body, field: "  "})
            self.assertEqual(response.status_code, 422); self.assertIn(field, response.json()["fields"])
        self.assertEqual(self.create({**self.body, "company": " 中通 "}).json()["company"], "中通")
    def test_integer_money(self):
        for value in ["235", 2.35, 235.0, True, -1, 99901]:
            with self.subTest(value=value): self.assertEqual(self.create({**self.body, "tip": value}).status_code, 422)
        self.assertEqual(self.create({**self.body, "tip": 0}).status_code, 201)
    def test_weight_string(self):
        for value in [1.2, True, "0", "30.01", "NaN", "1.001", "1e1"]:
            self.assertEqual(self.create({**self.body, "weight": value}).status_code, 422)
    def test_unknown_input(self):
        for key in ["uid", "amount", "status", "station"]:
            self.assertEqual(self.create({**self.body, key: "x"}).status_code, 422)
    def test_delivery_time(self):
        for value in [iso(now() - timedelta(seconds=1)), iso(now() + timedelta(days=8)), "2030-01-01T12:00"]:
            self.assertEqual(self.create({**self.body, "expectedAt": value}).status_code, 422)
    def test_delivery_time_requires_iso_string_before_coercion(self):
        future = now() + timedelta(hours=2)
        seconds = int(future.timestamp())
        for value in [seconds, seconds * 1000, seconds + 0.5, str(seconds), str(seconds * 1000),
                      True, None, future.replace(tzinfo=None).isoformat(), future.date().isoformat()]:
            for path in ["/api/orders", "/api/orders/quote"]:
                with self.subTest(path=path, value=value):
                    response = self.client.post(path, json={**self.body, "expectedAt": value}, headers=self.headers())
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
                    self.assertIn("expectedAt", response.json()["fields"])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Order)), 0)

    def test_delivery_time_accepts_iso_offsets_and_normalizes_utc(self):
        from datetime import timezone
        future = now() + timedelta(hours=2)
        for value in [iso(future), future.astimezone(timezone(timedelta(hours=8))).isoformat()]:
            draft = {**self.body, "expectedAt": value}
            quote = self.client.post("/api/orders/quote", json=draft, headers=self.headers())
            self.assertEqual(quote.status_code, 200, quote.text)
            response = self.create(draft)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["expectedAt"], iso(future))

    def test_all_order_endpoints_reject_undeclared_query_fields(self):
        order = self.create().json()
        cases = [
            ("GET", "/api/orders/locations", None),
            ("GET", "/api/orders", None),
            ("GET", f"/api/orders/{order['orderId']}", None),
            ("POST", "/api/orders/quote", self.body),
            ("POST", "/api/orders", self.body),
            ("POST", f"/api/orders/{order['orderId']}/payment-request", {"version": 1}),
        ]
        for method, path, body in cases:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path + "?unexpected=1", json=body, headers=self.headers())
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["code"], "VALIDATION_ERROR")
        self.assertEqual(self.client.get("/api/orders/locations").status_code, 200)
        self.assertEqual(self.client.get("/api/orders/locations?unexpected=1").status_code, 422)
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["version"], 1)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Order)), 1)

    def test_identity_admission(self):
        self.assertEqual(self.client.get("/api/orders").status_code, 401)
        self.assertEqual(self.create(uid="unverified").json()["code"], "VERIFICATION_REQUIRED")
        self.assertEqual(self.get("/api/orders", "unverified").status_code, 200)
    def test_missing_identity_dependency(self):
        del main.app.state.identity_service
        self.assertEqual(self.get("/api/orders").status_code, 503)
    def test_missing_pricing_dependency(self):
        del main.app.state.pricing_service
        self.assertEqual(self.create().status_code, 503)
    def test_invalid_quote(self):
        with patch.object(main.app.state.pricing_service, "quote", return_value={"amount": 1}):
            self.assertEqual(self.create().status_code, 503)
        with self.sessions() as db: self.assertEqual(db.scalar(select(func.count()).select_from(Order)), 0)
    def test_create_requotes(self):
        original = main.app.state.pricing_service.quote
        def changed(draft):
            result = original(draft); result.update(baseFee=1000, amount=1000 + draft.tip, pricingVersion="changed"); return result
        self.client.post("/api/orders/quote", json=self.body, headers=self.headers())
        with patch.object(main.app.state.pricing_service, "quote", side_effect=changed):
            self.assertEqual(self.create().json()["amount"], 1235)
    def test_creation_idempotency(self):
        key = str(uuid4()); first, second = self.create(key=key), self.create(key=key)
        self.assertEqual((first.status_code, second.status_code), (201, 201)); self.assertEqual(first.json(), second.json())
        self.assertEqual(self.create({**self.body, "tip": 1}, key=key).json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertNotEqual(self.create(uid="bob", key=key).json()["orderId"], first.json()["orderId"])
    def test_replay_after_expiry(self):
        key = str(uuid4()); first = self.create(key=key)
        with patch("app.modules.orders.api.now", return_value=now() + timedelta(days=2)):
            self.assertEqual(self.create(key=key).json(), first.json())
    def test_public_summary_private_detail(self):
        order, _ = self.paid()
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}", "bob").status_code, 404)
        for scope, uid in [("hall", "bob"), ("mine", "alice")]:
            row = self.get(f"/api/orders?scope={scope}", uid).json()["items"][0]
            for key in ["publisherUid", "courierUid", "paymentRequestId", "code", "address"]: self.assertNotIn(key, row)
    def test_hall_visibility(self):
        self.create(); order, _ = self.paid()
        self.assertEqual(self.get("/api/orders").json()["total"], 0)
        self.assertEqual(self.get("/api/orders", "bob").json()["total"], 1)
        with self.sessions() as db:
            item = OrderGateway.get_snapshot(db, order["orderId"])
            OrderGateway.transition(db, item, item.version, "accept", "bob", status="accepted", courier_uid="bob"); db.commit()
        self.assertEqual(self.get("/api/orders", "bob").json()["total"], 0)
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}", "bob").json()["code"], self.body["code"])
        self.assertEqual(self.get("/api/orders?scope=mine&role=courier", "bob").json()["total"], 1)
    def test_combined_inclusive_filters(self):
        order, _ = self.paid()
        path = "/api/orders?stationId=station_cainiao&deliveryAreaId=zone_qinyuan&tipMin=235&tipMax=235"
        self.assertEqual(self.get(path, "bob").json()["total"], 1)
        self.assertEqual(self.get(path + "&expectedFrom=" + order["expectedAt"] + "&expectedTo=" + order["expectedAt"], "bob").json()["total"], 1)
        self.assertEqual(self.get(path.replace("zone_qinyuan", "zone_public"), "bob").json()["total"], 0)
    def test_hall_hides_at_deadline_but_preserves_owner_history(self):
        deadline = now() + timedelta(hours=1)
        order, _ = self.paid({**self.body, "expectedAt": iso(deadline)})
        for moment, expected in [(deadline - timedelta(microseconds=1), 1), (deadline, 0),
                                 (deadline + timedelta(hours=1), 0)]:
            with self.subTest(moment=moment), patch("app.modules.orders.api.now", return_value=moment):
                self.assertEqual(self.get("/api/orders", "bob").json()["total"], expected)
                self.assertEqual(self.get("/api/orders?scope=mine").json()["total"], 1)
                latest = self.get(f"/api/orders/{order['orderId']}").json()
                self.assertEqual((latest["status"], latest["paymentStatus"], latest["version"]),
                                 ("pending", "paid", order["version"]))

    def test_hall_deadline_applies_before_total_filters_and_pagination(self):
        deadline = now() + timedelta(hours=1)
        for index in range(22):
            self.paid({**self.body, "expectedAt": iso(deadline), "note": str(index)})
        future, _ = self.paid({**self.body, "expectedAt": iso(deadline + timedelta(hours=1))})
        zero, _ = self.paid({**self.body, "expectedAt": iso(deadline + timedelta(hours=2)), "tip": 0})
        with patch("app.modules.orders.api.now", return_value=deadline):
            result = self.get("/api/orders", "bob").json()
            self.assertEqual((result["total"], result["pageSize"]), (2, 20))
            self.assertEqual([row["orderId"] for row in result["items"]], [future["orderId"], zero["orderId"]])
            self.assertEqual(self.get("/api/orders?page=2", "bob").json()["items"], [])
            self.assertEqual(self.get("/api/orders?tipMin=235", "bob").json()["total"], 1)
            self.assertEqual(self.get("/api/orders?scope=mine").json()["total"], 24)
    def test_filter_errors(self):
        for query in ["tipMin=2&tipMax=1", "tipMin=2.5", "tipMax=99901", "status=accepted", "expectedFrom=2026-01-01T12:00", "stationId=unknown", "address=302", "pageSize=101", "page=0"]:
            self.assertEqual(self.get("/api/orders?" + query).status_code, 422, query)
    def test_pagination_20_100(self):
        for index in range(22): self.create({**self.body, "note": str(index)})
        result = self.get("/api/orders?scope=mine").json()
        self.assertEqual((len(result["items"]), result["pageSize"], result["total"]), (20, 20, 22))
        self.assertEqual(len(self.get("/api/orders?scope=mine&page=2").json()["items"]), 2)
        self.assertEqual(len(self.get("/api/orders?scope=mine&pageSize=100").json()["items"]), 22)
    def test_reservation_recovery_and_version(self):
        order = self.create().json(); key = str(uuid4()); value = self.reserve(order, key).json()
        self.assertEqual((value["paymentStatus"], value["version"]), ("paying", 2))
        self.assertEqual(self.reserve(order, key).json(), value); self.assertEqual(self.reserve(order).status_code, 409)
        self.assertEqual(self.reserve({**order, "version": 2}).json()["paymentRequestId"], value["paymentRequestId"])
        self.assertEqual(self.client.post(f"/api/orders/{order['orderId']}/payment-request", json={"version": 2}, headers=self.headers("bob")).status_code, 404)
    def test_payment_event_deduplication(self):
        order = self.create().json(); event = self.event(order, self.reserve(order).json())
        first = self.consume(event); self.assertEqual(self.consume(event), first)
        self.consume({**event, "eventId": str(uuid4())})
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["version"], 3)
        with self.assertRaises(HTTPException): self.consume({**event, "payload": {**event["payload"], "amount": 1}})
    def test_payment_payload_validation(self):
        for changes in [{"payerUid": "bob"}, {"amount": 1}, {"paymentRequestId": "unknown"}]:
            order = self.create().json(); event = self.event(order, self.reserve(order).json(), **changes)
            with self.assertRaises(HTTPException): self.consume(event)
            self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["paymentStatus"], "paying")
    def test_failure_old_event_cannot_release_new_request(self):
        order = self.create().json(); first = self.reserve(order).json()
        event = self.event(order, first, "payment.failed", code="INSUFFICIENT_BALANCE"); self.consume(event)
        latest = self.get(f"/api/orders/{order['orderId']}").json()
        self.assertEqual(latest["paymentStatus"], "unpaid")
        self.assertNotEqual(first["paymentRequestId"], self.reserve(latest).json()["paymentRequestId"])
        self.consume({**event, "eventId": str(uuid4())})
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["paymentStatus"], "paying")
    def test_consumer_atomic_rollback(self):
        order = self.create().json(); event = self.event(order, self.reserve(order).json())
        with self.sessions() as db: handle(db, event); db.rollback()
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["paymentStatus"], "paying")
        self.consume(event)
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["paymentStatus"], "paid")
    def test_paying_blocks_cancellation(self):
        order = self.create().json(); self.reserve(order)
        with self.sessions() as db:
            item = OrderGateway.get_snapshot(db, order["orderId"])
            with self.assertRaises(HTTPException) as caught:
                OrderGateway.transition(db, item, item.version, "cancel", "alice", status="cancelled", refund_status="none")
            self.assertEqual(caught.exception.detail["code"], "PAYMENT_IN_PROGRESS")
    def test_refund_is_separate_fact(self):
        order, event = self.paid()
        with self.sessions() as db:
            item = OrderGateway.get_snapshot(db, order["orderId"])
            OrderGateway.transition(db, item, item.version, "cancel", "alice", status="cancelled", refund_status="processing"); db.commit()
        event.update(eventId=str(uuid4()), type="refund.succeeded", aggregateType="refund", aggregateId="refund-1")
        event["payload"] = {"refundId": "refund-1", "paymentId": event["payload"]["paymentId"], "payerUid": "alice", "amount": order["amount"]}
        self.consume(event); self.consume({**event, "eventId": str(uuid4())})
        latest = self.get(f"/api/orders/{order['orderId']}").json()
        self.assertEqual((latest["paymentStatus"], latest["refundStatus"]), ("paid", "succeeded"))
        self.assertEqual(self.get("/api/orders", "bob").json()["total"], 0)
    def test_immutable_snapshot_restricted_writes(self):
        order = self.create().json()
        with self.sessions() as db:
            item = OrderGateway.get_snapshot(db, order["orderId"])
            with self.assertRaises(AttributeError): item.amount = 1
            with self.assertRaises(HTTPException): OrderGateway.transition(db, item, item.version, "reserve", "alice", amount=1)
    def test_two_couriers_one_winner(self):
        order, _ = self.paid()
        with self.sessions() as db: snapshot = OrderGateway.get_snapshot(db, order["orderId"])
        def compete(actor):
            with self.sessions() as db:
                try:
                    OrderGateway.transition(db, snapshot, snapshot.version, "accept", actor, status="accepted", courier_uid=actor); db.commit(); return True
                except HTTPException: db.rollback(); return False
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sum(pool.map(compete, ["bob", "other"])), 1)
    def test_conflicting_payment_fact_rejected(self):
        order, event = self.paid()
        conflicting = {**event, "eventId": str(uuid4()), "type": "payment.failed", "payload": {**event["payload"], "code": "INSUFFICIENT_BALANCE"}}
        with self.assertRaises(HTTPException): self.consume(conflicting)
        altered_id = str(uuid4())
        with self.assertRaises(HTTPException):
            self.consume({**event, "eventId": str(uuid4()), "aggregateId": altered_id, "payload": {**event["payload"], "paymentId": altered_id}})
        self.assertEqual(self.get(f"/api/orders/{order['orderId']}").json()["paymentStatus"], "paid")

    def test_payment_reservation_races_cancellation(self):
        order = self.create().json()
        with self.sessions() as db: snapshot = OrderGateway.get_snapshot(db, order["orderId"])
        def compete(operation):
            with self.sessions() as db:
                try:
                    changes = {"payment_status": "paying", "payment_request_id": str(uuid4()), "payer_uid": "alice"} if operation == "reserve" else {"status": "cancelled", "refund_status": "none"}
                    OrderGateway.transition(db, snapshot, snapshot.version, operation, "alice", **changes)
                    db.commit(); return True
                except HTTPException: db.rollback(); return False
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sum(pool.map(compete, ["reserve", "cancel"])), 1)
        latest = self.get(f"/api/orders/{order['orderId']}").json()
        self.assertIn((latest["status"], latest["paymentStatus"]), {("pending_payment", "paying"), ("cancelled", "unpaid")})

    def test_no_legacy_demo_http(self):
        for path in ["/api/orders/demo/session", "/api/orders/demo/seed-hall", "/api/orders/events/payment-succeeded"]:
            self.assertIn(self.client.post(path, json={}).status_code, {404, 405})

if __name__ == "__main__": unittest.main()
