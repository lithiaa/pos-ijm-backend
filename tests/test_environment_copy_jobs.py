import json
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.models.admin import EnvironmentCopyJob
from app.models.audit_log import AuditLog
from app.models.barang import Barang, BarangFoto, BarangSupplier
from app.models.environment import Environment
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def _headers(user, request_key=None):
    token = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    result = {"Authorization": f"Bearer {token}"}
    if request_key:
        result["Idempotency-Key"] = request_key
    return result


def _fixture(db, tmp_path):
    owner = User(username="copy-owner", password_hash="x", nama="Owner", email="copy-owner@example.test", role="platform_owner", status="active")
    source = Environment(
        slug="copy-source", name="Source", status="active", business_type="retail",
        logo_url="logo.png", address="Source Road", phone="123", timezone="Asia/Jakarta", currency="IDR",
    )
    target = Environment(slug="copy-target", name="Target", status="active")
    db.add_all([owner, source, target]); db.flush()
    supplier = Supplier(environment_id=source.id, kode_supplier="SRC", nama="Source Supplier")
    db.add(supplier); db.flush()
    barang = Barang(environment_id=source.id, sku="COPY-1", nama="Copy Item", supplier_id=supplier.id, harga_jual=500)
    db.add(barang); db.flush()
    db.add_all([
        BarangSupplier(environment_id=source.id, barang_id=barang.id, supplier_id=supplier.id, jumlah_masuk_kumulatif=8),
        StokSaatIni(environment_id=source.id, barang_id=barang.id, jumlah=7),
        TransaksiStok(environment_id=source.id, barang_id=barang.id, supplier_id=supplier.id, jenis="masuk", jumlah=7),
        PrintJob(environment_id=source.id, barang_id=barang.id, qty=1),
        AuditLog(environment_id=source.id, action="CREATE", http_method="POST", resource="barang", path="/api/barang", status_code=200, summary="{}"),
        User(username="source-user", password_hash="x", nama="Source User", email="source-user@example.test", role="viewer", environment_id=source.id, status="active"),
    ])
    photo_dir = tmp_path / "photos"; photo_dir.mkdir()
    (photo_dir / "source.jpg").write_bytes(b"photo")
    db.add(BarangFoto(environment_id=source.id, barang_id=barang.id, filename="source.jpg", urutan=0))
    barang.foto = "source.jpg"
    db.commit()
    for obj in (owner, source, target): db.refresh(obj)
    return owner, source, target, photo_dir


def test_copy_job_maps_catalog_photos_settings_and_excludes_sensitive_data(client, db, tmp_path, monkeypatch):
    import app.services.environment_copy as copy_service

    owner, source, target, photo_dir = _fixture(db, tmp_path)
    monkeypatch.setattr(copy_service, "STORAGE_DIR", str(photo_dir))
    payload = {"source_environment_id": source.id, "target_environment_id": target.id}
    first = client.post("/api/environment-copy-jobs", headers=_headers(owner, "copy-001"), json=payload)
    second = client.post("/api/environment-copy-jobs", headers=_headers(owner, "copy-001"), json=payload)
    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert first.json()["status"] == "completed"
    assert db.query(EnvironmentCopyJob).count() == 1

    copied_supplier = db.query(Supplier).filter_by(environment_id=target.id).one()
    copied_barang = db.query(Barang).filter_by(environment_id=target.id).one()
    copied_link = db.query(BarangSupplier).filter_by(environment_id=target.id).one()
    copied_photo = db.query(BarangFoto).filter_by(environment_id=target.id).one()
    copied_stock = db.query(StokSaatIni).filter_by(environment_id=target.id).one()
    assert copied_supplier.id != db.query(Supplier).filter_by(environment_id=source.id).one().id
    assert copied_barang.supplier_id == copied_supplier.id
    assert copied_link.barang_id == copied_barang.id
    assert copied_link.supplier_id == copied_supplier.id
    assert copied_photo.barang_id == copied_barang.id
    assert copied_photo.filename.startswith(f"{target.id}/")
    assert (photo_dir / copied_photo.filename).read_bytes() == b"photo"
    assert copied_stock.jumlah == 0
    db.refresh(target)
    assert (target.business_type, target.address, target.currency) == ("retail", "Source Road", "IDR")
    assert db.query(User).filter_by(environment_id=target.id).count() == 0
    assert db.query(AuditLog).filter_by(environment_id=target.id).count() == 0
    assert db.query(TransaksiStok).filter_by(environment_id=target.id).count() == 0
    assert db.query(PrintJob).filter_by(environment_id=target.id).count() == 0


def test_copy_job_inventory_opt_in_and_cancel_pending(client, db, tmp_path, monkeypatch):
    import app.services.environment_copy as copy_service

    owner, source, target, photo_dir = _fixture(db, tmp_path)
    target_two = Environment(slug="copy-target-two", name="Target Two", status="active")
    db.add(target_two); db.commit(); db.refresh(target_two)
    monkeypatch.setattr(copy_service, "STORAGE_DIR", str(photo_dir))
    response = client.post(
        "/api/environment-copy-jobs",
        headers=_headers(owner, "copy-stock"),
        json={"source_environment_id": source.id, "target_environment_id": target_two.id, "include_inventory": True, "include_photos": False},
    )
    assert response.status_code == 201, response.text
    assert db.query(StokSaatIni).filter_by(environment_id=target_two.id).one().jumlah == 7
    assert db.query(BarangFoto).filter_by(environment_id=target_two.id).count() == 0

    pending_target = Environment(slug="pending-target", name="Pending", status="active")
    db.add(pending_target); db.flush()
    pending = EnvironmentCopyJob(
        request_key="pending", source_environment_id=source.id, target_environment_id=pending_target.id,
        requested_by_user_id=owner.id, options="{}", request_hash="hash", status="pending",
    )
    db.add(pending); db.commit(); db.refresh(pending)
    cancelled = client.post(f"/api/environment-copy-jobs/{pending.id}/cancel", headers=_headers(owner))
    assert cancelled.status_code == 200
    db.refresh(pending)
    assert pending.status == "cancelled"
    assert db.query(Barang).filter_by(environment_id=pending_target.id).count() == 0
