"""资金领域核心：全部资金状态变更的唯一入口（借用 A 的"不变量强制封装纪律"）。

不变量（信息隐藏，外部无法绕过）：
- 余额不为负，扣款超余额直接拒绝（Q-02 无超扣）；v1 账户仅可用余额，冻结字段后续迭代引入
- 每笔余额变动必有流水，余额更新与流水同库事务（Q-03）
- 幂等：幂等键 + ledger 唯一索引兜底，重复请求返回首次结果（Q-04）

事务约定（团队规范：写操作由业务层显式管理事务）：
- 低层函数 credit / debit / get_balance 假定调用方已持有事务（with session.begin():）；
- 带 _idempotent 后缀的对外入口自带事务，供单步用例（如充值回调）直接调用，
  不要在外层事务中调用它们。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Account, Ledger


class InsufficientBalanceError(Exception):
    """余额不足（FR3.5 同类校验，提现等扣款场景复用）。"""

    def __init__(self, uid: str, need_cent: int, have_cent: int) -> None:
        self.uid = uid
        self.need_cent = need_cent
        self.have_cent = have_cent
        super().__init__(f"余额不足：需要 {need_cent} 分，可用 {have_cent} 分")


def _ensure_account(session: Session, uid: str) -> Account:
    """获取账户，不存在则创建（可用余额 0）。需在事务内调用。"""
    account = session.get(Account, uid)
    if account is None:
        account = Account(uid=uid, available_cent=0)
        session.add(account)
        session.flush()
    return account


def _find_ledger(session: Session, idempotency_key: str, biz_type: str) -> Ledger | None:
    return session.execute(
        select(Ledger).where(
            Ledger.idempotency_key == idempotency_key, Ledger.biz_type == biz_type
        )
    ).scalar_one_or_none()


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
    """扣款：可用余额减，不足抛 InsufficientBalanceError。需在事务内调用。"""
    account = _ensure_account(session, uid)
    if account.available_cent < amount_cent:
        raise InsufficientBalanceError(uid, amount_cent, account.available_cent)
    account.available_cent -= amount_cent
    ledger = Ledger(
        uid=uid,
        biz_type=biz_type,
        delta=-amount_cent,
        balance_after=account.available_cent,
        idempotency_key=idempotency_key,
    )
    session.add(ledger)
    session.flush()
    return ledger


def credit_idempotent(
    session: Session, uid: str, amount_cent: int, idempotency_key: str, biz_type: str
) -> tuple[Ledger, bool]:
    """幂等入账（自带事务）：重复调用返回首次流水，余额不变。返回 (流水, 是否首次)。

    说明：入账前需先查幂等键，查询会隐式开启事务（autobegin），因此此处不用
    session.begin()，而以显式 commit/rollback 管理事务边界。
    """
    existing = _find_ledger(session, idempotency_key, biz_type)
    if existing is not None:
        session.rollback()  # 只读检查，回滚释放隐式事务
        return existing, False
    try:
        ledger = credit(session, uid, amount_cent, idempotency_key, biz_type)
        session.commit()
        return ledger, True
    except IntegrityError:
        session.rollback()
        first = _find_ledger(session, idempotency_key, biz_type)
        assert first is not None, "唯一索引冲突但未找到首次流水，属异常状态"
        session.rollback()
        return first, False


def get_balance(session: Session, uid: str) -> tuple[int, int]:
    """FR1 余额查询：返回 (可用余额, 冻结余额)。v1 无冻结字段，冻结恒为 0。"""
    account = session.get(Account, uid)
    if account is None:
        return 0, 0
    return account.available_cent, 0