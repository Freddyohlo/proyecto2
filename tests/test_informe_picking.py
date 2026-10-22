"""Tests del informe de productividad de picking."""

from __future__ import annotations

from src import informe_picking as ip

# Fila completa (22 columnas). h_inicio 22/10 00:19, h_termino 00:27 (~0.13 h)
FILA22 = ("2026\t10\t00\t01\t22/10/2026 00:00:00\t3028-NORPONIENTE\t52D-01\t1038\t"
          "22/10/2026-801666068-1038\tCD8000\tRecoger Sub-LPN\t\tLST000001973968\t"
          "AJMARTINH\t22/10/2026 00:19:28\t22/10/2026 00:27:01\t102\t6\t"
          "ANTONIO JAVIER MARTINEZ HUECHUCONA\tSAEP\tCD8000000014LYE\tZT PET MEDIANO")
FILA21 = FILA22.replace("\t\tLST000001973968", "\tLST000001973968")


def _fila(usuario: str, inicio: str, termino: str, cajas: int) -> str:
    f = FILA22.split("\t")
    f[13] = usuario
    f[14] = inicio
    f[15] = termino
    f[16] = str(cajas)
    return "\t".join(f)


def test_leer_tsv_normaliza_21_columnas():
    r = ip.leer_tsv(FILA21 + "\n")
    assert r.filas == 1
    assert r.anomalias == 1
    fila = r.dataframe.iloc[0]
    assert fila["usuario"] == "AJMARTINH"
    assert fila["cajas"] == 102
    assert fila["nivel_lpn"] == ""
    assert fila["zona_trabajo"] == "ZT PET MEDIANO"


def test_leer_tsv_descarta_lineas_basura():
    r = ip.leer_tsv(FILA22 + "\n\nbasura\notra\tcosa\n")
    assert r.filas == 1
    assert r.descartadas == 2


def test_usa_h_inicio_y_no_la_columna_hora():
    # Columna 'hora' = 00, pero h_inicio es la 05:xx del dia anterior (turno que cruza)
    fila = _fila("PICKER1", "21/10/2026 23:30:00", "22/10/2026 00:10:00", 50)
    r = ip.leer_tsv(fila + "\n")
    resumen = ip.resumen_por_hora(r.dataframe)
    assert len(resumen) == 1
    # Debe agrupar por el 21-10 23:00 (h_inicio), no por la hora 00
    assert resumen.iloc[0]["etiqueta"] == "21-10 23:00"
    assert resumen.iloc[0]["cajas"] == 50


def test_duracion_cruza_medianoche():
    fila = _fila("PICKER1", "21/10/2026 23:30:00", "22/10/2026 00:10:00", 50)
    r = ip.leer_tsv(fila + "\n")
    dur = r.dataframe.iloc[0]["duracion_h"]
    assert abs(dur - (40 / 60)) < 0.01  # 40 minutos


def test_resumen_por_hora_cajas_pickeadores_y_horas_hombre():
    # Misma hora (00:00-00:59), dos pickeadores, cada viaje de 30 min
    t = "\n".join([
        _fila("AJMARTINH", "22/10/2026 00:00:00", "22/10/2026 00:30:00", 100),
        _fila("ALESEUARA", "22/10/2026 00:10:00", "22/10/2026 00:40:00", 104),
    ])
    r = ip.leer_tsv(t)
    resumen = ip.resumen_por_hora(r.dataframe)
    fila = resumen.iloc[0]
    assert fila["cajas"] == 204
    assert fila["pickeadores"] == 2
    assert fila["viajes"] == 2
    assert abs(fila["horas_hombre"] - 1.0) < 0.01     # 0.5 + 0.5
    assert abs(fila["cajas_por_hora_hombre"] - 204.0) < 0.1


def test_proyectar_avance_y_termino():
    t = "\n".join([_fila("A", "22/10/2026 00:00:00", "22/10/2026 01:00:00", 1000)])
    r = ip.leer_tsv(t)
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=2000, hora_limite="07:00")
    assert proy.total_cajas == 1000
    assert proy.pct_avance == 50.0
    assert proy.tasa_actual == 1000.0
    assert proy.horas_restantes == 1.0
    assert proy.hora_termino == "22-10 01:00"
    assert proy.supera_limite is False


def test_proyectar_alerta_al_pasar_el_limite():
    t = "\n".join([_fila("A", "22/10/2026 06:00:00", "22/10/2026 07:00:00", 500)])
    r = ip.leer_tsv(t)
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=5000, hora_limite="07:00")
    # faltan 4500 a 500/hora -> 9 h desde las 06:00 -> 15:00
    assert proy.supera_limite is True
    assert proy.hora_termino == "22-10 15:00"


def test_proyectar_sin_meta_no_divide_por_cero():
    r = ip.leer_tsv(FILA22 + "\n")
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=0)
    assert proy.pct_avance == 0.0


def test_filas_sin_fecha_se_cuentan_y_descartan():
    fila_mala = FILA22.split("\t")
    fila_mala[14] = ""   # h_inicio vacio
    fila_mala[15] = ""
    r = ip.leer_tsv(FILA22 + "\n" + "\t".join(fila_mala) + "\n")
    assert r.sin_fechas == 1
    assert r.filas == 1
