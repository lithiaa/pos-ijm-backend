import importlib.util
from pathlib import Path

import pytest


def load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260909_remove_kategori.py"
    )
    spec = importlib.util.spec_from_file_location("remove_kategori_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, values=()):
        self.values = list(values)

    def scalar(self):
        return self.values[0] if self.values else None

    def scalars(self):
        return self

    def all(self):
        return self.values


class FakeConnection:
    class Dialect:
        name = "mysql"

    def __init__(self):
        self.dialect = self.Dialect()
        self.barang_exists = True
        self.kategori_exists = True
        self.column_exists = True
        self.foreign_keys = ["barang_ibfk_2", "fk`kategori"]
        self.indexes = ["idx_barang_kategori", "kategori_id"]
        self.ddl = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        if sql == "SELECT DATABASE()":
            return Result(["inventory"])
        if "information_schema.TABLES" in sql:
            exists = (
                self.barang_exists
                if parameters["table"] == "barang"
                else self.kategori_exists
            )
            return Result([1] if exists else [])
        if "information_schema.KEY_COLUMN_USAGE" in sql:
            return Result(self.foreign_keys)
        if "information_schema.STATISTICS" in sql:
            return Result(self.indexes)
        if "information_schema.COLUMNS" in sql:
            return Result([1] if self.column_exists else [])

        self.ddl.append(sql)
        if "DROP FOREIGN KEY" in sql:
            self.foreign_keys = []
        elif "DROP INDEX" in sql or "DROP PRIMARY KEY" in sql:
            self.indexes = []
        elif "DROP COLUMN" in sql:
            self.column_exists = False
        elif "DROP TABLE" in sql:
            self.kategori_exists = False
        return Result()


def test_migration_discovers_quotes_drops_in_order_and_is_idempotent():
    migration = load_migration()
    connection = FakeConnection()

    first = migration._migrate_connection(connection)
    first_ddl = list(connection.ddl)
    connection.ddl.clear()
    second = migration._migrate_connection(connection)

    assert first == {
        "foreign_keys_dropped": 2,
        "indexes_dropped": 2,
        "columns_dropped": 1,
        "tables_dropped": 1,
    }
    assert second == {
        "foreign_keys_dropped": 0,
        "indexes_dropped": 0,
        "columns_dropped": 0,
        "tables_dropped": 0,
    }
    assert first_ddl == [
        "ALTER TABLE `barang` DROP FOREIGN KEY `barang_ibfk_2`",
        "ALTER TABLE `barang` DROP FOREIGN KEY `fk``kategori`",
        "ALTER TABLE `barang` DROP INDEX `idx_barang_kategori`",
        "ALTER TABLE `barang` DROP INDEX `kategori_id`",
        "ALTER TABLE `barang` DROP COLUMN `kategori_id`",
        "DROP TABLE `kategori`",
    ]
    assert connection.ddl == []


def test_migration_refuses_non_mysql_connections():
    migration = load_migration()
    connection = FakeConnection()
    connection.dialect.name = "sqlite"

    with pytest.raises(RuntimeError, match="MySQL/MariaDB only"):
        migration._migrate_connection(connection)
