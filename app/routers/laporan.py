from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta

from app.database import get_db
from app.models.barang import Barang
from app.models.transaksi import TransaksiStok
from app.auth import get_current_user

router = APIRouter(prefix="/api/laporan", tags=["laporan"])


@router.get("/laba")
def laba(
    since: str = Query(None, description="Start date YYYY-MM-DD"),
    until: str = Query(None, description="End date YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Laba kotor per barang + total."""
    today = date.today()
    since_date = date.fromisoformat(since) if since else today.replace(day=1)
    until_date = date.fromisoformat(until) if until else today

    # Barang yg pernah terjual (keluar) di periode
    rows = (
        db.query(
            TransaksiStok.barang_id,
            func.sum(TransaksiStok.jumlah).label("total_terjual"),
        )
        .filter(
            TransaksiStok.jenis == "keluar",
            func.date(TransaksiStok.created_at) >= since_date,
            func.date(TransaksiStok.created_at) <= until_date,
        )
        .group_by(TransaksiStok.barang_id)
        .all()
    )

    detail = []
    total_modal = 0
    total_jual = 0
    total_laba = 0

    for row in rows:
        barang = db.query(Barang).filter(Barang.id == row.barang_id).first()
        if not barang:
            continue
        terjual = row.total_terjual or 0
        modal = (barang.harga_modal or 0) * terjual
        jual = (barang.harga_jual or 0) * terjual
        laba = jual - modal
        total_modal += modal
        total_jual += jual
        total_laba += laba
        detail.append({
            "id": barang.id,
            "nama": barang.nama,
            "sku": barang.sku or "",
            "terjual": terjual,
            "harga_modal": barang.harga_modal or 0,
            "harga_jual": barang.harga_jual or 0,
            "total_modal": modal,
            "total_jual": jual,
            "laba": laba,
            "margin_persen": round((laba / jual * 100), 1) if jual else 0,
        })

    return {
        "periode": {"since": str(since_date), "until": str(until_date)},
        "ringkasan": {
            "total_terjual": sum(d["terjual"] for d in detail),
            "total_modal": total_modal,
            "total_jual": total_jual,
            "total_laba": total_laba,
            "margin_rata": round((total_laba / total_jual * 100), 1) if total_jual else 0,
        },
        "detail": detail,
    }


@router.get("/top-laba")
def top_laba(
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Top-N barang by laba (all-time)."""
    rows = (
        db.query(
            TransaksiStok.barang_id,
            func.sum(TransaksiStok.jumlah).label("total_terjual"),
        )
        .filter(TransaksiStok.jenis == "keluar")
        .group_by(TransaksiStok.barang_id)
        .all()
    )

    results = []
    for row in rows:
        barang = db.query(Barang).filter(Barang.id == row.barang_id).first()
        if not barang:
            continue
        terjual = row.total_terjual or 0
        laba = ((barang.harga_jual or 0) - (barang.harga_modal or 0)) * terjual
        results.append({
            "id": barang.id,
            "nama": barang.nama,
            "terjual": terjual,
            "laba": laba,
        })

    results.sort(key=lambda x: x["laba"], reverse=True)
    return results[:limit]
