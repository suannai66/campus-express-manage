# 团队接口约定

版本：v1.1；生效日期：2026-10-30。公共规则与 F1/F2 于本日先批准为 v1.0，队长随后批准凭证、信用、隐私、计价、取消退款和事件责任方案，并授权确定 B/C/D 契约，现统一为团队开发基线。批准不表示接口已经实现。

已批准范围包括公共规则、F1/F2 及 B/C/D 对接边界。详细业务契约见 [B/C/D 业务接口与对接边界](business-contract.md)。本文件保留原名以维护已有链接，已不再是未审定建议稿。登录有效期 1800 秒、验证码有效期 300 秒作为本期配置默认值。

## 公共规则

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

## F1 身份契约

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

## F2 认证契约

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

## 前端会话行为

- 请求工具统一附加 Bearer 凭证，队友不各自读取和管理 Token。
- 401 清理当前凭证并跳转登录，redirect 仅允许本站路径；403 保留登录，根据 code 引导认证或显示权限不足。
- 主动退出先请求后端撤销 sid，再清理前端；退出失败显示明确错误，不声称后端已退出，可再次重试。页面关闭不代表 sid 被撤销，后端仍按到期时间失效。
- sessionStorage 可跨刷新保留、按标签页隔离，但仍可被脚本读取，不能防 XSS。禁止对用户内容使用未经处理的 v-html，不保存验证码、原始证件或服务端密钥。

## 文档责任与版本

A 提供公共鉴权、错误处理和事件投递基础能力；B/C/D 的路由、模型、事件与事务职责以 [业务契约 v1.1](business-contract.md) 为准。模拟实现也遵守同一契约。后续改动须经队长确认，记录版本、改动点及受影响成员；历史评审文档保留当时事实，变更记录在后续阶段。

变更记录：v1.0（2026-10-30）批准公共规则及 F1/F2；v1.1（同日）确定 sessionStorage、初始信用、取件码可见性、计价快照、接单前取消退款、事件重试/资金幂等责任及 B/C/D 详细契约。
