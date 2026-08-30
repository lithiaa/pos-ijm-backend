import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.auth import create_access_token
from app.models.supplier import Supplier
from app.models.user import User
from tests.conftest import TEST_INTEGRATION_KEY


INTEGRATION_URL = "/api/integration/suppliers"
INTEGRATION_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}
SUPPLIER_URL = "/api/supplier"


def bearer_headers(db):
    user = User(username="supplier-test", password_hash="unused", nama="Supplier Test")
    db.add(user)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


def add_supplier(db, *, kode_supplier="SUP-001", nama="Supplier One", **fields):
    supplier = Supplier(kode_supplier=kode_supplier, nama=nama, **fields)
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return supplier


@pytest.mark.parametrize(
    "integration_key",
    [None, "wrong-key", "", f" {TEST_INTEGRATION_KEY} "],
)
def test_supplier_dropdown_rejects_missing_wrong_blank_and_padded_keys(
    client, integration_key
):
    headers = {}
    if integration_key is not None:
        headers["X-Integration-Key"] = integration_key

    response = client.get(INTEGRATION_URL, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_supplier_dropdown_returns_sorted_minimal_exact_response(client, db):
    zulu = add_supplier(
        db,
        kode_supplier="z-2",
        nama="Zulu",
        kontak="secret contact",
        telepon="secret phone",
        email="secret@example.test",
    )
    alpha_second = add_supplier(db, kode_supplier="A-1", nama="beta")
    alpha_first = add_supplier(db, kode_supplier="a-1", nama="Alpha")

    response = client.get(INTEGRATION_URL, headers=INTEGRATION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": alpha_first.id,
                "kode_supplier": "a-1",
                "nama_supplier": "Alpha",
            },
            {
                "id": alpha_second.id,
                "kode_supplier": "A-1",
                "nama_supplier": "beta",
            },
            {
                "id": zulu.id,
                "kode_supplier": "z-2",
                "nama_supplier": "Zulu",
            },
        ]
    }
    assert all(
        set(item) == {"id", "kode_supplier", "nama_supplier"}
        for item in response.json()["data"]
    )


def test_supplier_dropdown_serializes_legacy_null_code_as_empty_string(client, db):
    supplier = add_supplier(db, kode_supplier=None, nama="Legacy Supplier")

    response = client.get(INTEGRATION_URL, headers=INTEGRATION_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": supplier.id,
                "kode_supplier": "",
                "nama_supplier": "Legacy Supplier",
            }
        ]
    }


def test_supplier_dropdown_openapi_contract(client):
    openapi = client.get("/openapi.json").json()

    assert INTEGRATION_URL in openapi["paths"]
    assert set(openapi["paths"][INTEGRATION_URL]) == {"get"}
    schema = openapi["paths"][INTEGRATION_URL]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/IntegrationSupplierListResponse"}


def test_supplier_create_old_payload_generates_code_and_preserves_legacy_fields(
    client, db
):
    response = client.post(
        SUPPLIER_URL,
        headers=bearer_headers(db),
        json={
            "nama": "  Legacy Client Supplier  ",
            "kontak": "Buyer",
            "telepon": "123",
            "email": "buyer@example.test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kode_supplier"] == f"SUP-{body['id']:03d}"
    assert body["nama"] == "Legacy Client Supplier"
    assert body["nama_supplier"] == "Legacy Client Supplier"
    assert body["kontak"] == "Buyer"
    assert body["telepon"] == "123"
    assert body["email"] == "buyer@example.test"


def test_supplier_create_normalizes_explicit_code(client, db):
    response = client.post(
        SUPPLIER_URL,
        headers=bearer_headers(db),
        json={"kode_supplier": "  ven-abc  ", "nama": "  Vendor ABC  "},
    )

    assert response.status_code == 200
    assert response.json()["kode_supplier"] == "VEN-ABC"
    assert response.json()["nama"] == "Vendor ABC"
    assert response.json()["nama_supplier"] == "Vendor ABC"


def test_supplier_create_duplicate_code_returns_409_and_rolls_back(client, db):
    add_supplier(db, kode_supplier="DUP-1", nama="Existing")
    headers = bearer_headers(db)

    response = client.post(
        SUPPLIER_URL,
        headers=headers,
        json={"kode_supplier": " dup-1 ", "nama": "Duplicate"},
    )

    assert response.status_code == 409
    assert db.query(Supplier).filter(Supplier.kode_supplier == "DUP-1").count() == 1
    assert db.query(Supplier).filter(Supplier.nama == "Duplicate").count() == 0
    assert client.get(SUPPLIER_URL, headers=headers).status_code == 200


def test_supplier_update_normalizes_code_and_name(client, db):
    supplier = add_supplier(db, kode_supplier="OLD", nama="Old Name")

    response = client.put(
        f"{SUPPLIER_URL}/{supplier.id}",
        headers=bearer_headers(db),
        json={"kode_supplier": " new-code ", "nama": " New Name "},
    )

    assert response.status_code == 200
    assert response.json()["kode_supplier"] == "NEW-CODE"
    assert response.json()["nama"] == "New Name"
    assert response.json()["nama_supplier"] == "New Name"


@pytest.mark.parametrize("kode_supplier", [None, "", "   ", "X" * 51])
def test_supplier_update_rejects_null_blank_and_too_long_code(
    client, db, kode_supplier
):
    supplier = add_supplier(db, kode_supplier="KEEP", nama="Keep")

    response = client.put(
        f"{SUPPLIER_URL}/{supplier.id}",
        headers=bearer_headers(db),
        json={"kode_supplier": kode_supplier},
    )

    assert response.status_code == 422
    db.refresh(supplier)
    assert supplier.kode_supplier == "KEEP"


@pytest.mark.parametrize("kode_supplier", ["", "   ", "X" * 51])
def test_supplier_create_rejects_blank_and_too_long_supplied_code(
    client, db, kode_supplier
):
    response = client.post(
        SUPPLIER_URL,
        headers=bearer_headers(db),
        json={"kode_supplier": kode_supplier, "nama": "Valid Name"},
    )

    assert response.status_code == 422


def test_supplier_update_duplicate_code_returns_409_without_changes(client, db):
    first = add_supplier(db, kode_supplier="FIRST", nama="First")
    second = add_supplier(db, kode_supplier="SECOND", nama="Second")
    headers = bearer_headers(db)

    response = client.put(
        f"{SUPPLIER_URL}/{second.id}",
        headers=headers,
        json={"kode_supplier": " first ", "nama": "Changed"},
    )

    assert response.status_code == 409
    db.expire_all()
    assert db.get(Supplier, first.id).kode_supplier == "FIRST"
    unchanged = db.get(Supplier, second.id)
    assert unchanged.kode_supplier == "SECOND"
    assert unchanged.nama == "Second"
    assert client.get(SUPPLIER_URL, headers=headers).status_code == 200


@pytest.mark.parametrize("nama", [None, "", "   ", "X" * 151])
def test_supplier_update_rejects_invalid_supplied_name(client, db, nama):
    supplier = add_supplier(db, kode_supplier="KEEP", nama="Keep")

    response = client.put(
        f"{SUPPLIER_URL}/{supplier.id}",
        headers=bearer_headers(db),
        json={"nama": nama},
    )

    assert response.status_code == 422


def test_supplier_out_list_handles_legacy_null_code_and_adds_name_alias(client, db):
    supplier = add_supplier(db, kode_supplier=None, nama="Legacy")

    response = client.get(SUPPLIER_URL, headers=bearer_headers(db))

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": supplier.id,
            "kode_supplier": None,
            "nama": "Legacy",
            "nama_supplier": "Legacy",
            "kontak": None,
            "telepon": None,
            "email": None,
            "jumlah_barang": 0,
        }
    ]


def test_barang_meta_adds_supplier_code_and_name_without_removing_old_fields(client, db):
    supplier = add_supplier(
        db,
        kode_supplier=None,
        nama="Legacy",
        kontak="Contact",
        telepon="555",
        email="legacy@example.test",
    )

    response = client.get(
        "/api/integration/barang/meta", headers=INTEGRATION_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["suppliers"] == [
        {
            "id": supplier.id,
            "kode_supplier": "",
            "nama_supplier": "Legacy",
            "nama": "Legacy",
            "kontak": "Contact",
            "telepon": "555",
            "email": "legacy@example.test",
        }
    ]


def load_supplier_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "20260831_add_supplier_kode.py"
    )
    spec = importlib.util.spec_from_file_location("supplier_code_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_supplier_migration_is_idempotent_and_enforces_unique_code_on_sqlite(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE supplier ("
                "id INTEGER PRIMARY KEY, nama VARCHAR(150), kontak VARCHAR(100), "
                "telepon VARCHAR(30), email VARCHAR(100), created_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO supplier (id, nama) VALUES "
                "(1, 'One'), (12, 'Twelve'), (1234, 'Large')"
            )
        )

    migration = load_supplier_migration()
    first = migration.migrate(database_url=database_url)
    second = migration.migrate(database_url=database_url)

    assert first == {"columns_added": 1, "indexes_added": 1, "rows_backfilled": 3}
    assert second == {"columns_added": 0, "indexes_added": 0, "rows_backfilled": 0}
    with engine.begin() as connection:
        assert "kode_supplier" in {
            column["name"] for column in inspect(connection).get_columns("supplier")
        }
        assert connection.execute(
            text("SELECT id, kode_supplier FROM supplier ORDER BY id")
        ).all() == [(1, "SUP-001"), (12, "SUP-012"), (1234, "SUP-1234")]
        with pytest.raises(Exception):
            connection.execute(
                text(
                    "INSERT INTO supplier (id, nama, kode_supplier) "
                    "VALUES (99, 'Duplicate', 'SUP-001')"
                )
            )
    engine.dispose()
