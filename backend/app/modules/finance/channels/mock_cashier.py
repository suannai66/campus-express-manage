"""模拟收银台适配器：默认渠道（C-06），模拟支付与回调，便于开发与课堂演示。

演示环境无真实资金，界面需明示模拟用途（C-09）；本适配器常驻兜底，
未来接入支付宝沙箱后仍可通过 config.CHANNEL_ACTIVE 切回。
"""

from .port import ChannelPort, InternalPaymentResult, PaymentStatus


class MockCashierAdapter:
    """实现 ChannelPort：pay 返回待支付结果与收银台地址；callback 直接归一化为成功。"""

    def pay(self, request) -> InternalPaymentResult:
        """生成模拟收银台地址，等待前端"我已支付"后由回调接口完成入账。"""
        out_trade_no = request["out_trade_no"]
        amount_cent = request["amount_cent"]
        return InternalPaymentResult(
            status=PaymentStatus.PENDING,
            amount_cent=amount_cent,
            channel_txn_id=None,
            raw_signed_payload="",
            channel="mock",
            pay_url=f"/mock-cashier?out_trade_no={out_trade_no}&amount={amount_cent}",
        )

    def callback(self, payload) -> InternalPaymentResult:
        """模拟渠道回调：无验签需求（真实渠道的验签/防重放由对应适配器实现）。"""
        out_trade_no = payload.get("out_trade_no")
        return InternalPaymentResult(
            status=PaymentStatus.SUCCESS,
            amount_cent=0,  # 金额以充值单为准，v1 回调报文不携带金额
            channel_txn_id=f"MOCK-{out_trade_no}",
            raw_signed_payload="mock",
            channel="mock",
        )