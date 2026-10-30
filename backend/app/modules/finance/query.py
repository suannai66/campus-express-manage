"""流水查询（FR9）：分页 ≤100、组合条件；仅本人可见，越权拒绝（Q-05）。

读模型与写模型分离：查询逻辑不进入资金事务路径（core/wallet_core.py）。
"""

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import Ledger


def query_ledger(
    db: Session,
    uid: str,
    page: int = 1,
    page_size: int = 20,
    *,
    biz_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """FR9 流水分页查询。

    组合条件：流水类型 / 时间范围（日期 YYYY-MM-DD，含当日）；
    权限约束：查询强制限定 uid 本人，不存在越权路径。
    """
    page_size = min(max(page_size, 1), config.LEDGER_PAGE_SIZE_MAX)
    stmt = select(Ledger).where(Ledger.uid == uid)
    if biz_type:
        stmt = stmt.where(Ledger.biz_type == biz_type)
    if start:
        stmt = stmt.where(
            Ledger.created_at >= datetime.combine(date.fromisoformat(start), time.min)
        )
    if end:
        stmt = stmt.where(
            Ledger.created_at <= datetime.combine(date.fromisoformat(end), time.max)
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Ledger.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "biz_type": row.biz_type,
                "delta": row.delta,
                "balance_after": row.balance_after,
                "idempotency_key": row.idempotency_key,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }