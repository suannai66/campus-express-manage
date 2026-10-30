"""F8 提现编排（团队接口约定 v1.1 第 10 节）。

- 申请：校验金额 → 扣可用余额（条件更新）→ 流水与提现记录同事务写入（第 11 节）；
- 到账：应用后台演示任务最早 3 秒后标记 succeeded，重启后继续处理 processing 记录；
- 失败：记录 failed，仅一次退回扣除金额（fail_reason 预留，流程后置）。
"""

import hashlib
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....database import SessionLocal
from .. import config
from ..core import wallet_core
from ..models import WithdrawOrder
from ..schemas import WithdrawRequest, WithdrawResponse


def _new_id(uid: str, idempotency_key: str | None) -> str:
    """提现单号：请求带 Idempotency-Key 时派生固定单号（重复请求返回同一单），否则随机。"""
    if idempotency_key:
        digest = hashlib.sha256(f"{uid}:{idempotency_key}".encode()).hexdigest()[:16]
        return f"WD{digest}"
    return f"WD{uuid.uuid4().hex[:16]}"


def apply_withdraw(
    db: Session, uid: str, request: WithdrawRequest, idempotency_key: str | None = None
) -> WithdrawResponse:
    """POST /api/wallet/withdraw：扣款 + 建单同一事务；余额不足抛 InsufficientBalanceError。"""
    withdraw_id = _new_id(uid, idempotency_key)
    with db.begin():
        existing = db.get(WithdrawOrder, withdraw_id)
        if existing is not None:
            return WithdrawResponse(
                withdrawId=existing.withdraw_no,
                amount=existing.amount_cent,
                status=existing.status,
            )
        wallet_core.debit(db, uid, request.amount, f"{uid}:{withdraw_id}", "withdrawal")
        db.add(WithdrawOrder(withdraw_no=withdraw_id, uid=uid, amount_cent=request.amount))
    return WithdrawResponse(withdrawId=withdraw_id, amount=request.amount, status="processing")


def query_withdrawal(db: Session, uid: str, withdraw_id: str) -> dict | None:
    """GET /api/wallet/withdrawals/{withdrawId}：仅本人可见，只读不写。"""
    order = db.get(WithdrawOrder, withdraw_id)
    if order is None or order.uid != uid:
        return None
    return {
        "withdrawId": order.withdraw_no,
        "amount": order.amount_cent,
        "status": order.status,
    }


def process_due_withdrawals() -> int:
    """单轮扫描：processing 且超过模拟到账延迟的记录标记 succeeded（后台任务循环调用）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.WITHDRAW_SETTLE_SECONDS)
    with SessionLocal() as session, session.begin():
        due = session.scalars(
            select(WithdrawOrder).where(
                WithdrawOrder.status == "processing", WithdrawOrder.created_at <= cutoff
            )
        ).all()
        for order in due:
            order.status = "succeeded"
        return len(due)


def start_withdraw_processor() -> threading.Thread:
    """启动后台演示任务（daemon 线程，每秒扫描）：重启后自动继续处理 processing 记录。

    TODO(联调) A 建立统一应用启动入口后，随其迁移到该入口。
    """
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                process_due_withdrawals()
            except Exception:
                pass  # 演示任务容错：单轮失败不影响后续轮次
            stop.wait(config.WITHDRAW_PROCESS_INTERVAL_SECONDS)

    thread = threading.Thread(target=loop, name="finance-withdraw-processor", daemon=True)
    thread.start()
    return thread