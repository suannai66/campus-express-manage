"""统一订单主表；旧演示表保留，只供历史数据迁移核对。"""
from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class Order(Base):
    __tablename__ = "orders_v2"
    __table_args__ = (CheckConstraint("amount = base_fee + tip AND base_fee >= 0 AND tip >= 0"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    publisher_uid: Mapped[str] = mapped_column(String(100), index=True)
    courier_uid: Mapped[str | None] = mapped_column(String(100), index=True)
    company: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(50))
    station_id: Mapped[str] = mapped_column(String(100), index=True)
    area_id: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(String(200))
    size: Mapped[str] = mapped_column(String(10))
    weight: Mapped[str] = mapped_column(String(20))
    expected_at: Mapped[str] = mapped_column(String(40), index=True)
    note: Mapped[str] = mapped_column(String(200))
    base_fee: Mapped[int] = mapped_column(Integer)
    tip: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)
    commission_bps: Mapped[int] = mapped_column(Integer)
    pricing_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid")
    refund_status: Mapped[str] = mapped_column(String(20), default="none")
    payment_request_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    payer_uid: Mapped[str | None] = mapped_column(String(100))
    payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    refund_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    pickup_failures: Mapped[int] = mapped_column(Integer, default=0)
    lock_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))
    demo: Mapped[bool] = mapped_column(Boolean)
