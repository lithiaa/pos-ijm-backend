from sqlalchemy.orm import Session

from app.models.supplier import Supplier


def assign_supplier_code(db: Session, supplier: Supplier, env_id: int) -> None:
    db.flush()
    number = supplier.id
    while db.query(Supplier.id).filter(
        Supplier.kode_supplier == f"SUP-{number:03d}",
        Supplier.id != supplier.id,
        Supplier.environment_id == env_id,
    ).first():
        number += 1
    supplier.kode_supplier = f"SUP-{number:03d}"
