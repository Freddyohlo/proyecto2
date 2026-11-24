"""Sumario de carga: la DEMANDA del dia cuando cae el sistema.

Cuando Blue Yonder se cae, la distribucion (que camiones salen y con que) ya
viene definida de afuera. Nosotros no decidimos la venta: la **recibimos**.

El documento es el **SUMARIO DE CARGA** (PDF), que trae, por camion y por pallet,
que producto y cuantas cajas lleva:

    LOAD SUMMARY RET_CL SUMARIO DE CARGA *012R01*
    CAMION # : 012R-01 FECHA : 07-11-2026 *012R01*
    801
    PALLET PRODUCTO DESCRIPCION CANTIDAD
    001 00447085 3R MANZANA 5GL VNR275X24 20
    Sub Total 20
    002 00700153 MIS_VARIET-CS-VNR187CCX24 3
    00700154 MIS_VARIET-SB-VNR187CCX24 1
    00700229 GATO_PREMIUM-CS-VNR187CCX24 2
    00700682 MIS_RES_MS-CS-VNR750CCX6-CO 5
    Sub Total 11
    TOTAL : 95 PESO: 0

Lo que nos importa para el picking:
  - CAMION  (ej. 012R-01)  -> agrupa los pallets
  - PALLET  (ej. 001)      -> un pallet fisico; puede ser MIXTO (varios SKU)
  - PRODUCTO (8 digitos)   -> el SKU, con ceros a la izquierda
  - CANTIDAD               -> cajas de ese SKU en ese pallet

Los campos que NO se usan (confirmado por el usuario):
  - El numero suelto despues del camion (801/802/803) es un correlativo.
  - El orden de los camiones lo define otra area.
  - "Prioridad" no se usa.

El **volante** (el otro PDF) es el papel de trabajo por pallet, con un codigo de
barras que identifica el pallet (0801 + camion + pallet). No hace falta leerlo:
el sumario ya trae todo lo necesario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Linea de producto CON pallet: PALLET(3) PRODUCTO(8) DESCRIPCION CANTIDAD
_RE_PRODUCTO_CON_PALLET = re.compile(r"^(\d{3})\s+(\d{4,14})\s+(.+?)\s+(\d+)$")
# Linea de producto SIN pallet (continuacion de un pallet mixto):
#   PRODUCTO(8) DESCRIPCION CANTIDAD
_RE_PRODUCTO_SIN_PALLET = re.compile(r"^(\d{4,14})\s+(.+?)\s+(\d+)$")
_RE_CAMION = re.compile(r"CAMION\s*#\s*:\s*(\S+)")
_RE_TOTAL = re.compile(r"TOTAL\s*:\s*(\d+)")


@dataclass
class Sumario:
    dataframe: pd.DataFrame
    camiones: list[str] = field(default_factory=list)
    pallets: int = 0
    cajas: int = 0
    descartadas: int = 0

    @property
    def filas(self) -> int:
        return len(self.dataframe)

    def por_camion(self) -> pd.DataFrame:
        """Cajas y SKUs por camion."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["camion", "pallets", "skus", "cajas"])
        g = self.dataframe.groupby("camion").agg(
            pallets=("pallet", "nunique"),
            skus=("sku", "nunique"),
            cajas=("cantidad", "sum"),
        ).reset_index()
        return g.sort_values("camion")

    def por_pallet(self) -> pd.DataFrame:
        """Una fila por pallet (con cuantos SKU y cajas lleva)."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["camion", "pallet", "skus", "cajas"])
        g = self.dataframe.groupby(["camion", "pallet"]).agg(
            skus=("sku", "nunique"),
            cajas=("cantidad", "sum"),
        ).reset_index()
        return g.sort_values(["camion", "pallet"])

    def demanda_por_sku(self) -> pd.DataFrame:
        """Cajas por SKU (formato que espera `picking.destinar`)."""
        if self.dataframe.empty:
            return pd.DataFrame(columns=["sku_clave", "cajas"])
        from .externos import clave_sku
        d = self.dataframe.copy()
        d["sku_clave"] = d["sku"].map(clave_sku)
        g = d.groupby("sku_clave", as_index=False)["cantidad"].sum()
        return g.rename(columns={"cantidad": "cajas"}).sort_values(
            "cajas", ascending=False)

    def guardar(self, destino: str | Path = "data/plan_b.sqlite") -> Path:
        import sqlite3
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(destino) as con:
            self.dataframe.to_sql("sumario", con, if_exists="replace", index=False)
        return destino

    @staticmethod
    def cargar(ruta: str | Path = "data/plan_b.sqlite") -> "Sumario":
        import sqlite3
        with sqlite3.connect(ruta) as con:
            df = pd.read_sql_query("SELECT * FROM sumario", con)
        return Sumario(
            dataframe=df,
            camiones=sorted(df["camion"].unique().tolist()) if len(df) else [],
            pallets=int(df[["camion", "pallet"]].drop_duplicates().shape[0])
            if len(df) else 0,
            cajas=int(df["cantidad"].sum()) if len(df) else 0,
        )


def leer_texto(texto: str) -> Sumario:
    """Parsea el texto ya extraido del PDF (o pegado a mano).

    OJO con los PALLETS MIXTOS: en el PDF, solo la PRIMERA linea de un pallet
    trae el numero de pallet. Las siguientes traen solo PRODUCTO, DESCRIPCION y
    CANTIDAD. Por eso se recuerda el pallet actual y se arrastra.

        PALLET PRODUCTO DESCRIPCION CANTIDAD
        002 00700153 MIS_VARIET-CS-VNR187CCX24  3   <- trae pallet
        00700154 MIS_VARIET-SB-VNR187CCX24      1   <- sin pallet: sigue el 002
        00700229 GATO_PREMIUM-CS-VNR187CCX24    2
        00700682 MIS_RES_MS-CS-VNR750CCX6-CO    5
        Sub Total 11
    """
    filas: list[dict] = []
    camion = ""
    pallet_actual = ""
    descartadas = 0

    for linea in (texto or "").split("\n"):
        s = linea.strip()
        if not s:
            continue

        m = _RE_CAMION.search(s)
        if m:
            camion = m.group(1).strip()
            pallet_actual = ""
            continue

        # Cabecera de tabla o pie de pagina
        if s.startswith(("PALLET PRODUCTO", "Sub Total", "LOAD SUMMARY",
                         "TOTAL", "Control de Portería")):
            continue

        # Linea CON pallet (primera de cada pallet)
        m = _RE_PRODUCTO_CON_PALLET.match(s)
        if m and camion:
            pallet, sku, desc, cant = m.groups()
            pallet_actual = pallet
            filas.append({"camion": camion, "pallet": pallet, "sku": sku,
                          "descripcion": desc.strip(), "cantidad": int(cant)})
            continue

        # Linea SIN pallet (continuacion de un pallet mixto)
        m = _RE_PRODUCTO_SIN_PALLET.match(s)
        if m and camion and pallet_actual:
            sku, desc, cant = m.groups()
            filas.append({"camion": camion, "pallet": pallet_actual, "sku": sku,
                          "descripcion": desc.strip(), "cantidad": int(cant)})
            continue

        # Linea rara que parece dato pero no calza
        if re.match(r"^\d{3}\s+\d", s) or re.match(r"^\d{8}\s", s):
            descartadas += 1

    df = pd.DataFrame(filas, columns=["camion", "pallet", "sku",
                                      "descripcion", "cantidad"])
    return Sumario(
        dataframe=df,
        camiones=sorted(df["camion"].unique().tolist()) if len(df) else [],
        pallets=int(df[["camion", "pallet"]].drop_duplicates().shape[0]) if len(df) else 0,
        cajas=int(df["cantidad"].sum()) if len(df) else 0,
        descartadas=descartadas,
    )


def leer_pdf(ruta: str | Path) -> Sumario:
    """Lee el PDF del sumario de carga."""
    import pdfplumber

    partes = []
    with pdfplumber.open(str(ruta)) as pdf:
        for p in pdf.pages:
            partes.append(p.extract_text() or "")
    return leer_texto("\n".join(partes))


def cargar_desde_archivo(ruta: str | Path) -> Sumario:
    """Acepta .pdf o .txt (util para probar sin PDF)."""
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".pdf":
        return leer_pdf(ruta)
    return leer_texto(ruta.read_text(encoding="utf-8", errors="replace"))
