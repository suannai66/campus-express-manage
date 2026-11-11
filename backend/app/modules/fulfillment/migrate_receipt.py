"""显式升级旧版完结状态：python -m app.modules.fulfillment.migrate_receipt。"""
from sqlalchemy import inspect, select, update

from ...events.models import OutboxEvent
from ...events.schema import validate
from ..orders.entities import Order


def upgrade(engine):
    """仅将已有完结事件佐证的旧 delivered 转为 completed；不生成事件或移动资金。"""
    if engine.dialect.name != "sqlite":
        raise ValueError("本升级仅支持 SQLite")
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            inspector = inspect(connection)
            if not inspector.has_table("orders_v2"):
                raise ValueError("订单表不存在；全新数据库无需执行此升级")
            if not inspector.has_table("outbox_events"):
                connection.rollback()
                return 0
            changed = 0
            orders = connection.execute(select(Order.__table__).where(Order.status == "delivered")).mappings().all()
            for order in orders:
                events = connection.execute(select(OutboxEvent.body, OutboxEvent.digest).where(
                    OutboxEvent.order_id == order["id"], OutboxEvent.type == "order.completed")).all()
                if not events:
                    continue  # 新版送达待收货没有完结事件，必须保留。
                expected = {"publisherUid": order["publisher_uid"], "courierUid": order["courier_uid"],
                    "amount": order["amount"], "baseFee": order["base_fee"], "tip": order["tip"],
                    "commissionRateBps": order["commission_bps"], "pricingVersion": order["pricing_version"],
                    "orderVersion": order["version"]}
                for event, stored_digest in events:
                    data, digest = validate(event)
                    if (stored_digest != digest or data["type"] != "order.completed" or data["orderId"] != order["id"]
                            or data["version"] != order["version"] or data["payload"] != expected):
                        raise ValueError(f"订单 {order['id']} 的历史完结事实冲突，升级已回滚")
                # 这是旧完结含义的重命名，版本和旧事件保持一致，便于投递重试。
                connection.execute(update(Order).where(Order.id == order["id"]).values(status="completed"))
                changed += 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise


if __name__ == "__main__":
    from ...database import engine
    print(f"已保留原完结事实并升级 {upgrade(engine)} 单；账号、余额、流水和事件均未改写")
