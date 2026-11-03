"""Tests del servidor de picking para terminales RF (prototipo de contingencia).

Se prueba la logica de seleccion FEFO y la de persistencia, que es lo critico.
El servidor HTTP se prueba de forma liviana (arranque real, un par de endpoints).
"""

from __future__ import annotations

import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import inventario as inv
from src import picking_servidor as ps


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 12, "01/12/2026 00:00:00", lpn="LPN_A"),
    _fila("AREA PICKING", "60-001", "000622", 30, "01/03/2027 00:00:00", lpn="LPN_B"),
    _fila("AREA PICKING", "60-002", "007266", 5, "01/01/2027 00:00:00", lpn="LPN_C"),
]) + "\n"


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "pick.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# FEFO
# --------------------------------------------------------------------------

def test_fefo_elige_el_lote_que_vence_antes(db):
    """Bug real: ordenar las fechas como texto elegia mal el lote.

    Como texto, "01/03/2027" < "01/12/2026", asi que devolvia el lote que vence
    MAS TARDE. Hay que parsear la fecha.
    """
    with ps._conectar(db) as con:
        dato = ps._buscar_sku(con, "60-001", "622")
    assert dato is not None
    assert dato["caducidad"] == "01/12/2026 00:00:00"
    assert dato["disponible"] == 12


def test_busca_por_lpn(db):
    with ps._conectar(db) as con:
        dato = ps._buscar_sku(con, "60-001", "LPN_B")
    assert dato is not None
    assert dato["caducidad"] == "01/03/2027 00:00:00"


def test_busca_por_sku_con_ceros(db):
    with ps._conectar(db) as con:
        dato = ps._buscar_sku(con, "60-002", "7266")
    assert dato is not None
    assert dato["sku"] == "007266"


def test_sku_que_no_esta_en_esa_ubicacion(db):
    with ps._conectar(db) as con:
        assert ps._buscar_sku(con, "60-002", "622") is None


def test_a_fecha_tolera_basura():
    from datetime import datetime
    assert ps._a_fecha("") == datetime.max
    assert ps._a_fecha("no es fecha") == datetime.max
    assert ps._a_fecha("01/12/2026").year == 2026


# --------------------------------------------------------------------------
# Parser del QR de ubicacion (los racks tienen QR; no sabemos el formato exacto)
# --------------------------------------------------------------------------

def test_parsear_ubicacion_codigo_pelado():
    assert ps.parsear_ubicacion("60-001") == "60-001"
    assert ps.parsear_ubicacion("  60-001  ") == "60-001"


def test_parsear_ubicacion_con_prefijo():
    assert ps.parsear_ubicacion("LOC:60-001") == "60-001"
    assert ps.parsear_ubicacion("UBIC:60-001") == "60-001"
    assert ps.parsear_ubicacion("ubicacion: 60-001") == "60-001"
    assert ps.parsear_ubicacion("STOLOC:60-001") == "60-001"


def test_parsear_ubicacion_desde_url():
    assert ps.parsear_ubicacion("https://wms.local/ub?loc=60-001") == "60-001"
    assert ps.parsear_ubicacion("http://host/x?ubicacion=60-001&otro=1") == "60-001"


def test_parsear_ubicacion_pipe():
    assert ps.parsear_ubicacion("60-001|AREA PICKING|PT01") == "60-001"


def test_parsear_ubicacion_no_reconocida_devuelve_tal_cual():
    assert ps.parsear_ubicacion("ALGO-RARO") == "ALGO-RARO"
    assert ps.parsear_ubicacion("") == ""


# --------------------------------------------------------------------------
# Persistencia de movimientos
# --------------------------------------------------------------------------

def test_movimientos_se_guardan_con_lote_y_vencimiento(db):
    with ps._conectar(db) as con:
        con.execute(
            """INSERT INTO picking
               (fecha, usuario, ubicacion, sku, lpn, cantidad, descripcion, lote, caducidad)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("2026-11-03T07:00:00", "RESIDENTE-STG", "60-001", "000622",
             "LPN_A", 5, "PRODUCTO", "LPN_A", "01/12/2026 00:00:00"),
        )
        con.commit()
    with sqlite3.connect(db) as con:
        fila = con.execute("SELECT ubicacion, sku, cantidad, caducidad FROM picking").fetchone()
    assert fila == ("60-001", "000622", 5, "01/12/2026 00:00:00")


# --------------------------------------------------------------------------
# Servidor HTTP (arranque real)
# --------------------------------------------------------------------------

@pytest.fixture()
def servidor(db):
    ps.Handler.db = db
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ps.Handler)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_pagina_de_picking_responde(servidor):
    with urllib.request.urlopen(servidor + "/") as r:
        html = r.read().decode()
    assert r.status == 200
    assert "Picking" in html
    assert "ubicacion" in html


def test_endpoint_ubicacion(servidor):
    import json
    with urllib.request.urlopen(servidor + "/api/ubicacion?codigo=60-001") as r:
        j = json.loads(r.read())
    assert j["ok"] is True
    assert j["skus"] == 1


def test_endpoint_sku_devuelve_fefo(servidor):
    import json
    with urllib.request.urlopen(servidor + "/api/sku?ubicacion=60-001&codigo=622") as r:
        j = json.loads(r.read())
    assert j["ok"] is True
    assert j["caducidad"] == "01/12/2026 00:00:00"


def test_endpoint_confirmar_rechaza_cantidad_excesiva(servidor):
    import json
    cuerpo = json.dumps({"ubicacion": "60-001", "codigo": "622",
                         "cantidad": 9999}).encode()
    req = urllib.request.Request(servidor + "/api/confirmar", data=cuerpo,
                                headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400
