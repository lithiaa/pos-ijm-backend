import os
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid

from app.database import get_db
from app.models.barang import Barang

# Go up twice: app/routers/ -> app/ -> toko-sparepart/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.path.join(BASE_DIR, "storage/foto-barang")
os.makedirs(STORAGE_DIR, exist_ok=True)

router = APIRouter()


@router.post("/api/upload/foto/{barang_id}")
async def upload_foto_barang(barang_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    db_barang = db.query(Barang).filter(Barang.id == barang_id).first()
    if not db_barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    _, ext = os.path.splitext(file.filename)
    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(STORAGE_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    db_barang.foto = filename
    db.commit()

    foto_url = f"/storage/foto-barang/{filename}"
    return {"foto_url": foto_url}
