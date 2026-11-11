"""C 验收：真实订单/资金/outbox；身份替身仅在临时测试应用装配。"""
import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update, delete
import app.main as main
from app.common import Idempotency, fail, fingerprint, iso, now
from app.events.models import OutboxEvent, Delivery
from app.events.service import Dispatcher
from app.modules.finance.models import Account, Settlement, Refund
from app.modules.fulfillment.credit import CreditService
from app.modules.fulfillment.handlers import on_order_completed
from app.modules.fulfillment.models import OperationLog, Notification, Review, ReviewOpening, ConsumerReceipt
from app.modules.orders.integrations import Identity
from app.modules.orders.entities import Order
import test_finance_payment


class FulfillmentTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.fixture
        class DatabaseIdentity:
            def current(self, request, db):
                db.execute(select(Account.uid))  # 共用鉴权已开启的事务
                uid = request.headers.get("Authorization", "").removeprefix("Bearer ")
                if uid not in {"alice", "bob", "carol", "unverified"}:
                    fail(401, "AUTH_REQUIRED", "请先登录")
                return Identity(uid, verified=uid != "unverified")
        main.app.state.identity_service = DatabaseIdentity()
        self.dispatcher = Dispatcher(self.f.sessions)

    def post(self, order, endpoint, body=None, uid="bob", key=None):
        return self.f.client.post(f"/api/orders/{order['orderId']}/{endpoint}",
            json=body if body is not None else {"version": order["version"]}, headers=self.f.headers(uid, key))

    def latest(self, order, uid="alice"):
        return self.f.get(f"/api/orders/{order['orderId']}", uid).json()

    def paid(self):
        self.helper.fund()
        body = self.helper.order()
        self.assertEqual(self.helper.pay(body).json()["status"], "succeeded")
        self.dispatcher.dispatch_once()
        return self.latest(body)

    def advance(self, order, action, uid="bob", key=None, **extra):
        return self.post(order, "status", {"version": order["version"], "action": action, **extra}, uid, key)

    def pickup(self):
        order = self.paid()
        order = self.post(order, "accept").json()
        return self.advance(order, "start_pickup").json()

    def delivered(self):
        order = self.pickup()
        order = self.advance(order, "confirm_pickup").json()
        return self.advance(order, "confirm_delivery").json()

    def completed(self, dispatch=True):
        order = self.advance(self.delivered(), "confirm_receipt", uid="alice").json()
        if dispatch:
            self.dispatcher.dispatch_once()
        return order

    def count(self, model):
        with self.f.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def test_real_lifecycle_settlement_opening_logs_and_event_privacy(self):
        order = self.completed()
        self.assertEqual(order["status"], "completed")
        self.assertEqual(self.count(OperationLog), 5)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(Settlement), 1)
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.f.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            events = list(db.scalars(select(OutboxEvent).where(OutboxEvent.type.like("order.%"))))
            self.assertEqual(len(events), 6)
            serialized = json.dumps([e.body for e in events])
            for private in (self.f.body["code"], self.f.body["address"], "token", "phone"):
                self.assertNotIn(private, serialized)
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status != "succeeded")), 0)
        self.assertEqual(self.post(order, "status", {"action": "confirm_delivery", "version": order["version"]}).status_code, 409)

    def test_admission_actor_privacy_and_strict_contract(self):
        order = self.paid()
        url = f"/api/orders/{order['orderId']}/accept"
        self.assertEqual(self.f.client.post(url, json={"version": order["version"]}).status_code, 401)
        for uid, code in (("alice", "FORBIDDEN"), ("unverified", "VERIFICATION_REQUIRED")):
            self.assertEqual(self.post(order, "accept", uid=uid).json()["code"], code)
        for body in ({"version": True}, {"version": "3"}, {"version": 0}, {"version": order["version"], "uid": "bob"}):
            self.assertEqual(self.post(order, "accept", body).status_code, 422)
        accepted = self.post(order, "accept").json()
        self.assertEqual(self.advance(accepted, "confirm_delivery").status_code, 409)
        self.assertEqual(self.advance(accepted, "confirm_receipt", uid="alice").status_code, 409)
        self.assertEqual(self.advance(accepted, "start_pickup", uid="alice").status_code, 403)
        self.assertEqual(self.post(accepted, "status", {"version": accepted["version"], "action": "start_pickup"}, uid="carol").status_code, 403)
        for body in ({"action": "start_pickup", "code": None}, {"action": "start_pickup", "code": "x"}, {"action": "confirm_pickup", "code": "x"}, {"action": "skip"}):
            self.assertEqual(self.post(accepted, "status", {"version": accepted["version"], **body}).status_code, 422)
        for endpoint in ("status", "reviews", "notifications"):
            self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/{endpoint}", "carol").status_code, 404)
        self.assertEqual(self.f.get("/api/users/bob/credit").status_code, 404)
        self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/reviews?page=0").status_code, 422)
        for query in ("page=1.0", "pageSize=101", "uid=alice"):
            self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/notifications?{query}").status_code, 422)

    def test_request_replay_survives_version_changes_and_key_conflict(self):
        order = self.paid()
        key = str(uuid4())
        first = self.post(order, "accept", key=key)
        self.assertEqual(first.status_code, 200)
        self.advance(first.json(), "start_pickup")
        self.assertEqual(self.post(order, "accept", key=key).json(), first.json())
        changed = self.post(order, "accept", {"version": order["version"] + 1}, key=key)
        self.assertEqual(changed.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)

    def test_pickup_requires_no_code_and_replays_without_old_locking(self):
        order = self.pickup()
        key = str(uuid4())
        first = self.advance(order, "confirm_pickup", key=key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "delivering")
        self.assertEqual(self.advance(order, "confirm_pickup", key=key).json(), first.json())
        for field in ("code", "pickupFailureCount", "locked"):
            self.assertNotIn(field, first.json())
        self.assertEqual(self.count(OperationLog), 3)
        self.assertEqual(self.count(Notification), 0)

    def test_legacy_accept_success_replay_hides_fields_without_rewriting_receipt(self):
        order = self.paid()
        key = str(uuid4())
        first = self.post(order, "accept", key=key).json()
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            original = {**row.result, "body": {**row.result["body"], "code": "legacy-code",
                "locked": True, "pickupFailureCount": 3}}
            row.result = original
        self.assertEqual(self.post(order, "accept", key=key).json(), first)
        self.assertEqual(self.count(OperationLog), 1)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(Idempotency).where(Idempotency.key == key)).result, original)

    def test_legacy_null_code_digest_replays_and_still_rejects_new_code_and_conflicts(self):
        order = self.post(self.paid(), "accept").json()
        key = str(uuid4())
        body = {"action": "start_pickup", "version": order["version"]}
        first = self.post(order, "status", body, key=key).json()
        old_digest = fingerprint({**body, "code": None})
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            row.digest = old_digest
            row.result = {**row.result, "body": {**row.result["body"], "code": "legacy-code",
                "locked": False, "pickupFailureCount": 0}}
        self.assertEqual(self.post(order, "status", body, key=key).json(), first)
        self.assertEqual(self.post(order, "status", {**body, "code": None}, key=key).status_code, 422)
        conflict = self.post(order, "status", {**body, "version": body["version"] + 1}, key=key)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(Idempotency).where(Idempotency.key == key)).digest, old_digest)

    def test_legacy_code_error_cannot_be_replayed_as_success_without_code(self):
        order = self.pickup()
        key = str(uuid4())
        body = {"action": "confirm_pickup", "version": order["version"]}
        original = {"statusCode": 422, "body": {"code": "PICKUP_CODE_MISMATCH",
            "detail": "旧版取件码错误", "fields": {"pickupFailureCount": 1, "locked": False}}}
        with self.f.sessions.begin() as db:
            db.add(Idempotency(uid="bob", operation=f"fulfillment:status:{order['orderId']}", key=key,
                digest=fingerprint({**body, "code": "wrong-code"}), result=original))
        response = self.post(order, "status", body, key=key)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            row.digest = fingerprint({**body, "code": None})
        response = self.post(order, "status", body, key=key)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), original["body"])
        self.assertEqual(self.count(OperationLog), 2)

    def test_delivery_waits_for_publisher_receipt_before_settlement_and_reviews(self):
        order = self.delivered()
        self.assertEqual(order["status"], "delivered")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Settlement), 0)
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.helper.balances(), (465, 535))
        self.assertFalse(self.f.get(f"/api/orders/{order['orderId']}/reviews").json()["reviewable"])
        self.assertEqual(self.post(order, "reviews", {"rating": 5}, "alice").status_code, 409)
        self.assertEqual(self.advance(order, "confirm_receipt").status_code, 403)
        self.assertEqual(self.advance(order, "confirm_receipt", uid="carol").status_code, 403)
        key = str(uuid4())
        completed = self.advance(order, "confirm_receipt", uid="alice", key=key)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertEqual(self.advance(order, "confirm_receipt", uid="alice", key=key).json(), completed.json())
        self.assertEqual(self.advance(completed.json(), "confirm_receipt", uid="alice").status_code, 409)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Settlement), 1)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.f.get("/api/orders?scope=mine&status=completed").json()["total"], 1)

    def test_two_couriers_compete_and_only_one_owns_order(self):
        for _ in range(5):
            order = self.paid()
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda uid: self.post(order, "accept", uid=uid), ("bob", "carol")))
            self.assertEqual(sorted(r.status_code for r in results), [200, 409])
            winner = next(uid for uid, r in zip(("bob", "carol"), results) if r.status_code == 200)
            self.assertEqual(self.latest(order)["courierUid"], winner)

    def test_accept_cancel_compete(self):
        for _ in range(5):
            order = self.paid()
            with ThreadPoolExecutor(2) as pool:
                a = pool.submit(self.post, order, "accept")
                b = pool.submit(self.post, order, "cancel", {"version": order["version"], "reason": "计划变更"}, "alice")
                results = [a.result(), b.result()]
            self.assertEqual(sorted(r.status_code for r in results), [200, 409])
            self.assertIn(self.latest(order)["status"], {"accepted", "cancelled"})

    def test_cancel_unpaid_paying_paid_and_refund_end_to_end(self):
        order = self.f.create().json()
        body = {"version": order["version"], "reason": "不再需要"}
        self.assertEqual(self.post(order, "cancel", body, "bob").status_code, 403)
        result = self.post(order, "cancel", body, "alice")
        self.assertEqual((result.json()["status"], result.json()["refundStatus"]), ("cancelled", "none"))
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Refund), 0)
        paying = self.f.create().json()
        self.f.reserve(paying)
        paying = self.latest(paying)
        self.assertEqual(self.post(paying, "cancel", {"version": paying["version"], "reason": "变更"}, "alice").json()["code"], "PAYMENT_IN_PROGRESS")
        order = self.paid()
        cancelled = self.post(order, "cancel", {"version": order["version"], "reason": "计划变更"}, "alice").json()
        self.assertEqual(cancelled["refundStatus"], "processing")
        self.dispatcher.dispatch_once(); self.dispatcher.dispatch_once()
        self.assertEqual(self.latest(order)["refundStatus"], "succeeded")
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.count(Refund), 1)

    def test_publish_failure_rolls_back_state_log_and_idempotency(self):
        order = self.paid()
        before = self.count(Idempotency)
        with patch("app.modules.fulfillment.service.publish", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError): self.post(order, "accept")
        self.assertEqual(self.latest(order)["status"], "pending")
        self.assertEqual(self.count(OperationLog), 0)
        self.assertEqual(self.count(Idempotency), before)
        self.assertEqual(self.post(order, "accept").status_code, 200)

    def test_receipt_publish_failure_rolls_back_completion_and_retry(self):
        order = self.delivered()
        key = str(uuid4())
        before = self.count(Idempotency)
        from app.events import publish as original_publish
        def publish_until_completion(db, event):
            if event["type"] == "order.completed":
                raise RuntimeError("injected completion failure")
            return original_publish(db, event)
        with patch("app.modules.fulfillment.service.publish", side_effect=publish_until_completion):
            with self.assertRaises(RuntimeError):
                self.advance(order, "confirm_receipt", uid="alice", key=key)
        self.assertEqual(self.latest(order)["status"], "delivered")
        self.assertEqual(self.count(OperationLog), 4)
        self.assertEqual(self.count(Idempotency), before)
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.count(Settlement), 0)
        self.assertEqual(self.advance(order, "confirm_receipt", uid="alice", key=key).status_code, 200)

    def test_receipt_rejects_stale_version_and_concurrent_completion_once(self):
        order = self.delivered()
        self.assertEqual(self.post(order, "status", {"version": order["version"] - 1, "action": "confirm_receipt"}, "alice").status_code, 409)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.advance(order, "confirm_receipt", uid="alice"), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(OperationLog), 5)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(Settlement), 1)

    def test_review_waits_for_event_and_both_sides_submit_immutable_once(self):
        order = self.completed(dispatch=False)
        body = {"rating": 5, "tags": [" 准时 "], "comment": "<script>plain text</script>"}
        self.assertEqual(self.post(order, "reviews", body, "alice").status_code, 409)
        self.dispatcher.dispatch_once()
        for uid in ("alice", "bob"):
            self.assertEqual(self.post(order, "reviews", body, uid).status_code, 201)
            self.assertEqual(self.post(order, "reviews", body, uid).json()["code"], "ALREADY_REVIEWED")
        result = self.f.get(f"/api/orders/{order['orderId']}/reviews").json()
        self.assertTrue(result["reviewable"])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["tags"], ["准时"])
        self.assertEqual(self.f.get("/api/users/bob/credit", "bob").json()["reviewCount"], 1)
        self.assertEqual(self.f.get("/api/users/alice/credit").json()["reviewCount"], 0)
        self.assertEqual(self.f.client.patch(f"/api/orders/{order['orderId']}/reviews", json=body, headers=self.f.headers()).status_code, 405)

    def test_review_validation_and_concurrent_double_click(self):
        order = self.completed()
        for body in ({"rating": True}, {"rating": "5"}, {"rating": 1.5}, {"rating": 0}, {"rating": 6},
                     {"rating": 5, "tags": ["a"] * 6}, {"rating": 5, "tags": [" "]}, {"rating": 5, "tags": ["a" * 21]},
                     {"rating": 5, "comment": "a" * 501}, {"rating": 5, "revieweeUid": "alice"}):
            self.assertEqual(self.post(order, "reviews", body, "alice").status_code, 422)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.post(order, "reviews", {"rating": 4}, "alice"), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        self.assertEqual(self.count(Review), 1)

    def test_completion_consumer_replay_conflict_rollback_and_retry(self):
        order = self.completed(dispatch=False)
        with self.f.sessions() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.type == "order.completed")).body
            on_order_completed(db, event)
            db.rollback()
        self.assertEqual(self.count(ReviewOpening), 0)
        with patch.dict("app.events.service._handlers", {("order.completed", "fulfillment"): lambda db, e: (_ for _ in ()).throw(RuntimeError("injected"))}):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.count(Settlement), 1)
        with self.f.sessions.begin() as db:
            db.execute(update(Delivery).where(Delivery.consumer == "fulfillment").values(next_attempt_at=0))
        self.dispatcher.dispatch_once()
        with self.f.sessions.begin() as db:
            first = on_order_completed(db, event)
            self.assertEqual(first, on_order_completed(db, event))
            self.assertEqual(first, on_order_completed(db, {**event, "eventId": str(uuid4())}))
        changed = copy.deepcopy(event)
        changed["payload"]["amount"] += 1
        changed["payload"]["tip"] += 1
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as caught: on_order_completed(db, changed)
            self.assertEqual(caught.exception.detail["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(ConsumerReceipt), 2)

    def seed_review(self, db, rating, index=0, role="publisher", created=None):
        db.add(Review(id=f"{index:03}-{uuid4()}", order_id=str(uuid4()), reviewer_uid="alice", reviewee_uid="bob",
            reviewer_role=role, rating=rating, tags=[], comment="", created_at=created or iso(now())))

    def test_credit_newcomer_recent_thirty_roles_boundaries_and_rounding(self):
        with self.f.sessions() as db:
            self.assertEqual(CreditService.get(db, "bob"), {"uid": "bob", "score": None, "level": "new", "reviewCount": 0, "creditEligible": True})
        for ratings, expected in (([1, 5], (3.0, "normal", True)), ([3, 5], (4.0, "good", True)), ([2, 3, 3], (2.67, "restricted", False))):
            with self.f.sessions.begin() as db:
                db.execute(delete(Review))
                for i, rating in enumerate(ratings): self.seed_review(db, rating, i)
                self.seed_review(db, 1, 90, role="courier")
            with self.f.sessions() as db:
                result = CreditService.get(db, "bob")
                self.assertEqual((result["score"], result["level"], result["creditEligible"]), expected)
                self.assertEqual(result["reviewCount"], len(ratings))
        with self.f.sessions.begin() as db:
            db.execute(delete(Review))
            for i in range(31): self.seed_review(db, 1 if i == 0 else 5, i, created="2026-10-31T00:00:00.000000Z")
        with self.f.sessions() as db:
            self.assertEqual(CreditService.get(db, "bob")["score"], 5.0)
            self.assertEqual(CreditService.get(db, "bob")["reviewCount"], 30)

    def test_low_credit_blocks_new_acceptance_but_not_existing_fulfillment(self):
        order = self.pickup()
        with self.f.sessions.begin() as db: self.seed_review(db, 1)
        another = self.paid()
        self.assertEqual(self.post(another, "accept").json()["code"], "CREDIT_TOO_LOW")
        self.assertEqual(self.advance(order, "confirm_pickup").status_code, 200)


if __name__ == "__main__":
    unittest.main()
