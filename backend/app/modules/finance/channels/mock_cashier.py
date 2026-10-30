"""模拟收银台适配器：默认渠道（C-06），模拟支付与回调，便于开发与课堂演示。

演示环境无真实资金，界面需明示模拟用途（C-09）；本适配器常驻兜底，
即使未来接入支付宝沙箱，也可通过 config.CHANNEL_ACTIVE 切回本渠道。
"""

from .port import ChannelPort, InternalPaymentResult


class MockCashierAdapter:
    """实现 ChannelPort。"""

    def pay(self, request) -> InternalPaymentResult:
        """生成模拟收银台支付页，等待"我已支付"触发模拟回调。"""
        # TODO(迭代7) 返回 pay_url 与 pending 结果；回调复用 RechargeAppService.handle_callback
        raise NotImplementedError("TODO(迭代7): 实现模拟支付")

    def callback(self, payload) -> InternalPaymentResult:
        """模拟渠道回调：无验签需求，直接归一化为 SUCCESS 结果。"""
        raise NotImplementedError("TODO(迭代7): 实现模拟回调")
