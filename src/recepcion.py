"""Recepcion de mercaderia (Plan B, contingencia).

Dos momentos, igual que en picking:

  1. RECIBIR: llega el camion. Se escanea el LPN de la tarja (y/o el SKU) y se
     registra la mercaderia. Entra al stock vivo con area RECEPCION, disponible
     para ubicar.

  2. UBICAR: se lleva a su ubicacion definitiva. La mercaderia sale de RECEPCION
     y entra al area destino (normalmente AREA ALMACENAMIENTO), con el lote y el
     vencimiento. Desde ahi ya es candidata para reaprovisionamiento.

Datos de la tarja (confirmado por el usuario, 2026-11-03):
    lpn      278043001201264701   (18 digitos)
    sku      700809
    ubicacion C16-01-01-01
    cantidad 198
    almacen  CD8000
  La tarja IMPRESA ademas trae FECHA DE ELABORACION y FECHA DE VENCIMIENTO.
  -> El vencimiento es imprescindible: sin el, FEFO no puede ordenar el lote.

El LPN se registra tal cual viene: no se intenta interpretar su estructura (no
hay documentacion del formato y adivinar seria peor que guardarlo crudo).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv
from .externos import clave_sku

TABLA_RECEPCION = "recepcion"
TABLA_UBICACIONES = "ubicaciones"


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def normalizar_fecha(texto: object) -> str:
    """Acepta 'dd/mm/aaaa' o 'dd-mm-aaaa' (con hora opcional) y devuelve dd/mm/aaaa.

    Devuelve "" si no se entiende. El vencimiento es critico para FEFO: mejor
    dejarlo vacio y avisar, que guardar una fecha mal.
    """
    if texto is None:
        return ""
    t = str(texto).strip()
    if not t:
        return ""
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


@dataclass
class Recepcion:
    lpn: str
    sku: str
    cantidad: int
    ubicacion: str = ""            # ubicacion sugerida (de la tarja), si viene
    almacen: str = ""
    descripcion: str = ""
    fecha_elaboracion: str = ""
    fecha_vencimiento: str = ""
    usuario: str = ""
    fecha: str = ""

    def faltantes(self) -> list[str]:
        """Campos imprescindibles que no vinieron."""
        malos = []
        if not self.lpn:
            malos.append("lpn")
        if not self.sku:
            malos.append("sku")
        if not self.cantidad or self.cantidad <= 0:
            malos.append("cantidad")
        return malos


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------

def preparar_tablas(con: sqlite3.Connection) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_RECEPCION} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, lpn TEXT, sku TEXT, sku_clave TEXT,
            descripcion TEXT, cantidad INTEGER, almacen TEXT,
            ubicacion_sugerida TEXT, ubicacion_final TEXT,
            fecha_elaboracion TEXT, fecha_vencimiento TEXT,
            estado TEXT NOT NULL DEFAULT 'recibido'
        )
    """)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_UBICACIONES} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ubicacion TEXT NOT NULL UNIQUE,
            sku TEXT, sku_clave TEXT, descripcion TEXT,
            capacidad INTEGER, ocupado INTEGER DEFAULT 0,
            zona TEXT, tipo TEXT
        )
    """)
    con.execute(f"CREATE INDEX IF NOT EXISTS ix_rec_lpn ON {TABLA_RECEPCION}(lpn)")


# ---------------------------------------------------------------------------
# Paso 1: recibir
# ---------------------------------------------------------------------------

def recibir(db: str | Path, recepcion: Recepcion) -> dict:
    """Registra la mercaderia recibida. Queda en RECEPCION, lista para ubicar.

    Idempotente por LPN: si el mismo LPN ya se recibio, NO se duplica (devuelve
    el registro existente). Evita el doble ingreso si el picker escanea dos veces.
    """
    malos = recepcion.faltantes()
    if malos:
        return {"ok": False, "error": f"faltan datos: {', '.join(malos)}", "code": 400}

    momento = recepcion.fecha or datetime.now().isoformat(timespec="seconds")

    with sv.abrir(db) as con:
        preparar_tablas(con)

        # Idempotencia: mismo LPN no se recibe dos veces.
        ya = con.execute(
            f"SELECT * FROM {TABLA_RECEPCION} WHERE lpn = ?", (recepcion.lpn,)
        ).fetchone()
        if ya:
            return {"ok": False, "error": f"el LPN {recepcion.lpn} ya fue recibido",
                    "code": 409, "id": int(ya["id"]),
                    "cantidad": int(ya["cantidad"])}

        clave = clave_sku(recepcion.sku)
        con.execute(
            f"""INSERT INTO {TABLA_RECEPCION}
                (fecha, usuario, lpn, sku, sku_clave, descripcion, cantidad,
                 almacen, ubicacion_sugerida, fecha_elaboracion, fecha_vencimiento,
                 estado)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'recibido')""",
            (momento, recepcion.usuario, recepcion.lpn, recepcion.sku, clave,
             recepcion.descripcion, recepcion.cantidad, recepcion.almacen,
             recepcion.ubicacion, recepcion.fecha_elaboracion,
             recepcion.fecha_vencimiento),
        )

        # Entra al stock vivo en RECEPCION (aun sin ubicacion final).
        sv.ingresar(
            con,
            ubicacion=sv.AREA_RECEPCION,
            sku=recepcion.sku,
            cantidad=recepcion.cantidad,
            lpn=recepcion.lpn,
            descripcion=recepcion.descripcion,
            area=sv.AREA_RECEPCION,
            fecha_caducidad=recepcion.fecha_vencimiento,
        )

    return {"ok": True, "lpn": recepcion.lpn, "sku": recepcion.sku,
            "cantidad": recepcion.cantidad,
            "aviso_vencimiento": not recepcion.fecha_vencimiento}


# ---------------------------------------------------------------------------
# Paso 2: ubicar
# ---------------------------------------------------------------------------

def sugerir_ubicacion(db: str | Path, sku: str) -> dict:
    """Sugiere ubicacion para un SKU recien recibido.

    Orden de preferencia:
      1. Una ubicacion ya conocida para ese SKU (no dispersar el mismo producto).
      2. Una ubicacion con capacidad libre.
      3. Sin sugerencia (que decida el operador).
    """
    clave = clave_sku(sku)
    with sv.abrir(db) as con:
        preparar_tablas(con)

        # 1) ubicacion ya usada para ese SKU en el stock
        fila = con.execute(
            f"""SELECT ubicacion, area FROM {sv.TABLA}
                 WHERE sku_clave = ? AND area NOT IN (?, '')
                 ORDER BY cantidad DESC LIMIT 1""",
            (clave, sv.AREA_RECEPCION),
        ).fetchone()
        if fila:
            return {"ok": True, "ubicacion": fila["ubicacion"], "area": fila["area"],
                    "motivo": "ya se guarda ese SKU ahi"}

        # 2) ubicacion con capacidad libre
        libre = con.execute(
            f"""SELECT ubicacion, capacidad, ocupado FROM {TABLA_UBICACIONES}
                 WHERE capacidad IS NOT NULL
                   AND (capacidad - COALESCE(ocupado,0)) > 0
                 ORDER BY (capacidad - COALESCE(ocupado,0)) DESC LIMIT 1"""
        ).fetchone()
        if libre:
            return {"ok": True, "ubicacion": libre["ubicacion"],
                    "capacidad_libre": int(libre["capacidad"]) - int(libre["ocupado"] or 0),
                    "motivo": "tiene capacidad libre"}

    return {"ok": False, "motivo": "sin ubicacion conocida; que decida el operador"}


def ubicar(db: str | Path, id_recepcion: int, ubicacion_final: str,
           usuario: str = "") -> dict:
    """Mueve la mercaderia de RECEPCION a su ubicacion definitiva.

    Sale de RECEPCION y entra al area destino conservando LOTE y VENCIMIENTO
    (sin eso FEFO no puede ordenar).
    """
    if not ubicacion_final:
        return {"ok": False, "error": "falta la ubicacion", "code": 400}

    with sv.abrir(db) as con:
        preparar_tablas(con)
        r = con.execute(
            f"SELECT * FROM {TABLA_RECEPCION} WHERE id = ?", (id_recepcion,)
        ).fetchone()
        if r is None:
            return {"ok": False, "error": "recepcion inexistente", "code": 404}
        if r["estado"] == "ubicado":
            return {"ok": False, "error": "esa recepcion ya fue ubicada", "code": 400}

        # Sale de RECEPCION (misma fila ubicacion=RECEPCION, mismo lote)
        fila = con.execute(
            f"""SELECT id FROM {sv.TABLA}
                 WHERE ubicacion = ? AND sku_clave = ? AND COALESCE(lpn,'') = ?""",
            (sv.AREA_RECEPCION, r["sku_clave"], r["lpn"] or ""),
        ).fetchone()
        if fila is None:
            return {"ok": False, "error": "no esta en RECEPCION", "code": 400}

        # Se descuenta de la fila de recepcion y se suma a la ubicacion final
        con.execute(f"DELETE FROM {sv.TABLA} WHERE id = ?", (fila["id"],))
        sv.ingresar(
            con,
            ubicacion=ubicacion_final,
            sku=r["sku"],
            cantidad=int(r["cantidad"]),
            lpn=r["lpn"] or "",
            descripcion=r["descripcion"] or "",
            area=sv.AREA_ALMACENAMIENTO,
            fecha_caducidad=r["fecha_vencimiento"] or "",
        )

        con.execute(
            f"""UPDATE {TABLA_RECEPCION}
                   SET estado = 'ubicado', ubicacion_final = ?, usuario = ?
                 WHERE id = ?""",
            (ubicacion_final, usuario, id_recepcion),
        )

    return {"ok": True, "lpn": r["lpn"], "sku": r["sku"],
            "cantidad": int(r["cantidad"]), "ubicacion": ubicacion_final,
            "vencimiento": r["fecha_vencimiento"] or ""}


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def pendientes(db: str | Path) -> pd.DataFrame:
    """Recepciones recibidas pero todavia sin ubicar."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        return pd.read_sql_query(
            f"""SELECT id, fecha, lpn, sku, descripcion, cantidad,
                       ubicacion_sugerida, fecha_vencimiento
                  FROM {TABLA_RECEPCION}
                 WHERE estado = 'recibido'
                 ORDER BY id""",
            con,
        )


def resumen(db: str | Path) -> dict:
    with sv.abrir(db) as con:
        preparar_tablas(con)
        f = con.execute(
            f"""SELECT COUNT(*) AS n,
                       SUM(cantidad) AS cajas,
                       SUM(CASE WHEN estado='recibido' THEN 1 ELSE 0 END) AS pend,
                       SUM(CASE WHEN estado='ubicado' THEN 1 ELSE 0 END) AS ubic,
                       SUM(CASE WHEN COALESCE(fecha_vencimiento,'')='' THEN 1 ELSE 0 END) AS sin_venc
                  FROM {TABLA_RECEPCION}"""
        ).fetchone()
    return {
        "recepciones": int(f["n"] or 0),
        "cajas": int(f["cajas"] or 0),
        "pendientes": int(f["pend"] or 0),
        "ubicadas": int(f["ubic"] or 0),
        "sin_vencimiento": int(f["sin_venc"] or 0),
    }
