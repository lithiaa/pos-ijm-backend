import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from app.database import get_db
from app.models.barang import Barang, BarangFoto, BarangSupplier
from app.services.stock_in import record_stock_in
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import (
    IntegrationStockOperation,
    StokSaatIni,
    TransaksiStok,
)
from app.schemas.barang import BarangCreate, BarangUpdate, BarangOut, BarangListResponse, BarangSupplierOut, BarangPhotoOut
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

    supplier_links = sorted(b.supplier_links, key=lambda link: (link.created_at or b.created_at, link.supplier_id))
    suppliers = [
        BarangSupplierOut(
            id=link.supplier.id, kode_supplier=link.supplier.kode_supplier, nama=link.supplier.nama,
            nama_supplier=link.supplier.nama, kontak=link.supplier.kontak, telepon=link.supplier.telepon,
            email=link.supplier.email, jumlah_barang=0, jumlah_masuk_kumulatif=link.jumlah_masuk_kumulatif,
            is_primary=link.supplier_id == b.supplier_id,
        ) for link in supplier_links
    ]
    photos = [BarangPhotoOut(id=p.id, filename=p.filename, foto=p.filename,
        foto_url=f"/storage/foto-barang/{p.filename}", urutan=p.urutan,
        is_primary=i == 0, created_at=str(p.created_at)[:19] if p.created_at else None)
        for i, p in enumerate(b.photos)]
    primary_photo = photos[0] if photos else None
    return BarangOut(
        id=b.id,
        sku=b.sku,
        nama=b.nama,
        merek=b.merek,
        supplier_id=b.supplier_id,
        supplier=sup_out,
        supplier_nama=b.supplier.nama if b.supplier else "",
        primary_supplier_id=b.supplier_id,
        primary_supplier=sup_out,
        suppliers=suppliers,
        harga_modal=b.harga_modal,
        harga_beli_kode=b.harga_beli_kode or "",
        harga_jual=b.harga_jual,
        harga_jual_kode=harga_encode(b.harga_jual),
        stok_minimum=b.stok_minimum,
        satuan=b.satuan,
        deskripsi=b.deskripsi,
        foto=primary_photo.filename if primary_photo else b.foto,
        foto_url=primary_photo.foto_url if primary_photo else (f"/storage/foto-barang/{b.foto}" if b.foto else None),
        photos=photos,
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
        query = query.filter(or_(Barang.supplier_id == supplier_id, Barang.supplier_links.any(BarangSupplier.supplier_id == supplier_id)))
    if stok_menipis:
        query = query.filter(stock <= Barang.stok_minimum)

    total = query.count()
    offset = skip if skip is not None else (page - 1) * limit
    data = (
        query.options(
            joinedload(Barang.supplier), joinedload(Barang.stok),
            joinedload(Barang.supplier_links).joinedload(BarangSupplier.supplier), joinedload(Barang.photos),
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
        joinedload(Barang.supplier), joinedload(Barang.stok),
        joinedload(Barang.supplier_links).joinedload(BarangSupplier.supplier), joinedload(Barang.photos),
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

    stok = StokSaatIni(barang_id=b.id, jumlah=0)
    db.add(stok)
    db.flush()
    if req.stok_awal > 0:
        record_stock_in(db, barang_id=b.id, jumlah=req.stok_awal, harga_satuan=req.harga_modal,
                        keterangan="Stok awal", user_id=user.id, supplier_id=req.supplier_id)
    elif req.supplier_id is not None:
        db.add(BarangSupplier(barang_id=b.id, supplier_id=req.supplier_id, jumlah_masuk_kumulatif=0))

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
    if "supplier_id" in req.model_fields_set and req.supplier_id is not None:
        if not db.get(BarangSupplier, (b.id, req.supplier_id)):
            db.add(BarangSupplier(barang_id=b.id, supplier_id=req.supplier_id, jumlah_masuk_kumulatif=0))
        winner = db.query(BarangSupplier).filter(
            BarangSupplier.barang_id == b.id, BarangSupplier.jumlah_masuk_kumulatif > 0
        ).order_by(BarangSupplier.jumlah_masuk_kumulatif.desc(), BarangSupplier.supplier_id).first()
        if winner:
            b.supplier_id = winner.supplier_id

    db.commit()
    db.refresh(b)
    return _barang_to_out(b)


@router.delete("/{barang_id}")
def delete_barang(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    photo_filenames = [photo.filename for photo in b.photos]
    if b.foto and b.foto not in photo_filenames:
        photo_filenames.append(b.foto)

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

    for filename in photo_filenames:
        try:
            os.remove(os.path.join(STORAGE_DIR, os.path.basename(filename)))
        except OSError:
            pass
    return {"id": barang_id}
