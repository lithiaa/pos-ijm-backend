import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from config import ALGORITHM, POS_INTEGRATION_KEY, SECRET_KEY

ALLOWED_ROLES = {"admin", "karyawan"}


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

            if user and user.role in ALLOWED_ROLES:
                request.state.audit_user_id = user.id
                request.state.audit_username = user.username
                return

    supplied = (x_integration_key or "").encode("utf-8")
    configured = POS_INTEGRATION_KEY.encode("utf-8")
    if POS_INTEGRATION_KEY and secrets.compare_digest(supplied, configured):
        request.state.audit_username = "integration"
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )
