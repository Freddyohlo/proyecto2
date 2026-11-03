"""Reaprovisionamiento guiado (Plan B).

Cuando el stock de una ubicacion de PICKING baja del MINIMO, hay que reponer
desde ALMACENAMIENTO hasta el MAXIMO.

Regla de negocio confirmada por el usuario:
  - Se dispara por stock minimo en la ubicacion de picking.
  - Se repone desde ubicaciones de almacenamiento (en altura).
  - Se repone HASTA EL MAXIMO, aunque se exceda
    (ej.: max=200, quedan 20 -> se reponen 200 -> quedan 220).

Flujo (idea del usuario):
  1. Un dashboard muestra los productos que estan BAJO EL MINIMO.
  2. El supervisor aprieta un boton y se GENERAN las tareas de reapro.
  3. Las tareas quedan destinadas a un OPERADOR DE GRUA, que las ve en su Zebra:
     "baja N cajas de la ubicacion A-01-01 al picking 60-001".

Diferencia con el picking normal: aca el movimiento es
ALMACENAMIENTO -> PICKING (no sale de la bodega). Por eso se reserva el origen
y se SUMA al destino al confirmar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv
from .externos import clave_sku

TABLA_REAPRO = "reapro"


@dataclass
class NecesidadReapro:
    ubicacion_picking: str
    sku: str
    descripcion: str
    stock_actual: int
    minimo: int
    maximo: int
    reponer: int
    origen_sugerido: str = ""
    disponible_origen: int = 0
    cubre: bool = False


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------

def preparar_tablas(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_REAPRO} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, operador TEXT,
            sku TEXT, sku_clave TEXT, descripcion TEXT,
            origen TEXT, destino TEXT, cantidad INTEGER,
            fila_origen INTEGER, reservado INTEGER DEFAULT 0,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            fecha_ok TEXT, cantidad_ok INTEGER DEFAULT 0
        )
    """)


# ---------------------------------------------------------------------------
# Calcular que falta reponer
# ---------------------------------------------------------------------------

def calcular(db: str | Path) -> list[NecesidadReapro]:
    """Ubicaciones de picking bajo el minimo, con cuanto reponer.

    Usa el STOCK VIVO (no la foto): asi respeta lo ya reservado y pickeado.
    """
    with sv.abrir(db) as con:
        minmax = con.execute("SELECT * FROM minmax").fetchall() if _existe(con, "minmax") else []
        if not minmax:
            return []

        vivo = con.execute(
            f"""SELECT ubicacion, sku, sku_clave, descripcion, area,
                       (cantidad - reservado - pickeado) AS disponible
                  FROM {sv.TABLA}"""
        ).fetchall()

    # Stock disponible por ubicacion de PICKING
    picking: dict[tuple[str, str], int] = {}
    desc_sku: dict[str, str] = {}
    for f in vivo:
        if f["area"] == "AREA PICKING":
            k = (str(f["ubicacion"]), str(f["sku_clave"]))
            picking[k] = picking.get(k, 0) + int(f["disponible"] or 0)
        if f["descripcion"]:
            desc_sku.setdefault(str(f["sku_clave"]), str(f["descripcion"]))

    # Disponible por SKU en ALMACENAMIENTO (para saber si alcanza)
    almacen: dict[str, int] = {}
    for f in vivo:
        if f["area"] == sv.AREA_ALMACENAMIENTO:
            almacen[str(f["sku_clave"])] = almacen.get(str(f["sku_clave"]), 0) + int(
                f["disponible"] or 0)

    resultado: list[NecesidadReapro] = []
    for m in minmax:
        ubic = str(m["ubicacion"])
        sku = str(m["sku"])
        clave = clave_sku(sku)
        minimo = int(m["minimo"] or 0)
        maximo = int(m["maximo"] or 0)
        actual = picking.get((ubic, clave), 0)
        if actual >= minimo or maximo <= 0:
            continue
        disponible = almacen.get(clave, 0)
        # Regla: se repone HASTA EL MAXIMO, sin descontar lo que ya hay.
        reponer = maximo
        resultado.append(NecesidadReapro(
            ubicacion_picking=ubic, sku=sku,
            descripcion=desc_sku.get(clave, ""),
            stock_actual=actual, minimo=minimo, maximo=maximo,
            reponer=reponer, disponible_origen=disponible,
            cubre=disponible >= reponer,
        ))

    resultado.sort(key=lambda n: (n.cubre, -n.reponer))
    return resultado


def _existe(con, tabla: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Destinar (generar las tareas para el operador de grua)
# ---------------------------------------------------------------------------

def destinar(db: str | Path, operador: str = "", usuario: str = "",
             incluir_sin_stock: bool = False) -> dict:
    """Genera las tareas de reapro y las asigna a un OPERADOR DE GRUA.

    Reserva el stock de la ubicacion de ORIGEN (almacenamiento) para que nadie
    mas lo tome mientras la grua lo baja.
    """
    necesidades = calcular(db)
    if not necesidades:
        return {"ok": True, "creadas": 0, "cajas": 0,
                "aviso": "no hay ubicaciones bajo el minimo"}

    momento = datetime.now().isoformat(timespec="seconds")
    creadas = 0
    cajas = 0
    sin_origen: list[str] = []

    with sv.abrir(db) as con:
        preparar_tablas(con)

        # Limpia las pendientes anteriores (suelta sus reservas)
        for t in con.execute(
            f"SELECT fila_origen, reservado FROM {TABLA_REAPRO} WHERE estado = 'pendiente'"
        ).fetchall():
            if t["fila_origen"]:
                sv.liberar(con, t["fila_origen"], int(t["reservado"] or 0))
        con.execute(f"DELETE FROM {TABLA_REAPRO} WHERE estado = 'pendiente'")

        for n in necesidades:
            clave = clave_sku(n.sku)
            # Buscar de donde bajarlo: almacenamiento con stock disponible, FEFO
            origenes = sv.filas_disponibles(con, clave, incluir_almacenamiento=True)
            origenes = [o for o in origenes if o["area"] == sv.AREA_ALMACENAMIENTO]
            restante = n.reponer

            for o in origenes:
                if restante <= 0:
                    break
                disp = sv.disponible_de(con, o["id"])
                if disp <= 0:
                    continue
                tomar = min(restante, disp)
                if not sv.reservar(con, o["id"], tomar):
                    continue
                con.execute(
                    f"""INSERT INTO {TABLA_REAPRO}
                        (fecha, usuario, operador, sku, sku_clave, descripcion,
                         origen, destino, cantidad, fila_origen, reservado)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (momento, usuario, operador, n.sku, clave, n.descripcion,
                     o["ubicacion"], n.ubicacion_picking, tomar, o["id"], tomar),
                )
                creadas += 1
                cajas += tomar
                restante -= tomar

            if restante > 0 and incluir_sin_stock:
                con.execute(
                    f"""INSERT INTO {TABLA_REAPRO}
                        (fecha, usuario, operador, sku, sku_clave, descripcion,
                         origen, destino, cantidad, fila_origen, reservado)
                        VALUES (?,?,?,?,?,?,?,?,?,0,0)""",
                    (momento, usuario, operador, n.sku, clave, n.descripcion,
                     "", n.ubicacion_picking, restante),
                )
                creadas += 1
                cajas += restante
            elif restante > 0:
                sin_origen.append(n.sku)

    return {"ok": True, "creadas": creadas, "cajas": cajas, "operador": operador,
            "sin_stock_suficiente": sin_origen[:20]}


# ---------------------------------------------------------------------------
# Consultar / confirmar
# ---------------------------------------------------------------------------

def tarea_pendiente(db: str | Path, operador: str = "") -> dict | None:
    """Primera tarea de reapro pendiente (del operador, si se indica)."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        sql = f"SELECT * FROM {TABLA_REAPRO} WHERE estado = 'pendiente'"
        params: tuple = ()
        if operador:
            sql += " AND (operador = ? OR operador = '')"
            params = (operador,)
        sql += " ORDER BY id LIMIT 1"
        fila = con.execute(sql, params).fetchone()
        if fila is None:
            return None
        total = con.execute(
            f"SELECT COUNT(*) FROM {TABLA_REAPRO}").fetchone()[0]
        hechas = con.execute(
            f"SELECT COUNT(*) FROM {TABLA_REAPRO} WHERE estado = 'ok'").fetchone()[0]
    return {**dict(fila), "total": total, "hechas": hechas}


def confirmar(db: str | Path, id_tarea: int, cantidad: int = 0,
              usuario: str = "") -> dict:
    """Confirma la bajada: sale del origen y ENTRA al destino (picking).

    A diferencia del picking normal, aca la mercaderia NO sale de la bodega:
    se mueve de almacenamiento a picking. Por eso se suma al destino.
    """
    momento = datetime.now().isoformat(timespec="seconds")

    with sv.abrir(db) as con:
        preparar_tablas(con)
        t = con.execute(f"SELECT * FROM {TABLA_REAPRO} WHERE id = ?", (id_tarea,)).fetchone()
        if t is None:
            return {"ok": False, "error": "tarea inexistente", "code": 404}
        if t["estado"] != "pendiente":
            return {"ok": False, "error": "la tarea ya no esta pendiente", "code": 400}

        pedida = int(t["cantidad"])
        movida = cantidad or pedida
        if movida <= 0 or movida > pedida:
            return {"ok": False,
                    "error": f"cantidad invalida (pedido {pedida})", "code": 400}

        # Sale del origen (se suelta la reserva y se descuenta)
        if t["fila_origen"]:
            sv.rebajar(con, t["fila_origen"], int(t["reservado"] or 0), movida)

        # Entra al destino (picking), con el mismo lote y vencimiento
        origen = con.execute(
            f"SELECT * FROM {sv.TABLA} WHERE id = ?", (t["fila_origen"],)
        ).fetchone() if t["fila_origen"] else None

        sv.ingresar(
            con,
            ubicacion=str(t["destino"]),
            sku=str(t["sku"]),
            cantidad=movida,
            lpn=str(origen["lpn"]) if origen else "",
            descripcion=str(t["descripcion"] or ""),
            area="AREA PICKING",
            fecha_caducidad=str(origen["fecha_caducidad"]) if origen else "",
        )

        con.execute(
            f"""UPDATE {TABLA_REAPRO}
                   SET estado = 'ok', fecha_ok = ?, cantidad_ok = ?
                 WHERE id = ?""",
            (momento, movida, id_tarea),
        )

    return {"ok": True, "sku": t["sku"], "cantidad": movida,
            "origen": t["origen"], "destino": t["destino"]}


def resumen(db: str | Path) -> dict:
    with sv.abrir(db) as con:
        preparar_tablas(con)
        f = con.execute(
            f"""SELECT COUNT(*) AS n, SUM(cantidad) AS c,
                       SUM(CASE WHEN estado='pendiente' THEN 1 ELSE 0 END) AS pend,
                       SUM(CASE WHEN estado='ok' THEN 1 ELSE 0 END) AS hechas
                  FROM {TABLA_REAPRO}"""
        ).fetchone()
    return {"tareas": int(f["n"] or 0), "cajas": int(f["c"] or 0),
            "pendientes": int(f["pend"] or 0), "hechas": int(f["hechas"] or 0)}


def necesidades_a_dataframe(items: list[NecesidadReapro]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=["ubicacion", "sku", "descripcion",
                                     "stock_actual", "minimo", "maximo", "reponer",
                                     "disponible_origen", "cubre"])
    return pd.DataFrame([{
        "ubicacion": n.ubicacion_picking, "sku": n.sku,
        "descripcion": n.descripcion, "stock_actual": n.stock_actual,
        "minimo": n.minimo, "maximo": n.maximo, "reponer": n.reponer,
        "disponible_origen": n.disponible_origen, "cubre": n.cubre,
    } for n in items])
