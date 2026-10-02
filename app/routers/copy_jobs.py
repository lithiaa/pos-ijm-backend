import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthPrincipal, get_current_principal
from app.database import get_db
from app.models.admin import EnvironmentCopyJob
from app.models.environment import Environment
from app.schemas.copy_job import CopyJobCreate
from app.services.environment_copy import run_copy_job

router = APIRouter(prefix="/api/environment-copy-jobs", tags=["environment-copy-jobs"])


def _owner(principal: AuthPrincipal) -> None:
    if not principal.is_platform_owner or principal.user.environment_id is not None:
        raise HTTPException(status_code=403, detail="Platform Owner required")


def _out(job: EnvironmentCopyJob) -> dict:
    return {
        "id": job.id,
        "source_environment_id": job.source_environment_id,
        "target_environment_id": job.target_environment_id,
        "status": job.status,
        "progress": job.progress,
        "result": json.loads(job.result) if job.result else None,
        "error": job.error,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_copy_job(
    payload: CopyJobCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=200),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    _owner(principal)
    if payload.source_environment_id == payload.target_environment_id:
        raise HTTPException(status_code=422, detail="Source and target must differ")
    if not db.get(Environment, payload.source_environment_id) or not db.get(Environment, payload.target_environment_id):
        raise HTTPException(status_code=404, detail="Environment not found")
    options = payload.model_dump()
    canonical = json.dumps(options, sort_keys=True, separators=(",", ":"))
    request_hash = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.query(EnvironmentCopyJob).filter_by(target_environment_id=payload.target_environment_id, request_key=idempotency_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency key already used")
        if existing.status == "failed":
            existing.error = None
            existing.completed_at = None
            existing.status = "pending"
            db.commit()
            try:
                run_copy_job(db, existing)
            except Exception as exc:
                failed = db.get(EnvironmentCopyJob, existing.id)
                failed.status = "failed"
                failed.error = str(exc)[:2000]
                failed.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                raise HTTPException(status_code=409, detail="Copy job failed")
            db.refresh(existing)
        response.status_code = status.HTTP_200_OK
        return _out(existing)
    job = EnvironmentCopyJob(
        request_key=idempotency_key,
        source_environment_id=payload.source_environment_id,
        target_environment_id=payload.target_environment_id,
        requested_by_user_id=principal.id,
        options=canonical,
        request_hash=request_hash,
        status="pending",
    )
    db.add(job); db.commit(); db.refresh(job)
    try:
        run_copy_job(db, job)
    except Exception as exc:
        failed = db.get(EnvironmentCopyJob, job.id)
        failed.status = "failed"
        failed.error = str(exc)[:2000]
        failed.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise HTTPException(status_code=409, detail="Copy job failed")
    db.refresh(job)
    return _out(job)


@router.get("/{job_id}")
def get_copy_job(job_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(get_current_principal)):
    _owner(principal)
    job = db.get(EnvironmentCopyJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Copy job not found")
    return _out(job)


@router.post("/{job_id}/cancel")
def cancel_copy_job(job_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(get_current_principal)):
    _owner(principal)
    job = db.get(EnvironmentCopyJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Copy job not found")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending jobs can be cancelled")
    job.status = "cancelled"
    job.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return _out(job)
