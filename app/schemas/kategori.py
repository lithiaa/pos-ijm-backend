from pydantic import BaseModel
from typing import Optional


class KategoriCreate(BaseModel):
    nama: str
    deskripsi: Optional[str] = None


class KategoriUpdate(BaseModel):
    nama: Optional[str] = None
    deskripsi: Optional[str] = None


class KategoriOut(BaseModel):
    id: int
    nama: str
    deskripsi: Optional[str] = None
    jumlah_barang: int = 0

    class Config:
        from_attributes = True
