"""Multi-supplier stock provenance and product gallery contracts."""
from io import BytesIO

import pytest

from app.models.barang import Barang, BarangFoto, BarangSupplier
from tests.conftest import TEST_INTEGRATION_KEY, get_legacy_environment

INTEGRATION_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}
from app.models.transaksi import TransaksiStok
from app.models.user import User
from app.auth import create_access_token

PNG = b"\x89PNG\r\n\x1a\n" + b"gallery-test"


def auth_client(client, db):
    user = User(username="multi", password_hash="x", nama="Multi", role="admin", environment_id=get_legacy_environment(db).id)
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


def test_gallery_reorders_under_unique_constraint_and_legacy_upload_is_primary(client, db, tmp_path, monkeypatch):
    api = auth_client(client, db)
    from app.routers import upload
    monkeypatch.setattr(upload, "STORAGE_DIR", str(tmp_path))
    product = api.post("/api/barang", json={"sku": "ORDER", "nama": "Order"}).json()
    first = api.post(f"/api/barang/{product['id']}/photos", files={"file": ("one.png", PNG, "image/png")}).json()
    second = api.post(f"/api/barang/{product['id']}/photos", files={"file": ("two.png", PNG, "image/png")}).json()

    promoted = api.put(f"/api/barang/{product['id']}/photos/{second['id']}/primary")
    assert promoted.status_code == 200, promoted.text
    photos = api.get(f"/api/barang/{product['id']}/photos").json()
    assert [(photo["id"], photo["urutan"]) for photo in photos] == [(second["id"], 0), (first["id"], 1)]

    uploaded = api.post(f"/api/upload/foto/{product['id']}", files={"file": ("three.png", PNG, "image/png")})
    assert uploaded.status_code == 200, uploaded.text
    photos = api.get(f"/api/barang/{product['id']}/photos").json()
    assert photos[0]["foto_url"] == uploaded.json()["foto_url"]
    assert [photo["urutan"] for photo in photos] == [0, 1, 2]
    assert db.get(Barang, product["id"]).foto == photos[0]["filename"]


def test_explicit_supplier_update_creates_link_without_replacing_positive_winner(client, db):
    api = auth_client(client, db)
    a = api.post("/api/supplier", json={"nama": "A"}).json()
    b = api.post("/api/supplier", json={"nama": "B"}).json()
    product = api.post("/api/barang", json={"sku": "SUPLINK", "nama": "Supplier link"}).json()
    assert api.put(f"/api/barang/{product['id']}", json={"supplier_id": a["id"]}).status_code == 200
    assert db.get(BarangSupplier, (product["id"], a["id"])).jumlah_masuk_kumulatif == 0
    api.post("/api/stok/masuk", json={"barang_id": product["id"], "jumlah": 3, "supplier_id": b["id"]})
    updated = api.put(f"/api/barang/{product['id']}", json={"supplier_id": a["id"]})
    assert updated.status_code == 200
    assert db.get(BarangSupplier, (product["id"], a["id"])).jumlah_masuk_kumulatif == 0
    assert updated.json()["supplier_id"] == b["id"]
    assert api.post("/api/stok/masuk", json={"barang_id": product["id"], "jumlah": 1, "supplier_id": a["id"]}).status_code == 200
    assert api.get(f"/api/barang/{product['id']}").json()["supplier_id"] == b["id"]


def test_integration_photo_routes_keep_gallery_consistent(client, db, tmp_path, monkeypatch):
    from app.routers import upload
    monkeypatch.setattr(upload, "STORAGE_DIR", str(tmp_path))
    product = auth_client(client, db).post("/api/barang", json={"sku": "INTPHOTO", "nama": "Integration photo"}).json()
    first = client.post(f"/api/integration/barang/{product['id']}/foto", headers=INTEGRATION_HEADERS, files={"file": ("one.png", PNG, "image/png")})
    assert first.status_code == 200
    second = client.post(f"/api/integration/barang/{product['id']}/foto", headers=INTEGRATION_HEADERS, files={"file": ("two.png", PNG, "image/png")})
    assert second.status_code == 200
    photos = client.get(f"/api/barang/{product['id']}/photos").json()
    assert len(photos) == 2 and photos[0]["filename"] == second.json()["foto"]
    assert client.delete(f"/api/integration/barang/{product['id']}/foto", headers=INTEGRATION_HEADERS).status_code == 204
    assert client.get(f"/api/barang/{product['id']}/photos").json()[0]["filename"] == photos[1]["filename"]


def test_product_delete_locks_product_before_gallery_snapshot(client, db, monkeypatch):
    from app.routers import barang
    product = auth_client(client, db).post("/api/barang", json={"sku": "LOCKDELETE", "nama": "Lock delete"}).json()
    locked = []
    original = barang._locked_barang
    monkeypatch.setattr(barang, "_locked_barang", lambda session, product_id: locked.append(product_id) or original(session, product_id))
    assert client.delete(f"/api/barang/{product['id']}").status_code == 200
    assert locked == [product["id"]]


def test_supplier_secondary_link_delete_is_controlled_and_product_delete_cleans_gallery(client, db, tmp_path, monkeypatch):
    from app.routers import barang, upload
    monkeypatch.setattr(upload, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(barang, "STORAGE_DIR", str(tmp_path))
    api = auth_client(client, db)
    supplier = api.post("/api/supplier", json={"nama": "Linked"}).json()
    product = api.post("/api/barang", json={"sku": "DELETEGALLERY", "nama": "Delete gallery", "supplier_id": supplier["id"]}).json()
    photos = [api.post(f"/api/barang/{product['id']}/photos", files={"file": (f"{n}.png", PNG, "image/png")}).json() for n in ("one", "two")]
    assert api.delete(f"/api/supplier/{supplier['id']}").status_code in (400, 409)
    assert api.delete(f"/api/barang/{product['id']}").status_code == 200
    assert all(not (tmp_path / photo["filename"]).exists() for photo in photos)


def test_gallery_allows_shared_legacy_filename_for_each_product(client, db):
    first = Barang(sku="SHARED-ONE", nama="Shared one")
    second = Barang(sku="SHARED-TWO", nama="Shared two")
    db.add_all((first, second))
    db.flush()
    db.add_all((
        BarangFoto(barang_id=first.id, filename="legacy.png", urutan=0),
        BarangFoto(barang_id=second.id, filename="legacy.png", urutan=0),
    ))
    db.commit()
    assert db.query(BarangFoto).filter_by(filename="legacy.png").count() == 2


def test_append_photo_removes_file_when_db_conflict(client, db, tmp_path, monkeypatch):
    from app.routers import upload
    monkeypatch.setattr(upload, "STORAGE_DIR", str(tmp_path))
    api = auth_client(client, db)
    product = api.post("/api/barang", json={"sku": "CONFLICT", "nama": "Conflict"}).json()
    monkeypatch.setattr(upload, "add_photo", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db conflict")))
    with pytest.raises(RuntimeError, match="db conflict"):
        api.post(f"/api/barang/{product['id']}/photos", files={"file": ("x.png", PNG, "image/png")})
    assert list(tmp_path.iterdir()) == []
