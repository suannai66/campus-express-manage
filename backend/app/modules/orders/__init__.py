"""成员 B：F3 需求发布与 F4 大厅查询。"""


def configure_dependencies(app, *, identity_service, pricing_service):
    """A/D 在单体入口注入共享能力，不能为每个模块另建身份事实来源。"""
    app.state.identity_service = identity_service
    app.state.pricing_service = pricing_service


def event_handlers():
    """A 投递器注册这些消费者，并在同一事务内提交业务变化与回执。"""
    from .handlers import handle
    return {kind: handle for kind in ("payment.succeeded", "payment.failed", "refund.succeeded")}
