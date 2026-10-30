"""F7 用例编排：订单定价、下单冻结、完结结算、取消解冻、超时赔付。

资金状态变更一律经 core/wallet_core.py；幂等键派生见 core/event_acl.py。
"""

from ..core.event_acl import PenaltyCommand, SettleCommand, UnfreezeCommand
from ..schemas import FreezeResponse, QuoteRequest, QuoteResponse


def quote(request: QuoteRequest) -> QuoteResponse:
    """FR2 定价：基础运费（距离/重量查表）+ 小费；低于起送价拒绝（FR2.3）。"""
    # TODO(迭代7) 定价规则表的具体数值（距离/重量档）待与成员 B 对齐（R2）
    # TODO(迭代7) 金额校验：≥ config.MIN_ORDER_AMOUNT_CENT，精度到分
    raise NotImplementedError("TODO(迭代7): 实现定价")


def pay_and_freeze(uid: str, order_id: str, amount_cent: int) -> FreezeResponse:
    """FR3 下单冻结：幂等键 <uid>:<order_id>，重复请求返回首次结果（FR3.4）。

    冻结成功后发布"支付成功 = 冻结成功"事件供 F3 订阅，订单状态由 F3 自行流转。
    """
    raise NotImplementedError("TODO(迭代7): 实现冻结编排")


def settle_order(command: SettleCommand) -> None:
    """FR4 完结结算：扣冻结 → 取货员 T+0 入账 → 平台服务费只记流水。

    金额恒等式：服务费 + 取货员到账 = 订单金额；多账户按 ID 固定顺序加锁防死锁（FR4.5）。
    """
    raise NotImplementedError("TODO(迭代7): 实现结算编排")


def cancel_and_unfreeze(command: UnfreezeCommand) -> None:
    """FR5 取消解冻：解冻仅由取消事件触发（唯一触发源）；已结算订单不再解冻（FR5.3）。"""
    raise NotImplementedError("TODO(迭代7): 实现解冻编排")


def timeout_penalty(command: PenaltyCommand) -> None:
    """FR6 超时赔付：解冻 + 扣取货员固定超时费（余额不足扣至 0 不追偿）补偿客户。

    同时请求 F6 自动扣减取货员信用积分（联动方向，信用数据归 C 维护）。
    """
    raise NotImplementedError("TODO(迭代7): 实现赔付编排")
