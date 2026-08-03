from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.models.user import User
from app.routers import (
    auth_router,
    kategori_router,
    supplier_router,
    barang_router,
    stok_router,
    dashboard_router,
    chatbot_router,
    upload_router,
)
from app.routers.printjob import router as printjob_router
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

# Register routers
app.include_router(auth_router)
app.include_router(kategori_router)
app.include_router(supplier_router)
app.include_router(barang_router)
app.include_router(stok_router)
app.include_router(dashboard_router)
app.include_router(chatbot_router)
app.include_router(upload_router)
from app.routers.label import router as label_router
app.include_router(label_router)
app.include_router(printjob_router)
from app.routers.laporan import router as laporan_router
app.include_router(laporan_router)

import os
from app.routers.upload import STORAGE_DIR as FOTO_STORAGE_DIR

# Mount static files
app.mount('/storage/foto-barang', StaticFiles(directory=FOTO_STORAGE_DIR), name='foto-barang')



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
            print(f"Admin default created: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    finally:
        db.close()
