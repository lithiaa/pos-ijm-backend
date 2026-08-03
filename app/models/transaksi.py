from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class StokSaatIni(Base):
    __tablename__ = "stok_saat_ini"

    barang_id = Column(Integer, ForeignKey("barang.id"), primary_key=True)
    jumlah = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    barang = relationship("Barang", back_populates="stok")


class TransaksiStok(Base):
    __tablename__ = "transaksi_stok"

    id = Column(Integer, primary_key=True, index=True)
    barang_id = Column(Integer, ForeignKey("barang.id"))
    jenis = Column(String(10))  # "masuk" / "keluar"
    jumlah = Column(Integer)
    harga_satuan = Column(Integer, nullable=True)
    total_harga = Column(Integer, nullable=True)
    keterangan = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    barang = relationship("Barang")
    user = relationship("User", foreign_keys=[user_id])
