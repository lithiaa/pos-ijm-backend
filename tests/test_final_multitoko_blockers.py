import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jose import jwt

from app.models.environment import Environment
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def _headers(user):
    token = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _user(db, environment, name, role, permissions=None):
    user = User(
        environment_id=environment.id,
        username=name,
        password_hash="unused",
        nama=name,
        role=role,
        permissions=permissions,
        status="active",
    )
    db.add(user)
    db.commit()
    return user


def test_tenant_permission_matrix_blocks_viewer_mutations_and_allows_granted_staff_and_admin(client, db):
    environment = Environment(slug="permissions", name="Permissions", status="active")
    db.add(environment)
    db.commit()
    viewer = _user(db, environment, "viewer-permissions", "viewer")
    staff = _user(db, environment, "staff-permissions", "staff", '["supplier.read"]')
    admin = _user(db, environment, "admin-permissions", "admin")

    payload = {"nama": "Supplier"}
    assert client.get("/api/supplier", headers=_headers(viewer)).status_code == 200
    assert client.post("/api/supplier", json=payload, headers=_headers(viewer)).status_code == 403
    assert client.post("/api/supplier", json=payload, headers=_headers(staff)).status_code == 403
    assert client.post("/api/supplier", json=payload, headers=_headers(admin)).status_code == 200


def test_tenant_read_routes_require_declared_read_permission(client, db):
    environment = Environment(slug="read-permissions", name="Read", status="active")
    db.add(environment)
    db.commit()
    staff = _user(db, environment, "staff-no-read", "staff", '[]')

    assert client.get("/api/barang", headers=_headers(staff)).status_code == 403
    assert client.get("/api/dashboard", headers=_headers(staff)).status_code == 403
    assert client.get("/api/laporan/laba", headers=_headers(staff)).status_code == 403


def load_photo_cutover():
    path = Path(__file__).resolve().parents[1] / "migrations" / "20261003_photo_storage_cutover.py"
    spec = importlib.util.spec_from_file_location("photo_storage_cutover", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_photo_cutover_copies_shared_legacy_references_per_environment_and_is_idempotent(tmp_path, db):
    from app.models.barang import Barang, BarangFoto

    migration = load_photo_cutover()
    first = Environment(slug="photo-one", name="One", status="active")
    second = Environment(slug="photo-two", name="Two", status="active")
    db.add_all((first, second)); db.flush()
    first_barang = Barang(environment_id=first.id, sku="P1", nama="One", foto="shared.jpg")
    second_barang = Barang(environment_id=second.id, sku="P2", nama="Two")
    db.add_all((first_barang, second_barang)); db.flush()
    db.add(BarangFoto(environment_id=second.id, barang_id=second_barang.id, filename="shared.jpg", urutan=0))
    db.commit()
    legacy = tmp_path / "shared.jpg"
    legacy.write_bytes(b"shared")

    report = migration.cutover_photo_storage(db, tmp_path, dry_run=False)

    assert report["missing"] == []
    assert (tmp_path / str(first.id) / "shared.jpg").read_bytes() == b"shared"
    assert (tmp_path / str(second.id) / "shared.jpg").read_bytes() == b"shared"
    assert legacy.exists()
    assert migration.cutover_photo_storage(db, tmp_path, dry_run=False)["copied"] == []


def test_photo_cutover_reports_missing_and_rejects_traversal(tmp_path, db):
    from app.models.barang import Barang

    migration = load_photo_cutover()
    environment = Environment(slug="photo-missing", name="Missing", status="active")
    db.add(environment); db.flush()
    db.add(Barang(environment_id=environment.id, sku="PM", nama="Missing", foto="../unsafe.jpg"))
    db.commit()

    report = migration.cutover_photo_storage(db, tmp_path, dry_run=True)

    assert report["invalid"] == [{"environment_id": environment.id, "filename": "../unsafe.jpg"}]


def test_production_invite_guard_refuses_before_user_persistence(client, db, monkeypatch):
    from app.invites import NoOpInviter, get_inviter
    from main import app

    environment = Environment(slug="invite-guard", name="Invite Guard", status="active")
    db.add(environment); db.commit()
    admin = _user(db, environment, "invite-guard-admin", "admin")
    monkeypatch.setattr("app.invites.APP_ENV", "production")
    app.dependency_overrides[get_inviter] = lambda: NoOpInviter()
    try:
        response = client.post("/api/users", json={"name": "Blocked", "email": "blocked@example.test", "username": "blocked", "role": "viewer"}, headers=_headers(admin))
    finally:
        app.dependency_overrides.pop(get_inviter, None)
    assert response.status_code == 503
    assert db.query(User).filter_by(username="blocked").count() == 0


def test_production_config_rejects_missing_invite_transport(tmp_path):
    import os
    import subprocess
    import sys

    environment = os.environ | {
        "APP_ENV": "production", "SECRET_KEY": "s" * 32,
        "POS_INTEGRATION_KEY": "p" * 32, "CORS_ORIGINS": "https://pos.example.test",
        "INVITE_ACTIVATION_URL": "https://pos.example.test/activate", "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "INVITE_SMTP_HOST", "INVITE_FROM_EMAIL"):
        environment.pop(name, None)
    result = subprocess.run([sys.executable, "-c", "import config"], cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "INVITE_SMTP_HOST" in result.stderr
    assert "INVITE_FROM_EMAIL" in result.stderr
