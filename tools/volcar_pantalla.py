"""Vuelca TODOS los controles de la pantalla actual de Blue Yonder (SOLO Windows).

Herramienta de diagnostico. Sirve para descubrir los auto_id reales de la
pantalla en la que estes, cuando los que tenemos no aparecen.

Uso:
    # Vuelca la ventana 'Soluciones' (la principal)
    python tools\\volcar_pantalla.py

    # Navega primero hasta CCU Cuadratura de Stock y luego vuelca
    python tools\\volcar_pantalla.py --menu

    # Vuelca TODAS las ventanas de nivel superior (incluye menus emergentes)
    python tools\\volcar_pantalla.py --todas

Sugerencia: si un auto_id no aparece, ejecuta esto y pega la salida en el chat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pywinauto import Desktop

from src import capture_ui, config


def volcar(ventana, titulo: str) -> None:
    print(f"\n=== VENTANA: {titulo!r} ===")
    n = 0
    try:
        for c in ventana.descendants():
            try:
                tipo = c.element_info.control_type
                auto_id = c.element_info.automation_id or ""
                texto = c.window_text().replace("\n", " ")[:60]
                n += 1
                print(f"  {tipo:<14} auto_id={auto_id!r:<26} texto={texto!r}")
            except Exception:
                continue
    except Exception as e:
        print("  (no se pudo recorrer:", e, ")")
    print(f"  --- total: {n} controles ---")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--menu", action="store_true",
                    help="Navegar el menu hasta CCU Cuadratura de Stock antes de volcar")
    ap.add_argument("--todas", action="store_true",
                    help="Volcar TODAS las ventanas de nivel superior")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    if args.todas:
        print("Volcando TODAS las ventanas de nivel superior...")
        for w in Desktop(backend="uia").windows(top_level_only=True):
            try:
                volcar(w, w.window_text())
            except Exception:
                continue
        print("\n>>> PEGA TODO ESTO EN EL CHAT.")
        return 0

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")

    if args.menu:
        print("Navegando el menu hasta CCU Cuadratura de Stock...")
        try:
            capture_ui.ir_a_ccu_cuadratura(cfg, ventana)
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {e}")

    volcar(ventana, ventana.window_text())
    print("\n>>> PEGA TODO ESTO EN EL CHAT (busco el auto_id de la grilla y los botones).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
