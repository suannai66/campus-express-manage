"""整数分结算；明确传入订单费率快照，不读取当前费率计算历史订单。"""

from .. import config


def calc_commission(base_fee_cent: int, commission_rate_bps: int | None = None) -> int:
    rate = config.COMMISSION_RATE_BPS if commission_rate_bps is None else commission_rate_bps
    if type(base_fee_cent) is not int or base_fee_cent < 0:
        raise ValueError("基础费用必须为非负整数分")
    if type(rate) is not int or not 0 <= rate <= 10000:
        raise ValueError("佣金比例必须为 0 至 10000 的整数基点")
    return base_fee_cent * rate // 10000


def split_settlement(
    amount_cent: int, base_fee_cent: int, commission_rate_bps: int | None = None
) -> tuple[int, int]:
    if (
        type(amount_cent) is not int
        or type(base_fee_cent) is not int
        or not 0 <= base_fee_cent <= amount_cent
    ):
        raise ValueError("订单金额和基础费用不合法")
    commission = calc_commission(base_fee_cent, commission_rate_bps)
    return amount_cent - commission, commission
