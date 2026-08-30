from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class IntegrationBarangCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=50)
    nama: str = Field(min_length=1, max_length=200)
    harga_beli: StrictInt = Field(ge=0)
    harga_beli_kode: str = Field(max_length=50)
    harga_jual: StrictInt = Field(ge=0)
    jumlah_barang_masuk: StrictInt = Field(ge=0)
    operation_id: UUID
    satuan: str = Field(default="pcs", min_length=1, max_length=20)
    merek: str | None = Field(default=None, max_length=100)
    kategori_id: int | None = None
    supplier_id: int | None = None
    stok_minimum: StrictInt = Field(default=5, ge=0)
    deskripsi: str | None = None

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("SKU must not be blank")
        return normalized

    @field_validator("nama", "satuan", "harga_beli_kode")
    @classmethod
    def strip_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("merek", "deskripsi")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class IntegrationBarangUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nama: str = Field(min_length=1, max_length=200)
    harga_beli: StrictInt = Field(ge=0)
    harga_beli_kode: str | None = Field(default=None, max_length=50)
    harga_jual: StrictInt = Field(ge=0)

    @field_validator("nama", "harga_beli_kode")
    @classmethod
    def strip_non_blank_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class IntegrationBarangMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, max_length=50)
    nama: str | None = Field(default=None, max_length=200)
    merek: str | None = Field(default=None, max_length=100)
    kategori_id: int | None = None
    supplier_id: int | None = None
    harga_beli: StrictInt | None = Field(default=None, ge=0)
    harga_beli_kode: str | None = Field(default=None, max_length=50)
    harga_jual: StrictInt | None = Field(default=None, ge=0)
    stok_minimum: StrictInt | None = Field(default=None, ge=0)
    satuan: str | None = Field(default=None, max_length=20)
    deskripsi: str | None = None

    @field_validator("sku")
    @classmethod
    def normalize_optional_sku(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("SKU must not be null")
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("SKU must not be blank")
        return normalized

    @field_validator("nama", "harga_beli_kode", "satuan")
    @classmethod
    def strip_optional_non_blank(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("value must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("harga_beli", "harga_jual", "stok_minimum")
    @classmethod
    def reject_null_numeric(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("value must not be null")
        return value

    @field_validator("merek", "deskripsi")
    @classmethod
    def strip_nullable_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class IntegrationStokMasuk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jumlah_barang_masuk: StrictInt = Field(ge=0)
    harga_satuan: StrictInt = Field(ge=0)
    operation_id: UUID


class IntegrationKategoriOut(BaseModel):
    id: int
    nama: str
    deskripsi: str | None


class IntegrationSupplierOut(BaseModel):
    id: int
    nama: str
    kontak: str | None
    telepon: str | None
    email: str | None


class IntegrationSupplierMetaOut(IntegrationSupplierOut):
    kode_supplier: str
    nama_supplier: str


class IntegrationBarangOut(BaseModel):
    id: int
    sku: str
    nama: str
    harga_beli: int
    harga_jual: int
    harga_beli_kode: str
    stok: int
    satuan: str
    merek: str | None
    foto: str | None
    foto_url: str | None
    kategori: IntegrationKategoriOut | None
    supplier: IntegrationSupplierOut | None
    stok_minimum: int
    stok_status: Literal["aman", "menipis", "habis"]
    deskripsi: str | None
    created_at: datetime | None
    updated_at: datetime | None


class IntegrationBarangSearchResponse(BaseModel):
    data: list[IntegrationBarangOut]


class IntegrationBarangListResponse(BaseModel):
    data: list[IntegrationBarangOut]
    total: int
    page: int
    limit: int


class IntegrationBarangMetaOut(BaseModel):
    categories: list[IntegrationKategoriOut]
    suppliers: list[IntegrationSupplierMetaOut]
    satuan: list[str]
