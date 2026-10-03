import os
from secrets import token_urlsafe
from urllib.parse import urlsplit


from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root@localhost:3306/toko_sparepart",
)
SECRET_KEY = os.getenv("SECRET_KEY") or (token_urlsafe(48) if APP_ENV in {"development", "test"} else "")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))
POS_INTEGRATION_KEY = os.getenv("POS_INTEGRATION_KEY", "")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()]
AUDIT_TRUSTED_PROXIES = os.getenv("AUDIT_TRUSTED_PROXIES", "")
INVITE_SMTP_HOST = os.getenv("INVITE_SMTP_HOST", "")
INVITE_SMTP_PORT = int(os.getenv("INVITE_SMTP_PORT", "25"))
INVITE_FROM_EMAIL = os.getenv("INVITE_FROM_EMAIL", "")
INVITE_ACTIVATION_URL = os.getenv("INVITE_ACTIVATION_URL", "http://localhost:3000/activate").strip()


def _validate_production_config() -> None:
    if APP_ENV != "production":
        return
    predictable = {
        "",
        "admin",
        "admin123",
        "change-me",
        "changeme",
        "default",
        "ganti-secret-key-ini",
        "secret",
        "test",
        "test-integration-key",
    }
    invalid = []
    if SECRET_KEY.lower() in predictable or len(SECRET_KEY) < 32:
        invalid.append("SECRET_KEY")
    if POS_INTEGRATION_KEY and (
        POS_INTEGRATION_KEY.lower() in predictable or len(POS_INTEGRATION_KEY) < 32
    ):
        invalid.append("POS_INTEGRATION_KEY")
    if not os.getenv("CORS_ORIGINS") or not CORS_ORIGINS or "*" in CORS_ORIGINS:
        invalid.append("CORS_ORIGINS")
    try:
        activation_url = urlsplit(INVITE_ACTIVATION_URL)
        activation_url.port
    except ValueError:
        activation_url = None
    if (
        not os.getenv("INVITE_ACTIVATION_URL")
        or activation_url is None
        or activation_url.scheme != "https"
        or not activation_url.netloc
        or activation_url.username
        or activation_url.password
        or activation_url.fragment
    ):
        invalid.append("INVITE_ACTIVATION_URL")
    if not INVITE_SMTP_HOST:
        invalid.append("INVITE_SMTP_HOST")
    if not INVITE_FROM_EMAIL:
        invalid.append("INVITE_FROM_EMAIL")
    for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD"):
        if os.getenv(name):
            invalid.append(name)
    if invalid:
        raise RuntimeError(
            "Production config has missing or predictable values: " + ", ".join(invalid)
        )


_validate_production_config()

HARGA_ENCODE_MAP = {
    "S": "1", "A": "2", "N": "3", "G": "4",
    "U": "5", "O": "6", "E": "7", "R": "8",
    "I": "9", "P": "0",
    "s": "1", "a": "2", "n": "3", "g": "4",
    "u": "5", "o": "6", "e": "7", "r": "8",
    "i": "9", "p": "0",
}

HARGA_DECODE_MAP = {
    "1": "S", "2": "A", "3": "N", "4": "G",
    "5": "U", "6": "O", "7": "E", "8": "R",
    "9": "I", "0": "P",
}
