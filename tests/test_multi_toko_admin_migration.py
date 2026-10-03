import importlib.util
from pathlib import Path

import pytest


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "20261003_multi_toko_admin.py"
    spec = importlib.util.spec_from_file_location("multi_toko_admin_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, value=None): self.value = value
    def scalar(self): return self.value
    def fetchall(self): return self.value if isinstance(self.value, list) else []


class FakeMySQL:
    class Dialect: name = "mysql"

    def __init__(self):
        self.dialect = self.Dialect()
        self.tables = {"environments", "users"}
        self.columns = {
            ("environments", name) for name in ("id", "slug", "name", "status")
        } | {
            ("users", name) for name in ("id", "environment_id", "username", "email", "role")
        }
        self.indexes = set()
        self.sql = []

    def execute(self, statement, params=None):
        sql = str(statement); params = params or {}; self.sql.append((sql, params))
        if "SELECT DATABASE()" in sql: return Result("pos")
        if "information_schema.TABLES" in sql: return Result(int(params.get("t") in self.tables))
        if "information_schema.COLUMNS" in sql: return Result(int((params.get("t"), params.get("c")) in self.columns))
        if "information_schema.STATISTICS" in sql: return Result(int((params.get("t"), params.get("n")) in self.indexes))
        if sql.startswith("CREATE TABLE"):
            self.tables.add(sql.split("`")[1])
        if "ADD COLUMN" in sql:
            parts = sql.split("`"); self.columns.add((parts[1], parts[3]))
        if "ADD UNIQUE INDEX" in sql or "ADD UNIQUE KEY" in sql or "ADD INDEX" in sql:
            parts = sql.split("`"); self.indexes.add((parts[1], parts[3]))
        return Result()


def test_admin_migration_creates_all_tables_columns_and_unique_email_idempotently():
    migration = load_migration(); conn = FakeMySQL()
    first = migration._migrate_connection(conn)
    assert set(first["tables_created"]) == set(migration.NEW_TABLES)
    assert set(first["environment_columns_added"]) == {
        "business_type", "logo_url", "address", "phone", "timezone", "currency"
    }
    sql = "\n".join(row[0] for row in conn.sql)
    assert "uq_users_email" in sql
    assert "token_hash" in sql
    assert "request_key" in sql
    assert "reason" in sql and "expires_at" in sql and "revoked_at" in sql
    assert "environment_copy_jobs" in sql and "status" in sql and "progress" in sql
    before = len(conn.sql)
    second = migration._migrate_connection(conn)
    assert second == {"tables_created": [], "environment_columns_added": [], "indexes_added": []}
    assert not any("CREATE TABLE" in row[0] or "ADD COLUMN" in row[0] or "ADD INDEX" in row[0] for row in conn.sql[before:])


def test_admin_migration_rejects_non_mysql():
    migration = load_migration(); conn = FakeMySQL(); conn.dialect.name = "sqlite"
    with pytest.raises(RuntimeError, match="MySQL/MariaDB"):
        migration._migrate_connection(conn)


def test_admin_migration_scopes_provision_and_invitation_users_to_environment():
    migration = load_migration(); conn = FakeMySQL()
    migration._migrate_connection(conn)
    migration._migrate_connection(conn)
    sql = "\n".join(row[0] for row in conn.sql)

    parent_key = "ALTER TABLE `users` ADD UNIQUE KEY `uq_users_id_env` (id, environment_id)"
    assert parent_key in sql
    assert sql.index(parent_key) < sql.index("CREATE TABLE `environment_provision_requests`")
    assert "CONSTRAINT `fk_provision_request_administrator_env` FOREIGN KEY (`administrator_id`, `environment_id`) REFERENCES `users` (`id`, `environment_id`) ON DELETE RESTRICT" in sql
    assert "CONSTRAINT `fk_invitation_user_env` FOREIGN KEY (`user_id`, `environment_id`) REFERENCES `users` (`id`, `environment_id`) ON DELETE RESTRICT" in sql
    assert "FOREIGN KEY (`administrator_id`) REFERENCES `users` (`id`)" not in sql
    assert "FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)" not in sql
    assert "environment_provision_requests` child LEFT JOIN `users` parent" in sql
    assert "user_invitations` child LEFT JOIN `users` parent" in sql
