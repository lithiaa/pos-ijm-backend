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
    def fetchall(self): return self.value if isinstance(self.value, list) else []


class FakeMySQL:
    class Dialect: name = "mysql"
    def __init__(self):
        self.dialect = self.Dialect(); self.columns = set(); self.indexes = set(); self.foreign_keys = set(); self.sql = []
        self.legacy_indexes = {
            ("barang", "legacy_barang_sku"),
            ("supplier", "legacy_supplier_kode"),
            ("integration_stock_operations", "PRIMARY"),
        }
        self.primary_keys = {"integration_stock_operations": ["operation_id"]}
    def execute(self, statement, params=None):
        sql = str(statement); self.sql.append(sql)
        if "SELECT DATABASE()" in sql: return Result("pos")
        if "FROM environments" in sql: return Result(1)
        if "information_schema.COLUMNS" in sql:
            return Result(int(((params or {}).get("t"), (params or {}).get("c")) in self.columns))
        if "information_schema.TABLE_CONSTRAINTS" in sql:
            return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.foreign_keys))
        if "information_schema.KEY_COLUMN_USAGE" in sql:
            return Result(self.primary_keys.get((params or {}).get("t"), []))
        if "information_schema.STATISTICS" in sql:
            if "GROUP BY INDEX_NAME" in sql:
                table = (params or {}).get("t")
                column = (params or {}).get("c")
                return Result([name for candidate, name in self.legacy_indexes if candidate == table and ((table == "barang" and column == "sku") or (table == "supplier" and column == "kode_supplier") or (table == "integration_stock_operations" and column == "operation_id"))])
            return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.indexes))
        if "ADD COLUMN environment_id" in sql:
            table = sql.split("`")[1]; self.columns.add((table, "environment_id"))
        if "DROP INDEX" in sql:
            parts = sql.split("`"); self.legacy_indexes.discard((parts[1], parts[3]))
        if "DROP PRIMARY KEY" in sql:
            self.primary_keys["integration_stock_operations"] = ["environment_id", "operation_id"]
        if "ADD CONSTRAINT" in sql:
            parts = sql.split("`"); self.foreign_keys.add((parts[1], parts[3]))
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
    for table in migration.TABLES:
        backfill = f"UPDATE `{table}` SET environment_id"
        assert (backfill in sql) is (table != "audit_logs")
    assert "uq_barang_env_sku" in sql and "uq_supplier_env_kode" in sql
    assert "uq_iso_env_opid" not in sql
    assert "GROUP BY environment_id, sku" in sql
    before = len(conn.sql)
    second = migration._migrate_connection(conn)
    assert second["columns_added"] == []
    assert not any("ADD COLUMN" in sql for sql in conn.sql[before:])


def test_domain_migration_preflights_backfill_then_sets_every_domain_scope_not_null():
    migration = load_migration(); conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    for table in migration.TABLES:
        backfill = f"UPDATE `{table}` SET environment_id"
        preflight = f"SELECT COUNT(*) FROM `{table}` WHERE environment_id IS NULL"
        not_null = f"ALTER TABLE `{table}` MODIFY COLUMN environment_id INT NOT NULL"
        if table == "audit_logs":
            assert backfill not in sql
            assert preflight not in sql
            assert not_null not in sql
        else:
            assert backfill in sql
            assert preflight in sql
            assert not_null in sql
            assert sql.index(backfill) < sql.index(preflight) < sql.index(not_null)
    for table, columns, name in (
        ("barang", "environment_id, sku", "uq_barang_env_sku"),
        ("supplier", "environment_id, kode_supplier", "uq_supplier_env_kode"),
    ):
        duplicate_preflight = f"SELECT COUNT(*) FROM `{table}` GROUP BY {columns} HAVING COUNT(*) > 1"
        not_null = f"ALTER TABLE `{table}` MODIFY COLUMN environment_id INT NOT NULL"
        assert sql.index(duplicate_preflight) < sql.index(not_null), name


def test_domain_migration_preflights_environment_references_adds_foreign_keys_and_drops_discovered_legacy_uniques():
    migration = load_migration(); conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    for table in migration.TABLES:
        reference_preflight = f"SELECT COUNT(*) FROM `{table}` d LEFT JOIN environments e ON e.id = d.environment_id WHERE e.id IS NULL"
        if table == "audit_logs":
            reference_preflight = reference_preflight.replace("WHERE e.id IS NULL", "WHERE d.environment_id IS NOT NULL AND e.id IS NULL")
        foreign_key = f"fk_{table}_environment_id"
        assert reference_preflight in sql
        assert f"ADD CONSTRAINT `{foreign_key}` FOREIGN KEY (environment_id) REFERENCES environments(id)" in sql
        assert sql.index(reference_preflight) < sql.index(f"ADD CONSTRAINT `{foreign_key}`")
    for table, legacy in (
        ("barang", "legacy_barang_sku"),
        ("supplier", "legacy_supplier_kode"),
    ):
        assert f"ALTER TABLE `{table}` DROP INDEX `{legacy}`" in sql
    assert "DROP INDEX `PRIMARY`" not in sql


def test_domain_migration_replaces_global_operation_primary_key_with_environment_scope():
    migration = load_migration(); conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    preflight = "SELECT COUNT(*) FROM `integration_stock_operations` GROUP BY environment_id, operation_id HAVING COUNT(*) > 1"
    primary = "ALTER TABLE `integration_stock_operations` DROP PRIMARY KEY, ADD PRIMARY KEY (environment_id, operation_id)"
    assert primary in sql
    assert "DROP INDEX `PRIMARY`" not in sql
    assert sql.index(preflight) < sql.index(primary)
    assert sql.index(primary) < sql.index("ADD CONSTRAINT `fk_integration_stock_operations_environment_id`")
    assert "uq_iso_env_opid" not in sql
    assert not any("DROP INDEX `PRIMARY`" in statement for statement in conn.sql)
    before = len(conn.sql)
    migration._migrate_connection(conn)
    assert not any("DROP PRIMARY KEY" in statement for statement in conn.sql[before:])
    before = len(conn.sql)
    migration._migrate_connection(conn)
    assert not any("DROP INDEX" in statement or "ADD CONSTRAINT" in statement for statement in conn.sql[before:])


def test_integration_stock_operation_model_uses_environment_scoped_primary_key():
    from app.models.transaksi import IntegrationStockOperation

    assert [column.name for column in IntegrationStockOperation.__table__.primary_key.columns] == [
        "environment_id", "operation_id"
    ]
    assert not any(
        getattr(constraint, "name", None) == "uq_iso_env_opid"
        for constraint in IntegrationStockOperation.__table__.constraints
    )


def test_domain_migration_refuses_sqlite():
    migration = load_migration(); conn = FakeMySQL(); conn.dialect.name = "sqlite"
    with pytest.raises(RuntimeError, match="MySQL/MariaDB"):
        migration._migrate_connection(conn)
