"""仅供本机演示：通过注册服务准备管理员与两名学生，不覆盖已有业务数据。"""
import argparse
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-phone", default="13900003001")
    parser.add_argument("--publisher-phone", default="13900001001")
    parser.add_argument("--courier-phone", default="13900001002")
    args = parser.parse_args()
    if os.getenv("CAMPUS_MODE") != "demo":
        parser.error("必须显式设置 CAMPUS_MODE=demo，正式模式不能准备演示账号")
    if not re.fullmatch(r"[0-9]{6}", os.getenv("CAMPUS_DEMO_CODE", "")):
        parser.error("请先设置六位 CAMPUS_DEMO_CODE，作为本次演示的验证码")
    accounts = [(args.admin_phone, "admin", "演示管理员"),
                (args.publisher_phone, "student", "演示发布者"),
                (args.courier_phone, "student", "演示取件员")]
    if len({phone for phone, _, _ in accounts}) != 3 or any(
            not re.fullmatch(r"1[3-9][0-9]{9}", phone) for phone, _, _ in accounts):
        parser.error("三个演示手机号必须格式正确且互不相同")

    from sqlalchemy import inspect, select
    from app import main as application  # 注册全部模型；不运行应用或后台线程
    from app.database import Base, DATABASE_PATH, SessionLocal, engine
    from app.modules.identity.config import Settings
    from app.modules.identity.models import User
    from app.modules.identity.service import IdentityService

    inspector = inspect(engine)
    if inspector.has_table("account") and "frozen_cent" not in {column["name"] for column in inspector.get_columns("account")}:
        parser.error("已有钱包表缺少冻结字段，请先按 README 备份并执行 migrate_frozen；不要删库")
    Base.metadata.create_all(engine)
    service = IdentityService(Settings.from_environment())
    with SessionLocal() as db:
        # 先检查全部角色，避免用保留号码意外提升已有普通账号权限。
        for phone, role, _ in accounts:
            user = db.scalar(select(User).where(User.phone == phone))
            if user and user.role != role:
                parser.error(f"{phone} 已存在且角色不同；请通过参数选择其他号码，或使用设置管理员.py 明确调整权限")
        for phone, role, nickname in accounts:
            user = db.scalar(select(User).where(User.phone == phone))
            if user is None:
                service.send_code(db, phone, "register")
                uid = service.register(db, phone, service.settings.demo_code)["uid"]
                user = db.get(User, uid)
                user.role, user.nickname = role, nickname
                db.commit()
            print(f"{nickname}：{phone}（{role}）")
    print(f"数据库：{DATABASE_PATH}")
    print("已准备完成。登录前点击获取验证码，再填写 CAMPUS_DEMO_CODE 配置的演示码。")
    print("学生仍需在认证页提交虚构资料，由管理员审核；已有余额、订单和认证状态保持原样。")


if __name__ == "__main__":
    main()
