"""F1 真实身份集成测试；短信为受控模拟，其余使用临时 SQLite。"""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

import app.main as main
from app.database import get_db
from app.modules.identity.config import Settings
from app.modules.identity.models import Challenge, LoginSession, User, VerificationState
from app.modules.identity.service import IdentityService, timestamp
from fixtures import TestPricing


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.processor_patch = patch("app.modules.finance.services.withdraw.start_withdraw_processor")
        self.processor_patch.start()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/identity.db", connect_args={"check_same_thread": False, "timeout": 30})
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.engine_patch = patch.object(main, "engine", self.engine)
        self.engine_patch.start()
        self.settings = Settings(secret="test-only-identity-secret-" * 3, demo_code="482917")
        main.app.state.identity_service = IdentityService(self.settings)
        main.app.state.pricing_service = TestPricing()
        def database():
            with self.sessions() as db:
                yield db
        main.app.dependency_overrides[get_db] = database
        self.client = TestClient(main.app).__enter__()
        self.phone = "13900001001"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        main.app.dependency_overrides.clear()
        for name in ("identity_service", "pricing_service"):
            if hasattr(main.app.state, name): delattr(main.app.state, name)
        self.engine_patch.stop()
        self.processor_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def code(self, purpose, phone=None):
        return self.client.post("/api/auth/codes", json={"phone": phone or self.phone, "purpose": purpose})

    def credentials(self, code="482917", phone=None):
        return {"phone": phone or self.phone, "code": code}

    def register(self, phone=None):
        self.assertEqual(self.code("register", phone).status_code, 200)
        result = self.client.post("/api/auth/register", json=self.credentials(phone=phone))
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["uid"]

    def login(self, phone=None):
        self.assertEqual(self.code("login", phone).status_code, 200)
        result = self.client.post("/api/auth/login", json=self.credentials(phone=phone))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual((result.json()["tokenType"], result.json()["expiresIn"]), ("bearer", 1800))
        return {"Authorization": "Bearer " + result.json()["accessToken"]}

    def test_registration_does_not_login_or_allow_role_override(self):
        self.register()
        self.assertEqual(self.client.get("/api/auth/current").status_code, 401)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(User)).role, "student")
            self.assertEqual(db.scalar(select(func.count()).select_from(LoginSession)), 0)
        result = self.client.post("/api/auth/register", json={**self.credentials(), "role": "admin"})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.client.post("/api/auth/register", json=self.credentials()).status_code, 409)

    def test_full_session_lifecycle_and_restart(self):
        uid = self.register()
        headers = self.login()
        expected = {"uid": uid, "phone": self.phone, "nickname": None, "role": "student"}
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).json(), expected)
        main.app.state.identity_service = IdentityService(self.settings)
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).json(), expected)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).json(), {"loggedOut": True})
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).json()["code"], "SESSION_EXPIRED")
        self.assertEqual(self.client.get("/api/orders", headers=headers).status_code, 401)

    def test_code_cooldown_and_no_secret_leak(self):
        first = self.code("register")
        self.assertEqual(first.json(), {"retryAfter": 60, "expiresIn": 300})
        second = self.code("register")
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["fields"]["retryAfter"], 60)
        with self.sessions() as db:
            row = db.get(Challenge, (self.phone, "register"))
            self.assertNotIn("482917", row.digest)
        with patch("app.modules.identity.service.timestamp", return_value=timestamp() + 60):
            self.assertEqual(self.code("register").status_code, 200)

    def test_code_expiry_and_five_errors(self):
        self.code("register")
        with patch("app.modules.identity.service.timestamp", return_value=timestamp() + 300):
            self.assertEqual(self.client.post("/api/auth/register", json=self.credentials()).status_code, 422)
        for _ in range(5):
            self.assertEqual(self.client.post("/api/auth/register", json=self.credentials("000000")).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/register", json=self.credentials()).status_code, 422)
        with self.sessions() as db:
            self.assertEqual(db.get(Challenge, (self.phone, "register")).attempts, 5)

    def test_code_bound_to_phone_and_purpose(self):
        self.register()
        self.code("register", "13900001002")
        self.assertEqual(self.client.post("/api/auth/register", json=self.credentials(phone="13900001003")).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/login", json=self.credentials()).status_code, 422)

    def test_one_login_code_creates_only_one_session_under_race(self):
        self.register()
        self.code("login")
        def attempt(_):
            return self.client.post("/api/auth/login", json=self.credentials()).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), [200, 422])
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(LoginSession)), 1)

    def test_jwt_signature_expiry_and_sid_are_all_checked(self):
        self.register()
        headers = self.login()
        token = headers["Authorization"].split()[1]
        claims = jwt.decode(token, self.settings.secret, algorithms=["HS256"], audience="campus-express-web")
        for changes in ({"sid": "nonexistent"}, {"exp": timestamp() - 1}, {"sub": "another-user"}, {"aud": "other"}):
            forged = jwt.encode({**claims, **changes}, self.settings.secret, algorithm="HS256")
            self.assertEqual(self.client.get("/api/auth/current", headers={"Authorization": "Bearer " + forged}).status_code, 401)
        bad = jwt.encode(claims, "a-different-secret-with-at-least-32-bytes", algorithm="HS256")
        self.assertEqual(self.client.get("/api/auth/current", headers={"Authorization": "Bearer " + bad}).status_code, 401)
        with self.sessions.begin() as db:
            db.execute(update(LoginSession).values(expires_at=timestamp() - 1))
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).status_code, 401)

    def test_logout_revokes_only_current_sid(self):
        self.register()
        first = self.login()
        with self.sessions.begin() as db:
            db.execute(update(Challenge).where(Challenge.purpose == "login").values(sent_at=timestamp() - 60))
        second = self.login()
        self.client.post("/api/auth/logout", headers=first)
        self.assertEqual(self.client.get("/api/auth/current", headers=first).status_code, 401)
        self.assertEqual(self.client.get("/api/auth/current", headers=second).status_code, 200)

    def test_latest_role_and_verification_are_read_from_database(self):
        uid = self.register()
        headers = self.login()
        expected = {"status": "not_submitted", "verified": False, "rejectReason": None, "applicationId": None, "version": None}
        self.assertEqual(self.client.get("/api/auth/verify-status", headers=headers).json(), expected)
        for status in ("pending", "approved", "rejected"):
            with self.sessions.begin() as db:
                db.merge(VerificationState(uid=uid, status=status, application_id="app-test", version=1, reject_reason="照片不清晰"))
            response = self.client.get("/api/auth/verify-status", headers=headers).json()
            self.assertEqual(response["verified"], status == "approved")
            self.assertEqual(response["rejectReason"], "照片不清晰" if status == "rejected" else None)
        with self.sessions.begin() as db:
            db.execute(update(User).where(User.uid == uid).values(role="admin"))
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).json()["role"], "admin")

    def test_real_identity_admission_to_orders(self):
        from datetime import timedelta
        from app.common import now, iso
        uid = self.register()
        headers = {**self.login(), "Idempotency-Key": str(uuid4())}
        self.assertEqual(self.client.get("/api/orders", headers=headers).status_code, 200)
        draft = {"company": "中通", "code": "private", "stationId": "station_cainiao", "deliveryAreaId": "zone_qinyuan", "address": "沁园302", "size": "small", "weight": "1", "tip": 0, "expectedAt": iso(now() + timedelta(hours=2))}
        self.assertEqual(self.client.post("/api/orders", json=draft, headers=headers).json()["code"], "VERIFICATION_REQUIRED")
        with self.sessions.begin() as db:
            db.add(VerificationState(uid=uid, status="approved", application_id="app-test", version=1))
        self.assertEqual(self.client.post("/api/orders", json=draft, headers=headers).status_code, 201)

    def test_untrusted_identity_and_malformed_inputs(self):
        self.assertEqual(self.client.get("/api/auth/current", headers={"X-User-Id": "admin"}).status_code, 401)
        for body in ({"phone": "invalid", "purpose": "login"}, {"phone": self.phone, "purpose": "admin"}, {"phone": self.phone, "purpose": "login", "uid": "x"}):
            response = self.client.post("/api/auth/codes", json=body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(set(response.json()), {"detail", "code", "fields"})
        self.register()
        headers = self.login()
        self.assertEqual(self.client.get("/api/auth/current?uid=other", headers=headers).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/logout", json={"sid": "other"}, headers=headers).status_code, 422)
        self.assertEqual(self.client.get("/api/auth/current", headers=headers).status_code, 200)

    def test_unconfigured_sms_and_production_settings(self):
        main.app.state.identity_service = IdentityService(Settings(secret=self.settings.secret))
        self.assertEqual(self.code("login").status_code, 503)
        with patch.dict("os.environ", {"CAMPUS_MODE": "production", "CAMPUS_DEMO_CODE": "482917", "CAMPUS_JWT_SECRET": self.settings.secret}):
            with self.assertRaises(ValueError): Settings.from_environment()

    def test_twenty_lifecycle_and_revocation_runs(self):
        for index in range(20):
            phone = f"13900002{index:03d}"
            with self.subTest(run=index + 1):
                self.register(phone)
                headers = self.login(phone)
                self.assertEqual(self.client.get("/api/auth/current", headers=headers).status_code, 200)
                self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 200)
                self.assertEqual(self.client.get("/api/orders", headers=headers).status_code, 401)


if __name__ == "__main__":
    unittest.main()
