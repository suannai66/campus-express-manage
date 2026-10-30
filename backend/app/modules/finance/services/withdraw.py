"""F8 提现编排（FR8）：申请 → 校验 → 扣款 → 处理中 → 模拟渠道到账 → 已到账。

v1 迭代说明：账户尚无冻结字段，申请时直接扣减可用余额（设计稿 FR8.2 的
"校验并冻结提现金额"待 frozen_cent 引入后对齐）；打款失败解冻路径预留
（fail_reason 字段已建，流程后置）。
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from .. import config
from ..core import wallet_core
from ..models import WithdrawOrder
from ..schemas import WithdrawRequest, WithdrawResponse


def apply_withdraw(db: Session, uid: str, request: WithdrawRequest) -> WithdrawResponse:
    """FR8.1 申请提现：金额为正且不超过可用余额；扣款 + 建单同一事务（Q-03）。

    幂等键 <uid>:<withdraw_no>。余额不足抛 wallet_core.InsufficientBalanceError。
    """
    withdraw_no = f"WD{uuid.uuid4().hex[:16]}"
    with db.begin():
        wallet_core.debit(db, uid, request.amount_cent, f"{uid}:{withdraw_no}", "WITHDRAW")
        db.add(WithdrawOrder(withdraw_no=withdraw_no, uid=uid, amount_cent=request.amount_cent))
    return WithdrawResponse(withdraw_no=withdraw_no, status="processing")


def query_withdraw(db: Session, uid: str, withdraw_no: str) -> dict | None:
    """FR8 提现单查询：processing 超过模拟打款延迟后惰性流转为 done（模拟渠道到账）。"""
    order = db.get(WithdrawOrder, withdraw_no)
    if order is None or order.uid != uid:
        return None
    if (
        order.status == "processing"
        and (datetime.now() - order.created_at).total_seconds()
        >= config.WITHDRAW_SETTLE_SECONDS
    ):
        # 查询已隐式开启事务（autobegin），直接更新后提交，不用 session.begin()
        order.status = "done"
        db.commit()
    return {
        "withdraw_no": order.withdraw_no,
        "amount_cent": order.amount_cent,
        "status": order.status,
        "fail_reason": order.fail_reason,
        "created_at": order.created_at,
    }