"""Prueba la NAVEGACION paso a paso (SOLO en el PC Windows con Blue Yonder).

Asume que YA estas logueado en Blue Yonder (entra a mano). Va ejecutando y
describiendo cada paso, con pausas, para que veas en pantalla que hace.
Si un paso falla, se detiene y muestra que controles hay para diagnosticar.

Uso (en el PC, ya logueado en Blue Yonder):
    python tools\\probar_navegacion.py
    python tools\\probar_navegacion.py --pausa 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config


def paso(n: int, descripcion: str) -> None:
    print(f"\n[PASO {n}] {descripcion}")


def diagnostico(ventana) -> None:
    print("   --- Controles disponibles (primeros 60) ---")
    for linea in capture_ui.listar_controles(ventana)[:60]:
        print("     ", linea)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausa", type=float, default=2.0, help="Segundos de pausa entre pasos")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")
    pausa = args.pausa

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")

    try:
        paso(1, "Menu de arriba: Aplicaciones -> Informes/Etiquetas -> CCU Cuadratura de Stock")
        capture_ui.ir_a_ccu_cuadratura(cfg, ventana)
        time.sleep(pausa)

        paso(2, "Seleccionar 'AREA VALORADO' en el combo de area")
        capture_ui.elegir_area(cfg, ventana)
        time.sleep(pausa)

        paso(3, "Pulsar el boton 'Buscar' y esperar resultados")
        capture_ui.pulsar_buscar(cfg, ventana)
        filas = capture_ui.esperar_resultados(cfg, ventana)
        print(f"   filas en la grilla: {filas}")
        time.sleep(pausa)

        paso(4, "Seleccionar y copiar la grilla (Ctrl+A / Ctrl+C)")
        texto = capture_ui.copiar_grilla(cfg, ventana)
        print(f"   OK: se copiaron {len(texto.splitlines())} lineas.")
        print("   Primeras 3 lineas:")
        for ln in texto.splitlines()[:3]:
            print("     ", ln)

        print("\nTODO OK: la navegacion y la copia funcionan.")
        return 0

    except Exception as e:
        print(f"\nFALLO: {type(e).__name__}: {e}")
        print("\nDiagnostico de la ventana:")
        try:
            diagnostico(ventana)
        except Exception as e2:
            print("   (no se pudo listar:", e2, ")")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
