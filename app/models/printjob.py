from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.database import Base

class PrintJob(Base):
    __tablename__ = "print_jobs"

    id = Column(Integer, primary_key=True, index=True)
    barang_id = Column(Integer, ForeignKey("barang.id"))
    qty = Column(Integer, default=1)
    status = Column(String(20), default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    printed_at = Column(DateTime, nullable=True)
