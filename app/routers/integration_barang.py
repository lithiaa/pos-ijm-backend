import os
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, UploadFile, status
from app.integration_auth import current_integration_env_id, get_integration_env_id
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.integration_auth import require_integration_key
from app.models.barang import Barang, BarangFoto, BarangSupplier
from app.services.stock_in import record_stock_in
from app.models.printjob import PrintJob
from app.models.supplier import Supplier
from app.models.transaksi import (
    IntegrationStockOperation,
    StokSaatIni,
    TransaksiStok,
)
from app.routers.upload import STORAGE_DIR, _locked_barang, _photo_path, _save, add_photo, delete_photo as _delete_gallery_photo, remove_unreferenced_file
from app.schemas.integration_barang import (
    IntegrationBarangCreate,
    IntegrationBarangListResponse,
    IntegrationBarangMetaOut,
    IntegrationBarangMetadataUpdate,
    IntegrationBarangOut,
    IntegrationBarangSearchResponse,
    IntegrationBarangStatistikItem,
    IntegrationBarangStatistikResponse,
    IntegrationBarangUpdate,
    IntegrationStokMasuk,
    IntegrationSupplierMetaOut,
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
    joinedload(Barang.supplier),
)


def _get_by_sku(db: Session, sku: str, env_id: int) -> Barang | None:
    return (
        db.query(Barang)
        .options(*FULL_ITEM_OPTIONS)
        .filter(Barang.sku == sku, Barang.environment_id == env_id)
        .first()
    )


def _get_by_id(db: Session, barang_id: int, env_id: int) -> Barang | None:
    return (
        db.query(Barang)
        .options(*FULL_ITEM_OPTIONS)
        .filter(Barang.id == barang_id, Barang.environment_id == env_id)
        .first()
    )


def _integration_env_id(request: Request | None = None) -> int:
    env_id = get_integration_env_id(request) if request is not None else current_integration_env_id()
    if env_id is None:
        raise HTTPException(status_code=401, detail="Integration environment required")
    return env_id


def _get_by_sku_for_integration(db: Session, sku: str, request: Request | None = None) -> Barang | None:
    return _get_by_sku(db, sku, _integration_env_id(request))


def _get_by_id_for_integration(db: Session, barang_id: int, request: Request | None = None) -> Barang | None:
    return _get_by_id(db, barang_id, _integration_env_id(request))


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
        foto_url=f"/api/foto-barang/{barang.environment_id}/{barang.foto}" if barang.foto else None,
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


def _validate_supplier_id(db: Session, supplier_id: int | None, env_id: int) -> None:
    if supplier_id is not None and not db.query(Supplier.id).filter(
        Supplier.id == supplier_id, Supplier.environment_id == env_id
    ).first():
        raise HTTPException(status_code=422, detail="Supplier not found")


def _get_operation_barang(
    db: Session,
    operation_id: str,
    expected_sku: str,
    env_id: int,
) -> Barang | None:
    operation = db.query(IntegrationStockOperation).filter(
        IntegrationStockOperation.operation_id == operation_id,
        IntegrationStockOperation.environment_id == env_id,
    ).first()
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
    request: Request,
    q: str | None = None,
    supplier_id: int | None = None,
    stok_status: Literal["aman", "menipis", "habis"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stock = func.coalesce(StokSaatIni.jumlah, 0)
    query = db.query(Barang).outerjoin(StokSaatIni)
    if (env_id := get_integration_env_id(request)) is not None:
        query = query.filter(Barang.environment_id == env_id)
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
    if supplier_id is not None:
        query = query.filter(or_(Barang.supplier_id == supplier_id, Barang.supplier_links.any(BarangSupplier.supplier_id == supplier_id)))
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
def get_integration_barang_meta(request: Request, db: Session = Depends(get_db)):
    env_id = _integration_env_id(request)
    suppliers = db.query(Supplier).filter(
        Supplier.environment_id == env_id
    ).order_by(func.lower(Supplier.nama), Supplier.id).all()
    values = {
        value.strip()
        for (value,) in db.query(Barang.satuan).filter(
            Barang.environment_id == env_id
        ).distinct().all()
        if value and value.strip()
    }
    values.add("pcs")
    return IntegrationBarangMetaOut(
        suppliers=[
            IntegrationSupplierMetaOut(
                id=item.id,
                kode_supplier=item.kode_supplier or "",
                nama_supplier=item.nama,
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
    request: Request,
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
        .filter(Barang.environment_id == _integration_env_id(request))
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


@router.get("/statistik", response_model=IntegrationBarangStatistikResponse)
def get_integration_barang_statistik(request: Request, db: Session = Depends(get_db)):
    stock = func.coalesce(StokSaatIni.jumlah, 0)
    rows = (
        db.query(Barang, stock.label("stok"))
        .outerjoin(StokSaatIni)
        .filter(Barang.environment_id == _integration_env_id(request))
        .order_by(stock, func.lower(Barang.nama), Barang.id)
        .all()
    )

    def item(barang: Barang, stok: int) -> IntegrationBarangStatistikItem:
        return IntegrationBarangStatistikItem(
            id=barang.id,
            sku=barang.sku or "",
            nama=barang.nama,
            stok=stok,
            stok_minimum=barang.stok_minimum or 0,
            satuan=barang.satuan or "pcs",
            foto=barang.foto,
        )

    # ponytail: lists include every item; add pagination when inventory grows large.
    stok_habis = [item(barang, stok) for barang, stok in rows if stok <= 0]
    stok_menipis = [
        item(barang, stok)
        for barang, stok in rows
        if 0 < stok <= (barang.stok_minimum or 0)
    ]
    return IntegrationBarangStatistikResponse(
        total_barang=len(rows),
        total_stok=sum(stok for _, stok in rows),
        total_stok_menipis=len(stok_menipis),
        total_stok_habis=len(stok_habis),
        stok_menipis=stok_menipis,
        stok_habis=stok_habis,
    )


@router.get("/by-sku/{sku}", response_model=IntegrationBarangOut)
def get_barang_by_sku(sku: str, db: Session = Depends(get_db), request: Request = None):
    barang = _get_by_sku_for_integration(db, _normalize_sku(sku), request)
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
    request: Request = None,
):
    operation_id = str(req.operation_id)
    previous_barang = _get_operation_barang(db, operation_id, req.sku, _integration_env_id(request))
    if previous_barang:
        return _to_integration_out(previous_barang)

    if _get_by_sku_for_integration(db, req.sku, request):
        raise HTTPException(status_code=409, detail="SKU already exists")
    _validate_supplier_id(db, req.supplier_id, _integration_env_id(request))

    barang = Barang(
        environment_id=_integration_env_id(request),
        sku=req.sku,
        nama=req.nama,
        merek=req.merek,
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
        db.add(StokSaatIni(environment_id=_integration_env_id(request), barang_id=barang.id, jumlah=0))
        db.flush()
        if req.jumlah_barang_masuk:
            record_stock_in(db, barang_id=barang.id, jumlah=req.jumlah_barang_masuk,
                harga_satuan=req.harga_beli, keterangan=_keterangan(operation_id),
                user_id=None, supplier_id=req.supplier_id)
        elif req.supplier_id is not None:
            db.add(BarangSupplier(environment_id=_integration_env_id(request), barang_id=barang.id, supplier_id=req.supplier_id, jumlah_masuk_kumulatif=0))
        db.add(
            IntegrationStockOperation(
                environment_id=_integration_env_id(request),
                operation_id=operation_id,
                barang_id=barang.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_barang = _get_operation_barang(db, operation_id, req.sku, _integration_env_id(request))
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
    request: Request = None,
):
    normalized_sku = _normalize_sku(sku)
    barang = _get_by_sku_for_integration(db, normalized_sku, request)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    operation_id = str(req.operation_id)
    previous_barang = _get_operation_barang(db, operation_id, normalized_sku, _integration_env_id(request))
    if previous_barang:
        return _to_integration_out(previous_barang)

    _validate_supplier_id(db, req.supplier_id, _integration_env_id(request))
    try:
        record_stock_in(
            db, barang_id=barang.id, jumlah=req.jumlah_barang_masuk,
            harga_satuan=req.harga_satuan, keterangan=_keterangan(operation_id),
            user_id=None, supplier_id=req.supplier_id,
        )
        db.add(
            IntegrationStockOperation(
                environment_id=_integration_env_id(request),
                operation_id=operation_id,
                barang_id=barang.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_barang = _get_operation_barang(db, operation_id, normalized_sku, _integration_env_id(request))
        if previous_barang:
            return _to_integration_out(previous_barang)
        raise
    except Exception:
        db.rollback()
        raise

    db.expire_all()
    barang = _get_by_sku_for_integration(db, normalized_sku, request)
    return _to_integration_out(barang)


@router.get("/{barang_id}", response_model=IntegrationBarangOut)
def get_integration_barang(
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    barang = _get_by_id_for_integration(db, barang_id, request)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    return _to_integration_out(barang)


@router.put("/{barang_id}", response_model=IntegrationBarangOut)
def update_integration_barang_by_id(
    req: IntegrationBarangMetadataUpdate,
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    barang = _get_by_id_for_integration(db, barang_id, request)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    supplied = req.model_fields_set
    if "sku" in supplied:
        duplicate = (
            db.query(Barang)
            .filter(
                Barang.sku == req.sku,
                Barang.id != barang.id,
                Barang.environment_id == _integration_env_id(request),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="SKU already exists")
    _validate_supplier_id(
        db,
        req.supplier_id if "supplier_id" in supplied else barang.supplier_id,
        _integration_env_id(request),
    )

    field_map = {"harga_beli": "harga_modal"}
    for field in supplied:
        setattr(barang, field_map.get(field, field), getattr(req, field))
    if "supplier_id" in supplied and req.supplier_id is not None:
        if not db.get(BarangSupplier, (barang.id, req.supplier_id)):
            db.add(BarangSupplier(environment_id=_integration_env_id(request), barang_id=barang.id, supplier_id=req.supplier_id, jumlah_masuk_kumulatif=0))
        winner = db.query(BarangSupplier).filter(
            BarangSupplier.barang_id == barang.id, BarangSupplier.jumlah_masuk_kumulatif > 0
        ).order_by(BarangSupplier.jumlah_masuk_kumulatif.desc(), BarangSupplier.supplier_id).first()
        if winner:
            barang.supplier_id = winner.supplier_id

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU already exists")
    except Exception:
        db.rollback()
        raise

    return _to_integration_out(_get_by_id_for_integration(db, barang.id, request))


@router.post("/{barang_id}/foto", response_model=IntegrationBarangOut)
async def upload_integration_barang_photo(
    file: UploadFile = File(...),
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    if not _get_by_id_for_integration(db, barang_id, request):
        raise HTTPException(status_code=404, detail="Barang not found")
    barang = _get_by_id_for_integration(db, barang_id, request)
    env_id = _integration_env_id(request)
    filename = await _save(file, env_id, STORAGE_DIR)
    old_photo = barang.foto
    try:
        add_photo(db, barang_id, filename, _integration_env_id(request), primary=True)
        db.commit()
    except Exception:
        db.rollback()
        try:
            os.remove(_photo_path(STORAGE_DIR, env_id, filename))
        except OSError:
            pass
        raise
    if old_photo and old_photo != filename:
        remove_unreferenced_file(db, old_photo, env_id, STORAGE_DIR)
    return _to_integration_out(_get_by_id_for_integration(db, barang_id, request))


@router.delete("/{barang_id}/foto", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration_barang_photo(
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    barang = _get_by_id_for_integration(db, barang_id, request)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    env_id = _integration_env_id(request)
    old_photo = barang.foto
    photo = db.query(BarangFoto).filter_by(
        environment_id=env_id, barang_id=barang_id, filename=old_photo
    ).first()
    if not photo:
        barang.foto = None
        db.commit()
        if old_photo:
            try:
                os.remove(_photo_path(STORAGE_DIR, env_id, old_photo))
            except OSError:
                pass
        return
    _delete_gallery_photo(barang_id, photo.id, db, None, env_id)


@router.delete("/{barang_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration_barang(
    barang_id: int = Path(ge=1),
    db: Session = Depends(get_db),
    request: Request = None,
):
    env_id = _integration_env_id(request)
    barang = _locked_barang(db, barang_id, env_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    if db.query(PrintJob.id).filter(
        PrintJob.barang_id == barang_id, PrintJob.environment_id == env_id
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Barang has print jobs and cannot be deleted",
        )
    photo_filenames = {
        photo.filename for photo in db.query(BarangFoto).filter_by(
            environment_id=env_id, barang_id=barang_id
        )
    }
    if barang.foto:
        photo_filenames.add(barang.foto)

    try:
        db.query(IntegrationStockOperation).filter(
            IntegrationStockOperation.barang_id == barang_id,
            IntegrationStockOperation.environment_id == env_id,
        ).delete(synchronize_session=False)
        db.query(TransaksiStok).filter(
            TransaksiStok.barang_id == barang_id,
            TransaksiStok.environment_id == env_id,
        ).delete(synchronize_session=False)
        db.query(StokSaatIni).filter(
            StokSaatIni.barang_id == barang_id,
            StokSaatIni.environment_id == env_id,
        ).delete(synchronize_session=False)
        db.query(Barang).filter(Barang.id == barang_id, Barang.environment_id == env_id).delete(
            synchronize_session=False
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.query(PrintJob.id).filter(
            PrintJob.barang_id == barang_id, PrintJob.environment_id == env_id
        ).first():
            raise HTTPException(
                status_code=409,
                detail="Barang has print jobs and cannot be deleted",
            )
        raise
    except Exception:
        db.rollback()
        raise

    for filename in photo_filenames:
        remove_unreferenced_file(db, filename, env_id, STORAGE_DIR)


@router.put("/by-sku/{sku}", response_model=IntegrationBarangOut)
def update_integration_barang(
    sku: str,
    req: IntegrationBarangUpdate,
    db: Session = Depends(get_db),
    request: Request = None,
):
    barang = _get_by_sku_for_integration(db, _normalize_sku(sku), request)
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
