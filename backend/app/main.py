"""公共应用入口。业务路由由对应模块实现后在此注册。"""
from fastapi import FastAPI

app = FastAPI(title="校园快递代取管理系统", version="0.1.0")


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "service": "campus-express"}
