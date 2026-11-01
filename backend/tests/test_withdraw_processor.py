"""提现后台任务启停、在途事务与应用生命周期测试。"""
import tempfile
import threading
import unittest
from datetime import timedelta
from unittest.mock import patch, Mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
import app.main as main
from app.common import now
from app.modules.finance.models import Account, WithdrawOrder, Ledger
from app.modules.finance.services import withdraw


class WithdrawProcessorTests(unittest.TestCase):
    def test_idle_stop_wakes_long_interval_and_is_repeatable(self):
        scanned = threading.Event()
        sentinel_factory = object()
        with patch.object(withdraw, "process_due_withdrawals", side_effect=lambda factory: scanned.set()) as scan:
            processor = withdraw.WithdrawProcessor(sentinel_factory, interval=3600)
            self.addCleanup(processor.stop)
            self.assertTrue(scanned.wait(2))
            processor.stop()
            processor.stop()
            self.assertFalse(processor.thread.is_alive())
            scan.assert_called_once_with(sentinel_factory)

    def test_scan_exception_can_retry_then_stop(self):
        attempted, recovered = threading.Event(), threading.Event()
        def scan(factory):
            if not attempted.is_set():
                attempted.set()
                raise RuntimeError("injected transient failure")
            recovered.set()
        with patch.object(withdraw, "process_due_withdrawals", side_effect=scan), self.assertLogs(withdraw.__name__, level="ERROR"):
            processor = withdraw.WithdrawProcessor(object(), interval=0.01)
            self.addCleanup(processor.stop)
            self.assertTrue(recovered.wait(2))
            processor.stop()
            self.assertFalse(processor.thread.is_alive())

    def test_stop_waits_for_real_refund_transaction_and_closes_session(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{directory}/withdraw.db", connect_args={"check_same_thread": False})
            sessions = sessionmaker(bind=engine)
            for model in (Account, WithdrawOrder, Ledger): model.__table__.create(engine)
            with sessions.begin() as db:
                db.add(Account(uid="test-user", available_cent=500))
                db.add(WithdrawOrder(withdraw_no="test-withdraw", uid="test-user", amount_cent=500,
                                     created_at=now() - timedelta(seconds=10)))
            inside, release, stopped = threading.Event(), threading.Event(), threading.Event()
            original = withdraw.finish_withdrawal
            def hold(*args, **kwargs):
                result = original(*args, **kwargs)
                inside.set()
                if not release.wait(5): raise RuntimeError("test gate timed out")
                return result
            with patch.object(withdraw, "finish_withdrawal", side_effect=hold), patch.object(withdraw.config, "WITHDRAW_DEMO_OUTCOME", "failed"):
                processor = withdraw.start_withdraw_processor(sessions)
                stopper = None
                try:
                    self.assertTrue(inside.wait(2))
                    stopper = threading.Thread(target=lambda: (processor.stop(), stopped.set()))
                    stopper.start()
                    self.assertTrue(processor.stopped.wait(2))
                    self.assertFalse(stopped.is_set())
                    with sessions() as db:
                        self.assertEqual(db.get(Account, "test-user").available_cent, 500)
                        self.assertEqual(db.get(WithdrawOrder, "test-withdraw").status, "processing")
                    release.set()
                    self.assertTrue(stopped.wait(2))
                    stopper.join()
                    with sessions() as db:
                        self.assertEqual(db.get(Account, "test-user").available_cent, 1000)
                        self.assertEqual(db.get(WithdrawOrder, "test-withdraw").status, "failed")
                    self.assertEqual(engine.pool.checkedout(), 0)
                finally:
                    release.set()
                    processor.stop()
                    if stopper: stopper.join()
                    engine.dispose()

    def test_real_application_shutdown_stops_withdraw_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{directory}/lifespan.db", connect_args={"check_same_thread": False})
            event_processor = Mock()
            with patch.object(main, "engine", engine), patch.object(main, "start_processor", return_value=event_processor),                     patch.dict(main.app.state._state, {"identity_service": object(), "pricing_service": object()}, clear=True):
                with TestClient(main.app):
                    processor = main.app.state.withdraw_processor
                    self.assertTrue(processor.thread.is_alive())
                    self.assertIs(processor.sessions.kw["bind"], engine)
                self.assertFalse(processor.thread.is_alive())
                self.assertFalse(hasattr(main.app.state, "withdraw_processor"))
                event_processor.stop.assert_called_once()
            engine.dispose()

    def test_partial_startup_failure_stops_already_started_withdraw_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{directory}/failed-start.db", connect_args={"check_same_thread": False})
            actual_start = withdraw.start_withdraw_processor
            workers = []
            def capture(sessions):
                worker = actual_start(sessions)
                workers.append(worker)
                return worker
            with patch.object(main, "engine", engine), patch.object(main, "start_processor", side_effect=RuntimeError("outbox startup failed")),                     patch.object(withdraw, "start_withdraw_processor", side_effect=capture),                     patch.dict(main.app.state._state, {"identity_service": object(), "pricing_service": object()}, clear=True):
                with self.assertRaises(RuntimeError):
                    with TestClient(main.app): pass
                self.assertEqual(len(workers), 1)
                self.assertFalse(workers[0].thread.is_alive())
                self.assertFalse(hasattr(main.app.state, "withdraw_processor"))
            engine.dispose()
