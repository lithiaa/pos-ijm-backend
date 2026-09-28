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
