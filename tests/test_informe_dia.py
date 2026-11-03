"""Tests del informe del dia y del alta de SKU nuevos (producto que va llegando)."""

from __future__ import annotations

import pandas as pd
import pytest

from src import informe_dia as inf
from src import inventario as inv
from src import picking as pk
from src import recepcion as rc
from src import stock_vivo as sv


def _fila(area, ubicacion, sku, cantidad, caducidad, lpn="LPN1", desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", lpn, "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", caducidad,
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


DETALLE = "\n".join([
    _fila("AREA PICKING", "60-001", "000622", 12, "01/12/2026 00:00:00", desc="COLA"),
    _fila("AREA PICKING", "60-002", "007266", 5, "01/01/2027 00:00:00", desc="JUGO"),
]) + "\n"

TARJA_NUEVA = dict(lpn="278043001201264701", sku="700809", cantidad=198,
                   descripcion="GATO DULCE", fecha_vencimiento="04.06.2027",
                   usuario="RECEPTOR")


@pytest.fixture()
def db(tmp_path):
    ruta = tmp_path / "t.sqlite"
    inv.leer_detalle(DETALLE).guardar(ruta)
    sv.inicializar(ruta)
    return str(ruta)


# --------------------------------------------------------------------------
# SKU nuevos (producto que viene llegando, no esta en la cuadratura)
# --------------------------------------------------------------------------

def test_crear_sku_nuevo_lo_ingresa_al_stock(db):
    r = rc.crear_sku(db, sku="700809", descripcion="GATO DULCE", cantidad=198,
                     ubicacion="C16-01-01-01", lpn=TARJA_NUEVA["lpn"],
                     fecha_vencimiento="04.06.2027", usuario="RECEPTOR")
    assert r["ok"] is True and r["nuevo"] is True

    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT cantidad, ubicacion FROM {sv.TABLA} WHERE sku_clave = ?",
            ("700809",),
        ).fetchone()
    assert int(f["cantidad"]) == 198
    assert f["ubicacion"] == "C16-01-01-01"


def test_crear_sku_sin_sku_falla(db):
    r = rc.crear_sku(db, sku="", cantidad=10)
    assert r["ok"] is False and r["code"] == 400


def test_sku_nuevo_queda_registrado(db):
    rc.crear_sku(db, sku="700809", descripcion="GATO DULCE", cantidad=198,
                 ubicacion="C16-01-01-01")
    df = rc.skus_nuevos(db)
    assert len(df) == 1
    assert df.iloc[0]["sku"] == "700809"


def test_sku_nuevo_sin_cantidad_solo_se_registra(db):
    """Se puede dar de alta el SKU sin ingresar stock (cantidad 0)."""
    r = rc.crear_sku(db, sku="999999", descripcion="NUEVO")
    assert r["ok"] is True
    assert len(rc.skus_nuevos(db)) == 1


def test_el_sku_nuevo_ya_se_puede_pickear(db):
    """Despues de darlo de alta, el SKU nuevo existe para el sistema."""
    rc.crear_sku(db, sku="700809", cantidad=100, ubicacion="C16-01-01-01",
                 lpn="L1", fecha_vencimiento="01/12/2027")
    with sv.abrir(db) as con:
        filas = sv.filas_disponibles(con, "700809", incluir_almacenamiento=True)
    assert len(filas) == 1
    assert int(filas[0]["cantidad"]) == 100


# --------------------------------------------------------------------------
# Informe del dia
# --------------------------------------------------------------------------

def test_recopilar_sin_movimiento(db):
    d = inf.recopilar(db, fecha="2026-11-03")
    assert d.fecha == "2026-11-03"
    assert d.cajas_pickeadas == 0
    assert d.cajas_recibidas == 0
    assert d.picking_mov.empty


def test_recopilar_junta_picking_y_recepcion(db):
    # Se pickea
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 10, "PICKER1")

    # Y se recibe
    rc.recibir(db, rc.Recepcion(**TARJA_NUEVA))

    d = inf.recopilar(db)
    assert d.cajas_pickeadas == 10
    assert d.cajas_recibidas == 198
    assert len(d.picking_mov) == 1
    assert len(d.recepcion_mov) == 1
    assert not d.por_sku.empty
    assert not d.ubicaciones.empty


def test_alertas_avisan_de_lo_pendiente(db):
    # Recepcion sin vencimiento y sin ubicar
    rc.recibir(db, rc.Recepcion(lpn="111", sku="700809", cantidad=5))
    d = inf.recopilar(db)
    textos = " ".join(a["texto"] for a in d.alertas())
    assert "sin fecha de vencimiento" in textos
    assert "sin ubicar" in textos


def test_alertas_ok_cuando_todo_bien(db):
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 10, "P1")
    d = inf.recopilar(db)
    assert any(a["nivel"] == "ok" for a in d.alertas())


def test_alertas_marcan_picks_parciales(db):
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 4, "P1")          # parcial
    d = inf.recopilar(db)
    assert any("parciales" in a["texto"] for a in d.alertas())


def test_generar_html_y_excel(db, tmp_path):
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 10, "P1")
    rc.recibir(db, rc.Recepcion(**TARJA_NUEVA))
    rc.crear_sku(db, sku="700809", cantidad=50, ubicacion="C16-01-01-01")

    d = inf.recopilar(db)
    html = inf.generar_html(d, tmp_path / "dia.html",
                            plantilla="templates/informe_dia.html.j2")
    xlsx = inf.generar_excel(d, tmp_path / "dia.xlsx")

    texto = html.read_text(encoding="utf-8")
    assert "Informe del día" in texto
    assert "Ubicaciones tocadas" in texto
    assert xlsx.exists() and xlsx.stat().st_size > 0


# --------------------------------------------------------------------------
# Producto nuevo: entra a ALMACENAMIENTO, nunca a PICKING
# --------------------------------------------------------------------------

def test_sku_nuevo_entra_a_almacenamiento_no_a_picking(db):
    """REGLA: un producto que recien llega NO tiene ubicacion de picking.

    Primero se guarda en altura (almacenamiento); despues el reaprovisionamiento
    lo baja al picking cuando corresponda.
    """
    rc.crear_sku(db, sku="700809", cantidad=198, ubicacion="C16-01-01-01",
                 lpn="LPN1", fecha_vencimiento="01/12/2027")
    with sv.abrir(db) as con:
        f = con.execute(
            f"SELECT area FROM {sv.TABLA} WHERE sku_clave = ?", ("700809",)
        ).fetchone()
    assert f["area"] == sv.AREA_ALMACENAMIENTO
    assert f["area"] != "AREA PICKING"


def test_sku_nuevo_no_aparece_en_las_tareas_de_picking(db):
    """El generador de tareas solo toma AREA PICKING: el nuevo no debe salir."""
    rc.crear_sku(db, sku="700809", cantidad=500, ubicacion="C16-01-01-01",
                 lpn="LPN1", fecha_vencimiento="01/12/2027")
    creadas, reservadas, _ = pk.destinar(
        db, pd.DataFrame([("700809", 100)], columns=["sku_clave", "cajas"]))
    assert creadas == 0, "un SKU nuevo en almacenamiento no debe generar picking"
    assert reservadas == 0


def test_sku_nuevo_si_sirve_para_reaprovisionar(db):
    """En almacenamiento SI queda disponible (para reapro o para picking con flag)."""
    rc.crear_sku(db, sku="700809", cantidad=100, ubicacion="C16-01-01-01",
                 lpn="LPN1", fecha_vencimiento="01/12/2027")
    with sv.abrir(db) as con:
        filas = sv.filas_disponibles(con, "700809", incluir_almacenamiento=True)
    assert len(filas) == 1


def test_crear_sku_reporta_el_area(db):
    r = rc.crear_sku(db, sku="700809", cantidad=10, ubicacion="C16-01-01-01")
    assert r["area"] == sv.AREA_ALMACENAMIENTO


# --------------------------------------------------------------------------
# Cierre del dia
# --------------------------------------------------------------------------

def test_cerrar_dia_libera_las_reservas_colgando(db):
    """Lo no pickeado vuelve a estar disponible al cerrar el dia."""
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    antes = sv.resumen(db)
    assert antes["reservado"] == 10

    cierre = pk.cerrar_dia(db, "SUPERVISOR")
    assert cierre["ok"] is True
    assert cierre["tareas_cerradas"] == 1
    assert cierre["cajas_liberadas"] == 10

    despues = sv.resumen(db)
    assert despues["reservado"] == 0
    assert despues["disponible"] == antes["disponible"] + 10


def test_cerrar_dia_no_toca_lo_pickeado(db):
    """Lo que ya se pickeo salio fisicamente: no se libera ni se borra."""
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    t = pk.tarea_pendiente(db)
    pk.confirmar(db, t["id"], 10, "P1")

    cierre = pk.cerrar_dia(db, "SUPERVISOR")
    assert cierre["tareas_cerradas"] == 0        # ya no habia pendientes
    r = sv.resumen(db)
    assert r["pickeado"] == 10
    assert r["reservado"] == 0


def test_cerrar_dia_marca_las_tareas_como_cerradas(db):
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    pk.cerrar_dia(db, "SUPERVISOR")
    assert pk.tarea_pendiente(db) is None
    assert "cerrada" in pk.resumen_tareas(db)


def test_cerrar_dia_dos_veces_no_rompe(db):
    pk.destinar(db, pd.DataFrame([("622", 10)], columns=["sku_clave", "cajas"]))
    pk.cerrar_dia(db, "S1")
    segunda = pk.cerrar_dia(db, "S1")
    assert segunda["ok"] is True
    assert segunda["tareas_cerradas"] == 0
