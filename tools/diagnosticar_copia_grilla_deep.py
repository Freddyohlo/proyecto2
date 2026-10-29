"""Diagnostico PROFUNDO de copiado de grilla (SOLO Windows, ya logueado).

Se usa cuando Ctrl+A/Ctrl+C no copian nada (grillas DevExpress que ignoran los
mensajes de teclado de pywinauto). Prueba vias ALTERNATIVAS:

  P1) pyautogui: keystrokes REALES del sistema (no mensajes al control)
  P2) clic derecho -> menu contextual -> 'Copiar' / 'Copy'
  P3) patron UIA de seleccion (SelectionPattern / select de celdas)
  P4) clic en el contenedor 'gridMst' (Custom) en vez de la Table interna
  P5) clic + Shift+clic en la ultima celda (seleccion por rango con mouse)
  P6) Ctrl+Insert (alternativa a Ctrl+C en muchas grillas)

Reporta cuantas lineas trae cada uno.

Uso (con la pantalla ya buscada, ej. reabastecimiento con 1122 filas):
    python tools\\diagnosticar_copia_grilla_deep.py --esperadas 1122
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyperclip

from src import capture_ui, config


def _lineas(texto: str) -> int:
    return len(texto.splitlines()) if texto.strip() else 0


def _p1_pyautogui(grilla, cfg) -> str:
    """Keystrokes reales del sistema operativo."""
    try:
        import pyautogui
    except ImportError:
        print("      (pyautogui no instalado: pip install pyautogui)")
        return ""
    pyperclip.copy("")
    try:
        grilla.click_input()
        time.sleep(0.5)
        # Ir al inicio y seleccionar todo con teclas reales
        pyautogui.hotkey("home")
        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "shift", "end")
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "c")
    except Exception as e:
        print(f"      (pyautogui fallo: {e})")
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def _p2_menu_contextual(grilla, cfg) -> str:
    """Clic derecho y elegir 'Copiar' del menu contextual."""
    from pywinauto import Desktop

    pyperclip.copy("")
    try:
        grilla.click_input(button="right")
        time.sleep(1.0)
    except Exception as e:
        print(f"      (clic derecho fallo: {e})")
        return ""
    # Buscar un item 'Copiar'/'Copy' en cualquier menu emergente
    elegido = None
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type not in ("MenuItem", "Button"):
                        continue
                    t = c.window_text().strip().lower()
                    if t in ("copiar", "copy", "copiar con encabezados", "copy with headers"):
                        elegido = c
                        break
                except Exception:
                    continue
        except Exception:
            continue
        if elegido:
            break
    if elegido is None:
        try:
            grilla.type_keys("{ESC}")
        except Exception:
            pass
        return ""
    try:
        elegido.click_input()
    except Exception:
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def _p3_patron_seleccion(grilla, cfg) -> str:
    """Intenta usar el patron de seleccion UIA sobre las celdas."""
    pyperclip.copy("")
    try:
        celdas = []
        for c in grilla.descendants():
            try:
                if c.element_info.control_type == "DataItem":
                    celdas.append(c)
            except Exception:
                continue
        if not celdas:
            return ""
        # Seleccionar la primera y la ultima con el patron si existe
        for c in (celdas[0], celdas[-1]):
            try:
                c.iface_selection_item.select()
            except Exception:
                pass
        time.sleep(0.5)
        grilla.type_keys("^c")
    except Exception as e:
        print(f"      (patron fallo: {e})")
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def _contenedor_grid(ventana):
    """El contenedor 'gridMst' (Custom), que a veces recibe mejor el foco."""
    return capture_ui._buscar(ventana, "gridMst")


def _p4_contenedor(ventana, cfg) -> str:
    pyperclip.copy("")
    cont = _contenedor_grid(ventana)
    if cont is None:
        print("      (no encontre 'gridMst')")
        return ""
    try:
        cont.click_input()
        time.sleep(0.5)
        cont.type_keys("{HOME}")
        time.sleep(0.3)
        cont.type_keys("^+{END}")
        time.sleep(0.5)
        cont.type_keys("^c")
    except Exception as e:
        print(f"      (fallo: {e})")
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def _p5_shift_click(grilla, cfg) -> str:
    """Clic en la 1a celda y Shift+clic en la ultima (seleccion por mouse)."""
    try:
        import pyautogui
    except ImportError:
        return ""
    pyperclip.copy("")
    try:
        celdas = []
        for c in grilla.descendants():
            try:
                if c.element_info.control_type == "DataItem":
                    celdas.append(c)
            except Exception:
                continue
        if not celdas:
            return ""
        r1 = celdas[0].rectangle()
        r2 = celdas[-1].rectangle()
        pyautogui.click(r1.left + 5, r1.top + 5)
        time.sleep(0.4)
        pyautogui.keyDown("shift")
        pyautogui.click(r2.left + 5, r2.top + 5)
        pyautogui.keyUp("shift")
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "c")
    except Exception as e:
        print(f"      (fallo: {e})")
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def _p6_ctrl_insert(grilla, cfg) -> str:
    pyperclip.copy("")
    try:
        grilla.click_input()
        time.sleep(0.4)
        grilla.type_keys("^+{END}")
        time.sleep(0.4)
        grilla.type_keys("^{INSERT}")
    except Exception:
        return ""
    time.sleep(cfg.app.espera_ui)
    return pyperclip.paste()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esperadas", type=int, default=0)
    ap.add_argument("--guardar", default="data/copia_deep_ok.tsv")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")
    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")

    grilla = capture_ui.grilla_principal(ventana)
    if grilla is None:
        print("[!] No encontre la grilla. Estas en la pantalla con resultados?")
        return 1
    filas_uia = capture_ui._contar_filas(grilla)
    print(f"Filas segun UIAutomation: {filas_uia} (esperadas: {args.esperadas or '?'})\n")

    pruebas = [
        ("P1 pyautogui (teclas reales)", lambda: _p1_pyautogui(grilla, cfg)),
        ("P2 clic derecho -> Copiar",    lambda: _p2_menu_contextual(grilla, cfg)),
        ("P3 patron UIA seleccion",      lambda: _p3_patron_seleccion(grilla, cfg)),
        ("P4 contenedor gridMst",        lambda: _p4_contenedor(ventana, cfg)),
        ("P5 Shift+clic ultima celda",   lambda: _p5_shift_click(grilla, cfg)),
        ("P6 Ctrl+Insert",               lambda: _p6_ctrl_insert(grilla, cfg)),
    ]

    resultados = []
    mejor, mejor_n = "", 0
    for nombre, fn in pruebas:
        try:
            texto = fn()
        except Exception as e:
            print(f"  {nombre:<32} -> ERROR {e}")
            texto = ""
        n = _lineas(texto)
        resultados.append((nombre, n))
        print(f"  {nombre:<32} -> {n} lineas")
        if n > mejor_n:
            mejor_n, mejor = n, texto
        time.sleep(0.6)

    print("\n=== RESUMEN ===")
    objetivo = args.esperadas or filas_uia
    for nombre, n in sorted(resultados, key=lambda x: -x[1]):
        ok = " OK" if objetivo and n >= objetivo * 0.5 else ""
        print(f"  {n:>6} lineas  {nombre}{ok}")

    if mejor.strip():
        Path(args.guardar).parent.mkdir(parents=True, exist_ok=True)
        Path(args.guardar).write_text(mejor, encoding="utf-8")
        print(f"\nMejor copia: {mejor_n} lineas -> {args.guardar}")

    print("\n>>> PEGA EN EL CHAT la tabla del RESUMEN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
