"""Create the immutable audit log table in MySQL/MariaDB.

Usage: python migrations/20260909_add_audit_logs.py
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402


def _table_exists(connection, schema: str) -> bool:
    return bool(
        connection.execute(
            text(
                "SELECT 1 FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = 'audit_logs' LIMIT 1"
            ),
            {"schema": schema},
        ).scalar()
    )


def _migrate_connection(connection) -> dict[str, int]:
    if connection.dialect.name not in {"mysql", "mariadb"}:
        raise RuntimeError("Audit log migration supports MySQL/MariaDB only")
    schema = connection.execute(text("SELECT DATABASE()")).scalar()
    if not schema:
        raise RuntimeError("No active MySQL database selected")
    if _table_exists(connection, schema):
        return {"tables_created": 0}

    connection.execute(
        text(
            """CREATE TABLE `audit_logs` (
                `id` BIGINT NOT NULL AUTO_INCREMENT,
                `created_at` DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
                `user_id` INT NULL,
                `username` VARCHAR(100) NULL,
                `action` VARCHAR(10) NOT NULL,
                `http_method` VARCHAR(10) NOT NULL,
                `resource` VARCHAR(100) NOT NULL,
                `resource_id` VARCHAR(255) NULL,
                `path` VARCHAR(500) NOT NULL,
                `status_code` SMALLINT NOT NULL,
                `ip_address` VARCHAR(45) NULL,
                `summary` TEXT NOT NULL,
                PRIMARY KEY (`id`),
                INDEX `ix_audit_logs_created_at_id` (`created_at`, `id`),
                INDEX `ix_audit_logs_action_resource` (`action`, `resource`),
                INDEX `ix_audit_logs_user_id` (`user_id`),
                INDEX `ix_audit_logs_username` (`username`),
                INDEX `ix_audit_logs_resource_id` (`resource_id`),
                INDEX `ix_audit_logs_status_code` (`status_code`),
                CONSTRAINT `fk_audit_logs_user_id`
                    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        )
    )
    return {"tables_created": 1}


def migrate(database_url: str = DATABASE_URL) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return _migrate_connection(connection)
    finally:
        engine.dispose()


def main() -> None:
    counts = migrate()
    print(f"Tables created: {counts['tables_created']}")


if __name__ == "__main__":
    main()
