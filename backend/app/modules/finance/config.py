"""参数外置（EV-2）：规则参数集中在此，业务代码禁止硬编码费率/金额。

全部参数支持 FIN_ 前缀环境变量覆盖；默认值即需求稿 V3.0 的当前口径。
调参不改代码，不影响幂等与事务。
"""

import os


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name) or default


# ---- 订单定价（FR2，定价规则表由本模块维护） ----
MIN_ORDER_AMOUNT_CENT = _env_int("FIN_MIN_ORDER_AMOUNT_CENT", 100)  # 起送价 1.00 元

# ---- 平台服务费（FR4） ----
SERVICE_FEE_RATE = float(_env_str("FIN_SERVICE_FEE_RATE", "0.01"))  # 金额 × 1%
MIN_SERVICE_FEE_CENT = _env_int("FIN_MIN_SERVICE_FEE_CENT", 1)  # 最低 0.01 元

# ---- 履约超时赔付（FR6） ----
# 12h 履约时限与超时检测归 F5（订单侧全局定时扫描），本模块只订阅超时事件；
# 此常量仅作团队对齐记录，结算逻辑不使用。
FULFILL_TIMEOUT_HOURS = _env_int("FIN_FULFILL_TIMEOUT_HOURS", 12)
PENALTY_CENT = _env_int("FIN_PENALTY_CENT", 100)  # 固定超时费 1 元，余额不足扣至 0 不追偿

# ---- 支付渠道（C-06，EV-1） ----
CHANNEL_ACTIVE = _env_str("FIN_CHANNEL_ACTIVE", "mock")  # mock | alipay_sandbox

# ---- 流水查询（FR9） ----
LEDGER_PAGE_SIZE_MAX = _env_int("FIN_LEDGER_PAGE_SIZE_MAX", 100)