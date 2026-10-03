"""Tests for multi-toko MySQL migration idempotence, contract, and safe bootstrap."""
import importlib.util
from pathlib import Path

import pytest


def load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "20261003_multi_toko_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("multi_toko_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = rows

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows


class FakeMySQLConnection:
    class Dialect:
        name = "mysql"

    def __init__(self):
        self.dialect = self.Dialect()
        self.tables = set()
        self.columns = set()  # set of (table, column)
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.statements.append((sql, parameters or {}))

        if "SELECT DATABASE()" in sql:
            return Result("lithia_pos")

        if "information_schema.TABLES" in sql:
            t = (parameters or {}).get("t")
            return Result(1 if t in self.tables else 0)

        if "information_schema.COLUMNS" in sql:
            t = (parameters or {}).get("t")
            c = (parameters or {}).get("c")
            if c:
                return Result(1 if (t, c) in self.columns else 0)
            return Result(1 if t in self.tables else 0)

        if "CREATE TABLE `environments`" in sql or "CREATE TABLE environments" in sql:
            self.tables.add("environments")
            for col in ("id", "slug", "name", "status", "created_at", "updated_at"):
                self.columns.add(("environments", col))
            return Result()

        if "ALTER TABLE `users` ADD COLUMN" in sql or "ALTER TABLE users ADD COLUMN" in sql:
            for col in ("environment_id", "email", "status", "must_change_password", "permissions"):
                if col in sql:
                    self.columns.add(("users", col))
            return Result()

        if "INSERT" in sql:
            return Result(1)

        if "UPDATE" in sql:
            return Result(1)

        return Result()


def test_migration_refuses_non_mysql_connection():
    migration = load_migration()
    conn = FakeMySQLConnection()
    conn.dialect.name = "sqlite"

    with pytest.raises(RuntimeError, match="MySQL/MariaDB only"):
        migration._migrate_connection(conn)


def test_migration_creates_environments_and_adds_user_columns_idempotently():
    migration = load_migration()
    conn = FakeMySQLConnection()
    # Baseline existing tables
    conn.tables.add("users")
    for col in ("id", "username", "password_hash", "nama", "role", "created_at"):
        conn.columns.add(("users", col))

    # First run
    res1 = migration._migrate_connection(conn)
    assert res1["environments_created"] is True
    assert "environment_id" in res1["columns_added"]
    assert "email" in res1["columns_added"]
    assert "status" in res1["columns_added"]
    assert "must_change_password" in res1["columns_added"]
    assert "permissions" in res1["columns_added"]

    sqls = "\n".join(s[0] for s in conn.statements)
    assert "CREATE TABLE" in sqls and "environments" in sqls
    assert "slug" in sqls and "status" in sqls
    assert "lithia-autoparts" in sqls
    assert "LOWER(role) != 'platform_owner'" in sqls

    # Second run should be fully idempotent
    statements_before = len(conn.statements)
    res2 = migration._migrate_connection(conn)
    assert res2["environments_created"] is False
    assert len(res2["columns_added"]) == 0

    # Ensure no DDL was run during second run
    new_sqls = [s[0] for s in conn.statements[statements_before:]]
    assert not any("CREATE TABLE" in s for s in new_sqls)
    assert not any("ALTER TABLE" in s for s in new_sqls)


def test_migration_safe_bootstrap_strategy_no_hardcoded_credentials():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "20261003_multi_toko_foundation.py"
    )
    content = path.read_text()

    # Must document manual bootstrap requirement
    assert "bootstrap" in content.lower()
    # Must not contain default passwords or credentials output
    forbidden_terms = ["password123", "admin123", "secret123", "default_password"]
    for term in forbidden_terms:
        assert term not in content.lower()
