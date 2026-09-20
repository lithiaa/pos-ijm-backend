"""Convert transaksi_stok.total_harga to BIGINT safely for MySQL/MariaDB.

Usage: python migrations/20260920_total_harga_bigint.py
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402


def _column_type(connection, schema: str) -> str | None:
    return connection.execute(
        text(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'transaksi_stok' "
            "AND COLUMN_NAME = 'total_harga' LIMIT 1"
        ),
        {"schema": schema},
    ).scalar()


def _migrate_connection(connection) -> dict[str, int]:
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Total harga migration supports MySQL/MariaDB only")
    schema = connection.execute(text("SELECT DATABASE()")).scalar()
    if not schema:
        raise RuntimeError("No active MySQL database selected")
    if _column_type(connection, schema) == "bigint":
        return {"columns_modified": 0}
    connection.execute(
        text("ALTER TABLE `transaksi_stok` MODIFY COLUMN `total_harga` BIGINT NULL")
    )
    return {"columns_modified": 1}


def migrate(database_url: str = DATABASE_URL) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            return _migrate_connection(connection)
    finally:
        engine.dispose()


def main() -> None:
    counts = migrate()
    print(f"Columns modified: {counts['columns_modified']}")


if __name__ == "__main__":
    main()
