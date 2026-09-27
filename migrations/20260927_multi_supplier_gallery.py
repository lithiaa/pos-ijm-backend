"""Add multi-supplier tallies, gallery, stock source supplier.

Usage: python migrations/20260927_multi_supplier_gallery.py
"""
from pathlib import Path
import sys
from sqlalchemy import create_engine, text
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL


def _exists(c, schema, table, column=None):
    q = "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"
    args = {"s": schema, "t": table}
    if column:
        q += " AND COLUMN_NAME=:c"; args["c"] = column
    return bool(c.execute(text(q), args).scalar())


def _drop_filename_unique_indexes(c, schema):
    indexes = c.execute(text("SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=:s AND TABLE_NAME='barang_foto' AND COLUMN_NAME='filename' AND NON_UNIQUE=0 AND INDEX_NAME <> 'PRIMARY'"), {"s": schema}).fetchall()
    for (index,) in indexes:
        c.execute(text(f"ALTER TABLE barang_foto DROP INDEX `{index.replace('`', '``')}`"))


def _migrate_connection(c):
    if c.dialect.name not in {"mysql", "mariadb"}: raise RuntimeError("Migration supports MySQL/MariaDB only")
    schema = c.execute(text("SELECT DATABASE()")).scalar()
    if not _exists(c, schema, "barang_supplier"):
        c.execute(text("CREATE TABLE barang_supplier (barang_id INT NOT NULL, supplier_id INT NOT NULL, jumlah_masuk_kumulatif BIGINT NOT NULL DEFAULT 0, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, PRIMARY KEY (barang_id,supplier_id), CONSTRAINT ck_barang_supplier_nonnegative CHECK (jumlah_masuk_kumulatif >= 0), FOREIGN KEY (barang_id) REFERENCES barang(id) ON DELETE CASCADE, FOREIGN KEY (supplier_id) REFERENCES supplier(id) ON DELETE RESTRICT)"))
    if not _exists(c, schema, "barang_foto"):
        c.execute(text("CREATE TABLE barang_foto (id INT NOT NULL AUTO_INCREMENT, barang_id INT NOT NULL, filename VARCHAR(255) NOT NULL, urutan INT NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(id), UNIQUE KEY uq_barang_foto_order(barang_id,urutan), FOREIGN KEY (barang_id) REFERENCES barang(id) ON DELETE CASCADE)"))
    else:
        _drop_filename_unique_indexes(c, schema)
    if not _exists(c, schema, "transaksi_stok", "supplier_id"):
        c.execute(text("ALTER TABLE transaksi_stok ADD COLUMN supplier_id INT NULL, ADD INDEX ix_transaksi_stok_supplier_id (supplier_id), ADD CONSTRAINT fk_transaksi_stok_supplier FOREIGN KEY (supplier_id) REFERENCES supplier(id)"))
    c.execute(text("INSERT IGNORE INTO barang_supplier (barang_id,supplier_id,jumlah_masuk_kumulatif) SELECT id,supplier_id,0 FROM barang WHERE supplier_id IS NOT NULL"))
    c.execute(text("INSERT INTO barang_foto (barang_id,filename,urutan) SELECT id,foto,0 FROM barang WHERE foto IS NOT NULL AND NOT EXISTS (SELECT 1 FROM barang_foto WHERE barang_foto.barang_id=barang.id AND barang_foto.urutan=0)"))


def migrate(database_url=DATABASE_URL):
    engine=create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as c: _migrate_connection(c)
    finally: engine.dispose()

if __name__ == '__main__': migrate()
