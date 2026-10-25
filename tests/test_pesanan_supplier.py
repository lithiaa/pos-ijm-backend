from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_principal
from app.models.environment import Environment
from app.models.pesanan_supplier import PesananSupplier
from app.routers import pesanan_supplier


def test_pesanan_supplier_crud_tenant_and_validation():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base = PesananSupplier.__mro__[1]
    Base.metadata.create_all(
        engine, tables=[Environment.__table__, PesananSupplier.__table__]
    )
    sessions = sessionmaker(bind=engine)
    tenant = {"id": 1}

    def override_db():
        with sessions() as db:
            yield db

    class Principal:
        def has_permission(self, *args, **kwargs):
            return True

    app = FastAPI()
    app.include_router(pesanan_supplier.router)
    app.dependency_overrides[pesanan_supplier.get_db] = override_db
    app.dependency_overrides[pesanan_supplier.get_current_user_env_id] = (
        lambda: tenant["id"]
    )
    app.dependency_overrides[get_current_principal] = (
        lambda: Principal()
    )
    collection = next(
        route.path for route in pesanan_supplier.router.routes if "POST" in route.methods
    )
    item_route = next(
        route.path
        for route in pesanan_supplier.router.routes
        if "GET" in route.methods and "{" in route.path
    )

    with TestClient(app) as client:
        payload = {"nama_barang": "Filter", "jumlah_barang": 2}
        created = client.post(collection, json=payload)
        assert created.status_code in (200, 201), created.text
        item_id = created.json()["id"]
        assert created.json()["status"] == "pending"
        listed = client.get(collection)
        assert listed.status_code == 200, listed.text
        assert any(entry["id"] == item_id for entry in listed.json())
        item = item_route.replace(item_route[item_route.index("{") : item_route.index("}") + 1], str(item_id))

        fetched = client.get(item)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["nama_barang"] == "Filter"

        updated = client.put(item, json={"nama_barang": "Oli", "status": "dipesan"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "dipesan"
        assert client.get(item).json()["nama_barang"] == "Oli"
        assert client.get(item).json()["status"] == "dipesan"

        principal_override = app.dependency_overrides.pop(get_current_principal)
        try:
            assert client.get(collection).status_code == 401
        finally:
            app.dependency_overrides[get_current_principal] = principal_override


        tenant["id"] = 2
        assert client.get(item).status_code == 404
        assert client.put(item, json={"nama_barang": "Lain"}).status_code == 404
        assert client.delete(item).status_code == 404
        tenant["id"] = 1

        for invalid in (
            {**payload, "nama_barang": "   "},
            {**payload, "jumlah": 0},
            {**payload, "status": "invalid"},
        ):
            assert client.post(collection, json=invalid).status_code == 422

        deleted = client.delete(item)
        assert deleted.status_code in (200, 204), deleted.text
        assert client.get(item).status_code == 404

    engine.dispose()
