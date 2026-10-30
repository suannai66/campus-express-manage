"""资金领域核心：全部资金状态变更的唯一入口（借用 A 的"不变量强制封装纪律"）。

对应团队接口约定 v1.1 第 11 节的 WalletService.changeBalance（D 独占维护，
支付/退款/充值/提现/结算均经此能力；余额、流水、业务记录与去重记录同事务保存）。

不变量（信息隐藏，外部无法绕过）：
- 余额不为负；扣款使用条件更新（WHERE balance >= amount），不先读余额再无条件覆盖
- 每笔余额变动必有流水，余额更新与流水同库事务（Q-03）
- 幂等：幂等键 + ledger 唯一索引兜底，重复请求返回首次结果（Q-04）

事务约定（团队规范：写操作由业务层显式管理事务）：
本模块函数假定调用方已持有事务（with session.begin(): 内调用），自行不提交。
"""

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Account, Ledger


class InsufficientBalanceError(Exception):
    """余额不足（约定：确定失败 code=INSUFFICIENT_BALANCE，余额不得为负）。"""

    def __init__(self, uid: str, need_cent: int, have_cent: int) -> None:
        self.uid = uid
        self.need_cent = need_cent
        self.have_cent = have_cent
        super().__init__(f"余额不足：需要 {need_cent} 分，可用 {have_cent} 分")


def _ensure_account(session: Session, uid: str) -> Account:
    """获取账户，不存在则创建（可用余额 0，约定：用户余额初始为 0）。需在事务内调用。"""
    account = session.get(Account, uid)
    if account is None:
        account = Account(uid=uid, available_cent=0)
        session.add(account)
        session.flush()
    return account


def credit(
    session: Session, uid: str, amount_cent: int, idempotency_key: str, biz_type: str
) -> Ledger:
    """入账：可用余额增。需在事务内调用；幂等由唯一索引兜底，重复写抛 IntegrityError。"""
    account = _ensure_account(session, uid)
    account.available_cent += amount_cent
    ledger = Ledger(
        uid=uid,
        biz_type=biz_type,
        delta=amount_cent,
        balance_after=account.available_cent,
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
    account = _ensure_account(session, uid)
    new_balance = session.execute(
        update(Account)
        .where(Account.uid == uid, Account.available_cent >= amount_cent)
        .values(available_cent=Account.available_cent - amount_cent)
        .returning(Account.available_cent)
    ).scalar_one_or_none()
    if new_balance is None:
        raise InsufficientBalanceError(uid, amount_cent, account.available_cent)
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