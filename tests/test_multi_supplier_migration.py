"""Migration helper rejects non-MySQL engines before touching any schema."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine


spec = importlib.util.spec_from_file_location(
    "multi_supplier_migration",
    Path(__file__).parents[1] / "migrations/20260927_multi_supplier_gallery.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_migration_helper_does_not_run_on_sqlite():
    with create_engine("sqlite://").connect() as connection:
        with pytest.raises(RuntimeError, match="MySQL/MariaDB"):
            migration._migrate_connection(connection)
