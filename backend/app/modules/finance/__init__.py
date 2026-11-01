"""成员 D：F7 订单支付与费用结算、F8 钱包充值与提现。

分层与职责（《软件架构设计专项任务》3.3 最终方案：轻量分层单体 + 端口/适配器）：
- routers/    接入层：薄控制器，JWT 鉴权（Q-05）+ 参数校验，不承载业务
- services/   应用/编排层：用例服务与事件消费处理器
- core/       领域核心层：wallet_core 唯一资金入口、fee_util 计费单函数、event_acl 事件映射
- channels/   端口/适配器层：ChannelPort 契约 + 模拟收银台（默认兜底）+ 支付宝沙箱（后置）
- query.py    流水查询（读模型与写模型分离）
- models.py   资金表 Schema（阶段 3.3 调整 C，SQLite 口径）

接口与协作以《docs/团队接口约定.md》v1.1（2026-10-30）为准：
- 钱包接口 /api/wallet*，金额整数分，创建 201，时间 UTC ISO 8601（Z）；
- 跨模块结果经持久化 outbox 事件传递（A 提供投递组件），本模块生产
  payment.succeeded / payment.failed / refund.succeeded，消费 order.completed /
  order.cancelled；只订阅不判定不回写（C-07）。
"""

from datetime import datetime, timezone


def iso_utc(value: datetime) -> str:
    """UTC ISO 8601（带 Z）序列化（团队接口约定 v1.1：时间返回带 Z 的 UTC）。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
