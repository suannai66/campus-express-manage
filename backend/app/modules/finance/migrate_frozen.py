"""显式升级已有 SQLite 钱包表；运行：python -m app.modules.finance.migrate_frozen。"""
from sqlalchemy import inspect


def upgrade(engine):
    """保留余额和流水，可重复执行；空库须先使用团队初始化脚本建表。"""
    if engine.dialect.name != "sqlite":
        raise ValueError("本升级仅支持 SQLite")
    with engine.connect() as connection:
        # 获取写锁后检查，避免两个升级进程同时添加同一列。
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            inspector = inspect(connection)
            if not inspector.has_table("account"):
                raise ValueError("account 表不存在，请先运行团队数据库初始化脚本")
            if "frozen_cent" in {column["name"] for column in inspector.get_columns("account")}:
                connection.rollback()
                return False
            connection.exec_driver_sql(
                "ALTER TABLE account ADD COLUMN frozen_cent BIGINT NOT NULL DEFAULT 0"
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise


if __name__ == "__main__":
    from ...database import engine
    print("已添加 frozen_cent，原有数据保留" if upgrade(engine) else "frozen_cent 已存在，无需升级")
