import importlib.util
from pathlib import Path


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "20260917_add_shopee_url.py"
    spec = importlib.util.spec_from_file_location("add_shopee_url_migration", path)
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
        self.column_exists = False
        self.ddl = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        if sql == "SELECT DATABASE()":
            return Result(["inventory"])
        if "information_schema.COLUMNS" in sql:
            return Result([1] if self.column_exists else [])
        self.ddl.append(sql)
        if "ADD COLUMN" in sql:
            self.column_exists = True
        return Result()


def test_migration_adds_shopee_url_once_and_is_idempotent():
    migration = load_migration()
    connection = FakeConnection()

    assert migration._migrate_connection(connection) == {"columns_added": 1}
    assert migration._migrate_connection(connection) == {"columns_added": 0}
    assert connection.ddl == ["ALTER TABLE `barang` ADD COLUMN `shopee_url` VARCHAR(500) NULL"]
