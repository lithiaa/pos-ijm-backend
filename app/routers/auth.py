import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.admin import Invitation
from app.models.user import User
from app.schemas.auth import InvitationAccept, LoginRequest, TokenResponse
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_current_principal,
    AuthPrincipal,
)

router = APIRouter(tags=["auth"])


@router.post("/api/auth/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Username atau password salah")
    if user.status != "active":
        raise HTTPException(status_code=401, detail="User account is disabled")
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.post("/api/auth/invitations/accept")
def accept_invitation(req: InvitationAccept, request: Request, db: Session = Depends(get_db)):
    if not req.valid_password:
        raise HTTPException(status_code=422, detail="Password must contain at least 10 characters")
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    invitation = db.query(Invitation).filter(Invitation.token_hash == token_hash).first()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.accepted_at is not None or invitation.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Invitation no longer valid")
    if invitation.expires_at <= now:
        raise HTTPException(status_code=410, detail="Invitation expired")
    user = db.get(User, invitation.user_id)
    if not user or user.environment_id != invitation.environment_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    user.password_hash = hash_password(req.password)
    user.status = "active"
    user.must_change_password = False
    invitation.accepted_at = now
    db.commit()
    request.state.audit_environment_id = invitation.environment_id
    request.state.audit_override = {
        "resource": "invitations",
        "resource_id": str(invitation.id),
        "summary": {"accepted": True, "user_id": user.id},
    }
    return {"ok": True}


@router.get("/api/auth/me")
def get_me(principal: AuthPrincipal = Depends(get_current_principal)):
    user = principal.user
    env = principal.environment
    env_data = (
        {"id": env.id, "name": env.name, "status": env.status}
        if env is not None
        else None
    )
    return {
        "id": user.id,
        "username": user.username,
        "nama": user.nama,
        "role": user.role,
        "environment": env_data,
        "permissions": principal.permissions,
    }
