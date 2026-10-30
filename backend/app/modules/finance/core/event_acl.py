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


def completed_to_command(payload) -> SettleCommand:
    """外部 order.completed 事件 → 结算命令。幂等键 <orderId>:settle。"""
    # TODO(迭代·结算) 按约定第 12 节 payload 字段映射；金额以订单快照为准（Q-05）
    raise NotImplementedError("TODO(迭代·结算): 实现完结事件映射")


def cancelled_to_command(payload) -> RefundCommand:
    """外部 order.cancelled 事件 → 退款命令。幂等键 <orderId>:refund。"""
    # TODO(迭代·退款) 按约定第 12 节 payload 字段映射
    raise NotImplementedError("TODO(迭代·退款): 实现取消事件映射")