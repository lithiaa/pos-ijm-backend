from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.audit import AuditMiddleware
from app.models.audit_log import AuditLog
from app.models.admin import EnvironmentCopyJob, Invitation, ProvisionRequest, SupportGrant
from app.models.user import User
from app.routers import (
    auth_router,
    supplier_router,
    barang_router,
    stok_router,
    dashboard_router,
    chatbot_router,
    upload_router,
    integration_barang_router,
    integration_supplier_router,
    logs_router,
    katalog_router,
)
from app.routers.printjob import router as printjob_router
from app.routers.environments import router as environments_router
from app.routers.users import router as users_router
from app.routers.copy_jobs import router as copy_jobs_router
from app.auth import hash_password
from config import ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_NAMA

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Toko Sparepart API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# Register routers
app.include_router(auth_router)
app.include_router(supplier_router)
app.include_router(barang_router)
app.include_router(stok_router)
app.include_router(dashboard_router)
app.include_router(chatbot_router)
app.include_router(upload_router)
app.include_router(integration_barang_router)
app.include_router(integration_supplier_router)
app.include_router(logs_router)
app.include_router(katalog_router)
from app.routers.label import router as label_router
app.include_router(label_router)
app.include_router(printjob_router)
app.include_router(environments_router)
app.include_router(users_router)
app.include_router(copy_jobs_router)
from app.routers.laporan import router as laporan_router
app.include_router(laporan_router)

import os
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user, get_current_user_env_id
from app.models.barang import Barang, BarangFoto
from app.routers.upload import STORAGE_DIR as FOTO_STORAGE_DIR


@app.get("/api/foto-barang/{environment_id}/{filename}")
def serve_foto_barang(
    environment_id: int,
    filename: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    env_id: int = Depends(get_current_user_env_id),
):
    if env_id != environment_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this environment's photos")
    if filename != os.path.basename(filename):
        raise HTTPException(status_code=404, detail="Photo not found")
    owned = (
        db.query(BarangFoto.id)
        .filter(BarangFoto.environment_id == environment_id, BarangFoto.filename == filename)
        .first()
        or db.query(Barang.id)
        .filter(Barang.environment_id == environment_id, Barang.foto == filename)
        .first()
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Photo not found")
    paths = (
        os.path.join(FOTO_STORAGE_DIR, str(environment_id), filename),
        os.path.join(FOTO_STORAGE_DIR, filename),
    )
    filepath = next((path for path in paths if os.path.isfile(path)), None)
    if filepath is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return FileResponse(filepath)



@app.on_event("startup")
def seed_data():
    """Buat admin default kalau belum ada"""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not admin:
            db.add(User(
                username=ADMIN_USERNAME,
                password_hash=hash_password(ADMIN_PASSWORD),
                nama=ADMIN_NAMA,
                role="admin",
            ))
            db.commit()
            print(f"Admin default created: {ADMIN_USERNAME}")
    finally:
        db.close()
