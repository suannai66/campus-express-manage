"""F8 充值编排（FR7）：充值单 → 调起渠道支付 → 回调 → 幂等入账 → 更新充值单状态。

渠道差异封装在 channels/ 适配器之后（EV-1）；v1 仅模拟收银台，支付宝沙箱
后续以「换适配器 + config.CHANNEL_ACTIVE 切换」方式接入，本流程不变（C-06）。
"""

import uuid

from sqlalchemy.orm import Session

from .. import config
from ..channels.mock_cashier import MockCashierAdapter
from ..channels.port import PaymentStatus
from ..core import wallet_core
from ..models import RechargeOrder
from ..schemas import RechargeRequest, RechargeResponse


def create_recharge(db: Session, uid: str, request: RechargeRequest) -> RechargeResponse:
    """FR7.2 创建充值单并调起渠道支付。入账幂等键 <channel>:<out_trade_no>。"""
    out_trade_no = f"RC{uuid.uuid4().hex[:16]}"
    with db.begin():
        db.add(
            RechargeOrder(
                out_trade_no=out_trade_no,
                uid=uid,
                amount_cent=request.amount_cent,
                channel=config.CHANNEL_ACTIVE,
            )
        )
    # TODO(迭代7·沙箱) 按 config.CHANNEL_ACTIVE 选择适配器；v1 恒为模拟收银台
    result = MockCashierAdapter().pay(
        {"out_trade_no": out_trade_no, "amount_cent": request.amount_cent}
    )
    return RechargeResponse(
        out_trade_no=out_trade_no,
        channel=config.CHANNEL_ACTIVE,
        status="pending",
        pay_url=result.pay_url,
    )


def handle_callback(db: Session, payload: dict) -> dict | None:
    """FR7.3 渠道回调：适配器验签/归一化 → 幂等入账；重复回调只入账一次。

    返回充值单字典；充值单不存在返回 None（路由转 404）。
    """
    out_trade_no = payload.get("out_trade_no")
    if not out_trade_no:
        raise ValueError("回调报文缺少 out_trade_no")
    order = db.get(RechargeOrder, out_trade_no)
    if order is None:
        return None
    if order.status == "success":
        return _order_dict(order)  # 重复回调幂等：已入账，直接返回首次结果

    # TODO(迭代7·沙箱) 按 order.channel 选择适配器；v1 恒为模拟收银台
    result = MockCashierAdapter().callback(payload)
    if result.status is not PaymentStatus.SUCCESS:
        order.status = "failed"
        db.commit()
        return _order_dict(order)

    # 入账与充值单状态更新分两步（v1 已知取舍：极端中断下可由重复回调自愈——
    # 幂等入账命中首次流水后仍会把充值单补记为 success）
    _ledger, _first = wallet_core.credit_idempotent(
        db, order.uid, order.amount_cent, f"{order.channel}:{out_trade_no}", "RECHARGE"
    )
    if order.status != "success":
        order.status = "success"
        order.channel_txn_id = result.channel_txn_id
        db.commit()
    return _order_dict(order)


def query_recharge(db: Session, uid: str, out_trade_no: str) -> dict | None:
    """FR7.5 充值单查询，仅本人可见。"""
    order = db.get(RechargeOrder, out_trade_no)
    if order is None or order.uid != uid:
        return None
    return _order_dict(order)


def _order_dict(order: RechargeOrder) -> dict:
    return {
        "out_trade_no": order.out_trade_no,
        "amount_cent": order.amount_cent,
        "channel": order.channel,
        "status": order.status,
        "channel_txn_id": order.channel_txn_id,
        "created_at": order.created_at,
    }