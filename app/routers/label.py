import base64
import html
import json
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import AuthPrincipal, get_current_user_env_id, require_permission
from app.database import get_db
from app.models.barang import Barang
from app.models.environment import Environment
from app.models.printjob import PrintJob

router = APIRouter(prefix="/api/label", tags=["label"])

LABEL_SIZES = [
    {"id": "80x40", "name": "80mm × 40mm", "width_mm": 80, "height_mm": 40, "cols": 1, "margin": 3, "font_size": "10px"},
    {"id": "75x50", "name": "75mm × 50mm", "width_mm": 75, "height_mm": 50, "cols": 1, "margin": 3, "font_size": "11px"},
    {"id": "50x30", "name": "50mm × 30mm", "width_mm": 50, "height_mm": 30, "cols": 1, "margin": 2, "font_size": "7px"},
    {"id": "a4_2col", "name": "A4 2 kolom", "width_mm": 95, "height_mm": 40, "cols": 2, "margin": 5, "font_size": "9px"},
    {"id": "a4_3col", "name": "A4 3 kolom", "width_mm": 62, "height_mm": 35, "cols": 3, "margin": 5, "font_size": "7px"},
]
DEFAULT_CONFIG = {"default_size": "a4_2col"}


def load_label_config(db: Session, env_id: int) -> dict:
    environment = db.query(Environment).filter(Environment.id == env_id).first()
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    try:
        config = json.loads(environment.label_config)
    except (TypeError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()
    return config if isinstance(config, dict) else DEFAULT_CONFIG.copy()


def save_label_config(db: Session, env_id: int, config: dict) -> None:
    environment = db.query(Environment).filter(Environment.id == env_id).first()
    if not environment:
        raise HTTPException(status_code=404, detail="Environment not found")
    environment.label_config = json.dumps(config, separators=(",", ":"), sort_keys=True)
    db.commit()


STICKER_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page {{ margin: 0; size: {page_width}mm {page_height}mm; }}
body {{ margin: {margin}mm; padding: 0; font-family: Arial, sans-serif; display: grid;
grid-template-columns: repeat({cols}, 1fr); gap: 0; box-sizing: border-box; }}
.sticker {{ border: 0.25mm dashed #aaa; padding: 2mm; text-align: center;
page-break-inside: avoid; box-sizing: border-box; display: flex; flex-direction: column;
align-items: center; justify-content: space-around; height: {height}mm; width: {width}mm; }}
.sticker img {{ max-width: 90%; max-height: 40%; margin-bottom: 1mm; }}
.sticker .nama {{ font-size: {font_size}; font-weight: bold; line-height: 1.1; }}
.sticker .harga {{ font-size: calc({font_size} * 0.85); font-weight: bold; color: #d32f2f; }}
.sticker .kode {{ font-size: 7px; color: #666; }}
.sticker .sku {{ font-size: 6px; color: #999; }}
@media print {{ .sticker {{ border: none; }} @page {{ margin: 0; }} }}
</style></head><body>{stickers}</body></html>"""

STICKER_ITEM = """<div class="sticker">
<div class="kode">ID:{id}</div>{barcode_img}<div class="nama">{nama}</div>
<div class="harga">Rp {harga_jual:,}</div><div class="sku">SKU: {sku}</div></div>"""


def generate_sticker_html(
    barang_id: int,
    qty: int,
    size_id: Optional[str],
    db: Session,
    env_id: int,
    *,
    autoprint: bool = False,
):
    config = load_label_config(db, env_id)
    final_size_id = size_id or config.get("default_size", "a4_2col")
    size_info = next((size for size in LABEL_SIZES if size["id"] == final_size_id), None)
    if not size_info:
        raise HTTPException(status_code=400, detail=f"Invalid size ID: {final_size_id}")
    barang = db.query(Barang).filter(
        Barang.id == barang_id, Barang.environment_id == env_id
    ).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang not found")

    try:
        import barcode
        from barcode.writer import ImageWriter

        code = barcode.get("code128", str(barang.id).zfill(6), writer=ImageWriter())
        buffer = BytesIO()
        code.write(buffer, options={"module_width": 0.3, "module_height": 8, "font_size": 0, "write_text": False, "dpi": 150})
        barcode_img = f'<img src="data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}" alt="barcode"/>'
    except ImportError:
        barcode_img = f'<div style="font-size:18px;font-family:monospace;">{str(barang.id).zfill(6)}</div>'

    stickers = "".join(
        STICKER_ITEM.format(
            id=barang.id,
            barcode_img=barcode_img,
            nama=html.escape(barang.nama[:25]),
            harga_jual=barang.harga_jual or 0,
            sku=html.escape(barang.sku or "-"),
        )
        for _ in range(qty)
    )
    page_width = size_info["width_mm"] * size_info["cols"]
    page_height = 297 if size_info["id"].startswith("a4") else size_info["height_mm"]
    content = STICKER_HTML.format(
        page_width=page_width,
        page_height=page_height,
        margin=size_info["margin"],
        cols=size_info["cols"],
        height=size_info["height_mm"],
        width=size_info["width_mm"],
        font_size=size_info["font_size"],
        stickers=stickers,
    )
    if autoprint:
        job = PrintJob(environment_id=env_id, barang_id=barang.id, qty=qty, status="pending")
        db.add(job)
        db.commit()
        content = content.replace("</body>", "<script>window.onload=function(){window.print();}</script></body>")
    return HTMLResponse(content=content, media_type="text/html")


@router.get("/sizes", response_model=list[dict])
def get_label_sizes(
    principal: AuthPrincipal = Depends(require_permission("barang.read")),
    env_id: int = Depends(get_current_user_env_id),
):
    return LABEL_SIZES


@router.get("/config")
def get_label_config(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_permission("environment.settings")),
    env_id: int = Depends(get_current_user_env_id),
):
    return load_label_config(db, env_id)


@router.post("/config")
def set_label_config(
    config: dict,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_permission("environment.settings")),
    env_id: int = Depends(get_current_user_env_id),
):
    if set(config) - {"default_size"}:
        raise HTTPException(status_code=400, detail="Invalid configuration key.")
    if config.get("default_size") not in {size["id"] for size in LABEL_SIZES}:
        raise HTTPException(status_code=400, detail="Invalid size ID")
    save_label_config(db, env_id, config)
    return {"message": "Configuration saved.", "config": config}


@router.get("/sticker/{barang_id}")
def sticker_print(
    barang_id: int,
    qty: int = Query(1, ge=1, le=500),
    size: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_permission("barang.read")),
    env_id: int = Depends(get_current_user_env_id),
):
    return generate_sticker_html(barang_id, qty, size, db, env_id)


@router.get("/sticker/{barang_id}/print")
def sticker_print_auto(
    barang_id: int,
    qty: int = Query(1, ge=1, le=500),
    size: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_permission("barang.read")),
    env_id: int = Depends(get_current_user_env_id),
):
    return generate_sticker_html(barang_id, qty, size, db, env_id, autoprint=True)
