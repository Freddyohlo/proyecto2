"""Tests del informe de productividad de picking."""

from __future__ import annotations

from src import informe_picking as ip

# Fila completa (22 columnas) y fila con 'nivel_lpn' omitido (21 columnas)
FILA22 = ("2026\t10\t00\t01\t22/10/2026 00:00:00\t3028-NORPONIENTE\t52D-01\t1038\t"
          "22/10/2026-801666068-1038\tCD8000\tRecoger Sub-LPN\t\tLST000001973968\t"
          "AJMARTINH\t22/10/2026 00:19:28\t22/10/2026 00:27:01\t102\t6\t"
          "ANTONIO JAVIER MARTINEZ HUECHUCONA\tSAEP\tCD8000000014LYE\tZT PET MEDIANO")
FILA21 = FILA22.replace("\t\tLST000001973968", "\tLST000001973968")


def test_leer_tsv_normaliza_21_columnas():
    r = ip.leer_tsv(FILA21 + "\n")
    assert r.filas == 1
    assert r.anomalias == 1
    fila = r.dataframe.iloc[0]
    assert fila["usuario"] == "AJMARTINH"
    assert fila["cajas"] == "102"
    assert fila["zona_trabajo"] == "ZT PET MEDIANO"
    assert fila["nivel_lpn"] == ""


def test_leer_tsv_descarta_lineas_basura():
    r = ip.leer_tsv(FILA22 + "\n\nbasura\notra\tcosa\n")
    assert r.filas == 1
    assert r.descartadas == 2


def test_resumen_por_hora_agrupa_cajas_y_pickeadores():
    texto = "\n".join([FILA22, FILA21.replace("AJMARTINH", "ALESEUARA")])
    r = ip.leer_tsv(texto)
    resumen = ip.resumen_por_hora(r.dataframe)
    assert len(resumen) == 1
    fila = resumen.iloc[0]
    assert fila["hora"] == 0
    assert fila["cajas"] == 204
    assert fila["pickeadores"] == 2
    assert fila["viajes"] == 2
    assert fila["cajas_por_pickeador"] == 102.0


def test_proyectar_calcula_avance_y_termino():
    r = ip.leer_tsv("\n".join([FILA22] * 10))  # 1020 cajas en la hora 0
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=2040, hora_limite="07:00", hora_actual=0)
    assert proy.total_cajas == 1020
    assert proy.pct_avance == 50.0
    assert proy.tasa_actual == 1020.0
    assert proy.horas_restantes == 1.0
    assert proy.hora_termino == "01:00"
    assert proy.supera_limite is False


def test_proyectar_alerta_al_pasar_el_limite():
    r = ip.leer_tsv("\n".join([FILA22] * 5))  # 510 cajas en la hora 0
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=5100, hora_limite="07:00", hora_actual=6)
    # faltan 4590 a 510/hora -> 9 h -> 15:00, pasa el limite de 07:00
    assert proy.supera_limite is True
    assert proy.hora_termino == "15:00"


def test_proyectar_sin_meta_no_divide_por_cero():
    r = ip.leer_tsv(FILA22 + "\n")
    resumen = ip.resumen_por_hora(r.dataframe)
    proy = ip.proyectar(resumen, meta=0, hora_actual=0)
    assert proy.pct_avance == 0.0
