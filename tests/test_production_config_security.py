import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_config(**overrides):
    environment = os.environ.copy()
    for key in ("APP_ENV", "SECRET_KEY", "POS_INTEGRATION_KEY", "CORS_ORIGINS", "ADMIN_USERNAME", "ADMIN_PASSWORD"):
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


def test_production_requires_explicit_non_wildcard_cors_origins():
    missing = run_config(
        APP_ENV="production",
        SECRET_KEY="x" * 32,
        POS_INTEGRATION_KEY="y" * 32,
    )
    assert missing.returncode != 0
    assert "CORS_ORIGINS" in missing.stderr

    wildcard = run_config(
        APP_ENV="production",
        SECRET_KEY="x" * 32,
        POS_INTEGRATION_KEY="y" * 32,
        CORS_ORIGINS="https://app.example.test,*",
    )
    assert wildcard.returncode != 0
    assert "CORS_ORIGINS" in wildcard.stderr


def test_cors_origins_parse_trimmed_comma_separated_values():
    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "test", "CORS_ORIGINS": " https://one.example.test,https://two.example.test , ,",
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONPATH": str(PROJECT_ROOT),
    })
    result = subprocess.run(
        [sys.executable, "-c", "from config import CORS_ORIGINS; print(repr(CORS_ORIGINS))"],
        cwd=PROJECT_ROOT, env=environment, check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "['https://one.example.test', 'https://two.example.test']"


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
