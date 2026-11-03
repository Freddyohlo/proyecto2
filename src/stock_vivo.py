"""Stock vivo: reservas y rebajas sobre la foto de inventario (Plan B).

La cuadratura captura una FOTO del stock de Blue Yonder. Durante la contingencia
esa foto se mueve:

  - Cuando el sistema DESTINA una tarea, RESERVA (toma) esa cantidad.
  - Cuando el picker CONFIRMA, se REBAJA.
  - Si el picker saca menos, lo que falta se libera y se vuelve a reservar.

Asi el sistema nunca destina dos veces la misma caja:

    disponible = cantidad (foto) - reservado - pickeado

La foto original (tabla `stock`) NO se toca: queda como respaldo de lo que Blue
Yonder decia. Todo el movimiento vive en `stock_vivo`, y queda auditado en
`tareas` y `picking`, que es lo que despues se reingresa a Blue Yonder.

Concurrencia: varios Zebra pegan al mismo servidor a la vez. SQLite en modo WAL
+ busy_timeout aguanta bien este volumen (escrituras cortas y espaciadas). Si el
dia de manana crece mucho, se puede migrar a PostgreSQL sin cambiar el modelo.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

TABLA = "stock_vivo"

# Area donde se registra la mercaderia recien recibida (antes de ubicarla).
AREA_RECEPCION = "RECEPCION"

# Area destino habitual al ubicar (ubicaciones en altura).
AREA_ALMACENAMIENTO = "AREA ALMACENAMIENTO"


# ---------------------------------------------------------------------------
# Conexion
# ---------------------------------------------------------------------------

@contextmanager
def abrir(db: str | Path):
    """Conexion a SQLite con WAL (permite lecturas mientras se escribe)."""
    con = sqlite3.connect(str(db), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fechas (el orden FEFO tiene que ser por fecha real, no por texto)
# ---------------------------------------------------------------------------

def a_fecha(texto: object):
    """'dd/mm/aaaa HH:MM:SS' -> datetime. Devuelve datetime.max si no se entiende."""
    if not texto:
        return datetime.max
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(texto).strip(), fmt)
        except ValueError:
            continue
    return datetime.max


def fecha_orden(texto: object) -> str:
    """Version ordenable (ISO) de la fecha, para poder ordenar en SQL."""
    f = a_fecha(texto)
    return "" if f == datetime.max else f.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Inicializacion
# ---------------------------------------------------------------------------

def _existe(con: sqlite3.Connection, tabla: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
    ).fetchone() is not None


def inicializar(db: str | Path, forzar: bool = False) -> int:
    """Crea `stock_vivo` desde la foto `stock` (si no existe o si forzar=True).

    Devuelve la cantidad de filas cargadas. No toca `stock`.
    """
    with abrir(db) as con:
        if not _existe(con, "stock"):
            raise SystemExit("No hay tabla `stock`. Carga primero la cuadratura.")

        if forzar:
            con.execute(f"DROP TABLE IF EXISTS {TABLA}")

        if _existe(con, TABLA):
            return con.execute(f"SELECT COUNT(*) FROM {TABLA}").fetchone()[0]

        con.execute(f"""
            CREATE TABLE {TABLA} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ubicacion TEXT NOT NULL,
                sku TEXT NOT NULL,
                sku_clave TEXT NOT NULL,
                lpn TEXT,
                descripcion TEXT,
                area TEXT,
                fecha_caducidad TEXT,
                fecha_ord TEXT,
                cantidad INTEGER NOT NULL,
                reservado INTEGER NOT NULL DEFAULT 0,
                pickeado INTEGER NOT NULL DEFAULT 0
            )
        """)

        filas = con.execute(
            "SELECT ubicacion, sku, lpn, descripcion, area, fecha_caducidad, cantidad "
            "FROM stock"
        ).fetchall()

        from .externos import clave_sku

        con.executemany(
            f"""INSERT INTO {TABLA}
                (ubicacion, sku, sku_clave, lpn, descripcion, area,
                 fecha_caducidad, fecha_ord, cantidad)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            [(f["ubicacion"], f["sku"], clave_sku(f["sku"]), f["lpn"], f["descripcion"],
              f["area"], f["fecha_caducidad"], fecha_orden(f["fecha_caducidad"]),
              int(f["cantidad"] or 0)) for f in filas],
        )
        con.execute(f"CREATE INDEX ix_{TABLA}_sku ON {TABLA}(sku_clave)")
        con.execute(f"CREATE INDEX ix_{TABLA}_ubic ON {TABLA}(ubicacion)")
        return len(filas)


# ---------------------------------------------------------------------------
# Reservas y rebajas
# ---------------------------------------------------------------------------

def reservar(con: sqlite3.Connection, fila_id: int, cantidad: int) -> bool:
    """Reserva `cantidad` de una fila. Devuelve False si ya no alcanza.

    La condicion de disponibilidad va en el propio UPDATE, asi que la reserva es
    atomica: dos Zebra pidiendo la ultima caja no pueden ganar los dos.
    """
    if cantidad <= 0:
        return False
    cur = con.execute(
        f"""UPDATE {TABLA}
               SET reservado = reservado + ?
             WHERE id = ?
               AND (cantidad - reservado - pickeado) >= ?""",
        (cantidad, fila_id, cantidad),
    )
    return cur.rowcount == 1


def liberar(con: sqlite3.Connection, fila_id: int, cantidad: int) -> None:
    """Suelta una reserva que no se va a usar (tarea saltada o anulada)."""
    con.execute(
        f"UPDATE {TABLA} SET reservado = MAX(0, reservado - ?) WHERE id = ?",
        (cantidad, fila_id),
    )


def rebajar(con: sqlite3.Connection, fila_id: int, reservado: int,
            pickeado: int) -> None:
    """Confirma un pick: suelta la reserva y suma lo efectivamente pickeado.

    `reservado` es lo que se habia tomado; `pickeado` es lo que realmente salio.
    Si son distintos, la diferencia vuelve a quedar disponible para re-asignar.
    """
    con.execute(
        f"""UPDATE {TABLA}
               SET reservado = MAX(0, reservado - ?),
                   pickeado  = pickeado + ?
             WHERE id = ?""",
        (reservado, pickeado, fila_id),
    )


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def disponible_de(con: sqlite3.Connection, fila_id: int) -> int:
    fila = con.execute(
        f"SELECT cantidad - reservado - pickeado AS d FROM {TABLA} WHERE id = ?",
        (fila_id,),
    ).fetchone()
    return int(fila["d"]) if fila else 0


def comprometido_por_sku(con: sqlite3.Connection) -> dict[str, int]:
    """Cuanto de cada SKU ya esta reservado o pickeado (para no destinar dos veces)."""
    filas = con.execute(
        f"""SELECT sku_clave, SUM(reservado + pickeado) AS c
              FROM {TABLA} GROUP BY sku_clave"""
    ).fetchall()
    return {f["sku_clave"]: int(f["c"] or 0) for f in filas}


def filas_disponibles(con: sqlite3.Connection, sku_clave: str,
                      incluir_almacenamiento: bool = False) -> list[sqlite3.Row]:
    """Filas con stock disponible, en orden de picking: picking primero, FEFO.

    El orden se resuelve en SQL con `fecha_ord` (ISO), no con el texto dd/mm/aaaa.
    """
    sql = f"""
        SELECT * FROM {TABLA}
         WHERE sku_clave = ?
           AND (cantidad - reservado - pickeado) > 0
    """
    if not incluir_almacenamiento:
        sql += " AND area = 'AREA PICKING'"
    sql += """
         ORDER BY (area <> 'AREA PICKING'),
                  CASE WHEN fecha_ord = '' THEN 1 ELSE 0 END,
                  fecha_ord,
                  ubicacion
    """
    return con.execute(sql, (sku_clave,)).fetchall()


def ingresar(
    con: sqlite3.Connection,
    ubicacion: str,
    sku: str,
    cantidad: int,
    lpn: str = "",
    descripcion: str = "",
    area: str = "",
    fecha_caducidad: str = "",
    fecha_elaboracion: str = "",
    almacen: str = "",
) -> int:
    """Ingresa mercaderia NUEVA al stock vivo (recepcion). Devuelve el id de la fila.

    Si ya existe una fila con la misma ubicacion+lote+SKU, se SUMA la cantidad en
    vez de crear una fila duplicada (el stock se acumula en el mismo lote).
    """
    from .externos import clave_sku

    clave = clave_sku(sku)
    existente = con.execute(
        f"""SELECT id FROM {TABLA}
             WHERE ubicacion = ? AND sku_clave = ? AND COALESCE(lpn,'') = ?""",
        (ubicacion, clave, lpn or ""),
    ).fetchone()

    if existente:
        con.execute(
            f"UPDATE {TABLA} SET cantidad = cantidad + ? WHERE id = ?",
            (cantidad, existente["id"]),
        )
        return int(existente["id"])

    cur = con.execute(
        f"""INSERT INTO {TABLA}
            (ubicacion, sku, sku_clave, lpn, descripcion, area,
             fecha_caducidad, fecha_ord, cantidad)
            VALUES (?,?,?,?,?,?,?,?,?)""",
        (ubicacion, sku, clave, lpn or "", descripcion, area or AREA_RECEPCION,
         fecha_caducidad, fecha_orden(fecha_caducidad), cantidad),
    )
    return int(cur.lastrowid)


def total_ingresado(con: sqlite3.Connection, area: str = AREA_RECEPCION) -> int:
    """Cuantas unidades se ingresaron por recepcion en un area."""
    fila = con.execute(
        f"SELECT COALESCE(SUM(cantidad),0) AS c FROM {TABLA} WHERE area = ?", (area,)
    ).fetchone()
    return int(fila["c"] or 0)


def estado(db: str | Path) -> pd.DataFrame:
    """Foto viva: por fila, cuanto hay, cuanto reservado y cuanto pickeado."""
    with abrir(db) as con:
        return pd.read_sql_query(
            f"""SELECT ubicacion, sku, descripcion, area, fecha_caducidad,
                       cantidad, reservado, pickeado,
                       (cantidad - reservado - pickeado) AS disponible
                  FROM {TABLA}
                 ORDER BY area, ubicacion, fecha_ord""",
            con,
        )


def resumen(db: str | Path) -> dict:
    """Totales generales del stock vivo."""
    with abrir(db) as con:
        f = con.execute(
            f"""SELECT COUNT(*) AS filas,
                       SUM(cantidad)  AS total,
                       SUM(reservado) AS reservado,
                       SUM(pickeado)  AS pickeado,
                       SUM(cantidad - reservado - pickeado) AS disponible
                  FROM {TABLA}"""
        ).fetchone()
    return {
        "filas": int(f["filas"] or 0),
        "total": int(f["total"] or 0),
        "reservado": int(f["reservado"] or 0),
        "pickeado": int(f["pickeado"] or 0),
        "disponible": int(f["disponible"] or 0),
    }
