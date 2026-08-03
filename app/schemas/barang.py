from pydantic import BaseModel
from typing import Optional


class BarangCreate(BaseModel):
    sku: Optional[str] = None
    nama: str
    merek: Optional[str] = None
    kategori_id: Optional[int] = None
    supplier_id: Optional[int] = None
    harga_modal: int = 0
    harga_jual_kode: str = "P"
    stok_minimum: int = 5
    satuan: str = "pcs"
    deskripsi: Optional[str] = None
    foto: Optional[str] = None
    stok_awal: int = 0


class BarangUpdate(BaseModel):
    nama: Optional[str] = None
    merek: Optional[str] = None
    kategori_id: Optional[int] = None
    supplier_id: Optional[int] = None
    harga_modal: Optional[int] = None
    harga_jual_kode: Optional[str] = None
    stok_minimum: Optional[int] = None
    satuan: Optional[str] = None
    deskripsi: Optional[str] = None
    foto: Optional[str] = None


class KategoriRef(BaseModel):
    id: int
    nama: str
    deskripsi: Optional[str] = None
    jumlah_barang: int = 0

    class Config:
        from_attributes = True


class SupplierRef(BaseModel):
    id: int
    nama: str
    kontak: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None
    jumlah_barang: int = 0

    class Config:
        from_attributes = True


class BarangOut(BaseModel):
    id: int
    sku: Optional[str] = None
    nama: str
    merek: Optional[str] = None
    kategori: Optional[KategoriRef] = None
    supplier: Optional[SupplierRef] = None
    harga_modal: int = 0
    harga_jual: int = 0
    harga_jual_kode: str = ""
    stok_minimum: int = 5
    satuan: str = "pcs"
    deskripsi: Optional[str] = None
    foto: Optional[str] = None
    stok: int = 0
    status: str = "Aman"
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class BarangListResponse(BaseModel):
    total: int
    page: int
    limit: int
    data: list[BarangOut]
