from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Kategori(Base):
    __tablename__ = "kategori"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), unique=True)
    deskripsi = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
