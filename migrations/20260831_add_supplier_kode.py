"""Add and backfill Supplier.kode_supplier safely.

Usage: python migrations/20260831_add_supplier_kode.py
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402


INDEX_NAME = "ux_supplier_kode_supplier"


def migrate(database_url: str = DATABASE_URL) -> dict[str, int]:
    engine = create_engine(database_url, pool_pre_ping=True)
    counts = {"columns_added": 0, "indexes_added": 0, "rows_backfilled": 0}
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"] for column in inspector.get_columns("supplier")
            }
            if "kode_supplier" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE supplier "
                        "ADD COLUMN kode_supplier VARCHAR(50) NULL"
                    )
                )
                counts["columns_added"] = 1

            rows = connection.execute(
                text("SELECT id, kode_supplier FROM supplier ORDER BY id")
            ).all()
            proposed = {}
            for row in rows:
                normalized = (
                    row.kode_supplier.strip().upper()
                    if row.kode_supplier and row.kode_supplier.strip()
                    else f"SUP-{row.id:03d}"
                )
                proposed.setdefault(normalized, []).append(
                    (row.id, row.kode_supplier, normalized)
                )

            conflicts = [owners for owners in proposed.values() if len(owners) > 1]
            if conflicts:
                details = "; ".join(
                    ", ".join(
                        f"id={supplier_id} code={original!r} normalized={normalized!r}"
                        for supplier_id, original, normalized in owners
                    )
                    for owners in conflicts
                )
                raise RuntimeError(f"Supplier code conflicts: {details}")

            for row in rows:
                if row.kode_supplier and row.kode_supplier.strip():
                    normalized = row.kode_supplier.strip().upper()
                    if normalized != row.kode_supplier:
                        connection.execute(
                            text(
                                "UPDATE supplier SET kode_supplier = :code "
                                "WHERE id = :id"
                            ),
                            {"code": normalized, "id": row.id},
                        )
                else:
                    result = connection.execute(
                        text(
                            "UPDATE supplier SET kode_supplier = :code "
                            "WHERE id = :id AND "
                            "(kode_supplier IS NULL OR TRIM(kode_supplier) = '')"
                        ),
                        {"code": f"SUP-{row.id:03d}", "id": row.id},
                    )
                    counts["rows_backfilled"] += result.rowcount

            inspector = inspect(connection)
            indexes = inspector.get_indexes("supplier")
            unique_constraints = inspector.get_unique_constraints("supplier")
            code_is_unique = any(
                index.get("unique")
                and index.get("column_names") == ["kode_supplier"]
                for index in indexes
            ) or any(
                constraint.get("column_names") == ["kode_supplier"]
                for constraint in unique_constraints
            )
            if not code_is_unique:
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX {INDEX_NAME} "
                        "ON supplier (kode_supplier)"
                    )
                )
                counts["indexes_added"] = 1
    finally:
        engine.dispose()
    return counts


def main() -> None:
    counts = migrate()
    print(f"Columns added: {counts['columns_added']}")
    print(f"Indexes added: {counts['indexes_added']}")
    print(f"Rows backfilled: {counts['rows_backfilled']}")


if __name__ == "__main__":
    main()
