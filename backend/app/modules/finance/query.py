"""流水查询（FR9）：分页 ≤100、组合条件、身份视角过滤；仅本人可见，越权拒绝（Q-05）。

读模型与写模型分离：查询逻辑不进入资金事务路径（core/wallet_core.py）。
"""

from . import config


def query_ledger(
    uid: str,
    page: int = 1,
    page_size: int = 20,
    *,
    order_id: str | None = None,
    biz_no: str | None = None,
    ledger_no: str | None = None,
    biz_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
    role: str | None = None,
) -> dict:
    """FR9 流水分页查询。

    组合条件：订单号 / 业务单号 / 流水号 / 流水类型 / 时间范围；
    身份视角（role）：作为客户的支出 / 作为取货员的收入。
    权限约束：结果强制限定 uid 本人，越权请求拒绝。

    TODO(迭代7) page_size 上限取 config.LEDGER_PAGE_SIZE_MAX；写 SQL 查询与分页。
    """
    raise NotImplementedError("TODO(迭代7): 实现流水查询")
