"""本机准备命令：拒绝正式模式、可重复执行、保留已有资料与资金。"""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class DemoAccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "demo.db"
        self.script = Path(__file__).resolve().parents[1] / "scripts" / "准备演示账号.py"
        self.env = {**os.environ, "CAMPUS_DATABASE_PATH": str(self.path), "CAMPUS_MODE": "demo",
                    "CAMPUS_DEMO_CODE": "482917", "CAMPUS_JWT_SECRET": "demo-script-test-secret-" * 3,
                    "PYTHONIOENCODING": "utf-8"}

    def run_script(self, mode="demo"):
        return subprocess.run([sys.executable, str(self.script)], env={**self.env, "CAMPUS_MODE": mode},
            capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_production_refused_before_database_creation(self):
        self.assertNotEqual(self.run_script("production").returncode, 0)
        self.assertFalse(self.path.exists())

    def test_prepare_repeat_preserves_roles_verification_and_balance_and_admin_can_login(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT phone,role FROM identity_users ORDER BY phone").fetchall(),
                [("13900001001", "student"), ("13900001002", "student"), ("13900003001", "admin")])
            uid = db.execute("SELECT uid FROM identity_users WHERE phone='13900001001'").fetchone()[0]
            db.execute("INSERT INTO account(uid,available_cent,frozen_cent,version,created_at) VALUES (?,1234,0,0,'2026-11-02')", (uid,))
            db.execute("INSERT INTO identity_verification_states(uid,status,version,application_id) VALUES (?,'rejected',2,'demo-test-application')", (uid,))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT available_cent FROM account WHERE uid=?", (uid,)).fetchone()[0], 1234)
            self.assertEqual(db.execute("SELECT status FROM identity_verification_states WHERE uid=?", (uid,)).fetchone()[0], "rejected")
            self.assertEqual(db.execute("SELECT count(*) FROM identity_users").fetchone()[0], 3)
        code = '''from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.post('/api/auth/codes',json={'phone':'13900003001','purpose':'login'}).status_code == 200
    login = client.post('/api/auth/login',json={'phone':'13900003001','code':'482917'})
    assert login.status_code == 200
    headers = {'Authorization':'Bearer '+login.json()['accessToken']}
    assert client.get('/api/auth/current',headers=headers).json()['role'] == 'admin'
    assert client.get('/api/admin/verification-applications',headers=headers).status_code == 200
'''
        result = subprocess.run([sys.executable, "-c", code], env={**self.env, "PYTHONPATH": str(self.script.parents[1])},
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_student_is_not_silently_promoted(self):
        self.assertEqual(self.run_script().returncode, 0)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE identity_users SET role='student' WHERE phone='13900003001'")
        self.assertNotEqual(self.run_script().returncode, 0)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT role FROM identity_users WHERE phone='13900003001'").fetchone()[0], "student")
