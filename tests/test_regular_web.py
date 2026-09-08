"""Regular Bearer web contracts, including real SQLite foreign keys."""
import pytest
from sqlalchemy import event, text

from app.auth import create_access_token
from app.database import engine
from app.models.barang import Barang
from app.models.kategori import Kategori
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import IntegrationStockOperation, StokSaatIni, TransaksiStok
from app.models.user import User


@pytest.fixture
def auth(client, db):
    user = User(username="web-qa", password_hash="unused", nama="QA", role="admin")
    db.add(user)
    db.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token({'sub': str(user.id)})}"
    return client


@pytest.fixture
def foreign_keys():
    engine.dispose()
    def enable(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    event.listen(engine, "connect", enable)
    yield
    engine.dispose()
    event.remove(engine, "connect", enable)


def item(auth, **values):
    response = auth.post("/api/barang", json={"sku": "WEB-QA", "nama": "Web QA", "stok_awal": 3, **values})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("status", ["pending", "printing", "done", "failed"])
def test_delete_cleans_print_jobs_and_all_target_dependencies(
    auth, db, foreign_keys, tmp_path, monkeypatch, status
):
    from app.routers import barang

    monkeypatch.setattr(barang, "STORAGE_DIR", str(tmp_path))
    target = item(auth)
    other = item(auth, sku="OTHER")
    db.get(Barang, target["id"]).foto = "target.jpg"
    db.get(Barang, other["id"]).foto = "other.jpg"
    db.commit()
    (tmp_path / "target.jpg").write_bytes(b"target")
    (tmp_path / "other.jpg").write_bytes(b"other")
    target_print = PrintJob(barang_id=target["id"], qty=1, status=status)
    other_print = PrintJob(barang_id=other["id"], qty=1, status="done")
    db.add_all(
        [
            target_print,
            other_print,
            IntegrationStockOperation(
                operation_id="qa-delete-target", barang_id=target["id"]
            ),
            IntegrationStockOperation(
                operation_id="qa-delete-other", barang_id=other["id"]
            ),
        ]
    )
    db.commit()
    target_id = target["id"]
    other_id = other["id"]
    target_print_id = target_print.id
    other_print_id = other_print.id

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
    response = auth.delete(f"/api/barang/{target_id}")

    assert response.status_code == 200
    assert response.json() == {"id": target_id}
    db.expire_all()
    assert db.get(Barang, target_id) is None
    assert db.get(StokSaatIni, target_id) is None
    assert db.query(TransaksiStok).filter_by(barang_id=target_id).count() == 0
    assert db.query(IntegrationStockOperation).filter_by(barang_id=target_id).count() == 0
    assert db.get(PrintJob, target_print_id) is None
    assert db.get(Barang, other_id)
    assert db.get(PrintJob, other_print_id)
    assert (tmp_path / "other.jpg").read_bytes() == b"other"
    assert not (tmp_path / "target.jpg").exists()
    assert auth.delete(f"/api/barang/{target_id}").status_code == 404


def test_delete_uses_photo_basename(auth, db, foreign_keys, tmp_path, monkeypatch):
    from app.routers import barang

    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    monkeypatch.setattr(barang, "STORAGE_DIR", str(storage))
    record = item(auth)
    db.get(Barang, record["id"]).foto = "../outside.jpg"
    db.commit()

    assert auth.delete(f"/api/barang/{record['id']}").status_code == 200
    assert outside.read_bytes() == b"keep"


def test_delete_keeps_photo_when_commit_fails(auth, db, tmp_path, monkeypatch):
    from app.routers import barang

    monkeypatch.setattr(barang, "STORAGE_DIR", str(tmp_path))
    record = item(auth)
    db.get(Barang, record["id"]).foto = "keep.jpg"
    db.commit()
    (tmp_path / "keep.jpg").write_bytes(b"keep")

    def fail_commit(_session):
        raise RuntimeError("forced delete failure")

    monkeypatch.setattr(type(db), "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced delete failure"):
        auth.delete(f"/api/barang/{record['id']}")

    assert db.get(Barang, record["id"])
    assert (tmp_path / "keep.jpg").read_bytes() == b"keep"


@pytest.mark.parametrize("resource", ["kategori", "supplier"])
def test_master_detail_and_linked_delete(auth, resource):
    record = auth.post(f"/api/{resource}", json={"nama": "QA master"}).json()
    response = auth.get(f"/api/{resource}/{record['id']}")
    assert response.status_code == 200
    assert response.json()["nama"] == "QA master"
    assert auth.put(f"/api/{resource}/{record['id']}", json={"nama": "QA edit"}).json()["nama"] == "QA edit"
    linked = item(auth, **{f"{resource}_id": record["id"]})
    assert auth.delete(f"/api/{resource}/{record['id']}").status_code in (400, 409)
    assert auth.delete(f"/api/barang/{linked['id']}").status_code == 200
    assert auth.delete(f"/api/{resource}/{record['id']}").status_code == 200


def test_create_and_update_use_nullable_relation_ids(auth, db):
    category = auth.post("/api/kategori", json={"nama": "QA category"}).json()
    supplier = auth.post("/api/supplier", json={"nama": "QA supplier"}).json()

    record = item(
        auth,
        harga_jual=1500,
        kategori_id=category["id"],
        supplier_id=supplier["id"],
    )

    assert record["harga_jual"] == 1500
    assert record["kategori"]["id"] == category["id"]
    assert record["supplier"]["id"] == supplier["id"]
    assert record["supplier_nama"] == "QA supplier"
    stored = db.get(Barang, record["id"])
    assert stored.kategori_id == category["id"]
    assert stored.supplier_id == supplier["id"]

    response = auth.put(
        f"/api/barang/{record['id']}",
        json={
            "sku": "CHANGED",
            "harga_jual": 2500,
            "kategori_id": None,
            "supplier_id": None,
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["sku"] == "CHANGED" and updated["harga_jual"] == 2500
    assert updated["kategori"] is None and updated["kategori_id"] is None
    assert updated["supplier"] is None and updated["supplier_id"] is None
    assert updated["supplier_nama"] == ""
    db.expire_all()
    stored = db.get(Barang, record["id"])
    assert stored.kategori_id is None and stored.supplier_id is None


def test_relation_contract_rejects_names_and_unknown_ids(auth):
    assert item(auth, sku="NULL-REFS", kategori_id=None, supplier_id=None)
    for payload in (
        {"sku": "NAME-SUP", "supplier": "Arbitrary supplier"},
        {"sku": "NAME-CAT", "kategori": "Arbitrary category"},
        {"sku": "BAD-SUP", "supplier_id": 9999},
        {"sku": "BAD-CAT", "kategori_id": 9999},
    ):
        assert auth.post(
            "/api/barang",
            json={"nama": "Invalid relation", "stok_awal": 0, **payload},
        ).status_code == 422


def test_item_supports_react_admin_search_page_and_skip_pagination(auth):
    alpha = item(auth, sku="A-SEARCH", nama="Alpha")
    beta = item(auth, sku="B-SEARCH", nama="Beta")
    item(auth, sku="OTHER", nama="Gamma")

    by_q = auth.get(
        "/api/barang",
        params={
            "q": "search",
            "page": 2,
            "limit": 1,
            "sort_by": "nama",
            "sort_order": "ASC",
        },
    ).json()
    by_search = auth.get(
        "/api/barang",
        params={
            "search": "search",
            "skip": 1,
            "limit": 1,
            "sort_by": "nama",
            "sort_order": "ASC",
        },
    ).json()

    assert by_q["total"] == 2
    assert [record["id"] for record in by_q["data"]] == [beta["id"]]
    assert by_search["total"] == 2
    assert [record["id"] for record in by_search["data"]] == [beta["id"]]
    assert alpha["id"] != beta["id"]


def test_stok_menipis_filters_before_total_and_pagination(auth):
    first = item(auth, sku="LOW-A", nama="Alpha low", stok_awal=1, stok_minimum=5)
    second = item(auth, sku="LOW-B", nama="Beta low", stok_awal=2, stok_minimum=5)
    item(auth, sku="SAFE", nama="Aardvark safe", stok_awal=10, stok_minimum=5)

    first_page = auth.get(
        "/api/barang",
        params={
            "stok_menipis": True,
            "skip": 0,
            "limit": 1,
            "sort_by": "nama",
            "sort_order": "ASC",
        },
    ).json()
    second_page = auth.get(
        "/api/barang",
        params={
            "stok_menipis": True,
            "skip": 1,
            "limit": 1,
            "sort_by": "nama",
            "sort_order": "ASC",
        },
    ).json()

    assert first_page["total"] == second_page["total"] == 2
    assert [record["id"] for record in first_page["data"]] == [first["id"]]
    assert [record["id"] for record in second_page["data"]] == [second["id"]]


def test_stock_history_exposes_stable_barang_supplier_and_date_fields(auth):
    supplier = auth.post("/api/supplier", json={"nama": "History supplier"}).json()
    record = item(auth, sku="HISTORY-SKU", supplier_id=supplier["id"])
    response = auth.post(
        "/api/stok/keluar",
        json={"barang_id": record["id"], "jumlah": 2, "harga_satuan": 2500},
    )
    assert response.status_code == 200

    history = auth.get(
        "/api/stok/riwayat",
        params={"jenis": "keluar", "skip": 0, "limit": 20},
    ).json()["data"]

    assert len(history) == 1
    row = history[0]
    assert row["sku"] == "HISTORY-SKU"
    assert row["nama_barang"] == "Web QA"
    assert row["supplier"] == "History supplier"
    assert row["jenis"] == "keluar"
    assert row["harga_satuan"] == 2500 and row["total_harga"] == 5000
    assert row["tanggal"] == row["created_at"]
    assert row["tanggal"]
