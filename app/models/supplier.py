from sqlalchemy import Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base


class Supplier(Base):
    __tablename__ = "supplier"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(150))
    kontak = Column(String(100), nullable=True)
    telepon = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    barang = relationship("Barang", back_populates="supplier")
