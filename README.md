# 校园快递代取管理系统

本项目由四人团队开发，用于体验校园内发布代取需求、接单配送和评价信用的完整流程。系统提供学生注册登录、实名认证审核、代取大厅、订单履约、模拟钱包及资金结算等功能。

项目采用 Vue 3 + JavaScript 构建前端，Python + FastAPI 构建后端，使用 SQLAlchemy 2.0 + SQLite 存储数据，无需单独安装数据库服务。

当前为课程演示版本：验证码和资金渠道均为模拟实现，不发送真实短信，不产生真实资金交易。首页部分卡片为示例内容，实际订单请通过发布、大厅和订单页面查看。

## 快速开始

以下步骤适用于 Windows PowerShell。请准备 Python 3.11+ 和 Node.js 22.12+（或 24 LTS），并在项目根目录开始操作。

### 1. 安装后端依赖

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.lock.txt
```

Python 依赖安装在项目的 `.venv` 中。已有旧版数据库的体验者，请先阅读下文的“已有数据库升级”。

### 2. 创建本地演示账号并启动后端

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/启动演示.ps1
```

启动脚本会在当前配置的本地数据库中准备一个管理员和两名学生账号，并启用演示验证码。看到应用启动完成的提示后，可访问[健康检查](http://127.0.0.1:8000/api/health)或[接口文档](http://127.0.0.1:8000/docs)。

### 3. 启动前端

另开一个终端，从项目根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

打开终端显示的访问地址，通常为 [http://localhost:5173](http://localhost:5173)。体验注册、订单和钱包等功能时，请保持前后端同时运行。只启动前端可预览页面，但依赖后端的功能无法使用。

## 演示账号与验证码

仓库提供账号创建脚本，不包含已创建的账号或数据库。每位体验者需先完成上述启动步骤，在自己的数据库中创建账号；这些账号仅能登录使用该数据库的后端服务，不能用于访问其他人的本地环境。

| 体验角色 | 脚本默认创建的手机号 | 首次创建后的状态 |
| --- | --- | --- |
| 管理员 | 13900003001 | 可审核学生认证申请 |
| 发布者 | 13900001001 | 普通学生，待认证 |
| 取件员 | 13900001002 | 普通学生，待认证 |

默认演示验证码为 **`482917`**。在登录页填写手机号后，先点击“获取验证码”，再输入演示码即可登录。也可在注册页使用其他虚构手机号注册。注册与登录需要分别获取验证码。

验证码发送间隔为 60 秒，有效期为 300 秒；连续输错 5 次后失效，成功使用后不能重用。演示码由启动配置指定，不会出现在接口响应或后端日志中。未配置演示码时，获取验证码会提示服务尚未配置。

启动脚本可重复运行，已有账号的认证、订单和余额会保留。若默认手机号已存在且角色不同，脚本会停止提示，不会自动修改其角色。

需要更换演示验证码时，可在后端停止后运行：

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/启动演示.ps1 -DemoCode 654321
```

## 推荐体验流程

建议使用不同浏览器或无痕窗口分别登录管理员、发布者和取件员，便于同时观察各角色的操作结果。

1. **提交学生认证。** 发布者和取件员分别进入“学生认证”，填写虚构姓名、学号并上传 JPEG/PNG 图片。可使用仓库中的[虚构学生证样例](frontend/tests/fixtures/学生证样例.png)。新账号可浏览大厅，认证通过后才能发布或接单。
2. **审核认证申请。** 管理员进入[认证审核页面](http://localhost:5173/admin/verification)，查看申请及证件图片，选择通过或填写理由驳回。学生可查看审核结果和通知；被驳回的申请可重新提交。
3. **充值并发布需求。** 发布者进入钱包模拟充值，再填写取件信息、送达地址和期望时间，确认报价、创建订单并支付。支付后等待状态同步，订单进入“待接单”后会出现在其他用户的大厅中。
4. **接单并完成配送。** 取件员在大厅接单，进入“我的订单”，依次执行开始取件、核验取件码和确认送达。接单后才能查看本单取件码及详细门牌。送达后系统自动结算收益，可在钱包查看余额和流水。
5. **互评与查看信用。** 送达结果同步后，双方可在订单详情或评价页各提交一次评价。信用分只统计作为取件员收到的最近 30 条有效评价；新人可接单，未四舍五入均分低于 3.0 时限制接取新订单，已接订单仍需完成。

还可另建订单体验取消退款：发布者在接单前取消已付款订单，页面先显示退款处理中，完成后钱包恢复对应金额。支付处理中不能取消，接单后不开放用户取消。

取件码连续输错三次会锁定订单，并通知双方；同一次请求重试不会重复计数。当前版本没有用户自行解锁入口。评价提交后不可修改。

认证照片最多 5 MB、2500 万像素，仅本人及审核管理员可查看。订单、认证和信用页面会定时刷新，也可手动刷新；状态同步需要短暂等待，请勿通过重复付款来推进订单。

## 页面入口

| 页面 | 路径 |
| --- | --- |
| 首页 | `/` |
| 代取大厅 | `/tasks` |
| 发布需求 | `/publish` |
| 我的订单 | `/orders` |
| 评价与信用 | `/reviews` |
| 模拟钱包 | `/wallet` |
| 登录 / 注册 | `/login`、`/register` |
| 学生认证与通知 | `/verification` |
| 管理员认证审核 | `/admin/verification` |

## 启动配置与账号维护

前端开发服务默认将 `/api` 请求代理到 `127.0.0.1:8000`。如需手动启动后端并自行配置环境变量，可在项目根目录执行：

```powershell
$env:CAMPUS_MODE = 'demo'
$env:CAMPUS_DEMO_CODE = '482917'
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload
```

环境变量需在启动后端的同一终端设置，项目不会自动加载 `.env`。只需创建账号、不启动服务时，可在配置以上两个变量后执行：

```powershell
.venv\Scripts\python backend/scripts/准备演示账号.py
```

准备脚本支持 `--admin-phone`、`--publisher-phone`、`--courier-phone` 参数，用于更换默认手机号。账号及业务数据默认保存在 `backend/campus_express.db`，也可通过 `CAMPUS_DATABASE_PATH` 指定其他路径；账号创建脚本和后端服务需使用同一数据库。

如需将其他已注册的虚构账号设为管理员，可由环境维护者执行以下命令，并替换对应手机号：

```powershell
.venv\Scripts\python backend/scripts/设置管理员.py --phone 13900003001 --grant
```

使用 `--revoke` 可恢复普通学生角色，权限变更在下次请求时生效。普通注册页面不能指定管理员角色。

登录凭证有效期为 1800 秒，仅存于 `sessionStorage`；退出登录只撤销当前会话。演示环境未配置 `CAMPUS_JWT_SECRET` 时，会在 `backend/.local/jwt-secret` 生成持久密钥，删除该文件会使已有登录凭证失效。

`CAMPUS_MODE=production` 要求配置至少 32 字节的随机 `CAMPUS_JWT_SECRET`，并取消演示验证码配置；该模式禁用模拟充值确认。当前版本尚未接入真实短信、真实支付渠道，切换模式不代表已具备正式运营能力。

## 已有数据库升级

全新数据库由应用启动时自动建表。若使用尚未添加冻结余额字段的旧版数据库，请先停止后端并备份数据，再从 `backend` 目录执行：

```powershell
..\.venv\Scripts\python.exe -m app.modules.finance.migrate_frozen
..\.venv\Scripts\python.exe scripts/init_db.py
```

升级保留现有账号、认证、订单、余额及流水，重复执行不会重置冻结金额。`create_all` 只创建缺失的表，不会添加已有表的列。详细步骤见[资金模块升级说明](backend/app/modules/finance/README.md)。

## 自动化测试与构建

后端测试在项目根目录运行：

```powershell
.venv\Scripts\python -m pip install -r backend/requirements-dev.txt
$env:PYTHONPATH = 'backend'
.venv\Scripts\python -m unittest discover -s backend/tests -v
```

测试使用临时 SQLite 数据库和虚构资料，不修改体验环境的数据。身份与认证的关键场景包含每类 20 轮可靠性验证；交易测试覆盖支付、结算、退款、提现回补、并发竞争及事件失败恢复。

前端测试与构建在 `frontend` 目录运行：

```powershell
npx playwright install chromium
npm test                   # 页面冒烟测试
npm run test:identity      # 注册登录、会话恢复与退出
npm run test:verification  # 认证审核、通知与照片权限
npm run test:orders        # 发布与大厅，使用隔离依赖替身
npm run test:fulfillment   # 接单履约、互评、信用、锁单与退款
npm run test:finance       # 充值支付、结算、退款与提现回补
npm run build              # 生产构建
npm run preview            # 预览构建产物
```

浏览器集成测试会启动临时服务并准备测试账号，无需手动创建。已安装 Edge 时，可先设置 `$env:PW_BROWSER_CHANNEL='msedge'`，使用系统浏览器运行测试。

后端依赖版本固定于 `backend/requirements.lock.txt`，直接依赖范围记录在 `backend/requirements.txt`；前端依赖版本由 `frontend/package-lock.json` 固定。

## 开发与协作

团队模块、接口、权限、状态、事务、事件与验收要求统一维护在[团队接口约定](docs/团队接口约定.md)中。参与开发前请阅读该约定，涉及接口或公共能力的变更需同步维护。

| 模块 | 负责人 | 前端目录 | 后端目录 |
| --- | --- | --- | --- |
| 注册登录与学生认证 | A | `frontend/src/features/identity/` | `backend/app/modules/identity/` |
| 需求发布与代取大厅 | B | `frontend/src/features/orders/` | `backend/app/modules/orders/` |
| 接单履约与评价信用 | C | `frontend/src/features/fulfillment/` | `backend/app/modules/fulfillment/` |
| 报价支付与模拟钱包 | D | `frontend/src/features/finance/` | `backend/app/modules/finance/` |

公共导航、样式和路由分别位于 `frontend/src/App.vue`、`frontend/src/styles.css` 和 `frontend/src/router/index.js`，页面请求统一使用 `frontend/src/services/http.js`。后端数据库入口为 `backend/app/database.py`，各模块模型继承同一 `Base`；写操作由业务用例统一提交，消费者与公共 outbox 遵守同事务约定。

功能分支经评审和相关测试后合入 `main`。数据库、密钥、真实证件、`.idea`、`.venv` 和 `node_modules` 不提交到仓库。事件维护与重试命令见[团队接口约定第 12 节](docs/团队接口约定.md#12-事件重试与幂等)。

生产构建部署时，非 `/api` 的前端路由需回退到 `index.html`，以支持子页面刷新。框架与数据库的使用可参考 [Vue 文档](https://vuejs.org/)、[Vite 文档](https://vite.dev/guide/)及 [SQLAlchemy 文档](https://docs.sqlalchemy.org/en/20/)。
