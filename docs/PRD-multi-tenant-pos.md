# PRD: Lithia POS Multi-Environment

**Status:** Draft — menunggu persetujuan Product Owner
**Versi:** 1.0
**Tanggal:** 2026-10-01
**Penulis:** Stella

---

## 1. Ringkasan Eksekutif

Lithia POS saat ini berisi data inventori sparepart dalam satu lingkungan. PRD ini mengubah Lithia POS menjadi platform inventori multi-environment: satu instalasi aplikasi dapat dipakai banyak bisnis atau jenis usaha, dengan data barang, supplier, stok, transaksi, foto, dan user yang terisolasi per environment.

Setiap environment memiliki Administrator sendiri. Administrator mengelola data bisnisnya dan dapat membuat user lain untuk membantu mengelola barang serta stok. User dari satu environment tidak boleh melihat atau mengubah data environment lain.

Data sparepart saat ini dipertahankan sebagai environment lama bernama `Lithia Autoparts`.

---

## 2. Latar Belakang & Masalah

### Masalah

- Struktur POS masih mengasumsikan satu bisnis: sparepart.
- Data barang, supplier, stok, transaksi, foto, dan audit log belum memiliki pemilik environment yang eksplisit.
- Administrator baru berisiko melihat atau mengubah data sparepart.
- Belum ada mekanisme pembuatan environment bisnis baru.
- Belum ada pengelolaan user per environment dengan batas akses yang jelas.

### Dampak

- Lithia POS sulit dipakai toko selain sparepart.
- Risiko kebocoran atau tercampurnya data antar bisnis.
- Pemilik bisnis tidak dapat mengelola user secara mandiri.
- Perubahan data sulit diaudit berdasarkan environment.

### Kenapa sekarang

Fitur multi-supplier, galeri foto, dan user management sudah menjadi fondasi. Isolasi environment perlu dibangun sebelum POS dipakai banyak bisnis.

---

## 3. Tujuan & Non-Tujuan

### Tujuan

1. Mendukung banyak environment bisnis dalam satu instalasi Lithia POS.
2. Memastikan data tiap environment terisolasi secara server-side.
3. Menjadikan istilah dan tampilan POS netral, tidak khusus sparepart.
4. Memungkinkan Administrator membuat dan mengelola user dalam environment sendiri.
5. Mempertahankan data sparepart lama tanpa kehilangan riwayat.
6. Menyediakan audit trail untuk pembuatan environment, user, dan perubahan akses.

### Non-tujuan MVP

- Multi-gudang dalam satu environment.
- Konsolidasi laporan lintas environment.
- Billing/subscription SaaS.
- Marketplace atau accounting integration.
- Transfer barang antar-environment.
- Satu user berada di banyak environment sekaligus.
- White-label domain berbeda per environment.

---

## 4. Definisi

| Istilah | Arti |
|---|---|
| **Environment** | Ruang data milik satu bisnis/organisasi. |
| **Platform Owner** | Operator seluruh instalasi: provisioning toko, status toko, dan support access terbatas. UI khusus wajib ada. |
| **Administrator** | Pengelola penuh satu environment, termasuk user dan data inventori. |
| **Staff** | User yang membantu mengelola barang, supplier, stok, dan foto sesuai permission. |
| **Environment aktif** | Environment yang sedang dipakai user pada sesi aktif. |

**Keputusan belum dikonfirmasi:** istilah UI final. Gunakan label sementara **Toko** untuk pengguna dan `environment` untuk kode/database sampai Product Owner mengonfirmasi.

---

## 5. User Persona

### 5.1. Platform Owner

- Menggunakan UI khusus untuk membuat toko/environment dan Administrator pertama.
- Mengelola status aktif/suspended environment.
- Mendapat support access ke data bisnis hanya bila dibutuhkan, reason-bound, time-bound, dan diaudit; bukan akses operasional default.

### 5.2. Administrator Environment

- Pemilik atau pengelola satu bisnis.
- Mengatur profil toko, user, permission, barang, supplier, foto, dan stok.
- Tidak dapat melihat environment lain.

### 5.3. Staff Inventori

- Membantu input barang.
- Mengelola supplier dan foto bila diberi akses.
- Mencatat stok masuk/keluar.
- Tidak dapat membuat administrator atau mengatur permission.

### 5.4. Viewer/Auditor

- Melihat data dan laporan sesuai izin.
- Tidak dapat mengubah data.

---

## 6. Model Akses

### Role MVP

| Role | Scope | Kemampuan utama |
|---|---|---|
| `platform_owner` | Semua environment | Membuat toko/environment, Administrator pertama, status toko, dan support access yang diaudit |
| `admin` | Satu environment | Semua data environment, user, custom permission, profil toko; tidak dapat membuat toko/environment baru |
| `staff` | Satu environment | Akses modul sesuai custom permission |
| `viewer` | Satu environment | Read-only sesuai custom permission |

### Permission MVP

- `barang.read`
- `barang.write`
- `barang.delete`
- `supplier.read`
- `supplier.write`
- `supplier.delete`
- `stok.read`
- `stok.write`
- `stok.delete` — default false; hanya bila diperlukan
- `foto.read`
- `foto.write`
- `logs.read`
- `users.read`
- `users.write`
- `users.disable`
- `environment.settings`

Administrator selalu memiliki semua permission dalam environment sendiri. Staff tidak dapat mengubah role admin atau membuat environment.

### Aturan keamanan

1. Semua tabel bisnis wajib memiliki `environment_id` atau relasi yang tervalidasi ke environment.
2. Backend mengambil environment dari user/session, bukan dari input client yang dipercaya.
3. Setiap query list, detail, create, update, delete, upload foto, dan transaksi stok wajib menerapkan filter environment.
4. ID object dari environment lain harus menghasilkan `404` agar tidak membocorkan keberadaan data.
5. JWT membawa `user_id`; environment aktif diverifikasi server-side. Jangan percaya `environment_id` dari local storage tanpa validasi.
6. User disabled langsung ditolak pada request berikutnya.
7. Audit log menyimpan `environment_id`, user, aksi, resource, resource ID, status, path, dan IP. Support access juga menyimpan alasan, pemberi akses, waktu mulai/berakhir, scope, dan semua aksi selama sesi.
8. Tidak ada kredensial atau token di log, response error, atau chat.

---

## 7. Fitur & Prioritas

### MVP — Wajib

| ID | Fitur | Deskripsi | Prioritas |
|---|---|---|---|
| F-01 | Environment model | Buat entitas environment dan status aktif/suspended | P0 |
| F-02 | Data isolation | Semua data bisnis terikat environment dan difilter backend | P0 |
| F-03 | Bootstrap environment | Platform Owner membuat environment + Administrator pertama secara atomik dan idempotent | P0 |
| F-04 | Login environment | User masuk ke satu environment miliknya dengan konteks tervalidasi | P0 |
| F-05 | User management | Admin membuat, melihat, disable, reset, dan invite user via email | P0 |
| F-06 | Role/permission | Admin mengatur custom permission staff/viewer dari dashboard tanpa memberi hak admin | P0 |
| F-06a | Copy-data wizard | Platform Owner memilih sumber dan data awal environment baru secara aman | P0 |
| F-07 | Environment settings | Nama toko, logo, alamat, kontak, timezone, mata uang | P1 |
| F-08 | Migrasi sparepart | Data lama dipetakan ke environment `Lithia Autoparts` | P0 |
| F-09 | UI netral | Hapus asumsi teks “sparepart”; label mengikuti environment | P1 |
| F-10 | Audit multi-environment | Semua aksi admin/user mencatat environment | P0 |
| F-11 | Foto dan file isolation | Foto hanya dapat diakses melalui object milik environment | P0 |
| F-12 | Backup/restore isolation | Backup menyimpan environment ID dan restore tidak mencampur data | P1 |

### Post-MVP

| ID | Fitur | Prioritas |
|---|---|---|
| F-13 | Switch environment | Satu user dapat menjadi member beberapa environment | P2 |
| F-14 | Undangan via WhatsApp | P2 |
| F-15 | Laporan per environment | P1 |
| F-16 | Billing/subscription | P3 |
| F-17 | Multi-gudang | P2 |
| F-18 | Domain/custom branding per environment | P3 |
| F-19 | Export/import data | P1 |

---

## 8. Alur Utama

### 8.1. Bootstrap environment pertama

1. Platform Owner membuka UI **Buat Toko**.
2. Isi nama toko dan data Administrator pertama.
3. Sistem memprovision environment dan Administrator pertama dalam satu transaksi atomik dan idempotent.
4. Administrator menerima invite aktivasi via email.
5. Setelah aktivasi, sistem menampilkan wizard profil toko.
6. Dashboard hanya menampilkan data environment baru atau hasil copy yang dipilih.

### 8.2. Administrator mengundang user staff

1. Admin membuka **Pengaturan → User**.
2. Klik **Tambah User**.
3. Isi nama, email, role, dan custom permission.
4. Sistem memvalidasi email unik sesuai aturan platform dan scope satu-environment-per-user.
5. Sistem membuat user pada environment sama dan mengirim invite aktivasi via email.
6. User aktivasi lalu login; sesi hanya memuat environment tersebut.

### 8.3. Platform Owner membuat environment lain dan wizard copy data

Hanya Platform Owner dapat memilih **Buat Toko** dan Administrator pertama. Administrator hanya mengelola user pada toko sendiri.

1. Isi nama toko dan data Administrator pertama.
2. Pilih data awal: **Kosong**, **Template**, atau **Salin dari toko lain yang dimiliki**.
3. Untuk Template/sumber toko, wizard menampilkan opsi: pengaturan, kategori, supplier, barang, dan foto tercentang; inventori default **0** dan hanya disalin bila Platform Owner memilihnya secara eksplisit.
4. Wizard tidak menawarkan user, audit log, transaksi stok, atau print job untuk disalin secara default.
5. Submit memprovision environment dan Administrator pertama secara atomik dan idempotent; retry request sama tidak membuat environment/admin duplikat.
6. Setelah environment valid, sistem membuat job copy DB-backed pada node FastAPI tunggal. Tidak ada dependency Redis/Celery untuk MVP.
7. UI menampilkan progress, hasil, dan error job. Pembatalan tersedia sebelum commit bila praktis; data belum ter-commit tidak boleh terlihat sebagai copy selesai.
8. Source memakai snapshot konsisten. Copy membuat ID baru dan mapping source→target untuk semua foreign key; tidak boleh DB clone langsung atau memakai raw ID sumber.
9. Foto disalin ke path target yang scoped environment. Audit mencatat sumber, target, opsi, peminta, status, hasil, dan kegagalan.
10. Retry job aman tanpa data duplikat. Administrator baru menerima invite email lalu hanya dapat mengakses toko target.

### 8.4. User mengelola barang

1. User login.
2. Sistem memuat environment dari session.
3. User membuka Barang.
4. API hanya mengembalikan barang environment aktif.
5. Create/update/delete, supplier, stok, dan foto memakai environment yang sama.
6. Audit log menyimpan user dan environment.

### 8.5. Percobaan akses lintas environment

1. User mengirim ID barang milik environment lain.
2. Backend menjalankan query dengan `environment_id`.
3. Data tidak ditemukan.
4. Backend mengembalikan `404` tanpa membocorkan detail.
5. Percobaan dicatat sebagai audit/security event bila sesuai kebijakan.

---

## 9. Perubahan Data & Struktur Database

### Entitas baru

#### `environments`

- `id`
- `name`
- `slug` atau identifier internal
- `business_type` nullable
- `logo_url` nullable
- `address` nullable
- `phone` nullable
- `timezone` default `Asia/Jakarta`
- `currency` default `IDR`
- `status` (`active`, `suspended`)
- `created_at`, `updated_at`

#### `environment_users` atau kolom user

Rekomendasi MVP: tambahkan `environment_id` pada `users` karena satu user hanya berada pada satu environment. Gunakan tabel membership pada post-MVP bila satu user dapat mengakses banyak environment.

- `users.environment_id`
- `users.role`
- `users.status`
- `users.must_change_password`
- `users.created_at`, `updated_at`

### Tabel yang wajib memiliki environment scope

- `barang`
- `supplier`
- `stok_saat_ini`
- `transaksi_stok`
- `barang_supplier`
- `barang_foto`
- `audit_logs`
- `print_jobs` bila print job dapat berasal dari environment
- data integration/chatbot yang menyimpan object bisnis
- `environment_copy_jobs` untuk job copy data yang persisted dan dapat diretry

### Aturan database

- Tambahkan foreign key `environment_id → environments.id`.
- Tambahkan index `(environment_id, id)` dan index sesuai query list.
- Tambahkan unique constraint yang scoped per environment, misalnya `(environment_id, sku)`.
- Jangan langsung menambahkan constraint tanpa backup dan dry-run migrasi.
- Migrasi harus idempotent.
- Backfill semua baris lama ke environment `Lithia Autoparts` sebelum constraint `NOT NULL`.
- Verifikasi jumlah baris sebelum dan sesudah migrasi.

### Isolasi file foto

Rekomendasi path:

```text
storage/foto-barang/{environment_id}/{uuid}.jpg
```

URL file tidak boleh menerima path arbitrary dari client. Delete barang/environment harus mengikuti kebijakan retention dan audit.

---

## 10. API Contract MVP

### Environment

```text
POST /api/environments                 # platform_owner; idempotency key wajib
GET  /api/environments/{id}            # owner/admin sesuai scope
PATCH /api/environments/{id}           # platform_owner atau admin settings
POST /api/environments/{id}/suspend    # platform_owner
POST /api/environments/{id}/support-access  # platform_owner; reason + durasi wajib
POST /api/environment-copy-jobs         # platform_owner
GET  /api/environment-copy-jobs/{id}    # platform_owner
POST /api/environment-copy-jobs/{id}/cancel # platform_owner; sebelum commit bila tersedia
```

### User

```text
GET  /api/users                         # admin environment
POST /api/users                        # admin environment
GET  /api/users/{id}                   # scoped
PATCH /api/users/{id}                  # scoped
POST /api/users/{id}/disable          # admin environment
POST /api/users/{id}/reset-password    # admin environment
```

### Session

```text
POST /api/auth/login
GET  /api/auth/me
```

`/api/auth/me` wajib mengembalikan role, environment ID, environment name, dan permission efektif. Jangan mengembalikan password, token, secret, atau field internal.

### Error behavior

- `401`: token invalid/expired.
- `403`: role/permission tidak cukup atau environment suspended.
- `404`: resource tidak ada dalam environment user.
- `409`: username/SKU scoped environment bentrok.
- `422`: payload tidak valid.

---

## 11. UI / Navigasi

### Menu Administrator

- Ikhtisar
- Barang
- Supplier
- Stok Masuk
- Stok Keluar
- Riwayat Stok
- Log Aktivitas
- User
- Pengaturan Environment

### Menu Staff

Menu ditentukan permission. Default tidak melihat User dan Environment Settings.

### Header

- Nama environment aktif.
- Nama user dan role.
- Status environment.
- Tidak menampilkan label “sparepart” kecuali itu nama environment lama.

### Empty state

Environment baru menampilkan:

> Belum ada data barang. Tambahkan barang pertama untuk mulai mengelola inventori.

---

## 12. Migrasi Data Sparepart

1. Backup database SQL penuh.
2. Buat environment `Lithia Autoparts`.
3. Set `environment_id` seluruh user lama ke environment tersebut.
4. Backfill tabel barang, supplier, stok, transaksi, relasi supplier, foto, print job, dan audit log.
5. Validasi jumlah baris dan foreign key.
6. Jalankan test isolasi: user lama tetap melihat seluruh data lama; environment baru melihat nol data.
7. Deploy backend dengan read/write scope.
8. Deploy frontend.
9. Smoke test login, Barang, Stok Masuk, Stok Keluar, Foto, Supplier, Logs.
10. Simpan backup sampai verifikasi produksi selesai.

Tidak boleh ada data lama yang dipindahkan manual tanpa query terukur dan hasil sebelum/sesudah.

---

## 13. Acceptance Criteria

### Provisioning

- [ ] Environment baru dapat dibuat secara atomik.
- [ ] Administrator pertama otomatis terikat ke environment baru.
- [ ] Environment baru tidak melihat data `Lithia Autoparts`.
- [ ] Environment lama tetap memiliki semua data dan riwayat.
- [ ] Hanya Platform Owner dapat membuka UI/API provisioning dan membuat Administrator pertama.
- [ ] Request provisioning berulang dengan idempotency key sama tidak membuat environment atau admin duplikat.

### Isolasi

- [ ] Semua endpoint barang, supplier, stok, foto, print, dan logs menerapkan environment scope.
- [ ] User environment A tidak dapat membaca resource environment B meskipun mengetahui ID.
- [ ] User environment A tidak dapat mengubah atau menghapus resource environment B.
- [ ] File foto tidak dapat diakses lintas environment melalui manipulasi filename/path.
- [ ] Test otomatis mencakup positive dan negative cross-environment access.

### User management

- [ ] Admin dapat membuat staff/viewer dalam environment sendiri.
- [ ] Admin dapat disable user.
- [ ] Staff tidak dapat membuat admin atau user baru.
- [ ] Staff tidak dapat mengubah permission dirinya sendiri.
- [ ] Dashboard admin dapat menetapkan custom permission staff/viewer; backend menerapkan permission efektif.
- [ ] Invite aktivasi user dikirim melalui email tanpa password/token pada audit log.
- [ ] User disabled gagal login/request berikutnya.
- [ ] Platform Owner support access membutuhkan alasan dan durasi, dibatasi scope, lalu seluruh penggunaan dicatat audit.

### Copy data environment

- [ ] Wizard hanya tersedia bagi Platform Owner dan menawarkan Kosong, Template, atau toko sumber yang dimiliki.
- [ ] Default copy memilih pengaturan, kategori, supplier, barang, dan foto; inventori tetap 0 tanpa opt-in eksplisit.
- [ ] Copy default tidak membawa user, audit log, transaksi stok, atau print job.
- [ ] Copy membuat ID target baru, mapping foreign key benar, dan tidak memakai DB clone/raw ID sumber.
- [ ] Foto tersalin hanya ke path target scoped environment dan tidak dapat diakses environment sumber/lain.
- [ ] Job DB-backed menampilkan progress dan hasil; retry idempotent tidak menduplikasi data.
- [ ] Cancel sebelum commit tidak menandai copy selesai atau mengekspos data parsial.
- [ ] Audit menyimpan sumber, target, opsi, peminta, status, hasil, dan kegagalan.
- [ ] Test otomatis mencakup setiap opsi copy, mapping relasi/foto, default inventori 0, opt-in inventori, cancel, dan retry.

### Operasional

- [ ] Barang, supplier, transaksi, gallery foto, dan audit log bekerja pada environment baru.
- [ ] API mengembalikan `environment` pada `/api/auth/me`.
- [ ] UI memakai nama environment, bukan asumsi sparepart.
- [ ] Backup dan rollback migrasi diuji pada salinan database.
- [ ] Full backend dan frontend test pass.
- [ ] Smoke test production desktop dan mobile pass.

---

## 14. Non-functional Requirements

- **Security:** server-side tenant isolation; tidak bergantung pada filter frontend.
- **Availability:** perubahan schema tidak boleh menambah downtime panjang; migrasi dilakukan dengan backup.
- **Performance:** query list environment memakai index; target response API normal < 500 ms di kondisi normal.
- **Auditability:** perubahan role, user, environment, dan data bisnis dapat ditelusuri.
- **Compatibility:** token lama dan data lama ditangani sesuai migrasi; token lama tidak otomatis mendapat akses environment baru.
- **Accessibility:** form user/environment memiliki label, error jelas, dan dapat dipakai keyboard.
- **Privacy:** tidak ada credential/token/password di log, audit summary, response, atau laporan.

---

## 15. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Ada endpoint terlewat dari scope | Data bocor lintas environment | Inventory semua router + negative isolation tests + code review |
| Backfill salah environment | Data bisnis tercampur | Backup, dry-run, count/hash sebelum-sesudah |
| File foto tetap global | Foto dapat ditebak/diakses lintas tenant | Path ber-prefix environment + authorization/static policy |
| Admin dapat membuat tenant tanpa kontrol | Environment liar dan biaya naik | MVP batasi provisioning ke Platform Owner |
| Copy memakai raw ID atau DB clone | Relasi lintas toko, data bocor, retry duplikat | Job snapshot dengan ID baru, mapping FK, idempotency, dan audit |
| Copy membawa inventori/transaksi tanpa sengaja | Saldo awal dan riwayat salah | Default inventori 0; transaksi tidak pernah default copy; opt-in eksplisit untuk inventori |
| Job copy terputus | Data parsial/duplikat | Job DB-backed dengan status, checkpoint, retry idempotent, dan cancel sebelum commit |
| User lama tidak kompatibel | Login atau akses terputus | Migration compatibility, smoke test, token policy |
| Query tanpa index | POS lambat saat tenant bertambah | Composite indexes dan query profiling |
| Hak admin terlalu luas | Penghapusan/ubah data berisiko | Confirmation, audit, permission separation |
| Backup restore mencampur tenant | Kerusakan data | Restore drill dan environment-aware backup |

---

## 16. Tahapan Implementasi yang Disarankan

### Fase 0 — Audit kontrak

- Inventaris model, router, file storage, audit, print, integration, dan frontend resource.
- Daftar semua query yang menyentuh data bisnis.
- Tetapkan istilah UI dan model ownership.

### Fase 1 — Foundation backend

- Model environment dan user scope.
- Migration idempotent + backfill `Lithia Autoparts`.
- Auth `/me` + permission resolver.
- Negative isolation tests.

### Fase 2 — Scope seluruh domain

- Barang, supplier, stok, transaksi, gallery, logs, print, integration.
- File path isolation.
- Audit environment.

### Fase 3 — User management

- CRUD user scoped.
- Role/permission.
- Disable/reset password.

### Fase 4 — Frontend

- Environment header/settings.
- User management.
- Permission-aware menu/action.
- Netralisasi label sparepart.

### Fase 5 — Production rollout

- Backup.
- Migration dry-run.
- Deploy backend/frontend.
- Smoke test.
- Monitor error and audit logs.

### Fase 6 — Copy-data wizard

- Job `environment_copy_jobs` DB-backed pada single-node FastAPI.
- Snapshot source, ID mapping/FK remap, target photo storage, progress/cancel/retry.
- Test opsi default, opt-in inventori, relasi/foto, cancel, retry, dan audit.

---

## 17. Keputusan Produk

1. **Istilah UI — belum dikonfirmasi:** gunakan label sementara `Toko`; kode/database memakai `environment`. Product Owner perlu mengonfirmasi label final.
2. **Pembuat environment:** hanya Platform Owner.
3. **Keanggotaan user:** satu user hanya berada pada satu environment untuk MVP.
4. **Administrator pertama:** hanya Platform Owner membuatnya saat provisioning; tidak ada self-signup publik.
5. **Invite user:** email invitation sejak MVP.
6. **Permission:** Administrator mengatur custom permission dari dashboard; role `admin`, `staff`, `viewer` tetap baseline.
7. **Data environment baru:** wizard mendukung Kosong, Template, atau salin dari toko sumber yang dimiliki; default aman tercantum pada §8.3.
8. **Environment sparepart lama:** `Lithia Autoparts`.
9. **UI Platform Owner:** wajib ada, untuk provisioning, status toko, dan support access.
10. **Support access Platform Owner:** diizinkan hanya untuk kebutuhan support, reason-bound, time-bound, scoped, dan diaudit penuh.

---

## 18. Approval

| Peran | Nama | Status | Tanggal |
|---|---|---|---|
| Product Owner | Indra | Menunggu persetujuan | 2026-10-01 |
| Developer Lead | — | Menunggu | — |
| Stakeholder | — | Menunggu | — |
