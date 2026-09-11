import importlib.util
from pathlib import Path

import pytest


def load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260909_add_audit_logs.py"
    )
    spec = importlib.util.spec_from_file_location("add_audit_logs_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, values=()):
        self.values = list(values)

    def scalar(self):
        return self.values[0] if self.values else None


class FakeConnection:
    class Dialect:
        name = "mysql"

    def __init__(self):
        self.dialect = self.Dialect()
        self.table_exists = False
        self.ddl = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        if sql == "SELECT DATABASE()":
            return Result(["inventory"])
        if "information_schema.TABLES" in sql:
            return Result([1] if self.table_exists else [])
        self.ddl.append(sql)
        if "CREATE TABLE" in sql:
            self.table_exists = True
        return Result()


def test_migration_creates_complete_table_once_and_is_safe_to_rerun():
    migration = load_migration()
    connection = FakeConnection()

    first = migration._migrate_connection(connection)
    second = migration._migrate_connection(connection)

    assert first == {"tables_created": 1}
    assert second == {"tables_created": 0}
    assert len(connection.ddl) == 1
    ddl = connection.ddl[0]
    for fragment in (
        "CREATE TABLE `audit_logs`",
        "`id` BIGINT",
        "`created_at` DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP())",
        "`user_id` INT NULL",
        "`username` VARCHAR(100) NULL",
        "`action` VARCHAR(10) NOT NULL",
        "`http_method` VARCHAR(10) NOT NULL",
        "`resource` VARCHAR(100) NOT NULL",
        "`resource_id` VARCHAR(255) NULL",
        "`path` VARCHAR(500) NOT NULL",
        "`status_code` SMALLINT",
        "`ip_address` VARCHAR(45)",
        "`summary` TEXT",
        "FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL",
    ):
        assert fragment in ddl
    assert "`created_at` TIMESTAMP" not in ddl
    assert "DEFAULT CURRENT_TIMESTAMP" not in ddl


def test_migration_refuses_non_mysql_connections():
    migration = load_migration()
    connection = FakeConnection()
    connection.dialect.name = "sqlite"

    with pytest.raises(RuntimeError, match="MySQL/MariaDB only"):
        migration._migrate_connection(connection)
