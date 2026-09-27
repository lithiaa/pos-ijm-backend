"""Migration contracts for shared legacy photo aliases."""
import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "multi_supplier_gallery_migration",
    Path(__file__).parents[1] / "migrations/20260927_multi_supplier_gallery.py",
)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


class Result:
    def __init__(self, scalar=None, rows=()):
        self._scalar = scalar
        self._rows = rows

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows


class Connection:
    class dialect:
        name = "mysql"

    def __init__(self):
        self.sql = []

    def execute(self, statement, args=None):
        sql = str(statement)
        self.sql.append(sql)
        if "SELECT DATABASE" in sql:
            return Result("test")
        if "information_schema.COLUMNS" in sql:
            return Result(1 if args["t"] == "barang_foto" and not args.get("c") else 0)
        if "information_schema.STATISTICS" in sql:
            return Result(rows=[("uq_barang_foto_filename",)])
        return Result()


def test_migration_drops_legacy_global_filename_key_before_backfill():
    connection = Connection()
    migration._drop_filename_unique_indexes(connection, "test")
    assert "ALTER TABLE barang_foto DROP INDEX `uq_barang_foto_filename`" in "\n".join(connection.sql)


def test_migration_new_table_and_backfill_allow_shared_legacy_filename():
    connection = Connection()
    migration._migrate_connection(connection)
    statements = "\n".join(connection.sql)
    assert "UNIQUE KEY uq_barang_foto_filename(filename)" not in statements
    assert "INSERT IGNORE INTO barang_foto" not in statements
    assert "INSERT INTO barang_foto (barang_id,filename,urutan)" in statements
