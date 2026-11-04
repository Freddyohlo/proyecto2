"""Lector de codigos GS1-128 (el codigo de barras de la tarja).

La tarja de CCU usa GS1-128: el codigo de barras no trae solo el LPN, trae
VARIOS datos juntos, cada uno marcado con un "Application Identifier" (AI).
Al escanear, el sistema puede llenar solo el SKU, la cantidad y las fechas.

Estructura:  (AI)(valor)(AI)(valor)...
Ejemplo:     (00)278043001201264701(17)270604(11)261031(30)198

Los AIs vienen en tres sabores:
  - Fijos:   longitud conocida -> se leen los N digitos y listo.
  - Variables: longitud variable -> terminan en un separador (FNC1) o cuando
    empieza el siguiente AI.

Referencia: GS1 General Specifications (lista de Application Identifiers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

# Separador FNC1. La mayoria de los lectores lo mandan como GS (\x1d, ASCII 29);
# algunos como GS1 o como '|'. Se toleran todos.
SEPARADORES = ("\x1d", "\x1e", "\x04", "|", "\n", "\r")

# AIs de longitud FIJA: codigo -> cuantos caracteres ocupa el valor.
AI_FIJOS = {
    "00": 18,   # SSCC (el LPN del pallet)
    "01": 14,   # GTIN (el producto, en formato GTIN)
    "02": 14,   # GTIN de los articulos contenidos
    "03": 14,   # GTIN de un articulo hecho a pedido
    "11": 6,    # fecha de elaboracion/produccion (YYMMDD)
    "12": 6,    # fecha de vencimiento del pago
    "13": 6,    # fecha de empaque (YYMMDD)
    "15": 6,    # consumir preferentemente antes de (YYMMDD)
    "16": 6,    # fecha de venta preferente (YYMMDD)
    "17": 6,    # FECHA DE VENCIMIENTO (YYMMDD)
    "20": 2,    # variante del producto
    "31": 6, "32": 6, "33": 6, "34": 6, "35": 6, "36": 6,
}

# AIs de longitud VARIABLE: se leen hasta el separador o hasta el proximo AI.
AI_VARIABLES = {
    "10",   # lote
    "21",   # numero de serie
    "22",   # datos secundarios
    "30",   # cantidad de unidades (cajas)  <- el "CAJAS REALES"
    "37",   # cantidad de articulos contenidos
    "240", "241", "242", "243", "250", "251", "253", "254", "255",
    "400", "401", "402", "403", "410", "411", "412", "413", "414",
    "420", "421", "422", "423", "424",
    "7001", "7002", "7003", "7004", "7005", "7006", "7007", "7008", "7009",
    "7010", "7020", "7021", "7022", "7023",
    "8001", "8002", "8003", "8004", "8005", "8006", "8007", "8008",
    "8018", "8020",
    "90", "91", "92", "93", "94", "95", "96", "97", "98", "99",
}

# AIs que pueden INICIAR un dato en una tarja de bodega. Se usan para decidir
# donde corta un valor variable cuando el lector NO manda el separador FNC1.
#
# OJO: los internos 90-99 NO estan aca a proposito. Si se aceptaran como corte,
# un valor como "198" se partiria en "1" + AI(98), que es un error real que ya
# nos paso (la cantidad salia 1 en vez de 198).
AI_CORTE = {
    "00", "01", "02", "03",
    "10", "11", "13", "15", "16", "17", "20", "21",
    "30", "37",
    "240", "241", "250",
}

# AIs de 4 digitos que empiezan con 3 y llevan 6 digitos de valor
# (pesos y medidas: 310n..369n). Se reconocen por prefijo.
PREFIJOS_FIJOS_4 = ("310", "311", "312", "313", "314", "315", "316", "320",
                    "321", "322", "323", "324", "325", "326", "327", "328",
                    "329", "330", "331", "332", "333", "334", "335", "336",
                    "340", "341", "342", "343", "344", "345", "346", "347",
                    "348", "349", "350", "351", "352", "353", "354", "355",
                    "356", "357", "360", "361", "362", "363", "364", "365",
                    "366", "367", "368", "369")

# Nombres legibles de los AIs que nos importan
NOMBRES = {
    "00": "sscc",
    "01": "gtin",
    "02": "gtin_contenido",
    "10": "lote",
    "11": "fecha_elaboracion",
    "13": "fecha_empaque",
    "15": "fecha_consumir_antes",
    "16": "fecha_venta",
    "17": "fecha_vencimiento",
    "20": "variante",
    "21": "serie",
    "30": "cantidad",
    "37": "cantidad_contenida",
    "240": "id_adicional",
    "241": "nro_parte_cliente",
    "250": "serie_secundaria",
    "90": "interno_90",
    "91": "interno_91",
    "92": "interno_92",
    "93": "interno_93",
    "94": "interno_94",
    "95": "interno_95",
    "96": "interno_96",
    "97": "interno_97",
    "98": "interno_98",
    "99": "interno_99",
}


@dataclass
class EscaneoGS1:
    """Resultado de parsear un codigo GS1-128."""
    crudo: str = ""
    valores: dict[str, str] = field(default_factory=dict)   # ai -> valor crudo
    no_reconocidos: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Campos ya interpretados
    # ------------------------------------------------------------------
    @property
    def sscc(self) -> str:
        return self.valores.get("00", "")

    @property
    def gtin(self) -> str:
        return self.valores.get("01", "") or self.valores.get("02", "")

    @property
    def lote(self) -> str:
        return self.valores.get("10", "")

    @property
    def cantidad(self) -> int:
        """Cajas (AI 30 o 37). 0 si no viene."""
        for ai in ("30", "37"):
            v = self.valores.get(ai, "")
            if v and v.isdigit():
                return int(v)
        return 0

    @property
    def fecha_vencimiento(self) -> str:
        """Vencimiento en dd/mm/aaaa. Prueba 17 y 15."""
        for ai in ("17", "15", "16"):
            f = _fecha_gs1(self.valores.get(ai, ""))
            if f:
                return f
        return ""

    @property
    def fecha_elaboracion(self) -> str:
        """Elaboracion en dd/mm/aaaa. Prueba 11 y 13."""
        for ai in ("11", "13"):
            f = _fecha_gs1(self.valores.get(ai, ""))
            if f:
                return f
        return ""

    def tiene_datos_utiles(self) -> bool:
        return bool(self.sscc or self.cantidad or self.fecha_vencimiento)

    def resumen(self) -> dict:
        return {
            "sscc": self.sscc,
            "gtin": self.gtin,
            "lote": self.lote,
            "cantidad": self.cantidad,
            "fecha_elaboracion": self.fecha_elaboracion,
            "fecha_vencimiento": self.fecha_vencimiento,
            "no_reconocidos": self.no_reconocidos,
        }


def _fecha_gs1(valor: str) -> str:
    """Convierte una fecha GS1 (YYMMDD) a dd/mm/aaaa.

    Reglas GS1:
      - El anio se interpreta con pivote: YY < 70 -> 20YY, si no 19YY.
      - El dia "00" significa el ULTIMO dia del mes.
    """
    if not valor or len(valor) != 6 or not valor.isdigit():
        return ""
    aa, mm, dd = int(valor[:2]), int(valor[2:4]), int(valor[4:6])
    anio = 2000 + aa if aa < 70 else 1900 + aa
    if not 1 <= mm <= 12:
        return ""
    if dd == 0:
        # Ultimo dia del mes
        if mm == 12:
            ultimo = date(anio, 12, 31)
        else:
            ultimo = date(anio, mm + 1, 1).toordinal() - 1
            ultimo = date.fromordinal(ultimo)
        dd = ultimo.day
    try:
        return datetime(anio, mm, dd).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _limpiar(codigo: str) -> str:
    """Quita prefijos/sufijos que agregan algunos lectores.

    Algunos lectores mandan los AIs con parentesis por comodidad:
    "(00)278043001201264701(17)270604". Se quitan para poder parsear igual.
    """
    texto = str(codigo or "").strip()
    for marca in ("]C1", "]Q3", "]d2", "]e0"):     # identificadores de simbologia
        if texto.startswith(marca):
            texto = texto[len(marca):]
    # Formato con parentesis -> se quitan
    if "(" in texto:
        texto = texto.replace("(", "").replace(")", "")
    # Algunos lectores anteponen FNC1
    while texto[:1] in ("\x1d", "\x1e", "\x04"):
        texto = texto[1:]
    return texto


def _leer_ai(texto: str, i: int, estricto: bool = False) -> tuple[str, int] | None:
    """Intenta leer un AI en la posicion i. Devuelve (ai, largo_del_ai) o None.

    Con `estricto=True` solo acepta los AIs de `AI_CORTE`, que son los que pueden
    empezar un dato en una tarja de bodega. Eso evita cortar un valor numerico
    en pedazos (ej. "198" -> "1" + AI 98).
    """
    candidatos = AI_CORTE if estricto else (set(AI_FIJOS) | set(AI_VARIABLES))

    # 4 digitos (310n..369n)
    if i + 4 <= len(texto):
        cuatro = texto[i:i + 4]
        if cuatro[:3] in PREFIJOS_FIJOS_4 and cuatro.isdigit():
            return cuatro, 4
    # 3 digitos
    if i + 3 <= len(texto):
        tres = texto[i:i + 3]
        if tres in candidatos:
            return tres, 3
    # 2 digitos
    if i + 2 <= len(texto):
        dos = texto[i:i + 2]
        if dos in candidatos:
            return dos, 2
    return None


def _interpretaciones(texto: str, i: int, tope: int = 12) -> list[list[tuple[str, str]]]:
    """Todas las formas validas de parsear el texto desde i hasta el final.

    Un codigo GS1 sin separadores es ambiguo (no se sabe donde corta un valor
    variable). En vez de quedarse con la primera lectura, se devuelven todas y
    quien llama elige la mejor por puntaje. `tope` limita la recursion.
    """
    if i >= len(texto):
        return [[]]

    while i < len(texto) and texto[i] == "\x1d":
        i += 1
    if i >= len(texto):
        return [[]]

    if tope <= 0:
        return []

    leido = _leer_ai(texto, i, estricto=bool(i))
    if leido is None:
        return []

    ai, largo_ai = leido
    i += largo_ai
    resultados: list[list[tuple[str, str]]] = []

    # AI de 4 digitos (pesos/medidas): 6 de valor, sin ambiguedad
    if len(ai) == 4:
        valor = texto[i:i + 6]
        for resto in _interpretaciones(texto, i + 6, tope - 1):
            resultados.append([(ai, valor)] + resto)
        return resultados

    # AI de longitud fija: sin ambiguedad
    if ai in AI_FIJOS:
        n = AI_FIJOS[ai]
        valor = texto[i:i + n]
        for resto in _interpretaciones(texto, i + n, tope - 1):
            resultados.append([(ai, valor)] + resto)
        return resultados

    # AI variable: probar cada posible fin
    sep = texto.find("\x1d", i)
    if sep != -1:
        valor = texto[i:sep]
        for resto in _interpretaciones(texto, sep + 1, tope - 1):
            resultados.append([(ai, valor)] + resto)
        return resultados

    # Sin separador: todos los cortes posibles (de 1 caracter en adelante)
    for fin in range(i + 1, len(texto) + 1):
        valor = texto[i:fin]
        for resto in _interpretaciones(texto, fin, tope - 1):
            resultados.append([(ai, valor)] + resto)
    return resultados


def _puntaje(pares: list[tuple[str, str]]) -> int:
    """Que tan creible es una interpretacion del codigo.

    Se premia lo que sabemos que trae una tarja de bodega (SSCC valido, fechas,
    cantidad) y se castigan valores absurdamente largos en AIs variables.
    """
    p = 0
    for ai, valor in pares:
        p += 10                                    # cada AI reconocido suma
        if ai == "00" and sscc_valido(valor):
            p += 30                                # SSCC con digito de control OK
        elif ai == "00":
            p -= 20                                # un SSCC invalido es sospechoso
        if ai in ("17", "15", "16") and _fecha_gs1(valor):
            p += 10                                # vencimiento interpretable
        if ai in ("11", "13") and _fecha_gs1(valor):
            p += 5
        if ai in ("30", "37") and valor.isdigit() and 0 < int(valor) < 100000:
            p += 10                                # cantidad razonable
        if ai in ("30", "37", "10", "21", "240", "241") and len(valor) > 14:
            p -= 10                                # valor demasiado largo
        if ai in ("90", "91", "92", "93", "94", "95", "96", "97", "98", "99"):
            p += 8                                 # los internos suelen traer el SKU
    return p


def sscc_valido(sscc: str) -> bool:
    """True si el SSCC tiene 18 digitos y su digito de control es correcto."""
    if not sscc or len(sscc) != 18 or not sscc.isdigit():
        return False
    suma = 0
    for i, d in enumerate(reversed(sscc[:-1])):
        suma += int(d) * (3 if i % 2 == 0 else 1)
    return (10 - (suma % 10)) % 10 == int(sscc[-1])


def parsear(codigo: str) -> EscaneoGS1:
    """Parsea un codigo GS1-128 y devuelve los datos reconocidos.

    Tolera:
      - Que el lector NO mande el separador FNC1 (se resuelve por puntaje entre
        todas las lecturas posibles).
      - AIs con parentesis: "(00)278043...(17)270604".
      - Prefijo de simbologia (]C1).
      - Un SSCC pelado de 18 digitos (la tarja "de un solo dato").
    """
    texto = _limpiar(codigo)
    res = EscaneoGS1(crudo=str(codigo or ""))
    if not texto:
        return res

    # Caso especial: SSCC pelado (18 digitos).
    if texto.isdigit() and len(texto) == 18:
        res.valores["00"] = texto
        return res

    for sep in SEPARADORES:
        texto = texto.replace(sep, "\x1d")

    lecturas = _interpretaciones(texto, 0)
    if not lecturas:
        res.no_reconocidos.append(texto.strip("\x1d").strip())
        return res

    # La mejor lectura: la de mayor puntaje. A igual puntaje, la que trae mas AIs.
    mejor = max(lecturas, key=lambda p: (_puntaje(p), len(p)))

    for ai, valor in mejor:
        res.valores[ai] = valor
    return res


def es_gs1(codigo: str) -> bool:
    """Heuristica: True si el codigo parece GS1-128 con varios datos.

    Un SSCC pelado (18 digitos) tambien es GS1, pero de un solo dato.
    """
    texto = _limpiar(codigo)
    if not texto:
        return False
    if any(sep in texto for sep in SEPARADORES):
        return True
    return _leer_ai(texto, 0) is not None and len(texto) > 18


# ---------------------------------------------------------------------------
# SKU dentro del codigo
# ---------------------------------------------------------------------------

# AIs donde puede venir el SKU (codigo de producto), en orden de probabilidad.
# El GTIN (01/02) NO esta: ese es el codigo global del producto, no el SKU de
# la bodega, y confundirlos seria un error.
AI_SKU = ("240", "241", "90", "91", "92", "93", "94", "95", "96", "97", "98", "99")


def ubicar_sscc(codigo: str) -> tuple[int, str]:
    """Busca un SSCC VALIDO dentro del texto. Devuelve (posicion, sscc) o (-1, "").

    El SSCC tiene digito de control, asi que se puede reconocer sin saber el
    formato del resto: se prueban las ventanas de 18 digitos y se queda con la
    que pase el control. Eso sirve de ANCLA para saber donde empiezan los demas
    datos.
    """
    texto = _limpiar(codigo)
    for i in range(0, max(1, len(texto) - 17)):
        ventana = texto[i:i + 18]
        if ventana.isdigit() and sscc_valido(ventana):
            return i, ventana
    return -1, ""


def sku_candidatos(codigo: str) -> list[tuple[str, str]]:
    """Devuelve los (ai, valor) que PODRIAN ser el SKU, del mas probable al menos.

    Como NO sabemos en que AI viene el SKU, se combinan tres fuentes:
      1. Los AIs pensados para el codigo de producto (240, 241, 90-99).
      2. Los numeros que aparecen DESPUES del SSCC (el SSCC es el ancla: lo que
         viene despues son los demas datos de la tarja).
      3. Como ultimo recurso, los numeros del texto completo.

    Quien llama debe cruzar estos candidatos contra el stock
    (`recepcion.identificar_sku`): el que existe es el SKU.

    El GTIN (01/02) y el SSCC (00) se excluyen: NO son el SKU de bodega.
    """
    import re

    e = parsear(codigo)
    candidatos: list[tuple[str, str]] = []
    vistos: set[str] = set()

    def agregar(ai: str, valor: str) -> None:
        v = str(valor).strip()
        if not v or v in vistos:
            return
        vistos.add(v)
        candidatos.append((ai, v))

    # Valores que YA sabemos que no son el SKU
    no_sku = {e.sscc, e.gtin}
    for ai in ("11", "12", "13", "15", "16", "17", "30", "37"):
        if e.valores.get(ai):
            no_sku.add(e.valores[ai])

    # 1) AIs que suelen traer el codigo de producto
    for ai in AI_SKU:
        v = e.valores.get(ai, "").strip()
        if v:
            agregar(ai, v)

    crudo = _limpiar(codigo)

    # 2) Numeros DESPUES del SSCC (el ancla)
    pos, sscc = ubicar_sscc(crudo)
    if pos >= 0:
        no_sku.add(sscc)
        resto = crudo[pos + 18:]
        for run in sorted(re.findall(r"\d{4,14}", resto), key=len, reverse=True):
            if run not in no_sku:
                agregar("post-sscc", run)

    # 3) Ultimo recurso: numeros del texto completo
    if not candidatos:
        for run in sorted(re.findall(r"\d{4,14}", crudo), key=len, reverse=True):
            if run not in no_sku:
                agregar("crudo", run)

    return candidatos


def describir(codigo: str) -> list[dict]:
    """Desglose legible del codigo: que trae cada AI.

    Sirve para la pantalla de diagnostico: asi se ve, sin adivinar, que datos
    manda la tarja realmente.
    """
    e = parsear(codigo)
    salida = []
    for ai, valor in e.valores.items():
        salida.append({
            "ai": ai,
            "nombre": NOMBRES.get(ai, f"AI {ai}"),
            "valor": valor,
            "interpretado": _interpretar(ai, valor),
        })
    return salida


def _interpretar(ai: str, valor: str) -> str:
    """Version legible de un valor segun su AI (fechas, etc.)."""
    if ai in ("11", "12", "13", "15", "16", "17"):
        return _fecha_gs1(valor)
    if ai == "30" or ai == "37":
        return f"{valor} unidades" if valor.isdigit() else valor
    return ""
