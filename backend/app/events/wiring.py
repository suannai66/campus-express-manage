"""单体订阅装配。"""
from . import register_consumer


def register_defaults():
    from ..modules.orders import event_handlers
    from ..modules.orders.projections import handle as refresh
    from ..modules.finance.services.event_handlers import on_order_cancelled, on_order_completed
    from ..modules.fulfillment.handlers import on_order_completed as open_reviews
    for kind, handler in event_handlers().items():
        register_consumer(kind, "orders", handler)
    for kind in ("order.status_changed", "order.cancelled"):
        register_consumer(kind, "orders", refresh)
    register_consumer("order.cancelled", "finance", on_order_cancelled)
    register_consumer("order.completed", "finance", on_order_completed)
    register_consumer("order.completed", "fulfillment", open_reviews)
