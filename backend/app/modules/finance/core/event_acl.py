"""事件防腐映射（EV-3，借用 A）：外部事件报文 → 内部命令 + 幂等键派生，单点收敛。

B/C 的字段契约一旦变化，只改本文件；事件处理器与业务服务不接触外部字段名。

幂等键派生规则（阶段 3.3 调整 B）：
- 下单冻结 = <uid>:<order_id>
- 完结结算 = <order_id>:settle
- 取消解冻 = <order_id>:cancel
- 超时赔付 = <order_id>:penalty
- 充值    = <channel>:<out_trade_no>
- 提现    = <uid>:<withdraw_no>
- 事件消费 = <source>:<event_id>
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UnfreezeCommand:
    """取消事件映射出的解冻命令。"""

    idempotency_key: str  # <order_id>:cancel
    order_id: str
    customer_uid: str


@dataclass(frozen=True)
class SettleCommand:
    """完结事件映射出的结算命令。"""

    idempotency_key: str  # <order_id>:settle
    order_id: str
    customer_uid: str
    courier_uid: str
    amount_cent: int


@dataclass(frozen=True)
class PenaltyCommand:
    """超时事件映射出的赔付命令。"""

    idempotency_key: str  # <order_id>:penalty
    order_id: str
    customer_uid: str
    courier_uid: str


def cancel_to_command(payload) -> UnfreezeCommand:
    """外部取消事件 → 解冻命令。幂等键 <order_id>:cancel。"""
    # TODO(团队对齐) 与 B/C 书面固化字段名与取值（R1）；校验事件来源身份
    raise NotImplementedError("TODO(迭代7): 实现取消事件映射")


def complete_to_command(payload) -> SettleCommand:
    """外部完结事件 → 结算命令。幂等键 <order_id>:settle。"""
    # TODO(团队对齐) 与 B/C 书面固化字段名与取值；金额以服务端为准（Q-05）
    raise NotImplementedError("TODO(迭代7): 实现完结事件映射")


def timeout_to_command(payload) -> PenaltyCommand:
    """外部超时事件 → 赔付命令。幂等键 <order_id>:penalty。"""
    # TODO(团队对齐) 与 B/C 书面固化字段名与取值；12h 超时检测由 F5 负责（本模块只订阅）
    raise NotImplementedError("TODO(迭代7): 实现超时事件映射")
