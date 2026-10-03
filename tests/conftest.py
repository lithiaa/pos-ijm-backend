import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session


TEST_INTEGRATION_KEY = "test-integration-key"
_test_database_dir = tempfile.mkdtemp(prefix="toko-sparepart-tests-")
_test_database_path = Path(_test_database_dir) / "test.db"

# These must be set before importing the application because its engine and
# configuration values are created at import time.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_database_path}"
os.environ["POS_INTEGRATION_KEY"] = TEST_INTEGRATION_KEY

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.environment import Environment  # noqa: E402
from main import app  # noqa: E402


LEGACY_ENVIRONMENT_SLUG = "lithia-autoparts"
SCOPED_DOMAIN_MODELS = {
    "Barang", "Supplier", "StokSaatIni", "TransaksiStok", "BarangSupplier",
    "BarangFoto", "PrintJob", "IntegrationStockOperation",
}


@event.listens_for(Session, "before_flush")
def assign_test_environment_ids(session, _flush_context, _instances):
    """Test-only compatibility for legacy fixtures; production models remain NOT NULL."""
    if os.environ.get("APP_ENV") == "production":
        return
    pending = [
        item for item in session.new
        if item.__class__.__name__ in SCOPED_DOMAIN_MODELS
        and getattr(item, "environment_id", None) is None
    ]
    if not pending:
        return
    environment = get_legacy_environment(session)
    for item in pending:
        item.environment_id = environment.id


def get_legacy_environment(session):
    environment = session.query(Environment).filter_by(slug=LEGACY_ENVIRONMENT_SLUG).first()
    if environment is None:
        environment = Environment(slug=LEGACY_ENVIRONMENT_SLUG, name="Lithia Autoparts", status="active")
        session.add(environment)
        session.flush()
    return environment


@pytest.fixture
def legacy_environment(db):
    return get_legacy_environment(db)


@pytest.fixture
def legacy_environment_id(legacy_environment):
    return legacy_environment.id


@pytest.fixture
def legacy_user(db, legacy_environment):
    from app.models.user import User

    user = User(username="legacy-user", password_hash="unused", nama="Legacy User", role="admin", environment_id=legacy_environment.id)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def legacy_auth_headers(legacy_user):
    from app.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': str(legacy_user.id)})}"}


@pytest.fixture
def legacy_integration_headers():
    return {"X-Integration-Key": TEST_INTEGRATION_KEY}


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(monkeypatch, request):
    if request.module.__name__ not in {"test_security_findings", "test_multi_toko_isolation"}:
        session = SessionLocal()
        try:
            get_legacy_environment(session)
            session.commit()
        finally:
            session.close()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(_test_database_dir, ignore_errors=True)
