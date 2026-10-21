"""Parseo de los datos copiados desde la grilla de Blue Yonder.

La grilla se copia con Ctrl+A / Ctrl+C y queda en el portapapeles en formato
TSV (valores separados por tabulaciones), con una fila por linea.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Columna, Reporte


@dataclass
class ResultadoParseo:
    dataframe: pd.DataFrame
    filas_validas: int
    filas_descartadas: int


def parsear_texto(
    texto: str,
    columnas: list[Columna],
    reporte: Reporte | None = None,
) -> ResultadoParseo:
    """Convierte el texto TSV del portapapeles en un DataFrame limpio."""
    lineas = [ln for ln in texto.splitlines() if ln.strip() != ""]

    saltar = reporte.saltar_encabezado if reporte else 0
    if saltar:
        lineas = lineas[saltar:]

    ignorar = reporte.ignorar_si_contiene if reporte else {}
    claves = [c.clave for c in columnas]

    registros: list[list[str]] = []
    descartadas = 0
    ncols = len(columnas)

    for ln in lineas:
        celdas = ln.split("\t")
        # Una fila valida debe tener al menos tantas celdas como columnas definidas.
        if len(celdas) < ncols:
            descartadas += 1
            continue
        # Las celdas copiadas de la grilla traen espacios de relleno.
        fila = [c.strip() for c in celdas[:ncols]]
        valores = dict(zip(claves, fila))
        if any(
            patron.lower() in str(valores.get(col, "")).lower()
            for col, patrones in ignorar.items()
            for patron in patrones
        ):
            descartadas += 1
            continue
        registros.append(fila)

    df = pd.DataFrame(registros, columns=claves)

    for col in columnas:
        if col.tipo == "numero":
            df[col.clave] = pd.to_numeric(df[col.clave], errors="coerce")

    return ResultadoParseo(
        dataframe=df,
        filas_validas=len(df),
        filas_descartadas=descartadas,
    )


def parsear_portapapeles(columnas: list[Columna]) -> ResultadoParseo:
    """Lee el portapapeles (Windows) y lo parsea."""
    import pyperclip

    return parsear_texto(pyperclip.paste(), columnas)
