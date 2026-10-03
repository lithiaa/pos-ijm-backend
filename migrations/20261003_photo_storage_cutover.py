"""Copy legacy flat product photos into environment-scoped storage.

Run after 20261003_multi_toko_domain.py:
  python migrations/20261003_photo_storage_cutover.py --dry-run
  python migrations/20261003_photo_storage_cutover.py
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.barang import Barang, BarangFoto
from config import DATABASE_URL


def _filename(value: str) -> str | None:
    if not value or value != os.path.basename(value) or value in {".", ".."}:
        return None
    return value


def _references(db):
    seen = set()
    for environment_id, filename in db.query(Barang.environment_id, Barang.foto).filter(Barang.foto.isnot(None)):
        if (environment_id, filename) not in seen:
            seen.add((environment_id, filename)); yield environment_id, filename
    for environment_id, filename in db.query(BarangFoto.environment_id, BarangFoto.filename):
        if (environment_id, filename) not in seen:
            seen.add((environment_id, filename)); yield environment_id, filename


def cutover_photo_storage(db, storage_dir: str | Path, dry_run: bool = True) -> dict:
    """Preflight then copy flat legacy files. Never mutates filesystem during import."""
    root = Path(storage_dir)
    report = {"copied": [], "present": [], "missing": [], "invalid": []}
    for environment_id, raw_filename in _references(db):
        filename = _filename(raw_filename)
        if filename is None:
            report["invalid"].append({"environment_id": environment_id, "filename": raw_filename})
            continue
        target = root / str(environment_id) / filename
        item = {"environment_id": environment_id, "filename": filename}
        if target.is_file():
            report["present"].append(item)
        elif not (root / filename).is_file():
            report["missing"].append(item)
        elif not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / filename, target)
            report["copied"].append(item)
        else:
            report["copied"].append(item)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage-dir", default=str(Path(__file__).resolve().parents[1] / "storage/foto-barang"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=create_engine(DATABASE_URL))()
    try:
        report = cutover_photo_storage(session, args.storage_dir, dry_run=args.dry_run)
    finally:
        session.close()
    print(report)
    if report["missing"] or report["invalid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
