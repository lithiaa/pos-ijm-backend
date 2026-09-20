from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.auth import create_access_token
from app.models.barang import Barang
from app.models.transaksi import StokSaatIni, TransaksiStok
from app.models.user import User


LARGE_STOCK = 485_000
STOCK_OUT = 484_994
UNIT_PRICE = 485_000
TOTAL_PRICE = 235_222_090_000


def test_stock_out_persists_total_above_mysql_int_limit(client, db):
    user = User(username="stock-total-qa", password_hash="unused", nama="QA")
    barang = Barang(sku="LABEL-308", nama="Lithia Label Printer")
    db.add_all([user, barang])
    db.flush()
    db.add(StokSaatIni(barang_id=barang.id, jumlah=LARGE_STOCK))
    db.commit()

    response = client.post(
        "/api/stok/keluar",
        headers={"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"},
        json={
            "barang_id": barang.id,
            "jumlah": STOCK_OUT,
            "harga_satuan": UNIT_PRICE,
            "keterangan": "Lithia Label Printer",
        },
    )

    assert response.status_code == 200
    assert response.json()["stok_baru"] == 6
    db.expire_all()
    assert db.get(StokSaatIni, barang.id).jumlah == 6
    history = db.query(TransaksiStok).filter_by(barang_id=barang.id, jenis="keluar").one()
    assert history.total_harga == TOTAL_PRICE


def test_total_harga_uses_mysql_bigint():
    ddl = str(CreateTable(TransaksiStok.__table__).compile(dialect=mysql.dialect()))

    assert "total_harga BIGINT" in ddl
