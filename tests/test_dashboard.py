from pathlib import Path

from src import dashboard
from src.config import Columna, Config, Reporte
from src.parser import parsear_texto

COLUMNAS = [
    Columna("planta", "Planta"),
    Columna("cantidad", "Cantidad", tipo="numero"),
]

TSV = (
    "PT01\t33\n"
    "PT01\t12\n"
    "PT02\t50\n"
    "PT02\t7\n"
)


def _cfg() -> Config:
    cfg = Config()
    cfg.columnas = COLUMNAS
    cfg.reporte = Reporte(
        titulo="Reporte de prueba",
        agrupar_por="planta",
        totalizar="cantidad",
    )
    return cfg


def test_genera_html_con_totales(tmp_path: Path):
    r = parsear_texto(TSV, COLUMNAS)
    salida = dashboard.generar(r.dataframe, _cfg(), tmp_path / "out.html")
    html = salida.read_text(encoding="utf-8")

    assert "Reporte de prueba" in html
    assert "102" in html          # total general
    assert "PT01" in html and "PT02" in html
    assert "45" in html and "57" in html  # subtotales por grupo


def test_grupos_ordenados_por_total(tmp_path: Path):
    r = parsear_texto(TSV, COLUMNAS)
    salida = dashboard.generar(r.dataframe, _cfg(), tmp_path / "out.html")
    html = salida.read_text(encoding="utf-8")
    # PT02 (57) debe aparecer antes que PT01 (45) en la tabla de resumen
    assert html.index("PT02") < html.index("PT01")
