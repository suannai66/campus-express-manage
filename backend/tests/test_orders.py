"""F3 API 测试：每例使用独立临时 SQLite，不写开发数据库。"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.database import Base, get_db
from app.modules.orders import integrations
from app.modules.orders.models import Order, OrderStatusReceipt, PaymentReceipt


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite+pysqlite:///{self.temp.name}/orders.db", connect_args={"check_same_thread": False})
        self.sessions = sessionmaker(bind=self.engine)
        self.environment = patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "demo"})
        self.environment.start()
        self.engine_patch = patch.object(main, "engine", self.engine)
        self.engine_patch.start()
        def session_dependency():
            with self.sessions() as session:
                yield session
        main.app.dependency_overrides[get_db] = session_dependency
        self.client = TestClient(main.app).__enter__()
        self.body = {"company": "中通快递", "code": "1-2-3456", "station": "菜鸟驿站", "size": "小件",
                     "weight": "1.2", "address": "图书馆正门", "tip": "2.35",
                     "expectedAt": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), "note": "轻拿轻放"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        self.engine_patch.stop()
        self.environment.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def create(self, body=None, key=None):
        return self.client.post("/api/orders", json=body or self.body, headers={"Idempotency-Key": key or str(uuid4())})

    def test_created_and_persisted_with_server_pricing(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.text)
        order = response.json()
        self.assertEqual(order["status"], "awaiting_payment")
        self.assertEqual(order["amountCents"], 535)
        with self.sessions() as db:
            self.assertEqual(db.get(Order, order["orderId"]).pickup_code, "1-2-3456")
        self.assertEqual(self.client.get(f'/api/orders/{order["orderId"]}').json()["amountCents"], 535)
        self.assertEqual(len(self.client.get("/api/orders/mine").json()["items"]), 1)

    def test_required_fields_and_whitespace(self):
        for key in ["company", "code", "station", "address"]:
            with self.subTest(key=key):
                self.assertEqual(self.create({**self.body, key: "   "}).status_code, 422)

    def test_general_addresses_and_legacy_order(self):
        for address in ["实验楼 A 座 302 室", "图书馆正门", "第一饭堂门口", "沁园3栋502室", "地" * 200]:
            response = self.create({**self.body, "address": address})
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["address"], address)
        self.assertEqual(self.create({**self.body, "address": "地" * 201}).status_code, 422)
        order = self.create().json()
        with self.sessions.begin() as db:
            stored = db.get(Order, order["orderId"])
            stored.address = "沁园3栋"
            stored.legacy_room = "502室"
        self.assertEqual(self.client.get(f'/api/orders/{order["orderId"]}').json()["address"], "沁园3栋 502室")

    def test_numeric_and_time_boundaries(self):
        for key, value in [("tip", "-1"), ("tip", "1.001"), ("tip", "NaN"), ("weight", "0"),
                           ("weight", "30.01"), ("weight", "NaN"), ("size", "超大件"),
                           ("expectedAt", "2020-01-01T00:00:00+08:00"),
                           ("expectedAt", (datetime.now(timezone.utc) + timedelta(days=8)).isoformat()),
                           ("expectedAt", "2030-01-01T12:00:00")]:
            with self.subTest(key=key, value=value):
                self.assertEqual(self.create({**self.body, key: value}).status_code, 422)

    def test_client_cannot_supply_price_or_state(self):
        for key in ["amountCents", "publisherUid", "status", "verified"]:
            self.assertEqual(self.create({**self.body, key: "fake"}).status_code, 422)

    def test_identity_and_verification_enforced_on_server(self):
        for state, expected in [("guest", 401), ("unverified", 403)]:
            self.client.post("/api/orders/demo/session", json={"state": state})
            self.assertEqual(self.create().status_code, expected)
            self.assertEqual(self.client.post("/api/orders/quote", json=self.body).status_code, expected)

    def test_idempotent_create_and_payload_conflict(self):
        key = str(uuid4())
        first = self.create(key=key).json()
        self.assertEqual(self.create(key=key).json()["orderId"], first["orderId"])
        self.assertEqual(self.create({**self.body, "tip": "5"}, key).status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Order)), 1)

    def test_payment_demo_is_explicit_and_idempotent(self):
        order = self.create().json()
        path = f'/api/orders/{order["orderId"]}'
        self.assertEqual(self.client.post(path + "/prepay").json()["mode"], "demo")
        self.assertEqual(self.client.get(path).json()["status"], "awaiting_payment")
        for _ in range(2):
            self.assertEqual(self.client.post(path + "/demo-pay").json()["status"], "pending")
        self.assertEqual(self.client.post(path + "/prepay").status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(PaymentReceipt)), 1)

    def test_order_ownership(self):
        order = self.create().json()
        main.app.dependency_overrides[integrations.current_identity] = lambda: integrations.Identity("other-user", "其他同学", True)
        for path, method in [("", "get"), ("/prepay", "post"), ("/demo-pay", "post")]:
            self.assertEqual(getattr(self.client, method)(f'/api/orders/{order["orderId"]}{path}').status_code, 403)
        self.assertEqual(self.client.get("/api/orders/mine").json()["items"], [])

    def test_missing_orders(self):
        self.assertEqual(self.client.get("/api/orders/missing").status_code, 404)

    def external_event_setup(self):
        order = self.create().json()
        with self.sessions.begin() as db:
            db.get(Order, order["orderId"]).pricing_source = "external"
        return {"eventId": "event-1", "paymentId": "payment-1", "orderId": order["orderId"],
                "uid": "demo-student-b", "amountCents": order["amountCents"]}

    def test_external_event_auth_amount_and_replay(self):
        event = self.external_event_setup()
        path = "/api/orders/events/payment-succeeded"
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external", "F3_PAYMENT_EVENT_SECRET": "test-secret"}):
            headers = {"X-Order-Event-Secret": "test-secret"}
            self.assertEqual(self.client.post(path, json=event).status_code, 403)
            for changed in [{"amountCents": 1}, {"uid": "wrong-user"}]:
                self.assertEqual(self.client.post(path, json={**event, **changed}, headers=headers).status_code, 409)
            self.assertEqual(self.client.post(path, json=event, headers=headers).json()["duplicate"], False)
            self.assertEqual(self.client.post(path, json=event, headers=headers).json()["duplicate"], True)
            self.assertEqual(self.client.post(path, json={**event, "amountCents": 1}, headers=headers).status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.get(Order, event["orderId"]).status, "pending")
            self.assertEqual(db.scalar(select(func.count()).select_from(PaymentReceipt)), 1)

    def test_external_mode_never_falls_back_to_demo(self):
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external", "F3_IDENTITY_BASE_URL": ""}):
            self.assertEqual(self.client.post("/api/orders/demo/session", json={"state": "verified"}).status_code, 404)
            self.assertEqual(self.client.get("/api/orders/integration-context").status_code, 503)
            self.assertEqual(self.create().status_code, 503)

    def test_payment_id_cannot_pay_two_orders_and_rolls_back(self):
        first = self.external_event_setup()
        second = self.external_event_setup()
        second.update(eventId="event-2", paymentId=first["paymentId"])
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external", "F3_PAYMENT_EVENT_SECRET": "test-secret"}):
            headers = {"X-Order-Event-Secret": "test-secret"}
            self.assertEqual(self.client.post("/api/orders/events/payment-succeeded", json=first, headers=headers).status_code, 200)
            self.assertEqual(self.client.post("/api/orders/events/payment-succeeded", json=second, headers=headers).status_code, 409)
        with self.sessions() as db:
            self.assertEqual(db.get(Order, second["orderId"]).status, "awaiting_payment")
            self.assertIsNone(db.get(PaymentReceipt, "event-2"))

    def test_external_adapter_contract(self):
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external"}):
            with patch.object(integrations, "remote_json", side_effect=[{"uid": "real-uid", "nickname": "同学"}, {"verified": True}, {"baseFeeCents": 650}]):
                result = self.create()
                self.assertEqual(result.status_code, 201, result.text)
                self.assertEqual(result.json()["publisherUid"], "real-uid")
                self.assertEqual(result.json()["amountCents"], 885)
                self.assertEqual(result.json()["pricingSource"], "external")

    def peer_order(self, **changes):
        order = self.create({**self.body, **changes}).json()
        self.client.post(f'/api/orders/{order["orderId"]}/demo-pay')
        with self.sessions.begin() as db:
            db.get(Order, order["orderId"]).publisher_uid = "peer-student"
        return order

    def test_hall_only_paid_pending_other_people_and_no_pickup_code(self):
        own = self.create().json()
        self.client.post(f'/api/orders/{own["orderId"]}/demo-pay')
        self.create()  # 未付款，不进入大厅
        peer = self.peer_order()
        hidden = self.peer_order()
        with self.sessions.begin() as db:
            db.get(Order, hidden["orderId"]).status = "accepted"
        response = self.client.get("/api/orders?status=pending").json()
        self.assertEqual(response["total"], 1)
        self.assertEqual(response["items"][0]["orderId"], peer["orderId"])
        self.assertNotIn("code", response["items"][0])
        self.assertNotIn("publisherUid", response["items"][0])
        detail = self.client.get(f'/api/orders/hall/{peer["orderId"]}').json()
        self.assertNotIn("code", detail)
        self.assertEqual(detail["address"], "图书馆正门")

    def test_hall_combined_filters_literal_address_and_tip_boundaries(self):
        target = self.peer_order(address="实验楼 A_区 100%门口", tip="5.00")
        self.peer_order(address="实验楼 AB区 100门口", tip="5.01")
        self.peer_order(address="图书馆正门", station="顺丰服务点", tip="9.00")
        params = {"station": "菜鸟驿站", "address": "_区 100%", "tipMinCents": 500, "tipMaxCents": 500,
                  "expectedFrom": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                  "expectedTo": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}
        response = self.client.get("/api/orders", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row["orderId"] for row in response.json()["items"]], [target["orderId"]])
        self.assertEqual(self.client.get("/api/orders", params={"address": "饭堂"}).json()["total"], 0)

    def test_hall_pagination_and_validation(self):
        for index in range(4):
            self.peer_order(address=f"实验楼{index}")
        first = self.client.get("/api/orders?pageSize=2&page=1").json()
        second = self.client.get("/api/orders?pageSize=2&page=2").json()
        self.assertEqual(first["total"], 4)
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(set(row["orderId"] for row in first["items"]).isdisjoint(row["orderId"] for row in second["items"]))
        for params in [{"tipMinCents": 501, "tipMaxCents": 500}, {"page": 0}, {"pageSize": 61},
                       {"status": "awaiting_payment"}, {"expectedFrom": "2026-01-01T12:00:00"},
                       {"expectedFrom": "2026-12-02T12:00:00Z", "expectedTo": "2026-12-01T12:00:00Z"}]:
            self.assertEqual(self.client.get("/api/orders", params=params).status_code, 422)

    def test_hall_auth_and_unavailable_task_detail(self):
        own = self.create().json()
        self.assertEqual(self.client.get(f'/api/orders/hall/{own["orderId"]}').status_code, 403)
        self.assertEqual(self.client.get("/api/orders/hall/missing").status_code, 404)
        peer = self.peer_order()
        with self.sessions.begin() as db:
            db.get(Order, peer["orderId"]).status = "cancelled"
        self.assertEqual(self.client.get(f'/api/orders/hall/{peer["orderId"]}').status_code, 409)
        self.client.post("/api/orders/demo/session", json={"state": "guest"})
        self.assertEqual(self.client.get("/api/orders").status_code, 401)

    def test_demo_hall_seed_is_persisted_idempotent_and_not_reopened(self):
        self.assertEqual(self.client.post("/api/orders/demo/seed-hall").json()["created"], 3)
        self.assertEqual(self.client.post("/api/orders/demo/seed-hall").json()["created"], 0)
        rows = self.client.get("/api/orders").json()["items"]
        self.assertEqual(len(rows), 3)
        for order, status in zip(rows[:2], ["accepted", "cancelled"]):
            self.assertEqual(self.client.post(f'/api/orders/demo/hall/{order["orderId"]}/status', json={"status": status}).status_code, 200)
        self.assertEqual(self.client.get("/api/orders").json()["total"], 1)
        self.client.post("/api/orders/demo/seed-hall")
        self.assertEqual(self.client.get("/api/orders").json()["total"], 1)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(OrderStatusReceipt)), 2)

    def test_status_event_auth_replay_out_of_order_and_terminal_state(self):
        order = self.peer_order()
        with self.sessions.begin() as db:
            db.get(Order, order["orderId"]).pricing_source = "external"
        event = {"eventId": "status-2", "orderId": order["orderId"], "version": 2, "status": "accepted"}
        path = "/api/orders/events/status-changed"
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external", "F4_STATUS_EVENT_SECRET": "status-secret"}):
            headers = {"X-Order-Status-Secret": "status-secret"}
            self.assertEqual(self.client.post(path, json=event).status_code, 403)
            self.assertEqual(self.client.post(path, json=event, headers=headers).json()["duplicate"], False)
            self.assertEqual(self.client.post(path, json=event, headers=headers).json()["duplicate"], True)
            self.assertEqual(self.client.post(path, json={**event, "status": "cancelled"}, headers=headers).status_code, 409)
            self.assertEqual(self.client.post(path, json={**event, "eventId": "other-id"}, headers=headers).status_code, 409)
            older = {**event, "eventId": "status-1", "version": 1, "status": "delivering"}
            self.assertEqual(self.client.post(path, json=older, headers=headers).json()["ignored"], True)
            with self.sessions() as db:
                self.assertEqual(db.get(Order, order["orderId"]).status, "accepted")
            terminal = {**event, "eventId": "status-3", "version": 3, "status": "cancelled"}
            self.assertEqual(self.client.post(path, json=terminal, headers=headers).status_code, 200)
            self.assertEqual(self.client.post(path, json={**terminal, "eventId": "status-4", "version": 4, "status": "delivered"}, headers=headers).status_code, 409)

    def test_hall_demo_endpoints_closed_in_external_mode_and_modes_isolated(self):
        order = self.peer_order()
        with self.sessions.begin() as db:
            db.get(Order, order["orderId"]).pricing_source = "external"
        self.assertEqual(self.client.get("/api/orders").json()["total"], 0)
        self.assertEqual(self.client.get(f'/api/orders/hall/{order["orderId"]}').status_code, 404)
        main.app.dependency_overrides[integrations.current_identity] = lambda: integrations.Identity("real-user", "同学", True)
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external"}):
            self.assertEqual(self.client.post("/api/orders/demo/seed-hall").status_code, 404)
            self.assertEqual(self.client.post(f'/api/orders/demo/hall/{order["orderId"]}/status', json={"status": "accepted"}).status_code, 404)

    def test_unpaid_order_cannot_accept_status_event(self):
        order = self.create().json()
        with self.sessions.begin() as db:
            db.get(Order, order["orderId"]).pricing_source = "external"
        with patch.dict(os.environ, {"F3_DEPENDENCY_MODE": "external", "F4_STATUS_EVENT_SECRET": "status-secret"}):
            result = self.client.post("/api/orders/events/status-changed", headers={"X-Order-Status-Secret": "status-secret"},
                                      json={"eventId": "unpaid-status", "orderId": order["orderId"], "version": 1, "status": "accepted"})
            self.assertEqual(result.status_code, 409)


if __name__ == "__main__":
    unittest.main()
