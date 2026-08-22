import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from config import POS_INTEGRATION_KEY


def require_integration_key(
    x_integration_key: Annotated[
        str | None,
        Header(alias="X-Integration-Key"),
    ] = None,
) -> None:
    supplied = (x_integration_key or "").encode("utf-8")
    configured = POS_INTEGRATION_KEY.encode("utf-8")
    matches = secrets.compare_digest(supplied, configured)

    if not POS_INTEGRATION_KEY or not matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
