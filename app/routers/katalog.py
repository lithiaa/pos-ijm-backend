import os
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.barang import Barang
from app.models.environment import Environment
from app.schemas.katalog import KatalogBarangListResponse, KatalogBarangOut, KatalogFilterMeta

router = APIRouter(prefix="/api/katalog/barang", tags=["katalog"])
LITHIA_SLUG = "lithia-autoparts"


def _catalog_query(db: Session):
    env = db.query(Environment).filter(Environment.slug == LITHIA_SLUG).first()
    if not env:
        # No Lithia Autoparts environment configured - return empty query
        return db.query(Barang).filter(False)
    return db.query(Barang).filter(Barang.environment_id == env.id)


def _slug(barang: Barang) -> str:
    normalized = unicodedata.normalize("NFKD", barang.nama).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return f"{value or 'barang'}-{barang.id}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_out(barang: Barang) -> KatalogBarangOut:
    foto = os.path.basename(barang.foto) if barang.foto else None
    return KatalogBarangOut(id=barang.id, slug=_slug(barang), sku=barang.sku, nama=barang.nama,
        merek=barang.merek, harga_jual=int(barang.harga_jual or 0), satuan=barang.satuan or "pcs",
        deskripsi=barang.deskripsi, foto_url=f"/storage/foto-barang/{foto}" if foto else None,
        shopee_url=barang.shopee_url)


@router.get("/filter-meta", response_model=KatalogFilterMeta)
def katalog_filter_meta(db: Session = Depends(get_db)):
    query = _catalog_query(db)
    harga_min, harga_max = query.with_entities(func.min(Barang.harga_jual), func.max(Barang.harga_jual)).one()
    merek = {}
    for (value,) in query.with_entities(Barang.merek).order_by(func.lower(Barang.merek), Barang.id):
        normalized = (value or "").strip()
        if normalized: merek.setdefault(normalized.casefold(), normalized)
    return KatalogFilterMeta(merek=sorted(merek.values(), key=str.casefold), harga_min=int(harga_min or 0), harga_max=int(harga_max or 0))


@router.get("", response_model=KatalogBarangListResponse)
def list_katalog_barang(q: str | None = None, merek: str | None = None, harga_min: int | None = Query(default=None, ge=0), harga_max: int | None = Query(default=None, ge=0), page: int = Query(default=1, ge=1), limit: int = Query(default=24, ge=1, le=48), db: Session = Depends(get_db)):
    if harga_min is not None and harga_max is not None and harga_min > harga_max:
        raise HTTPException(status_code=422, detail="harga_min tidak boleh melebihi harga_max")
    query = _catalog_query(db)
    term = (q or "").strip()
    if term:
        contains = f"%{_escape_like(term.lower())}%"
        query = query.filter(or_(func.lower(Barang.nama).like(contains, escape="\\"), func.lower(Barang.sku).like(contains, escape="\\"), func.lower(func.coalesce(Barang.merek, "")).like(contains, escape="\\")))
    if (selected := (merek or "").strip()): query = query.filter(func.lower(func.trim(func.coalesce(Barang.merek, ""))) == selected.lower())
    if harga_min is not None: query = query.filter(Barang.harga_jual >= harga_min)
    if harga_max is not None: query = query.filter(Barang.harga_jual <= harga_max)
    total = query.count(); data = query.order_by(func.lower(Barang.nama), Barang.id).offset((page - 1) * limit).limit(limit).all()
    return KatalogBarangListResponse(data=[_to_out(b) for b in data], total=total, page=page, limit=limit)


@router.get("/{slug}", response_model=KatalogBarangOut)
def detail_katalog_barang(slug: str, db: Session = Depends(get_db)):
    match = re.fullmatch(r".+-(\d+)", slug)
    if not match: raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    barang = _catalog_query(db).filter(Barang.id == int(match.group(1))).first()
    if not barang or _slug(barang) != slug: raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return _to_out(barang)
