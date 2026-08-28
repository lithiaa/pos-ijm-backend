"""Add and backfill Barang.harga_beli_kode for an existing MySQL database.

Usage: python migrations/20260828_backfill_harga_beli_kode.py
"""

from pathlib import Path
import sys

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATABASE_URL  # noqa: E402
from app.services.harga import harga_encode  # noqa: E402


def main() -> None:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    added = False
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("barang")}
        if "harga_beli_kode" not in columns:
            connection.execute(
                text("ALTER TABLE barang ADD COLUMN harga_beli_kode VARCHAR(50) NULL")
            )
            added = True

        rows = connection.execute(
            text("SELECT id, harga_modal FROM barang WHERE harga_beli_kode IS NULL")
        ).all()
        for row in rows:
            connection.execute(
                text("UPDATE barang SET harga_beli_kode = :code WHERE id = :id"),
                {"code": harga_encode(int(row.harga_modal or 0)), "id": row.id},
            )

    print(f"Column added: {1 if added else 0}")
    print(f"Rows backfilled: {len(rows)}")


if __name__ == "__main__":
    main()
