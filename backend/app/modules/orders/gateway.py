"""订单唯一受控写入口，不提交调用方事务。"""
from dataclasses import make_dataclass
from sqlalchemy import update

from ...common import fail
from .entities import Order

OrderSnapshot = make_dataclass("OrderSnapshot", [(column.key, object) for column in Order.__table__.columns], frozen=True)


def snapshot(order):
    return OrderSnapshot(**{column.key: getattr(order, column.key) for column in Order.__table__.columns})


class OrderGateway:
    @staticmethod
    def get_snapshot(db, order_id):
        order = db.get(Order, order_id)
        if not order:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        return snapshot(order)

    @staticmethod
    def related(db, order_id, uid):
        order = OrderGateway.get_snapshot(db, order_id)
        if uid not in {order.publisher_uid, order.courier_uid}:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        return order

    @staticmethod
    def transition(db, order, version, operation, actor_uid, **changes):
        rules = {
            "reserve": ({"pending_payment"}, {"payment_status", "payment_request_id", "payer_uid"}),
            "payment": ({"pending_payment"}, {"payment_status", "status", "payment_id"}),
            "accept": ({"pending"}, {"status", "courier_uid"}),
            "cancel": ({"pending_payment", "pending"}, {"status", "refund_status"}),
            "fulfill": ({"accepted", "picking_up", "delivering"}, {"status"}),
            "confirm_receipt": ({"delivered"}, {"status"}),
            "refund": ({"cancelled"}, {"refund_status", "refund_id"}),
        }
        if operation not in rules:
            fail(409, "ORDER_CONFLICT", "不支持的订单操作")
        statuses, allowed = rules[operation]
        if set(changes) - allowed or order.status not in statuses:
            fail(409, "ORDER_CONFLICT", "订单状态不允许此操作")
        if operation in {"reserve", "cancel", "confirm_receipt"} and actor_uid != order.publisher_uid:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        if operation == "accept" and (actor_uid == order.publisher_uid or order.payment_status != "paid"):
            fail(409, "ORDER_CONFLICT", "此订单不能接单")
        if operation == "cancel" and order.payment_status == "paying":
            fail(409, "PAYMENT_IN_PROGRESS", "支付处理中，请等待确定结果")
        if operation == "fulfill" and actor_uid != order.courier_uid:
            fail(409, "ORDER_CONFLICT", "无权推进订单履约")
        valid = True
        if operation == "reserve":
            valid = (order.payment_status == "unpaid" and changes.get("payment_status") == "paying"
                     and changes.get("payer_uid") == order.publisher_uid and bool(changes.get("payment_request_id")))
        elif operation == "payment":
            valid = (order.payment_status == "paying" and (changes.get("status"), changes.get("payment_status"))
                     in {("pending", "paid"), ("pending_payment", "unpaid")}
                     and (bool(changes.get("payment_id")) == (changes.get("payment_status") == "paid")))
        elif operation == "accept":
            valid = (changes == {"status": "accepted", "courier_uid": actor_uid} and actor_uid is not None)
        elif operation == "cancel":
            valid = (changes.get("status") == "cancelled" and changes.get("refund_status") ==
                     ("processing" if order.payment_status == "paid" else "none") and
                     (order.status, order.payment_status) in {("pending_payment", "unpaid"), ("pending", "paid")})
        elif operation == "fulfill":
            valid = (set(changes) == {"status"} and (order.status, changes["status"]) in
                     {("accepted", "picking_up"), ("picking_up", "delivering"), ("delivering", "delivered")})
        elif operation == "confirm_receipt":
            valid = (changes == {"status": "completed"} and order.payment_status == "paid"
                     and order.refund_status == "none" and bool(order.courier_uid))
        elif operation == "refund":
            valid = (order.payment_status == "paid" and order.refund_status == "processing" and
                     changes.get("refund_status") == "succeeded" and bool(changes.get("refund_id")))
        if not valid:
            fail(409, "ORDER_CONFLICT", "订单转换不符合状态规则")
        changed = db.execute(update(Order).where(Order.id == order.id, Order.version == version,
                             Order.status == order.status, Order.payment_status == order.payment_status
                             ).values(**changes, version=Order.version + 1))
        if changed.rowcount != 1:
            fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新后重试")
        db.flush()
        db.expire_all()
        return OrderGateway.get_snapshot(db, order.id)
