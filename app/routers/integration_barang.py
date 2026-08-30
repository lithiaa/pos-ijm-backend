import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile, status
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.integration_auth import require_integration_key
from app.models.barang import Barang
from app.models.kategori import Kategori
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import (
    IntegrationStockOperation,
    StokSaatIni,
    TransaksiStok,
)
from app.routers.upload import STORAGE_DIR
from app.schemas.integration_barang import (
    IntegrationBarangCreate,
    IntegrationBarangListResponse,
    IntegrationBarangMetaOut,
    IntegrationBarangMetadataUpdate,
    IntegrationBarangOut,
    IntegrationBarangSearchResponse,
    IntegrationBarangUpdate,
    IntegrationKategoriOut,
    IntegrationStokMasuk,
    IntegrationSupplierOut,
)


router = APIRouter(
    prefix="/api/integration/barang",
    tags=["integration-barang"],
    dependencies=[Depends(require_integration_key)],
)

INTEGRATION_KETERANGAN_PREFIX = (
    "Niimbot label integration | NIIMBOT_OPERATION_ID="
)
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
PHOTO_SIGNATURES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


def _matches_photo_signature(content_type: str, prefix: bytes) -> bool:
    if content_type == "image/webp":
        return prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    return prefix.startswith(PHOTO_SIGNATURES[content_type])


def _normalize_sku(sku: str) -> str:
    normalized = sku.strip().upper()
    if not normalized:
        raise HTTPException(status_code=422, detail="SKU must not be blank")
    return normalized


FULL_ITEM_OPTIONS = (
    joinedload(Barang.stok),
    joinedload(Barang.kategori),
    joinedload(Barang.supplier),
)


def _get_by_sku(db: Session, sku: str) -> Barang | None:
    return (
        db.query(Barang)
        .options(*FULL_ITEM_OPTIONS)
        .filter(Barang.sku == sku)
        .first()
    )


def _get_by_id(db: Session, barang_id: int) -> Barang | None:
    return (
        db.query(Barang)
        .options(*FULL_ITEM_OPTIONS)
        .filter(Barang.id == barang_id)
        .first()
    )


def _stock_status(stok: int, stok_minimum: int) -> str:
    if stok <= 0:
        return "habis"
    if stok <= stok_minimum:
        return "menipis"
    return "aman"


def _to_integration_out(barang: Barang) -> IntegrationBarangOut:
    stok = barang.stok.jumlah if barang.stok else 0
    return IntegrationBarangOut(
        id=barang.id,
        sku=barang.sku or "",
        nama=barang.nama,
        harga_beli=int(barang.harga_modal or 0),
        harga_jual=int(barang.harga_jual or 0),
        harga_beli_kode=barang.harga_beli_kode or "",
        stok=stok,
        satuan=barang.satuan or "pcs",
        merek=barang.merek,
        foto=barang.foto,
        foto_url=f"/storage/foto-barang/{barang.foto}" if barang.foto else None,
        kategori=(
            IntegrationKategoriOut(
                id=barang.kategori.id,
                nama=barang.kategori.nama,
                deskripsi=barang.kategori.deskripsi,
            )
            if barang.kategori
            else None
        ),
        supplier=(
            IntegrationSupplierOut(
                id=barang.supplier.id,
                nama=barang.supplier.nama,
                kontak=barang.supplier.kontak,
                telepon=barang.supplier.telepon,
                email=barang.supplier.email,
            )
            if barang.supplier
            else None
        ),
        stok_minimum=barang.stok_minimum or 0,
        stok_status=_stock_status(stok, barang.stok_minimum or 0),
        deskripsi=barang.deskripsi,
        created_at=barang.created_at,
        updated_at=barang.updated_at,
    )


def _keterangan(operation_id: str) -> str:
    return f"{INTEGRATION_KETERANGAN_PREFIX}{operation_id}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _validate_foreign_keys(
    db: Session,
    kategori_id: int | None,
    supplier_id: int | None,
) -> None:
    if kategori_id is not None and not db.get(Kategori, kategori_id):
        raise HTTPException(status_code=422, detail="Kategori not found")
    if supplier_id is not None and not db.get(Supplier, supplier_id):
        raise HTTPException(status_code=422, detail="Supplier not found")


def _get_operation_barang(
    db: Session,
    operation_id: str,
    expected_sku: str,
) -> Barang | None:
    operation = db.get(IntegrationStockOperation, operation_id)
    if not operation:
        return None

    barang = (
        db.query(Barang)
        .options(joinedload(Barang.stok))
        .filter(Barang.id == operation.barang_id)
        .first()
    )
    if not barang or barang.sku != expected_sku:
        raise HTTPException(
            status_code=409,
            detail="Operation ID already used for another SKU",
        )
    return barang


def _add_stock_transaction(
    db: Session,
    *,
    barang_id: int,
    jumlah: int,
    harga_satuan: int,
    operation_id: str,
) -> None:
    if jumlah == 0:
        return

    db.add(
        TransaksiStok(
            barang_id=barang_id,
            jenis="masuk",
            jumlah=jumlah,
            harga_satuan=harga_satuan,
            total_harga=harga_satuan * jumlah,
            keterangan=_keterangan(operation_id),
            user_id=None,
        )
    )


@router.get("", response_model=IntegrationBarangListResponse)
def list_integration_barang(
    q: str | None = None,
    kategori_id: int | None = None,
    supplier_id: int | None = None,
    stok_status: Literal["aman", "menipis", "habis"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stock = func.coalesce(StokSaatIni.jumlah, 0)
    query = db.query(Barang).outerjoin(StokSaatIni)
    term = (q or "").strip()
    if term:
        contains = f"%{_escape_like(term.lower())}%"
        query = query.filter(
            or_(
                func.lower(Barang.nama).like(contains, escape="\\"),
                func.lower(Barang.sku).like(contains, escape="\\"),
                func.lower(func.coalesce(Barang.merek, "")).like(
                    contains, escape="\\"
                ),
            )
        )
    if kategori_id is not None:
        query = query.filter(Barang.kategori_id == kategori_id)
    if supplier_id is not None:
        query = query.filter(Barang.supplier_id == supplier_id)
    if stok_status == "habis":
        query = query.filter(stock <= 0)
    elif stok_status == "menipis":
        query = query.filter(stock > 0, stock <= Barang.stok_minimum)
    elif stok_status == "aman":
        query = query.filter(stock > Barang.stok_minimum)

    total = query.count()
    items = (
        query.options(*FULL_ITEM_OPTIONS)
        .order_by(func.lower(Barang.nama), Barang.id)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return IntegrationBarangListResponse(
        data=[_to_integration_out(item) for item in items],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/meta", response_model=IntegrationBarangMetaOut)
def get_integration_barang_meta(db: Session = Depends(get_db)):
    categories = db.query(Kategori).order_by(func.lower(Kategori.nama), Kategori.id).all()
    suppliers = db.query(Supplier).order_by(func.lower(Supplier.nama), Supplier.id).all()
    values = {
        value.strip()
        for (value,) in db.query(Barang.satuan).distinct().all()
        if value and value.strip()
    }
    values.add("pcs")
    return IntegrationBarangMetaOut(
        categories=[
            IntegrationKategoriOut(id=item.id, nama=item.nama, deskripsi=item.deskripsi)
            for item in categories
        ],
        suppliers=[
            IntegrationSupplierOut(
                id=item.id,
                nama=item.nama,
                kontak=item.kontak,
                telepon=item.telepon,
                email=item.email,
            )
            for item in suppliers
        ],
        satuan=sorted(values, key=str.lower),
    )


@router.get("/search", response_model=IntegrationBarangSearchResponse)
def search_integration_barang(
    q: str | None = None,
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
):
    query = (q or "").strip()
    if len(query) < 2:
        return IntegrationBarangSearchResponse(data=[])

    literal = _escape_like(query.lower())
    contains = f"%{literal}%"
    prefix = f"{literal}%"
    lower_name = func.lower(Barang.nama)
    lower_sku = func.lower(Barang.sku)
    rank = case(
        (lower_name == query.lower(), 0),
        (lower_name.like(prefix, escape="\\"), 1),
        (lower_name.like(contains, escape="\\"), 2),
        else_=3,
    )
    barang = (
        db.query(Barang)
        .options(joinedload(Barang.stok))
        .filter(
            or_(
                lower_name.like(contains, escape="\\"),
                lower_sku.like(contains, escape="\\"),
            )
        )
        .order_by(rank, lower_name, Barang.id)
        .limit(limit)
        .all()
    )
    return IntegrationBarangSearchResponse(
        data=[_to_integration_out(item) for item in barang]
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
    operation_id = str(req.operation_id)
    previous_barang = _get_operation_barang(db, operation_id, req.sku)
    if previous_barang:
        return _to_integration_out(previous_barang)

    if _get_by_sku(db, req.sku):
        raise HTTPException(status_code=409, detail="SKU already exists")
    _validate_foreign_keys(db, req.kategori_id, req.supplier_id)

    barang = Barang(
        sku=req.sku,
        nama=req.nama,
        merek=req.merek,
        kategori_id=req.kategori_id,
        supplier_id=req.supplier_id,
        harga_modal=req.harga_beli,
        harga_beli_kode=req.harga_beli_kode,
        harga_jual=req.harga_jual,
        stok_minimum=req.stok_minimum,
        satuan=req.satuan,
        deskripsi=req.deskripsi,
    )

    try:
        db.add(barang)
        db.flush()
        db.add(
            StokSaatIni(
                barang_id=barang.id,
                jumlah=req.jumlah_barang_masuk,
            )
        )
        _add_stock_transaction(
            db,
            barang_id=barang.id,
            jumlah=req.jumlah_barang_masuk,
            harga_satuan=req.harga_beli,
            operation_id=operation_id,
        )
        db.add(
            IntegrationStockOperation(
                operation_id=operation_id,
                barang_id=barang.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_barang = _get_operation_barang(db, operation_id, req.sku)
        if previous_barang:
            return _to_integration_out(previous_barang)
        raise HTTPException(status_code=409, detail="SKU already exists")
    except Exception:
        db.rollback()
        raise

    db.refresh(barang)
    return _to_integration_out(barang)


@router.post(
    "/by-sku/{sku}/stok-masuk",
    response_model=IntegrationBarangOut,
)
def add_integration_stock(
    sku: str,
    req: IntegrationStokMasuk,
    db: Session = Depends(get_db),
):
    normalized_sku = _normalize_sku(sku)
    barang = _get_by_sku(db, normalized_sku)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    operation_id = str(req.operation_id)
    previous_barang = _get_operation_barang(db, operation_id, normalized_sku)
    if previous_barang:
        return _to_integration_out(previous_barang)

    try:
        result = db.execute(
            update(StokSaatIni)
            .where(StokSaatIni.barang_id == barang.id)
            .values(jumlah=StokSaatIni.jumlah + req.jumlah_barang_masuk)
        )
        if result.rowcount == 0:
            db.add(
                StokSaatIni(
                    barang_id=barang.id,
                    jumlah=req.jumlah_barang_masuk,
                )
            )

        _add_stock_transaction(
            db,
            barang_id=barang.id,
            jumlah=req.jumlah_barang_masuk,
            harga_satuan=req.harga_satuan,
            operation_id=operation_id,
        )
        db.add(
            IntegrationStockOperation(
                operation_id=operation_id,
                barang_id=barang.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_barang = _get_operation_barang(db, operation_id, normalized_sku)
        if previous_barang:
            return _to_integration_out(previous_barang)
        raise
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    barang = _get_by_sku(db, normalized_sku)
    return _to_integration_out(barang)


@router.get("/{barang_id}", response_model=IntegrationBarangOut)
def get_integration_barang(
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    barang = _get_by_id(db, barang_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    return _to_integration_out(barang)


@router.put("/{barang_id}", response_model=IntegrationBarangOut)
def update_integration_barang_by_id(
    req: IntegrationBarangMetadataUpdate,
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    barang = _get_by_id(db, barang_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    supplied = req.model_fields_set
    if "sku" in supplied:
        duplicate = (
            db.query(Barang)
            .filter(Barang.sku == req.sku, Barang.id != barang.id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="SKU already exists")
    _validate_foreign_keys(
        db,
        req.kategori_id if "kategori_id" in supplied else barang.kategori_id,
        req.supplier_id if "supplier_id" in supplied else barang.supplier_id,
    )

    field_map = {"harga_beli": "harga_modal"}
    for field in supplied:
        setattr(barang, field_map.get(field, field), getattr(req, field))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists")
    except Exception:
        db.rollback()
        raise

    return _to_integration_out(_get_by_id(db, barang.id))


@router.post("/{barang_id}/foto", response_model=IntegrationBarangOut)
async def upload_integration_barang_photo(
    file: UploadFile = File(...),
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    barang = _get_by_id(db, barang_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    content_type = file.content_type or ""
    extension = PHOTO_EXTENSIONS.get(content_type)
    if not extension:
        raise HTTPException(status_code=422, detail="Unsupported image type")

    os.makedirs(STORAGE_DIR, exist_ok=True)
    filename = f"{uuid.uuid4()}{extension}"
    path = os.path.join(STORAGE_DIR, filename)
    size = 0
    prefix = bytearray()
    try:
        with open(path, "xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_PHOTO_BYTES:
                    raise HTTPException(status_code=413, detail="Image exceeds 5 MiB")
                if len(prefix) < 12:
                    prefix.extend(chunk[: 12 - len(prefix)])
                output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="Image must not be empty")
        if not _matches_photo_signature(content_type, prefix):
            raise HTTPException(status_code=422, detail="Invalid image content")

        old_photo = barang.foto
        barang.foto = filename
        db.commit()
    except Exception:
        db.rollback()
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    finally:
        await file.close()

    if old_photo and os.path.basename(old_photo) != filename:
        try:
            os.remove(os.path.join(STORAGE_DIR, os.path.basename(old_photo)))
        except OSError:
            pass
    return _to_integration_out(_get_by_id(db, barang_id))


@router.delete("/{barang_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration_barang(
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
):
    barang = _get_by_id(db, barang_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    if db.query(PrintJob.id).filter(PrintJob.barang_id == barang_id).first():
        raise HTTPException(
            status_code=409,
            detail="Barang has print jobs and cannot be deleted",
        )
    old_photo = barang.foto

    try:
        db.query(IntegrationStockOperation).filter(
            IntegrationStockOperation.barang_id == barang_id
        ).delete(synchronize_session=False)
        db.query(TransaksiStok).filter(
            TransaksiStok.barang_id == barang_id
        ).delete(synchronize_session=False)
        db.query(StokSaatIni).filter(
            StokSaatIni.barang_id == barang_id
        ).delete(synchronize_session=False)
        db.query(Barang).filter(Barang.id == barang_id).delete(
            synchronize_session=False
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(PrintJob.id).filter(PrintJob.barang_id == barang_id).first():
            raise HTTPException(
                status_code=409,
                detail="Barang has print jobs and cannot be deleted",
            )
        raise
    except Exception:
        db.rollback()
        raise

    if old_photo:
        try:
            os.remove(os.path.join(STORAGE_DIR, os.path.basename(old_photo)))
        except OSError:
            pass


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
    if req.harga_beli_kode is not None:
        barang.harga_beli_kode = req.harga_beli_kode
    barang.harga_jual = req.harga_jual

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(barang)
    return _to_integration_out(barang)
