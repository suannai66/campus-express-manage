# Finance 数据库升级

本轮加入 `account.frozen_cent`：整数分、非空、默认 0，独立于可用余额 `available_cent`。
钱包 HTTP 响应保持团队现有契约；支付冻结、取消解冻和配送结算已实现，事件统一接入公共 outbox。

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

### 公共事件接入

finance_payments.event 保留原始完整事件。新支付在资金业务事务内调用
app.events.publish(db, event)，event_status=outbox_saved 表示已入公共 outbox，
不表示 B 已消费。后台任务每秒扫描并投递至 B，B 成功提交后订单才由 paying→paid。
消费者失败不会重新冻结或将成功付款改为失败；生产代码不直接调用 B 的消费者。

## 公共接口与历史事件补录

- `app.events.publish(db, event)`：已在支付/退款用例同一 Session、提交之前调用，
  只保存 outbox；失败必须连同冻结、流水、支付事实、幂等记录一起回滚。
- `register_consumer(event_type, consumer_name, handler)`：由 A 在启动入口统一装配；
  B 的消费者为 `orders.handlers.handle(db, event)`，消费者不得自行提交。
- app.events 已实现；不用直接调用 B 或超时解除预占替代投递。
- 后台对 pending 的历史支付/退款读取完整 envelope，复用原 eventId 补录 outbox；
  不生成新 eventId，不重新冻结或重建支付记录。补录与标记已入 outbox 应同事务进行；
  event_status=pending 仅表示尚未入箱，outbox_saved 也不能当作已成功投递。
- version=1 属于支付聚合，与订单版本无关。
- 结算只消耗冻结资金，不再扣可用余额；允许取消时全额解冻并发布
  refund.succeeded，原支付状态保留 paid。实际投递状态见 outbox_deliveries。
- 重试、租约、dead 维护命令及 C 的对接职责统一见根目录 docs/团队接口约定.md 第 12 节。

成功/失败 envelope 样例见同目录 payment-event-examples.json；均为虚构数据，
只用于核对字段，不应直接投递到共享数据库。

## 取消解冻消费者

由 A 注册 `order.cancelled` → consumer_name=`finance` →
`app.modules.finance.services.event_handlers.on_order_cancelled(db, event)`。
消费者只使用传入 Session，不提交、不新开事务；投递方须在异常时回滚。
严格校验完整 envelope、事件摘要、取消事实、发布者、支付 ID 与金额。

未支付取消只保存消费回执，不移动资金。已支付取消以条件更新将支付资金状态
frozen→refunded，并将全部冻结金额转回可用余额；同事务保存 refund 流水、
finance_refunds 退款记录和 finance_event_receipts 去重回执。
订单和支付维度的唯一约束保证换 eventId 也不重复退款；已结算资金不能退款。
结算端也通过 frozen 状态条件更新与退款互斥。

退款表保存完整 refund.succeeded envelope、稳定 eventId 和 outbox_saved 标记，
在同一消费事务内调用 publish；退款、流水、回执、下游事件与本次投递确认一起提交。
B 消费后更新 refundStatus，原 paymentStatus 保留 paid。历史 pending 退款只补录，不重新退款。

新增 finance_refunds、finance_event_receipts 均为新表，无旧表删改。
停止应用并备份共享库后，从 backend 运行：

```powershell
..\.venv\Scripts\python.exe scripts/init_db.py
```

此前尚未升级 frozen_cent 的库仍须先执行上文冻结字段升级命令。
现有余额、订单、认证、流水均保留。不新增匿名退款 HTTP 接口。

## 配送完成结算

A 在公共事件组件中注册 `order.completed` → consumer_name=`finance` →
`app.modules.finance.services.event_handlers.on_order_completed(db, event)`。
消费者使用投递方 Session，不自行提交。校验已送达订单、付款人、取件员、
成功支付事实、金额、基础费、小费与费率版本；不得从事件覆盖订单快照。

平台佣金 = 订单 base_fee × 订单 commission_bps // 10000；
取件员收益 = amount - 佣金，小费全部归取件员。使用订单快照，不读取最新费率结算历史订单。
以 Payment.funds_status 的 frozen→settled 条件更新与退款 frozen→refunded 互斥。
消耗客户冻结资金，不再扣客户可用余额；取件员收益写 settlement 流水。
finance_settlements 独立保存客户冻结消耗、取件员收入、平台佣金及费率快照作为审计，
平台佣金可汇总该表，不伪造学生 UID 或占用用户钱包记录平台资金。

同订单、同支付各最多一笔结算，换 eventId 仍返回原结算；同 eventId 不同内容返回冲突。
资金更新、取件员流水、结算审计、消费回执必须同事务提交或回滚。
没有新增 settlement.succeeded 事件（团队契约未定义），也不直接修改 C/B 的订单状态。
公共投递器已注册此消费者；C 交付实际完结业务入口并同事务发布 order.completed 后即可投递。
C 自己的评价订阅尚未装配时单独保留重试，不影响已成功的资金结算。

本轮只新增 finance_settlements 表。停止应用、备份共享库后，从 backend 执行
`..\.venv\Scripts\python.exe scripts/init_db.py` 即可无损创建新表；
此前未添加 frozen_cent 的库先运行冻结字段升级命令。

## 交易专项验收

专项测试位于 tests/test_finance_trade_audit.py，使用隔离临时数据库：

- 同一客户三笔支付，一笔退款、一笔结算，第三笔保持原冻结额；
  全部账户可用额与冻结额加平台佣金等于最初充值额。
- 错用另一订单的支付 ID 拒绝解冻，不移动任何资金。
- 在资金核心同时争用同一笔支付执行退款和结算，只有一方成功，另一方冲突。
- 超前于数据库订单版本的取消/完结事件拒绝处理；合法旧事件不按版本简单丢弃。
- 模拟旧共享库，保存身份、认证、会话、订单、账户、流水数据后升级，
  检查原有行保留，并验证升级后可正常支付和退款。

资金专项测试验证本地资金及消费者事务；公共事件联调另见 tests/test_events.py、
tests/test_events_integration.py。C 的生产业务入口仍待其交付，不能将测试内的网关动作算作已交付接口。

## 真实身份与后台自动投递联调

`tests/test_finance_full_chain.py` 使用隔离临时数据库，通过真实 HTTP 接口完成：
注册登录、认证资料提交、管理员审核、充值确认、服务端报价、发单支付、
接单配送结算，以及另一条支付后取消退款链路。
启用应用实际启动的后台事件投递器，不手动调用 dispatch_once 或消费者，
确认最终全部投递 succeeded、资金与流水一致。
仅短信使用受控演示码，初始管理员角色在测试装配中设置；不访问共享开发库。
该验证属于 API/服务集成测试，不代表浏览器交互已验收。

## 浏览器交易验收

从 frontend 运行 `npm run test:finance`，使用独立端口和临时数据库，
后端为真实 A/B/C/D 与后台投递器，虚构账号经注册登录和认证审核准备。
浏览器通过 sessionStorage 恢复真实登录凭证；页面执行充值、报价发单、支付、
接单配送、余额和流水查询、取消退款。另验证充值确认响应丢失后同键重试，
以及 390px 钱包布局、确认防连点与刷新恢复。

本机使用系统 Edge 验证（PowerShell：`$env:PW_BROWSER_CHANNEL='msedge'`），
未安装 Playwright 内置 Chromium 时可使用该配置。截图和失败 trace 保存到
frontend/test-results（已忽略，不提交）。钱包充值/确认/提现增加提交中保护，
提现申请成功后立即刷新可用余额，无需等模拟到账后才显示扣款。

## 提现失败回补与正式模式充值确认

- 继续使用公共 CAMPUS_MODE=demo/production，由启动入口读取并固定。
  production 下充值 confirm 返回 404，先于幂等结果重放检查；请求头、查询参数
  不能打开演示入口。不支持真实充值回调，不代表生产支付已实现。
- 默认模拟提现结果为 succeeded。仅在受控演示/测试启动配置中设置
  FIN_WITHDRAW_DEMO_OUTCOME=failed 可演示失败；不提供客户端指定结果的 HTTP 接口。
- 提现最早 3 秒后处理。失败原因保存到已有 fail_reason，状态 processing→failed
  条件更新、金额全额回补及唯一业务键流水同事务保存。技术异常回滚后保留 processing，
  下一轮重试，不能把暂时数据库异常当作确定打款失败。
- 回补流水沿用 withdrawal 类型、direction=in，原扣款为 direction=out，
  不增加团队未批准的流水枚举或响应字段。钱包页面显示提现失败并刷新余额。
- 成功和失败是互斥终态，重复扫描、并发失败或成功/失败竞争不会重复回补。
  本轮没有模型字段变化，不需要数据库迁移。
- test_finance_wallet_safety.py 覆盖模式限制、并发、回补幂等、错误回滚与恢复；
  finance 浏览器配置启用受控失败结果，验证真实后台处理后的余额和流水。
