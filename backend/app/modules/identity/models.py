"""F1 身份事实；F2 当前状态预留，后续审核用例维护此投影。"""
from sqlalchemy import Boolean, CheckConstraint, Integer, String, LargeBinary, Index, text
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


class VerificationApplication(Base):
    __tablename__ = "identity_verification_applications"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')"),
        Index("uq_verification_pending_user", "uid", unique=True, sqlite_where=text("status = 'pending'")),
    )
    application_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    uid: Mapped[str] = mapped_column(String(100), index=True)
    real_name: Mapped[str] = mapped_column(String(30))
    student_no: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1)
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[str] = mapped_column(String(40))
    reviewed_at: Mapped[str | None] = mapped_column(String(40))
    reviewer_uid: Mapped[str | None] = mapped_column(String(100))


class VerificationPhoto(Base):
    __tablename__ = "identity_verification_photos"
    application_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(30))
    content: Mapped[bytes] = mapped_column(LargeBinary)


class VerificationReview(Base):
    __tablename__ = "identity_verification_reviews"
    review_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(100), unique=True)
    reviewer_uid: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(20))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))


class VerificationNotification(Base):
    __tablename__ = "identity_verification_notifications"
    notification_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(100), unique=True)
    uid: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20))
    reject_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String(40))
