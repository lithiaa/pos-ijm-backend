from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from io import BytesIO
import base64
import json
import os
from typing import Optional, List

from app.database import get_db
from app.models.barang import Barang
from app.services.harga import harga_encode

router = APIRouter(prefix="/api/label", tags=["label"])

# --- Label Size Definitions ---
LABEL_SIZES = [
    {'id': '80x40', 'name': '80mm × 40mm', 'width_mm': 80, 'height_mm': 40, 'cols': 1, 'margin': 3, 'font_size': '10px'},
    {'id': '75x50', 'name': '75mm × 50mm', 'width_mm': 75, 'height_mm': 50, 'cols': 1, 'margin': 3, 'font_size': '11px'},
    {'id': '50x30', 'name': '50mm × 30mm', 'width_mm': 50, 'height_mm': 30, 'cols': 1, 'margin': 2, 'font_size': '7px'},
    {'id': 'a4_2col', 'name': 'A4 2 kolom', 'width_mm': 95, 'height_mm': 40, 'cols': 2, 'margin': 5, 'font_size': '9px'},
    {'id': 'a4_3col', 'name': 'A4 3 kolom', 'width_mm': 62, 'height_mm': 35, 'cols': 3, 'margin': 5, 'font_size': '7px'},
]
LABEL_CONFIG_FILE = os.path.join("storage", "label_config.json")

def load_label_config():
    if os.path.exists(LABEL_CONFIG_FILE):
        with open(LABEL_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {'default_size': 'a4_2col'}

def save_label_config(config):
    os.makedirs(os.path.dirname(LABEL_CONFIG_FILE), exist_ok=True)
    with open(LABEL_CONFIG_FILE, 'w') as f:
        json.dump(config, f)

# --- HTML Templates ---
STICKER_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page {{
    margin: 0;
    size: {page_width}mm {page_height}mm;
}}
body {{
    margin: {margin}mm;
    padding: 0;
    font-family: Arial, sans-serif;
    display: grid;
    grid-template-columns: repeat({cols}, 1fr);
    gap: 0;
    box-sizing: border-box;
}}
.sticker {{
    border: 0.25mm dashed #aaa;
    padding: 2mm;
    text-align: center;
    page-break-inside: avoid;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: space-around;
    height: {height}mm;
    width: {width}mm;
}}
.sticker img {{ max-width: 90%; max-height: 40%; margin-bottom: 1mm; }}
.sticker .nama {{ font-size: {font_size}; font-weight: bold; line-height: 1.1; }}
.sticker .harga {{
    font-size: calc({font_size} * 0.85);
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 3mm;
    width: 100%;
}}
.sticker .harga-jual {{
    font-weight: bold;
    color: #d32f2f;
}}
.sticker .harga-beli {{
    font-style: italic;
    font-weight: 600;
    color: #1565c0;
    letter-spacing: 0.5px;
}}
.sticker .kode {{ font-size: 7px; color: #666; }}
.sticker .sku {{ font-size: 6px; color: #999; }}
@media print {{ .sticker {{ border: none; }} @page {{ margin: 0; }} }}
</style></head><body>
{stickers}
</body></html>"""

STICKER_ITEM = """<div class="sticker">
    <div class="kode">ID:{id}</div>
    {barcode_img}
    <div class="nama">{nama}</div>
    <div class="harga">
        <span class="harga-beli">{kode_beli}</span>
        <span class="harga-jual">Rp {harga_jual:,}</span>
    </div>
    <div class="sku">SKU: {sku}</div>
</div>"""

# --- Helper for Sticker Generation ---
def generate_sticker_html(barang_id: int, qty: int, size_id: Optional[str], db: Session, autoprint: bool = False):
    config = load_label_config()

    # Determine size
    final_size_id = size_id or config.get('default_size', 'a4_2col')
    size_info = next((s for s in LABEL_SIZES if s['id'] == final_size_id), None)
    if not size_info:
        raise HTTPException(400, f"Invalid size ID: {final_size_id}")

    # Fetch barang
    barang = db.query(Barang).filter(Barang.id == barang_id).first()
    if not barang:
        raise HTTPException(404, "Barang not found")

    # Generate Barcode
    try:
        import barcode
        from barcode.writer import ImageWriter
        code = barcode.get('code128', str(barang.id).zfill(6), writer=ImageWriter())
        buf = BytesIO()
        code.write(buf, options={"module_width": 0.3, "module_height": 8, "font_size": 0, "write_text": False, "dpi": 150})
        b64 = base64.b64encode(buf.getvalue()).decode()
        barcode_img = f'<img src="data:image/png;base64,{b64}" alt="barcode"/>'
    except ImportError:
        barcode_img = f'<div style="font-size:18px;font-family:monospace;">{str(barang.id).zfill(6)}</div>'

    # Prepare sticker items
    stickers_html = "".join(
        STICKER_ITEM.format(
            id=barang.id,
            barcode_img=barcode_img,
            nama=barang.nama[:25],
            harga_jual=barang.harga_jual or 0,
            kode_jual=harga_encode(barang.harga_jual or 0),
            harga_beli=barang.harga_modal or 0,
            kode_beli=harga_encode(barang.harga_modal or 0),
            sku=barang.sku or "-",
        )
        for _ in range(qty)
    )

    page_width = size_info['width_mm'] * size_info['cols']
    page_height = 297 if size_info['id'].startswith('a4') else size_info['height_mm']

    # Final HTML
    html = STICKER_HTML.format(
        page_width=page_width,
        page_height=page_height,
        margin=size_info['margin'],
        cols=size_info['cols'],
        height=size_info['height_mm'],
        width=size_info['width_mm'],
        font_size=size_info['font_size'],
        stickers=stickers_html,
    )
    if autoprint:
        html = html.replace("</body>", "<script>window.onload=function(){window.print();}</script></body>")

    return HTMLResponse(content=html, media_type="text/html")

# --- API Endpoints ---
@router.get("/sizes", response_model=List[dict])
def get_label_sizes():
    """Returns a list of available label sizes."""
    return JSONResponse(content=LABEL_SIZES)

@router.get("/config")
def get_label_config():
    """Returns the current label configuration."""
    return JSONResponse(content=load_label_config())

@router.post("/config")
def set_label_config(config: dict):
    """Saves the label configuration."""
    valid_keys = ['default_size']
    if not all(k in valid_keys for k in config.keys()):
        raise HTTPException(400, "Invalid configuration key.")

    size_ids = [s['id'] for s in LABEL_SIZES]
    if 'default_size' in config and config['default_size'] not in size_ids:
        raise HTTPException(400, f"Invalid size ID: {config['default_size']}")

    save_label_config(config)
    return JSONResponse(content={"message": "Configuration saved.", "config": config})

@router.get("/sticker/{barang_id}")
def sticker_print(
    barang_id: int,
    qty: int = Query(1, ge=1, le=500),
    size: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Generates barcode sticker(s) for a product. Opens in new tab as print-friendly HTML."""
    return generate_sticker_html(barang_id, qty, size, db, autoprint=False)

@router.get("/sticker/{barang_id}/print")
def sticker_print_auto(
    barang_id: int,
    qty: int = Query(1, ge=1, le=500),
    size: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Same as sticker, but auto-shows print dialog via window.print()."""
    return generate_sticker_html(barang_id, qty, size, db, autoprint=True)
