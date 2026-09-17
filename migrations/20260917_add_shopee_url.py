"""Add nullable Barang.shopee_url safely for MySQL/MariaDB.

Usage: python migrations/20260917_add_shopee_url.py
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402


def _column_exists(connection, schema: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'barang' "
                "AND COLUMN_NAME = 'shopee_url' LIMIT 1"
            ),
            {"schema": schema},
        ).scalar()
    )


def _migrate_connection(connection) -> dict[str, int]:
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Shopee URL migration supports MySQL/MariaDB only")
    schema = connection.execute(text("SELECT DATABASE()")).scalar()
    if not schema:
        raise RuntimeError("No active MySQL database selected")
    if _column_exists(connection, schema):
        return {"columns_added": 0}
    connection.execute(
        text("ALTER TABLE `barang` ADD COLUMN `shopee_url` VARCHAR(500) NULL")
    )
    return {"columns_added": 1}


def migrate(database_url: str = DATABASE_URL) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return _migrate_connection(connection)
    finally:
        engine.dispose()


def main() -> None:
    counts = migrate()
    print(f"Columns added: {counts['columns_added']}")


if __name__ == "__main__":
    main()
