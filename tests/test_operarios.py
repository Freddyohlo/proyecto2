"""Tests de operarios fijos, PIN y terminar turno."""

from __future__ import annotations

import pandas as pd
import pytest

from src import inventario as inv
from src import operarios as op
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
    _fila("AREA PICKING", "60-001", "000622", 50, "01/12/2026 00:00:00", desc="COLA"),
    _fila("AREA PICKING", "60-002", "007266", 30, "01/01/2027 00:00:00", desc="JUGO"),
]) + "\n"


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    sv.inicializar(ruta)
    op.sembrar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Usuarios fijos
# --------------------------------------------------------------------------

def test_se_siembran_los_usuarios_por_defecto(db):
    picks = op.listar(db, "picking")
    gruas = op.listar(db, "grua")
    assert len(picks) == 4
    assert len(gruas) == 2
    assert {u["codigo"] for u in picks} == {"PICK1", "PICK2", "PICK3", "PICK4"}
    assert {u["codigo"] for u in gruas} == {"GRUA1", "GRUA2"}


def test_usuario_sin_nombre_muestra_solo_el_codigo(db):
    assert op.nombre(db, "PICK1") == ""
    assert op.etiqueta(db, "PICK1") == "PICK1"


def test_asignar_nombre_al_operario(db):
    """'el usuario PICK1 se destino al operario Juan'."""
    r = op.asignar(db, "PICK1", "Juan")
    assert r["ok"] is True
    assert op.nombre(db, "PICK1") == "Juan"
    assert op.etiqueta(db, "PICK1") == "PICK1 — Juan"


def test_asignar_no_pierde_el_pin(db):
    op.asignar(db, "PICK1", "Juan")
    assert op.verificar_pin(db, "PICK1", "1111") is True


def test_verificar_pin(db):
    assert op.verificar_pin(db, "PICK1", "1111") is True
    assert op.verificar_pin(db, "PICK1", "9999") is False
    assert op.verificar_pin(db, "", "1111") is False
    assert op.verificar_pin(db, "NOEXISTE", "1111") is False


# --------------------------------------------------------------------------
# Terminar turno
# --------------------------------------------------------------------------

def test_terminar_turno_libera_lo_no_pickeado(db):
    """El operario marca que pickeo el ultimo item y el trabajo pasa a otro."""
    pk.destinar(db, pd.DataFrame([("622", 20)], columns=["sku_clave", "cajas"]))
    # El operario toma su tarea (queda a su nombre)
    t = pk.tarea_pendiente(db, "PICK1")
    pk.tomar_tarea(db, t["id"], "PICK1")
    r = pk.terminar_turno(db, "PICK1")
    assert r["ok"] is True
    assert r["liberadas"] == 1
    assert r["cajas_liberadas"] == 20
    assert r["quedan_pendientes"] == 0
    # La mercaderia vuelve a estar disponible
    assert sv.resumen(db)["reservado"] == 0


def test_terminar_turno_no_toca_lo_pickeado(db):
    pk.destinar(db, pd.DataFrame([("622", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.tomar_tarea(db, t["id"], "PICK1")
    pk.confirmar(db, t["id"], 20, "PICK1")
    r = pk.terminar_turno(db, "PICK1")
    assert r["liberadas"] == 0
    assert sv.resumen(db)["pickeado"] == 20


def test_terminar_turno_deja_las_tareas_libres_para_otro(db):
    pk.destinar(db, pd.DataFrame([("622", 20)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db, "PICK1")
    pk.tomar_tarea(db, t["id"], "PICK1")
    pk.terminar_turno(db, "PICK1")
    # Otro operario las puede tomar
    pendiente = pk.tarea_pendiente(db)
    assert pendiente is None, "ya no hay pendientes: quedaron libres"
    assert "libre" in pk.resumen_tareas(db)


# --------------------------------------------------------------------------
# Productividad
# --------------------------------------------------------------------------

def test_productividad_cruza_usuario_con_movimientos(db):
    op.asignar(db, "PICK1", "Juan")
    op.asignar(db, "PICK2", "Pedro")

    pk.destinar(db, pd.DataFrame([("622", 50), ("7266", 30)],
                                 columns=["sku_clave", "cajas"]))
    # Juan toma y pickea las dos tareas
    for _ in range(2):
        t = pk.tarea_pendiente(db, "PICK1")
        if t is None:
            break
        pk.tomar_tarea(db, t["id"], "PICK1")
        pk.confirmar(db, t["id"], t["cantidad"], "PICK1")

    prod = {p["codigo"]: p for p in op.productividad(db, "picking")}
    assert prod["PICK1"]["nombre"] == "Juan"
    assert prod["PICK1"]["movimientos"] == 2
    assert prod["PICK1"]["cajas"] == 80
    assert prod["PICK2"]["movimientos"] == 0
    assert prod["PICK2"]["cajas"] == 0


def test_productividad_sin_movimientos(db):
    prod = op.productividad(db, "picking")
    assert len(prod) == 4
    assert all(p["movimientos"] == 0 for p in prod)
