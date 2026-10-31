"""F2 浏览器测试入口：真实 F1/F2，仅在临时库创建虚构审核账号。生产不导入。"""
from contextlib import asynccontextmanager
from app.main import app
from app.database import SessionLocal
from app.modules.identity.models import User

original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        with SessionLocal.begin() as db:
            for uid, phone in (("verification-test-admin", "13900999999"), ("outbox-test-admin", "13900999998")):
                if not db.get(User, uid):
                    db.add(User(uid=uid, phone=phone, role="admin", nickname="演示审核员"))
        yield


app.router.lifespan_context = lifespan
