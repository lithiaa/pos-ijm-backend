from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.schemas.stok import StokMasukRequest, StokKeluarRequest, TransaksiOut, TransaksiListResponse
from app.auth import get_current_user

router = APIRouter(prefix="/api/stok", tags=["stok"])


@router.post("/masuk")
def stok_masuk(req: StokMasukRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    barang = db.query(Barang).filter(Barang.id == req.barang_id).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")

    stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == req.barang_id).first()
    if not stok:
        stok = StokSaatIni(barang_id=req.barang_id, jumlah=0)
        db.add(stok)
    stok.jumlah += req.jumlah

    tx = TransaksiStok(
        barang_id=req.barang_id,
        jenis="masuk",
        jumlah=req.jumlah,
        harga_satuan=req.harga_satuan,
        total_harga=(req.harga_satuan or 0) * req.jumlah if req.harga_satuan else None,
        keterangan=req.keterangan,
        user_id=user.id,
    )
    db.add(tx)
    db.commit()
    return {"ok": True, "stok_baru": stok.jumlah, "transaksi_id": tx.id}


@router.post("/keluar")
def stok_keluar(req: StokKeluarRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    barang = db.query(Barang).filter(Barang.id == req.barang_id).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")

    stok = db.query(StokSaatIni).filter(StokSaatIni.barang_id == req.barang_id).first()
    if not stok or stok.jumlah < req.jumlah:
        raise HTTPException(status_code=400, detail="Stok tidak mencukupi")

    stok.jumlah -= req.jumlah

    tx = TransaksiStok(
        barang_id=req.barang_id,
        jenis="keluar",
        jumlah=req.jumlah,
        keterangan=req.keterangan,
        user_id=user.id,
    )
    db.add(tx)
    db.commit()
    return {"ok": True, "stok_baru": stok.jumlah, "transaksi_id": tx.id}


@router.get("/riwayat")
def riwayat_stok(
    tanggal_mulai: str = Query(None),
    tanggal_akhir: str = Query(None),
    jenis: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(TransaksiStok).options(
        joinedload(TransaksiStok.barang), joinedload(TransaksiStok.user)
    )

    if tanggal_mulai:
        q = q.filter(TransaksiStok.created_at >= f"{tanggal_mulai} 00:00:00")
    if tanggal_akhir:
        q = q.filter(TransaksiStok.created_at <= f"{tanggal_akhir} 23:59:59")
    if jenis:
        q = q.filter(TransaksiStok.jenis == jenis)

    total = q.count()
    data = q.order_by(TransaksiStok.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    result = []
    for t in data:
        result.append(TransaksiOut(
            id=t.id,
            tanggal=str(t.created_at)[:19] if t.created_at else "",
            nama_barang=t.barang.nama if t.barang else "-",
            jenis=t.jenis,
            jumlah=t.jumlah,
            harga_satuan=t.harga_satuan,
            total_harga=t.total_harga,
            keterangan=t.keterangan,
            user=t.user.nama if t.user else None,
        ))

    return TransaksiListResponse(total=total, page=page, limit=limit, data=result)
