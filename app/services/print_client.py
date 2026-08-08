# Hook print ke Niimbot Print Agent (Android, via Tailscale)
# 
# Alur:
#   chatbot "cetak label id=X" → buat PrintJob → kirim HTTP POST ke agent → agent cetak via BLE
#
# Config di .env:
#   PRINT_AGENT_URL=http://100.x.x.x:8080   (IP tailscale tablet)
#   PRINT_AGENT_TIMEOUT=30

import os
import requests
import threading

PRINT_AGENT_URL = os.getenv("PRINT_AGENT_URL", "").rstrip("/")
PRINT_AGENT_TIMEOUT = float(os.getenv("PRINT_AGENT_TIMEOUT", "30"))


def is_configured() -> bool:
    """True kalau PRINT_AGENT_URL ter-set di .env"""
    return bool(PRINT_AGENT_URL)


def send_print_job(
    nama: str,
    harga_jual: int,
    sku: str = "",
    stok: int = 0,
    satuan: str = "pcs",
    qty: int = 1,
) -> dict:
    """Kirim job ke print agent. Return dict: {ok, job_id?, error?}"""
    if not is_configured():
        return {"ok": False, "error": "PRINT_AGENT_URL belum di-set di .env"}

    payload = {
        "nama": nama,
        "hargaJual": harga_jual,
        "sku": sku or "000000",
        "stok": stok,
        "satuan": satuan,
        "qty": qty,
    }

    try:
        resp = requests.post(
            f"{PRINT_AGENT_URL}/print",
            json=payload,
            timeout=PRINT_AGENT_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"ok": data.get("success", False), "job_id": data.get("jobId"), "error": data.get("error")}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": str(e)}


def print_job_async(nama, harga_jual, sku="", stok=0, satuan="pcs", qty=1, on_done=None):
    """Kirim print job di thread terpisah (tidak block request chatbot)."""
    def _run():
        result = send_print_job(nama, harga_jual, sku, stok, satuan, qty)
        if on_done:
            on_done(result)

    threading.Thread(target=_run, daemon=True).start()
