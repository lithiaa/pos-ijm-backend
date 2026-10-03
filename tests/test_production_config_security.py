import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_config(**overrides):
    environment = os.environ.copy()
    for key in ("APP_ENV", "SECRET_KEY", "POS_INTEGRATION_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
        environment.pop(key, None)
    environment.update(overrides)
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_production_rejects_missing_or_predictable_secrets_without_printing_values():
    missing = run_config(APP_ENV="production")
    assert missing.returncode != 0
    assert "SECRET_KEY" in missing.stderr
    assert "ganti-secret-key-ini" not in missing.stderr

    predictable = run_config(
        APP_ENV="production",
        SECRET_KEY="ganti-secret-key-ini",
        POS_INTEGRATION_KEY="test-integration-key",
        ADMIN_PASSWORD="admin123",
    )
    assert predictable.returncode != 0
    assert "predictable" in predictable.stderr.lower()
    assert "admin123" not in predictable.stderr
    assert "test-integration-key" not in predictable.stderr


def test_test_config_needs_no_credentials_and_has_no_admin_bootstrap_defaults():
    result = run_config(APP_ENV="test")
    assert result.returncode == 0, result.stderr
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "PYTHON_DOTENV_DISABLED": "1", "PYTHONPATH": str(PROJECT_ROOT)})
    output = subprocess.run(
        [sys.executable, "-c", "import config; print(hasattr(config, 'ADMIN_PASSWORD'))"],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.stdout.strip() == "False"
