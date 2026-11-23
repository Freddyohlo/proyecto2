"""Tests del chequeo fisico por muestreo."""

from __future__ import annotations

import pytest

from src import chequeo as ch
from src import sumario as sm


def _sumario(n_pallets: int) -> str:
    """Genera un sumario con n pallets en un camion."""
    lineas = ["CAMION # : 012R-01 FECHA : 07-11-2026", "801",
              "PALLET PRODUCTO DESCRIPCION CANTIDAD"]
    for i in range(1, n_pallets + 1):
        lineas.append(f"{i:03d} 00447085 PRODUCTO {i} 10")
        lineas.append(f"Sub Total 10")
    lineas.append("TOTAL : 999 PESO: 0")
    return "\n".join(lineas)


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    sm.leer_texto(_sumario(100)).guardar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# Elegir la muestra
# --------------------------------------------------------------------------

def test_muestra_del_10_por_ciento(db):
    m = ch.elegir_muestra(db, porcentaje=10, semilla=1)
    assert m.pallets_total == 100
    assert m.cantidad == 10


def test_muestra_del_5_por_ciento(db):
    m = ch.elegir_muestra(db, porcentaje=5, semilla=1)
    assert m.cantidad == 5


def test_muestra_siempre_elige_al_menos_uno(db):
    """Con 3 pallets y 5%, el redondeo daria 0: igual se chequea 1."""
    ruta = db  # 100 pallets
    m = ch.elegir_muestra(ruta, porcentaje=1, semilla=1)
    assert m.cantidad >= 1


def test_muestra_es_reproducible_con_semilla(db):
    a = ch.elegir_muestra(db, 10, semilla=42)
    b = ch.elegir_muestra(db, 10, semilla=42)
    assert [p["pallet"] for p in a.elegidos] == [p["pallet"] for p in b.elegidos]


def test_muestra_cambia_con_otra_semilla(db):
    a = ch.elegir_muestra(db, 10, semilla=1)
    b = ch.elegir_muestra(db, 10, semilla=2)
    assert [p["pallet"] for p in a.elegidos] != [p["pallet"] for p in b.elegidos]


def test_muestra_no_repite_pallets(db):
    m = ch.elegir_muestra(db, 30, semilla=7)
    pallets = [p["pallet"] for p in m.elegidos]
    assert len(pallets) == len(set(pallets))


def test_muestra_del_100_por_ciento(db):
    m = ch.elegir_muestra(db, 100, semilla=1)
    assert m.cantidad == 100


def test_sin_sumario_no_hay_muestra(tmp_path):
    ruta = tmp_path / "vacia.sqlite"
    sm.Sumario(__import__("pandas").DataFrame(
        columns=["camion", "pallet", "sku", "descripcion", "cantidad"])).guardar(ruta)
    m = ch.elegir_muestra(ruta, 10)
    assert m.cantidad == 0 and m.pallets_total == 0


# --------------------------------------------------------------------------
# Ficha de chequeo
# --------------------------------------------------------------------------

def test_ficha_trae_lo_que_dice_el_sumario(db):
    f = ch.ficha(db, "012R-01", "001")
    assert f is not None
    assert f["skus"] == 1
    assert f["cajas"] == 10
    assert f["lineas"][0]["sku"] == "00447085"


def test_ficha_pallet_inexistente(db):
    assert ch.ficha(db, "NOEXISTE", "999") is None


def test_fichas_de_muestra(db):
    m = ch.elegir_muestra(db, 10, semilla=3)
    fs = ch.fichas_de_muestra(db, m)
    assert len(fs) == m.cantidad


# --------------------------------------------------------------------------
# Registrar el resultado
# --------------------------------------------------------------------------

def test_registrar_conforme(db):
    r = ch.registrar(db, "012R-01", "001", conforme=True, usuario="CHEQ1")
    assert r["ok"] is True and r["estado"] == "conforme"
    assert ch.resumen(db)["conformes"] == 1


def test_registrar_diferencia(db):
    r = ch.registrar(db, "012R-01", "002", conforme=False,
                     diferencia="faltan 2 cajas", observacion="pallet roto",
                     usuario="CHEQ1")
    assert r["estado"] == "diferencia"
    df = ch.chequeos(db)
    assert df.iloc[0]["diferencia"] == "faltan 2 cajas"
    assert df.iloc[0]["observacion"] == "pallet roto"


def test_registrar_dos_veces_actualiza_no_duplica(db):
    ch.registrar(db, "012R-01", "001", conforme=False, diferencia="falta 1")
    ch.registrar(db, "012R-01", "001", conforme=True)
    df = ch.chequeos(db)
    assert len(df) == 1
    assert df.iloc[0]["estado"] == "conforme"


def test_resumen_calcula_porcentaje(db):
    ch.registrar(db, "012R-01", "001", conforme=True)
    ch.registrar(db, "012R-01", "002", conforme=True)
    ch.registrar(db, "012R-01", "003", conforme=False, diferencia="x")
    r = ch.resumen(db)
    assert r["chequeos"] == 3
    assert r["conformes"] == 2
    assert r["diferencias"] == 1
    assert r["pct_conforme"] == 66.7


def test_resumen_sin_chequeos(db):
    r = ch.resumen(db)
    assert r["chequeos"] == 0 and r["pct_conforme"] == 0.0
