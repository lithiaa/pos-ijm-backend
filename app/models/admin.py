from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class ProvisionRequest(Base):
    __tablename__ = "environment_provision_requests"

    id = Column(Integer, primary_key=True)
    request_key = Column(String(200), unique=True, nullable=False, index=True)
    request_hash = Column(String(64), nullable=False)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False)
    administrator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Invitation(Base):
    __tablename__ = "user_invitations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class SupportGrant(Base):
    __tablename__ = "support_grants"

    id = Column(Integer, primary_key=True)
    environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    platform_owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class EnvironmentCopyJob(Base):
    __tablename__ = "environment_copy_jobs"
    __table_args__ = (
        UniqueConstraint("target_environment_id", "request_key", name="uq_copy_target_request"),
    )

    id = Column(Integer, primary_key=True)
    request_key = Column(String(200), nullable=False)
    source_environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    target_environment_id = Column(Integer, ForeignKey("environments.id"), nullable=False, index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    options = Column(Text, nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0, server_default="0")
    result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
