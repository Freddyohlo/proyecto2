"""Recepcion de mercaderia (Plan B, contingencia).

Dos momentos, igual que en picking:

  1. RECIBIR: llega el camion. Se escanea el LPN de la tarja (y/o el SKU) y se
     registra la mercaderia. Entra al stock vivo con area RECEPCION, disponible
     para ubicar.

  2. UBICAR: se lleva a su ubicacion definitiva. La mercaderia sale de RECEPCION
     y entra al area destino (normalmente AREA ALMACENAMIENTO), con el lote y el
     vencimiento. Desde ahi ya es candidata para reaprovisionamiento.

Datos de la tarja (confirmado por el usuario, 2026-11-03):
    lpn      278043001201264701   (18 digitos)
    sku      700809
    ubicacion C16-01-01-01
    cantidad 198
    almacen  CD8000
  La tarja IMPRESA ademas trae FECHA DE ELABORACION y FECHA DE VENCIMIENTO.
  -> El vencimiento es imprescindible: sin el, FEFO no puede ordenar el lote.

El LPN se registra tal cual viene: no se intenta interpretar su estructura (no
hay documentacion del formato y adivinar seria peor que guardarlo crudo).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import stock_vivo as sv
from .externos import clave_sku

TABLA_RECEPCION = "recepcion"
TABLA_UBICACIONES = "ubicaciones"


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def normalizar_fecha(texto: object) -> str:
    """Normaliza la fecha al formato interno dd/mm/aaaa.

    La TARJA IMPRESA usa PUNTOS (31.10.2026, 04.06.2027), no barras: es el
    formato real de Blue Yonder. Se aceptan todas estas variantes:
        31.10.2026        (tarja)      -> 31/10/2026
        31.10.2026 08:10  (con hora)   -> 31/10/2026
        31/10/2026        (con barras) -> 31/10/2026
        31-10-2026        (con guiones)-> 31/10/2026
        2026-10-31        (ISO)        -> 31/10/2026
    Devuelve "" si no se entiende. El vencimiento es critico para FEFO: mejor
    dejarlo vacio y avisar, que guardar una fecha mal.
    """
    if texto is None:
        return ""
    t = str(texto).strip()
    if not t:
        return ""
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%d-%m-%Y %H:%M:%S", "%d-%m-%Y",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return ""


# ---------------------------------------------------------------------------
# SSCC: el LPN de la tarja es un codigo GS1 estandar
# ---------------------------------------------------------------------------

# El SSCC se valida con la misma funcion que usa el lector GS1: una sola
# fuente de verdad (src/gs1.py).
from .gs1 import sscc_valido  # noqa: E402


def digito_control_sscc(sscc: str) -> int | None:
    """Digito de control de un SSCC (modulo 10, GS1). None si no aplica."""
    if not sscc or len(sscc) != 18 or not sscc.isdigit():
        return None
    suma = 0
    for i, d in enumerate(reversed(sscc[:-1])):
        suma += int(d) * (3 if i % 2 == 0 else 1)
    return (10 - (suma % 10)) % 10


def desde_escaneo(codigo: str, sku: str = "", cantidad: int = 0,
                  ubicacion: str = "", almacen: str = "",
                  descripcion: str = "", usuario: str = "",
                  fecha: str = "", sku_detectado: str = "") -> Recepcion:
    """Arma una Recepcion a partir del codigo de barras GS1-128 de la tarja.

    El escaneo llena solo: SSCC, vencimiento, elaboracion, cantidad y lote.
    El SKU tambien viene DENTRO del codigo; si `sku_detectado` viene vacio, se
    intenta detectar con `identificar_sku()` (sin cruzar contra el stock, porque
    aca no tenemos la base a mano).

    Lo que no venga en el codigo se toma de los parametros, para que la pantalla
    pueda completarlo.
    """
    from . import gs1

    e = gs1.parsear(codigo)
    sku_final = sku or sku_detectado
    if not sku_final:
        candidatos = gs1.sku_candidatos(codigo)
        if candidatos:
            sku_final = candidatos[0][1]

    return Recepcion(
        lpn=e.sscc or str(codigo or "").strip(),
        sku=sku_final,
        cantidad=e.cantidad or cantidad,
        ubicacion=ubicacion,
        almacen=almacen,
        descripcion=descripcion,
        fecha_elaboracion=e.fecha_elaboracion,
        fecha_vencimiento=e.fecha_vencimiento,
        usuario=usuario,
        fecha=fecha,
    )


def identificar_sku(db: str | Path, codigo: str) -> dict:
    """Averigua cual de los numeros del codigo es el SKU real.

    El codigo GS1 sin separadores es ambiguo: no se sabe donde corta cada valor.
    En vez de adivinar el formato, se buscan **todas** las secuencias numericas
    del texto y se elige la que **existe en el stock**. El catalogo de SKU es el
    que desambigua.

    Devuelve {"sku", "origen", "candidatos"} y un "aviso" si nada calzo.
    """
    import re

    from . import gs1

    crudo = gs1._limpiar(codigo)
    if not crudo:
        return {"sku": "", "origen": "", "candidatos": []}

    # SKU conocidos en el stock, normalizados (sin ceros a la izquierda)
    try:
        with sv.abrir(db) as con:
            conocidos = {
                str(f["sku_clave"]) for f in
                con.execute(f"SELECT DISTINCT sku_clave FROM {sv.TABLA}").fetchall()
            }
    except Exception:
        conocidos = set()

    # 1) Los AIs que suelen traer el codigo de producto
    for ai, valor in gs1.sku_candidatos(codigo):
        if ai != "crudo" and ai != "post-sscc":
            if clave_sku(valor) in conocidos:
                return {"sku": valor, "origen": "stock",
                        "candidatos": [{"ai": a, "valor": v}
                                       for a, v in gs1.sku_candidatos(codigo)]}

    # 2) Cualquier numero del codigo que EXISTA en el stock.
    #    Se recorren las sub-secuencias de mayor a menor largo, para preferir el
    #    SKU completo antes que un pedazo.
    numeros: set[str] = set()
    for corrida in re.findall(r"\d{4,}", crudo):
        for i in range(len(corrida)):
            for j in range(i + 4, min(len(corrida), i + 15) + 1):
                numeros.add(corrida[i:j])
    for num in sorted(numeros, key=len, reverse=True):
        if clave_sku(num) in conocidos:
            return {"sku": num, "origen": "stock",
                    "candidatos": [{"ai": "texto", "valor": num}]}

    # 3) Ninguno calza: se devuelve el mas probable del parseo, con aviso
    cands = gs1.sku_candidatos(codigo)
    if cands:
        return {"sku": cands[0][1], "origen": "codigo",
                "candidatos": [{"ai": a, "valor": v} for a, v in cands],
                "aviso": "el SKU del codigo no esta en el stock cargado"}
    return {"sku": "", "origen": "", "candidatos": []}


@dataclass
class Recepcion:
    lpn: str
    sku: str
    cantidad: int
    ubicacion: str = ""            # ubicacion sugerida (de la tarja), si viene
    almacen: str = ""
    descripcion: str = ""
    fecha_elaboracion: str = ""
    fecha_vencimiento: str = ""
    cajas_pallet: int = 0          # "CAJAS / PALLET" de la tarja
    perfil_antiguedad: str = ""    # "PERFIL DE ANTIGUEDAD" de la tarja
    usuario: str = ""
    fecha: str = ""

    def faltantes(self) -> list[str]:
        """Campos imprescindibles que no vinieron."""
        malos = []
        if not self.lpn:
            malos.append("lpn")
        if not self.sku:
            malos.append("sku")
        if not self.cantidad or self.cantidad <= 0:
            malos.append("cantidad")
        return malos

    def pallets_completos(self) -> float:
        """Cuantos pallets representa (cajas reales / cajas por pallet).

        Ej. de la tarja: 198 cajas reales, 60 por pallet -> 3.3 pallets.
        """
        if not self.cajas_pallet:
            return 0.0
        return round(self.cantidad / self.cajas_pallet, 2)


# ---------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------

def preparar_tablas(con: sqlite3.Connection) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_RECEPCION} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, lpn TEXT, sku TEXT, sku_clave TEXT,
            descripcion TEXT, cantidad INTEGER, almacen TEXT,
            ubicacion_sugerida TEXT, ubicacion_final TEXT,
            fecha_elaboracion TEXT, fecha_vencimiento TEXT,
            cajas_pallet INTEGER DEFAULT 0, perfil_antiguedad TEXT,
            sscc_ok INTEGER, estado TEXT NOT NULL DEFAULT 'recibido'
        )
    """)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA_UBICACIONES} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ubicacion TEXT NOT NULL UNIQUE,
            sku TEXT, sku_clave TEXT, descripcion TEXT,
            capacidad INTEGER, ocupado INTEGER DEFAULT 0,
            zona TEXT, tipo TEXT
        )
    """)
    con.execute(f"CREATE INDEX IF NOT EXISTS ix_rec_lpn ON {TABLA_RECEPCION}(lpn)")


# ---------------------------------------------------------------------------
# Paso 1: recibir
# ---------------------------------------------------------------------------

def recibir(db: str | Path, recepcion: Recepcion) -> dict:
    """Registra la mercaderia recibida. Queda en RECEPCION, lista para ubicar.

    Idempotente por LPN: si el mismo LPN ya se recibio, NO se duplica (devuelve
    el registro existente). Evita el doble ingreso si el operario escanea dos veces.

    NO se valida contra el transito de SAP: si la mercaderia esta llegando, es
    porque llega; se recibe y despues se cuadra (criterio del usuario).
    """
    malos = recepcion.faltantes()
    if malos:
        return {"ok": False, "error": f"faltan datos: {', '.join(malos)}", "code": 400}

    # Normaliza las fechas aca adentro, para que valga sin importar quien llame
    # (la tarja las trae con puntos: 31.10.2026).
    fecha_venc = normalizar_fecha(recepcion.fecha_vencimiento)
    fecha_elab = normalizar_fecha(recepcion.fecha_elaboracion)

    momento = recepcion.fecha or datetime.now().isoformat(timespec="seconds")
    # El SSCC tiene digito de control: si no cuadra, el escaneo vino mal.
    sscc_ok = 1 if sscc_valido(recepcion.lpn) else 0

    with sv.abrir(db) as con:
        preparar_tablas(con)

        ya = con.execute(
            f"SELECT * FROM {TABLA_RECEPCION} WHERE lpn = ?", (recepcion.lpn,)
        ).fetchone()
        if ya:
            return {"ok": False, "error": f"el LPN {recepcion.lpn} ya fue recibido",
                    "code": 409, "id": int(ya["id"]),
                    "cantidad": int(ya["cantidad"])}

        clave = clave_sku(recepcion.sku)
        con.execute(
            f"""INSERT INTO {TABLA_RECEPCION}
                (fecha, usuario, lpn, sku, sku_clave, descripcion, cantidad,
                 almacen, ubicacion_sugerida, fecha_elaboracion, fecha_vencimiento,
                 cajas_pallet, perfil_antiguedad, sscc_ok, estado)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'recibido')""",
            (momento, recepcion.usuario, recepcion.lpn, recepcion.sku, clave,
             recepcion.descripcion, recepcion.cantidad, recepcion.almacen,
             recepcion.ubicacion, fecha_elab,
             fecha_venc, recepcion.cajas_pallet,
             recepcion.perfil_antiguedad, sscc_ok),
        )

        sv.ingresar(
            con,
            ubicacion=sv.AREA_RECEPCION,
            sku=recepcion.sku,
            cantidad=recepcion.cantidad,
            lpn=recepcion.lpn,
            descripcion=recepcion.descripcion,
            area=sv.AREA_RECEPCION,
            fecha_caducidad=fecha_venc,
        )

    avisos = []
    if not fecha_venc:
        avisos.append("sin fecha de vencimiento: FEFO no podra ordenar este lote")
    if not sscc_ok and len(recepcion.lpn) == 18:
        avisos.append(f"el SSCC {recepcion.lpn} no pasa el digito de control (posible mala lectura)")

    return {"ok": True, "lpn": recepcion.lpn, "sku": recepcion.sku,
            "cantidad": recepcion.cantidad,
            "aviso_vencimiento": not fecha_venc,
            "sscc_ok": bool(sscc_ok), "avisos": avisos,
            "pallets": recepcion.pallets_completos()}


# ---------------------------------------------------------------------------
# Paso 2: ubicar
# ---------------------------------------------------------------------------

def sugerir_ubicacion(db: str | Path, sku: str) -> dict:
    """Sugiere ubicacion para un SKU recien recibido.

    Orden de preferencia:
      1. Una ubicacion ya conocida para ese SKU (no dispersar el mismo producto).
      2. Una ubicacion con capacidad libre.
      3. Sin sugerencia (que decida el operador).
    """
    clave = clave_sku(sku)
    with sv.abrir(db) as con:
        preparar_tablas(con)

        # 1) ubicacion ya usada para ese SKU en el stock
        fila = con.execute(
            f"""SELECT ubicacion, area FROM {sv.TABLA}
                 WHERE sku_clave = ? AND area NOT IN (?, '')
                 ORDER BY cantidad DESC LIMIT 1""",
            (clave, sv.AREA_RECEPCION),
        ).fetchone()
        if fila:
            return {"ok": True, "ubicacion": fila["ubicacion"], "area": fila["area"],
                    "motivo": "ya se guarda ese SKU ahi"}

        # 2) ubicacion con capacidad libre
        libre = con.execute(
            f"""SELECT ubicacion, capacidad, ocupado FROM {TABLA_UBICACIONES}
                 WHERE capacidad IS NOT NULL
                   AND (capacidad - COALESCE(ocupado,0)) > 0
                 ORDER BY (capacidad - COALESCE(ocupado,0)) DESC LIMIT 1"""
        ).fetchone()
        if libre:
            return {"ok": True, "ubicacion": libre["ubicacion"],
                    "capacidad_libre": int(libre["capacidad"]) - int(libre["ocupado"] or 0),
                    "motivo": "tiene capacidad libre"}

    return {"ok": False, "motivo": "sin ubicacion conocida; que decida el operador"}


def ubicar(db: str | Path, id_recepcion: int, ubicacion_final: str,
           usuario: str = "") -> dict:
    """Mueve la mercaderia de RECEPCION a su ubicacion definitiva.

    Sale de RECEPCION y entra al area destino conservando LOTE y VENCIMIENTO
    (sin eso FEFO no puede ordenar).
    """
    if not ubicacion_final:
        return {"ok": False, "error": "falta la ubicacion", "code": 400}

    with sv.abrir(db) as con:
        preparar_tablas(con)
        r = con.execute(
            f"SELECT * FROM {TABLA_RECEPCION} WHERE id = ?", (id_recepcion,)
        ).fetchone()
        if r is None:
            return {"ok": False, "error": "recepcion inexistente", "code": 404}
        if r["estado"] == "ubicado":
            return {"ok": False, "error": "esa recepcion ya fue ubicada", "code": 400}

        # Sale de RECEPCION (misma fila ubicacion=RECEPCION, mismo lote)
        fila = con.execute(
            f"""SELECT id FROM {sv.TABLA}
                 WHERE ubicacion = ? AND sku_clave = ? AND COALESCE(lpn,'') = ?""",
            (sv.AREA_RECEPCION, r["sku_clave"], r["lpn"] or ""),
        ).fetchone()
        if fila is None:
            return {"ok": False, "error": "no esta en RECEPCION", "code": 400}

        # Se descuenta de la fila de recepcion y se suma a la ubicacion final
        con.execute(f"DELETE FROM {sv.TABLA} WHERE id = ?", (fila["id"],))
        sv.ingresar(
            con,
            ubicacion=ubicacion_final,
            sku=r["sku"],
            cantidad=int(r["cantidad"]),
            lpn=r["lpn"] or "",
            descripcion=r["descripcion"] or "",
            area=sv.AREA_ALMACENAMIENTO,
            fecha_caducidad=r["fecha_vencimiento"] or "",
        )

        con.execute(
            f"""UPDATE {TABLA_RECEPCION}
                   SET estado = 'ubicado', ubicacion_final = ?, usuario = ?
                 WHERE id = ?""",
            (ubicacion_final, usuario, id_recepcion),
        )

    return {"ok": True, "lpn": r["lpn"], "sku": r["sku"],
            "cantidad": int(r["cantidad"]), "ubicacion": ubicacion_final,
            "vencimiento": r["fecha_vencimiento"] or ""}


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def recibir_y_ubicar(db: str | Path, recepcion: Recepcion,
                     ubicacion_final: str = "") -> dict:
    """Recibe y ubica en UN SOLO PASO (optimizacion de operacion).

    Si la tarja ya trae la ubicacion destino (ej. C16-01-01-01), no tiene sentido
    hacer que el operario confirme dos veces: se recibe y se ubica de una.
    Si no se pasa ubicacion_final, se usa la de la tarja.

    Devuelve el resultado combinado, mas `paso_unico: True`.
    """
    destino = ubicacion_final or recepcion.ubicacion
    if not destino:
        return {"ok": False,
                "error": "sin ubicacion: use recibir() y ubique despues", "code": 400}

    r = recibir(db, recepcion)
    if not r["ok"]:
        return r

    with sv.abrir(db) as con:
        preparar_tablas(con)
        fila = con.execute(
            f"SELECT id FROM {TABLA_RECEPCION} WHERE lpn = ?", (recepcion.lpn,)
        ).fetchone()
    if fila is None:
        return {"ok": False, "error": "no se encontro la recepcion recien creada",
                "code": 500}

    u = ubicar(db, int(fila["id"]), destino, recepcion.usuario)
    if not u["ok"]:
        return u

    return {**r, **u, "ok": True, "paso_unico": True, "ubicacion": destino}


def crear_sku(db: str | Path, sku: str, descripcion: str = "",
              ubicacion: str = "", cantidad: int = 0,
              lpn: str = "", fecha_vencimiento: str = "",
              usuario: str = "") -> dict:
    """Da de alta un SKU que NO venia en la cuadratura (producto que va llegando).

    Caso real: llega un producto nuevo, que no estaba en el stock capturado. En
    vez de rechazarlo, se registra en la tabla `sku_nuevos` y se ingresa al stock
    vivo. Asi el sistema queda completo y despues se cuadra con Blue Yonder.

    ⚠️ REGLA (confirmada por el usuario): el producto nuevo entra al stock en
    **ALMACENAMIENTO**, nunca en PICKING. Un producto que recien llega no tiene
    ubicacion de picking asignada; primero se guarda en altura y despues el
    reaprovisionamiento lo baja al picking cuando corresponda.
    """
    from .externos import clave_sku

    if not sku or not str(sku).strip():
        return {"ok": False, "error": "falta el SKU", "code": 400}

    sku = str(sku).strip()
    momento = datetime.now().isoformat(timespec="seconds")
    venc = normalizar_fecha(fecha_vencimiento)

    with sv.abrir(db) as con:
        preparar_tablas(con)
        con.execute("""
            CREATE TABLE IF NOT EXISTS sku_nuevos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT, usuario TEXT, sku TEXT, sku_clave TEXT,
                descripcion TEXT, ubicacion TEXT, cantidad INTEGER,
                lpn TEXT, fecha_vencimiento TEXT
            )
        """)
        con.execute(
            """INSERT INTO sku_nuevos
               (fecha, usuario, sku, sku_clave, descripcion, ubicacion, cantidad,
                lpn, fecha_vencimiento)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (momento, usuario, sku, clave_sku(sku), descripcion, ubicacion,
             cantidad, lpn, venc),
        )

        # Entra al stock vivo SIEMPRE en ALMACENAMIENTO (nunca en picking).
        # Si todavia no se sabe donde va, queda en RECEPCION para ubicarlo luego.
        if cantidad > 0:
            sv.ingresar(
                con,
                ubicacion=ubicacion or sv.AREA_RECEPCION,
                sku=sku,
                cantidad=cantidad,
                lpn=lpn or "",
                descripcion=descripcion,
                area=sv.AREA_ALMACENAMIENTO if ubicacion else sv.AREA_RECEPCION,
                fecha_caducidad=venc,
            )

    return {"ok": True, "sku": sku, "cantidad": cantidad,
            "ubicacion": ubicacion or sv.AREA_RECEPCION, "nuevo": True,
            "area": sv.AREA_ALMACENAMIENTO if ubicacion else sv.AREA_RECEPCION}


def skus_nuevos(db: str | Path) -> pd.DataFrame:
    """SKU dados de alta que no venian en la cuadratura."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        try:
            return pd.read_sql_query(
                "SELECT fecha, sku, descripcion, cantidad, ubicacion, lpn, "
                "fecha_vencimiento FROM sku_nuevos ORDER BY id", con)
        except Exception:
            return pd.DataFrame(columns=["fecha", "sku", "descripcion", "cantidad",
                                         "ubicacion", "lpn", "fecha_vencimiento"])


def pendientes(db: str | Path) -> pd.DataFrame:
    """Recepciones recibidas pero todavia sin ubicar."""
    with sv.abrir(db) as con:
        preparar_tablas(con)
        return pd.read_sql_query(
            f"""SELECT id, fecha, lpn, sku, descripcion, cantidad,
                       ubicacion_sugerida, fecha_vencimiento
                  FROM {TABLA_RECEPCION}
                 WHERE estado = 'recibido'
                 ORDER BY id""",
            con,
        )


def resumen(db: str | Path) -> dict:
    with sv.abrir(db) as con:
        preparar_tablas(con)
        f = con.execute(
            f"""SELECT COUNT(*) AS n,
                       SUM(cantidad) AS cajas,
                       SUM(CASE WHEN estado='recibido' THEN 1 ELSE 0 END) AS pend,
                       SUM(CASE WHEN estado='ubicado' THEN 1 ELSE 0 END) AS ubic,
                       SUM(CASE WHEN COALESCE(fecha_vencimiento,'')='' THEN 1 ELSE 0 END) AS sin_venc
                  FROM {TABLA_RECEPCION}"""
        ).fetchone()
    recepciones = int(f["n"] or 0)
    ubicadas = int(f["ubic"] or 0)
    return {
        "recepciones": recepciones,
        "cajas": int(f["cajas"] or 0),
        "pendientes": int(f["pend"] or 0),
        "ubicadas": ubicadas,
        "sin_vencimiento": int(f["sin_venc"] or 0),
        # MOVIMIENTOS: cada accion fisica cuenta. Recibir un pallet es un
        # movimiento (baja del camion) y ubicarlo es otro (va a la estanteria).
        # Un pallet que se recibe y se ubica son 2 movimientos.
        # OJO: las CAJAS no se duplican (son las mismas cajas movidas dos veces).
        "movimientos": recepciones + ubicadas,
    }
