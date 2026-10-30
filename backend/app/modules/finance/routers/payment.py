"""支付路由（F7）：定价报价 + 下单冻结。JWT 鉴权依赖 F1 接入后统一处理（Q-05）。"""

from fastapi import APIRouter

from ..schemas import FreezeRequest, FreezeResponse, QuoteRequest, QuoteResponse

router = APIRouter(prefix="/api/pay", tags=["finance: F7 支付"])


@router.post("/quote", response_model=QuoteResponse)
async def quote(request: QuoteRequest) -> QuoteResponse:
    """FR2 订单定价（原型约定 POST /api/pay/quote，F3 创建订单时调用）。

    金额 = 基础运费（距离/重量查表）+ 小费；低于起送价拒绝。
    TODO(迭代7) 调用 OrderPaymentAppService.quote，金额以服务端计算为准。
    """
    raise NotImplementedError("TODO(迭代7): 接入定价编排")


@router.post("/freeze", response_model=FreezeResponse)
async def freeze(request: FreezeRequest) -> FreezeResponse:
    """FR3 下单冻结：可用减、冻结增（原子）；余额不足拒绝，订单不进大厅。

    幂等键 <uid>:<order_id>；冻结成功后发布"支付成功 = 冻结成功"事件供 F3 订阅（R4）。
    TODO(迭代7) 调用 OrderPaymentAppService.pay_and_freeze。
    """
    raise NotImplementedError("TODO(迭代7): 接入冻结编排")
