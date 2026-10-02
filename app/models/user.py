from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(255))
    nama = Column(String(100))
    email = Column(String(255), nullable=True, unique=True, index=True)
    role = Column(String(20), default="karyawan")
    status = Column(String(20), default="active", nullable=False, server_default="active")
    must_change_password = Column(Boolean, default=False, nullable=False, server_default=text("0"))
    permissions = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    environment = relationship("Environment", back_populates="users")

    @property
    def effective_permissions(self) -> list[str]:
        from app.auth import get_effective_permissions
        return get_effective_permissions(self)

    def has_permission(self, permission: str) -> bool:
        from app.auth import user_has_permission
        return user_has_permission(self, permission)
