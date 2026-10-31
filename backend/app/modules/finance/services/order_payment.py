"""F7 用例编排（团队接口约定 v1.1）：报价、余额支付、结算、退款。

资金状态变更一律经 core/wallet_core.py；事件命令与幂等键派生见 core/event_acl.py。
TODO(迭代·冻结) 冻结字段（v2）与 OrderGateway（B 的只读快照）接入后实现。
"""

from ..core.event_acl import RefundCommand, SettleCommand
from ..schemas import PrepayRequest, PrepayResponse


def quote(draft: dict) -> dict:
    """应用内定价能力 PricingService.quote（约定第 10 节：不提供 HTTP 自调用）。

    输入：stationId、deliveryAreaId、size、weight（十进制字符串 kg）、tip（整数分）；
    输出 Quote：quoteId、pricingVersion、baseFee、tip、amount、commissionRateBps、expiresAt、demo。
    按团队第 10 节演示路线费率计算，不产生资金写入。
    """
    from .pricing import PricingService
    return PricingService.quote(draft)


def prepay(db, uid: str, request: PrepayRequest, idempotency_key: str) -> PrepayResponse:
    """顶层支付冻结入口，订单状态通知等待公共投递器接入。"""
    from .payment import prepay as pay
    return pay(db, uid, request, idempotency_key)


def settle_order(command: SettleCommand) -> None:
    """order.completed 结算：按订单快照结算，取货员入账 + 平台佣金留账（仅 baseFee 计佣）。"""
    raise NotImplementedError("TODO(迭代·结算): 实现结算编排")


def refund_order(command: RefundCommand) -> None:
    """order.cancelled 退款：全额退回发布者钱包，不收佣金。"""
    raise NotImplementedError("TODO(迭代·退款): 实现退款编排")
