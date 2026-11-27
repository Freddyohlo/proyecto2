"""Tests de cuadratura de stock y comprometido por carga."""

from __future__ import annotations

import pandas as pd
import pytest

from src import cuadratura as cua
from src import inventario as inv
from src import picking as pk
from src import stock_vivo as sv
from src import sumario as sm


def _fila(area, ubic, sku, cant, lpn="L1", desc="COLA"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubic, "Llena", lpn, "D1", sku, sku, desc,
        str(cant), "0", "0", "08/07/2025 15:55:58", "23/05/2026 13:30:12",
        "01/12/2027 00:00:00", "", "Disponible", "9999", "9529",
        "05/10/2026 13:07:15", area,
    ])


STOCK = "\n".join([
    _fila("AREA PICKING", "C01-01-01-01", "00000622", 500),
    _fila("AREA ALMACENAMIENTO", "A-01-01-01", "00000622", 300),
]) + "\n"

SUMARIO = """CAMION # : 012R-01 FECHA : 07-11-2026
801
PALLET PRODUCTO DESCRIPCION CANTIDAD
001 000622 COLA 200
Sub Total 200
TOTAL : 200 PESO: 0
"""


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(STOCK).guardar(ruta)
    sv.inicializar(ruta)
    sm.leer_texto(SUMARIO).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Cuadratura
# --------------------------------------------------------------------------

def test_cuadratura_trae_el_stock(db):
    c = cua.cuadratura_actual(db)
    assert c.cajas == 800
    assert len(c.lineas) == 2


def test_cuadratura_por_sku_agrupa(db):
    c = cua.cuadratura_actual(db)
    s = cua.por_sku(c)
    assert len(s) == 1
    assert s[0]["cantidad"] == 800
    assert s[0]["ubicaciones"] == 2


def test_cuadratura_muestra_libre_vs_comprometido(db):
    """Reserva 200 para el camion: el libre baja a 600."""
    pk.destinar(db, pd.DataFrame([("622", 200)], columns=["sku_clave", "cajas"]))
    c = cua.cuadratura_actual(db)
    r = c.resumen()
    assert r["cajas"] == 800
    assert r["reservado"] == 200
    assert r["disponible"] == 600
    s = cua.por_sku(c)[0]
    assert s["reservado"] == 200
    assert s["disponible"] == 600


# --------------------------------------------------------------------------
# Comprometido por carga
# --------------------------------------------------------------------------

def _destinar_con_camion(db, cajas=200):
    """Destina con el detalle del sumario, para que la tarea quede con camion."""
    s = sm.Sumario.cargar(db)
    return pk.destinar(db, pd.DataFrame([("622", cajas)],
                                        columns=["sku_clave", "cajas"]),
                       detalle=s.dataframe)


def test_comprometido_por_carga(db):
    _destinar_con_camion(db)
    cargas = cua.comprometido_por_carga(db)
    assert len(cargas) >= 1
    c = cargas[0]
    assert c["camion"] == "012R-01"
    assert c["reservado"] == 200
    assert c["comprometido"] == 200


def test_comprometido_despues_de_pickear(db):
    _destinar_con_camion(db)
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 200, "PICK1")
    r = cua.comprometido_de(db, "00000622")
    assert r["pickeado"] == 200
    assert r["reservado"] == 0
    assert r["total"] == 200


def test_comprometido_por_carga_filtra_por_sku(db):
    _destinar_con_camion(db)
    assert len(cua.comprometido_por_carga(db, "00000622")) >= 1
    assert cua.comprometido_por_carga(db, "999999") == []


# --------------------------------------------------------------------------
# Corte del dia
# --------------------------------------------------------------------------

def test_guardar_corte(db):
    r = cua.guardar_corte(db, usuario="SUPERVISOR", nota="Corte 19:00")
    assert r["ok"] is True
    assert r["cajas"] == 800
    df = cua.cortes(db)
    assert len(df) == 1
    assert df.iloc[0]["nota"] == "Corte 19:00"


def test_corte_guarda_la_foto(db):
    """El corte deja una tabla con las lineas, para comparar despues."""
    r = cua.guardar_corte(db)
    import sqlite3
    with sqlite3.connect(db) as con:
        n = con.execute(f"SELECT COUNT(*) FROM {r['tabla']}").fetchone()[0]
    assert n == 2


def test_guardar_corte_dos_veces_reemplaza(db):
    cua.guardar_corte(db, nota="primero")
    cua.guardar_corte(db, nota="segundo")
    df = cua.cortes(db)
    assert len(df) == 1, "no debe duplicar el corte de la misma fecha"
    assert df.iloc[0]["nota"] == "segundo"


def test_comparar_detecta_movimientos(db):
    """Si pickeo entre el corte y ahora, la comparacion lo muestra."""
    cua.guardar_corte(db)
    # Ahora pickeo 200 (sale de la bodega hacia staging)
    pk.destinar(db, pd.DataFrame([("622", 200)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.confirmar(db, t["id"], 200, "PICK1")

    r = cua.comparar_con_corte_anterior(db)
    assert r["ok"] is True
    assert r["cambios"] >= 1


def test_comparar_sin_corte(db):
    r = cua.comparar_con_corte_anterior(db, fecha="2020-01-01")
    assert r["ok"] is False
