from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.barang import Barang
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.services.supplier_code import assign_supplier_code

router = APIRouter(prefix="/api/supplier", tags=["supplier"])


def _supplier_out(supplier: Supplier, jumlah_barang: int = 0) -> SupplierOut:
    return SupplierOut(
        id=supplier.id,
        kode_supplier=supplier.kode_supplier,
        nama=supplier.nama,
        nama_supplier=supplier.nama,
        kontak=supplier.kontak,
        telepon=supplier.telepon,
        email=supplier.email,
        jumlah_barang=jumlah_barang,
    )


def _commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Kode supplier sudah digunakan")
    except Exception:
        db.rollback()
        raise


@router.get("", response_model=list[SupplierOut])
def list_supplier(db: Session = Depends(get_db), user=Depends(get_current_user)):
    suppliers = db.query(Supplier).all()
    return [
        _supplier_out(
            supplier,
            db.query(Barang).filter(Barang.supplier_id == supplier.id).count(),
        )
        for supplier in suppliers
    ]


@router.post("", response_model=SupplierOut)
def create_supplier(
    req: SupplierCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    supplier = Supplier(
        kode_supplier=req.kode_supplier,
        nama=req.nama,
        kontak=req.kontak,
        telepon=req.telepon,
        email=req.email,
    )
    db.add(supplier)
    try:
        if supplier.kode_supplier is None:
            assign_supplier_code(db, supplier)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Kode supplier sudah digunakan")
    except Exception:
        db.rollback()
        raise
    db.refresh(supplier)
    return _supplier_out(supplier)


@router.put("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    req: SupplierUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")

    for field in req.model_fields_set:
        value = getattr(req, field)
        if value is not None:
            setattr(supplier, field, value)
    _commit_or_conflict(db)
    db.refresh(supplier)
    return _supplier_out(
        supplier,
        db.query(Barang).filter(Barang.supplier_id == supplier.id).count(),
    )


@router.delete("/{supplier_id}")
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    jumlah_barang = (
        db.query(Barang).filter(Barang.supplier_id == supplier_id).count()
    )
    if jumlah_barang > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tidak bisa hapus, ada {jumlah_barang} barang dari supplier ini"
            ),
        )
    db.delete(supplier)
    db.commit()
    return {"ok": True}
