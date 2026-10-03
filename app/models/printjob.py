from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func

from app.database import Base


class PrintJob(Base):
    __tablename__ = "print_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ("barang_id", "environment_id"),
            ("barang.id", "barang.environment_id"),
            name="fk_print_jobs_barang_env",
            ondelete="RESTRICT",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    barang_id = Column(Integer, nullable=True)
    qty = Column(Integer, default=1)
    status = Column(String(20), default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    printed_at = Column(DateTime, nullable=True)
