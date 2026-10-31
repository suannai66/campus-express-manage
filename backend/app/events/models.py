"""同库持久化事件与每消费者独立投递状态，时间使用 UTC Unix 秒。"""
from sqlalchemy import Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(60))
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)


class Delivery(Base):
    __tablename__ = "outbox_deliveries"
    __table_args__ = (Index("ix_outbox_due", "status", "next_attempt_at", "lease_until"),)
    event_id: Mapped[str] = mapped_column(ForeignKey("outbox_events.id"), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(30), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    lease_until: Mapped[float | None] = mapped_column(Float)
    lease_owner: Mapped[str | None] = mapped_column(String(36))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
