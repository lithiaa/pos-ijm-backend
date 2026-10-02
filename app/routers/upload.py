import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session


from app.auth import get_current_user, get_current_user_env_id
from app.database import get_db
from app.models.barang import Barang, BarangFoto

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_DIR = os.path.join(BASE_DIR, "storage/foto-barang")
os.makedirs(STORAGE_DIR, exist_ok=True)
MAX_PHOTO_BYTES = 5 * 1024 * 1024
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

router = APIRouter()


def _env_filter(column, env_id: int, user):
    return column == env_id if user.role == "platform_owner" else ((column == env_id) | column.is_(None))


def _valid_image(content_type: str, data: bytes) -> bool:
    if content_type == "image/jpeg": return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png": return data.startswith(b"\x89PNG\r\n\x1a\n")
    return content_type == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


async def _save(file: UploadFile, storage_dir: str = STORAGE_DIR) -> str:
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if file.content_type not in EXTENSIONS or not data:
        raise HTTPException(status_code=422, detail="Foto harus JPEG, PNG, atau WebP valid maksimal 5MB")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 5 MiB")
    if not _valid_image(file.content_type, data):
        raise HTTPException(status_code=422, detail="Foto harus JPEG, PNG, atau WebP valid maksimal 5MB")
    filename = f"{uuid.uuid4()}{EXTENSIONS[file.content_type]}"
    os.makedirs(storage_dir, exist_ok=True)
    with open(os.path.join(storage_dir, filename), "wb") as output:
        output.write(data)
    return filename


def _out(photo: BarangFoto, primary: bool) -> dict:
    return {"id": photo.id, "filename": photo.filename, "foto": photo.filename,
            "foto_url": f"/storage/foto-barang/{photo.filename}", "urutan": photo.urutan,
            "is_primary": primary, "created_at": str(photo.created_at)[:19] if photo.created_at else None}


def _locked_barang(db: Session, barang_id: int) -> Barang | None:
    barang = db.execute(select(Barang).where(Barang.id == barang_id).with_for_update()).scalar_one_or_none()
    if barang and db.bind.dialect.name == "sqlite":
        db.execute(update(Barang).where(Barang.id == barang_id).values(id=Barang.id))
    return barang


def remove_unreferenced_file(db: Session, filename: str, storage_dir: str = STORAGE_DIR) -> None:
    if db.query(BarangFoto.id).filter_by(filename=filename).first() or db.query(Barang.id).filter_by(foto=filename).first():
        return
    try: os.remove(os.path.join(storage_dir, os.path.basename(filename)))
    except OSError: pass


def _reorder(db: Session, photos: list[BarangFoto]) -> None:
    offset = max((photo.urutan for photo in photos), default=-1) + len(photos) + 1
    for index, photo in enumerate(photos):
        photo.urutan = offset + index
    db.flush()
    for index, photo in enumerate(photos):
        photo.urutan = index


def add_photo(db: Session, barang_id: int, filename: str, primary: bool = False) -> BarangFoto:
    barang = _locked_barang(db, barang_id)
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")
    photos = db.query(BarangFoto).filter_by(barang_id=barang_id).order_by(BarangFoto.urutan, BarangFoto.id).all()
    photo = BarangFoto(environment_id=barang.environment_id, barang_id=barang_id, filename=filename, urutan=len(photos))
    db.add(photo)
    db.flush()
    if primary:
        photos.insert(0, photo)
        _reorder(db, photos)
        barang.foto = filename
    elif not photos:
        barang.foto = filename
    return photo


@router.get("/api/barang/{barang_id}/photos")
def list_photos(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    if not db.query(Barang.id).filter(Barang.id == barang_id, _env_filter(Barang.environment_id, env_id, user)).first(): raise HTTPException(status_code=404, detail="Barang not found")
    photos = db.query(BarangFoto).filter(BarangFoto.barang_id == barang_id, _env_filter(BarangFoto.environment_id, env_id, user)).order_by(BarangFoto.urutan, BarangFoto.id).all()
    return [_out(photo, index == 0) for index, photo in enumerate(photos)]


@router.post("/api/barang/{barang_id}/photos")
async def append_photo(barang_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    if not db.query(Barang.id).filter(Barang.id == barang_id, _env_filter(Barang.environment_id, env_id, user)).first(): raise HTTPException(status_code=404, detail="Barang not found")
    filename = await _save(file)
    try:
        photo = add_photo(db, barang_id, filename)
        db.commit(); db.refresh(photo)
    except Exception:
        db.rollback()
        try: os.remove(os.path.join(STORAGE_DIR, filename))
        except OSError: pass
        raise
    return _out(photo, photo.urutan == 0)


@router.delete("/api/barang/{barang_id}/photos/{photo_id}")
def delete_photo(barang_id: int, photo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    barang_query = db.query(Barang).filter(Barang.id == barang_id)
    if isinstance(env_id, int):
        barang_query = barang_query.filter(_env_filter(Barang.environment_id, env_id, user))
    barang = barang_query.first()
    if not barang: raise HTTPException(status_code=404, detail="Barang not found")
    photo_query = db.query(BarangFoto).filter_by(id=photo_id, barang_id=barang_id)
    if isinstance(env_id, int):
        photo_query = photo_query.filter(BarangFoto.environment_id == env_id)
    photo = photo_query.first()
    if not photo: raise HTTPException(status_code=404, detail="Foto not found")
    filename = photo.filename
    db.delete(photo); db.flush()
    photos = db.query(BarangFoto).filter_by(barang_id=barang_id).order_by(BarangFoto.urutan, BarangFoto.id).all()
    _reorder(db, photos)
    barang = db.get(Barang, barang_id)
    barang.foto = photos[0].filename if photos else None
    db.commit()
    remove_unreferenced_file(db, filename, STORAGE_DIR)
    return {"ok": True}


@router.put("/api/barang/{barang_id}/photos/{photo_id}/primary")
def primary_photo(barang_id: int, photo_id: int, db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    photo = db.query(BarangFoto).filter(BarangFoto.id == photo_id, BarangFoto.barang_id == barang_id, _env_filter(BarangFoto.environment_id, env_id, user)).first()
    if not photo: raise HTTPException(status_code=404, detail="Foto not found")
    photos = db.query(BarangFoto).filter(BarangFoto.barang_id == barang_id, _env_filter(BarangFoto.environment_id, env_id, user)).order_by(BarangFoto.urutan, BarangFoto.id).all()
    photos.remove(photo); photos.insert(0, photo)
    _reorder(db, photos)
    db.query(Barang).filter(Barang.id == barang_id, _env_filter(Barang.environment_id, env_id, user)).one().foto = photo.filename
    db.commit(); db.refresh(photo)
    return _out(photo, True)


@router.post("/api/upload/foto/{barang_id}")
async def upload_foto_barang(barang_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user), env_id: int = Depends(get_current_user_env_id)):
    """Legacy endpoint appends then makes upload primary."""
    if not db.query(Barang.id).filter(Barang.id == barang_id, _env_filter(Barang.environment_id, env_id, user)).first(): raise HTTPException(status_code=404, detail="Barang not found")
    filename = await _save(file)
    try:
        photo = add_photo(db, barang_id, filename, primary=True)
        db.commit(); db.refresh(photo)
    except Exception:
        db.rollback()
        try: os.remove(os.path.join(STORAGE_DIR, filename))
        except OSError: pass
        raise
    return {"foto_url": _out(photo, True)["foto_url"]}
