from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.schemas.barang import BarangCreate, BarangUpdate, BarangOut, BarangListResponse
from app.schemas.kategori import KategoriOut
from app.schemas.supplier import SupplierOut
from app.auth import get_current_user
from app.services.harga import harga_encode, harga_decode

router = APIRouter(prefix="/api/barang", tags=["barang"])


def _barang_to_out(b: Barang) -> BarangOut:
    stok = b.stok.jumlah if b.stok else 0
    sisa = stok - b.stok_minimum
    if sisa <= 0:
        status = "Habis" if stok == 0 else "Menipis"
    else:
        status = "Aman"

    kat_out = None
    if b.kategori:
        kat_out = KategoriOut(id=b.kategori.id, nama=b.kategori.nama,
                              deskripsi=b.kategori.deskripsi, jumlah_barang=0)

    sup_out = None
    if b.supplier:
        sup_out = SupplierOut(id=b.supplier.id, nama=b.supplier.nama,
                              kontak=b.supplier.kontak, telepon=b.supplier.telepon,
                              email=b.supplier.email, jumlah_barang=0)

    return BarangOut(
        id=b.id,
        sku=b.sku,
        nama=b.nama,
        merek=b.merek,
        kategori=kat_out,
        supplier=sup_out,
        harga_modal=b.harga_modal,
        harga_beli_kode=b.harga_beli_kode or "",
        harga_jual=b.harga_jual,
        harga_jual_kode=harga_encode(b.harga_jual),
        stok_minimum=b.stok_minimum,
        satuan=b.satuan,
        deskripsi=b.deskripsi,
        foto=b.foto,
        stok=stok,
        status=status,
        created_at=str(b.created_at)[:19] if b.created_at else None,
    )


@router.get("", response_model=BarangListResponse)
def list_barang(
    search: str = Query(None),
    kategori_id: int = Query(None),
    stok_menipis: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(Barang).options(joinedload(Barang.kategori), joinedload(Barang.supplier), joinedload(Barang.stok))

    if search:
        search = f"%{search}%"
        q = q.filter(
            Barang.nama.ilike(search) |
            Barang.sku.ilike(search) |
            Barang.merek.ilike(search)
        )
    if kategori_id:
        q = q.filter(Barang.kategori_id == kategori_id)

    total = q.count()
    data = q.offset((page - 1) * limit).limit(limit).all()

    result = []
    for b in data:
        out = _barang_to_out(b)
        if stok_menipis and out.status == "Aman":
            continue
        result.append(out)

    if stok_menipis:
        total = len(result)

    return BarangListResponse(total=total, page=page, limit=limit, data=result)


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
        joinedload(Barang.kategori), joinedload(Barang.supplier), joinedload(Barang.stok)
    ).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return _barang_to_out(b)


@router.post("")
def create_barang(req: BarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    harga_jual = harga_decode(req.harga_jual_kode)

    sku = req.sku
    if not sku:
        count = db.query(func.count(Barang.id)).scalar() + 1
        prefix = (req.nama[:3] + req.merek[:2] if req.merek else req.nama[:5]).upper()
        sku = f"{prefix}-{count:04d}"

    b = Barang(
        sku=sku,
        nama=req.nama,
        merek=req.merek,
        kategori_id=req.kategori_id,
        supplier_id=req.supplier_id,
        harga_modal=req.harga_modal,
        harga_beli_kode=req.harga_beli_kode or harga_encode(req.harga_modal),
        harga_jual=harga_jual,
        stok_minimum=req.stok_minimum,
        satuan=req.satuan,
        deskripsi=req.deskripsi,
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

    if req.nama is not None: b.nama = req.nama
    if req.merek is not None: b.merek = req.merek
    if req.kategori_id is not None: b.kategori_id = req.kategori_id
    if req.supplier_id is not None: b.supplier_id = req.supplier_id
    if req.harga_modal is not None: b.harga_modal = req.harga_modal
    if req.harga_beli_kode is not None: b.harga_beli_kode = req.harga_beli_kode
    if req.harga_jual_kode is not None: b.harga_jual = harga_decode(req.harga_jual_kode)
    if req.stok_minimum is not None: b.stok_minimum = req.stok_minimum
    if req.satuan is not None: b.satuan = req.satuan
    if req.deskripsi is not None: b.deskripsi = req.deskripsi

    db.commit()
    return _barang_to_out(b)


@router.delete("/{barang_id}")
def delete_barang(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    db.query(StokSaatIni).filter(StokSaatIni.barang_id == barang_id).delete()
    db.query(TransaksiStok).filter(TransaksiStok.barang_id == barang_id).delete()
    db.delete(b)
    db.commit()
    return {"ok": True}
