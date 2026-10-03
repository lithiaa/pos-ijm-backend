from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class StokSaatIni(Base):
    __tablename__ = "stok_saat_ini"
    __table_args__ = (
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_stok_saat_ini_barang_env",
            ondelete="RESTRICT",
        ),
    )

    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    barang_id = Column(Integer, primary_key=True)
    jumlah = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    barang = relationship("Barang", back_populates="stok")


class TransaksiStok(Base):
    __tablename__ = "transaksi_stok"
    __table_args__ = (
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_transaksi_stok_barang_env",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("supplier_id", "environment_id"),
            ("supplier.id", "supplier.environment_id"),
            name="fk_transaksi_stok_supplier_env",
            ondelete="RESTRICT",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    barang_id = Column(Integer)
    supplier_id = Column(Integer, nullable=True, index=True)
    jenis = Column(String(10))  # "masuk" / "keluar"
    jumlah = Column(Integer)
    harga_satuan = Column(Integer, nullable=True)
    total_harga = Column(BigInteger, nullable=True)
    keterangan = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    barang = relationship("Barang")
    user = relationship("User", foreign_keys=[user_id])
    supplier = relationship("Supplier", foreign_keys=[supplier_id])


class IntegrationStockOperation(Base):
    __tablename__ = "integration_stock_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_integration_stock_operations_barang_env",
            ondelete="CASCADE",
        ),
    )

    environment_id = Column(Integer, ForeignKey("environments.id"), primary_key=True)
    operation_id = Column(String(36), primary_key=True)
    barang_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    barang = relationship("Barang")
