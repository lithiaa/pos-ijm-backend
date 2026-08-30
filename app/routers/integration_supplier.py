from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.integration_auth import require_integration_key
from app.models.supplier import Supplier
from app.schemas.integration_supplier import (
    IntegrationSupplierDropdownOut,
    IntegrationSupplierListResponse,
)


router = APIRouter(
    prefix="/api/integration/suppliers",
    tags=["integration-suppliers"],
    dependencies=[Depends(require_integration_key)],
)


@router.get("", response_model=IntegrationSupplierListResponse)
def list_integration_suppliers(db: Session = Depends(get_db)):
    suppliers = (
        db.query(Supplier)
        .order_by(
            func.lower(func.coalesce(Supplier.kode_supplier, "")),
            func.lower(Supplier.nama),
            Supplier.id,
        )
        .all()
    )
    return IntegrationSupplierListResponse(
        data=[
            IntegrationSupplierDropdownOut(
                id=supplier.id,
                kode_supplier=supplier.kode_supplier or "",
                nama_supplier=supplier.nama,
            )
            for supplier in suppliers
        ]
    )
