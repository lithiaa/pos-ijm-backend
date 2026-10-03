import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthPrincipal, get_current_principal
from app.database import get_db
from app.invites import Inviter, get_inviter
from app.models.admin import Invitation, ProvisionRequest, SupportGrant
from app.models.environment import Environment
from app.models.user import User
from app.schemas.admin import EnvironmentCreate, EnvironmentUpdate, SupportGrantCreate

router = APIRouter(prefix="/api/environments", tags=["environments"])


def _require_owner(principal: AuthPrincipal) -> None:
    if not principal.is_platform_owner or principal.user.environment_id is not None:
        raise HTTPException(status_code=403, detail="Platform Owner required")


def _response(environment: Environment, admin: User | None) -> dict:
    return {
        "id": environment.id,
        "slug": environment.slug,
        "name": environment.name,
        "status": environment.status,
        "administrator": None if admin is None else {
            "id": admin.id,
            "username": admin.username,
            "name": admin.nama,
            "email": admin.email,
            "status": admin.status,
        },
    }


@router.get("")
def list_environments(
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    _require_owner(principal)
    if page < 1 or not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    query = db.query(Environment).order_by(Environment.id)
    total = query.count()
    environments = query.offset((page - 1) * limit).limit(limit).all()
    administrators = {}
    for admin in db.query(User).filter(
        User.environment_id.in_([environment.id for environment in environments]),
        User.role == "admin",
    ).order_by(User.id):
        administrators.setdefault(admin.environment_id, admin)
    return {
        "data": [_response(environment, administrators.get(environment.id)) for environment in environments],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_environment(
    payload: EnvironmentCreate,
    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
    inviter: Inviter = Depends(get_inviter),
):
    _require_owner(principal)
    canonical = json.dumps(payload.model_dump(), sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.query(ProvisionRequest).filter_by(request_key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        environment = db.get(Environment, existing.environment_id)
        admin = db.get(User, existing.administrator_id)
        request.scope["state"]["audit_skip"] = True
        response.status_code = status.HTTP_200_OK
        return _response(environment, admin)

    if db.query(User.id).filter(User.email == payload.administrator.email).first():
        raise HTTPException(status_code=409, detail="Email already used")
    if db.query(User.id).filter(User.username == payload.administrator.username).first():
        raise HTTPException(status_code=409, detail="Username already used")
    if db.query(Environment.id).filter(Environment.slug == payload.slug).first():
        raise HTTPException(status_code=409, detail="Slug already used")

    token = secrets.token_urlsafe(32)
    environment = Environment(slug=payload.slug, name=payload.name, status="active")
    db.add(environment)
    try:
        db.flush()
        admin = User(
            environment_id=environment.id,
            username=payload.administrator.username,
            password_hash="!invited",
            nama=payload.administrator.name,
            email=payload.administrator.email,
            role="admin",
            status="pending",
            must_change_password=True,
        )
        db.add(admin)
        db.flush()
        db.add(
            Invitation(
                user_id=admin.id,
                environment_id=environment.id,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=48),
            )
        )
        db.add(
            ProvisionRequest(
                request_key=idempotency_key,
                request_hash=request_hash,
                environment_id=environment.id,
                administrator_id=admin.id,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Environment, user, or request already exists")
    except Exception:
        db.rollback()
        raise

    inviter.send_invitation(
        email=admin.email,
        name=admin.nama,
        token=token,
        environment_name=environment.name,
    )
    db.refresh(environment)
    db.refresh(admin)
    request.state.audit_override = {
        "resource": "environments",
        "resource_id": str(environment.id),
        "summary": {"environment_id": environment.id, "administrator_id": admin.id},
    }
    return _response(environment, admin)


@router.get("/{environment_id}")
def get_environment(
    environment_id: int,
    request: Request,
    support_grant_id: int | None = Header(None, alias="X-Support-Grant"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    environment = db.get(Environment, environment_id)
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    if principal.is_platform_owner:
        if support_grant_id is None:
            raise HTTPException(status_code=403, detail="Active support grant required")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        grant = db.query(SupportGrant).filter(
            SupportGrant.id == support_grant_id,
            SupportGrant.environment_id == environment_id,
            SupportGrant.platform_owner_id == principal.id,
            SupportGrant.revoked_at.is_(None),
            SupportGrant.starts_at <= now,
            SupportGrant.expires_at > now,
        ).first()
        if not grant:
            raise HTTPException(status_code=403, detail="Active support grant required")
        request.state.audit_environment_id = environment_id
        request.state.audit_environment_id = environment_id
        request.state.audit_override = {
            "action": "SUPPORT",
            "resource": "support-access",
            "resource_id": str(environment_id),
            "summary": {"support_grant_id": grant.id, "environment_id": environment_id},
        }
    elif principal.user.environment_id != environment_id:
        raise HTTPException(status_code=404, detail="Environment not found")
    return {"id": environment.id, "slug": environment.slug, "name": environment.name, "status": environment.status}


@router.patch("/{environment_id}")
def update_environment(
    environment_id: int,
    payload: EnvironmentUpdate,
    request: Request,
    support_grant_id: int | None = Header(None, alias="X-Support-Grant"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    fields = payload.model_fields_set
    lifecycle_fields = {"status"}
    settings_fields = fields - lifecycle_fields
    if principal.is_platform_owner:
        environment = db.get(Environment, environment_id)
        if settings_fields:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            grant = db.query(SupportGrant).filter(
                SupportGrant.id == support_grant_id,
                SupportGrant.environment_id == environment_id,
                SupportGrant.platform_owner_id == principal.id,
                SupportGrant.revoked_at.is_(None),
                SupportGrant.starts_at <= now,
                SupportGrant.expires_at > now,
            ).first()
            if not grant:
                raise HTTPException(status_code=403, detail="Active support grant required")
            request.state.audit_environment_id = environment_id
            request.state.audit_override = {
                "action": "SUPPORT",
                "resource": "environment-settings",
                "resource_id": str(environment_id),
                "summary": {"support_grant_id": grant.id, "fields": sorted(settings_fields)},
            }
    else:
        if lifecycle_fields & fields:
            raise HTTPException(status_code=403, detail="Platform Owner required")
        environment = db.query(Environment).filter(
            Environment.id == environment_id,
            Environment.id == principal.user.environment_id,
        ).first()
        if principal.role != "admin" or not principal.has_permission("environment.settings"):
            raise HTTPException(status_code=403, detail="Environment Administrator required")
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    for field in fields:
        setattr(environment, field, getattr(payload, field))
    db.commit()
    db.refresh(environment)
    return {"id": environment.id, "slug": environment.slug, "name": environment.name, "status": environment.status}


@router.post("/{environment_id}/suspend")
def suspend_environment(
    environment_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    _require_owner(principal)
    environment = db.get(Environment, environment_id)
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    environment.status = "suspended"
    db.commit(); db.refresh(environment)
    return {"id": environment.id, "status": environment.status}


@router.post("/{environment_id}/support-access", status_code=status.HTTP_201_CREATED)
def create_support_grant(
    environment_id: int,
    payload: SupportGrantCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    _require_owner(principal)
    if not db.get(Environment, environment_id):
        raise HTTPException(status_code=404, detail="Environment not found")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    grant = SupportGrant(
        environment_id=environment_id,
        platform_owner_id=principal.id,
        reason=payload.reason,
        starts_at=now,
        expires_at=now + timedelta(minutes=payload.duration_minutes),
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    request.state.audit_environment_id = environment_id
    request.state.audit_override = {
        "resource": "support-access",
        "resource_id": str(grant.id),
        "summary": {"support_grant_id": grant.id, "duration_minutes": payload.duration_minutes},
    }
    return {"id": grant.id, "environment_id": environment_id, "starts_at": grant.starts_at, "expires_at": grant.expires_at, "status": "active"}


@router.post("/{environment_id}/support-access/{grant_id}/revoke")
def revoke_support_grant(
    environment_id: int,
    grant_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    _require_owner(principal)
    grant = db.query(SupportGrant).filter(
        SupportGrant.id == grant_id,
        SupportGrant.environment_id == environment_id,
        SupportGrant.platform_owner_id == principal.id,
    ).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Support grant not found")
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        grant.revoked_by_user_id = principal.id
        db.commit()
    request.state.audit_environment_id = environment_id
    request.state.audit_override = {
        "resource": "support-access",
        "resource_id": str(grant.id),
        "summary": {"support_grant_id": grant.id, "revoked": True},
    }
    return {"ok": True}
