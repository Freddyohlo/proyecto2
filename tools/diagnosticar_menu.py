"""Diagnostica cual boton ABRE el menu de las tres barritas (SOLO en Windows).

Prueba cada boton candidato, hace clic, y reporta si el menu quedo abierto
(aparece el panel 'pnlMenu') y que ventanas emergentes surgieron.

Uso (en el PC con Blue Yonder logueado y el MENU CERRADO):
    python tools\\diagnosticar_menu.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pywinauto import Desktop

from src import capture_ui

CANDIDATOS = ["btnMenuClose", "btnPinMenu", "btnFavorites", "btnMenu"]


def estado_menu(ventana) -> str:
    """Devuelve un resumen del estado del menu."""
    tiene_pnl = capture_ui._buscar(ventana, "pnlMenu") is not None
    tiene_grp = capture_ui._buscar(ventana, "grpMenu") is not None
    tiene_pin = capture_ui._buscar(ventana, "btnPinMenu") is not None
    return f"pnlMenu={tiene_pnl} grpMenu={tiene_grp} btnPinMenu={tiene_pin}"


def ventanas_superiores() -> list[str]:
    salida = []
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            salida.append(repr(w.window_text()))
        except Exception:
            continue
    return salida


def main() -> int:
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")

    # Traer la app al frente para que los clics le lleguen.
    try:
        ventana.set_focus()
        time.sleep(1)
    except Exception as e:
        print(f"(no se pudo poner en foco: {e})")

    print(f"Estado inicial del menu: {estado_menu(ventana)}")
    print(f"Ventanas: {ventanas_superiores()}\n")

    for auto_id in CANDIDATOS:
        boton = capture_ui._buscar(ventana, auto_id)
        if boton is None:
            print(f"[{auto_id}] NO existe en la ventana. Se omite.")
            continue

        print(f"[{auto_id}] haciendo clic...")
        try:
            try:
                ventana.set_focus()
            except Exception:
                pass
            boton.click_input()
        except Exception as e:
            print(f"    error al hacer clic: {e}")
            continue
        time.sleep(2.5)

        print(f"    estado del menu tras el clic: {estado_menu(ventana)}")
        print(f"    ventanas: {ventanas_superiores()}")

        # Si abrio el menu, lo dejamos; si no, seguimos probando.
        if capture_ui._buscar(ventana, "pnlMenu") is not None:
            print(f"\n>>> '{auto_id}' ABRE EL MENU. Ese es el boton correcto.")
            return 0

    print("\n>>> Ninguno de los candidatos abrio el menu. Ver notas mas arriba.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
