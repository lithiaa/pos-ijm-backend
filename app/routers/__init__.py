from app.routers.auth import router as auth_router
from app.routers.kategori import router as kategori_router
from app.routers.supplier import router as supplier_router
from app.routers.barang import router as barang_router
from app.routers.stok import router as stok_router
from app.routers.dashboard import router as dashboard_router
from app.routers.chatbot import router as chatbot_router
from app.routers.upload import router as upload_router
from app.routers.printjob import router as printjob_router
from app.routers.integration_barang import router as integration_barang_router
from app.routers.integration_supplier import router as integration_supplier_router

__all__ = [
    "auth_router",
    "kategori_router",
    "supplier_router",
    "barang_router",
    "stok_router",
    "dashboard_router",
    "chatbot_router",
    "upload_router",
    "printjob_router",
    "integration_barang_router",
    "integration_supplier_router",
]
