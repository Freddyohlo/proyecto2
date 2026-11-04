"""Minimos y maximos por ubicacion, y calculo de reaprovisionamiento (Plan B).

La cuadratura de stock dice CUANTO HAY. Esta parte dice CUANTO DEBERIA HABER
(minimo y maximo por ubicacion de picking) y calcula QUE REPONER.

FUENTE DE MIN/MAX (confirmada 2026-10-29):
  Pantalla Blue Yonder: Aplicaciones > Reabastecimiento > Operaciones de reabastecimiento
  (herramienta: tools/inspeccionar_reabastecimiento.py -> data/reabastecimiento_<fecha>.tsv)
  Columnas reales (18):
   1. Id. de almacén              (wh_id)     -> CD8000
   2. Número de artículo          (prtnum)    -> SKU
   3. Ubicación                   (stoloc)    -> KEG-04
   4. Zona de movimiento          (movzone)   -> ZM PICKING
   5. Estado de inventario        (invsts)    -> Disponible
   6. Porcentaje                  (pctflg)
   7. Máximo de unidades          (maxunt)    -> 🔑 MÁXIMO
   8. Mínimo de unidades          (minunt)    -> 🔑 MÍNIMO
   9. Máximo de ubicaciones para artículo (maxloc)
  10. Completo                    (cmpflg)
  11. Último intento de reabastecimiento
  12. Última modificación de
  13. Número de reabastecimiento
  14. Porcentaje de incremento    (inc_pct_flg)
  15. Unidad de incremento        (inc_unt)
  16. Porcentaje de liberación    (rls_pct)
  17. is_purged
  18. Código de zona de movimiento (movzone code) -> ZM-PICK

  Fila real de ejemplo:
  CD8000 | 000622 | KEG-04 | ZM PICKING | Disponible | Unchecked | 168 | 160 | 0 |
  Unchecked | 28/10/2026 03:06:29 | RSUAREZ | RCF00006U3 | Unchecked | 100 | 100 | 0 | ZM-PICK
  => SKU 000622, ubicacion KEG-04, MAX=168, MIN=160

Reglas de negocio (confirmadas):
  - Se dispara cuando la ubicacion de picking baja del MINIMO.
  - Se repone desde AREA ALMACENAMIENTO.
  - Se repone HASTA EL MAXIMO, aunque se exceda
    (ej.: max=200, quedan 20 -> se reponen 200 -> quedan 220).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import inventario as inv

# Columnas reales de la grilla de reabastecimiento (en orden)
COLUMNAS_REAB = [
    "wh_id", "sku", "ubicacion", "zona_movimiento", "invsts", "pctflg",
    "maximo", "minimo", "maxloc", "cmpflg", "ultimo_intento", "ultima_mod",
    "num_reab", "inc_pct_flg", "inc_unt", "rls_pct", "is_purged", "movzone_cod",
]

# Indices (0-based) de las columnas que nos importan
IDX_SKU = 1
IDX_UBICACION = 2
IDX_MAXIMO = 6
IDX_MINIMO = 7


@dataclass
class MinMax:
    dataframe: pd.DataFrame      # columnas: ubicacion, sku, minimo, maximo

    def guardar(self, destino: str | Path = "data/plan_b.sqlite") -> Path:
        import sqlite3

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destino) as con:
            self.dataframe.to_sql("minmax", con, if_exists="replace", index=False)
        return destino

    @staticmethod
    def cargar(ruta: str | Path = "data/plan_b.sqlite") -> "MinMax":
        import sqlite3

        with sqlite3.connect(ruta) as con:
            df = pd.read_sql_query("SELECT * FROM minmax", con)
        return MinMax(df)


def leer_reabastecimiento(texto: str) -> MinMax:
    """Lee el TSV de 'Operaciones de reabastecimiento' (18 columnas) -> MinMax.

    Normaliza filas cortas rellenando al final, y tipa minimo/maximo a entero.
    """
    registros: list[list[str]] = []
    n = len(COLUMNAS_REAB)
    for ln in texto.splitlines():
        if not ln.strip():
            continue
        celdas = [c.strip() for c in ln.split("\t")]
        if len(celdas) < 8:  # al menos hasta el minimo
            continue
        if len(celdas) < n:
            celdas = celdas + [""] * (n - len(celdas))
        registros.append(celdas[:n])

    if not registros:
        return MinMax(pd.DataFrame(columns=["ubicacion", "sku", "minimo", "maximo"]))

    df = pd.DataFrame(registros, columns=COLUMNAS_REAB)
    out = pd.DataFrame({
        "ubicacion": df["ubicacion"].astype(str).str.strip(),
        "sku": df["sku"].astype(str).str.strip(),
        "minimo": pd.to_numeric(df["minimo"], errors="coerce").fillna(0).astype(int),
        "maximo": pd.to_numeric(df["maximo"], errors="coerce").fillna(0).astype(int),
    })
    # Quita filas sin ubicacion (encabezados o basura)
    out = out[out["ubicacion"] != ""].reset_index(drop=True)
    return MinMax(out)


def leer_minmax(
    texto: str,
    col_ubicacion: str = "ubicacion",
    col_sku: str = "sku",
    col_minimo: str = "minimo",
    col_maximo: str = "maximo",
    separador: str = "\t",
) -> MinMax:
    """Lee un archivo generico de minimos/maximos (mapeo de columnas configurable).

    Acepta TSV o CSV. Util si el formato cambia o viene de otra fuente.
    """
    import io

    df = pd.read_csv(io.StringIO(texto), sep=separador, dtype=str)
    df.columns = [c.strip().lower() for c in df.columns]

    faltan = [c for c in (col_ubicacion, col_sku, col_minimo, col_maximo) if c not in df.columns]
    if faltan:
        raise ValueError(
            f"Faltan columnas en el archivo de minimos/maximos: {faltan}. "
            f"Columnas encontradas: {list(df.columns)}. "
            f"Usa --col-ubicacion/--col-sku/--col-minimo/--col-maximo para mapearlas."
        )

    out = pd.DataFrame({
        "ubicacion": df[col_ubicacion].astype(str).str.strip(),
        "sku": df[col_sku].astype(str).str.strip(),
        "minimo": pd.to_numeric(df[col_minimo], errors="coerce").fillna(0).astype(int),
        "maximo": pd.to_numeric(df[col_maximo], errors="coerce").fillna(0).astype(int),
    })
    return MinMax(out)


def leer_minmax_archivo(ruta: str | Path, **kwargs) -> MinMax:
    ruta = Path(ruta)
    separador = kwargs.pop("separador", None)
    if separador is None:
        separador = "," if ruta.suffix.lower() == ".csv" else "\t"
    return leer_minmax(ruta.read_text(encoding="utf-8"), separador=separador, **kwargs)


def cargar_reabastecimiento(ruta: str | Path) -> MinMax:
    """Carga el TSV de la pantalla de reabastecimiento (formato real de Blue Yonder)."""
    return leer_reabastecimiento(Path(ruta).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Reaprovisionamiento
# --------------------------------------------------------------------------
@dataclass
class NecesidadReposicion:
    """Una ubicacion de picking que quedo bajo el minimo y hay que reponer."""
    ubicacion: str
    sku: str
    descripcion: str
    stock_actual: int
    minimo: int
    maximo: int
    reponer: int              # cuanto mandar (hasta el maximo)
    disponible_almacen: int   # stock en AREA ALMACENAMIENTO
    cubre: bool               # si el almacen tiene suficiente


def calcular_reposicion(
    stock: inv.Inventario,
    minmax: MinMax,
    area_picking: str = inv.AREA_PICKING,
    area_almacen: str = inv.AREA_ALMACENAMIENTO,
) -> list[NecesidadReposicion]:
    """Ubicaciones de picking bajo el minimo, con cuanto reponer desde almacenamiento.

    Regla: si el stock de la ubicacion de picking < minimo, se repone hasta el
    maximo (cantidad = maximo, sin descontar lo que ya hay, segun lo confirmado).
    """
    df_stock = stock.dataframe
    if df_stock.empty or minmax.dataframe.empty:
        return []

    # Stock por ubicacion (solo picking)
    pick = (
        df_stock[df_stock["area"] == area_picking]
        .groupby(["ubicacion", "sku"], as_index=False)
        .agg(stock_actual=("cantidad", "sum"), descripcion=("descripcion", "first"))
    )

    # Stock disponible por SKU en almacenamiento (total, para saber si alcanza)
    alm = (
        df_stock[df_stock["area"] == area_almacen]
        .groupby("sku", as_index=False)
        .agg(disponible_almacen=("cantidad", "sum"))
    )

    mm = minmax.dataframe
    # Unir por ubicacion+sku (si el minmax no trae sku, unir solo por ubicacion)
    if (mm["sku"] == "").all():
        base = pick.merge(mm.drop(columns="sku"), on="ubicacion", how="inner")
    else:
        base = pick.merge(mm, on=["ubicacion", "sku"], how="inner")

    if base.empty:
        return []

    base = base.merge(alm, on="sku", how="left")
    base["disponible_almacen"] = base["disponible_almacen"].fillna(0).astype(int)

    # Solo las que estan BAJO el minimo
    bajo = base[base["stock_actual"] < base["minimo"]].copy()

    resultado: list[NecesidadReposicion] = []
    for _, r in bajo.iterrows():
        reponer = int(r["maximo"])  # hasta el maximo (segun regla confirmada)
        disponible = int(r["disponible_almacen"])
        resultado.append(NecesidadReposicion(
            ubicacion=str(r["ubicacion"]),
            sku=str(r["sku"]),
            descripcion=str(r.get("descripcion", "")),
            stock_actual=int(r["stock_actual"]),
            minimo=int(r["minimo"]),
            maximo=int(r["maximo"]),
            reponer=reponer,
            disponible_almacen=disponible,
            cubre=disponible >= reponer,
        ))

    # Ordenar: primero las que no se pueden cubrir (mas urgentes) y luego por faltante
    resultado.sort(key=lambda x: (x.cubre, x.stock_actual - x.minimo))
    return resultado


def reposicion_a_dataframe(items: list[NecesidadReposicion]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=[
            "ubicacion", "sku", "descripcion", "stock_actual", "minimo", "maximo",
            "reponer", "disponible_almacen", "cubre",
        ])
    return pd.DataFrame([vars(i) for i in items])
