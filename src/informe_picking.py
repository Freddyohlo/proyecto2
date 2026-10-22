"""Informe de productividad de picking (pantalla 'CCU Caja Pickeada').

Lee el TSV capturado (una fila por viaje/trip), lo agrupa por hora y calcula:
  - cajas pickeadas por hora
  - numero de pickeadores distintos por hora
  - rendimiento (cajas por pickeador)
  - acumulado y % de avance respecto a la META (ingresada a mano)
  - proyeccion de la hora de termino

Genera HTML (con graficos SVG, sin dependencias externas) y un Excel basico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Columnas reales de la grilla 'CCU Caja Pickeada' (en orden)
COLUMNAS = [
    "anio", "mes", "hora", "trip_number", "fecha_oc", "tipo_pedido", "num_oc",
    "num_departamento", "num_lote", "id_almacen", "tipo_trabajo", "nivel_lpn",
    "id_lista", "usuario", "h_inicio", "h_termino", "cajas", "lineas",
    "descripcion", "empresa", "lpn", "zona_trabajo",
]

# auto_id del pane que trae la fecha (para captura)
PANE_DESDE = "fecha_desde"
PANE_HASTA = "fecha_hasta"


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------
def _normalizar(celdas: list[str]) -> list[str]:
    """Ajusta una fila a 22 columnas.

    La grilla omite la celda vacia de 'nivel_lpn' al copiar, asi que una fila
    con 21 celdas se corrige insertando "" en esa posicion.
    """
    n = len(COLUMNAS)
    if len(celdas) == n:
        return celdas
    if len(celdas) == n - 1:
        return celdas[:11] + [""] + celdas[11:]
    return (celdas + [""] * n)[:n]


@dataclass
class ResultadoLectura:
    dataframe: pd.DataFrame
    filas: int
    descartadas: int
    anomalias: int  # filas cuyo numero de columnas no era 22 (se normalizaron)


def leer_tsv(texto: str) -> ResultadoLectura:
    registros: list[list[str]] = []
    descartadas = 0
    anomalias = 0
    for ln in texto.splitlines():
        if not ln.strip():
            continue
        celdas = [c.strip() for c in ln.split("\t")]
        if len(celdas) < 18:  # menos que lo minimo razonable -> basura
            descartadas += 1
            continue
        if len(celdas) != len(COLUMNAS):
            anomalias += 1
        registros.append(_normalizar(celdas))
    df = pd.DataFrame(registros, columns=COLUMNAS)
    return ResultadoLectura(df, len(df), descartadas, anomalias)


# --------------------------------------------------------------------------
# Agregacion por hora
# --------------------------------------------------------------------------
def resumen_por_hora(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una tabla por hora con cajas, pickeadores y rendimiento."""
    if df.empty:
        return pd.DataFrame(columns=["hora", "cajas", "pickeadores", "viajes", "cajas_por_pickeador"])

    d = df.copy()
    d["cajas"] = pd.to_numeric(d["cajas"], errors="coerce").fillna(0).astype(int)
    d["hora_num"] = pd.to_numeric(d["hora"], errors="coerce")
    d = d[d["hora_num"].notna()]
    d["hora_num"] = d["hora_num"].astype(int)

    # Usamos el usuario; si viene vacio, caemos al nombre (descripcion)
    d["quien"] = d["usuario"].where(d["usuario"].astype(bool), d["descripcion"])

    g = (
        d.groupby("hora_num")
        .agg(cajas=("cajas", "sum"), pickeadores=("quien", "nunique"), viajes=("cajas", "size"))
        .reset_index()
        .rename(columns={"hora_num": "hora"})
        .sort_values("hora")
    )
    g["cajas_por_pickeador"] = (
        g["cajas"] / g["pickeadores"].replace(0, pd.NA)
    ).round(1).fillna(0)
    return g.reset_index(drop=True)


@dataclass
class Proyeccion:
    meta: int
    total_cajas: int
    pct_avance: float
    hora_actual: int | None
    tasa_actual: float          # cajas/hora (promedio reciente)
    horas_restantes: float | None
    hora_termino: str | None    # "HH:MM"
    alerta: str                 # mensaje para mostrar
    supera_limite: bool


def proyectar(
    resumen: pd.DataFrame,
    meta: int,
    hora_limite: str = "07:00",
    hora_actual: int | None = None,
    ventana_tasa: int = 3,
) -> Proyeccion:
    """Calcula el avance y la hora estimada de termino.

    `ventana_tasa` = cuantas horas recientes usar para estimar el ritmo.
    """
    total = int(resumen["cajas"].sum()) if not resumen.empty else 0
    pct = (total / meta * 100) if meta else 0.0

    if hora_actual is None:
        hora_actual = int(resumen["hora"].max()) if not resumen.empty else None

    # Ritmo: promedio de las ultimas `ventana_tasa` horas CON actividad
    activas = resumen[resumen["cajas"] > 0]
    tasa = float(activas["cajas"].tail(ventana_tasa).mean()) if not activas.empty else 0.0

    horas_restantes = None
    hora_termino = None
    if meta and tasa > 0:
        faltan = max(meta - total, 0)
        horas_restantes = faltan / tasa
        if hora_actual is not None:
            fin = datetime(2000, 1, 1, hora_actual) + timedelta(hours=horas_restantes)
            hora_termino = fin.strftime("%H:%M")

    lim_h, lim_m = (int(x) for x in hora_limite.split(":"))
    limite_min = lim_h * 60 + lim_m
    supera = False
    alerta = ""
    if hora_termino:
        fh, fm = (int(x) for x in hora_termino.split(":"))
        # si termina al dia siguiente (>=24h), lo marcamos
        if fh >= 24:
            supera = True
            alerta = f"⚠️ Se proyecta terminar DESPUES de medianoche ({hora_termino})."
        elif fh * 60 + fm > limite_min:
            supera = True
            alerta = (f"⚠️ Se proyecta terminar a las {hora_termino}, "
                      f"despues del limite de {hora_limite}. Se retiran pickeadores.")
        else:
            alerta = f"✅ Proyeccion: termina a las {hora_termino} (dentro del limite {hora_limite})."
    elif total >= meta:
        alerta = "✅ Meta alcanzada."

    return Proyeccion(
        meta=meta, total_cajas=total, pct_avance=round(pct, 1),
        hora_actual=hora_actual, tasa_actual=round(tasa, 1),
        horas_restantes=round(horas_restantes, 2) if horas_restantes is not None else None,
        hora_termino=hora_termino, alerta=alerta, supera_limite=supera,
    )


# --------------------------------------------------------------------------
# Graficos SVG (sin dependencias; funcionan offline)
# --------------------------------------------------------------------------
def _svg_barras(resumen: pd.DataFrame, ancho: int = 720, alto: int = 240) -> str:
    if resumen.empty:
        return "<p>Sin datos</p>"
    horas = resumen["hora"].tolist()
    vals = resumen["cajas"].tolist()
    maxv = max(vals) or 1
    n = len(horas)
    m_izq, m_der, m_sup, m_inf = 46, 12, 16, 34
    w = ancho - m_izq - m_der
    h = alto - m_sup - m_inf
    bw = w / n * 0.7
    paso = w / n
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
              f'xmlns="http://www.w3.org/2000/svg" role="img">']
    # ejes
    partes.append(f'<line x1="{m_izq}" y1="{m_sup}" x2="{m_izq}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    partes.append(f'<line x1="{m_izq}" y1="{m_sup+h}" x2="{m_izq+w}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    for i, (hh, v) in enumerate(zip(horas, vals)):
        x = m_izq + i * paso + (paso - bw) / 2
        bh = (v / maxv) * h
        y = m_sup + h - bh
        partes.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                      f'fill="#2563eb" rx="2"><title>{hh:02d}:00 — {v} cajas</title></rect>')
        partes.append(f'<text x="{x+bw/2:.1f}" y="{m_sup+h+14}" font-size="10" '
                      f'text-anchor="middle" fill="#475569">{hh:02d}</text>')
        if v:
            partes.append(f'<text x="{x+bw/2:.1f}" y="{y-3:.1f}" font-size="9" '
                          f'text-anchor="middle" fill="#334155">{v}</text>')
    partes.append(f'<text x="{m_izq-6}" y="{m_sup+8}" font-size="10" text-anchor="end" '
                  f'fill="#475569">{maxv}</text>')
    partes.append("</svg>")
    return "".join(partes)


def _svg_linea(resumen: pd.DataFrame, meta: int, ancho: int = 720, alto: int = 240) -> str:
    if resumen.empty:
        return "<p>Sin datos</p>"
    horas = resumen["hora"].tolist()
    acum = resumen["cajas"].cumsum().tolist()
    maxv = max(max(acum) if acum else 0, meta or 0) or 1
    n = len(horas)
    m_izq, m_der, m_sup, m_inf = 46, 12, 16, 34
    w = ancho - m_izq - m_der
    h = alto - m_sup - m_inf
    paso = w / max(n - 1, 1)

    def px(i): return m_izq + i * paso
    def py(v): return m_sup + h - (v / maxv) * h

    partes = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
              f'xmlns="http://www.w3.org/2000/svg" role="img">']
    partes.append(f'<line x1="{m_izq}" y1="{m_sup}" x2="{m_izq}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    partes.append(f'<line x1="{m_izq}" y1="{m_sup+h}" x2="{m_izq+w}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    if meta:
        ym = py(meta)
        partes.append(f'<line x1="{m_izq}" y1="{ym:.1f}" x2="{m_izq+w}" y2="{ym:.1f}" '
                      f'stroke="#dc2626" stroke-dasharray="6 4"/>')
        partes.append(f'<text x="{m_izq+w}" y="{ym-4:.1f}" font-size="10" text-anchor="end" '
                      f'fill="#dc2626">Meta {meta}</text>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(acum))
    partes.append(f'<polyline points="{pts}" fill="none" stroke="#16a34a" stroke-width="2"/>')
    for i, v in enumerate(acum):
        partes.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="2.5" fill="#16a34a"/>')
        partes.append(f'<text x="{px(i):.1f}" y="{m_sup+h+14}" font-size="10" '
                      f'text-anchor="middle" fill="#475569">{horas[i]:02d}</text>')
    partes.append("</svg>")
    return "".join(partes)


# --------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------
def generar_excel(resumen: pd.DataFrame, proy: Proyeccion, destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabla = resumen.copy()
    tabla["acumulado"] = tabla["cajas"].cumsum()
    if proy.meta:
        tabla["pct_meta"] = (tabla["acumulado"] / proy.meta * 100).round(1)
    with pd.ExcelWriter(destino, engine="openpyxl") as xw:
        tabla.to_excel(xw, sheet_name="Por hora", index=False)
        pd.DataFrame([
            {"indicador": "Meta (manual)", "valor": proy.meta},
            {"indicador": "Total pickeado", "valor": proy.total_cajas},
            {"indicador": "% avance", "valor": proy.pct_avance},
            {"indicador": "Ritmo (cajas/hora)", "valor": proy.tasa_actual},
            {"indicador": "Hora estimada termino", "valor": proy.hora_termino or "-"},
            {"indicador": "Alerta", "valor": proy.alerta},
        ]).to_excel(xw, sheet_name="Resumen", index=False)
    return destino


def generar_html(
    resumen: pd.DataFrame,
    proy: Proyeccion,
    titulo: str,
    fecha: str,
    destino: str | Path,
    plantilla: str | Path = "templates/informe_picking.html.j2",
) -> Path:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    plantilla = Path(plantilla)
    env = Environment(
        loader=FileSystemLoader(str(plantilla.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template(plantilla.name)

    filas = []
    acum = 0
    for _, r in resumen.iterrows():
        acum += int(r["cajas"])
        filas.append({
            "hora": f"{int(r['hora']):02d}:00",
            "cajas": int(r["cajas"]),
            "pickeadores": int(r["pickeadores"]),
            "cajas_por_pickeador": r["cajas_por_pickeador"],
            "viajes": int(r["viajes"]),
            "acumulado": acum,
            "pct": round(acum / proy.meta * 100, 1) if proy.meta else 0,
        })

    html = tmpl.render(
        titulo=titulo,
        fecha=fecha,
        proy=proy,
        filas=filas,
        svg_barras=_svg_barras(resumen),
        svg_linea=_svg_linea(resumen, proy.meta),
        generado=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    destino.write_text(html, encoding="utf-8")
    return destino
