"""应用内公共 outbox；发布借用业务事务，投递器独立管理消费事务。"""
from .service import publish, register_consumer, dispatch_once, retry_dead, start_processor

__all__ = ["publish", "register_consumer", "dispatch_once", "retry_dead", "start_processor"]
