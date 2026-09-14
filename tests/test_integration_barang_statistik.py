import pytest

from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.models.user import User
from tests.conftest import TEST_INTEGRATION_KEY


URL = "/api/integration/barang/statistik"
KEY_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}


def add_barang(
    db,
    *,
    sku,
    nama,
    stok,
    stok_minimum=5,
    satuan="pcs",
    foto=None,
):
    barang = Barang(
        sku=sku,
        nama=nama,
        harga_modal=111_000,
        harga_beli_kode="SECRET-BUY-CODE",
        harga_jual=222_000,
        stok_minimum=stok_minimum,
        satuan=satuan,
        foto=foto,
    )
    db.add(barang)
    db.flush()
    if stok is not None:
        db.add(StokSaatIni(barang_id=barang.id, jumlah=stok))
    db.commit()
    db.refresh(barang)
    return barang


def login_headers(client, db, monkeypatch, *, role):
    user = User(
        username=f"statistik-{role}",
        password_hash="unused",
        nama="Statistics User",
        role=role,
    )
    db.add(user)
    db.commit()
    monkeypatch.setattr("app.routers.auth.verify_password", lambda *_: True)
    response = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.parametrize("role", ["admin", "karyawan"])
def test_statistik_accepts_bearer_jwt(client, db, monkeypatch, role):
    headers = login_headers(client, db, monkeypatch, role=role)
    response = client.get(URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "total_barang": 0,
        "total_stok": 0,
        "total_stok_menipis": 0,
        "total_stok_habis": 0,
        "stok_menipis": [],
        "stok_habis": [],
    }


def test_statistik_keeps_legacy_key_compatibility(client):
    response = client.get(URL, headers=KEY_HEADERS)

    assert response.status_code == 200


def test_statistik_missing_auth_returns_generic_401(client):
    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_statistik_returns_exact_summary_boundaries_order_and_safe_fields(client, db):
    absent = add_barang(
        db,
        sku="ABSENT",
        nama="Alpha Absent",
        stok=None,
        satuan="unit",
        foto="absent.webp",
    )
    negative = add_barang(db, sku="NEG", nama="Negative", stok=-2)
    zero = add_barang(db, sku="ZERO", nama="Zulu Zero", stok=0)
    low = add_barang(db, sku="LOW", nama="Low One", stok=1)
    exact_alpha = add_barang(db, sku="EXACT-A", nama="Exact Alpha", stok=5)
    exact_zulu = add_barang(db, sku="EXACT-Z", nama="Exact Zulu", stok=5)
    add_barang(db, sku="SAFE", nama="Safe", stok=6)

    response = client.get(URL, headers=KEY_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "total_barang": 7,
        "total_stok": 15,
        "total_stok_menipis": 3,
        "total_stok_habis": 3,
        "stok_menipis": [
            {
                "id": low.id,
                "sku": "LOW",
                "nama": "Low One",
                "stok": 1,
                "stok_minimum": 5,
                "satuan": "pcs",
                "foto": None,
            },
            {
                "id": exact_alpha.id,
                "sku": "EXACT-A",
                "nama": "Exact Alpha",
                "stok": 5,
                "stok_minimum": 5,
                "satuan": "pcs",
                "foto": None,
            },
            {
                "id": exact_zulu.id,
                "sku": "EXACT-Z",
                "nama": "Exact Zulu",
                "stok": 5,
                "stok_minimum": 5,
                "satuan": "pcs",
                "foto": None,
            },
        ],
        "stok_habis": [
            {
                "id": negative.id,
                "sku": "NEG",
                "nama": "Negative",
                "stok": -2,
                "stok_minimum": 5,
                "satuan": "pcs",
                "foto": None,
            },
            {
                "id": absent.id,
                "sku": "ABSENT",
                "nama": "Alpha Absent",
                "stok": 0,
                "stok_minimum": 5,
                "satuan": "unit",
                "foto": "absent.webp",
            },
            {
                "id": zero.id,
                "sku": "ZERO",
                "nama": "Zulu Zero",
                "stok": 0,
                "stok_minimum": 5,
                "satuan": "pcs",
                "foto": None,
            },
        ],
    }

    serialized = response.text
    assert "harga_modal" not in serialized
    assert "harga_beli" not in serialized
    assert "harga_beli_kode" not in serialized
    assert "harga_jual" not in serialized
