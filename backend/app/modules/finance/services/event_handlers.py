"""资金侧事件消费者（团队接口约定 v1.1 第 12 节）。

事件经 A 提供的持久化 outbox 投递（应用内轻量投递任务，不引 MQ），本模块实现消费处理器：
- order.completed → 结算：按订单快照（pricingVersion/commissionRateBps）结算，
  取件员入账 + 平台佣金留账（约定：佣金仅对 baseFee 计，小费全归取件员）；
- order.cancelled → 退款：全额退回发布者钱包，不收佣金（refundStatus 由 B 消费 refund.succeeded 流转）。

消费者纪律：
- 本地事务内同时保存处理结果与唯一去重记录 (consumer,eventId)；
- 业务唯一约束：订单结算、订单退款各至多一次，换键也不得重复入账；
- 资金事件不能仅因版本较旧就丢弃，应检查对应业务事实。

TODO(迭代·冻结) 冻结字段（v2）与 OrderGateway 接入后实现。
"""


def on_order_completed(event: dict) -> None:
    """消费 order.completed：结算（取货员入账 + 平台佣金留账）。"""
    raise NotImplementedError("TODO(迭代·结算): 消费订单完结事件")


def on_order_cancelled(event: dict) -> None:
    """消费 order.cancelled：退款（全额退回发布者钱包，不收佣金）。"""
    raise NotImplementedError("TODO(迭代·退款): 消费订单取消事件")