"""Fuentes EXTERNAS del Plan B: la VENTA (TRUCK) y el TRANSITO (SAP).

Estas dos fuentes NO se capturan de Blue Yonder; llegan como archivos:

VENTA — programa TRUCK
  Archivo: CSV con separador ';' y encoding UTF-8 (ej. "ExcelPreventaBIARRIAG (75).csv").
  44 columnas; las utiles para el Plan B:
    PRODUCTO       -> SKU (llave de cruce)
    DESCRIPCION.4  -> descripcion del producto
    CANTIDAD       -> cajas pedidas
    UNIDAD         -> CJ (caja) / CU (unidad)
    FECHA          -> fecha del pedido (dd/mm/aaaa)
    ESTADO         -> ING (ingresado) / LIQ (liquidado)
    CATEGORIA, MARCA, TAMAÑO, CAMION, VIAJE, PLANILLA, ID-CLIENTE, RAZON SOCIAL
  OJO: el archivo trae MUCHAS filas totalmente vacias al final (se descartan).

TRANSITO — SAP (mercaderia en camino, identificada por OCA)
  Archivo: Excel (.xlsx), hoja 'Data', 52 columnas. Las utiles:
    Material                  -> SKU (llave de cruce)
    Texto breve material      -> descripcion
    Cantidad Entrega          -> cajas en transito
    Cantidad Pallet           -> pallets
    OCA(Orden de Carga)       -> OCA
    Id.1 / OCA                -> id alternativo de OCA
    Nº de transporte, Centro Origen/Destino, Fecha, Clase de movimiento,
    Stat.global transp. (6 = en transito, 7 = ...), Grupo de artículos

LLAVE DE CRUCE
  El SKU es la llave entre las tres fuentes (cuadratura.prtnum = TRUCK.PRODUCTO
  = SAP.Material). Los formatos varian: cuadratura/SAP usan ceros a la izquierda
  ("000622") y TRUCK no ("622"). Por eso se compara con `clave_sku()`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Llave de cruce
# ---------------------------------------------------------------------------


def clave_sku(valor: object) -> str:
    """Normaliza un SKU para cruzarlo entre fuentes.

    Quita espacios y ceros a la izquierda ("000622" -> "622"). Si queda vacio
    devuelve "".
    """
    if valor is None:
        return ""
    texto = str(valor).strip()
    if not texto:
        return ""
    limpio = texto.lstrip("0")
    return limpio if limpio else "0"


# ---------------------------------------------------------------------------
# VENTA (TRUCK)
# ---------------------------------------------------------------------------

COLUMNAS_VENTA = [
    "sku", "descripcion", "cantidad", "unidad", "fecha", "estado",
    "categoria", "marca", "tamano", "camion", "viaje", "planilla",
    "id_cliente", "razon_social", "sku_clave",
]

# Nombres reales en el CSV de TRUCK
_CSV_VENTA = {
    "PRODUCTO": "sku",
    "DESCRIPCION.4": "descripcion",
    "CANTIDAD": "cantidad",
    "UNIDAD": "unidad",
    "FECHA": "fecha",
    "ESTADO": "estado",
    "CATEGORIA": "categoria",
    "MARCA": "marca",
    "TAMAÑO": "tamano",
    "CAMION": "camion",
    "VIAJE": "viaje",
    "PLANILLA": "planilla",
    "ID-CLIENTE": "id_cliente",
    "RAZON SOCIAL": "razon_social",
}


@dataclass
class Venta:
    dataframe: pd.DataFrame
    filas: int = 0
    descartadas: int = 0

    def __post_init__(self):
        if self.filas == 0 and not self.dataframe.empty:
            self.filas = len(self.dataframe)

    def guardar(self, destino: str | Path = "data/plan_b.sqlite") -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destino) as con:
            self.dataframe.to_sql("venta", con, if_exists="replace", index=False)
        return destino

    @staticmethod
    def cargar(ruta: str | Path = "data/plan_b.sqlite") -> "Venta":
        with sqlite3.connect(ruta) as con:
            df = pd.read_sql_query("SELECT * FROM venta", con)
        return Venta(df, filas=len(df))

    def demanda_por_sku(self) -> pd.DataFrame:
        """Cajas pedidas por SKU (agrupado)."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["sku_clave", "cajas"])
        agrupado = (
            self.dataframe.groupby("sku_clave", as_index=False)["cantidad"].sum()
            .rename(columns={"cantidad": "cajas"})
        )
        return agrupado.sort_values("cajas", ascending=False)


def leer_venta(contenido: bytes | str, encoding: str = "utf-8") -> Venta:
    """Lee el CSV de TRUCK (separador ';').

    Acepta bytes (recomendado, para detectar el encoding) o texto ya decodificado.
    """
    if isinstance(contenido, bytes):
        texto = None
        for enc in (encoding, "utf-8-sig", "latin-1"):
            try:
                texto = contenido.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        contenido = texto if texto is not None else contenido.decode("latin-1")

    bruto = pd.read_csv(StringIO(contenido), sep=";", dtype=str, engine="python")
    total = len(bruto)
    # El archivo trae miles de filas vacias al final
    utiles = bruto.dropna(how="all")
    utiles = utiles[utiles.apply(lambda f: f.astype(str).str.strip().ne("").any(), axis=1)]

    faltan = [c for c in _CSV_VENTA if c not in utiles.columns]
    if faltan:
        raise ValueError(
            f"Al CSV de TRUCK le faltan columnas esperadas: {faltan}. "
            f"Columnas presentes: {list(utiles.columns)}"
        )

    df = utiles[list(_CSV_VENTA)].rename(columns=_CSV_VENTA).copy()
    for c in ("sku", "descripcion", "unidad", "estado", "categoria", "marca",
              "tamano", "planilla", "razon_social"):
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["sku_clave"] = df["sku"].map(clave_sku)
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype("int64")
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y", errors="coerce")
    df = df[df["sku_clave"] != ""]

    return Venta(df[COLUMNAS_VENTA], filas=len(df), descartadas=total - len(df))


# ---------------------------------------------------------------------------
# TRANSITO (SAP)
# ---------------------------------------------------------------------------

COLUMNAS_TRANSITO = [
    "sku", "descripcion", "cantidad", "pallets", "oca", "oca_alt",
    "n_transporte", "centro_origen", "centro_destino", "fecha",
    "clase_movimiento", "stat_transp", "grupo_articulos", "sociedad",
    "sku_clave",
]

# Nombres reales en el Excel de SAP
_XLSX_TRANSITO = {
    "Material": "sku",
    "Texto breve material": "descripcion",
    "Cantidad Entrega": "cantidad",
    "Cantidad Pallet": "pallets",
    "OCA(Orden de Carga)": "oca",
    "Id.1 / OCA": "oca_alt",
    "Nº de transporte": "n_transporte",
    "Centro Origen": "centro_origen",
    "Centro Destino": "centro_destino",
    "Fecha": "fecha",
    "Clase de movimiento": "clase_movimiento",
    "Stat.global transp.": "stat_transp",
    "Grupo de artículos": "grupo_articulos",
    "Sociedad": "sociedad",
}


@dataclass
class Transito:
    dataframe: pd.DataFrame
    filas: int = 0
    descartadas: int = 0

    def __post_init__(self):
        if self.filas == 0 and not self.dataframe.empty:
            self.filas = len(self.dataframe)

    def guardar(self, destino: str | Path = "data/plan_b.sqlite") -> Path:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destino) as con:
            self.dataframe.to_sql("transito", con, if_exists="replace", index=False)
        return destino

    @staticmethod
    def cargar(ruta: str | Path = "data/plan_b.sqlite") -> "Transito":
        with sqlite3.connect(ruta) as con:
            df = pd.read_sql_query("SELECT * FROM transito", con)
        return Transito(df, filas=len(df))

    def por_oca(self) -> pd.DataFrame:
        """Cajas en transito agrupadas por OCA."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["oca", "cajas"])
        agrupado = (
            self.dataframe.groupby("oca", as_index=False)["cantidad"].sum()
            .rename(columns={"cantidad": "cajas"})
        )
        return agrupado.sort_values("cajas", ascending=False)

    def en_camino_por_sku(self) -> pd.DataFrame:
        """Cajas en camino por SKU (agrupado)."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["sku_clave", "cajas"])
        agrupado = (
            self.dataframe.groupby("sku_clave", as_index=False)["cantidad"].sum()
            .rename(columns={"cantidad": "cajas"})
        )
        return agrupado.sort_values("cajas", ascending=False)


def leer_transito(contenido: bytes, hoja: str = "Data") -> Transito:
    """Lee el Excel de SAP (transito). `contenido` son los bytes del .xlsx."""
    bruto = pd.read_excel(BytesIO(contenido), sheet_name=hoja, dtype=str)
    total = len(bruto)

    faltan = [c for c in _XLSX_TRANSITO if c not in bruto.columns]
    if faltan:
        raise ValueError(
            f"Al Excel de SAP le faltan columnas esperadas: {faltan}. "
            f"Columnas presentes: {list(bruto.columns)}"
        )

    df = bruto[list(_XLSX_TRANSITO)].rename(columns=_XLSX_TRANSITO).copy()
    for c in ("sku", "descripcion", "oca", "oca_alt", "n_transporte",
              "centro_origen", "centro_destino", "clase_movimiento",
              "stat_transp", "grupo_articulos", "sociedad"):
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["sku_clave"] = df["sku"].map(clave_sku)
    for c in ("cantidad", "pallets"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df = df[df["sku_clave"] != ""]

    return Transito(df[COLUMNAS_TRANSITO], filas=len(df), descartadas=total - len(df))


def cargar_venta_desde_archivo(ruta: str | Path) -> Venta:
    return leer_venta(Path(ruta).read_bytes())


def cargar_transito_desde_archivo(ruta: str | Path) -> Transito:
    return leer_transito(Path(ruta).read_bytes())
