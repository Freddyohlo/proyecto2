"""Inspeccion PROFUNDA de 'CCU Caja Pickeada' (SOLO Windows, ya logueado).

Objetivo: encontrar las CASILLAS (checkbox) "Desde" y "Hasta" que hay que
activar para poder filtrar por fecha, y entender el panel de CRITERIOS.

Diferencia con inspeccionar_caja_pickeada.py: aqui NO se filtra por tipo, se
vuelca TODO (incluidos controles ocultos) con visibilidad, habilitado y posicion.
Ademas, opcionalmente pulsa 'btnExpand' para desplegar el panel de criterios.

Uso:
    python tools\\inspeccionar_caja_pickeada_deep.py
    python tools\\inspeccionar_caja_pickeada_deep.py --expandir
    python tools\\inspeccionar_caja_pickeada_deep.py --solo-checkbox
    python tools\\inspeccionar_caja_pickeada_deep.py --sin-menu   # usar pantalla actual
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

RUTA_MENU = [
    ("Aplicaciones", "aplicaciones"),
    ("Informes/Etiquetas", "informes/etiquetas"),
    ("CCU Caja Pickeada", "caja pickeada"),
]

# Tipos de control que casi siempre son ruido de navegacion
RUIDO = {"ScrollBar", "Thumb", "TitleBar", "MenuBar", "StatusBar", "Separator"}


def navegar(ventana, cfg) -> None:
    try:
        ventana.set_focus()
        time.sleep(0.5)
    except Exception:
        pass
    for nivel, texto in RUTA_MENU:
        item = capture_ui._buscar_menuitem(texto)
        if item is None:
            raise RuntimeError(f"No encontre el MenuItem {nivel!r}.")
        item.click_input()
        time.sleep(cfg.app.espera_ui)


def _estado(ctrl) -> str:
    vis = hab = "?"
    try:
        vis = "V" if ctrl.is_visible() else "-"
    except Exception:
        pass
    try:
        hab = "H" if ctrl.is_enabled() else "-"
    except Exception:
        pass
    return f"{vis}{hab}"


def volcar(ventana, solo_checkbox: bool) -> None:
    print("\n=== TODOS los controles (V=visible, H=habilitado) ===")
    total = 0
    por_tipo: dict[str, int] = {}
    for c in ventana.descendants():
        try:
            tipo = c.element_info.control_type
        except Exception:
            continue
        if tipo in RUIDO:
            continue
        if solo_checkbox and tipo != "CheckBox":
            continue
        try:
            auto_id = c.element_info.automation_id or ""
            texto = c.window_text().replace("\n", " ")[:50]
            estado = _estado(c)
            rect = c.rectangle()
            total += 1
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
            print(f"  [{estado}] {tipo:<12} auto_id={auto_id!r:<24} texto={texto!r:<52} "
                  f"L{rect.left} T{rect.top}")
        except Exception:
            continue
    print(f"\n  --- total: {total} controles ---")
    print("  --- por tipo: " + ", ".join(f"{k}={v}" for k, v in sorted(por_tipo.items())))


def volcar_checkboxes(ventana) -> None:
    print("\n=== SOLO CheckBox (incluye ocultos) ===")
    n = 0
    for c in ventana.descendants():
        try:
            if c.element_info.control_type != "CheckBox":
                continue
            auto_id = c.element_info.automation_id or ""
            texto = c.window_text().replace("\n", " ")[:60]
            estado = _estado(c)
            try:
                toggle = c.get_toggle_state()
            except Exception:
                toggle = "?"
            rect = c.rectangle()
            n += 1
            print(f"  [{estado}] auto_id={auto_id!r:<22} texto={texto!r:<52} "
                  f"toggle={toggle} L{rect.left} T{rect.top}")
        except Exception:
            continue
    if n == 0:
        print("  (no hay CheckBox accesibles; puede que el panel este colapsado -> usa --expandir)")
    else:
        print(f"  --- total: {n} CheckBox ---")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-menu", action="store_true", help="No navegar; usar la pantalla actual")
    ap.add_argument("--expandir", action="store_true", help="Pulsar 'btnExpand' para abrir el panel")
    ap.add_argument("--solo-checkbox", action="store_true", help="Mostrar solo los CheckBox")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}\n")

    if not args.sin_menu:
        print("[1] Navegando: Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada...")
        try:
            navegar(ventana, cfg)
            print("   OK.")
        except Exception as e:
            print(f"   [!] FALLO: {e}")
            return 1
    else:
        print("[1] Navegacion OMITIDA (--sin-menu).")

    if args.expandir:
        print("\n[2] Pulsando 'btnExpand' para desplegar el panel de criterios...")
        boton = capture_ui._buscar(ventana, "btnExpand")
        if boton is None:
            boton = capture_ui._buscar_texto(ventana, "expandir", tipos=("Button",))
        if boton is None:
            print("   [!] No encontre 'btnExpand'.")
        else:
            try:
                capture_ui._clic(boton)
                time.sleep(1.5)
                print("   (panel desplegado)")
            except Exception as e:
                print(f"   [!] No pude pulsar btnExpand: {e}")

    volcar_checkboxes(ventana)
    if not args.solo_checkbox:
        volcar(ventana, solo_checkbox=False)

    print("\n>>> PEGA EN EL CHAT la seccion '=== SOLO CheckBox ==='.")
    print(">>> Busco las casillas 'Desde' y 'Hasta' para poder filtrar por fecha.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
