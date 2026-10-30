"""F8 提现编排（FR8）：申请 → 校验并冻结 → 处理中 → 模拟渠道到账 → 扣冻结；失败解冻。

提现仅模拟渠道（企业付款能力个人沙箱不开放，FR8 渠道说明）；
接口仍走 channels/port.py 统一抽象，预留未来接入能力。
"""

from ..schemas import WithdrawRequest, WithdrawResponse


def apply_withdraw(uid: str, request: WithdrawRequest) -> WithdrawResponse:
    """FR8.1/FR8.2 申请提现：金额为正且不超过可用余额（手续费 0），校验并冻结 → 处理中。

    幂等键 <uid>:<withdraw_no>。
    """
    raise NotImplementedError("TODO(迭代7): 实现提现申请")


def process_withdraw(withdraw_no: str) -> None:
    """FR8.2 模拟渠道打款：延迟自动流转"已到账" → 扣减冻结余额；打款失败解冻并记录失败原因。"""
    raise NotImplementedError("TODO(迭代7): 实现模拟打款流转")


def query_withdraw(uid: str, withdraw_no: str) -> dict:
    """FR8 提现单状态查询（状态机：processing / done / failed）。"""
    raise NotImplementedError("TODO(迭代7): 实现提现单查询")
