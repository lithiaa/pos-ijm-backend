from config import HARGA_ENCODE_MAP, HARGA_DECODE_MAP


def harga_encode(angka: int) -> str:
    """encode 25000 jadi AUP (collapse repeating last char)"""
    if angka == 0:
        return "P"
    s = str(angka)
    encoded = "".join(HARGA_DECODE_MAP.get(c, c) for c in s)
    # Collapse repeating trailing chars: AUPPP → AUP
    if len(encoded) > 1:
        stripped = encoded.rstrip(encoded[-1])
        if stripped:
            encoded = stripped + encoded[-1]
        else:
            encoded = encoded[-1]
    return encoded


def harga_decode(kode: str) -> int:
    """decode AUPPP jadi 25000"""
    kode = kode.strip().upper()
    decoded = "".join(HARGA_ENCODE_MAP.get(c, c) for c in kode)
    return int(decoded)
