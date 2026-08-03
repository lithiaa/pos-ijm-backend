import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root@localhost:3306/toko_sparepart"
)
SECRET_KEY = os.getenv("SECRET_KEY", "ganti-secret-key-ini")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))

# Admin default
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_NAMA = os.getenv("ADMIN_NAMA", "Admin Toko")

# SANGUOERIP mapping
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
