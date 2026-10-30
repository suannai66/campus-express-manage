"""资金领域核心：全部资金状态变更的唯一入口（借用 A 的"不变量强制封装纪律"）。

不变量（信息隐藏，外部无法绕过）：
- 余额不为负；账户仅可用/冻结两项，无欠款字段（FR1.2）
- 每笔余额变动必有流水，余额变动与流水同库事务（Q-03）
- 状态转移触发源唯一：结算仅由完结事件、解冻仅由取消事件触发（FR4/FR5）
- 幂等：幂等键 + ledger 唯一索引兜底，重复请求返回首次结果（Q-04）

实现约束（阶段 3.3 调整 C）：
- SELECT ... FOR UPDATE 锁 account 行 → 计算新余额 → 写 ledger → 单事务提交
- 多账户结算按账户 ID 固定顺序加锁，防死锁（FR4.5）
- 本模块为资金表唯一写入口，禁止其他模块直写 account / ledger 表
"""


def freeze(uid: str, amount_cent: int, idempotency_key: str) -> None:
    """FR3 冻结：可用余额减、冻结余额增，原子完成；余额不足抛业务错误（订单不进大厅）。"""
    # TODO(迭代7) 行锁 + 事务 + 幂等键唯一索引兜底
    raise NotImplementedError("TODO(迭代7): 实现冻结")


def unfreeze(uid: str, amount_cent: int, idempotency_key: str) -> None:
    """FR5 解冻：冻结余额减、可用余额增。已结算订单不再解冻（由调用方状态机保证）。"""
    raise NotImplementedError("TODO(迭代7): 实现解冻")


def settle(
    customer_uid: str,
    courier_uid: str,
    amount_cent: int,
    idempotency_key: str,
) -> None:
    """FR4 完结结算：客户冻结扣减 + 取货员 T+0 入账 + 平台服务费只记流水。

    三项金额恒等：服务费 + 取货员到账 = 订单金额（fee_util.split_settlement）；
    涉及多账户时按账户 ID 固定顺序加锁（FR4.5）。
    """
    raise NotImplementedError("TODO(迭代7): 实现结算")


def penalize(
    courier_uid: str,
    customer_uid: str,
    penalty_cent: int,
    idempotency_key: str,
) -> None:
    """FR6 超时赔付：扣取货员超时费补偿客户；取货员余额不足扣至 0 为止，不追偿。

    F6 信用扣分由事件编排层联动（本模块不维护信用数据）。
    """
    raise NotImplementedError("TODO(迭代7): 实现超时赔付")


def credit(uid: str, amount_cent: int, idempotency_key: str) -> None:
    """入账（充值回调，FR7.3）：可用余额增。重复回调只入账一次（幂等键唯一索引）。"""
    raise NotImplementedError("TODO(迭代7): 实现入账")


def debit(uid: str, amount_cent: int, idempotency_key: str) -> None:
    """扣款（提现到账，FR8.2）：扣减冻结余额。"""
    raise NotImplementedError("TODO(迭代7): 实现扣款")


def get_balance(uid: str) -> tuple[int, int]:
    """FR1 余额查询：返回 (可用余额, 冻结余额)，单位分。"""
    raise NotImplementedError("TODO(迭代7): 实现余额查询")
