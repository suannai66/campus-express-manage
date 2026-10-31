"""F2 申请、权限、审核事务及可靠性测试，全部使用虚构资料和临时库。"""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import unittest
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from PIL import Image
from sqlalchemy import func, select, update

import test_identity as identity_tests
from app.modules.identity.models import (User, VerificationApplication as Application,
    VerificationState as State, VerificationPhoto as Photo, VerificationReview as Review,
    VerificationNotification as Notification)


def image_bytes(kind="PNG"):
    stream = BytesIO()
    Image.new("RGB", (60, 30), "green").save(stream, format=kind)
    return stream.getvalue()


class VerificationTests(unittest.TestCase):
    register = identity_tests.IdentityTests.register
    login = identity_tests.IdentityTests.login
    code = identity_tests.IdentityTests.code
    credentials = identity_tests.IdentityTests.credentials

    def setUp(self):
        identity_tests.IdentityTests.setUp(self)
        self.uid = self.register()
        self.owner = self.login()
        admin_uid = self.register("13900003001")
        with self.sessions.begin() as db:
            db.execute(update(User).where(User.uid == admin_uid).values(role="admin"))
        self.admin = self.login("13900003001")
        self.register("13900003002")
        self.other = self.login("13900003002")

    def tearDown(self):
        identity_tests.IdentityTests.tearDown(self)

    def submit(self, content=None, headers=None, **fields):
        return self.client.post("/api/auth/verification-applications", headers=headers or self.owner,
            data={"realName": " 测试同学 ", "studentNo": " 202600123456 ", **fields},
            files={"photo": ("../../fake.png", image_bytes() if content is None else content, "image/png")})

    def review(self, application, decision="approved", reason=None, version=1, headers=None):
        return self.client.post(f"/api/admin/verification-applications/{application}/review",
            headers=headers or self.admin, json={"decision": decision, "rejectReason": reason, "version": version})

    def state(self):
        return self.client.get("/api/auth/verify-status", headers=self.owner).json()

    def test_submit_and_approve_updates_state_audit_and_notification(self):
        result = self.submit()
        self.assertEqual(result.status_code, 201, result.text)
        application = result.json()["applicationId"]
        self.assertEqual(self.state()["status"], "pending")
        self.assertFalse(self.state()["verified"])
        with self.sessions() as db:
            self.assertEqual(db.get(Application, application).real_name, "测试同学")
            self.assertEqual(db.get(Application, application).student_no, "202600123456")
        self.assertEqual(self.review(application).json(), {"applicationId": application, "status": "approved", "version": 2})
        self.assertEqual(self.state()["version"], 2)
        self.assertTrue(self.state()["verified"])
        notifications = self.client.get("/api/auth/verification-notifications", headers=self.owner).json()
        self.assertEqual(notifications["total"], 1)
        self.assertEqual(notifications["items"][0]["status"], "approved")
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Review)), 1)
        self.assertEqual(self.submit().status_code, 409)

    def test_rejected_resubmission_preserves_history_and_reason(self):
        first = self.submit().json()["applicationId"]
        self.assertEqual(self.review(first, "rejected", " 学号不清晰 ").status_code, 200)
        self.assertEqual(self.state()["rejectReason"], "学号不清晰")
        second = self.submit().json()["applicationId"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.state()["version"], 1)
        self.assertIsNone(self.state()["rejectReason"])
        history = self.client.get("/api/auth/verification-applications", headers=self.owner).json()
        self.assertEqual(history["total"], 2)
        self.assertTrue(all(row["studentNo"] == "********3456" for row in history["items"]))
        self.assertEqual(self.review(first).status_code, 409)

    def test_photo_checks_real_type_and_content_not_filename_or_mime(self):
        corrupt = bytearray(image_bytes())
        corrupt[45] ^= 1
        for content in (b"", b"not a picture", image_bytes("GIF"), image_bytes()[:40], bytes(corrupt), b"x" * (5*1024*1024+1)):
            self.assertEqual(self.submit(content).status_code, 422)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Application)), 0)
        result = self.submit(image_bytes("JPEG"))
        self.assertEqual(result.status_code, 201)
        response = self.client.get(f"/api/auth/verification-applications/{result.json()['applicationId']}/photo", headers=self.owner)
        self.assertEqual(response.headers["content-type"], "image/jpeg")

    def test_photo_and_application_permissions(self):
        application = self.submit().json()["applicationId"]
        photo = f"/api/auth/verification-applications/{application}/photo"
        self.assertEqual(self.client.get(photo).status_code, 401)
        self.assertEqual(self.client.get(photo, headers=self.other).status_code, 404)
        for headers in (self.owner, self.admin):
            result = self.client.get(photo, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual(result.content, image_bytes())
        for path in ("/api/admin/verification-applications", f"/api/admin/verification-applications/{application}"):
            self.assertEqual(self.client.get(path, headers=self.owner).status_code, 403)
        self.assertEqual(self.review(application, headers=self.owner).status_code, 403)
        self.assertEqual(self.client.get("/api/auth/verification-applications", headers=self.other).json()["total"], 0)
        self.assertEqual(self.client.get("/api/auth/verification-notifications", headers=self.other).json()["total"], 0)

    def test_admin_list_masks_details_and_filters_status(self):
        application = self.submit().json()["applicationId"]
        listing = self.client.get("/api/admin/verification-applications?status=pending", headers=self.admin).json()
        self.assertEqual(listing["total"], 1)
        row = listing["items"][0]
        self.assertNotIn("photo", row)
        self.assertNotIn("content", row)
        self.assertNotEqual(row["studentNo"], "202600123456")
        detail = self.client.get(f"/api/admin/verification-applications/{application}", headers=self.admin).json()
        self.assertEqual(detail["studentNo"], "202600123456")
        self.assertNotIn("photoPath", detail)
        self.review(application)
        self.assertEqual(self.client.get("/api/admin/verification-applications?status=pending", headers=self.admin).json()["total"], 0)

    def test_review_validation_stale_version_and_role_change(self):
        application = self.submit().json()["applicationId"]
        for args in (("rejected", "   ", 1), ("approved", "无关理由", 1), ("approved", None, True)):
            self.assertEqual(self.review(application, *args).status_code, 422)
        self.assertEqual(self.review(application, version=2).status_code, 409)
        self.assertEqual(self.state()["status"], "pending")
        with self.sessions.begin() as db:
            db.execute(update(User).where(User.phone == "13900003001").values(role="student"))
        self.assertEqual(self.review(application).status_code, 403)

    def test_submit_rejects_extra_fields_and_duplicate_parts(self):
        self.assertEqual(self.submit(role="admin").status_code, 422)
        self.assertEqual(self.submit(realName=" ").status_code, 422)
        self.assertEqual(self.submit(studentNo="a"*31).status_code, 422)
        result = self.client.post("/api/auth/verification-applications", headers=self.owner,
            data={"realName":"测试","studentNo":"2026001"},
            files=[("photo",("a.png",image_bytes(),"image/png")),("photo",("b.png",image_bytes(),"image/png"))])
        self.assertEqual(result.status_code, 422)

    def test_pagination_and_unknown_parameters(self):
        for prefix, headers in (("/api/auth/verification-applications", self.owner), ("/api/auth/verification-notifications",self.owner),("/api/admin/verification-applications", self.admin)):
            result = self.client.get(prefix, headers=headers).json()
            self.assertEqual((result["page"], result["pageSize"]), (1,20))
            for query in ("page=0", "pageSize=101", "page=1.0", "uid=other"):
                self.assertEqual(self.client.get(prefix+"?"+query, headers=headers).status_code, 422)

    def test_notification_failure_rolls_back_entire_review(self):
        application = self.submit().json()["applicationId"]
        with patch("app.modules.identity.verification.Notification", side_effect=RuntimeError("injected notification failure")):
            with self.assertRaises(RuntimeError): self.review(application)
        self.assertEqual(self.state()["status"], "pending")
        with self.sessions() as db:
            self.assertEqual(db.get(Application, application).version, 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Review)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(Notification)), 0)
        self.assertEqual(self.review(application).status_code, 200)

    def test_admin_cli_updates_only_an_existing_account(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "设置管理员.py"
        env = {**os.environ, "CAMPUS_DATABASE_PATH": str(Path(self.temp.name) / "identity.db"), "PYTHONUTF8": "1"}
        for phone, action, expected in (("13900003002", "--grant", 0), ("13900003002", "--revoke", 0), ("13900009999", "--grant", 2)):
            result = subprocess.run([sys.executable, str(script), "--phone", phone, action], env=env, capture_output=True)
            self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(self.client.get("/api/auth/current", headers=self.other).json()["role"], "student")

    def test_history_and_notifications_paginate_without_exposing_photos(self):
        with self.sessions.begin() as db:
            for i in range(21):
                application_id = f"history-{i}"
                db.add(Application(application_id=application_id, uid=self.uid, real_name="虚构学生",
                    student_no="202600123456", status="rejected", version=2, created_at=f"2026-10-31T00:00:{i:02d}Z"))
                db.add(Notification(notification_id=f"notice-{i}", application_id=application_id, uid=self.uid,
                    status="rejected", version=2, reject_reason="演示驳回", created_at=f"2026-10-31T00:00:{i:02d}Z"))
        for path in ("/api/auth/verification-applications", "/api/auth/verification-notifications"):
            first = self.client.get(path, headers=self.owner).json()
            last = self.client.get(path+"?page=2", headers=self.owner).json()
            self.assertEqual((first["total"],len(first["items"]),len(last["items"])), (21,20,1))
            self.assertEqual(first["items"][0]["applicationId"], "history-20")
            self.assertNotIn("content",first["items"][0])

    def test_twenty_runs_of_submit_review_and_retry_races(self):
        # 每轮包含两个提交者与两个审核者的竞争，以及驳回重提、旧审核拒绝和通知去重。
        for run in range(20):
            with self.subTest(run=run+1):
                if run:
                    # 新虚构学生账号，每轮独立验证完整流程。
                    phone=f"1390040{run:04d}"
                    self.uid=self.register(phone);self.owner=self.login(phone)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(lambda _:self.submit(), range(2)))
                self.assertEqual(sorted(result.status_code for result in results), [201,409])
                application=next(r.json()["applicationId"] for r in results if r.status_code==201)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    statuses=list(pool.map(lambda _:self.review(application,"rejected","照片不清晰").status_code, range(2)))
                self.assertEqual(sorted(statuses), [200,409])
                self.assertEqual(self.client.get("/api/auth/verification-notifications",headers=self.owner).json()["total"],1)
                new=self.submit().json()["applicationId"]
                self.assertNotEqual(new,application)
                self.assertEqual(self.review(application).status_code,409)
                with patch("app.modules.identity.verification.Notification", side_effect=RuntimeError("injected notification failure")):
                    with self.assertRaises(RuntimeError): self.review(new)
                self.assertEqual(self.state()["status"],"pending")
                self.assertEqual(self.review(new).status_code,200)
                self.assertTrue(self.state()["verified"])
                self.assertEqual(self.review(new).status_code,409)
                self.assertEqual(self.client.get("/api/auth/verification-notifications",headers=self.owner).json()["total"],2)


if __name__ == "__main__": unittest.main()
