"""Multi-Toko foundation migration: environments table and user scoping columns.

This migration establishes the multi-environment schema foundation:
1. Creates the `environments` table if not exists.
2. Adds `environment_id`, `email`, `status`, `must_change_password`, and `permissions` to `users`.
3. Seeds the legacy `Lithia Autoparts` environment (`lithia-autoparts`).
4. Backfills existing non-platform users to `lithia-autoparts`.

Platform Owner Bootstrap Strategy:
- This migration intentionally avoids generating or hardcoding default admin credentials.
- Platform owners must be created or promoted via explicit manual bootstrap:
    python scripts/bootstrap_platform_owner.py --username <username>
  or by an existing platform administrator running a cryptographically secure CLI bootstrap.
- Existing admins remain scoped to the legacy environment (Lithia Autoparts) until explicit promotion.

Usage: python migrations/20261003_multi_toko_foundation.py
"""
from pathlib import Path
import sys
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL


def _table_exists(c, schema: str, table: str) -> bool:
    q = "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"
    return bool(c.execute(text(q), {"s": schema, "t": table}).scalar())


def _column_exists(c, schema: str, table: str, column: str) -> bool:
    q = "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t AND COLUMN_NAME=:c"
    return bool(c.execute(text(q), {"s": schema, "t": table, "c": column}).scalar())


def _migrate_connection(c) -> dict:
    if c.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Migration supports MySQL/MariaDB only")

    schema = c.execute(text("SELECT DATABASE()")).scalar()
    environments_created = False
    columns_added: list[str] = []

    if not _table_exists(c, schema, "environments"):
        c.execute(
            text(
                "CREATE TABLE environments ("
                "id INT NOT NULL AUTO_INCREMENT, "
                "slug VARCHAR(100) NOT NULL UNIQUE, "
                "name VARCHAR(255) NOT NULL, "
                "status VARCHAR(20) NOT NULL DEFAULT 'active', "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
                "PRIMARY KEY (id)"
                ")"
            )
        )
        environments_created = True

    user_column_definitions = [
        (
            "environment_id",
            "ALTER TABLE users ADD COLUMN environment_id INT NULL, "
            "ADD INDEX ix_users_environment_id (environment_id), "
            "ADD CONSTRAINT fk_users_environment FOREIGN KEY (environment_id) REFERENCES environments(id) ON DELETE SET NULL",
        ),
        ("email", "ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL, ADD INDEX ix_users_email (email)"),
        ("status", "ALTER TABLE users ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"),
        ("must_change_password", "ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0"),
        ("permissions", "ALTER TABLE users ADD COLUMN permissions TEXT NULL"),
    ]

    for col_name, alter_sql in user_column_definitions:
        if not _column_exists(c, schema, "users", col_name):
            c.execute(text(alter_sql))
            columns_added.append(col_name)

    # Idempotently ensure legacy environment exists
    c.execute(
        text(
            "INSERT INTO environments (slug, name, status) "
            "SELECT 'lithia-autoparts', 'Lithia Autoparts', 'active' "
            "WHERE NOT EXISTS (SELECT 1 FROM environments WHERE slug = 'lithia-autoparts')"
        )
    )

    # Backfill legacy non-platform users without environment
    c.execute(
        text(
            "UPDATE users "
            "SET environment_id = (SELECT id FROM environments WHERE slug = 'lithia-autoparts') "
            "WHERE environment_id IS NULL AND (role != 'platform_owner')"
        )
    )

    return {
        "environments_created": environments_created,
        "columns_added": columns_added,
    }


def migrate(database_url: str = DATABASE_URL):
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            return _migrate_connection(conn)
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
