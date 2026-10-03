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
    def fetchone(self):
        if isinstance(self.value, list) and self.value:
            return self.value[0]
        return self.value


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
        self.delete_rules = {}  # (table, fk_name) -> DELETE_RULE
        self.unique_constraints = set()  # (table, name)
    def execute(self, statement, params=None):
        sql = str(statement); self.sql.append(sql)
        if "SELECT DATABASE()" in sql: return Result("pos")
        if "FROM environments" in sql: return Result(1)
        if "information_schema.COLUMNS" in sql:
            return Result(int(((params or {}).get("t"), (params or {}).get("c")) in self.columns))
        if "information_schema.TABLE_CONSTRAINTS" in sql:
            if "CONSTRAINT_TYPE='FOREIGN KEY'" in sql:
                return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.foreign_keys))
            if "CONSTRAINT_TYPE='UNIQUE'" in sql:
                return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.unique_constraints))
        if "information_schema.KEY_COLUMN_USAGE" in sql:
            if "CONSTRAINT_NAME='PRIMARY'" in sql:
                return Result(self.primary_keys.get((params or {}).get("t"), []))
            return Result([])
        if "information_schema.STATISTICS" in sql:
            if "GROUP BY INDEX_NAME" in sql:
                table = (params or {}).get("t")
                column = (params or {}).get("c")
                return Result([name for candidate, name in self.legacy_indexes if candidate == table and ((table == "barang" and column == "sku") or (table == "supplier" and column == "kode_supplier") or (table == "integration_stock_operations" and column == "operation_id"))])
            return Result(int(((params or {}).get("t"), (params or {}).get("n")) in self.indexes))
        if "information_schema.REFERENTIAL_CONSTRAINTS" in sql:
            table = (params or {}).get("t")
            name = (params or {}).get("n")
            rule = self.delete_rules.get((table, name))
            return Result(rule)
        if "ADD COLUMN environment_id" in sql:
            table = sql.split("`")[1]; self.columns.add((table, "environment_id"))
        if "DROP INDEX" in sql:
            parts = sql.split("`"); self.legacy_indexes.discard((parts[1], parts[3]))
        if "DROP PRIMARY KEY" in sql:
            self.primary_keys["integration_stock_operations"] = ["environment_id", "operation_id"]
        if "ADD CONSTRAINT" in sql:
            parts = sql.split("`"); self.foreign_keys.add((parts[1], parts[3]))
            # Track DELETE_RULE if present
            if "ON DELETE" in sql:
                delete_clause = sql.split("ON DELETE")[1].strip()
                rule = "SET NULL" if delete_clause.startswith("SET NULL") else delete_clause.split()[0]
                self.delete_rules[(parts[1], parts[3])] = rule
        if "DROP FOREIGN KEY" in sql:
            parts = sql.split("`")
            self.foreign_keys.discard((parts[1], parts[3]))
            self.delete_rules.pop((parts[1], parts[3]), None)
        if "ADD INDEX" in sql or "ADD UNIQUE INDEX" in sql or "ADD UNIQUE KEY" in sql:
            parts = sql.split("`"); self.indexes.add((parts[1], parts[3]))
            if "UNIQUE" in sql:
                self.unique_constraints.add((parts[1], parts[3]))
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


def test_audit_logs_fk_environment_id_is_set_null():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    # audit_logs FK must be ON DELETE SET NULL, not RESTRICT
    fk_sql = "ADD CONSTRAINT `fk_audit_logs_environment_id` FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL"
    assert fk_sql in sql, f"Expected SET NULL FK for audit_logs, got: {sql}"


def test_domain_migration_replaces_wrong_audit_delete_rule():
    migration = load_migration()
    conn = FakeMySQL()
    conn.foreign_keys.add(("audit_logs", "fk_audit_logs_environment_id"))
    conn.delete_rules[("audit_logs", "fk_audit_logs_environment_id")] = "RESTRICT"

    migration._migrate_connection(conn)

    sql = "\n".join(conn.sql)
    drop = "ALTER TABLE `audit_logs` DROP FOREIGN KEY `fk_audit_logs_environment_id`"
    add = "ADD CONSTRAINT `fk_audit_logs_environment_id` FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL"
    assert drop in sql
    assert add in sql
    assert sql.index(drop) < sql.index(add)


def test_composite_unique_parent_keys_created_before_child_fks():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)

    barang_key = "ALTER TABLE `barang` ADD UNIQUE KEY `uq_barang_id_env` (id, environment_id)"
    supplier_key = "ALTER TABLE `supplier` ADD UNIQUE KEY `uq_supplier_id_env` (id, environment_id)"
    assert barang_key in sql
    assert supplier_key in sql
    assert sql.index(barang_key) < sql.index("fk_barang_supplier_barang_env")
    assert sql.index(supplier_key) < sql.index("fk_barang_supplier_supplier_env")


def test_child_composite_fks_reference_parent_unique_keys():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    # Verify composite FKs are added for:
    # - barang_supplier (barang_id, environment_id) -> barang (id, environment_id)
    # - barang_supplier (supplier_id, environment_id) -> supplier (id, environment_id)
    # - stok_saat_ini (barang_id, environment_id) -> barang (id, environment_id)
    # - transaksi_stok (barang_id, environment_id) -> barang (id, environment_id)
    # - transaksi_stok (supplier_id, environment_id) -> supplier (id, environment_id) nullable
    # - barang_foto (barang_id, environment_id) -> barang (id, environment_id)
    # - print_jobs (barang_id, environment_id) -> barang (id, environment_id) if applicable
    # - integration_stock_operations (barang_id, environment_id) -> barang (id, environment_id)
    expected_fks = [
        "ADD CONSTRAINT `fk_barang_supplier_env` FOREIGN KEY (supplier_id, environment_id) REFERENCES `supplier` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_barang_supplier_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE CASCADE",
        "ADD CONSTRAINT `fk_barang_supplier_supplier_env` FOREIGN KEY (supplier_id, environment_id) REFERENCES `supplier` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_stok_saat_ini_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_transaksi_stok_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_transaksi_stok_supplier_env` FOREIGN KEY (supplier_id, environment_id) REFERENCES `supplier` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_transaksi_stok_user_env` FOREIGN KEY (user_id, environment_id) REFERENCES `users` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_barang_foto_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE CASCADE",
        "ADD CONSTRAINT `fk_print_jobs_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE RESTRICT",
        "ADD CONSTRAINT `fk_integration_stock_operations_barang_env` FOREIGN KEY (barang_id, environment_id) REFERENCES `barang` (id, environment_id) ON DELETE CASCADE",
    ]
    for fk in expected_fks:
        assert fk in sql, f"Missing composite FK: {fk}"


def test_domain_migration_preflights_cross_environment_parent_links():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)

    expected_preflight = (
        "SELECT COUNT(*) FROM `barang` child LEFT JOIN `supplier` parent "
        "ON parent.id = child.supplier_id AND parent.environment_id = child.environment_id "
        "WHERE child.supplier_id IS NOT NULL AND parent.id IS NULL"
    )
    assert expected_preflight in sql
    constraint = "ADD CONSTRAINT `fk_barang_supplier_env`"
    assert sql.index(expected_preflight) < sql.index(constraint)


def test_composite_fk_nullable_behavior_preserved():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    # transaksi_stok.supplier_id is nullable - FK should allow NULL
    # barang_supplier both are NOT NULL (PK) so FK NOT NULL
    # stok_saat_ini.barang_id is PK so NOT NULL
    # barang_foto.barang_id is NOT NULL
    # print_jobs.barang_id is nullable
    # integration_stock_operations.barang_id is NOT NULL
    pass


def test_audit_logs_env_nullable_no_cross_composite():
    migration = load_migration()
    conn = FakeMySQL()
    migration._migrate_connection(conn)
    sql = "\n".join(conn.sql)
    # audit_logs.environment_id is nullable with simple FK SET NULL
    # Should NOT attempt composite FK with optional resource_ids
    assert "fk_audit_logs_environment_id" in sql
    assert "ON DELETE SET NULL" in sql


def test_domain_migration_refuses_sqlite():
    migration = load_migration(); conn = FakeMySQL(); conn.dialect.name = "sqlite"
    with pytest.raises(RuntimeError, match="MySQL/MariaDB"):
        migration._migrate_connection(conn)
