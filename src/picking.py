"""Lista de picking GUIADA por ubicacion (Plan B, contingencia).

Modelo de trabajo (confirmado por el usuario, 2026-11-03):

  El sistema DIRIGE al picker: "ve a la ubicacion X y saca N cajas".
  El picker escanea el QR del rack (que trae SOLO la ubicacion) y el sistema
  VERIFICA que sea la ubicacion correcta. No hace falta escanear el SKU: la
  ubicacion de picking es unica por SKU, asi que la ubicacion ya identifica el
  producto.

  Los codigos de barra de producto y LPN se escanean SOLO EN RECEPCION (ahi esta
  la tarja con cantidad y LPN), no en picking.

Por eso las tareas se generan por ubicacion, no por SKU escaneado.

Orden de asignacion (FEFO):
  1. Ubicaciones de AREA PICKING primero.
  2. Dentro de cada una, el lote que VENCE ANTES.
  3. Si no alcanza, se puede seguir con AREA ALMACENAMIENTO (opcional).
  4. Lo que no se cubre queda como FALTANTE (insumo para reaprovisionamiento).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import externos
from . import inventario as inv


def a_fecha(texto: object):
    """Convierte 'dd/mm/aaaa HH:MM:SS' a datetime, para ordenar FEFO de verdad.

    Ordenar estas fechas como texto es un error: "01/03/2027" quedaria antes que
    "01/12/2026", o sea elegiria el lote que vence MAS TARDE.
    """
    if not texto:
        return datetime.max
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(texto).strip(), fmt)
        except ValueError:
            continue
    return datetime.max


@dataclass
class Tarea:
    ubicacion: str
    sku: str
    descripcion: str
    cantidad: int
    lote: str
    caducidad: str
    area: str


def generar_tareas(
    stock: inv.Inventario,
    demanda: pd.DataFrame,
    incluir_almacenamiento: bool = False,
) -> tuple[list[Tarea], pd.DataFrame]:
    """Convierte la demanda (venta) en tareas de picking por ubicacion.

    `demanda` es un DataFrame con al menos las columnas `sku_clave` y `cajas`
    (lo que devuelve `externos.Venta.demanda_por_sku`).

    Devuelve (tareas, faltantes). `faltantes` trae los SKU que no se alcanzan a
    cubrir con el stock disponible (para disparar reaprovisionamiento).
    """
    vacio = pd.DataFrame(columns=["sku", "descripcion", "faltante"])
    if stock.dataframe.empty or demanda is None or len(demanda) == 0:
        return [], vacio

    df = stock.dataframe.copy()
    df["sku_clave"] = df["sku"].map(externos.clave_sku)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype("int64")
    df["_fecha"] = df["fecha_caducidad"].map(a_fecha)

    if not incluir_almacenamiento:
        df = df[df["area"].eq(inv.AREA_PICKING)]

    # El picking va antes que el almacenamiento; dentro de cada area, FEFO.
    df["_prioridad_area"] = (~df["area"].eq(inv.AREA_PICKING)).astype(int)

    desc_por_sku = df.groupby("sku_clave")["descripcion"].first().to_dict()

    pedido = demanda.copy()
    pedido["sku_clave"] = pedido["sku_clave"].map(externos.clave_sku)
    pedido["cajas"] = pd.to_numeric(pedido["cajas"], errors="coerce").fillna(0).astype("int64")

    tareas: list[Tarea] = []
    faltantes: list[dict] = []

    for _, fila in pedido.iterrows():
        clave = fila["sku_clave"]
        restante = int(fila["cajas"])
        if restante <= 0:
            continue

        lotes = df[df["sku_clave"].eq(clave)].sort_values(["_prioridad_area", "_fecha"])
        for _, lote in lotes.iterrows():
            if restante <= 0:
                break
            disponible = int(lote["cantidad"])
            if disponible <= 0:
                continue
            tomar = min(restante, disponible)
            tareas.append(Tarea(
                ubicacion=str(lote["ubicacion"]),
                sku=str(lote["sku"]),
                descripcion=str(lote["descripcion"]),
                cantidad=tomar,
                lote=str(lote["lpn"]),
                caducidad=str(lote["fecha_caducidad"] or ""),
                area=str(lote["area"]),
            ))
            restante -= tomar

        if restante > 0:
            faltantes.append({
                "sku": str(fila.get("sku", clave)),
                "descripcion": desc_por_sku.get(clave, ""),
                "faltante": restante,
            })

    return tareas, pd.DataFrame(faltantes) if faltantes else vacio


def guardar_tareas(tareas: list[Tarea], destino: str | Path = "data/plan_b.sqlite") -> Path:
    """Guarda las tareas en la tabla `tareas` (reemplaza las anteriores)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destino) as con:
        con.execute("DROP TABLE IF EXISTS tareas")
        con.execute("""
            CREATE TABLE tareas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ubicacion TEXT NOT NULL,
                sku TEXT NOT NULL,
                descripcion TEXT,
                cantidad INTEGER NOT NULL,
                lote TEXT,
                caducidad TEXT,
                area TEXT,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                fecha_ok TEXT,
                usuario TEXT,
                cantidad_ok INTEGER NOT NULL DEFAULT 0
            )
        """)
        con.executemany(
            """INSERT INTO tareas (ubicacion, sku, descripcion, cantidad, lote, caducidad, area)
               VALUES (?,?,?,?,?,?,?)""",
            [(t.ubicacion, t.sku, t.descripcion, t.cantidad, t.lote, t.caducidad, t.area)
             for t in tareas],
        )
        con.commit()
    return destino


def tarea_pendiente(db: str | Path = "data/plan_b.sqlite") -> dict | None:
    """Devuelve la primera tarea pendiente (o None si ya no hay)."""
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        fila = con.execute(
            "SELECT * FROM tareas WHERE estado = 'pendiente' ORDER BY id LIMIT 1"
        ).fetchone()
        if fila is None:
            return None
        total = con.execute("SELECT COUNT(*) FROM tareas").fetchone()[0]
        hechas = con.execute(
            "SELECT COUNT(*) FROM tareas WHERE estado = 'ok'"
        ).fetchone()[0]
    return {**dict(fila), "total": total, "hechas": hechas}
