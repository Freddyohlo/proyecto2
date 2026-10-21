"""Lista las opciones del combo de area (arecod).

SOLO funciona en el PC Windows con Blue Yonder (ya logueado).

Sirve para responder: ¿picking y almacenamiento son AREAS distintas?
Si el combo no expone sus opciones por UIAutomation, la herramienta abre el
desplegable, captura los ListItem visibles, y los imprime.

Uso:
    python tools\\listar_areas.py
"""

from __future__ import annotations

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


def _opciones_abriendo(ventana, combo) -> list[str]:
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
    config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}\n")

    combo = capture_ui._buscar(ventana, COMBO_AREA, control_type="ComboBox")
    if combo is None:
        combo = capture_ui._buscar(ventana, COMBO_AREA)
    if combo is None:
        print(f"[!] No encontre el combo de area {COMBO_AREA!r}. Estas en la pantalla de cuadratura?")
        return 1

    print("[1] Opciones expuestas por el control:")
    directas = _opciones_directas(combo)
    for o in directas:
        print("   -", o)
    if not directas:
        print("   (ninguna)")

    print("\n[2] Abriendo el desplegable para capturar las opciones visibles...")
    abriendo = _opciones_abriendo(ventana, combo)
    for o in abriendo:
        print("   -", o)
    if not abriendo:
        print("   (ninguna; puede que el desplegable no exponga ListItem)")

    print("\n>>> PEGA EN EL CHAT todas las opciones que aparecieron arriba.")
    print(">>> Interesa saber si hay areas de PICKING y de ALMACENAMIENTO por separado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
