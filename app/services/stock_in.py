from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.barang import Barang, BarangSupplier
from app.models.transaksi import StokSaatIni, TransaksiStok


def record_stock_in(db: Session, *, barang_id: int, jumlah: int, harga_satuan: int | None,
                    keterangan: str | None, user_id: int | None, supplier_id: int | None,
                    environment_id: int | None = None):
    """Caller owns transaction. MySQL row lock prevents conflicting tally/primary decisions."""
    query = select(Barang).where(Barang.id == barang_id)
    if environment_id is not None:
        query = query.where(Barang.environment_id == environment_id)
    if db.bind.dialect.name in {"mysql", "mariadb"}:
        query = query.with_for_update()
    barang = db.execute(query).scalar_one_or_none()
    if not barang:
        return None, None
    if jumlah == 0:
        return barang, None
    env_id = environment_id if environment_id is not None else barang.environment_id
    stok = db.query(StokSaatIni).filter(
        StokSaatIni.barang_id == barang_id,
        StokSaatIni.environment_id == env_id,
    ).first()
    if not stok:
        stok = StokSaatIni(environment_id=env_id, barang_id=barang_id, jumlah=0)
        db.add(stok)
    stok.jumlah += jumlah
    tx = TransaksiStok(environment_id=environment_id or barang.environment_id, barang_id=barang_id, jenis="masuk", jumlah=jumlah,
        harga_satuan=harga_satuan, total_harga=(harga_satuan * jumlah if harga_satuan is not None else None),
        keterangan=keterangan, user_id=user_id, supplier_id=supplier_id)
    db.add(tx)
    if supplier_id is not None:
        link = db.get(BarangSupplier, (barang_id, supplier_id))
        if not link:
            link = BarangSupplier(environment_id=env_id, barang_id=barang_id, supplier_id=supplier_id, jumlah_masuk_kumulatif=0)
            db.add(link)
            db.flush()
        link.jumlah_masuk_kumulatif += jumlah
        links = db.query(BarangSupplier).filter_by(barang_id=barang_id).order_by(BarangSupplier.created_at, BarangSupplier.supplier_id).all()
        largest = max(x.jumlah_masuk_kumulatif for x in links)
        tied = [x for x in links if x.jumlah_masuk_kumulatif == largest]
        winner = next((x for x in tied if x.supplier_id == barang.supplier_id), tied[0])
        barang.supplier_id = winner.supplier_id
    db.flush()
    return barang, tx
