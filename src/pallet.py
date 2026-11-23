"""Pallet de armado y contraste volante vs sumario.

Dos cosas del flujo real de despacho (aclaradas por el usuario):

1. **PALLET DE ARMADO** — el armador necesita ver el pallet COMPLETO, con todos
   sus SKUs juntos, no una tarea suelta por SKU. Un pallet mixto tiene 4 SKUs y
   hoy el sistema los entrega como 4 tareas separadas.

2. **CONTRASTE VOLANTE vs SUMARIO** — el volante es lo que el pickeador **anota
   a mano** cuando saca mercadería. Después, en el área de despacho, se contrasta
   contra el sumario: ¿el volante trae los productos y cantidades que el sumario
   pide? Si falta algo, se detecta ANTES de que salga el camión.

   El volante se puede cargar a mano (lo que está escrito) o, si algún día tiene
   código, se podría leer. Por ahora: se digita.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .externos import clave_sku
from . import stock_vivo as sv


# ---------------------------------------------------------------------------
# 1. Pallet de armado
# ---------------------------------------------------------------------------

@dataclass
class Pallet:
    camion: str
    pallet: str
    lineas: list[dict] = field(default_factory=list)

    @property
    def cajas(self) -> int:
        return sum(int(l.get("cantidad", 0)) for l in self.lineas)

    @property
    def skus(self) -> int:
        return len(self.lineas)

    @property
    def mixto(self) -> bool:
        return self.skus > 1

    def resumen(self) -> dict:
        return {"camion": self.camion, "pallet": self.pallet,
                "skus": self.skus, "cajas": self.cajas, "mixto": self.mixto}


def pallet_de(db: str | Path, camion: str, pallet: str) -> Pallet | None:
    """Trae el pallet completo del sumario, con el stock disponible de cada SKU.

    Es lo que el armador necesita ver: todos los SKUs juntos, en que ubicacion
    esta cada uno y cuanto hay.
    """
    with sv.abrir(db) as con:
        try:
            filas = con.execute(
                """SELECT camion, pallet, sku, descripcion, cantidad
                     FROM sumario WHERE camion = ? AND pallet = ?
                     ORDER BY sku""", (camion, pallet)
            ).fetchall()
        except Exception:
            return None
        if not filas:
            return None

        lineas = []
        for f in filas:
            clave = clave_sku(f["sku"])
            ubic = con.execute(
                f"""SELECT ubicacion, area, SUM(cantidad - reservado - pickeado) AS disp
                      FROM {sv.TABLA} WHERE sku_clave = ?
                     GROUP BY ubicacion, area
                     ORDER BY (area <> 'AREA PICKING'), disp DESC""",
                (clave,),
            ).fetchall()
            disp_total = sum(int(u["disp"] or 0) for u in ubic)
            primera = ubic[0] if ubic else None
            lineas.append({
                "sku": f["sku"],
                "descripcion": f["descripcion"],
                "cantidad": int(f["cantidad"]),
                "ubicacion": primera["ubicacion"] if primera else "",
                "area": primera["area"] if primera else "",
                "disponible": disp_total,
                "alcanza": disp_total >= int(f["cantidad"]),
            })

    return Pallet(camion=camion, pallet=pallet, lineas=lineas)


def pallets_de_camion(db: str | Path, camion: str) -> list[dict]:
    """Los pallets de un camion, con su resumen (para elegir cual armar)."""
    with sv.abrir(db) as con:
        try:
            filas = con.execute(
                """SELECT pallet, COUNT(*) AS skus, SUM(cantidad) AS cajas
                     FROM sumario WHERE camion = ?
                     GROUP BY pallet ORDER BY pallet""", (camion,)
            ).fetchall()
        except Exception:
            return []
    return [{"camion": camion, "pallet": f["pallet"], "skus": int(f["skus"]),
             "cajas": int(f["cajas"]), "mixto": int(f["skus"]) > 1}
            for f in filas]


# ---------------------------------------------------------------------------
# 2. Contraste volante vs sumario
# ---------------------------------------------------------------------------

@dataclass
class Contraste:
    camion: str
    pallet: str
    filas: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f["estado"] == "ok" for f in self.filas)

    @property
    def faltantes(self) -> int:
        return sum(1 for f in self.filas if f["estado"] == "falta")

    @property
    def sobrantes(self) -> int:
        return sum(1 for f in self.filas if f["estado"] == "sobra")

    def resumen(self) -> dict:
        return {"camion": self.camion, "pallet": self.pallet, "ok": self.ok,
                "lineas": len(self.filas), "faltantes": self.faltantes,
                "sobrantes": self.sobrantes}


def _normalizar_volante(volante: pd.DataFrame | list[dict]) -> dict[str, int]:
    """Convierte lo anotado en el volante a {clave_sku: cantidad}.

    Acepta un DataFrame con columnas `sku` y `cantidad`, o una lista de dicts.
    """
    if isinstance(volante, pd.DataFrame):
        datos = volante.to_dict("records")
    else:
        datos = list(volante or [])

    acum: dict[str, int] = {}
    for r in datos:
        sku = str(r.get("sku", "")).strip()
        if not sku:
            continue
        try:
            cant = int(float(r.get("cantidad", 0) or 0))
        except (TypeError, ValueError):
            continue
        if cant <= 0:
            continue
        k = clave_sku(sku)
        acum[k] = acum.get(k, 0) + cant
    return acum


def contrastar(db: str | Path, camion: str, pallet: str,
               volante: pd.DataFrame | list[dict]) -> Contraste:
    """Contrasta lo anotado en el volante contra lo que pide el sumario.

    Devuelve, linea por linea:
      - ok     : lo anotado coincide con el sumario
      - falta  : se anoto menos de lo pedido (o nada)
      - sobra  : se anoto mas de lo pedido

    Y marca los SKU que estan en el volante pero NO en el sumario.
    """
    with sv.abrir(db) as con:
        try:
            pedido = con.execute(
                """SELECT sku, descripcion, cantidad FROM sumario
                    WHERE camion = ? AND pallet = ? ORDER BY sku""",
                (camion, pallet),
            ).fetchall()
        except Exception:
            pedido = []

    anotado = _normalizar_volante(volante)

    filas = []
    vistos = set()
    for f in pedido:
        k = clave_sku(f["sku"])
        vistos.add(k)
        esperado = int(f["cantidad"])
        real = anotado.get(k, 0)
        if real == esperado:
            estado = "ok"
        elif real < esperado:
            estado = "falta"
        else:
            estado = "sobra"
        filas.append({
            "sku": f["sku"], "descripcion": f["descripcion"],
            "sumario": esperado, "volante": real,
            "diferencia": real - esperado, "estado": estado,
        })

    # SKU anotados que el sumario NO pide
    for k, real in anotado.items():
        if k in vistos:
            continue
        filas.append({"sku": k, "descripcion": "(no está en el sumario)",
                      "sumario": 0, "volante": real,
                      "diferencia": real, "estado": "sobra"})

    filas.sort(key=lambda x: (x["estado"] == "ok", x["sku"]))
    return Contraste(camion=camion, pallet=pallet, filas=filas)
