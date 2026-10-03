"""Two-Toko isolation tests for multi-environment domain scoping."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text

from app.models.barang import Barang, BarangFoto, BarangSupplier
from app.models.environment import Environment
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import IntegrationStockOperation, StokSaatIni, TransaksiStok
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def _token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def _setup_two_tokos(db):
    env_a = Environment(slug="lithia-autoparts", name="Lithia Autoparts", status="active")
    env_b = Environment(slug="toko-b", name="Toko B", status="active")
    db.add_all([env_a, env_b])
    db.flush()
    user_a = User(username="admin-a", password_hash="hash", nama="Admin A", role="admin", environment_id=env_a.id, status="active")
    user_b = User(username="admin-b", password_hash="hash", nama="Admin B", role="admin", environment_id=env_b.id, status="active")
    db.add_all([user_a, user_b])
    db.commit()
    for obj in (env_a, env_b, user_a, user_b):
        db.refresh(obj)
    return env_a, env_b, user_a, user_b


def _auth(user):
    return {"Authorization": f"Bearer {_token(user.id)}"}


class TestBarangIsolation:
    def test_toko_a_cannot_list_toko_b_barang(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Barang(sku="SKU-A", nama="Item A", environment_id=env_a.id), Barang(sku="SKU-B", nama="Item B", environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/barang", headers=_auth(user_a))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["sku"] == "SKU-A"

    def test_toko_a_update_toko_b_barang_gets_404(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        b_b = Barang(sku="SKU-B", nama="Item B", environment_id=env_b.id)
        db.add(b_b)
        db.commit()
        db.refresh(b_b)
        assert client.put(f"/api/barang/{b_b.id}", headers=_auth(user_a), json={"nama": "Hacked"}).status_code == 404

    def test_toko_a_delete_toko_b_barang_gets_404(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        b_b = Barang(sku="SKU-B", nama="Item B", environment_id=env_b.id)
        db.add(b_b)
        db.commit()
        db.refresh(b_b)
        assert client.delete(f"/api/barang/{b_b.id}", headers=_auth(user_a)).status_code == 404

    def test_identical_sku_across_tokos_no_collision(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Barang(sku="SHARED-SKU", nama="A Item", environment_id=env_a.id), Barang(sku="SHARED-SKU", nama="B Item", environment_id=env_b.id)])
        db.commit()
        resp_a = client.get("/api/barang", headers=_auth(user_a)).json()
        resp_b = client.get("/api/barang", headers=_auth(user_b)).json()
        assert resp_a["total"] == 1 and resp_b["total"] == 1
        assert resp_a["data"][0]["nama"] == "A Item"
        assert resp_b["data"][0]["nama"] == "B Item"


class TestSupplierIsolation:
    def test_toko_a_cannot_list_toko_b_suppliers(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Supplier(kode_supplier="SUP-A", nama="Supplier A", environment_id=env_a.id), Supplier(kode_supplier="SUP-B", nama="Supplier B", environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/supplier", headers=_auth(user_a))
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["kode_supplier"] == "SUP-A"

    def test_toko_a_update_toko_b_supplier_gets_404(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        s_b = Supplier(kode_supplier="SUP-B", nama="Supplier B", environment_id=env_b.id)
        db.add(s_b)
        db.commit()
        db.refresh(s_b)
        assert client.put(f"/api/supplier/{s_b.id}", headers=_auth(user_a), json={"nama": "Hacked"}).status_code == 404

    def test_identical_kode_supplier_across_tokos(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Supplier(kode_supplier="SHARED-CODE", nama="A Sup", environment_id=env_a.id), Supplier(kode_supplier="SHARED-CODE", nama="B Sup", environment_id=env_b.id)])
        db.commit()
        assert len(client.get("/api/supplier", headers=_auth(user_a)).json()) == 1
        assert len(client.get("/api/supplier", headers=_auth(user_b)).json()) == 1


class TestStokIsolation:
    def test_toko_a_stok_history_only_own(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        ba = Barang(sku="STK-A", nama="A", environment_id=env_a.id)
        bb = Barang(sku="STK-B", nama="B", environment_id=env_b.id)
        db.add_all([ba, bb])
        db.flush()
        db.add_all([TransaksiStok(barang_id=ba.id, jenis="masuk", jumlah=10, environment_id=env_a.id), TransaksiStok(barang_id=bb.id, jenis="masuk", jumlah=5, environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/stok/riwayat", headers=_auth(user_a))
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


class TestPrintJobIsolation:
    def test_toko_a_cannot_see_toko_b_print_jobs(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        ba = Barang(sku="PJ-A", nama="A", environment_id=env_a.id)
        bb = Barang(sku="PJ-B", nama="B", environment_id=env_b.id)
        db.add_all([ba, bb])
        db.flush()
        db.add_all([PrintJob(barang_id=ba.id, qty=1, environment_id=env_a.id), PrintJob(barang_id=bb.id, qty=1, environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/print-jobs/", headers=_auth(user_a))
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestPublicCatalogLock:
    def test_catalog_only_returns_lithia_autoparts_items(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Barang(sku="CAT-A", nama="Lithia Item", harga_jual=100, environment_id=env_a.id), Barang(sku="CAT-B", nama="Toko B Item", harga_jual=200, environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/katalog/barang")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1
        assert resp.json()["data"][0]["sku"] == "CAT-A"

    def test_catalog_filter_meta_only_lithia(self, client, db):
        env_a, env_b, _, _ = _setup_two_tokos(db)
        db.add_all([Barang(sku="FM-A", nama="A", merek="BrandA", harga_jual=100, environment_id=env_a.id), Barang(sku="FM-B", nama="B", merek="BrandB", harga_jual=200, environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/katalog/barang/filter-meta")
        assert resp.status_code == 200
        assert resp.json()["merek"] == ["BrandA"]

    def test_catalog_detail_toko_b_item_returns_404(self, client, db):
        env_a, env_b, _, _ = _setup_two_tokos(db)
        bb = Barang(sku="DET-B", nama="Toko B Detail", harga_jual=200, environment_id=env_b.id)
        db.add(bb)
        db.commit()
        db.refresh(bb)
        assert client.get(f"/api/katalog/barang/toko-b-detail-{bb.id}").status_code == 404


class TestIntegrationBearerScoping:
    def test_integration_bearer_scopes_to_user_toko(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Barang(sku="INT-A", nama="A", harga_jual=100, environment_id=env_a.id), Barang(sku="INT-B", nama="B", harga_jual=200, environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/integration/barang", headers=_auth(user_a))
        assert resp.status_code == 200
        skus = [item["sku"] for item in resp.json()["data"]]
        assert "INT-A" in skus
        assert "INT-B" not in skus

    def test_integration_supplier_bearer_scopes(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        db.add_all([Supplier(kode_supplier="ISUP-A", nama="Sup A", environment_id=env_a.id), Supplier(kode_supplier="ISUP-B", nama="Sup B", environment_id=env_b.id)])
        db.commit()
        resp = client.get("/api/integration/suppliers", headers=_auth(user_a))
        assert resp.status_code == 200
        codes = [s["kode_supplier"] for s in resp.json()["data"]]
        assert "ISUP-A" in codes
        assert "ISUP-B" not in codes


class TestDashboardIsolation:
    def test_dashboard_counts_only_own_toko(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        ba = Barang(sku="DASH-A", nama="A", stok_minimum=5, environment_id=env_a.id)
        bb = Barang(sku="DASH-B", nama="B", stok_minimum=5, environment_id=env_b.id)
        db.add_all([ba, bb])
        db.flush()
        db.add_all([StokSaatIni(barang_id=ba.id, jumlah=1), StokSaatIni(barang_id=bb.id, jumlah=1)])
        db.commit()
        resp = client.get("/api/dashboard", headers=_auth(user_a))
        assert resp.status_code == 200
        assert resp.json()["total_barang"] == 1


class TestLogsIsolation:
    def test_anonymous_audit_log_survives_and_toko_admin_cannot_list_it(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        from app.models.audit_log import AuditLog
        db.add_all([
            AuditLog(user_id=user_a.id, username="admin-a", action="CREATE", http_method="POST", resource="barang", path="/api/barang", status_code=200, summary="{}", environment_id=env_a.id),
            AuditLog(user_id=None, username=None, action="CREATE", http_method="POST", resource="auth", path="/api/auth/login", status_code=401, summary="{}", environment_id=None),
        ])
        db.commit()
        assert db.query(AuditLog).filter(AuditLog.environment_id.is_(None)).count() == 1
        response = client.get("/api/logs", headers=_auth(user_a))
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert [row["username"] for row in response.json()["data"]] == ["admin-a"]

    def test_logs_only_own_environment(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        from app.models.audit_log import AuditLog
        db.add_all([
            AuditLog(user_id=user_a.id, username="admin-a", action="CREATE", http_method="POST", resource="barang", path="/api/barang", status_code=200, summary="{}", environment_id=env_a.id),
            AuditLog(user_id=user_b.id, username="admin-b", action="CREATE", http_method="POST", resource="barang", path="/api/barang", status_code=200, summary="{}", environment_id=env_b.id),
            AuditLog(user_id=None, username="legacy", action="CREATE", http_method="POST", resource="barang", path="/api/barang", status_code=200, summary="{}", environment_id=None),
        ])
        db.commit()
        resp = client.get("/api/logs", headers=_auth(user_a))
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert [row["username"] for row in resp.json()["data"]] == ["admin-a"]


class TestPhotoIsolation:
    def test_toko_a_cannot_access_toko_b_photo(self, client, db):
        env_a, env_b, user_a, user_b = _setup_two_tokos(db)
        bb = Barang(sku="PHOTO-B", nama="B", environment_id=env_b.id)
        db.add(bb)
        db.flush()
        photo = BarangFoto(barang_id=bb.id, filename="test.jpg", urutan=0, environment_id=env_b.id)
        db.add(photo)
        db.commit()
        db.refresh(photo)
        assert client.delete(f"/api/barang/{bb.id}/photos/{photo.id}", headers=_auth(user_a)).status_code == 404
