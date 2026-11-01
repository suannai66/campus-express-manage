"""F8 充值编排（团队接口约定 v1.1 第 10 节）：create → confirm（演示专用）幂等入账。

- v1 走演示路径 POST /api/wallet/recharge/{rechargeId}/confirm，真实渠道回调本期不实现；
- 余额、流水、业务记录同事务保存（约定第 11 节）；
- HTTP 幂等（约定第 12 节）：Idempotency-Key 必填，(uid,operation,key) 持久化请求摘要与
  结果；同键同请求返回原结果，同键不同内容 409 IDEMPOTENCY_CONFLICT（由公共组件
  app.common.replay/remember 提供）；
- 渠道差异封装在 channels/ 适配器之后（EV-1），沙箱迭代换适配器不改本流程。
"""

import hashlib

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....common import fail, remember, replay
from .transaction import wallet_transaction
from .. import config
from ..core import wallet_core
from ..models import RechargeOrder
from ..schemas import RechargeRequest

OPERATION = "wallet-recharge"


def _new_id(uid: str, idempotency_key: str) -> str:
    """充值单号：由 (uid, 幂等键) 派生固定单号（重复请求返回同一单，并发同键主键冲突兜底）。"""
    digest = hashlib.sha256(f"{uid}:{idempotency_key}".encode()).hexdigest()[:16]
    return f"RC{digest}"


def _create_dict(order: RechargeOrder) -> dict:
    return {
        "rechargeId": order.out_trade_no,
        "amount": order.amount_cent,
        "status": order.status,
        "demo": True,
    }


def create_recharge(db: Session, uid: str, request: RechargeRequest, idempotency_key: str) -> dict:
    """POST /api/wallet/recharge：创建充值单（pending），201。

    同幂等键同请求返回首次结果（保留原 201）；同键不同内容由 replay 抛 409。
    """
    payload = {"amount": request.amount}
    with wallet_transaction(db):
        existing_result = replay(db, uid, OPERATION, idempotency_key, payload)
        if existing_result is not None:
            return existing_result
        recharge_id = _new_id(uid, idempotency_key)
        existing = db.get(RechargeOrder, recharge_id)
        if existing is not None:
            return _create_dict(existing)
        order = RechargeOrder(
            out_trade_no=recharge_id,
            uid=uid,
            amount_cent=request.amount,
            channel=config.CHANNEL_ACTIVE,
        )
        db.add(order)
        db.flush()  # 应用 status 默认值；并发同键由主键唯一约束在此拦截（→409）
        result = _create_dict(order)
        remember(db, uid, OPERATION, idempotency_key, payload, result)
        return result


def handle_confirm(
    db: Session, uid: str, recharge_id: str, idempotency_key: str, *, demo_enabled: bool = False
) -> dict | None:
    """POST /api/wallet/recharge/{rechargeId}/confirm：幂等入账，与充值单状态更新同一事务。

    重复 confirm 返回首次结果；充值单不存在或非本人返回 None（路由转 404）。
    """
    if demo_enabled is not True:
        fail(404, "NOT_FOUND", "接口不存在")
    try:
        with wallet_transaction(db):
            payload = {"rechargeId": recharge_id}
            previous = replay(db, uid, "wallet-recharge-confirm", idempotency_key, payload)
            if previous is not None:
                return previous
            order = db.get(RechargeOrder, recharge_id)
            if order is None or order.uid != uid:
                return None
            if order.status == "succeeded":
                result = _confirm_dict(order)
                remember(db, uid, "wallet-recharge-confirm", idempotency_key, payload, result)
                return result
            if order.status != "pending" or order.channel != "mock":
                fail(409, "ORDER_CONFLICT", "充值单状态或渠道不支持模拟确认")
            # 入账（唯一索引兜底）+ 更新充值单，同一事务（约定：余额/流水/业务记录同事务）
            wallet_core.credit(
                db, order.uid, order.amount_cent, f"{order.channel}:{recharge_id}", "recharge"
            )
            order.status = "succeeded"
            order.channel_txn_id = f"MOCK-{recharge_id}"
            result = _confirm_dict(order)
            remember(db, uid, "wallet-recharge-confirm", idempotency_key, payload, result)
            return result
    except IntegrityError:
        # Only replay a committed matching request. Other constraint failures must
        # remain conflicts; never turn an unrelated database error into success.
        db.rollback()
        result = replay(
            db, uid, "wallet-recharge-confirm", idempotency_key, {"rechargeId": recharge_id}
        )
        if result is not None:
            return result
        raise


def _confirm_dict(order: RechargeOrder) -> dict:
    return {
        "rechargeId": order.out_trade_no,
        "amount": order.amount_cent,
        "status": order.status,
    }
