"""Contraste VENTA vs STOCK vs TRANSITO (proceso 1 del Plan B).

Responde la pregunta central de la contingencia: **¿alcanza lo que hay para
abastecer la venta del dia?** y, si no alcanza, cuanto falta.

Entradas
  - STOCK     : cuadratura con Detalle (src/inventario.py) -> picking + almacen
  - VENTA     : demanda del dia, desde TRUCK (src/externos.py)
  - TRANSITO  : lo que viene en camino, desde SAP, por OCA (src/externos.py)

Regla
  disponible = stock_picking + stock_almacenamiento + transito
  falta      = max(0, demanda - disponible)

La llave de cruce es el SKU normalizado (ver `externos.clave_sku`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import externos
from . import inventario as inv

COLUMNAS_CONTRASTE = [
    "sku", "descripcion", "demanda", "picking", "almacen", "transito",
    "disponible", "falta", "cubre",
]


@dataclass
class Contraste:
    dataframe: pd.DataFrame
    sin_venta: pd.DataFrame = field(default_factory=pd.DataFrame)
    sin_stock: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def filas(self) -> int:
        return len(self.dataframe)

    @property
    def quiebres(self) -> pd.DataFrame:
        """SKUs donde la venta NO alcanza a cubrirse."""
        if self.dataframe.empty:
            return self.dataframe
        return self.dataframe[~self.dataframe["cubre"]].sort_values(
            "falta", ascending=False)

    def resumen(self) -> dict:
        total_demanda = int(self.dataframe["demanda"].sum()) if not self.dataframe.empty else 0
        total_falta = int(self.dataframe["falta"].sum()) if not self.dataframe.empty else 0
        return {
            "skus": len(self.dataframe),
            "demanda": total_demanda,
            "cubierto": total_demanda - total_falta,
            "falta": total_falta,
            "quiebres": len(self.quiebres),
            "pct_cubierto": round(
                100 * (total_demanda - total_falta) / total_demanda, 1
            ) if total_demanda else 100.0,
        }


def _stock_por_sku(stock: inv.Inventario) -> pd.DataFrame:
    """Stock por SKU separado en picking y almacenamiento (clave normalizada)."""
    if stock.dataframe.empty:
        return pd.DataFrame(columns=["sku_clave", "picking", "almacen", "descripcion"])

    df = stock.dataframe.copy()
    df["sku_clave"] = df["sku"].map(externos.clave_sku)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype("int64")
    df["area_tipo"] = "otros"
    df.loc[df["area"].eq(inv.AREA_PICKING), "area_tipo"] = "picking"
    df.loc[df["area"].eq(inv.AREA_ALMACENAMIENTO), "area_tipo"] = "almacen"

    por_area = (
        df.pivot_table(index="sku_clave", columns="area_tipo", values="cantidad",
                       aggfunc="sum", fill_value=0)
    )
    for c in ("picking", "almacen"):
        if c not in por_area.columns:
            por_area[c] = 0
    desc = df.groupby("sku_clave")["descripcion"].first()
    por_area = por_area.join(desc)
    return por_area.reset_index()[["sku_clave", "picking", "almacen", "descripcion"]]


def _demanda_por_sku(venta: externos.Venta) -> pd.DataFrame:
    if venta is None or venta.dataframe.empty:
        return pd.DataFrame(columns=["sku_clave", "demanda", "descripcion_venta"])
    df = venta.dataframe.copy()
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    agrupado = df.groupby("sku_clave").agg(
        demanda=("cantidad", lambda s: int(s.sum())),
        descripcion_venta=("descripcion", "first"),
    ).reset_index()
    return agrupado


def _transito_por_sku(transito: externos.Transito) -> pd.DataFrame:
    if transito is None or transito.dataframe.empty:
        return pd.DataFrame(columns=["sku_clave", "transito"])
    df = transito.dataframe.copy()
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    agrupado = df.groupby("sku_clave").agg(
        transito=("cantidad", lambda s: int(s.sum())),
    ).reset_index()
    return agrupado


def calcular(
    stock: inv.Inventario,
    venta: externos.Venta | None = None,
    transito: externos.Transito | None = None,
) -> Contraste:
    """Cruza venta vs stock vs transito y detecta quiebres."""
    demanda = _demanda_por_sku(venta) if venta is not None else pd.DataFrame(
        columns=["sku_clave", "demanda", "descripcion_venta"])
    stock_sku = _stock_por_sku(stock)
    transito_sku = _transito_por_sku(transito) if transito is not None else pd.DataFrame(
        columns=["sku_clave", "transito"])

    # Base: todos los SKUs que aparecen en la venta (es lo que hay que abastecer)
    base = demanda.merge(stock_sku, on="sku_clave", how="left")
    base = base.merge(transito_sku, on="sku_clave", how="left")

    for c in ("picking", "almacen", "transito", "demanda"):
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0).astype("int64")
        else:
            base[c] = 0

    base["disponible"] = base["picking"] + base["almacen"] + base["transito"]
    base["falta"] = (base["demanda"] - base["disponible"]).clip(lower=0).astype("int64")
    base["cubre"] = base["falta"].eq(0)
    base["descripcion"] = base["descripcion"].fillna(base["descripcion_venta"]).fillna("")

    # SKUs que estan en venta pero NO tienen stock (quiebre total)
    sin_stock = base[base["disponible"].eq(0)][["sku_clave", "descripcion", "demanda"]].copy()
    sin_stock = sin_stock.rename(columns={"sku_clave": "sku"}).reset_index(drop=True)

    base = base.rename(columns={"sku_clave": "sku"})

    # SKUs con stock pero sin venta (no se necesitan hoy)
    con_stock = set(stock_sku["sku_clave"]) if not stock_sku.empty else set()
    con_venta = set(demanda["sku_clave"]) if not demanda.empty else set()
    sobrantes = sorted(con_stock - con_venta)
    if sobrantes:
        sin_venta = stock_sku[stock_sku["sku_clave"].isin(sobrantes)].copy()
        sin_venta = sin_venta.rename(columns={"sku_clave": "sku"}).reset_index(drop=True)
    else:
        sin_venta = pd.DataFrame(columns=["sku", "picking", "almacen", "descripcion"])

    resultado = base[COLUMNAS_CONTRASTE].sort_values(
        ["cubre", "falta", "demanda"], ascending=[True, False, False]
    ).reset_index(drop=True)

    return Contraste(resultado, sin_venta=sin_venta, sin_stock=sin_stock)
