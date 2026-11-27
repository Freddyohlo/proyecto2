"""Tests del sumario de carga (la demanda del dia cuando cae el sistema)."""

from __future__ import annotations

import pytest

from src import sumario as sm

# Fragmento real del PDF (camion 012R-01, pallets 001 y 002 mixto)
TEXTO = """LOAD SUMMARY RET_CL SUMARIO DE CARGA *012R01*
CAMION # : 012R-01 FECHA : 07-11-2026 *012R01*
801
PALLET PRODUCTO DESCRIPCION CANTIDAD
001 00447085 3R MANZANA 5GL VNR275X24 20
Sub Total 20
002 00700153 MIS_VARIET-CS-VNR187CCX24 3
00700154 MIS_VARIET-SB-VNR187CCX24 1
00700229 GATO_PREMIUM-CS-VNR187CCX24 2
00700682 MIS_RES_MS-CS-VNR750CCX6-CO 5
Sub Total 11
TOTAL : 95 PESO: 0
viernes, 6 de noviembre de 2026 23:02:10 Página 1 de 14 *2026110700123801*
*2026110700123801*
Control de Portería
LOAD SUMMARY RET_CL SUMARIO DE CARGA *015R01*
CAMION # : 015R-01 FECHA : 07-11-2026 *015R01*
802
PALLET PRODUCTO DESCRIPCION CANTIDAD
001 00450607 CRISTAL VRE1200CCX10-TC 40
Sub Total 40
TOTAL : 515 PESO: 0
"""


def test_lee_las_lineas_de_producto():
    """6 lineas: 1 del pallet 001 + 4 del pallet 002 (mixto) + 1 del otro camion."""
    s = sm.leer_texto(TEXTO)
    assert s.filas == 6


def test_detecta_los_camiones():
    s = sm.leer_texto(TEXTO)
    assert s.camiones == ["012R-01", "015R-01"]


def test_cuenta_pallets_unicos():
    s = sm.leer_texto(TEXTO)
    # 012R-01 tiene pallets 001 y 002; 015R-01 tiene el 001 -> 3 en total
    assert s.pallets == 3


def test_suma_las_cajas():
    s = sm.leer_texto(TEXTO)
    assert s.cajas == 20 + 3 + 1 + 2 + 5 + 40


def test_pallet_mixto_tiene_varios_skus():
    s = sm.leer_texto(TEXTO)
    p = s.por_pallet()
    fila = p[(p["camion"] == "012R-01") & (p["pallet"] == "002")].iloc[0]
    assert fila["skus"] == 4
    assert fila["cajas"] == 11


def test_pallet_de_un_solo_sku():
    s = sm.leer_texto(TEXTO)
    p = s.por_pallet()
    fila = p[(p["camion"] == "012R-01") & (p["pallet"] == "001")].iloc[0]
    assert fila["skus"] == 1
    assert fila["cajas"] == 20


def test_demanda_por_sku_agrupa():
    """El mismo SKU en dos camiones se suma (es la demanda total del dia)."""
    s = sm.leer_texto(TEXTO)
    d = s.demanda_por_sku().set_index("sku_clave")["cajas"].to_dict()
    assert d["447085"] == 20
    assert d["700153"] == 3
    # 00450607 -> clave 450607
    assert d["450607"] == 40


def test_sku_conserva_los_ceros():
    s = sm.leer_texto(TEXTO)
    assert s.dataframe.iloc[0]["sku"] == "00447085"


def test_descripcion_se_lee_completa():
    s = sm.leer_texto(TEXTO)
    assert s.dataframe.iloc[0]["descripcion"] == "3R MANZANA 5GL VNR275X24"


def test_ignora_cabeceras_y_pies():
    s = sm.leer_texto(TEXTO)
    assert s.descartadas == 0, "no debe descartar lineas validas"


def test_texto_vacio():
    s = sm.leer_texto("")
    assert s.filas == 0 and s.cajas == 0 and s.camiones == []


def test_por_camion():
    s = sm.leer_texto(TEXTO)
    c = s.por_camion()
    f = c[c["camion"] == "012R-01"].iloc[0]
    assert f["pallets"] == 2
    assert f["skus"] == 5
    assert f["cajas"] == 31


# --------------------------------------------------------------------------
# Con el PDF real (si esta disponible)
# --------------------------------------------------------------------------

RUTA_PDF = "/workspace/project/data_externa/sumario_carga.pdf"


@pytest.mark.skipif(not __import__("os").path.exists(RUTA_PDF),
                    reason="PDF de ejemplo no disponible")
def test_pdf_real():
    """Datos verificados contra el PDF: 104 lineas, 92 pallets, 5.701 cajas.

    Las 104 lineas son 92 pallets + 12 continuaciones de pallets MIXTOS (que no
    repiten el numero de pallet). La suma de Sub Totales y la de TOTAL por camion
    dan las mismas 5.701 cajas: el parseo cuadra.
    """
    s = sm.cargar_desde_archivo(RUTA_PDF)
    assert s.filas == 104
    assert len(s.camiones) == 9
    assert s.pallets == 92
    assert s.cajas == 5701
    assert s.descartadas == 0


@pytest.mark.skipif(not __import__("os").path.exists(RUTA_PDF),
                    reason="PDF de ejemplo no disponible")
def test_pdf_real_demanda_por_sku():
    s = sm.cargar_desde_archivo(RUTA_PDF)
    d = s.demanda_por_sku()
    assert len(d) == 35, "35 SKUs distintos en el sumario real"
    assert d["cajas"].sum() == 5701
