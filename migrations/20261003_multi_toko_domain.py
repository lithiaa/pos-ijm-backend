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


def _migrate_connection(c):
    if c.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Migration supports MySQL/MariaDB only")
    schema = c.execute(text("SELECT DATABASE()")).scalar()
    env = c.execute(text("SELECT id FROM environments WHERE slug='lithia-autoparts'")).scalar()
    if env is None:
        c.execute(text("INSERT INTO environments (slug,name,status) VALUES ('lithia-autoparts','Lithia Autoparts','active')"))
        env = c.execute(text("SELECT id FROM environments WHERE slug='lithia-autoparts'")).scalar()
    added = []
    for table in TABLES:
        if not _exists(c, schema, table, "environment_id"):
            c.execute(text(f"ALTER TABLE `{table}` ADD COLUMN environment_id INT NULL"))
            added.append(table)
        c.execute(text(f"UPDATE `{table}` SET environment_id=:e WHERE environment_id IS NULL"), {"e": env})
        index = f"ix_{table}_environment_id"
        if not _index_exists(c, schema, table, index):
            c.execute(text(f"ALTER TABLE `{table}` ADD INDEX `{index}` (environment_id)"))
    # Legacy global unique keys need manual index-name discovery in deployment; add scoped indexes safely.
    for table, columns, name in (("barang", "environment_id, sku", "uq_barang_env_sku"), ("supplier", "environment_id, kode_supplier", "uq_supplier_env_kode"), ("integration_stock_operations", "environment_id, operation_id", "uq_iso_env_opid")):
        if not _index_exists(c, schema, table, name):
            c.execute(text(f"ALTER TABLE `{table}` ADD UNIQUE INDEX `{name}` ({columns})"))
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
