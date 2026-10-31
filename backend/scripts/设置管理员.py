"""通过本机受控命令授予/撤销已注册账号的审核权限，不提供改角色 HTTP。"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.database import SessionLocal
from app.modules.identity.models import User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="已注册的虚构演示手机号")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--grant", action="store_true", help="授予管理员角色")
    actions.add_argument("--revoke", action="store_true", help="恢复普通学生角色")
    args = parser.parse_args()
    if not re.fullmatch(r"1[3-9][0-9]{9}", args.phone):
        parser.error("手机号格式不正确")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.phone == args.phone))
        if not user:
            parser.error("账号不存在，请先启动服务并注册该账号")
        user.role = "admin" if args.grant else "student"
        db.commit()
    print("权限已更新，下次请求立即生效。")


if __name__ == "__main__":
    main()
