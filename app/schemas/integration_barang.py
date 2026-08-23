from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class IntegrationBarangCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=50)
    nama: str = Field(min_length=1, max_length=200)
    harga_beli: StrictInt = Field(ge=0)
    harga_jual: StrictInt = Field(ge=0)
    jumlah_barang_masuk: StrictInt = Field(ge=0)
    operation_id: UUID
    satuan: str = Field(default="pcs", min_length=1, max_length=20)

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("SKU must not be blank")
        return normalized

    @field_validator("nama", "satuan")
    @classmethod
    def strip_non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class IntegrationBarangUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nama: str = Field(min_length=1, max_length=200)
    harga_beli: StrictInt = Field(ge=0)
    harga_jual: StrictInt = Field(ge=0)

    @field_validator("nama")
    @classmethod
    def strip_non_blank_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized


class IntegrationStokMasuk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jumlah_barang_masuk: StrictInt = Field(ge=0)
    harga_satuan: StrictInt = Field(ge=0)
    operation_id: UUID


class IntegrationBarangOut(BaseModel):
    id: int
    sku: str
    nama: str
    harga_beli: int
    harga_jual: int
    harga_beli_kode: str
    stok: int
    satuan: str
