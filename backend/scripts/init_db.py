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


def main() -> None:
    Base.metadata.create_all(engine)
    tables = sorted(Base.metadata.tables)
    print(f"建表完成，共 {len(tables)} 张：{', '.join(tables)}")


if __name__ == "__main__":
    main()
