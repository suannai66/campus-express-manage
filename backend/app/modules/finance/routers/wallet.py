"""钱包路由（F8）：余额、充值、提现、流水查询。JWT 鉴权依赖 F1 接入后统一处理（Q-05）。"""

from fastapi import APIRouter

from ..schemas import (
    BalanceResponse,
    LedgerPage,
    RechargeRequest,
    RechargeResponse,
    WithdrawRequest,
    WithdrawResponse,
)

router = APIRouter(prefix="/api/wallet", tags=["finance: F8 钱包"])


@router.get("/balance", response_model=BalanceResponse)
async def balance() -> BalanceResponse:
    """FR1 余额查询：返回可用/冻结两项余额。"""
    raise NotImplementedError("TODO(迭代7): 接入余额查询")


@router.post("/recharge", response_model=RechargeResponse)
async def recharge(request: RechargeRequest) -> RechargeResponse:
    """FR7 发起充值（原型约定 POST /api/wallet/recharge）：生成充值单并调起渠道支付。"""
    raise NotImplementedError("TODO(迭代7): 接入充值编排")


@router.post("/recharge/callback")
async def recharge_callback() -> None:
    """FR7 渠道回调：验签/防重放由适配器完成，幂等入账；重复回调只入账一次。

    注意：回调由渠道服务器发起，不走 JWT 鉴权，鉴权依赖渠道验签（Q-05 例外项，需团队确认）。
    TODO(迭代7) 路由收到原始报文后交给 RechargeAppService.handle_callback。
    """
    raise NotImplementedError("TODO(迭代7): 接入充值回调")


@router.get("/recharge/{out_trade_no}")
async def recharge_query(out_trade_no: str) -> dict:
    """FR7.5 充值单状态查询。"""
    raise NotImplementedError("TODO(迭代7): 接入充值单查询")


@router.post("/withdraw", response_model=WithdrawResponse)
async def withdraw(request: WithdrawRequest) -> WithdrawResponse:
    """FR8 申请提现：校验并冻结 → 处理中 → 模拟渠道到账 → 扣冻结；失败解冻。"""
    raise NotImplementedError("TODO(迭代7): 接入提现编排")


@router.get("/withdraw/{withdraw_no}")
async def withdraw_query(withdraw_no: str) -> dict:
    """FR8 提现单状态查询。"""
    raise NotImplementedError("TODO(迭代7): 接入提现单查询")


@router.get("/ledger", response_model=LedgerPage)
async def ledger(
    page: int = 1,
    page_size: int = 20,
) -> LedgerPage:
    """FR9 流水查询：分页 ≤100、组合条件、身份视角过滤，仅本人可见。"""
    raise NotImplementedError("TODO(迭代7): 接入流水查询")
