"""Tests del lector GS1-128 (el codigo de barras de la tarja)."""

from __future__ import annotations

import pytest

import pytest

from src import gs1
from src import inventario as inv
from src import stock_vivo as sv

SSCC = "278043001201264701"

# La tarja real: SSCC + vencimiento 04/06/2027 + elaboracion 31/10/2026 + 198 cajas
GS1_COMPLETO = f"(00){SSCC}(17)270604(11)261031(30)198"


# --------------------------------------------------------------------------
# Fechas GS1 (YYMMDD)
# --------------------------------------------------------------------------

def test_fecha_gs1_basica():
    assert gs1._fecha_gs1("270604") == "04/06/2027"
    assert gs1._fecha_gs1("261031") == "31/10/2026"


def test_fecha_gs1_dia_cero_es_ultimo_dia_del_mes():
    """Regla GS1: el dia 00 significa el ULTIMO dia del mes."""
    assert gs1._fecha_gs1("270600") == "30/06/2027"
    assert gs1._fecha_gs1("270200") == "28/02/2027"


def test_fecha_gs1_pivote_del_anio():
    """YY < 70 -> 20YY ; si no -> 19YY."""
    assert gs1._fecha_gs1("250101") == "01/01/2025"
    assert gs1._fecha_gs1("990101") == "01/01/1999"


def test_fecha_gs1_invalidas():
    assert gs1._fecha_gs1("") == ""
    assert gs1._fecha_gs1("123") == ""
    assert gs1._fecha_gs1("271399") == ""      # mes 13
    assert gs1._fecha_gs1("abc") == ""


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------

def test_parsea_con_parentesis():
    r = gs1.parsear(GS1_COMPLETO)
    assert r.sscc == SSCC
    assert r.cantidad == 198
    assert r.fecha_vencimiento == "04/06/2027"
    assert r.fecha_elaboracion == "31/10/2026"


def test_parsea_sin_separadores():
    """La mayoria de los lectores NO manda FNC1: hay que cortar por longitud."""
    codigo = f"00{SSCC}172706041126103130198"
    r = gs1.parsear(codigo)
    assert r.sscc == SSCC
    assert r.cantidad == 198, "la cantidad no debe cortarse en pedazos"
    assert r.fecha_vencimiento == "04/06/2027"
    assert r.fecha_elaboracion == "31/10/2026"


def test_cantidad_no_se_parte_por_los_ai_internos():
    """BUG REAL: '198' se partia en '1' + AI(98) y la cantidad salia 1.

    Los AIs internos 90-99 NO deben usarse como corte de un valor variable.
    """
    r = gs1.parsear(f"00{SSCC}30198")
    assert r.cantidad == 198


def test_parsea_con_separador_gs_real():
    codigo = f"00{SSCC}172706041126103130198\x1d"
    r = gs1.parsear(codigo)
    assert r.cantidad == 198
    assert r.fecha_vencimiento == "04/06/2027"


def test_parsea_con_lote():
    codigo = f"(00){SSCC}(10)LOTE123(17)270604(30)198"
    r = gs1.parsear(codigo)
    assert r.lote == "LOTE123"
    assert r.cantidad == 198
    assert r.fecha_vencimiento == "04/06/2027"


def test_parsea_gtin():
    codigo = "(01)78012345678904(17)270604(30)198"
    r = gs1.parsear(codigo)
    assert r.gtin == "78012345678904"
    assert r.fecha_vencimiento == "04/06/2027"


def test_sscc_pelado_sigue_funcionando():
    """La tarja de un solo dato (18 digitos) tambien debe leerse."""
    r = gs1.parsear(SSCC)
    assert r.sscc == SSCC
    assert r.cantidad == 0
    assert r.fecha_vencimiento == ""


def test_codigo_vacio_o_basura():
    assert gs1.parsear("").sscc == ""
    assert gs1.parsear("").tiene_datos_utiles() is False
    r = gs1.parsear("XYZ")
    assert r.sscc == "" and r.no_reconocidos


def test_quita_identificador_de_simbologia():
    """Algunos lectores anteponen ]C1 (indicador de GS1-128)."""
    r = gs1.parsear("]C1" + f"00{SSCC}172706041126103130198")
    assert r.sscc == SSCC
    assert r.cantidad == 198


def test_pesos_y_medidas_de_4_digitos():
    codigo = f"00{SSCC}3103001234"
    r = gs1.parsear(codigo)
    assert r.valores.get("3103") == "001234"


def test_es_gs1():
    assert gs1.es_gs1(GS1_COMPLETO) is True
    assert gs1.es_gs1(f"00{SSCC}17270604") is True
    assert gs1.es_gs1("") is False


# --------------------------------------------------------------------------
# Integracion con recepcion
# --------------------------------------------------------------------------

def test_desde_escaneo_llena_los_datos():
    from src import recepcion as rc
    r = rc.desde_escaneo(GS1_COMPLETO, sku="700809", ubicacion="C16-01-01-01")
    assert r.lpn == SSCC
    assert r.cantidad == 198
    assert r.fecha_vencimiento == "04/06/2027"
    assert r.fecha_elaboracion == "31/10/2026"
    assert r.sku == "700809"          # el SKU no viene en el codigo: lo pone la pantalla


def test_desde_escaneo_respeta_la_cantidad_de_la_pantalla_si_el_codigo_no_la_trae():
    from src import recepcion as rc
    r = rc.desde_escaneo(f"00{SSCC}17270604", sku="700809", cantidad=50)
    assert r.cantidad == 50


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    fila = "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", "60-001", "Llena", "L1", "D1",
        "000622", "000622", "COLA", "12", "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", "01/12/2026 00:00:00",
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", "AREA PICKING",
    ]) + "\n"
    inv.leer_detalle(fila).guardar(ruta)
    sv.inicializar(ruta)
    return str(ruta)


def test_recepcion_completa_desde_escaneo(db):
    """Flujo real: escanear la tarja y recibir, sin digitar fechas."""
    from src import recepcion as rc
    from src import stock_vivo as sv

    r = rc.desde_escaneo(GS1_COMPLETO, sku="700809",
                         ubicacion="C16-01-01-01", usuario="RECEPTOR")
    res = rc.recibir_y_ubicar(db, r)
    assert res["ok"] is True

    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT cantidad, fecha_caducidad, ubicacion FROM {sv.TABLA} "
            "WHERE lpn = ?", (SSCC,)
        ).fetchone()
    assert int(f["cantidad"]) == 198
    assert f["fecha_caducidad"] == "04/06/2027"
    assert f["ubicacion"] == "C16-01-01-01"


# --------------------------------------------------------------------------
# Deteccion del SKU dentro del codigo
# --------------------------------------------------------------------------

def test_sku_en_ai_240():
    """El AI 240 (id adicional) es el lugar mas probable para el SKU."""
    codigo = f"00{SSCC}240007008091727060430198"
    cands = gs1.sku_candidatos(codigo)
    assert cands, "debe haber candidatos"
    assert cands[0][0] == "240"


def test_gtin_no_se_confunde_con_sku():
    """El GTIN (01) es el codigo global del producto, NO el SKU de bodega."""
    codigo = "(01)78012345678904(17)270604(30)198"
    cands = [v for ai, v in gs1.sku_candidatos(codigo)]
    assert "78012345678904" not in cands


def test_sscc_tampoco_es_sku():
    codigo = f"00{SSCC}1727060430198"
    cands = [v for ai, v in gs1.sku_candidatos(codigo)]
    assert SSCC not in cands


def test_candidatos_encuentran_el_sku_en_ai_240():
    """El AI 240 es el lugar mas probable para el codigo de producto."""
    codigo = f"00{SSCC}" + "240" + "700809" + "1727060430198"
    valores = [v for _, v in gs1.sku_candidatos(codigo)]
    assert "700809" in valores


def test_ubicar_sscc_usa_el_digito_de_control():
    """El SSCC se reconoce por su digito de control: sirve de ancla."""
    codigo = f"00{SSCC}" + "240" + "700809" + "17270604"
    pos, sscc = gs1.ubicar_sscc(codigo)
    assert sscc == SSCC
    assert codigo[pos:pos + 18] == SSCC


def test_describir_muestra_los_ais():
    codigo = f"(00){SSCC}(17)270604(11)261031(30)198"
    d = gs1.describir(codigo)
    por_ai = {x["ai"]: x for x in d}
    assert por_ai["00"]["valor"] == SSCC
    assert por_ai["17"]["interpretado"] == "04/06/2027"
    assert por_ai["30"]["interpretado"] == "198 unidades"


def test_identificar_sku_usa_el_stock_para_desambiguar(db):
    """De todos los numeros del codigo, el que existe en el stock es el SKU."""
    from src import recepcion as rc

    # El stock de prueba tiene 000622; el codigo trae 000622 y otros numeros.
    codigo = f"00{SSCC}" + "91000622" + "1727060430198"
    r = rc.identificar_sku(db, codigo)
    assert r["sku"] == "000622"
    assert r["origen"] == "stock"


def test_identificar_sku_avisa_si_no_esta_en_el_stock(db):
    """Si ningun candidato calza con el stock, se devuelve el mas probable + aviso."""
    from src import recepcion as rc

    codigo = f"00{SSCC}" + "240" + "700809" + "1727060430198"
    r = rc.identificar_sku(db, codigo)
    assert r["sku"] == "700809"
    assert r["origen"] == "codigo"
    assert "aviso" in r


def test_identificar_sku_sin_candidatos():
    from src import recepcion as rc
    r = rc.identificar_sku("no-existe.db", f"00{SSCC}17270604")
    assert r["sku"] == "" or r["origen"] in ("codigo", "stock")
