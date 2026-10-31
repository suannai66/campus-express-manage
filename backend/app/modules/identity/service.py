"""身份服务：验证码端口与业务隔离，所有身份均从数据库实时核验。"""
import hashlib
import hmac
import time
from dataclasses import dataclass
from uuid import uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from ...common import fail
from .models import Challenge, LoginSession, User, VerificationState

ISSUER = "campus-express"
AUDIENCE = "campus-express-web"


@dataclass(frozen=True)
class Identity:
    uid: str
    role: str = "student"
    verified: bool = False
    phone: str = ""
    nickname: str | None = None
    sid: str = ""


def timestamp():
    return int(time.time())


def verification_status(db, uid):
    row = db.get(VerificationState, uid)
    return {"status": row.status if row else "not_submitted",
            "verified": bool(row and row.status == "approved"),
            "rejectReason": row.reject_reason if row and row.status == "rejected" else None,
            "applicationId": row.application_id if row else None,
            "version": row.version if row else None}


class DemoCodeProvider:
    """模拟短信，不发送网络请求、不向响应或日志暴露验证码。"""
    def __init__(self, code):
        self.code = code

    def issue(self):
        if self.code is None:
            fail(503, "DEPENDENCY_UNAVAILABLE", "演示验证码尚未配置，请联系项目维护者")
        return self.code


class IdentityService:
    def __init__(self, settings, code_provider=None):
        self.settings = settings
        self.codes = code_provider or DemoCodeProvider(settings.demo_code)

    def digest(self, phone, purpose, challenge_id, code):
        message = f"{phone}:{purpose}:{challenge_id}:{code}".encode()
        return hmac.new(self.settings.secret.encode(), message, hashlib.sha256).hexdigest()

    def send_code(self, db, phone, purpose):
        code = self.codes.issue()
        sent = timestamp()
        challenge_id = str(uuid4())
        values = dict(phone=phone, purpose=purpose, challenge_id=challenge_id,
                      digest=self.digest(phone, purpose, challenge_id, code), sent_at=sent,
                      expires_at=sent + self.settings.code_seconds, attempts=0, consumed=False)
        statement = insert(Challenge).values(**values)
        result = db.execute(statement.on_conflict_do_update(
            index_elements=[Challenge.phone, Challenge.purpose],
            set_=values, where=Challenge.sent_at <= sent - self.settings.cooldown_seconds))
        if result.rowcount != 1:
            row = db.get(Challenge, (phone, purpose))
            retry = max(1, row.sent_at + self.settings.cooldown_seconds - sent)
            fail(429, "RATE_LIMITED", "验证码发送过于频繁", {"retryAfter": retry})
        db.commit()
        return {"retryAfter": self.settings.cooldown_seconds, "expiresIn": self.settings.code_seconds}

    def consume_code(self, db, phone, purpose, code):
        row = db.get(Challenge, (phone, purpose))
        active = bool(row and not row.consumed and row.expires_at > timestamp()
                      and row.attempts < self.settings.max_attempts)
        if not active:
            fail(422, "VALIDATION_ERROR", "验证码无效或已过期，请重新获取", {"code": "请重新获取验证码"})
        conditions = (Challenge.phone == phone, Challenge.purpose == purpose,
                      Challenge.challenge_id == row.challenge_id, Challenge.consumed.is_(False),
                      Challenge.attempts < self.settings.max_attempts, Challenge.expires_at > timestamp())
        expected = self.digest(phone, purpose, row.challenge_id, code)
        if not hmac.compare_digest(row.digest, expected):
            db.execute(update(Challenge).where(*conditions).values(attempts=Challenge.attempts + 1))
            # 错误次数是需要持久化的业务事实，提交后才返回错误。
            db.commit()
            fail(422, "VALIDATION_ERROR", "验证码错误", {"code": "验证码错误，连续五次错误后失效"})
        changed = db.execute(update(Challenge).where(*conditions).values(consumed=True))
        if changed.rowcount != 1:
            fail(422, "VALIDATION_ERROR", "验证码已失效，请重新获取", {"code": "验证码已使用"})

    def register(self, db, phone, code):
        if db.scalar(select(User).where(User.phone == phone)):
            fail(409, "ACCOUNT_EXISTS", "手机号已注册，请直接登录")
        self.consume_code(db, phone, "register", code)
        user = User(uid=str(uuid4()), phone=phone, role="student")
        db.add(user)
        db.flush()
        uid = user.uid
        db.commit()
        return {"uid": uid}

    def login(self, db, phone, code):
        user = db.scalar(select(User).where(User.phone == phone))
        if not user:
            fail(404, "NOT_FOUND", "账号不存在，请先注册")
        self.consume_code(db, phone, "login", code)
        sid = str(uuid4())
        issued = timestamp()
        expires = issued + self.settings.token_seconds
        token = jwt.encode({"sub": user.uid, "sid": sid, "iat": issued, "exp": expires,
                            "iss": ISSUER, "aud": AUDIENCE}, self.settings.secret, algorithm="HS256")
        db.add(LoginSession(sid=sid, uid=user.uid, expires_at=expires, revoked=False))
        db.commit()
        return {"accessToken": token, "tokenType": "bearer", "expiresIn": self.settings.token_seconds}

    def current(self, request, db):
        authorization = request.headers.get("Authorization", "").split()
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            fail(401, "AUTH_REQUIRED", "请先登录")
        try:
            claims = jwt.decode(authorization[1], self.settings.secret, algorithms=["HS256"],
                                issuer=ISSUER, audience=AUDIENCE,
                                options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"]})
            if not isinstance(claims["sid"], str):
                raise jwt.InvalidTokenError()
        except jwt.InvalidTokenError:
            fail(401, "SESSION_EXPIRED", "登录已失效，请重新登录")
        session = db.get(LoginSession, claims["sid"])
        user = db.get(User, claims["sub"])
        if (not session or not user or session.uid != user.uid or session.revoked
                or session.expires_at <= timestamp()):
            fail(401, "SESSION_EXPIRED", "登录已失效，请重新登录")
        return Identity(uid=user.uid, role=user.role, phone=user.phone, nickname=user.nickname,
                        sid=session.sid, verified=verification_status(db, user.uid)["verified"])

    def logout(self, db, identity):
        db.execute(update(LoginSession).where(LoginSession.sid == identity.sid,
                   LoginSession.uid == identity.uid).values(revoked=True))
        db.commit()
        return {"loggedOut": True}
