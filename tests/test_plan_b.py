"""Tests del Plan B: inventario offline y calculo de reposicion."""

from __future__ import annotations

from src import inventario as inv
from src import minmax as mm


def _fila(area, ubicacion, sku, lpn, cantidad, desc="PRODUCTO", caducidad="22/11/2052 15:55:58"):
    """Arma una fila de 22 columnas (formato cuadratura con Detalle)."""
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0000007RPCI",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


TSV = "\n".join([
    _fila("AREA PICKING", "60-001", "SKU1", "LPN1", 100),
    _fila("AREA PICKING", "60-002", "SKU2", "LPN2", 50),
    _fila("AREA ALMACENAMIENTO", "A-01-01", "SKU1", "LPN3", 500),
    _fila("AREA ALMACENAMIENTO", "A-01-02", "SKU2", "LPN4", 30),
    _fila("AREA ALMACENAMIENTO", "A-01-03", "SKU3", "LPN5", 200),
]) + "\n"


def test_leer_detalle_columnas_y_tipos():
    r = inv.leer_detalle(TSV)
    assert r.filas == 5
    assert list(r.dataframe.columns) == inv.COLUMNAS_DETALLE
    assert r.dataframe["cantidad"].dtype == "int64"
    assert r.dataframe.iloc[0]["sku"] == "SKU1"
    assert r.dataframe.iloc[0]["area"] == "AREA PICKING"


def test_descarta_lineas_basura():
    r = inv.leer_detalle(TSV + "\nbasura\ncorta\tfila\n")
    assert r.filas == 5
    assert r.descartadas == 2


def test_resumen_sku_separa_picking_y_almacen():
    r = inv.leer_detalle(TSV)
    res = r.resumen_sku("SKU1")
    assert res["en_picking"] == 100
    assert res["en_almacenamiento"] == 500
    assert res["total"] == 600
    assert res["ubicaciones"] == 2


def test_buscar_por_sku_descripcion_ubicacion():
    r = inv.leer_detalle(TSV)
    assert len(r.buscar("SKU1")) == 2
    assert len(r.buscar("60-00")) == 2
    assert len(r.buscar("producto")) == 5


def test_fefo_ordena_por_vencimiento():
    tsv = "\n".join([
        _fila("AREA PICKING", "60-001", "SKU9", "L1", 10, caducidad="22/12/2052 00:00:00"),
        _fila("AREA PICKING", "60-001", "SKU9", "L2", 10, caducidad="22/01/2050 00:00:00"),
    ]) + "\n"
    r = inv.leer_detalle(tsv)
    ordenado = r.fefo("SKU9")
    assert list(ordenado["lpn"]) == ["L2", "L1"]  # vence antes primero


def test_guardar_y_cargar_sqlite(tmp_path):
    r = inv.leer_detalle(TSV)
    db = tmp_path / "t.sqlite"
    r.guardar(db)
    recargado = inv.Inventario.cargar(db)
    assert len(recargado.dataframe) == 5
    assert recargado.resumen_sku("SKU2")["total"] == 80


# --------------------------------------------------------------------------
# Minimos / maximos y reposicion
# --------------------------------------------------------------------------
MINMAX_TSV = "\n".join([
    "ubicacion\tsku\tminimo\tmaximo",
    "60-001\tSKU1\t30\t200",   # tiene 100 -> NO repone
    "60-002\tSKU2\t80\t300",   # tiene 50 -> REPONE 300 (hay 30 en almacen -> NO cubre)
    "60-003\tSKU3\t10\t50",    # no existe en picking -> no aparece
]) + "\n"


def test_leer_minmax_mapea_columnas():
    m = mm.leer_minmax(MINMAX_TSV)
    assert len(m.dataframe) == 3
    assert m.dataframe.iloc[0]["minimo"] == 30
    assert m.dataframe.iloc[0]["maximo"] == 200


def test_leer_minmax_columnas_alternativas():
    tsv = "loc\tart\tmin\tmax\n60-001\tSKU1\t30\t200\n"
    m = mm.leer_minmax(tsv, col_ubicacion="loc", col_sku="art",
                       col_minimo="min", col_maximo="max")
    assert m.dataframe.iloc[0]["sku"] == "SKU1"


def test_leer_minmax_error_si_faltan_columnas():
    try:
        mm.leer_minmax("a\tb\n1\t2\n")
    except ValueError as e:
        assert "Faltan columnas" in str(e)
    else:
        raise AssertionError("debia fallar")


def test_reposicion_detecta_bajo_minimo_y_calcula_hasta_maximo():
    stock = inv.leer_detalle(TSV)
    m = mm.leer_minmax(MINMAX_TSV)
    items = mm.calcular_reposicion(stock, m)
    # Solo SKU2 (60-002) esta bajo el minimo (50 < 80)
    assert len(items) == 1
    it = items[0]
    assert it.ubicacion == "60-002"
    assert it.sku == "SKU2"
    assert it.stock_actual == 50
    assert it.reponer == 300           # hasta el maximo, sin descontar lo que hay
    assert it.disponible_almacen == 30
    assert it.cubre is False           # el almacen no alcanza


def test_reposicion_vacia_sin_minmax():
    stock = inv.leer_detalle(TSV)
    m = mm.MinMax(mm.leer_minmax("ubicacion\tsku\tminimo\tmaximo\n").dataframe)
    assert mm.calcular_reposicion(stock, m) == []


def test_reposicion_cubre_cuando_almacen_alcanza():
    tsv = "\n".join([
        _fila("AREA PICKING", "60-001", "SKU1", "L1", 10),
        _fila("AREA ALMACENAMIENTO", "A-1", "SKU1", "L2", 900),
    ]) + "\n"
    stock = inv.leer_detalle(tsv)
    m = mm.leer_minmax("ubicacion\tsku\tminimo\tmaximo\n60-001\tSKU1\t50\t200\n")
    items = mm.calcular_reposicion(stock, m)
    assert len(items) == 1
    assert items[0].cubre is True


# --------------------------------------------------------------------------
# Formato REAL de 'Operaciones de reabastecimiento' (18 columnas)
# --------------------------------------------------------------------------
# Fila real de ejemplo del PC del usuario
REAB_FILA = ("CD8000\t000622\tKEG-04\tZM PICKING\tDisponible\tUnchecked\t168\t160\t0\t"
             "Unchecked\t28/10/2026 03:06:29\tRSUAREZ\tRCF00006U3\tUnchecked\t100\t100\t0\tZM-PICK")


def test_leer_reabastecimiento_columnas_reales():
    m = mm.leer_reabastecimiento(REAB_FILA + "\n")
    assert len(m.dataframe) == 1
    fila = m.dataframe.iloc[0]
    assert fila["sku"] == "000622"
    assert fila["ubicacion"] == "KEG-04"
    assert fila["maximo"] == 168     # 'Máximo de unidades' (col 7)
    assert fila["minimo"] == 160     # 'Mínimo de unidades' (col 8)


def test_reabastecimiento_descarta_basura():
    m = mm.leer_reabastecimiento(REAB_FILA + "\nbasura\n" + REAB_FILA + "\n")
    assert len(m.dataframe) == 2


def test_reposicion_con_formato_real_de_reabastecimiento():
    # Ubicacion KEG-04 con 100 en picking (< min 160) y 900 en almacen
    stock_tsv = "\n".join([
        _fila("AREA PICKING", "KEG-04", "000622", "L1", 100),
        _fila("AREA ALMACENAMIENTO", "A-1", "000622", "L2", 900),
    ]) + "\n"
    stock = inv.leer_detalle(stock_tsv)
    m = mm.leer_reabastecimiento(REAB_FILA + "\n")
    items = mm.calcular_reposicion(stock, m)
    assert len(items) == 1
    it = items[0]
    assert it.ubicacion == "KEG-04"
    assert it.stock_actual == 100
    assert it.minimo == 160
    assert it.reponer == 168         # hasta el maximo
    assert it.cubre is True          # 900 >= 168
