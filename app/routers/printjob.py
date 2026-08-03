from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.barang import Barang
from app.models.printjob import PrintJob

router = APIRouter(prefix="/api/print-jobs", tags=["print-jobs"])

class JobCreate(BaseModel):
    barang_id: int
    qty: int = 1

class JobUpdate(BaseModel):
    status: str
    error: Optional[str] = None

@router.post("/")
def create_job(req: JobCreate, db: Session = Depends(get_db)):
    barang = db.query(Barang).filter(Barang.id == req.barang_id).first()
    if not barang:
        raise HTTPException(404, "Barang not found")
    if not 1 <= req.qty <= 500:
        raise HTTPException(400, "qty must be 1-500")
    job = PrintJob(barang_id=req.barang_id, qty=req.qty, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"id": job.id, "status": job.status, "qty": job.qty, "barang_id": job.barang_id}

@router.get("/")
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(PrintJob, Barang).join(Barang, PrintJob.barang_id == Barang.id)
    if status:
        q = q.filter(PrintJob.status == status)
    q = q.order_by(PrintJob.id.asc())
    return [
        {
            "id": pj.id, "barang_id": pj.barang_id, "qty": pj.qty, "status": pj.status,
            "error": pj.error, "created_at": pj.created_at.isoformat() if pj.created_at else None,
            "printed_at": pj.printed_at.isoformat() if pj.printed_at else None,
            "barang": {"nama": b.nama, "sku": b.sku, "harga_jual": b.harga_jual, "harga_modal": b.harga_modal}
        }
        for pj, b in q.all()
    ]

@router.patch("/{job_id}")
def update_job(job_id: int, req: JobUpdate, db: Session = Depends(get_db)):
    if req.status not in ("pending", "printing", "done", "failed"):
        raise HTTPException(400, "Invalid status")
    job = db.query(PrintJob).filter(PrintJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    job.status = req.status
    if req.error:
        job.error = req.error
    if req.status in ("done", "failed"):
        job.printed_at = func.now()
    db.commit()
    return {"id": job.id, "status": job.status}
