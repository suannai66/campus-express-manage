"""C 模块事实表；订单状态仍由 B 的 OrderGateway 独占维护。"""
from sqlalchemy import CheckConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class OperationLog(Base):
    __tablename__ = "fulfillment_operations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    actor_uid: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    order_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))


class Notification(Base):
    __tablename__ = "fulfillment_notifications"
    __table_args__ = (UniqueConstraint("order_id", "uid", "type"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    uid: Mapped[str] = mapped_column(String(100), index=True)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))


class ReviewOpening(Base):
    __tablename__ = "fulfillment_review_openings"
    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    fact_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class ConsumerReceipt(Base):
    __tablename__ = "fulfillment_event_receipts"
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class Review(Base):
    __tablename__ = "fulfillment_reviews"
    __table_args__ = (UniqueConstraint("order_id", "reviewer_uid"),
                      CheckConstraint("rating >= 1 AND rating <= 5"))
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    reviewer_uid: Mapped[str] = mapped_column(String(100))
    reviewee_uid: Mapped[str] = mapped_column(String(100), index=True)
    reviewer_role: Mapped[str] = mapped_column(String(20))
    rating: Mapped[int] = mapped_column(Integer)
    tags: Mapped[list] = mapped_column(JSON)
    comment: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[str] = mapped_column(String(40), index=True)


TABLES = [model.__table__ for model in (OperationLog, Notification, ReviewOpening, ConsumerReceipt, Review)]
