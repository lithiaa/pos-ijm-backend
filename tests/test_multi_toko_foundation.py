"""Tests for multi-toko foundation: Environment model, User extensions, auth resolver, /api/auth/me, and permissions."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import text

from app.models.barang import Barang
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def create_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=60)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def test_environment_model_creation_and_user_relationship(db):
    from app.models.environment import Environment

    env = Environment(
        slug="toko-berkah",
        name="Toko Berkah",
        status="active",
    )
    db.add(env)
    db.commit()
    db.refresh(env)

    assert env.id is not None
    assert env.slug == "toko-berkah"
    assert env.name == "Toko Berkah"
    assert env.status == "active"
    assert env.created_at is not None
    assert env.updated_at is not None

    user = User(
        username="berkah-admin",
        password_hash="hashed",
        nama="Admin Berkah",
        role="admin",
        environment_id=env.id,
        email="admin@berkah.com",
        status="active",
        must_change_password=False,
        permissions=json.dumps(["barang.read", "barang.write"]),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.environment_id == env.id
    assert user.environment is not None
    assert user.environment.slug == "toko-berkah"
    assert user.email == "admin@berkah.com"
    assert user.status == "active"
    assert user.must_change_password is False


def test_permissions_normalizer():
    from app.auth import get_effective_permissions, normalize_permissions

    # Test raw normalizer with varying inputs
    assert normalize_permissions(None) == []
    assert normalize_permissions("") == []
    assert normalize_permissions([]) == []
    assert normalize_permissions(["barang.write", "barang.read", "barang.read"]) == ["barang.read", "barang.write"]
    assert normalize_permissions('["barang.write", "barang.read"]') == ["barang.read", "barang.write"]
    assert normalize_permissions("barang.read, barang.write, barang.read") == ["barang.read", "barang.write"]
    assert normalize_permissions("invalid json {") == []

    # Test effective permissions for admin role (full environment access)
    admin = User(username="adm", role="admin")
    admin_perms = get_effective_permissions(admin)
    assert "barang.read" in admin_perms
    assert "barang.write" in admin_perms
    assert "barang.delete" in admin_perms
    assert "environment.settings" in admin_perms

    # Test effective permissions for platform_owner role
    owner = User(username="owner", role="platform_owner")
    owner_perms = get_effective_permissions(owner)
    assert "barang.read" in owner_perms
    assert "environment.settings" in owner_perms

    # Test effective permissions for staff/karyawan with default
    staff = User(username="stf", role="staff")
    staff_perms = get_effective_permissions(staff)
    assert "barang.read" in staff_perms
    assert "barang.write" in staff_perms
    assert "environment.settings" not in staff_perms

    # Test effective permissions for viewer with default
    viewer = User(username="vw", role="viewer")
    viewer_perms = get_effective_permissions(viewer)
    assert "barang.read" in viewer_perms
    assert "barang.write" not in viewer_perms

    # Test custom explicit permissions for staff
    custom_staff = User(username="cstf", role="staff", permissions=json.dumps(["barang.read"]))
    assert get_effective_permissions(custom_staff) == ["barang.read"]


def test_auth_me_regular_scoped_user(client, db):
    from app.models.environment import Environment

    env = Environment(slug="toko-jaya", name="Toko Jaya", status="active")
    db.add(env)
    db.commit()
    db.refresh(env)

    user = User(
        username="jaya-staff",
        password_hash="hashed",
        nama="Staff Jaya",
        role="staff",
        environment_id=env.id,
        status="active",
        permissions=json.dumps(["barang.read", "stok.read"]),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == user.id
    assert data["username"] == "jaya-staff"
    assert data["nama"] == "Staff Jaya"
    assert data["role"] == "staff"
    assert data["environment"] == {
        "id": env.id,
        "name": "Toko Jaya",
        "status": "active",
    }
    assert data["permissions"] == ["barang.read", "stok.read"]


def test_auth_me_platform_owner_has_null_environment(client, db):
    owner = User(
        username="platform-root",
        password_hash="hashed",
        nama="Platform Superuser",
        role="platform_owner",
        environment_id=None,
        status="active",
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)

    token = create_token(owner.id)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == owner.id
    assert data["username"] == "platform-root"
    assert data["role"] == "platform_owner"
    assert data["environment"] is None
    assert isinstance(data["permissions"], list)
    assert len(data["permissions"]) > 0


def test_auth_rejects_disabled_user(client, db):
    user = User(
        username="disabled-user",
        password_hash="hashed",
        nama="Disabled User",
        role="karyawan",
        status="disabled",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "disabled" in response.json()["detail"].lower()


def test_auth_rejects_suspended_environment(client, db):
    from app.models.environment import Environment

    env = Environment(slug="toko-tutup", name="Toko Tutup", status="suspended")
    db.add(env)
    db.commit()
    db.refresh(env)

    user = User(
        username="user-suspended-env",
        password_hash="hashed",
        nama="User Suspended",
        role="admin",
        environment_id=env.id,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "suspended" in response.json()["detail"].lower()


def test_old_jwt_sub_continues_working(client, db):
    from app.models.environment import Environment

    env = Environment(slug="legacy-env", name="Legacy Env", status="active")
    db.add(env)
    db.commit()
    db.refresh(env)

    user = User(
        username="legacy-user",
        password_hash="hashed",
        nama="Legacy User",
        role="karyawan",
        environment_id=env.id,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Legacy JWT payload with only sub string
    token = jwt.encode({"sub": str(user.id)}, SECRET_KEY, algorithm=ALGORITHM)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["username"] == "legacy-user"


def test_require_permission_dependency_and_helper(client, db):
    from app.auth import require_permission
    from fastapi import Depends
    from main import app

    @app.get("/api/test-perm-barang-write")
    def sample_endpoint(principal=Depends(require_permission("barang.write"))):
        return {"ok": True, "user_id": principal.id}

    user_with_perm = User(
        username="writer-user",
        password_hash="hashed",
        nama="Writer",
        role="staff",
        status="active",
        permissions=json.dumps(["barang.write"]),
    )
    user_without_perm = User(
        username="reader-user",
        password_hash="hashed",
        nama="Reader",
        role="staff",
        status="active",
        permissions=json.dumps(["barang.read"]),
    )
    db.add_all([user_with_perm, user_without_perm])
    db.commit()
    db.refresh(user_with_perm)
    db.refresh(user_without_perm)

    token_ok = create_token(user_with_perm.id)
    token_forbidden = create_token(user_without_perm.id)

    res_ok = client.get("/api/test-perm-barang-write", headers={"Authorization": f"Bearer {token_ok}"})
    assert res_ok.status_code == 200
    assert res_ok.json() == {"ok": True, "user_id": user_with_perm.id}

    res_forbidden = client.get("/api/test-perm-barang-write", headers={"Authorization": f"Bearer {token_forbidden}"})
    assert res_forbidden.status_code == 403
