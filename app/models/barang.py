from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Barang(Base):
    __tablename__ = "barang"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(50), unique=True, index=True)
    nama = Column(String(200))
    merek = Column(String(100), nullable=True)
    foto = Column(String(255), nullable=True)
    kategori_id = Column(Integer, ForeignKey("kategori.id"), nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)
    harga_modal = Column(Integer, default=0)
    harga_beli_kode = Column(String(50), nullable=True)
    harga_jual = Column(Integer, default=0)
    stok_minimum = Column(Integer, default=5)
    satuan = Column(String(20), default="pcs")
    deskripsi = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    kategori = relationship("Kategori")
    supplier = relationship("Supplier", back_populates="barang")
    stok = relationship("StokSaatIni", uselist=False, back_populates="barang")
