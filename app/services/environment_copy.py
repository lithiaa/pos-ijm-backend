import json
import os
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.admin import EnvironmentCopyJob
from app.models.barang import Barang, BarangFoto, BarangSupplier
from app.models.environment import Environment
from app.models.supplier import Supplier
from app.models.transaksi import StokSaatIni
from app.routers.upload import STORAGE_DIR

SETTINGS = ("business_type", "logo_url", "address", "phone", "timezone", "currency")


def _copy_photo(source_filename: str, source_environment_id: int, target_environment_id: int | None = None) -> str:
    if not source_filename or source_filename != os.path.basename(source_filename):
        raise ValueError("Source filename must be a plain storage filename")
    if target_environment_id is None:
        raise ValueError("Target environment is required")
    filename = f"{uuid.uuid4()}{os.path.splitext(source_filename)[1]}"
    storage_root = os.path.realpath(STORAGE_DIR)
    source_path = os.path.realpath(os.path.join(storage_root, str(source_environment_id), source_filename))
    target_dir = os.path.realpath(os.path.join(storage_root, str(target_environment_id)))
    target_path = os.path.join(target_dir, filename)
    if os.path.commonpath((storage_root, source_path)) != storage_root:
        raise ValueError("Source filename must be within storage directory")
    if os.path.commonpath((storage_root, target_dir)) != storage_root:
        raise ValueError("Target path traversal detected")
    os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return filename


def run_copy_job(db: Session, job: EnvironmentCopyJob) -> None:
    options = json.loads(job.options)
    source = db.get(Environment, job.source_environment_id)
    target = db.get(Environment, job.target_environment_id)
    if not source or not target:
        raise ValueError("Source or target environment not found")
    if db.query(Barang.id).filter(Barang.environment_id == target.id).first() or db.query(Supplier.id).filter(Supplier.environment_id == target.id).first():
        raise ValueError("Target environment must be fresh")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job.status = "running"
    job.started_at = now
    db.flush()
    created_files: list[str] = []
    try:
        if options["include_settings"]:
            for field in SETTINGS:
                setattr(target, field, getattr(source, field))

        supplier_map: dict[int, int] = {}
        if options["include_suppliers"]:
            for source_supplier in db.query(Supplier).filter_by(environment_id=source.id).order_by(Supplier.id):
                copied = Supplier(
                    environment_id=target.id,
                    kode_supplier=source_supplier.kode_supplier,
                    nama=source_supplier.nama,
                    kontak=source_supplier.kontak,
                    telepon=source_supplier.telepon,
                    email=source_supplier.email,
                )
                db.add(copied); db.flush()
                supplier_map[source_supplier.id] = copied.id

        barang_map: dict[int, int] = {}
        if options["include_barang"]:
            for source_barang in db.query(Barang).filter_by(environment_id=source.id).order_by(Barang.id):
                copied = Barang(
                    environment_id=target.id,
                    sku=source_barang.sku,
                    nama=source_barang.nama,
                    merek=source_barang.merek,
                    shopee_url=source_barang.shopee_url,
                    supplier_id=supplier_map.get(source_barang.supplier_id),
                    harga_modal=source_barang.harga_modal,
                    harga_beli_kode=source_barang.harga_beli_kode,
                    harga_jual=source_barang.harga_jual,
                    stok_minimum=source_barang.stok_minimum,
                    satuan=source_barang.satuan,
                    deskripsi=source_barang.deskripsi,
                )
                db.add(copied); db.flush()
                barang_map[source_barang.id] = copied.id
                source_stock = db.get(StokSaatIni, source_barang.id)
                db.add(StokSaatIni(environment_id=target.id, barang_id=copied.id, jumlah=(source_stock.jumlah if source_stock and options["include_inventory"] else 0)))

            for link in db.query(BarangSupplier).filter_by(environment_id=source.id).all():
                if link.barang_id in barang_map and link.supplier_id in supplier_map:
                    db.add(BarangSupplier(
                        environment_id=target.id,
                        barang_id=barang_map[link.barang_id],
                        supplier_id=supplier_map[link.supplier_id],
                        jumlah_masuk_kumulatif=(link.jumlah_masuk_kumulatif if options["include_inventory"] else 0),
                    ))

            if options["include_photos"]:
                gallery_filenames: dict[int, set[str]] = {}
                for photo in db.query(BarangFoto).filter_by(environment_id=source.id).order_by(BarangFoto.id):
                    if photo.barang_id not in barang_map:
                        continue
                    filename = _copy_photo(photo.filename, source.id, target.id)
                    created_files.append(filename)
                    gallery_filenames.setdefault(photo.barang_id, set()).add(photo.filename)
                    db.add(BarangFoto(environment_id=target.id, barang_id=barang_map[photo.barang_id], filename=filename, urutan=photo.urutan))
                    copied_barang = db.get(Barang, barang_map[photo.barang_id])
                    if photo.urutan == 0:
                        copied_barang.foto = filename

                for source_barang_id, target_barang_id in barang_map.items():
                    source_barang = db.get(Barang, source_barang_id)
                    if not source_barang.foto or source_barang.foto in gallery_filenames.get(source_barang_id, set()):
                        continue
                    filename = _copy_photo(source_barang.foto, source.id, target.id)
                    created_files.append(filename)
                    urutan = db.query(BarangFoto).filter_by(barang_id=target_barang_id).count()
                    db.add(BarangFoto(environment_id=target.id, barang_id=target_barang_id, filename=filename, urutan=urutan))
                    db.get(Barang, target_barang_id).foto = filename

        job.status = "completed"
        job.progress = 100
        job.result = json.dumps({"suppliers": len(supplier_map), "barang": len(barang_map)})
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
    except Exception:
        db.rollback()
        for filename in created_files:
            try:
                os.remove(os.path.join(STORAGE_DIR, str(target.id), filename))
            except OSError:
                pass
        raise
