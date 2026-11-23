"""Tests del pallet de armado y del contraste volante vs sumario."""

from __future__ import annotations

import pandas as pd
import pytest

from src import inventario as inv
from src import pallet as pl
from src import stock_vivo as sv
from src import sumario as sm


def _fila_stock(area, ubic, sku, cant, lpn="L1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubic, "Llena", lpn, "D1", sku, sku, desc,
        str(cant), "0", "0", "08/07/2025 15:55:58", "23/05/2026 13:30:12",
        "01/12/2027 00:00:00", "", "Disponible", "9999", "9529",
        "05/10/2026 13:07:15", area,
    ])


STOCK = "\n".join([
    _fila_stock("AREA PICKING", "C01-01-01-01", "00447085", 40, "L1", "3R MANZANA"),
    _fila_stock("AREA PICKING", "C01-01-02-01", "00700153", 10, "L2", "MIS_VARIET CS"),
    _fila_stock("AREA PICKING", "C01-01-03-01", "00700154", 5, "L3", "MIS_VARIET SB"),
    _fila_stock("AREA PICKING", "C01-01-04-01", "00700229", 1, "L4", "GATO PREMIUM"),
    _fila_stock("AREA ALMACENAMIENTO", "A-01-01-01", "00700682", 100, "L5", "MIS RES"),
]) + "\n"

TEXTO_SUMARIO = """CAMION # : 012R-01 FECHA : 07-11-2026
801
PALLET PRODUCTO DESCRIPCION CANTIDAD
001 00447085 3R MANZANA 5GL VNR275X24 20
Sub Total 20
002 00700153 MIS_VARIET-CS-VNR187CCX24 3
00700154 MIS_VARIET-SB-VNR187CCX24 1
00700229 GATO_PREMIUM-CS-VNR187CCX24 2
00700682 MIS_RES_MS-CS-VNR750CCX6-CO 5
Sub Total 11
TOTAL : 31 PESO: 0
"""


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(STOCK).guardar(ruta)
    sv.inicializar(ruta)
    sm.leer_texto(TEXTO_SUMARIO).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Pallet de armado
# --------------------------------------------------------------------------

def test_pallet_trae_todos_los_skus_juntos(db):
    """El armador ve el pallet COMPLETO, no una tarea suelta por SKU."""
    p = pl.pallet_de(db, "012R-01", "002")
    assert p is not None
    assert p.skus == 4
    assert p.cajas == 11
    assert p.mixto is True


def test_pallet_simple_no_es_mixto(db):
    p = pl.pallet_de(db, "012R-01", "001")
    assert p.skus == 1
    assert p.cajas == 20
    assert p.mixto is False


def test_pallet_muestra_ubicacion_y_disponible(db):
    p = pl.pallet_de(db, "012R-01", "002")
    por_sku = {l["sku"]: l for l in p.lineas}
    assert por_sku["00700153"]["ubicacion"] == "C01-01-02-01"
    assert por_sku["00700153"]["disponible"] == 10
    assert por_sku["00700153"]["alcanza"] is True


def test_pallet_marca_cuando_no_alcanza(db):
    """GATO PREMIUM pide 2 y solo hay 1."""
    p = pl.pallet_de(db, "012R-01", "002")
    por_sku = {l["sku"]: l for l in p.lineas}
    assert por_sku["00700229"]["disponible"] == 1
    assert por_sku["00700229"]["alcanza"] is False


def test_pallet_busca_en_almacenamiento_si_no_esta_en_picking(db):
    """MIS RES solo esta en almacenamiento: debe encontrarlo igual."""
    p = pl.pallet_de(db, "012R-01", "002")
    por_sku = {l["sku"]: l for l in p.lineas}
    assert por_sku["00700682"]["area"] == sv.AREA_ALMACENAMIENTO
    assert por_sku["00700682"]["disponible"] == 100


def test_pallet_inexistente(db):
    assert pl.pallet_de(db, "NOEXISTE", "999") is None


def test_pallets_de_camion(db):
    ps = pl.pallets_de_camion(db, "012R-01")
    assert len(ps) == 2
    assert ps[0]["pallet"] == "001"
    assert ps[1]["mixto"] is True


# --------------------------------------------------------------------------
# Contraste volante vs sumario
# --------------------------------------------------------------------------

def test_contraste_todo_ok(db):
    volante = [
        {"sku": "00700153", "cantidad": 3},
        {"sku": "00700154", "cantidad": 1},
        {"sku": "00700229", "cantidad": 2},
        {"sku": "00700682", "cantidad": 5},
    ]
    c = pl.contrastar(db, "012R-01", "002", volante)
    assert c.ok is True
    assert c.faltantes == 0
    assert c.sobrantes == 0


def test_contraste_detecta_faltante(db):
    """El volante anoto 1 donde el sumario pide 3."""
    volante = [
        {"sku": "00700153", "cantidad": 1},
        {"sku": "00700154", "cantidad": 1},
        {"sku": "00700229", "cantidad": 2},
        {"sku": "00700682", "cantidad": 5},
    ]
    c = pl.contrastar(db, "012R-01", "002", volante)
    assert c.ok is False
    assert c.faltantes == 1
    f = [x for x in c.filas if x["sku"] == "00700153"][0]
    assert f["estado"] == "falta"
    assert f["diferencia"] == -2


def test_contraste_detecta_sobrante(db):
    volante = [{"sku": "00447085", "cantidad": 25}]
    c = pl.contrastar(db, "012R-01", "001", volante)
    assert c.ok is False
    assert c.sobrantes == 1
    assert c.filas[0]["diferencia"] == 5


def test_contraste_detecta_sku_que_no_va_en_el_pallet(db):
    """Se anoto un SKU que el sumario NO pide para ese pallet."""
    volante = [
        {"sku": "00447085", "cantidad": 20},
        {"sku": "00999999", "cantidad": 5},
    ]
    c = pl.contrastar(db, "012R-01", "001", volante)
    assert c.sobrantes >= 1
    extra = [x for x in c.filas if x["sku"] == "999999"]
    assert extra and extra[0]["estado"] == "sobra"
    assert extra[0]["sumario"] == 0


def test_contraste_volante_vacio_reporta_todo_faltante(db):
    c = pl.contrastar(db, "012R-01", "002", [])
    assert c.faltantes == 4
    assert c.ok is False


def test_contraste_acepta_dataframe(db):
    volante = pd.DataFrame([
        {"sku": "00700153", "cantidad": 3},
        {"sku": "00700154", "cantidad": 1},
        {"sku": "00700229", "cantidad": 2},
        {"sku": "00700682", "cantidad": 5},
    ])
    c = pl.contrastar(db, "012R-01", "002", volante)
    assert c.ok is True


def test_contraste_suma_el_mismo_sku_repetido(db):
    """Si el operario anota el mismo SKU en dos lineas, se suma."""
    volante = [
        {"sku": "00447085", "cantidad": 15},
        {"sku": "00447085", "cantidad": 5},
    ]
    c = pl.contrastar(db, "012R-01", "001", volante)
    assert c.ok is True


def test_contraste_pallet_inexistente(db):
    c = pl.contrastar(db, "NOEXISTE", "999", [{"sku": "1", "cantidad": 1}])
    assert c.filas and c.filas[0]["estado"] == "sobra"
