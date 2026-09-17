import pytest

from app.auth import create_access_token
from app.models.user import User


@pytest.fixture
def auth(client, db):
    user = User(username="shopee-qa", password_hash="unused", nama="QA", role="admin")
    db.add(user)
    db.commit()
    client.headers["Authorization"] = f"Bearer {create_access_token({'sub': str(user.id)})}"
    return client


def test_barang_create_update_and_output_accept_only_shopee_https_urls(auth):
    created = auth.post(
        "/api/barang",
        json={
            "sku": "SHOPEE-001",
            "nama": "Shopee Item",
            "stok_awal": 0,
            "shopee_url": " https://shop.shopee.co.id/product/1 ",
        },
    )

    assert created.status_code == 200
    assert created.json()["shopee_url"] == "https://shop.shopee.co.id/product/1"
    cleared = auth.put(f"/api/barang/{created.json()['id']}", json={"shopee_url": "  "})
    assert cleared.status_code == 200
    assert cleared.json()["shopee_url"] is None

    for value in (
        "http://shopee.co.id/item",
        "https://notshopee.co.id/item",
        "https://shopee.co.id@evil.example/item",
        "https://user:pass@shopee.co.id/item",
    ):
        assert auth.put(f"/api/barang/{created.json()['id']}", json={"shopee_url": value}).status_code == 422
