"""统一错误、严格输入、持久化请求幂等和时间格式。"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def now():
    return datetime.now(timezone.utc)


def iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def fail(status, code, detail, fields=None):
    raise HTTPException(status, {"detail": detail, "code": code, "fields": fields or {}})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Money = Annotated[int, Field(strict=True, ge=0, le=99900)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)]


class VersionInput(Input):
    version: int = Field(strict=True, gt=0)


class Idempotency(Base):
    __tablename__ = "request_idempotency"
    __table_args__ = (UniqueConstraint("uid", "operation", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


def fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def replay(db, uid, operation, key, body):
    from sqlalchemy import select
    row = db.scalar(select(Idempotency).where(Idempotency.uid == uid,
                    Idempotency.operation == operation, Idempotency.key == key))
    if row and row.digest != fingerprint(body):
        fail(409, "IDEMPOTENCY_CONFLICT", "相同提交标识不能用于不同内容")
    return row.result if row else None


def remember(db, uid, operation, key, body, result):
    db.add(Idempotency(uid=uid, operation=operation, key=key,
                       digest=fingerprint(body), result=result))
