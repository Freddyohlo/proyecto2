"""Picking guiado con RESERVA de stock (Plan B, contingencia).

Modelo de trabajo (confirmado por el usuario, 2026-11-03):

  El sistema DIRIGE al picker: "ve a la ubicacion X y saca N cajas".
  El picker escanea el QR del rack (que trae SOLO la ubicacion) y el sistema
  VERIFICA que sea la ubicacion correcta. No hace falta escanear el SKU: la
  ubicacion de picking es unica por SKU, asi que la ubicacion ya identifica el
  producto.

  La cantidad la digita el picker. Los codigos de barra de producto y LPN se
  escanean SOLO EN RECEPCION (ahi esta la tarja).

DOS MOMENTOS DISTINTOS (clave para no hacer doble picking):

  1. DESTINAR (aqui): se elige la ubicacion/lote y se RESERVA la cantidad.
     Desde ese momento esa mercaderia queda "tomada" y el sistema ya no la
     vuelve a ofrecer a otro picker.

  2. CONFIRMAR (en picking_servidor): el picker escanea y digita lo que saco.
     Se suelta la reserva y se REBAJA el stock.

  disponible = cantidad (foto de la cuadratura) - reservado - pickeado

  Las tareas se guardan en la tabla `tareas` (fuente de verdad, sobrevive
  reinicios). El movimiento queda auditado en `picking` para reingresar a Blue
  Yonder cuando vuelva.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv

TABLA_TAREAS = "tareas"


@dataclass
class Tarea:
    ubicacion: str
    sku: str
    descripcion: str
    cantidad: int
    lote: str
    caducidad: str
    area: str
    fila_stock: int = 0          # id de la fila en stock_vivo (para reservar/rebajar)
    reservado: int = 0


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------

def preparar_tablas(con: sqlite3.Connection) -> None:
    """Crea `tareas` y `picking` si no existen. `tareas` es la fuente de verdad."""
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_TAREAS} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ubicacion TEXT NOT NULL,
            sku TEXT NOT NULL,
            sku_clave TEXT,
            descripcion TEXT,
            cantidad INTEGER NOT NULL,
            lote TEXT,
            caducidad TEXT,
            area TEXT,
            fila_stock INTEGER,
            reservado INTEGER NOT NULL DEFAULT 0,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            fecha_ok TEXT,
            usuario TEXT,
            cantidad_ok INTEGER NOT NULL DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS picking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, ubicacion TEXT, sku TEXT, lpn TEXT,
            cantidad INTEGER, descripcion TEXT, lote TEXT, caducidad TEXT
        )
    """)


# ---------------------------------------------------------------------------
# Destinar
# ---------------------------------------------------------------------------

def destinar(
    db: str | Path,
    demanda: pd.DataFrame,
    incluir_almacenamiento: bool = False,
) -> tuple[int, int, pd.DataFrame]:
    """Convierte la demanda en tareas, RESERVANDO el stock de cada una.

    `demanda` trae al menos `sku_clave` y `cajas`.

    Devuelve (tareas_creadas, cajas_reservadas, faltantes).
    """
    vacio = pd.DataFrame(columns=["sku", "descripcion", "faltante"])
    if demanda is None or len(demanda) == 0:
        return 0, 0, vacio

    creadas = 0
    reservadas = 0
    faltantes: list[dict] = []

    with sv.abrir(db) as con:
        preparar_tablas(con)

        # Limpia las tareas pendientes anteriores para no acumular duplicados.
        # Las reservas de esas pendientes se sueltan antes de borrarlas.
        for t in con.execute(
            f"SELECT fila_stock, reservado FROM {TABLA_TAREAS} WHERE estado = 'pendiente'"
        ).fetchall():
            if t["fila_stock"]:
                sv.liberar(con, t["fila_stock"], int(t["reservado"] or 0))
        con.execute(f"DELETE FROM {TABLA_TAREAS} WHERE estado = 'pendiente'")

        for _, fila in demanda.iterrows():
            clave = str(fila["sku_clave"])
            restante = int(fila["cajas"])
            if restante <= 0:
                continue

            for lote in sv.filas_disponibles(con, clave, incluir_almacenamiento):
                if restante <= 0:
                    break
                disponible = sv.disponible_de(con, lote["id"])
                if disponible <= 0:
                    continue
                tomar = min(restante, disponible)
                if not sv.reservar(con, lote["id"], tomar):
                    continue          # otro Zebra se adelanto; se prueba la siguiente

                con.execute(
                    f"""INSERT INTO {TABLA_TAREAS}
                        (ubicacion, sku, sku_clave, descripcion, cantidad, lote,
                         caducidad, area, fila_stock, reservado)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (lote["ubicacion"], lote["sku"], clave, lote["descripcion"],
                     tomar, lote["lpn"], lote["fecha_caducidad"], lote["area"],
                     lote["id"], tomar),
                )
                creadas += 1
                reservadas += tomar
                restante -= tomar

            if restante > 0:
                faltantes.append({
                    "sku": str(fila.get("sku", clave)),
                    "descripcion": "",
                    "faltante": restante,
                })

    return creadas, reservadas, (pd.DataFrame(faltantes) if faltantes else vacio)


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------

def tarea_pendiente(db: str | Path) -> dict | None:
    """Toma la primera tarea pendiente. No la reserva (ya se reservo al destinar)."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        fila = con.execute(
            f"SELECT * FROM {TABLA_TAREAS} WHERE estado = 'pendiente' ORDER BY id LIMIT 1"
        ).fetchone()
        if fila is None:
            return None
        total = con.execute(f"SELECT COUNT(*) FROM {TABLA_TAREAS}").fetchone()[0]
        hechas = con.execute(
            f"SELECT COUNT(*) FROM {TABLA_TAREAS} WHERE estado IN ('ok','parcial')"
        ).fetchone()[0]
    return {**dict(fila), "total": total, "hechas": hechas}


def obtener_tarea(db: str | Path, id_tarea: int) -> dict | None:
    """Devuelve una tarea por id (o None)."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        fila = con.execute(
            f"SELECT * FROM {TABLA_TAREAS} WHERE id = ?", (id_tarea,)
        ).fetchone()
    return dict(fila) if fila else None


def resumen_tareas(db: str | Path) -> dict:
    with sv.abrir(db) as con:
        preparar_tablas(con)
        filas = con.execute(
            f"SELECT estado, COUNT(*) AS n, SUM(cantidad) AS c "
            f"FROM {TABLA_TAREAS} GROUP BY estado"
        ).fetchall()
    por_estado = {f["estado"]: {"tareas": int(f["n"]), "cajas": int(f["c"] or 0)}
                  for f in filas}
    return por_estado


# ---------------------------------------------------------------------------
# Confirmar / liberar
# ---------------------------------------------------------------------------

def confirmar(
    db: str | Path,
    id_tarea: int,
    cantidad: int,
    usuario: str = "",
) -> dict:
    """Confirma un pick: rebaja el stock y libera la reserva.

    Si el picker saca menos de lo pedido, lo que falta se libera y se
    RE-ENCOLA como tarea nueva, para que otro picker (o el mismo) lo tome.
    """
    momento = datetime.now().isoformat(timespec="seconds")

    with sv.abrir(db) as con:
        preparar_tablas(con)
        t = con.execute(f"SELECT * FROM {TABLA_TAREAS} WHERE id = ?", (id_tarea,)).fetchone()
        if t is None:
            return {"ok": False, "error": "tarea inexistente", "code": 404}
        if t["estado"] != "pendiente":
            return {"ok": False, "error": "la tarea ya no esta pendiente", "code": 400}

        pedida = int(t["cantidad"])
        reservado = int(t["reservado"] or 0)
        if cantidad <= 0:
            return {"ok": False, "error": "la cantidad debe ser mayor que 0", "code": 400}
        if cantidad > pedida:
            return {"ok": False,
                    "error": f"pedido {pedida} y se digito {cantidad}", "code": 400}

        # Rebaja: suelta lo reservado y suma lo que realmente salio.
        if t["fila_stock"]:
            sv.rebajar(con, t["fila_stock"], reservado, cantidad)

        con.execute(
            """INSERT INTO picking
               (fecha, usuario, ubicacion, sku, lpn, cantidad, descripcion, lote, caducidad)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (momento, usuario, t["ubicacion"], t["sku"], t["lote"], cantidad,
             t["descripcion"], t["lote"], t["caducidad"]),
        )

        estado = "ok" if cantidad == pedida else "parcial"
        con.execute(
            f"""UPDATE {TABLA_TAREAS}
                   SET estado = ?, fecha_ok = ?, usuario = ?, cantidad_ok = ?
                 WHERE id = ?""",
            (estado, momento, usuario, cantidad, id_tarea),
        )

        # Lo que no se pickeo vuelve a la cola, con su reserva.
        sobra = pedida - cantidad
        if sobra > 0 and t["fila_stock"]:
            if sv.reservar(con, t["fila_stock"], sobra):
                con.execute(
                    f"""INSERT INTO {TABLA_TAREAS}
                        (ubicacion, sku, sku_clave, descripcion, cantidad, lote,
                         caducidad, area, fila_stock, reservado)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (t["ubicacion"], t["sku"], t["sku_clave"], t["descripcion"],
                     sobra, t["lote"], t["caducidad"], t["area"],
                     t["fila_stock"], sobra),
                )
            else:
                # Ya no queda stock suficiente en esa fila: se avisa, no se inventa.
                estado = "parcial"

    return {"ok": True, "cantidad": cantidad, "sku": t["sku"],
            "estado": estado, "pedida": pedida}


def saltar(db: str | Path, id_tarea: int, usuario: str = "") -> dict:
    """Salta una tarea y LIBERA su reserva (vuelve a estar disponible)."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        t = con.execute(f"SELECT * FROM {TABLA_TAREAS} WHERE id = ?", (id_tarea,)).fetchone()
        if t is None:
            return {"ok": False, "error": "tarea inexistente", "code": 404}
        if t["estado"] != "pendiente":
            return {"ok": False, "error": "la tarea ya no esta pendiente", "code": 400}
        if t["fila_stock"]:
            sv.liberar(con, t["fila_stock"], int(t["reservado"] or 0))
        con.execute(
            f"UPDATE {TABLA_TAREAS} SET estado = 'saltada', usuario = ? WHERE id = ?",
            (usuario, id_tarea),
        )
    return {"ok": True}
