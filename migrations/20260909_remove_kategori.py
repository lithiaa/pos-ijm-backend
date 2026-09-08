"""Remove the kategori feature from a MySQL database safely.

Usage: python migrations/20260909_remove_kategori.py

MySQL DDL commits implicitly. Every step discovers the current schema state so a
rerun safely continues after either a successful or interrupted earlier run.
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402


def _quote_identifier(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def _table_exists(connection, schema: str, table: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table LIMIT 1"
            ),
            {"schema": schema, "table": table},
        ).scalar()
    )


def _migrate_connection(connection) -> dict[str, int]:
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Category removal migration supports MySQL/MariaDB only")

    schema = connection.execute(text("SELECT DATABASE()")).scalar()
    if not schema:
        raise RuntimeError("No active MySQL database selected")

    counts = {
        "foreign_keys_dropped": 0,
        "indexes_dropped": 0,
        "columns_dropped": 0,
        "tables_dropped": 0,
    }

    if _table_exists(connection, schema, "barang"):
        foreign_keys = connection.execute(
            text(
                "SELECT DISTINCT CONSTRAINT_NAME "
                "FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'barang' "
                "AND COLUMN_NAME = 'kategori_id' "
                "AND REFERENCED_TABLE_NAME IS NOT NULL "
                "ORDER BY CONSTRAINT_NAME"
            ),
            {"schema": schema},
        ).scalars().all()
        for name in foreign_keys:
            connection.execute(
                text(
                    "ALTER TABLE `barang` DROP FOREIGN KEY "
                    f"{_quote_identifier(name)}"
                )
            )
            counts["foreign_keys_dropped"] += 1

        indexes = connection.execute(
            text(
                "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'barang' "
                "AND COLUMN_NAME = 'kategori_id' ORDER BY INDEX_NAME"
            ),
            {"schema": schema},
        ).scalars().all()
        for name in indexes:
            if name == "PRIMARY":
                connection.execute(text("ALTER TABLE `barang` DROP PRIMARY KEY"))
            else:
                connection.execute(
                    text(
                        "ALTER TABLE `barang` DROP INDEX "
                        f"{_quote_identifier(name)}"
                    )
                )
            counts["indexes_dropped"] += 1

        column_exists = connection.execute(
            text(
                "SELECT 1 FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'barang' "
                "AND COLUMN_NAME = 'kategori_id' LIMIT 1"
            ),
            {"schema": schema},
        ).scalar()
        if column_exists:
            connection.execute(
                text("ALTER TABLE `barang` DROP COLUMN `kategori_id`")
            )
            counts["columns_dropped"] = 1

    if _table_exists(connection, schema, "kategori"):
        connection.execute(text("DROP TABLE `kategori`"))
        counts["tables_dropped"] = 1

    return counts


def migrate(database_url: str = DATABASE_URL) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return _migrate_connection(connection)
    finally:
        engine.dispose()


def main() -> None:
    counts = migrate()
    print(f"Foreign keys dropped: {counts['foreign_keys_dropped']}")
    print(f"Indexes dropped: {counts['indexes_dropped']}")
    print(f"Columns dropped: {counts['columns_dropped']}")
    print(f"Tables dropped: {counts['tables_dropped']}")


if __name__ == "__main__":
    main()
