from pydantic import BaseModel
from typing import Optional


class StokMasukRequest(BaseModel):
    barang_id: int
    jumlah: int
    harga_satuan: Optional[int] = None
    keterangan: Optional[str] = None


class StokKeluarRequest(BaseModel):
    barang_id: int
    jumlah: int
    keterangan: Optional[str] = None


class TransaksiOut(BaseModel):
    id: int
    tanggal: str
    nama_barang: str
    jenis: str
    jumlah: int
    harga_satuan: Optional[int] = None
    total_harga: Optional[int] = None
    keterangan: Optional[str] = None
    user: Optional[str] = None

    class Config:
        from_attributes = True


class TransaksiListResponse(BaseModel):
    total: int
    page: int
    limit: int
    data: list[TransaksiOut]


class DashboardResponse(BaseModel):
    total_barang: int = 0
    stok_menipis: int = 0
    barang_masuk_hari_ini: int = 0
    barang_keluar_hari_ini: int = 0
    grafik_stok_menipis: list[dict] = []
    transaksi_terbaru: list[TransaksiOut] = []
    laba_bulan_ini: int = 0
