"""公共数据库入口。仅配置连接与会话，不自动建表。"""
from collections.abc import Generator
import os
from pathlib import Path

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_PATH = Path(os.getenv("CAMPUS_DATABASE_PATH", str(Path(__file__).resolve().parents[1] / "campus_express.db"))).resolve()
DATABASE_URL = URL.create("sqlite+pysqlite", database=str(DATABASE_PATH))

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """各业务模块的 ORM 模型统一继承此基类。"""


def get_db() -> Generator[Session, None, None]:
    """供 FastAPI Depends 使用；事务由业务层显式提交。"""
    with SessionLocal() as session:
        yield session
