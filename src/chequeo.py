"""Chequeo físico por muestreo.

PROCESO REAL (aclarado por el usuario):

  Los **chequeadores** toman una copia física impresa del sumario y verifican
  **una muestra (un %)** de los pallets: que la mercadería que llega sea la que
  sale.

Entonces el sistema tiene que:
  1. **Elegir la muestra**: qué pallets se van a chequear (un % del total).
  2. **Emitir la ficha de chequeo**: una hoja imprimible por pallet, con lo que
     el sumario dice, para que el chequeador anote lo que encuentra.
  3. **Registrar el resultado**: conforme o con diferencias (y cuáles).

El porcentaje es **configurable**: cada bodega define el suyo. No se inventan
tablas estadísticas: se usa el % que la operación ya tiene definido.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv

TABLA = "chequeos"
PORCENTAJE_DEFECTO = 10


def preparar_tabla(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, camion TEXT, pallet TEXT,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            diferencia TEXT, observacion TEXT
        )
    """)


# ---------------------------------------------------------------------------
# Elegir la muestra
# ---------------------------------------------------------------------------

@dataclass
class Muestra:
    porcentaje: int
    pallets_total: int
    elegidos: list[dict] = field(default_factory=list)

    @property
    def cantidad(self) -> int:
        return len(self.elegidos)


def pallets_del_sumario(db: str | Path) -> list[dict]:
    """Todos los pallets del sumario, con su camión y cajas."""
    with sv.abrir(db) as con:
        try:
            filas = con.execute(
                """SELECT camion, pallet, COUNT(*) AS skus, SUM(cantidad) AS cajas
                     FROM sumario GROUP BY camion, pallet
                     ORDER BY camion, pallet"""
            ).fetchall()
        except Exception:
            return []
    return [{"camion": f["camion"], "pallet": f["pallet"],
             "skus": int(f["skus"]), "cajas": int(f["cajas"])} for f in filas]


def elegir_muestra(db: str | Path, porcentaje: int = PORCENTAJE_DEFECTO,
                   semilla: int | None = None) -> Muestra:
    """Elige al azar un % de los pallets para chequear.

    Se baraja la lista completa y se toman los primeros N. Con `semilla` la
    elección es **reproducible** (útil para poder repetir/auditar el mismo día).

    Siempre elige **al menos 1** si hay pallets: un muestreo del 0% no chequea
    nada y un redondeo a 0 dejaría el control vacío.
    """
    pallets = pallets_del_sumario(db)
    total = len(pallets)
    if total == 0:
        return Muestra(porcentaje=porcentaje, pallets_total=0, elegidos=[])

    n = max(1, round(total * porcentaje / 100))
    n = min(n, total)

    rnd = random.Random(semilla)
    barajados = list(pallets)
    rnd.shuffle(barajados)
    elegidos = sorted(barajados[:n], key=lambda p: (p["camion"], p["pallet"]))

    return Muestra(porcentaje=porcentaje, pallets_total=total, elegidos=elegidos)


# ---------------------------------------------------------------------------
# Ficha de chequeo (lo que se imprime)
# ---------------------------------------------------------------------------

def ficha(db: str | Path, camion: str, pallet: str) -> dict | None:
    """Lo que el chequeador tiene que verificar en ese pallet.

    Trae lo que el sumario dice (SKU, descripción, cantidad) para que compare
    contra lo que ve físicamente.
    """
    with sv.abrir(db) as con:
        try:
            filas = con.execute(
                """SELECT sku, descripcion, cantidad FROM sumario
                    WHERE camion = ? AND pallet = ? ORDER BY sku""",
                (camion, pallet),
            ).fetchall()
        except Exception:
            return None

    if not filas:
        return None

    lineas = [{"sku": f["sku"], "descripcion": f["descripcion"],
               "cantidad": int(f["cantidad"])} for f in filas]
    return {
        "camion": camion,
        "pallet": pallet,
        "lineas": lineas,
        "skus": len(lineas),
        "cajas": sum(l["cantidad"] for l in lineas),
    }


def fichas_de_muestra(db: str | Path, muestra: Muestra) -> list[dict]:
    """Todas las fichas de los pallets elegidos (para imprimir de una)."""
    salida = []
    for p in muestra.elegidos:
        f = ficha(db, p["camion"], p["pallet"])
        if f:
            salida.append(f)
    return salida


# ---------------------------------------------------------------------------
# Registrar el resultado
# ---------------------------------------------------------------------------

def registrar(db: str | Path, camion: str, pallet: str, conforme: bool,
              diferencia: str = "", observacion: str = "",
              usuario: str = "") -> dict:
    """Registra el chequeo de un pallet.

    `conforme=True`  -> la mercadería coincide con el sumario.
    `conforme=False` -> hay diferencias (se guarda cuáles en `diferencia`).
    """
    momento = datetime.now().isoformat(timespec="seconds")
    estado = "conforme" if conforme else "diferencia"

    with sv.abrir(db) as con:
        preparar_tabla(con)
        # Si ya se chequeó ese pallet, se actualiza (no se duplica)
        ya = con.execute(
            f"SELECT id FROM {TABLA} WHERE camion = ? AND pallet = ?",
            (camion, pallet),
        ).fetchone()
        if ya:
            con.execute(
                f"""UPDATE {TABLA}
                       SET fecha = ?, usuario = ?, estado = ?, diferencia = ?,
                           observacion = ?
                     WHERE id = ?""",
                (momento, usuario, estado, diferencia, observacion, ya["id"]),
            )
        else:
            con.execute(
                f"""INSERT INTO {TABLA}
                    (fecha, usuario, camion, pallet, estado, diferencia, observacion)
                    VALUES (?,?,?,?,?,?,?)""",
                (momento, usuario, camion, pallet, estado, diferencia, observacion),
            )

    return {"ok": True, "camion": camion, "pallet": pallet, "estado": estado}


def chequeos(db: str | Path) -> pd.DataFrame:
    """Todos los chequeos registrados."""
    with sv.abrir(db) as con:
        preparar_tabla(con)
        return pd.read_sql_query(
            f"""SELECT fecha, usuario, camion, pallet, estado, diferencia,
                       observacion
                  FROM {TABLA} ORDER BY camion, pallet""", con)


def resumen(db: str | Path) -> dict:
    """Cuántos chequeos hay y cuántos dieron diferencia."""
    df = chequeos(db)
    if df.empty:
        return {"chequeos": 0, "conformes": 0, "diferencias": 0,
                "pct_conforme": 0.0}
    conf = int((df["estado"] == "conforme").sum())
    dif = int((df["estado"] == "diferencia").sum())
    return {"chequeos": len(df), "conformes": conf, "diferencias": dif,
            "pct_conforme": round(conf / len(df) * 100, 1) if len(df) else 0.0}
