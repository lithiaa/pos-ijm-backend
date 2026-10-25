from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String

from app.database import Base


class PesananSupplier(Base):
    __tablename__ = "pesanan_supplier"
    __table_args__ = (
        CheckConstraint("jumlah_barang > 0", name="ck_pesanan_supplier_jumlah_positive"),
        CheckConstraint("length(trim(nama_barang)) > 0", name="ck_pesanan_supplier_nama_nonblank"),
        CheckConstraint(
            "status IN ('pending', 'dipesan', 'diterima', 'dibatalkan')",
            name="ck_pesanan_supplier_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False)
    nama_barang = Column(String(200), nullable=False)
    jumlah_barang = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
