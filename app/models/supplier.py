from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.database import Base


class Supplier(Base):
    __tablename__ = "supplier"
    __table_args__ = (UniqueConstraint("environment_id", "kode_supplier", name="uq_supplier_env_kode"),)

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True, index=True)
    kode_supplier = Column(String(50), nullable=True, index=True)
    nama = Column(String(150))
    kontak = Column(String(100), nullable=True)
    telepon = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    barang = relationship("Barang", back_populates="supplier")
    barang_links = relationship("BarangSupplier", back_populates="supplier")
