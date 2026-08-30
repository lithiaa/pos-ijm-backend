from pydantic import BaseModel, Field, field_validator


class SupplierCreate(BaseModel):
    kode_supplier: str | None = Field(default=None, max_length=50)
    nama: str = Field(max_length=150)
    kontak: str | None = None
    telepon: str | None = None
    email: str | None = None

    @field_validator("kode_supplier")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("kode_supplier must not be blank")
        return normalized

    @field_validator("nama")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("nama must not be blank")
        return normalized


class SupplierUpdate(BaseModel):
    kode_supplier: str | None = Field(default=None, max_length=50)
    nama: str | None = Field(default=None, max_length=150)
    kontak: str | None = None
    telepon: str | None = None
    email: str | None = None

    @field_validator("kode_supplier")
    @classmethod
    def normalize_code(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("kode_supplier must not be null")
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("kode_supplier must not be blank")
        return normalized

    @field_validator("nama")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("nama must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("nama must not be blank")
        return normalized


class SupplierOut(BaseModel):
    id: int
    kode_supplier: str | None = None
    nama: str
    nama_supplier: str
    kontak: str | None = None
    telepon: str | None = None
    email: str | None = None
    jumlah_barang: int = 0
