"""Idempotently scope all domain tables to Lithia Autoparts.

Usage: python migrations/20261003_multi_toko_domain.py
"""
from pathlib import Path
import sys
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

TABLES = (
    "barang", "supplier", "stok_saat_ini", "transaksi_stok", "barang_supplier",
    "barang_foto", "audit_logs", "print_jobs", "integration_stock_operations",
)


def _exists(c, schema, table, column=None):
    sql = "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"
    args = {"s": schema, "t": table}
    if column:
        sql += " AND COLUMN_NAME=:c"; args["c"] = column
    return bool(c.execute(text(sql), args).scalar())


def _index_exists(c, schema, table, name):
    return bool(c.execute(text("SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t AND INDEX_NAME=:n"), {"s": schema, "t": table, "n": name}).scalar())


def _foreign_key_exists(c, schema, table, name):
    return bool(c.execute(text("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=:s AND TABLE_NAME=:t AND CONSTRAINT_NAME=:n AND CONSTRAINT_TYPE='FOREIGN KEY'"), {"s": schema, "t": table, "n": name}).scalar())


def _legacy_unique_indexes(c, schema, table, column):
    rows = c.execute(text("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t AND NON_UNIQUE=0 AND INDEX_NAME <> 'PRIMARY' GROUP BY INDEX_NAME HAVING COUNT(*)=1 AND MAX(COLUMN_NAME)=:c"), {"s": schema, "t": table, "c": column}).fetchall()
    return [row if isinstance(row, str) else row[0] for row in rows]


def _primary_key_columns(c, schema, table):
    rows = c.execute(text("SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t AND CONSTRAINT_NAME='PRIMARY' ORDER BY ORDINAL_POSITION"), {"s": schema, "t": table}).fetchall()
    return [row if isinstance(row, str) else row[0] for row in rows]


def _migrate_connection(c):
    if c.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Migration supports MySQL/MariaDB only")
    schema = c.execute(text("SELECT DATABASE()")).scalar()
    env = c.execute(text("SELECT id FROM environments WHERE slug='lithia-autoparts'")).scalar()
    if env is None:
        c.execute(text("INSERT INTO environments (slug,name,status) VALUES ('lithia-autoparts','Lithia Autoparts','active')"))
        env = c.execute(text("SELECT id FROM environments WHERE slug='lithia-autoparts'")).scalar()
    added = []
    required_tables = tuple(table for table in TABLES if table != "audit_logs")
    for table in TABLES:
        if not _exists(c, schema, table, "environment_id"):
            c.execute(text(f"ALTER TABLE `{table}` ADD COLUMN environment_id INT NULL"))
            added.append(table)
    for table in required_tables:
        c.execute(text(f"UPDATE `{table}` SET environment_id=:e WHERE environment_id IS NULL"), {"e": env})
        missing = c.execute(text(f"SELECT COUNT(*) FROM `{table}` WHERE environment_id IS NULL")).scalar()
        if missing:
            raise RuntimeError(f"Preflight failed: {table} still has NULL environment_id rows")
        unresolved = c.execute(text(f"SELECT COUNT(*) FROM `{table}` d LEFT JOIN environments e ON e.id = d.environment_id WHERE e.id IS NULL")).scalar()
        if unresolved:
            raise RuntimeError(f"Preflight failed: {table} has unknown environment_id rows")
    for table, column in (("barang", "sku"), ("supplier", "kode_supplier")):
        for index in _legacy_unique_indexes(c, schema, table, column):
            c.execute(text(f"ALTER TABLE `{table}` DROP INDEX `{index}`"))
    for table, columns, name in (("barang", "environment_id, sku", "uq_barang_env_sku"), ("supplier", "environment_id, kode_supplier", "uq_supplier_env_kode")):
        if not _index_exists(c, schema, table, name):
            dup_check = c.execute(text(f"SELECT COUNT(*) FROM `{table}` GROUP BY {columns} HAVING COUNT(*) > 1")).fetchall()
            if dup_check:
                raise RuntimeError(f"Cannot create unique index {name} on {table}: duplicates exist")
            c.execute(text(f"ALTER TABLE `{table}` ADD UNIQUE INDEX `{name}` ({columns})"))
    operation_columns = "environment_id, operation_id"
    duplicates = c.execute(text(f"SELECT COUNT(*) FROM `integration_stock_operations` GROUP BY {operation_columns} HAVING COUNT(*) > 1")).fetchall()
    if duplicates:
        raise RuntimeError("Cannot create composite primary key on integration_stock_operations: duplicates exist")
    if _primary_key_columns(c, schema, "integration_stock_operations") != ["environment_id", "operation_id"]:
        c.execute(text("ALTER TABLE `integration_stock_operations` DROP PRIMARY KEY, ADD PRIMARY KEY (environment_id, operation_id)"))
    for table in required_tables:
        c.execute(text(f"ALTER TABLE `{table}` MODIFY COLUMN environment_id INT NOT NULL"))
    unresolved_audits = c.execute(text("SELECT COUNT(*) FROM `audit_logs` d LEFT JOIN environments e ON e.id = d.environment_id WHERE d.environment_id IS NOT NULL AND e.id IS NULL")).scalar()
    if unresolved_audits:
        raise RuntimeError("Preflight failed: audit_logs has unknown environment_id rows")
    for table in TABLES:
        index = f"ix_{table}_environment_id"
        if not _index_exists(c, schema, table, index):
            c.execute(text(f"ALTER TABLE `{table}` ADD INDEX `{index}` (environment_id)"))
        foreign_key = f"fk_{table}_environment_id"
        if not _foreign_key_exists(c, schema, table, foreign_key):
            c.execute(text(f"ALTER TABLE `{table}` ADD CONSTRAINT `{foreign_key}` FOREIGN KEY (environment_id) REFERENCES environments(id)"))
    return {"columns_added": added, "environment_id": env}


def migrate(database_url=DATABASE_URL):
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            return _migrate_connection(conn)
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
