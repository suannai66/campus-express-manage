"""资金表 Schema（阶段 3.3 调整 C，附件 2 数据设计）。

- account: (uid PK, available_cent, frozen_cent, version)
  统一虚拟账户，可用/冻结两项余额，金额以"分"整数存储（FR1.2/FR1.3）；
  version 用于乐观锁记录（正确性最终依赖行锁与事务）。
- ledger:  (id, uid, biz_type, delta, balance_after, idempotency_key,
           created_at, UNIQUE(idempotency_key, biz_type))
  全部资金变动流水；幂等键唯一索引是幂等兜底（Q-04）；流水保留 ≥ 2 年（NFR2.4）。
- recharge_order / withdraw_order：充值单与提现单（状态机：pending/processing/
  success/failed/closed），独立于资金双表。

TODO(团队对齐) 数据库驱动与 ORM 未定（SQLAlchemy 或 pymysql），
连接串与 .env 约定待队长统一；本文件届时按团队方案落地为模型或建表 SQL。
"""
