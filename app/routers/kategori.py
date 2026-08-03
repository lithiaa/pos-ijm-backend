from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.kategori import Kategori
from app.models.barang import Barang
from app.schemas.kategori import KategoriCreate, KategoriUpdate, KategoriOut
from app.auth import get_current_user

router = APIRouter(prefix="/api/kategori", tags=["kategori"])


@router.get("")
def list_kategori(db: Session = Depends(get_db), user=Depends(get_current_user)):
    kat = db.query(Kategori).all()
    result = []
    for k in kat:
        jml = db.query(Barang).filter(Barang.kategori_id == k.id).count()
        result.append(KategoriOut(id=k.id, nama=k.nama, deskripsi=k.deskripsi, jumlah_barang=jml))
    return result


@router.post("")
def create_kategori(req: KategoriCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    existing = db.query(Kategori).filter(Kategori.nama == req.nama).first()
    if existing:
        raise HTTPException(status_code=400, detail="Kategori sudah ada")
    kat = Kategori(nama=req.nama, deskripsi=req.deskripsi)
    db.add(kat)
    db.commit()
    db.refresh(kat)
    return kat


@router.put("/{kategori_id}")
def update_kategori(kategori_id: int, req: KategoriUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    kat = db.query(Kategori).filter(Kategori.id == kategori_id).first()
    if not kat:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    if req.nama is not None:
        kat.nama = req.nama
    if req.deskripsi is not None:
        kat.deskripsi = req.deskripsi
    db.commit()
    return kat


@router.delete("/{kategori_id}")
def delete_kategori(kategori_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    kat = db.query(Kategori).filter(Kategori.id == kategori_id).first()
    if not kat:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    jml = db.query(Barang).filter(Barang.kategori_id == kategori_id).count()
    if jml > 0:
        raise HTTPException(status_code=400, detail=f"Tidak bisa hapus, ada {jml} barang dalam kategori ini")
    db.delete(kat)
    db.commit()
    return {"ok": True}
