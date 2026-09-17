from typing import Optional

from pydantic import BaseModel


class KatalogBarangOut(BaseModel):
    id: int
    slug: str
    sku: Optional[str] = None
    nama: str
    merek: Optional[str] = None
    harga_jual: int
    satuan: str
    deskripsi: Optional[str] = None
    foto_url: Optional[str] = None
    shopee_url: Optional[str] = None


class KatalogBarangListResponse(BaseModel):
    data: list[KatalogBarangOut]
    total: int
    page: int
    limit: int
