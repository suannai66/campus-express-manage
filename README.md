# 校园快递代取管理系统

四人协作的课程项目。前端使用 Vue 3 + JavaScript + Vue Router + Vite，后端使用 Python + FastAPI，数据库采用 SQLAlchemy 2.0 + SQLite，无需单独安装数据库服务。

当前版本是公共界面骨架，已配置数据库连接、ORM 基类和会话依赖，暂未定义业务模型或创建数据表。页面导航、示例任务筛选、详情预览和表单校验可用。登录、实名认证、订单、信用与钱包业务尚未实现。界面不保存身份资料、不发送短信，也不产生交易。

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
```

## 启动后端

Python 3.11+，在项目根目录执行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r backend/requirements.lock.txt
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload
```

健康检查：http://127.0.0.1:8000/api/health ，接口文档：http://127.0.0.1:8000/docs 。当前后端只提供健康检查。开发时 Vite 将 `/api` 代理到 `127.0.0.1:8000`，无需修改页面中的请求地址。

`requirements.txt` 声明后端直接依赖范围，`requirements.lock.txt` 固定当前验证的依赖版本。所有 Python 包安装在项目 `.venv` 中。前端版本由 `package-lock.json` 固定，使用 `npm ci` 安装。

本机若已安装 Edge，也可用 `$env:PW_BROWSER_CHANNEL='msedge'; npm test` 运行冒烟测试，无需另行下载 Chromium。

## 数据库接入

公共入口为 `backend/app/database.py`，提供 `engine`、`SessionLocal`、`Base` 和 `get_db`。SQLite 使用 Python 自带驱动，数据库路径固定为 `backend/campus_express.db`，不随启动时的工作目录变化。

- 后续业务模型统一继承 `Base`，在各自模块中定义。
- 同步业务接口通过 `Depends(get_db)` 获取独立的 `Session`；后台任务使用 `with SessionLocal() as session:`，不要跨请求或任务共享会话。
- 写操作由业务层显式管理事务，例如 `with session.begin():`；会话退出时关闭，未提交的事务会回滚。
- 当前不调用 `Base.metadata.create_all()`，也没有迁移或自动建表逻辑。仅启动应用不会创建数据库文件，首次实际连接时才会创建空数据库文件。
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

开发前先阅读已由队长授权确定的 **v1.1 接口基线**：

- [团队接口约定](docs/团队接口约定.md)：统一记录所有模块接口、分工、权限、状态、事务、事件、联调与验收要求。

金额均为整数分；所有模块使用公共鉴权；数据库统一 SQLAlchemy 2.0 + SQLite。模拟实现也须遵守相同接口。发现问题先向队长反馈，修订契约后同步相关实现。

1. 拉取 `main` 后创建个人功能分支，如 `feat/f1-auth`、`feat/f3-orders`。主分支保留经过验证的基础代码。
2. 优先在自己模块目录实现业务；修改公共样式、路由或应用入口前先与队员沟通。新增组件样式建议使用 Vue 的 `scoped`。
3. 提交 PR 前运行前端构建及相关测试，由另一位队员评审。不要提交 `.idea`、`.venv`、密钥、真实证件和 `node_modules`。
4. API 使用 `/api` 前缀。身份接口沿用 `GET /api/auth/current`，认证状态沿用 `GET /api/auth/verify-status`。字段、枚举与错误返回按 v1.1 契约实现。
5. 接入 F1 后，各模块受保护请求须使用同一后端会话校验（JWT + sid）；前端路由与按钮限制不能代替服务端鉴权。只有认证已通过映射 `verified=true`，接单还需通过信用等业务检查。
6. 审核通知属于 F2；支付成功、订单状态变化和完结等跨模块写操作按团队事件约定实现。当前骨架尚未实现事件或数据库模型。
7. F1/F2 相关可靠性场景每类测试 20 次；本次界面冒烟测试不代替最终业务验收。

## 页面入口

`/` 首页，`/tasks` 大厅，`/publish` 发布，`/orders` 订单，`/reviews` 信用评价，`/wallet` 钱包，`/login` 登录，`/register` 注册，`/verification` 认证。`/admin/verification` 仅为管理员审核页面占位，不包含任何真实数据或可执行审核操作。管理员鉴权由 F1/F2 接入时落实。

生产部署需将非 `/api` 的前端路由回退到 `index.html`，避免刷新子页面返回 404。框架用法可参考 [Vite 文档](https://vite.dev/guide/) 与 [Vue Router 文档](https://router.vuejs.org/guide/)。
