"""Tests del reaprovisionamiento guiado (almacenamiento -> picking)."""

from __future__ import annotations

import pytest

from src import inventario as inv
from src import minmax as mm
from src import reapro as rp
from src import stock_vivo as sv


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


# Picking 60-001 bajo el minimo (5 < 20) y almacenamiento con stock
DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 5, "01/12/2026 00:00:00", desc="COLA"),
    _fila("AREA ALMACENAMIENTO", "A-01", "000622", 500, "01/06/2027 00:00:00", desc="COLA"),
]) + "\n"

# Fila de la grilla de reabastecimiento: 18 columnas, max=col7, min=col8
FILA_REAB = "\t".join([
    "CD8000", "000622", "60-001", "ZM PICKING", "Disponible", "Unchecked",
    "200", "20", "1", "Completo", "", "", "1", "0", "UN", "0", "0", "ZM PICKING",
])


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    sv.inicializar(ruta)
    mm.leer_reabastecimiento(FILA_REAB).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Calcular
# --------------------------------------------------------------------------

def test_detecta_el_picking_bajo_el_minimo(db):
    n = rp.calcular(db)
    assert len(n) == 1
    assert n[0].ubicacion_picking == "60-001"
    assert n[0].stock_actual == 5
    assert n[0].minimo == 20
    assert n[0].maximo == 200


def test_reponer_es_hasta_el_maximo_sin_descontar(db):
    """Regla: max=200 y quedan 5 -> se reponen 200 (quedarian 205)."""
    n = rp.calcular(db)[0]
    assert n.reponer == 200
    assert n.cubre is True


def test_no_reporta_las_que_estan_sobre_el_minimo(db, tmp_path):
    ruta = tmp_path / "t2.sqlite"
    inv.leer_detalle("\n".join([
        _fila("AREA PICKING", "60-001", "000622", 50, "01/12/2026 00:00:00"),
    ]) + "\n").guardar(ruta)
    sv.inicializar(ruta)
    mm.leer_reabastecimiento(FILA_REAB).guardar(ruta)
    assert rp.calcular(ruta) == []


def test_marca_cuando_no_alcanza_el_almacen(db, tmp_path):
    ruta = tmp_path / "t3.sqlite"
    inv.leer_detalle("\n".join([
        _fila("AREA PICKING", "60-001", "000622", 5, "01/12/2026 00:00:00"),
        _fila("AREA ALMACENAMIENTO", "A-01", "000622", 30, "01/06/2027 00:00:00"),
    ]) + "\n").guardar(ruta)
    sv.inicializar(ruta)
    mm.leer_reabastecimiento(FILA_REAB).guardar(ruta)
    n = rp.calcular(ruta)[0]
    assert n.reponer == 200 and n.disponible_origen == 30
    assert n.cubre is False


def test_respeta_lo_reservado(db):
    """Si el picking tiene stock pero esta reservado, cuenta como no disponible."""
    with sv.abrir(db) as con:
        f = con.execute(f"SELECT id FROM {sv.TABLA} WHERE area='AREA PICKING'").fetchone()
        sv.reservar(con, f["id"], 5)
    n = rp.calcular(db)
    assert n and n[0].stock_actual == 0


# --------------------------------------------------------------------------
# Destinar (a un operador de grua)
# --------------------------------------------------------------------------

def test_destinar_crea_tareas_para_el_operador(db):
    r = rp.destinar(db, operador="GRUA1", usuario="SUPERVISOR")
    assert r["ok"] is True
    assert r["creadas"] >= 1
    assert r["cajas"] == 200

    t = rp.tarea_pendiente(db, "GRUA1")
    assert t is not None
    assert t["origen"] == "A-01"
    assert t["destino"] == "60-001"
    assert t["cantidad"] == 200


def test_destinar_reserva_el_origen(db):
    rp.destinar(db, operador="GRUA1")
    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT reservado FROM {sv.TABLA} WHERE area = ?",
            (sv.AREA_ALMACENAMIENTO,),
        ).fetchone()
    assert int(f["reservado"]) == 200


def test_confirmar_mueve_de_almacen_a_picking(db):
    rp.destinar(db, operador="GRUA1")
    t = rp.tarea_pendiente(db)
    r = rp.confirmar(db, t["id"], 200, "GRUA1")
    assert r["ok"] is True
    assert r["destino"] == "60-001"

    with sv.abrir(db) as con:
        # El origen baja: 500 en total, 200 pickeados (bajados)
        alm = con.execute(
            f"SELECT cantidad, pickeado FROM {sv.TABLA} WHERE area = ?",
            (sv.AREA_ALMACENAMIENTO,),
        ).fetchone()
        # El destino sube: en picking quedan DOS filas (lotes separados) = 205
        total = con.execute(
            f"""SELECT SUM(cantidad) AS c FROM {sv.TABLA}
                 WHERE ubicacion = '60-001' AND area = 'AREA PICKING'"""
        ).fetchone()

    assert int(alm["cantidad"]) == 500 and int(alm["pickeado"]) == 200
    assert int(total["c"]) == 205, "5 + 200 = 205 (se excede el maximo, es correcto)"


def test_confirmar_conserva_lote_y_vencimiento(db):
    """Lo que baja de almacenamiento CONSERVA su lote y su vencimiento.

    Ademas NO se mezcla con el lote que ya estaba en picking: queda como fila
    aparte. Eso es lo correcto para FEFO (el lote viejo se consume primero).
    """
    rp.destinar(db, operador="GRUA1")
    t = rp.tarea_pendiente(db)
    rp.confirmar(db, t["id"], 200, "GRUA1")

    with sv.abrir(db) as con:
        filas = con.execute(
            f"""SELECT lpn, cantidad, fecha_caducidad FROM {sv.TABLA}
                 WHERE ubicacion='60-001' AND area='AREA PICKING'
                 ORDER BY fecha_ord"""
        ).fetchall()

    assert len(filas) == 2, "los lotes deben quedar separados (no mezclados)"
    assert filas[0]["fecha_caducidad"] == "01/12/2026 00:00:00"   # el viejo, primero
    assert filas[1]["fecha_caducidad"] == "01/06/2027 00:00:00"   # el que bajo
    assert int(filas[1]["cantidad"]) == 200
    # El total en la ubicacion sube a 205
    assert sum(int(f["cantidad"]) for f in filas) == 205


def test_destinar_dos_veces_no_duplica(db):
    rp.destinar(db, operador="GRUA1")
    r1 = sv.resumen(db)["reservado"]
    rp.destinar(db, operador="GRUA1")
    r2 = sv.resumen(db)["reservado"]
    assert r1 == r2, "no debe reservar dos veces"


def test_confirmar_dos_veces_falla(db):
    rp.destinar(db, operador="GRUA1")
    t = rp.tarea_pendiente(db)
    assert rp.confirmar(db, t["id"], 200)["ok"] is True
    segunda = rp.confirmar(db, t["id"], 200)
    assert segunda["ok"] is False and segunda["code"] == 400


def test_destinar_sin_necesidades(db, tmp_path):
    ruta = tmp_path / "t4.sqlite"
    inv.leer_detalle("\n".join([
        _fila("AREA PICKING", "60-001", "000622", 500, "01/12/2026 00:00:00"),
    ]) + "\n").guardar(ruta)
    sv.inicializar(ruta)
    mm.leer_reabastecimiento(FILA_REAB).guardar(ruta)
    r = rp.destinar(ruta, operador="GRUA1")
    assert r["creadas"] == 0


def test_resumen(db):
    rp.destinar(db, operador="GRUA1")
    r = rp.resumen(db)
    assert r["tareas"] >= 1 and r["pendientes"] >= 1 and r["hechas"] == 0


# --------------------------------------------------------------------------
# PIN y nombres de operadores
# --------------------------------------------------------------------------

def test_verificar_pin():
    assert rp.verificar_pin("GRUA1", "1111") is True
    assert rp.verificar_pin("GRUA2", "2222") is True
    assert rp.verificar_pin("GRUA1", "2222") is False
    assert rp.verificar_pin("GRUA1", "") is False
    assert rp.verificar_pin("", "1111") is False
    assert rp.verificar_pin("GRUA9", "1111") is False


def test_nombre_y_etiqueta_del_operador():
    assert rp.nombre_operador("GRUA1") == "Carlos"
    assert rp.nombre_operador("GRUA2") == "Manuel"
    assert rp.nombre_operador("DESCONOCIDO") == ""
    assert rp.etiqueta_operador("GRUA1") == "GRUA1 — Carlos"
    assert rp.etiqueta_operador("X") == "X"


def test_tarea_filtra_por_operador(db):
    """Cada grua ve solo lo suyo (y lo que no tiene operador asignado)."""
    rp.destinar(db, operador="GRUA1")
    t1 = rp.tarea_pendiente(db, "GRUA1")
    assert t1 is not None
    assert t1["operador"] == "GRUA1"


# --------------------------------------------------------------------------
# El reapro aparece en el informe del dia
# --------------------------------------------------------------------------

def test_informe_incluye_reapro(db):
    from src import informe_dia as inf

    rp.destinar(db, operador="GRUA1", usuario="SUPERVISOR")
    t = rp.tarea_pendiente(db)
    rp.confirmar(db, t["id"], 200, "GRUA1")

    d = inf.recopilar(db)
    assert d.reapro["tareas"] >= 1
    assert d.cajas_reapro == 200
    assert not d.reapro_mov.empty
    assert d.reapro_mov.iloc[0]["operador"] == "GRUA1"
    assert d.reapro_mov.iloc[0]["origen"] == "A-01"
    assert d.reapro_mov.iloc[0]["destino"] == "60-001"


def test_informe_avisa_reapro_sin_confirmar(db):
    from src import informe_dia as inf

    rp.destinar(db, operador="GRUA1")
    d = inf.recopilar(db)
    textos = " ".join(a["texto"] for a in d.alertas())
    assert "sin confirmar" in textos


def test_informe_sin_reapro_no_falla(db):
    from src import informe_dia as inf
    d = inf.recopilar(db)
    assert d.reapro["tareas"] == 0
    assert d.cajas_reapro == 0
    assert d.reapro_mov.empty
