"""Prueba varias formas de copiar la grilla y reporta cual funciona (SOLO Windows).

Asume que YA estas en la pantalla 'CCU Cuadratura de Stock' con resultados en la
grilla (busca a mano si hace falta).

Uso:
    python tools\\diagnosticar_copia.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyperclip
from pywinauto import Desktop

from src import capture_ui


def ventana_app():
    return capture_ui.buscar_ventana_app()


def grilla_de(ventana):
    return capture_ui._buscar(ventana, "GridView:Parent=Control", control_type="Table")


def validar(nombre: str) -> bool:
    texto = pyperclip.paste()
    ok = bool(texto.strip())
    print(f"    [{nombre}] lineas en portapapeles: {len(texto.splitlines())}  -> {'OK' if ok else 'vacio'}")
    if ok:
        print("    Primeras 2 lineas:")
        for ln in texto.splitlines()[:2]:
            print("      ", ln)
    return ok


def estrategia(nombre: str, funcion) -> bool:
    print(f"\n>>> Estrategia: {nombre}")
    pyperclip.copy("")
    try:
        funcion()
    except Exception as e:
        print(f"    error: {type(e).__name__}: {e}")
        return False
    time.sleep(1.5)
    try:
        return validar(nombre)
    except Exception as e:
        print(f"    error al leer portapapeles: {e}")
        return False


def main() -> int:
    ventana = ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    grilla = grilla_de(ventana)
    if grilla is None:
        print("No encontre la grilla 'GridView:Parent=Control'.")
        return 1
    r = grilla.rectangle()
    print(f"Grilla: L{r.left} T{r.top} R{r.right} B{r.bottom}")

    # 1) clic en el centro de la grilla + type_keys en la grilla
    def e1():
        grilla.click_input()
        time.sleep(0.5)
        grilla.type_keys("{HOME}")   # asegura foco dentro de la grilla
        time.sleep(0.3)
        grilla.type_keys("^a")
        time.sleep(0.5)
        grilla.type_keys("^c")

    # 2) clic en una celda + send_keys a nivel de ventana
    def e2():
        grilla.click_input()
        time.sleep(0.5)
        ventana.type_keys("^a")
        time.sleep(0.5)
        ventana.type_keys("^c")

    # 3) set_focus + Alt+Supr? no: usar send_keys del teclado global
    def e3():
        import pyautogui
        grilla.click_input()
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "c")

    # 4) clic + doble clic en el header para seleccionar todo + copiar
    def e4():
        grilla.click_input()
        time.sleep(0.3)
        grilla.type_keys("{ENTER}")
        time.sleep(0.3)
        grilla.type_keys("^a")
        time.sleep(0.5)
        grilla.type_keys("^c")

    for nombre, fn in [("clic+type_keys en grilla", e1),
                       ("clic+type_keys en ventana", e2),
                       ("clic+pyautogui hotkey", e3),
                       ("clic+ENTER+^a^c", e4)]:
        if estrategia(nombre, fn):
            print(f"\n>>> FUNCIONA: {nombre}")
            return 0

    print("\n>>> Ninguna estrategia copio datos. Revisar manualmente.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
