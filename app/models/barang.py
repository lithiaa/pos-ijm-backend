from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class Barang(Base):
    __tablename__ = "barang"
    __table_args__ = (
        UniqueConstraint("environment_id", "sku", name="uq_barang_env_sku"),
        UniqueConstraint("id", "environment_id", name="uq_barang_id_env"),
        ForeignKeyConstraint(
            ("supplier_id", "environment_id"),
            ("supplier.id", "supplier.environment_id"),
            name="fk_barang_supplier_env",
            ondelete="RESTRICT",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    sku = Column(String(50), index=True)
    nama = Column(String(200))
    merek = Column(String(100), nullable=True)
    foto = Column(String(255), nullable=True)  # legacy alias for primary gallery photo
    shopee_url = Column(String(500), nullable=True)
    supplier_id = Column(Integer, nullable=True)  # legacy primary alias
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
    supplier_links = relationship("BarangSupplier", back_populates="barang", cascade="all, delete-orphan", overlaps="barang_links,supplier")
    photos = relationship("BarangFoto", back_populates="barang", cascade="all, delete-orphan", order_by="BarangFoto.urutan")


class BarangSupplier(Base):
    __tablename__ = "barang_supplier"
    __table_args__ = (
        CheckConstraint("jumlah_masuk_kumulatif >= 0", name="ck_barang_supplier_nonnegative"),
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_barang_supplier_barang_env",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("supplier_id", "environment_id"),
            ("supplier.id", "supplier.environment_id"),
            name="fk_barang_supplier_supplier_env",
            ondelete="RESTRICT",
        ),
    )

    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    barang_id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, primary_key=True)
    jumlah_masuk_kumulatif = Column(BigInteger, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    barang = relationship("Barang", back_populates="supplier_links", overlaps="barang_links,supplier")
    supplier = relationship("Supplier", back_populates="barang_links", overlaps="barang,supplier_links")


class BarangFoto(Base):
    __tablename__ = "barang_foto"
    __table_args__ = (
        UniqueConstraint("barang_id", "urutan", name="uq_barang_foto_order"),
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_barang_foto_barang_env",
            ondelete="CASCADE",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    barang_id = Column(Integer, nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    urutan = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    barang = relationship("Barang", back_populates="photos")
