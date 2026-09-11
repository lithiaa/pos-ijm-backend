from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.database import Base


class UtcTimestamp(FunctionElement):
    type = DateTime()
    inherit_cache = True


@compiles(UtcTimestamp)
def _compile_utc_timestamp_default(_element, _compiler, **_kwargs):
    return "CURRENT_TIMESTAMP"


@compiles(UtcTimestamp, "mysql")
@compiles(UtcTimestamp, "mariadb")
def _compile_mysql_utc_timestamp_default(_element, _compiler, **_kwargs):
    return "(UTC_TIMESTAMP())"


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=UtcTimestamp(),
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username = Column(String(100), nullable=True, index=True)
    action = Column(String(10), nullable=False, index=True)
    http_method = Column(String(10), nullable=False)
    resource = Column(String(100), nullable=False, index=True)
    resource_id = Column(String(255), nullable=True, index=True)
    path = Column(String(500), nullable=False)
    status_code = Column(SmallInteger, nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    summary = Column(Text, nullable=False)
