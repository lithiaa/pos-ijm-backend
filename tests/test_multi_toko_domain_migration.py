import importlib.util
from pathlib import Path

import pytest


def load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations" / "20261003_multi_toko_domain.py"
    spec = importlib.util.spec_from_file_location("domain_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Result:
    def __init__(self, value=None): self.value = value
    def scalar(self): return self.value
    def fetchall(self): return []


class FakeMySQL:
    class Dialect: name = "mysql"
    def __init__(self):
        self.dialect = self.Dialect(); self.columns = set(); self.indexes = set(); self.sql = []
    def execute(self, statement, params=None):
        sql = str(statement); self.sql.append(sql)
        if "SELECT DATABASE()" in sql: return Result("pos")
        if "FROM environments" in sql: return Result(1)
        if "information_schema.COLUMNS" in sql:
            return Result(int(((params or {}).get("t"), (params or {}).get("c")) in self.columns))
        if "information_schema.STATISTICS" in sql:
            return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.indexes))
        if "ADD COLUMN environment_id" in sql:
            table = sql.split("`")[1]; self.columns.add((table, "environment_id"))
        if "ADD INDEX" in sql or "ADD UNIQUE INDEX" in sql:
            parts = sql.split("`"); self.indexes.add((parts[1], parts[3]))
        return Result()


def test_domain_migration_adds_and_backfills_all_tables_idempotently():
    migration = load_migration(); conn = FakeMySQL()
    first = migration._migrate_connection(conn)
    assert set(first["columns_added"]) == set(migration.TABLES)
    sql = "\n".join(conn.sql)
    for table in migration.TABLES:
        assert f"`{table}` ADD COLUMN environment_id" in sql
        assert f"UPDATE `{table}` SET environment_id" in sql
    assert "uq_barang_env_sku" in sql and "uq_supplier_env_kode" in sql and "uq_iso_env_opid" in sql
    assert "GROUP BY environment_id, sku" in sql
    before = len(conn.sql)
    second = migration._migrate_connection(conn)
    assert second["columns_added"] == []
    assert not any("ADD COLUMN" in sql for sql in conn.sql[before:])


def test_domain_migration_refuses_sqlite():
    migration = load_migration(); conn = FakeMySQL(); conn.dialect.name = "sqlite"
    with pytest.raises(RuntimeError, match="MySQL/MariaDB"):
        migration._migrate_connection(conn)
