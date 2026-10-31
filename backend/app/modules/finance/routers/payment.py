"""支付路由（F7，团队接口约定 v1.1 第 10 节）：余额支付与支付结果查询（接口骨架）。

TODO(迭代·冻结) 依赖 OrderGateway（B 的只读快照）与账户冻结字段（v2），当前未注册；
报价为应用内能力 PricingService.quote（约定不提供 HTTP 自调用），实现见 core/fee_util.py。
"""

from fastapi import APIRouter

from ..schemas import PrepayRequest, PrepayResponse

router = APIRouter(prefix="/api/pay", tags=["finance: F7 支付"])


@router.post("/prepay", response_model=PrepayResponse)
async def prepay(request: PrepayRequest) -> PrepayResponse:
    """余额支付：B 完成支付预占后由前端调用。

    - 经只读 OrderGateway 验证预占、发布者与金额，不直接修改订单（约定第 8 节）；
    - 同 paymentRequestId 只创建一个支付记录，重试返回原结果（约定第 10 节）；
    - 成功同步返回 succeeded 并发布 payment.succeeded；确定失败返回 failed（code）并发布 payment.failed。
    """
    raise NotImplementedError("TODO(迭代·冻结): 实现余额支付（依赖 OrderGateway 与冻结字段）")


@router.get("/payments/{payment_id}")
async def payment_query(payment_id: str) -> dict:
    """支付结果查询，仅付款人（约定：成功 code=null）。"""
    raise NotImplementedError("TODO(迭代·冻结): 实现支付结果查询")