"""Inventario offline para el Plan B.

Lee el TSV capturado de 'CCU Cuadratura de Stock' con el checkbox DETALLE activo
(22 columnas) y lo guarda en una base SQLite local, para poder consultarlo aunque
Blue Yonder este caido.

Tambien puede cargar el TSV/CSV de MINIMOS Y MAXIMOS por ubicacion (cuando se
conozca su formato) y cruzarlo con el stock para saber que reponer.

Uso como modulo:
    from src import inventario
    inv = inventario.cargar_desde_archivo("data/raw_detalle_2026-10-21.tsv")
    inv.guardar("data/plan_b.sqlite")
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Columnas reales de la cuadratura con DETALLE activo (en orden)
COLUMNAS_DETALLE = [
    "zona_trabajo", "zona_recogida", "area_sap", "ubicacion", "estado_ubicacion",
    "lpn", "lpn_detalle", "sku", "cod_espacio", "descripcion", "cantidad",
    "cantidad_pendiente", "cantidad_confirmada", "fecha_fifo", "fecha_fabricacion",
    "fecha_caducidad", "fecha_recepcion", "estado_inv", "perfil_antiguedad",
    "dias_caducidad", "ult_movimiento", "area",
]

# Columnas numericas
NUMERICAS = ["cantidad", "cantidad_pendiente", "cantidad_confirmada", "dias_caducidad"]

# Columnas de fecha (dd/mm/yyyy HH:MM:SS)
FECHAS = ["fecha_fifo", "fecha_fabricacion", "fecha_caducidad", "fecha_recepcion",
          "ult_movimiento"]

# Areas relevantes para el plan B
AREA_PICKING = "AREA PICKING"
AREA_ALMACENAMIENTO = "AREA ALMACENAMIENTO"


def _normalizar(celdas: list[str]) -> list[str]:
    """Ajusta una fila a 22 columnas.

    La grilla puede omitir celdas vacias al copiar; se rellenan al final para no
    correr las columnas.
    """
    n = len(COLUMNAS_DETALLE)
    if len(celdas) >= n:
        return celdas[:n]
    return celdas + [""] * (n - len(celdas))


@dataclass
class Inventario:
    dataframe: pd.DataFrame
    filas: int = 0
    descartadas: int = 0
    anomalias: int = 0

    def __post_init__(self):
        if self.filas == 0 and not self.dataframe.empty:
            self.filas = len(self.dataframe)

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def guardar(self, destino: str | Path = "data/plan_b.sqlite") -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destino) as con:
            self.dataframe.to_sql("stock", con, if_exists="replace", index=False)
        return destino

    @staticmethod
    def cargar(ruta: str | Path = "data/plan_b.sqlite") -> "Inventario":
        with sqlite3.connect(ruta) as con:
            df = pd.read_sql_query("SELECT * FROM stock", con)
        return Inventario(df, filas=len(df))

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def por_area(self, area: str) -> pd.DataFrame:
        return self.dataframe[self.dataframe["area"] == area]

    def stock_de(self, sku: str, area: str | None = None) -> pd.DataFrame:
        df = self.dataframe[self.dataframe["sku"] == sku]
        if area:
            df = df[df["area"] == area]
        return df

    def resumen_sku(self, sku: str) -> dict:
        """Totales de un SKU, separando picking y almacenamiento."""
        df = self.stock_de(sku)
        pick = df[df["area"] == AREA_PICKING]["cantidad"].sum()
        alm = df[df["area"] == AREA_ALMACENAMIENTO]["cantidad"].sum()
        return {
            "sku": sku,
            "descripcion": df["descripcion"].iloc[0] if not df.empty else "",
            "en_picking": int(pick),
            "en_almacenamiento": int(alm),
            "total": int(pick + alm),
            "ubicaciones": int(df["ubicacion"].nunique()),
            "lotes": int(df["lpn"].nunique()),
        }

    def fefo(self, sku: str, area: str | None = None) -> pd.DataFrame:
        """Stock de un SKU ordenado por vencimiento (FEFO)."""
        df = self.stock_de(sku, area).copy()
        if df.empty:
            return df
        df["_venc"] = pd.to_datetime(df["fecha_caducidad"], format="%d/%m/%Y %H:%M:%S",
                                     errors="coerce")
        return df.sort_values("_venc", na_position="last").drop(columns="_venc")

    def buscar(self, texto: str, limite: int = 50) -> pd.DataFrame:
        """Busca por SKU, descripcion o ubicacion (contiene, sin mayusculas)."""
        t = texto.lower()
        df = self.dataframe
        mask = (
            df["sku"].str.lower().str.contains(t, na=False)
            | df["descripcion"].str.lower().str.contains(t, na=False)
            | df["ubicacion"].str.lower().str.contains(t, na=False)
        )
        return df[mask].head(limite)


def leer_detalle(texto: str) -> Inventario:
    """Convierte el TSV de la cuadratura (con Detalle) en un Inventario."""
    registros: list[list[str]] = []
    descartadas = 0
    anomalias = 0
    n = len(COLUMNAS_DETALLE)

    for ln in texto.splitlines():
        if not ln.strip():
            continue
        celdas = [c.strip() for c in ln.split("\t")]
        # Una fila valida tiene al menos 18 celdas (las primeras columnas siempre vienen)
        if len(celdas) < 18:
            descartadas += 1
            continue
        if len(celdas) != n:
            anomalias += 1
        registros.append(_normalizar(celdas))

    df = pd.DataFrame(registros, columns=COLUMNAS_DETALLE)

    if not df.empty:
        for col in NUMERICAS:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")
        # Normaliza el nombre del area (mayusculas, sin espacios dobles)
        df["area"] = df["area"].str.upper().str.replace(r"\s+", " ", regex=True).str.strip()

    return Inventario(df, filas=len(df), descartadas=descartadas, anomalias=anomalias)


def cargar_desde_archivo(ruta: str | Path) -> Inventario:
    return leer_detalle(Path(ruta).read_text(encoding="utf-8"))
