"""Tests de la consulta de stock."""

from __future__ import annotations

import pytest

from src import consulta as cq
from src import inventario as inv
from src import stock_vivo as sv


def _fila(area, ubic, sku, cant, lpn="L1", desc="COLA", cad="01/12/2027 00:00:00"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubic, "Llena", lpn, "D1", sku, sku, desc,
        str(cant), "0", "0", "08/07/2025 15:55:58", "23/05/2026 13:30:12",
        cad, "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


STOCK = "\n".join([
    _fila("AREA PICKING", "C01-01-01-01", "000622", 100, "LA"),
    _fila("AREA ALMACENAMIENTO", "A-01-01-01", "000622", 500, "LB"),
    _fila("AREA PICKING", "C01-02-01-01", "007266", 30, "LC", "JUGO"),
]) + "\n"


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(STOCK).guardar(ruta)
    sv.inicializar(ruta)
    return str(ruta)


def test_consulta_total_y_ubicaciones(db):
    r = cq.consultar(db, "000622")
    assert r["encontrado"] is True
    assert r["total"] == 600
    assert len(r["ubicaciones"]) == 2
    assert r["en_picking"] == 100
    assert r["en_almacenamiento"] == 500


def test_consulta_acepta_sin_ceros(db):
    """Escribir '622' debe encontrar '000622'."""
    r = cq.consultar(db, "622")
    assert r["encontrado"] is True
    assert r["total"] == 600


def test_consulta_trae_descripcion(db):
    r = cq.consultar(db, "7266")
    assert r["descripcion"] == "JUGO"


def test_consulta_descuenta_lo_reservado(db):
    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT id FROM {sv.TABLA} WHERE lpn = 'LA'").fetchone()
        sv.reservar(con, f["id"], 40)
    r = cq.consultar(db, "000622")
    assert r["reservado"] == 40
    # El disponible de picking baja a 60
    ub = [u for u in r["ubicaciones"] if u["ubicacion"] == "C01-01-01-01"][0]
    assert ub["disponible"] == 60


def test_consulta_lotes_en_orden_fefo(db, tmp_path):
    ruta = tmp_path / "t2.sqlite"
    inv.leer_detalle("\n".join([
        _fila("AREA PICKING", "C01-01-01-01", "000999", 10, "L1", "X",
              "01/06/2027 00:00:00"),
        _fila("AREA PICKING", "C01-01-01-01", "000999", 10, "L2", "X",
              "01/01/2027 00:00:00"),
    ]) + "\n").guardar(ruta)
    sv.inicializar(ruta)
    r = cq.consultar(ruta, "999")
    vencimientos = [l["vencimiento"] for l in r["lotes"]]
    assert vencimientos[0].startswith("01/01/2027"), "el que vence antes va primero"


def test_consulta_sku_inexistente_da_sugerencias_por_descripcion(db):
    r = cq.consultar(db, "JUGO")
    assert r["encontrado"] is False
    assert r["sugerencias"]
    assert r["sugerencias"][0]["sku"] == "007266"


def test_consulta_sin_resultados(db):
    r = cq.consultar(db, "NOEXISTE123")
    assert r["encontrado"] is False
    assert "error" in r


def test_consulta_codigo_vacio(db):
    r = cq.consultar(db, "")
    assert r["encontrado"] is False
    assert r["error"] == "falta el codigo"
