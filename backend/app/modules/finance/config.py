"""参数外置（EV-2）：规则参数集中在此，业务代码禁止硬编码费率/金额。

全部参数支持 FIN_ 前缀环境变量覆盖；默认值对齐《团队接口约定》v1.1（2026-10-30）。
调参不改代码，不影响幂等与事务。
"""

import os


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name) or default


# ---- 平台佣金（团队接口约定 v1.1：1000 bps，仅对 baseFee 向下取整） ----
# commission = baseFee × COMMISSION_RATE_BPS 整除 10000；小费全部归取件员。
COMMISSION_RATE_BPS = _env_int("FIN_COMMISSION_RATE_BPS", 1000)

# ---- 提现（FR8 / 团队接口约定 v1.1） ----
WITHDRAW_SETTLE_SECONDS = _env_int(
    "FIN_WITHDRAW_SETTLE_SECONDS", 3
)  # 后台演示任务最早 3 秒后标记 succeeded
WITHDRAW_PROCESS_INTERVAL_SECONDS = _env_int(
    "FIN_WITHDRAW_PROCESS_INTERVAL_SECONDS", 1
)  # 后台扫描间隔

# ---- 支付渠道（C-06，EV-1） ----
# v1 走演示路径：POST /api/wallet/recharge/{rechargeId}/confirm，真实回调本期不实现；
# 支付宝沙箱后续以「换适配器 + 配置切换」方式接入。
CHANNEL_ACTIVE = _env_str("FIN_CHANNEL_ACTIVE", "mock")  # mock | alipay_sandbox

# ---- 流水查询（团队接口约定 v1.1：分页 pageSize 默认 20、最大 100） ----
LEDGER_PAGE_SIZE_MAX = _env_int("FIN_LEDGER_PAGE_SIZE_MAX", 100)

# ---- 资金写入金额上限（团队接口约定 v1.1：整数 1 ~ 100000 分） ----
AMOUNT_MIN_CENT = 1
AMOUNT_MAX_CENT = 100000
# 团队 v1.1 演示报价；修改费率时必须同步更新版本。
PRICING_VERSION = "demo-20261030-v1"
ROUTE_FEES = {
    "station_cainiao": {"zone_qinyuan": 200, "zone_zhuyuan": 300, "zone_public": 200},
    "station_sf": {"zone_qinyuan": 300, "zone_zhuyuan": 200, "zone_public": 200},
}
SIZE_FEES = {"small": 0, "medium": 100, "large": 300}
EXTRA_KG_FEE = 100
QUOTE_VALID_SECONDS = 300


def application_mode() -> str:
    """复用公共 CAMPUS_MODE；由应用启动时读取并固定。"""
    mode = os.getenv("CAMPUS_MODE", "demo")
    if mode not in {"demo", "production"}:
        raise ValueError("CAMPUS_MODE 必须为 demo 或 production")
    return mode


WITHDRAW_DEMO_OUTCOME = _env_str("FIN_WITHDRAW_DEMO_OUTCOME", "succeeded")
if WITHDRAW_DEMO_OUTCOME not in {"succeeded", "failed"}:
    raise ValueError("FIN_WITHDRAW_DEMO_OUTCOME 必须为 succeeded 或 failed")
