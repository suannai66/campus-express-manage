"""流水查询（团队接口约定 v1.1 第 10 节）：GET /api/wallet/transactions。

- 分页：page 从 1 开始，pageSize 默认 20、最大 100；
- type 过滤：recharge / payment / refund / settlement / withdrawal（枚举区分大小写）；
- 权限约束：查询强制限定 uid 本人，不存在越权路径（Q-05）；
- 读模型与写模型分离：查询逻辑不进入资金事务路径（core/wallet_core.py）。
"""

from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, iso_utc
from .models import Ledger


def query_transactions(
    db: Session,
    uid: str,
    page: int = 1,
    page_size: int = 20,
    *,
    type: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """流水分页查询：items 字段见 schemas.TransactionItem（约定第 10 节）。"""
    if page < 1 or not 1 <= page_size <= config.LEDGER_PAGE_SIZE_MAX:
        raise ValueError("分页参数超出范围")
    stmt = select(Ledger).where(Ledger.uid == uid)
    if type:
        stmt = stmt.where(Ledger.biz_type == type)
    if start:
        stmt = stmt.where(
            Ledger.created_at
            >= datetime.combine(date.fromisoformat(start), time.min, tzinfo=timezone.utc)
        )
    if end:
        stmt = stmt.where(
            Ledger.created_at
            <= datetime.combine(date.fromisoformat(end), time.max, tzinfo=timezone.utc)
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Ledger.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "transactionId": str(row.id),
                "type": row.biz_type,
                "direction": "in" if row.delta > 0 else "out",
                "amount": abs(row.delta),
                "balanceAfter": row.balance_after,
                "orderId": None,  # v1 仅有钱包类流水；订单资金流后续迭代补齐
                "referenceId": row.idempotency_key,
                "createdAt": iso_utc(row.created_at),
            }
            for row in rows
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
    }