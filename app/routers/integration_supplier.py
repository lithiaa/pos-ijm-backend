from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.integration_auth import get_integration_env_id, require_integration_key
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
def list_integration_suppliers(request: Request, db: Session = Depends(get_db)):
    query = db.query(Supplier)
    if (env_id := get_integration_env_id(request)) is not None:
        query = query.filter(Supplier.environment_id == env_id)
    suppliers = (
        query
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
