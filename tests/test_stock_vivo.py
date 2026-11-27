"""Tests del stock vivo: reservas, rebajas y que NO se pueda hacer doble picking."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from src import inventario as inv
from src import picking as pk
from src import stock_vivo as sv


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 12, "01/12/2026 00:00:00", lpn="LPN_A", desc="COLA"),
    _fila("AREA PICKING", "60-001", "000622", 30, "01/03/2027 00:00:00", lpn="LPN_B", desc="COLA"),
    _fila("AREA PICKING", "60-002", "007266", 5, "01/01/2027 00:00:00", lpn="LPN_C", desc="JUGO"),
    _fila("AREA ALMACENAMIENTO", "A-01", "000622", 500, "01/06/2027 00:00:00", lpn="LPN_D", desc="COLA"),
]) + "\n"


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    sv.inicializar(ruta)
    return str(ruta)


def _demanda(pares):
    return pd.DataFrame(pares, columns=["sku_clave", "cajas"])


# --------------------------------------------------------------------------
# Inicializacion
# --------------------------------------------------------------------------

def test_inicializar_copia_la_foto(db):
    r = sv.resumen(db)
    assert r["total"] == 12 + 30 + 5 + 500
    assert r["reservado"] == 0
    assert r["pickeado"] == 0
    assert r["disponible"] == r["total"]


def test_inicializar_no_toca_la_foto_original(db):
    """`stock` es el respaldo de lo que decia Blue Yonder: no se modifica."""
    with sqlite3.connect(db) as con:
        antes = con.execute("SELECT SUM(cantidad) FROM stock").fetchone()[0]
    sv.inicializar(db, forzar=True)
    with sqlite3.connect(db) as con:
        despues = con.execute("SELECT SUM(cantidad) FROM stock").fetchone()[0]
    assert antes == despues


def test_inicializar_no_repite_filas(db):
    n1 = sv.inicializar(db)
    n2 = sv.inicializar(db)
    assert n1 == n2


# --------------------------------------------------------------------------
# Reservas
# --------------------------------------------------------------------------

def test_reservar_baja_el_disponible(db):
    with sv.abrir(db) as con:
        fila = con.execute(
            "SELECT id FROM stock_vivo WHERE lpn='LPN_A'").fetchone()
        assert sv.reservar(con, fila["id"], 7) is True
        assert sv.disponible_de(con, fila["id"]) == 5      # 12 - 7


def test_no_se_puede_reservar_mas_de_lo_que_hay(db):
    with sv.abrir(db) as con:
        fila = con.execute("SELECT id FROM stock_vivo WHERE lpn='LPN_A'").fetchone()
        assert sv.reservar(con, fila["id"], 12) is True
        assert sv.reservar(con, fila["id"], 1) is False    # ya no queda
        assert sv.disponible_de(con, fila["id"]) == 0


def test_liberar_devuelve_el_disponible(db):
    with sv.abrir(db) as con:
        fila = con.execute("SELECT id FROM stock_vivo WHERE lpn='LPN_A'").fetchone()
        sv.reservar(con, fila["id"], 5)
        sv.liberar(con, fila["id"], 5)
        assert sv.disponible_de(con, fila["id"]) == 12


def test_rebajar_suelta_reserva_y_suma_pickeado(db):
    with sv.abrir(db) as con:
        fila = con.execute("SELECT id FROM stock_vivo WHERE lpn='LPN_A'").fetchone()
        sv.reservar(con, fila["id"], 12)
        sv.rebajar(con, fila["id"], reservado=12, pickeado=7)
        assert sv.disponible_de(con, fila["id"]) == 5      # 12 - 0 - 7


# --------------------------------------------------------------------------
# Destinar: lo importante es que NO se destine dos veces
# --------------------------------------------------------------------------

def test_destinar_reserva_el_stock(db):
    creadas, reservadas, _ = pk.destinar(db, _demanda([("622", 20)]))
    assert creadas == 2          # 12 del lote A + 8 del lote B
    assert reservadas == 20
    r = sv.resumen(db)
    assert r["reservado"] == 20
    assert r["disponible"] == r["total"] - 20


def test_destinar_dos_veces_no_duplica_el_picking(db):
    """LA PRUEBA CLAVE: destinar dos veces no puede reservar la misma caja."""
    pk.destinar(db, _demanda([("622", 20)]))
    r1 = sv.resumen(db)

    # Segunda corrida con la misma demanda
    creadas2, reservadas2, faltan2 = pk.destinar(db, _demanda([("622", 20)]))
    r2 = sv.resumen(db)

    # El reservado NO se duplica: sigue siendo 20 (las pendientes se limpian)
    assert r2["reservado"] == r1["reservado"] == 20
    assert r2["disponible"] == r1["disponible"]
    # Y el faltante aparece: solo hay 42 en picking, ya reservamos 20 -> quedan 22
    assert creadas2 == 2 and reservadas2 == 20


def test_destinar_agota_picking_y_usa_almacenamiento(db):
    """Por defecto TAMBIEN busca en almacenamiento (flujo real confirmado).

    Picking tiene 42 y almacenamiento 500 -> los 60 se cubren.
    """
    creadas, reservadas, faltan = pk.destinar(db, _demanda([("622", 60)]))
    assert reservadas == 60
    assert faltan.empty


def test_destinar_solo_picking_reporta_faltante(db):
    """Con solo_picking, lo que no alcanza en picking es faltante."""
    creadas, reservadas, faltan = pk.destinar(
        db, _demanda([("622", 60)]), incluir_almacenamiento=False)
    assert reservadas == 42
    assert faltan.iloc[0]["faltante"] == 18


def test_destinar_respeta_fefo_tambien_desde_almacenamiento(db):
    """Al usar almacenamiento, el orden sigue siendo FEFO."""
    pk.destinar(db, _demanda([("622", 60)]))
    with sv.abrir(db) as con:
        filas = con.execute(
            "SELECT lote, area FROM tareas WHERE estado='pendiente' ORDER BY id"
        ).fetchall()
    # Primero el picking (lote A, vence antes), despues el lote B y luego almacen
    assert filas[0]["area"] == "AREA PICKING"
    assert any(f["area"] == sv.AREA_ALMACENAMIENTO for f in filas)


def test_destinar_respeta_fefo(db):
    pk.destinar(db, _demanda([("622", 20)]))
    with sv.abrir(db) as con:
        filas = con.execute(
            "SELECT lote, cantidad FROM tareas WHERE estado='pendiente' ORDER BY id"
        ).fetchall()
    assert filas[0]["lote"] == "LPN_A"     # vence 01/12/2026
    assert filas[0]["cantidad"] == 12
    assert filas[1]["lote"] == "LPN_B"


def test_destinar_sin_stock_no_reserva_nada(db):
    creadas, reservadas, faltan = pk.destinar(db, _demanda([("999999", 5)]))
    assert creadas == 0 and reservadas == 0
    assert sv.resumen(db)["reservado"] == 0


# --------------------------------------------------------------------------
# Confirmar / saltar liberan bien
# --------------------------------------------------------------------------

def test_confirmar_rebaja_y_libera(db):
    pk.destinar(db, _demanda([("622", 20)]))
    t = pk.tarea_pendiente(db)
    r = pk.confirmar(db, t["id"], 12, "RESIDENTE-STG")
    assert r["ok"] and r["estado"] == "ok"

    s = sv.resumen(db)
    # El lote A tenia 12: se pickearon 12 -> queda 0 disponible de esa fila
    # El lote B sigue reservado con 8
    assert s["pickeado"] == 12
    assert s["reservado"] == 8


def test_confirmar_parcial_libera_lo_que_sobra(db):
    pk.destinar(db, _demanda([("622", 20)]))
    t = pk.tarea_pendiente(db)          # pide 12 del lote A
    r = pk.confirmar(db, t["id"], 5, "RESIDENTE-STG")
    assert r["estado"] == "parcial"

    # Se pickearon 5; los 7 que faltan vuelven a quedar disponibles/reservados
    # en una tarea nueva, y el lote B sigue reservado con 8.
    pendientes = pk.resumen_tareas(db).get("pendiente", {}).get("cajas", 0)
    assert pendientes == 7 + 8


def test_confirmar_excedido_se_rechaza(db):
    pk.destinar(db, _demanda([("622", 20)]))
    t = pk.tarea_pendiente(db)
    r = pk.confirmar(db, t["id"], 99, "x")
    assert r["ok"] is False and r["code"] == 400
    assert sv.resumen(db)["reservado"] == 20     # no cambio nada


def test_saltar_libera_la_reserva(db):
    pk.destinar(db, _demanda([("622", 20)]))
    t = pk.tarea_pendiente(db)
    pk.saltar(db, t["id"], "RESIDENTE-STG")
    s = sv.resumen(db)
    assert s["reservado"] == 8          # solo queda el lote B
    assert s["disponible"] == s["total"] - 8


def test_confirmar_dos_veces_la_misma_tarea(db):
    pk.destinar(db, _demanda([("622", 20)]))
    t = pk.tarea_pendiente(db)
    assert pk.confirmar(db, t["id"], 12, "x")["ok"] is True
    segunda = pk.confirmar(db, t["id"], 12, "x")
    assert segunda["ok"] is False and segunda["code"] == 400
    assert sv.resumen(db)["pickeado"] == 12      # no se rebajo dos veces


def test_la_suma_reservado_mas_pickeado_nunca_pasa_la_foto(db):
    """Invariante: reservado + pickeado <= cantidad, en toda fila."""
    pk.destinar(db, _demanda([("622", 60)]), incluir_almacenamiento=True)
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 12, "x")
    with sv.abrir(db) as con:
        malas = con.execute(
            "SELECT COUNT(*) FROM stock_vivo WHERE reservado + pickeado > cantidad"
        ).fetchone()[0]
    assert malas == 0
