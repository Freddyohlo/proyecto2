"""Consulta de stock: "¿tengo este código? ¿cuánto y dónde?"

Es la consulta que el operador hace todo el tiempo en bodega. Debe responder
rápido y sin ambigüedad:

    código (SKU)  ->  cuánto hay  y  en qué ubicaciones

Se consulta contra el **stock vivo** (no la foto), así que descuenta lo ya
reservado y lo pickeado: el número que muestra es lo que **realmente se puede
usar ahora**.

Acepta el SKU con o sin ceros a la izquierda ("622" == "000622"), y también
busca por descripción si no se encuentra por código.
"""

from __future__ import annotations

from pathlib import Path

from .externos import clave_sku
from . import stock_vivo as sv


def consultar(db: str | Path, codigo: str, incluir_agotados: bool = False) -> dict:
    """Ficha de stock de un SKU: totales y detalle por ubicación.

    Devuelve:
      {
        "encontrado": bool,
        "sku": str, "descripcion": str,
        "total": int,            # cajas totales en bodega
        "en_picking": int,       # disponible en AREA PICKING
        "en_almacenamiento": int,# disponible en AREA ALMACENAMIENTO
        "en_staging": int,       # pickeado esperando consolidar
        "reservado": int,        # comprometido en tareas
        "pickeado": int,         # ya salio (o esta en staging)
        "ubicaciones": [ {...}, ... ],
        "lotes": [ {...}, ... ], # con vencimiento, orden FEFO
      }
    """
    codigo = str(codigo or "").strip()
    if not codigo:
        return {"encontrado": False, "sku": "", "descripcion": "",
                "total": 0, "en_picking": 0, "en_almacenamiento": 0,
                "en_staging": 0, "reservado": 0, "pickeado": 0,
                "ubicaciones": [], "lotes": [], "error": "falta el codigo"}

    clave = clave_sku(codigo)

    with sv.abrir(db) as con:
        filas = con.execute(
            f"""SELECT ubicacion, area, lpn, descripcion, fecha_caducidad,
                       cantidad, reservado, pickeado,
                       (cantidad - reservado - pickeado) AS disponible
                  FROM {sv.TABLA}
                 WHERE sku_clave = ?
                 ORDER BY area, ubicacion""",
            (clave,),
        ).fetchall()

        if not filas:
            # Segundo intento: por descripcion (util si no saben el codigo)
            return _por_descripcion(con, codigo)

    # Agrupar por ubicacion
    por_ubic: dict[tuple[str, str], dict] = {}
    for f in filas:
        k = (str(f["ubicacion"]), str(f["area"]))
        if k not in por_ubic:
            por_ubic[k] = {"ubicacion": k[0], "area": k[1], "cantidad": 0,
                           "reservado": 0, "pickeado": 0, "disponible": 0}
        por_ubic[k]["cantidad"] += int(f["cantidad"] or 0)
        por_ubic[k]["reservado"] += int(f["reservado"] or 0)
        por_ubic[k]["pickeado"] += int(f["pickeado"] or 0)
        por_ubic[k]["disponible"] += int(f["disponible"] or 0)

    ubicaciones = list(por_ubic.values())
    if not incluir_agotados:
        ubicaciones = [u for u in ubicaciones if u["cantidad"] > 0]

    def suma(area: str, campo: str = "disponible") -> int:
        return sum(u[campo] for u in ubicaciones if u["area"] == area)

    lotes = [{
        "ubicacion": str(f["ubicacion"]), "area": str(f["area"]),
        "lpn": str(f["lpn"] or ""), "cantidad": int(f["cantidad"] or 0),
        "disponible": int(f["disponible"] or 0),
        "vencimiento": str(f["fecha_caducidad"] or ""),
    } for f in filas if int(f["cantidad"] or 0) > 0]
    # FEFO: lo que vence antes, primero
    lotes.sort(key=lambda l: (l["vencimiento"] or "9999"))

    desc = next((str(f["descripcion"]) for f in filas if f["descripcion"]), "")

    return {
        "encontrado": True,
        "sku": codigo,
        "codigo": codigo,
        "descripcion": desc,
        "total": sum(u["cantidad"] for u in ubicaciones),
        "en_picking": suma(sv.AREA_PICKING),
        "en_almacenamiento": suma(sv.AREA_ALMACENAMIENTO),
        "en_staging": suma(sv.AREA_STAGING),
        "reservado": sum(u["reservado"] for u in ubicaciones),
        "pickeado": sum(u["pickeado"] for u in ubicaciones),
        "ubicaciones": ubicaciones,
        "lotes": lotes,
    }


def _por_descripcion(con, texto: str) -> dict:
    """Si no se encontro por codigo, busca por descripcion (max 20)."""
    filas = con.execute(
        f"""SELECT sku, sku_clave, descripcion,
                   SUM(cantidad - reservado - pickeado) AS disponible
              FROM {sv.TABLA}
             WHERE UPPER(descripcion) LIKE UPPER(?)
             GROUP BY sku, sku_clave, descripcion
             ORDER BY disponible DESC LIMIT 20""",
        (f"%{texto}%",),
    ).fetchall()

    if not filas:
        return {"encontrado": False, "sku": "", "descripcion": "",
                "total": 0, "en_picking": 0, "en_almacenamiento": 0,
                "en_staging": 0, "reservado": 0, "pickeado": 0,
                "ubicaciones": [], "lotes": [],
                "error": f"no se encontro '{texto}'"}

    return {
        "encontrado": False,          # no es un SKU exacto
        "sugerencias": [{
            "sku": str(f["sku"]), "descripcion": str(f["descripcion"] or ""),
            "disponible": int(f["disponible"] or 0),
        } for f in filas],
        "sku": "", "descripcion": "", "total": 0, "en_picking": 0,
        "en_almacenamiento": 0, "en_staging": 0, "reservado": 0, "pickeado": 0,
        "ubicaciones": [], "lotes": [],
    }
