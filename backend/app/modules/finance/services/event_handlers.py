"""事件处理器（EV-3）：订阅 B/C 的取消/完结/超时事件，只订阅不判定不回写（C-07）。

处理链：HTTP 报文（routers/events.py）→ EventACL 映射为内部命令（core/event_acl.py）
→ 调用对应应用服务（本模块或其他 services 模块）。
事件处理器不接触外部字段名，契约变更只改 event_acl 一处。
"""

from ..core.event_acl import (
    PenaltyCommand,
    SettleCommand,
    UnfreezeCommand,
)
from .order_payment import (
    cancel_and_unfreeze,
    settle_order,
    timeout_penalty,
)


def on_cancel(payload) -> UnfreezeCommand:
    """订单取消事件 → 解冻命令 → FR5 解冻。幂等键 <order_id>:cancel。"""
    command = _acl_cancel(payload)
    cancel_and_unfreeze(command)
    return command


def on_complete(payload) -> SettleCommand:
    """订单完结事件 → 结算命令 → FR4 结算。幂等键 <order_id>:settle。"""
    command = _acl_complete(payload)
    settle_order(command)
    return command


def on_timeout(payload) -> PenaltyCommand:
    """履约超时事件 → 赔付命令 → FR6 赔付 + 联动 F6 扣分。幂等键 <order_id>:penalty。"""
    command = _acl_timeout(payload)
    timeout_penalty(command)
    return command


# TODO(迭代7) 由 core/event_acl.py 提供映射函数后删除以下占位


def _acl_cancel(payload) -> UnfreezeCommand:
    raise NotImplementedError("TODO(迭代7): 改为 event_acl.cancel_to_command(payload)")


def _acl_complete(payload) -> SettleCommand:
    raise NotImplementedError("TODO(迭代7): 改为 event_acl.complete_to_command(payload)")


def _acl_timeout(payload) -> PenaltyCommand:
    raise NotImplementedError("TODO(迭代7): 改为 event_acl.timeout_to_command(payload)")
