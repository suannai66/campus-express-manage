"""钱包路由（F8，团队接口约定 v1.1 第 10 节）：余额、充值（confirm 演示）、提现、流水。

身份：复用公共身份依赖 orders.integrations.current_identity（约定第 6 节：所有模块
使用同一后端依赖，不信任客户端自报身份；A 的 F1 落地后统一切换，路由与业务代码不变）。
资金写入要求 Idempotency-Key 请求头（约定第 12 节）：同键同请求返回原结果（保留原 201），
同键不同内容 409 IDEMPOTENCY_CONFLICT，并发同键 409 REQUEST_IN_PROGRESS。
"""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ....common import Key, fail
from ....database import get_db
from ...orders.integrations import current_identity as current
from .. import query as ledger_query
from ..core import wallet_core
from ..core.wallet_core import InsufficientBalanceError
from ..schemas import (
    RechargeConfirmResponse,
    RechargeRequest,
    RechargeResponse,
    TransactionsPage,
    WalletResponse,
    WithdrawalQueryResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from ..services import recharge as recharge_service
from ..services import withdraw as withdraw_service

router = APIRouter(prefix="/api/wallet", tags=["finance: F8 钱包"])

TRANSACTION_TYPES = Literal["recharge", "payment", "refund", "settlement", "withdrawal"]


@router.get("", response_model=WalletResponse)
def wallet(db: Session = Depends(get_db), user=Depends(current)) -> WalletResponse:
    """GET /api/wallet：统一虚拟账户余额（约定：balance 为整数分，demo 恒 true）。"""
    return WalletResponse(balance=wallet_core.get_balance(db, user.uid))


@router.post("/recharge", response_model=RechargeResponse, status_code=201)
def recharge_create(
    request: RechargeRequest,
    idempotency_key: Key,
    db: Session = Depends(get_db),
    user=Depends(current),
) -> RechargeResponse:
    """POST /api/wallet/recharge：创建充值单（pending），返回 201。

    Idempotency-Key 必填（约定：所有资金写入须 Idempotency-Key）。
    """
    return recharge_service.create_recharge(db, user.uid, request, idempotency_key)


@router.post("/recharge/{recharge_id}/confirm", response_model=RechargeConfirmResponse)
def recharge_confirm(
    recharge_id: str, db: Session = Depends(get_db), user=Depends(current)
) -> RechargeConfirmResponse:
    """POST /api/wallet/recharge/{rechargeId}/confirm：演示专用确认入账（幂等）。

    真实渠道回调本期不实现（约定 v1.1）；关闭演示模式时本接口应返回 404（后续迭代）。
    """
    result = recharge_service.handle_confirm(db, user.uid, recharge_id)
    if result is None:
        fail(404, "NOT_FOUND", "充值单不存在")
    return result


@router.post("/withdraw", response_model=WithdrawResponse, status_code=201)
def withdraw_apply(
    request: WithdrawRequest,
    idempotency_key: Key,
    db: Session = Depends(get_db),
    user=Depends(current),
) -> WithdrawResponse:
    """POST /api/wallet/withdraw：扣可用余额 + 建单同事务；后台任务 ≥3 秒标记 succeeded。

    Idempotency-Key 必填（约定：所有资金写入须 Idempotency-Key）。
    """
    try:
        return withdraw_service.apply_withdraw(db, user.uid, request, idempotency_key)
    except InsufficientBalanceError as exc:
        fail(422, "VALIDATION_ERROR", "提现金额超过可用余额", {"amount": f"可用余额不足 {exc.have_cent} 分"})


@router.get("/withdrawals/{withdraw_id}", response_model=WithdrawalQueryResponse)
def withdrawal_query(
    withdraw_id: str, db: Session = Depends(get_db), user=Depends(current)
) -> WithdrawalQueryResponse:
    """GET /api/wallet/withdrawals/{withdrawId}：仅本人可见。"""
    result = withdraw_service.query_withdrawal(db, user.uid, withdraw_id)
    if result is None:
        fail(404, "NOT_FOUND", "提现单不存在")
    return result


@router.get("/transactions", response_model=TransactionsPage)
def transactions(
    page: int = 1,
    pageSize: int = 20,
    type: TRANSACTION_TYPES | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    user=Depends(current),
) -> TransactionsPage:
    """GET /api/wallet/transactions：分页（pageSize ≤100）、type/时间过滤，仅本人可见。"""
    try:
        return ledger_query.query_transactions(
            db, user.uid, page, pageSize, type=type, start=start, end=end
        )
    except ValueError as exc:
        fail(422, "VALIDATION_ERROR", f"查询参数错误：{exc}")
