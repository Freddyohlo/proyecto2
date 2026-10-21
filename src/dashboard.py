"""Generacion del dashboard HTML a partir del DataFrame."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _resumen(df: pd.DataFrame, cfg: Config) -> dict:
    rep = cfg.reporte
    resumen: dict = {"total_filas": len(df)}

    if rep.totalizar and rep.totalizar in df.columns:
        resumen["total"] = float(df[rep.totalizar].sum(skipna=True))

    if rep.agrupar_por and rep.agrupar_por in df.columns:
        grp = df.groupby(rep.agrupar_por)
        filas = []
        for nombre, sub in grp:
            item = {"grupo": nombre, "cantidad_filas": len(sub)}
            if rep.totalizar and rep.totalizar in sub.columns:
                item["total"] = float(sub[rep.totalizar].sum(skipna=True))
            filas.append(item)
        filas.sort(key=lambda x: x.get("total", x["cantidad_filas"]), reverse=True)
        resumen["grupos"] = filas
        resumen["agrupar_titulo"] = next(
            (c.titulo for c in cfg.columnas if c.clave == rep.agrupar_por),
            rep.agrupar_por,
        )

    return resumen


def generar(df: pd.DataFrame, cfg: Config, salida: str | Path) -> Path:
    salida = Path(salida)
    salida.parent.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    plantilla = env.get_template("dashboard.html.j2")

    contexto = {
        "titulo": cfg.reporte.titulo,
        "fecha": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "columnas": [{"clave": c.clave, "titulo": c.titulo} for c in cfg.columnas],
        "filas": df.to_dict(orient="records"),
        "resumen": _resumen(df, cfg),
        "filas_preview": min(len(df), 200),
    }

    salida.write_text(plantilla.render(**contexto), encoding="utf-8")
    return salida
