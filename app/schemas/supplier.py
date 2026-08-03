from pydantic import BaseModel
from typing import Optional


class SupplierCreate(BaseModel):
    nama: str
    kontak: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None


class SupplierUpdate(BaseModel):
    nama: Optional[str] = None
    kontak: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None


class SupplierOut(BaseModel):
    id: int
    nama: str
    kontak: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None
    jumlah_barang: int = 0

    class Config:
        from_attributes = True
