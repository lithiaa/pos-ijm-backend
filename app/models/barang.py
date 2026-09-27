from sqlalchemy import BigInteger, CheckConstraint, Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.database import Base


class Barang(Base):
    __tablename__ = "barang"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(50), unique=True, index=True)
    nama = Column(String(200))
    merek = Column(String(100), nullable=True)
    foto = Column(String(255), nullable=True)  # legacy alias for primary gallery photo
    shopee_url = Column(String(500), nullable=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id"), nullable=True)  # legacy primary alias
    harga_modal = Column(Integer, default=0)
    harga_beli_kode = Column(String(50), nullable=True)
    harga_jual = Column(Integer, default=0)
    stok_minimum = Column(Integer, default=5)
    satuan = Column(String(20), default="pcs")
    deskripsi = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    supplier = relationship("Supplier", back_populates="barang")
    stok = relationship("StokSaatIni", uselist=False, back_populates="barang")
    supplier_links = relationship("BarangSupplier", back_populates="barang", cascade="all, delete-orphan")
    photos = relationship("BarangFoto", back_populates="barang", cascade="all, delete-orphan", order_by="BarangFoto.urutan")


class BarangSupplier(Base):
    __tablename__ = "barang_supplier"
    __table_args__ = (CheckConstraint("jumlah_masuk_kumulatif >= 0", name="ck_barang_supplier_nonnegative"),)

    barang_id = Column(Integer, ForeignKey("barang.id", ondelete="CASCADE"), primary_key=True)
    supplier_id = Column(Integer, ForeignKey("supplier.id", ondelete="RESTRICT"), primary_key=True)
    jumlah_masuk_kumulatif = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    barang = relationship("Barang", back_populates="supplier_links")
    supplier = relationship("Supplier", back_populates="barang_links")


class BarangFoto(Base):
    __tablename__ = "barang_foto"
    __table_args__ = (UniqueConstraint("barang_id", "urutan", name="uq_barang_foto_order"),)

    id = Column(Integer, primary_key=True, index=True)
    barang_id = Column(Integer, ForeignKey("barang.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    urutan = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    barang = relationship("Barang", back_populates="photos")
