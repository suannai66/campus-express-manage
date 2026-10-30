"""F8 充值编排（团队接口约定 v1.1 第 10 节）：create → confirm（演示专用）幂等入账。

- v1 走演示路径 POST /api/wallet/recharge/{rechargeId}/confirm，真实渠道回调本期不实现；
- 余额、流水、业务记录同事务保存（约定第 11 节）；
- 渠道差异封装在 channels/ 适配器之后（EV-1），沙箱迭代换适配器不改本流程。
"""

import hashlib
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..core import wallet_core
from ..models import RechargeOrder
from ..schemas import RechargeRequest, RechargeResponse


def _new_id(uid: str, idempotency_key: str | None) -> str:
    """充值单号：请求带 Idempotency-Key 时派生固定单号（重复请求返回同一单），否则随机。"""
    if idempotency_key:
        digest = hashlib.sha256(f"{uid}:{idempotency_key}".encode()).hexdigest()[:16]
        return f"RC{digest}"
    return f"RC{uuid.uuid4().hex[:16]}"


def create_recharge(
    db: Session, uid: str, request: RechargeRequest, idempotency_key: str | None = None
) -> RechargeResponse:
    """POST /api/wallet/recharge：创建充值单（pending）。同幂等键重复请求返回原单。"""
    recharge_id = _new_id(uid, idempotency_key)
    with db.begin():
        existing = db.get(RechargeOrder, recharge_id)
        if existing is not None:
            return RechargeResponse(
                rechargeId=existing.out_trade_no,
                amount=existing.amount_cent,
                status=existing.status,
            )
        db.add(
            RechargeOrder(
                out_trade_no=recharge_id,
                uid=uid,
                amount_cent=request.amount,
                channel=config.CHANNEL_ACTIVE,
            )
        )
    return RechargeResponse(rechargeId=recharge_id, amount=request.amount, status="pending")


def handle_confirm(db: Session, uid: str, recharge_id: str) -> dict | None:
    """POST /api/wallet/recharge/{rechargeId}/confirm：幂等入账，与充值单状态更新同一事务。

    重复 confirm 返回首次结果；充值单不存在或非本人返回 None（路由转 404）。
    """
    try:
        with db.begin():
            order = db.get(RechargeOrder, recharge_id)
            if order is None or order.uid != uid:
                return None
            if order.status == "succeeded":
                return _confirm_dict(order)  # 重复 confirm：直接返回首次结果
            # 入账（唯一索引兜底）+ 更新充值单，同一事务（约定：余额/流水/业务记录同事务）
            wallet_core.credit(
                db, order.uid, order.amount_cent, f"{order.channel}:{recharge_id}", "recharge"
            )
            order.status = "succeeded"
            order.channel_txn_id = f"MOCK-{recharge_id}"
            return _confirm_dict(order)
    except IntegrityError:
        # 并发重复 confirm：唯一索引拦截后，读取已提交的首次结果
        db.rollback()
        order = db.get(RechargeOrder, recharge_id)
        if order is None or order.uid != uid:
            return None
        db.rollback()
        return _confirm_dict(order)


def _confirm_dict(order: RechargeOrder) -> dict:
    return {
        "rechargeId": order.out_trade_no,
        "amount": order.amount_cent,
        "status": order.status,
    }