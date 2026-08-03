# POS IJM - Backend Manajemen Stok Sparepart

Backend API untuk sistem manajemen stok sparepart kendaraan muatan (truk, bus, dll). Dibangun dengan **FastAPI** + **SQLAlchemy**.

---

## Fitur

- 📦 **Manajemen Barang** — CRUD barang dengan SKU otomatis, kategori, supplier
- 📊 **Manajemen Stok** — Catat barang masuk/keluar, riwayat transaksi, stok menipis
- 🏷️ **Kategori & Supplier** — Kelola pengelompokan barang dan data pemasok
- 🔐 **Autentikasi JWT** — Login multi-user dengan role
- 🕵️ **Kode Harga SANGUOERIP** — Harga jual ditampilkan dalam kode rahasia (S=1 A=2 N=3 G=4 U=5 O=6 E=7 R=8 I=9 P=0)
- 📈 **Dashboard** — Statistik ringkasan, grafik stok menipis, transaksi terbaru

---

## Tech Stack

| Komponen | Teknologi |
|---|---|
| Framework | FastAPI (Python) |
| Database | MySQL 8 / SQLite (via `DATABASE_URL`) |
| ORM | SQLAlchemy 2 |
| Auth | JWT (python-jose) + bcrypt |
| Env | python-dotenv |

---

## Struktur Direktori

```
pos-ijm-backend/
├── main.py                  # Entry point aplikasi
├── config.py                # Konfigurasi dari environment
├── requirements.txt         # Dependencies Python
├── .env.example             # Template konfigurasi
├── .gitignore
└── app/
    ├── __init__.py
    ├── database.py          # Koneksi & session database
    ├── auth.py              # Login, JWT, password hashing
    ├── models/              # Model database (SQLAlchemy)
    │   ├── barang.py
    │   ├── kategori.py
    │   ├── supplier.py
    │   ├── transaksi.py     # StokSaatIni & TransaksiStok
    │   └── user.py
    ├── schemas/             # Schema request/response (Pydantic)
    │   ├── auth.py
    │   ├── barang.py
    │   ├── kategori.py
    │   ├── stok.py
    │   └── supplier.py
    ├── routers/             # Endpoint API
    │   ├── auth.py
    │   ├── barang.py
    │   ├── dashboard.py
    │   ├── kategori.py
    │   ├── stok.py
    │   └── supplier.py
    └── services/
        └── harga.py         # Encode/decode kode SANGUOERIP
```

---

## Cara Setup

### 1. Clone repo

```bash
git clone https://github.com/lithiaa/pos-ijm-backend.git
cd pos-ijm-backend
```

### 2. Buat virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# atau
venv\Scripts\activate     # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup database

**Opsi A — SQLite (paling gampang untuk dev lokal):**

```bash
export DATABASE_URL=sqlite:///./toko_sparepart.db
```

**Opsi B — MySQL:**

```sql
CREATE DATABASE toko_sparepart CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 5. Konfigurasi environment

```bash
cp .env.example .env
```

Edit file `.env` sesuai server kamu:

```env
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/toko_sparepart
SECRET_KEY=isi-dengan-random-string-panjang
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123
ADMIN_NAMA=Admin Toko
```

### 6. Jalankan

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Admin default (`admin / admin123`) akan dibuat otomatis saat pertama kali jalan.

---

## Dev Setup Lokal (cepat)

Jalanin backend di mesin sendiri tanpa MySQL:

```bash
# 1. Clone + masuk
git clone https://github.com/lithiaa/pos-ijm-backend.git
cd pos-ijm-backend

# 2. Venv + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Jalankan dengan SQLite
export DATABASE_URL="sqlite:///./toko_sparepart.db"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- DB file `toko_sparepart.db` dibuat otomatis, tabel di-create saat startup (`Base.metadata.create_all`)
- Admin default: `admin / admin123`
- Swagger: http://localhost:8000/docs
- Reset DB: `rm toko_sparepart.db` lalu restart

---

## Print Job API (Cetak Label Otomatis)

Antrian cetak label: bot/chatbot bikin job → agent di laptop toko poll → kirim TSPL ke printer USB.

| Method | Endpoint | Fungsi |
|---|---|---|
| `POST` | `/api/print-jobs` | Buat job `{barang_id, qty}` → status `pending` |
| `GET` | `/api/print-jobs?status=pending` | Ambil antrian (join data barang) |
| `PATCH` | `/api/print-jobs/{id}` | Update status: `printing` / `done` / `failed` |

**Status job:** `pending` → `printing` → `done` / `failed`

**Chatbot:**
- `cetak label id=1 qty=2` — buat job print, bukan URL
- `stok masuk id=1 jumlah=20 cetak=1` — stok masuk + langsung bikin job print

**Agent laptop** (folder `~/print-agent`, laptop Linux + printer USB):
```bash
./install.sh                          # systemd user service, restart otomatis
python3 agent.py --test               # cetak label test
journalctl --user -u print-agent -f   # log
```
Env: `PRINT_API_URL` (default `https://api.ijm.lithiaproject.site`), `PRINT_DEVICE` (default `/dev/usb/lp0`), `PRINT_POLL_INTERVAL` (default 5).

---

## API Endpoint

> Semua endpoint (kecuali login) membutuhkan header: `Authorization: Bearer <token>`

### 🔐 Autentikasi

| Method | Endpoint | Fungsi |
|---|---|---|
| `POST` | `/api/auth/login` | Login, dapatkan token JWT |
| `GET` | `/api/auth/me` | Info user yang sedang login |

### 🏷️ Kategori

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/api/kategori` | Daftar semua kategori |
| `POST` | `/api/kategori` | Tambah kategori baru |
| `PUT` | `/api/kategori/{id}` | Edit kategori |
| `DELETE` | `/api/kategori/{id}` | Hapus kategori |

### 🤝 Supplier

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/api/supplier` | Daftar semua supplier |
| `POST` | `/api/supplier` | Tambah supplier baru |
| `PUT` | `/api/supplier/{id}` | Edit supplier |
| `DELETE` | `/api/supplier/{id}` | Hapus supplier |

### 📦 Barang

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/api/barang` | Daftar barang (support search, filter kategori, pagination) |
| `GET` | `/api/barang/stok-menipis` | Barang dengan stok <= stok minimum |
| `GET` | `/api/barang/{id}` | Detail barang |
| `POST` | `/api/barang` | Tambah barang baru |
| `PUT` | `/api/barang/{id}` | Edit barang |
| `DELETE` | `/api/barang/{id}` | Hapus barang |

**Query params untuk GET `/api/barang`:**

| Param | Tipe | Fungsi |
|---|---|---|
| `search` | string | Cari berdasarkan nama/SKU/merek |
| `kategori_id` | int | Filter berdasarkan kategori |
| `stok_menipis` | bool | Tampilkan hanya barang stok menipis |
| `page` | int | Halaman (default: 1) |
| `limit` | int | Jumlah per halaman (default: 20, max: 100) |

### 📊 Stok

| Method | Endpoint | Fungsi |
|---|---|---|
| `POST` | `/api/stok/masuk` | Catat barang masuk |
| `POST` | `/api/stok/keluar` | Catat barang keluar |
| `GET` | `/api/stok/riwayat` | Riwayat transaksi stok |

**Query params untuk GET `/api/stok/riwayat`:**

| Param | Tipe | Fungsi |
|---|---|---|
| `tanggal_mulai` | string | Filter tanggal (YYYY-MM-DD) |
| `tanggal_akhir` | string | Filter tanggal akhir |
| `jenis` | string | Filter jenis (masuk/keluar) |
| `page` | int | Halaman |
| `limit` | int | Jumlah per halaman |

### 📈 Dashboard

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/api/dashboard` | Statistik: total barang, stok menipis, transaksi hari ini, grafik |

---

---

## Dokumentasi API (Swagger)

Setelah server jalan, buka di browser:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## Lisensi

Hak cipta milik IJM Store.
