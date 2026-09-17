import os
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.barang import Barang
from app.schemas.katalog import KatalogBarangListResponse, KatalogBarangOut

router = APIRouter(prefix="/api/katalog/barang", tags=["katalog"])


def _slug(barang: Barang) -> str:
    normalized = unicodedata.normalize("NFKD", barang.nama).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return f"{value or 'barang'}-{barang.id}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_out(barang: Barang) -> KatalogBarangOut:
    foto = os.path.basename(barang.foto) if barang.foto else None
    return KatalogBarangOut(
        id=barang.id,
        slug=_slug(barang),
        sku=barang.sku,
        nama=barang.nama,
        merek=barang.merek,
        harga_jual=int(barang.harga_jual or 0),
        satuan=barang.satuan or "pcs",
        deskripsi=barang.deskripsi,
        foto_url=f"/storage/foto-barang/{foto}" if foto else None,
        shopee_url=barang.shopee_url,
    )


@router.get("", response_model=KatalogBarangListResponse)
def list_katalog_barang(
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
):
    query = db.query(Barang)
    term = (q or "").strip()
    if term:
        contains = f"%{_escape_like(term.lower())}%"
        query = query.filter(
            or_(
                func.lower(Barang.nama).like(contains, escape="\\"),
                func.lower(Barang.sku).like(contains, escape="\\"),
                func.lower(func.coalesce(Barang.merek, "")).like(contains, escape="\\"),
            )
        )
    total = query.count()
    data = (
        query.order_by(func.lower(Barang.nama), Barang.id)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return KatalogBarangListResponse(
        data=[_to_out(barang) for barang in data], total=total, page=page, limit=limit
    )


@router.get("/{slug}", response_model=KatalogBarangOut)
def detail_katalog_barang(slug: str, db: Session = Depends(get_db)):
    match = re.fullmatch(r".+-(\d+)", slug)
    if not match:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    barang = db.get(Barang, int(match.group(1)))
    if not barang or _slug(barang) != slug:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return _to_out(barang)
