"""冻结字段的新库默认值与旧库无损升级测试。"""
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.modules.finance.models import Account
from app.modules.finance.migrate_frozen import upgrade
from app.modules.finance.core import wallet_core


class FrozenBalanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def test_new_account_defaults_and_balance_independence(self):
        from app.modules.finance.models import Ledger
        Account.__table__.create(self.engine)
        Ledger.__table__.create(self.engine)
        with Session(self.engine) as db, db.begin():
            wallet_core.credit(db, "alice", 1000, "initial", "recharge")
            account = db.get(Account, "alice")
            self.assertEqual(account.frozen_cent, 0)
            account.frozen_cent = 500
        with Session(self.engine) as db, db.begin():
            wallet_core.debit(db, "alice", 200, "withdraw", "withdrawal")
        with Session(self.engine) as db:
            account = db.get(Account, "alice")
            self.assertEqual((account.available_cent, account.frozen_cent), (800, 500))
        self.assertFalse(upgrade(self.engine))

    def test_upgrade_preserves_existing_data_and_is_repeatable(self):
        with self.engine.begin() as db:
            db.exec_driver_sql("CREATE TABLE account (uid TEXT PRIMARY KEY, available_cent BIGINT NOT NULL)")
            db.exec_driver_sql("INSERT INTO account VALUES ('alice', 3000)")
            db.exec_driver_sql("CREATE TABLE ledger (id INTEGER PRIMARY KEY, delta BIGINT)")
            db.exec_driver_sql("INSERT INTO ledger VALUES (1, 3000)")
        self.assertTrue(upgrade(self.engine))
        with self.engine.begin() as db:
            self.assertEqual(tuple(db.execute(text("SELECT available_cent, frozen_cent FROM account")).one()), (3000, 0))
            db.exec_driver_sql("UPDATE account SET frozen_cent = 100")
            db.exec_driver_sql("INSERT INTO account (uid, available_cent) VALUES ('bob', 0)")
        self.assertFalse(upgrade(self.engine))
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT frozen_cent FROM account WHERE uid='alice'")).scalar_one(), 100)
            self.assertEqual(db.execute(text("SELECT frozen_cent FROM account WHERE uid='bob'")).scalar_one(), 0)
            self.assertEqual(db.execute(text("SELECT delta FROM ledger")).scalar_one(), 3000)

    def test_empty_database_requires_initialization(self):
        with self.assertRaises(ValueError):
            upgrade(self.engine)
