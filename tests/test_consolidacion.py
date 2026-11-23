"""Tests de consolidacion: el picker deja en staging, el consolidador arma."""

from __future__ import annotations

import pandas as pd
import pytest

from src import consolidacion as cs
from src import inventario as inv
from src import picking as pk
from src import stock_vivo as sv
from src import sumario as sm


def _fila(area, ubic, sku, cant, lpn="L1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubic, "Llena", lpn, "D1", sku, sku, desc,
        str(cant), "0", "0", "08/07/2025 15:55:58", "23/05/2026 13:30:12",
        "01/12/2027 00:00:00", "", "Disponible", "9999", "9529",
        "05/10/2026 13:07:15", area,
    ])


STOCK = "\n".join([
    _fila("AREA PICKING", "C01-01-01-01", "00447085", 40, "L1", "3R MANZANA"),
    _fila("AREA PICKING", "C01-01-02-01", "00700153", 20, "L2", "MIS CS"),
]) + "\n"

SUMARIO = """CAMION # : 012R-01 FECHA : 07-11-2026
801
PALLET PRODUCTO DESCRIPCION CANTIDAD
001 00447085 3R MANZANA 5GL VNR275X24 20
Sub Total 20
002 00700153 MIS_VARIET-CS-VNR187CCX24 5
Sub Total 5
TOTAL : 25 PESO: 0
"""


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(STOCK).guardar(ruta)
    sv.inicializar(ruta)
    sm.leer_texto(SUMARIO).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# El picker deja en staging
# --------------------------------------------------------------------------

def test_al_confirmar_el_pick_queda_en_staging(db):
    """El picker NO arma pallets: deja lo pickeado en STAGING."""
    pk.destinar(db, pd.DataFrame([("447085", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 20, "PICK1")

    assert cs.disponible_staging(db, "00447085") == 20
    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT area FROM {sv.TABLA} WHERE area = ?", (sv.AREA_STAGING,)
        ).fetchone()
    assert f["area"] == sv.AREA_STAGING


def test_staging_esta_vacio_al_inicio(db):
    assert cs.disponible_staging(db, "00447085") == 0
    assert cs.en_staging(db).empty


# --------------------------------------------------------------------------
# Estado de consolidacion
# --------------------------------------------------------------------------

def test_pallet_sin_juntar_marca_falta(db):
    p = cs.estado_pallet(db, "012R-01", "001")
    assert p is not None
    assert p.completo is False
    assert p.juntado == 0
    assert p.lineas[0]["falta"] == 20


def test_pallet_con_stock_en_staging_esta_completo(db):
    """Si el picker ya dejo las 20 cajas en staging, el pallet esta completo."""
    pk.destinar(db, pd.DataFrame([("447085", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 20, "PICK1")

    p = cs.estado_pallet(db, "012R-01", "001")
    assert p.completo is True
    assert p.juntado == 20
    assert p.lineas[0]["en_staging"] == 20
    assert p.lineas[0]["falta"] == 0


def test_pallet_parcial(db):
    pk.destinar(db, pd.DataFrame([("447085", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 10, "PICK1")

    p = cs.estado_pallet(db, "012R-01", "001")
    assert p.completo is False
    assert p.juntado == 10
    assert p.lineas[0]["falta"] == 10


def test_pallets_del_dia(db):
    ps = cs.pallets_del_dia(db)
    assert len(ps) == 2
    assert all(p["completo"] is False for p in ps)


def test_pallets_filtrado_por_camion(db):
    assert len(cs.pallets_del_dia(db, "012R-01")) == 2
    assert cs.pallets_del_dia(db, "NOEXISTE") == []


# --------------------------------------------------------------------------
# Consolidar
# --------------------------------------------------------------------------

def test_no_consolida_si_falta(db):
    r = cs.consolidar(db, "012R-01", "001", "CONSOL1")
    assert r["ok"] is False
    assert r["code"] == 400
    assert r["faltantes"]


def test_consolidar_descuenta_de_staging(db):
    pk.destinar(db, pd.DataFrame([("447085", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 20, "PICK1")
    assert cs.disponible_staging(db, "00447085") == 20

    r = cs.consolidar(db, "012R-01", "001", "CONSOL1")
    assert r["ok"] is True
    assert r["cajas"] == 20
    # Ya salio de staging
    assert cs.disponible_staging(db, "00447085") == 0


def test_consolidar_dos_veces_no_duplica(db):
    pk.destinar(db, pd.DataFrame([("447085", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 20, "PICK1")
    cs.consolidar(db, "012R-01", "001", "C1")

    p = cs.estado_pallet(db, "012R-01", "001")
    assert p.completo is True
    assert p.lineas[0]["consolidado"] == 20
    # Consolidar de nuevo no rompe ni duplica
    r = cs.consolidar(db, "012R-01", "001", "C1")
    assert r["ok"] is True
    p2 = cs.estado_pallet(db, "012R-01", "001")
    assert p2.lineas[0]["consolidado"] == 20


def test_consolidar_pallet_inexistente(db):
    r = cs.consolidar(db, "NOEXISTE", "999")
    assert r["ok"] is False and r["code"] == 404


def test_resumen_consolidacion(db):
    r = cs.resumen(db)
    assert r["pallets"] == 2
    assert r["completos"] == 0
    assert r["pendientes"] == 2
    assert r["cajas"] == 25
