# POS IJM - Backend Manajemen Stok Sparepart

Backend API untuk sistem manajemen stok sparepart kendaraan muatan (truk, bus, dll). Dibangun dengan **FastAPI** + **SQLAlchemy**.

---

## Fitur

- 📦 **Manajemen Barang** — CRUD barang dengan SKU otomatis, kategori, supplier
- 📊 **Manajemen Stok** — Catat barang masuk/keluar, riwayat transaksi, stok menipis
- 🏷️ **Kategori & Supplier** — Kelola pengelompokan barang dan data pemasok
- 🔐 **Autentikasi JWT** — Login multi-user dengan role
- 🕵️ **Kode Harga** — Harga jual dapat ditampilkan dalam kode toko
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
POS_INTEGRATION_KEY=ganti-dengan-kunci-integrasi-yang-panjang

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

> Endpoint reguler `/api` (kecuali login) memakai header `Authorization: Bearer <token>`, sedangkan endpoint `/api/integration` memakai header `X-Integration-Key`.

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

### 🔗 Integrasi Mobile/POS

Semua endpoint berikut memakai header `X-Integration-Key`. SKU dinormalisasi
dengan menghapus spasi tepi dan mengubahnya menjadi huruf kapital.

| Method | Endpoint | Fungsi |
|---|---|---|
| `GET` | `/api/integration/barang` | Daftar barang; filter `q`, `kategori_id`, `supplier_id`, `stok_status`; pagination `page`, `limit` |
| `GET` | `/api/integration/barang/meta` | Daftar kategori, supplier, dan satuan untuk form mobile |
| `GET` | `/api/integration/barang/{id}` | Detail barang berdasarkan ID |
| `PUT` | `/api/integration/barang/{id}` | Ubah sebagian metadata barang; field yang tidak dikirim tetap |
| `DELETE` | `/api/integration/barang/{id}` | Hapus barang beserta riwayat stok dan record idempotensi terkait; HTTP 409 jika ada riwayat cetak |
| `POST` | `/api/integration/barang/{id}/foto` | Unggah/ganti foto barang |
| `GET` | `/api/integration/barang/search?q=...` | Pencarian ringkas lama berdasarkan nama/SKU |
| `GET` | `/api/integration/barang/by-sku/{sku}` | Detail lama berdasarkan SKU persis |
| `POST` | `/api/integration/barang` | Buat barang dan stok awal secara atomik |
| `PUT` | `/api/integration/barang/by-sku/{sku}` | Ubah nama dan harga melalui kontrak lama |
| `POST` | `/api/integration/barang/by-sku/{sku}/stok-masuk` | Tambah stok secara idempoten |

`stok_status` menerima `aman`, `menipis`, atau `habis`; `limit` maksimal 100.
Perubahan metadata tidak mengubah stok. Semua perubahan stok memakai endpoint
`/by-sku/{sku}/stok-masuk`, bukan `PUT /{id}`.

Contoh buat barang:

```json
{
  "sku": "OIL-001",
  "nama": "Oil Filter",
  "harga_beli": 45000,
  "harga_beli_kode": "KODE-BELI",
  "harga_jual": 60000,
  "jumlah_barang_masuk": 10,
  "operation_id": "b71d24f8-24a8-4e79-8c3c-e330807ca8ec",
  "merek": "Acme",
  "kategori_id": 2,
  "supplier_id": 3,
  "stok_minimum": 5,
  "satuan": "pcs",
  "deskripsi": "Filter oli"
}
```

Contoh ubah metadata; `null` pada relasi/teks opsional menghapus nilainya:

```json
{
  "nama": "Oil Filter Premium",
  "kategori_id": null,
  "supplier_id": null,
  "merek": null,
  "deskripsi": null,
  "stok_minimum": 8
}
```

Contoh respons detail:

```json
{
  "id": 12,
  "sku": "OIL-001",
  "nama": "Oil Filter Premium",
  "harga_beli": 45000,
  "harga_jual": 60000,
  "harga_beli_kode": "KODE-BELI",
  "stok": 10,
  "satuan": "pcs",
  "merek": null,
  "foto": null,
  "foto_url": null,
  "kategori": null,
  "supplier": null,
  "stok_minimum": 8,
  "stok_status": "aman",
  "deskripsi": null,
  "created_at": "2026-08-31T10:00:00",
  "updated_at": "2026-08-31T10:05:00"
}
```

Contoh stok masuk:

```json
{
  "jumlah_barang_masuk": 5,
  "harga_satuan": 45000,
  "operation_id": "f335a272-39a3-4aa9-b836-da430958927f"
}
```

`operation_id` wajib berupa UUID unik; retry UUID sama tidak menambah stok dua
kali. Upload foto memakai multipart field `file`, maksimal 5 MiB, dengan tipe
JPEG, PNG, atau WebP. Nama file dibuat server. Penghapusan barang juga menghapus
riwayat stok dan record idempotensi terkait dalam transaksi yang sama. Jika barang
memiliki riwayat cetak (`PrintJob`), penghapusan ditolak dengan HTTP 409; barang,
riwayat stok, dan foto tetap tersimpan. Pengguna harus mempertahankan riwayat cetak
tersebut.

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
