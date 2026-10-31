# Finance 数据库升级

本轮加入 `account.frozen_cent`：整数分、非空、默认 0，独立于可用余额 `available_cent`。
钱包 HTTP 响应保持团队现有契约；本轮不提供冻结、解冻或支付接口。

新数据库使用团队初始化脚本建表。已有数据库在停止应用后，从 `backend` 目录运行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.finance.migrate_frozen
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
