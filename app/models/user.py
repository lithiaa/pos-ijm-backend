from sqlalchemy import Column, Integer, String, DateTime, func
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(255))
    nama = Column(String(100))
    role = Column(String(20), default="karyawan")
    created_at = Column(DateTime, server_default=func.now())
