"""仅从受控环境启用演示验证码；JWT 开发密钥持久保存，重启不失效。"""
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    secret: str
    demo_code: str | None = None
    token_seconds: int = 1800
    code_seconds: int = 300
    cooldown_seconds: int = 60
    max_attempts: int = 5

    @classmethod
    def from_environment(cls):
        mode = os.getenv("CAMPUS_MODE", "demo")
        if mode not in {"demo", "production"}:
            raise ValueError("CAMPUS_MODE 必须为 demo 或 production")
        secret = os.getenv("CAMPUS_JWT_SECRET")
        code = os.getenv("CAMPUS_DEMO_CODE") or None
        if mode == "production" and (not secret or code):
            raise ValueError("正式模式须配置签名密钥，且禁止演示验证码")
        if code and not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("演示验证码须为六位数字")
        if not secret:
            directory = Path(__file__).resolve().parents[3] / ".local"
            directory.mkdir(exist_ok=True)
            path = directory / "jwt-secret"
            try:
                with path.open("x", encoding="utf8") as file:
                    file.write(secrets.token_urlsafe(48))
                path.chmod(0o600)
            except FileExistsError:
                pass
            secret = path.read_text(encoding="utf8").strip()
        if len(secret.encode()) < 32:
            raise ValueError("JWT 签名密钥至少为 32 字节")
        return cls(secret=secret, demo_code=code)
