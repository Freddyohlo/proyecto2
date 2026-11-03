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
    incluir_almacenamiento: bool = True,
) -> tuple[int, int, pd.DataFrame]:
    """Convierte la demanda en tareas, RESERVANDO el stock de cada una.

    `demanda` trae al menos `sku_clave` y `cajas`.

    IMPORTANTE: por defecto TAMBIEN busca en ALMACENAMIENTO cuando la ubicacion
    de picking no alcanza. Eso es el flujo real: "en algun momento para completar
    la venta van a traer pallet del almacenamiento para completar" (usuario).

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


def cerrar_dia(db: str | Path, usuario: str = "", liberar: bool = True) -> dict:
    """Cierra el dia por completo: el sistema es para UN dia, no se arrastra.

    Criterio del usuario: lo que no se pickeo, se cierra. No debe pasar de un dia.

    Lo que hace:
      - Marca como 'cerrada' TODA tarea pendiente (no queda nada abierto).
      - LIBERA su reserva, para que la mercaderia vuelva a estar disponible.
      - Registra el cierre en la tabla `cierres` (fecha, quien, totales), para que
        quede la traza de que ese dia se cerro y con que numeros.
      - NO toca lo pickeado: eso ya salio fisicamente.

    Si el dia ya estaba cerrado, no lo vuelve a cerrar (devuelve ya_cerrado=True).
    """
    momento = datetime.now().isoformat(timespec="seconds")
    fecha = datetime.now().strftime("%Y-%m-%d")

    with sv.abrir(db) as con:
        preparar_tablas(con)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cierres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT, momento TEXT, usuario TEXT,
                tareas_cerradas INTEGER, cajas_liberadas INTEGER,
                cajas_pickeadas INTEGER, cajas_recibidas INTEGER
            )
        """)

        ya = con.execute(
            "SELECT * FROM cierres WHERE fecha = ? ORDER BY id DESC LIMIT 1", (fecha,)
        ).fetchone()
        if ya:
            return {"ok": True, "ya_cerrado": True, "fecha": fecha,
                    "tareas_cerradas": int(ya["tareas_cerradas"]),
                    "cajas_liberadas": int(ya["cajas_liberadas"]),
                    "momento": ya["momento"]}

        pendientes = con.execute(
            f"""SELECT id, fila_stock, reservado, cantidad
                  FROM {TABLA_TAREAS} WHERE estado = 'pendiente'"""
        ).fetchall()

        liberado = 0
        if liberar:
            for t in pendientes:
                if t["fila_stock"]:
                    sv.liberar(con, t["fila_stock"], int(t["reservado"] or 0))
                    liberado += int(t["reservado"] or 0)
            con.execute(
                f"""UPDATE {TABLA_TAREAS}
                       SET estado = 'cerrada', fecha_ok = ?, usuario = ?
                     WHERE estado = 'pendiente'""",
                (momento, usuario),
            )

        # Totales del dia, para dejarlos registrados en el cierre
        pickeado = con.execute(
            f"SELECT COALESCE(SUM(cantidad_ok),0) AS c FROM {TABLA_TAREAS} "
            "WHERE estado IN ('ok','parcial')"
        ).fetchone()["c"]
        try:
            recibidas = con.execute(
                "SELECT COALESCE(SUM(cantidad),0) AS c FROM recepcion").fetchone()["c"]
        except Exception:
            recibidas = 0

        con.execute(
            """INSERT INTO cierres
               (fecha, momento, usuario, tareas_cerradas, cajas_liberadas,
                cajas_pickeadas, cajas_recibidas)
               VALUES (?,?,?,?,?,?,?)""",
            (fecha, momento, usuario, len(pendientes), liberado,
             int(pickeado or 0), int(recibidas or 0)),
        )

    return {"ok": True, "ya_cerrado": False, "fecha": fecha,
            "tareas_cerradas": len(pendientes), "cajas_liberadas": liberado,
            "cajas_pickeadas": int(pickeado or 0),
            "cajas_recibidas": int(recibidas or 0), "momento": momento}


def cierre_de(db: str | Path, fecha: str = "") -> dict | None:
    """Devuelve el cierre registrado de una fecha (o None si no se cerro)."""
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")
    with sv.abrir(db) as con:
        preparar_tablas(con)
        try:
            f = con.execute(
                "SELECT * FROM cierres WHERE fecha = ? ORDER BY id DESC LIMIT 1",
                (fecha,),
            ).fetchone()
        except Exception:
            return None
    return dict(f) if f else None


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
