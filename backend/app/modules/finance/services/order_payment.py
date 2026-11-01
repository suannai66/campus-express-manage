"""F7 用例编排（团队接口约定 v1.1）：报价、余额支付、结算、退款。

资金状态变更一律经 core/wallet_core.py；事件命令与幂等键派生见 core/event_acl.py。
支付冻结、取消解冻与完结结算已实现，跨模块通知通过公共 outbox。
"""

from sqlalchemy.orm import Session

from ..core.event_acl import RefundCommand, SettleCommand
from ..schemas import PrepayRequest


def quote(draft: dict) -> dict:
    """应用内定价能力 PricingService.quote（约定第 10 节：不提供 HTTP 自调用）。

    输入：stationId、deliveryAreaId、size、weight（十进制字符串 kg）、tip（整数分）；
    输出 Quote：quoteId、pricingVersion、baseFee、tip、amount、commissionRateBps、expiresAt、demo。
    按团队第 10 节演示路线费率计算，不产生资金写入。
    """
    from .pricing import PricingService

    return PricingService.quote(draft)


def prepay(db: Session, uid: str, request: PrepayRequest, idempotency_key: str) -> dict:
    """顶层支付冻结入口，同事务保存支付事实与公共 outbox 事件。"""
    from .payment import prepay as pay

    return pay(db, uid, request, idempotency_key)


def settle_order(db: Session, command: SettleCommand) -> dict:
    """按订单快照消费冻结额；消费者共享事务，不提交。"""
    from .settlement import settle_order as settle

    return settle(db, command)


def refund_order(db: Session, command: RefundCommand) -> dict:
    """共享事务内执行全额解冻，不自行提交。"""
    from .refund import refund_order as refund

    return refund(db, command)
