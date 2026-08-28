from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.integration_auth import require_integration_key
from app.models.barang import Barang
from app.models.transaksi import (
    IntegrationStockOperation,
    StokSaatIni,
    TransaksiStok,
)
from app.schemas.integration_barang import (
    IntegrationBarangCreate,
    IntegrationBarangOut,
    IntegrationBarangSearchResponse,
    IntegrationBarangUpdate,
    IntegrationStokMasuk,
)


router = APIRouter(
    prefix="/api/integration/barang",
    tags=["integration-barang"],
    dependencies=[Depends(require_integration_key)],
)

INTEGRATION_KETERANGAN_PREFIX = (
    "Niimbot label integration | NIIMBOT_OPERATION_ID="
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
        harga_beli_kode=barang.harga_beli_kode or "",
        stok=barang.stok.jumlah if barang.stok else 0,
        satuan=barang.satuan or "pcs",
    )


def _keterangan(operation_id: str) -> str:
    return f"{INTEGRATION_KETERANGAN_PREFIX}{operation_id}"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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

    barang = Barang(
        sku=req.sku,
        nama=req.nama,
        harga_modal=req.harga_beli,
        harga_beli_kode=req.harga_beli_kode,
        harga_jual=req.harga_jual,
        satuan=req.satuan,
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
