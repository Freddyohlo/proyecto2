"""Tests del servidor de picking guiado (HTTP) sobre el stock vivo con reservas."""

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
]) + "\n"


def _demanda(pares):
    return pd.DataFrame(pares, columns=["sku_clave", "cajas"])


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
# Servidor HTTP (arranque real, con stock vivo)
# --------------------------------------------------------------------------

@pytest.fixture()
def servidor(tmp_path):
    db = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(db)
    sv.inicializar(db)
    pk.destinar(db, _demanda([("622", 20), ("7266", 5)]))

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


def test_portada_es_el_menu(servidor):
    """La raiz es la portada con menu (mas simple para el operario)."""
    base, _ = servidor
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode()
    assert r.status == 200
    assert "PICKEAR" in html and "RECIBIR MERCADERIA" in html


def test_pantalla_de_picking_responde(servidor):
    base, _ = servidor
    with urllib.request.urlopen(base + "/picking") as r:
        html = r.read().decode()
    assert r.status == 200
    assert "Picking" in html


def test_tarea_devuelve_la_primera_pendiente(servidor):
    base, _ = servidor
    j = _get(base + "/api/tarea")
    assert j["ok"] is True
    assert j["tarea"]["ubicacion"] == "60-001"
    assert j["tarea"]["cantidad"] == 12      # FEFO: lote A
    assert j["total"] == 3


def test_verificar_ubicacion_correcta_e_incorrecta(servidor):
    base, _ = servidor
    ok = _get(base + "/api/verificar?ubicacion=60-001&codigo=60-001")
    assert ok["ok"] is True
    mal = _get(base + "/api/verificar?ubicacion=60-001&codigo=60-002")
    assert mal["ok"] is False and mal["leida"] == "60-002"


def test_verificar_acepta_qr_con_prefijo(servidor):
    base, _ = servidor
    assert _get(base + "/api/verificar?ubicacion=60-001&codigo=LOC%3A60-001")["ok"] is True


def test_confirmar_rebaja_el_stock_vivo(servidor):
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]
    j = _post(base + "/api/confirmar", {"id": t["id"], "usuario": "RESIDENTE-STG",
                                       "cantidad": 12})
    assert j["ok"] is True and j["estado"] == "ok"

    s = sv.resumen(db)
    assert s["pickeado"] == 12
    with sqlite3.connect(db) as con:
        mov = con.execute("SELECT ubicacion, sku, cantidad, lote FROM picking").fetchone()
    assert mov == ("60-001", "000622", 12, "LPN_A")


def test_pick_parcial_reencola_y_ajusta_el_stock(servidor):
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]       # pide 12
    j = _post(base + "/api/confirmar", {"id": t["id"], "cantidad": 7})
    assert j["estado"] == "parcial"

    s = sv.resumen(db)
    assert s["pickeado"] == 7
    # lote A: se pickearon 7 y los 5 que faltan vuelven a reservarse |
    # lote B: 8 | 7266: 5
    assert s["reservado"] == 5 + 8 + 5


def test_no_deja_digitar_mas_de_lo_pedido(servidor):
    base, _ = servidor
    t = _get(base + "/api/tarea")["tarea"]
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
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]
    _post(base + "/api/confirmar", {"id": t["id"]})
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/api/confirmar", {"id": t["id"]})
    assert e.value.code == 400
    assert sv.resumen(db)["pickeado"] == 12      # no se rebajo dos veces


def test_al_terminar_no_hay_mas_tareas(servidor):
    base, _ = servidor
    for _ in range(5):
        t = _get(base + "/api/tarea")
        if t["ok"]:
            _post(base + "/api/confirmar", {"id": t["tarea"]["id"]})
    assert _get(base + "/api/tarea")["ok"] is False


def test_saltar_tarea_libera_la_reserva(servidor):
    base, db = servidor
    t = _get(base + "/api/tarea")["tarea"]       # 12 del lote A
    _post(base + "/api/saltar", {"id": t["id"]})
    s = sv.resumen(db)
    # se libero el lote A (12); siguen reservados el lote B (8) y el 7266 (5)
    assert s["reservado"] == 8 + 5
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT estado FROM tareas WHERE id=?", (t["id"],)).fetchone()[0] == "saltada"
