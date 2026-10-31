"""计费工具（EV-2，团队接口约定 v1.1）：佣金计算收敛到单一纯函数，参数全部来自 config。

约定（第 10 节）：平台佣金 = baseFee × 1000 bps 向下取整（整除），仅对 baseFee 计佣，
小费全部归取件员；income = amount − commission。禁止在业务代码中散落计算公式。
"""

from .. import config


def calc_commission(base_fee_cent: int) -> int:
    """平台佣金 = baseFee × COMMISSION_RATE_BPS 整除 10000（向下取整到分）。"""
    # TODO(迭代·结算) return base_fee_cent * config.COMMISSION_RATE_BPS // 10000
    raise NotImplementedError("TODO(迭代·结算): 实现佣金计算")


def split_settlement(amount_cent: int, base_fee_cent: int) -> tuple[int, int]:
    """结算拆分：返回 (取件员到账, 平台佣金)。恒等式：到账 + 佣金 = 订单金额。"""
    # TODO(迭代·结算) commission = calc_commission(base_fee_cent); return amount - commission, commission
    raise NotImplementedError("TODO(迭代·结算): 实现结算拆分")