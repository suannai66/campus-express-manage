"""公共 outbox 的原子性、持久化重试、租约恢复及多消费者隔离。"""
import copy
import tempfile
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from unittest.mock import patch
from fastapi import HTTPException
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event as sqlalchemy_event, func, select, update
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.events import publish, register_consumer
from app.events import service
from app.events.models import Delivery, OutboxEvent
from app.common import iso, now
from app.modules.finance import models as finance_models  # 注册历史补录所需模型


class EventTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/events.db",
            connect_args={"check_same_thread": False, "timeout": 30})
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        Base.metadata.create_all(self.engine)
        self.effects = Table("test_effects", MetaData(), Column("id", String, primary_key=True), Column("count", Integer))
        self.effects.create(self.engine)
        with self.engine.begin() as db:
            db.execute(self.effects.insert().values(id="effect", count=0))
        self.registry = patch.dict(service._handlers, clear=True)
        self.registry.start()
        self.dispatcher = service.Dispatcher(self.sessions)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.registry.stop)

    def envelope(self, kind="payment.succeeded"):
        order, payment = str(uuid4()), str(uuid4())
        data = {"eventId": str(uuid4()), "type": kind, "occurredAt": iso(now()), "orderId": order,
                "aggregateType": "payment", "aggregateId": payment, "version": 1,
                "payload": {"paymentId": payment, "paymentRequestId": str(uuid4()), "payerUid": "test-payer", "amount": 535}}
        if kind == "order.cancelled":
            data.update(aggregateType="order", aggregateId=order,
                payload={"publisherUid": "test-payer", "paymentId": None, "amount": 535, "paid": False, "orderVersion": 1})
        return data

    def save(self, event):
        with self.sessions.begin() as db:
            return publish(db, event)

    def effect(self, db, event):
        db.execute(self.effects.update().values(count=self.effects.c.count + 1))
        return {"accepted": True}

    def count(self):
        with self.sessions() as db:
            return db.scalar(select(self.effects.c.count))

    def delivery(self, event, consumer="orders"):
        with self.sessions() as db:
            row = db.get(Delivery, (event["eventId"], consumer))
            db.expunge(row)
            return row

    def test_business_and_publish_rollback_together_and_never_call_handler_inline(self):
        event = self.envelope()
        register_consumer(event["type"], "orders", self.effect)
        with self.sessions() as db:
            self.effect(db, event)
            publish(db, event)
            db.rollback()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery)), 0)
        self.assertEqual(self.count(), 0)
        self.save(event)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual(self.count(), 1)

    def test_event_id_replay_preserves_success_and_changed_content_conflicts(self):
        event = self.envelope()
        register_consumer(event["type"], "orders", self.effect)
        self.save(event)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.save(dict(reversed(list(event.items())))), event["eventId"])
        self.assertEqual(self.dispatcher.dispatch_once(), 0)
        changed = copy.deepcopy(event)
        changed["payload"]["amount"] += 1
        with self.assertRaises(HTTPException) as exc:
            self.save(changed)
        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.delivery(event).status, "succeeded")

    def test_strict_envelope_rejects_private_fields_unknown_types_and_non_json_values(self):
        event = self.envelope()
        variants = [{**event, "token": "forbidden"}, {**event, "type": "invented"},
            {**event, "eventId": "bad"}, {**event, "occurredAt": 123},
            {**event, "occurredAt": "2026-10-31T12:00:00+00:00"},
            {**event, "payload": {**event["payload"], "amount": True}},
            {**event, "payload": {**event["payload"], "amount": float("nan")}},
            {**event, "payload": {**event["payload"], "pickupCode": "secret"}}]
        for bad in variants:
            with self.assertRaises(HTTPException) as exc:
                self.save(bad)
            self.assertEqual(exc.exception.status_code, 422)
        self.assertEqual(self.dispatcher.dispatch_once(), 0)

    def test_failed_business_rollback_backoff_dead_and_original_id_retry(self):
        event = self.envelope()
        def broken(db, data):
            self.effect(db, data)
            raise RuntimeError("injected")
        register_consumer(event["type"], "orders", broken)
        with patch.object(service.time, "time", return_value=1000) as clock:
            self.save(event)
            for attempt in range(1, 11):
                current = clock.return_value
                self.assertEqual(self.dispatcher.dispatch_once(), 1)
                row = self.delivery(event)
                self.assertEqual(row.attempts, attempt)
                self.assertEqual(row.status, "dead" if attempt == 10 else "pending")
                self.assertEqual(row.next_attempt_at - current, (1 if attempt == 1 else 5 if attempt == 2 else 30))
                self.assertIsNotNone(row.last_error)
                self.assertEqual(self.count(), 0)
                self.assertEqual(self.dispatcher.dispatch_once(), 0)
                clock.return_value = row.next_attempt_at
            self.assertEqual(self.dispatcher.dispatch_once(), 0)
            register_consumer(event["type"], "orders", self.effect)
            self.assertEqual(self.dispatcher.retry_dead(event["eventId"], consumer_name="orders"), 1)
            self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual(self.delivery(event).status, "succeeded")
        self.assertEqual(self.delivery(event).attempts, 1)
        self.assertEqual(self.count(), 1)

    def test_missing_consumer_is_persisted_and_does_not_repeat_other_consumer(self):
        event = self.envelope("order.cancelled")
        register_consumer(event["type"], "finance", self.effect)
        with patch.object(service.time, "time", return_value=1000) as clock:
            self.save(event)
            self.assertEqual(self.dispatcher.dispatch_once(), 2)
            self.assertEqual(self.delivery(event, "finance").status, "succeeded")
            self.assertEqual(self.delivery(event).status, "pending")
            self.assertIn("未装配", self.delivery(event).last_error)
            register_consumer(event["type"], "orders", self.effect)
            clock.return_value = 1001
            self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.delivery(event, "finance").attempts, 1)

    def test_restart_reclaims_expired_lease_old_owner_cannot_consume_or_record_failure(self):
        event = self.envelope()
        register_consumer(event["type"], "orders", self.effect)
        with patch.object(service.time, "time", return_value=1000) as clock:
            self.save(event)
            old = self.dispatcher._claim(set())
            restarted = service.Dispatcher(self.sessions)
            clock.return_value = 1059
            self.assertEqual(restarted.dispatch_once(), 0)
            clock.return_value = 1061
            new = restarted._claim(set())
            self.assertNotEqual(old[2], new[2])
            with self.assertRaises(service.LeaseLost):
                self.dispatcher._deliver(*old)
            self.dispatcher._failure(*old, RuntimeError("stale"))
            self.assertEqual(self.delivery(event).lease_owner, new[2])
            restarted._deliver(*new)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.delivery(event).attempts, 2)

    def test_expiry_before_ack_rolls_back_business_and_next_owner_retries(self):
        event = self.envelope()
        with patch.object(service.time, "time", return_value=1000) as clock:
            def slow(db, data):
                self.effect(db, data)
                clock.return_value += 61
            register_consumer(event["type"], "orders", slow)
            self.save(event)
            self.dispatcher.dispatch_once()
            self.assertEqual(self.count(), 0)
            self.assertEqual(self.delivery(event).status, "processing")
            register_consumer(event["type"], "orders", self.effect)
            self.assertEqual(service.Dispatcher(self.sessions).dispatch_once(), 1)
        self.assertEqual(self.count(), 1)

    def test_tenth_interrupted_lease_becomes_dead_and_can_be_retried(self):
        event = self.envelope()
        self.save(event)
        with self.sessions.begin() as db:
            db.execute(update(Delivery).values(status="processing", attempts=10, lease_until=0, lease_owner="crashed"))
        self.assertEqual(self.dispatcher.dispatch_once(), 0)
        self.assertEqual(self.delivery(event).status, "dead")
        register_consumer(event["type"], "orders", self.effect)
        self.assertEqual(self.dispatcher.retry_dead(event["eventId"]), 1)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(), 1)

    def test_maintenance_command_lists_metadata_and_retries_only_requested_consumer(self):
        event = self.envelope("order.cancelled")
        self.save(event)
        with self.sessions.begin() as db:
            db.execute(update(Delivery).values(status="dead", attempts=10))
        script = Path(__file__).resolve().parents[1] / "scripts" / "维护事件.py"
        environment = {**os.environ, "CAMPUS_DATABASE_PATH": str(Path(self.temp.name) / "events.db"), "PYTHONIOENCODING": "utf-8"}
        def run(*arguments):
            result = subprocess.run([sys.executable, str(script), *arguments], env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        output = run("--list")
        self.assertIn(event["eventId"], output)
        self.assertNotIn("test-payer", output)
        run("--retry", event["eventId"], "--consumer", "finance")
        self.assertEqual(self.delivery(event, "finance").status, "pending")
        self.assertEqual(self.delivery(event).status, "dead")

    def test_consumer_cannot_commit_before_delivery_ack(self):
        event = self.envelope()
        def illegal(db, data):
            self.effect(db, data)
            db.commit()
        register_consumer(event["type"], "orders", illegal)
        self.save(event)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.delivery(event).status, "pending")

    def test_failure_at_final_commit_rolls_back_business_and_success_ack(self):
        event = self.envelope()
        def interrupted(db, data):
            result = self.effect(db, data)
            def before_commit(session):
                raise RuntimeError("injected at final commit")
            sqlalchemy_event.listen(db, "before_commit", before_commit, once=True)
            return result
        register_consumer(event["type"], "orders", interrupted)
        self.save(event)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.delivery(event).status, "pending")
        self.assertIsNone(self.delivery(event).result)

    def test_two_dispatchers_claim_each_delivery_once(self):
        for _ in range(20):
            self.save(self.envelope())
        register_consumer("payment.succeeded", "orders", self.effect)
        with ThreadPoolExecutor(max_workers=2) as pool:
            counts = list(pool.map(lambda _: service.Dispatcher(self.sessions).dispatch_once(), range(2)))
        self.assertEqual(sum(counts), 20)
        self.assertEqual(self.count(), 20)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status == "succeeded")), 20)

    def test_processor_automatically_delivers_and_stops_its_thread(self):
        event = self.envelope()
        register_consumer(event["type"], "orders", self.effect)
        self.save(event)
        processor = service.start_processor(self.sessions)
        try:
            deadline = time.monotonic() + 5
            while self.delivery(event).status != "succeeded" and time.monotonic() < deadline:
                threading.Event().wait(0.02)
            self.assertEqual(self.delivery(event).status, "succeeded")
        finally:
            processor.stop()
        self.assertFalse(processor.thread.is_alive())
        self.assertEqual(self.count(), 1)

    def test_application_lifespan_installs_and_stops_dispatcher(self):
        import app.main as main
        from fastapi.testclient import TestClient
        with patch.object(main, "engine", self.engine), \
             patch("app.modules.finance.services.withdraw.start_withdraw_processor"), \
             patch.dict(main.app.state._state, {"identity_service": object(), "pricing_service": object()}, clear=True):
            with TestClient(main.app):
                processor = main.app.state.event_processor
                self.assertTrue(processor.thread.is_alive())
            self.assertFalse(processor.thread.is_alive())
            self.assertFalse(hasattr(main.app.state, "event_processor"))

    def test_twenty_publish_delivery_replay_and_failure_recovery_runs(self):
        for _ in range(20):
            event = self.envelope()
            def broken(db, data):
                self.effect(db, data)
                raise RuntimeError("injected")
            register_consumer(event["type"], "orders", broken)
            self.save(event)
            self.dispatcher.dispatch_once()
            with self.sessions.begin() as db:
                db.execute(update(Delivery).where(Delivery.event_id == event["eventId"]).values(next_attempt_at=0))
            register_consumer(event["type"], "orders", self.effect)
            service.Dispatcher(self.sessions).dispatch_once()
            self.save(event)
            self.assertEqual(self.dispatcher.dispatch_once(), 0)
        self.assertEqual(self.count(), 20)
