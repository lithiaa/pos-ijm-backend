from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text

from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.models.user import User
from config import ALGORITHM, SECRET_KEY
from tests.conftest import TEST_INTEGRATION_KEY

BARANG_URL = "/api/integration/barang"
SUPPLIER_URL = "/api/integration/suppliers"
KEY_HEADERS = {"X-Integration-Key": TEST_INTEGRATION_KEY}


def login_headers(client, db, monkeypatch, *, username, role="karyawan"):
    user = User(
        username=username,
        password_hash="unused",
        nama="Integration User",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    monkeypatch.setattr("app.routers.auth.verify_password", lambda *_: True)
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200
    return user, {"Authorization": f"Bearer {response.json()['access_token']}"}


def drain_audits(client):
    from app.audit import drain_audit_logs

    client.portal.call(drain_audit_logs)


@pytest.mark.parametrize(
    ("url", "role"),
    [(BARANG_URL, "admin"), (SUPPLIER_URL, "karyawan")],
)
def test_integration_reads_accept_login_jwt(client, db, monkeypatch, url, role):
    _, headers = login_headers(
        client,
        db,
        monkeypatch,
        username=f"{role}-{url.rsplit('/', 1)[-1]}",
        role=role,
    )

    response = client.get(url, headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_integration_key_remains_supported(client):
    assert client.get(BARANG_URL, headers=KEY_HEADERS).status_code == 200
    assert client.get(SUPPLIER_URL, headers=KEY_HEADERS).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Integration-Key": "wrong"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer malformed"},
        {
            "Authorization": "Bearer malformed",
            "X-Integration-Key": "wrong",
        },
    ],
)
def test_integration_invalid_credentials_return_generic_401(client, headers):
    response = client.get(BARANG_URL, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_expired_bearer_returns_generic_401(client):
    token = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    response = client.get(
        BARANG_URL,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@pytest.mark.parametrize("bearer", ["malformed", "expired"])
def test_invalid_bearer_falls_back_to_valid_integration_key(client, bearer):
    token = "malformed"
    if bearer == "expired":
        token = jwt.encode(
            {
                "sub": "1",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            SECRET_KEY,
            algorithm=ALGORITHM,
        )

    response = client.get(
        BARANG_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Integration-Key": TEST_INTEGRATION_KEY,
        },
    )

    assert response.status_code == 200


def test_integration_rejects_login_jwt_for_other_role(client, db, monkeypatch):
    _, headers = login_headers(
        client,
        db,
        monkeypatch,
        username="integration-owner",
        role="owner",
    )

    response = client.get(BARANG_URL, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_integration_jwt_populates_audit_actor(client, db, monkeypatch):
    user, headers = login_headers(
        client,
        db,
        monkeypatch,
        username="integration-auditor",
        role="admin",
    )
    barang = Barang(sku="JWT-AUDIT", nama="Before", harga_jual=100)
    db.add(barang)
    db.flush()
    db.add(StokSaatIni(barang_id=barang.id, jumlah=1))
    db.commit()

    response = client.put(
        f"{BARANG_URL}/{barang.id}",
        headers=headers,
        json={"nama": "After"},
    )

    assert response.status_code == 200
    drain_audits(client)
    db.expire_all()
    row = db.execute(
        text(
            "SELECT user_id, username FROM audit_logs "
            "WHERE path = :path ORDER BY id DESC LIMIT 1"
        ),
        {"path": f"{BARANG_URL}/{barang.id}"},
    ).mappings().one()
    assert row["user_id"] == user.id
    assert row["username"] == user.username
