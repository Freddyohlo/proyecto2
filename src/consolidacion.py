"""Consolidación: los consolidadores arman los pallets en staging.

MODELO REAL (aclarado por el usuario):

    PICKER                          CONSOLIDADOR
    ──────                          ────────────
    Saca la mercadería de la        Recibe todo lo pickeado en STAGING
    ubicación y la deja en          y ARMA los pallets de cada camión,
    STAGING (no arma pallets)       según lo que pide el sumario.

Por eso el picker NO necesita saber para qué pallet es: solo saca y deja.
El pallet se arma después, en staging.

El consolidador necesita ver:
  - Qué falta juntar para cada pallet (según el sumario)
  - Qué hay disponible en staging
  - El avance: cuántos pallets están completos y cuántos no

Cuando un pallet se completa, se marca como consolidado (sale de staging hacia
el camión).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv
from .externos import clave_sku

TABLA = "consolidado"


def preparar_tabla(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, camion TEXT, pallet TEXT,
            sku TEXT, sku_clave TEXT, descripcion TEXT,
            cantidad INTEGER, estado TEXT NOT NULL DEFAULT 'ok'
        )
    """)


# ---------------------------------------------------------------------------
# Lo que hay en staging
# ---------------------------------------------------------------------------

def en_staging(db: str | Path) -> pd.DataFrame:
    """Mercadería pickeada que está esperando ser consolidada."""
    with sv.abrir(db) as con:
        return pd.read_sql_query(
            f"""SELECT ubicacion, sku, descripcion, lpn,
                       cantidad - reservado - pickeado AS disponible
                  FROM {sv.TABLA}
                 WHERE area = ? AND (cantidad - reservado - pickeado) > 0
                 ORDER BY sku""",
            con, params=(sv.AREA_STAGING,),
        )


def disponible_staging(db: str | Path, sku: str) -> int:
    """Cuántas cajas de un SKU hay en staging, listas para consolidar."""
    clave = clave_sku(sku)
    with sv.abrir(db) as con:
        f = con.execute(
            f"""SELECT COALESCE(SUM(cantidad - reservado - pickeado), 0) AS c
                  FROM {sv.TABLA}
                 WHERE area = ? AND sku_clave = ?""",
            (sv.AREA_STAGING, clave),
        ).fetchone()
    return int(f["c"] or 0)


# ---------------------------------------------------------------------------
# Estado de consolidación por pallet
# ---------------------------------------------------------------------------

@dataclass
class PalletConsolidado:
    camion: str
    pallet: str
    lineas: list[dict] = field(default_factory=list)

    @property
    def pedido(self) -> int:
        return sum(int(l["pedido"]) for l in self.lineas)

    @property
    def juntado(self) -> int:
        return sum(int(l["juntado"]) for l in self.lineas)

    @property
    def completo(self) -> bool:
        return all(l["estado"] == "ok" for l in self.lineas)

    def resumen(self) -> dict:
        return {"camion": self.camion, "pallet": self.pallet,
                "pedido": self.pedido, "juntado": self.juntado,
                "completo": self.completo,
                "pct": round(self.juntado / self.pedido * 100, 1) if self.pedido else 0}


def estado_pallet(db: str | Path, camion: str, pallet: str) -> PalletConsolidado | None:
    """Cuánto de cada SKU del pallet ya está en staging.

    Compara lo que pide el sumario contra lo que hay en staging y contra lo ya
    consolidado. Así el consolidador ve qué le falta juntar.
    """
    with sv.abrir(db) as con:
        preparar_tabla(con)
        try:
            pedido = con.execute(
                """SELECT sku, descripcion, cantidad FROM sumario
                    WHERE camion = ? AND pallet = ? ORDER BY sku""",
                (camion, pallet),
            ).fetchall()
        except Exception:
            return None
        if not pedido:
            return None

        filas = []
        for f in pedido:
            clave = clave_sku(f["sku"])
            # Ya consolidado para este pallet
            cons = con.execute(
                f"""SELECT COALESCE(SUM(cantidad),0) AS c FROM {TABLA}
                     WHERE camion = ? AND pallet = ? AND sku_clave = ?""",
                (camion, pallet, clave),
            ).fetchone()
            ya = int(cons["c"] or 0)
            # Disponible en staging
            disp = con.execute(
                f"""SELECT COALESCE(SUM(cantidad - reservado - pickeado),0) AS c
                      FROM {sv.TABLA} WHERE area = ? AND sku_clave = ?""",
                (sv.AREA_STAGING, clave),
            ).fetchone()
            en_stage = int(disp["c"] or 0)

            necesita = int(f["cantidad"])
            alcanza = ya + en_stage
            filas.append({
                "sku": f["sku"], "descripcion": f["descripcion"],
                "pedido": necesita, "consolidado": ya,
                "en_staging": en_stage, "juntado": min(alcanza, necesita),
                "falta": max(0, necesita - alcanza),
                "estado": "ok" if alcanza >= necesita else "falta",
            })

    return PalletConsolidado(camion=camion, pallet=pallet, lineas=filas)


def pallets_del_dia(db: str | Path, camion: str = "") -> list[dict]:
    """Todos los pallets con su avance, para el tablero del consolidador."""
    with sv.abrir(db) as con:
        preparar_tabla(con)
        try:
            if camion:
                filas = con.execute(
                    """SELECT camion, pallet, COUNT(*) AS skus, SUM(cantidad) AS cajas
                         FROM sumario WHERE camion = ?
                         GROUP BY camion, pallet ORDER BY camion, pallet""",
                    (camion,),
                ).fetchall()
            else:
                filas = con.execute(
                    """SELECT camion, pallet, COUNT(*) AS skus, SUM(cantidad) AS cajas
                         FROM sumario
                         GROUP BY camion, pallet ORDER BY camion, pallet"""
                ).fetchall()
        except Exception:
            return []

    salida = []
    for f in filas:
        est = estado_pallet(db, f["camion"], f["pallet"])
        if est is None:
            continue
        r = est.resumen()
        r["skus"] = int(f["skus"])
        salida.append(r)
    return salida


# ---------------------------------------------------------------------------
# Consolidar (marcar el pallet como armado)
# ---------------------------------------------------------------------------

def consolidar(db: str | Path, camion: str, pallet: str,
               usuario: str = "") -> dict:
    """Marca el pallet como armado: descuenta de staging y lo registra.

    Solo se puede consolidar si en staging alcanza para cubrir lo que pide el
    sumario. Si falta algo, NO se consolida (se avisa qué falta).
    """
    est = estado_pallet(db, camion, pallet)
    if est is None:
        return {"ok": False, "error": "pallet no encontrado", "code": 404}

    if not est.completo:
        faltan = [l for l in est.lineas if l["estado"] == "falta"]
        return {"ok": False, "code": 400,
                "error": "no alcanza en staging para consolidar",
                "faltantes": [{"sku": l["sku"], "falta": l["falta"]}
                              for l in faltan]}

    momento = datetime.now().isoformat(timespec="seconds")

    with sv.abrir(db) as con:
        preparar_tabla(con)
        for l in est.lineas:
            clave = clave_sku(l["sku"])
            por_juntar = int(l["pedido"]) - int(l["consolidado"])
            if por_juntar <= 0:
                continue

            # Descontar de staging (FEFO: primero lo que vence antes)
            restante = por_juntar
            filas = con.execute(
                f"""SELECT id, cantidad, reservado, pickeado FROM {sv.TABLA}
                     WHERE area = ? AND sku_clave = ?
                       AND (cantidad - reservado - pickeado) > 0
                     ORDER BY CASE WHEN fecha_ord = '' THEN 1 ELSE 0 END, fecha_ord""",
                (sv.AREA_STAGING, clave),
            ).fetchall()
            for f in filas:
                if restante <= 0:
                    break
                disp = int(f["cantidad"]) - int(f["reservado"] or 0) - int(f["pickeado"] or 0)
                tomar = min(restante, disp)
                if tomar <= 0:
                    continue
                # Sale de staging: se suma a "pickeado" (ya se consumió)
                con.execute(
                    f"UPDATE {sv.TABLA} SET pickeado = pickeado + ? WHERE id = ?",
                    (tomar, f["id"]),
                )
                restante -= tomar

            con.execute(
                f"""INSERT INTO {TABLA}
                    (fecha, usuario, camion, pallet, sku, sku_clave, descripcion,
                     cantidad, estado)
                    VALUES (?,?,?,?,?,?,?,?,'ok')""",
                (momento, usuario, camion, pallet, l["sku"], clave,
                 l["descripcion"], por_juntar),
            )

    return {"ok": True, "camion": camion, "pallet": pallet,
            "cajas": est.pedido, "momento": momento}


def resumen(db: str | Path) -> dict:
    """Cuántos pallets están completos y cuántos faltan."""
    pallets = pallets_del_dia(db)
    total = len(pallets)
    completos = sum(1 for p in pallets if p["completo"])
    return {"pallets": total, "completos": completos,
            "pendientes": total - completos,
            "cajas": sum(p["pedido"] for p in pallets),
            "cajas_juntadas": sum(p["juntado"] for p in pallets)}
