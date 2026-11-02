"""事件防腐映射（EV-3，借用 A）：外部事件报文 → 内部命令 + 幂等键派生，单点收敛。

B/C 的字段契约一旦变化，只改本文件；事件处理器与业务服务不接触外部字段名。
事件 envelope 与类型见《团队接口约定》v1.1 第 12 节：
{eventId, type, occurredAt, orderId, aggregateType, aggregateId, version, payload}。

幂等与唯一约束（约定第 12 节）：
- 事件消费 = <consumer>:<eventId>（本地事务内保存去重记录）
- 订单结算 = <orderId>:settle（至多一次）
- 订单退款 = <orderId>:refund（至多一次）
- 充值 confirm = <channel>:<rechargeId>
- 提现 = <uid>:<withdrawId>
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SettleCommand:
    """order.completed 映射出的结算命令。"""

    idempotency_key: str  # <orderId>:settle
    order_id: str
    publisher_uid: str
    courier_uid: str
    amount_cent: int
    base_fee_cent: int
    commission_rate_bps: int  # 订单快照费率（约定：按快照结算，不使用届时新费率）


@dataclass(frozen=True)
class RefundCommand:
    """order.cancelled 映射出的退款命令。"""

    idempotency_key: str  # <orderId>:refund
    order_id: str
    publisher_uid: str
    payment_id: str | None  # 未支付取消为 null
    amount_cent: int


def completed_to_command(event: dict) -> SettleCommand:
    body = event["payload"]
    return SettleCommand(
        idempotency_key=f"{event['orderId']}:settle",
        order_id=event["orderId"],
        publisher_uid=body["publisherUid"],
        courier_uid=body["courierUid"],
        amount_cent=body["amount"],
        base_fee_cent=body["baseFee"],
        commission_rate_bps=body["commissionRateBps"],
    )


def cancelled_to_command(event: dict) -> RefundCommand:
    """完整且已验证的 order.cancelled envelope 映射为退款命令。"""
    body = event["payload"]
    return RefundCommand(
        idempotency_key=f"{event['orderId']}:refund",
        order_id=event["orderId"],
        publisher_uid=body["publisherUid"],
        payment_id=body["paymentId"],
        amount_cent=body["amount"],
    )
