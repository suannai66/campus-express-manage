"""短事务抢租约；消费、业务回执及确认同事务；失败另开事务记录。"""
import copy
import json
import inspect
import logging
import threading
import time
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import and_, event as sqlalchemy_event, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from .. import database
from ..common import fail
from .models import Delivery, OutboxEvent
from .schema import SUBSCRIPTIONS, validate

logger = logging.getLogger(__name__)
_handlers = {}
_registry_lock = threading.Lock()
LEASE_SECONDS = 60
MAX_ATTEMPTS = 10


def register_consumer(event_type, consumer_name, handler):
    if (consumer_name not in SUBSCRIPTIONS.get(event_type, ()) or not callable(handler)
            or inspect.iscoroutinefunction(handler)):
        raise ValueError("消费者必须属于团队约定的订阅关系，并提供同步处理器")
    with _registry_lock:
        _handlers[event_type, consumer_name] = handler


def publish(db, event: dict) -> str:
    body, digest = validate(event)
    event_id, clock = body["eventId"], time.time()
    db.execute(insert(OutboxEvent).values(id=event_id, type=body["type"],
        order_id=body["orderId"], digest=digest, body=body, created_at=clock).on_conflict_do_nothing())
    if db.get(OutboxEvent, event_id).digest != digest:
        fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
    for consumer in SUBSCRIPTIONS[body["type"]]:
        db.execute(insert(Delivery).values(event_id=event_id, consumer=consumer,
            status="pending", attempts=0, next_attempt_at=clock).on_conflict_do_nothing())
    db.flush()
    return event_id


class LeaseLost(RuntimeError):
    pass


class MissingConsumer(RuntimeError):
    pass


class Dispatcher:
    """会话工厂可由单体入口/隔离测试注入；每次操作均新建 Session。"""
    def __init__(self, sessions):
        self.sessions = sessions
        self._backfill_after = {}

    def _claim(self, excluded):
        clock = time.time()
        due = or_(and_(Delivery.status == "pending", Delivery.next_attempt_at <= clock),
                  and_(Delivery.status == "processing", Delivery.lease_until <= clock))
        with self.sessions.begin() as db:
            candidates = db.execute(select(Delivery.event_id, Delivery.consumer, Delivery.attempts).where(due)
                .order_by(Delivery.next_attempt_at, Delivery.event_id, Delivery.consumer).limit(40)).all()
            for event_id, consumer, attempts in candidates:
                if (event_id, consumer) in excluded:
                    continue
                if attempts >= MAX_ATTEMPTS:
                    db.execute(update(Delivery).where(Delivery.event_id == event_id,
                        Delivery.consumer == consumer, due, Delivery.attempts >= MAX_ATTEMPTS).values(
                            status="dead", lease_owner=None, lease_until=None,
                            last_error="租约过期或中断，已达到连续尝试上限"))
                    continue
                owner = str(uuid4())
                changed = db.execute(update(Delivery).where(Delivery.event_id == event_id,
                    Delivery.consumer == consumer, due).values(status="processing", lease_owner=owner,
                    lease_until=clock + LEASE_SECONDS, attempts=Delivery.attempts + 1))
                if changed.rowcount == 1:
                    return event_id, consumer, owner

    @staticmethod
    def _owned(event_id, consumer, owner):
        return (Delivery.event_id == event_id, Delivery.consumer == consumer,
                Delivery.status == "processing", Delivery.lease_owner == owner)

    def _deliver(self, event_id, consumer, owner):
        with self.sessions.begin() as db:
            # 首次条件写取得 SQLite 写锁，租约失效时不能执行消费者。
            guard = db.execute(update(Delivery).where(*self._owned(event_id, consumer, owner),
                Delivery.lease_until > time.time()).values(lease_owner=owner))
            if guard.rowcount != 1:
                raise LeaseLost()
            event = db.get(OutboxEvent, event_id)
            with _registry_lock:
                handler = _handlers.get((event.type, consumer))
            if handler is None:
                raise MissingConsumer(f"未装配消费者 {event.type}/{consumer}")
            def forbid_commit(session):
                raise RuntimeError("消费者不能自行提交公共消费事务")
            sqlalchemy_event.listen(db, "before_commit", forbid_commit)
            try:
                result = handler(db, copy.deepcopy(event.body))
            finally:
                sqlalchemy_event.remove(db, "before_commit", forbid_commit)
            if result is not None and type(result) is not dict:
                raise TypeError("消费者结果须为字典或 None")
            json.dumps(result, allow_nan=False)
            db.flush()
            ack = db.execute(update(Delivery).where(*self._owned(event_id, consumer, owner),
                Delivery.lease_until > time.time()).values(status="succeeded", result=result,
                    last_error=None, lease_owner=None, lease_until=None))
            if ack.rowcount != 1:
                raise LeaseLost()

    def _failure(self, event_id, consumer, owner, error):
        if isinstance(error, HTTPException) and isinstance(error.detail, dict):
            reason = f"{error.detail.get('code', 'REQUEST_FAILED')}: {error.detail.get('detail', '')}"
        elif isinstance(error, MissingConsumer):
            reason = str(error)
        else:
            # 不把 SQL 参数、凭证或完整事件写入诊断字段。
            reason = f"{type(error).__name__}: 消费失败，请检查对应处理器"
        with self.sessions.begin() as db:
            row = db.get(Delivery, (event_id, consumer))
            if not row or row.status != "processing" or row.lease_owner != owner:
                return
            dead = row.attempts >= MAX_ATTEMPTS
            delay = (1, 5, 30)[min(max(row.attempts - 1, 0), 2)]
            db.execute(update(Delivery).where(*self._owned(event_id, consumer, owner)).values(
                status="dead" if dead else "pending", next_attempt_at=time.time() + delay,
                last_error=reason[:1000], lease_owner=None, lease_until=None))
        logger.warning("事件投递失败 %s/%s：%s", event_id, consumer, reason[:1000])

    def dispatch_once(self, *, limit=20):
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("每批投递数量须为 1 至 20")
        attempted = set()
        for _ in range(limit):
            claim = self._claim(attempted)
            if claim is None:
                break
            event_id, consumer, owner = claim
            attempted.add((event_id, consumer))
            try:
                self._deliver(event_id, consumer, owner)
            except LeaseLost:
                pass  # 整笔消费事务已回滚；由当前租约持有者或过期回收处理。
            except Exception as error:
                self._failure(event_id, consumer, owner, error)
        return len(attempted)

    def retry_dead(self, event_id, *, consumer_name=None):
        with self.sessions.begin() as db:
            criteria = [Delivery.event_id == event_id, Delivery.status == "dead"]
            if consumer_name is not None:
                criteria.append(Delivery.consumer == consumer_name)
            return db.execute(update(Delivery).where(*criteria).values(status="pending", attempts=0,
                next_attempt_at=time.time(), last_error=None, lease_owner=None, lease_until=None)).rowcount

    def backfill_once(self, *, limit=20):
        """只搬运原始事件及入箱标记；绝不再次执行支付或退款。"""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("每批补录数量须为 1 至 20")
        from ..modules.finance.models import Payment, Refund
        copied = 0
        for model in (Payment, Refund):
            with self.sessions() as db:
                query = select(model.id).where(model.event_status == "pending")
                cursor = self._backfill_after.get(model)
                page = query.where(model.id > cursor) if cursor else query
                ids = db.scalars(page.order_by(model.id).limit(limit - copied)).all()
                if not ids and cursor:
                    ids = db.scalars(query.order_by(model.id).limit(limit - copied)).all()
                    self._backfill_after[model] = None
            for row_id in ids:
                # 坏数据继续保留 pending，但下一轮向后扫描，不能堵住其他历史事件。
                # 游标仅优化扫描位置；重启从头扫描仍由持久化标记及 eventId 保证安全。
                self._backfill_after[model] = row_id
                try:
                    with self.sessions.begin() as db:
                        changed = db.execute(update(model).where(model.id == row_id,
                            model.event_status == "pending").values(event_status="outbox_saved"))
                        if changed.rowcount == 1:
                            publish(db, db.get(model, row_id).event)
                            copied += 1
                except Exception as error:
                    logger.error("历史资金事件补录失败 %s/%s (%s)", model.__tablename__, row_id, type(error).__name__)
            if copied >= limit:
                break
        return copied


def dispatch_once(*, limit=20):
    return Dispatcher(database.SessionLocal).dispatch_once(limit=limit)


def retry_dead(event_id, *, consumer_name=None):
    return Dispatcher(database.SessionLocal).retry_dead(event_id, consumer_name=consumer_name)


class Processor:
    def __init__(self, sessions):
        self.dispatcher = Dispatcher(sessions)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="outbox-dispatcher", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                self.dispatcher.backfill_once()
                self.dispatcher.dispatch_once()
            except Exception as error:
                logger.error("公共事件扫描暂时失败 (%s)，保留租约与待办下轮恢复", type(error).__name__)
            self.stopped.wait(1)

    def stop(self):
        self.stopped.set()
        self.thread.join()


def start_processor(sessions):
    return Processor(sessions)
