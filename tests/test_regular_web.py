"""Regular Bearer web contracts, including real SQLite foreign keys."""
import pytest
from sqlalchemy import event

from app.auth import create_access_token
from app.database import engine
from app.models.barang import Barang
from app.models.printjob import PrintJob
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
def test_delete_preserves_print_history(auth, db, foreign_keys, status):
    record = item(auth)
    db.add(PrintJob(barang_id=record["id"], qty=1, status=status))
    db.commit()
    response = auth.delete(f"/api/barang/{record['id']}")
    assert response.status_code == 409
    assert "cetak" in response.json()["detail"].lower()
    assert db.get(Barang, record["id"])
    assert db.get(StokSaatIni, record["id"]).jumlah == 3
    assert db.query(TransaksiStok).filter_by(barang_id=record["id"]).count() == 1
    assert db.query(PrintJob).filter_by(barang_id=record["id"], status=status).count() == 1


def test_delete_cleans_only_target_dependencies(auth, db, foreign_keys):
    record = item(auth)
    other = item(auth, sku="OTHER")
    db.add(IntegrationStockOperation(operation_id="qa-delete-operation", barang_id=record["id"]))
    db.commit()
    response = auth.delete(f"/api/barang/{record['id']}")
    assert response.status_code == 200 and response.json() == {"ok": True}
    db.expire_all()
    assert db.get(Barang, record["id"]) is None
    assert db.get(StokSaatIni, record["id"]) is None
    assert db.query(TransaksiStok).filter_by(barang_id=record["id"]).count() == 0
    assert db.query(IntegrationStockOperation).filter_by(barang_id=record["id"]).count() == 0
    assert db.get(Barang, other["id"])
    assert auth.delete(f"/api/barang/{record['id']}").status_code == 404


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


def test_numeric_price_sku_and_nullable_relations(auth):
    category = auth.post("/api/kategori", json={"nama": "QA"}).json()
    record = item(auth, harga_jual=1500, kategori_id=category["id"])
    assert record["harga_jual"] == 1500
    response = auth.put(f"/api/barang/{record['id']}", json={"sku": "CHANGED", "harga_jual": 2500, "kategori_id": None})
    assert response.status_code == 200
    updated = auth.get(f"/api/barang/{record['id']}").json()
    assert updated["sku"] == "CHANGED" and updated["harga_jual"] == 2500
    assert updated["kategori"] is None


def test_item_sort_and_pagination(auth):
    first = item(auth, sku="Z", nama="Zulu")
    second = item(auth, sku="A", nama="Alpha")
    response = auth.get("/api/barang", params={"sort_by": "nama", "sort_order": "ASC", "page": 1, "limit": 1}).json()
    assert response["data"][0]["id"] == second["id"]
    response = auth.get("/api/barang", params={"sort_by": "nama", "sort_order": "ASC", "page": 2, "limit": 1}).json()
    assert response["data"][0]["id"] == first["id"]


def test_stock_out_records_price(auth):
    record = item(auth)
    response = auth.post("/api/stok/keluar", json={"barang_id": record["id"], "jumlah": 2, "harga_satuan": 2500})
    assert response.status_code == 200
    history = auth.get("/api/stok/riwayat?jenis=keluar").json()["data"]
    assert len(history) == 1
    assert history[0]["harga_satuan"] == 2500 and history[0]["total_harga"] == 5000
