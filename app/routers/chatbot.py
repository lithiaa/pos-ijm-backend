from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import re
import os
import uuid
import base64
import requests

from app.database import get_db
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.models.kategori import Kategori
from app.models.supplier import Supplier
from app.services.harga import harga_decode, harga_encode
from app.routers.upload import STORAGE_DIR as FOTO_STORAGE_DIR

router = APIRouter(
    prefix="/api/chatbot",
    tags=["chatbot"],
)

# Used by chatbot responses that link to external URLs
API_URL = "https://api.ijm.lithiaproject.site"


class ChatbotRequest(BaseModel):
    command: str


def get_current_user_placeholder():
    pass


@router.post("/")
def process_command(req: ChatbotRequest, db: Session = Depends(get_db), user=Depends(get_current_user_placeholder)):
    cmd = req.command.strip()
    response = "Perintah tidak dikenali."

    # Parse action — words before first key=value
    match = re.match(r"(\w[\w\s]*?)\s+(?=\w+=|$)", cmd + " ")
    if not match:
        return {"response": response}

    action = match.group(1).strip()
    after = cmd[len(action):].strip()

    params = {}
    if after:
        try:
            # Parse key=value pairs
            pairs = re.findall(r"(\w+)=([\w\s/:.,?&=#%+-]+?)(?=\s+\w+=|$)", after + " ")
            params = {k: v.strip() for k, v in pairs}

            if "foto_base64" in after:
                # Handle potentially long base64 string separately
                match_b64 = re.search(r"foto_base64=([a-zA-Z0-9+/=]+)", after)
                if match_b64:
                    params["foto_base64"] = match_b64.group(1)
        except Exception as e:
            return {"response": f"Error parsing parameter: {e}"}

    # =============== CREATE ===============
    if action == "tambah barang":
        try:
            nama = params.get("nama")
            if not nama:
                return {"response": "Gagal: Parameter 'nama' wajib diisi."}

            kategori = None
            if "kategori" in params:
                kategori = db.query(Kategori).filter(Kategori.nama == params["kategori"]).first()
                if not kategori:
                    kategori = Kategori(nama=params["kategori"])
                    db.add(kategori)
                    db.flush()

            supplier = None
            if "supplier" in params:
                supplier = db.query(Supplier).filter(Supplier.nama == params["supplier"]).first()
                if not supplier:
                    supplier = Supplier(nama=params["supplier"])
                    db.add(supplier)
                    db.flush()

            # Handle SANGUOERIP price code
            harga_jual_str = params.get("harga_jual", "0")
            if not harga_jual_str.isdigit():
                harga_jual = harga_decode(harga_jual_str)
            else:
                harga_jual = float(harga_jual_str)

            harga_modal_str = params.get("harga_modal", "0")
            if not harga_modal_str.isdigit():
                harga_modal = harga_decode(harga_modal_str)
            else:
                harga_modal = float(harga_modal_str)

            new_barang = Barang(
                nama=nama,
                merek=params.get("merek"),
                kategori_id=kategori.id if kategori else None,
                supplier_id=supplier.id if supplier else None,
                harga_modal=int(harga_modal),
                harga_jual=int(harga_jual),
                stok_minimum=int(params.get("stok_minimum", 5)),
                satuan=params.get("satuan", "pcs"),
                foto=params.get("foto"),
            )
            db.add(new_barang)
            db.commit()
            db.refresh(new_barang)

            # Initial stock
            if "stok" in params:
                stok_awal = int(params["stok"])
                if stok_awal > 0:
                    stok = StokSaatIni(barang_id=new_barang.id, jumlah=stok_awal)
                    db.add(stok)
                    db.commit()

            response = f"✅ Berhasil tambah barang: {new_barang.nama} (ID: {new_barang.id})"
        except Exception as e:
            db.rollback()
            response = f"❌ Gagal: {e}"

    # =============== LIST / SEARCH ===============
    elif action in ("cari barang", "lihat semua barang", "list barang"):
        q = db.query(Barang)
        if "nama" in params:
            q = q.filter(Barang.nama.ilike(f"%{params['nama']}%"))
        barangs = q.all()
        if not barangs:
            response = "Barang tidak ditemukan."
        else:
            lines = [f"Ditemukan {len(barangs)} barang:"]
            for b in barangs:
                stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == b.id).first()
                jml = stok.jumlah if stok else 0
                foto_info = "Ada foto" if b.foto else "Tanpa foto"
                lines.append(f"• ID:{b.id} {b.nama} | Rp{b.harga_jual:,} | Stok:{jml} {b.satuan} | {foto_info}")
            response = "\n".join(lines)

    # =============== UPLOAD FOTO ===============
    elif action == "upload foto":
        if "id" not in params:
            return {"response": "Gagal: ID barang diperlukan."}

        try:
            barang_id = int(params["id"])
            barang = db.query(Barang).filter(Barang.id == barang_id).first()
            if not barang:
                return {"response": f"Barang ID {barang_id} tidak ditemukan."}

            foto_filename = f"{uuid.uuid4()}.jpg"
            os.makedirs(FOTO_STORAGE_DIR, exist_ok=True)

            if "foto_base64" in params:
                img_data = base64.b64decode(params["foto_base64"])
                with open(os.path.join(FOTO_STORAGE_DIR, foto_filename), "wb") as f:
                    f.write(img_data)
            elif "url" in params:
                img_response = requests.get(params["url"], stream=True)
                img_response.raise_for_status()
                with open(os.path.join(FOTO_STORAGE_DIR, foto_filename), "wb") as f:
                    for chunk in img_response.iter_content(chunk_size=8192):
                        f.write(chunk)
            else:
                return {"response": "Gagal: 'foto_base64' atau 'url' parameter harus disediakan."}

            barang.foto = foto_filename
            db.commit()

            foto_url = f"/storage/foto-barang/{foto_filename}"
            response = f"✅ Berhasil upload foto untuk {barang.nama}. URL: {foto_url}"

        except ValueError:
            return {"response": "Gagal: ID tidak valid."}
        except Exception as e:
            db.rollback()
            return {"response": f"❌ Gagal upload foto: {e}"}



    # =============== FOTO BARANG ===============
    elif action == "foto barang":
        if "id" not in params:
            return {"response": "Gagal: ID barang diperlukan."}
        try:
            barang_id = int(params["id"])
            barang = db.query(Barang).filter(Barang.id == barang_id).first()
            if not barang:
                return {"response": f"Barang ID {barang_id} tidak ditemukan."}
            if not barang.foto:
                return {"response": f"Barang ID {barang_id} ({barang.nama}) tidak memiliki foto."}

            foto_url = f"/storage/foto-barang/{barang.foto}"
            response = f"Foto untuk {barang.nama} (ID: {barang.id}): {foto_url}"
        except ValueError:
            return {"response": "Gagal: ID tidak valid."}


    # =============== UPDATE ===============
    elif action == "ubah barang":
        if "id" not in params:
            return {"response": "Gagal: ID barang diperlukan."}
        try:
            barang_id = int(params["id"])
        except ValueError:
            return {"response": "Gagal: ID tidak valid."}

        barang = db.query(Barang).filter(Barang.id == barang_id).first()
        if not barang:
            return {"response": f"Barang ID {barang_id} tidak ditemukan."}

        try:
            for key, val in params.items():
                if key == "id":
                    continue
                if key == "harga_jual" or key == "harga_modal":
                    val_str = str(val)
                    val = harga_decode(val_str) if not val_str.isdigit() else int(val_str)
                if key == "kategori":
                    kat = db.query(Kategori).filter(Kategori.nama == val).first()
                    if not kat:
                        kat = Kategori(nama=val)
                        db.add(kat)
                        db.flush()
                    setattr(barang, "kategori_id", kat.id)
                elif key == "supplier":
                    sup = db.query(Supplier).filter(Supplier.nama == val).first()
                    if not sup:
                        sup = Supplier(nama=val)
                        db.add(sup)
                        db.flush()
                    setattr(barang, "supplier_id", sup.id)
                elif key == "foto":
                    setattr(barang, key, val)
                elif hasattr(barang, key):
                    setattr(barang, key, val)
            db.commit()
            response = f"✅ Berhasil ubah barang ID {barang_id}."
        except Exception as e:
            db.rollback()
            response = f"❌ Gagal: {e}"

    # =============== DELETE ===============
    elif action == "hapus barang":
        if "id" not in params:
            return {"response": "Gagal: ID barang diperlukan."}
        try:
            barang_id = int(params["id"])
        except ValueError:
            return {"response": "Gagal: ID tidak valid."}

        barang = db.query(Barang).filter(Barang.id == barang_id).first()
        if not barang:
            return {"response": f"Barang ID {barang_id} tidak ditemukan."}

        try:
            db.query(StokSaatIni).filter(StokSaatIni.barang_id == barang_id).delete()
            db.delete(barang)
            db.commit()
            response = f"✅ Berhasil hapus barang ID {barang_id}."
        except Exception as e:
            db.rollback()
            response = f"❌ Gagal: {e}"

    # =============== CEK STOK ===============
    elif action == "cek stok":
        if "id" in params:
            barang_id = int(params["id"])
            stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == barang_id).first()
            barang = db.query(Barang).filter(Barang.id == barang_id).first()
            if barang and stok:
                response = f"Stok {barang.nama}: {stok.jumlah} {barang.satuan}"
            elif barang:
                response = f"Stok {barang.nama}: 0 {barang.satuan}"
            else:
                response = f"Barang ID {barang_id} tidak ditemukan."
        else:
            response = "Gunakan: cek stok id=1"

    elif action == "stok menipis":
        barangs = db.query(Barang).join(StokSaatIni).filter(StokSaatIni.jumlah <= Barang.stok_minimum).all()
        if not barangs:
            response = "Tidak ada barang dengan stok menipis."
        else:
            lines = ["Barang stok menipis:"]
            for b in barangs:
                stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == b.id).first()
                lines.append(f"• {b.nama} (ID:{b.id}) Stok:{stok.jumlah} Min:{b.stok_minimum}")
            response = "\n".join(lines)

    # =============== CEK HARGA ===============
    elif action == "harga barang":
        if "id" in params:
            barang_id = int(params["id"])
            barang = db.query(Barang).filter(Barang.id == barang_id).first()
            if barang:
                kode = harga_encode(barang.harga_jual)
                response = f"Harga {barang.nama}: Rp{barang.harga_jual:,} (Kode: {kode})"
            else:
                response = f"Barang ID {barang_id} tidak ditemukan."
        else:
            response = "Gunakan: harga barang id=1"

    # =============== CETAK LABEL ===============
    elif action == "cetak label":
        if "id" not in params:
            return {"response": "Gunakan: cetak label id=1 [qty=2] [ukuran=80x40]"}

        try:
            barang_id = int(params["id"])
            qty = int(params.get("qty", 1))
            size = params.get("ukuran")

            barang = db.query(Barang).filter(Barang.id == barang_id).first()
            if not barang:
                return {"response": f"Barang ID {barang_id} tidak ditemukan."}

            from app.models.printjob import PrintJob
            job = PrintJob(barang_id=barang_id, qty=qty, status="pending")
            db.add(job)
            db.commit()
            response = f"✅ Cetak {qty} label untuk {barang.nama} (ID:{barang_id}) masuk antrian. Printer akan mencetak otomatis."
        except ValueError:
            response = "ID atau Qty tidak valid."
        except Exception as e:
            response = f"❌ Gagal: {e}"

    # =============== SETELAN LABEL ===============
    elif action == "setelan label":
        from app.routers.label import load_label_config, save_label_config, LABEL_SIZES

        if "ukuran" in params:
            new_size = params["ukuran"]
            size_ids = [s['id'] for s in LABEL_SIZES]
            if new_size not in size_ids:
                return {"response": f"Ukuran tidak valid. Pilihan: {', '.join(size_ids)}"}

            config = load_label_config()
            config['default_size'] = new_size
            save_label_config(config)
            response = f"✅ Ukuran label default diubah menjadi: {new_size}"
        else:
            config = load_label_config()
            current_size = config.get('default_size', 'a4_2col')
            response = f"Ukuran label default saat ini: {current_size}. Untuk mengubah, gunakan: setelan label ukuran=80x40"

    # =============== STOK MASUK + CETAK OTOMATIS ===============
    elif action == "stok masuk":
        if "id" not in params or "jumlah" not in params:
            response = "Gunakan: stok masuk id=2 jumlah=20 [harga=50000 keterangan=restock ukuran=80x40]"
        else:
            try:
                barang_id = int(params["id"])
                jumlah = int(params["jumlah"])
                harga = int(params.get("harga", 0))
                keterangan = params.get("keterangan", "")

                from app.models.transaksi import StokSaatIni, TransaksiStok as Ts
                db_barang = db.query(Barang).filter(Barang.id == barang_id).first()
                if not db_barang:
                    response = f"Barang ID {barang_id} tidak ditemukan."
                else:
                    # Update/set stok
                    stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == barang_id).first()
                    if not stok:
                        stok = StokSaatIni(barang_id=barang_id, jumlah=0)
                        db.add(stok)
                    stok.jumlah = (stok.jumlah or 0) + jumlah

                    # Record transaksi
                    total = harga * jumlah if harga else 0
                    ts = Ts(
                        barang_id=barang_id, jenis="masuk", jumlah=jumlah,
                        harga_satuan=harga or None, total_harga=total or None,
                        keterangan=keterangan or None,
                    )
                    db.add(ts)
                    db.commit()

                    from app.routers.label import load_label_config
                    config = load_label_config()
                    # Use size from params, or fallback to default config
                    label_size = params.get('ukuran') or config.get('default_size', 'a4_2col')  # noqa: F841 (used by future direct-print link)

                    response = (
                        f"✅ Stok {db_barang.nama} bertambah {jumlah}. "
                        f"Stok sekarang: {stok.jumlah}"
                    )
                    if params.get("cetak") == "1":
                        from app.models.printjob import PrintJob
                        job = PrintJob(barang_id=barang_id, qty=jumlah, status="pending")
                        db.add(job)
                        db.commit()
                        response += " Label akan dicetak otomatis."
            except Exception as e:
                db.rollback()
                response = f"❌ Gagal: {e}"

    return {"response": response}
