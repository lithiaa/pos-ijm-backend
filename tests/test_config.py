import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_access_token_expiry_defaults_to_seven_days_without_environment_override(tmp_path):
    environment = os.environ.copy()
    environment.pop("ACCESS_TOKEN_EXPIRE_MINUTES", None)
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    environment["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from config import ACCESS_TOKEN_EXPIRE_MINUTES; print(ACCESS_TOKEN_EXPIRE_MINUTES)",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "10080"


def test_production_rejects_http_invite_activation_url(tmp_path):
    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "production",
        "SECRET_KEY": "s" * 32,
        "POS_INTEGRATION_KEY": "p" * 32,
        "CORS_ORIGINS": "https://pos.example.test",
        "INVITE_ACTIVATION_URL": "http://pos.example.test/activate",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(PROJECT_ROOT),
    })
    environment.pop("ADMIN_USERNAME", None)
    environment.pop("ADMIN_PASSWORD", None)

    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "INVITE_ACTIVATION_URL" in result.stderr


def test_production_rejects_malformed_invite_activation_url(tmp_path):
    environment = os.environ.copy()
    environment.update({
        "APP_ENV": "production",
        "SECRET_KEY": "s" * 32,
        "POS_INTEGRATION_KEY": "p" * 32,
        "CORS_ORIGINS": "https://pos.example.test",
        "INVITE_ACTIVATION_URL": "https://pos.example.test:not-a-port/activate",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(PROJECT_ROOT),
    })
    environment.pop("ADMIN_USERNAME", None)
    environment.pop("ADMIN_PASSWORD", None)

    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "INVITE_ACTIVATION_URL" in result.stderr
