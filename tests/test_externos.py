"""Tests de las fuentes externas (TRUCK venta + SAP transito) y del contraste."""

from __future__ import annotations

from src import contraste as ct
from src import externos as ex
from src import inventario as inv

# --------------------------------------------------------------------------
# Muestras
# --------------------------------------------------------------------------

# Cuadratura con Detalle: 22 columnas. Cantidad = col 11.
def _fila_detalle(area, ubicacion, sku, cantidad, desc="PRODUCTO"):
    return "\t".join([
        "ZTPMOD", "ZSPCJ", "PT01", ubicacion, "Llena", "LPN1", "D0001",
        sku, sku, desc, str(cantidad), "0", "0",
        "08/07/2025 15:55:58", "23/05/2026 13:30:12", "22/11/2052 15:55:58",
        "", "Disponible", "9999", "9529", "05/10/2026 13:07:15", area,
    ])


DETALLE = "\n".join([
    _fila_detalle("AREA PICKING", "60-001", "000622", 10, "GASEOSA"),
    _fila_detalle("AREA ALMACENAMIENTO", "A-01", "000622", 100, "GASEOSA"),
    _fila_detalle("AREA PICKING", "60-002", "007266", 5, "JUGO"),
]) + "\n"


# CSV de TRUCK: separador ';', miles de filas vacias al final.
CABECERA_TRUCK = (
    "CD;PLANILLA;ESTADO;FECHA;TRANSPORTISTA;DESCRIPCION;CAMION;VIAJE;"
    "ZONA DE ENTRGA;DESCRIPCION;OFICINA;DESCRIPCION;PREVENTISTA;ID-CLIENTE;RUT;"
    "RAZON SOCIAL;CALLE;NUMERO;CIUDAD;COMUNA;TIPO FACTURA;DESCRIPCION;UEN;RSC;"
    "NRO-PED-REF;SEC-REG-REF;FORMULARIO;CATEGORIA;MARCA;TAMAÑO;PRODUCTO;"
    "DESCRIPCION;UNIDAD;CANTIDAD;PESO-CAJA;PESO TOTAL;% DESCUENTO;VALOR LINEA;"
    "MENSAJE FACTURA;MOT ANU;DESCRIPCION ANULACION;DIRECCION ALTERNATIVA;"
    "PLANILLA REFERENCIA;USUARIO EPV"
)


def _fila_truck(producto, cantidad, unidad="CJ", estado="ING", fecha="29/10/2026"):
    campos = [""] * 44
    campos[0] = "8"
    campos[1] = "801667860"
    campos[2] = estado
    campos[3] = fecha
    campos[13] = "2370547"
    campos[15] = "NEW-REST CHILE"
    campos[27] = "GASEOSAS"
    campos[28] = "LIMON SODA"
    campos[29] = "24 x 350 CC"
    campos[30] = producto
    campos[31] = "DESC PRODUCTO"
    campos[32] = unidad
    campos[33] = str(cantidad)
    return ";".join(campos)


TRUCK_CSV = "\n".join([
    CABECERA_TRUCK,
    _fila_truck("622", 50),
    _fila_truck("622", 30),
    _fila_truck("7266", 20, unidad="CU"),
    ";".join([""] * 44),   # fila vacia
    ";".join([""] * 44),
]) + "\n"


def _transito_df():
    """Arma el DataFrame que devolveria leer el Excel de SAP."""
    import pandas as pd
    filas = [
        {"Material": "000622", "Texto breve material": "GASEOSA",
         "Cantidad Entrega": "200", "Cantidad Pallet": "3",
         "OCA(Orden de Carga)": "1001373854", "Id.1 / OCA": "A000732387",
         "Nº de transporte": "101748285", "Centro Origen": "9051",
         "Centro Destino": "9018", "Fecha": "2026-10-29 00:00:00",
         "Clase de movimiento": "101", "Stat.global transp.": "6",
         "Grupo de artículos": "PT GASEOS", "Sociedad": "A007"},
        {"Material": "000900", "Texto breve material": "VINO",
         "Cantidad Entrega": "40", "Cantidad Pallet": "1",
         "OCA(Orden de Carga)": "1001373415", "Id.1 / OCA": "A000732050",
         "Nº de transporte": "101747751", "Centro Origen": "2313",
         "Centro Destino": "9018", "Fecha": "2026-10-29 00:00:00",
         "Clase de movimiento": "101", "Stat.global transp.": "6",
         "Grupo de artículos": "PT VINNAC", "Sociedad": "A023"},
    ]
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------
# Llave de cruce
# --------------------------------------------------------------------------

def test_clave_sku_quita_ceros_a_la_izquierda():
    assert ex.clave_sku("000622") == "622"
    assert ex.clave_sku("622") == "622"
    assert ex.clave_sku(" 000622 ") == "622"
    assert ex.clave_sku("") == ""
    assert ex.clave_sku(None) == ""
    assert ex.clave_sku("000") == "0"


# --------------------------------------------------------------------------
# Venta (TRUCK)
# --------------------------------------------------------------------------

def test_leer_venta_descarta_filas_vacias():
    v = ex.leer_venta(TRUCK_CSV)
    assert v.filas == 3
    assert v.descartadas == 2


def test_leer_venta_tipos_y_clave():
    v = ex.leer_venta(TRUCK_CSV)
    df = v.dataframe
    assert df["cantidad"].dtype == "int64"
    assert df.iloc[0]["sku"] == "622"
    assert df.iloc[0]["sku_clave"] == "622"
    assert df.iloc[0]["unidad"] == "CJ"


def test_venta_demanda_por_sku_agrupa():
    v = ex.leer_venta(TRUCK_CSV)
    d = v.demanda_por_sku().set_index("sku_clave")["cajas"].to_dict()
    assert d["622"] == 80      # 50 + 30
    assert d["7266"] == 20


def test_venta_guardar_y_cargar(tmp_path):
    v = ex.leer_venta(TRUCK_CSV)
    db = tmp_path / "t.sqlite"
    v.guardar(db)
    recargada = ex.Venta.cargar(db)
    assert len(recargada.dataframe) == 3


# --------------------------------------------------------------------------
# Transito (SAP)
# --------------------------------------------------------------------------

def test_leer_transito_columnas_y_clave(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _transito_df())
    t = ex.leer_transito(b"xlsx-falso")
    df = t.dataframe
    assert t.filas == 2
    assert df.iloc[0]["sku"] == "000622"
    assert df.iloc[0]["sku_clave"] == "622"
    assert df.iloc[0]["cantidad"] == 200
    assert df.iloc[0]["oca"] == "1001373854"


def test_transito_por_oca_y_en_camino(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _transito_df())
    t = ex.leer_transito(b"xlsx-falso")
    por_oca = t.por_oca().set_index("oca")["cajas"].to_dict()
    assert por_oca["1001373854"] == 200
    assert por_oca["1001373415"] == 40
    camino = t.en_camino_por_sku().set_index("sku_clave")["cajas"].to_dict()
    assert camino["622"] == 200


# --------------------------------------------------------------------------
# Contraste
# --------------------------------------------------------------------------

def test_contraste_detecta_quiebre_y_cobertura(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _transito_df())

    stock = inv.leer_detalle(DETALLE)
    venta = ex.leer_venta(TRUCK_CSV)
    transito = ex.leer_transito(b"xlsx-falso")

    c = ct.calcular(stock, venta, transito)
    fila = c.dataframe.set_index("sku")

    # 622: demanda 80, picking 10 + almacen 100 + transito 200 = 310 -> cubre
    assert fila.loc["622", "demanda"] == 80
    assert fila.loc["622", "picking"] == 10
    assert fila.loc["622", "almacen"] == 100
    assert fila.loc["622", "transito"] == 200
    assert bool(fila.loc["622", "cubre"]) is True

    # 7266: demanda 20, picking 5, sin almacen ni transito -> falta 15
    assert fila.loc["7266", "demanda"] == 20
    assert fila.loc["7266", "disponible"] == 5
    assert fila.loc["7266", "falta"] == 15
    assert bool(fila.loc["7266", "cubre"]) is False


def test_contraste_resumen(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: _transito_df())
    stock = inv.leer_detalle(DETALLE)
    c = ct.calcular(stock, ex.leer_venta(TRUCK_CSV), ex.leer_transito(b"x"))
    r = c.resumen()
    assert r["skus"] == 2
    assert r["demanda"] == 100          # 80 + 20
    assert r["falta"] == 15
    assert r["quiebres"] == 1
    assert r["pct_cubierto"] == 85.0


def test_contraste_sin_transito_ni_venta():
    stock = inv.leer_detalle(DETALLE)
    c = ct.calcular(stock, None, None)
    assert c.filas == 0
    assert c.resumen()["demanda"] == 0
    assert c.resumen()["pct_cubierto"] == 100.0


def test_contraste_sin_stock_lista_quiebres_totales():
    stock = inv.leer_detalle(DETALLE)
    venta = ex.leer_venta(TRUCK_CSV)
    c = ct.calcular(stock, venta, None)
    sin_stock = set(c.sin_stock["sku"])
    # 7266 tiene picking 5, asi que no es quiebre total; pero si hubiera un SKU
    # sin ninguna fila de stock apareceria aqui.
    assert "7266" not in sin_stock
