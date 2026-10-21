"""Lista las opciones del combo de area (arecod) y vuelca la pantalla de cuadratura.

SOLO funciona en el PC Windows con Blue Yonder (ya logueado).

Hace todo el flujo por si solo:
  1. Busca la ventana principal de Blue Yonder.
  2. NAVEGA EL MENU: Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock.
  3. Muestra las opciones del combo de area (arecod): por API y abriendo el desplegable.
  4. Vuelca la lista COMPLETA de controles de la ventana (para calibrar auto_id).

Uso:
    python tools\\listar_areas.py
    python tools\\listar_areas.py --sin-menu   # no navegar; usar la pantalla actual
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

COMBO_AREA = "arecod"


def _opciones_directas(combo) -> list[str]:
    """Intenta obtener las opciones sin abrir el desplegable (si el control las expone)."""
    opciones = []
    try:
        for item in combo.items():
            try:
                opciones.append(item.text())
            except Exception:
                opciones.append(str(item))
    except Exception:
        pass
    return opciones


def _opciones_abriendo(combo) -> list[str]:
    """Abre el desplegable y recolecta los ListItem visibles en todo el escritorio."""
    from pywinauto import Desktop

    opciones = []
    capture_ui._clic(combo)
    time.sleep(1.5)
    for w in Desktop(backend="uia").windows(top_level_only=False):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type != "ListItem":
                        continue
                    texto = c.window_text().strip()
                    if texto and texto not in opciones:
                        opciones.append(texto)
                except Exception:
                    continue
        except Exception:
            continue
    try:
        combo.type_keys("{ESC}")
    except Exception:
        pass
    return opciones


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-menu", action="store_true",
                    help="No navegar el menu; usar la pantalla actual")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}\n")

    if not args.sin_menu:
        print("[1] Navegando el menu: Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock...")
        try:
            capture_ui.ir_a_ccu_cuadratura(cfg, ventana)
            print("   OK.")
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {e}")

    print("\n[2] Controles de la ventana (auto_id, tipo, texto):")
    for linea in capture_ui.listar_controles(ventana)[:150]:
        print("   ", linea)

    combo = capture_ui._buscar(ventana, COMBO_AREA, control_type="ComboBox")
    if combo is None:
        combo = capture_ui._buscar(ventana, COMBO_AREA)
    if combo is None:
        print(f"\n[!] No encontre el combo de area {COMBO_AREA!r}.")
        return 1

    print("\n[3] Opciones expuestas por el control:")
    directas = _opciones_directas(combo)
    for o in directas:
        print("   -", o)
    if not directas:
        print("   (ninguna)")

    print("\n[4] Abriendo el desplegable para capturar las opciones visibles...")
    abriendo = _opciones_abriendo(combo)
    for o in abriendo:
        print("   -", o)
    if not abriendo:
        print("   (ninguna; puede que el desplegable no exponga ListItem)")

    print("\n>>> PEGA EN EL CHAT todo lo de arriba ([2], [3] y [4]).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
