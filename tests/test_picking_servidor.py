"""Tests del picking guiado (generacion de tareas FEFO + servidor para el Zebra)."""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pandas as pd
import pytest

from src import inventario as inv
from src import picking as pk
from src import picking_servidor as ps


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


# La ubicacion de picking es unica por SKU; hay lotes con vencimientos distintos.
DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 12, "01/12/2026 00:00:00", lpn="LPN_A", desc="COLA"),
    _fila("AREA PICKING", "60-001", "000622", 30, "01/03/2027 00:00:00", lpn="LPN_B", desc="COLA"),
    _fila("AREA PICKING", "60-002", "007266", 5, "01/01/2027 00:00:00", lpn="LPN_C", desc="JUGO"),
    _fila("AREA ALMACENAMIENTO", "A-01", "000622", 500, "01/06/2027 00:00:00", lpn="LPN_D", desc="COLA"),
]) + "\n"


def _stock():
    return inv.leer_detalle(DETALLE)


def _demanda(pares):
    return pd.DataFrame(pares, columns=["sku_clave", "cajas"])


# --------------------------------------------------------------------------
# Generacion de tareas
# --------------------------------------------------------------------------

def test_genera_tareas_por_ubicacion_no_por_sku():
    """El picking se dirige por ubicacion (unica por SKU)."""
    tareas, faltan = pk.generar_tareas(_stock(), _demanda([("622", 5)]))
    assert len(tareas) == 1
    assert tareas[0].ubicacion == "60-001"
    assert tareas[0].cantidad == 5
    assert faltan.empty


def test_fefo_toma_primero_el_lote_que_vence_antes():
    """Pide 20: 12 del lote que vence 01/12 y 8 del que vence 01/03."""
    tareas, _ = pk.generar_tareas(_stock(), _demanda([("622", 20)]))
    assert len(tareas) == 2
    assert tareas[0].lote == "LPN_A"      # vence 01/12/2026 (antes)
    assert tareas[0].cantidad == 12
    assert tareas[1].lote == "LPN_B"      # vence 01/03/2027
    assert tareas[1].cantidad == 8


def test_no_usa_almacenamiento_por_defecto():
    tareas, faltan = pk.generar_tareas(_stock(), _demanda([("622", 50)]))
    # solo hay 42 en picking (12+30); los 8 que faltan NO se toman del almacen
    assert sum(t.cantidad for t in tareas) == 42
    assert faltan.iloc[0]["faltante"] == 8


def test_puede_usar_almacenamiento_si_se_pide():
    tareas, faltan = pk.generar_tareas(
        _stock(), _demanda([("622", 50)]), incluir_almacenamiento=True)
    assert sum(t.cantidad for t in tareas) == 50
    assert faltan.empty
    # el almacenamiento va despues del picking
    assert tareas[-1].area == "AREA ALMACENAMIENTO"


def test_sku_sin_stock_queda_como_faltante():
    tareas, faltan = pk.generar_tareas(_stock(), _demanda([("999999", 7)]))
    assert tareas == []
    assert faltan.iloc[0]["sku"] == "999999"
    assert faltan.iloc[0]["faltante"] == 7


def test_normaliza_sku_con_ceros():
    tareas, _ = pk.generar_tareas(_stock(), _demanda([("000622", 3)]))
    assert len(tareas) == 1
    assert tareas[0].cantidad == 3


def test_sin_stock_o_sin_demanda_no_genera_nada():
    t, f = pk.generar_tareas(_stock(), _demanda([]))
    assert t == [] and f.empty

    vacio = inv.leer_detalle("")
    t2, f2 = pk.generar_tareas(vacio, _demanda([("622", 5)]))
    assert t2 == [] and f2.empty


def test_a_fecha_ordena_por_fecha_real():
    from datetime import datetime
    # como texto, "01/03/2027" < "01/12/2026" (mal); como fecha es al reves
    assert pk.a_fecha("01/12/2026") < pk.a_fecha("01/03/2027")
    assert pk.a_fecha("") == datetime.max
    assert pk.a_fecha(None) == datetime.max


# --------------------------------------------------------------------------
# Parser del QR (los racks traen solo la ubicacion)
# --------------------------------------------------------------------------

def test_parsear_ubicacion_formatos():
    assert ps.parsear_ubicacion("60-001") == "60-001"
    assert ps.parsear_ubicacion("  60-001  ") == "60-001"
    assert ps.parsear_ubicacion("LOC:60-001") == "60-001"
    assert ps.parsear_ubicacion("UBIC:60-001") == "60-001"
    assert ps.parsear_ubicacion("https://wms.local/ub?loc=60-001") == "60-001"
    assert ps.parsear_ubicacion("60-001|AREA PICKING") == "60-001"
    assert ps.parsear_ubicacion("") == ""


# --------------------------------------------------------------------------
# Persistencia de tareas
# --------------------------------------------------------------------------

def test_guardar_y_leer_primera_tarea(tmp_path):
    db = tmp_path / "t.sqlite"
    _stock().guardar(db)
    tareas, _ = pk.generar_tareas(_stock(), _demanda([("622", 20)]))
    pk.guardar_tareas(tareas, db)

    t = pk.tarea_pendiente(db)
    assert t is not None
    assert t["ubicacion"] == "60-001"
    assert t["cantidad"] == 12
    assert t["total"] == 2
    assert t["hechas"] == 0


# --------------------------------------------------------------------------
# Servidor HTTP (arranque real)
# --------------------------------------------------------------------------

@pytest.fixture()
def servidor(tmp_path):
    db = tmp_path / "t.sqlite"
    _stock().guardar(db)
    tareas, _ = pk.generar_tareas(_stock(), _demanda([("622", 20), ("7266", 5)]))
    pk.guardar_tareas(tareas, db)

    ps.Handler.db = str(db)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ps.Handler)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", str(db)
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _post(url, datos):
    cuerpo = json.dumps(datos).encode()
    req = urllib.request.Request(url, data=cuerpo,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_pagina_responde(servidor):
    base, _ = servidor
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode()
    assert r.status == 200
    assert "Picking" in html


def test_tarea_devuelve_la_primera_pendiente(servidor):
    base, _ = servidor
    j = _get(base + "/api/tarea")
    assert j["ok"] is True
    assert j["tarea"]["ubicacion"] == "60-001"
    assert j["tarea"]["cantidad"] == 12
    assert j["total"] == 3


def test_verificar_ubicacion_correcta_e_incorrecta(servidor):
    base, _ = servidor
    ok = _get(base + "/api/verificar?ubicacion=60-001&codigo=60-001")
    assert ok["ok"] is True
    mal = _get(base + "/api/verificar?ubicacion=60-001&codigo=60-002")
    assert mal["ok"] is False
    assert mal["leida"] == "60-002"


def test_verificar_acepta_qr_con_prefijo(servidor):
    base, _ = servidor
    j = _get(base + "/api/verificar?ubicacion=60-001&codigo=LOC%3A60-001")
    assert j["ok"] is True


def test_confirmar_marca_ok_y_guarda_movimiento(servidor):
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]
    j = _post(base + "/api/confirmar", {"id": t["id"], "usuario": "RESIDENTE-STG",
                                       "cantidad": 12})
    assert j["ok"] is True
    assert j["cantidad"] == 12
    assert j["estado"] == "ok"

    with sqlite3.connect(db) as con:
        estado = con.execute("SELECT estado FROM tareas WHERE id=?", (t["id"],)).fetchone()[0]
        mov = con.execute("SELECT ubicacion, sku, cantidad, lote FROM picking").fetchone()
    assert estado == "ok"
    assert mov == ("60-001", "000622", 12, "LPN_A")


def test_pick_parcial_reencola_lo_que_falta(servidor):
    """Si el picker saca menos, el resto vuelve a quedar pendiente."""
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]       # pide 12
    j = _post(base + "/api/confirmar", {"id": t["id"], "cantidad": 7})
    assert j["ok"] is True
    assert j["estado"] == "parcial"
    assert j["cantidad"] == 7

    with sqlite3.connect(db) as con:
        estado = con.execute("SELECT estado FROM tareas WHERE id=?", (t["id"],)).fetchone()[0]
        # La re-encolada es la ultima (id mas alto)
        nueva = con.execute(
            "SELECT cantidad, estado, ubicacion FROM tareas ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert estado == "parcial"
    assert nueva == (5, "pendiente", "60-001")     # 12 - 7, misma ubicacion


def test_no_deja_digitar_mas_de_lo_pedido(servidor):
    base, _ = servidor
    t = _get(base + "/api/tarea")["tarea"]       # pide 12
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/api/confirmar", {"id": t["id"], "cantidad": 99})
    assert e.value.code == 400


def test_cantidad_cero_o_negativa_es_rechazada(servidor):
    base, _ = servidor
    t = _get(base + "/api/tarea")["tarea"]
    for mala in (0, -3):
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(base + "/api/confirmar", {"id": t["id"], "cantidad": mala})
        assert e.value.code == 400


def test_sin_cantidad_asume_la_pedida(servidor):
    base, _ = servidor
    t = _get(base + "/api/tarea")["tarea"]
    j = _post(base + "/api/confirmar", {"id": t["id"]})
    assert j["ok"] is True and j["cantidad"] == 12


def test_confirmar_dos_veces_la_misma_tarea_falla(servidor):
    base, _ = servidor
    t = _get(base + "/api/tarea")["tarea"]
    _post(base + "/api/confirmar", {"id": t["id"]})
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/api/confirmar", {"id": t["id"]})
    assert e.value.code == 400


def test_al_terminar_no_hay_mas_tareas(servidor):
    base, _ = servidor
    for _ in range(3):
        t = _get(base + "/api/tarea")
        if t["ok"]:
            _post(base + "/api/confirmar", {"id": t["tarea"]["id"]})
    assert _get(base + "/api/tarea")["ok"] is False


def test_saltar_tarea_la_deja_fuera(servidor):
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]
    _post(base + "/api/saltar", {"id": t["id"]})
    siguiente = _get(base + "/api/tarea")["tarea"]
    assert siguiente["id"] != t["id"]
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT estado FROM tareas WHERE id=?", (t["id"],)).fetchone()[0] == "saltada"
