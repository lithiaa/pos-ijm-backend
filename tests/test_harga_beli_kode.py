from app.auth import create_access_token
from app.models.barang import Barang
from app.models.user import User
from app.services.harga import harga_encode


MANUAL_CODE = "LABEL-MANUAL-X9"


def auth_headers(db):
    user = User(username="test-user", password_hash="unused", nama="Test User")
    db.add(user)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


def test_label_uses_stored_buy_code_not_encoded_buy_price(client, db):
    barang = Barang(
        sku="LABEL-001",
        nama="Label Item",
        harga_modal=45_000,
        harga_beli_kode=MANUAL_CODE,
        harga_jual=60_000,
    )
    db.add(barang)
    db.commit()

    response = client.get(f"/api/label/sticker/{barang.id}")

    assert response.status_code == 200
    assert MANUAL_CODE in response.text
    assert harga_encode(45_000) not in response.text


def test_main_barang_create_defaults_code_once_and_price_update_preserves_it(client, db):
    headers = auth_headers(db)
    created = client.post(
        "/api/barang",
        headers=headers,
        json={
            "sku": "MAIN-001",
            "nama": "Main Item",
            "harga_modal": 45_000,
            "harga_jual_kode": harga_encode(60_000),
        },
    )

    assert created.status_code == 200
    initial_code = harga_encode(45_000)
    assert created.json()["harga_beli_kode"] == initial_code

    updated = client.put(
        f"/api/barang/{created.json()['id']}",
        headers=headers,
        json={"harga_modal": 99_000},
    )

    assert updated.status_code == 200
    assert updated.json()["harga_modal"] == 99_000
    assert updated.json()["harga_beli_kode"] == initial_code
    db.expire_all()
    barang = db.query(Barang).filter(Barang.sku == "MAIN-001").one()
    assert barang.harga_beli_kode == initial_code


def test_main_barang_explicit_code_is_trimmed_and_independent(client, db):
    headers = auth_headers(db)
    created = client.post(
        "/api/barang",
        headers=headers,
        json={
            "sku": "MAIN-002",
            "nama": "Manual Main Item",
            "harga_modal": 45_000,
            "harga_beli_kode": "  MAIN-MANUAL  ",
            "harga_jual_kode": harga_encode(60_000),
        },
    )

    assert created.status_code == 200
    assert created.json()["harga_beli_kode"] == "MAIN-MANUAL"

    updated = client.put(
        f"/api/barang/{created.json()['id']}",
        headers=headers,
        json={
            "harga_modal": 88_000,
            "harga_beli_kode": "  MAIN-CHANGED  ",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["harga_modal"] == 88_000
    assert updated.json()["harga_beli_kode"] == "MAIN-CHANGED"
