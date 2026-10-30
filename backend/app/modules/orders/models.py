"""F3 自有数据；金额统一以分存储，不依赖其他模块的表。"""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("publisher_uid", "request_key"),
        CheckConstraint("base_fee_cents >= 0 AND tip_cents >= 0 AND amount_cents = base_fee_cents + tip_cents"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publisher_uid: Mapped[str] = mapped_column(String(100), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    company: Mapped[str] = mapped_column(String(30))
    pickup_code: Mapped[str] = mapped_column(String(50))
    station: Mapped[str] = mapped_column(String(60))
    size: Mapped[str] = mapped_column(String(10))
    weight_kg: Mapped[str] = mapped_column(String(10))
    # 沿用 SQLite 旧列，避免已发布订单需要破坏性迁移；新订单只写完整地址。
    address: Mapped[str] = mapped_column("building", String(200))
    legacy_room: Mapped[str] = mapped_column("room", String(30), default="")
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(String(200), default="")
    base_fee_cents: Mapped[int] = mapped_column(Integer)
    tip_cents: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    pricing_source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="awaiting_payment", index=True)
    paid_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @property
    def delivery_address(self):
        return " ".join(part for part in (self.address, self.legacy_room) if part)


class PaymentReceipt(Base):
    __tablename__ = "order_payment_receipts"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    payment_id: Mapped[str] = mapped_column(String(100), unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrderStatusReceipt(Base):
    """C 状态事件在 B 模块的幂等回执，不接管 C 的履约表。"""
    __tablename__ = "order_status_receipts"
    __table_args__ = (UniqueConstraint("order_id", "version"),)

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
