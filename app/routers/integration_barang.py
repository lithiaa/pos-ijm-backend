from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.integration_auth import require_integration_key
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni
from app.schemas.integration_barang import (
    IntegrationBarangCreate,
    IntegrationBarangOut,
    IntegrationBarangUpdate,
)
from app.services.harga import harga_encode


router = APIRouter(
    prefix="/api/integration/barang",
    tags=["integration-barang"],
    dependencies=[Depends(require_integration_key)],
)


def _normalize_sku(sku: str) -> str:
    normalized = sku.strip().upper()
    if not normalized:
        raise HTTPException(status_code=422, detail="SKU must not be blank")
    return normalized


def _get_by_sku(db: Session, sku: str) -> Barang | None:
    return (
        db.query(Barang)
        .options(joinedload(Barang.stok))
        .filter(Barang.sku == sku)
        .first()
    )


def _to_integration_out(barang: Barang) -> IntegrationBarangOut:
    harga_beli = int(barang.harga_modal or 0)
    return IntegrationBarangOut(
        id=barang.id,
        sku=barang.sku,
        nama=barang.nama,
        harga_beli=harga_beli,
        harga_jual=int(barang.harga_jual or 0),
        harga_beli_kode=harga_encode(harga_beli),
        stok=barang.stok.jumlah if barang.stok else 0,
        satuan=barang.satuan or "pcs",
    )


@router.get("/by-sku/{sku}", response_model=IntegrationBarangOut)
def get_barang_by_sku(sku: str, db: Session = Depends(get_db)):
    barang = _get_by_sku(db, _normalize_sku(sku))
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    return _to_integration_out(barang)


@router.post(
    "",
    response_model=IntegrationBarangOut,
    status_code=status.HTTP_201_CREATED,
)
def create_integration_barang(
    req: IntegrationBarangCreate,
    db: Session = Depends(get_db),
):
    if _get_by_sku(db, req.sku):
        raise HTTPException(status_code=409, detail="SKU already exists")

    barang = Barang(
        sku=req.sku,
        nama=req.nama,
        harga_modal=req.harga_beli,
        harga_jual=req.harga_jual,
        satuan=req.satuan,
    )

    try:
        db.add(barang)
        db.flush()
        db.add(StokSaatIni(barang_id=barang.id, jumlah=req.stok))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists")
    except Exception:
        db.rollback()
        raise

    db.refresh(barang)
    return _to_integration_out(barang)


@router.put("/by-sku/{sku}", response_model=IntegrationBarangOut)
def update_integration_barang(
    sku: str,
    req: IntegrationBarangUpdate,
    db: Session = Depends(get_db),
):
    barang = _get_by_sku(db, _normalize_sku(sku))
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    barang.nama = req.nama
    barang.harga_modal = req.harga_beli
    barang.harga_jual = req.harga_jual

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(barang)
    return _to_integration_out(barang)
