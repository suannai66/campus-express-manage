"""渠道端口契约（阶段 3.3 调整 A）：所有支付渠道适配器的统一接口。

核心流程只依赖 ChannelPort 抽象（DIP）；换渠道只增适配器、不改核心（开闭原则）。
适配器负责：验签、防重放、回调字段归一化；渠道差异不得渗入核心流程。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PaymentStatus(str, Enum):
    """归一化支付状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


@dataclass
class InternalPaymentResult:
    """渠道结果归一化契约（调整 A）。"""

    status: PaymentStatus
    amount_cent: int
    channel_txn_id: str
    raw_signed_payload: str
    channel: str  # mock / alipay_sandbox


class ChannelPort(Protocol):
    """统一支付渠道接口。充值/提现流程经本接口调用渠道，不直接依赖 SDK。"""

    def pay(self, request) -> InternalPaymentResult:
        """调起渠道支付：返回归一化结果。"""
        ...

    def callback(self, payload) -> InternalPaymentResult:
        """处理渠道回调：验签/防重放后归一化为 InternalPaymentResult。"""
        ...
