"""Tests de recepcion: recibir (tarja), ubicar, idempotencia y vencimiento."""

from __future__ import annotations

import sqlite3

import pytest

from src import inventario as inv
from src import recepcion as rc
from src import stock_vivo as sv
from src.recepcion import TABLA_RECEPCION


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 12, "01/12/2026 00:00:00", desc="COLA"),
]) + "\n"

# Tarja real que paso el usuario (imagen IMG_20261103_045905.jpg)
TARJA = dict(lpn="278043001201264701", sku="700809", cantidad=198,
             ubicacion="C16-01-01-01", almacen="CD8000",
             descripcion="GATO DULCE-DC-VNR1500CCX8-TR",
             fecha_elaboracion="31.10.2026 08:10",
             fecha_vencimiento="04.06.2027",
             cajas_pallet=60, perfil_antiguedad="999",
             usuario="RESIDENTE-STG")


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    sv.inicializar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Normalizacion de fechas
# --------------------------------------------------------------------------

def test_normalizar_fecha_formatos():
    assert rc.normalizar_fecha("05/10/2027") == "05/10/2027"
    assert rc.normalizar_fecha("05-10-2027") == "05/10/2027"
    assert rc.normalizar_fecha("05/10/2027 00:00:00") == "05/10/2027"
    assert rc.normalizar_fecha("2027-10-05") == "05/10/2027"
    assert rc.normalizar_fecha("") == ""
    assert rc.normalizar_fecha(None) == ""
    assert rc.normalizar_fecha("no es fecha") == ""


def test_normalizar_fecha_con_puntos_de_la_tarja():
    """BUG REAL: la tarja imprime las fechas con PUNTOS (31.10.2026), no barras.

    Antes esto devolvia "" y el vencimiento se perdia en silencio -> FEFO ciego.
    """
    assert rc.normalizar_fecha("31.10.2026") == "31/10/2026"
    assert rc.normalizar_fecha("04.06.2027") == "04/06/2027"
    assert rc.normalizar_fecha("31.10.2026 08:10") == "31/10/2026"
    assert rc.normalizar_fecha("31.10.2026 08:10:00") == "31/10/2026"


# --------------------------------------------------------------------------
# SSCC (el LPN de la tarja es un codigo GS1 estandar)
# --------------------------------------------------------------------------

def test_sscc_de_la_tarja_es_valido():
    """El LPN de la tarja real pasa el digito de control GS1."""
    assert rc.sscc_valido("278043001201264701") is True


def test_sscc_con_digito_cambiado_es_invalido():
    assert rc.sscc_valido("278043001201264702") is False


def test_sscc_de_largo_o_formato_incorrecto():
    assert rc.sscc_valido("") is False
    assert rc.sscc_valido("123") is False
    assert rc.sscc_valido("CD800000000HNRN") is False       # el LPN de la cuadratura
    assert rc.digito_control_sscc("123") is None


def test_recibir_avisa_si_el_sscc_no_cuadra(db):
    """Un escaneo malo se detecta por el digito de control (aviso, no bloqueo)."""
    r = rc.recibir(db, rc.Recepcion(lpn="278043001201264702", sku="700809",
                                    cantidad=10, fecha_vencimiento="01/01/2027"))
    assert r["ok"] is True
    assert r["sscc_ok"] is False
    assert any("digito de control" in a for a in r["avisos"])


def test_recibir_sscc_correcto_no_avisa(db):
    r = rc.recibir(db, rc.Recepcion(**TARJA))
    assert r["sscc_ok"] is True
    assert r["avisos"] == []


# --------------------------------------------------------------------------
# Campos de la tarja
# --------------------------------------------------------------------------

def test_cajas_pallet_y_pallets_completos():
    """La tarja trae 'CAJAS REALES' (198) y 'CAJAS / PALLET' (60)."""
    r = rc.Recepcion(**TARJA)
    assert r.pallets_completos() == round(198 / 60, 2)      # 3.3


def test_recibir_guarda_los_campos_de_la_tarja(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT * FROM {TABLA_RECEPCION} WHERE lpn = ?", (TARJA["lpn"],)
        ).fetchone()
    assert int(f["cajas_pallet"]) == 60
    assert f["perfil_antiguedad"] == "999"
    assert f["descripcion"] == TARJA["descripcion"]
    assert f["fecha_elaboracion"] == "31/10/2026"
    assert f["fecha_vencimiento"] == "04/06/2027"
    assert int(f["sscc_ok"]) == 1


# --------------------------------------------------------------------------
# Recibir + ubicar en un paso (optimizacion)
# --------------------------------------------------------------------------

def test_recibir_y_ubicar_en_un_paso(db):
    """Si la tarja trae la ubicacion, no hace falta confirmar dos veces."""
    r = rc.recibir_y_ubicar(db, rc.Recepcion(**TARJA))
    assert r["ok"] is True and r["paso_unico"] is True
    assert r["ubicacion"] == TARJA["ubicacion"]          # C16-01-01-01

    with sv.abrir(db) as con:
        en_rec = con.execute(
            f"SELECT COUNT(*) FROM {sv.TABLA} WHERE area = ?", (sv.AREA_RECEPCION,)
        ).fetchone()[0]
        ubicado = con.execute(
            f"SELECT cantidad, fecha_caducidad FROM {sv.TABLA} WHERE ubicacion = ?",
            (TARJA["ubicacion"],),
        ).fetchone()
    assert en_rec == 0
    assert int(ubicado["cantidad"]) == 198
    assert ubicado["fecha_caducidad"] == "04/06/2027"


def test_recibir_y_ubicar_sin_ubicacion_falla(db):
    r = rc.recibir_y_ubicar(db, rc.Recepcion(lpn="111", sku="700809", cantidad=5))
    assert r["ok"] is False and r["code"] == 400


def test_recibir_y_ubicar_respeta_la_ubicacion_explicita(db):
    r = rc.recibir_y_ubicar(db, rc.Recepcion(**TARJA), ubicacion_final="C99-99-99-99")
    assert r["ok"] is True
    assert r["ubicacion"] == "C99-99-99-99"


# --------------------------------------------------------------------------
# Recibir
# --------------------------------------------------------------------------

def test_recibir_tarja_real(db):
    r = rc.recibir(db, rc.Recepcion(**TARJA))
    assert r["ok"] is True
    assert r["lpn"] == "278043001201264701"
    assert r["cantidad"] == 198
    assert r["aviso_vencimiento"] is False


def test_recibir_deja_la_mercaderia_en_recepcion(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    with sv.abrir(db) as con:
        fila = con.execute(
            f"SELECT * FROM {sv.TABLA} WHERE lpn = ?", (TARJA["lpn"],)
        ).fetchone()
    assert fila["area"] == sv.AREA_RECEPCION
    assert fila["ubicacion"] == sv.AREA_RECEPCION
    assert int(fila["cantidad"]) == 198
    assert fila["fecha_caducidad"] == "04/06/2027"


def test_no_recibe_dos_veces_el_mismo_lpn(db):
    """Escaneo doble de la tarja no debe duplicar el ingreso."""
    rc.recibir(db, rc.Recepcion(**TARJA))
    r2 = rc.recibir(db, rc.Recepcion(**TARJA))
    assert r2["ok"] is False
    assert r2["code"] == 409
    assert r2["cantidad"] == 198

    with sv.abrir(db) as con:
        n = con.execute(
            f"SELECT COUNT(*) FROM {sv.TABLA} WHERE lpn = ?", (TARJA["lpn"],)
        ).fetchone()[0]
    assert n == 1


def test_recibir_sin_vencimiento_avisa(db):
    """Sin vencimiento FEFO no puede ordenar: hay que avisarlo."""
    r = rc.recibir(db, rc.Recepcion(lpn="111", sku="700809", cantidad=5))
    assert r["ok"] is True
    assert r["aviso_vencimiento"] is True


def test_recibir_sin_datos_obligatorios_falla(db):
    r = rc.recibir(db, rc.Recepcion(lpn="", sku="", cantidad=0))
    assert r["ok"] is False and r["code"] == 400
    assert "lpn" in r["error"] and "sku" in r["error"]


def test_recibir_cantidad_cero_falla(db):
    r = rc.recibir(db, rc.Recepcion(lpn="222", sku="700809", cantidad=0))
    assert r["ok"] is False and r["code"] == 400


# --------------------------------------------------------------------------
# Ubicar
# --------------------------------------------------------------------------

def test_ubicar_mueve_y_conserva_lote_y_vencimiento(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    r = rc.ubicar(db, 1, "C16-02-03-04", "RECEPTOR1")
    assert r["ok"] is True
    assert r["vencimiento"] == "04/06/2027"

    with sv.abrir(db) as con:
        # ya no esta en RECEPCION
        en_rec = con.execute(
            f"SELECT COUNT(*) FROM {sv.TABLA} WHERE area = ?", (sv.AREA_RECEPCION,)
        ).fetchone()[0]
        # esta en almacenamiento con su vencimiento
        f = con.execute(
            f"SELECT * FROM {sv.TABLA} WHERE ubicacion = ?", ("C16-02-03-04",)
        ).fetchone()
    assert en_rec == 0
    assert f["lpn"] == TARJA["lpn"]
    assert f["fecha_caducidad"] == "04/06/2027"
    assert f["area"] == sv.AREA_ALMACENAMIENTO
    assert int(f["cantidad"]) == 198


def test_no_se_puede_ubicar_dos_veces(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    assert rc.ubicar(db, 1, "C16-02-03-04")["ok"] is True
    r2 = rc.ubicar(db, 1, "C16-09-09-09")
    assert r2["ok"] is False and r2["code"] == 400


def test_ubicar_sin_ubicacion_falla(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    assert rc.ubicar(db, 1, "")["ok"] is False


def test_ubicar_recepcion_inexistente(db):
    r = rc.ubicar(db, 999, "C16-01-01-01")
    assert r["ok"] is False and r["code"] == 404


def test_lo_recibido_queda_disponible_para_reaprovisionar(db):
    """La mercaderia ubicada debe quedar como stock real en almacenamiento."""
    rc.recibir(db, rc.Recepcion(**TARJA))
    rc.ubicar(db, 1, "C16-02-03-04")
    with sv.abrir(db) as con:
        filas = sv.filas_disponibles(con, "700809", incluir_almacenamiento=True)
    assert len(filas) == 1
    assert filas[0]["ubicacion"] == "C16-02-03-04"


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------

def test_pendientes_lista_lo_recibido_sin_ubicar(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    rc.recibir(db, rc.Recepcion(lpn="222", sku="700809", cantidad=7))
    assert len(rc.pendientes(db)) == 2
    rc.ubicar(db, 1, "C16-02-03-04")
    assert len(rc.pendientes(db)) == 1


def test_resumen(db):
    rc.recibir(db, rc.Recepcion(**TARJA))
    rc.recibir(db, rc.Recepcion(lpn="222", sku="700809", cantidad=7))
    rc.ubicar(db, 1, "C16-02-03-04")
    r = rc.resumen(db)
    assert r["recepciones"] == 2
    assert r["cajas"] == 205
    assert r["pendientes"] == 1
    assert r["ubicadas"] == 1
    assert r["sin_vencimiento"] == 1        # el lpn 222 no trae vencimiento


def test_sugerir_ubicacion_para_sku_conocido(db):
    """Si el SKU ya se guarda en algun lado, se sugiere ahi (no dispersar)."""
    with sv.abrir(db) as con:
        sv.ingresar(con, ubicacion="C16-05-05-05", sku="000622", cantidad=50,
                    lpn="L1", area=sv.AREA_ALMACENAMIENTO)
    s = rc.sugerir_ubicacion(db, "622")
    assert s["ok"] is True
    assert s["ubicacion"] == "C16-05-05-05"
