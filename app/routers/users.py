import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthPrincipal, get_current_principal, hash_password
from app.database import get_db
from app.invites import Inviter, get_inviter, require_invite_delivery
from app.models.admin import Invitation
from app.models.user import User
from app.schemas.users import UserCreate, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


def _admin(principal: AuthPrincipal) -> int:
    if principal.role != "admin" or principal.user.environment_id is None:
        raise HTTPException(status_code=403, detail="Environment Administrator required")
    return principal.user.environment_id


def _out(user: User) -> dict:
    return {
        "id": user.id,
        "environment_id": user.environment_id,
        "username": user.username,
        "name": user.nama,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "permissions": sorted(json.loads(user.permissions)) if user.permissions else [],
    }


def _scoped_user(db: Session, user_id: int, environment_id: int) -> User:
    user = db.query(User).filter(User.id == user_id, User.environment_id == environment_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("")
def list_users(
    db: Session = Depends(get_db), principal: AuthPrincipal = Depends(get_current_principal)
):
    environment_id = _admin(principal)
    return [
        _out(user)
        for user in db.query(User)
        .filter(User.environment_id == environment_id, User.role.in_(("staff", "viewer")))
        .order_by(User.id)
        .all()
    ]


@router.get("/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    return _out(_scoped_user(db, user_id, _admin(principal)))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
    inviter: Inviter = Depends(get_inviter),
):
    environment_id = _admin(principal)
    require_invite_delivery(inviter)
    if db.query(User.id).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already used")
    if db.query(User.id).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already used")
    token = secrets.token_urlsafe(32)
    user = User(
        environment_id=environment_id,
        username=payload.username,
        password_hash="!invited",
        nama=payload.name,
        email=payload.email,
        role=payload.role,
        status="pending",
        must_change_password=True,
        permissions=json.dumps(payload.permissions),
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            Invitation(
                user_id=user.id,
                environment_id=environment_id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=48),
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or username already used")
    inviter.send_invitation(
        email=user.email,
        name=user.nama,
        token=token,
        environment_name=principal.environment.name,
    )
    db.refresh(user)
    request.state.audit_override = {
        "resource": "users",
        "resource_id": str(user.id),
        "summary": {"user_id": user.id, "role": user.role},
    }
    return _out(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    user = _scoped_user(db, user_id, _admin(principal))
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Administrator role cannot be changed here")
    if payload.name is not None:
        user.nama = payload.name
    if payload.role is not None:
        if payload.role == "platform_owner":
            raise HTTPException(status_code=403, detail="Administrator cannot assign platform_owner role")
        user.role = payload.role
    if payload.permissions is not None:
        user.permissions = json.dumps(payload.permissions)
    db.commit()
    db.refresh(user)
    return _out(user)


@router.post("/{user_id}/disable")
def disable_user(
    user_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    user = _scoped_user(db, user_id, _admin(principal))
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Administrator cannot be disabled here")
    user.status = "disabled"
    db.commit()
    return _out(user)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
    inviter: Inviter = Depends(get_inviter),
):
    user = _scoped_user(db, user_id, _admin(principal))
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Administrator cannot be reset here")
    require_invite_delivery(inviter)
    db.query(Invitation).filter(Invitation.user_id == user.id, Invitation.accepted_at.is_(None)).update(
        {Invitation.revoked_at: datetime.now(timezone.utc).replace(tzinfo=None)}
    )
    token = secrets.token_urlsafe(32)
    db.add(
        Invitation(
            user_id=user.id,
            environment_id=user.environment_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=48),
        )
    )
    user.status = "pending"
    user.password_hash = "!invited"
    user.must_change_password = True
    db.commit()
    inviter.send_invitation(email=user.email, name=user.nama, token=token, environment_name=principal.environment.name)
    request.state.audit_override = {"resource": "users", "resource_id": str(user.id), "summary": {"password_reset": True}}
    return {"ok": True}
