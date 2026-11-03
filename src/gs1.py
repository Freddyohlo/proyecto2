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


def parsear(codigo: str) -> EscaneoGS1:
    """Parsea un codigo GS1-128 y devuelve los datos reconocidos.

    Tolera que el lector NO mande separadores (FNC1): en ese caso los AIs de
    longitud fija se leen por su largo, y los variables cortan al encontrar el
    siguiente AI valido de `AI_CORTE`.

    Si el codigo es un SSCC pelado (18 digitos, sin AI), se reconoce igual y se
    devuelve como si viniera de AI 00. Asi la tarja vieja sigue funcionando.
    """
    texto = _limpiar(codigo)
    res = EscaneoGS1(crudo=str(codigo or ""))
    if not texto:
        return res

    # Caso especial: SSCC pelado (18 digitos). Es la tarja "de un solo dato".
    if texto.isdigit() and len(texto) == 18:
        res.valores["00"] = texto
        return res

    # Normaliza: los separadores se marcan para saber donde cortan los variables
    for sep in SEPARADORES:
        texto = texto.replace(sep, "\x1d")

    i = 0
    while i < len(texto):
        if texto[i] == "\x1d":       # separador suelto
            i += 1
            continue

        # Al principio se acepta cualquier AI conocido; despues, solo los que
        # pueden iniciar un dato (para no cortar un valor numerico en pedazos).
        leido = _leer_ai(texto, i, estricto=bool(res.valores))
        if leido is None:
            resto = texto[i:].strip("\x1d").strip()
            if resto:
                res.no_reconocidos.append(resto)
            break

        ai, largo_ai = leido
        i += largo_ai

        # --- AI de 4 digitos (pesos/medidas): 6 de valor ---
        if len(ai) == 4:
            valor = texto[i:i + 6]
            i += 6
            res.valores[ai] = valor
            continue

        # --- AI de longitud FIJA ---
        if ai in AI_FIJOS:
            n = AI_FIJOS[ai]
            res.valores[ai] = texto[i:i + n]
            i += n
            continue

        # --- AI de longitud VARIABLE ---
        fin = texto.find("\x1d", i)
        if fin == -1:
            # Sin separador: cortar cuando empiece el siguiente AI valido
            fin = len(texto)
            j = i
            while j < len(texto):
                if _leer_ai(texto, j, estricto=True) is not None:
                    fin = j
                    break
                j += 1
        res.valores[ai] = texto[i:fin]
        i = fin + 1 if fin < len(texto) and texto[fin:fin + 1] == "\x1d" else fin

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
