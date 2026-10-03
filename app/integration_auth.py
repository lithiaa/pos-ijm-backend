import secrets
from contextvars import ContextVar
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

integration_environment_id: ContextVar[int | None] = ContextVar("integration_environment_id", default=None)


def current_integration_env_id() -> int | None:
    return integration_environment_id.get()


def _set_integration_env(request: Request, env_id: int) -> None:
    request.state.integration_env_id = env_id
    integration_environment_id.set(env_id)


from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.environment import Environment
from app.models.user import User
from config import ALGORITHM, POS_INTEGRATION_KEY, SECRET_KEY

ALLOWED_ROLES = {"admin", "karyawan"}


def get_integration_env_id(request: Request) -> int | None:
    return getattr(request.state, "integration_env_id", None)


def require_integration_key(
    request: Request,
    authorization: Annotated[
        str | None,
        Header(alias="Authorization"),
    ] = None,
    x_integration_key: Annotated[
        str | None,
        Header(alias="X-Integration-Key"),
    ] = None,
    db: Session = Depends(get_db),
) -> None:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                user_id = int(payload.get("sub"))
                user = db.get(User, user_id)
            except (JWTError, TypeError, ValueError):
                user = None

            if (
                user
                and user.status == "active"
                and user.role in ALLOWED_ROLES
                and (user.environment is None or user.environment.status == "active")
            ):
                request.state.audit_user_id = user.id
                request.state.audit_username = user.username
                request.state.audit_environment_id = user.environment_id
                _set_integration_env(request, user.environment_id)
                return

    supplied = (x_integration_key or "").encode("utf-8")
    configured = POS_INTEGRATION_KEY.encode("utf-8")
    if POS_INTEGRATION_KEY and secrets.compare_digest(supplied, configured):
        # Integration key only grants access to the hardcoded legacy environment
        legacy = db.query(Environment).filter(Environment.slug == "lithia-autoparts").first()
        if not legacy:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Legacy environment not found",
            )
        request.state.audit_username = "integration"
        _set_integration_env(request, legacy.id)
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )
