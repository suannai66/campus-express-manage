# Finance 数据库升级

本轮加入 `account.frozen_cent`：整数分、非空、默认 0，独立于可用余额 `available_cent`。
钱包 HTTP 响应保持团队现有契约；支付冻结接口见下文，解冻和结算后续实现。

新数据库使用团队初始化脚本建表。已有数据库在停止应用后，从 `backend` 目录运行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.finance.migrate_frozen
..\.venv\Scripts\python.exe scripts/init_db.py
```

命令使用公共数据库配置（支持 `CAMPUS_DATABASE_PATH`），保留账户余额和流水；
重复运行不会重置已存在的冻结金额。仅支持 SQLite，不在应用启动时自动修改表结构。
升级前请备份需要保留的本地数据库。不要仅运行 `create_all` 来升级旧表，它不会添加列。

## 支付冻结

`POST /api/pay/prepay` 输入 `orderId`、`paymentRequestId`，必须登录并提供
`Idempotency-Key`。须先经 B 的 payment-request 接口取得有效预占。
金额只读取订单快照；成功后可用余额减少、冻结余额增加，同事务保存支付事实、
流水、HTTP 幂等记录和待投递事件。余额不足返回 HTTP 200 的 failed 确定结果，
同一预占之后即使充值也不会变为成功，必须由 B 在失败事件消费后重新预占。
同一订单只能有一个成功支付，重复预占或换键不会重复冻结。

`GET /api/pay/payments/{paymentId}` 仅付款人可查。
支付冻结流水对外使用既有 `payment` 类型，并返回实际关联的 orderId。
已有数据库先升级 frozen_cent，再运行团队初始化脚本创建 finance_payments 表。

### 事件接入限制

finance_payments.event 保存团队格式事件，event_status 初始 pending。
这是支付事实附带的待投递数据，不是公共 outbox 或完整的重试投递器。
当前没有自动投递任务，支付响应 succeeded 仅表示资金已冻结；订单会保持 paying，
直至 A 的公共组件将该事件投递至 B 的 orders.handlers.handle。
生产代码不直接调用 B 的消费者，不能人工重复发起支付来解除预占。
后续与 A 对齐公共组件后，应接入其同事务发布能力及投递确认、重试机制。
本轮不实现取消退款、配送完成结算，也不修改队友的订单/履约业务代码。

## 与 A 的公共事件接口对接（队长已确认，组件尚未实现）

- `app.events.publish(db, event)`：未来在支付用例同一 Session、提交之前调用，
  只保存 outbox；失败必须连同冻结、流水、支付事实、幂等记录一起回滚。
- `register_consumer(event_type, consumer_name, handler)`：由 A 在启动入口统一装配；
  B 的消费者为 `orders.handlers.handle(db, event)`，消费者不得自行提交。
- 当前不导入不存在的 app.events，不用直接调用 B 或超时解除预占替代投递。
- 已有支付从 finance_payments.event 读取完整 envelope，复用原 eventId 补录 outbox；
  不生成新 eventId，不重新冻结或重建支付记录。补录与标记已入 outbox 应同事务进行；
  event_status=pending 仅表示等待公共接入，不能当作已成功投递。
- version=1 属于支付聚合，与订单版本无关。
- 后续结算只消耗冻结资金，不再扣可用余额；允许取消时全额解冻并发布
  refund.succeeded，原支付状态保留 paid。这两条由队长确认，本轮尚未实现。

成功/失败 envelope 样例见同目录 payment-event-examples.json；均为虚构数据，
只用于核对字段，不应直接投递到共享数据库。
