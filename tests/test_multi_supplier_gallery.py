"""Multi-supplier stock provenance and product gallery contracts."""
from io import BytesIO

from app.models.barang import BarangSupplier
from app.models.transaksi import TransaksiStok
from app.models.user import User
from app.auth import create_access_token

PNG = b"\x89PNG\r\n\x1a\n" + b"gallery-test"


def auth_client(client, db):
    user = User(username="multi", password_hash="x", nama="Multi", role="admin")
    db.add(user)
    db.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token({'sub': str(user.id)})}"
    return client


def test_supplier_ranking_provenance_and_legacy_stock_in(client, db):
    api = auth_client(client, db)
    a = api.post("/api/supplier", json={"nama": "A"}).json()
    b = api.post("/api/supplier", json={"nama": "B"}).json()
    product = api.post("/api/barang", json={"sku": "MULTI", "nama": "Multi"}).json()

    for supplier_id, amount in ((a["id"], 10), (b["id"], 9), (b["id"], 2), (a["id"], 1)):
        response = api.post("/api/stok/masuk", json={"barang_id": product["id"], "jumlah": amount, "supplier_id": supplier_id})
        assert response.status_code == 200, response.text

    detail = api.get(f"/api/barang/{product['id']}").json()
    assert detail["primary_supplier_id"] == b["id"]
    assert detail["supplier_id"] == b["id"]
    assert [(x["id"], x["jumlah_masuk_kumulatif"], x["is_primary"]) for x in detail["suppliers"]] == [
        (a["id"], 11, False), (b["id"], 11, True)
    ]
    history = api.get("/api/stok/riwayat", params={"jenis": "masuk"}).json()["data"]
    assert history[0]["supplier_id"] == a["id"]
    assert history[0]["supplier_nama"] == "A"
    assert db.query(TransaksiStok).filter_by(barang_id=product["id"]).count() == 4

    response = api.post("/api/stok/masuk", json={"barang_id": product["id"], "jumlah": 1})
    assert response.status_code == 200
    assert db.query(BarangSupplier).filter_by(barang_id=product["id"]).count() == 2
    assert db.query(TransaksiStok).filter_by(barang_id=product["id"]).order_by(TransaksiStok.id.desc()).first().supplier_id is None


def test_gallery_promotes_primary_and_legacy_alias(client, db, tmp_path, monkeypatch):
    api = auth_client(client, db)
    from app.routers import upload
    monkeypatch.setattr(upload, "STORAGE_DIR", str(tmp_path))
    product = api.post("/api/barang", json={"sku": "PHOTOS", "nama": "Photos"}).json()
    first = api.post(f"/api/barang/{product['id']}/photos", files={"file": ("one.png", PNG, "image/png")})
    second = api.post(f"/api/barang/{product['id']}/photos", files={"file": ("two.png", PNG, "image/png")})
    assert first.status_code == second.status_code == 200
    photos = api.get(f"/api/barang/{product['id']}/photos").json()
    assert [p["is_primary"] for p in photos] == [True, False]
    assert api.delete(f"/api/barang/{product['id']}/photos/{photos[0]['id']}").status_code == 200
    detail = api.get(f"/api/barang/{product['id']}").json()
    assert detail["foto"] == photos[1]["filename"]
    assert detail["photos"][0]["is_primary"] is True


def test_gallery_rejects_unauthorized_and_malformed(client, db):
    api = auth_client(client, db)
    product = api.post("/api/barang", json={"sku": "BADPHOTO", "nama": "Bad"}).json()
    token = api.headers["Authorization"]
    client.headers.pop("Authorization")
    assert client.post(f"/api/barang/{product['id']}/photos", files={"file": ("x.png", PNG, "image/png")}).status_code == 401
    client.headers["Authorization"] = token
    assert client.post(f"/api/barang/{product['id']}/photos", files={"file": ("x.png", b"not image", "image/png")}).status_code == 422
