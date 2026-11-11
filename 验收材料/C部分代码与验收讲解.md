# C 部分完整代码与验收讲解

对应仓库：campus-express-manage；原功能提交：51b14f7；本材料按 2026-11-11 当前工作区的确认收货流程修订，源码基准和状态见末尾文件清单。

这是个人验收学习材料。接口规范仍以 [团队接口约定](D:/campusexpressmanage/docs/团队接口约定.md) 第 9、9.1、12 节为准。本材料前半部分逐模块解释，后半部分逐文件展示完整源码，包含模板、样式、测试及公共接入文件；公共文件另附本次修改差异，便于分清个人贡献。源码从当前工作区直接读取，未删节或用伪代码替代。

阅读顺序：先掌握“一分钟介绍”和业务链路，再看后端、前端算法，最后对照完整源码。现场讲述按功能展开，不需要逐行念 Vue 样式。

## 1. 一分钟介绍：我做了什么

可以直接这样说：

> 我负责 C 部分，包括 F5 接单履约和 F6 评价信用。我实现了接单资格检查、开始取件、确认取件、确认送达、发布者确认收货、接单前取消，以及完成后的双向评价和信用计算。代取员送达后先等待发布者收货，确认后才结算和开放评价；C 的履约操作不需要输入或核验取件码，页面也不展示。前端使用 Vue 3，后端使用 FastAPI，通过数据库版本号、事务、幂等记录和唯一约束保证竞争与重复操作下的数据正确。登录认证复用 A，订单主数据通过 B 的订单网关操作，退款与结算通过事件交给 D。我还补充了个人需求、验收标准、接口约束和自动测试。

个人实现与团队基础的界限如下。

| 归属 | 能力 | 本人做的部分 |
| --- | --- | --- |
| C | F5 接单、取件、配送、送达、收货、有限取消 | 实现 HTTP 接口、用例编排、权限与信用检查、操作日志、收货完成边界及 Vue 工作台 |
| C | F6 双向评价、信用 | 实现评价表、评价开放消费者、评价唯一性、最近 30 条均分及 Vue 页面 |
| A / 公共基础 | 登录、认证、公共错误、请求幂等工具、事件投递器 | C 调用这些接口和工具；新增自己的消费者注册 |
| B | 发布、大厅、订单详情/列表、订单主表与受控状态入口 | C 使用已有大厅接单按钮及订单查询，经 OrderGateway 推进订单 |
| D | 冻结、退款、佣金与结算 | C 发布取消/完结事实，提供快照字段；实际资金处理由 D 完成 |

原功能提交修改 22 个文件，新增 1950 行、删除 54 行；这是原提交的规模，本次确认收货流程还包含工作区修订。源码附录和差异按当前工作区重新生成，不把公共文件的全部既有代码计为个人原创。个人需求已在团队接口约定第 9.1 节，责任人仍为“成员 C（实际姓名待本人填写）”。

## 2. 需求、验收标准和可见成果

| 需求 | 用户能做什么 | 验收时看什么 |
| --- | --- | --- |
| C-F5-01 接单 | 认证通过且信用合格的用户接他人的已付款待接单订单 | 自接、未认证、低信用被拒；同单只能归一个取件员 |
| C-F5-02 履约 | 开始取件 → 确认取件 → 确认送达 | 顺序固定，仅本单取件员操作；版本变化有日志 |
| C-F5-03 收货完成 | 发布者在送达后确认收货 | 取件员不能代确认；收货前不结算、不评价，收货后才完结 |
| C-F5-04 取消 | 发布者在接单前取消 | 未付款无需退款；付款待接单取消先处理中，后显示真实退款结果 |
| C-F5-05 我的订单 | 身份/状态筛选、分页、详情和进度查询 | 每页 10 条，页面可见时每 10 秒刷新，离开停止 |
| C-F6-01 互评 | 完结后双方各评一次 | 1～5 星、标签和评论；重复提交拒绝，无修改入口 |
| C-F6-02 信用 | 查看取件信用和接新单资格 | 新人可接，最近最多 30 条有效评价，原始均分低于 3 分限制新单 |
| C-F6-03 评价查询 | 参与双方查询本单评价 | 无关用户不能查，评论按文本显示 |

质量要求集中在权限、合法状态、竞争互斥、收货完成边界、事务回滚、评价去重、信用边界、事件重试和手机可用性。每条要求都有后端或浏览器测试对应，见第 9 节。

## 3. 先理解整条业务链

~~~mermaid
flowchart TD
    A["A：注册登录、学生认证"] --> B["B：发布需求、创建订单"]
    B --> D["D：付款并冻结资金"]
    D --> P["B：消费支付成功，订单变为 pending"]
    P --> C["C：接单 accepted"]
    C --> S["C：开始取件 picking_up"]
    S --> V["C：取件员确认取件"]
    V --> R["配送中 delivering"]
    R --> E["C：确认送达 delivered"]
    E --> W["已送达待收货：不结算、不开放评价"]
    W --> U["C：发布者确认收货 completed"]
    U --> O["同事务保存 order.completed"]
    O --> F["D 消费：结算"]
    O --> G["C 消费：核验事实并开放评价"]
    G --> H["双方各评价一次"]
    H --> I["C：实时计算最近 30 条取件评价"]
    I --> J["后续接单时检查信用资格"]
~~~

订单状态是 B 的唯一主数据。C 没有复制订单表，也没有绕过网关直接修改余额。送达不等于订单完成；发布者确认收货的响应成功后，结算和评价开放可能稍后完成，两个消费者各自重试。

### 3.1 状态机

| 当前状态 | 动作 | 下一状态 | 执行人及附加条件 |
| --- | --- | --- | --- |
| pending | accept | accepted | 已认证、信用合格、非发布者，订单已付款 |
| accepted | start_pickup | picking_up | 已认证的本单取件员 |
| picking_up | confirm_pickup | delivering | 已认证的本单取件员，直接确认已取件 |
| delivering | confirm_delivery | delivered | 已认证的本单取件员 |
| delivered | confirm_receipt | completed | 已登录的本单发布者，确认包裹已经收到 |
| pending_payment 且 unpaid | cancel | cancelled | 发布者；无需退款 |
| pending 且 paid | cancel | cancelled | 发布者；退款处理中 |

C 不输入、不校验、不展示取件码，旧失败计数列仅为数据库兼容保留。支付处理中不能取消；接单后没有用户取消入口。确认送达由取件员执行，确认收货由发布者执行，两种动作与权限分开。

## 4. 后端模块逐一讲解

### 4.1 contract.py：先把不合法请求拦在业务入口外

文件：[contract.py](D:/campusexpressmanage/backend/app/modules/fulfillment/contract.py)。

| 定义 | 作用 | 逻辑 |
| --- | --- | --- |
| StatusInput | 履约动作请求 | 继承严格正整数 version，action 限定开始取件、确认取件、确认送达、确认收货四种动作；不声明 code 字段 |
| CancelInput | 取消请求 | 必须包含版本和 1～200 字取消原因 |
| Tag | 单个标签规则 | 去首尾空格，长度 1～20 |
| ReviewInput | 评价请求 | 严格整数 1～5 星，标签最多 5 个，评论最多 500 字 |

这里的“算法”是类型、范围、枚举与条件校验。公共 Input 拒绝额外字段并去掉字符串首尾空格，因此不能提交 uid 或 revieweeUid 冒充身份。version=true、version="3"、rating=1.5 都不合法。数据不合法先返回 422，不进入数据库更新。

标签限制数量但没有额外去重；后端接受的合法标签不局限于前端显示的五个选项。

### 4.2 models.py：用五张表保存 C 的业务事实

文件：[models.py](D:/campusexpressmanage/backend/app/modules/fulfillment/models.py)。

| 模型 / 表 | 主要字段 | 约束与意义 |
| --- | --- | --- |
| OperationLog / fulfillment_operations | order_id、actor_uid、action、from_status、status、order_version、reason、created_at | 记录谁在何时做了什么，取消原因可追溯 |
| Notification / fulfillment_notifications | order_id、uid、type、message、created_at | order_id + uid + type 唯一，防同类通知重复 |
| ReviewOpening / fulfillment_review_openings | order_id、fact_digest、created_at | order_id 主键，一单只开放一次评价 |
| ConsumerReceipt / fulfillment_event_receipts | event_id、digest、result | event_id 主键，保留消费结果及摘要 |
| Review / fulfillment_reviews | 双方 uid、reviewer_role、rating、tags、comment、created_at | order_id + reviewer_uid 唯一；数据库限制 1～5 星 |

表设计的关键是“在应用层判断之外，再由数据库兜底”。两个人为同一位用户同时提交同单评价，即便同时读到尚未评价，唯一约束也不允许产生两条。TABLES 集合供应用启动创建 C 的表。

操作日志保存在数据库，但本期没有专门的日志查询页面/API。C 的请求不接受取件码，履约响应裁剪 code，也不把取件码写进日志、通知或事件。B 的订单主表仍保留原发布资料，不能把 C 不处理取件码扩大为整个仓库没有该字段。通知表和旧列兼容保留，不能将历史锁单机制作为本次新流程演示。

### 4.3 api.py：HTTP 入口、权限隔离、分页与评价提交

文件：[api.py](D:/campusexpressmanage/backend/app/modules/fulfillment/api.py)。

路由统一以 /api 开头，依赖公共 current_identity 和 get_db。身份由已验证会话取得，客户端不提供操作者 uid。

| 函数 | 请求 | 实际处理 |
| --- | --- | --- |
| response | 内部辅助 | 按保存的 statusCode 和 body 返回 JSON，兼容幂等重放的成功/业务错误 |
| accept | POST /orders/{id}/accept | 接收 version、Idempotency-Key，转交 service.execute |
| advance | POST /orders/{id}/status | 只接收动作、版本，转交统一用例；包括发布者确认收货 |
| cancel | POST /orders/{id}/cancel | 接收原因、版本、幂等键，转交统一用例 |
| status | GET /orders/{id}/status | 校验参与关系，返回状态、支付/退款状态与版本 |
| notifications | GET /orders/{id}/notifications | 仅本人、本单的通知，支持分页 |
| credit | GET /users/{uid}/credit | 仅 uid 等于当前用户时允许查询 |
| review | POST /orders/{id}/reviews | 检查 completed 和评价开放，推导对方身份，原子插入一次评价 |
| reviews | GET /orders/{id}/reviews | 仅本单参与者读取双方评价，附 reviewable |

#### 查询权限算法

状态、通知、评价先调用 OrderGateway.related，要求当前 uid 是发布者或取件员。无关用户返回 404，避免披露资源信息。通知再按 Notification.uid 等于当前 uid 过滤。信用接口只允许本人读取。接单、开始取件、确认取件和确认送达检查学生认证；发布者确认收货、取消、查询、评价不重复调用 require_verified，不能把所有 C 接口都说成“必须再认证”。

#### 分页算法

pagination 拒绝 page、pageSize 之外的参数，并检查原始文本是 ASCII 十进制数字；FastAPI 再限制 page≥1、1≤pageSize≤100，默认 1/20。

~~~text
偏移量 = (page - 1) × pageSize
记录 = WHERE 业务条件
       ORDER BY created_at DESC, id DESC
       OFFSET 偏移量 LIMIT pageSize
总数 = 满足业务条件的 COUNT
~~~

例如第 3 页、每页 10 条，跳过 20 条。返回 items、total、page、pageSize；时间相同时用 id 保证排序稳定。前端自己的订单列表由 B 提供，排序规则不要和这里的通知/评价分页混淆。

#### 评价提交算法

1. 确认本人参与订单；订单必须 completed，且存在 ReviewOpening。
2. 当前用户是发布者，就评价取件员并标 reviewer_role=publisher；否则评价发布者并标 courier。
3. 被评价者由服务端推导，禁止自评。
4. SQLite 使用 INSERT ... ON CONFLICT DO NOTHING，冲突目标为 order_id、reviewer_uid。
5. 插入影响一行则提交并返回 201；未插入则返回 409 ALREADY_REVIEWED。

评价没有使用 Idempotency-Key。它通过“每人每单一次”的永久业务唯一性防重；重复提交返回冲突，不是再次返回原 201。没有 PATCH/DELETE 评价入口，提交后不可修改。

reviews 的 reviewable 仅表示 completed 且开放，不包含“当前人是否已经评过”；前端再结合已有本人评价判断是否显示表单。

### 4.4 service.py：接单、取消、履约的核心编排

文件：[service.py](D:/campusexpressmanage/backend/app/modules/fulfillment/service.py)。

#### execute 的固定处理顺序

~~~text
读取认证身份
→ 接单和取件配送动作检查学生认证，收货与取消除外
→ 经 replay_fulfillment 查询同用户、同操作、同键的请求回执
→ 获取订单只读快照
→ 检查操作者及接单信用
→ 检查 version
→ 经 OrderGateway 条件更新
→ 写操作日志及 outbox 事件
→ 保存本次请求的 HTTP 状态和响应
→ 统一 commit 一次
~~~

实际幂等作用域为 fulfillment:{operation}:{orderId}，operation 分 accept、status、cancel；status 的具体 action 和版本进入请求摘要。发布者确认收货也走相同幂等与版本机制。

辅助函数 emit 生成 UUID 事件 ID、UTC 时间，使用变更后订单版本，并把该版本写入 payload.orderVersion。record 写日志并发布 order.status_changed；只有 confirm_receipt 进入 completed 时额外发 order.completed。

#### 接单：资格判断加乐观并发控制

先禁止本人接自己的单，再通过 CreditService 判断信用。B 的网关还会验证 pending、paid，变更限定为 accepted 和当前取件员 uid。旧 locked 列不参与新流程。

真正解决“两人同时抢一单”的是数据库条件更新：

~~~sql
-- 说明性 SQL，具体实现使用 SQLAlchemy；完整实际源码见附录。
UPDATE orders
SET status = 'accepted', courier_uid = :uid, version = version + 1
WHERE id = :id
  AND version = :client_version
  AND status = :snapshot_status
  AND payment_status = :snapshot_payment_status;
~~~

只能影响一行。两人都拿版本 3，先成功的人把版本改为 4；另一个请求的 WHERE 条件不再匹配，返回 409。接单与取消也竞争同一行、同一版本，因此最多一个成功。Python 中先比版本用于尽早报错，最终保障来自数据库。没有使用 Redis 锁或内存锁。

#### 履约：有限状态机

以映射表把 action 转为固定的起点与终点。当前状态不等于起点就返回 409，不能从 accepted 直接跳到 delivered 或 completed。开始取件、确认取件和送达限定本单取件员；确认收货限定本单发布者。服务层和 B 网关分别检查规则。

#### 收货完成算法与事件边界

~~~text
action = confirm_receipt 时：
  当前用户必须等于 publisher_uid
  当前状态必须为 delivered，version 必须匹配
  条件更新 delivered → completed，version + 1
  保存操作日志、order.status_changed、order.completed、幂等回执
  同一事务提交
其余三种动作：由 courier_uid 执行，仅推进到下一配送状态
confirm_delivery 到 delivered：不发 order.completed，资金仍冻结
~~~

这样把“配送者报告已送达”与“接收者确认收到”拆为两个业务事实。取件员不能替发布者确认收货，旁人不能操作，重复请求复用结果，旧版本和跳步不能覆盖事实。confirm_pickup 只确认已取件，不执行验证码比较或错误次数累加。

#### 取消与退款

发布者可取消 unpaid 的 pending_payment 订单，结果 refundStatus=none；也可取消 paid 的 pending 订单，结果 processing。paying 禁止取消，accepted 之后也不能取消。

取消同事务保存日志、order.status_changed 和 order.cancelled。C 不直接退钱。D 消费取消事件解冻资金，发布 refund.succeeded，B 再把退款状态改成 succeeded。首次取消返回 processing 仅表示申请已记录，不能演示成“钱立即已到账”。

#### 收货与资金边界

进入 completed 时额外发布 order.completed，携带双方 uid、amount、baseFee、tip、commissionRateBps、pricingVersion、orderVersion。delivered 时不发完结事件，D/C 消费者也拒绝尚未 completed 的完结事实。金额是整数分，使用订单原有快照。D 消费后计算结算；C 不直接写钱包或佣金。订单完结事件不携带取件码、手机号、Token 或证件。

#### 事务与请求幂等

订单更新、日志、outbox、请求回执使用同一个 Session、一次 commit。中途保存事件失败，会话回滚，不留下半个成功结果。发布者确认收货的 completed 更新与完结事件必须一起成功或一起失败，避免订单显示完成却丢失结算事实。

C 的 replay_fulfillment 与公共 remember 用 uid、operation、key 定位请求，并比较规范化 JSON 的 SHA-256 摘要。replay_fulfillment 还兼容历史三种配送动作缺省 code:null 的摘要；成功回执返回前裁剪 code、locked、pickupFailureCount，既有错误仍按原错误重放，不修改旧回执、不重新执行业务。带明确旧码的摘要不会被无 code 请求命中，也不能将旧错码结果改成成功。新提交携带 code 仍在契约入口返回 422，兼容逻辑不放宽新请求：

| 情形 | 结果 |
| --- | --- |
| 第一次同键请求 | 执行业务并保存结果 |
| 同键同内容重试 | 返回原 statusCode/body，版本后来变化也不重做 |
| 同键换内容 | 409 IDEMPOTENCY_CONFLICT |
| 同业务换新键、旧版本 | 不命中原回执，由状态/版本限制拒绝 |

版本号防旧请求覆盖和并发冲突；幂等键识别同一次命令的重复投递；二者用途不同。公共回执唯一约束也提供兜底。现有 C 测试验证顺序重放和业务竞争，没有专门承诺所有数据库繁忙情况或同键首次并发都返回同一种友好错误。

### 4.5 handlers.py：完结后可靠开放评价

文件：[handlers.py](D:/campusexpressmanage/backend/app/modules/fulfillment/handlers.py)。

on_order_completed 的处理：

1. 公共 validate 检查事件格式并计算整条事件摘要，只接受 order.completed。
2. 按 eventId 查 ConsumerReceipt；相同 ID、相同摘要直接返回旧结果，内容改变则冲突。
3. 读取订单快照，必须 completed，事件版本必须与订单版本一致；delivered 不能冒充完结。
4. 完整比对双方身份、金额、基础费、小费、佣金比例、计价版本、订单版本。
5. 对这些完结事实计算 fact_digest；ReviewOpening 以 order_id 为主键，一单只开一次。
6. 同事实换 eventId 可复用开放标记；事实变了则拒绝。
7. 保存消费回执并 flush，交给公共投递器提交，不自行 commit。

这是两层去重：eventId 去重负责重复投递；订单完结事实去重负责换 ID 的同一业务。摘要用于识别内容一致性，不是数字签名，也不提供来源鉴权。

公共投递器统一提交“评价开放 + C 回执 + 投递成功标记”。D 和 C 是两个独立消费者；C 失败时 D 可能已结算，随后只重试 C，不让 D 再结算。C 不自行实现新的调度器，也不在消费者内另开会话。

### 4.6 credit.py：最近 30 条取件评价的实时均分

文件：[credit.py](D:/campusexpressmanage/backend/app/modules/fulfillment/credit.py)。

CreditService.get 的 SQL 筛选逻辑：

~~~text
被评价人 = 当前用户
并且评价者角色 = publisher
按 created_at 降序、id 降序
取最多 30 条 rating
~~~

评价者是发布者，意味着被评价人在该单扮演取件员。因此只统计“作为取件员收到的评价”。取件员给发布者的评价会保存和展示，但不计入发布者的取件信用；本人给别人打高分也不能提高自己的信用。

~~~text
n = 本次有效评价数，最多 30
原始均分 = Decimal(星级之和) / n
展示分 = 原始均分按 ROUND_HALF_UP 保留两位小数
~~~

| 有效评价 | score | level | creditEligible |
| --- | --- | --- | --- |
| 0 条 | null | new | true |
| 原始均分 < 3 | 两位展示 | restricted | false |
| 3 ≤ 原始均分 < 4 | 两位展示 | normal | true |
| 原始均分 ≥ 4 | 两位展示 | good | true |

例：[1,5] 得 3.00，正常可接；[3,5] 得 4.00，良好可接；[2,3,3] 得 2.67，限制新接单。判断资格使用未舍入均值，展示才四舍五入。没有评价表示未知的新人，不是 0 分。

“最近 30 条”先筛角色、再排序取样、最后平均；未评价订单不计入分母。31 条时旧的第 31 条退出窗口。reviewCount 是本次样本数，不是累计完成订单数。应用内求和最多处理 30 个值；数据库仍需要过滤排序，不能把整个查询简单宣称为 O(1)。

这里直接查询评价表计算，没有另存一份可能过期的信用分。后续查询能看到新评价；页面显示仍可能等待轮询。信用只限制新接单，已接订单仍允许继续履约。

### 4.7 migrate_receipt.py：用历史事实区分旧完结与新待收货

文件：[migrate_receipt.py](D:/campusexpressmanage/backend/app/modules/fulfillment/migrate_receipt.py)。

旧版 delivered 已表示完成并发过完结事件，新版 delivered 表示等待发布者收货。不能仅按状态批量把所有 delivered 改成 completed，否则会把新订单提前完成。迁移采用事实匹配算法：

1. 仅支持 SQLite，开启 BEGIN IMMEDIATE，将本批升级放在同一事务中。
2. 读取 delivered 订单，查找该单旧 order.completed outbox；无事件就保留待收货。
3. 对每条旧事件做公共格式校验，核对存储摘要，并比对订单 ID、版本、双方身份、金额和费率快照。
4. 全部匹配才把订单状态改 completed，保留版本、旧事件、账号与资金。
5. 任一历史事实冲突就整批回滚；提交后再次运行已没有同一批 delivered，因此不重复修改。

这是一次显式数据语义升级，不会模拟用户确认收货，也不会生成新完结事件或直接移动余额。已存在的事件仍由公共投递器和消费者按原幂等规则处理。运行前必须停服并备份；全新数据库无需迁移。

B 的既有大厅投影也作了小范围兼容：旧 delivering→delivered 状态事件可能尚未投递，而订单已在迁移中改成同版本 completed。此时先核对事件版本、起止状态和取件员，再查找摘要与双方、金额、费率快照全部匹配的历史 order.completed，存在佐证才按当前 completed 快照保存刷新回执。其他同版本状态冲突仍返回 409，不能把所有 delivered 事件都视为合法完结。原状态事件内容保持不变。

## 5. Vue 前端模块逐一讲解

前端使用 Vue 3 Composition API。ref 保存可变界面状态，computed 从现有状态推导显示规则，watch 对筛选/订单变更作反应，生命周期负责初始化与清理。

### 5.1 api.js：集中构造请求和显示映射

文件：[api.js](D:/campusexpressmanage/frontend/src/features/fulfillment/api.js)。

path 用 encodeURIComponent 编码订单 ID；post 统一 JSON 请求体，有 key 时才附加 Idempotency-Key。全部请求走公共 request，由公共层添加 Bearer 凭证、处理 JSON/错误和 401 会话清理。

| 方法 | 用途 |
| --- | --- |
| current | 读取当前用户 |
| mine | 固定 scope=mine，再加入角色、状态、页码 |
| detail | 订单详情 |
| advance / cancel | 履约、取消，传版本及幂等键 |
| reviews / review | 读取、提交评价 |
| credit | 查询本人信用 |

statusLabels 做状态英文到中文的字典映射；money 把整数分除 100 并保留两位。235 分显示 ¥2.35。这是显示转换，不用于资金记账。formatTime、sizeLabels 复用 B 的格式工具。C 后端保留历史通知查询接口，但当前前端 API 封装和工作台均已移除该调用。

接单按钮所在大厅使用 B 已有的 API 包装调用 C 后端 accept；所以 C 的前端 api.js 里没有另写 accept，也不影响大厅接单生效。

### 5.2 OrdersView.vue：页面入口和组件复用

文件：[OrdersView.vue](D:/campusexpressmanage/frontend/src/features/fulfillment/OrdersView.vue)。

只组合 PageHeading 和 OrderWorkspace，自己不复制订单查询和履约逻辑。它相当于页面壳；把完整工作台抽成独立组件后，评价页面也能复用。

### 5.3 OrderWorkspace.vue：订单列表、详情与操作的核心

文件：[OrderWorkspace.vue](D:/campusexpressmanage/frontend/src/features/fulfillment/OrderWorkspace.vue)。

该文件包括脚本、完整模板及 scoped 样式。脚本实现业务交互，模板根据状态显示，样式负责布局与手机适配。

#### 数据状态如何组织

| 数据组 | 变量 | 用途 |
| --- | --- | --- |
| 列表 | user、items、total、page、role、status、loading、listError | 当前用户、筛选、分页和加载结果 |
| 详情 | selected、detail、detailError | 当前所选订单及加载错误 |
| 操作 | reason、busy、message、revision | 取消原因、提交中、提示及评价刷新标记；不保存取件码输入 |
| 生命周期 | alive、listGeneration、detailGeneration、polling、timer | 处理异步请求顺序和卸载清理 |
| 请求重试 | keys Map | 同一命令复用幂等键 |

reviewOnly 属性用于评价页：默认只查 completed，隐藏取消/履约操作；reviewed 事件向父组件通知评价已提交。

#### next 与 canCancel：从服务器状态推导按钮

next 是状态到动作的字典：取件员在 accepted 显示开始取件、picking_up 显示确认取件、delivering 显示确认送达；发布者在 delivered 显示确认收货。它同时检查身份和状态，只给本人下一步入口。canCancel 同时检查本人是发布者、接单前、不是 paying。

这些判断改善操作体验，不能代替后端权限和状态检查。直接伪造网络请求仍会被后端拒绝。

#### loadList：请求代次法，避免旧响应覆盖新筛选

每发一次请求先让 listGeneration 加一，并保存自己的 current。响应回来只有 alive 且 current 等于最新代次才更新界面。

~~~text
请求 A：查询“我发布的”，编号 1
请求 B：改为“我接取的”，编号 2
B 先返回：2 等于最新 2，显示 B
A 后返回：1 不等于最新 2，丢弃 A
~~~

这里丢弃过期结果，没有使用 AbortController 取消网络请求。loadList 的 quiet 模式用于后台刷新，减少加载提示闪动。

#### loadDetail 与 open：切单防串数据

loadDetail 读取所选订单详情，写回前检查 alive、请求代次及 id 是否仍是 selected。成功后 revision 加一，通知评价组件重查。读取失败会标记详情错误，提示刷新，并阻止用旧状态继续操作。

open 换订单时先清空上次详情、取消原因和消息，避免显示另一单遗留内容，再请求新详情。

#### act：动作提交、同命令复用键和结果确认

1. 没详情、正在提交或详情更新失败时直接停止。
2. 取消构造 version/reason；履约（含确认收货）只构造 version/action。
3. 用 JSON.stringify([订单ID, operation, body]) 作为命令签名。
4. 相同签名从 Map 复用 UUID；首次命令生成新 UUID。
5. 提交时 busy=true，禁用按钮；成功显示结果，网络错误提示“结果待确认”。
6. 不论成功或失败，最后并行刷新详情与列表，再解除 busy。

例如“订单 A、版本 4、开始取件”断网后重试，仍使用同一键。若版本或输入变化，就是不同命令。键只保存在当前组件内，整页刷新后会丢失；服务端回执持久化，版本和状态继续提供保护。不能把前端 Map 说成永久存储。

#### refresh、watch 和生命周期

refresh 防止定时器重叠，提交中不刷新；首次先获取本人，再并行查询列表与所选详情。身份/状态筛选变化时重置第一页，页码变化重新查询。

onMounted 首次加载，再每 10 秒检查 document.hidden，仅可见页面刷新。onBeforeUnmount 清定时器、alive=false 并增加代次，防止离开页面后继续写回。

这是定时查询，不是 WebSocket 实时推送。正常可见页面约 10 秒查询一次，网络或事件处理异常时没有固定时延保证。

#### 模板和样式做了什么

未登录显示登录入口；列表错误与“暂无订单”分开。订单卡显示快递、规格、路线、时间、金额和状态。详情展示进度、地址、费用组成、付款/退款；不展示取件码、取件错误次数或旧锁单通知。

进度条用 steps 有序数组，索引不超过当前状态索引的步骤高亮；cancelled 单独显示取消。待付款订单链接到 B 的发布页继续支付。delivered 显示等待发布者收货，completed 才加载 OrderReviews。

默认两列订单卡；650px 及以下改一列，表单纵向，地址和长 ID 可换行。scoped 使这些样式主要作用于组件，避免影响其他模块。

### 5.4 OrderReviews.vue：单个订单的互评组件

文件：[OrderReviews.vue](D:/campusexpressmanage/frontend/src/features/fulfillment/OrderReviews.vue)。

props 包含 orderId、uid、revision；提交成功发 submitted。records 保存双方评价，reviewable/loaded 区分开放与加载状态，rating/tags/comment 保存输入，busy/error/loadError 保存请求状态。

mine 通过 records.some 判断是否已有 reviewerUid 等于本人的评价。因每单最多双方各一条，列表默认 20 条足以包含两条，不需要这里再分页翻页。

load 请求双方评价及 reviewable，generation 只接受最新响应；watch 监听订单和 revision，立即加载及随外部更新重查；卸载时增加代次废弃旧响应。

submit 发送星级、标签、去空格评论。成功通知父组件刷新信用；409 展示具体业务原因，其他异常提示先刷新确认。finally 再读取一次服务端评价，处理“已提交但响应丢失”的情况。

显示顺序：已经评过 → 显示不可修改；completed 但事件未消费 → 显示完成结果确认中；已开放且未评 → 显示表单。delivered 阶段不提供评价入口。星级 1～5，五个可选标签，评论 maxlength=500，真正校验仍由后端完成。

评论使用 Vue 文本插值，没有 v-html，因此输入带 script 标签的内容按文字展示。不要把这个结论扩大为系统所有位置都已做完整安全审计。

### 5.5 ReviewsView.vue：本人信用卡和已完成订单复用

文件：[ReviewsView.vue](D:/campusexpressmanage/frontend/src/features/fulfillment/ReviewsView.vue)。

load 先检查登录及 busy，获取本人 uid 后调用 credit；alive 防止卸载后写回。挂载立即查询，每 10 秒在页面可见时刷新，卸载清理。

页面只展示后端 score、level、reviewCount、creditEligible，不在浏览器重新计算信用。无评价显示“—”和新人；低分提示不能接新单但仍需完成旧单。

OrderWorkspace 以 review-only 模式复用，reviewed 触发 load。本账号提交评价影响的是对方取件员信用；对方账号通过手动刷新或轮询看到新分数，不能解释成本人评价后本人涨分。

## 6. 公共接入文件：为了让 C 能运行，我改了哪里

| 文件 | C 相关变更 | 为什么需要 |
| --- | --- | --- |
| backend/app/main.py | 导入 C 路由和 TABLES，启动建表并注册路由 | HTTP 端点能访问，C 表无损创建 |
| backend/app/events/wiring.py | 注册 order.completed → fulfillment → open_reviews | 公共投递器知道把完结事件交给 C |
| backend/app/events/schema.py | 在状态枚举中增加 completed | 公共状态事件能校验并投递确认收货结果 |
| backend/app/modules/orders/gateway.py、api.py | 受控 confirm_receipt 转换及 completed 状态筛选 | 发布者收货与代取员履约使用不同权限，完成订单可查询 |
| backend/app/modules/orders/projections.py | 兼容历史 delivered 完结状态重命名 | B 既有投影按有凭据的旧完结事实接受升级，避免迁移后积压状态事件冲突 |
| backend/app/modules/finance/services/settlement.py | 完结消费者要求 completed | delivered 阶段不能提前结算 |
| backend/app/modules/fulfillment/migrate_receipt.py | 按旧完结 outbox 事实升级 delivered | 无损保留历史完成单及新版待收货订单 |
| backend/scripts/init_db.py | 导入 C 模型 | 手动初始化也包含 C 表 |
| backend/tests/test_events_integration.py | 验证完结既结算又开放评价 | 原来缺处理器场景随 C 接入更新 |
| frontend/src/App.vue | 订单/评价页显示“履约服务”标签 | 页面已接真实业务接口 |
| frontend/src/features/orders/PublishView.vue | 送达显示待收货，新增已完成文案，隐私提示只提详细地址 | B 既有页面与 C 新状态语义一致，不承诺提供取件码 |
| frontend/src/features/orders/HallTaskDialog.vue | 接单提示只承诺提供详细地址 | B 既有弹窗不再提示 C 会提供取件码 |
| frontend/package.json | 新增 test:fulfillment 命令 | 一条命令运行 C 浏览器测试 |
| README.md | 增加 C 启动/演示、测试、边界说明 | 团队成员能复现 |
| docs/团队接口约定.md | 补第 9.1 节个人需求/质量/约束及实际交付 | 需求和开发遵守同一契约 |

已有 router/index.js 的 /orders、/reviews 路由、大厅 TaskHallView、公共 http.js、A 的 common.py 和事件投递器不是本次新写。确认收货修订还扩展 B 的 gateway.py 受控状态入口、状态筛选和旧投影兼容；B 的 PublishView、HallTaskDialog 仅作状态与接单提示文案修改，D 的完结消费者改为要求 completed。这些是为完成 C 流程做的集成修改，不将团队原文件整体归为个人原创。完整源码附录展示实际现状及差异。

## 7. 接口契约：验收时能解释请求里每个字段

接单示例，路径 /api/orders/{真实订单ID}/accept：

~~~http
POST /api/orders/{orderId}/accept
Authorization: Bearer <登录凭证>
Idempotency-Key: <本次命令的UUID>
Content-Type: application/json

{"version":3}
~~~

version 来自服务端详情，不是固定写死 3。成功后返回最新详情，新版本用于下一步。

确认取件示例，不需要额外输入：

~~~json
{"version":5,"action":"confirm_pickup"}
~~~

不能让客户端直接提交目标 status；它只能提交允许的动作，由服务端按状态机决定下一状态。携带 code 属于额外字段，返回 422。

代取员确认送达后，发布者用最新版本执行确认收货：

~~~json
{"version":7,"action":"confirm_receipt"}
~~~

评价示例，不需要也不允许提供评价对象：

~~~json
{"rating":5,"tags":["准时送达","包裹完好"],"comment":"谢谢帮忙"}
~~~

常见错误含义：

| HTTP / code | 含义 | 界面应做什么 |
| --- | --- | --- |
| 401 AUTH_REQUIRED / SESSION_EXPIRED | 登录凭证不可用 | 走公共登录流程 |
| 403 VERIFICATION_REQUIRED | 学生认证不满足 | 认证后再接单/履约 |
| 403 CREDIT_TOO_LOW | 信用不够接新单 | 显示原因，旧单仍可完成 |
| 404 NOT_FOUND | 不存在或无权读取 | 不显示敏感详情 |
| 409 ORDER_CONFLICT | 版本过期或状态不允许 | 刷新，不擅自覆盖 |
| 409 PAYMENT_IN_PROGRESS | 支付结果还未确定 | 等待真实结果 |
| 409 IDEMPOTENCY_CONFLICT | 同一键用于不同内容 | 不更改原命令含义 |
| 409 ALREADY_REVIEWED | 本人本单已评价 | 刷新展示已提交内容 |
| 422 VALIDATION_ERROR | 输入违反字段契约 | 修改输入 |

## 8. 验收演示：建议 8～12 分钟

准备两个独立会话的虚构账号：发布者 P、取件员 Q，均通过学生认证；开发服务按 README 启动。不同普通浏览器窗口可能共享登录状态，建议两个独立浏览器配置或浏览器与隐私窗口。旧开发库先按 README 停服、备份并迁移；新版演示订单由发布者实际确认收货。

| 顺序 | 操作 | 讲解重点 |
| --- | --- | --- |
| 1 | 打开第 9.1 节个人需求与目录 | 我负责 F5/F6，前后端及质量保证 |
| 2 | P 发布并付款，Q 在大厅查看和接单 | 发布、付款复用 B/D，接单由 C 判断资格并原子占用 |
| 3 | Q 打开我的订单，筛选我接取的，查看详情 | 数据来自接口；接单成功后才获得敏感详情 |
| 4 | Q 开始取件 → 确认取件 → 确认送达 | C 无取件码输入和展示；delivered 待收货，资金仍冻结，无评价入口 |
| 5 | P 确认收货，等待评价开放，双方各评价一次 | delivered→completed、完结事件、每人一次；先用高分保持后续演示顺畅 |
| 6 | Q 打开信用页，展示样本和均分 | 只算 Q 作为取件员收到的发布者评价 |
| 7 | 检查代取员不能确认收货、发布者不能提前收货 | 身份与状态双重检查；送达前后资金及评价边界 |
| 8 | 分别取消未付款和付款待接单订单 | 无需退款与 processing → succeeded 区别 |
| 9 | 用低分专用账号演示限制新接单 | 不用主流程账号，以免阻碍其他演示 |
| 10 | 展示测试结果，解释竞争/幂等/回滚 | 这些场景由自动测试重复制造，比现场手速更可复现 |

全程不要拿首页示例卡片作为真实订单证据。账户、学号与照片使用虚构测试数据。本期短信和资金是演示实现，无真实交易。

## 9. 测试模块：我如何证明功能正确

### 9.1 后端 test_fulfillment.py

测试真实订单、资金和 outbox，使用临时 SQLite；身份用受控测试替身 alice/bob/carol/unverified，不能称这些测试验证了真实登录本身。测试替身特意先执行数据库读取，覆盖“鉴权已开启事务，业务复用同一事务”的情况。

辅助方法分层搭流程：paid 创建并付款，pickup 接单并开始取件，delivered 完成代取员送达，completed 再让发布者确认收货；post/latest/advance 封装请求，count 读取表条数，seed_review 仅为信用边界构造样本。每个测试有独立准备与清理，不改开发库。

| 测试方法（省略 test_ 前缀） | 证明什么 |
| --- | --- |
| real_lifecycle_settlement_opening_logs_and_event_privacy | 5 条动作日志、1 次结算和评价开放，订单事件不带私人资料；重复完成拒绝 |
| admission_actor_privacy_and_strict_contract | 登录、认证、自接、非取件员、跳步、字段和分页、无关人权限 |
| request_replay_survives_version_changes_and_key_conflict | 原键重放原结果，即使订单已推进；同键换内容冲突 |
| pickup_requires_no_code_and_replays_without_old_locking | 确认取件只需 action/version；携 code 拒绝，旧错误计数不再读写 |
| legacy_accept_success_replay_hides_fields_without_rewriting_receipt | 旧成功回执仍能重放，C 响应裁剪私人/锁定字段，原数据库回执不变 |
| legacy_null_code_digest_replays_and_still_rejects_new_code_and_conflicts | 兼容旧缺省 code:null 的摘要，新输入 code 仍拒绝，同键换版本仍冲突 |
| legacy_code_error_cannot_be_replayed_as_success_without_code | 旧明确错码摘要不能命中无 code 请求，旧失败不能重放成成功 |
| delivery_waits_for_publisher_receipt_before_settlement_and_reviews | 送达后仍冻结、未开放评价；仅发布者收货后完成，重放不重复结算 |
| two_couriers_compete_and_only_one_owns_order | 两线程抢单，5 轮均只有一个成功 |
| accept_cancel_compete | 两线程抢单/取消，5 轮均只有一个成功 |
| cancel_unpaid_paying_paid_and_refund_end_to_end | 三类付款状态取消规则、完整退款及只退款一次 |
| publish_failure_rolls_back_state_log_and_idempotency | 注入事件异常，订单、日志、回执一起回滚 |
| receipt_publish_failure_rolls_back_completion_and_retry | 完结事件写入失败，保持 delivered；恢复后可重试 |
| receipt_rejects_stale_version_and_concurrent_completion_once | 旧版本被拒，并发收货只有一次成功、完结和结算 |
| review_waits_for_event_and_both_sides_submit_immutable_once | 事件前不能评，事件后双方各一次，不可修改及角色统计 |
| review_validation_and_concurrent_double_click | 非法星级/标签/字数拒绝；并发同人评价只有一条 |
| completion_consumer_replay_conflict_rollback_and_retry | C 消费失败可重试、D 仍可结算；两层去重、回滚和内容冲突 |
| credit_newcomer_recent_thirty_roles_boundaries_and_rounding | 新人、角色筛选、3/4 分边界、两位展示、31 取 30 |
| low_credit_blocks_new_acceptance_but_not_existing_fulfillment | 信用下降只影响新单，现有履约可继续 |

方法名和数量以附录当前测试源码为准。README 的 F1/F2“20 轮”不是 C 的测试次数。失败注入场景会主动制造并记录错误日志，应看最终断言和测试汇总判断成败。迁移专项测试另覆盖旧 delivered 事实升级、新 delivered 保留、重复运行、冲突整批回滚，以及旧状态事件迁移后正常刷新且不能放过无佐证/状态或取件员不符的事件。

### 9.2 浏览器 fulfillment.spec.js 与配置

使用 Playwright，配置复用团队临时应用，后端端口 18161、前端 18162、单 worker。测试专用启动入口只预置虚构审核管理员，其余注册、登录、认证、审核、发布、充值、支付、事件与 C 都走真实接口。登录前置通过接口完成，再把合法 token 放进 sessionStorage；不是全程手点注册页面。

| 场景 | 检查点 |
| --- | --- |
| 桌面全流程 | 大厅接单、履约、发布者收货、互评、1 星导致限制新单、评论标签文本安全显示 |
| 390×844 手机 | 无取件码输入/展示，送达待收货，发布者完成后开放评价，无横向溢出 |
| 取消与退款 | 未付显示无需退款，已付等实际 succeeded 才显示已退款 |
| 网络失败 | 中断一次状态请求，重试键一致；详情失败禁用操作 |
| 轮询与列表错误 | 虚拟时钟验证刷新，离开停止；503 不冒充空列表 |

测试调用 student/create/accept 等辅助函数准备数据，visit/open 操作浏览器；expect.poll 等待异步事实，page.route 注入网络故障，page.clock 验证时间逻辑。算法重点是可控条件与可重复断言，而非人工反复点击。

### 9.3 本轮验证记录

2026-11-11 确认收货及历史兼容修订后的实际验证如下。生成材料本身不执行测试。

| 检查 | 本次结果 | 范围或耗时 |
| --- | --- | --- |
| 全量后端自动测试 | 166 项通过 | 161.173 秒，包含团队全部已发现测试 |
| C 履约专项 | 19 项通过 | 权限、无取件码、收货边界、历史回执、竞争、回滚、评价、信用 |
| 历史迁移专项 | 5 项通过 | 保留新待收货订单、旧事实/摘要核对、投影兼容、冲突整批回滚 |
| 公共事件专项 | 11 项通过 | 事件投递、独立消费、失败重试及完结协作 |
| Vue 生产构建 | 通过 | 6.18 秒 |
| C 浏览器验收 | 5/5 通过 | 36.2 秒，使用本机 Edge 与临时 A/B/C/D 真实接口 |

本节仅记录本次确认收货流程的有效结果，不沿用旧流程的测试结论。后端测试中的“事件投递失败”来自故障注入，用来验证回滚与重试，应以最终测试汇总判断成败。

后端命令在项目根目录执行：

~~~powershell
$env:PYTHONPATH = 'backend'
.venv\Scripts\python.exe -m unittest discover -s backend/tests -p test_fulfillment.py -v
~~~

前端命令在 frontend 目录执行：

~~~powershell
npm.cmd run build
npm.cmd run test:fulfillment
# 若使用本机 Edge：
$env:PW_BROWSER_CHANNEL = 'msedge'
npm.cmd run test:fulfillment
~~~

本轮结果只证明当前记录的检查范围，不等于老师已完成验收，也不等于再次执行全部团队测试。运行条件、数据库隔离及依赖安装详见 README。

## 10. 高频答辩题与回答

| 问题 | 可直接回答 |
| --- | --- |
| C 最核心贡献是什么？ | 把已付款订单从接单推进到送达、发布者确认收货，再把完结事实转为双方评价和取件信用，补全前后端及异常路径。 |
| 为什么用版本号？ | 页面可能过期，多人可能同时抢单，带版本条件更新让同一旧版本最多一次成功。 |
| 按钮禁用为什么还不够？ | 只约束当前页面，网络重发、多窗口和直接接口调用仍存在，要靠服务端幂等、状态和唯一约束。 |
| 为什么送达后不直接结算？ | 送达是代取员报告的配送事实，发布者确认收货才完成交易，避免未收到就完成结算和评价。 |
| 谁能推进每一步？ | 开始取件、确认取件和送达属于本单取件员；收货确认属于发布者。后端比较当前身份与订单双方 UID，客户端不能自报操作者。 |
| 如何防别人给任意用户刷评价？ | 服务端从订单推导对方，只能参与双方在收货完成并开放后各评一次。 |
| 两种幂等有何区别？ | 接单/履约/取消用请求键重放结果；评价用每人每单唯一约束，重复返回冲突。 |
| 确认收货后为什么还可能等一下评价？ | 收货同事务保存完结事件，C 消费并核对 completed 事实后开放；故障可以重试。 |
| 怎么防重复结算？ | 我只发布事件，D 的结算按自己的业务事实防重，C 与 D 是独立消费者。 |
| 信用怎么计算？ | 找本人作为取件员收到的最近最多 30 条评价，Decimal 求均值，原值判门槛，展示两位。 |
| 新人为什么可接？ | 没评价是未知而非零分，score=null，规则允许进入。 |
| 信用低了旧单怎么办？ | 信用只检查新接单，已有订单仍要完成，避免在途包裹卡住。 |
| 是实时推送吗？ | 用每 10 秒定时查询和手动刷新；卸载清理，过期响应不写回。 |
| 如何避免前端串单？ | 切单清空输入，详情响应检查最新请求代次和订单 ID，旧响应丢弃。 |
| 评价评论能执行脚本吗？ | 当前组件用 Vue 文本插值，不用 v-html，脚本标签按文字显示。 |
| 为什么不自己做订单表/钱包？ | 团队有唯一事实来源，我通过网关和事件协作，避免同一状态多处维护。 |
| 用了什么“算法”？ | 有限状态机、乐观并发控制、幂等摘要、唯一约束防重、最近 N 条均值、分页、请求代次处理。 |

### 10.1 应如实说明的当前范围

没有接单后用户取消、部分退款、违约金、申诉、评价修改/撤回接口。确认送达由取件员执行，确认收货由发布者执行；尚未实现自动收货超时、申诉或线下交接证明。C 的履约流程没有取件码校验；旧锁定和错误计数列仅兼容保留，不参与新流程。

旧数据库升级时先停服备份，在 backend 目录运行 `..\.venv\Scripts\python.exe -m app.modules.fulfillment.migrate_receipt`。迁移只将存在匹配旧 order.completed outbox 事实的 delivered 改为 completed，不改版本、事件或资金；没有完结事件的新版 delivered 保留等待收货。重复运行无变化，历史事实冲突整批回滚。源码附录包含迁移与测试，旧数据库不通过删库升级。

事件投递器、身份、钱包、订单网关是团队基础；C 负责接入与自身业务。前端键 Map 只在组件存活期间存在；旧请求被忽略而非真正取消。信用是简单近期均分规则，不是机器学习或复杂反作弊模型。

## 11. 现场讲代码的最短路线

1. 从 contract.py 说明输入不可乱填。
2. 打开 service.execute，按“权限 → 幂等 → 快照 → 版本 → 动作 → 日志事件 → 提交”讲。
3. 指到 B 的 OrderGateway.transition，说清数据库条件更新的竞争保障。
4. 回到 confirm_receipt 分支，解释发布者权限、delivered/completed 差异及完结事件同事务。
5. 打开 handlers.py，说明 completed 事实校验、双层去重与评价开放。
6. 打开 api.review，说明服务端推导对象与数据库唯一性。
7. 打开 credit.py，用 [2,3,3] 算出 2.67，说明最近 30 条和角色过滤。
8. 打开 OrderWorkspace 的 next、act、loadList、onBeforeUnmount，说明 Vue 交互、幂等键、竞态和清理。
9. 打开 OrderReviews/ReviewsView，串起来说评价提交与信用刷新。
10. 展示测试汇总，选一条竞争测试、一条回滚测试解释如何证明异常正确。

完整源码在下一部分，保留实际源文件行序。每个文件标题注明角色、行数与 SHA-256，供核对当前材料是否仍对应源文件。源文件以后修改后，应重新生成这份源码快照再作为新版本验收材料。

## 12. C 部分完整业务源码
以下为当前文件完整内容；公共文件包含既有团队代码，其个人修改另见第 15 节。

### backend/app/modules/fulfillment/__init__.py

Python 包入口与模块说明；1 行。

SHA-256（原始文件字节）：`953fa47d61d47ab6e1302190348edcfe8eaf7f450093592e49b2235d88546347`

~~~~python
"""成员 C：F5 履约与 F6 评价信用。"""
~~~~

### backend/app/modules/fulfillment/contract.py

请求字段、类型和条件校验；22 行。

SHA-256（原始文件字节）：`466d2d6bae1c6a06b7998b27ec634e5d58e443952378a51a2bbc08067ee953d3`

~~~~python
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from ...common import Input, VersionInput


class StatusInput(VersionInput):
    action: Literal["start_pickup", "confirm_pickup", "confirm_delivery", "confirm_receipt"]


class CancelInput(VersionInput):
    reason: str = Field(min_length=1, max_length=200)


Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ReviewInput(Input):
    rating: int = Field(strict=True, ge=1, le=5)
    tags: list[Tag] = Field(default_factory=list, max_length=5)
    comment: str = Field(default="", max_length=500)
~~~~

### backend/app/modules/fulfillment/models.py

C 的五张业务表与唯一约束；61 行。

SHA-256（原始文件字节）：`c59f1cf4c1d545254d73f8bdbd099ec480749511907c8afef014f92cbfa6894e`

~~~~python
"""C 模块事实表；订单状态仍由 B 的 OrderGateway 独占维护。"""
from sqlalchemy import CheckConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class OperationLog(Base):
    __tablename__ = "fulfillment_operations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    actor_uid: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    order_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))


class Notification(Base):
    __tablename__ = "fulfillment_notifications"
    __table_args__ = (UniqueConstraint("order_id", "uid", "type"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    uid: Mapped[str] = mapped_column(String(100), index=True)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[str] = mapped_column(String(40))


class ReviewOpening(Base):
    __tablename__ = "fulfillment_review_openings"
    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    fact_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))


class ConsumerReceipt(Base):
    __tablename__ = "fulfillment_event_receipts"
    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class Review(Base):
    __tablename__ = "fulfillment_reviews"
    __table_args__ = (UniqueConstraint("order_id", "reviewer_uid"),
                      CheckConstraint("rating >= 1 AND rating <= 5"))
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    reviewer_uid: Mapped[str] = mapped_column(String(100))
    reviewee_uid: Mapped[str] = mapped_column(String(100), index=True)
    reviewer_role: Mapped[str] = mapped_column(String(20))
    rating: Mapped[int] = mapped_column(Integer)
    tags: Mapped[list] = mapped_column(JSON)
    comment: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[str] = mapped_column(String(40), index=True)


TABLES = [model.__table__ for model in (OperationLog, Notification, ReviewOpening, ConsumerReceipt, Review)]
~~~~

### backend/app/modules/fulfillment/api.py

HTTP 路由、查询权限、分页和评价提交；113 行。

SHA-256（原始文件字节）：`cfc5cdc4035b987556649ba48b44a39084a1f6216901d2a530ae707c78e43c3d`

~~~~python
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ...common import Key, VersionInput, fail, iso, now
from ...database import get_db
from ..identity.dependencies import current_identity
from ..orders.gateway import OrderGateway
from . import service
from .contract import CancelInput, ReviewInput, StatusInput
from .credit import CreditService
from .models import Notification, Review, ReviewOpening

router = APIRouter(prefix="/api", tags=["fulfillment"])


def response(value):
    return JSONResponse(value["body"], status_code=value["statusCode"])


@router.post("/orders/{order_id}/accept")
def accept(order_id: str, body: VersionInput, idempotency_key: Key,
           user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "accept", body, idempotency_key))


@router.post("/orders/{order_id}/status")
def advance(order_id: str, body: StatusInput, idempotency_key: Key,
            user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "status", body, idempotency_key))


@router.post("/orders/{order_id}/cancel")
def cancel(order_id: str, body: CancelInput, idempotency_key: Key,
           user=Depends(current_identity), db: Session = Depends(get_db)):
    return response(service.execute(db, user, order_id, "cancel", body, idempotency_key))


@router.get("/orders/{order_id}/status")
def status(order_id: str, user=Depends(current_identity), db: Session = Depends(get_db)):
    order = OrderGateway.related(db, order_id, user.uid)
    return {"orderId": order.id, "status": order.status, "paymentStatus": order.payment_status,
            "refundStatus": order.refund_status, "version": order.version}


def pagination(request):
    if set(request.query_params) - {"page", "pageSize"}:
        fail(422, "VALIDATION_ERROR", "查询包含未声明字段")
    for field in ("page", "pageSize"):
        value = request.query_params.get(field)
        if value is not None and (not value.isascii() or not value.isdigit()):
            fail(422, "VALIDATION_ERROR", "分页参数必须为正整数", {field: "请输入正整数"})


def paged(db, model, conditions, page, page_size, render):
    total = db.scalar(select(func.count()).select_from(model).where(*conditions))
    rows = db.scalars(select(model).where(*conditions).order_by(model.created_at.desc(), model.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return {"items": [render(row) for row in rows], "total": total, "page": page, "pageSize": page_size}


@router.get("/orders/{order_id}/notifications")
def notifications(order_id: str, request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
                  user=Depends(current_identity), db: Session = Depends(get_db)):
    pagination(request)
    OrderGateway.related(db, order_id, user.uid)
    return paged(db, Notification, [Notification.order_id == order_id, Notification.uid == user.uid], page, pageSize,
        lambda row: {"notificationId": row.id, "orderId": row.order_id, "type": row.type,
                     "message": row.message, "createdAt": row.created_at})


@router.get("/users/{uid}/credit")
def credit(uid: str, user=Depends(current_identity), db: Session = Depends(get_db)):
    if uid != user.uid:
        fail(404, "NOT_FOUND", "信用记录不存在或不可访问")
    return CreditService.get(db, uid)


@router.post("/orders/{order_id}/reviews", status_code=201)
def review(order_id: str, body: ReviewInput, user=Depends(current_identity), db: Session = Depends(get_db)):
    order = OrderGateway.related(db, order_id, user.uid)
    if order.status != "completed" or not db.get(ReviewOpening, order_id):
        fail(409, "ORDER_CONFLICT", "订单尚未确认收货或评价入口准备中，请稍后刷新")
    publisher = user.uid == order.publisher_uid
    target = order.courier_uid if publisher else order.publisher_uid
    if not target or target == user.uid:
        fail(403, "FORBIDDEN", "不能评价自己")
    review_id, created = str(uuid4()), iso(now())
    changed = db.execute(insert(Review).values(id=review_id, order_id=order.id, reviewer_uid=user.uid,
        reviewee_uid=target, reviewer_role="publisher" if publisher else "courier", rating=body.rating,
        tags=body.tags, comment=body.comment, created_at=created).on_conflict_do_nothing(
            index_elements=[Review.order_id, Review.reviewer_uid]))
    if changed.rowcount != 1:
        fail(409, "ALREADY_REVIEWED", "此订单已评价，提交后不可修改")
    db.commit()
    return {"reviewId": review_id, "orderId": order.id, "createdAt": created}


@router.get("/orders/{order_id}/reviews")
def reviews(order_id: str, request: Request, page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100),
            user=Depends(current_identity), db: Session = Depends(get_db)):
    pagination(request)
    order = OrderGateway.related(db, order_id, user.uid)
    result = paged(db, Review, [Review.order_id == order_id], page, pageSize,
        lambda row: {"reviewId": row.id, "orderId": row.order_id, "reviewerUid": row.reviewer_uid,
                     "revieweeUid": row.reviewee_uid, "reviewerRole": row.reviewer_role,
                     "rating": row.rating, "tags": row.tags, "comment": row.comment, "createdAt": row.created_at})
    result["reviewable"] = order.status == "completed" and db.get(ReviewOpening, order_id) is not None
    return result
~~~~

### backend/app/modules/fulfillment/service.py

接单、履约、取消及同事务日志事件；112 行。

SHA-256（原始文件字节）：`4a860539b0c08967c46356e5b79cdc021918d4d23ea53621a0b8c804e817c47f`

~~~~python
"""履约用例：状态、日志、请求幂等与 outbox 使用同一事务。"""
from uuid import uuid4
from sqlalchemy import select

from ...common import Idempotency, fail, fingerprint, iso, now, remember
from ...events import publish
from ..identity.dependencies import require_verified
from ..orders.api import summary
from ..orders.gateway import OrderGateway
from .credit import CreditService
from .models import OperationLog


def emit(db, order, kind, payload):
    publish(db, {"eventId": str(uuid4()), "type": kind, "occurredAt": iso(now()),
                 "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                 "version": order.version, "payload": {**payload, "orderVersion": order.version}})


def record(db, before, after, uid, action, reason=None):
    db.add(OperationLog(id=str(uuid4()), order_id=after.id, actor_uid=uid, action=action,
                        from_status=before.status, status=after.status, order_version=after.version,
                        reason=reason, created_at=iso(now())))
    emit(db, after, "order.status_changed", {"fromStatus": before.status, "status": after.status,
                                             "courierUid": after.courier_uid})


def fulfillment_detail(order, uid):
    """履约动作无需取件码，也不向 C 页面返回该字段。"""
    result = {**summary(order), "publisherUid": order.publisher_uid,
              "courierUid": order.courier_uid, "address": order.address}
    if uid == order.publisher_uid:
        result["paymentRequestId"] = order.payment_request_id
    return result


def replay_fulfillment(db, uid, operation, key, payload):
    """只兼容旧版缺省 code:null 的摘要；不改写旧回执或重做业务。"""
    row = db.scalar(select(Idempotency).where(Idempotency.uid == uid,
                    Idempotency.operation == operation, Idempotency.key == key))
    if row is None:
        return None
    digests = {fingerprint(payload)}
    if payload.get("action") in {"start_pickup", "confirm_pickup", "confirm_delivery"}:
        digests.add(fingerprint({**payload, "code": None}))
    if row.digest not in digests:
        fail(409, "IDEMPOTENCY_CONFLICT", "相同提交标识不能用于不同内容")
    result = row.result
    if result["statusCode"] == 200:
        # 历史成功快照仍可重放，但 C 响应不再暴露取件码及旧锁定字段。
        result = {**result, "body": {name: value for name, value in result["body"].items()
                  if name not in {"code", "locked", "pickupFailureCount"}}}
    return result


def execute(db, user, order_id, operation, body, key):
    name = f"fulfillment:{operation}:{order_id}"
    payload = body.model_dump()
    receipt = operation == "status" and body.action == "confirm_receipt"
    if operation != "cancel" and not receipt:
        require_verified(user)
    previous = replay_fulfillment(db, user.uid, name, key, payload)
    if previous:
        return previous
    before = OrderGateway.get_snapshot(db, order_id)
    if operation == "accept":
        if user.uid == before.publisher_uid:
            fail(403, "FORBIDDEN", "不能接取自己发布的订单")
        if not CreditService.get(db, user.uid)["creditEligible"]:
            fail(403, "CREDIT_TOO_LOW", "信用分低于 3.0，暂时不能接单")
    elif operation == "cancel":
        if user.uid != before.publisher_uid:
            fail(403, "FORBIDDEN", "仅发布者可取消订单")
    elif receipt:
        if user.uid != before.publisher_uid:
            fail(403, "FORBIDDEN", "仅发布者可确认收货")
    elif user.uid != before.courier_uid:
        fail(403, "FORBIDDEN", "仅本单取件员可推进履约")
    if before.version != body.version:
        fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新后重试")
    status_code = 200
    if operation == "accept":
        after = OrderGateway.transition(db, before, body.version, "accept", user.uid,
                                        status="accepted", courier_uid=user.uid)
        record(db, before, after, user.uid, "accept")
        result = fulfillment_detail(after, user.uid)
    elif operation == "cancel":
        after = OrderGateway.transition(db, before, body.version, "cancel", user.uid,
                                        status="cancelled", refund_status="processing" if before.payment_status == "paid" else "none")
        record(db, before, after, user.uid, "cancel", body.reason)
        emit(db, after, "order.cancelled", {"publisherUid": after.publisher_uid, "paymentId": after.payment_id,
                                            "amount": after.amount, "paid": after.payment_status == "paid"})
        result = {"orderId": after.id, "status": after.status, "refundStatus": after.refund_status, "version": after.version}
    else:
        source, target = {"start_pickup": ("accepted", "picking_up"),
                          "confirm_pickup": ("picking_up", "delivering"),
                          "confirm_delivery": ("delivering", "delivered"),
                          "confirm_receipt": ("delivered", "completed")}[body.action]
        if before.status != source:
            fail(409, "ORDER_CONFLICT", "请按取件、配送、送达、确认收货的顺序操作")
        after = OrderGateway.transition(db, before, body.version, "confirm_receipt" if receipt else "fulfill",
                                       user.uid, status=target)
        record(db, before, after, user.uid, body.action)
        if target == "completed":
            emit(db, after, "order.completed", {"publisherUid": after.publisher_uid, "courierUid": after.courier_uid,
                "amount": after.amount, "baseFee": after.base_fee, "tip": after.tip,
                "commissionRateBps": after.commission_bps, "pricingVersion": after.pricing_version})
        result = fulfillment_detail(after, user.uid)
    stored = {"statusCode": status_code, "body": result}
    remember(db, user.uid, name, key, payload, stored)
    db.commit()
    return stored
~~~~

### backend/app/modules/fulfillment/handlers.py

完结事件校验、去重和评价开放；33 行。

SHA-256（原始文件字节）：`cffe57cb394a1ef0a43cdb9e6b00655440e1b5978c176101d5d6bf54ff6b6289`

~~~~python
"""完结事件消费者：只开放评价，不写订单和资金，不提交调用方事务。"""
from ...common import fail, fingerprint
from ...events.schema import validate
from ..orders.gateway import OrderGateway
from .models import ConsumerReceipt, ReviewOpening


def on_order_completed(db, event):
    data, digest = validate(event)
    if data["type"] != "order.completed":
        fail(422, "VALIDATION_ERROR", "评价仅订阅订单完结事件")
    receipt = db.get(ConsumerReceipt, data["eventId"])
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    order = OrderGateway.get_snapshot(db, data["orderId"])
    expected = {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
                "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
                "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
                "orderVersion": order.version}
    if order.status != "completed" or data["version"] != order.version or data["payload"] != expected:
        fail(409, "ORDER_CONFLICT", "完结事件与订单事实不一致")
    fact_digest = fingerprint(expected)
    opening = db.get(ReviewOpening, order.id)
    if opening and opening.fact_digest != fact_digest:
        fail(409, "ORDER_CONFLICT", "订单完结事实发生冲突")
    if not opening:
        db.add(ReviewOpening(order_id=order.id, fact_digest=fact_digest, created_at=data["occurredAt"]))
    result = {"accepted": True, "orderId": order.id, "reviewable": True}
    db.add(ConsumerReceipt(event_id=data["eventId"], digest=digest, result=result))
    db.flush()
    return result
~~~~

### backend/app/modules/fulfillment/credit.py

最近 30 条取件评价均分；20 行。

SHA-256（原始文件字节）：`d0cdd14514e0878200ca4fb1622bc5768c7a3c8190cef0cc6c38329c37c9e062`

~~~~python
"""实时信用，无缓存投影；只统计作为取件员收到的最近 30 单评价。"""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from .models import Review


class CreditService:
    @staticmethod
    def get(db, uid):
        ratings = list(db.scalars(select(Review.rating).where(
            Review.reviewee_uid == uid, Review.reviewer_role == "publisher"
        ).order_by(Review.created_at.desc(), Review.id.desc()).limit(30)))
        if not ratings:
            return {"uid": uid, "score": None, "level": "new", "reviewCount": 0, "creditEligible": True}
        average = Decimal(sum(ratings)) / len(ratings)
        return {"uid": uid, "score": float(average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "level": "restricted" if average < 3 else "normal" if average < 4 else "good",
                "reviewCount": len(ratings), "creditEligible": average >= 3}
~~~~

### backend/app/modules/fulfillment/migrate_receipt.py

保留历史完结事实的确认收货流程迁移；50 行。

SHA-256（原始文件字节）：`a7730d40dccc77fe09a8b95a2c25c85d8a82ca0b92fafe92f83746d226176124`

~~~~python
"""显式升级旧版完结状态：python -m app.modules.fulfillment.migrate_receipt。"""
from sqlalchemy import inspect, select, update

from ...events.models import OutboxEvent
from ...events.schema import validate
from ..orders.entities import Order


def upgrade(engine):
    """仅将已有完结事件佐证的旧 delivered 转为 completed；不生成事件或移动资金。"""
    if engine.dialect.name != "sqlite":
        raise ValueError("本升级仅支持 SQLite")
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            inspector = inspect(connection)
            if not inspector.has_table("orders_v2"):
                raise ValueError("订单表不存在；全新数据库无需执行此升级")
            if not inspector.has_table("outbox_events"):
                connection.rollback()
                return 0
            changed = 0
            orders = connection.execute(select(Order.__table__).where(Order.status == "delivered")).mappings().all()
            for order in orders:
                events = connection.execute(select(OutboxEvent.body, OutboxEvent.digest).where(
                    OutboxEvent.order_id == order["id"], OutboxEvent.type == "order.completed")).all()
                if not events:
                    continue  # 新版送达待收货没有完结事件，必须保留。
                expected = {"publisherUid": order["publisher_uid"], "courierUid": order["courier_uid"],
                    "amount": order["amount"], "baseFee": order["base_fee"], "tip": order["tip"],
                    "commissionRateBps": order["commission_bps"], "pricingVersion": order["pricing_version"],
                    "orderVersion": order["version"]}
                for event, stored_digest in events:
                    data, digest = validate(event)
                    if (stored_digest != digest or data["type"] != "order.completed" or data["orderId"] != order["id"]
                            or data["version"] != order["version"] or data["payload"] != expected):
                        raise ValueError(f"订单 {order['id']} 的历史完结事实冲突，升级已回滚")
                # 这是旧完结含义的重命名，版本和旧事件保持一致，便于投递重试。
                connection.execute(update(Order).where(Order.id == order["id"]).values(status="completed"))
                changed += 1
            connection.commit()
            return changed
        except Exception:
            connection.rollback()
            raise


if __name__ == "__main__":
    from ...database import engine
    print(f"已保留原完结事实并升级 {upgrade(engine)} 单；账号、余额、流水和事件均未改写")
~~~~

### frontend/src/features/fulfillment/api.js

C 前端请求封装和显示映射；31 行。

SHA-256（原始文件字节）：`3e9ebaa59b09e6778e73128b7bd71f105b20497f42e08c4d157105d756c8bf97`

~~~~javascript
import { request } from "../../services/http";
export { formatTime, sizeLabels } from "../orders/api";
const path = (id) => `/orders/${encodeURIComponent(id)}`;
const post = (url, body, key) =>
  request(url, {
    method: "POST",
    body: JSON.stringify(body),
    ...(key ? { headers: { "Idempotency-Key": key } } : {}),
  });
export const fulfillmentApi = {
  current: () => request("/auth/current"),
  mine: (params) =>
    request(`/orders?${new URLSearchParams({ scope: "mine", ...params })}`),
  detail: (id) => request(path(id)),
  advance: (id, body, key) => post(`${path(id)}/status`, body, key),
  cancel: (id, body, key) => post(`${path(id)}/cancel`, body, key),
  reviews: (id) => request(`${path(id)}/reviews`),
  review: (id, body) => post(`${path(id)}/reviews`, body),
  credit: (uid) => request(`/users/${encodeURIComponent(uid)}/credit`),
};
export const statusLabels = {
  pending_payment: "待支付",
  pending: "待接单",
  accepted: "已接单",
  picking_up: "取件中",
  delivering: "配送中",
  delivered: "已送达，待收货",
  completed: "已完成",
  cancelled: "已取消",
};
export const money = (value) => `¥${(value / 100).toFixed(2)}`;
~~~~

### frontend/src/features/fulfillment/OrdersView.vue

订单页面入口；12 行。

SHA-256（原始文件字节）：`ce8d6af75708f6706627fe8811d24384702cc99b930ea2e00398980c6ddde0f1`

~~~~vue
<script setup>
import PageHeading from "../../components/PageHeading.vue";
import OrderWorkspace from "./OrderWorkspace.vue";
</script>
<template>
  <PageHeading
    title="每一份托付，都有迹可循"
    subtitle="查看发布与接取的订单，关注包裹的每一步。"
    eyebrow="MY ORDERS"
  />
  <OrderWorkspace />
</template>
~~~~

### frontend/src/features/fulfillment/OrderWorkspace.vue

订单工作台、履约交互和轮询；542 行。

SHA-256（原始文件字节）：`f3b053b2cadcad149f4711d666f285797cf8c1d16f3133517f64c72c58986a47`

~~~~vue
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { accessToken } from "../../services/auth-state";
import EmptyState from "../../components/EmptyState.vue";
import OrderReviews from "./OrderReviews.vue";
import {
  fulfillmentApi as api,
  statusLabels,
  money,
  formatTime,
  sizeLabels,
} from "./api";
const props = defineProps({ reviewOnly: Boolean });
const emit = defineEmits(["reviewed"]);
const user = ref(null),
  items = ref([]),
  total = ref(0),
  page = ref(1),
  role = ref("all");
const status = ref(props.reviewOnly ? "completed" : ""),
  loading = ref(false),
  listError = ref("");
const selected = ref(null),
  detail = ref(null),
  detailError = ref("");
const reason = ref(""),
  busy = ref(false),
  message = ref(""),
  revision = ref(0);
const loggedIn = !!accessToken(),
  pageSize = 10;
const steps = [
  "pending_payment",
  "pending",
  "accepted",
  "picking_up",
  "delivering",
  "delivered",
  "completed",
];
const next = computed(() => {
  if (
    detail.value?.status === "delivered" &&
    detail.value?.publisherUid === user.value?.uid
  )
    return ["confirm_receipt", "确认收货"];
  if (detail.value?.courierUid !== user.value?.uid) return;
  return {
    accepted: ["start_pickup", "开始取件"],
    picking_up: ["confirm_pickup", "确认取件"],
    delivering: ["confirm_delivery", "确认送达"],
  }[detail.value?.status];
});
const canCancel = computed(
  () =>
    detail.value?.publisherUid === user.value?.uid &&
    ["pending_payment", "pending"].includes(detail.value?.status) &&
    detail.value?.paymentStatus !== "paying",
);
let alive = true,
  listGeneration = 0,
  detailGeneration = 0,
  polling = false,
  timer;
const keys = new Map();
async function loadList(quiet = false) {
  const current = ++listGeneration;
  if (!quiet) {
    loading.value = true;
    listError.value = "";
  }
  try {
    const result = await api.mine({
      role: role.value,
      ...(status.value ? { status: status.value } : {}),
      page: page.value,
      pageSize,
    });
    if (!alive || current !== listGeneration) return;
    items.value = result.items;
    total.value = result.total;
    listError.value = "";
  } catch (e) {
    if (alive && current === listGeneration) listError.value = e.message;
  } finally {
    if (alive && current === listGeneration) loading.value = false;
  }
}
async function loadDetail(id = selected.value) {
  if (!id) return;
  const current = ++detailGeneration;
  try {
    const order = await api.detail(id);
    if (!alive || current !== detailGeneration || id !== selected.value) return;
    detail.value = order;
    detailError.value = "";
    revision.value++;
  } catch (e) {
    if (alive && current === detailGeneration)
      detailError.value = `无法更新订单：${e.message}。请刷新后操作。`;
  }
}
function open(id) {
  selected.value = id;
  detail.value = null;
  reason.value = "";
  message.value = "";
  detailError.value = "";
  loadDetail(id);
}
async function act(operation) {
  if (
    !detail.value ||
    busy.value ||
    detailError.value ||
    (operation !== "cancel" && !next.value)
  )
    return;
  const id = detail.value.orderId;
  const body =
    operation === "cancel"
      ? { version: detail.value.version, reason: reason.value.trim() }
      : {
          version: detail.value.version,
          action: next.value[0],
        };
  const signature = JSON.stringify([id, operation, body]);
  if (!keys.has(signature)) keys.set(signature, crypto.randomUUID());
  busy.value = true;
  message.value = "";
  try {
    await (operation === "cancel" ? api.cancel : api.advance)(
      id,
      body,
      keys.get(signature),
    );
    message.value =
      operation === "cancel"
        ? "订单已取消。已支付订单的退款结果将在此更新。"
        : "履约进度已更新。";
  } catch (e) {
    message.value = e.status
      ? e.message
      : "连接中断，操作结果待确认。刷新后可重试。";
  } finally {
    await Promise.all([loadDetail(id), loadList(true)]);
    busy.value = false;
  }
}
async function refresh() {
  if (polling || busy.value || !loggedIn) return;
  polling = true;
  try {
    if (!user.value) {
      const current = await api.current();
      if (!alive) return;
      user.value = current;
    }
    await Promise.all([loadList(true), loadDetail()]);
  } catch (e) {
    if (alive) listError.value = e.message;
  } finally {
    polling = false;
  }
}
watch([role, status], () => {
  page.value = 1;
  loadList();
});
watch(page, () => loadList());
onMounted(() => {
  if (!loggedIn) return;
  loading.value = true;
  refresh().finally(() => {
    if (alive) loading.value = false;
  });
  timer = window.setInterval(() => {
    if (!document.hidden) refresh();
  }, 10000);
});
onBeforeUnmount(() => {
  alive = false;
  listGeneration++;
  detailGeneration++;
  clearInterval(timer);
});
</script>
<template>
  <EmptyState
    v-if="!loggedIn"
    class="panel"
    title="登录后查看我的订单"
    description="跟进履约进度，发布者确认收货后互相评价。"
    ><RouterLink class="primary-button" to="/login?redirect=/orders"
      >去登录</RouterLink
    ></EmptyState
  >
  <section v-else class="fulfillment-workspace">
    <div class="panel filters">
      <label
        >我的身份<select v-model="role">
          <option value="all">全部参与订单</option>
          <option value="publisher">我发布的</option>
          <option value="courier">我接取的</option>
        </select></label
      >
      <label v-if="!reviewOnly"
        >订单状态<select v-model="status">
          <option value="">全部状态</option>
          <option
            v-for="(label, value) in statusLabels"
            :key="value"
            :value="value"
          >
            {{ label }}
          </option>
        </select></label
      >
      <button
        type="button"
        class="secondary-button"
        :disabled="loading || busy"
        @click="refresh"
      >
        刷新订单
      </button>
    </div>
    <p v-if="listError" class="error" role="alert">{{ listError }}</p>
    <p v-if="loading" role="status">正在加载订单…</p>
    <EmptyState
      v-else-if="!listError && !items.length"
      class="panel"
      title="暂无符合条件的订单"
      description="去大厅接取任务，或发布一份代取需求。"
      ><RouterLink class="primary-button" to="/tasks"
        >前往大厅</RouterLink
      ></EmptyState
    >
    <div v-else class="order-grid">
      <article
        v-for="item in items"
        :key="item.orderId"
        class="panel order-card"
        :class="{ chosen: item.orderId === selected }"
      >
        <div class="card-top">
          <strong>{{ item.company }} · {{ sizeLabels[item.size] }}</strong
          ><span class="badge">{{ statusLabels[item.status] }}</span>
        </div>
        <p>{{ item.stationName }} → {{ item.deliveryAreaName }}</p>
        <small>期望送达 {{ formatTime(item.expectedAt) }}</small>
        <div class="card-bottom">
          <strong>{{ money(item.amount) }}</strong
          ><button
            type="button"
            class="secondary-button"
            :disabled="busy"
            @click="open(item.orderId)"
          >
            {{ reviewOnly ? "查看与评价" : "查看订单" }}
          </button>
        </div>
      </article>
    </div>
    <nav v-if="total > pageSize" class="pagination" aria-label="订单分页">
      <button :disabled="page === 1 || loading" @click="page--">上一页</button
      ><span
        >第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页 ·
        {{ total }} 单</span
      ><button :disabled="page * pageSize >= total || loading" @click="page++">
        下一页
      </button>
    </nav>
    <section v-if="selected" class="panel detail" aria-label="订单详情">
      <h2>订单详情</h2>
      <p class="order-id">{{ selected }}</p>
      <p v-if="detailError" class="error" role="alert">{{ detailError }}</p>
      <p v-if="!detail && !detailError" role="status">正在加载详情…</p>
      <template v-if="detail">
        <ol
          v-if="detail.status !== 'cancelled'"
          class="progress"
          aria-label="履约进度"
        >
          <li
            v-for="(step, index) in steps"
            :key="step"
            :class="{ reached: index <= steps.indexOf(detail.status) }"
            :aria-current="step === detail.status ? 'step' : undefined"
          >
            {{ statusLabels[step] }}
          </li>
        </ol>
        <p v-else class="badge">订单已取消</p>
        <dl>
          <dt>取件位置</dt>
          <dd>{{ detail.stationName }}</dd>
          <dt>送达地址</dt>
          <dd>{{ detail.address }}</dd>
          <dt>备注</dt>
          <dd>{{ detail.note || "无" }}</dd>
          <dt>订单金额</dt>
          <dd>
            {{ money(detail.amount) }}（基础费 {{ money(detail.baseFee) }}，打赏
            {{ money(detail.tip) }}）
          </dd>
          <dt>支付 / 退款</dt>
          <dd>
            {{
              { unpaid: "未支付", paying: "支付处理中", paid: "已支付" }[
                detail.paymentStatus
              ]
            }}
            /
            {{
              {
                none: "无需退款",
                processing: "退款处理中",
                succeeded: "已退款",
              }[detail.refundStatus]
            }}
          </dd>
        </dl>
        <p v-if="detail.status === 'delivered'" role="status">
          代取员已确认送达，等待发布者确认收货；确认后订单完成并开放评价。
        </p>
        <p v-if="message" role="status">{{ message }}</p>
        <form
          v-if="next && !reviewOnly"
          class="action-form"
          @submit.prevent="act('advance')"
        >
          <button class="primary-button" :disabled="busy || !!detailError">
            {{ busy ? "处理中…" : next[1] }}
          </button>
        </form>
        <RouterLink
          v-if="
            detail.status === 'pending_payment' &&
            detail.publisherUid === user?.uid
          "
          class="secondary-button"
          :to="{ path: '/publish', query: { orderId: detail.orderId } }"
          >{{
            detail.paymentStatus === "paying" ? "查看支付进度" : "继续支付"
          }}</RouterLink
        >
        <form
          v-if="canCancel && !reviewOnly"
          class="action-form cancel-form"
          @submit.prevent="act('cancel')"
        >
          <label
            >取消原因<input
              v-model="reason"
              required
              maxlength="200"
              placeholder="请填写取消原因"
              :disabled="busy" /></label
          ><button class="secondary-button" :disabled="busy || !!detailError">
            取消订单
          </button>
        </form>
        <OrderReviews
          v-if="detail.status === 'completed'"
          :key="detail.orderId"
          :order-id="detail.orderId"
          :uid="user?.uid"
          :revision="revision"
          @submitted="emit('reviewed')"
        />
      </template>
    </section>
  </section>
</template>
<style scoped>
.fulfillment-workspace {
  display: grid;
  gap: 20px;
  min-width: 0;
  font-size: 13px;
}
.panel {
  padding: 24px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: end;
}
label {
  display: grid;
  gap: 7px;
}
.secondary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f1f6f2;
  border: 1px solid #ceddce;
  color: #345a41;
  padding: 11px 16px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
}
select,
input {
  font: inherit;
  padding: 11px;
  border: 1px solid #cad7ce;
  border-radius: 9px;
  min-width: 0;
  max-width: 100%;
}
.order-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}
.order-card {
  display: grid;
  gap: 10px;
  border: 1px solid var(--border);
}
.chosen {
  border-color: #60966b;
}
.card-top,
.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.card-bottom {
  margin-top: 12px;
}
.badge {
  background: #edf4e9;
  color: #36623c;
  padding: 5px 10px;
  border-radius: 20px;
  font-size: 13px;
}
.pagination {
  display: flex;
  justify-content: center;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.pagination button {
  padding: 9px;
  border-radius: 7px;
  border: 1px solid #ced9ce;
  background: white;
}
.order-id {
  color: #69736a;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.progress {
  display: flex;
  padding: 0;
  list-style: none;
  gap: 8px;
  flex-wrap: wrap;
  margin: 24px 0;
}
.progress li {
  color: #6d786e;
  background: #f1f3f0;
  padding: 8px 12px;
  border-radius: 8px;
}
.progress .reached {
  color: #2e5d37;
  background: #e4efd9;
}
dl {
  display: grid;
  grid-template-columns: 100px minmax(0, 1fr);
  gap: 14px;
}
dt {
  color: #6d786e;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.action-form {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 12px;
  margin: 24px 0;
}
.cancel-form {
  border-top: 1px solid #e3e8e4;
  padding-top: 20px;
}
.action-form label {
  flex: 1;
  max-width: 420px;
}
.error {
  color: #a3342b;
}
small {
  color: #66766a;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
@media (max-width: 650px) {
  .order-grid {
    grid-template-columns: 1fr;
  }
  .filters {
    align-items: stretch;
  }
  .filters label {
    flex: 1 1 100%;
  }
  dl {
    grid-template-columns: 78px minmax(0, 1fr);
  }
  .detail {
    padding: 20px;
  }
  .action-form {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
~~~~

### frontend/src/features/fulfillment/OrderReviews.vue

单个订单的双向评价；165 行。

SHA-256（原始文件字节）：`e13e7aeb08784c6ab47982b38f6c2935706b391b8d416e126928006c933c3397`

~~~~vue
<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { fulfillmentApi as api, formatTime } from "./api";
const props = defineProps({ orderId: String, uid: String, revision: Number });
const emit = defineEmits(["submitted"]);
const records = ref([]),
  reviewable = ref(false),
  loaded = ref(false),
  busy = ref(false),
  loadError = ref(""),
  error = ref("");
const rating = ref(5),
  tags = ref([]),
  comment = ref("");
const choices = ["准时送达", "沟通顺畅", "包裹完好", "态度友好", "有待改进"];
const mine = computed(() =>
  records.value.some((item) => item.reviewerUid === props.uid),
);
let generation = 0;
async function load() {
  const current = ++generation;
  try {
    const result = await api.reviews(props.orderId);
    if (current !== generation) return;
    records.value = result.items;
    reviewable.value = result.reviewable;
    loaded.value = true;
    loadError.value = "";
  } catch (e) {
    if (current === generation) loadError.value = e.message;
  }
}
async function submit() {
  busy.value = true;
  error.value = "";
  try {
    await api.review(props.orderId, {
      rating: rating.value,
      tags: tags.value,
      comment: comment.value.trim(),
    });
    emit("submitted");
  } catch (e) {
    error.value =
      e.status === 409 ? e.message : `${e.message}。请刷新确认评价是否已提交。`;
  } finally {
    await load();
    busy.value = false;
  }
}
watch(() => [props.orderId, props.revision], load, { immediate: true });
onBeforeUnmount(() => {
  generation++;
});
</script>
<template>
  <section class="reviews" aria-label="订单评价">
    <h3>双向评价</h3>
    <p v-if="loadError || error" role="alert" class="error">
      {{ loadError || error }}
    </p>
    <button type="button" class="text-button" @click="load">刷新评价</button>
    <p v-if="!loaded && !loadError">正在加载评价…</p>
    <article v-for="item in records" :key="item.reviewId" class="review">
      <strong
        >{{ item.reviewerUid === uid ? "我的评价" : "对方的评价" }} ·
        {{ item.rating }} / 5 星</strong
      >
      <p v-if="item.tags.length">{{ item.tags.join(" · ") }}</p>
      <p class="comment">{{ item.comment || "未填写文字评价" }}</p>
      <small>{{ formatTime(item.createdAt) }}</small>
    </article>
    <p v-if="loaded && mine" role="status">
      评价已提交，不可修改。等待彼此的下一次信任。
    </p>
    <p v-else-if="loaded && !reviewable">
      完成结果确认中，评价入口将自动更新。
    </p>
    <form v-else-if="loaded" @submit.prevent="submit">
      <label
        >评分
        <select v-model="rating" :disabled="busy">
          <option v-for="n in 5" :key="n" :value="n">{{ n }} 星</option>
        </select>
      </label>
      <fieldset :disabled="busy">
        <legend>评价标签（可选，最多 5 项）</legend>
        <label v-for="tag in choices" :key="tag" class="tag"
          ><input v-model="tags" type="checkbox" :value="tag" />{{ tag }}</label
        >
      </fieldset>
      <label
        >文字评价（可选）<textarea
          v-model="comment"
          maxlength="500"
          rows="3"
          :disabled="busy"
          placeholder="分享本次互助体验"
        />
      </label>
      <small>{{ comment.length }} / 500 · 提交后不可修改</small>
      <button class="primary-button" :disabled="busy">
        {{ busy ? "提交中…" : "提交评价" }}
      </button>
    </form>
  </section>
</template>
<style scoped>
.reviews {
  border-top: 1px solid #e3e8e4;
  margin-top: 24px;
  padding-top: 12px;
}
.review {
  padding: 16px;
  background: #f4f7f3;
  border-radius: 12px;
  margin: 12px 0;
}
.comment {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
form {
  display: grid;
  gap: 12px;
  max-width: 620px;
}
label {
  display: grid;
  gap: 6px;
}
select,
textarea {
  padding: 10px;
  border: 1px solid #cdd8ce;
  border-radius: 8px;
  font: inherit;
  width: 100%;
}
fieldset {
  border: 1px solid #dde4de;
  border-radius: 8px;
  padding: 12px;
}
.tag {
  display: inline-flex;
  align-items: center;
  margin: 6px 16px 6px 0;
  gap: 6px;
}
.error {
  color: #a3342b;
}
small {
  color: #66766a;
}
.text-button {
  background: none;
  border: 0;
  color: #346844;
  cursor: pointer;
  padding: 8px 0;
}
</style>
~~~~

### frontend/src/features/fulfillment/ReviewsView.vue

本人信用与评价页面；112 行。

SHA-256（原始文件字节）：`82cbd43e117ecadd5f2d99f1aea406c8da7d8cf47f7f0e5e38bb72caa85d0799`

~~~~vue
<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import PageHeading from "../../components/PageHeading.vue";
import OrderWorkspace from "./OrderWorkspace.vue";
import { fulfillmentApi as api } from "./api";
import { accessToken } from "../../services/auth-state";
const credit = ref(null),
  error = ref(""),
  busy = ref(false);
let alive = true,
  user,
  timer;
async function load() {
  if (!accessToken() || busy.value) return;
  busy.value = true;
  try {
    user ||= await api.current();
    const result = await api.credit(user.uid);
    if (alive) {
      credit.value = result;
      error.value = "";
    }
  } catch (e) {
    if (alive) error.value = e.message;
  } finally {
    if (alive) busy.value = false;
  }
}
onMounted(() => {
  load();
  timer = setInterval(() => {
    if (!document.hidden) load();
  }, 10000);
});
onBeforeUnmount(() => {
  alive = false;
  clearInterval(timer);
});
</script>
<template>
  <PageHeading
    title="认真对待，每一份信任"
    subtitle="发布者确认收货后可进行评价，信用让校园互助更安心。"
    eyebrow="REVIEWS & CREDIT"
  />
  <div class="summary-grid">
    <div class="panel summary">
      <p>我的信用分</p>
      <strong
        >{{ credit?.score?.toFixed(2) ?? "—" }} <small>/ 5.0</small></strong
      ><span v-if="credit"
        >{{
          {
            new: "新人信用",
            restricted: "限制接单",
            normal: "信用正常",
            good: "信用良好",
          }[credit.level]
        }}
        · 最近 {{ credit.reviewCount }} 条有效评价</span
      ><span v-else>{{ busy ? "正在查询…" : "登录后查询" }}</span
      ><button
        type="button"
        class="secondary-button"
        :disabled="busy"
        @click="load"
      >
        刷新信用
      </button>
    </div>
    <div class="panel summary">
      <p>信用规则</p>
      <h3>最近 30 条取件评价均分</h3>
      <span
        >仅计入作为取件员收到的评价；新人可接单，均分低于 3.0 时限制接单。</span
      >
      <p v-if="credit && !credit.creditEligible" role="status">
        当前信用不足，暂时不能接取新订单，已接订单仍需完成。
      </p>
    </div>
  </div>
  <p v-if="error" role="alert">{{ error }}</p>
  <OrderWorkspace review-only @reviewed="load" />
</template>
<style scoped>
.summary {
  display: flex;
  flex-direction: column;
  align-items: start;
  gap: 10px;
}
.summary strong {
  margin: 4px 0;
}
.summary h3 {
  margin: 10px 0;
}
.summary > span {
  line-height: 1.8;
  font-size: 12px;
  color: #66776c;
}
.secondary-button {
  background: #f1f6f2;
  color: #345a41;
  border: 1px solid #ceddce;
  padding: 9px 14px;
  border-radius: 8px;
  font-size: 12px;
  margin-top: 4px;
}
</style>
~~~~

## 13. 修改过的公共接入与需求文档
以下为当前文件完整内容；公共文件包含既有团队代码，其个人修改另见第 15 节。

### backend/app/main.py

公共应用入口：接入 C 的表和路由；98 行。

SHA-256（原始文件字节）：`098f5d1d867c9f7ba0e2f396fb25116dffdfcd98d5b3bde16db6d7df0ff807ca`

~~~~python
"""F3/F4 应用入口与统一错误处理；A/C/D 的业务服务由单体装配注入。"""

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from .database import Base, engine
from .common import Idempotency
from .events import start_processor
from .events.models import OutboxEvent, Delivery
from .events.wiring import register_defaults
from .modules.identity.api import router as identity_router
from .modules.identity.config import Settings
from .modules.identity.models import User, Challenge, LoginSession, VerificationState
from .modules.identity.service import IdentityService
from .modules.identity.verification_api import router as verification_router
from .modules.identity.models import VerificationApplication, VerificationPhoto, VerificationReview, VerificationNotification

from .modules.finance.services.pricing import PricingService
from .modules.finance.models import Account, Ledger, RechargeOrder, WithdrawOrder, Payment, Refund, FinanceReceipt, Settlement
from .modules.finance.routers import wallet, payment
from .modules.finance.services import withdraw as withdraw_service
from .modules.orders.api import router as orders_router
from .modules.orders.entities import Order
from .modules.orders.handlers import EventReceipt, PaymentFact
from .modules.fulfillment.api import router as fulfillment_router
from .modules.fulfillment.models import TABLES as fulfillment_tables


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine, tables=[Order.__table__, Idempotency.__table__,
                                          EventReceipt.__table__, PaymentFact.__table__,
                                          User.__table__, Challenge.__table__,
                                          LoginSession.__table__, VerificationState.__table__,
                                          Account.__table__, Ledger.__table__, Payment.__table__, Refund.__table__, FinanceReceipt.__table__, Settlement.__table__,
                                          RechargeOrder.__table__, WithdrawOrder.__table__,
                                          VerificationApplication.__table__, VerificationPhoto.__table__,
                                          VerificationReview.__table__, VerificationNotification.__table__,
                                          OutboxEvent.__table__, Delivery.__table__, *fulfillment_tables])
    if not hasattr(app.state, "identity_service"):
        app.state.identity_service = IdentityService(Settings.from_environment())
    if not hasattr(app.state, "pricing_service"):
        app.state.pricing_service = PricingService()
    # 成员 D：提现后台演示任务（团队接口约定 v1.1：≥3 秒标记 succeeded，重启续处理）
    withdraw_service.start_withdraw_processor()
    register_defaults()
    processor = start_processor(sessionmaker(bind=engine, autoflush=False))
    app.state.event_processor = processor
    try:
        yield
    finally:
        await asyncio.to_thread(processor.stop)
        del app.state.event_processor


app = FastAPI(title="校园快递代取管理系统", version="1.1.0", lifespan=lifespan)
for router in (orders_router, identity_router, verification_router, wallet.router, payment.router, fulfillment_router):
    app.include_router(router)


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    body = error.detail if isinstance(error.detail, dict) else {
        "detail": error.detail, "code": {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "ORDER_CONFLICT", 422: "VALIDATION_ERROR", 503: "DEPENDENCY_UNAVAILABLE"}.get(error.status_code, "REQUEST_FAILED"), "fields": {}}
    return JSONResponse(body, status_code=error.status_code, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    fields = {str(item["loc"][-1]): item["msg"] for item in error.errors()}
    return JSONResponse({"detail": "请检查输入内容", "code": "VALIDATION_ERROR", "fields": fields}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, error):
    return JSONResponse({"detail": "请求发生并发冲突，请使用原提交标识重试", "code": "REQUEST_IN_PROGRESS", "fields": {}}, status_code=409)


@app.exception_handler(OperationalError)
async def unavailable(request, error):
    return JSONResponse({"detail": "数据服务繁忙，请稍后重试", "code": "DEPENDENCY_UNAVAILABLE", "fields": {}}, status_code=503)


@app.exception_handler(Exception)
async def internal_error(request, error):
    return JSONResponse({"detail": "服务暂时无法完成请求，请稍后重试", "code": "INTERNAL_ERROR", "fields": {}}, status_code=500)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
~~~~

### backend/app/events/wiring.py

公共事件订阅：接入 C 开放评价消费者；16 行。

SHA-256（原始文件字节）：`8da010f2bec1272672edbc301afcaa80d34083a0f3e35d3e5525afd595e313d8`

~~~~python
"""单体订阅装配。"""
from . import register_consumer


def register_defaults():
    from ..modules.orders import event_handlers
    from ..modules.orders.projections import handle as refresh
    from ..modules.finance.services.event_handlers import on_order_cancelled, on_order_completed
    from ..modules.fulfillment.handlers import on_order_completed as open_reviews
    for kind, handler in event_handlers().items():
        register_consumer(kind, "orders", handler)
    for kind in ("order.status_changed", "order.cancelled"):
        register_consumer(kind, "orders", refresh)
    register_consumer("order.cancelled", "finance", on_order_cancelled)
    register_consumer("order.completed", "finance", on_order_completed)
    register_consumer("order.completed", "fulfillment", open_reviews)
~~~~

### backend/app/events/schema.py

公共状态事件枚举：增加 completed；117 行。

SHA-256（原始文件字节）：`08ee0806be2269ea8263b0ac244891f3e931482700470ce35549b6d605e2b815`

~~~~python
"""公共事件边界：严格 JSON、已约定类型及必要业务字段，拒绝隐私附加字段。"""
import hashlib
import json
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, ValidationError
from ..common import Input, fail


SUBSCRIPTIONS = {
    "payment.succeeded": ("orders",),
    "payment.failed": ("orders",),
    "refund.succeeded": ("orders",),
    "order.status_changed": ("orders",),
    "order.cancelled": ("orders", "finance"),
    "order.completed": ("finance", "fulfillment"),
}

Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Positive = Annotated[int, Field(strict=True, gt=0)]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
Status = Literal["pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "completed", "cancelled"]


class Envelope(Input):
    eventId: str
    type: str
    occurredAt: str
    orderId: Identifier
    aggregateType: Literal["payment", "refund", "order"]
    aggregateId: Identifier
    version: Positive
    payload: dict


class PaymentPayload(Input):
    paymentId: Identifier
    paymentRequestId: Identifier
    payerUid: Identifier
    amount: Positive
    code: str | None = None


class RefundPayload(Input):
    refundId: Identifier
    paymentId: Identifier
    payerUid: Identifier
    amount: Positive


class Cancellation(Input):
    publisherUid: Identifier
    paymentId: Identifier | None
    amount: Positive
    paid: bool = Field(strict=True)
    orderVersion: Positive


class Completion(Input):
    publisherUid: Identifier
    courierUid: Identifier
    amount: Positive
    baseFee: Nonnegative
    tip: Nonnegative
    commissionRateBps: int = Field(strict=True, ge=0, le=10000)
    pricingVersion: Identifier
    orderVersion: Positive


class StatusChange(Input):
    fromStatus: Status
    status: Status
    courierUid: Identifier | None
    orderVersion: Positive


def validate(event):
    try:
        if type(event) is not dict:
            raise ValueError("事件必须为字典")
        data = Envelope.model_validate(event)
        if str(UUID(data.eventId)) != event["eventId"]:
            raise ValueError("事件标识必须为规范 UUID")
        if not event["occurredAt"].endswith("Z"):
            raise ValueError("事件时间必须为 UTC Z 字符串")
        occurred = datetime.fromisoformat(event["occurredAt"].replace("Z", "+00:00"))
        if occurred.utcoffset() != timedelta(0):
            raise ValueError("事件时间缺少 UTC 时区")
        if data.type not in SUBSCRIPTIONS:
            raise ValueError("事件类型未约定")
        if data.type.startswith("payment."):
            body = PaymentPayload.model_validate(data.payload)
            if ((data.type == "payment.failed" and not body.code)
                    or (data.type == "payment.succeeded" and body.code is not None)):
                raise ValueError("支付结果与失败代码不一致")
            aggregate_type, aggregate_id = "payment", body.paymentId
        elif data.type == "refund.succeeded":
            body = RefundPayload.model_validate(data.payload)
            aggregate_type, aggregate_id = "refund", body.refundId
        else:
            model = {"order.cancelled": Cancellation, "order.completed": Completion,
                     "order.status_changed": StatusChange}[data.type]
            body = model.model_validate(data.payload)
            aggregate_type, aggregate_id = "order", data.orderId
            if body.orderVersion != data.version:
                raise ValueError("订单版本不一致")
            if isinstance(body, Cancellation) and body.paid != (body.paymentId is not None):
                raise ValueError("支付标识不一致")
            if isinstance(body, Completion) and body.amount != body.baseFee + body.tip:
                raise ValueError("金额不一致")
        if (data.aggregateType, data.aggregateId) != (aggregate_type, aggregate_id):
            raise ValueError("聚合标识不一致")
        encoded = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return json.loads(encoded), hashlib.sha256(encoded.encode()).hexdigest()
    except (ValidationError, ValueError, TypeError, OverflowError):
        fail(422, "VALIDATION_ERROR", "事件格式不符合团队接口约定")
~~~~

### backend/app/modules/orders/gateway.py

B 受控写入口：发布者收货与配送动作分离；86 行。

SHA-256（原始文件字节）：`ddf2def64a4ebd5b39862fc39405edf92b7641e797286a3d1cff3b30c1e46e34`

~~~~python
"""订单唯一受控写入口，不提交调用方事务。"""
from dataclasses import make_dataclass
from sqlalchemy import update

from ...common import fail
from .entities import Order

OrderSnapshot = make_dataclass("OrderSnapshot", [(column.key, object) for column in Order.__table__.columns], frozen=True)


def snapshot(order):
    return OrderSnapshot(**{column.key: getattr(order, column.key) for column in Order.__table__.columns})


class OrderGateway:
    @staticmethod
    def get_snapshot(db, order_id):
        order = db.get(Order, order_id)
        if not order:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        return snapshot(order)

    @staticmethod
    def related(db, order_id, uid):
        order = OrderGateway.get_snapshot(db, order_id)
        if uid not in {order.publisher_uid, order.courier_uid}:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        return order

    @staticmethod
    def transition(db, order, version, operation, actor_uid, **changes):
        rules = {
            "reserve": ({"pending_payment"}, {"payment_status", "payment_request_id", "payer_uid"}),
            "payment": ({"pending_payment"}, {"payment_status", "status", "payment_id"}),
            "accept": ({"pending"}, {"status", "courier_uid"}),
            "cancel": ({"pending_payment", "pending"}, {"status", "refund_status"}),
            "fulfill": ({"accepted", "picking_up", "delivering"}, {"status"}),
            "confirm_receipt": ({"delivered"}, {"status"}),
            "refund": ({"cancelled"}, {"refund_status", "refund_id"}),
        }
        if operation not in rules:
            fail(409, "ORDER_CONFLICT", "不支持的订单操作")
        statuses, allowed = rules[operation]
        if set(changes) - allowed or order.status not in statuses:
            fail(409, "ORDER_CONFLICT", "订单状态不允许此操作")
        if operation in {"reserve", "cancel", "confirm_receipt"} and actor_uid != order.publisher_uid:
            fail(404, "NOT_FOUND", "订单不存在或不可访问")
        if operation == "accept" and (actor_uid == order.publisher_uid or order.payment_status != "paid"):
            fail(409, "ORDER_CONFLICT", "此订单不能接单")
        if operation == "cancel" and order.payment_status == "paying":
            fail(409, "PAYMENT_IN_PROGRESS", "支付处理中，请等待确定结果")
        if operation == "fulfill" and actor_uid != order.courier_uid:
            fail(409, "ORDER_CONFLICT", "无权推进订单履约")
        valid = True
        if operation == "reserve":
            valid = (order.payment_status == "unpaid" and changes.get("payment_status") == "paying"
                     and changes.get("payer_uid") == order.publisher_uid and bool(changes.get("payment_request_id")))
        elif operation == "payment":
            valid = (order.payment_status == "paying" and (changes.get("status"), changes.get("payment_status"))
                     in {("pending", "paid"), ("pending_payment", "unpaid")}
                     and (bool(changes.get("payment_id")) == (changes.get("payment_status") == "paid")))
        elif operation == "accept":
            valid = (changes == {"status": "accepted", "courier_uid": actor_uid} and actor_uid is not None)
        elif operation == "cancel":
            valid = (changes.get("status") == "cancelled" and changes.get("refund_status") ==
                     ("processing" if order.payment_status == "paid" else "none") and
                     (order.status, order.payment_status) in {("pending_payment", "unpaid"), ("pending", "paid")})
        elif operation == "fulfill":
            valid = (set(changes) == {"status"} and (order.status, changes["status"]) in
                     {("accepted", "picking_up"), ("picking_up", "delivering"), ("delivering", "delivered")})
        elif operation == "confirm_receipt":
            valid = (changes == {"status": "completed"} and order.payment_status == "paid"
                     and order.refund_status == "none" and bool(order.courier_uid))
        elif operation == "refund":
            valid = (order.payment_status == "paid" and order.refund_status == "processing" and
                     changes.get("refund_status") == "succeeded" and bool(changes.get("refund_id")))
        if not valid:
            fail(409, "ORDER_CONFLICT", "订单转换不符合状态规则")
        changed = db.execute(update(Order).where(Order.id == order.id, Order.version == version,
                             Order.status == order.status, Order.payment_status == order.payment_status
                             ).values(**changes, version=Order.version + 1))
        if changed.rowcount != 1:
            fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新后重试")
        db.flush()
        db.expire_all()
        return OrderGateway.get_snapshot(db, order.id)
~~~~

### backend/app/modules/orders/api.py

B 查询：completed 状态过滤；166 行。

SHA-256（原始文件字节）：`a57cb8356bd845607dfe5a763c4002f20e7e33937be24154d79bc3008de8a756`

~~~~python
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...common import Key, VersionInput, fail, iso, now, remember, replay
from . import integrations
from ...database import get_db

from .integrations import current_identity as current, require_verified
from .contract import AREAS, STATIONS, OrderDraft
from .entities import Order
from .gateway import OrderGateway

router = APIRouter(prefix="/api/orders", tags=["orders"])
STATUSES = {"pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "completed", "cancelled"}


def validate_delivery_time(body):
    if not now() < body.expectedAt <= now() + timedelta(days=7):
        fail(422, "VALIDATION_ERROR", "请选择未来七天内的送达时间", {"expectedAt": "请选择未来七天内的送达时间"})


def summary(order):
    return {"orderId": order.id, "company": order.company, "stationId": order.station_id,
            "stationName": STATIONS[order.station_id], "deliveryAreaId": order.area_id,
            "deliveryAreaName": AREAS[order.area_id], "size": order.size, "weight": order.weight,
            "expectedAt": order.expected_at, "note": order.note, "baseFee": order.base_fee,
            "tip": order.tip, "amount": order.amount, "status": order.status,
            "paymentStatus": order.payment_status, "refundStatus": order.refund_status,
            "version": order.version, "createdAt": order.created_at, "demo": order.demo}


def detail_view(order, uid):
    result = {**summary(order), "publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
              "locked": order.locked, "pickupFailureCount": order.pickup_failures,
              "address": order.address, "code": order.code}
    if uid == order.publisher_uid:
        result["paymentRequestId"] = order.payment_request_id
    return result


@router.get("/locations")
def locations():
    return {"stations": [{"id": key, "name": value} for key, value in STATIONS.items()],
            "deliveryAreas": [{"id": key, "name": value} for key, value in AREAS.items()]}


@router.post("/quote")
def quote(body: OrderDraft, request: Request, user=Depends(current), db: Session = Depends(get_db)):
    require_verified(user)
    validate_delivery_time(body)
    return integrations.quote(body, request)


@router.post("", status_code=201)
def create(body: OrderDraft, request: Request, idempotency_key: Key, user=Depends(current), db: Session = Depends(get_db)):
    require_verified(user)
    payload = body.model_dump(mode="json")
    result = replay(db, user.uid, "create-order", idempotency_key, payload)
    if result:
        return result
    validate_delivery_time(body)
    fees = integrations.quote(body, request)
    order = Order(id=str(uuid4()), publisher_uid=user.uid, company=body.company, code=body.code,
                  station_id=body.stationId, area_id=body.deliveryAreaId, address=body.address,
                  size=body.size, weight=body.weight, expected_at=iso(body.expectedAt), note=body.note,
                  base_fee=fees["baseFee"], tip=fees["tip"], amount=fees["amount"],
                  commission_bps=fees["commissionRateBps"], pricing_version=fees["pricingVersion"],
                  created_at=iso(now()), demo=fees["demo"])
    db.add(order)
    db.flush()
    result = detail_view(order, user.uid)
    remember(db, user.uid, "create-order", idempotency_key, payload, result)
    db.commit()
    return result


def query_time(value, field):
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone")
        return iso(result.astimezone(timezone.utc))
    except ValueError:
        fail(422, "VALIDATION_ERROR", "时间必须是带时区的 ISO 8601 格式", {field: "时间格式不正确"})


@router.get("")
def orders(request: Request, scope: Literal["hall", "mine"] = "hall", status: str | None = None,
           stationId: str | None = None, deliveryAreaId: str | None = None,
           tipMin: int | None = Query(None, ge=0, le=99900), tipMax: int | None = Query(None, ge=0, le=99900),
           expectedFrom: str | None = None, expectedTo: str | None = None,
           role: Literal["publisher", "courier", "all"] = "all", page: int = Query(1, ge=1),
           pageSize: int = Query(20, ge=1, le=100), user=Depends(current), db: Session = Depends(get_db)):
    allowed = {"scope", "status", "stationId", "deliveryAreaId", "tipMin", "tipMax", "expectedFrom", "expectedTo", "role", "page", "pageSize"}
    if set(request.query_params) - allowed:
        fail(422, "VALIDATION_ERROR", "查询包含未声明字段")
    for name in ("tipMin", "tipMax", "page", "pageSize"):
        raw = request.query_params.get(name)
        if raw is not None and (not raw.isascii() or not raw.isdigit()):
            fail(422, "VALIDATION_ERROR", "金额和分页参数必须为整数", {name: "请输入非负整数"})
    if status is not None and (status not in STATUSES or (scope == "hall" and status != "pending")):
        fail(422, "VALIDATION_ERROR", "订单状态筛选值不正确", {"status": "大厅仅允许 pending"})
    if stationId is not None and stationId not in STATIONS or deliveryAreaId is not None and deliveryAreaId not in AREAS:
        fail(422, "VALIDATION_ERROR", "请从地点目录选择取件点和送达区域")
    start, end = query_time(expectedFrom, "expectedFrom"), query_time(expectedTo, "expectedTo")
    if (tipMin is not None and tipMax is not None and tipMin > tipMax) or (start and end and start > end):
        fail(422, "VALIDATION_ERROR", "筛选下限不能大于上限")
    conditions = []
    if scope == "hall":
        conditions += [Order.status == "pending", Order.payment_status == "paid", Order.publisher_uid != user.uid]
    else:
        if role == "publisher":
            conditions.append(Order.publisher_uid == user.uid)
        elif role == "courier":
            conditions.append(Order.courier_uid == user.uid)
        else:
            conditions.append(or_(Order.publisher_uid == user.uid, Order.courier_uid == user.uid))
        if status:
            conditions.append(Order.status == status)
    for column, value in [(Order.station_id, stationId), (Order.area_id, deliveryAreaId)]:
        if value is not None:
            conditions.append(column == value)
    for column, value, lower in [(Order.tip, tipMin, True), (Order.tip, tipMax, False),
                                  (Order.expected_at, start, True), (Order.expected_at, end, False)]:
        if value is not None:
            conditions.append(column >= value if lower else column <= value)
    total = db.scalar(select(func.count()).select_from(Order).where(*conditions))
    sort = [Order.expected_at.asc(), Order.created_at.desc(), Order.id.asc()] if scope == "hall" else [Order.created_at.desc(), Order.id.asc()]
    rows = db.scalars(select(Order).where(*conditions).order_by(*sort).offset((page - 1) * pageSize).limit(pageSize))
    return {"items": [summary(order) for order in rows], "total": total, "page": page, "pageSize": pageSize}


@router.get("/{order_id}")
def detail(order_id: str, user=Depends(current), db: Session = Depends(get_db)):
    return detail_view(OrderGateway.related(db, order_id, user.uid), user.uid)


@router.post("/{order_id}/payment-request")
def payment_request(order_id: str, body: VersionInput, idempotency_key: Key,
                    user=Depends(current), db: Session = Depends(get_db)):
    operation = f"payment-request:{order_id}"
    result = replay(db, user.uid, operation, idempotency_key, body.model_dump())
    if result:
        return result
    order = OrderGateway.related(db, order_id, user.uid)
    if order.publisher_uid != user.uid:
        fail(404, "NOT_FOUND", "订单不存在")
    if order.version != body.version:
        fail(409, "ORDER_CONFLICT", "订单版本已变化，请刷新")
    if order.status != "pending_payment" or order.payment_status == "paid":
        fail(409, "ORDER_CONFLICT", "订单不允许支付")
    if order.payment_status == "unpaid":
        order = OrderGateway.transition(db, order, body.version, "reserve", user.uid,
                                payment_status="paying", payment_request_id=str(uuid4()), payer_uid=user.uid)
    result = {"orderId": order.id, "paymentRequestId": order.payment_request_id, "amount": order.amount,
              "paymentStatus": order.payment_status, "version": order.version}
    remember(db, user.uid, operation, idempotency_key, body.model_dump(), result)
    db.commit()
    return result
~~~~

### backend/app/modules/orders/projections.py

B 既有大厅投影：兼容历史完结状态重命名；60 行。

SHA-256（原始文件字节）：`2fcae0c0736d6486739bce7bc13434bd8ceaefde0e326eaf7f5759401357fc22`

~~~~python
"""大厅直接查询订单主表；状态事件校准到最新快照并持久化刷新回执。"""
from sqlalchemy import select
from ...common import fail, fingerprint
from ...events.schema import validate
from ...events.models import OutboxEvent
from .gateway import OrderGateway
from .handlers import EventReceipt


def legacy_delivery_matches(db, order, data):
    """旧 delivered 完结重命名后，保留原状态事件而以匹配的完结事实校准。"""
    body = data["payload"]
    if (order.status != "completed" or data["version"] != order.version
            or (body["fromStatus"], body["status"], body["courierUid"])
            != ("delivering", "delivered", order.courier_uid)):
        return False
    expected = {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
                "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
                "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
                "orderVersion": order.version}
    events = db.scalars(select(OutboxEvent).where(OutboxEvent.order_id == order.id,
                                                 OutboxEvent.type == "order.completed"))
    for event in events:
        completion, digest = validate(event.body)
        if (event.digest == digest and completion["type"] == "order.completed"
                and completion["orderId"] == order.id and completion["version"] == order.version
                and completion["payload"] == expected):
            return True
    return False


def handle(db, event):
    data, _ = validate(event)
    if data["type"] not in {"order.status_changed", "order.cancelled"}:
        fail(422, "VALIDATION_ERROR", "不支持的大厅刷新事件")
    digest = fingerprint(event)
    receipt = db.scalar(select(EventReceipt).where(EventReceipt.consumer == "orders",
        EventReceipt.event_id == data["eventId"]))
    if receipt:
        if receipt.digest != digest:
            fail(409, "IDEMPOTENCY_CONFLICT", "同一事件标识的内容发生变化")
        return receipt.result
    order = OrderGateway.get_snapshot(db, data["orderId"])
    if data["version"] > order.version:
        fail(409, "ORDER_CONFLICT", "事件版本超前于订单事实")
    body = data["payload"]
    if data["type"] == "order.cancelled":
        if (order.status != "cancelled" or body["publisherUid"] != order.publisher_uid
                or body["amount"] != order.amount or body["paymentId"] != order.payment_id
                or body["paid"] != (order.payment_status == "paid")):
            fail(409, "ORDER_CONFLICT", "取消事件与订单事实不一致")
    elif (data["version"] == order.version
          and (body["status"], body["courierUid"]) != (order.status, order.courier_uid)
          and not legacy_delivery_matches(db, order, data)):
        fail(409, "ORDER_CONFLICT", "状态事件与当前订单快照不一致")
    result = {"accepted": True, "orderId": order.id, "version": order.version, "status": order.status}
    db.add(EventReceipt(id=f"orders:{data['eventId']}", consumer="orders",
        event_id=data["eventId"], digest=digest, result=result))
    db.flush()
    return result
~~~~

### backend/app/modules/finance/services/settlement.py

D 结算消费者：仅 completed 可结算；44 行。

SHA-256（原始文件字节）：`171a759a580930e0cd8a1c4851de4bc917c077756b649b79f80012912960ab75`

~~~~python
"""完结结算共享消费者事务，不直接修改订单，不二次扣可用余额。"""
from uuid import uuid4
from sqlalchemy import select
from ....common import fail
from ...orders.gateway import OrderGateway
from ..models import Payment, Settlement
from ..core.wallet_core import settle_payment
from ..core.fee_util import split_settlement


def settle_order(db, command):
    order = OrderGateway.get_snapshot(db, command.order_id)
    if (order.status != "completed" or order.payment_status != "paid" or order.refund_status != "none"
            or not order.courier_uid or order.publisher_uid == order.courier_uid
            or (command.publisher_uid, command.courier_uid, command.amount_cent,
                command.base_fee_cent, command.commission_rate_bps) !=
               (order.publisher_uid, order.courier_uid, order.amount, order.base_fee, order.commission_bps)):
        fail(409, "ORDER_CONFLICT", "完结事件与订单状态或金额快照不一致")
    payment = db.get(Payment, order.payment_id) if order.payment_id else None
    if (payment is None or payment.order_id != order.id or payment.payer_uid != order.publisher_uid
            or payment.amount != order.amount or payment.status != "succeeded"):
        fail(409, "ORDER_CONFLICT", "订单缺少匹配的成功支付事实")
    existing = db.scalar(select(Settlement).where(Settlement.order_id == order.id))
    if existing:
        if (existing.payment_id, existing.courier_uid, existing.amount, existing.base_fee,
            existing.commission_bps, existing.pricing_version) != (
            payment.id, order.courier_uid, order.amount, order.base_fee, order.commission_bps, order.pricing_version):
            fail(409, "ORDER_CONFLICT", "原结算事实与请求冲突")
        return result(existing)
    income, commission = split_settlement(order.amount, order.base_fee, order.commission_bps)
    settlement_id = str(uuid4())
    settle_payment(db, payment, order.courier_uid, income, settlement_id)
    row = Settlement(id=settlement_id, order_id=order.id, payment_id=payment.id,
                     publisher_uid=order.publisher_uid, courier_uid=order.courier_uid,
                     amount=order.amount, base_fee=order.base_fee, commission_bps=order.commission_bps,
                     income=income, commission=commission, pricing_version=order.pricing_version)
    db.add(row)
    db.flush()
    return result(row)


def result(row):
    return {"settlementId": row.id, "orderId": row.order_id,
            "income": row.income, "commission": row.commission, "status": "succeeded"}
~~~~

### backend/app/modules/finance/README.md

D 说明：收货后结算的集成边界；118 行。

SHA-256（原始文件字节）：`d177759eb53b6bbc6e19b887e60fd8a0856869ebc01fd629bdbd810ec8191e3f`

~~~~markdown
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

## 发布者确认收货后的完成结算

A 在公共事件组件中注册 `order.completed` → consumer_name=`finance` →
`app.modules.finance.services.event_handlers.on_order_completed(db, event)`。
消费者使用投递方 Session，不自行提交。校验发布者已确认收货的 completed 订单、付款人、取件员、
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
公共投递器已注册此消费者；C 的发布者 confirm_receipt 入口将 delivered 改为 completed 并同事务发布 order.completed。取件员 confirm_delivery 只改为 delivered，不触发结算，资金保持冻结。C 的评价订阅独立投递、失败独立重试，不影响已成功的资金结算。

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
tests/test_events_integration.py。C 的生产业务入口已接入确认收货流程，联调应验证 delivered 不结算、completed 才结算；不能将测试内网关动作等同于完整的客户端操作。
~~~~

### backend/scripts/init_db.py

初始化入口：注册 C 模型；31 行。

SHA-256（原始文件字节）：`72ca611c24fe1cb863d8476aea2a89f0101c748c2dea7ea95ea04d17e579ebf6`

~~~~python
"""初始化本地开发数据库：按已注册的业务模型建表。

用法（任意目录执行）：
    .venv\\Scripts\\python backend/scripts/init_db.py

- create_all 只创建缺失的表，重复执行安全；
- create_all 不升级已有列；冻结字段须先按 finance/README.md 执行无损升级，
  不要删除含有团队账号、认证、订单和余额的共享数据库；
- 数据库文件已被 .gitignore 排除，不提交个人运行数据。
"""

import sys
from pathlib import Path

# 保证从任意目录执行时 backend 在 sys.path 上，app 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, engine  # noqa: E402
from app.modules.finance import models  # noqa: E402,F401 导入即注册模型到 Base.metadata
from app.events import models as event_models  # noqa: E402,F401
from app.modules.fulfillment import models as fulfillment_models  # noqa: E402,F401


def main() -> None:
    Base.metadata.create_all(engine)
    tables = sorted(Base.metadata.tables)
    print(f"建表完成，共 {len(tables)} 张：{', '.join(tables)}")


if __name__ == "__main__":
    main()
~~~~

### frontend/src/App.vue

公共导航：更新订单和评价页的服务标签；151 行。

SHA-256（原始文件字节）：`b3b47cec39b6318ba3e4824d8a634c9d596e48527a8aaf357e8cb6f03b66706f`

~~~~vue
<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { auth, restoreSession, logout } from "./services/session";
import {
  Package,
  LayoutDashboard,
  Compass,
  Plus,
  ClipboardList,
  Star,
  Wallet,
  ShieldCheck,
  ArrowUpRight,
  Menu,
  X,
  ChevronRight,
} from "@lucide/vue";
const route = useRoute();
const router = useRouter();
const exiting = ref(false);
const sessionError = ref("");
onMounted(() => restoreSession().catch(() => {}));
async function signOut() {
  exiting.value = true;
  sessionError.value = "";
  try {
    await logout();
    await router.push("/login");
  } catch (error) {
    sessionError.value = `退出失败：${error.message}，请重试。`;
  } finally {
    exiting.value = false;
  }
}
const open = ref(false);
const navigation = computed(() => [
  { to: "/", label: "首页概览", icon: LayoutDashboard },
  { to: "/tasks", label: "代取大厅", icon: Compass },
  { to: "/publish", label: "发布代取", icon: Plus },
  { to: "/orders", label: "我的订单", icon: ClipboardList },
  { to: "/reviews", label: "评价与信用", icon: Star },
  { to: "/wallet", label: "我的钱包", icon: Wallet },
  { to: "/verification", label: "学生认证", icon: ShieldCheck },
  ...(auth.user?.role === "admin"
    ? [{ to: "/admin/verification", label: "认证审核", icon: ShieldCheck }]
    : []),
]);
</script>
<template>
  <a class="skip" href="#main">跳到主要内容</a>
  <aside class="sidebar" :class="{ expanded: open }">
    <RouterLink to="/" class="brand" @click="open = false"
      ><span class="brand-icon"><Package :size="25" /></span
      ><span>校园速递<small>CAMPUS EXPRESS</small></span></RouterLink
    >
    <p class="nav-caption">校园服务</p>
    <nav aria-label="主导航">
      <RouterLink
        v-for="item in navigation"
        :key="item.to"
        :to="item.to"
        class="nav-link"
        :class="{ selected: route.path === item.to }"
        @click="open = false"
        ><component :is="item.icon" :size="19" />{{ item.label
        }}<ChevronRight
          v-if="route.path === item.to"
          :size="15"
          class="nav-arrow"
      /></RouterLink>
    </nav>
    <div class="sidebar-bottom">
      <div class="help-card">
        <span class="help-symbol">↗</span><strong>一份托付，一路安心</strong>
        <p>让顺路的善意，连接校园的你我。</p>
        <RouterLink to="/tasks"
          >去发现顺路任务 <ArrowUpRight :size="15"
        /></RouterLink>
      </div>
      <div class="sidebar-foot">
        <span class="dot"></span>校园互助 · 温暖同行
      </div>
    </div>
  </aside>
  <div v-if="open" class="overlay" @click="open = false"></div>
  <div class="workspace">
    <header class="topbar">
      <div class="topbar-left">
        <button
          class="icon-button mobile-menu"
          aria-label="切换导航"
          @click="open = !open"
        >
          <component :is="open ? X : Menu" :size="22" /></button
        ><span class="breadcrumb"
          >校园速递 <ChevronRight :size="14" />
          <strong>{{
            route.path === "/" ? "首页概览" : route.meta.title
          }}</strong></span
        >
      </div>
      <div class="topbar-right">
        <span class="preview-label">{{
          [
            "/login",
            "/register",
            "/verification",
            "/admin/verification",
          ].includes(route.path)
            ? "身份认证服务"
            : ["/publish", "/tasks"].includes(route.path)
              ? `${route.meta.title} · 订单服务`
              : ["/orders", "/reviews"].includes(route.path)
                ? `${route.meta.title} · 履约服务`
                : "界面预览 · 示例数据"
        }}</span>
        <template v-if="auth.user">
          <span class="user-link"
            ><span class="avatar">{{ auth.user.nickname?.[0] || "同" }}</span
            ><span>{{ auth.user.nickname || auth.user.phone }}</span></span
          >
          <button class="text-button" :disabled="exiting" @click="signOut">
            {{ exiting ? "正在退出…" : "退出登录" }}
          </button>
        </template>
        <template v-else-if="auth.status === 'unavailable'">
          <button class="text-button" @click="restoreSession().catch(() => {})">
            重试会话核验
          </button>
          <button class="text-button" :disabled="exiting" @click="signOut">
            退出登录
          </button>
        </template>
        <RouterLink v-else to="/login" class="user-link"
          ><span class="avatar">访</span><span>登录 / 注册</span></RouterLink
        >
      </div>
    </header>
    <main id="main" tabindex="-1">
      <p v-if="sessionError || auth.error" class="notice" role="alert">
        {{ sessionError || auth.error }}
      </p>
      <RouterView />
    </main>
    <footer class="page-footer">
      <span>校园速递 CAMPUS EXPRESS</span
      ><span>每一份托付，都值得认真对待。</span>
    </footer>
  </div>
</template>
~~~~

### frontend/src/features/orders/PublishView.vue

B 既有发布页：收货状态与详细地址提示文案；948 行。

SHA-256（原始文件字节）：`b01abee212f3890190e73b2d08a63427bb23b865df3ffb76acbd63a8e37bddad`

~~~~vue
<script setup>
import {
  computed,
  onMounted,
  onBeforeUnmount,
  reactive,
  ref,
  watch,
} from "vue";
import { useRoute, useRouter } from "vue-router";
import { Package, MapPin, ShieldCheck, Clock, X } from "@lucide/vue";
import PageHeading from "../../components/PageHeading.vue";
import { orderApi, sizeLabels, formatTime } from "./api";
const route = useRoute(),
  router = useRouter();
const freshDraft = () => ({
  company: "",
  code: "",
  stationId: "",
  deliveryAreaId: "",
  address: "",
  size: "small",
  weight: "1",
  time: "",
  tip: "0",
  note: "",
});
const draft = reactive(freshDraft());
const context = ref(null),
  locations = ref({ stations: [], deliveryAreas: [] });
const order = ref(null),
  recent = ref([]),
  fees = ref(null),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  quoteError = ref(""),
  submitted = ref(false),
  fields = ref({}),
  paymentDialog = ref(null);
let quoteTimer,
  pollTimer,
  generation = 0,
  orderGeneration = 0,
  disposed = false,
  requestKey = "",
  snapshot = "",
  reserveKey = "",
  payKey = "";
const canPublish = computed(() => context.value?.verified === true);
const money = (value) => (Number(value) / 100).toFixed(2);
const localTime = (value) =>
  new Date(`${value}${value.length === 16 ? ":00" : ""}+08:00`);
const errors = computed(() => {
  const result = { ...fields.value };
  for (const [key, label] of Object.entries({
    company: "快递公司",
    code: "取件码",
    stationId: "取件点",
    deliveryAreaId: "送达区域",
    address: "送达地址",
  }))
    if (!draft[key].trim()) result[key] = `请填写${label}`;
  if (
    !/^\d+(\.\d{1,2})?$/.test(String(draft.weight)) ||
    Number(draft.weight) <= 0 ||
    Number(draft.weight) > 30
  )
    result.weight = "重量需大于 0 且不超过 30 kg，最多两位小数";
  if (!/^\d+(\.\d{1,2})?$/.test(String(draft.tip)) || Number(draft.tip) > 999)
    result.tip = "请输入 0 至 999 元，最多两位小数";
  const time = localTime(draft.time).getTime();
  if (
    !Number.isFinite(time) ||
    time <= Date.now() ||
    time > Date.now() + 7 * 86400000
  )
    result.time = "请选择未来七天内的送达时间";
  return result;
});
const payload = () => ({
  company: draft.company.trim(),
  code: draft.code.trim(),
  stationId: draft.stationId,
  deliveryAreaId: draft.deliveryAreaId,
  address: draft.address.trim(),
  size: draft.size,
  weight: String(draft.weight),
  expectedAt: localTime(draft.time).toISOString(),
  tip: Math.round(Number(draft.tip) * 100),
  note: draft.note.trim(),
});
const statusLabels = {
  pending_payment: "待支付",
  pending: "待接单",
  accepted: "已接单",
  picking_up: "取件中",
  delivering: "配送中",
  delivered: "已送达，待确认收货",
  completed: "已完成",
  cancelled: "已取消",
};
const statusText = computed(() =>
  order.value?.paymentStatus === "paying"
    ? "支付处理中"
    : statusLabels[order.value?.status],
);
const feeDisplay = computed(() => order.value || fees.value);
const sections = computed(() => [
  {
    title: "取件信息",
    description: "让同学准确找到你的包裹",
    icon: Package,
    fields: [
      {
        key: "company",
        label: "快递公司",
        max: 30,
        placeholder: "例如：中通快递",
      },
      { key: "stationId", label: "取件点", options: locations.value.stations },
      {
        key: "code",
        label: "取件码",
        max: 50,
        placeholder: "请填写完整取件码",
      },
      {
        key: "size",
        label: "包裹规格",
        options: Object.entries(sizeLabels).map(([id, name]) => ({ id, name })),
      },
      {
        key: "weight",
        label: "包裹重量（kg）",
        type: "number",
        min: 0.01,
        limit: 30,
      },
    ],
  },
  {
    title: "送到哪里",
    description: "选择区域，再写清宿舍楼与门牌",
    icon: MapPin,
    fields: [
      {
        key: "deliveryAreaId",
        label: "送达区域",
        options: locations.value.deliveryAreas,
      },
      {
        key: "address",
        label: "详细送达地址",
        max: 200,
        placeholder: "例如：沁园 3 栋 302 室",
      },
      {
        key: "time",
        label: "期望送达时间",
        type: "datetime-local",
        help: "新加坡时间（UTC+8），未来七天内",
      },
      {
        key: "tip",
        label: "小费金额（元）",
        type: "number",
        min: 0,
        limit: 999,
        help: "可填 0 元",
      },
    ],
  },
]);
function report(cause) {
  error.value = cause.message;
  fields.value = { ...(cause.fields || {}) };
  if (fields.value.expectedAt) {
    fields.value.time = fields.value.expectedAt;
    delete fields.value.expectedAt;
  }
  if (cause.code === "VERIFICATION_REQUIRED" && context.value)
    context.value.verified = false;
}
async function loadOrder(id) {
  generation++;
  clearTimeout(quoteTimer);
  const version = ++orderGeneration;
  if (id !== order.value?.orderId) {
    reserveKey = "";
    payKey = "";
  }
  order.value = null;
  if (!id) return;
  busy.value = true;
  try {
    const result = await orderApi.detail(id);
    if (!disposed && version === orderGeneration) order.value = result;
  } catch (cause) {
    if (!disposed && version === orderGeneration) report(cause);
  } finally {
    if (version === orderGeneration) busy.value = false;
  }
}
function scheduleQuote() {
  clearTimeout(quoteTimer);
  const version = ++generation;
  fees.value = null;
  quoteError.value = "";
  if (!canPublish.value || order.value || Object.keys(errors.value).length)
    return;
  quoteTimer = setTimeout(async () => {
    try {
      const result = await orderApi.quote(payload());
      if (version === generation && !disposed) fees.value = result;
    } catch (cause) {
      if (version === generation && !disposed) quoteError.value = cause.message;
    }
  }, 350);
}
async function submit() {
  if (busy.value) return;
  submitted.value = true;
  fields.value = {};
  error.value = "";
  if (!canPublish.value || Object.keys(errors.value).length) return;
  busy.value = true;
  generation++;
  clearTimeout(quoteTimer);
  try {
    const body = payload(),
      serialized = JSON.stringify(body);
    if (snapshot !== serialized) {
      snapshot = serialized;
      requestKey = crypto.randomUUID();
    }
    order.value = await orderApi.create(body, requestKey);
    await router.replace({
      path: "/publish",
      query: { orderId: order.value.orderId },
    });
    recent.value = (await orderApi.mine()).items;
  } catch (cause) {
    report(cause);
  } finally {
    busy.value = false;
  }
}
async function pay() {
  busy.value = true;
  error.value = "";
  try {
    reserveKey ||= crypto.randomUUID();
    const reservation =
      order.value.paymentStatus === "paying" && order.value.paymentRequestId
        ? { paymentRequestId: order.value.paymentRequestId }
        : await orderApi.reservePayment(
            order.value.orderId,
            order.value.version,
            reserveKey,
          );
    order.value = { ...order.value, ...reservation };
    payKey ||= crypto.randomUUID();
    const result = await orderApi.prepay(
      order.value.orderId,
      reservation.paymentRequestId,
      payKey,
    );
    paymentDialog.value.close();
    if (result.status === "failed")
      error.value =
        result.code === "INSUFFICIENT_BALANCE"
          ? "余额不足，请到钱包充值，等待支付失败状态同步后重试。"
          : "支付未完成，请刷新状态后重试。";
    else error.value = "支付结果正在同步，请等待订单状态更新。";
    await refreshOrder();
  } catch (cause) {
    report(cause);
    await refreshOrder();
  } finally {
    busy.value = false;
  }
}
async function refreshOrder() {
  if (!order.value || disposed) return;
  try {
    const id = order.value.orderId,
      latest = await orderApi.detail(id);
    if (disposed || order.value?.orderId !== id) return;
    if (
      latest.paymentStatus === "unpaid" &&
      order.value.paymentStatus === "paying"
    ) {
      reserveKey = "";
      payKey = "";
    }
    order.value = latest;
    if (latest.paymentStatus === "paid") error.value = "";
  } catch (cause) {
    if (!disposed) report(cause);
  }
}
async function newOrder() {
  order.value = null;
  reserveKey = "";
  payKey = "";
  requestKey = "";
  snapshot = "";
  Object.assign(draft, freshDraft());
  submitted.value = false;
  fields.value = {};
  error.value = "";
  await router.replace("/publish");
  scheduleQuote();
}
watch(draft, () => {
  fields.value = {};
  scheduleQuote();
});
watch(
  () => route.query.orderId,
  (id) => {
    if (id !== order.value?.orderId)
      loadOrder(typeof id === "string" ? id : null);
  },
);
onMounted(async () => {
  try {
    locations.value = await orderApi.locations();
    context.value = await orderApi.context();
    recent.value = (await orderApi.mine()).items;
    if (route.query.orderId) await loadOrder(String(route.query.orderId));
  } catch (cause) {
    report(cause);
  } finally {
    loading.value = false;
  }
  pollTimer = setInterval(() => {
    if (
      !document.hidden &&
      !busy.value &&
      order.value?.paymentStatus === "paying"
    )
      refreshOrder();
  }, 3000);
});
onBeforeUnmount(() => {
  disposed = true;
  generation++;
  clearTimeout(quoteTimer);
  clearInterval(pollTimer);
});
</script>
<template>
  <PageHeading
    title="把取件这件事，交给顺路的同学"
    subtitle="填写取件信息，确认费用后再支付。"
    eyebrow="NEW REQUEST"
  />
  <div v-if="loading" class="notice" role="status">正在读取发布信息…</div>
  <div v-if="error" class="error-banner" role="alert">
    {{ error }}
    <button v-if="!context" class="text-button" @click="router.go(0)">
      重新加载
    </button>
  </div>
  <div v-if="context && !canPublish" class="notice identity-notice">
    <ShieldCheck :size="22" />
    <div>
      <strong>完成学生认证后，即可发布需求</strong>
      <p>认证让每一份校园托付更安心。</p>
    </div>
    <RouterLink class="primary-button" to="/verification?redirect=%2Fpublish"
      >去认证</RouterLink
    >
  </div>
  <div class="publish-layout">
    <form
      v-if="!order"
      class="panel publish-form"
      novalidate
      @submit.prevent="submit"
    >
      <fieldset :disabled="loading || busy || !canPublish">
        <section
          v-for="(section, index) in sections"
          :key="section.title"
          class="form-section"
        >
          <div class="section-title">
            <span class="section-icon"
              ><component :is="section.icon" :size="20"
            /></span>
            <div>
              <h2>{{ section.title }}</h2>
              <p>{{ section.description }}</p>
            </div>
          </div>
          <div class="form-grid">
            <label v-for="field in section.fields" :key="field.key"
              >{{ field.label }} <span class="required">*</span>
              <select
                :aria-label="field.label"
                v-if="field.options"
                v-model="draft[field.key]"
                :aria-invalid="submitted && !!errors[field.key]"
                :aria-describedby="field.key + '-help'"
              >
                <option value="" disabled>请选择</option>
                <option
                  v-for="option in field.options"
                  :key="option.id"
                  :value="option.id"
                >
                  {{ option.name }}
                </option>
              </select>
              <input
                :aria-label="field.label"
                v-else
                v-model="draft[field.key]"
                :type="field.type || 'text'"
                :maxlength="field.max"
                :min="field.min"
                :max="field.limit"
                :step="field.type === 'number' ? '0.01' : undefined"
                :placeholder="field.placeholder"
                :aria-invalid="submitted && !!errors[field.key]"
                :aria-describedby="field.key + '-help'"
              />
              <small
                :id="field.key + '-help'"
                :class="
                  submitted && errors[field.key] ? 'field-error' : 'field-hint'
                "
                >{{
                  submitted && errors[field.key]
                    ? errors[field.key]
                    : field.help
                }}</small
              >
            </label>
            <label v-if="index === 1" class="wide-field"
              >备注<textarea
                aria-label="备注"
                v-model="draft.note"
                maxlength="200"
                rows="3"
                placeholder="例如：包裹易碎，请轻拿轻放"
              /><small class="field-hint"
                >请勿填写手机号、取件码或门牌号。{{ draft.note.length }} /
                200</small
              ></label
            >
          </div>
        </section>
        <div class="submit-row">
          <span><ShieldCheck :size="16" />支付成功后，需求才会进入大厅</span
          ><button class="primary-button" type="submit">
            {{ busy ? "正在创建…" : "创建订单" }}
          </button>
        </div>
      </fieldset>
    </form>
    <section
      v-else
      class="panel order-result"
      aria-labelledby="order-result-title"
    >
      <div class="result-symbol"><Clock :size="28" /></div>
      <span class="soft-tag">{{ statusText }}</span>
      <h2 id="order-result-title">
        {{
          order.status === "pending_payment"
            ? "订单已创建，支付后发布"
            : "需求状态已更新"
        }}
      </h2>
      <p class="result-description">
        {{
          order.paymentStatus === "paying"
            ? "支付正在处理，请勿重复付款。超时后可回来继续查询。"
            : order.status === "pending"
              ? "需求已发布，等待同学接单。"
              : "取件信息与费用已保存。"
        }}
      </p>
      <dl class="order-details">
        <div>
          <dt>订单号</dt>
          <dd>{{ order.orderId }}</dd>
        </div>
        <div>
          <dt>快递公司</dt>
          <dd>{{ order.company }}</dd>
        </div>
        <div>
          <dt>取件信息</dt>
          <dd>{{ order.stationName }} / {{ order.code }}</dd>
        </div>
        <div>
          <dt>包裹规格</dt>
          <dd>{{ sizeLabels[order.size] }} / {{ order.weight }} kg</dd>
        </div>
        <div>
          <dt>送达地址</dt>
          <dd>{{ order.deliveryAreaName }} / {{ order.address }}</dd>
        </div>
        <div>
          <dt>期望送达</dt>
          <dd>{{ formatTime(order.expectedAt) }}</dd>
        </div>
        <div v-if="order.note">
          <dt>备注</dt>
          <dd>{{ order.note }}</dd>
        </div>
      </dl>
      <div class="result-actions">
        <button
          v-if="order.status === 'pending_payment'"
          class="primary-button"
          :disabled="busy"
          @click="paymentDialog.showModal()"
        >
          {{
            order.paymentStatus === "paying"
              ? "查询并继续支付"
              : "去支付 ¥" + money(order.amount)
          }}</button
        ><button class="outline-button" :disabled="busy" @click="refreshOrder">
          刷新状态</button
        ><button class="text-button" :disabled="busy" @click="newOrder">
          再发一单
        </button>
      </div>
    </section>
    <aside class="publish-aside">
      <section class="panel fee-panel">
        <h2>费用明细</h2>
        <div class="fee-line">
          <span>基础运费</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.baseFee) : "待计算"
          }}</strong>
        </div>
        <div class="fee-line">
          <span>给同学的小费</span
          ><strong>{{ feeDisplay ? "¥" + money(feeDisplay.tip) : "—" }}</strong>
        </div>
        <div class="fee-total">
          <span>合计</span
          ><strong>{{
            feeDisplay ? "¥" + money(feeDisplay.amount) : "—"
          }}</strong>
        </div>
        <p class="fee-help" role="status">
          {{
            order
              ? "费用已随订单保存。"
              : quoteError ||
                (fees
                  ? "创建订单时会重新报价并确认费用。"
                  : "填完必填信息后，自动计算费用。")
          }}
        </p>
        <p v-if="feeDisplay?.demo" class="demo-pricing">
          演示计费与模拟资金，不产生真实扣款。
        </p>
      </section>
      <section class="publish-guide">
        <ShieldCheck :size="21" />
        <h3>把托付说清楚</h3>
        <p>
          详细地址仅向你和接单后的同学提供。请在备注中避免填写敏感信息。
        </p>
      </section>
      <section v-if="recent.length" class="recent-orders">
        <h3>最近发布</h3>
        <RouterLink
          v-for="item in recent.slice(0, 5)"
          :key="item.orderId"
          :to="{ path: '/publish', query: { orderId: item.orderId } }"
          ><span
            >{{ item.company }}<small>{{ item.deliveryAreaName }}</small></span
          ><span
            >{{ statusLabels[item.status]
            }}<small>¥{{ money(item.amount) }}</small></span
          ></RouterLink
        >
      </section>
    </aside>
  </div>
  <dialog
    ref="paymentDialog"
    class="payment-dialog"
    aria-labelledby="payment-title"
    @cancel="busy && $event.preventDefault()"
  >
    <button
      class="icon-button close-payment"
      aria-label="关闭支付"
      :disabled="busy"
      @click="paymentDialog.close()"
    >
      <X :size="20" /></button
    ><span class="soft-tag">{{ order?.demo ? "模拟资金" : "订单支付" }}</span>
    <h2 id="payment-title">确认这份校园托付</h2>
    <p>使用钱包余额支付，付款结果以订单状态为准。</p>
    <strong class="payment-amount">¥{{ money(order?.amount || 0) }}</strong>
    <p v-if="error" role="alert">{{ error }}</p>
    <button class="primary-button" :disabled="busy" @click="pay">
      {{ busy ? "正在处理…" : "确认支付" }}</button
    ><RouterLink class="text-button later-button" to="/wallet"
      >前往钱包</RouterLink
    ><button
      class="text-button later-button"
      :disabled="busy"
      @click="paymentDialog.close()"
    >
      稍后支付
    </button>
  </dialog>
</template>
<style scoped>
.publish-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 290px;
  gap: 24px;
  align-items: start;
}
.publish-form fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.publish-form fieldset:disabled {
  opacity: 0.65;
}
.form-section {
  padding: 28px;
}
.form-section + .form-section {
  border-top: 1px solid var(--border);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.section-title h2,
.fee-panel h2 {
  font-size: 17px;
}
.section-title p {
  font-size: 11px;
  color: #6d7f74;
  margin-top: 3px;
}
.section-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  background: #edf4ef;
  border-radius: 10px;
  color: #547961;
}
.publish-form .form-grid {
  gap: 22px 20px;
}
.required {
  color: #9b654c;
}
.wide-field {
  grid-column: 1 / -1;
}
.field-hint,
.field-error {
  display: block;
  font-size: 11px;
  font-weight: 400;
  line-height: 1.7;
  margin-top: 6px;
}
.field-hint {
  color: #6f7e74;
}
.field-error,
.error-banner {
  color: #a33d32;
}
[aria-invalid="true"] {
  border-color: #bd685b;
}
textarea {
  resize: vertical;
  min-height: 85px;
}
textarea:focus-visible {
  outline: 3px solid #89b9a5;
  outline-offset: 3px;
}
.submit-row {
  padding: 22px 28px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.submit-row > span {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #657e69;
}
.primary-button:disabled {
  opacity: 0.6;
}
.publish-aside {
  position: sticky;
  top: 24px;
  min-width: 0;
}
.fee-panel {
  padding: 24px;
}
.fee-panel h2 {
  margin-bottom: 24px;
}
.fee-line,
.fee-total {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.fee-line {
  font-size: 12px;
  color: #68796e;
  margin-top: 17px;
}
.fee-line strong {
  font-weight: 500;
  color: #3a5145;
}
.fee-total {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px dashed #dbe4dd;
  font-size: 13px;
}
.fee-total strong {
  font-size: 30px;
  color: #a77a47;
  font-weight: 600;
}
.fee-help,
.demo-pricing {
  font-size: 11px;
  color: #6d7e71;
  margin-top: 16px;
}
.demo-pricing {
  border-top: 1px solid var(--border);
  padding-top: 15px;
}
.publish-guide {
  padding: 24px 6px;
  color: #67815d;
}
.publish-guide h3 {
  display: inline;
  margin-left: 8px;
  font-size: 13px;
}
.publish-guide p {
  margin-top: 12px;
  font-size: 12px;
  color: #6c7c6b;
}
.recent-orders {
  padding: 18px 0;
  border-top: 1px solid var(--border);
}
.recent-orders h3 {
  font-size: 13px;
  margin-bottom: 10px;
}
.recent-orders a {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 0;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
}
.recent-orders a > span:last-child {
  text-align: right;
  white-space: nowrap;
}
.recent-orders small {
  display: block;
  color: #738273;
  margin-top: 5px;
  font-size: 11px;
}
.identity-notice {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.identity-notice p {
  font-size: 11px;
}
.identity-notice .primary-button {
  margin-left: auto;
}
.error-banner {
  margin: 16px 0;
  padding: 14px 18px;
  background: #fff2ef;
  border: 1px solid #efd5cd;
  border-radius: 9px;
  font-size: 13px;
  line-height: 1.8;
}
.order-result {
  padding: 34px;
}
.result-symbol {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: #edf4ef;
  color: #547961;
  margin-bottom: 18px;
}
.order-result h2 {
  font-size: 22px;
  margin-top: 16px;
}
.result-description {
  font-size: 12px;
  color: #697e70;
  margin-top: 10px;
}
.order-details {
  margin: 28px 0;
}
.order-details div {
  display: grid;
  grid-template-columns: 85px minmax(0, 1fr);
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.8;
}
.order-details dt {
  color: #6d7e71;
}
.order-details dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.result-actions {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.payment-dialog {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 36px;
  width: min(430px, calc(100vw - 36px));
  color: #253c36;
}
.payment-dialog::backdrop {
  background: #12322480;
  backdrop-filter: blur(4px);
}
.close-payment {
  position: absolute;
  top: 12px;
  right: 12px;
}
.payment-dialog h2 {
  margin-top: 18px;
}
.payment-dialog p {
  font-size: 12px;
  color: #667b6b;
  margin-top: 12px;
}
.payment-amount {
  display: block;
  font-size: 38px;
  color: #a77a47;
  margin: 28px 0;
}
.payment-dialog > .primary-button {
  width: 100%;
}
.later-button {
  display: block;
  margin: 18px auto 0;
}
@media (max-width: 1100px) {
  .publish-layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .publish-aside {
    position: static;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }
  .recent-orders {
    grid-column: 1 / -1;
  }
}
@media (max-width: 640px) {
  .form-section {
    padding: 22px;
  }
  .submit-row {
    padding: 20px 22px;
    align-items: stretch;
    flex-direction: column;
  }
  .publish-aside {
    display: block;
  }
  .order-result {
    padding: 24px;
  }
  .order-result h2 {
    font-size: 20px;
  }
}
</style>
~~~~

### frontend/src/features/orders/HallTaskDialog.vue

B 既有大厅弹窗：仅提示接单后提供详细地址；191 行。

SHA-256（原始文件字节）：`b9ce3aa527e1d6ea8aac5f296b492470c0adc583aeef025d0b0665503088261e`

~~~~vue
<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { sizeLabels, formatTime } from "./api";
import { MapPin, Package, X } from "@lucide/vue";

const props = defineProps({
  task: Object,

  busy: Boolean,
  error: String,
});
const emit = defineEmits(["close", "accept"]);
const dialog = ref(null);
let previousFocus;
const money = (value) => (value / 100).toFixed(2);
watch(
  () => props.task,
  async (task) => {
    if (task) {
      if (!dialog.value?.open) previousFocus = document.activeElement;
      await nextTick();
      if (!dialog.value.open) dialog.value.showModal();
    } else if (dialog.value?.open) {
      dialog.value.close();
      previousFocus?.focus();
    }
  },
);
onBeforeUnmount(() => dialog.value?.close());
</script>
<template>
  <dialog
    ref="dialog"
    class="hall-dialog"
    aria-labelledby="hall-task-title"
    @cancel="busy ? $event.preventDefault() : emit('close')"
    @click.self="!busy && emit('close')"
  >
    <template v-if="task">
      <button
        class="icon-button close-detail"
        aria-label="关闭详情"
        :disabled="busy"
        @click="emit('close')"
      >
        <X :size="20" />
      </button>
      <span class="soft-tag"
        >{{ task.demo ? "演示订单" : "已支付" }} · 待接单</span
      >
      <h2 id="hall-task-title">{{ task.company }}代取需求</h2>
      <div class="detail-route">
        <p><MapPin :size="18" />{{ task.stationName }}</p>
        <span>送至</span>
        <p><MapPin :size="18" />{{ task.deliveryAreaName }}</p>
      </div>
      <dl>
        <div>
          <dt>包裹规格</dt>
          <dd>
            <Package :size="15" /> {{ sizeLabels[task.size] }} /
            {{ task.weight }} kg
          </dd>
        </div>
        <div>
          <dt>期望送达</dt>
          <dd>
            {{ formatTime(task.expectedAt) }}
          </dd>
        </div>
        <div>
          <dt>基础运费</dt>
          <dd>¥{{ money(task.baseFee) }}</dd>
        </div>
        <div>
          <dt>代取小费</dt>
          <dd class="detail-tip">¥{{ money(task.tip) }}</dd>
        </div>
        <div>
          <dt>备注</dt>
          <dd>{{ task.note || "暂无备注" }}</dd>
        </div>
      </dl>
      <p class="privacy-note">
        详细地址在接单后提供。请先确认取件点与送达区域是否顺路。
      </p>
      <button
        class="primary-button close-action"
        :disabled="busy"
        @click="emit('accept')"
      >
        {{ busy ? "正在接单…" : "确认接单" }}
      </button>
      <p v-if="error" class="dialog-error" role="alert">{{ error }}</p>
      <button
        class="outline-button close-action"
        :disabled="busy"
        @click="emit('close')"
      >
        知道了
      </button>
    </template>
  </dialog>
</template>
<style scoped>
.hall-dialog {
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
  width: min(540px, calc(100vw - 36px));
  max-height: calc(100dvh - 36px);
  overflow-y: auto;
  color: #253c36;
}
.hall-dialog::backdrop {
  background: #12322480;
  backdrop-filter: blur(4px);
}
.close-detail {
  position: absolute;
  top: 12px;
  right: 12px;
}
h2 {
  font-size: 22px;
  margin: 18px 0 22px;
}
.detail-route {
  background: #f4f8f3;
  padding: 18px;
  border-radius: 9px;
}
.detail-route p {
  display: flex;
  align-items: start;
  gap: 10px;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.detail-route p svg {
  margin-top: 4px;
  color: #6f9277;
}
.detail-route > span {
  display: block;
  margin: 7px 0 7px 28px;
  font-size: 11px;
  color: #728475;
}
dl {
  margin: 20px 0;
}
dl > div {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  line-height: 1.8;
}
dt {
  color: #718174;
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.detail-tip {
  color: #a77a47;
  font-weight: 650;
}
.privacy-note {
  font-size: 12px;
  color: #647a69;
}
.close-action {
  margin-top: 22px;
}
.dialog-error {
  color: #a33d32;
  font-size: 12px;
  margin-top: 16px;
}
@media (max-width: 640px) {
  .hall-dialog {
    padding: 24px;
  }
}
</style>
~~~~

### frontend/package.json

前端命令：加入 C 浏览器测试；31 行。

SHA-256（原始文件字节）：`06536d30be1ed85463ce7169e720023dc01e31972a20600798459c381542d7c2`

~~~~json
{
  "name": "campus-express-frontend",
  "version": "0.1.0",
  "description": "",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "playwright test",
    "test:f3": "playwright test --config playwright.f3.config.js",
    "test:orders": "playwright test --config playwright.f3.config.js",
    "test:identity": "playwright test --config playwright.identity.config.js",
    "test:verification": "playwright test --config playwright.verification.config.js",
    "test:fulfillment": "playwright test --config playwright.fulfillment.config.js"
  },
  "keywords": [],
  "author": "",
  "type": "module",
  "dependencies": {
    "@lucide/vue": "1.64.0",
    "vue": "3.5.44",
    "vue-router": "4.6.3"
  },
  "devDependencies": {
    "@playwright/test": "1.56.1",
    "@vitejs/plugin-vue": "6.0.2",
    "prettier": "3.6.2",
    "vite": "7.3.7"
  },
  "private": true
}
~~~~

### backend/tests/test_events_integration.py

公共事件集成测试：同时结算并开放评价；312 行。

SHA-256（原始文件字节）：`80957e2a478cd6d75c59db3a8b66c3ed1c3cf32026d470b8595a91864de6e93d`

~~~~python
"""真实资金/订单消费者联调；C 动作仅在测试内通过受控网关模拟。"""
import copy
import threading
import time
import unittest
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import delete, func, select, update
from app.common import iso, now
from app.events import publish
from app.events.models import Delivery, OutboxEvent
from app.events.service import Dispatcher, start_processor
from app.events.wiring import register_defaults
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import EventReceipt, handle
from app.modules.finance.models import Account, FinanceReceipt, Ledger, Payment, Refund, Settlement
import test_finance_payment


class EventIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture
        self.dispatcher = Dispatcher(self.fixture.sessions)
        register_defaults()

    def paid_order(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        self.dispatcher.dispatch_once()
        return body, payment

    def order(self, order_id):
        with self.fixture.sessions() as db:
            return OrderGateway.get_snapshot(db, order_id)

    def action(self, order_id, cancelled):
        with self.fixture.sessions.begin() as db:
            order = OrderGateway.get_snapshot(db, order_id)
            if cancelled:
                order = OrderGateway.transition(db, order, order.version, "cancel", "alice",
                    status="cancelled", refund_status="processing")
                payload = {"publisherUid": "alice", "paymentId": order.payment_id,
                    "amount": order.amount, "paid": True, "orderVersion": order.version}
            else:
                order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
                for status in ("picking_up", "delivering", "delivered"):
                    order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=status)
                order = OrderGateway.transition(db, order, order.version, "confirm_receipt", "alice", status="completed")
                payload = {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                    "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                    "pricingVersion": order.pricing_version, "orderVersion": order.version}
            event = {"eventId": str(uuid4()), "type": "order.cancelled" if cancelled else "order.completed",
                "occurredAt": iso(now()), "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                "version": order.version, "payload": payload}
            publish(db, event)
        return event

    def retry_now(self, event_id, consumer):
        with self.fixture.sessions.begin() as db:
            db.execute(update(Delivery).where(Delivery.event_id == event_id,
                Delivery.consumer == consumer).values(next_attempt_at=0))

    def test_payment_success_and_failure_automatically_update_orders_without_refreezing(self):
        body = self.helper.order()
        failed = self.helper.pay(body).json()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paying")
        self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual(self.order(body["orderId"]).payment_status, "unpaid")
        self.helper.fund()
        order = self.fixture.get("/api/orders/" + body["orderId"]).json()
        reserved = self.fixture.reserve(order).json()
        success_body = {"orderId": order["orderId"], "paymentRequestId": reserved["paymentRequestId"]}
        success = self.helper.pay(success_body).json()
        self.assertEqual(self.dispatcher.dispatch_once(), 1)
        self.assertEqual((self.order(order["orderId"]).status, self.order(order["orderId"]).payment_status), ("pending", "paid"))
        self.assertEqual(self.helper.pay(success_body).json(), success)
        self.assertEqual(self.helper.pay(body).json(), failed)
        self.assertEqual(self.helper.balances(), (465, 535))
        self.assertEqual(self.dispatcher.dispatch_once(), 0)

    def test_outbox_insert_failure_rolls_back_freeze_payment_ledger_and_http_dedup(self):
        self.helper.fund()
        body = self.helper.order()
        def interrupted(db, event):
            publish(db, event)
            raise RuntimeError("injected after outbox insert")
        with patch("app.modules.finance.services.payment.publish", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.helper.pay(body)
        self.assertEqual(self.helper.balances(), (1000, 0))
        with self.fixture.sessions() as db:
            for model in (OutboxEvent, Delivery, Payment):
                self.assertEqual(db.scalar(select(func.count()).select_from(model)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(Ledger.biz_type == "payment")), 0)
        self.assertEqual(self.helper.pay(body).json()["status"], "succeeded")

    def test_cancel_refund_event_and_order_confirmation_are_delivered_end_to_end(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], True)
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        order = self.order(body["orderId"])
        self.assertEqual((order.payment_status, order.refund_status), ("paid", "succeeded"))
        with self.fixture.sessions.begin() as db:
            publish(db, event)
            publish(db, {**event, "eventId": str(uuid4())})
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status != "succeeded")), 0)

    def test_refund_publish_failure_rolls_back_funds_receipt_and_downstream_outbox(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], True)
        def interrupted(db, data):
            publish(db, data)
            raise RuntimeError("injected before finance consumer ack")
        with patch("app.modules.finance.services.refund.publish", side_effect=interrupted):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(FinanceReceipt)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.type == "refund.succeeded")), 0)
            self.assertEqual(db.get(Delivery, (event["eventId"], "orders")).status, "succeeded")
        self.retry_now(event["eventId"], "finance")
        self.dispatcher.dispatch_once()
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.order(body["orderId"]).refund_status, "succeeded")

    def test_order_consumer_failure_rolls_back_state_and_receipt_then_retries_same_payment(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        def interrupted(db, event):
            handle(db, event)
            raise RuntimeError("injected after orders receipt")
        with patch.dict("app.events.service._handlers", {("payment.succeeded", "orders"): interrupted}):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paying")
        with self.fixture.sessions() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            self.assertEqual(db.scalar(select(func.count()).select_from(EventReceipt)), 0)
        self.retry_now(event_id, "orders")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_completion_settles_once_and_opens_reviews(self):
        body, _ = self.paid_order()
        event = self.action(body["orderId"], False)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            self.assertEqual(db.scalar(select(Settlement.commission)), 30)
            self.assertEqual(db.get(Delivery, (event["eventId"], "finance")).status, "succeeded")
            self.assertEqual(db.get(Delivery, (event["eventId"], "fulfillment")).status, "succeeded")
            from app.modules.fulfillment.models import ReviewOpening
            self.assertIsNotNone(db.get(ReviewOpening, body["orderId"]))
        self.retry_now(event["eventId"], "fulfillment")
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)
            self.assertEqual(db.get(Delivery, (event["eventId"], "finance")).attempts, 1)

    def test_legacy_payment_backfill_uses_original_id_and_marker_is_atomic(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery))
            db.execute(delete(OutboxEvent))
        with patch("app.events.service.publish", side_effect=RuntimeError("injected")):
            self.assertEqual(self.dispatcher.backfill_once(), 0)
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Payment, payment["paymentId"]).event_status, "pending")
        self.assertEqual(Dispatcher(self.fixture.sessions).backfill_once(), 1)
        self.assertEqual(self.dispatcher.backfill_once(), 0)
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(OutboxEvent.id)), event_id)
            self.assertEqual(db.get(Payment, payment["paymentId"]).event_status, "outbox_saved")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_legacy_refund_backfill_confirms_order_without_refunding_again(self):
        body, _ = self.paid_order()
        self.action(body["orderId"], True)
        # 先只消费取消的 finance 订阅，模拟旧版已退款但未向 B 投递。
        claim = None
        while True:
            current = self.dispatcher._claim(set())
            if current is None:
                break
            self.dispatcher._deliver(*current)
            if current[1] == "finance":
                claim = current
                break
        self.assertIsNotNone(claim)
        with self.fixture.sessions.begin() as db:
            row = db.scalar(select(Refund))
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery).where(Delivery.event_id == event_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.dispatcher.backfill_once(), 1)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).refund_status, "succeeded")
        self.assertEqual(self.helper.balances(), (1000, 0))

    def test_invalid_legacy_page_does_not_block_later_valid_events(self):
        self.helper.fund()
        body = self.helper.order()
        payment = self.helper.pay(body).json()
        with self.fixture.sessions.begin() as db:
            row = db.get(Payment, payment["paymentId"])
            event_id = row.event["eventId"]
            row.event_status = "pending"
            db.execute(delete(Delivery).where(Delivery.event_id == event_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.id == event_id))
            for i in range(20):
                db.add(Payment(id=f"!invalid-{i:02}", order_id=f"bad-order-{i}", request_id=f"bad-request-{i}",
                    payer_uid="invalid-legacy", amount=1, status="failed", code="INVALID_LEGACY", funds_status="none", event={}))
        self.assertEqual(self.dispatcher.backfill_once(), 0)
        self.assertEqual(self.dispatcher.backfill_once(), 1)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.order(body["orderId"]).payment_status, "paid")
        self.assertEqual(self.helper.balances(), (465, 535))

    def test_status_subscription_validates_facts_and_reads_latest_snapshot_for_old_versions(self):
        body, _ = self.paid_order()
        order = self.order(body["orderId"])
        with self.fixture.sessions.begin() as db:
            accepted = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            data = {"eventId": str(uuid4()), "type": "order.status_changed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": accepted.version,
                "payload": {"fromStatus": "pending", "status": "accepted", "courierUid": "bob", "orderVersion": accepted.version}}
            publish(db, data)
            latest = OrderGateway.transition(db, accepted, accepted.version, "fulfill", "bob", status="picking_up")
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            row = db.get(Delivery, (data["eventId"], "orders"))
            self.assertEqual(row.status, "succeeded")
            self.assertEqual(row.result["version"], latest.version)
            self.assertEqual(row.result["status"], "picking_up")
        future = copy.deepcopy(data)
        future["eventId"] = str(uuid4())
        future["version"] = future["payload"]["orderVersion"] = latest.version + 1
        with self.fixture.sessions.begin() as db:
            publish(db, future)
        self.dispatcher.dispatch_once()
        with self.fixture.sessions() as db:
            row = db.get(Delivery, (future["eventId"], "orders"))
            self.assertEqual(row.status, "pending")
            self.assertIn("ORDER_CONFLICT", row.last_error)


class RealIdentityWorkerTests(unittest.TestCase):
    def test_real_registration_verification_quote_payment_and_background_delivery(self):
        import test_verification
        import app.main as main
        from app.modules.finance.services.pricing import PricingService
        helper = test_verification.VerificationTests()
        helper.setUp()
        self.addCleanup(helper.tearDown)
        application = helper.submit().json()["applicationId"]
        self.assertEqual(helper.review(application).status_code, 200)
        main.app.state.pricing_service = PricingService()
        headers = lambda: {**helper.owner, "Idempotency-Key": str(uuid4())}
        recharge = helper.client.post("/api/wallet/recharge", json={"amount": 1000}, headers=headers())
        self.assertEqual(recharge.status_code, 201, recharge.text)
        confirmed = helper.client.post(f"/api/wallet/recharge/{recharge.json()['rechargeId']}/confirm", headers=headers())
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        draft = {"company": "中通快递", "code": "1-2-3456", "stationId": "station_cainiao", "deliveryAreaId": "zone_qinyuan",
            "size": "small", "weight": "1", "address": "测试楼101", "tip": 35, "expectedAt": iso(now() + timedelta(hours=2)), "note": ""}
        created = helper.client.post("/api/orders", json=draft, headers=headers())
        self.assertEqual(created.status_code, 201, created.text)
        order = created.json()
        reserved = helper.client.post(f"/api/orders/{order['orderId']}/payment-request", json={"version": order["version"]}, headers=headers())
        self.assertEqual(reserved.status_code, 200, reserved.text)
        paid = helper.client.post("/api/pay/prepay", json={"orderId": order["orderId"],
            "paymentRequestId": reserved.json()["paymentRequestId"]}, headers=headers())
        self.assertEqual(paid.status_code, 200, paid.text)
        processor = start_processor(helper.sessions)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                latest = helper.client.get(f"/api/orders/{order['orderId']}", headers=helper.owner).json()
                if latest["paymentStatus"] == "paid":
                    break
                threading.Event().wait(0.02)
            self.assertEqual((latest["status"], latest["paymentStatus"]), ("pending", "paid"))
            with helper.sessions() as db:
                account = db.get(Account, helper.uid)
                self.assertEqual((account.available_cent, account.frozen_cent), (765, 235))
        finally:
            processor.stop()
        self.assertFalse(processor.thread.is_alive())
~~~~

### README.md

团队说明中的 C 启动、测试及演示说明；142 行。

SHA-256（原始文件字节）：`8749dce5d5325d0e4247b6a06b8ec3527a601749b070e48e868d62f24b65691d`

~~~~markdown
# 校园快递代取管理系统

四人协作的课程项目。前端使用 Vue 3 + JavaScript + Vue Router + Vite，后端使用 Python + FastAPI，数据库采用 SQLAlchemy 2.0 + SQLite，无需单独安装数据库服务。

当前已实现 F1 注册登录与公共鉴权、F2 学生认证提交/审核/通知、B 的发布/大厅与订单公共能力、C 的接单履约/取消/评价信用、D 的模拟钱包/正式计价/支付冻结及退款结算，以及公共 outbox 和后台事件投递。C 的个人功能需求、验收标准及集成约束见[团队接口约定第 9.1 节](docs/团队接口约定.md#91-c-个人任务功能需求质量需求与开发约束)。首页部分卡片仍为示例数据，不代表真实订单。本项目不发送真实短信、不产生真实资金交易。

## 启动前端

安装 Node.js 22.12+（或 24 LTS），在项目根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

打开终端显示的地址，通常为 http://127.0.0.1:5173 。前端可独立预览，不需要启动后端。

```powershell
npm run build     # 生产构建
npm run preview   # 预览构建产物
npx playwright install chromium
npm test          # 浏览器冒烟测试，自动启动前端服务
npm run test:identity # 真实账号流程，临时数据库和受控模拟验证码
npm run test:orders   # F3/F4 测试，A/D 使用隔离测试替身
npm run test:verification # 真实账号提交、审核、通知与照片权限
npm run test:fulfillment  # C：真实账号接单、履约、收货确认、互评、信用与退款
```

## 启动后端

Python 3.11+，在项目根目录执行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.lock.txt
$env:CAMPUS_MODE = 'demo'
$env:CAMPUS_DEMO_CODE = '482917'
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload
```

健康检查：http://127.0.0.1:8000/api/health ，接口文档：http://127.0.0.1:8000/docs 。开发时 Vite 将 `/api` 代理到 `127.0.0.1:8000`，无需修改页面中的请求地址。

演示流程：打开 `/register`，输入虚构手机号并点击“获取验证码”，输入上述环境配置的验证码注册；注册成功后在登录页重新获取登录验证码并登录。验证码发送间隔 60 秒、有效期 300 秒、连续错误 5 次失效，成功使用后不能重用。模拟验证码仅由受控配置指定，不出现在接口响应或日志中；未配置时获取验证码返回 503。环境变量需在启动后端的同一 PowerShell 窗口设置，项目不会自动加载 `.env`。

登录凭证有效期 1800 秒，仅存 `sessionStorage`；退出只撤销当前会话。新账号认证状态为 `not_submitted`，可浏览大厅，但不能发布或接单；在 `/verification` 提交虚构姓名、学号和 JPEG/PNG 照片后进入待审核。照片不超过 5 MB、2500 万像素，服务端检查实际图片内容；照片仅由本人或审核管理员通过鉴权接口读取，不生成公开文件链接。驳回后可重提，历史保留；审核通过后身份准入立即生效。已认证用户可创建订单、充值并支付冻结；后台每秒投递支付事件，B 消费后订单由 paying 变为 paid/待接单，页面每 3 秒查询同步。故障期间保持 paying 并重试，不能直接改订单或重新冻结来绕过投递。

C 的完整演示使用两个已通过学生认证的账号：发布者发布并支付，取件员在 `/tasks` 接单后进入 `/orders`，依次开始取件、确认取件、确认送达。此时订单为 `delivered`（已送达、待收货），资金仍冻结、评价尚未开放；发布者确认收货（`confirm_receipt`）后变为 `completed`（已完成），才发布完结事件，由后台分别处理资金结算与评价开放，双方可在订单详情或 `/reviews` 各评价一次。C 的页面和履约接口不输入、不校验、不展示取件码。信用按本人作为取件员收到的最近 30 条评价计算，新人允许接单，未四舍五入均分低于 3.0 时限制新接单。发布者只能在接单前取消；已付款取消先显示退款处理中，实际到账由 D/B 的事件处理结果决定。订单和信用页每 10 秒刷新，离开页面停止。

管理员账号先通过注册页面创建，再由维护者在本机授予角色（不需要重新登录，下次请求立即生效）：

```powershell
.venv\Scripts\python backend/scripts/设置管理员.py --phone 13900003001 --grant
```

将手机号替换为已注册的虚构账号。使用 `--revoke` 替代 `--grant` 可恢复普通学生角色。管理员登录后进入 `/admin/verification`，查看申请和受控照片，再通过或填写理由驳回。学生在认证页查看结果、申请历史及通知；待审核时页面每 10 秒刷新一次，可手动刷新。普通注册请求不能设置管理员角色。

开发模式未设置 `CAMPUS_JWT_SECRET` 时，会在忽略提交的 `backend/.local/jwt-secret` 自动生成持久密钥；不要删除该文件，否则既有 Token 会失效。部署正式模式使用 `CAMPUS_MODE=production`，必须另行配置至少 32 字节的随机 `CAMPUS_JWT_SECRET`，并取消演示验证码配置。当前尚无真实短信提供者，正式模式不会启用模拟验证码。

后端测试：

```powershell
.venv\Scripts\python -m pip install -r backend/requirements-dev.txt
$env:PYTHONPATH = 'backend'
.venv\Scripts\python -m unittest discover -s backend/tests -v
```

测试使用临时 SQLite，不修改开发库；F1 测试包含 20 轮注册、登录、退出与旧凭证拒绝验证。F2 关键场景运行 20 轮，覆盖重复提交竞争、重复审核竞争、驳回重提、旧版本拒绝、通知去重及通知写入失败回滚。

C 后端场景位于 `backend/tests/test_fulfillment.py`，覆盖抢单与取消竞争、旧版本/重复提交、履约动作权限、送达与确认收货的边界、事件失败回滚、完结事件重试、双向评价和最近 30 条信用边界。验收应特别检查：取件员确认送达后不结算、不能评价；仅发布者确认收货后结算一次并开放评价。`test:fulfillment` 自动启动临时后端及 Vue 服务，使用真实 A/B/C/D 接口和虚构账号，不需要手动准备账号或修改开发库；只在测试环境预置审核管理员。

`requirements.txt` 声明后端直接依赖范围，`requirements.lock.txt` 固定当前验证的依赖版本。所有 Python 包安装在项目 `.venv` 中。前端版本由 `package-lock.json` 固定，使用 `npm ci` 安装。

本机若已安装 Edge，也可用 `$env:PW_BROWSER_CHANNEL='msedge'; npm test` 运行冒烟测试，无需另行下载 Chromium。

## 已有数据库升级冻结字段

保留现有账号、认证、订单、余额和流水，先停止服务并备份数据库；从 backend 目录依次运行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.finance.migrate_frozen
..\.venv\Scripts\python.exe scripts/init_db.py
```

仅全新数据库可直接启动建表；旧库 create_all 不会添加冻结列。重复升级不会重置冻结金额，不要删除共享数据库。细节见 [资金模块升级说明](backend/app/modules/finance/README.md)。

## 升级 C 的确认收货流程

已有开发库先停止服务并备份数据库，再从 backend 目录执行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.fulfillment.migrate_receipt
```

迁移仅将存在匹配旧 `order.completed` outbox 事实的历史 `delivered` 订单改为 `completed`，保留原版本、事件和资金记录，避免重新结算。新版没有完结事件的 `delivered` 订单保持待收货，由发布者正常确认；重复运行无变化，历史事实冲突时整批回滚。旧取件失败/锁定列兼容保留。全新数据库无需迁移；不要删库重建来升级。

B 的大厅投影只在同版本旧 `delivering→delivered` 事件具有完全匹配的历史完结 outbox 佐证时兼容状态重命名，原事件保持不变；其他事实冲突仍拒绝。C 重放旧成功请求时裁剪取件码和锁定字段，并兼容旧缺省 `code:null` 的请求摘要；新请求携带 `code` 仍返回 422，旧失败回执不会变成成功。

## 数据库接入

公共入口为 `backend/app/database.py`，提供 `engine`、`SessionLocal`、`Base` 和 `get_db`。SQLite 使用 Python 自带驱动，数据库默认路径为 `backend/campus_express.db`，可通过 `CAMPUS_DATABASE_PATH` 指定隔离数据库。

- 后续业务模型统一继承 `Base`，在各自模块中定义。
- 同步业务接口通过 `Depends(get_db)` 获取独立的 `Session`；后台任务使用 `with SessionLocal() as session:`，不要跨请求或任务共享会话。
- 写操作由业务编排层统一提交；公共鉴权读取会自动开启 Session 事务，业务层复用此事务，不能再次无条件 `session.begin()`。鉴权层与仓储不自行提交；会话退出时未提交的操作回滚。
- 应用启动时创建当前已注册模型的数据表；不会自动修改既有表结构。身份新增表不影响已有订单表，后续模型变更仍须明确迁移办法。
- 数据库文件及 SQLite 辅助文件已加入 `.gitignore`，不提交个人运行数据。后续表结构及迁移方案由团队统一后再实现。

连接与会话用法参考 [SQLAlchemy 会话文档](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) 和 [SQLite 方言文档](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)。

## 分工与目录

| 负责人 | 功能 | 前端目录 | 后端目录 |
| --- | --- | --- | --- |
| A（队长） | F1 注册登录、F2 实名认证 | `frontend/src/features/identity/` | `backend/app/modules/identity/` |
| B | F3 发布需求、F4 浏览筛选 | `frontend/src/features/orders/` | `backend/app/modules/orders/` |
| C | F5 接单履约、F6 评价信用 | `frontend/src/features/fulfillment/` | `backend/app/modules/fulfillment/` |
| D | F7 支付结算、F8 模拟钱包 | `frontend/src/features/finance/` | `backend/app/modules/finance/` |

公共导航在 `frontend/src/App.vue`，公共样式在 `src/styles.css`，路由在 `src/router/index.js`，通用组件在 `src/components/`。所有 HTTP 请求通过 `src/services/http.js`。示例数据仅存在于 `src/data/demo.js`，不代表服务端订单。

## 协作约定

开发前先阅读已由队长授权确定的 **v1.3 接口基线**：

- [团队接口约定](docs/团队接口约定.md)：统一记录所有模块接口、分工、权限、状态、事务、事件、联调与验收要求。

金额均为整数分；所有模块使用公共鉴权；数据库统一 SQLAlchemy 2.0 + SQLite。模拟实现也须遵守相同接口。发现问题先向队长反馈，修订契约后同步相关实现。

1. 拉取 `main` 后在个人功能分支开发，A 使用 `feature/A`；验证后通过 PR 合并到 `main`。主分支保留经过验证的基础代码。
2. 优先在自己模块目录实现业务；修改公共样式、路由或应用入口前先与队员沟通。新增组件样式建议使用 Vue 的 `scoped`。
3. 提交 PR 前运行前端构建及相关测试，由另一位队员评审。不要提交 `.idea`、`.venv`、密钥、真实证件和 `node_modules`。
4. API 使用 `/api` 前缀。身份接口沿用 `GET /api/auth/current`，认证状态沿用 `GET /api/auth/verify-status`。字段、枚举与错误返回按团队当前契约实现。
5. 接入 F1 后，各模块受保护请求须使用同一后端会话校验（JWT + sid）；前端路由与按钮限制不能代替服务端鉴权。只有认证已通过映射 `verified=true`，接单还需通过信用等业务检查。
6. 审核通知属于 F2；跨模块事件统一调用 `app.events.publish(db, event)`，与业务共用 Session 和事务。消费者、投递重试、历史补录与维护命令见[团队接口约定第 12 节](docs/团队接口约定.md#12-事件重试与幂等)。投递器随应用启动/停止，新增 outbox 和 C 模块表自动创建；历史支付和退款保留原 eventId 自动补录，不再次移动资金。完结事件分别交给 D 结算、C 开放评价；此前缺少 C 处理器而进入 dead 的投递，可按原 eventId 仅重试 fulfillment 订阅，已成功的结算不重复执行。
7. F1/F2 相关可靠性场景每类测试 20 次；本次界面冒烟测试不代替最终业务验收。

## 页面入口

`/` 首页，`/tasks` 大厅，`/publish` 发布，`/orders` 订单，`/reviews` 信用评价，`/wallet` 钱包，`/login` 登录，`/register` 注册，`/verification` 认证与通知，`/admin/verification` 管理员审核。审核列表、详情及操作均由后端校验管理员角色。

生产部署需将非 `/api` 的前端路由回退到 `index.html`，避免刷新子页面返回 404。框架用法可参考 [Vite 文档](https://vite.dev/guide/) 与 [Vue Router 文档](https://router.vuejs.org/guide/)。
~~~~

### docs/团队接口约定.md

个人功能、质量、约束和交付契约；426 行。

SHA-256（原始文件字节）：`b24c96e1c9c0717ffc85cd8a7cee8249f598265ef78f87f0115606b1a304adcb`

~~~~markdown
# 团队接口约定

版本：v1.3，C 履约流程于 2026-11-11 修订；原基线生效日期：2026-10-31。本文件统一记录四人团队的接口、权限、数据状态、对接边界、事件、事务、验收及协作规则，是唯一的团队协作约定入口。v1.3 落实公共 outbox 与投递器，接入支付、退款及结算消费者；C 现采用不验证取件码的履约操作，发布者确认收货后才完成、结算及开放评价，第 9.1 节记录个人任务与验收要求。合并和团队验收状态以 GitHub 及实际验收为准。

## 1. 项目范围与分工

四人共同开发校园快递代取管理系统，同一学生可在不同订单中担任委托方或取件员。

| 分组 | 功能 | 前后端模块目录标识 |
| --- | --- | --- |
| A（队长） | F1 注册登录、F2 实名认证，以及公共鉴权、错误与事件基础组件 | identity |
| B | F3 发布需求、F4 大厅与订单公共能力 | orders |
| C | F5 接单履约与取消资格、F6 评价信用 | fulfillment |
| D | F7 报价支付结算、F8 模拟钱包与资金幂等 | finance |

前端 Vue + JavaScript，后端 Python + FastAPI，数据访问 SQLAlchemy 2.0 + SQLite；单体部署，课程版使用模拟资金及验证码。数据库由原 MySQL 在架构阶段三调整，历史阶段一、二仍保留当时方案。

当前 main 已有前端骨架和公共数据库配置；业务实现及 PR 状态以代码和 GitHub 为准。Python 依赖仅装入项目 .venv；启动步骤见根目录 README.md。以下接口和协作要求适用于各模块未来提交，不能用界面演示成功替代服务端业务结果。

## 2. 公共规则

| 项目 | 已批准约定 |
| --- | --- |
| 路径 | /api 前缀，资源使用复数，小写与短横线命名 |
| 格式 | 默认 JSON；认证资料提交采用 multipart/form-data；字段 camelCase |
| 标识 | uid、orderId、applicationId 等统一为不透明字符串 |
| 金额 | 整数，单位分；amount=350 表示 3.50 元；不使用浮点数计算资金 |
| 时间 | ISO 8601，服务端带 Z 的 UTC 时间；页面转为 Asia/Singapore 展示 |
| 成功 | 直接返回对象，不套额外 data/code 层；创建成功 201，其余正常响应 200 |
| 空值 | 无值 null；空列表 []；不以空字符串代替对象或数组 |
| 分页 | page 从 1 开始，pageSize 默认 20、最大 100；返回 items、total、page、pageSize |

错误示例，detail 保留字符串，兼容当前前端请求工具：

```json
{"detail":"请先完成学生认证","code":"VERIFICATION_REQUIRED","fields":{}}
```

401 表示未登录/会话失效；403 表示已登录但权限不足或业务准入不满足；404 表示资源不可访问或不存在；409 表示重复、状态或版本冲突；422 表示参数校验失败；429 表示限频；500 不返回内部堆栈。前端依据 code 判断行为，不匹配中文文案。FastAPI 默认参数校验错误需由公共处理器转换为上述格式。

## 3. F1 注册登录与公共身份

凭证通过 Authorization: Bearer 传递。登录返回 accessToken、tokenType（bearer）、expiresIn（秒）；有效期 1800 秒，不新增刷新令牌。前端由 F1 统一将 accessToken 保存在 sessionStorage，内存状态用于当前页面；刷新时恢复后调用 current 核验，不信任缓存的角色或认证状态。禁止把凭证放在 URL、日志或 localStorage 中。

| 方法与路径 | 请求 / 响应 | 权限 |
| --- | --- | --- |
| POST /api/auth/codes | 输入 phone、purpose（register/login）；返回 retryAfter、expiresIn，不返回验证码 | 公开，限频 |
| POST /api/auth/register | 输入 phone、code；返回 uid，不自动登录 | 公开 |
| POST /api/auth/login | 输入 phone、code；返回 accessToken、tokenType、expiresIn | 公开 |
| POST /api/auth/logout | 撤销当前 sid；返回 loggedOut=true | 已登录 |
| GET /api/auth/current | 返回 uid、phone、nickname、role | 已登录本人 |

nickname 无值时为 null；role 为 student/admin。一个 student 可同时发单和接单，注册请求不可自行设置 admin。验证码按手机号和用途绑定：60 秒发送间隔，300 秒有效，连续错误 5 次或成功使用一次即失效。演示验证码来自受控开发配置，不混入正式响应。

队长统一提供后端鉴权依赖，校验 JWT 与 sid。其他模块不能只校验签名，也不能信任请求中的 uid、role、verified。单体内部直接复用身份服务/依赖，不要求后端通过 HTTP 调用自身。

F1 对接补充（2026-10-31，不改变 v1.1 协议）：公共入口为 `app.modules.identity.dependencies.current_identity` 与 `require_verified`，返回 uid、role、verified，并携本次请求已校验的 sid；`orders.integrations` 保留兼容导出，B/C/D 可继续使用。应用启动默认装配 `IdentityService`，只有隔离测试入口可替换它。角色和认证状态每次从数据库读取，不使用 JWT 内的角色或认证缓存。鉴权与业务共用请求 Session，鉴权只读不提交；读查询已触发事务时，业务编排须复用现有事务并统一提交/回滚，不再无条件调用 `db.begin()`。验证码错误次数须持久化后再返回 422，成功消费与注册/创建会话同事务保存。

模拟验证码仅在受控环境设置 `CAMPUS_DEMO_CODE` 且 `CAMPUS_MODE=demo` 时启用，不随接口返回，不打印到日志；未配置返回 503 DEPENDENCY_UNAVAILABLE。正式模式拒绝演示验证码配置。手机号已注册返回 409 ACCOUNT_EXISTS，发送间隔内重复获取返回 429 RATE_LIMITED，fields.retryAfter 为剩余秒数。客户端注册成功后另行请求登录验证码，注册不创建会话。签名密钥和本地数据库不提交仓库，具体启动方式见 README。

## 4. F2 学生实名认证

| status | 含义 | verified |
| --- | --- | --- |
| not_submitted | 未提交 | false |
| pending | 待审核 | false |
| approved | 已通过 | true |
| rejected | 已驳回 | false |

GET /api/auth/verify-status 返回示例：

```json
{"status":"rejected","verified":false,"rejectReason":"学号不清晰，请重新拍摄","applicationId":"ver_demo_001","version":1}
```

非驳回状态 rejectReason=null；未提交时 applicationId、version=null。其他模块只读取 verified，不根据照片或申请是否存在自行推断认证通过。

F2 接入补充（2026-10-31）：已提供状态查询、资料提交、申请历史、管理员列表/详情/审核、受控照片和审核通知。`identity_verification_states` 为 F2 维护的当前状态投影，无记录时返回 not_submitted；其他模块只读 verified，不另建认证事实来源。新申请版本为 1，审核成功变为 2；驳回重提创建新的 applicationId，版本重新从 1 开始，旧申请和审核记录保留。认证通过后不开放用户再次提交，已待审核或已通过时提交返回 409 VERIFICATION_CONFLICT。

姓名、学号先 trim，各为 1～30 字符；multipart 仅允许 realName、studentNo、photo 各一项。照片检查真实 JPEG/PNG 内容、完整性、5 MB 字节限制与 2500 万像素解码上限；文件名和声明 MIME 不作为类型依据。照片保存于独立受控表，列表/通知不加载原始照片，不暴露磁盘路径；照片响应 no-store，前端经公共请求工具读取 Blob，不把 Token 放进图片 URL。

申请历史与管理员列表返回 items/total/page/pageSize；items 含 applicationId、realName、脱敏 studentNo、status、version、rejectReason、createdAt、reviewedAt。管理员单条详情返回完整 studentNo，并增加 uid、reviewerUid；仅本人/管理员可读取照片，其他学生返回 404。通知 items 为 notificationId、applicationId、status、rejectReason、version、createdAt，仅本人可查。分页默认 20、最大 100，未声明参数返回 422。

审核输入 decision、rejectReason、version；通过时 rejectReason=null，驳回理由 1～500 个非空字符。申请与状态投影均须匹配 pending、applicationId 和 version 才能审核；过期/重复审核返回 409 VERIFICATION_CONFLICT。审核审计、状态更新和单条结果通知同事务写入，通知写入失败整笔回滚。申请表以用户待审核唯一索引防重复；审核记录、通知均以 applicationId 唯一约束防重。

管理员仅由维护者执行本地 `backend/scripts/设置管理员.py` 为已注册账号授予/撤销角色，不提供改角色的 HTTP 接口；命令与演示步骤见 README。角色变更下次请求立即生效。学生认证页待审核时每 10 秒刷新，离开页面停止；审核通知仍为本地同步记录，不依赖后续公共 outbox 投递器。

| 方法与路径 | 请求 / 响应 | 权限 |
| --- | --- | --- |
| POST /api/auth/verification-applications | multipart：realName、studentNo、photo；返回 applicationId、status、version | 已登录本人 |
| GET /api/auth/verification-applications | 本人申请历史，分页，展示学号脱敏 | 已登录本人 |
| GET /api/admin/verification-applications | 按 status 筛选，分页，不批量返回原始照片 | 审核管理员 |
| GET /api/admin/verification-applications/{applicationId} | 审核所需资料与版本，不返回物理文件路径 | 审核管理员 |
| POST /api/admin/verification-applications/{applicationId}/review | 输入 decision（approved/rejected）、rejectReason、version；返回申请 ID、状态和新版本 | 审核管理员 |
| GET /api/auth/verification-applications/{applicationId}/photo | 受控返回照片内容 | 本人或审核管理员 |
| GET /api/auth/verification-notifications | 本人审核结果通知，分页 | 已登录本人 |

照片随申请提交，JPEG/PNG、单张不超过 5 MB，后端检查真实类型。驳回理由不能只含空白。待审核不可修改或重复提交；驳回重提创建新申请编号，保留历史；过期/重复审核返回 409。审核、记录与通知同事务保存，后端确认提交成功才允许页面显示成功。

## 5. 前端会话行为

- 请求工具统一附加 Bearer 凭证，队友不各自读取和管理 Token。
- 401 清理当前凭证并跳转登录，redirect 仅允许本站路径；403 保留登录，根据 code 引导认证或显示权限不足。
- 主动退出先请求后端撤销 sid，再清理前端；退出失败显示明确错误，不声称后端已退出，可再次重试。页面关闭不代表 sid 被撤销，后端仍按到期时间失效。
- sessionStorage 可跨刷新保留、按标签页隔离，但仍可被脚本读取，不能防 XSS。禁止对用户内容使用未经处理的 v-html，不保存验证码、原始证件或服务端密钥。

## 6. 共用数据和所有权

| 能力 | 实现负责人 | 调用者 / 边界 |
| --- | --- | --- |
| 当前身份、认证、公共鉴权 | A | 所有模块使用同一后端依赖；不能信任客户端自报身份 |
| 订单主表、查询、报价快照、统一状态更新入口 | B | C 通过 B 的公共订单能力操作，不另建第二套订单主表 |
| 接单、履约、取消资格、评价、信用 | C | 编排规则并通过统一订单能力原子更新状态 |
| 报价、支付、退款、结算、钱包流水 | D | B 只读取报价和支付结果，不自行计算正式费用或写余额 |
| 事件表、投递器、重试公共组件 | A | B/C/D 各自实现生产与消费处理器；组件由 A 接入应用启动入口 |

B 的 OrderGateway 公共能力是订单所有者提供的同步命令入口，不是任意 ORM 写入权限。C 可调用该入口完成本模块的状态操作；支付、取消、完结等跨模块结果通知仍走持久化事件，不允许形成互相回调的写入循环。事件消费不能重新发布同一个事实来回触发。

### 标识、金额和字段

- 所有 ID 为字符串，长度 1～100；订单 ID 建议 UUID。客户端不依赖编码规则。
- 所有金额字段，包括 tip、baseFee、amount、balance、commission、income、refundAmount，均为 JSON 整数，单位分。禁止用 amount 表示元字符串；页面自行除以 100 展示。
- 未声明的请求字段拒绝，返回 422。金额拒绝字符串、小数、布尔值、NaN；枚举区分大小写。
- version 为正整数，从 1 开始，每次订单业务状态或支付控制状态变化增加 1。业务规则与版本必须在同一次条件更新中检查。
- 所有日期返回 UTC ISO 8601（Z），日期请求必须有时区；金额、时间、UID 不能由页面隐藏字段获得信任。

## 7. 订单状态和通用响应

| status | 中文 | 允许的后续状态 / 触发者 |
| --- | --- | --- |
| pending_payment | 待支付 | pending：B 消费支付成功；cancelled：C 取消，且 paymentStatus=unpaid |
| pending | 待接单 | accepted：C 接单；cancelled：C 取消 |
| accepted | 已接单 | picking_up：本单取件员开始取件 |
| picking_up | 取件中 | delivering：本单取件员确认已取件 |
| delivering | 配送中 | delivered：本单取件员确认送达 |
| delivered | 已送达、待收货 | completed：本单发布者确认收货；尚不结算、不开放评价 |
| completed | 已完成 | 终态；完结事件驱动结算和评价开放 |
| cancelled | 已取消 | 终态；已支付订单异步退款 |

paymentStatus：unpaid / paying / paid。退款不改写原支付成功事实；refundStatus 单独使用 none / processing / succeeded。订单不使用 locked 状态；历史 locked、pickupFailureCount、lockReason 列仅为数据库兼容保留，C 不再读取或写入这些列，不产生错码计数或锁单。

OrderSummary 固定字段：orderId、company、stationId、stationName、deliveryAreaId、deliveryAreaName、size、weight、expectedAt、note、baseFee、tip、amount、status、paymentStatus、refundStatus、version、createdAt、demo。

OrderDetail 在 Summary 上增加：publisherUid、courierUid（未接单为 null）、locked、pickupFailureCount，以及按权限裁剪的 address、code。发布者查看自己的订单时还可获得当前 paymentRequestId（无则 null）。这些是 B 的兼容详情字段；C 的履约响应不包含 code、locked、pickupFailureCount，C 页面不展示取件码或旧锁定信息，也不把它们用于履约校验。

### 资料可见范围

| 请求者 | 送达区域 | 完整 address | 取件 code |
| --- | --- | --- | --- |
| 已登录大厅浏览者、未接单同学 | 可见 | 不返回该字段 | 不返回该字段 |
| 本单发布者 | 可见 | 可见 | 可见 |
| 接单成功后的本单取件员 | 可见 | 可见 | 可见 |
| 无关用户直接请求订单详情 | 拒绝 404 | 不返回 | 不返回 |

大厅列表不返回 publisherUid、courierUid、paymentRequestId。备注在提交页提示勿填写手机号、取件码或门牌；接口字段裁剪不能保证用户自填备注不泄露隐私。

## 8. B：发布、查询与支付预占

除地点目录外，以下接口均要求已登录。创建和报价还要求最新 verified=true。创建、支付预占要求 Idempotency-Key，UUID 字符串建议值，同一用户与操作范围隔离。

### 地点目录及报价输入

GET /api/orders/locations → `{stations:[{id,name}],deliveryAreas:[{id,name}]}`。目录由 B 维护稳定 ID，D 的费率表引用这些 ID；不从自由文本猜测距离。

OrderDraft 必填：company（1～30 字符）、code（1～50）、stationId、deliveryAreaId（来自目录）、address（1～200）、size（small/medium/large）、weight（十进制字符串，kg，>0 且 ≤30，最多两位小数）、expectedAt（未来至 7 天内）、tip（整数 0～99900）。note 选填，默认空字符串，最长 200。字符串先 trim，必填项不能全空白。UID、总价和订单状态不允许作为创建输入。

| 方法与路径 | 输入 | 成功响应 | 责任 |
| --- | --- | --- | --- |
| POST /api/orders/quote | OrderDraft | Quote，200 | B 校验，调用 D PricingService.quote |
| POST /api/orders | OrderDraft + Idempotency-Key | OrderDetail，201，status=pending_payment | B 后端重新报价并保存快照 |
| GET /api/orders | scope=hall/mine，默认 hall；分页参数 | 通用分页对象 | B |
| GET /api/orders/{orderId} | 路径 ID | 本单相关用户的 OrderDetail | B，使用统一订单权限能力 |
| POST /api/orders/{orderId}/payment-request | `{version}` + Idempotency-Key | `{orderId,paymentRequestId,amount,paymentStatus,version}` | B，原子预占 |

Quote：quoteId、pricingVersion、baseFee、tip、amount、commissionRateBps、expiresAt、demo；quoteId 为服务端标识，不由前端用于覆盖价格。订单创建重新报价并保存 pricingVersion、baseFee、tip、amount、commissionRateBps 快照。报价预览 5 分钟有效；创建后费率变化不修改已有订单。

GET /api/orders 过滤参数：status（hall 仅 pending）、stationId、deliveryAreaId、tipMin、tipMax（均整数分，0～99900）、expectedFrom、expectedTo（含端点）。下限大于上限返回 422。mine 增加 role=publisher/courier/all，默认 all；缺省不过滤状态。page 默认 1、pageSize 默认 20、最大 100。排序：hall 为 expectedAt 升序、createdAt 降序、orderId 升序；mine 为 createdAt 降序、orderId 升序。hall 仅已支付待接单且非本人发布，允许未认证学生浏览。前端至多每 10 秒刷新可见大厅，离开页面停止轮询，失败不能伪装为零条任务。

### 支付与取消竞争

支付前由 B 的 payment-request 将 paymentStatus 从 unpaid 原子改为 paying，生成并保存 paymentRequestId、payerUid 和金额快照；只允许发布者对未取消的 pending_payment 订单执行。已有预占返回现有请求标识，不创建第二次支付预占。版本冲突返回 409。

前端随后携 orderId、paymentRequestId 调 D 的 /api/pay/prepay。D 必须通过只读 OrderGateway 验证预占、发布者和金额，不直接修改订单。B 消费 payment.succeeded 后将 paying→paid，pending_payment→pending；消费明确的 payment.failed 后 paying→unpaid。取消仅能在 unpaid 或已支付 pending 时成功；paying 返回 409 PAYMENT_IN_PROGRESS。

页面或请求超时不代表支付失败。不得根据超时直接解除预占；发布者重新进入页面可取回同一请求继续查询/重试。维护命令通过 D 的支付结果对账并重投事件；没有确定失败事实前保留 paying，避免已扣款后又允许取消。D 确定失败时也保存失败结果并发布事件。不得持有 SQLite 写事务等待网络或用户输入。

## 9. C：接单、履约、取消、评价和信用

| 方法与路径 | 输入 | 成功响应 / 条件 |
| --- | --- | --- |
| POST /api/orders/{orderId}/accept | `{version}` + Idempotency-Key | 裁剪 code 和旧锁定字段后的 OrderDetail；已认证、信用合格、非本人发布、已支付 pending |
| POST /api/orders/{orderId}/status | `{action,version}` + Idempotency-Key | 裁剪 code 和旧锁定字段后的 OrderDetail；取件配送动作仅本单取件员，收货动作仅本单发布者 |
| GET /api/orders/{orderId}/status | 无 | `{orderId,status,paymentStatus,refundStatus,version}`；本单相关用户 |
| POST /api/orders/{orderId}/cancel | `{version,reason}` + Idempotency-Key；reason 1～200 字符 | `{orderId,status,refundStatus,version}`；仅发布者、接单前 |
| POST /api/orders/{orderId}/reviews | `{rating,tags,comment}` | `{reviewId,orderId,createdAt}`，201 |
| GET /api/orders/{orderId}/reviews | 分页 | 本单相关用户的双方评价列表 |
| GET /api/users/{uid}/credit | 无 | `{uid,score,level,reviewCount,creditEligible}`；仅本人 |

action 固定 start_pickup / confirm_pickup / confirm_delivery / confirm_receipt，对应 accepted→picking_up→delivering→delivered→completed。前三个动作仅本单已认证取件员可执行；confirm_receipt 仅本单已登录发布者可执行，不重复要求学生认证。请求只允许 action、version，携带 code 或其他未声明字段返回 422。信用分在接单时检查，不因履约途中降分导致订单无法完成。

C 不输入、不校验、不展示取件码，confirm_pickup 直接确认取件事实。confirm_delivery 仅保存 delivered 状态及状态事件；不发布 order.completed。发布者执行 confirm_receipt 后，completed 状态、日志、状态事件、order.completed 和请求回执同事务提交，随后才由 D 结算、C 开放评价。旧锁定字段不参与新流程。

评价要求 completed 且完结事件已由 C 消费开放、本人为发布者或取件员、每人每单一次，提交后不可修改；数据库唯一约束为 (orderId,reviewerUid)。delivered 尚不满足评价条件。rating 为整数 1～5；tags 为字符串数组，最多 5 项、每项 1～20 字符；comment 默认空字符串，最多 500。禁止自己评价自己，目标用户由服务端根据订单确定。

初始信用：score=null、level=new、reviewCount=0、creditEligible=true。取得评价后，只统计该用户以取件员身份收到的最近 30 个订单评价，按评价 createdAt 降序、reviewId 降序；以未四舍五入均分决定准入。level：均分<3 为 restricted，3≤均分<4 为 normal，≥4 为 good。score 展示四舍五入两位小数；reviewCount 是本次均分采用的有效样本数，0～30。F5 结合认证等其他条件决定能否接单。

取消：pending_payment 且 unpaid 可取消且不退款；pending 且 paid 可取消并全额退 amount，refundStatus=processing；accepted 及后续不开放用户取消。接单与取消通过同一订单版本条件更新竞争，只能一次成功。取消写入 order.cancelled，D 消费后退款；B 消费 refund.succeeded 后才将 refundStatus 改为 succeeded。页面应显示“退款处理中”，不得在取消响应中提前显示已退款。本期不实现部分退款、违约金、已接单申诉或用户解锁。

### 9.1 C 个人任务：功能需求、质量需求与开发约束

责任人：成员 C（实际姓名待本人填写）。范围为 F5、F6，前端使用 Vue 3，后端使用 FastAPI。需求来源为《校园快递代取系统团队任务清单.xlsx》“任务清单”第 8、9 行；实现细节以本文 v1.3 基线为准。

#### 功能需求（功能描述）

| 编号 | 功能描述 | 输入、处理和输出 |
| --- | --- | --- |
| C-F5-01 | 接取已付款的他人需求 | 读取 F1 身份、F2 最新认证及 F6 信用，通过 B 的 OrderGateway 原子占用待接单订单，返回裁剪 code 后的详情；接单成功后可查看门牌地址。 |
| C-F5-02 | 按顺序完成取件与配送 | 本单取件员依次开始取件、确认取件、确认送达；状态为 accepted→picking_up→delivering→delivered。每次动作记录操作者、时间、前后状态及新版本，C 不处理取件码。 |
| C-F5-03 | 发布者确认收货后完成 | delivered 时仅本单发布者执行 confirm_receipt，进入 completed 并同事务发布完结事件；D 才结算、C 才开放评价。无关用户、取件员及跳步动作均拒绝。 |
| C-F5-04 | 接单前取消与退款展示 | 仅发布者取消未支付或已付款待接单订单。与接单、支付预占竞争时最多一个操作成功；已付款取消先显示退款处理中，再读取 D/B 的异步退款结果。 |
| C-F5-05 | 我的订单与进度查询 | Vue 页面按我发布/我接取和状态分页查询，展示详情、取件进度和待收货状态；可见页面每 10 秒刷新，离开停止。错误与空列表分开显示。历史通知接口保留兼容，当前页面不查询或展示。 |
| C-F6-01 | 确认收货完成后双方互评 | 发布者确认收货且订单完结事件消费成功后开放评价。每位参与人对另一方评价一次，包含 1～5 星、最多 5 个标签和 500 字以内评论，提交后不可修改。 |
| C-F6-02 | 信用展示与接单准入 | 实时查询本人以取件员身份收到的最近 30 单评价；展示均分、等级、样本数及接单资格。均分低于 3.0 拒绝接单，新人 score=null 且允许接单。 |
| C-F6-03 | 历史评价查询 | 仅本单参与人可分页查看双方评价，支持在订单详情及评价页查看；用户文字按普通文本渲染。 |

#### 质量需求（可执行验收标准）

| 编号 | 验收标准 |
| --- | --- |
| C-Q01 权限 | 未登录返回 401；未认证接单/取件配送返回 403 VERIFICATION_REQUIRED；仅本单取件员可开始/确认取件及送达，仅本单已登录发布者可确认收货；无关用户读取详情、通知或评价返回 404；信用仅本人可读。 |
| C-Q02 状态与竞争 | 两个取件员同时抢单仅一人成功；接单与取消互斥；旧版本及跳步动作返回 409，不能覆盖更新后的状态。paying 期间禁止取消。 |
| C-Q03 收货边界 | confirm_pickup 无额外输入即可推进；code 字段返回 422，C 页面和 C 履约响应不展示 code。delivered 时无完结事件、不结算、不开放评价；取件员不能代替发布者确认收货，跳步和旧版本被拒。 |
| C-Q04 原子性 | 注入事件保存失败时，订单状态、操作记录与幂等结果整体回滚；发布者确认收货时同时保存 completed、状态事件和完结事件，C 不直接改钱包。确认收货重试不重复完结或结算。 |
| C-Q05 评价 | 非 completed 或完结事件尚未消费时不能提交；本人每单仅一次，数据库唯一约束兜底；并发提交只能创建一条；整数星级、标签、字数及额外字段由服务端严格校验。 |
| C-Q06 信用 | 0 条时为新人；只计收到的取件员评价，最多 30 条，按 createdAt/reviewId 逆序；以未四舍五入均分判断 3.0、4.0 边界，展示两位小数。 |
| C-Q07 事件 | 重复完结事件及换 eventId 的同一完结事实不重复开放评价；消费与回执同事务。故障保留重试，恢复后可继续，不提前显示退款/结算成功。 |
| C-Q08 页面 | 桌面及 390px 手机页面可完成流程、无横向溢出；按钮提交时禁用；失败保留错误和重试入口；轮询正常情况下 30 秒内更新，离开页面停止；登录及认证沿用公共流程。 |

#### 开发约束（集成关系、接口契约）

| 对接方 | C 的依赖或提供能力 | 约束 |
| --- | --- | --- |
| A / F1、F2 | current_identity、require_verified；前端公共 request | 不信任客户端 UID、角色或认证状态；共用请求 Session、JWT/sid 校验，不建立独立登录体系。 |
| B / F3、F4 | 读取 OrderGateway.get_snapshot/related，调用 transition；提供 order.status_changed、order.cancelled | 不直接写订单 ORM，不另建订单主表；每次条件更新检查版本；大厅读取主表并消费刷新事件。 |
| C / F5、F6 | CreditService.get；order.completed 消费者 | 信用检查在接单时执行；履约不因之后降分受阻；完结消费者只开放评价并写回执，不回写履约或触发同一事件。 |
| D / F7 | order.completed、order.cancelled | C 仅发事实事件，由 D 结算/退款、B 接收退款结果；不调用钱包修改余额，不根据超时认定支付失败。 |
| 公共事件 | publish(db,event)，consumer_name=fulfillment | 状态、日志、幂等记录和 outbox 同事务；消费者不 commit，不另开会话；保留原 eventId 重投。 |

HTTP 路径、动作、输入、错误和响应沿用第 9 节。保留 `GET /api/orders/{orderId}/notifications?page=1&pageSize=20` 以查询历史履约通知，通知项为 notificationId、orderId、type、message、createdAt，仅本人接收的本单通知；新流程不产生错码锁单通知。评价列表项为 reviewId、orderId、reviewerUid、revieweeUid、reviewerRole、rating、tags、comment、createdAt；列表额外提供 reviewable，表示已 completed 且完结事件已消费。分页拒绝未声明字段、page<1、pageSize>100。所有时间为 UTC Z，金额为整数分。接单、履约（含收货）、取消共用 Idempotency-Key 机制，网络失败重试沿用原键；评价由每人每单唯一约束防重，重复提交返回 409 ALREADY_REVIEWED。

C 的表保存操作记录、历史履约通知、评价、评价开放标记和消费者回执，启动时无损建表，不修改既有列。为接入确认收货，本次同步扩展 B 的受控状态入口/状态筛选，以及 D 与 C 完结消费者的 completed 状态校验；沿用现有路径和事件结构。课程阶段历史文档和外部原始任务清单保留原样。

历史请求兼容由 C 的 replay_fulfillment 处理：匹配当前规范化摘要，或旧三种配送动作缺省 code:null 的摘要；成功回执返回前裁剪 code、locked、pickupFailureCount，失败仍重放原错误，不修改旧记录或重做业务。带明确旧码的摘要不会被无 code 请求命中，新提交携带 code 仍返回 422。B 既有大厅投影只对同版本旧 delivering→delivered 状态事件，且存在摘要、身份、金额、费率快照全部匹配的历史 order.completed outbox 时兼容 completed 状态重命名；其他同版本事实冲突仍拒绝，原事件不改写。

## 10. D：报价、支付、钱包与资金规则

报价是同一应用内的只读 PricingService.quote(draft)；不要求 HTTP 自调用。接口负责人 D，输入取件点 ID、送达区域 ID、规格、weight 和整数 tip；输出 Quote。不修改钱包或订单，也不信任前端 quoteId 对应金额。

演示地点 ID：station_cainiao（菜鸟驿站）、station_sf（顺丰服务点）；deliveryAreas：zone_qinyuan（沁园）、zone_zhuyuan（竹园）、zone_public（公共交接点）。演示路线费率（分）如下，不代表真实校园距离：

| stationId | zone_qinyuan | zone_zhuyuan | zone_public |
| --- | --- | --- | --- |
| station_cainiao | 200 | 300 | 200 |
| station_sf | 300 | 200 | 200 |

规格附加费 small=0、medium=100、large=300；重量前 1kg 包含在路线费中，之后按不足 1kg 进 1kg，每档加 100 分。baseFee=路线费+规格费+重量附加费，amount=baseFee+tip。费率版本 demo-20261030-v1，平台抽成 1000 bps（10%），仅对 baseFee 向下取整，小费全部归取件员：commission=baseFee×1000整除10000，income=amount-commission。B 保存抽成比例快照；D 按快照结算，不使用届时新费率。

除回调外以下接口须登录，所有资金写入须 Idempotency-Key；客户端不得提交 uid、余额、paymentStatus 或佣金覆盖值。

| 方法与路径 | 输入 | 成功响应 |
| --- | --- | --- |
| POST /api/pay/prepay | `{orderId,paymentRequestId}` | `{paymentId,orderId,amount,status,code}`；余额支付同步返回 succeeded（code=null）或确定失败的 failed 结果 |
| GET /api/pay/payments/{paymentId} | 无 | `{paymentId,orderId,amount,status,code}`；仅付款人，成功 code=null |
| GET /api/wallet | 无 | `{balance,currency:"CNY",demo:true}` |
| POST /api/wallet/recharge | `{amount}`，整数 1～100000 | `{rechargeId,amount,status:"pending",demo:true}`，201 |
| POST /api/wallet/recharge/{rechargeId}/confirm | 无 | `{rechargeId,amount,status:"succeeded"}`；演示专用且仅本人 |
| POST /api/wallet/withdraw | `{amount}`，整数 1～100000，不超过可用余额 | `{withdrawId,amount,status:"processing"}`，201 |
| GET /api/wallet/transactions | type 可选 recharge/payment/refund/settlement/withdrawal；分页 | 通用分页对象 |
| GET /api/wallet/withdrawals/{withdrawId} | 无 | `{withdrawId,amount,status}`；仅本人 |

支付确定失败 code 如 INSUFFICIENT_BALANCE；失败也保存 paymentId、paymentRequestId 与结果，发 payment.failed。相同支付预占只创建一个支付记录，重试返回原结果。重新付款必须由 B 在明确失败解锁后创建新的预占；成功支付不得换幂等键再扣款。

演示充值 confirm 在关闭演示模式时返回 404；真实回调路径本期不实现。提现先扣可用余额，流水与提现记录同事务写入；应用后台演示任务最早 3 秒后更新为 succeeded，重启后继续处理 processing 记录；失败记录为 failed，并且仅一次退回扣除金额。不涉及银行账号或真实资金。

交易流水字段：transactionId、type、direction（in/out）、amount、balanceAfter、orderId（无则 null）、referenceId、createdAt。用户余额初始为 0；演示数据通过受控初始化脚本生成，不提供匿名改余额接口。

钱包扣款必须使用条件更新保证 balance≥amount，不能先读余额再无条件覆盖；余额不得为负。WalletService.changeBalance 由 D 独占维护，支付、退款、充值、提现、结算都使用该能力，且余额、流水、业务记录、去重记录与应发事件在同一事务保存。取件员收益及平台佣金均须留账；退款退回全额到原发布者钱包，退款不收佣金。结算状态由 D 维护并可随订单详情通过只读接口聚合展示。

### v1.2 支付冻结与结算语义

本节取代 v1.1 对订单付款直接扣可用余额后等待结算的理解；充值、提现、金额单位、订单状态链及原有 HTTP 路径保持不变。

- D 维护可用余额与冻结余额，两者均不得为负。GET /api/wallet 的 balance 继续表示可用余额，不包含冻结资金；本次不新增钱包响应字段，如需向页面展示冻结余额，D 提交实际接口方案后再补充，不能静默改变 balance 含义。
- payment.succeeded 明确表示本次 orderId/paymentRequestId 对应的 amount 已成功冻结；可用余额减 amount、冻结余额增 amount，支付结果、资金流水/业务唯一记录与 payment.succeeded outbox 记录必须同事务提交。资金总额此时不变，不等于取件员或平台已经收到收入。
- 支付确定失败时余额与冻结额不变，保存 paymentId、失败结果和 payment.failed outbox 记录；数据库错误或提交失败不伪装为确定失败。相同 paymentRequestId 返回原结果，成功支付不能换键再次冻结。
- B 仍仅在消费 payment.succeeded 后将 paying→paid、pending_payment→pending。这里 paid 表示已冻结并取得履约资金保障，不表示已结算；原支付查询 status=succeeded 同样表示冻结成功。D 的同步成功响应只确认自身事务提交，不承诺 B 已收到事件。投递尚未完成时保留 paying，不超时释放预占或自动解冻。
- 收到有效 order.completed 后，D 校验 B 的只读订单快照与支付事实，在同一事务内扣除对应冻结额、按订单保存的 baseFee/tip/commissionRateBps/pricingVersion 快照入账。平台佣金仍为基础运费的 10% 向下取整，小费全部归取件员。结算不能再次扣发布者可用余额；发布者冻结额减少、取件员及平台入账必须同时成功或同时回滚。
- 取消范围不变：仅 unpaid 的 pending_payment 或 paid 的 pending 允许发布者取消，accepted 以后不开放用户取消。未支付取消无资金变化；已冻结付款取消由 D 消费 order.cancelled，一次性将全额 amount 从冻结额转回原发布者可用余额，不收佣金，并同事务保存退款事实与 refund.succeeded outbox 记录。B 消费该事件后将 refundStatus 改为 succeeded，原 paymentStatus 保留 paid。
- 冻结、解冻和结算都经 D 的唯一资金入口；按支付/订单建立永久业务唯一约束，并以条件更新校验对应资金状态与冻结额。订单资金只能结算或退款一次，两者互斥；换 eventId 或 HTTP 幂等键也不能再次移动资金。重复事件返回原结果，冲突事件保留诊断。
- 支付冻结的可用余额流出记 payment，取消解冻的可用余额流入记 refund；发布者的冻结资金消耗应有内部审计，不再次生成一笔可用余额扣款。取件员收益与平台佣金分别留账。校验所有账户的“可用+冻结”总额及平台账守恒。
- D 负责提供冻结余额字段和资金业务表的升级脚本，保留现有账号、认证、订单与钱包数据；create_all 不会自动给旧表加列，不能把删除共享数据库作为默认升级步骤。隔离测试可重新建临时数据库。

## 11. 内部能力接口（Python，不作为匿名 HTTP 入口）

所有能力由应用启动入口装配，使用同一 Base 和会话工厂；涉及同一次写入时共用 UnitOfWork。仓储内部不得自行 commit，编排用例统一提交。

| 能力 | 参数与结果 | 维护者 |
| --- | --- | --- |
| IdentityService.current / require_verified | 凭证→uid、role、最新认证状态 | A |
| OrderGateway.get_snapshot | orderId→发布者、取件员、状态、版本、金额和费率快照、支付预占及已成功 paymentId（无则 null） | B，D/C 仅按业务权限读取 |
| OrderGateway.transition | orderId、expectedVersion、expectedStatus、changes、actorUid、operation；条件更新成功返回新快照 | B；C 用于接单/履约/取消，禁止开放任意 changes 给 HTTP 请求 |
| PricingService.quote | 见第 10 节，返回 Quote | D |
| CreditService.get | uid→score、level、reviewCount、creditEligible | C；F5 内部可读取目标取件员 |
| WalletService.changeBalance | uid、direction、amount、businessType、businessId、共享事务→流水结果 | D 内部使用 |

C 的业务动作事务同时调用受控 OrderGateway 并写本模块的日志/事件。B 的支付事件消费者调用同一状态入口。只有白名单状态转换可执行；处理器负责校验权限、paymentStatus、refundStatus 和版本。不得将同一个事务拆成多次提交，不在 SQLite 写事务内发 HTTP。B/D 只读相互查询不构成相互写回。

## 12. 事件、重试与幂等

事件 envelope：`{eventId,type,occurredAt,orderId,aggregateType,aggregateId,version,payload}`。eventId 为 UUID，occurredAt 为 UTC；version 属于 aggregateType/aggregateId 指向的实体，支付版本不得与订单版本比较。事件只包含必要业务标识与金额，不携 Token、手机号、取件码或证件。

| type | 生产者 | 消费者 | payload 必填 |
| --- | --- | --- | --- |
| payment.succeeded | D | B | paymentId、paymentRequestId、payerUid、amount |
| payment.failed | D | B | paymentId、paymentRequestId、payerUid、amount、code |
| order.status_changed | C | B 大厅投影/刷新订阅 | fromStatus、status、courierUid（可 null）、orderVersion |
| order.completed | C | D 结算；C 开放评价 | publisherUid、courierUid、amount、baseFee、tip、commissionRateBps、pricingVersion、orderVersion |
| order.cancelled | C | D 退款；B 大厅投影 | publisherUid、paymentId（未支付 null）、amount、paid、orderVersion |
| refund.succeeded | D | B | refundId、paymentId、payerUid、amount |

事件与生产者业务变更同一事务写入 outbox；回滚不能留下待发事件。A 提供应用内每秒扫描的轻量投递任务，每批最多 20 条，不引入独立通知进程或消息队列。各消费者使用独立投递记录；一个成功不影响其他消费者的失败重试。SQLite 下以条件更新获得处理租约，租约 60 秒，进程重启后可回收过期租约。数据库中存 attempts、nextAttemptAt、lastError、status、leaseUntil，不只保存在内存中。

首次失败后延迟 1、5、30 秒重试，之后每 30 秒重试；连续失败 10 次进入 dead 状态，保留错误并提供维护命令按原 eventId 重试。业务校验失败与暂时不可用均保留诊断，不无限高速重试，不向客户端假报下游完成。原期望大厅 30 秒内刷新的指标在正常运行下验收；故障期间保留待办，不能宣称已满足时限。

消费者在本地事务内同时保存处理结果与唯一去重记录 (consumer,eventId)。资金消费还需业务唯一约束：paymentRequestId、订单支付成功、订单退款、订单结算、充值回调、提现回补分别至多一次；不能只依赖 eventId 或请求键，换键也不得重复入账。重复投递返回原结果。同事件 ID 内容不同视为冲突。订单状态投影忽略已处理的旧版本，版本有缺口时读取订单所有者快照校准；资金事件不能仅因版本较旧就丢弃，应检查对应业务事实。

HTTP Idempotency-Key 的范围为 (uid,operation,key)，持久化请求摘要、业务 ID 和结果；同键同请求返回原结果，同键不同内容返回 409 IDEMPOTENCY_CONFLICT。新建资源重试保留原 201 和资源 ID。请求仍在处理中返回 409 REQUEST_IN_PROGRESS。课程版保留幂等记录，不自动清理；永久业务唯一约束独立于这些记录。

F2 审核通知仍按既定方案同步写入，不改为异步。C 保留 GET /api/orders/{orderId}/notifications（仅本单相关用户，分页）查询历史履约通知；新流程不再生成错码锁单通知，不占用 F2 的认证通知接口。

### 公共 outbox 接入接口（v1.3，已实现）

公共实现位于 backend/app/events，应用启动时建表、装配已交付的消费者并启动每秒扫描任务，关闭应用时停止并等待本轮处理结束。支付成功/失败自动投递至 B；C 的取消、完结入口同事务发布事件，分别由 D 退款/结算、C 开放评价。不创建各模块独立投递器或匿名“支付成功”HTTP 接口。

```python
# 可直接从 app.events 导入；消费者在 app/events/wiring.py 集中装配。
def publish(db, event: dict) -> str: ...  # 返回 eventId；传入完整 envelope
def register_consumer(event_type, consumer_name, handler) -> None: ...
def dispatch_once(*, limit=20) -> int: ...  # 独立会话，返回本轮尝试投递数
def retry_dead(event_id, *, consumer_name=None) -> int: ...  # 保留原 eventId
```

- publish 只使用调用方已有 Session，校验 JSON envelope 并写入事件及各消费者的独立投递记录；不 commit、不新开会话、不调用消费者。资金冻结/失败结果与 publish 必须共用同一事务，outbox 保存失败则资金与支付记录一并回滚。同 eventId 同内容复用，同 eventId 不同内容返回冲突；重试不得重新生成事件标识。D 负责按业务唯一事实避免换 eventId 重发造成重复资金操作。
- event 为可 JSON 序列化的 camelCase 字典；occurredAt 是带 Z 的 UTC 字符串，version 是 payment/refund 等自身聚合的版本，不能使用订单版本替代。payment.succeeded payload 为 paymentId/paymentRequestId/payerUid/amount；payment.failed 另有非空 code。orderId 在 envelope 顶层，aggregateType=payment，aggregateId=paymentId；成功 payload 可不带 code，或明确为 null。
- register_consumer 由 A 在启动时装配，handler 签名为 handler(db, event) -> dict | None，同步调用、不可自行提交或另开会话。投递器阻止处理器调用 Session.commit；处理器也不得绕过 Session 另行提交连接。B 的 app.modules.orders.handlers.handle 处理三个资金事件，consumer_name 固定 orders；D 使用 finance，其退款/结算处理器已接收共享 db；C 使用 fulfillment。只允许登记本节事件表中的订阅组合，异步处理器不可注册。
- 投递方使用独立本地事务调用 handler；消费者业务变更、消费者去重回执和本次投递成功标记一起提交。异常整笔回滚，再用新事务记录失败并按既定 1/5/30 秒等策略重试。租约获取使用短事务，租约持有者以条件更新完成确认；公共组件避免旧处理者覆盖新租约结果。进程中断、重复投递、多消费者失败隔离和 dead 原 ID 重试均由 A 验证。
- 订阅关系以本节前的事件表为准，各消费者独立持久化记录；没有装配处理器不能静默标记已完成或丢掉事件。F2 认证通知不接公共 outbox。HTTP 调用超时、B 处理失败、投递器停止均不得使 D 重复冻结、提前解冻或把支付成功改成失败。
- D 保留支付/退款表内的原始事件作为业务审计，公共投递以 outbox 为准。新支付和退款已调用 publish，event_status=outbox_saved 只表示入箱，不表示下游完成。后台每轮最多补录 20 条历史 pending 支付/退款，复用原 eventId；补录与修改标记同事务，不重新冻结、退款或生成新事件。格式错误或入箱失败整笔回滚、保留 pending 并记录日志，修正后可继续补录。

实际装配与交付边界：

| 事件 | consumer_name | 当前处理器/边界 |
| --- | --- | --- |
| payment.succeeded / payment.failed / refund.succeeded | orders | orders.handlers.handle；订单状态、业务回执与投递确认同事务 |
| order.status_changed / order.cancelled | orders | orders.projections.handle；大厅直接读主表，校验事件并读取最新快照、保存刷新回执，不另建重复订单表 |
| order.cancelled | finance | finance.services.event_handlers.on_order_cancelled；全额解冻并在消费事务发布 refund.succeeded |
| order.completed | finance | finance.services.event_handlers.on_order_completed；按快照消耗冻结并结算 |
| order.completed | fulfillment | fulfillment.handlers.on_order_completed；核验完结事实、开放双方评价并保存去重回执，与投递确认同事务；不修改订单或资金 |

数据表为 outbox_events（完整不可变事件、摘要）和 outbox_deliveries（以 event_id/consumer 为联合主键）。后者使用 status、attempts、next_attempt_at、last_error、lease_until、lease_owner、result；时间为 UTC Unix 秒。pending→processing→succeeded，异常回到 pending，第 10 次失败转 dead。attempts 在每次获得租约时递增，中断后回收也计一次尝试；人工重试只重置 dead 订阅的尝试轮次，不改事件正文、ID、业务事实或其他订阅结果。每条消费前单独抢租约，确认前再次检查所有者及有效期；过期消费回滚，旧持有者不能覆盖新租约。数据库忙导致失败记录也无法提交时，原 processing 租约保留，过期后恢复。

C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.transition、保存本模块事实/HTTP 幂等结果，并调用 publish(db, 完整事件)，最后由业务用例提交一次。只有发布者确认收货使 delivered→completed 时发布 order.completed，取件员确认送达时只发状态事件；D/C 消费者均要求订单 completed。订单 version 和 payload.orderVersion 使用变更后快照的 version。order.completed 同时生成 finance、fulfillment 两条投递，当前均已在 wiring.py 装配；历史缺处理器而进入 dead 的记录可仅恢复 fulfillment，已成功的 finance 不重复结算。历史 delivered 先停服备份，再执行 `python -m app.modules.fulfillment.migrate_receipt`，仅将有匹配旧完结 outbox 事实的订单迁移为 completed；不改版本、不新建事件、不移动资金，事实冲突整批回滚。没有完结事件的新版 delivered 保持等待发布者收货。事件中不得携手机号、取件码、Token 或证件；公共校验拒绝约定外字段、非整数金额、未知事件类型和非规范 UUID，occurredAt 必须为带 Z 的 UTC 字符串。

维护命令从仓库根目录执行，使用与应用相同的 CAMPUS_DATABASE_PATH；已有冻结列升级要求不变。新增 outbox 表由应用启动或 scripts/init_db.py 无损创建，不删除旧数据：

```powershell
.venv\Scripts\python backend/scripts/维护事件.py --list
.venv\Scripts\python backend/scripts/维护事件.py --list --status pending --consumer fulfillment
.venv\Scripts\python backend/scripts/维护事件.py --retry <原eventId> --consumer fulfillment
.venv\Scripts\python backend/scripts/维护事件.py --once
.venv\Scripts\python backend/scripts/维护事件.py --backfill
```

--list 最多显示 100 条投递元信息，不输出事件正文；默认只看 dead。--once 返回尝试数，成功与否查看投递记录；--backfill 只补录原始事件。先修复处理器/业务冲突再重试，不能改正文规避同 ID 摘要冲突。

## 13. 失败语义与验收责任

422：VALIDATION_ERROR。401：AUTH_REQUIRED / SESSION_EXPIRED。403：FORBIDDEN / VERIFICATION_REQUIRED / CREDIT_TOO_LOW。404：NOT_FOUND。409：ORDER_CONFLICT / PAYMENT_IN_PROGRESS / IDEMPOTENCY_CONFLICT / REQUEST_IN_PROGRESS / ALREADY_REVIEWED。503：DEPENDENCY_UNAVAILABLE。字段错误示例 fields 为 `{tip:"必须为整数分且在允许范围内"}`，所有错误均返回 code、detail、fields；500 不暴露堆栈或 SQL。C 不再产生错码或锁单错误。

模拟模式由启动配置统一确定，返回 demo:true，界面明确提示。模拟用户通过受控演示配置创建；正式模式不得接受演示 Cookie、任意 uid 或演示确认接口。模拟与未来真实实现使用同一字段和单位，不准另造一套“元字符串”接口。

| 负责人 | PR 合并前必须验证 |
| --- | --- |
| A | sessionStorage 刷新恢复、401清理/403保留、sid撤销、角色和认证映射；投递失败、重启与多消费者重试 |
| B | 整数分输入输出、20/100分页、字段裁剪、服务器报价、支付预占与取消竞争、支付成功/失败事件幂等 |
| C | 两人抢单仅一人成功、接单与取消互斥、版本冲突、无额外输入确认取件、仅发布者收货后完成/结算/开放评价、并发收货一次完成、评价去重、新人信用 |
| D | 并发扣款不透支、重复支付/充值/退款/结算/提现回补不重复记账；事务失败回滚；中断后资金事件可重投 |

公共契约测试与各自功能测试均应通过。2026-10-30 对 B 的 PR #1 首轮审查中，原 22 项后端与 11 项浏览器测试通过，但仍发现整数分、错误结构和分页差异；这些问题需按本基线修正后再合并，最新 PR 状态以 GitHub 为准。实现中发现协议缺陷先向队长说明，再在本文记录版本与影响，不能静默改字段、单位或历史评审记录。

## 14. 代码协作与版本维护

- 团队仓库：https://github.com/suannai66/campus-express-manage 。从最新 main 创建个人功能分支，经 PR 评审及相关检查后合并。
- 优先修改所属模块；公共路由、样式、数据库模型、状态入口及事件基础组件变更先协调负责人，不分别实现同一能力。
- 不提交 .idea、.venv、node_modules、数据库文件、密钥或真实证件；演示使用虚构账号与证件样例。
- F1/F2 为分层单体并局部隔离验证码来源和核心仓储，其他辅助能力按既定设计复用；身份与认证只有单一事实来源。
- 接口变更先经队长确认，在本文件记录版本、改动点和受影响模块，随后同步代码、OpenAPI 和契约测试。所有协作相关补充继续写入本文件，不按个人或分组再拆文档。
- 需求和架构作业保留阶段历史事实。新增技术决策写入后续阶段，不追溯编造历史评审。
- 本文件仅定义开发与验收要求，不记录尚未执行的验收结果。F1/F2 可靠性场景每类测试 20 次。

### 版本记录

- v1.0（2026-10-30）：队长批准公共规则与 F1/F2。
- v1.1（2026-10-30）：队长批准凭证存储、初始信用、资料可见性、计价快照、取消退款及事件/资金责任，并授权确定 B/C/D 详细契约。
- 文档整理（2026-10-30）：合并原接口稿、业务契约和项目背景为本文件，统一维护入口；协议版本仍为 v1.1，协议语义不变。
- v1.2（2026-10-31）：明确订单支付成功为冻结成功，完结消耗冻结资金后按订单快照结算，允许范围内取消全额解冻；B 状态链和现有 HTTP 字段不变。确定 A 的公共 outbox 待实现 API、同事务写入与消费提交边界，影响 A/B/C/D；历史需求和架构阶段不追溯改写。
- v1.3（2026-10-31）：实现公共 outbox API、每消费者租约/重试/dead 恢复及历史支付/退款补录，接入 B/D 的现有处理器并明确 C 尚未交付的生产与消费边界；补充维护命令及实际字段，HTTP 契约和资金语义不变。
- v1.3 C 实现记录（2026-10-31）：补充第 9.1 节个人功能需求、验收标准及集成约束，实现 F5/F6 的 FastAPI/Vue 功能并装配评价消费者；补全通知和评价列表字段，不改变既有 HTTP 路径、订单状态链或资金语义。

### 相关定稿资料

- 团队任务清单：D:/study/School/term5/选修课/软件工程/校园快递代取系统团队任务清单.xlsx
- 需求分析：D:/study/School/term5/选修课/软件工程/需求分析/校园快递代取系统需求分析专项作业.docx
- 架构设计：D:/study/School/term5/选修课/软件工程/架构设计/校园快递代取系统软件架构设计专项作业.docx

上述文件为课程定稿资料，本接口约定不代替它们；历史初稿及架构备选稿不再保留于 docs。
~~~~

## 14. C 部分完整测试和测试配置
以下为当前文件完整内容；公共文件包含既有团队代码，其个人修改另见第 15 节。

### backend/tests/test_fulfillment.py

C 后端功能、并发、权限与收货边界测试；380 行。

SHA-256（原始文件字节）：`484ee1a3e804169637caed03821108ac05eb8ab4c41f6c8e50d0696524b2b6ff`

~~~~python
"""C 验收：真实订单/资金/outbox；身份替身仅在临时测试应用装配。"""
import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update, delete
import app.main as main
from app.common import Idempotency, fail, fingerprint, iso, now
from app.events.models import OutboxEvent, Delivery
from app.events.service import Dispatcher
from app.modules.finance.models import Account, Settlement, Refund
from app.modules.fulfillment.credit import CreditService
from app.modules.fulfillment.handlers import on_order_completed
from app.modules.fulfillment.models import OperationLog, Notification, Review, ReviewOpening, ConsumerReceipt
from app.modules.orders.integrations import Identity
from app.modules.orders.entities import Order
import test_finance_payment


class FulfillmentTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.fixture
        class DatabaseIdentity:
            def current(self, request, db):
                db.execute(select(Account.uid))  # 共用鉴权已开启的事务
                uid = request.headers.get("Authorization", "").removeprefix("Bearer ")
                if uid not in {"alice", "bob", "carol", "unverified"}:
                    fail(401, "AUTH_REQUIRED", "请先登录")
                return Identity(uid, verified=uid != "unverified")
        main.app.state.identity_service = DatabaseIdentity()
        self.dispatcher = Dispatcher(self.f.sessions)

    def post(self, order, endpoint, body=None, uid="bob", key=None):
        return self.f.client.post(f"/api/orders/{order['orderId']}/{endpoint}",
            json=body if body is not None else {"version": order["version"]}, headers=self.f.headers(uid, key))

    def latest(self, order, uid="alice"):
        return self.f.get(f"/api/orders/{order['orderId']}", uid).json()

    def paid(self):
        self.helper.fund()
        body = self.helper.order()
        self.assertEqual(self.helper.pay(body).json()["status"], "succeeded")
        self.dispatcher.dispatch_once()
        return self.latest(body)

    def advance(self, order, action, uid="bob", key=None, **extra):
        return self.post(order, "status", {"version": order["version"], "action": action, **extra}, uid, key)

    def pickup(self):
        order = self.paid()
        order = self.post(order, "accept").json()
        return self.advance(order, "start_pickup").json()

    def delivered(self):
        order = self.pickup()
        order = self.advance(order, "confirm_pickup").json()
        return self.advance(order, "confirm_delivery").json()

    def completed(self, dispatch=True):
        order = self.advance(self.delivered(), "confirm_receipt", uid="alice").json()
        if dispatch:
            self.dispatcher.dispatch_once()
        return order

    def count(self, model):
        with self.f.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def test_real_lifecycle_settlement_opening_logs_and_event_privacy(self):
        order = self.completed()
        self.assertEqual(order["status"], "completed")
        self.assertEqual(self.count(OperationLog), 5)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(Settlement), 1)
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.f.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            events = list(db.scalars(select(OutboxEvent).where(OutboxEvent.type.like("order.%"))))
            self.assertEqual(len(events), 6)
            serialized = json.dumps([e.body for e in events])
            for private in (self.f.body["code"], self.f.body["address"], "token", "phone"):
                self.assertNotIn(private, serialized)
            self.assertEqual(db.scalar(select(func.count()).select_from(Delivery).where(Delivery.status != "succeeded")), 0)
        self.assertEqual(self.post(order, "status", {"action": "confirm_delivery", "version": order["version"]}).status_code, 409)

    def test_admission_actor_privacy_and_strict_contract(self):
        order = self.paid()
        url = f"/api/orders/{order['orderId']}/accept"
        self.assertEqual(self.f.client.post(url, json={"version": order["version"]}).status_code, 401)
        for uid, code in (("alice", "FORBIDDEN"), ("unverified", "VERIFICATION_REQUIRED")):
            self.assertEqual(self.post(order, "accept", uid=uid).json()["code"], code)
        for body in ({"version": True}, {"version": "3"}, {"version": 0}, {"version": order["version"], "uid": "bob"}):
            self.assertEqual(self.post(order, "accept", body).status_code, 422)
        accepted = self.post(order, "accept").json()
        self.assertEqual(self.advance(accepted, "confirm_delivery").status_code, 409)
        self.assertEqual(self.advance(accepted, "confirm_receipt", uid="alice").status_code, 409)
        self.assertEqual(self.advance(accepted, "start_pickup", uid="alice").status_code, 403)
        self.assertEqual(self.post(accepted, "status", {"version": accepted["version"], "action": "start_pickup"}, uid="carol").status_code, 403)
        for body in ({"action": "start_pickup", "code": None}, {"action": "start_pickup", "code": "x"}, {"action": "confirm_pickup", "code": "x"}, {"action": "skip"}):
            self.assertEqual(self.post(accepted, "status", {"version": accepted["version"], **body}).status_code, 422)
        for endpoint in ("status", "reviews", "notifications"):
            self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/{endpoint}", "carol").status_code, 404)
        self.assertEqual(self.f.get("/api/users/bob/credit").status_code, 404)
        self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/reviews?page=0").status_code, 422)
        for query in ("page=1.0", "pageSize=101", "uid=alice"):
            self.assertEqual(self.f.get(f"/api/orders/{order['orderId']}/notifications?{query}").status_code, 422)

    def test_request_replay_survives_version_changes_and_key_conflict(self):
        order = self.paid()
        key = str(uuid4())
        first = self.post(order, "accept", key=key)
        self.assertEqual(first.status_code, 200)
        self.advance(first.json(), "start_pickup")
        self.assertEqual(self.post(order, "accept", key=key).json(), first.json())
        changed = self.post(order, "accept", {"version": order["version"] + 1}, key=key)
        self.assertEqual(changed.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)

    def test_pickup_requires_no_code_and_replays_without_old_locking(self):
        order = self.pickup()
        key = str(uuid4())
        first = self.advance(order, "confirm_pickup", key=key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "delivering")
        self.assertEqual(self.advance(order, "confirm_pickup", key=key).json(), first.json())
        for field in ("code", "pickupFailureCount", "locked"):
            self.assertNotIn(field, first.json())
        self.assertEqual(self.count(OperationLog), 3)
        self.assertEqual(self.count(Notification), 0)

    def test_legacy_accept_success_replay_hides_fields_without_rewriting_receipt(self):
        order = self.paid()
        key = str(uuid4())
        first = self.post(order, "accept", key=key).json()
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            original = {**row.result, "body": {**row.result["body"], "code": "legacy-code",
                "locked": True, "pickupFailureCount": 3}}
            row.result = original
        self.assertEqual(self.post(order, "accept", key=key).json(), first)
        self.assertEqual(self.count(OperationLog), 1)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(Idempotency).where(Idempotency.key == key)).result, original)

    def test_legacy_null_code_digest_replays_and_still_rejects_new_code_and_conflicts(self):
        order = self.post(self.paid(), "accept").json()
        key = str(uuid4())
        body = {"action": "start_pickup", "version": order["version"]}
        first = self.post(order, "status", body, key=key).json()
        old_digest = fingerprint({**body, "code": None})
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            row.digest = old_digest
            row.result = {**row.result, "body": {**row.result["body"], "code": "legacy-code",
                "locked": False, "pickupFailureCount": 0}}
        self.assertEqual(self.post(order, "status", body, key=key).json(), first)
        self.assertEqual(self.post(order, "status", {**body, "code": None}, key=key).status_code, 422)
        conflict = self.post(order, "status", {**body, "version": body["version"] + 1}, key=key)
        self.assertEqual(conflict.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)
        with self.f.sessions() as db:
            self.assertEqual(db.scalar(select(Idempotency).where(Idempotency.key == key)).digest, old_digest)

    def test_legacy_code_error_cannot_be_replayed_as_success_without_code(self):
        order = self.pickup()
        key = str(uuid4())
        body = {"action": "confirm_pickup", "version": order["version"]}
        original = {"statusCode": 422, "body": {"code": "PICKUP_CODE_MISMATCH",
            "detail": "旧版取件码错误", "fields": {"pickupFailureCount": 1, "locked": False}}}
        with self.f.sessions.begin() as db:
            db.add(Idempotency(uid="bob", operation=f"fulfillment:status:{order['orderId']}", key=key,
                digest=fingerprint({**body, "code": "wrong-code"}), result=original))
        response = self.post(order, "status", body, key=key)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(OperationLog), 2)
        with self.f.sessions.begin() as db:
            row = db.scalar(select(Idempotency).where(Idempotency.key == key))
            row.digest = fingerprint({**body, "code": None})
        response = self.post(order, "status", body, key=key)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), original["body"])
        self.assertEqual(self.count(OperationLog), 2)

    def test_delivery_waits_for_publisher_receipt_before_settlement_and_reviews(self):
        order = self.delivered()
        self.assertEqual(order["status"], "delivered")
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Settlement), 0)
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.helper.balances(), (465, 535))
        self.assertFalse(self.f.get(f"/api/orders/{order['orderId']}/reviews").json()["reviewable"])
        self.assertEqual(self.post(order, "reviews", {"rating": 5}, "alice").status_code, 409)
        self.assertEqual(self.advance(order, "confirm_receipt").status_code, 403)
        self.assertEqual(self.advance(order, "confirm_receipt", uid="carol").status_code, 403)
        key = str(uuid4())
        completed = self.advance(order, "confirm_receipt", uid="alice", key=key)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertEqual(self.advance(order, "confirm_receipt", uid="alice", key=key).json(), completed.json())
        self.assertEqual(self.advance(completed.json(), "confirm_receipt", uid="alice").status_code, 409)
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Settlement), 1)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.f.get("/api/orders?scope=mine&status=completed").json()["total"], 1)

    def test_two_couriers_compete_and_only_one_owns_order(self):
        for _ in range(5):
            order = self.paid()
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda uid: self.post(order, "accept", uid=uid), ("bob", "carol")))
            self.assertEqual(sorted(r.status_code for r in results), [200, 409])
            winner = next(uid for uid, r in zip(("bob", "carol"), results) if r.status_code == 200)
            self.assertEqual(self.latest(order)["courierUid"], winner)

    def test_accept_cancel_compete(self):
        for _ in range(5):
            order = self.paid()
            with ThreadPoolExecutor(2) as pool:
                a = pool.submit(self.post, order, "accept")
                b = pool.submit(self.post, order, "cancel", {"version": order["version"], "reason": "计划变更"}, "alice")
                results = [a.result(), b.result()]
            self.assertEqual(sorted(r.status_code for r in results), [200, 409])
            self.assertIn(self.latest(order)["status"], {"accepted", "cancelled"})

    def test_cancel_unpaid_paying_paid_and_refund_end_to_end(self):
        order = self.f.create().json()
        body = {"version": order["version"], "reason": "不再需要"}
        self.assertEqual(self.post(order, "cancel", body, "bob").status_code, 403)
        result = self.post(order, "cancel", body, "alice")
        self.assertEqual((result.json()["status"], result.json()["refundStatus"]), ("cancelled", "none"))
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(Refund), 0)
        paying = self.f.create().json()
        self.f.reserve(paying)
        paying = self.latest(paying)
        self.assertEqual(self.post(paying, "cancel", {"version": paying["version"], "reason": "变更"}, "alice").json()["code"], "PAYMENT_IN_PROGRESS")
        order = self.paid()
        cancelled = self.post(order, "cancel", {"version": order["version"], "reason": "计划变更"}, "alice").json()
        self.assertEqual(cancelled["refundStatus"], "processing")
        self.dispatcher.dispatch_once(); self.dispatcher.dispatch_once()
        self.assertEqual(self.latest(order)["refundStatus"], "succeeded")
        self.assertEqual(self.helper.balances(), (1000, 0))
        self.assertEqual(self.count(Refund), 1)

    def test_publish_failure_rolls_back_state_log_and_idempotency(self):
        order = self.paid()
        before = self.count(Idempotency)
        with patch("app.modules.fulfillment.service.publish", side_effect=RuntimeError("injected")):
            with self.assertRaises(RuntimeError): self.post(order, "accept")
        self.assertEqual(self.latest(order)["status"], "pending")
        self.assertEqual(self.count(OperationLog), 0)
        self.assertEqual(self.count(Idempotency), before)
        self.assertEqual(self.post(order, "accept").status_code, 200)

    def test_receipt_publish_failure_rolls_back_completion_and_retry(self):
        order = self.delivered()
        key = str(uuid4())
        before = self.count(Idempotency)
        from app.events import publish as original_publish
        def publish_until_completion(db, event):
            if event["type"] == "order.completed":
                raise RuntimeError("injected completion failure")
            return original_publish(db, event)
        with patch("app.modules.fulfillment.service.publish", side_effect=publish_until_completion):
            with self.assertRaises(RuntimeError):
                self.advance(order, "confirm_receipt", uid="alice", key=key)
        self.assertEqual(self.latest(order)["status"], "delivered")
        self.assertEqual(self.count(OperationLog), 4)
        self.assertEqual(self.count(Idempotency), before)
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.count(Settlement), 0)
        self.assertEqual(self.advance(order, "confirm_receipt", uid="alice", key=key).status_code, 200)

    def test_receipt_rejects_stale_version_and_concurrent_completion_once(self):
        order = self.delivered()
        self.assertEqual(self.post(order, "status", {"version": order["version"] - 1, "action": "confirm_receipt"}, "alice").status_code, 409)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.advance(order, "confirm_receipt", uid="alice"), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])
        self.dispatcher.dispatch_once()
        self.assertEqual(self.count(OperationLog), 5)
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(Settlement), 1)

    def test_review_waits_for_event_and_both_sides_submit_immutable_once(self):
        order = self.completed(dispatch=False)
        body = {"rating": 5, "tags": [" 准时 "], "comment": "<script>plain text</script>"}
        self.assertEqual(self.post(order, "reviews", body, "alice").status_code, 409)
        self.dispatcher.dispatch_once()
        for uid in ("alice", "bob"):
            self.assertEqual(self.post(order, "reviews", body, uid).status_code, 201)
            self.assertEqual(self.post(order, "reviews", body, uid).json()["code"], "ALREADY_REVIEWED")
        result = self.f.get(f"/api/orders/{order['orderId']}/reviews").json()
        self.assertTrue(result["reviewable"])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["tags"], ["准时"])
        self.assertEqual(self.f.get("/api/users/bob/credit", "bob").json()["reviewCount"], 1)
        self.assertEqual(self.f.get("/api/users/alice/credit").json()["reviewCount"], 0)
        self.assertEqual(self.f.client.patch(f"/api/orders/{order['orderId']}/reviews", json=body, headers=self.f.headers()).status_code, 405)

    def test_review_validation_and_concurrent_double_click(self):
        order = self.completed()
        for body in ({"rating": True}, {"rating": "5"}, {"rating": 1.5}, {"rating": 0}, {"rating": 6},
                     {"rating": 5, "tags": ["a"] * 6}, {"rating": 5, "tags": [" "]}, {"rating": 5, "tags": ["a" * 21]},
                     {"rating": 5, "comment": "a" * 501}, {"rating": 5, "revieweeUid": "alice"}):
            self.assertEqual(self.post(order, "reviews", body, "alice").status_code, 422)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.post(order, "reviews", {"rating": 4}, "alice"), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [201, 409])
        self.assertEqual(self.count(Review), 1)

    def test_completion_consumer_replay_conflict_rollback_and_retry(self):
        order = self.completed(dispatch=False)
        with self.f.sessions() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.type == "order.completed")).body
            on_order_completed(db, event)
            db.rollback()
        self.assertEqual(self.count(ReviewOpening), 0)
        with patch.dict("app.events.service._handlers", {("order.completed", "fulfillment"): lambda db, e: (_ for _ in ()).throw(RuntimeError("injected"))}):
            self.dispatcher.dispatch_once()
        self.assertEqual(self.count(ReviewOpening), 0)
        self.assertEqual(self.count(Settlement), 1)
        with self.f.sessions.begin() as db:
            db.execute(update(Delivery).where(Delivery.consumer == "fulfillment").values(next_attempt_at=0))
        self.dispatcher.dispatch_once()
        with self.f.sessions.begin() as db:
            first = on_order_completed(db, event)
            self.assertEqual(first, on_order_completed(db, event))
            self.assertEqual(first, on_order_completed(db, {**event, "eventId": str(uuid4())}))
        changed = copy.deepcopy(event)
        changed["payload"]["amount"] += 1
        changed["payload"]["tip"] += 1
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as caught: on_order_completed(db, changed)
            self.assertEqual(caught.exception.detail["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(ReviewOpening), 1)
        self.assertEqual(self.count(ConsumerReceipt), 2)

    def seed_review(self, db, rating, index=0, role="publisher", created=None):
        db.add(Review(id=f"{index:03}-{uuid4()}", order_id=str(uuid4()), reviewer_uid="alice", reviewee_uid="bob",
            reviewer_role=role, rating=rating, tags=[], comment="", created_at=created or iso(now())))

    def test_credit_newcomer_recent_thirty_roles_boundaries_and_rounding(self):
        with self.f.sessions() as db:
            self.assertEqual(CreditService.get(db, "bob"), {"uid": "bob", "score": None, "level": "new", "reviewCount": 0, "creditEligible": True})
        for ratings, expected in (([1, 5], (3.0, "normal", True)), ([3, 5], (4.0, "good", True)), ([2, 3, 3], (2.67, "restricted", False))):
            with self.f.sessions.begin() as db:
                db.execute(delete(Review))
                for i, rating in enumerate(ratings): self.seed_review(db, rating, i)
                self.seed_review(db, 1, 90, role="courier")
            with self.f.sessions() as db:
                result = CreditService.get(db, "bob")
                self.assertEqual((result["score"], result["level"], result["creditEligible"]), expected)
                self.assertEqual(result["reviewCount"], len(ratings))
        with self.f.sessions.begin() as db:
            db.execute(delete(Review))
            for i in range(31): self.seed_review(db, 1 if i == 0 else 5, i, created="2026-10-31T00:00:00.000000Z")
        with self.f.sessions() as db:
            self.assertEqual(CreditService.get(db, "bob")["score"], 5.0)
            self.assertEqual(CreditService.get(db, "bob")["reviewCount"], 30)

    def test_low_credit_blocks_new_acceptance_but_not_existing_fulfillment(self):
        order = self.pickup()
        with self.f.sessions.begin() as db: self.seed_review(db, 1)
        another = self.paid()
        self.assertEqual(self.post(another, "accept").json()["code"], "CREDIT_TOO_LOW")
        self.assertEqual(self.advance(order, "confirm_pickup").status_code, 200)


if __name__ == "__main__":
    unittest.main()
~~~~

### backend/tests/test_receipt_migration.py

旧流程无损迁移和冲突回滚测试；138 行。

SHA-256（原始文件字节）：`cca59dfdb8bb81dfb9d0302f567fea9e10dd1660cc82bba233c83f9f83ee26f6`

~~~~python
"""旧版完结语义升级：保留原事件、余额和新版待收货订单。"""
import copy
import unittest
from uuid import uuid4
from fastapi import HTTPException

from sqlalchemy import select, update

from app.common import iso, now
from app.events import publish
from app.events.models import Delivery, OutboxEvent
from app.events.service import Dispatcher
from app.modules.finance.models import Settlement
from app.modules.fulfillment.migrate_receipt import upgrade
from app.modules.fulfillment.models import ReviewOpening
from app.modules.orders.entities import Order
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.orders.projections import handle as refresh
import test_finance_payment


class ReceiptMigrationTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.f = self.helper.fixture

    def delivered(self, legacy=False):
        self.helper.fund()
        body = self.helper.order()
        payment_id = self.helper.pay(body).json()["paymentId"]
        from app.modules.finance.models import Payment
        with self.f.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
            order = OrderGateway.get_snapshot(db, body["orderId"])
            order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            for state in ("picking_up", "delivering", "delivered"):
                order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=state)
            event = {"eventId": str(uuid4()), "type": "order.completed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": order.version,
                "payload": {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
                    "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
                    "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
                    "orderVersion": order.version}}
            if legacy:
                publish(db, self.status_event(order))
                publish(db, event)
        return order, event

    def status_event(self, order):
        return {"eventId": str(uuid4()), "type": "order.status_changed", "occurredAt": iso(now()),
            "orderId": order.id, "aggregateType": "order", "aggregateId": order.id, "version": order.version,
            "payload": {"fromStatus": "delivering", "status": "delivered",
                "courierUid": order.courier_uid, "orderVersion": order.version}}

    def test_preserves_waiting_orders_and_retries_old_completion_once(self):
        old, event = self.delivered(legacy=True)
        waiting, _ = self.delivered()
        before = self.helper.balances()
        with self.f.sessions() as db:
            old_status = db.scalar(select(OutboxEvent.body).where(OutboxEvent.order_id == old.id,
                OutboxEvent.type == "order.status_changed"))
        self.assertEqual(upgrade(self.f.engine), 1)
        self.assertEqual(upgrade(self.f.engine), 0)
        self.assertEqual(self.helper.balances(), before)
        with self.f.sessions() as db:
            migrated = OrderGateway.get_snapshot(db, old.id)
            self.assertEqual((migrated.status, migrated.version), ("completed", old.version))
            self.assertEqual(db.get(Order, waiting.id).status, "delivered")
            self.assertEqual(db.get(OutboxEvent, event["eventId"]).body, event)
        dispatcher = Dispatcher(self.f.sessions)
        dispatcher.dispatch_once()
        dispatcher.dispatch_once()
        with self.f.sessions() as db:
            self.assertEqual(len(list(db.scalars(select(Settlement)))), 1)
            self.assertIsNotNone(db.get(ReviewOpening, old.id))
            self.assertIsNone(db.get(ReviewOpening, waiting.id))
            delivery = db.get(Delivery, (old_status["eventId"], "orders"))
            self.assertEqual(delivery.status, "succeeded")
            self.assertEqual(delivery.result["status"], "completed")
            self.assertEqual(delivery.result["version"], old.version)
            self.assertEqual(db.get(OutboxEvent, old_status["eventId"]).body, old_status)

    def test_current_version_conflict_without_completion_is_still_rejected(self):
        order, _ = self.delivered()
        with self.f.sessions.begin() as db:
            db.execute(update(Order).where(Order.id == order.id).values(status="completed"))
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                refresh(db, self.status_event(order))
            self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")

    def test_legacy_compatibility_rejects_different_status_courier_and_completion_facts(self):
        order, completion = self.delivered(legacy=True)
        self.assertEqual(upgrade(self.f.engine), 1)
        for changes in ({"fromStatus": "accepted"}, {"status": "accepted"}, {"courierUid": "carol"}):
            event = self.status_event(order)
            event["payload"].update(changes)
            with self.f.sessions() as db:
                with self.assertRaises(HTTPException) as raised:
                    refresh(db, event)
                self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")
        changed = copy.deepcopy(completion)
        changed["payload"]["courierUid"] = "carol"
        from app.events.schema import validate
        _, digest = validate(changed)
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == completion["eventId"]).values(
                body=changed, digest=digest))
        with self.f.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                refresh(db, self.status_event(order))
            self.assertEqual(raised.exception.detail["code"], "ORDER_CONFLICT")

    def test_conflicting_history_rolls_back_all_changes(self):
        first, _ = self.delivered(legacy=True)
        second, event = self.delivered(legacy=True)
        altered = copy.deepcopy(event)
        altered["payload"]["courierUid"] = "carol"
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == event["eventId"]).values(body=altered))
        with self.assertRaises(ValueError):
            upgrade(self.f.engine)
        with self.f.sessions() as db:
            self.assertEqual([db.get(Order, item.id).status for item in (first, second)], ["delivered", "delivered"])

    def test_changed_completion_metadata_digest_rolls_back_all_changes(self):
        first, _ = self.delivered(legacy=True)
        second, event = self.delivered(legacy=True)
        altered = {**event, "occurredAt": "2020-01-01T00:00:00.000000Z"}
        with self.f.sessions.begin() as db:
            db.execute(update(OutboxEvent).where(OutboxEvent.id == event["eventId"]).values(body=altered))
        with self.assertRaises(ValueError):
            upgrade(self.f.engine)
        with self.f.sessions() as db:
            self.assertEqual([db.get(Order, item.id).status for item in (first, second)], ["delivered", "delivered"])
~~~~

### backend/tests/test_finance_settlement.py

D 结算边界与幂等回归测试；161 行。

SHA-256（原始文件字节）：`5e4de4b440c1a827910b09bbf3fe62b34926955e384c8a72a8b334636c45826f`

~~~~python
"""结算金额守恒、快照费率、重复事件及退款互斥回归。"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func
import test_finance_payment
from app.common import iso, now
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.orders.entities import Order
from app.modules.finance.models import Account, Payment, Settlement, FinanceReceipt, Ledger
from app.modules.finance.services.event_handlers import on_order_completed
from app.modules.finance.core.fee_util import split_settlement


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture

    def completion(self):
        self.helper.fund()
        body = self.helper.order()
        payment_id = self.helper.pay(body).json()["paymentId"]
        with self.fixture.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
            order = OrderGateway.get_snapshot(db, body["orderId"])
            order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
            for status in ("picking_up", "delivering", "delivered"):
                order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=status)
            order = OrderGateway.transition(db, order, order.version, "confirm_receipt", "alice", status="completed")
        return {"eventId": str(uuid4()), "type": "order.completed", "occurredAt": iso(now()),
                "orderId": order.id, "aggregateType": "order", "aggregateId": order.id,
                "version": order.version,
                "payload": {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                            "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                            "pricingVersion": order.pricing_version, "orderVersion": order.version}}

    def consume(self, event):
        with self.fixture.sessions.begin() as db:
            return on_order_completed(db, event)

    def assert_balances(self):
        self.assertEqual(self.helper.balances(), (465, 0))
        with self.fixture.sessions() as db:
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            row = db.scalar(select(Settlement))
            self.assertEqual((row.amount, row.income, row.commission), (535, 505, 30))
            self.assertEqual(465 + 505 + row.commission, 1000)
            self.assertEqual(db.get(Payment, row.payment_id).funds_status, "settled")

    def test_settlement_once_and_ledger(self):
        event = self.completion()
        first = self.consume(event)
        self.assertEqual(self.consume(event), first)
        self.assertEqual(self.consume({**event, "eventId": str(uuid4())}), first)
        self.assert_balances()
        page = self.fixture.get("/api/wallet/transactions?type=settlement", "bob").json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["orderId"], event["orderId"])
        self.assertEqual(self.fixture.get("/api/wallet/transactions?type=settlement").json()["total"], 0)

    def test_uses_snapshot_not_current_rate(self):
        event = self.completion()
        with patch("app.modules.finance.config.COMMISSION_RATE_BPS", 9000):
            result = self.consume(event)
        self.assertEqual(result["commission"], 30)
        self.assert_balances()

    def test_rate_boundaries_and_floor(self):
        for amount, base, rate, expected in [(535, 300, 1000, (505, 30)),
                (101, 101, 1000, (91, 10)), (535, 300, 0, (535, 0)),
                (535, 300, 10000, (235, 300)), (300, 300, 10000, (0, 300))]:
            self.assertEqual(split_settlement(amount, base, rate), expected)

    def test_invalid_and_conflicting_events(self):
        event = self.completion()
        for field, bad in [("amount", True), ("commissionRateBps", "1000"), ("tip", 235.0)]:
            altered = copy.deepcopy(event)
            altered["payload"][field] = bad
            with self.assertRaises(HTTPException) as exc:
                self.consume(altered)
            self.assertEqual(exc.exception.status_code, 422)
        altered = copy.deepcopy(event)
        altered["payload"]["courierUid"] = "mallory"
        with self.assertRaises(HTTPException):
            self.consume(altered)
        self.consume(event)
        altered = copy.deepcopy(event)
        altered["payload"]["pricingVersion"] = "wrong"
        with self.assertRaises(HTTPException) as exc:
            self.consume(altered)
        self.assertEqual(exc.exception.status_code, 409)
        self.assert_balances()

    def test_refunded_funds_cannot_settle(self):
        event = self.completion()
        with self.fixture.sessions.begin() as db:
            db.scalar(select(Payment)).funds_status = "refunded"
        with self.assertRaises(HTTPException):
            self.consume(event)
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 0)

    def test_insufficient_frozen_rolls_payment_state_back(self):
        event = self.completion()
        with self.fixture.sessions.begin() as db:
            db.get(Account, "alice").frozen_cent = 100
        with self.assertRaises(HTTPException):
            self.consume(event)
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(Payment)).funds_status, "frozen")
            self.assertIsNone(db.get(Account, "bob"))

    def test_failure_after_income_rolls_everything_back(self):
        event = self.completion()
        from app.modules.finance.services import settlement
        original = settlement.settle_payment
        def fail(*args):
            original(*args)
            raise RuntimeError("injected after courier income")
        with patch.object(settlement, "settle_payment", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.consume(event)
        self.assertEqual(self.helper.balances(), (465, 535))
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(Payment)).funds_status, "frozen")
            self.assertIsNone(db.get(Account, "bob"))
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(FinanceReceipt)), 0)
        self.consume(event)
        self.assert_balances()

    def test_caller_controls_commit(self):
        event = self.completion()
        with self.fixture.sessions() as db:
            on_order_completed(db, event)
            db.rollback()
        self.assertEqual(self.helper.balances(), (465, 535))
        self.consume(event)
        self.assert_balances()

    def test_concurrent_events_settle_once(self):
        event = self.completion()
        def consume_one(event_id):
            try:
                return self.consume({**event, "eventId": event_id})
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(consume_one, [str(uuid4()), str(uuid4())]))
        self.consume(event)
        self.assert_balances()
        with self.fixture.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)
~~~~

### backend/tests/test_finance_trade_audit.py

跨订单资金守恒、退款结算竞争回归测试；164 行。

SHA-256（原始文件字节）：`d3d611ff8a7dcdd81a9ee5d287b6213ef0ef261387d4cdbb148f5abcfb14c11d`

~~~~python
"""跨订单资金隔离、退款与结算争用及共享库升级验收。"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func, inspect
import test_finance_payment
from app.common import now, iso
from app.database import Base
from app.modules.orders.gateway import OrderGateway
from app.modules.orders.handlers import handle
from app.modules.finance.models import Account, Payment, Settlement, Refund, Ledger
from app.modules.finance.core import wallet_core
from app.modules.finance.services.event_handlers import on_order_completed, on_order_cancelled


class TradeAuditTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_finance_payment.PaymentTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.fixture = self.helper.fixture

    def paid_order(self):
        body = self.helper.order()
        response = self.helper.pay(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "succeeded")
        payment_id = response.json()["paymentId"]
        with self.fixture.sessions.begin() as db:
            handle(db, db.get(Payment, payment_id).event)
        return body["orderId"], payment_id

    def event(self, order_id, cancel):
        with self.fixture.sessions.begin() as db:
            order = OrderGateway.get_snapshot(db, order_id)
            if cancel:
                order = OrderGateway.transition(db, order, order.version, "cancel", "alice",
                    status="cancelled", refund_status="processing")
                payload = {"publisherUid": "alice", "paymentId": order.payment_id,
                           "amount": order.amount, "paid": True, "orderVersion": order.version}
            else:
                order = OrderGateway.transition(db, order, order.version, "accept", "bob", status="accepted", courier_uid="bob")
                for state in ("picking_up", "delivering", "delivered"):
                    order = OrderGateway.transition(db, order, order.version, "fulfill", "bob", status=state)
                order = OrderGateway.transition(db, order, order.version, "confirm_receipt", "alice", status="completed")
                payload = {"publisherUid": "alice", "courierUid": "bob", "amount": order.amount,
                           "baseFee": order.base_fee, "tip": order.tip, "commissionRateBps": order.commission_bps,
                           "pricingVersion": order.pricing_version, "orderVersion": order.version}
        return {"eventId": str(uuid4()), "type": "order.cancelled" if cancel else "order.completed",
                "occurredAt": iso(now()), "orderId": order.id, "aggregateType": "order",
                "aggregateId": order.id, "version": order.version, "payload": payload}

    def consume(self, event):
        with self.fixture.sessions.begin() as db:
            return (on_order_cancelled if event["type"] == "order.cancelled" else on_order_completed)(db, event)

    def test_multi_order_refund_and_settlement_leave_third_order_frozen(self):
        self.helper.fund(3000)
        orders = [self.paid_order() for _ in range(3)]
        cancel = self.event(orders[0][0], True)
        complete = self.event(orders[1][0], False)
        self.consume(cancel)
        self.assertEqual(self.helper.balances(), (1930, 1070))
        self.consume(complete)
        self.assertEqual(self.helper.balances(), (1930, 535))
        for event in (cancel, complete):
            self.consume(event)
            self.consume({**event, "eventId": str(uuid4())})
        with self.fixture.sessions() as db:
            self.assertEqual([db.get(Payment, payment_id).funds_status for _, payment_id in orders],
                             ["refunded", "settled", "frozen"])
            self.assertEqual(db.get(Account, "bob").available_cent, 505)
            balances = db.scalar(select(func.sum(Account.available_cent + Account.frozen_cent)))
            commissions = db.scalar(select(func.sum(Settlement.commission)))
            self.assertEqual(balances + commissions, 3000)
            self.assertEqual(db.scalar(select(func.count()).select_from(Refund)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Settlement)), 1)

    def test_payment_id_of_other_order_cannot_release_its_funds(self):
        self.helper.fund(2000)
        first, second = self.paid_order(), self.paid_order()
        event = self.event(first[0], True)
        event["payload"]["paymentId"] = second[1]
        with self.assertRaises(HTTPException):
            self.consume(event)
        self.assertEqual(self.helper.balances(), (930, 1070))

    def test_future_versions_rejected_without_moving_money(self):
        self.helper.fund(2000)
        for cancel in (True, False):
            order_id, _ = self.paid_order()
            event = self.event(order_id, cancel)
            future = copy.deepcopy(event)
            future["version"] += 100
            future["payload"]["orderVersion"] = future["version"]
            before = self.helper.balances()
            with self.assertRaises(HTTPException) as exc:
                self.consume(future)
            self.assertEqual(exc.exception.status_code, 409)
            self.assertEqual(self.helper.balances(), before)
            self.consume(event)

    def test_refund_and_settlement_compete_for_same_payment_at_core_boundary(self):
        # 订单层终态本身互斥；领域层再验证并发消费者也只能消耗一次。
        self.helper.fund(1000)
        _, payment_id = self.paid_order()
        barrier = Barrier(2)
        def compete(operation):
            try:
                with self.fixture.sessions.begin() as db:
                    payment = db.get(Payment, payment_id)
                    barrier.wait(timeout=10)
                    if operation == "refund":
                        wallet_core.release_payment(db, payment, "race-refund")
                    else:
                        wallet_core.settle_payment(db, payment, "bob", 505, "race-settle")
                return operation
            except HTTPException as exc:
                self.assertEqual(exc.status_code, 409)
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(compete, ["refund", "settle"]))
        self.assertEqual(results.count("conflict"), 1)
        with self.fixture.sessions() as db:
            state = db.get(Payment, payment_id).funds_status
            self.assertIn(state, ("refunded", "settled"))
            self.assertEqual(db.get(Account, "alice").frozen_cent, 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Ledger).where(
                Ledger.biz_type.in_(["refund", "settlement"]))), 1)
            total = db.scalar(select(func.sum(Account.available_cent + Account.frozen_cent)))
            self.assertEqual(total + (30 if state == "settled" else 0), 1000)

    def test_old_shared_database_upgrade_preserves_all_existing_rows(self):
        from app.modules.finance.migrate_frozen import upgrade
        self.helper.fund(1000)
        self.fixture.create()
        from app.modules.identity.models import User, VerificationState, LoginSession
        with self.fixture.sessions.begin() as db:
            db.add(User(uid="audit-user", phone="13900009999", nickname="upgrade-test", role="student"))
            db.add(VerificationState(uid="audit-user", status="approved", application_id="audit-app", version=2))
            db.add(LoginSession(sid="audit-session", uid="audit-user", expires_at=2000000000, revoked=False))
        # 当前隔离库含订单/身份/钱包表；移除新表和冻结列，模拟本轮升级前的共享库。
        new_tables = [Settlement.__table__, Refund.__table__, Payment.__table__]
        with self.fixture.engine.begin() as db:
            for table in new_tables:
                table.drop(db)
            db.exec_driver_sql("ALTER TABLE account DROP COLUMN frozen_cent")
            tables = inspect(db).get_table_names()
            before = {name: db.exec_driver_sql('SELECT * FROM "' + name + '"').fetchall() for name in tables}
        self.assertTrue(upgrade(self.fixture.engine))
        Base.metadata.create_all(self.fixture.engine)
        self.assertFalse(upgrade(self.fixture.engine))
        with self.fixture.engine.connect() as db:
            for name, rows in before.items():
                query = "SELECT uid, available_cent, version, created_at FROM account" if name == "account" else 'SELECT * FROM "' + name + '"'
                self.assertEqual(db.exec_driver_sql(query).fetchall(), rows, name)
            self.assertEqual(db.exec_driver_sql("SELECT frozen_cent FROM account").scalar_one(), 0)
        # 升级后实际支付、退款，而非仅检查列存在。
        order_id, _ = self.paid_order()
        self.consume(self.event(order_id, True))
        self.assertEqual(self.helper.balances(), (1000, 0))
~~~~

### frontend/tests/fulfillment.spec.js

浏览器验收场景；353 行。

SHA-256（原始文件字节）：`a06a7769f7e2e7f8f4e178067d000eddb693b6f831eae5f68ac4642c66764455`

~~~~javascript
import { test, expect } from "@playwright/test";
import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";

const photo = readFileSync(
  new URL("./fixtures/学生证样例.png", import.meta.url),
);
const code = "482917";
let admin;
const auth = (user) => ({ Authorization: `Bearer ${user.accessToken}` });
const keyed = (user) => ({
  ...auth(user),
  "Idempotency-Key": crypto.randomUUID(),
});
async function login(request, phone) {
  expect(
    (
      await request.post("/api/auth/codes", {
        data: { phone, purpose: "login" },
      })
    ).status(),
  ).toBe(200);
  const response = await request.post("/api/auth/login", {
    data: { phone, code },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function student(request) {
  const phone = `139${String(randomInt(100000000)).padStart(8, "0")}`;
  await request.post("/api/auth/codes", {
    data: { phone, purpose: "register" },
  });
  expect(
    (
      await request.post("/api/auth/register", { data: { phone, code } })
    ).status(),
  ).toBe(201);
  const user = await login(request, phone);
  admin ||= await login(request, "13900999998");
  const submitted = await request.post("/api/auth/verification-applications", {
    headers: auth(user),
    multipart: {
      realName: "履约测试同学",
      studentNo: "2026001234",
      photo: { name: "sample.png", mimeType: "image/png", buffer: photo },
    },
  });
  expect(submitted.status()).toBe(201);
  const approved = await request.post(
    `/api/admin/verification-applications/${(await submitted.json()).applicationId}/review`,
    {
      headers: auth(admin),
      data: { decision: "approved", rejectReason: null, version: 1 },
    },
  );
  expect(approved.status()).toBe(200);
  return user;
}
async function create(request, user, paid = true) {
  const result = await request.post("/api/orders", {
    headers: keyed(user),
    data: {
      company: `测试快递${randomInt(100000)}`,
      code: "C-123456",
      stationId: "station_cainiao",
      deliveryAreaId: "zone_qinyuan",
      size: "small",
      weight: "1",
      address: "测试楼302",
      tip: 235,
      expectedAt: new Date(Date.now() + 3600000).toISOString(),
      note: "履约验收包裹",
    },
  });
  expect(result.status()).toBe(201);
  const order = await result.json();
  if (!paid) return order;
  const recharge = await request.post("/api/wallet/recharge", {
    headers: keyed(user),
    data: { amount: 1000 },
  });
  expect(recharge.status()).toBe(201);
  expect(
    (
      await request.post(
        `/api/wallet/recharge/${(await recharge.json()).rechargeId}/confirm`,
        { headers: keyed(user) },
      )
    ).status(),
  ).toBe(200);
  const reserve = await request.post(
    `/api/orders/${order.orderId}/payment-request`,
    { headers: keyed(user), data: { version: order.version } },
  );
  const payment = await request.post("/api/pay/prepay", {
    headers: keyed(user),
    data: {
      orderId: order.orderId,
      paymentRequestId: (await reserve.json()).paymentRequestId,
    },
  });
  expect((await payment.json()).status).toBe("succeeded");
  await expect
    .poll(async () => (await latest(request, order, user)).status)
    .toBe("pending");
  return latest(request, order, user);
}
async function latest(request, order, user) {
  return (
    await request.get(`/api/orders/${order.orderId}`, { headers: auth(user) })
  ).json();
}
async function accept(request, order, courier) {
  const result = await request.post(`/api/orders/${order.orderId}/accept`, {
    headers: keyed(courier),
    data: { version: order.version },
  });
  expect(result.status()).toBe(200);
  return result.json();
}
async function visit(page, user, path = "/orders") {
  await page.goto("/login");
  await page.evaluate(
    (token) => sessionStorage.setItem("accessToken", token),
    user.accessToken,
  );
  await page.goto(path);
}
async function open(page, order) {
  await page
    .locator(".order-card")
    .filter({ hasText: order.company })
    .getByRole("button")
    .click();
  await expect(page.getByRole("region", { name: "订单详情" })).toContainText(
    order.orderId,
  );
  await expect(page.locator(".detail dl")).toBeVisible();
}
test("真实账号：无取件码履约、发布者确认收货、双向评价与低分准入", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await create(request, publisher);
  await visit(page, courier, "/tasks");
  await page
    .locator(".task-card")
    .filter({ hasText: order.company })
    .getByRole("button", { name: "查看详情" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /确认接单/ })
    .click();
  await expect(page.getByText(/接单成功/)).toBeVisible();
  await page.goto("/orders");
  await open(page, order);
  await expect(page.locator(".detail")).not.toContainText("取件码");
  await expect(page.locator(".detail")).not.toContainText("C-123456");
  const commands = [];
  page.on("request", (req) => {
    if (req.url().endsWith(`/orders/${order.orderId}/status`))
      commands.push(req.postDataJSON());
  });
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await page.getByRole("button", { name: "确认取件", exact: true }).click();
  await page.getByRole("button", { name: "确认送达", exact: true }).click();
  await expect(page.locator(".detail")).toContainText("等待发布者确认收货");
  await expect(page.getByLabel("评分")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "确认收货", exact: true }),
  ).toHaveCount(0);
  expect((await latest(request, order, courier)).status).toBe("delivered");
  expect(commands.map((body) => body.action)).toEqual([
    "start_pickup",
    "confirm_pickup",
    "confirm_delivery",
  ]);
  expect(commands.every((body) => !("code" in body))).toBe(true);
  await visit(page, publisher);
  await open(page, order);
  await page.getByRole("button", { name: "确认收货", exact: true }).click();
  await expect(page.getByLabel("评分")).toBeVisible({ timeout: 15000 });
  expect((await latest(request, order, publisher)).status).toBe("completed");
  await page.getByLabel("评分").selectOption("1");
  await page.getByLabel("文字评价（可选）").fill("<script>仅作为文字</script>");
  await page.getByRole("button", { name: "提交评价" }).click();
  await expect(
    page.getByText("<script>仅作为文字</script>", { exact: true }),
  ).toBeVisible();
  await visit(page, courier, "/reviews");
  await expect(page.locator(".summary").first()).toContainText("限制接单");
  await open(page, order);
  await page.getByLabel("文字评价（可选）").fill("沟通顺畅");
  await page.getByRole("button", { name: "提交评价" }).click();
  await expect(page.getByText(/评价已提交/)).toBeVisible();
  await expect(page.locator(".review")).toHaveCount(2);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/c-reviews-desktop.png",
    fullPage: true,
  });
  const another = await create(request, publisher);
  await page.goto("/tasks");
  await page
    .locator(".task-card")
    .filter({ hasText: another.company })
    .getByRole("button", { name: "查看详情" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /确认接单/ })
    .click();
  await expect(page.getByRole("dialog")).toContainText("信用分低于");
});

test("390px 手机：无需输入取件码，送达待收货且无横向溢出", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await accept(
    request,
    await create(request, publisher),
    courier,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await visit(page, courier);
  await open(page, order);
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await expect(page.locator(".detail input")).toHaveCount(0);
  await expect(page.locator(".detail")).not.toContainText("取件码");
  await expect(page.locator(".detail")).not.toContainText("C-123456");
  await page.getByRole("button", { name: "确认取件", exact: true }).click();
  await page.getByRole("button", { name: "确认送达", exact: true }).click();
  await expect(page.locator(".detail")).toContainText("等待发布者确认收货");
  await expect(page.getByLabel("评分")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: "test-results/c-receipt-mobile.png",
    fullPage: true,
  });
  await visit(page, publisher);
  await open(page, order);
  await expect(page.locator(".detail")).not.toContainText("取件码");
  await page.getByRole("button", { name: "确认收货", exact: true }).click();
  await expect(page.getByLabel("评分")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".progress li").last()).toHaveAttribute(
    "aria-current",
    "step",
  );
});

test("取消未支付和已支付订单，等待真实退款结果", async ({ page, request }) => {
  const publisher = await student(request);
  const unpaid = await create(request, publisher, false);
  await visit(page, publisher);
  await open(page, unpaid);
  await page.getByLabel("取消原因").fill("计划变更");
  await page.getByRole("button", { name: "取消订单", exact: true }).click();
  await expect(page.locator(".detail")).toContainText("订单已取消");
  await expect(page.locator(".detail dl")).toContainText("无需退款");
  const paid = await create(request, publisher);
  await page.getByRole("button", { name: "刷新订单" }).click();
  await open(page, paid);
  await page.getByLabel("取消原因").fill("不再需要");
  await page.getByRole("button", { name: "取消订单", exact: true }).click();
  await expect
    .poll(async () => (await latest(request, paid, publisher)).refundStatus)
    .toBe("succeeded");
  await page.getByRole("button", { name: "刷新订单" }).click();
  await expect(page.locator(".detail dl")).toContainText("已退款");
});

test("连接失败保留重试且使用同一提交标识，详情失败禁用操作", async ({
  page,
  request,
}) => {
  const publisher = await student(request),
    courier = await student(request);
  const order = await accept(
    request,
    await create(request, publisher),
    courier,
  );
  await visit(page, courier);
  await open(page, order);
  let failed = false;
  const keys = [];
  await page.route(`**/api/orders/${order.orderId}/status`, async (route) => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (!failed) {
      failed = true;
      await route.abort();
    } else await route.continue();
  });
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await expect(page.getByText(/连接中断/)).toBeVisible();
  await page.getByRole("button", { name: "开始取件", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "确认取件", exact: true }),
  ).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
  await page.route(`**/api/orders/${order.orderId}`, (route) =>
    route.fulfill({ status: 503, json: { detail: "暂不可用" } }),
  );
  await page.getByRole("button", { name: "刷新订单" }).click();
  await expect(page.getByRole("alert")).toContainText("无法更新订单");
  await expect(
    page.getByRole("button", { name: "确认取件", exact: true }),
  ).toBeDisabled();
});

test("轮询在离开页面时停止，列表错误与空态分开显示", async ({
  page,
  request,
}) => {
  const publisher = await student(request);
  await create(request, publisher, false);
  await page.clock.install();
  await visit(page, publisher);
  await expect(page.locator(".order-card")).toHaveCount(1);
  let queries = 0;
  page.on("request", (req) => {
    if (req.url().includes("scope=mine")) queries++;
  });
  await page.clock.runFor(11000);
  await expect.poll(() => queries).toBeGreaterThan(0);
  await page
    .getByRole("link", { name: "代取大厅", exact: true })
    .first()
    .click();
  await expect(page.locator(".fulfillment-workspace")).toHaveCount(0);
  const before = queries;
  await page.clock.runFor(31000);
  expect(queries).toBe(before);
  await page.route("**/api/orders?*scope=mine*", (route) =>
    route.fulfill({ status: 503, json: { detail: "查询暂不可用" } }),
  );
  await page.goto("/orders");
  await expect(page.getByRole("alert")).toContainText("查询暂不可用");
  await expect(page.getByText("暂无符合条件的订单")).toHaveCount(0);
});
~~~~

### frontend/playwright.fulfillment.config.js

临时测试服务、端口和运行配置；22 行。

SHA-256（原始文件字节）：`4e56e30da930bc0da326d974101ed99eb67e2c893d52eae9d22b1b3b63d54123`

~~~~javascript
import { defineConfig } from "@playwright/test";
import verification from "./playwright.verification.config.js";
// 真实 A/B/C/D + 后台事件；仅复用临时库中的虚构审核管理员。
export default defineConfig({
  ...verification,
  testMatch: "fulfillment.spec.js",
  timeout: 60000,
  use: { ...verification.use, baseURL: "http://127.0.0.1:18162" },
  webServer: [
    {
      ...verification.webServer[0],
      command: verification.webServer[0].command.replace("18151", "18161"),
      url: "http://127.0.0.1:18161/api/health",
    },
    {
      ...verification.webServer[1],
      command: "npm run dev -- --port 18162 --strictPort",
      url: "http://127.0.0.1:18162",
      env: { CAMPUS_API_TARGET: "http://127.0.0.1:18161" },
    },
  ],
});
~~~~

## 15. 公共文件中与 C 交付相关的修改

以下逐文件展示团队基线 506db07 到当前工作区的真实差异，涵盖首次 C 实现和本次确认收货修订，包含未提交修改；第 13 节展示当前完整文件。B/D 原文件的既有部分仍属于团队贡献，公共鉴权和投递器也不计为 C 原创。

### backend/app/main.py

~~~~diff
diff --git a/backend/app/main.py b/backend/app/main.py
index b4d16fa..18787dd 100644
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -31,0 +32,2 @@ from .modules.orders.handlers import EventReceipt, PaymentFact
+from .modules.fulfillment.api import router as fulfillment_router
+from .modules.fulfillment.models import TABLES as fulfillment_tables
@@ -44 +46 @@ async def lifespan(app):
-                                          OutboxEvent.__table__, Delivery.__table__])
+                                          OutboxEvent.__table__, Delivery.__table__, *fulfillment_tables])
@@ -62 +64 @@ app = FastAPI(title="校园快递代取管理系统", version="1.1.0", lifespan=
-for router in (orders_router, identity_router, verification_router, wallet.router, payment.router):
+for router in (orders_router, identity_router, verification_router, wallet.router, payment.router, fulfillment_router):
~~~~

### backend/app/events/wiring.py

~~~~diff
diff --git a/backend/app/events/wiring.py b/backend/app/events/wiring.py
index d55fe1c..5644d97 100644
--- a/backend/app/events/wiring.py
+++ b/backend/app/events/wiring.py
@@ -1 +1 @@
-"""单体订阅装配；C 的评价处理器由其交付后在此显式注册。"""
+"""单体订阅装配。"""
@@ -8,0 +9 @@ def register_defaults():
+    from ..modules.fulfillment.handlers import on_order_completed as open_reviews
@@ -14,0 +16 @@ def register_defaults():
+    register_consumer("order.completed", "fulfillment", open_reviews)
~~~~

### backend/app/events/schema.py

~~~~diff
diff --git a/backend/app/events/schema.py b/backend/app/events/schema.py
index 7b82c31..1b46799 100644
--- a/backend/app/events/schema.py
+++ b/backend/app/events/schema.py
@@ -23 +23 @@ Nonnegative = Annotated[int, Field(strict=True, ge=0)]
-Status = Literal["pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "cancelled"]
+Status = Literal["pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "completed", "cancelled"]
~~~~

### backend/app/modules/orders/gateway.py

~~~~diff
diff --git a/backend/app/modules/orders/gateway.py b/backend/app/modules/orders/gateway.py
index 2e7614e..30d64d9 100644
--- a/backend/app/modules/orders/gateway.py
+++ b/backend/app/modules/orders/gateway.py
@@ -37 +37,2 @@ class OrderGateway:
-            "fulfill": ({"accepted", "picking_up", "delivering"}, {"status", "pickup_failures", "locked", "lock_reason"}),
+            "fulfill": ({"accepted", "picking_up", "delivering"}, {"status"}),
+            "confirm_receipt": ({"delivered"}, {"status"}),
@@ -45 +46 @@ class OrderGateway:
-        if operation in {"reserve", "cancel"} and actor_uid != order.publisher_uid:
+        if operation in {"reserve", "cancel", "confirm_receipt"} and actor_uid != order.publisher_uid:
@@ -51,2 +52,2 @@ class OrderGateway:
-        if operation == "fulfill" and (actor_uid != order.courier_uid or order.locked):
-            fail(409, "ORDER_LOCKED" if order.locked else "ORDER_CONFLICT", "订单已锁定或无权操作")
+        if operation == "fulfill" and actor_uid != order.courier_uid:
+            fail(409, "ORDER_CONFLICT", "无权推进订单履约")
@@ -62 +63 @@ class OrderGateway:
-            valid = (changes == {"status": "accepted", "courier_uid": actor_uid} and actor_uid is not None and not order.locked)
+            valid = (changes == {"status": "accepted", "courier_uid": actor_uid} and actor_uid is not None)
@@ -68,2 +69 @@ class OrderGateway:
-            target = changes.get("status", order.status)
-            valid = (target == order.status or (order.status, target) in
+            valid = (set(changes) == {"status"} and (order.status, changes["status"]) in
@@ -70,0 +71,3 @@ class OrderGateway:
+        elif operation == "confirm_receipt":
+            valid = (changes == {"status": "completed"} and order.payment_status == "paid"
+                     and order.refund_status == "none" and bool(order.courier_uid))
@@ -77,2 +80,2 @@ class OrderGateway:
-                             Order.status == order.status, Order.payment_status == order.payment_status,
-                             Order.locked == order.locked).values(**changes, version=Order.version + 1))
+                             Order.status == order.status, Order.payment_status == order.payment_status
+                             ).values(**changes, version=Order.version + 1))
~~~~

### backend/app/modules/orders/api.py

~~~~diff
diff --git a/backend/app/modules/orders/api.py b/backend/app/modules/orders/api.py
index ea054fb..fc8c278 100644
--- a/backend/app/modules/orders/api.py
+++ b/backend/app/modules/orders/api.py
@@ -19 +19 @@ router = APIRouter(prefix="/api/orders", tags=["orders"])
-STATUSES = {"pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "cancelled"}
+STATUSES = {"pending_payment", "pending", "accepted", "picking_up", "delivering", "delivered", "completed", "cancelled"}
~~~~

### backend/app/modules/orders/projections.py

~~~~diff
diff --git a/backend/app/modules/orders/projections.py b/backend/app/modules/orders/projections.py
index ff1e54f..7e96094 100644
--- a/backend/app/modules/orders/projections.py
+++ b/backend/app/modules/orders/projections.py
@@ -4,0 +5 @@ from ...events.schema import validate
+from ...events.models import OutboxEvent
@@ -8,0 +10,22 @@ from .handlers import EventReceipt
+def legacy_delivery_matches(db, order, data):
+    """旧 delivered 完结重命名后，保留原状态事件而以匹配的完结事实校准。"""
+    body = data["payload"]
+    if (order.status != "completed" or data["version"] != order.version
+            or (body["fromStatus"], body["status"], body["courierUid"])
+            != ("delivering", "delivered", order.courier_uid)):
+        return False
+    expected = {"publisherUid": order.publisher_uid, "courierUid": order.courier_uid,
+                "amount": order.amount, "baseFee": order.base_fee, "tip": order.tip,
+                "commissionRateBps": order.commission_bps, "pricingVersion": order.pricing_version,
+                "orderVersion": order.version}
+    events = db.scalars(select(OutboxEvent).where(OutboxEvent.order_id == order.id,
+                                                 OutboxEvent.type == "order.completed"))
+    for event in events:
+        completion, digest = validate(event.body)
+        if (event.digest == digest and completion["type"] == "order.completed"
+                and completion["orderId"] == order.id and completion["version"] == order.version
+                and completion["payload"] == expected):
+            return True
+    return False
+
+
@@ -29 +52,3 @@ def handle(db, event):
-    elif data["version"] == order.version and (body["status"], body["courierUid"]) != (order.status, order.courier_uid):
+    elif (data["version"] == order.version
+          and (body["status"], body["courierUid"]) != (order.status, order.courier_uid)
+          and not legacy_delivery_matches(db, order, data)):
~~~~

### backend/app/modules/finance/services/settlement.py

~~~~diff
diff --git a/backend/app/modules/finance/services/settlement.py b/backend/app/modules/finance/services/settlement.py
index 4024b06..80451c1 100644
--- a/backend/app/modules/finance/services/settlement.py
+++ b/backend/app/modules/finance/services/settlement.py
@@ -13 +13 @@ def settle_order(db, command):
-    if (order.status != "delivered" or order.payment_status != "paid" or order.refund_status != "none"
+    if (order.status != "completed" or order.payment_status != "paid" or order.refund_status != "none"
~~~~

### backend/app/modules/finance/README.md

~~~~diff
diff --git a/backend/app/modules/finance/README.md b/backend/app/modules/finance/README.md
index 8d81619..372c926 100644
--- a/backend/app/modules/finance/README.md
+++ b/backend/app/modules/finance/README.md
@@ -82 +82 @@ B 消费后更新 refundStatus，原 paymentStatus 保留 paid。历史 pending
-## 配送完成结算
+## 发布者确认收货后的完成结算
@@ -86 +86 @@ A 在公共事件组件中注册 `order.completed` → consumer_name=`finance`
-消费者使用投递方 Session，不自行提交。校验已送达订单、付款人、取件员、
+消费者使用投递方 Session，不自行提交。校验发布者已确认收货的 completed 订单、付款人、取件员、
@@ -99,2 +99 @@ finance_settlements 独立保存客户冻结消耗、取件员收入、平台佣
-公共投递器已注册此消费者；C 交付实际完结业务入口并同事务发布 order.completed 后即可投递。
-C 自己的评价订阅尚未装配时单独保留重试，不影响已成功的资金结算。
+公共投递器已注册此消费者；C 的发布者 confirm_receipt 入口将 delivered 改为 completed 并同事务发布 order.completed。取件员 confirm_delivery 只改为 delivered，不触发结算，资金保持冻结。C 的评价订阅独立投递、失败独立重试，不影响已成功的资金结算。
@@ -119 +118 @@ C 自己的评价订阅尚未装配时单独保留重试，不影响已成功的
-tests/test_events_integration.py。C 的生产业务入口仍待其交付，不能将测试内的网关动作算作已交付接口。
+tests/test_events_integration.py。C 的生产业务入口已接入确认收货流程，联调应验证 delivered 不结算、completed 才结算；不能将测试内网关动作等同于完整的客户端操作。
~~~~

### backend/scripts/init_db.py

~~~~diff
diff --git a/backend/scripts/init_db.py b/backend/scripts/init_db.py
index 8a684e4..c2a455b 100644
--- a/backend/scripts/init_db.py
+++ b/backend/scripts/init_db.py
@@ -20,0 +21 @@ from app.events import models as event_models  # noqa: E402,F401
+from app.modules.fulfillment import models as fulfillment_models  # noqa: E402,F401
~~~~

### frontend/src/App.vue

~~~~diff
diff --git a/frontend/src/App.vue b/frontend/src/App.vue
index 164f8ef..7f09ea0 100644
--- a/frontend/src/App.vue
+++ b/frontend/src/App.vue
@@ -114 +114,3 @@ const navigation = computed(() => [
-              : "界面预览 · 示例数据"
+              : ["/orders", "/reviews"].includes(route.path)
+                ? `${route.meta.title} · 履约服务`
+                : "界面预览 · 示例数据"
~~~~

### frontend/src/features/orders/PublishView.vue

~~~~diff
diff --git a/frontend/src/features/orders/PublishView.vue b/frontend/src/features/orders/PublishView.vue
index abe702f..48ad95c 100644
--- a/frontend/src/features/orders/PublishView.vue
+++ b/frontend/src/features/orders/PublishView.vue
@@ -99 +99,2 @@ const statusLabels = {
-  delivered: "已送达",
+  delivered: "已送达，待确认收货",
+  completed: "已完成",
@@ -573 +574 @@ onBeforeUnmount(() => {
-          取件码与详细地址仅向你和接单后的同学提供。请在备注中避免填写敏感信息。
+          详细地址仅向你和接单后的同学提供。请在备注中避免填写敏感信息。
~~~~

### frontend/src/features/orders/HallTaskDialog.vue

~~~~diff
diff --git a/frontend/src/features/orders/HallTaskDialog.vue b/frontend/src/features/orders/HallTaskDialog.vue
index 032a734..8f4342a 100644
--- a/frontend/src/features/orders/HallTaskDialog.vue
+++ b/frontend/src/features/orders/HallTaskDialog.vue
@@ -85 +85 @@ onBeforeUnmount(() => dialog.value?.close());
-        取件码和详细地址在接单后提供。请先确认取件点与送达区域是否顺路。
+        详细地址在接单后提供。请先确认取件点与送达区域是否顺路。
~~~~

### frontend/package.json

~~~~diff
diff --git a/frontend/package.json b/frontend/package.json
index ab9d97e..aa91470 100644
--- a/frontend/package.json
+++ b/frontend/package.json
@@ -13 +13,2 @@
-    "test:verification": "playwright test --config playwright.verification.config.js"
+    "test:verification": "playwright test --config playwright.verification.config.js",
+    "test:fulfillment": "playwright test --config playwright.fulfillment.config.js"
~~~~

### backend/tests/test_events_integration.py

~~~~diff
diff --git a/backend/tests/test_events_integration.py b/backend/tests/test_events_integration.py
index c4c944d..b6e53a8 100644
--- a/backend/tests/test_events_integration.py
+++ b/backend/tests/test_events_integration.py
@@ -52,0 +53 @@ class EventIntegrationTests(unittest.TestCase):
+                order = OrderGateway.transition(db, order, order.version, "confirm_receipt", "alice", status="completed")
@@ -157 +158 @@ class EventIntegrationTests(unittest.TestCase):
-    def test_completion_settles_once_while_missing_fulfillment_subscription_remains_pending(self):
+    def test_completion_settles_once_and_opens_reviews(self):
@@ -166 +167,3 @@ class EventIntegrationTests(unittest.TestCase):
-            self.assertEqual(db.get(Delivery, (event["eventId"], "fulfillment")).status, "pending")
+            self.assertEqual(db.get(Delivery, (event["eventId"], "fulfillment")).status, "succeeded")
+            from app.modules.fulfillment.models import ReviewOpening
+            self.assertIsNotNone(db.get(ReviewOpening, body["orderId"]))
~~~~

### README.md

~~~~diff
diff --git a/README.md b/README.md
index e11a988..cefd0c8 100644
--- a/README.md
+++ b/README.md
@@ -5 +5 @@
-当前已实现 F1 注册登录与公共鉴权、F2 学生认证提交/审核/通知、B 的发布/大厅与订单公共能力、D 的模拟钱包、正式计价、支付冻结及退款/结算消费者，以及公共 outbox 和后台事件投递。C 的履约、信用业务入口和评价消费者仍待交付。首页部分卡片仍为示例数据，不代表真实订单。本项目不发送真实短信、不产生真实资金交易。
+当前已实现 F1 注册登录与公共鉴权、F2 学生认证提交/审核/通知、B 的发布/大厅与订单公共能力、C 的接单履约/取消/评价信用、D 的模拟钱包/正式计价/支付冻结及退款结算，以及公共 outbox 和后台事件投递。C 的个人功能需求、验收标准及集成约束见[团队接口约定第 9.1 节](docs/团队接口约定.md#91-c-个人任务功能需求质量需求与开发约束)。首页部分卡片仍为示例数据，不代表真实订单。本项目不发送真实短信、不产生真实资金交易。
@@ -26,0 +27 @@ npm run test:verification # 真实账号提交、审核、通知与照片权限
+npm run test:fulfillment  # C：真实账号接单、履约、收货确认、互评、信用与退款
@@ -46,0 +48,2 @@ $env:CAMPUS_DEMO_CODE = '482917'
+C 的完整演示使用两个已通过学生认证的账号：发布者发布并支付，取件员在 `/tasks` 接单后进入 `/orders`，依次开始取件、确认取件、确认送达。此时订单为 `delivered`（已送达、待收货），资金仍冻结、评价尚未开放；发布者确认收货（`confirm_receipt`）后变为 `completed`（已完成），才发布完结事件，由后台分别处理资金结算与评价开放，双方可在订单详情或 `/reviews` 各评价一次。C 的页面和履约接口不输入、不校验、不展示取件码。信用按本人作为取件员收到的最近 30 条评价计算，新人允许接单，未四舍五入均分低于 3.0 时限制新接单。发布者只能在接单前取消；已付款取消先显示退款处理中，实际到账由 D/B 的事件处理结果决定。订单和信用页每 10 秒刷新，离开页面停止。
+
@@ -66,0 +70,2 @@ $env:PYTHONPATH = 'backend'
+C 后端场景位于 `backend/tests/test_fulfillment.py`，覆盖抢单与取消竞争、旧版本/重复提交、履约动作权限、送达与确认收货的边界、事件失败回滚、完结事件重试、双向评价和最近 30 条信用边界。验收应特别检查：取件员确认送达后不结算、不能评价；仅发布者确认收货后结算一次并开放评价。`test:fulfillment` 自动启动临时后端及 Vue 服务，使用真实 A/B/C/D 接口和虚构账号，不需要手动准备账号或修改开发库；只在测试环境预置审核管理员。
+
@@ -81,0 +87,12 @@ $env:PYTHONPATH = 'backend'
+## 升级 C 的确认收货流程
+
+已有开发库先停止服务并备份数据库，再从 backend 目录执行：
+
+```powershell
+..\.venv\Scripts\python.exe -m app.modules.fulfillment.migrate_receipt
+```
+
+迁移仅将存在匹配旧 `order.completed` outbox 事实的历史 `delivered` 订单改为 `completed`，保留原版本、事件和资金记录，避免重新结算。新版没有完结事件的 `delivered` 订单保持待收货，由发布者正常确认；重复运行无变化，历史事实冲突时整批回滚。旧取件失败/锁定列兼容保留。全新数据库无需迁移；不要删库重建来升级。
+
+B 的大厅投影只在同版本旧 `delivering→delivered` 事件具有完全匹配的历史完结 outbox 佐证时兼容状态重命名，原事件保持不变；其他事实冲突仍拒绝。C 重放旧成功请求时裁剪取件码和锁定字段，并兼容旧缺省 `code:null` 的请求摘要；新请求携带 `code` 仍返回 422，旧失败回执不会变成成功。
+
@@ -118 +135 @@ $env:PYTHONPATH = 'backend'
-6. 审核通知属于 F2；跨模块事件统一调用 `app.events.publish(db, event)`，与业务共用 Session 和事务。消费者、投递重试、历史补录与维护命令见[团队接口约定第 12 节](docs/团队接口约定.md#12-事件重试与幂等)。投递器随应用启动/停止，新增 outbox 表自动创建；历史支付和退款保留原 eventId 自动补录，不再次移动资金。C 未交付的评价订阅会保留重试，不能假报完成。
+6. 审核通知属于 F2；跨模块事件统一调用 `app.events.publish(db, event)`，与业务共用 Session 和事务。消费者、投递重试、历史补录与维护命令见[团队接口约定第 12 节](docs/团队接口约定.md#12-事件重试与幂等)。投递器随应用启动/停止，新增 outbox 和 C 模块表自动创建；历史支付和退款保留原 eventId 自动补录，不再次移动资金。完结事件分别交给 D 结算、C 开放评价；此前缺少 C 处理器而进入 dead 的投递，可按原 eventId 仅重试 fulfillment 订阅，已成功的结算不重复执行。
~~~~

### docs/团队接口约定.md

~~~~diff
diff --git "a/docs/\345\233\242\351\230\237\346\216\245\345\217\243\347\272\246\345\256\232.md" "b/docs/\345\233\242\351\230\237\346\216\245\345\217\243\347\272\246\345\256\232.md"
index 7d7a42b..36c032c 100644
--- "a/docs/\345\233\242\351\230\237\346\216\245\345\217\243\347\272\246\345\256\232.md"
+++ "b/docs/\345\233\242\351\230\237\346\216\245\345\217\243\347\272\246\345\256\232.md"
@@ -3 +3 @@
-版本：v1.3；生效日期：2026-10-31。本文件统一记录四人团队的接口、权限、数据状态、对接边界、事件、事务、验收及协作规则，是唯一的团队协作约定入口。v1.3 落实公共 outbox 与投递器，接入现有支付、退款及结算消费者；C 的履约生产接口和评价消费者仍待交付，不能据此宣称全项目已完成。
+版本：v1.3，C 履约流程于 2026-11-11 修订；原基线生效日期：2026-10-31。本文件统一记录四人团队的接口、权限、数据状态、对接边界、事件、事务、验收及协作规则，是唯一的团队协作约定入口。v1.3 落实公共 outbox 与投递器，接入支付、退款及结算消费者；C 现采用不验证取件码的履约操作，发布者确认收货后才完成、结算及开放评价，第 9.1 节记录个人任务与验收要求。合并和团队验收状态以 GitHub 及实际验收为准。
@@ -134 +134 @@ B 的 OrderGateway 公共能力是订单所有者提供的同步命令入口，
-| picking_up | 取件中 | delivering：本单取件员核对取件码并确认取件 |
+| picking_up | 取件中 | delivering：本单取件员确认已取件 |
@@ -136 +136,2 @@ B 的 OrderGateway 公共能力是订单所有者提供的同步命令入口，
-| delivered | 已送达 | 终态，可评价和结算，不再变更履约状态 |
+| delivered | 已送达、待收货 | completed：本单发布者确认收货；尚不结算、不开放评价 |
+| completed | 已完成 | 终态；完结事件驱动结算和评价开放 |
@@ -139 +140 @@ B 的 OrderGateway 公共能力是订单所有者提供的同步命令入口，
-paymentStatus：unpaid / paying / paid。退款不改写原支付成功事实；refundStatus 单独使用 none / processing / succeeded。订单不使用 locked 状态；锁定另设 locked 布尔值、pickupFailureCount、lockReason。取件码累计连续错误 3 次后锁定，不自动解锁，本期不提供用户解锁功能，课程异常演示由维护脚本明确重置。
+paymentStatus：unpaid / paying / paid。退款不改写原支付成功事实；refundStatus 单独使用 none / processing / succeeded。订单不使用 locked 状态；历史 locked、pickupFailureCount、lockReason 列仅为数据库兼容保留，C 不再读取或写入这些列，不产生错码计数或锁单。
@@ -143 +144 @@ OrderSummary 固定字段：orderId、company、stationId、stationName、delive
-OrderDetail 在 Summary 上增加：publisherUid、courierUid（未接单为 null）、locked、pickupFailureCount，以及按权限裁剪的 address、code。发布者查看自己的订单时还可获得当前 paymentRequestId（无则 null）。
+OrderDetail 在 Summary 上增加：publisherUid、courierUid（未接单为 null）、locked、pickupFailureCount，以及按权限裁剪的 address、code。发布者查看自己的订单时还可获得当前 paymentRequestId（无则 null）。这些是 B 的兼容详情字段；C 的履约响应不包含 code、locked、pickupFailureCount，C 页面不展示取件码或旧锁定信息，也不把它们用于履约校验。
@@ -190,3 +191,3 @@ GET /api/orders 过滤参数：status（hall 仅 pending）、stationId、delive
-| POST /api/orders/{orderId}/accept | `{version}` + Idempotency-Key | OrderDetail；已认证、信用合格、非本人发布、已支付 pending |
-| POST /api/orders/{orderId}/status | `{action,version,code?}` + Idempotency-Key | OrderDetail；仅本单取件员 |
-| GET /api/orders/{orderId}/status | 无 | `{orderId,status,paymentStatus,refundStatus,locked,version}`；本单相关用户 |
+| POST /api/orders/{orderId}/accept | `{version}` + Idempotency-Key | 裁剪 code 和旧锁定字段后的 OrderDetail；已认证、信用合格、非本人发布、已支付 pending |
+| POST /api/orders/{orderId}/status | `{action,version}` + Idempotency-Key | 裁剪 code 和旧锁定字段后的 OrderDetail；取件配送动作仅本单取件员，收货动作仅本单发布者 |
+| GET /api/orders/{orderId}/status | 无 | `{orderId,status,paymentStatus,refundStatus,version}`；本单相关用户 |
@@ -198 +199 @@ GET /api/orders 过滤参数：status（hall 仅 pending）、stationId、delive
-action 固定 start_pickup / confirm_pickup / confirm_delivery，分别对应 accepted→picking_up→delivering→delivered。confirm_pickup 必须携 code，其他 action 拒绝携 code。身份认证要求在接单和履约动作时均检查；信用分在接单时检查，不因履约途中降分导致订单无法送达。
+action 固定 start_pickup / confirm_pickup / confirm_delivery / confirm_receipt，对应 accepted→picking_up→delivering→delivered→completed。前三个动作仅本单已认证取件员可执行；confirm_receipt 仅本单已登录发布者可执行，不重复要求学生认证。请求只允许 action、version，携带 code 或其他未声明字段返回 422。信用分在接单时检查，不因履约途中降分导致订单无法完成。
@@ -200 +201 @@ action 固定 start_pickup / confirm_pickup / confirm_delivery，分别对应 ac
-code 错误返回 422 PICKUP_CODE_MISMATCH，但错误次数须提交；第三次返回 409 ORDER_LOCKED，同时写入双方可查询的履约通知。错误重试同一幂等键不得重复计数；正确核对清零连续错误次数。已经锁定的订单拒绝后续履约动作。
+C 不输入、不校验、不展示取件码，confirm_pickup 直接确认取件事实。confirm_delivery 仅保存 delivered 状态及状态事件；不发布 order.completed。发布者执行 confirm_receipt 后，completed 状态、日志、状态事件、order.completed 和请求回执同事务提交，随后才由 D 结算、C 开放评价。旧锁定字段不参与新流程。
@@ -202 +203 @@ code 错误返回 422 PICKUP_CODE_MISMATCH，但错误次数须提交；第三
-评价要求 delivered、本人为发布者或取件员、每人每单一次，提交后不可修改；数据库唯一约束为 (orderId,reviewerUid)。rating 为整数 1～5；tags 为字符串数组，最多 5 项、每项 1～20 字符；comment 默认空字符串，最多 500。禁止自己评价自己，目标用户由服务端根据订单确定。
+评价要求 completed 且完结事件已由 C 消费开放、本人为发布者或取件员、每人每单一次，提交后不可修改；数据库唯一约束为 (orderId,reviewerUid)。delivered 尚不满足评价条件。rating 为整数 1～5；tags 为字符串数组，最多 5 项、每项 1～20 字符；comment 默认空字符串，最多 500。禁止自己评价自己，目标用户由服务端根据订单确定。
@@ -207,0 +209,46 @@ code 错误返回 422 PICKUP_CODE_MISMATCH，但错误次数须提交；第三
+### 9.1 C 个人任务：功能需求、质量需求与开发约束
+
+责任人：成员 C（实际姓名待本人填写）。范围为 F5、F6，前端使用 Vue 3，后端使用 FastAPI。需求来源为《校园快递代取系统团队任务清单.xlsx》“任务清单”第 8、9 行；实现细节以本文 v1.3 基线为准。
+
+#### 功能需求（功能描述）
+
+| 编号 | 功能描述 | 输入、处理和输出 |
+| --- | --- | --- |
+| C-F5-01 | 接取已付款的他人需求 | 读取 F1 身份、F2 最新认证及 F6 信用，通过 B 的 OrderGateway 原子占用待接单订单，返回裁剪 code 后的详情；接单成功后可查看门牌地址。 |
+| C-F5-02 | 按顺序完成取件与配送 | 本单取件员依次开始取件、确认取件、确认送达；状态为 accepted→picking_up→delivering→delivered。每次动作记录操作者、时间、前后状态及新版本，C 不处理取件码。 |
+| C-F5-03 | 发布者确认收货后完成 | delivered 时仅本单发布者执行 confirm_receipt，进入 completed 并同事务发布完结事件；D 才结算、C 才开放评价。无关用户、取件员及跳步动作均拒绝。 |
+| C-F5-04 | 接单前取消与退款展示 | 仅发布者取消未支付或已付款待接单订单。与接单、支付预占竞争时最多一个操作成功；已付款取消先显示退款处理中，再读取 D/B 的异步退款结果。 |
+| C-F5-05 | 我的订单与进度查询 | Vue 页面按我发布/我接取和状态分页查询，展示详情、取件进度和待收货状态；可见页面每 10 秒刷新，离开停止。错误与空列表分开显示。历史通知接口保留兼容，当前页面不查询或展示。 |
+| C-F6-01 | 确认收货完成后双方互评 | 发布者确认收货且订单完结事件消费成功后开放评价。每位参与人对另一方评价一次，包含 1～5 星、最多 5 个标签和 500 字以内评论，提交后不可修改。 |
+| C-F6-02 | 信用展示与接单准入 | 实时查询本人以取件员身份收到的最近 30 单评价；展示均分、等级、样本数及接单资格。均分低于 3.0 拒绝接单，新人 score=null 且允许接单。 |
+| C-F6-03 | 历史评价查询 | 仅本单参与人可分页查看双方评价，支持在订单详情及评价页查看；用户文字按普通文本渲染。 |
+
+#### 质量需求（可执行验收标准）
+
+| 编号 | 验收标准 |
+| --- | --- |
+| C-Q01 权限 | 未登录返回 401；未认证接单/取件配送返回 403 VERIFICATION_REQUIRED；仅本单取件员可开始/确认取件及送达，仅本单已登录发布者可确认收货；无关用户读取详情、通知或评价返回 404；信用仅本人可读。 |
+| C-Q02 状态与竞争 | 两个取件员同时抢单仅一人成功；接单与取消互斥；旧版本及跳步动作返回 409，不能覆盖更新后的状态。paying 期间禁止取消。 |
+| C-Q03 收货边界 | confirm_pickup 无额外输入即可推进；code 字段返回 422，C 页面和 C 履约响应不展示 code。delivered 时无完结事件、不结算、不开放评价；取件员不能代替发布者确认收货，跳步和旧版本被拒。 |
+| C-Q04 原子性 | 注入事件保存失败时，订单状态、操作记录与幂等结果整体回滚；发布者确认收货时同时保存 completed、状态事件和完结事件，C 不直接改钱包。确认收货重试不重复完结或结算。 |
+| C-Q05 评价 | 非 completed 或完结事件尚未消费时不能提交；本人每单仅一次，数据库唯一约束兜底；并发提交只能创建一条；整数星级、标签、字数及额外字段由服务端严格校验。 |
+| C-Q06 信用 | 0 条时为新人；只计收到的取件员评价，最多 30 条，按 createdAt/reviewId 逆序；以未四舍五入均分判断 3.0、4.0 边界，展示两位小数。 |
+| C-Q07 事件 | 重复完结事件及换 eventId 的同一完结事实不重复开放评价；消费与回执同事务。故障保留重试，恢复后可继续，不提前显示退款/结算成功。 |
+| C-Q08 页面 | 桌面及 390px 手机页面可完成流程、无横向溢出；按钮提交时禁用；失败保留错误和重试入口；轮询正常情况下 30 秒内更新，离开页面停止；登录及认证沿用公共流程。 |
+
+#### 开发约束（集成关系、接口契约）
+
+| 对接方 | C 的依赖或提供能力 | 约束 |
+| --- | --- | --- |
+| A / F1、F2 | current_identity、require_verified；前端公共 request | 不信任客户端 UID、角色或认证状态；共用请求 Session、JWT/sid 校验，不建立独立登录体系。 |
+| B / F3、F4 | 读取 OrderGateway.get_snapshot/related，调用 transition；提供 order.status_changed、order.cancelled | 不直接写订单 ORM，不另建订单主表；每次条件更新检查版本；大厅读取主表并消费刷新事件。 |
+| C / F5、F6 | CreditService.get；order.completed 消费者 | 信用检查在接单时执行；履约不因之后降分受阻；完结消费者只开放评价并写回执，不回写履约或触发同一事件。 |
+| D / F7 | order.completed、order.cancelled | C 仅发事实事件，由 D 结算/退款、B 接收退款结果；不调用钱包修改余额，不根据超时认定支付失败。 |
+| 公共事件 | publish(db,event)，consumer_name=fulfillment | 状态、日志、幂等记录和 outbox 同事务；消费者不 commit，不另开会话；保留原 eventId 重投。 |
+
+HTTP 路径、动作、输入、错误和响应沿用第 9 节。保留 `GET /api/orders/{orderId}/notifications?page=1&pageSize=20` 以查询历史履约通知，通知项为 notificationId、orderId、type、message、createdAt，仅本人接收的本单通知；新流程不产生错码锁单通知。评价列表项为 reviewId、orderId、reviewerUid、revieweeUid、reviewerRole、rating、tags、comment、createdAt；列表额外提供 reviewable，表示已 completed 且完结事件已消费。分页拒绝未声明字段、page<1、pageSize>100。所有时间为 UTC Z，金额为整数分。接单、履约（含收货）、取消共用 Idempotency-Key 机制，网络失败重试沿用原键；评价由每人每单唯一约束防重，重复提交返回 409 ALREADY_REVIEWED。
+
+C 的表保存操作记录、历史履约通知、评价、评价开放标记和消费者回执，启动时无损建表，不修改既有列。为接入确认收货，本次同步扩展 B 的受控状态入口/状态筛选，以及 D 与 C 完结消费者的 completed 状态校验；沿用现有路径和事件结构。课程阶段历史文档和外部原始任务清单保留原样。
+
+历史请求兼容由 C 的 replay_fulfillment 处理：匹配当前规范化摘要，或旧三种配送动作缺省 code:null 的摘要；成功回执返回前裁剪 code、locked、pickupFailureCount，失败仍重放原错误，不修改旧记录或重做业务。带明确旧码的摘要不会被无 code 请求命中，新提交携带 code 仍返回 422。B 既有大厅投影只对同版本旧 delivering→delivered 状态事件，且存在摘要、身份、金额、费率快照全部匹配的历史 order.completed outbox 时兼容 completed 状态重命名；其他同版本事实冲突仍拒绝，原事件不改写。
+
@@ -269 +316 @@ code 错误返回 422 PICKUP_CODE_MISMATCH，但错误次数须提交；第三
-C 的业务动作事务同时调用受控 OrderGateway 并写本模块的日志/事件。B 的支付事件消费者调用同一状态入口。只有白名单状态转换可执行；处理器负责校验权限、paymentStatus 和 locked。不得将同一个事务拆成多次提交，不在 SQLite 写事务内发 HTTP。B/D 只读相互查询不构成相互写回。
+C 的业务动作事务同时调用受控 OrderGateway 并写本模块的日志/事件。B 的支付事件消费者调用同一状态入口。只有白名单状态转换可执行；处理器负责校验权限、paymentStatus、refundStatus 和版本。不得将同一个事务拆成多次提交，不在 SQLite 写事务内发 HTTP。B/D 只读相互查询不构成相互写回。
@@ -292 +339 @@ HTTP Idempotency-Key 的范围为 (uid,operation,key)，持久化请求摘要、
-F2 审核通知仍按既定方案同步写入，不改为异步。C 的取件锁定通知由 C 提供 GET /api/orders/{orderId}/notifications（仅本单相关用户，分页），与锁定事务一起保存；不占用 F2 的认证通知接口。
+F2 审核通知仍按既定方案同步写入，不改为异步。C 保留 GET /api/orders/{orderId}/notifications（仅本单相关用户，分页）查询历史履约通知；新流程不再生成错码锁单通知，不占用 F2 的认证通知接口。
@@ -296 +343 @@ F2 审核通知仍按既定方案同步写入，不改为异步。C 的取件锁
-公共实现位于 backend/app/events，应用启动时建表、装配已交付的消费者并启动每秒扫描任务，关闭应用时停止并等待本轮处理结束。支付成功/失败已自动投递至 B；取消、完结事件的 D 消费者已装配，生产事件仍须由 C 的实际业务入口同事务发布。不创建各模块独立投递器或匿名“支付成功”HTTP 接口。
+公共实现位于 backend/app/events，应用启动时建表、装配已交付的消费者并启动每秒扫描任务，关闭应用时停止并等待本轮处理结束。支付成功/失败自动投递至 B；C 的取消、完结入口同事务发布事件，分别由 D 退款/结算、C 开放评价。不创建各模块独立投递器或匿名“支付成功”HTTP 接口。
@@ -321 +368 @@ def retry_dead(event_id, *, consumer_name=None) -> int: ...  # 保留原 eventId
-| order.completed | fulfillment | C 尚未交付；投递记录仍会生成，缺处理器按规则重试/进入 dead，装配后仅恢复该订阅，已成功的 finance 不重复结算 |
+| order.completed | fulfillment | fulfillment.handlers.on_order_completed；核验完结事实、开放双方评价并保存去重回执，与投递确认同事务；不修改订单或资金 |
@@ -325 +372 @@ def retry_dead(event_id, *, consumer_name=None) -> int: ...  # 保留原 eventId
-C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.transition、保存本模块事实/HTTP 幂等结果，并调用 publish(db, 完整事件)，最后由业务用例提交一次。订单 version 和 payload.orderVersion 使用变更后快照的 version。order.completed 同时生成 finance、fulfillment 两条投递，不因后者尚未装配而丢掉订阅；C 交付处理器后由 A 更新 wiring.py。事件中不得携手机号、取件码、Token 或证件；公共校验拒绝约定外字段、非整数金额、未知事件类型和非规范 UUID，occurredAt 必须为带 Z 的 UTC 字符串。
+C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.transition、保存本模块事实/HTTP 幂等结果，并调用 publish(db, 完整事件)，最后由业务用例提交一次。只有发布者确认收货使 delivered→completed 时发布 order.completed，取件员确认送达时只发状态事件；D/C 消费者均要求订单 completed。订单 version 和 payload.orderVersion 使用变更后快照的 version。order.completed 同时生成 finance、fulfillment 两条投递，当前均已在 wiring.py 装配；历史缺处理器而进入 dead 的记录可仅恢复 fulfillment，已成功的 finance 不重复结算。历史 delivered 先停服备份，再执行 `python -m app.modules.fulfillment.migrate_receipt`，仅将有匹配旧完结 outbox 事实的订单迁移为 completed；不改版本、不新建事件、不移动资金，事实冲突整批回滚。没有完结事件的新版 delivered 保持等待发布者收货。事件中不得携手机号、取件码、Token 或证件；公共校验拒绝约定外字段、非整数金额、未知事件类型和非规范 UUID，occurredAt 必须为带 Z 的 UTC 字符串。
@@ -341 +388 @@ C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.tr
-422：VALIDATION_ERROR / PICKUP_CODE_MISMATCH。401：AUTH_REQUIRED / SESSION_EXPIRED。403：FORBIDDEN / VERIFICATION_REQUIRED / CREDIT_TOO_LOW。404：NOT_FOUND。409：ORDER_CONFLICT / ORDER_LOCKED / PAYMENT_IN_PROGRESS / IDEMPOTENCY_CONFLICT / REQUEST_IN_PROGRESS / ALREADY_REVIEWED。503：DEPENDENCY_UNAVAILABLE。字段错误示例 fields 为 `{tip:"必须为整数分且在允许范围内"}`，所有错误均返回 code、detail、fields；500 不暴露堆栈或 SQL。
+422：VALIDATION_ERROR。401：AUTH_REQUIRED / SESSION_EXPIRED。403：FORBIDDEN / VERIFICATION_REQUIRED / CREDIT_TOO_LOW。404：NOT_FOUND。409：ORDER_CONFLICT / PAYMENT_IN_PROGRESS / IDEMPOTENCY_CONFLICT / REQUEST_IN_PROGRESS / ALREADY_REVIEWED。503：DEPENDENCY_UNAVAILABLE。字段错误示例 fields 为 `{tip:"必须为整数分且在允许范围内"}`，所有错误均返回 code、detail、fields；500 不暴露堆栈或 SQL。C 不再产生错码或锁单错误。
@@ -349 +396 @@ C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.tr
-| C | 两人抢单仅一人成功、接单与取消互斥、版本冲突、三次错误锁定及重试不重复计数、评价去重、新人信用 |
+| C | 两人抢单仅一人成功、接单与取消互斥、版本冲突、无额外输入确认取件、仅发布者收货后完成/结算/开放评价、并发收货一次完成、评价去重、新人信用 |
@@ -370,0 +418 @@ C 的接单/履约/取消入口必须在同一 Session 里调用 OrderGateway.tr
+- v1.3 C 实现记录（2026-10-31）：补充第 9.1 节个人功能需求、验收标准及集成约束，实现 F5/F6 的 FastAPI/Vue 功能并装配评价消费者；补全通知和评价列表字段，不改变既有 HTTP 路径、订单状态链或资金语义。
~~~~
