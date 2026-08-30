from pydantic import BaseModel


class IntegrationSupplierDropdownOut(BaseModel):
    id: int
    kode_supplier: str
    nama_supplier: str


class IntegrationSupplierListResponse(BaseModel):
    data: list[IntegrationSupplierDropdownOut]
