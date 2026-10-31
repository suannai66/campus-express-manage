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
    TODO(迭代·报价) 按约定第 10 节演示路线费率实现查表与报价。
    """
    raise NotImplementedError("TODO(迭代·报价): 实现定价")


def prepay(uid: str, request: PrepayRequest) -> PrepayResponse:
    """余额支付（POST /api/pay/prepay）：同 paymentRequestId 只创建一个支付记录，重试返回原结果。

    成功同步返回 succeeded 并发布 payment.succeeded；确定失败返回 failed（code）并发布 payment.failed。
    TODO(迭代·冻结) 经只读 OrderGateway 校验预占/发布者/金额，不直接修改订单。
    """
    raise NotImplementedError("TODO(迭代·冻结): 实现余额支付")


def settle_order(command: SettleCommand) -> None:
    """order.completed 结算：按订单快照结算，取货员入账 + 平台佣金留账（仅 baseFee 计佣）。"""
    raise NotImplementedError("TODO(迭代·结算): 实现结算编排")


def refund_order(command: RefundCommand) -> None:
    """order.cancelled 退款：全额退回发布者钱包，不收佣金。"""
    raise NotImplementedError("TODO(迭代·退款): 实现退款编排")
