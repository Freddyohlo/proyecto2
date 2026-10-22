"""Informe de productividad de picking (pantalla 'CCU Caja Pickeada').

Lee el TSV capturado (una fila por viaje/trip) y lo agrupa por la **hora real de
trabajo**, usando `h_inicio` / `h_termino` (NO la columna `hora`).

¿Por qué `h_inicio` y no `hora`?  Porque el picking de un dia se trabaja con
turnos que cruzan la medianoche: hay pickeadores que entran el dia anterior
(ej. 21/10) para dejar listo el picking del dia 22/10. La columna `hora` no
distingue eso; `h_inicio` trae fecha y hora completas.

Calcula, por cada hora:
  - cajas pickeadas
  - pickeadores distintos
  - viajes
  - horas-hombre trabajadas (suma de h_termino - h_inicio)
  - cajas por hora-hombre

Y proyecta la hora estimada de termino respecto a una META (ingresada a mano).
Genera HTML (graficos SVG propios, sin dependencias) y un Excel basico.
"""

from __future__ import annotations

from dataclasses import dataclass
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

FORMATO_FECHA = "%d/%m/%Y %H:%M:%S"


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------
def _normalizar(celdas: list[str]) -> list[str]:
    """Ajusta una fila a 22 columnas.

    La grilla omite la celda vacia de 'nivel_lpn' al copiar, asi que una fila
    con 21 celdas se corrige insertando "" en esa posicion (indice 11).
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
    anomalias: int      # filas con numero de columnas != 22 (se normalizaron)
    sin_fechas: int     # filas sin h_inicio/h_termino validos


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
    if df.empty:
        return ResultadoLectura(df, 0, descartadas, anomalias, 0)

    df["cajas"] = pd.to_numeric(df["cajas"], errors="coerce").fillna(0).astype(int)
    df["inicio_dt"] = pd.to_datetime(df["h_inicio"], format=FORMATO_FECHA, errors="coerce")
    df["termino_dt"] = pd.to_datetime(df["h_termino"], format=FORMATO_FECHA, errors="coerce")

    # Duracion del viaje en horas (si termino < inicio, el turno cruzo medianoche: +1 dia)
    dur = (df["termino_dt"] - df["inicio_dt"]).dt.total_seconds() / 3600.0
    dur = dur.where(dur >= 0, dur + 24.0)
    df["duracion_h"] = dur.fillna(0).clip(lower=0)

    sin_fechas = int(df["inicio_dt"].isna().sum())
    df = df[df["inicio_dt"].notna()].copy()

    # Quien pickeo: usuario; si viene vacio, el nombre
    df["quien"] = df["usuario"].where(df["usuario"].astype(bool), df["descripcion"])
    # Hora real de trabajo, truncada a la hora (para agrupar)
    df["hora_ts"] = df["inicio_dt"].dt.floor("h")

    return ResultadoLectura(df, len(df), descartadas, anomalias, sin_fechas)


# --------------------------------------------------------------------------
# Agregacion por hora real
# --------------------------------------------------------------------------
def resumen_por_hora(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla por hora real de trabajo (segun h_inicio).

    Nota sobre la duracion: `h_termino - h_inicio` es la duracion de UN viaje/LPN,
    que puede ser de segundos. NO representa horas trabajadas, por eso se reporta
    solo como promedio por viaje (informativo), y las metricas de rendimiento son
    cajas por pickeador y cajas por viaje.
    """
    vacio = pd.DataFrame(columns=["hora_ts", "etiqueta", "cajas", "pickeadores",
                                  "viajes", "cajas_por_pickeador", "cajas_por_viaje",
                                  "min_por_viaje"])
    if df.empty:
        return vacio

    g = (
        df.groupby("hora_ts")
        .agg(
            cajas=("cajas", "sum"),
            pickeadores=("quien", "nunique"),
            viajes=("cajas", "size"),
            minutos=("duracion_h", "sum"),
        )
        .reset_index()
        .sort_values("hora_ts")
    )
    g["etiqueta"] = g["hora_ts"].dt.strftime("%d-%m %H:00")
    g["cajas_por_pickeador"] = (g["cajas"] / g["pickeadores"].replace(0, pd.NA)).round(1).fillna(0)
    g["cajas_por_viaje"] = (g["cajas"] / g["viajes"].replace(0, pd.NA)).round(1).fillna(0)
    g["min_por_viaje"] = (g["minutos"] * 60 / g["viajes"].replace(0, pd.NA)).round(1).fillna(0)
    return g[["hora_ts", "etiqueta", "cajas", "pickeadores", "viajes",
              "cajas_por_pickeador", "cajas_por_viaje", "min_por_viaje"]].reset_index(drop=True)


# --------------------------------------------------------------------------
# Proyeccion
# --------------------------------------------------------------------------
@dataclass
class Proyeccion:
    meta: int
    total_cajas: int
    pct_avance: float
    total_viajes: int
    cajas_por_viaje: float
    ultima_hora: str | None
    tasa_actual: float           # cajas/hora (promedio reciente)
    horas_restantes: float | None
    hora_termino: str | None     # "dd-mm HH:MM"
    alerta: str
    supera_limite: bool


def proyectar(
    resumen: pd.DataFrame,
    meta: int,
    hora_limite: str = "07:00",
    ventana_tasa: int = 3,
) -> Proyeccion:
    """Avance vs meta y hora estimada de termino.

    `ventana_tasa` = cuantas horas recientes (con actividad) usar para el ritmo.
    """
    total = int(resumen["cajas"].sum()) if not resumen.empty else 0
    viajes = int(resumen["viajes"].sum()) if not resumen.empty else 0
    pct = (total / meta * 100) if meta else 0.0
    cpv = round(total / viajes, 1) if viajes else 0.0

    ultima = None
    if not resumen.empty:
        ultima = resumen["hora_ts"].max().strftime("%d-%m %H:%M")

    activas = resumen[resumen["cajas"] > 0] if not resumen.empty else resumen
    # Ritmo: promedio de las ultimas horas CON ACTIVIDAD SIGNIFICATIVA.
    # Se descartan las horas de "cola" (limpieza/cierre) que tienen muy poco volumen
    # y distorsionarian la proyeccion.
    if not activas.empty:
        tope = activas["cajas"].max()
        significativas = activas[activas["cajas"] >= tope * 0.10]
        if significativas.empty:
            significativas = activas
        tasa = float(significativas["cajas"].tail(ventana_tasa).mean())
    else:
        tasa = 0.0

    horas_restantes = None
    hora_termino = None
    if meta and tasa > 0 and not resumen.empty:
        faltan = max(meta - total, 0)
        horas_restantes = faltan / tasa
        ultimo_dt = resumen["hora_ts"].max().to_pydatetime()
        fin = ultimo_dt + timedelta(hours=horas_restantes)
        hora_termino = fin.strftime("%d-%m %H:%M")

    lim_h, lim_m = (int(x) for x in hora_limite.split(":"))
    limite_min = lim_h * 60 + lim_m
    supera = False
    alerta = ""
    if total >= meta and meta:
        alerta = "✅ Meta alcanzada."
    elif hora_termino:
        hh_, mm_ = (int(x) for x in hora_termino.split(" ")[1].split(":"))
        if hh_ * 60 + mm_ > limite_min:
            supera = True
            alerta = (f"⚠️ Se proyecta terminar a las {hora_termino}, "
                      f"despues del limite de {hora_limite}. Se retiran pickeadores.")
        else:
            alerta = (f"✅ Proyeccion: termina a las {hora_termino} "
                      f"(dentro del limite {hora_limite}).")
    else:
        alerta = "Sin datos suficientes para proyectar."

    return Proyeccion(
        meta=meta, total_cajas=total, pct_avance=round(pct, 1),
        total_viajes=viajes, cajas_por_viaje=cpv,
        ultima_hora=ultima, tasa_actual=round(tasa, 1),
        horas_restantes=round(horas_restantes, 2) if horas_restantes is not None else None,
        hora_termino=hora_termino, alerta=alerta, supera_limite=supera,
    )


# --------------------------------------------------------------------------
# Graficos SVG (sin dependencias; funcionan offline)
# --------------------------------------------------------------------------
def _svg_barras(resumen: pd.DataFrame, ancho: int = 900, alto: int = 260) -> str:
    if resumen.empty:
        return "<p>Sin datos</p>"
    etiquetas = resumen["etiqueta"].tolist()
    vals = resumen["cajas"].tolist()
    maxv = max(vals) or 1
    n = len(etiquetas)
    m_izq, m_der, m_sup, m_inf = 52, 12, 18, 46
    w, h = ancho - m_izq - m_der, alto - m_sup - m_inf
    paso = w / n
    bw = paso * 0.68
    p = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
         f'xmlns="http://www.w3.org/2000/svg" role="img">']
    p.append(f'<line x1="{m_izq}" y1="{m_sup}" x2="{m_izq}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    p.append(f'<line x1="{m_izq}" y1="{m_sup+h}" x2="{m_izq+w}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    for i, (lab, v) in enumerate(zip(etiquetas, vals)):
        x = m_izq + i * paso + (paso - bw) / 2
        bh = (v / maxv) * h
        y = m_sup + h - bh
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'fill="#2563eb" rx="2"><title>{lab} — {v} cajas</title></rect>')
        if v:
            p.append(f'<text x="{x+bw/2:.1f}" y="{y-3:.1f}" font-size="9" '
                     f'text-anchor="middle" fill="#334155">{v}</text>')
        # etiqueta rotada si hay muchas horas
        rot = -60 if n > 10 else 0
        p.append(f'<text x="{x+bw/2:.1f}" y="{m_sup+h+14}" font-size="9" '
                 f'text-anchor="{"end" if rot else "middle"}" fill="#475569" '
                 f'transform="rotate({rot} {x+bw/2:.1f} {m_sup+h+14})">{lab}</text>')
    p.append("</svg>")
    return "".join(p)


def _svg_linea(resumen: pd.DataFrame, meta: int, ancho: int = 900, alto: int = 260) -> str:
    if resumen.empty:
        return "<p>Sin datos</p>"
    etiquetas = resumen["etiqueta"].tolist()
    acum = resumen["cajas"].cumsum().tolist()
    maxv = max(max(acum) if acum else 0, meta or 0) or 1
    n = len(etiquetas)
    m_izq, m_der, m_sup, m_inf = 52, 12, 18, 46
    w, h = ancho - m_izq - m_der, alto - m_sup - m_inf
    paso = w / max(n - 1, 1)

    def px(i): return m_izq + i * paso
    def py(v): return m_sup + h - (v / maxv) * h

    p = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" height="{alto}" '
         f'xmlns="http://www.w3.org/2000/svg" role="img">']
    p.append(f'<line x1="{m_izq}" y1="{m_sup}" x2="{m_izq}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    p.append(f'<line x1="{m_izq}" y1="{m_sup+h}" x2="{m_izq+w}" y2="{m_sup+h}" stroke="#cbd5e1"/>')
    if meta:
        ym = py(meta)
        p.append(f'<line x1="{m_izq}" y1="{ym:.1f}" x2="{m_izq+w}" y2="{ym:.1f}" '
                 f'stroke="#dc2626" stroke-dasharray="6 4"/>')
        p.append(f'<text x="{m_izq+w}" y="{ym-4:.1f}" font-size="10" text-anchor="end" '
                 f'fill="#dc2626">Meta {meta}</text>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(acum))
    p.append(f'<polyline points="{pts}" fill="none" stroke="#16a34a" stroke-width="2"/>')
    for i, v in enumerate(acum):
        p.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="2.5" fill="#16a34a"/>')
        p.append(f'<text x="{px(i):.1f}" y="{m_sup+h+14}" font-size="9" text-anchor="end" '
                 f'fill="#475569" transform="rotate(-60 {px(i):.1f} {m_sup+h+14})">{etiquetas[i]}</text>')
    p.append("</svg>")
    return "".join(p)


# --------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------
def tabla_para_mostrar(resumen: pd.DataFrame, meta: int) -> list[dict]:
    """Convierte el resumen en filas listas para la plantilla/consola."""
    filas = []
    acum = 0
    for _, r in resumen.iterrows():
        acum += int(r["cajas"])
        filas.append({
            "hora": r["etiqueta"],
            "cajas": int(r["cajas"]),
            "pickeadores": int(r["pickeadores"]),
            "viajes": int(r["viajes"]),
            "cajas_por_pickeador": r["cajas_por_pickeador"],
            "cajas_por_viaje": r["cajas_por_viaje"],
            "acumulado": acum,
            "pct": round(acum / meta * 100, 1) if meta else 0,
        })
    return filas


def generar_excel(resumen: pd.DataFrame, proy: Proyeccion, meta: int, destino: str | Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabla = pd.DataFrame(tabla_para_mostrar(resumen, meta))
    with pd.ExcelWriter(destino, engine="openpyxl") as xw:
        tabla.to_excel(xw, sheet_name="Por hora", index=False)
        pd.DataFrame([
            {"indicador": "Meta (manual)", "valor": proy.meta},
            {"indicador": "Total pickeado", "valor": proy.total_cajas},
            {"indicador": "% avance", "valor": proy.pct_avance},
            {"indicador": "Viajes totales", "valor": proy.total_viajes},
            {"indicador": "Cajas por viaje", "valor": proy.cajas_por_viaje},
            {"indicador": "Ritmo (cajas/hora)", "valor": proy.tasa_actual},
            {"indicador": "Hora estimada termino", "valor": proy.hora_termino or "-"},
            {"indicador": "Alerta", "valor": proy.alerta},
        ]).to_excel(xw, sheet_name="Resumen", index=False)
    return destino


def generar_html(
    resumen: pd.DataFrame,
    proy: Proyeccion,
    meta: int,
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

    html = tmpl.render(
        titulo=titulo, fecha=fecha, proy=proy, meta=meta,
        filas=tabla_para_mostrar(resumen, meta),
        svg_barras=_svg_barras(resumen),
        svg_linea=_svg_linea(resumen, meta),
        generado=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    destino.write_text(html, encoding="utf-8")
    return destino
