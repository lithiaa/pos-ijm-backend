from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.supplier import Supplier
from app.models.barang import Barang
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierOut
from app.auth import get_current_user

router = APIRouter(prefix="/api/supplier", tags=["supplier"])


@router.get("")
def list_supplier(db: Session = Depends(get_db), user=Depends(get_current_user)):
    sup = db.query(Supplier).all()
    result = []
    for s in sup:
        jml = db.query(Barang).filter(Barang.supplier_id == s.id).count()
        result.append(SupplierOut(id=s.id, nama=s.nama, kontak=s.kontak,
                      telepon=s.telepon, email=s.email, jumlah_barang=jml))
    return result


@router.post("")
def create_supplier(req: SupplierCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = Supplier(nama=req.nama, kontak=req.kontak, telepon=req.telepon, email=req.email)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.put("/{supplier_id}")
def update_supplier(supplier_id: int, req: SupplierUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    if req.nama is not None: s.nama = req.nama
    if req.kontak is not None: s.kontak = req.kontak
    if req.telepon is not None: s.telepon = req.telepon
    if req.email is not None: s.email = req.email
    db.commit()
    return s


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    s = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Supplier tidak ditemukan")
    jml = db.query(Barang).filter(Barang.supplier_id == supplier_id).count()
    if jml > 0:
        raise HTTPException(status_code=400, detail=f"Tidak bisa hapus, ada {jml} barang dari supplier ini")
    db.delete(s)
    db.commit()
    return {"ok": True}
