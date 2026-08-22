import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_INTEGRATION_KEY = "test-integration-key"
_test_database_dir = tempfile.mkdtemp(prefix="toko-sparepart-tests-")
_test_database_path = Path(_test_database_dir) / "test.db"

# These must be set before importing the application because its engine and
# configuration values are created at import time.
os.environ["DATABASE_URL"] = f"sqlite:///{_test_database_path}"
os.environ["POS_INTEGRATION_KEY"] = TEST_INTEGRATION_KEY

from app.database import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


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
