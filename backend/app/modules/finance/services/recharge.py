"""F8 充值编排（FR7）：充值单 → 调起渠道支付 → 回调验签 → 幂等入账 → 更新充值单状态。

渠道差异封装在 channels/ 适配器之后（EV-1），本流程只依赖 ChannelPort 抽象。
"""

from ..schemas import RechargeRequest, RechargeResponse


def create_recharge(uid: str, request: RechargeRequest) -> RechargeResponse:
    """FR7.2 发起充值单并调起渠道支付；渠道由 config.CHANNEL_ACTIVE 决定（模拟收银台默认兜底）。"""
    raise NotImplementedError("TODO(迭代7): 实现充值发起")


def handle_callback(channel: str, payload: dict) -> None:
    """FR7.3 渠道回调处理：适配器验签/防重放/归一化为 InternalPaymentResult → 幂等入账。

    幂等键 <channel>:<out_trade_no>；重复回调只入账一次，返回首次结果（FR7.3）。
    支付失败或超时未支付：充值单关闭，不改变余额（FR7.4）。
    """
    raise NotImplementedError("TODO(迭代7): 实现充值回调")


def query_recharge(uid: str, out_trade_no: str) -> dict:
    """FR7.5 充值单状态查询。"""
    raise NotImplementedError("TODO(迭代7): 实现充值单查询")
