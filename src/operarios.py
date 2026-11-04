"""Operarios y usuarios fijos (Plan B).

IDEA (del usuario): no queremos administrar usuarios con registro, base de datos
robusta, altas y bajas. Queremos unos pocos **usuarios fijos** que el supervisor
**asigna** a los operarios del dia:

    "el usuario PICK1 se destino al operario Juan"
    -> al final igual sabemos quien hizo cada movimiento.

Entonces:
  - Hay un puñado de usuarios fijos por rol (PICK1..PICK4, GRUA1..GRUA2).
  - El supervisor les pone el nombre del operario (y opcionalmente un PIN).
  - Cada movimiento guarda el usuario fijo -> la productividad se puede medir.
  - Si el nombre no esta cargado, se muestra solo el codigo.

Se guarda en una tabla chica (`operarios`) en la misma base. Si esta vacia, se
siembran los usuarios por defecto. No hay login con contrasena ni roles complejos:
es una asignacion, no un sistema de identidades.
"""

from __future__ import annotations

from pathlib import Path

from . import stock_vivo as sv

TABLA = "operarios"

# Usuarios por defecto, por rol. El supervisor les asigna el nombre del operario.
POR_DEFECTO = [
    ("PICK1", "picking"), ("PICK2", "picking"),
    ("PICK3", "picking"), ("PICK4", "picking"),
    ("GRUA1", "grua"), ("GRUA2", "grua"),
]

ROLES = ("picking", "grua")

# PIN por defecto. Es simple a proposito: sirve para que quede registrado QUIEN
# hizo el movimiento, no para blindar el equipo.
PIN_POR_DEFECTO = {
    "PICK1": "1111", "PICK2": "2222", "PICK3": "3333", "PICK4": "4444",
    "GRUA1": "1111", "GRUA2": "2222",
}


def preparar_tabla(con) -> None:
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLA} (
            codigo TEXT PRIMARY KEY,
            nombre TEXT DEFAULT '',
            rol TEXT NOT NULL DEFAULT 'picking',
            pin TEXT DEFAULT ''
        )
    """)
    # Siembra los usuarios por defecto la primera vez
    n = con.execute(f"SELECT COUNT(*) FROM {TABLA}").fetchone()[0]
    if not n:
        con.executemany(
            f"INSERT INTO {TABLA} (codigo, nombre, rol, pin) VALUES (?,?,?,?)",
            [(c, "", r, PIN_POR_DEFECTO.get(c, "")) for c, r in POR_DEFECTO],
        )


def sembrar(db: str | Path) -> int:
    """Asegura que existan los usuarios por defecto. Devuelve cuantos hay."""
    with sv.abrir(db) as con:
        preparar_tabla(con)
        return con.execute(f"SELECT COUNT(*) FROM {TABLA}").fetchone()[0]


def listar(db: str | Path, rol: str = "") -> list[dict]:
    """Usuarios (de un rol, si se indica), ordenados por codigo."""
    with sv.abrir(db) as con:
        preparar_tabla(con)
        if rol:
            filas = con.execute(
                f"SELECT codigo, nombre, rol FROM {TABLA} WHERE rol = ? ORDER BY codigo",
                (rol,),
            ).fetchall()
        else:
            filas = con.execute(
                f"SELECT codigo, nombre, rol FROM {TABLA} ORDER BY rol, codigo"
            ).fetchall()
    return [dict(f) for f in filas]


def nombre(db: str | Path, codigo: str) -> str:
    """Nombre del operario asignado a ese usuario ('' si no tiene)."""
    codigo = str(codigo or "").strip().upper()
    if not codigo:
        return ""
    with sv.abrir(db) as con:
        preparar_tabla(con)
        f = con.execute(
            f"SELECT nombre FROM {TABLA} WHERE codigo = ?", (codigo,)
        ).fetchone()
    return str(f["nombre"] or "") if f else ""


def etiqueta(db: str | Path, codigo: str) -> str:
    """'PICK1 — Juan' (o solo el codigo si no tiene nombre)."""
    n = nombre(db, codigo)
    return f"{codigo} — {n}" if n else str(codigo)


def verificar_pin(db: str | Path, codigo: str, pin: str) -> bool:
    """True si el PIN corresponde a ese usuario.

    Si el usuario no tiene PIN cargado, se acepta cualquiera (para no trabar la
    operacion: el PIN es para dejar registro, no para blindar).
    """
    codigo = str(codigo or "").strip().upper()
    if not codigo:
        return False
    with sv.abrir(db) as con:
        preparar_tabla(con)
        f = con.execute(
            f"SELECT pin FROM {TABLA} WHERE codigo = ?", (codigo,)
        ).fetchone()
    if f is None:
        return False
    guardado = str(f["pin"] or "").strip()
    if not guardado:
        return True
    return guardado == str(pin or "").strip()


def asignar(db: str | Path, codigo: str, nombre_operario: str = "",
            rol: str = "", pin: str = "") -> dict:
    """Asigna el nombre del operario (y opcionalmente rol/PIN) a un usuario fijo."""
    codigo = str(codigo or "").strip().upper()
    if not codigo:
        return {"ok": False, "error": "falta el codigo de usuario"}

    with sv.abrir(db) as con:
        preparar_tabla(con)
        actual = con.execute(
            f"SELECT * FROM {TABLA} WHERE codigo = ?", (codigo,)
        ).fetchone()
        if actual is None:
            con.execute(
                f"INSERT INTO {TABLA} (codigo, nombre, rol, pin) VALUES (?,?,?,?)",
                (codigo, nombre_operario, rol or "picking", pin),
            )
        else:
            con.execute(
                f"""UPDATE {TABLA}
                       SET nombre = ?, rol = ?, pin = ?
                     WHERE codigo = ?""",
                (nombre_operario,
                 rol or str(actual["rol"] or "picking"),
                 pin if pin else str(actual["pin"] or ""),
                 codigo),
            )
    return {"ok": True, "codigo": codigo, "nombre": nombre_operario}


def productividad(db: str | Path, rol: str = "picking") -> list[dict]:
    """Movimientos por usuario, para medir productividad.

    Cruza los usuarios fijos con lo que realmente movieron (tablas `picking`,
    `reapro` y `recepcion`). Asi se ve quien hizo cuanto, sin haber tenido que
    registrar usuarios.
    """
    with sv.abrir(db) as con:
        preparar_tabla(con)
        usuarios = {
            str(f["codigo"]): str(f["nombre"] or "")
            for f in con.execute(
                f"SELECT codigo, nombre FROM {TABLA} WHERE rol = ?", (rol,)
            ).fetchall()
        }

        mov: dict[str, dict] = {c: {"movimientos": 0, "cajas": 0} for c in usuarios}

        if rol == "picking":
            try:
                for f in con.execute(
                    """SELECT usuario, COUNT(*) AS n, COALESCE(SUM(cantidad),0) AS c
                         FROM picking GROUP BY usuario"""
                ).fetchall():
                    u = str(f["usuario"] or "")
                    if u in mov:
                        mov[u]["movimientos"] += int(f["n"] or 0)
                        mov[u]["cajas"] += int(f["c"] or 0)
            except Exception:
                pass
        else:
            try:
                for f in con.execute(
                    """SELECT operador, COUNT(*) AS n, COALESCE(SUM(cantidad),0) AS c
                         FROM reapro WHERE estado = 'ok' GROUP BY operador"""
                ).fetchall():
                    u = str(f["operador"] or "")
                    if u in mov:
                        mov[u]["movimientos"] += int(f["n"] or 0)
                        mov[u]["cajas"] += int(f["c"] or 0)
            except Exception:
                pass

    return [
        {"codigo": c, "nombre": usuarios[c], "etiqueta": f"{c} — {usuarios[c]}"
         if usuarios[c] else c,
         "movimientos": v["movimientos"], "cajas": v["cajas"]}
        for c, v in sorted(mov.items())
    ]
