"""钱包路由（F8，团队接口约定 v1.1 第 10 节）：余额、充值（confirm 演示）、提现、流水。

鉴权说明：F1 JWT 尚未接入，当前以请求头 X-User-Id 作为开发占位身份，
F1 接入后统一替换为 JWT 依赖，路由与业务代码不变（Q-05）。
资金写入支持 Idempotency-Key 请求头（同键重复请求返回原单）。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ....database import get_db
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


def _uid(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    """开发占位身份：F1 JWT 接入后替换为 Depends 鉴权依赖。"""
    if not x_user_id:
        raise HTTPException(
            status_code=401, detail="未登录：缺少 X-User-Id（F1 接入后由 JWT 提供）"
        )
    return x_user_id


def _idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    """资金写入幂等键（约定：所有资金写入须 Idempotency-Key；缺省时服务端生成随机单号）。"""
    return idempotency_key


@router.get("", response_model=WalletResponse)
def wallet(db: Session = Depends(get_db), uid: str = Depends(_uid)) -> WalletResponse:
    """GET /api/wallet：统一虚拟账户余额（约定：balance 为整数分，demo 恒 true）。"""
    return WalletResponse(balance=wallet_core.get_balance(db, uid))


@router.post("/recharge", response_model=RechargeResponse, status_code=201)
def recharge_create(
    request: RechargeRequest,
    idempotency_key: str | None = Depends(_idempotency_key),
    db: Session = Depends(get_db),
    uid: str = Depends(_uid),
) -> RechargeResponse:
    """POST /api/wallet/recharge：创建充值单（pending），返回 201。"""
    return recharge_service.create_recharge(db, uid, request, idempotency_key)


@router.post("/recharge/{recharge_id}/confirm", response_model=RechargeConfirmResponse)
def recharge_confirm(
    recharge_id: str, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> RechargeConfirmResponse:
    """POST /api/wallet/recharge/{rechargeId}/confirm：演示专用确认入账（幂等）。

    真实渠道回调本期不实现（约定 v1.1）；关闭演示模式时本接口应返回 404（后续迭代）。
    """
    result = recharge_service.handle_confirm(db, uid, recharge_id)
    if result is None:
        raise HTTPException(status_code=404, detail="充值单不存在")
    return result


@router.post("/withdraw", response_model=WithdrawResponse, status_code=201)
def withdraw_apply(
    request: WithdrawRequest,
    idempotency_key: str | None = Depends(_idempotency_key),
    db: Session = Depends(get_db),
    uid: str = Depends(_uid),
) -> WithdrawResponse:
    """POST /api/wallet/withdraw：扣可用余额 + 建单同事务；后台任务 ≥3 秒标记 succeeded。"""
    try:
        return withdraw_service.apply_withdraw(db, uid, request, idempotency_key)
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/withdrawals/{withdraw_id}", response_model=WithdrawalQueryResponse)
def withdrawal_query(
    withdraw_id: str, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> WithdrawalQueryResponse:
    """GET /api/wallet/withdrawals/{withdrawId}：仅本人可见。"""
    result = withdraw_service.query_withdrawal(db, uid, withdraw_id)
    if result is None:
        raise HTTPException(status_code=404, detail="提现单不存在")
    return result


@router.get("/transactions", response_model=TransactionsPage)
def transactions(
    page: int = 1,
    pageSize: int = 20,
    type: TRANSACTION_TYPES | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    uid: str = Depends(_uid),
) -> TransactionsPage:
    """GET /api/wallet/transactions：分页（pageSize ≤100）、type/时间过滤，仅本人可见。"""
    try:
        return ledger_query.query_transactions(
            db, uid, page, pageSize, type=type, start=start, end=end
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"查询参数错误：{exc}") from exc