from src.config import Columna, Reporte
from src.parser import parsear_texto

COLUMNAS = [
    Columna("planta", "Planta"),
    Columna("ubicacion", "Ubicacion"),
    Columna("sku", "SKU"),
    Columna("descripcion", "Descripcion"),
    Columna("cantidad", "Cantidad", tipo="numero"),
    Columna("estado", "Estado"),
    Columna("flag", "Flag"),
    Columna("area", "Area"),
]

TSV = (
    "PT01\t60-267\t856473\tPROD A\t33\tDisponible\t1\tAREA VALORADO\n"
    "PT01\t60-268\t856473\tPROD A\t12\tDisponible\t1\tAREA VALORADO\n"
)


def test_parsea_tsv_basico():
    r = parsear_texto(TSV, COLUMNAS)
    assert r.filas_validas == 2
    assert r.filas_descartadas == 0
    assert list(r.dataframe.columns) == [c.clave for c in COLUMNAS]


def test_convierte_columna_numerica():
    r = parsear_texto(TSV, COLUMNAS)
    assert r.dataframe["cantidad"].sum() == 45
    assert r.dataframe["cantidad"].dtype.kind in "iu"


def test_ignora_lineas_cortas():
    texto = TSV + "TOTAL\t\t\t\t45\n"
    r = parsear_texto(texto, COLUMNAS)
    assert r.filas_validas == 2
    assert r.filas_descartadas == 1


def test_salta_encabezado():
    texto = "Planta\tUbicacion\tSKU\tDesc\tCant\tEstado\tFlag\tArea\n" + TSV
    r = parsear_texto(texto, COLUMNAS, Reporte(saltar_encabezado=1))
    assert r.filas_validas == 2


def test_ignorar_si_contiene():
    texto = TSV + "PT01\t60-269\t999\tPROD B\t5\tDisponible\t1\tAREA VALORADO\n"
    rep = Reporte(ignorar_si_contiene={"sku": ["999"]})
    r = parsear_texto(texto, COLUMNAS, rep)
    assert r.filas_validas == 2
    assert r.filas_descartadas == 1


def test_lineas_vacias_se_ignoran():
    r = parsear_texto("\n" + TSV + "\n\n", COLUMNAS)
    assert r.filas_validas == 2
    assert r.filas_descartadas == 0


def test_quita_espacios_de_relleno():
    # La grilla copia con espacios de relleno en las celdas.
    texto = "PT01\t  60-267  \t856473\t C MOLINA-CS VNR750-CO \t 33 \tDisponible\t1\tAREA VALORADO\n"
    r = parsear_texto(texto, COLUMNAS)
    fila = r.dataframe.iloc[0]
    assert fila["ubicacion"] == "60-267"
    assert fila["descripcion"] == "C MOLINA-CS VNR750-CO"
    assert fila["cantidad"] == 33
