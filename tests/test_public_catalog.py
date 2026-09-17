from app.models.barang import Barang


BASE_URL = "/api/katalog/barang"


def add_barang(
    db, *, sku, nama, merek="Merek", harga_jual=125_000, foto=None, shopee_url=None
):
    barang = Barang(
        sku=sku,
        nama=nama,
        merek=merek,
        harga_modal=90_000,
        harga_beli_kode="INTERNAL",
        harga_jual=harga_jual,
        stok_minimum=7,
        satuan="pcs",
        deskripsi="Public description",
        foto=foto,
        shopee_url=shopee_url,
    )
    db.add(barang)
    db.commit()
    db.refresh(barang)
    return barang


def test_catalog_is_anonymous_and_returns_only_safe_fields(client, db):
    barang = add_barang(
        db,
        sku="BRAKE-001",
        nama="Brake Pad Pro",
        foto="brake.webp",
        shopee_url="https://shopee.co.id/brake-pad-pro",
    )

    response = client.get(BASE_URL)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": barang.id,
                "slug": f"brake-pad-pro-{barang.id}",
                "sku": "BRAKE-001",
                "nama": "Brake Pad Pro",
                "merek": "Merek",
                "harga_jual": 125_000,
                "satuan": "pcs",
                "deskripsi": "Public description",
                "foto_url": "/storage/foto-barang/brake.webp",
                "shopee_url": "https://shopee.co.id/brake-pad-pro",
            }
        ],
        "total": 1,
        "page": 1,
        "limit": 24,
    }


def test_catalog_filter_meta_is_public_normalized_and_safe(client, db):
    add_barang(db, sku="ALPHA", nama="Alpha", merek="  Bosch  ", harga_jual=100_000)
    add_barang(db, sku="BETA", nama="Beta", merek="bosch", harga_jual=200_000)
    add_barang(db, sku="GAMMA", nama="Gamma", merek="NGK", harga_jual=150_000)
    add_barang(db, sku="EMPTY", nama="Empty", merek="   ", harga_jual=75_000)

    response = client.get(f"{BASE_URL}/filter-meta")

    assert response.status_code == 200
    assert response.json() == {
        "merek": ["Bosch", "NGK"],
        "harga_min": 75_000,
        "harga_max": 200_000,
    }
    assert "harga_modal" not in response.text
    assert "harga_beli_kode" not in response.text


def test_catalog_filter_meta_returns_zero_price_bounds_when_catalog_empty(client):
    response = client.get(f"{BASE_URL}/filter-meta")

    assert response.status_code == 200
    assert response.json() == {"merek": [], "harga_min": 0, "harga_max": 0}


def test_catalog_composes_normalized_brand_and_inclusive_price_filters(client, db):
    low = add_barang(db, sku="BOSCH-LOW", nama="Filter Low", merek=" Bosch ", harga_jual=100_000)
    high = add_barang(db, sku="BOSCH-HIGH", nama="Filter High", merek="bosch", harga_jual=200_000)
    add_barang(db, sku="NGK-MID", nama="Filter NGK", merek="NGK", harga_jual=150_000)

    response = client.get(
        BASE_URL,
        params={"q": "filter", "merek": "  bOsCh ", "harga_min": 100_000, "harga_max": 200_000},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert [item["id"] for item in response.json()["data"]] == [high.id, low.id]
    for item in response.json()["data"]:
        assert set(item) == {
            "id", "slug", "sku", "nama", "merek", "harga_jual", "satuan", "deskripsi", "foto_url", "shopee_url"
        }


def test_catalog_rejects_invalid_price_range(client):
    response = client.get(BASE_URL, params={"harga_min": 200_000, "harga_max": 100_000})

    assert response.status_code == 422


def test_catalog_filters_paginates_slugs_and_handles_missing_photo(client, db):
    alpha = add_barang(db, sku="ALPHA", nama="Alpha Filter", foto=None)
    beta = add_barang(db, sku="BETA", nama="Beta Filter")
    add_barang(db, sku="GAMMA", nama="Gamma Brake")

    page = client.get(BASE_URL, params={"q": " filter ", "page": 2, "limit": 1})
    detail = client.get(f"{BASE_URL}/alpha-filter-{alpha.id}")

    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert [item["id"] for item in page.json()["data"]] == [beta.id]
    assert detail.status_code == 200
    assert detail.json()["foto_url"] is None
    assert client.get(f"{BASE_URL}/wrong-{alpha.id}").status_code == 404
    assert client.get(f"{BASE_URL}/missing-999").status_code == 404
    for params in ({"page": 0}, {"limit": 0}, {"limit": 49}):
        assert client.get(BASE_URL, params=params).status_code == 422
