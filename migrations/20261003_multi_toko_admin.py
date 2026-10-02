"""Add Platform Owner administration, invitations, support grants, and copy jobs.

Run after 20261003_multi_toko_foundation.py and 20261003_multi_toko_domain.py.
Usage: python migrations/20261003_multi_toko_admin.py
"""
from pathlib import Path
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

NEW_TABLES = (
    "environment_provision_requests",
    "user_invitations",
    "support_grants",
    "environment_copy_jobs",
)
ENVIRONMENT_COLUMNS = {
    "business_type": "VARCHAR(100) NULL",
    "logo_url": "VARCHAR(500) NULL",
    "address": "VARCHAR(500) NULL",
    "phone": "VARCHAR(50) NULL",
    "timezone": "VARCHAR(100) NOT NULL DEFAULT 'Asia/Jakarta'",
    "currency": "VARCHAR(10) NOT NULL DEFAULT 'IDR'",
}


def _exists(connection, schema, source, table, name=None):
    sql = f"SELECT COUNT(*) FROM information_schema.{source} WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"
    params = {"s": schema, "t": table}
    if name is not None:
        key = "COLUMN_NAME" if source == "COLUMNS" else "INDEX_NAME"
        sql += f" AND {key}=:n"
        params["c" if source == "COLUMNS" else "n"] = name
        sql = sql.replace(":n", ":c" if source == "COLUMNS" else ":n")
    return bool(connection.execute(text(sql), params).scalar())


def _table(connection, schema, name):
    return _exists(connection, schema, "TABLES", name)


def _column(connection, schema, table, name):
    return _exists(connection, schema, "COLUMNS", table, name)


def _index(connection, schema, table, name):
    return _exists(connection, schema, "STATISTICS", table, name)


def _migrate_connection(connection):
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Migration supports MySQL/MariaDB only")
    schema = connection.execute(text("SELECT DATABASE()")).scalar()
    tables_created = []
    columns_added = []
    indexes_added = []

    for name, definition in ENVIRONMENT_COLUMNS.items():
        if not _column(connection, schema, "environments", name):
            connection.execute(text(f"ALTER TABLE `environments` ADD COLUMN `{name}` {definition}"))
            columns_added.append(name)

    if not _index(connection, schema, "users", "uq_users_email"):
        connection.execute(text("ALTER TABLE `users` ADD UNIQUE INDEX `uq_users_email` (`email`)"))
        indexes_added.append("uq_users_email")

    statements = {
        "environment_provision_requests": """CREATE TABLE `environment_provision_requests` (
            `id` INT NOT NULL AUTO_INCREMENT, `request_key` VARCHAR(200) NOT NULL,
            `request_hash` CHAR(64) NOT NULL, `environment_id` INT NOT NULL, `administrator_id` INT NOT NULL,
            `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (`id`),
            UNIQUE INDEX `uq_provision_request_key` (`request_key`),
            FOREIGN KEY (`environment_id`) REFERENCES `environments` (`id`),
            FOREIGN KEY (`administrator_id`) REFERENCES `users` (`id`))""",
        "user_invitations": """CREATE TABLE `user_invitations` (
            `id` INT NOT NULL AUTO_INCREMENT, `user_id` INT NOT NULL, `environment_id` INT NOT NULL,
            `token_hash` CHAR(64) NOT NULL, `expires_at` DATETIME NOT NULL, `accepted_at` DATETIME NULL,
            `revoked_at` DATETIME NULL, `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`), UNIQUE INDEX `uq_invitation_token_hash` (`token_hash`),
            INDEX `ix_invitation_user` (`user_id`), INDEX `ix_invitation_environment` (`environment_id`),
            FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
            FOREIGN KEY (`environment_id`) REFERENCES `environments` (`id`))""",
        "support_grants": """CREATE TABLE `support_grants` (
            `id` INT NOT NULL AUTO_INCREMENT, `environment_id` INT NOT NULL, `platform_owner_id` INT NOT NULL,
            `reason` TEXT NOT NULL, `starts_at` DATETIME NOT NULL, `expires_at` DATETIME NOT NULL,
            `revoked_at` DATETIME NULL, `revoked_by_user_id` INT NULL,
            `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (`id`),
            INDEX `ix_support_environment` (`environment_id`), INDEX `ix_support_expiry` (`expires_at`),
            FOREIGN KEY (`environment_id`) REFERENCES `environments` (`id`),
            FOREIGN KEY (`platform_owner_id`) REFERENCES `users` (`id`),
            FOREIGN KEY (`revoked_by_user_id`) REFERENCES `users` (`id`))""",
        "environment_copy_jobs": """CREATE TABLE `environment_copy_jobs` (
            `id` INT NOT NULL AUTO_INCREMENT, `request_key` VARCHAR(200) NOT NULL,
            `source_environment_id` INT NOT NULL, `target_environment_id` INT NOT NULL,
            `requested_by_user_id` INT NOT NULL, `options` TEXT NOT NULL, `request_hash` CHAR(64) NOT NULL,
            `status` VARCHAR(20) NOT NULL DEFAULT 'pending', `progress` INT NOT NULL DEFAULT 0,
            `result` TEXT NULL, `error` TEXT NULL, `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `started_at` DATETIME NULL, `completed_at` DATETIME NULL, `cancelled_at` DATETIME NULL,
            PRIMARY KEY (`id`), UNIQUE INDEX `uq_copy_target_request` (`target_environment_id`, `request_key`),
            INDEX `ix_copy_source` (`source_environment_id`), INDEX `ix_copy_status` (`status`),
            FOREIGN KEY (`source_environment_id`) REFERENCES `environments` (`id`),
            FOREIGN KEY (`target_environment_id`) REFERENCES `environments` (`id`),
            FOREIGN KEY (`requested_by_user_id`) REFERENCES `users` (`id`))""",
    }
    for table in NEW_TABLES:
        if not _table(connection, schema, table):
            connection.execute(text(statements[table]))
            tables_created.append(table)

    return {
        "tables_created": tables_created,
        "environment_columns_added": columns_added,
        "indexes_added": indexes_added,
    }


def migrate(database_url=DATABASE_URL):
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            return _migrate_connection(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
