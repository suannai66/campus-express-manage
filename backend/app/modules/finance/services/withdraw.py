"""F8 提现编排（团队接口约定 v1.1 第 10 节）。

- 申请：校验金额 → 扣可用余额（条件更新）→ 流水与提现记录同事务写入（第 11 节）；
- HTTP 幂等（第 12 节）：Idempotency-Key 必填，(uid,operation,key) 持久化请求摘要与
  结果；同键同请求返回原结果，同键不同内容 409 IDEMPOTENCY_CONFLICT（由公共组件
  app.common.replay/remember 提供）；并发同键由提现单主键/幂等表唯一约束拦截
  → 409 REQUEST_IN_PROGRESS；
- 到账：应用后台演示任务最早 3 秒后标记 succeeded，重启后继续处理 processing 记录；
- 失败：记录 failed，仅一次退回扣除金额（fail_reason 预留，流程后置）。
"""

import hashlib
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ....common import remember, replay
from ....database import SessionLocal
from .. import config
from ..core import wallet_core
from ..models import WithdrawOrder
from ..schemas import WithdrawRequest, WithdrawResponse

OPERATION = "wallet-withdraw"


def _new_id(uid: str, idempotency_key: str) -> str:
    """提现单号：由 (uid, 幂等键) 派生固定单号（重复请求返回同一单，并发同键主键冲突兜底）。"""
    digest = hashlib.sha256(f"{uid}:{idempotency_key}".encode()).hexdigest()[:16]
    return f"WD{digest}"


def _apply_dict(order: WithdrawOrder) -> dict:
    return {
        "withdrawId": order.withdraw_no,
        "amount": order.amount_cent,
        "status": order.status,
    }


def apply_withdraw(
    db: Session, uid: str, request: WithdrawRequest, idempotency_key: str
) -> WithdrawResponse:
    """POST /api/wallet/withdraw：扣款 + 建单同一事务，201；余额不足抛 InsufficientBalanceError。

    同幂等键同请求返回首次结果（只扣一次）；同键不同内容由 replay 抛 409。
    """
    payload = {"amount": request.amount}
    with db.begin():
        existing_result = replay(db, uid, OPERATION, idempotency_key, payload)
        if existing_result is not None:
            return existing_result
        withdraw_id = _new_id(uid, idempotency_key)
        existing = db.get(WithdrawOrder, withdraw_id)
        if existing is not None:
            return _apply_dict(existing)
        wallet_core.debit(db, uid, request.amount, f"{uid}:{withdraw_id}", "withdrawal")
        order = WithdrawOrder(withdraw_no=withdraw_id, uid=uid, amount_cent=request.amount)
        db.add(order)
        db.flush()  # 应用 status 默认值；并发同键由主键唯一约束在此拦截（→409）
        result = _apply_dict(order)
        remember(db, uid, OPERATION, idempotency_key, payload, result)
        return result


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
