"""钱包路由（F8）：余额、充值、提现、流水查询（v1 钱包闭环）。

鉴权说明：F1 JWT 尚未接入，当前以请求头 X-User-Id 作为开发占位身份，
F1 接入后统一替换为 JWT 依赖，路由与业务代码不变（Q-05）。
"""

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ....database import get_db
from .. import query as ledger_query
from ..core import wallet_core
from ..core.wallet_core import InsufficientBalanceError
from ..schemas import (
    BalanceResponse,
    LedgerPage,
    RechargeRequest,
    RechargeResponse,
    WithdrawRequest,
    WithdrawResponse,
)
from ..services import recharge as recharge_service
from ..services import withdraw as withdraw_service

router = APIRouter(prefix="/api/wallet", tags=["finance: F8 钱包"])


def _uid(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    """开发占位身份：F1 JWT 接入后替换为 Depends 鉴权依赖。"""
    if not x_user_id:
        raise HTTPException(
            status_code=401, detail="未登录：缺少 X-User-Id（F1 接入后由 JWT 提供）"
        )
    return x_user_id


@router.get("/balance", response_model=BalanceResponse)
def balance(db: Session = Depends(get_db), uid: str = Depends(_uid)) -> BalanceResponse:
    """FR1 余额查询：返回可用/冻结两项余额（v1 冻结恒为 0）。"""
    available, frozen = wallet_core.get_balance(db, uid)
    return BalanceResponse(available_cent=available, frozen_cent=frozen)


@router.post("/recharge", response_model=RechargeResponse)
def recharge_create(
    request: RechargeRequest, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> RechargeResponse:
    """FR7 发起充值（原型约定 POST /api/wallet/recharge）：生成充值单并调起渠道支付。"""
    return recharge_service.create_recharge(db, uid, request)


@router.post("/recharge/callback")
def recharge_callback(payload: dict, db: Session = Depends(get_db)) -> dict:
    """FR7 渠道回调：验签/防重放由适配器完成，幂等入账；重复回调只入账一次。

    回调由渠道服务器发起，不走 JWT 鉴权，鉴权依赖渠道验签（mock 渠道无验签）。
    """
    try:
        order = recharge_service.handle_callback(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if order is None:
        raise HTTPException(status_code=404, detail="充值单不存在")
    return order


@router.get("/recharge/{out_trade_no}")
def recharge_query(
    out_trade_no: str, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> dict:
    """FR7.5 充值单状态查询，仅本人可见。"""
    order = recharge_service.query_recharge(db, uid, out_trade_no)
    if order is None:
        raise HTTPException(status_code=404, detail="充值单不存在")
    return order


@router.post("/withdraw", response_model=WithdrawResponse)
def withdraw_apply(
    request: WithdrawRequest, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> WithdrawResponse:
    """FR8 申请提现：校验并扣款（v1 无冻结字段，直接扣可用余额）→ 处理中 → 模拟到账。"""
    try:
        return withdraw_service.apply_withdraw(db, uid, request)
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/withdraw/{withdraw_no}")
def withdraw_query(
    withdraw_no: str, db: Session = Depends(get_db), uid: str = Depends(_uid)
) -> dict:
    """FR8 提现单状态查询（processing 超模拟打款延迟后自动流转 done）。"""
    order = withdraw_service.query_withdraw(db, uid, withdraw_no)
    if order is None:
        raise HTTPException(status_code=404, detail="提现单不存在")
    return order


@router.get("/ledger", response_model=LedgerPage)
def ledger(
    page: int = 1,
    page_size: int = 20,
    biz_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    uid: str = Depends(_uid),
) -> LedgerPage:
    """FR9 流水查询：分页 ≤100、组合条件（类型/时间范围），仅本人可见。"""
    try:
        return ledger_query.query_ledger(
            db, uid, page, page_size, biz_type=biz_type, start=start, end=end
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"查询参数错误：{exc}") from exc