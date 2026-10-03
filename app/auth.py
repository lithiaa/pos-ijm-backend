import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import SupportGrant
from app.models.environment import Environment
from app.models.user import User
from config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

ALL_PERMISSIONS = [
    "barang.delete",
    "barang.read",
    "barang.write",
    "environment.settings",
    "foto.read",
    "foto.write",
    "logs.read",
    "stok.delete",
    "stok.read",
    "stok.write",
    "supplier.delete",
    "supplier.read",
    "supplier.write",
    "users.disable",
    "users.read",
    "users.write",
]

DEFAULT_STAFF_PERMISSIONS = [
    "barang.read",
    "barang.write",
    "foto.read",
    "foto.write",
    "stok.read",
    "stok.write",
    "supplier.read",
    "supplier.write",
]

DEFAULT_VIEWER_PERMISSIONS = [
    "barang.read",
    "foto.read",
    "stok.read",
    "supplier.read",
]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def normalize_permissions(raw: Any) -> list[str]:
    """Normalize permissions from list/set/tuple, JSON string, or comma-separated string."""
    if not raw:
        return []
    items: list[Any] = []
    if isinstance(raw, (list, tuple, set)):
        items = list(raw)
    elif isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned:
            return []
        if cleaned.startswith(("[", "{")) or "{" in cleaned or "[" in cleaned:
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, list):
                    items = parsed
                elif isinstance(parsed, dict):
                    items = [k for k, v in parsed.items() if v]
            except (json.JSONDecodeError, ValueError):
                return []
        else:
            items = [part.strip() for part in cleaned.split(",")]
    else:
        return []

    valid = {str(item).strip() for item in items if str(item).strip()}
    return sorted(valid)


def get_effective_permissions(user: User) -> list[str]:
    """Compute effective permission list based on user role and explicit permissions."""
    role = (user.role or "").lower()
    if role in ("admin", "platform_owner"):
        return sorted(ALL_PERMISSIONS)

    if user.permissions is not None:
        custom = normalize_permissions(user.permissions)
        return custom

    if role in ("staff", "karyawan"):
        return sorted(DEFAULT_STAFF_PERMISSIONS)
    if role == "viewer":
        return sorted(DEFAULT_VIEWER_PERMISSIONS)

    return []


def user_has_permission(user: User, permission: str) -> bool:
    """Check whether a user has a specific permission."""
    role = (user.role or "").lower()
    if role in ("admin", "platform_owner"):
        return True
    effective = user.effective_permissions
    if permission in effective or "*" in effective:
        return True
    resource, _, _ = permission.partition(".")
    if f"{resource}.*" in effective:
        return True
    return False


class AuthPrincipal:
    """Authenticated security principal holding user, resolved environment, and permissions."""

    def __init__(self, user: User, environment: Environment | None, permissions: list[str]):
        self.user = user
        self.environment = environment
        self.permissions = permissions

    @property
    def id(self) -> int:
        return self.user.id

    @property
    def username(self) -> str:
        return self.user.username

    @property
    def nama(self) -> str:
        return self.user.nama

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def email(self) -> str | None:
        return self.user.email

    @property
    def status(self) -> str:
        return self.user.status

    @property
    def is_platform_owner(self) -> bool:
        return (self.user.role or "").lower() == "platform_owner"

    def has_permission(self, permission: str) -> bool:
        return user_has_permission(self.user, permission)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.user, name)


def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> AuthPrincipal:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is disabled")

    env: Environment | None = None
    if user.environment_id is not None:
        env = db.query(Environment).filter(Environment.id == user.environment_id).first()
        if not env:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Environment not found")
        if env.status != "active":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Environment is suspended")

    permissions = get_effective_permissions(user)
    principal = AuthPrincipal(user=user, environment=env, permissions=permissions)

    request.state.audit_user_id = user.id
    request.state.audit_username = user.username
    request.state.audit_environment_id = user.environment_id
    return principal


def get_current_user(
    principal: AuthPrincipal = Depends(get_current_principal),
) -> User:
    user = principal.user
    user.effective_environment = principal.environment
    return user


def get_current_user_env_id(
    request: Request,
    support_grant_id: int | None = Header(None, alias="X-Support-Grant"),
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> int:
    """Return server-resolved environment ID for a domain route."""
    if principal.environment is not None:
        return principal.environment.id
    if principal.is_platform_owner:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        grant = db.query(SupportGrant).filter(
            SupportGrant.id == support_grant_id,
            SupportGrant.platform_owner_id == principal.id,
            SupportGrant.revoked_at.is_(None),
            SupportGrant.starts_at <= now,
            SupportGrant.expires_at > now,
        ).first()
        if not grant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Active support grant required")
        request.state.audit_environment_id = grant.environment_id
        request.state.audit_override = {
            "action": "SUPPORT",
            "resource": "support-access",
            "summary": {"support_grant_id": grant.id, "environment_id": grant.environment_id},
        }
        return grant.environment_id
    # Non-platform owner without environment_id is an error - they must be assigned to an environment
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User not assigned to an environment")


def require_permission(permission: str):
    """FastAPI dependency factory demanding a specific permission."""
    def dependency(principal: AuthPrincipal = Depends(get_current_principal)) -> AuthPrincipal:
        if not principal.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return principal

    return dependency
