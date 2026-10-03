import base64
import binascii
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import AuthPrincipal, get_current_principal, get_current_user_env_id
from app.database import get_db
from app.models.barang import Barang
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.routers.upload import MAX_PHOTO_BYTES, STORAGE_DIR as FOTO_STORAGE_DIR
from app.services.harga import harga_decode, harga_encode
from app.services.print_client import print_job_async
from app.services.supplier_code import assign_supplier_code

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


class ChatbotRequest(BaseModel):
    command: str


def _audit_mutation(
    request: Request, *, action: str, resource: str, resource_id: object
) -> None:
    request.state.audit_skip = False
    request.state.audit_override = {
        "action": action,
        "resource": resource,
        "resource_id": str(resource_id),
        "summary": {"request": request.state.audit_params},
    }


def _required_permission(action: str) -> str | None:
    return {
        "tambah barang": "barang.write",
        "cari barang": "barang.read",
        "lihat semua barang": "barang.read",
        "list barang": "barang.read",
        "upload foto": "foto.write",
        "foto barang": "foto.read",
        "ubah barang": "barang.write",
        "hapus barang": "barang.delete",
        "cek stok": "stok.read",
        "stok menipis": "stok.read",
        "harga barang": "barang.read",
        "cetak label": "barang.read",
        "setelan label": "environment.settings",
        "stok masuk": "stok.write",
    }.get(action)


def _barang(db: Session, barang_id: int, env_id: int) -> Barang:
    barang = db.query(Barang).filter(
        Barang.id == barang_id, Barang.environment_id == env_id
    ).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    return barang


def _supplier_by_name(db: Session, name: str, env_id: int) -> Supplier | None:
    return db.query(Supplier).filter(
        Supplier.nama == name, Supplier.environment_id == env_id
    ).first()


def _parse_id(params: dict[str, str]) -> int:
    try:
        return int(params["id"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=422, detail="Valid barang ID required")


def _save_base64_photo(value: str, env_id: int) -> str:
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="Invalid photo data")
    if not data.startswith(b"\xff\xd8\xff") or len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=422, detail="Photo must be JPEG and at most 5MB")
    filename = f"{uuid.uuid4()}.jpg"
    directory = os.path.join(FOTO_STORAGE_DIR, str(env_id))
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, filename), "wb") as output:
        output.write(data)
    return filename


@router.post("/")
def process_command(
    req: ChatbotRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
    env_id: int = Depends(get_current_user_env_id),
):
    request.state.audit_skip = True
    cmd = req.command.strip()
    match = re.match(r"(\w[\w\s]*?)\s+(?=\w+=|$)", cmd + " ")
    if not match:
        return {"response": "Perintah tidak dikenali."}

    action = match.group(1).strip()
    required = _required_permission(action)
    if required and not principal.has_permission(required):
        raise HTTPException(status_code=403, detail=f"Permission '{required}' required")

    after = cmd[len(action):].strip()
    pairs = re.findall(r"(\w+)=([\w\s/:.,?&=#%+-]+?)(?=\s+\w+=|$)", after + " ")
    params = {key: value.strip() for key, value in pairs}
    if "foto_base64" in after:
        match_b64 = re.search(r"foto_base64=([a-zA-Z0-9+/=]+)", after)
        if match_b64:
            params["foto_base64"] = match_b64.group(1)
    request.state.audit_params = params

    if action == "tambah barang":
        nama = params.get("nama")
        if not nama:
            return {"response": "Gagal: Parameter 'nama' wajib diisi."}
        supplier = None
        if "supplier" in params:
            supplier = _supplier_by_name(db, params["supplier"], env_id)
            if not supplier:
                supplier = Supplier(environment_id=env_id, nama=params["supplier"])
                db.add(supplier)
                assign_supplier_code(db, supplier, env_id)
        try:
            harga_jual_text = params.get("harga_jual", "0")
            harga_jual = int(harga_jual_text) if harga_jual_text.isdigit() else harga_decode(harga_jual_text)
            harga_modal_text = params.get("harga_modal", "0")
            harga_modal = int(harga_modal_text) if harga_modal_text.isdigit() else harga_decode(harga_modal_text)
            new_barang = Barang(
                environment_id=env_id,
                nama=nama,
                merek=params.get("merek"),
                supplier_id=supplier.id if supplier else None,
                harga_modal=harga_modal,
                harga_jual=harga_jual,
                stok_minimum=int(params.get("stok_minimum", 5)),
                satuan=params.get("satuan", "pcs"),
            )
            db.add(new_barang)
            db.flush()
            stock = StokSaatIni(
                environment_id=env_id,
                barang_id=new_barang.id,
                jumlah=max(0, int(params.get("stok", 0))),
            )
            db.add(stock)
            db.commit()
            _audit_mutation(request, action="CREATE", resource="barang", resource_id=new_barang.id)
            return {"response": f"✅ Berhasil tambah barang: {new_barang.nama} (ID: {new_barang.id})"}
        except (TypeError, ValueError):
            db.rollback()
            raise HTTPException(status_code=422, detail="Invalid numeric value")
        except Exception:
            db.rollback()
            raise

    if action in ("cari barang", "lihat semua barang", "list barang"):
        query = db.query(Barang).filter(Barang.environment_id == env_id)
        if "nama" in params:
            query = query.filter(Barang.nama.ilike(f"%{params['nama']}%"))
        barang_list = query.all()
        if not barang_list:
            return {"response": "Barang tidak ditemukan."}
        lines = [f"Ditemukan {len(barang_list)} barang:"]
        for item in barang_list:
            stock = db.query(StokSaatIni).filter(
                StokSaatIni.barang_id == item.id,
                StokSaatIni.environment_id == env_id,
            ).first()
            quantity = stock.jumlah if stock else 0
            photo = "Ada foto" if item.foto else "Tanpa foto"
            lines.append(
                f"• ID:{item.id} {item.nama} | Rp{item.harga_jual:,} | "
                f"Stok:{quantity} {item.satuan} | {photo}"
            )
        return {"response": "\n".join(lines)}

    if action == "upload foto":
        barang = _barang(db, _parse_id(params), env_id)
        if "foto_base64" not in params:
            raise HTTPException(status_code=422, detail="foto_base64 required")
        filename = _save_base64_photo(params["foto_base64"], env_id)
        barang.foto = filename
        db.commit()
        _audit_mutation(request, action="UPDATE", resource="barang", resource_id=barang.id)
        return {
            "response": f"✅ Berhasil upload foto untuk {barang.nama}. URL: "
            f"/api/foto-barang/{env_id}/{filename}"
        }

    if action == "foto barang":
        barang = _barang(db, _parse_id(params), env_id)
        if not barang.foto:
            return {"response": f"Barang ID {barang.id} ({barang.nama}) tidak memiliki foto."}
        return {
            "response": f"Foto untuk {barang.nama} (ID: {barang.id}): "
            f"/api/foto-barang/{env_id}/{barang.foto}"
        }

    if action == "ubah barang":
        barang_id = _parse_id(params)
        barang = _barang(db, barang_id, env_id)
        allowed = {"nama", "merek", "harga_jual", "harga_modal", "stok_minimum", "satuan", "supplier"}
        changed = False
        try:
            for key, raw_value in params.items():
                if key not in allowed:
                    continue
                value: object = raw_value
                if key in {"harga_jual", "harga_modal"}:
                    value = int(raw_value) if raw_value.isdigit() else harga_decode(raw_value)
                elif key == "stok_minimum":
                    value = int(raw_value)
                if key == "supplier":
                    supplier = _supplier_by_name(db, raw_value, env_id)
                    if not supplier:
                        supplier = Supplier(environment_id=env_id, nama=raw_value)
                        db.add(supplier)
                        assign_supplier_code(db, supplier, env_id)
                    value = supplier.id
                    key = "supplier_id"
                if getattr(barang, key) != value:
                    setattr(barang, key, value)
                    changed = True
            if changed:
                db.commit()
                _audit_mutation(request, action="UPDATE", resource="barang", resource_id=barang_id)
            return {"response": f"✅ Berhasil ubah barang ID {barang_id}."}
        except (TypeError, ValueError):
            db.rollback()
            raise HTTPException(status_code=422, detail="Invalid value")

    if action == "hapus barang":
        barang_id = _parse_id(params)
        barang = _barang(db, barang_id, env_id)
        db.query(TransaksiStok).filter(
            TransaksiStok.barang_id == barang_id,
            TransaksiStok.environment_id == env_id,
        ).delete()
        db.query(StokSaatIni).filter(
            StokSaatIni.barang_id == barang_id,
            StokSaatIni.environment_id == env_id,
        ).delete()
        db.delete(barang)
        db.commit()
        _audit_mutation(request, action="DELETE", resource="barang", resource_id=barang_id)
        return {"response": f"✅ Berhasil hapus barang ID {barang_id}."}

    if action == "cek stok":
        barang = _barang(db, _parse_id(params), env_id)
        stock = db.query(StokSaatIni).filter(
            StokSaatIni.barang_id == barang.id,
            StokSaatIni.environment_id == env_id,
        ).first()
        return {"response": f"Stok {barang.nama}: {stock.jumlah if stock else 0} {barang.satuan}"}

    if action == "stok menipis":
        items = db.query(Barang).join(
            StokSaatIni,
            (StokSaatIni.barang_id == Barang.id)
            & (StokSaatIni.environment_id == env_id),
        ).filter(
            Barang.environment_id == env_id,
            StokSaatIni.jumlah <= Barang.stok_minimum,
        ).all()
        if not items:
            return {"response": "Tidak ada barang dengan stok menipis."}
        lines = ["Barang stok menipis:"]
        for item in items:
            stock = db.query(StokSaatIni).filter(
                StokSaatIni.barang_id == item.id,
                StokSaatIni.environment_id == env_id,
            ).one()
            lines.append(f"• {item.nama} (ID:{item.id}) Stok:{stock.jumlah} Min:{item.stok_minimum}")
        return {"response": "\n".join(lines)}

    if action == "harga barang":
        barang = _barang(db, _parse_id(params), env_id)
        return {"response": f"Harga {barang.nama}: Rp{barang.harga_jual:,} (Kode: {harga_encode(barang.harga_jual)})"}

    if action == "cetak label":
        barang = _barang(db, _parse_id(params), env_id)
        try:
            qty = int(params.get("qty", 1))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid quantity")
        if not 1 <= qty <= 500:
            raise HTTPException(status_code=422, detail="Quantity must be 1-500")
        job = PrintJob(environment_id=env_id, barang_id=barang.id, qty=qty, status="pending")
        db.add(job)
        db.commit()
        _audit_mutation(request, action="CREATE", resource="print-jobs", resource_id=job.id)
        try:
            print_job_async(
                nama=barang.nama,
                harga_jual=int(barang.harga_jual or 0),
                harga_beli=int(barang.harga_modal or 0),
                sku=barang.sku or "",
                stok=0,
                satuan=barang.satuan or "pcs",
                qty=qty,
            )
        except Exception:
            pass
        return {"response": f"✅ Cetak {qty} label untuk {barang.nama} (ID:{barang.id}) masuk antrian. Printer akan mencetak otomatis."}

    if action == "setelan label":
        from app.routers.label import LABEL_SIZES, load_label_config, save_label_config

        config = load_label_config(db, env_id)
        if "ukuran" not in params:
            current = config.get("default_size", "a4_2col")
            return {"response": f"Ukuran label default saat ini: {current}. Untuk mengubah, gunakan: setelan label ukuran=80x40"}
        size = params["ukuran"]
        valid = [item["id"] for item in LABEL_SIZES]
        if size not in valid:
            return {"response": f"Ukuran tidak valid. Pilihan: {', '.join(valid)}"}
        if config.get("default_size") != size:
            config["default_size"] = size
            save_label_config(db, env_id, config)
            _audit_mutation(request, action="UPDATE", resource="label", resource_id="config")
        return {"response": f"✅ Ukuran label default diubah menjadi: {size}"}

    if action == "stok masuk":
        barang = _barang(db, _parse_id(params), env_id)
        try:
            quantity = int(params["jumlah"])
            price = int(params.get("harga", 0))
        except (KeyError, ValueError):
            raise HTTPException(status_code=422, detail="Valid quantity required")
        stock = db.query(StokSaatIni).filter(
            StokSaatIni.barang_id == barang.id,
            StokSaatIni.environment_id == env_id,
        ).first()
        if not stock:
            stock = StokSaatIni(environment_id=env_id, barang_id=barang.id, jumlah=0)
            db.add(stock)
        stock.jumlah = (stock.jumlah or 0) + quantity
        transaction = TransaksiStok(
            environment_id=env_id,
            barang_id=barang.id,
            jenis="masuk",
            jumlah=quantity,
            harga_satuan=price or None,
            total_harga=price * quantity or None,
            keterangan=params.get("keterangan") or None,
            user_id=principal.id,
        )
        db.add(transaction)
        db.commit()
        _audit_mutation(request, action="CREATE", resource="stok", resource_id=transaction.id)
        return {"response": f"✅ Stok {barang.nama} bertambah {quantity}. Stok sekarang: {stock.jumlah}"}

    return {"response": "Perintah tidak dikenali."}
