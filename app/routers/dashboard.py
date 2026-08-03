from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.schemas.stok import DashboardResponse, TransaksiOut
from app.auth import get_current_user
from datetime import date

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db), user=Depends(get_current_user)):
    today = str(date.today())

    total_barang = db.query(func.count(Barang.id)).scalar() or 0
    stok_menipis = 0
    barang_menipis_list = []

    all_barang = db.query(Barang).options(joinedload(Barang.stok)).all()
    for b in all_barang:
        stok = b.stok.jumlah if b.stok else 0
        if stok <= b.stok_minimum:
            stok_menipis += 1
            barang_menipis_list.append({
                "nama": b.nama,
                "stok": stok,
                "stok_minimum": b.stok_minimum,
            })

    barang_menipis_list.sort(key=lambda x: x["stok"])
    grafik = barang_menipis_list[:10]

    barang_masuk = db.query(func.count(TransaksiStok.id)).filter(
        TransaksiStok.jenis == "masuk",
        TransaksiStok.created_at >= f"{today} 00:00:00",
    ).scalar() or 0

    barang_keluar = db.query(func.count(TransaksiStok.id)).filter(
        TransaksiStok.jenis == "keluar",
        TransaksiStok.created_at >= f"{today} 00:00:00",
    ).scalar() or 0

    txs = db.query(TransaksiStok).options(
        joinedload(TransaksiStok.barang), joinedload(TransaksiStok.user)
    ).order_by(TransaksiStok.created_at.desc()).limit(5).all()

    transaksi_out = []
    for t in txs:
        transaksi_out.append(TransaksiOut(
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

    return DashboardResponse(
        total_barang=total_barang,
        stok_menipis=stok_menipis,
        barang_masuk_hari_ini=barang_masuk,
        barang_keluar_hari_ini=barang_keluar,
        grafik_stok_menipis=grafik,
        transaksi_terbaru=transaksi_out,
    )


@router.get("/laba-full")
def laba_full(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Full laba detail endpoint for the frontend."""
    first_of_month = str(date.today().replace(day=1))
    today = str(date.today())

    rows = (
        db.query(
            TransaksiStok.barang_id,
            func.sum(TransaksiStok.jumlah).label("total_terjual"),
        )
        .filter(
            TransaksiStok.jenis == "keluar",
            func.date(TransaksiStok.created_at) >= first_of_month,
            func.date(TransaksiStok.created_at) <= today,
        )
        .group_by(TransaksiStok.barang_id)
        .all()
    )

    detail = []
    total_laba = 0
    total_jual = 0
    total_modal = 0
    for row in rows:
        b = db.query(Barang).filter(Barang.id == row.barang_id).first()
        if not b:
            continue
        terjual = row.total_terjual or 0
        modal = (b.harga_modal or 0) * terjual
        jual = (b.harga_jual or 0) * terjual
        laba = jual - modal
        total_modal += modal
        total_jual += jual
        total_laba += laba
        detail.append({
            "nama": b.nama,
            "terjual": terjual,
            "laba": laba,
        })

    return {
        "laba_bulan_ini": total_laba,
        "total_penjualan": total_jual,
        "total_modal": total_modal,
        "detail": sorted(detail, key=lambda x: x["laba"], reverse=True),
    }
