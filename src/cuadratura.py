"""Cuadratura de stock: la foto real de la bodega, con lo comprometido aparte.

DOS COSAS DISTINTAS que hay que no confundir:

  STOCK FÍSICO    lo que hay en la bodega ahora mismo
  COMPROMETIDO    lo que ya está reservado/pickeado para una CARGA (camión)

Cuando alguien consulta un SKU necesita ver las dos: "tengo 900, pero 200 ya
están comprometidos para el camión 012R-01, así que en realidad me quedan 700
libres". Sin eso se compromete dos veces la misma mercadería.

La **cuadratura** es el corte de las 19:00: se congela la foto y se compara con
lo que había antes, para tener números reales del día.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from .externos import clave_sku
from . import stock_vivo as sv

TABLA_CORTES = "cuadraturas"


def preparar_tablas(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_CORTES} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            momento TEXT,
            usuario TEXT,
            lineas INTEGER,
            cajas INTEGER,
            reservado INTEGER,
            pickeado INTEGER,
            disponible INTEGER,
            nota TEXT
        )
    """)


# ---------------------------------------------------------------------------
# Comprometido por carga
# ---------------------------------------------------------------------------

def comprometido_por_carga(db: str | Path, codigo: str = "") -> list[dict]:
    """Cuánto de cada SKU está comprometido para cada camión (carga).

    Se toma de las tareas de picking: lo reservado (aún sin pickear) y lo ya
    pickeado, agrupado por camión.
    """
    clave = clave_sku(codigo) if codigo else ""
    with sv.abrir(db) as con:
        sql = """SELECT COALESCE(camion,'') AS camion,
                        COALESCE(sku,'') AS sku,
                        COALESCE(descripcion,'') AS descripcion,
                        SUM(CASE WHEN estado = 'pendiente' THEN reservado ELSE 0 END) AS reservado,
                        SUM(CASE WHEN estado IN ('ok','parcial') THEN cantidad_ok ELSE 0 END) AS pickeado,
                        COUNT(*) AS tareas
                   FROM tareas
                  WHERE COALESCE(camion,'') <> ''"""
        params: tuple = ()
        if clave:
            sql += " AND sku_clave = ?"
            params = (clave,)
        sql += " GROUP BY camion, sku, descripcion ORDER BY camion, sku"
        try:
            filas = con.execute(sql, params).fetchall()
        except Exception:
            return []

    salida = []
    for f in filas:
        reservado = int(f["reservado"] or 0)
        pickeado = int(f["pickeado"] or 0)
        if reservado == 0 and pickeado == 0:
            continue
        salida.append({
            "camion": str(f["camion"]), "sku": str(f["sku"]),
            "descripcion": str(f["descripcion"]),
            "reservado": reservado, "pickeado": pickeado,
            "comprometido": reservado + pickeado,
            "tareas": int(f["tareas"]),
        })
    return salida


def comprometido_de(db: str | Path, codigo: str) -> dict:
    """Resumen de lo comprometido de un SKU, por camión."""
    filas = comprometido_por_carga(db, codigo)
    total = sum(f["comprometido"] for f in filas)
    return {
        "total": total,
        "reservado": sum(f["reservado"] for f in filas),
        "pickeado": sum(f["pickeado"] for f in filas),
        "camiones": filas,
        "n_camiones": len({f["camion"] for f in filas}),
    }


# ---------------------------------------------------------------------------
# Cuadratura (el corte de las 19:00)
# ---------------------------------------------------------------------------

@dataclass
class Cuadratura:
    fecha: str
    momento: str
    lineas: list[dict] = field(default_factory=list)

    @property
    def cajas(self) -> int:
        return sum(l["cantidad"] for l in self.lineas)

    @property
    def reservado(self) -> int:
        return sum(l["reservado"] for l in self.lineas)

    @property
    def pickeado(self) -> int:
        return sum(l["pickeado"] for l in self.lineas)

    @property
    def disponible(self) -> int:
        return sum(l["disponible"] for l in self.lineas)

    def resumen(self) -> dict:
        return {
            "fecha": self.fecha, "momento": self.momento,
            "lineas": len(self.lineas), "cajas": self.cajas,
            "reservado": self.reservado, "pickeado": self.pickeado,
            "disponible": self.disponible,
            "skus": len({l["sku"] for l in self.lineas}),
            "ubicaciones": len({l["ubicacion"] for l in self.lineas}),
        }


def cuadratura_actual(db: str | Path, fecha: str = "") -> Cuadratura:
    """La foto del stock vivo AHORA, con lo comprometido marcado.

    Es lo que se manda a transportes a las 19:00: por SKU y ubicación, cuánto
    hay, cuánto está comprometido y cuánto queda libre.
    """
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")
    momento = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sv.abrir(db) as con:
        filas = con.execute(
            f"""SELECT ubicacion, sku, sku_clave, descripcion, area, lpn,
                       fecha_caducidad, cantidad, reservado, pickeado,
                       (cantidad - reservado - pickeado) AS disponible
                  FROM {sv.TABLA}
                 WHERE cantidad > 0
                 ORDER BY area, ubicacion, sku""",
        ).fetchall()

    lineas = [{
        "ubicacion": str(f["ubicacion"]), "sku": str(f["sku"]),
        "descripcion": str(f["descripcion"] or ""), "area": str(f["area"]),
        "lpn": str(f["lpn"] or ""), "vencimiento": str(f["fecha_caducidad"] or ""),
        "cantidad": int(f["cantidad"] or 0),
        "reservado": int(f["reservado"] or 0),
        "pickeado": int(f["pickeado"] or 0),
        "disponible": int(f["disponible"] or 0),
    } for f in filas]

    return Cuadratura(fecha=fecha, momento=momento, lineas=lineas)


def por_sku(cuad: Cuadratura) -> list[dict]:
    """La cuadratura agrupada por SKU (lo que se manda a transportes)."""
    acum: dict[str, dict] = {}
    for l in cuad.lineas:
        k = clave_sku(l["sku"])
        if k not in acum:
            acum[k] = {"sku": l["sku"], "descripcion": l["descripcion"],
                       "cantidad": 0, "reservado": 0, "pickeado": 0,
                       "disponible": 0, "ubicaciones": 0}
        a = acum[k]
        a["cantidad"] += l["cantidad"]
        a["reservado"] += l["reservado"]
        a["pickeado"] += l["pickeado"]
        a["disponible"] += l["disponible"]
        a["ubicaciones"] += 1
    return sorted(acum.values(), key=lambda x: x["disponible"], reverse=True)


def guardar_corte(db: str | Path, usuario: str = "", nota: str = "",
                  fecha: str = "") -> dict:
    """Congela el corte del día (el de las 19:00) y lo deja registrado.

    Guarda los totales en `cuadraturas` y las líneas del stock en `cuadratura_<fecha>`
    para poder comparar después. Si ya hay un corte de esa fecha, lo reemplaza.
    """
    cuad = cuadratura_actual(db, fecha)
    r = cuad.resumen()

    with sv.abrir(db) as con:
        preparar_tablas(con)
        tabla = f"cuadratura_{cuad.fecha.replace('-', '_')}"
        con.execute(f"DROP TABLE IF EXISTS {tabla}")
        con.execute(f"""
            CREATE TABLE {tabla} AS
            SELECT ubicacion, sku, descripcion, area, lpn, fecha_caducidad,
                   cantidad, reservado, pickeado
              FROM {sv.TABLA} WHERE cantidad > 0
        """)
        con.execute(
            f"DELETE FROM {TABLA_CORTES} WHERE fecha = ?", (cuad.fecha,))
        con.execute(
            f"""INSERT INTO {TABLA_CORTES}
                (fecha, momento, usuario, lineas, cajas, reservado, pickeado,
                 disponible, nota)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (cuad.fecha, cuad.momento, usuario, r["lineas"], r["cajas"],
             r["reservado"], r["pickeado"], r["disponible"], nota),
        )

    return {"ok": True, "tabla": tabla, **r}


def cortes(db: str | Path) -> pd.DataFrame:
    """Los cortes de cuadratura registrados."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        return pd.read_sql_query(
            f"""SELECT fecha, momento, usuario, lineas, cajas, reservado,
                       pickeado, disponible, nota
                  FROM {TABLA_CORTES} ORDER BY fecha DESC""", con)


def comparar_con_corte_anterior(db: str | Path, fecha: str = "") -> dict:
    """Compara el stock actual contra el corte guardado de una fecha.

    Sirve para ver los MOVIMIENTOS del período: qué entró y qué salió.
    """
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")
    tabla = f"cuadratura_{fecha.replace('-', '_')}"
    actual = cuadratura_actual(db, fecha)
    actual_por_sku = {clave_sku(s["sku"]): s for s in por_sku(actual)}

    with sv.abrir(db) as con:
        try:
            antes = con.execute(f"SELECT sku, SUM(cantidad) AS c FROM {tabla} "
                                "GROUP BY sku").fetchall()
        except Exception:
            return {"ok": False, "error": f"no hay corte guardado para {fecha}"}

    antes_por_sku = {clave_sku(f["sku"]): int(f["c"] or 0) for f in antes}

    movimientos = []
    for k in set(antes_por_sku) | set(actual_por_sku):
        a = antes_por_sku.get(k, 0)
        b = actual_por_sku.get(k, {}).get("cantidad", 0)
        if a != b:
            movimientos.append({
                "sku": actual_por_sku.get(k, {}).get("sku", k),
                "descripcion": actual_por_sku.get(k, {}).get("descripcion", ""),
                "antes": a, "ahora": b, "diferencia": b - a,
            })
    movimientos.sort(key=lambda x: abs(x["diferencia"]), reverse=True)
    return {"ok": True, "fecha": fecha, "movimientos": movimientos,
            "cambios": len(movimientos)}
