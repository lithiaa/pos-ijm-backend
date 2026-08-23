import pytest

from app.models.barang import Barang
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.services.harga import harga_encode
from tests.conftest import TEST_INTEGRATION_KEY


BASE_URL = "/api/integration/barang"
AUTH_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}
CREATE_OPERATION_ID = "11111111-1111-4111-8111-111111111111"
SECOND_OPERATION_ID = "22222222-2222-4222-8222-222222222222"


def integration_keterangan(operation_id):
    return f"Niimbot label integration | NIIMBOT_OPERATION_ID={operation_id}"


def create_payload(**overrides):
    payload = {
        "sku": "OIL-001",
        "nama": "Oil Filter",
        "harga_beli": 45_000,
        "harga_jual": 60_000,
        "jumlah_barang_masuk": 0,
        "operation_id": CREATE_OPERATION_ID,
    }
    payload.update(overrides)
    return payload


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


def test_post_with_zero_quantity_creates_item_without_stock_transaction(client, db):
    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(sku="  oil-001  ", nama="  Oil Filter  "),
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
    assert db.query(TransaksiStok).count() == 0


def test_post_with_positive_quantity_creates_exact_stock_and_transaction(client, db):
    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(jumlah_barang_masuk=6),
    )

    assert response.status_code == 201
    assert response.json()["stok"] == 6

    barang = db.query(Barang).filter(Barang.sku == "OIL-001").one()
    assert barang.stok.jumlah == 6
    transaction = db.query(TransaksiStok).one()
    assert transaction.barang_id == barang.id
    assert transaction.jenis == "masuk"
    assert transaction.jumlah == 6
    assert transaction.harga_satuan == 45_000
    assert transaction.total_harga == 270_000
    assert transaction.keterangan == integration_keterangan(CREATE_OPERATION_ID)
    assert transaction.user_id is None


def test_post_retry_with_same_operation_id_returns_item_without_readding_stock(client, db):
    payload = create_payload(jumlah_barang_masuk=4)

    first = client.post(BASE_URL, headers=AUTH_HEADERS, json=payload)
    retry = client.post(BASE_URL, headers=AUTH_HEADERS, json=payload)

    assert first.status_code == 201
    assert retry.status_code == 201
    assert retry.json() == first.json()
    db.expire_all()
    assert db.query(Barang).filter(Barang.sku == "OIL-001").one().stok.jumlah == 4
    assert db.query(TransaksiStok).count() == 1


def test_post_rejects_duplicate_normalized_sku(client, db):
    add_barang(db, sku="DUPLICATE-1")

    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(
            sku=" duplicate-1 ",
            nama="Duplicate",
            harga_beli=1,
            harga_jual=2,
            operation_id=SECOND_OPERATION_ID,
        ),
    )

    assert response.status_code == 409
    assert db.query(Barang).filter(Barang.sku == "DUPLICATE-1").count() == 1
    assert db.query(TransaksiStok).count() == 0


def test_existing_sku_stock_endpoint_atomically_increments_and_records_transaction(client, db):
    barang = add_barang(db, sku="EXISTING-1", stok=7)

    response = client.post(
        f"{BASE_URL}/by-sku/%20existing-1%20/stok-masuk",
        headers=AUTH_HEADERS,
        json={
            "jumlah_barang_masuk": 5,
            "harga_satuan": 130_000,
            "operation_id": CREATE_OPERATION_ID,
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == barang.id
    assert response.json()["stok"] == 12
    db.expire_all()
    assert db.query(Barang).filter(Barang.id == barang.id).one().stok.jumlah == 12
    transaction = db.query(TransaksiStok).one()
    assert transaction.jenis == "masuk"
    assert transaction.jumlah == 5
    assert transaction.harga_satuan == 130_000
    assert transaction.total_harga == 650_000
    assert transaction.keterangan == integration_keterangan(CREATE_OPERATION_ID)
    assert transaction.user_id is None


def test_existing_sku_stock_retry_is_noop_and_returns_same_current_stock(client, db):
    add_barang(db, sku="RETRY-1", stok=3)
    payload = {
        "jumlah_barang_masuk": 2,
        "harga_satuan": 50_000,
        "operation_id": CREATE_OPERATION_ID,
    }

    first = client.post(
        f"{BASE_URL}/by-sku/RETRY-1/stok-masuk", headers=AUTH_HEADERS, json=payload
    )
    retry = client.post(
        f"{BASE_URL}/by-sku/RETRY-1/stok-masuk", headers=AUTH_HEADERS, json=payload
    )

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json()["stok"] == 5
    assert retry.json()["stok"] == 5
    db.expire_all()
    assert db.query(Barang).filter(Barang.sku == "RETRY-1").one().stok.jumlah == 5
    assert db.query(TransaksiStok).count() == 1


def test_existing_sku_different_operation_ids_both_apply(client, db):
    add_barang(db, sku="TWICE-1", stok=10)

    for operation_id in (CREATE_OPERATION_ID, SECOND_OPERATION_ID):
        response = client.post(
            f"{BASE_URL}/by-sku/TWICE-1/stok-masuk",
            headers=AUTH_HEADERS,
            json={
                "jumlah_barang_masuk": 3,
                "harga_satuan": 25_000,
                "operation_id": operation_id,
            },
        )
        assert response.status_code == 200

    db.expire_all()
    assert db.query(Barang).filter(Barang.sku == "TWICE-1").one().stok.jumlah == 16
    assert db.query(TransaksiStok).count() == 2


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
    assert updated.stok.jumlah == 7
    assert db.query(TransaksiStok).count() == 0


def test_metadata_conflict_does_not_modify_existing_stock(client, db):
    add_barang(db, sku="CONFLICT-1", stok=9)

    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(
            sku="CONFLICT-1",
            jumlah_barang_masuk=100,
            operation_id=SECOND_OPERATION_ID,
        ),
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.query(Barang).filter(Barang.sku == "CONFLICT-1").one().stok.jumlah == 9
    assert db.query(TransaksiStok).count() == 0


@pytest.mark.parametrize(
    "payload",
    [
        create_payload(sku="  "),
        create_payload(nama="\t"),
        create_payload(harga_beli=-1),
        create_payload(harga_jual=-2),
        create_payload(harga_beli="1"),
        create_payload(jumlah_barang_masuk=-1),
        create_payload(jumlah_barang_masuk="1"),
        create_payload(operation_id="not-a-uuid"),
        {k: v for k, v in create_payload().items() if k != "operation_id"},
        {k: v for k, v in create_payload().items() if k != "jumlah_barang_masuk"},
        create_payload(stok=10),
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


@pytest.mark.parametrize(
    "payload",
    [
        {"harga_satuan": 1, "operation_id": CREATE_OPERATION_ID},
        {"jumlah_barang_masuk": 1, "operation_id": CREATE_OPERATION_ID},
        {"jumlah_barang_masuk": 1, "harga_satuan": 1},
        {
            "jumlah_barang_masuk": -1,
            "harga_satuan": 1,
            "operation_id": CREATE_OPERATION_ID,
        },
        {
            "jumlah_barang_masuk": "1",
            "harga_satuan": 1,
            "operation_id": CREATE_OPERATION_ID,
        },
        {
            "jumlah_barang_masuk": 1,
            "harga_satuan": -1,
            "operation_id": CREATE_OPERATION_ID,
        },
        {
            "jumlah_barang_masuk": 1,
            "harga_satuan": 1,
            "operation_id": "bad-operation-id",
        },
    ],
)
def test_stock_endpoint_rejects_missing_negative_and_malformed_fields(client, db, payload):
    add_barang(db, sku="VALIDATION-1")

    response = client.post(
        f"{BASE_URL}/by-sku/VALIDATION-1/stok-masuk",
        headers=AUTH_HEADERS,
        json=payload,
    )

    assert response.status_code == 422


def test_stock_endpoint_preserves_integration_key_auth(client, db):
    add_barang(db, sku="AUTH-1")

    response = client.post(
        f"{BASE_URL}/by-sku/AUTH-1/stok-masuk",
        json={
            "jumlah_barang_masuk": 1,
            "harga_satuan": 1,
            "operation_id": CREATE_OPERATION_ID,
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_create_rolls_back_item_stock_and_transaction_when_commit_fails(
    client, db, monkeypatch
):
    def fail_commit(_session):
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(type(db), "commit", fail_commit)

    with pytest.raises(RuntimeError, match="forced commit failure"):
        client.post(
            BASE_URL,
            headers=AUTH_HEADERS,
            json=create_payload(jumlah_barang_masuk=8),
        )

    assert db.query(Barang).filter(Barang.sku == "OIL-001").count() == 0
    assert db.query(StokSaatIni).count() == 0
    assert db.query(TransaksiStok).count() == 0
