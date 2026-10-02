import json
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.models.barang import Barang
from app.models.environment import Environment
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def _token(user_id: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _headers(user: User, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user.id)}", **extra}


def _owner(db) -> User:
    user = User(
        username="platform-owner",
        password_hash="unused",
        nama="Platform Owner",
        email="owner@example.test",
        role="platform_owner",
        environment_id=None,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class CapturingInviter:
    def __init__(self):
        self.messages = []

    def send_invitation(self, *, email, name, token, environment_name):
        self.messages.append(
            {
                "email": email,
                "name": name,
                "token": token,
                "environment_name": environment_name,
            }
        )


def test_platform_owner_provisions_toko_and_admin_idempotently(client, db):
    from app.invites import get_inviter
    from app.models.admin import Invitation, ProvisionRequest
    from main import app

    owner = _owner(db)
    inviter = CapturingInviter()
    app.dependency_overrides[get_inviter] = lambda: inviter
    payload = {
        "name": "Toko Baru",
        "slug": "toko-baru",
        "administrator": {
            "name": "Admin Baru",
            "email": "Admin@Example.Test",
            "username": "admin-baru",
        },
    }
    try:
        first = client.post(
            "/api/environments",
            headers=_headers(owner, **{"Idempotency-Key": "provision-001"}),
            json=payload,
        )
        second = client.post(
            "/api/environments",
            headers=_headers(owner, **{"Idempotency-Key": "provision-001"}),
            json=payload,
        )
    finally:
        app.dependency_overrides.pop(get_inviter, None)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert "token" not in json.dumps(first.json()).lower()
    environment_id = first.json()["id"]
    admin = db.query(User).filter(User.username == "admin-baru").one()
    assert admin.environment_id == environment_id
    assert admin.role == "admin"
    assert admin.status == "pending"
    assert admin.email == "admin@example.test"
    assert db.query(Environment).filter(Environment.slug == "toko-baru").count() == 1
    assert db.query(ProvisionRequest).count() == 1
    invitation = db.query(Invitation).one()
    assert invitation.token_hash
    assert invitation.token_hash != inviter.messages[0]["token"]
    assert len(inviter.messages) == 1


def test_scoped_admin_manages_only_staff_and_viewer_with_allowlisted_permissions(client, db):
    environment = Environment(slug="admin-scope", name="Admin Scope", status="active")
    other = Environment(slug="other", name="Other", status="active")
    db.add_all([environment, other])
    db.flush()
    admin = User(
        username="scope-admin",
        password_hash="unused",
        nama="Scope Admin",
        email="scope-admin@example.test",
        role="admin",
        environment_id=environment.id,
        status="active",
    )
    foreign = User(
        username="foreign-user",
        password_hash="unused",
        nama="Foreign",
        email="foreign@example.test",
        role="staff",
        environment_id=other.id,
        status="active",
    )
    db.add_all([admin, foreign])
    db.commit()

    response = client.post(
        "/api/users",
        headers=_headers(admin),
        json={
            "name": "Staff One",
            "email": "staff@example.test",
            "username": "staff-one",
            "role": "staff",
            "permissions": ["barang.read", "stok.write"],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["environment_id"] == environment.id
    assert created["permissions"] == ["barang.read", "stok.write"]
    assert client.get("/api/users", headers=_headers(admin)).json()[0]["id"] == created["id"]
    assert client.get(f"/api/users/{foreign.id}", headers=_headers(admin)).status_code == 404

    for role in ("admin", "platform_owner"):
        denied = client.post(
            "/api/users",
            headers=_headers(admin),
            json={
                "name": "Denied",
                "email": f"{role}@example.test",
                "username": f"denied-{role}",
                "role": role,
                "permissions": [],
            },
        )
        assert denied.status_code == 422
    assert client.post(
        "/api/users",
        headers=_headers(admin),
        json={
            "name": "Bad Permission",
            "email": "bad-perm@example.test",
            "username": "bad-permission",
            "role": "staff",
            "permissions": ["platform.owner"],
        },
    ).status_code == 422


def test_staff_cannot_manage_users_and_admin_cannot_assign_environment(client, db):
    environment = Environment(slug="staff-scope", name="Staff Scope", status="active")
    db.add(environment)
    db.flush()
    staff = User(
        username="staff-manager",
        password_hash="unused",
        nama="Staff",
        email="staff-manager@example.test",
        role="staff",
        permissions=json.dumps(["users.write"]),
        environment_id=environment.id,
        status="active",
    )
    db.add(staff)
    db.commit()
    payload = {
        "name": "New User",
        "email": "new-user@example.test",
        "username": "new-user",
        "role": "viewer",
        "permissions": ["barang.read"],
        "environment_id": 999,
    }
    response = client.post("/api/users", headers=_headers(staff), json=payload)
    assert response.status_code == 422
    payload.pop("environment_id")
    assert client.post("/api/users", headers=_headers(staff), json=payload).status_code == 403


def test_invitation_accepts_once_with_hashed_durable_token_and_password(client, db, monkeypatch):
    from app.invites import get_inviter
    from app.models.admin import Invitation
    from main import app

    environment = Environment(slug="invite", name="Invite", status="active")
    db.add(environment)
    db.flush()
    admin = User(
        username="invite-admin",
        password_hash="unused",
        nama="Invite Admin",
        email="invite-admin@example.test",
        role="admin",
        environment_id=environment.id,
        status="active",
    )
    db.add(admin)
    db.commit()
    inviter = CapturingInviter()
    app.dependency_overrides[get_inviter] = lambda: inviter
    try:
        created = client.post(
            "/api/users",
            headers=_headers(admin),
            json={
                "name": "Invited",
                "email": "invited@example.test",
                "username": "invited",
                "role": "viewer",
                "permissions": ["barang.read"],
            },
        )
    finally:
        app.dependency_overrides.pop(get_inviter, None)
    assert created.status_code == 201
    token = inviter.messages[0]["token"]
    invitation = db.query(Invitation).one()
    assert invitation.token_hash != token
    monkeypatch.setattr("app.routers.auth.hash_password", lambda password: f"hashed:{password}")

    accepted = client.post("/api/auth/invitations/accept", json={"token": token, "password": "valid-pass-123"})
    assert accepted.status_code == 200, accepted.text
    db.expire_all()
    user = db.query(User).filter_by(username="invited").one()
    assert user.password_hash == "hashed:valid-pass-123"
    assert user.status == "active"
    assert user.must_change_password is False
    assert client.post("/api/auth/invitations/accept", json={"token": token, "password": "other-pass-123"}).status_code == 409
    assert "token" not in accepted.text.lower()


def test_email_is_globally_unique_across_toko(client, db):
    first = Environment(slug="email-one", name="One", status="active")
    second = Environment(slug="email-two", name="Two", status="active")
    db.add_all([first, second])
    db.flush()
    admins = [
        User(username="email-admin-one", password_hash="x", nama="One", email="one-admin@example.test", role="admin", environment_id=first.id, status="active"),
        User(username="email-admin-two", password_hash="x", nama="Two", email="two-admin@example.test", role="admin", environment_id=second.id, status="active"),
    ]
    db.add_all(admins)
    db.flush()
    db.add(User(username="existing-email", password_hash="x", nama="Existing", email="unique@example.test", role="viewer", environment_id=first.id, status="active"))
    db.commit()
    response = client.post(
        "/api/users",
        headers=_headers(admins[1]),
        json={"name": "Duplicate", "email": "UNIQUE@example.test", "username": "duplicate-email", "role": "viewer", "permissions": []},
    )
    assert response.status_code == 409


def test_support_grant_is_reason_time_target_bound_audited_and_revocable(client, db):
    from app.audit import drain_audit_logs
    from app.models.admin import SupportGrant
    from app.models.audit_log import AuditLog

    owner = _owner(db)
    target = Environment(slug="support-target", name="Support Target", status="active")
    other = Environment(slug="support-other", name="Support Other", status="active")
    db.add_all([target, other])
    db.commit()
    db.refresh(target)
    db.refresh(other)

    bad = client.post(
        f"/api/environments/{target.id}/support-access",
        headers=_headers(owner),
        json={"reason": "x", "duration_minutes": 30},
    )
    assert bad.status_code == 422
    created = client.post(
        f"/api/environments/{target.id}/support-access",
        headers=_headers(owner),
        json={"reason": "Investigate inventory mismatch", "duration_minutes": 30},
    )
    assert created.status_code == 201, created.text
    grant_id = created.json()["id"]
    grant = db.get(SupportGrant, grant_id)
    assert grant.environment_id == target.id
    assert grant.expires_at > grant.starts_at

    target_access = client.get(
        f"/api/environments/{target.id}",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    )
    assert target_access.status_code == 200
    target_item = Barang(environment_id=target.id, sku="SUPPORT-TARGET", nama="Target Item")
    other_item = Barang(environment_id=other.id, sku="SUPPORT-OTHER", nama="Other Item")
    db.add_all([target_item, other_item]); db.commit(); db.refresh(target_item); db.refresh(other_item)
    assert client.get(
        f"/api/barang/{target_item.id}",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    ).status_code == 200
    assert client.get(
        f"/api/barang/{other_item.id}",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    ).status_code == 404
    assert client.get(
        f"/api/barang/{target_item.id}/photos",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    ).status_code == 200
    assert client.get(
        f"/api/environments/{other.id}",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    ).status_code == 403
    client.portal.call(drain_audit_logs)
    db.expire_all()
    log = db.query(AuditLog).filter(AuditLog.path == f"/api/environments/{target.id}").order_by(AuditLog.id.desc()).first()
    assert log is not None
    assert log.environment_id == target.id
    assert "support_grant_id" in log.summary
    assert "Investigate inventory mismatch" not in log.summary

    revoked = client.post(f"/api/environments/{target.id}/support-access/{grant_id}/revoke", headers=_headers(owner))
    assert revoked.status_code == 200
    assert client.get(
        f"/api/environments/{target.id}",
        headers=_headers(owner, **{"X-Support-Grant": str(grant_id)}),
    ).status_code == 403


def test_owner_suspends_toko_and_admin_updates_only_own_settings(client, db):
    owner = _owner(db)
    first = Environment(slug="settings-one", name="Settings One", status="active")
    second = Environment(slug="settings-two", name="Settings Two", status="active")
    db.add_all([first, second]); db.flush()
    admin = User(
        username="settings-admin", password_hash="x", nama="Settings Admin",
        email="settings-admin@example.test", role="admin", environment_id=first.id, status="active",
    )
    db.add(admin); db.commit(); db.refresh(first); db.refresh(second); db.refresh(admin)

    updated = client.patch(
        f"/api/environments/{first.id}", headers=_headers(admin),
        json={"name": "Renamed Store", "address": "New Address", "timezone": "Asia/Makassar", "currency": "IDR"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Renamed Store"
    assert client.patch(
        f"/api/environments/{second.id}", headers=_headers(admin), json={"name": "Forbidden"},
    ).status_code == 404
    suspended = client.post(f"/api/environments/{first.id}/suspend", headers=_headers(owner))
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert client.post(f"/api/environments/{second.id}/suspend", headers=_headers(admin)).status_code in {401, 403}


def test_provisioning_requires_global_platform_owner_and_matching_idempotency_payload(client, db):
    owner = _owner(db)
    environment = Environment(slug="local", name="Local", status="active")
    db.add(environment)
    db.flush()
    admin = User(
        username="local-admin",
        password_hash="unused",
        nama="Local Admin",
        email="local@example.test",
        role="admin",
        environment_id=environment.id,
        status="active",
    )
    db.add(admin)
    db.commit()
    payload = {
        "name": "One",
        "slug": "one",
        "administrator": {"name": "One Admin", "email": "one@example.test", "username": "one-admin"},
    }

    assert client.post(
        "/api/environments",
        headers=_headers(admin, **{"Idempotency-Key": "forbidden"}),
        json=payload,
    ).status_code == 403
    assert client.post(
        "/api/environments",
        headers=_headers(owner, **{"Idempotency-Key": "same-key"}),
        json=payload,
    ).status_code == 201
    payload["name"] = "Different"
    assert client.post(
        "/api/environments",
        headers=_headers(owner, **{"Idempotency-Key": "same-key"}),
        json=payload,
    ).status_code == 409
