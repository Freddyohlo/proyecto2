"""Genera el HTML del Plan B (estado del inventario offline + reposicion)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import inventario as inv
from . import minmax as mm


def _tabla_reposicion(items: list[mm.NecesidadReposicion]) -> str:
    if not items:
        return "<p class='vacio'>Sin reposiciones pendientes (o no hay minimos cargados).</p>"
    filas = []
    for it in items:
        clase = "" if it.cubre else " class='alerta-fila'"
        marca = "" if it.cubre else " ⚠️"
        filas.append(
            f"<tr{clase}><td>{it.ubicacion}</td><td>{it.sku}</td>"
            f"<td>{it.descripcion[:40]}</td><td>{it.stock_actual}</td>"
            f"<td>{it.minimo}</td><td>{it.maximo}</td>"
            f"<td><b>{it.reponer}</b></td><td>{it.disponible_almacen}{marca}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Ubicación</th><th>SKU</th><th>Descripción</th>"
        "<th>Stock</th><th>Mín</th><th>Máx</th><th>Reponer</th>"
        "<th>Disp. almacén</th></tr></thead><tbody>"
        + "".join(filas) + "</tbody></table>"
    )


def generar(
    inventario: inv.Inventario,
    repos: list[mm.NecesidadReposicion],
    destino: str | Path,
    plantilla: str | Path = "templates/plan_b.html.j2",
) -> Path:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    df = inventario.dataframe
    por_area = (
        df.groupby("area")["cantidad"].agg(["count", "sum"]).reset_index()
        if not df.empty else None
    )
    total_cajas = int(df["cantidad"].sum()) if not df.empty else 0
    n_ubic = int(df["ubicacion"].nunique()) if not df.empty else 0
    n_sku = int(df["sku"].nunique()) if not df.empty else 0
    n_lotes = int(df["lpn"].nunique()) if not df.empty else 0

    areas = []
    if por_area is not None:
        for _, r in por_area.iterrows():
            areas.append({
                "area": r["area"],
                "ubicaciones": int(r["count"]),
                "cantidad": int(r["sum"]),
            })

    plantilla = Path(plantilla)
    env = Environment(
        loader=FileSystemLoader(str(plantilla.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template(plantilla.name)
    html = tmpl.render(
        total_cajas=total_cajas,
        n_ubic=n_ubic,
        n_sku=n_sku,
        n_lotes=n_lotes,
        areas=areas,
        n_repos=len(repos),
        n_repos_sin_cubrir=sum(1 for r in repos if not r.cubre),
        tabla_reposicion=_tabla_reposicion(repos),
        generado=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    destino.write_text(html, encoding="utf-8")
    return destino
