import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.barang import Barang, BarangFoto

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.path.join(BASE_DIR, "storage/foto-barang")
os.makedirs(STORAGE_DIR, exist_ok=True)
MAX_PHOTO_BYTES = 5 * 1024 * 1024
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

router = APIRouter()


def _valid_image(content_type: str, data: bytes) -> bool:
    if content_type == "image/jpeg": return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png": return data.startswith(b"\x89PNG\r\n\x1a\n")
    return content_type == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


async def _save(file: UploadFile) -> str:
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if file.content_type not in EXTENSIONS or not data or len(data) > MAX_PHOTO_BYTES or not _valid_image(file.content_type, data):
        raise HTTPException(status_code=422, detail="Foto harus JPEG, PNG, atau WebP valid maksimal 5MB")
    filename = f"{uuid.uuid4()}{EXTENSIONS[file.content_type]}"
    os.makedirs(STORAGE_DIR, exist_ok=True)
    with open(os.path.join(STORAGE_DIR, filename), "wb") as output:
        output.write(data)
    return filename


def _out(photo: BarangFoto, primary: bool) -> dict:
    return {"id": photo.id, "filename": photo.filename, "foto": photo.filename,
            "foto_url": f"/storage/foto-barang/{photo.filename}", "urutan": photo.urutan,
            "is_primary": primary, "created_at": str(photo.created_at)[:19] if photo.created_at else None}


@router.get("/api/barang/{barang_id}/photos")
def list_photos(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not db.get(Barang, barang_id): raise HTTPException(status_code=404, detail="Barang not found")
    photos = db.query(BarangFoto).filter_by(barang_id=barang_id).order_by(BarangFoto.urutan, BarangFoto.id).all()
    return [_out(photo, index == 0) for index, photo in enumerate(photos)]


@router.post("/api/barang/{barang_id}/photos")
async def append_photo(barang_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    barang = db.get(Barang, barang_id)
    if not barang: raise HTTPException(status_code=404, detail="Barang not found")
    filename = await _save(file)
    try:
        next_order = (db.query(BarangFoto).filter_by(barang_id=barang_id).count())
        photo = BarangFoto(barang_id=barang_id, filename=filename, urutan=next_order)
        db.add(photo)
        if next_order == 0: barang.foto = filename
        db.commit(); db.refresh(photo)
    except Exception:
        db.rollback()
        try: os.remove(os.path.join(STORAGE_DIR, filename))
        except OSError: pass
        raise
    return _out(photo, next_order == 0)


@router.delete("/api/barang/{barang_id}/photos/{photo_id}")
def delete_photo(barang_id: int, photo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    photo = db.query(BarangFoto).filter_by(id=photo_id, barang_id=barang_id).first()
    if not photo: raise HTTPException(status_code=404, detail="Foto not found")
    filename = photo.filename
    db.delete(photo); db.flush()
    photos = db.query(BarangFoto).filter_by(barang_id=barang_id).order_by(BarangFoto.urutan, BarangFoto.id).all()
    for index, other in enumerate(photos): other.urutan = index
    barang = db.get(Barang, barang_id)
    barang.foto = photos[0].filename if photos else None
    db.commit()
    try: os.remove(os.path.join(STORAGE_DIR, os.path.basename(filename)))
    except OSError: pass
    return {"ok": True}


@router.put("/api/barang/{barang_id}/photos/{photo_id}/primary")
def primary_photo(barang_id: int, photo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    photo = db.query(BarangFoto).filter_by(id=photo_id, barang_id=barang_id).first()
    if not photo: raise HTTPException(status_code=404, detail="Foto not found")
    photos = db.query(BarangFoto).filter_by(barang_id=barang_id).order_by(BarangFoto.urutan, BarangFoto.id).all()
    photos.remove(photo); photos.insert(0, photo)
    for index, other in enumerate(photos): other.urutan = index
    db.get(Barang, barang_id).foto = photo.filename
    db.commit(); db.refresh(photo)
    return _out(photo, True)


@router.post("/api/upload/foto/{barang_id}")
async def upload_foto_barang(barang_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Legacy endpoint appends then makes upload primary."""
    result = await append_photo(barang_id, file, db, user)
    primary_photo(barang_id, result["id"], db, user)
    return {"foto_url": result["foto_url"]}
