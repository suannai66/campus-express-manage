"""F1 身份事实；F2 当前状态预留，后续审核用例维护此投影。"""
from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


class User(Base):
    __tablename__ = "identity_users"
    __table_args__ = (CheckConstraint("role IN ('student', 'admin')"),)
    uid: Mapped[str] = mapped_column(String(100), primary_key=True)
    phone: Mapped[str] = mapped_column(String(11), unique=True)
    nickname: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(20), default="student")


class LoginSession(Base):
    __tablename__ = "identity_sessions"
    sid: Mapped[str] = mapped_column(String(100), primary_key=True)
    uid: Mapped[str] = mapped_column(String(100), index=True)
    expires_at: Mapped[int] = mapped_column(Integer)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Challenge(Base):
    __tablename__ = "identity_code_challenges"
    phone: Mapped[str] = mapped_column(String(11), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(String(100))
    digest: Mapped[str] = mapped_column(String(64))
    sent_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class VerificationState(Base):
    __tablename__ = "identity_verification_states"
    __table_args__ = (CheckConstraint("status IN ('pending', 'approved', 'rejected')"),)
    uid: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    application_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer)
