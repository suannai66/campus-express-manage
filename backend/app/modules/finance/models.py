"""资金表 ORM 模型（阶段 3.3 调整 C + 2026-10-30 SQLite 口径修订）。

继承团队公共基类 app.database.Base；金额一律以"分"整数存储（FR1.3）。
正确性依赖：事务 + ledger 幂等键唯一索引（Q-03/Q-04）；SQLite 写事务串行化，
无需显式行锁（C-03 修订）。

冻结字段：account.frozen_cent 保存冻结金额（整数分），初始为 0，不计入可用余额。
本次包含支付冻结及其流水，解冻和结算后续实现。
已有数据库执行 python -m app.modules.finance.migrate_frozen 升级，保留原有数据。
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Index, text, BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base

# ---------- 资金双表 ----------


class Account(Base):
    """统一虚拟账户（FR1.2）：用户可同时作为客户与取货员，共用同一账户。

    available_cent 为可用余额；frozen_cent 为冻结余额，二者独立存储。
    """

    __tablename__ = "account"

    uid: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户 ID（F1 UID）")
    available_cent: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="可用余额（分），不为负"
    )
    frozen_cent: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0",
        comment="冻结余额（分），不计入可用余额，初始为 0",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="版本号，审计用途（SQLite 写串行化下不承担并发控制）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class Ledger(Base):
    """资金流水（FR1.4）：每次余额变动必有流水，与余额更新同事务（Q-03）。

    (idempotency_key, biz_type) 唯一索引是幂等兜底：重复请求直接命中首次结果（Q-04）。
    """

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="账户所有者")
    biz_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="流水类型（团队接口约定 v1.1 枚举）：v1 为 recharge / withdrawal；payment/refund/settlement 后续迭代加入"
    )
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="变动额（分），正入负出")
    balance_after: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="变动后余额快照（分），便于对账"
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="幂等键（派生规则见 core/event_acl.py）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("idempotency_key", "biz_type", name="uq_ledger_idempotency"),
    )


# ---------- 业务单表（独立于资金双表） ----------


class RechargeOrder(Base):
    """充值单（FR7）：v1 走演示路径（create → confirm 幂等入账）；真实回调后续迭代接入。"""

    __tablename__ = "recharge_order"

    out_trade_no: Mapped[str] = mapped_column(String(64), primary_key=True, comment="充值单号（对外为 rechargeId）")
    uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_cent: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="充值金额（分）")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, comment="mock / alipay_sandbox")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", comment="pending / succeeded / failed / closed"
    )
    channel_txn_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="渠道流水号")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WithdrawOrder(Base):
    """提现单（FR8，团队接口约定 v1.1）：申请 → 校验并扣可用余额（同事务）→ processing → 后台任务 ≥3s 标记 succeeded；失败退回（后置）。"""

    __tablename__ = "withdraw_order"

    withdraw_no: Mapped[str] = mapped_column(String(64), primary_key=True, comment="提现单号（对外为 withdrawId）")
    uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_cent: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="提现金额（分）")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing", comment="processing / succeeded / failed"
    )
    fail_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="打款失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

class Payment(Base):
    """支付事实与待投递事件同事务保存，事件交由 A 的投递组件接入。"""
    __tablename__ = "finance_payments"
    __table_args__ = (
        Index("uq_finance_successful_order", "order_id", unique=True,
              sqlite_where=text("status = 'succeeded'")),
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    request_id: Mapped[str] = mapped_column(String(100), unique=True)
    payer_uid: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    funds_status: Mapped[str] = mapped_column(String(20))  # frozen / none；后续 settled/refunded
    event: Mapped[dict] = mapped_column(JSON)
    event_status: Mapped[str] = mapped_column(String(20), default="pending")
