from app.database import SessionLocal
from app.models.barang import Barang
from app.models.kategori import Kategori
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import IntegrationStockOperation, StokSaatIni, TransaksiStok
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import TEST_INTEGRATION_KEY


BASE_URL = "/api/integration/barang"
AUTH_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}
IMAGE_BYTES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP",
}


def add_refs(db):
    kategori = Kategori(nama="Filter", deskripsi="Mesin")
    supplier = Supplier(
        nama="Maju Jaya",
        kontak="Budi",
        telepon="021",
        email="sales@example.test",
    )
    db.add_all([kategori, supplier])
    db.commit()
    return kategori, supplier


def add_barang(
    db,
    *,
    sku="PART-001",
    nama="Brake Pad",
    merek="Akebono",
    kategori_id=None,
    supplier_id=None,
    stok=7,
    stok_minimum=5,
    satuan="box",
    foto=None,
):
    barang = Barang(
        sku=sku,
        nama=nama,
        merek=merek,
        kategori_id=kategori_id,
        supplier_id=supplier_id,
        harga_modal=125_000,
        harga_beli_kode="BUY-X",
        harga_jual=175_000,
        stok_minimum=stok_minimum,
        satuan=satuan,
        deskripsi="Ceramic",
        foto=foto,
    )
    db.add(barang)
    db.flush()
    if stok is not None:
        db.add(StokSaatIni(barang_id=barang.id, jumlah=stok))
    db.commit()
    db.refresh(barang)
    return barang


def test_list_requires_integration_key(client):
    assert client.get(BASE_URL).status_code == 401
    assert client.get(BASE_URL, headers={"X-Integration-Key": "wrong"}).status_code == 401


def test_list_serializes_full_items_and_paginates_with_total(client, db):
    kategori, supplier = add_refs(db)
    beta = add_barang(
        db,
        sku="BETA",
        nama="beta",
        kategori_id=kategori.id,
        supplier_id=supplier.id,
        foto="part.webp",
    )
    alpha = add_barang(db, sku="ALPHA", nama="Alpha", stok=0)
    add_barang(db, sku="GAMMA", nama="Gamma")

    response = client.get(BASE_URL, headers=AUTH_HEADERS, params={"page": 1, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 2
    assert [item["id"] for item in body["data"]] == [alpha.id, beta.id]
    assert body["data"][1] == {
        "id": beta.id,
        "sku": "BETA",
        "nama": "beta",
        "harga_beli": 125_000,
        "harga_jual": 175_000,
        "harga_beli_kode": "BUY-X",
        "stok": 7,
        "satuan": "box",
        "merek": "Akebono",
        "foto": "part.webp",
        "foto_url": "/storage/foto-barang/part.webp",
        "kategori": {"id": kategori.id, "nama": "Filter", "deskripsi": "Mesin"},
        "supplier": {
            "id": supplier.id,
            "nama": "Maju Jaya",
            "kontak": "Budi",
            "telepon": "021",
            "email": "sales@example.test",
        },
        "stok_minimum": 5,
        "stok_status": "aman",
        "deskripsi": "Ceramic",
        "created_at": body["data"][1]["created_at"],
        "updated_at": body["data"][1]["updated_at"],
    }
    assert body["data"][1]["created_at"]
    assert body["data"][1]["updated_at"]


def test_list_filters_query_refs_and_stock_status_with_missing_stock(client, db):
    kategori, supplier = add_refs(db)
    safe = add_barang(
        db,
        sku="SAFE-100%",
        nama="Oil_Filter",
        merek="Bosch\\Pro",
        kategori_id=kategori.id,
        supplier_id=supplier.id,
        stok=10,
    )
    low = add_barang(db, sku="LOW", nama="low", stok=2)
    empty = add_barang(db, sku="EMPTY", nama="Empty", stok=0)
    missing = add_barang(db, sku="MISSING", nama="Missing", stok=None)

    literal = client.get(BASE_URL, headers=AUTH_HEADERS, params={"q": "100%"})
    refs = client.get(
        BASE_URL,
        headers=AUTH_HEADERS,
        params={"kategori_id": kategori.id, "supplier_id": supplier.id},
    )
    low_result = client.get(BASE_URL, headers=AUTH_HEADERS, params={"stok_status": "menipis"})
    empty_result = client.get(BASE_URL, headers=AUTH_HEADERS, params={"stok_status": "habis"})
    slash = client.get(BASE_URL, headers=AUTH_HEADERS, params={"q": "bosch\\pro"})

    assert [item["id"] for item in literal.json()["data"]] == [safe.id]
    assert [item["id"] for item in refs.json()["data"]] == [safe.id]
    assert [item["id"] for item in low_result.json()["data"]] == [low.id]
    assert {item["id"] for item in empty_result.json()["data"]} == {empty.id, missing.id}
    assert next(item for item in empty_result.json()["data"] if item["id"] == missing.id)["stok"] == 0
    assert [item["id"] for item in slash.json()["data"]] == [safe.id]


def test_list_is_case_insensitive_deterministic_and_validates_params(client, db):
    first = add_barang(db, sku="ONE", nama="same", merek="Needle")
    second = add_barang(db, sku="TWO", nama="Same", merek="Needle")

    response = client.get(BASE_URL, headers=AUTH_HEADERS, params={"q": "  nEeDlE  "})

    assert [item["id"] for item in response.json()["data"]] == [first.id, second.id]
    for params in (
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"stok_status": "unknown"},
        {"kategori_id": "x"},
    ):
        assert client.get(BASE_URL, headers=AUTH_HEADERS, params=params).status_code == 422


def test_meta_is_authenticated_sorted_distinct_and_has_pcs_fallback(client, db):
    db.add_all(
        [
            Kategori(nama="zeta", deskripsi=None),
            Kategori(nama="Alpha", deskripsi="A"),
            Supplier(nama="zulu"),
            Supplier(nama="Beta"),
        ]
    )
    db.commit()
    add_barang(db, sku="BOX", nama="Box", satuan=" box ")
    add_barang(db, sku="BLANK", nama="Blank", satuan="   ")
    add_barang(db, sku="BOX2", nama="Box2", satuan="box")

    assert client.get(f"{BASE_URL}/meta").status_code == 401
    response = client.get(f"{BASE_URL}/meta", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert [item["nama"] for item in body["categories"]] == ["Alpha", "zeta"]
    assert [item["nama"] for item in body["suppliers"]] == ["Beta", "zulu"]
    assert body["satuan"] == ["box", "pcs"]
    assert set(body["categories"][0]) == {"id", "nama", "deskripsi"}
    assert set(body["suppliers"][0]) == {"id", "nama", "kontak", "telepon", "email"}


def test_detail_returns_full_item_and_missing_404(client, db):
    barang = add_barang(db)

    assert client.get(f"{BASE_URL}/{barang.id}").status_code == 401
    response = client.get(f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == barang.id
    assert response.json()["stok_status"] == "aman"
    assert client.get(f"{BASE_URL}/9999", headers=AUTH_HEADERS).status_code == 404
    assert client.get(f"{BASE_URL}/0", headers=AUTH_HEADERS).status_code == 422
    assert client.get(f"{BASE_URL}/-1", headers=AUTH_HEADERS).status_code == 422


def test_detail_allows_legacy_null_timestamps(client, db):
    barang = add_barang(db)
    barang.created_at = None
    barang.updated_at = None
    db.commit()

    response = client.get(f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["created_at"] is None
    assert response.json()["updated_at"] is None


def test_read_endpoints_serialize_legacy_null_sku_as_empty_string(client, db):
    barang = add_barang(db, sku=None, nama="Legacy Null SKU")

    responses = [
        client.get(BASE_URL, headers=AUTH_HEADERS),
        client.get(f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS),
        client.get(f"{BASE_URL}/search", headers=AUTH_HEADERS, params={"q": "Legacy"}),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert responses[0].json()["data"][0]["sku"] == ""
    assert responses[1].json()["sku"] == ""
    assert responses[2].json()["data"][0]["sku"] == ""
    assert client.get(f"{BASE_URL}/meta", headers=AUTH_HEADERS).status_code == 200


def create_payload(**overrides):
    payload = {
        "sku": "NEW-1",
        "nama": "New Part",
        "harga_beli": 10,
        "harga_beli_kode": "CODE",
        "harga_jual": 20,
        "jumlah_barang_masuk": 0,
        "operation_id": str(uuid4()),
    }
    payload.update(overrides)
    return payload


def test_post_accepts_metadata_validates_fks_and_keeps_old_payload(client, db):
    kategori, supplier = add_refs(db)
    response = client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(
            sku=" meta-1 ",
            nama=" Metadata ",
            merek="  Bosch  ",
            kategori_id=kategori.id,
            supplier_id=supplier.id,
            stok_minimum=9,
            deskripsi="  Detail  ",
        ),
    )

    assert response.status_code == 201
    assert response.json()["merek"] == "Bosch"
    assert response.json()["kategori"]["id"] == kategori.id
    assert response.json()["supplier"]["id"] == supplier.id
    assert response.json()["stok_minimum"] == 9
    assert response.json()["deskripsi"] == "Detail"
    assert client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(sku="OLD-1"),
    ).status_code == 201
    assert client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(sku="BAD-CAT", kategori_id=9999),
    ).status_code == 422
    assert client.post(
        BASE_URL,
        headers=AUTH_HEADERS,
        json=create_payload(sku="BAD-SUP", supplier_id=9999),
    ).status_code == 422


def test_put_partial_preserves_omitted_normalizes_sku_and_validates_fks(client, db):
    kategori, supplier = add_refs(db)
    barang = add_barang(db, sku="UPDATE-1", stok=4)

    response = client.put(
        f"{BASE_URL}/{barang.id}",
        headers=AUTH_HEADERS,
        json={
            "sku": " updated-1 ",
            "merek": "   ",
            "kategori_id": kategori.id,
            "supplier_id": supplier.id,
            "deskripsi": "   ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sku"] == "UPDATED-1"
    assert body["nama"] == "Brake Pad"
    assert body["merek"] is None
    assert body["deskripsi"] is None
    assert body["stok"] == 4
    assert client.put(
        f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS, json={"kategori_id": 9999}
    ).status_code == 422
    assert client.put(
        f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS, json={"supplier_id": 9999}
    ).status_code == 422
    assert client.put(f"{BASE_URL}/9999", headers=AUTH_HEADERS, json={}).status_code == 404


def test_put_allows_nullable_relationships_and_text_without_resetting_numbers(client, db):
    kategori, supplier = add_refs(db)
    barang = add_barang(
        db,
        sku="CLEAR-1",
        kategori_id=kategori.id,
        supplier_id=supplier.id,
    )

    response = client.put(
        f"{BASE_URL}/{barang.id}",
        headers=AUTH_HEADERS,
        json={
            "kategori_id": None,
            "supplier_id": None,
            "merek": None,
            "deskripsi": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kategori"] is None
    assert body["supplier"] is None
    assert body["merek"] is None
    assert body["deskripsi"] is None
    assert body["harga_beli"] == 125_000
    assert body["harga_jual"] == 175_000
    assert body["stok_minimum"] == 5


def test_put_rejects_duplicate_sku_invalid_values_null_buy_code_and_extra(client, db):
    first = add_barang(db, sku="FIRST")
    second = add_barang(db, sku="SECOND")

    duplicate = client.put(
        f"{BASE_URL}/{second.id}", headers=AUTH_HEADERS, json={"sku": " first "}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "SKU already exists"
    for payload in (
        {"nama": "   "},
        {"satuan": "   "},
        {"sku": None},
        {"harga_beli": -1},
        {"harga_beli": "1"},
        {"harga_beli": None},
        {"harga_jual": -1},
        {"harga_jual": None},
        {"stok_minimum": -1},
        {"stok_minimum": None},
        {"harga_beli_kode": None},
        {"harga_beli_kode": "   "},
        {"stok": 10},
    ):
        assert client.put(
            f"{BASE_URL}/{first.id}", headers=AUTH_HEADERS, json=payload
        ).status_code == 422


def test_delete_requires_auth_cleans_dependencies_file_and_preserves_unrelated(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    target = add_barang(db, sku="DELETE", foto="target.jpg")
    other = add_barang(db, sku="KEEP")
    (tmp_path / "target.jpg").write_bytes(b"photo")
    db.add_all(
        [
            TransaksiStok(barang_id=target.id, jenis="masuk", jumlah=1),
            TransaksiStok(barang_id=other.id, jenis="masuk", jumlah=2),
            IntegrationStockOperation(operation_id=str(uuid4()), barang_id=target.id),
            IntegrationStockOperation(operation_id=str(uuid4()), barang_id=other.id),
        ]
    )
    db.commit()

    target_id = target.id
    other_id = other.id
    assert client.delete(f"{BASE_URL}/{target_id}").status_code == 401
    response = client.delete(f"{BASE_URL}/{target_id}", headers=AUTH_HEADERS)

    assert response.status_code == 204
    assert response.content == b""
    db.expire_all()
    assert db.get(Barang, target_id) is None
    assert db.query(StokSaatIni).filter_by(barang_id=target_id).count() == 0
    assert db.query(TransaksiStok).filter_by(barang_id=target_id).count() == 0
    assert db.query(IntegrationStockOperation).filter_by(barang_id=target_id).count() == 0
    assert db.get(Barang, other_id) is not None
    assert db.query(TransaksiStok).filter_by(barang_id=other_id).count() == 1
    assert db.query(IntegrationStockOperation).filter_by(barang_id=other_id).count() == 1
    assert not (tmp_path / "target.jpg").exists()
    assert client.delete(f"{BASE_URL}/{target_id}", headers=AUTH_HEADERS).status_code == 404


def test_delete_rejects_print_history_without_partial_cleanup(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku="PRINTED", foto="printed.jpg")
    (tmp_path / "printed.jpg").write_bytes(b"photo")
    transaction = TransaksiStok(barang_id=barang.id, jenis="masuk", jumlah=1)
    operation = IntegrationStockOperation(
        operation_id=str(uuid4()), barang_id=barang.id
    )
    print_job = PrintJob(barang_id=barang.id, qty=1, status="printed")
    db.add_all([transaction, operation, print_job])
    db.commit()

    barang_id = barang.id
    transaction_id = transaction.id
    operation_id = operation.operation_id
    print_job_id = print_job.id
    response = client.delete(f"{BASE_URL}/{barang_id}", headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert response.json()["detail"] == "Barang has print jobs and cannot be deleted"
    db.expire_all()
    assert db.get(Barang, barang_id) is not None
    assert db.get(PrintJob, print_job_id) is not None
    assert db.query(StokSaatIni).filter_by(barang_id=barang_id).count() == 1
    assert db.get(TransaksiStok, transaction_id) is not None
    assert db.get(IntegrationStockOperation, operation_id) is not None
    assert (tmp_path / "printed.jpg").read_bytes() == b"photo"


def test_delete_concurrent_print_job_conflict_rolls_back_and_keeps_photo(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku="PRINT-RACE", foto="race.jpg")
    (tmp_path / "race.jpg").write_bytes(b"photo")
    transaction = TransaksiStok(barang_id=barang.id, jenis="masuk", jumlah=1)
    operation = IntegrationStockOperation(
        operation_id=str(uuid4()), barang_id=barang.id
    )
    db.add_all([transaction, operation])
    db.commit()

    barang_id = barang.id
    transaction_id = transaction.id
    operation_id = operation.operation_id
    original_commit = type(db).commit

    def add_print_job_then_fail(_session):
        _session.rollback()
        monkeypatch.setattr(type(db), "commit", original_commit)
        concurrent_db = SessionLocal()
        try:
            concurrent_db.add(PrintJob(barang_id=barang_id, qty=1, status="pending"))
            concurrent_db.commit()
        finally:
            concurrent_db.close()
        raise IntegrityError(
            "DELETE FROM barang",
            {},
            Exception("FOREIGN KEY constraint failed: print_jobs.barang_id"),
        )

    monkeypatch.setattr(type(db), "commit", add_print_job_then_fail)
    response = client.delete(f"{BASE_URL}/{barang_id}", headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert response.json()["detail"] == "Barang has print jobs and cannot be deleted"
    db.expire_all()
    assert db.get(Barang, barang_id) is not None
    assert db.query(PrintJob).filter_by(barang_id=barang_id).count() == 1
    assert db.query(StokSaatIni).filter_by(barang_id=barang_id).count() == 1
    assert db.get(TransaksiStok, transaction_id) is not None
    assert db.get(IntegrationStockOperation, operation_id) is not None
    assert (tmp_path / "race.jpg").read_bytes() == b"photo"


def test_delete_uses_basename_for_photo_cleanup(client, db, tmp_path, monkeypatch):
    from app.routers import integration_barang

    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(storage))
    barang = add_barang(db, sku="SAFE-DELETE", foto="../outside.jpg")

    assert client.delete(f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS).status_code == 204
    assert outside.exists()


def test_delete_rolls_back_when_commit_fails(client, db, monkeypatch):
    barang = add_barang(db, sku="ROLLBACK")

    def fail_commit(_session):
        raise RuntimeError("forced delete failure")

    monkeypatch.setattr(type(db), "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced delete failure"):
        client.delete(f"{BASE_URL}/{barang.id}", headers=AUTH_HEADERS)

    assert db.get(Barang, barang.id) is not None
    assert db.query(StokSaatIni).filter_by(barang_id=barang.id).count() == 1


def test_upload_requires_auth_validates_missing_type_size_and_empty(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku="UPLOAD")
    url = f"{BASE_URL}/{barang.id}/foto"

    assert client.post(url, files={"file": ("x.jpg", b"x", "image/jpeg")}).status_code == 401
    assert client.post(
        f"{BASE_URL}/9999/foto",
        headers=AUTH_HEADERS,
        files={"file": ("x.jpg", b"x", "image/jpeg")},
    ).status_code == 404
    assert client.post(
        url,
        headers=AUTH_HEADERS,
        files={"file": ("x.gif", b"GIF89a", "image/gif")},
    ).status_code == 422
    assert client.post(
        url,
        headers=AUTH_HEADERS,
        files={"file": ("x.jpg", b"", "image/jpeg")},
    ).status_code == 422
    assert client.post(
        url,
        headers=AUTH_HEADERS,
        files={"file": ("x.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")},
    ).status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_upload_rejects_fake_jpeg_without_file_or_db_change(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku="FAKE-JPEG", foto="existing.jpg")
    (tmp_path / "existing.jpg").write_bytes(b"existing")

    response = client.post(
        f"{BASE_URL}/{barang.id}/foto",
        headers=AUTH_HEADERS,
        files={"file": ("fake.jpg", b"not actually an image", "image/jpeg")},
    )

    assert response.status_code == 422
    db.expire_all()
    assert db.get(Barang, barang.id).foto == "existing.jpg"
    assert {path.name for path in tmp_path.iterdir()} == {"existing.jpg"}
    assert (tmp_path / "existing.jpg").read_bytes() == b"existing"


@pytest.mark.parametrize(
    ("content_type", "expected_ext"),
    [("image/jpeg", ".jpg"), ("image/png", ".png"), ("image/webp", ".webp")],
)
def test_upload_streams_uses_safe_server_extension_and_returns_full_item(
    client, db, tmp_path, monkeypatch, content_type, expected_ext
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku=f"UPLOAD-{expected_ext}")

    response = client.post(
        f"{BASE_URL}/{barang.id}/foto",
        headers=AUTH_HEADERS,
        files={"file": ("../../evil.exe", IMAGE_BYTES[content_type], content_type)},
    )

    assert response.status_code == 200
    filename = response.json()["foto"]
    assert filename.endswith(expected_ext)
    assert "/" not in filename and "\\" not in filename
    assert response.json()["foto_url"] == f"/storage/foto-barang/{filename}"
    assert (tmp_path / filename).read_bytes() == IMAGE_BYTES[content_type]


def test_upload_replaces_old_photo_and_removes_new_file_on_db_failure(
    client, db, tmp_path, monkeypatch
):
    from app.routers import integration_barang

    monkeypatch.setattr(integration_barang, "STORAGE_DIR", str(tmp_path))
    barang = add_barang(db, sku="REPLACE", foto="old.jpg")
    (tmp_path / "old.jpg").write_bytes(b"old")

    response = client.post(
        f"{BASE_URL}/{barang.id}/foto",
        headers=AUTH_HEADERS,
        files={"file": ("new.png", IMAGE_BYTES["image/png"], "image/png")},
    )

    assert response.status_code == 200
    assert not (tmp_path / "old.jpg").exists()
    assert (tmp_path / response.json()["foto"]).exists()

    original = response.json()["foto"]

    def fail_commit(_session):
        raise RuntimeError("forced upload failure")

    monkeypatch.setattr(type(db), "commit", fail_commit)
    with pytest.raises(RuntimeError, match="forced upload failure"):
        client.post(
            f"{BASE_URL}/{barang.id}/foto",
            headers=AUTH_HEADERS,
            files={"file": ("fail.webp", IMAGE_BYTES["image/webp"], "image/webp")},
        )
    assert {path.name for path in tmp_path.iterdir()} == {original}


def test_openapi_lists_old_and_new_integration_methods(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert {"get", "post"}.issubset(paths[BASE_URL])
    assert "get" in paths[f"{BASE_URL}/search"]
    assert "get" in paths[f"{BASE_URL}/meta"]
    assert {"get", "put"}.issubset(paths[f"{BASE_URL}/by-sku/{{sku}}"])
    assert "post" in paths[f"{BASE_URL}/by-sku/{{sku}}/stok-masuk"]
    assert {"get", "put", "delete"}.issubset(paths[f"{BASE_URL}/{{barang_id}}"])
    assert "post" in paths[f"{BASE_URL}/{{barang_id}}/foto"]
    assert {"get", "post"}.issubset(paths["/api/barang"])
    assert {"get", "put", "delete"}.issubset(paths["/api/barang/{barang_id}"])
