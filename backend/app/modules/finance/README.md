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
