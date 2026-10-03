from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, get_current_user_env_id
from app.database import get_db
from app.models.barang import Barang
from app.models.supplier import Supplier
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.schemas.stok import StokMasukRequest, StokKeluarRequest, TransaksiOut, TransaksiListResponse
from app.services.stock_in import record_stock_in

router = APIRouter(prefix="/api/stok", tags=["stok"])


@router.post("/masuk")
def stok_masuk(req: StokMasukRequest, db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    barang = db.query(Barang).filter(Barang.id == req.barang_id, Barang.environment_id == env_id).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    if req.supplier_id is not None and not db.query(Supplier).filter(Supplier.id == req.supplier_id, Supplier.environment_id == env_id).first():
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    barang, tx = record_stock_in(db, barang_id=req.barang_id, jumlah=req.jumlah, harga_satuan=req.harga_satuan,
        keterangan=req.keterangan, user_id=user.id, supplier_id=req.supplier_id, environment_id=env_id)
    db.commit()
    return {"ok": True, "stok_baru": barang.stok.jumlah, "transaksi_id": tx.id}


@router.post("/keluar")
def stok_keluar(req: StokKeluarRequest, db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    barang = db.query(Barang).filter(Barang.id == req.barang_id, Barang.environment_id == env_id).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == req.barang_id).first()
    if not stok or stok.jumlah < req.jumlah:
        raise HTTPException(status_code=400, detail="Stok tidak mencukupi")
    stok.jumlah -= req.jumlah
    db.add(TransaksiStok(environment_id=env_id, barang_id=req.barang_id, jenis="keluar", jumlah=req.jumlah,
        harga_satuan=req.harga_satuan, total_harga=(req.harga_satuan or 0) * req.jumlah if req.harga_satuan else None,
        keterangan=req.keterangan, user_id=user.id))
    db.commit()
    return {"ok": True, "stok_baru": stok.jumlah}


@router.get("/riwayat", response_model=TransaksiListResponse)
def riwayat_stok(tanggal_mulai: str = Query(None), tanggal_akhir: str = Query(None), jenis: str = Query(None), tipe: str = Query(None), page: int = Query(1, ge=1), skip: int | None = Query(None, ge=0), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    q = db.query(TransaksiStok).filter(TransaksiStok.environment_id == env_id).options(joinedload(TransaksiStok.barang).joinedload(Barang.supplier), joinedload(TransaksiStok.supplier), joinedload(TransaksiStok.user))
    if tanggal_mulai: q = q.filter(TransaksiStok.created_at >= f"{tanggal_mulai} 00:00:00")
    if tanggal_akhir: q = q.filter(TransaksiStok.created_at <= f"{tanggal_akhir} 23:59:59")
    if jenis or tipe: q = q.filter(TransaksiStok.jenis == (jenis or tipe))
    total = q.count(); offset = skip if skip is not None else (page - 1) * limit
    data = q.order_by(TransaksiStok.created_at.desc(), TransaksiStok.id.desc()).offset(offset).limit(limit).all()
    return TransaksiListResponse(total=total, page=page, limit=limit, data=[TransaksiOut(id=t.id, tanggal=str(t.created_at)[:19] if t.created_at else "", created_at=str(t.created_at)[:19] if t.created_at else "", sku=(t.barang.sku or "") if t.barang else "", nama_barang=t.barang.nama if t.barang else "-", supplier=t.supplier.nama if t.supplier else (t.barang.supplier.nama if t.barang and t.barang.supplier else None), supplier_id=t.supplier_id, supplier_nama=t.supplier.nama if t.supplier else None, jenis=t.jenis, jumlah=t.jumlah, harga_satuan=t.harga_satuan, total_harga=t.total_harga, keterangan=t.keterangan, user=t.user.nama if t.user else None) for t in data])
