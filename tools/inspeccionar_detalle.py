"""Inspecciona la grilla de 'CCU Cuadratura de Stock' con la opcion DETALLE activa.

SOLO funciona en el PC Windows con Blue Yonder.

Objetivo: descubrir los nombres REALES de las columnas cuando se activa el
checkbox "Detalle" (hld_flg), que despliega lote, vencimiento, tipo de area, etc.

Hace:
  1. Se conecta a la ventana principal de Blue Yonder (ya logueado a mano).
  2. Marca el checkbox "Detalle" (hld_flg) si esta disponible.
  3. Pulsa "Buscar" y espera resultados.
  4. Vuelca los NOMBRES de columna (HeaderItem) de la grilla, en orden.
  5. Copia la grilla (Ctrl+A/Ctrl+C) y guarda el TSV en data/raw_detalle_<fecha>.tsv
  6. Muestra las primeras 5 filas para ver el contenido.

Uso (en el PC, ya logueado y en la pantalla de la cuadratura):
    python tools\\inspeccionar_detalle.py
    python tools\\inspeccionar_detalle.py --sin-buscar   # solo lee lo que ya esta en pantalla
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

CHECK_DETALLE = "hld_flg"


def _click_detalle(ventana) -> bool:
    """Marca el checkbox 'Detalle'. Devuelve True si lo encontro y lo dejo marcado."""
    ctrl = capture_ui._buscar(ventana, CHECK_DETALLE, control_type="CheckBox")
    if ctrl is None:
        ctrl = capture_ui._buscar(ventana, CHECK_DETALLE)
    if ctrl is None:
        print(f"   [!] No encontre el checkbox {CHECK_DETALLE!r} ('Detalle').")
        return False
    try:
        estado = ctrl.get_toggle_state()
        print(f"   (estado previo de 'Detalle': {estado})")
        if estado == 0:
            capture_ui._clic(ctrl)
            time.sleep(1.0)
            print("   (marcado 'Detalle')")
        else:
            print("   ('Detalle' ya estaba marcado)")
        return True
    except Exception as e:
        print(f"   [!] No pude togglear 'Detalle': {e}")
        return False


def _nombres_columnas(ventana) -> list[str]:
    """Devuelve el texto de cada HeaderItem de la grilla, en orden."""
    grilla = capture_ui._buscar(ventana, capture_ui.GRILLA, control_type="Table")
    if grilla is None:
        grilla = capture_ui._buscar(ventana, capture_ui.GRILLA)
    if grilla is None:
        print("   [!] No encontre la grilla.")
        return []
    nombres = []
    for c in grilla.descendants():
        try:
            if c.element_info.control_type != "HeaderItem":
                continue
            texto = c.window_text().strip()
            if texto:
                nombres.append(texto)
        except Exception:
            continue
    return nombres


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-buscar", action="store_true",
                    help="No marcar Detalle ni pulsar Buscar; solo leer la pantalla actual")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}\n")

    if not args.sin_buscar:
        print("[1] Marcando 'Detalle'...")
        _click_detalle(ventana)
        print("\n[2] Pulsando 'Buscar' y esperando resultados...")
        capture_ui.pulsar_buscar(cfg, ventana)
        filas = capture_ui.esperar_resultados(cfg, ventana)
        print(f"   filas (DataItem): {filas}")

    print("\n[3] Nombres de columna (HeaderItem) de la grilla, en orden:")
    nombres = _nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem (la grilla puede no tener encabezado expuesto).")

    print("\n[4] Copiando la grilla (Ctrl+A/Ctrl+C)...")
    try:
        texto = capture_ui.copiar_grilla(cfg, ventana)
    except Exception as e:
        print(f"   [!] No se pudo copiar: {e}")
        return 1
    lineas = texto.splitlines()
    print(f"   OK: {len(lineas)} lineas, {len(nombres) or '?'} columnas esperadas.")

    Path("data").mkdir(exist_ok=True)
    destino = Path(f"data/raw_detalle_{datetime.now():%Y-%m-%d}.tsv")
    destino.write_text(texto, encoding="utf-8")
    print(f"   Guardado en: {destino}\n")

    print("[5] Primeras 5 filas:")
    for ln in lineas[:5]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: la lista de columnas ([3]) y las 5 filas ([5]).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
