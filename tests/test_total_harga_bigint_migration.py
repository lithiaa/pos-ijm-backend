import importlib.util
from pathlib import Path


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "20260920_total_harga_bigint.py"
    spec = importlib.util.spec_from_file_location("total_harga_bigint_migration", path)
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

    def __init__(self, column_type):
        self.dialect = self.Dialect()
        self.column_type = column_type
        self.ddl = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        if sql == "SELECT DATABASE()":
            return Result(["inventory"])
        if "information_schema.COLUMNS" in sql:
            return Result([self.column_type])
        self.ddl.append(sql)
        if "MODIFY COLUMN" in sql:
            self.column_type = "bigint"
        return Result()


def test_migration_converts_total_harga_to_bigint_once():
    migration = load_migration()
    connection = FakeConnection("int")

    assert migration._migrate_connection(connection) == {"columns_modified": 1}
    assert migration._migrate_connection(connection) == {"columns_modified": 0}
    assert connection.ddl == ["ALTER TABLE `transaksi_stok` MODIFY COLUMN `total_harga` BIGINT NULL"]
