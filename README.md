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
npm run test:fulfillment  # C：真实账号接单、履约、互评、信用、锁单与退款
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

仓库只提供演示账号的创建脚本，**不包含已创建的账号或数据库，也没有团队共享的登录账号**。每位开发者拉取代码后，需先在自己的电脑上创建账号；无法直接登录其他队员本地数据库中的账号。

依赖安装完成后，在各自电脑的仓库根目录运行 `powershell -ExecutionPolicy Bypass -File backend/scripts/启动演示.ps1`。脚本会在该电脑配置的开发数据库中创建下表账号，再启动该电脑的后端；前端另行运行 `cd frontend`、`npm run dev`。**仅在账号创建成功、且连接到同一开发数据库的演示后端时，下表手机号才可用于登录。** 默认演示验证码为 `482917`，可通过 `-DemoCode` 修改，不发送真实短信。每次登录或注册仍须先点击“获取验证码”，发送间隔、过期与错误次数规则不变。

| 创建用途 | 脚本默认创建的手机号 | 首次创建后的状态 |
| --- | --- | --- |
| 管理员 | 13900003001 | 可进入 `/admin/verification` 审核 |
| 发布者 | 13900001001 | 普通学生，待认证 |
| 取件员 | 13900001002 | 普通学生，待认证 |

也可设置 `CAMPUS_MODE=demo` 和六位 `CAMPUS_DEMO_CODE` 后，仅运行 `.venv\Scripts\python backend/scripts/准备演示账号.py`。脚本可重复执行，保留已有账号、认证、订单和余额；遇到同号不同角色会停止提示，不自动覆盖。账号只写入当前 `CAMPUS_DATABASE_PATH` 指定的本地库（默认 `backend/campus_express.db`），不会随 Git 分享；其他队员需自行运行准备脚本。三个手机号可通过准备脚本的 `--admin-phone`、`--publisher-phone`、`--courier-phone` 参数更换。首次测试时由学生上传虚构资料，再用管理员审核，以覆盖 F2 的真实流程。

演示流程：打开 `/register`，输入虚构手机号并点击“获取验证码”，输入上述环境配置的验证码注册；注册成功后在登录页重新获取登录验证码并登录。验证码发送间隔 60 秒、有效期 300 秒、连续错误 5 次失效，成功使用后不能重用。模拟验证码仅由受控配置指定，不出现在接口响应或日志中；未配置时获取验证码返回 503。环境变量需在启动后端的同一 PowerShell 窗口设置，项目不会自动加载 `.env`。

登录凭证有效期 1800 秒，仅存 `sessionStorage`；退出只撤销当前会话。新账号认证状态为 `not_submitted`，可浏览大厅，但不能发布或接单；在 `/verification` 提交虚构姓名、学号和 JPEG/PNG 照片后进入待审核。照片不超过 5 MB、2500 万像素，服务端检查实际图片内容；照片仅由本人或审核管理员通过鉴权接口读取，不生成公开文件链接。驳回后可重提，历史保留；审核通过后身份准入立即生效。已认证用户可创建订单、充值并支付冻结；后台每秒投递支付事件，B 消费后订单由 paying 变为 paid/待接单，页面每 3 秒查询同步。故障期间保持 paying 并重试，不能直接改订单或重新冻结来绕过投递。

C 的完整演示使用两个已通过学生认证的账号：发布者发布并支付，取件员在 `/tasks` 接单后进入 `/orders`，依次开始取件、核验订单中的取件码、确认送达。后台分别处理资金结算与评价开放，双方可在订单详情或 `/reviews` 各评价一次。信用按本人作为取件员收到的最近 30 条评价计算，新人允许接单，未四舍五入均分低于 3.0 时限制新接单。连续三次输错取件码会锁定订单并通知双方，本期没有用户解锁入口。发布者只能在接单前取消；已付款取消先显示退款处理中，实际到账由 D/B 的事件处理结果决定。订单和信用页每 10 秒刷新，离开页面停止。

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

C 后端场景位于 `backend/tests/test_fulfillment.py`，覆盖抢单与取消竞争、旧版本/重复提交、三次错误锁单、通知/事件失败回滚、完结事件重试、双向评价和最近 30 条信用边界。`test:fulfillment` 自动启动临时后端及 Vue 服务，使用真实 A/B/C/D 接口和虚构账号，不需要手动准备账号或修改开发库；只在测试环境预置审核管理员。

`requirements.txt` 声明后端直接依赖范围，`requirements.lock.txt` 固定当前验证的依赖版本。所有 Python 包安装在项目 `.venv` 中。前端版本由 `package-lock.json` 固定，使用 `npm ci` 安装。

本机若已安装 Edge，也可用 `$env:PW_BROWSER_CHANNEL='msedge'; npm test` 运行冒烟测试，无需另行下载 Chromium。

演示模式下，学生认证页右上角提供“自动审核（演示）”：先提交虚构资料，再点击按钮通过本人当前待审核申请。复用审核事务，保留申请历史、操作者与结果通知，不授予管理员角色；正式模式隐藏按钮并拒绝调用。

## B：发布与大厅验收

B 的 F3/F4 复用 A 的会话与最新认证状态、D 的正式报价与支付冻结、C 的接单状态入口，以及公共 outbox。订单和支付金额由服务端确定，B 不写钱包余额，不根据支付请求超时解除预占。大厅仅展示已支付、待接单、期望送达时间晚于服务端当前时间且非本人发布的订单，可见页面每 10 秒刷新，离开后停止。任务到期后从大厅和当前打开的大厅详情移除，发布者仍可在我的订单中查看和处理。发布页刷新会忽略旧请求及较低版本快照，避免已付款订单显示回待支付。

在根目录运行后端全套测试；在 `frontend` 目录运行以下检查：

```powershell
npm run build
$env:PW_BROWSER_CHANNEL = 'msedge' # 使用已安装的 Edge；使用 Chromium 时无需此行
npm run test:orders
npm run test:fulfillment
```

`test:orders` 覆盖 B 的表单、整数分、筛选、隐私、错误态、移动布局和轮询，A/D 使用测试替身。`test:fulfillment` 使用真实 A/B/C/D 与后台投递器；其中 B 的发布页面用例覆盖真实学生认证、余额不足后充值重试、支付事件发布到大厅、自单隐藏、隐私字段和接单后自动移除。复用现有临时数据库和虚构管理员机制，不修改日常演示库。

手工演示时，先按上文准备并认证发布者和取件员：发布者创建订单，余额不足时充值后重试；取件员在大厅等待付款订单出现并接单，发布者不能在自己的大厅看到该单。付款处理中保持原订单查询，取消和退款沿用 C/D 的既有流程。

B 模块新增质量回归包含后端 23 个、浏览器 8 个用例，覆盖权限隐私、输入边界、事务回滚、并发幂等、故障恢复、键盘操作、屏幕适配及千条订单分页查询。用例与质量要求对应关系、执行命令和本次验证结果见 [B模块质量测试清单](docs/B模块质量测试清单.md)。浏览器用例已纳入 `npm run test:orders`。

## 已有数据库升级冻结字段

保留现有账号、认证、订单、余额和流水，先停止服务并备份数据库；从 backend 目录依次运行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.finance.migrate_frozen
..\.venv\Scripts\python.exe scripts/init_db.py
```

仅全新数据库可直接启动建表；旧库 create_all 不会添加冻结列。重复升级不会重置冻结金额，不要删除共享数据库。细节见 [资金模块升级说明](backend/app/modules/finance/README.md)。

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
