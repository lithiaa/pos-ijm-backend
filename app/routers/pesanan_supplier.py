from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy.orm import Session

from app.auth import get_current_user_env_id, require_permission
from app.database import get_db
from app.models.pesanan_supplier import PesananSupplier

router = APIRouter(prefix="/api/pesanan-supplier", tags=["pesanan-supplier"])

NamaBarang = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)
]
JumlahBarang = Annotated[int, Field(strict=True, gt=0)]
Status = Literal["pending", "dipesan", "diterima", "dibatalkan"]


class PesananSupplierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nama_barang: NamaBarang
    jumlah_barang: JumlahBarang
    status: Status = "pending"


class PesananSupplierUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nama_barang: NamaBarang | None = None
    jumlah_barang: JumlahBarang | None = None
    status: Status | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null(cls, values):
        if isinstance(values, dict) and any(value is None for value in values.values()):
            raise ValueError("Fields cannot be null")
        return values


def _get_pesanan(db: Session, environment_id: int, pesanan_id: int) -> PesananSupplier:
    pesanan = (
        db.query(PesananSupplier)
        .filter_by(id=pesanan_id, environment_id=environment_id)
        .first()
    )
    if pesanan is None:
        raise HTTPException(status_code=404, detail="Pesanan supplier not found")
    return pesanan


@router.get("/", dependencies=[Depends(require_permission("supplier.read"))])
def list_pesanan_supplier(
    db: Session = Depends(get_db),
    environment_id: int = Depends(get_current_user_env_id),
):
    return db.query(PesananSupplier).filter_by(environment_id=environment_id).all()


@router.get("/{pesanan_id}", dependencies=[Depends(require_permission("supplier.read"))])
def detail_pesanan_supplier(
    pesanan_id: int,
    db: Session = Depends(get_db),
    environment_id: int = Depends(get_current_user_env_id),
):
    return _get_pesanan(db, environment_id, pesanan_id)


@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("supplier.write"))])
def create_pesanan_supplier(
    payload: PesananSupplierCreate,
    db: Session = Depends(get_db),
    environment_id: int = Depends(get_current_user_env_id),
):
    pesanan = PesananSupplier(environment_id=environment_id, **payload.model_dump())
    db.add(pesanan)
    db.commit()
    db.refresh(pesanan)
    return pesanan


@router.put("/{pesanan_id}", dependencies=[Depends(require_permission("supplier.write"))])
def update_pesanan_supplier(
    pesanan_id: int,
    payload: PesananSupplierUpdate,
    db: Session = Depends(get_db),
    environment_id: int = Depends(get_current_user_env_id),
):
    pesanan = _get_pesanan(db, environment_id, pesanan_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pesanan, field, value)
    db.commit()
    db.refresh(pesanan)
    return pesanan


@router.delete("/{pesanan_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("supplier.delete"))])
def delete_pesanan_supplier(
    pesanan_id: int,
    db: Session = Depends(get_db),
    environment_id: int = Depends(get_current_user_env_id),
):
    db.delete(_get_pesanan(db, environment_id, pesanan_id))
    db.commit()
