"""计费工具（EV-2）：平台服务费/超时费等计算收敛到单一纯函数，参数全部来自 config。

禁止在业务代码中散落计算公式；调参只改配置不改代码（策略模式已裁决不采用）。
"""

from .. import config


def calc_platform_fee(amount_cent: int) -> int:
    """FR4：平台服务费 = max(金额 × 费率, 最低服务费)，四舍五入到分。

    TODO(迭代7) 公式：round(amount_cent * config.SERVICE_FEE_RATE)，
    下限 config.MIN_SERVICE_FEE_CENT；补充金额恒等式测试。
    """
    raise NotImplementedError("TODO(迭代7): 实现服务费计算")


def split_settlement(amount_cent: int) -> tuple[int, int]:
    """FR4：返回 (取货员到账, 平台服务费)。恒等式：到账 + 服务费 = 订单金额。"""
    raise NotImplementedError("TODO(迭代7): 实现结算拆分")
