"""Navega el menu clasico de arriba paso a paso (SOLO en Windows).

Ruta esperada: Aplicaciones -> Informes/Etiquetas -> CCU Cuadratura de Stock.

Va haciendo clic en cada nivel y reportando los items que aparecen, para
descubrir los nombres exactos. Deja pausas para que veas que ocurre.

Uso (en el PC con Blue Yonder logueado, menu cerrado):
    python tools\\probar_menu_arriba.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pywinauto import Desktop

from src import capture_ui


def items_visibles() -> list[tuple[str, str]]:
    """(texto, tipo) de todos los MenuItem/Menu visibles en cualquier ventana."""
    salida = []
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    tipo = c.element_info.control_type
                    if tipo not in ("MenuItem", "Menu"):
                        continue
                    texto = c.window_text()
                    if texto.strip() and texto != "Sistema":
                        salida.append((texto, tipo))
                except Exception:
                    continue
        except Exception:
            continue
    return salida


def buscar_menuitem(texto_deseado: str):
    """Devuelve el MenuItem cuyo texto contenga lo deseado."""
    objetivo = texto_deseado.lower()
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type != "MenuItem":
                        continue
                    if objetivo in c.window_text().lower():
                        return c
                except Exception:
                    continue
        except Exception:
            continue
    return None


def titulo_actual(ventana) -> str:
    lbl = capture_ui._buscar(ventana, "lblCurAppTitle")
    flujo = capture_ui._buscar(ventana, "lblCurAppFlow")
    t = lbl.window_text() if lbl else "?"
    f = flujo.window_text() if flujo else "?"
    return f"titulo={t!r}  flujo={f!r}"


def main() -> int:
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado actual: {titulo_actual(ventana)}\n")

    try:
        ventana.set_focus()
        time.sleep(0.5)
    except Exception:
        pass

    # --- Paso A: clic en 'Aplicaciones' ---
    print("[A] Buscando MenuItem 'Aplicaciones'...")
    item = buscar_menuitem("aplicaciones")
    if item is None:
        print("    NO encontrado. Items visibles:", items_visibles())
        return 1
    print("    clic...")
    item.click_input()
    time.sleep(2)

    print("    Items que aparecen ahora:")
    for texto, tipo in items_visibles():
        print(f"       {tipo}: {texto!r}")

    # --- Paso B: clic en 'Informes/Etiquetas' ---
    print("\n[B] Buscando MenuItem 'Informes/Etiquetas'...")
    item = buscar_menuitem("informes")
    if item is None:
        print("    NO encontrado todavia.")
        return 1
    print("    clic...")
    item.click_input()
    time.sleep(2)

    print("    Items que aparecen ahora:")
    for texto, tipo in items_visibles():
        print(f"       {tipo}: {texto!r}")

    # --- Paso C: clic en 'CCU Cuadratura de Stock' ---
    print("\n[C] Buscando MenuItem 'CCU cuadratura de stock'...")
    item = buscar_menuitem("cuadratura")
    if item is None:
        print("    NO encontrado todavia.")
        return 1
    print("    clic...")
    item.click_input()
    time.sleep(3)

    print(f"\n   Estado tras el clic: {titulo_actual(ventana)}")
    print("\nOK: si el titulo dice 'CCU Cuadratura de Stock', la ruta del menu funciona.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
