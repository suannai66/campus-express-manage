"""B 模块质量回归：隔离数据库、故障注入、权限及一致性断言。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event as sql_event, func, insert, select
from sqlalchemy.exc import OperationalError

import app.main as main
from app.common import Idempotency, iso, now
from app.modules.orders.entities import Order
from app.modules.orders.handlers import EventReceipt, PaymentFact, handle
from app.modules.orders.contract import OrderDraft
from test_orders import OrderTestCase


class OrderQualityTests(OrderTestCase):
    def count(self, model):
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def latest(self, order):
        response = self.get(f"/api/orders/{order['orderId']}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        body = response.json()
        self.assertEqual(set(body), {"code", "detail", "fields"})
        self.assertEqual(body["code"], code)
        self.assertIsInstance(body["detail"], str)
        self.assertIsInstance(body["fields"], dict)
        return body

    def test_q01_unauthenticated_endpoints_have_no_side_effects(self):
        order = self.create().json()
        for method, path, body in [
            ("GET", "/api/orders", None),
            ("GET", f"/api/orders/{order['orderId']}", None),
            ("POST", "/api/orders", self.body),
            ("POST", "/api/orders/quote", self.body),
            ("POST", f"/api/orders/{order['orderId']}/payment-request", {"version": 1}),
        ]:
            with self.subTest(path=path, method=method):
                response = self.client.request(method, path, json=body,
                                               headers={"Idempotency-Key": str(uuid4())})
                self.assert_error(response, 401, "AUTH_REQUIRED")
        self.assertEqual(self.latest(order), order)
        self.assertEqual(self.count(Order), 1)
        self.assertEqual(self.count(Idempotency), 1)

    def test_q02_foreign_and_missing_orders_are_indistinguishable(self):
        order = self.create().json()
        for suffix, body in [("", None), ("/payment-request", {"version": 1})]:
            method = "POST" if body else "GET"
            responses = [self.client.request(method, f"/api/orders/{oid}{suffix}",
                         json=body, headers=self.headers("bob"))
                         for oid in [order["orderId"], str(uuid4())]]
            for response in responses:
                self.assert_error(response, 404, "NOT_FOUND")
                self.assertNotIn(self.body["code"], response.text)
                self.assertNotIn(self.body["address"], response.text)
            self.assertEqual(responses[0].json(), responses[1].json())
        self.assertEqual(self.latest(order), order)
        self.assertEqual(self.count(Idempotency), 1)

    def test_q03_mine_scope_cannot_read_other_users_orders(self):
        alice = self.create().json()
        bob = self.create(uid="bob").json()
        for uid, expected in [("alice", alice), ("bob", bob)]:
            for role in ["all", "publisher", "courier"]:
                result = self.get(f"/api/orders?scope=mine&role={role}", uid).json()
                self.assertEqual([row["orderId"] for row in result["items"]],
                                 [] if role == "courier" else [expected["orderId"]])

    def test_q04_mass_assignment_cannot_change_owned_fields(self):
        for field, value in {"publisherUid": "bob", "courierUid": "bob", "version": 99,
                             "paymentStatus": "paid", "refundStatus": "succeeded",
                             "baseFee": 0, "commissionRateBps": 0, "demo": False}.items():
            with self.subTest(field=field):
                self.assert_error(self.create({**self.body, field: value}), 422, "VALIDATION_ERROR")
        self.assertEqual(self.count(Order), 0)
        self.assertEqual(self.count(Idempotency), 0)

    def test_q05_text_length_limits_accept_boundary_reject_overflow(self):
        for field, limit in [("company", 30), ("code", 50), ("address", 200), ("note", 200)]:
            with self.subTest(field=field):
                self.assertEqual(self.create({**self.body, field: "测" * limit}).status_code, 201)
                self.assert_error(self.create({**self.body, field: "测" * (limit + 1)}),
                                  422, "VALIDATION_ERROR")
        self.assertEqual(self.count(Order), 4)

    def test_q06_idempotency_key_missing_and_length_limits(self):
        for key in [None, "x" * 7, "x" * 101]:
            headers = {"Authorization": "Bearer alice"}
            if key is not None:
                headers["Idempotency-Key"] = key
            self.assert_error(self.client.post("/api/orders", json=self.body, headers=headers),
                              422, "VALIDATION_ERROR")
        for length in [8, 100]:
            self.assertEqual(self.create(key="x" * length).status_code, 201)
        self.assertEqual(self.count(Order), 2)

    def test_q07_delivery_window_exact_boundaries(self):
        fixed = now()
        for delta, status in [(timedelta(0), 422), (timedelta(microseconds=1), 201),
                              (timedelta(days=7), 201),
                              (timedelta(days=7, microseconds=1), 422)]:
            with self.subTest(delta=delta), patch("app.modules.orders.api.now", return_value=fixed):
                response = self.create({**self.body, "expectedAt": iso(fixed + delta)})
                self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.count(Order), 2)

    def test_q08_versions_reject_coercion_without_reserving(self):
        order = self.create().json()
        for value in [True, "1", 1.0, 0, -1, None]:
            with self.subTest(version=value):
                response = self.client.post(f"/api/orders/{order['orderId']}/payment-request",
                           json={"version": value}, headers=self.headers())
                self.assert_error(response, 422, "VALIDATION_ERROR")
        self.assertEqual(self.latest(order), order)

    def test_q09_invalid_pricing_matrix_never_persists_order(self):
        valid = main.app.state.pricing_service.quote
        for changes in [{"amount": 1}, {"tip": 0}, {"baseFee": True},
                        {"amount": "535"}, {"commissionRateBps": 10001},
                        {"expiresAt": iso(now() - timedelta(seconds=1))},
                        {"expiresAt": "2030-01-01T12:00:00"}, {"demo": "true"}]:
            with self.subTest(changes=changes):
                quote = {**valid(OrderDraft.model_validate(self.body)), **changes}
                with patch.object(main.app.state.pricing_service, "quote", return_value=quote):
                    self.assert_error(self.create(), 503, "DEPENDENCY_UNAVAILABLE")
                self.assertEqual(self.count(Order), 0)
                self.assertEqual(self.count(Idempotency), 0)

    def test_q10_pricing_outage_retry_with_same_key(self):
        key = str(uuid4())
        with patch.object(main.app.state.pricing_service, "quote",
                          side_effect=OperationalError("SELECT private_table", {}, Exception("secret"))):
            response = self.create(key=key)
        self.assert_error(response, 503, "DEPENDENCY_UNAVAILABLE")
        self.assertNotIn("private_table", response.text)
        self.assertNotIn("secret", response.text)
        self.assertEqual(self.count(Order), 0)
        self.assertEqual(self.count(Idempotency), 0)
        self.assertEqual(self.create(key=key).status_code, 201)
        self.assertEqual(self.count(Order), 1)

    def test_q11_create_failure_after_flush_rolls_back_and_retries(self):
        key = str(uuid4())
        with patch("app.modules.orders.api.remember", side_effect=OperationalError(
                "INSERT private_table", {}, Exception("secret"))):
            self.assert_error(self.create(key=key), 503, "DEPENDENCY_UNAVAILABLE")
        self.assertEqual(self.count(Order), 0)
        self.assertEqual(self.count(Idempotency), 0)
        first = self.create(key=key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.create(key=key).json(), first.json())
        self.assertEqual(self.count(Order), 1)

    def test_q12_reservation_failure_rolls_back_and_retries(self):
        order = self.create().json()
        key = str(uuid4())
        with patch("app.modules.orders.api.remember", side_effect=OperationalError(
                "INSERT private_table", {}, Exception("secret"))):
            self.assert_error(self.reserve(order, key), 503, "DEPENDENCY_UNAVAILABLE")
        self.assertEqual(self.latest(order), order)
        self.assertEqual(self.count(Idempotency), 1)
        reservation = self.reserve(order, key)
        self.assertEqual(reservation.status_code, 200)
        self.assertEqual(self.reserve(order, key).json(), reservation.json())
        self.assertEqual(self.latest(order)["version"], 2)

    def test_q13_retry_after_lost_response_does_not_requote_or_duplicate(self):
        key = str(uuid4())
        original = self.create(key=key)
        with patch.object(main.app.state.pricing_service, "quote",
                          side_effect=AssertionError("已提交的重试不应再次报价")):
            repeated = self.create(key=key)
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json(), original.json())
        self.assertEqual(self.count(Order), 1)
        self.assertEqual(self.count(Idempotency), 1)

    def test_q14_concurrent_same_key_create_has_one_resource(self):
        key = str(uuid4())
        barrier = Barrier(2)
        def submit(_):
            barrier.wait(timeout=5)
            return self.create(key=key)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        self.assertIn(201, [r.status_code for r in responses])
        for response in responses:
            self.assertIn(response.status_code, {201, 409, 503}, response.text)
        replay = self.create(key=key)
        self.assertEqual(replay.status_code, 201)
        for response in responses:
            if response.status_code == 201:
                self.assertEqual(response.json(), replay.json())
            else:
                self.assert_error(response, response.status_code,
                                  "REQUEST_IN_PROGRESS" if response.status_code == 409
                                  else "DEPENDENCY_UNAVAILABLE")
        self.assertEqual(self.count(Order), 1)
        self.assertEqual(self.count(Idempotency), 1)

    def test_q15_concurrent_reservations_converge_to_one_request(self):
        order = self.create().json()
        barrier = Barrier(2)
        def submit(_):
            barrier.wait(timeout=5)
            return self.reserve(order)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        self.assertEqual(sum(r.status_code == 200 for r in responses), 1)
        for response in responses:
            self.assertIn(response.status_code, {200, 409, 503}, response.text)
        latest = self.latest(order)
        self.assertEqual((latest["version"], latest["paymentStatus"]), (2, "paying"))
        replay = self.reserve(latest)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["paymentRequestId"], latest["paymentRequestId"])

    def test_q16_rejected_event_matrix_has_no_partial_facts(self):
        order = self.create().json()
        reservation = self.reserve(order).json()
        original = self.event(order, reservation)
        cases = [{"aggregateId": "wrong"}, {"aggregateType": "refund"},
                 {"occurredAt": "2026-11-11T12:00:00"}, {"version": True}]
        cases += [{"payload": {**original["payload"], **change}} for change in
                  [{"amount": True}, {"amount": "535"}, {"amount": 0},
                   {"code": "FAILED"}, {"unexpected": "private"}]]
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises((HTTPException, ValidationError)):
                    self.consume({**deepcopy(original), **changes})
                self.assertEqual(self.latest(order)["paymentStatus"], "paying")
                self.assertEqual(self.count(PaymentFact), 0)
                self.assertEqual(self.count(EventReceipt), 0)
        self.consume(original)
        self.assertEqual(self.latest(order)["paymentStatus"], "paid")

    def test_q17_event_receipt_failure_rolls_back_status_and_fact(self):
        order = self.create().json()
        event = self.event(order, self.reserve(order).json())
        with self.sessions() as db:
            original_add = db.add
            def fail_receipt(instance):
                if isinstance(instance, EventReceipt):
                    raise RuntimeError("回执写入失败")
                original_add(instance)
            with patch.object(db, "add", side_effect=fail_receipt):
                with self.assertRaises(RuntimeError):
                    handle(db, event)
            db.rollback()
        self.assertEqual(self.latest(order)["version"], 2)
        self.assertEqual(self.latest(order)["paymentStatus"], "paying")
        self.assertEqual(self.count(PaymentFact), 0)
        self.assertEqual(self.count(EventReceipt), 0)
        self.consume(event)
        self.assertEqual(self.latest(order)["version"], 3)
        self.assertEqual(self.count(PaymentFact), 1)
        self.assertEqual(self.count(EventReceipt), 1)

    def test_q18_same_event_id_mutation_does_not_change_committed_state(self):
        order, event = self.paid()
        before = self.latest(order)
        changed = deepcopy(event)
        changed["payload"]["amount"] += 1
        with self.assertRaises(HTTPException) as caught:
            self.consume(changed)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.latest(order), before)
        self.assertEqual(self.count(PaymentFact), 1)
        self.assertEqual(self.count(EventReceipt), 1)

    def test_q19_event_replay_burst_preserves_single_business_fact(self):
        order, event = self.paid()
        for _ in range(20):
            self.consume(event)
        self.assertEqual(self.latest(order), order)
        self.assertEqual(self.count(PaymentFact), 1)
        self.assertEqual(self.count(EventReceipt), 1)

    def test_q20_pagination_tie_break_is_stable_and_disjoint(self):
        fixed = now()
        created = []
        with patch("app.modules.orders.api.now", return_value=fixed):
            for _ in range(23):
                created.append(self.create().json()["orderId"])
        pages = [self.get(f"/api/orders?scope=mine&pageSize=10&page={page}").json()
                 for page in [1, 2, 3]]
        ids = [row["orderId"] for page in pages for row in page["items"]]
        self.assertEqual(ids, sorted(created))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(page["total"] == 23 for page in pages))
        self.assertEqual(self.get("/api/orders?scope=mine&pageSize=10&page=2").json(), pages[1])

    def test_q21_query_injection_and_numeric_coercion_rejected(self):
        for params in [{"stationId": "' OR 1=1 --"}, {"scope": "mine UNION SELECT *"},
                       {"page": "1e2"}, {"page": "+1"}, {"page": "１"},
                       {"tipMin": "235.0"}, {"tipMin": "true"}, {"pageSize": "1.0"}]:
            with self.subTest(params=params):
                self.assert_error(self.client.get("/api/orders", params=params,
                                  headers=self.headers()), 422, "VALIDATION_ERROR")
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.count(Order), 1)

    def test_q22_timezone_filter_matches_same_instant(self):
        order, _ = self.paid()
        utc = datetime.fromisoformat(order["expectedAt"].replace("Z", "+00:00"))
        local = utc.astimezone(timezone(timedelta(hours=8))).isoformat()
        response = self.client.get("/api/orders", params={"expectedFrom": local,
                                   "expectedTo": local}, headers=self.headers("bob"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([row["orderId"] for row in response.json()["items"]], [order["orderId"]])

    def test_q29_large_list_uses_bounded_queries_and_database_pagination(self):
        order = self.create().json()
        with self.sessions() as db:
            source = db.get(Order, order["orderId"])
            values = {column.name: getattr(source, column.name) for column in Order.__table__.columns}
            db.execute(insert(Order), [{**values, "id": str(uuid4())} for _ in range(999)])
            db.commit()
        statements = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and "orders_v2" in statement:
                statements.append(statement)
        sql_event.listen(self.engine, "before_cursor_execute", capture)
        try:
            for page in [1, 10]:
                statements.clear()
                response = self.get(f"/api/orders?scope=mine&pageSize=100&page={page}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["total"], 1000)
                self.assertEqual(len(response.json()["items"]), 100)
                self.assertEqual(len(statements), 2, statements)
                self.assertTrue(any("LIMIT" in sql.upper() and "OFFSET" in sql.upper()
                                    for sql in statements))
        finally:
            sql_event.remove(self.engine, "before_cursor_execute", capture)
