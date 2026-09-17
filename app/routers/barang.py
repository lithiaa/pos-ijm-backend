import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from app.database import get_db
from app.models.barang import Barang
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import (
    IntegrationStockOperation,
    StokSaatIni,
    TransaksiStok,
)
from app.schemas.barang import BarangCreate, BarangUpdate, BarangOut, BarangListResponse
from app.schemas.supplier import SupplierOut
from app.auth import get_current_user
from app.services.harga import harga_encode, harga_decode
from app.routers.upload import STORAGE_DIR

router = APIRouter(prefix="/api/barang", tags=["barang"])


def _validate_supplier_id(db: Session, req: BarangCreate | BarangUpdate) -> None:
    supplied = req.model_fields_set
    if "supplier_id" in supplied and req.supplier_id is not None:
        if not db.get(Supplier, req.supplier_id):
            raise HTTPException(status_code=422, detail="Supplier tidak ditemukan")


def _barang_to_out(b: Barang) -> BarangOut:
    stok = b.stok.jumlah if b.stok else 0
    sisa = stok - b.stok_minimum
    if sisa <= 0:
        status = "Habis" if stok == 0 else "Menipis"
    else:
        status = "Aman"

    sup_out = None
    if b.supplier:
        sup_out = SupplierOut(id=b.supplier.id,
                              kode_supplier=b.supplier.kode_supplier,
                              nama=b.supplier.nama,
                              nama_supplier=b.supplier.nama,
                              kontak=b.supplier.kontak, telepon=b.supplier.telepon,
                              email=b.supplier.email, jumlah_barang=0)

    return BarangOut(
        id=b.id,
        sku=b.sku,
        nama=b.nama,
        merek=b.merek,
        supplier_id=b.supplier_id,
        supplier=sup_out,
        supplier_nama=b.supplier.nama if b.supplier else "",
        harga_modal=b.harga_modal,
        harga_beli_kode=b.harga_beli_kode or "",
        harga_jual=b.harga_jual,
        harga_jual_kode=harga_encode(b.harga_jual),
        stok_minimum=b.stok_minimum,
        satuan=b.satuan,
        deskripsi=b.deskripsi,
        foto=b.foto,
        shopee_url=b.shopee_url,
        stok=stok,
        status=status,
        created_at=str(b.created_at)[:19] if b.created_at else None,
    )


@router.get("", response_model=BarangListResponse)
def list_barang(
    q: str = Query(None),
    search: str = Query(None),
    supplier_id: int = Query(None),
    stok_menipis: bool = Query(False),
    sort_by: str = Query("id"),
    sort_order: str = Query("ASC"),
    page: int = Query(1, ge=1),
    skip: int | None = Query(None, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    sortable = {
        "id": Barang.id,
        "sku": Barang.sku,
        "nama": Barang.nama,
        "merek": Barang.merek,
        "harga_modal": Barang.harga_modal,
        "harga_beli": Barang.harga_modal,
        "harga_jual": Barang.harga_jual,
        "stok_minimum": Barang.stok_minimum,
    }
    order_col = sortable.get(sort_by, Barang.id)
    order = order_col.asc() if str(sort_order).upper() != "DESC" else order_col.desc()
    stock = func.coalesce(StokSaatIni.jumlah, 0)
    query = db.query(Barang).outerjoin(StokSaatIni)

    term = (q or search or "").strip()
    if term:
        contains = f"%{term}%"
        query = query.filter(
            or_(
                Barang.nama.ilike(contains),
                Barang.sku.ilike(contains),
                Barang.merek.ilike(contains),
            )
        )
    if supplier_id is not None:
        query = query.filter(Barang.supplier_id == supplier_id)
    if stok_menipis:
        query = query.filter(stock <= Barang.stok_minimum)

    total = query.count()
    offset = skip if skip is not None else (page - 1) * limit
    data = (
        query.options(
            joinedload(Barang.supplier),
            joinedload(Barang.stok),
        )
        .order_by(order, Barang.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return BarangListResponse(
        total=total,
        page=(offset // limit) + 1,
        limit=limit,
        data=[_barang_to_out(barang) for barang in data],
    )


@router.get("/stok-menipis")
def stok_menipis(db: Session = Depends(get_db), user=Depends(get_current_user)):
    q = db.query(Barang).options(joinedload(Barang.stok)).all()
    result = []
    for b in q:
        stok = b.stok.jumlah if b.stok else 0
        if stok <= b.stok_minimum:
            result.append(_barang_to_out(b))
    return result


@router.get("/{barang_id}")
def detail_barang(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    b = db.query(Barang).options(
        joinedload(Barang.supplier), joinedload(Barang.stok)
    ).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return _barang_to_out(b)


@router.post("")
def create_barang(req: BarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _validate_supplier_id(db, req)
    if req.harga_jual is not None:
        harga_jual = req.harga_jual
    else:
        harga_jual = harga_decode(req.harga_jual_kode) if req.harga_jual_kode else 0

    sku = req.sku
    if not sku:
        count = db.query(func.count(Barang.id)).scalar() + 1
        prefix = (req.nama[:3] + req.merek[:2] if req.merek else req.nama[:5]).upper()
        sku = f"{prefix}-{count:04d}"

    b = Barang(
        sku=sku,
        nama=req.nama,
        merek=req.merek,
        supplier_id=req.supplier_id,
        harga_modal=req.harga_modal,
        harga_beli_kode=req.harga_beli_kode or harga_encode(req.harga_modal),
        harga_jual=harga_jual,
        stok_minimum=req.stok_minimum,
        satuan=req.satuan,
        deskripsi=req.deskripsi,
        shopee_url=req.shopee_url,
    )
    db.add(b)
    db.flush()

    stok = StokSaatIni(barang_id=b.id, jumlah=req.stok_awal)
    db.add(stok)

    if req.stok_awal > 0:
        tx = TransaksiStok(
            barang_id=b.id, jenis="masuk", jumlah=req.stok_awal,
            keterangan="Stok awal", user_id=user.id,
        )
        db.add(tx)

    db.commit()
    db.refresh(b)
    return _barang_to_out(b)


@router.put("/{barang_id}")
def update_barang(barang_id: int, req: BarangUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    _validate_supplier_id(db, req)

    # Update fields explicitly provided
    for field in req.model_fields_set:
        if field == "harga_jual_kode":
            continue
        if field == "harga_jual":
            b.harga_jual = req.harga_jual
        else:
            setattr(b, field, getattr(req, field))

    # Handle harga_jual_kode only if harga_jual not provided
    if "harga_jual" not in req.model_fields_set and "harga_jual_kode" in req.model_fields_set:
        b.harga_jual = harga_decode(req.harga_jual_kode)

    db.commit()
    db.refresh(b)
    return _barang_to_out(b)


@router.delete("/{barang_id}")
def delete_barang(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    old_photo = b.foto

    try:
        for model in (
            PrintJob,
            IntegrationStockOperation,
            StokSaatIni,
            TransaksiStok,
        ):
            db.query(model).filter(model.barang_id == barang_id).delete(
                synchronize_session=False
            )
        db.delete(b)
        db.commit()
    except Exception:
        db.rollback()
        raise

    if old_photo:
        try:
            os.remove(os.path.join(STORAGE_DIR, os.path.basename(old_photo)))
        except OSError:
            pass
    return {"id": barang_id}
