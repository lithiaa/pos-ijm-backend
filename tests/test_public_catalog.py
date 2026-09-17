from app.models.barang import Barang


BASE_URL = "/api/katalog/barang"


def add_barang(db, *, sku, nama, merek="Merek", foto=None, shopee_url=None):
    barang = Barang(
        sku=sku,
        nama=nama,
        merek=merek,
        harga_modal=90_000,
        harga_beli_kode="INTERNAL",
        harga_jual=125_000,
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
