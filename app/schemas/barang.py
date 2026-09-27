from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_shopee_url(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or (parsed.hostname != "shopee.co.id" and not parsed.hostname.endswith(".shopee.co.id"))
    ):
        raise ValueError("shopee_url must be an https Shopee Indonesia URL")
    return normalized


class BarangCreate(BaseModel):
    # The supplier relation accepts an ID only; null means no supplier.
    model_config = ConfigDict(extra="forbid")

    sku: Optional[str] = None
    nama: str
    merek: Optional[str] = None
    supplier_id: Optional[int] = None
    harga_modal: int = 0
    harga_beli_kode: Optional[str] = Field(default=None, max_length=50)
    harga_jual_kode: Optional[str] = None
    harga_jual: Optional[int] = None
    stok_minimum: int = 5

    @field_validator("harga_beli_kode")
    @classmethod
    def strip_buy_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("buy code must not be blank")
        return normalized
    satuan: str = "pcs"
    deskripsi: Optional[str] = None
    foto: Optional[str] = None
    shopee_url: Optional[str] = Field(default=None, max_length=500)
    stok_awal: int = 0

    _normalize_shopee_url = field_validator("shopee_url")(normalize_shopee_url)


class BarangUpdate(BaseModel):
    # An omitted supplier preserves it; explicit null clears it.
    model_config = ConfigDict(extra="forbid")

    sku: Optional[str] = None
    nama: Optional[str] = None
    merek: Optional[str] = None
    supplier_id: Optional[int] = None
    harga_modal: Optional[int] = None
    harga_beli_kode: Optional[str] = Field(default=None, max_length=50)
    harga_jual_kode: Optional[str] = None
    harga_jual: Optional[int] = None
    stok_minimum: Optional[int] = None

    @field_validator("harga_beli_kode")
    @classmethod
    def strip_buy_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("buy code must not be blank")
        return normalized
    satuan: Optional[str] = None
    deskripsi: Optional[str] = None
    foto: Optional[str] = None
    shopee_url: Optional[str] = Field(default=None, max_length=500)

    _normalize_shopee_url = field_validator("shopee_url")(normalize_shopee_url)


class SupplierRef(BaseModel):
    id: int
    kode_supplier: Optional[str] = None
    nama: str
    nama_supplier: str
    kontak: Optional[str] = None
    telepon: Optional[str] = None
    email: Optional[str] = None
    jumlah_barang: int = 0

    class Config:
        from_attributes = True


class BarangSupplierOut(SupplierRef):
    jumlah_masuk_kumulatif: int
    is_primary: bool


class BarangPhotoOut(BaseModel):
    id: int
    filename: str
    foto: str
    foto_url: str
    urutan: int
    is_primary: bool
    created_at: Optional[str] = None


class BarangOut(BaseModel):
    id: int
    sku: Optional[str] = None
    nama: str
    merek: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier: Optional[SupplierRef] = None
    supplier_nama: str = ""
    primary_supplier_id: Optional[int] = None
    primary_supplier: Optional[SupplierRef] = None
    suppliers: list[BarangSupplierOut] = []
    harga_modal: int = 0
    harga_beli_kode: str = ""
    harga_jual: int = 0
    harga_jual_kode: str = ""
    stok_minimum: int = 5
    satuan: str = "pcs"
    deskripsi: Optional[str] = None
    foto: Optional[str] = None
    foto_url: Optional[str] = None
    photos: list[BarangPhotoOut] = []
    shopee_url: Optional[str] = None
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
