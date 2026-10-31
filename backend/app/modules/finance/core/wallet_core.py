"""资金领域核心：全部资金状态变更的唯一入口（借用 A 的"不变量强制封装纪律"）。

对应团队接口约定 v1.1 第 11 节的 WalletService.changeBalance（D 独占维护，
支付/退款/充值/提现/结算均经此能力；余额、流水、业务记录与去重记录同事务保存）。

不变量（信息隐藏，外部无法绕过）：
- 余额不为负；扣款使用条件更新（WHERE balance >= amount），不先读余额再无条件覆盖
- 入账/扣款一律使用数据库原子相对更新（SET available_cent = available_cent ± amount），
  并发多笔变动不互相覆盖（Q-01：并发充值不得丢失余额更新）
- 每笔余额变动必有流水，余额更新与流水同库事务（Q-03）
- 幂等：幂等键 + ledger 唯一索引兜底，重复请求返回首次结果（Q-04）

事务约定（团队规范：写操作由业务层显式管理事务）：
本模块函数假定调用方已持有事务（with session.begin(): 内调用），自行不提交。
"""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..models import Account, Ledger, Payment


class InsufficientBalanceError(Exception):
    """余额不足（约定：确定失败 code=INSUFFICIENT_BALANCE，余额不得为负）。"""

    def __init__(self, uid: str, need_cent: int, have_cent: int) -> None:
        self.uid = uid
        self.need_cent = need_cent
        self.have_cent = have_cent
        super().__init__(f"余额不足：需要 {need_cent} 分，可用 {have_cent} 分")


def _ensure_account(session: Session, uid: str) -> None:
    """幂等创建账户（可用余额 0，约定：用户余额初始为 0），并发安全：INSERT ... ON CONFLICT DO NOTHING。

    不做「先 SELECT 再 INSERT」：并发首笔变动时两个事务都可能看到账户不存在，
    后写者主键冲突（改用 ON CONFLICT 则与既有行共存）。需在事务内调用。
    """
    session.execute(
        sqlite_insert(Account)
        .values(
            uid=uid,
            available_cent=0,
            version=0,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=[Account.uid])
    )


def credit(
    session: Session, uid: str, amount_cent: int, idempotency_key: str, biz_type: str
) -> Ledger:
    """入账：可用余额原子累加（SET available_cent = available_cent + amount）。

    并发多笔入账按相对值串行叠加，不会互相覆盖（Q-01）。需在事务内调用；
    幂等由唯一索引兜底，重复写抛 IntegrityError。
    """
    _ensure_account(session, uid)
    new_balance = session.execute(
        update(Account)
        .where(Account.uid == uid)
        .values(available_cent=Account.available_cent + amount_cent)
        .returning(Account.available_cent)
    ).scalar_one()
    ledger = Ledger(
        uid=uid,
        biz_type=biz_type,
        delta=amount_cent,
        balance_after=new_balance,
        idempotency_key=idempotency_key,
    )
    session.add(ledger)
    session.flush()  # 触发 (idempotency_key, biz_type) 唯一索引，重复入账立即失败
    return ledger


def debit(
    session: Session, uid: str, amount_cent: int, idempotency_key: str, biz_type: str
) -> Ledger:
    """扣款：条件更新保证 balance≥amount（约定：不得先读余额再无条件覆盖）。

    不足抛 InsufficientBalanceError。需在事务内调用。
    """
    _ensure_account(session, uid)
    new_balance = session.execute(
        update(Account)
        .where(Account.uid == uid, Account.available_cent >= amount_cent)
        .values(available_cent=Account.available_cent - amount_cent)
        .returning(Account.available_cent)
    ).scalar_one_or_none()
    if new_balance is None:
        have_cent = session.scalar(
            select(Account.available_cent).where(Account.uid == uid)
        )
        raise InsufficientBalanceError(uid, amount_cent, have_cent or 0)
    ledger = Ledger(
        uid=uid,
        biz_type=biz_type,
        delta=-amount_cent,
        balance_after=new_balance,
        idempotency_key=idempotency_key,
    )
    session.add(ledger)
    session.flush()
    return ledger


def get_balance(session: Session, uid: str) -> int:
    """余额查询：返回可用余额（分）。账户不存在视为 0（约定：初始为 0）。"""
    account = session.get(Account, uid)
    return account.available_cent if account is not None else 0


def freeze(session: Session, uid: str, amount_cent: int, payment_id: str) -> Ledger:
    """原子转移可用资金到冻结资金；由调用方统一提交，重复业务由支付记录保护。"""
    if type(amount_cent) is not int or amount_cent <= 0:
        raise ValueError("冻结金额必须为正整数分")
    _ensure_account(session, uid)
    balance = session.execute(
        update(Account).where(Account.uid == uid, Account.available_cent >= amount_cent)
        .values(available_cent=Account.available_cent - amount_cent,
                frozen_cent=Account.frozen_cent + amount_cent,
                version=Account.version + 1)
        .returning(Account.available_cent)
    ).scalar_one_or_none()
    if balance is None:
        raise InsufficientBalanceError(uid, amount_cent, get_balance(session, uid))
    ledger = Ledger(uid=uid, biz_type="payment", delta=-amount_cent,
                    balance_after=balance, idempotency_key=payment_id)
    session.add(ledger)
    session.flush()
    return ledger


def release_payment(session: Session, payment: Payment, refund_id: str) -> Ledger:
    """只释放指定支付的冻结额，状态条件更新与资金、流水处于调用方事务。"""
    from ....common import fail
    changed = session.execute(update(Payment).where(
        Payment.id == payment.id, Payment.status == "succeeded", Payment.funds_status == "frozen"
    ).values(funds_status="refunded"))
    if changed.rowcount != 1:
        fail(409, "ORDER_CONFLICT", "支付资金已退款、已结算或未冻结")
    balance = session.execute(update(Account).where(
        Account.uid == payment.payer_uid, Account.frozen_cent >= payment.amount
    ).values(available_cent=Account.available_cent + payment.amount,
             frozen_cent=Account.frozen_cent - payment.amount,
             version=Account.version + 1).returning(Account.available_cent)).scalar_one_or_none()
    if balance is None:
        fail(409, "ORDER_CONFLICT", "冻结资金不足，无法解冻")
    ledger = Ledger(uid=payment.payer_uid, biz_type="refund", delta=payment.amount,
                    balance_after=balance, idempotency_key=refund_id)
    session.add(ledger)
    session.flush()
    return ledger


def settle_payment(session: Session, payment: Payment, courier_uid: str,
                   income_cent: int, settlement_id: str):
    """原子消耗指定支付冻结资金，并给取件员入账；平台份额由结算审计留账。"""
    from ....common import fail
    if (type(income_cent) is not int or not 0 <= income_cent <= payment.amount
            or not courier_uid or courier_uid == payment.payer_uid):
        fail(409, "ORDER_CONFLICT", "结算收款人或金额无效")
    changed = session.execute(update(Payment).where(
        Payment.id == payment.id, Payment.status == "succeeded", Payment.funds_status == "frozen"
    ).values(funds_status="settled"))
    if changed.rowcount != 1:
        fail(409, "ORDER_CONFLICT", "支付资金已结算、已退款或未冻结")
    changed = session.execute(update(Account).where(
        Account.uid == payment.payer_uid, Account.frozen_cent >= payment.amount
    ).values(frozen_cent=Account.frozen_cent - payment.amount, version=Account.version + 1))
    if changed.rowcount != 1:
        fail(409, "ORDER_CONFLICT", "冻结资金不足，无法结算")
    # 0 收益允许存在（100% 佣金且无小费），仍在 Settlement 中完整留账。
    if income_cent:
        credit(session, courier_uid, income_cent, settlement_id, "settlement")
