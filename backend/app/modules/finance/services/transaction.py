"""钱包 HTTP 用例统一提交或回滚，包括公共身份查询触发的自动事务。

只供顶层钱包编排使用，不供仓储、领域能力或外部事务内部调用。
不使用 begin_nested：保存点释放不等于请求已提交。
"""

from contextlib import contextmanager
from collections.abc import Iterator
from sqlalchemy.orm import Session


@contextmanager
def wallet_transaction(db: Session) -> Iterator[None]:
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise
