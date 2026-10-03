import json
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.models.barang import Barang
from app.models.admin import SupportGrant
from app.models.audit_log import AuditLog
from app.models.environment import Environment
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import StokSaatIni
from app.models.user import User
from config import ALGORITHM, SECRET_KEY


def auth_headers(user: User, **extra: str) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}", **extra}


def add_environment(db, slug: str) -> Environment:
    environment = Environment(slug=slug, name=slug.title(), status="active")
    db.add(environment)
    db.flush()
    return environment


def add_user(db, environment: Environment, username: str, permissions: list[str]) -> User:
    user = User(
        environment_id=environment.id,
        username=username,
        password_hash="unused",
        nama=username,
        role="staff",
        status="active",
        permissions=json.dumps(permissions),
    )
    db.add(user)
    db.flush()
    return user


def test_chatbot_requires_auth_permission_and_scopes_reads(client, db):
    own_env = add_environment(db, "chat-own")
    other_env = add_environment(db, "chat-other")
    reader = add_user(db, own_env, "chat-reader", ["barang.read", "stok.read", "foto.read"])
    denied = add_user(db, own_env, "chat-denied", [])
    own = Barang(
        environment_id=own_env.id,
        sku="CHAT-OWN",
        nama="Own Item",
        harga_jual=12000,
        harga_beli_kode="SECRET-COST-CODE",
        foto="own.jpg",
    )
    foreign = Barang(environment_id=other_env.id, sku="CHAT-FOREIGN", nama="Foreign Item")
    db.add_all([own, foreign])
    db.flush()
    db.add(StokSaatIni(environment_id=own_env.id, barang_id=own.id, jumlah=4))
    db.commit()

    assert client.post("/api/chatbot/", json={"command": "list barang"}).status_code == 401
    assert client.post(
        "/api/chatbot/",
        headers=auth_headers(denied),
        json={"command": "list barang"},
    ).status_code == 403

    listed = client.post(
        "/api/chatbot/",
        headers=auth_headers(reader),
        json={"command": "list barang"},
    )
    assert listed.status_code == 200
    assert "Own Item" in listed.json()["response"]
    assert "Foreign Item" not in listed.json()["response"]
    assert "SECRET-COST-CODE" not in listed.text

    photo = client.post(
        "/api/chatbot/",
        headers=auth_headers(reader),
        json={"command": f"foto barang id={own.id}"},
    )
    assert photo.status_code == 200
    assert f"/api/foto-barang/{own_env.id}/own.jpg" in photo.json()["response"]


def test_chatbot_mutations_are_permissioned_scoped_and_cross_toko_is_404(client, db):
    own_env = add_environment(db, "chat-write-own")
    other_env = add_environment(db, "chat-write-other")
    writer = add_user(
        db,
        own_env,
        "chat-writer",
        ["barang.read", "barang.write", "barang.delete", "stok.write", "foto.write"],
    )
    foreign = Barang(environment_id=other_env.id, sku="FOREIGN", nama="Foreign")
    foreign_supplier = Supplier(environment_id=other_env.id, kode_supplier="FOREIGN", nama="Foreign Supplier")
    db.add_all([foreign, foreign_supplier])
    db.commit()

    for command in (
        f"ubah barang id={foreign.id} nama=Hacked",
        f"hapus barang id={foreign.id}",
        f"stok masuk id={foreign.id} jumlah=1",
        f"cetak label id={foreign.id}",
    ):
        response = client.post(
            "/api/chatbot/", headers=auth_headers(writer), json={"command": command}
        )
        assert response.status_code == 404, command

    created = client.post(
        "/api/chatbot/",
        headers=auth_headers(writer),
        json={"command": "tambah barang nama=Scoped Item supplier=Scoped Vendor stok=2"},
    )
    assert created.status_code == 200, created.text
    item = db.query(Barang).filter_by(nama="Scoped Item").one()
    supplier = db.query(Supplier).filter_by(nama="Scoped Vendor").one()
    stock = db.query(StokSaatIni).filter_by(barang_id=item.id).one()
    assert item.environment_id == own_env.id
    assert supplier.environment_id == own_env.id
    assert stock.environment_id == own_env.id


def test_label_routes_require_permissions_scope_config_and_hide_cost_code(client, db):
    own_env = add_environment(db, "label-own")
    other_env = add_environment(db, "label-other")
    reader = add_user(db, own_env, "label-reader", ["barang.read"])
    manager = add_user(db, own_env, "label-manager", ["barang.read", "environment.settings"])
    denied = add_user(db, own_env, "label-denied", [])
    own = Barang(
        environment_id=own_env.id,
        sku="LABEL-OWN",
        nama="Own Label",
        harga_jual=15000,
        harga_modal=9000,
        harga_beli_kode="PRIVATE-COST-CODE",
    )
    foreign = Barang(environment_id=other_env.id, sku="LABEL-OTHER", nama="Other Label")
    db.add_all([own, foreign])
    db.commit()

    assert client.get("/api/label/sizes").status_code == 401
    assert client.get("/api/label/sizes", headers=auth_headers(denied)).status_code == 403
    assert client.get("/api/label/config", headers=auth_headers(reader)).status_code == 403

    saved = client.post(
        "/api/label/config",
        headers=auth_headers(manager),
        json={"default_size": "80x40"},
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/api/label/config", headers=auth_headers(manager)).json() == {
        "default_size": "80x40"
    }

    other_manager = add_user(db, other_env, "label-other-manager", ["environment.settings"])
    db.commit()
    assert client.get("/api/label/config", headers=auth_headers(other_manager)).json() == {
        "default_size": "a4_2col"
    }

    sticker = client.get(f"/api/label/sticker/{own.id}", headers=auth_headers(reader))
    assert sticker.status_code == 200
    assert "PRIVATE-COST-CODE" not in sticker.text
    assert "harga-beli" not in sticker.text
    assert client.get(
        f"/api/label/sticker/{foreign.id}", headers=auth_headers(reader)
    ).status_code == 404
    assert client.get(
        f"/api/label/sticker/{own.id}", headers=auth_headers(denied)
    ).status_code == 403


def test_label_print_job_creation_is_environment_scoped(client, db):
    environment = add_environment(db, "label-print")
    user = add_user(db, environment, "label-printer", ["barang.read"])
    barang = Barang(environment_id=environment.id, sku="PRINT-LABEL", nama="Print Label")
    db.add(barang)
    db.commit()

    response = client.get(
        f"/api/label/sticker/{barang.id}/print",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    assert db.query(PrintJob).filter_by(
        environment_id=environment.id, barang_id=barang.id
    ).count() == 1


def test_integration_supplier_and_barang_metadata_never_fall_back_global(client, db):
    legacy = db.query(Environment).filter_by(slug="lithia-autoparts").one()
    other = add_environment(db, "integration-other")
    legacy_supplier = Supplier(environment_id=legacy.id, kode_supplier="LEGACY", nama="Legacy Supplier")
    other_supplier = Supplier(environment_id=other.id, kode_supplier="OTHER", nama="Other Supplier")
    legacy_item = Barang(environment_id=legacy.id, sku="META-LEGACY", nama="Legacy", satuan="box")
    other_item = Barang(environment_id=other.id, sku="META-OTHER", nama="Other", satuan="secret-unit")
    db.add_all([legacy_supplier, other_supplier, legacy_item, other_item])
    db.commit()

    headers = {"X-Integration-Key": "test-integration-key"}
    suppliers = client.get("/api/integration/suppliers", headers=headers)
    assert suppliers.status_code == 200
    assert [item["kode_supplier"] for item in suppliers.json()["data"]] == ["LEGACY"]

    metadata = client.get("/api/integration/barang/meta", headers=headers)
    assert metadata.status_code == 200
    assert metadata.json()["satuan"] == ["box", "pcs"]
    assert [item["kode_supplier"] for item in metadata.json()["suppliers"]] == ["LEGACY"]


def test_integration_update_supplier_duplicate_and_delete_are_strictly_scoped(client, db):
    legacy = db.query(Environment).filter_by(slug="lithia-autoparts").one()
    other = add_environment(db, "integration-update-other")
    foreign_supplier = Supplier(environment_id=other.id, kode_supplier="FOREIGN", nama="Foreign Supplier")
    own = Barang(environment_id=legacy.id, sku="OWN-SKU", nama="Own")
    foreign = Barang(environment_id=other.id, sku="FOREIGN-SKU", nama="Foreign")
    duplicate_other = Barang(environment_id=other.id, sku="SHARED-SKU", nama="Other Shared")
    db.add_all([foreign_supplier, own, foreign, duplicate_other])
    db.commit()
    headers = {"X-Integration-Key": "test-integration-key"}

    update = client.put(
        f"/api/integration/barang/{own.id}",
        headers=headers,
        json={"sku": "SHARED-SKU"},
    )
    assert update.status_code == 200, update.text
    assert client.put(
        f"/api/integration/barang/{own.id}",
        headers=headers,
        json={"supplier_id": foreign_supplier.id},
    ).status_code == 422
    assert client.delete(
        f"/api/integration/barang/{foreign.id}", headers=headers
    ).status_code == 404
    db.expire_all()
    assert db.get(Barang, foreign.id) is not None


def test_environment_patch_separates_owner_lifecycle_from_tenant_settings(client, db):
    environment = add_environment(db, "patch-scope")
    admin = User(
        environment_id=environment.id,
        username="patch-admin",
        password_hash="unused",
        nama="Patch Admin",
        role="admin",
        status="active",
    )
    owner = User(
        environment_id=None,
        username="patch-owner",
        password_hash="unused",
        nama="Patch Owner",
        role="platform_owner",
        status="active",
    )
    db.add_all([admin, owner])
    db.commit()

    assert client.patch(
        f"/api/environments/{environment.id}",
        headers=auth_headers(admin),
        json={"status": "suspended"},
    ).status_code == 403
    assert client.patch(
        f"/api/environments/{environment.id}",
        headers=auth_headers(owner),
        json={"address": "Tenant data"},
    ).status_code == 403

    lifecycle = client.patch(
        f"/api/environments/{environment.id}",
        headers=auth_headers(owner),
        json={"status": "suspended"},
    )
    assert lifecycle.status_code == 200, lifecycle.text
    assert lifecycle.json()["status"] == "suspended"


def test_owner_tenant_settings_patch_requires_reason_time_bound_grant_and_audit(client, db):
    from app.audit import drain_audit_logs

    environment = add_environment(db, "patch-grant")
    owner = User(
        environment_id=None,
        username="patch-grant-owner",
        password_hash="unused",
        nama="Patch Grant Owner",
        role="platform_owner",
        status="active",
    )
    db.add(owner)
    db.flush()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    grant = SupportGrant(
        environment_id=environment.id,
        platform_owner_id=owner.id,
        reason="Correct tenant address during support session",
        starts_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
    )
    db.add(grant)
    db.commit()

    assert client.patch(
        f"/api/environments/{environment.id}",
        headers=auth_headers(owner),
        json={"address": "Granted Address"},
    ).status_code == 403
    response = client.patch(
        f"/api/environments/{environment.id}",
        headers=auth_headers(owner, **{"X-Support-Grant": str(grant.id)}),
        json={"address": "Granted Address"},
    )
    assert response.status_code == 200, response.text
    client.portal.call(drain_audit_logs)
    db.expire_all()
    assert db.get(Environment, environment.id).address == "Granted Address"
    log = db.query(AuditLog).filter(
        AuditLog.path == f"/api/environments/{environment.id}",
        AuditLog.action == "SUPPORT",
    ).order_by(AuditLog.id.desc()).first()
    assert log is not None
    assert str(grant.id) in log.summary
    assert grant.reason not in log.summary


def test_domain_models_require_environment_ids_and_supplier_codes_never_use_null_scope():
    from app.models.barang import BarangFoto, BarangSupplier
    from app.models.printjob import PrintJob
    from app.models.transaksi import IntegrationStockOperation, StokSaatIni, TransaksiStok
    from app.services import supplier_code

    for model in (Barang, Supplier, StokSaatIni, TransaksiStok, BarangSupplier, BarangFoto, PrintJob, IntegrationStockOperation):
        assert model.__table__.c.environment_id.nullable is False
    assert "is_(None)" not in supplier_code.assign_supplier_code.__code__.co_names


def test_photo_serializers_and_public_route_use_only_scoped_safe_urls(client, db, tmp_path, monkeypatch):
    import main

    legacy = db.query(Environment).filter_by(slug="lithia-autoparts").one()
    other = add_environment(db, "photo-other")
    user = add_user(db, legacy, "photo-reader", ["barang.read", "foto.read"])
    own = Barang(environment_id=legacy.id, sku="PHOTO-OWN", nama="Own Photo", foto="own.jpg")
    foreign = Barang(environment_id=other.id, sku="PHOTO-OTHER", nama="Other Photo", foto="other.jpg")
    db.add_all([own, foreign])
    db.commit()
    (tmp_path / str(legacy.id)).mkdir()
    (tmp_path / str(legacy.id) / "own.jpg").write_bytes(b"own")
    (tmp_path / "own.jpg").write_bytes(b"legacy fallback")
    (tmp_path / str(other.id)).mkdir()
    (tmp_path / str(other.id) / "other.jpg").write_bytes(b"other")
    monkeypatch.setattr(main, "FOTO_STORAGE_DIR", str(tmp_path))

    no_photo_access = add_user(db, legacy, "photo-denied", ["barang.read"])
    db.commit()
    assert client.get(
        f"/api/foto-barang/{legacy.id}/own.jpg", headers=auth_headers(no_photo_access)
    ).status_code == 403

    internal = client.get(f"/api/barang/{own.id}", headers=auth_headers(user))
    assert internal.status_code == 200
    assert internal.json()["foto_url"] == f"/api/foto-barang/{legacy.id}/own.jpg"
    assert "/storage/" not in internal.text

    public = client.get("/api/katalog/barang")
    assert public.status_code == 200
    assert public.json()["data"][0]["foto_url"] == "/api/katalog/foto/own.jpg"
    assert client.get("/api/katalog/foto/own.jpg").content == b"own"
    assert client.get("/api/katalog/foto/other.jpg").status_code == 404
    assert client.get("/api/katalog/foto/../own.jpg").status_code == 404

    (tmp_path / str(legacy.id) / "own.jpg").unlink()
    assert client.get(
        f"/api/foto-barang/{legacy.id}/own.jpg", headers=auth_headers(user)
    ).status_code == 404
