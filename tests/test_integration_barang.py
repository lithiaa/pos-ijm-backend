import pytest

from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.services.harga import harga_encode
from tests.conftest import TEST_INTEGRATION_KEY


BASE_URL = "/api/integration/barang"
AUTH_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}


def add_barang(
    db,
    *,
    sku="PART-001",
    nama="Brake Pad",
    harga_beli=125_000,
    harga_jual=175_000,
    stok=7,
    satuan="box",
):
    barang = Barang(
        sku=sku,
        nama=nama,
        harga_modal=harga_beli,
        harga_jual=harga_jual,
        satuan=satuan,
    )
    db.add(barang)
    db.flush()
    db.add(StokSaatIni(barang_id=barang.id, jumlah=stok))
    db.commit()
    db.refresh(barang)
    return barang


@pytest.mark.parametrize(
    "integration_key",
    [None, "wrong-key", "", f" {TEST_INTEGRATION_KEY} "],
)
def test_integration_key_failures_are_generic_401(client, integration_key):
    headers = {}
    if integration_key is not None:
        headers["X-Integration-Key"] = integration_key

    response = client.get(f"{BASE_URL}/by-sku/PART-001", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert TEST_INTEGRATION_KEY not in response.text
    assert "wrong-key" not in response.text


def test_get_by_sku_normalizes_input_and_returns_full_item(client, db):
    barang = add_barang(db)

    response = client.get(
        f"{BASE_URL}/by-sku/%20part-001%20",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": barang.id,
        "sku": "PART-001",
        "nama": "Brake Pad",
        "harga_beli": 125_000,
        "harga_jual": 175_000,
        "harga_beli_kode": harga_encode(125_000),
        "stok": 7,
        "satuan": "box",
    }


def test_get_by_sku_requires_an_exact_normalized_match(client, db):
    add_barang(db, sku="PART-001")

    partial = client.get(f"{BASE_URL}/by-sku/PART", headers=AUTH_HEADERS)
    missing = client.get(f"{BASE_URL}/by-sku/MISSING", headers=AUTH_HEADERS)

    assert partial.status_code == 404
    assert missing.status_code == 404


def test_post_creates_manual_normalized_sku_with_numeric_prices_and_defaults(client, db):
    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json={
            "sku": "  oil-001  ",
            "nama": "  Oil Filter  ",
            "harga_beli": 45_000,
            "harga_jual": 60_000,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"],
        "sku": "OIL-001",
        "nama": "Oil Filter",
        "harga_beli": 45_000,
        "harga_jual": 60_000,
        "harga_beli_kode": harga_encode(45_000),
        "stok": 0,
        "satuan": "pcs",
    }

    barang = db.query(Barang).filter(Barang.sku == "OIL-001").one()
    assert barang.harga_modal == 45_000
    assert barang.harga_jual == 60_000
    assert barang.satuan == "pcs"
    assert barang.stok is not None
    assert barang.stok.jumlah == 0


def test_post_rejects_duplicate_normalized_sku(client, db):
    add_barang(db, sku="DUPLICATE-1")

    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json={
            "sku": " duplicate-1 ",
            "nama": "Duplicate",
            "harga_beli": 1,
            "harga_jual": 2,
        },
    )

    assert response.status_code == 409
    assert db.query(Barang).filter(Barang.sku == "DUPLICATE-1").count() == 1


def test_put_by_sku_updates_name_and_both_numeric_prices(client, db):
    barang = add_barang(db, sku="UPDATE-1", nama="Old Name")

    response = client.put(
        f"{BASE_URL}/by-sku/%20update-1%20",
        headers=AUTH_HEADERS,
        json={
            "nama": "  New Name  ",
            "harga_beli": 222_000,
            "harga_jual": 275_000,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": barang.id,
        "sku": "UPDATE-1",
        "nama": "New Name",
        "harga_beli": 222_000,
        "harga_jual": 275_000,
        "harga_beli_kode": harga_encode(222_000),
        "stok": 7,
        "satuan": "box",
    }

    db.expire_all()
    updated = db.query(Barang).filter(Barang.sku == "UPDATE-1").one()
    assert updated.nama == "New Name"
    assert updated.harga_modal == 222_000
    assert updated.harga_jual == 275_000


@pytest.mark.parametrize(
    "payload",
    [
        {"sku": "  ", "nama": "Valid", "harga_beli": 1, "harga_jual": 2},
        {"sku": "VALID", "nama": "\t", "harga_beli": 1, "harga_jual": 2},
        {"sku": "VALID", "nama": "Valid", "harga_beli": -1, "harga_jual": 2},
        {"sku": "VALID", "nama": "Valid", "harga_beli": 1, "harga_jual": -2},
        {"sku": "VALID", "nama": "Valid", "harga_beli": "1", "harga_jual": 2},
    ],
)
def test_post_rejects_blank_fields_negative_prices_and_non_numeric_prices(client, payload):
    response = client.post(BASE_URL, headers=AUTH_HEADERS, json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"nama": " ", "harga_beli": 1, "harga_jual": 2},
        {"nama": "Valid", "harga_beli": -1, "harga_jual": 2},
        {"nama": "Valid", "harga_beli": 1, "harga_jual": -2},
    ],
)
def test_put_rejects_blank_name_and_negative_prices(client, db, payload):
    add_barang(db, sku="VALID")

    response = client.put(
        f"{BASE_URL}/by-sku/VALID",
        headers=AUTH_HEADERS,
        json=payload,
    )

    assert response.status_code == 422
