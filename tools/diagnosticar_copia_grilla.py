"""Diagnostica QUE metodo copia la grilla completa (SOLO Windows, ya logueado).

Asume que YA estas en la pantalla con resultados (ej. 'Operaciones de
reabastecimiento' tras pulsar Buscar). Prueba cada metodo de copiado por separado
y reporta cuantas lineas trajo cada uno, para quedarnos con el que funciona.

Uso:
    python tools\\diagnosticar_copia_grilla.py
    python tools\\diagnosticar_copia_grilla.py --esperadas 1122
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyperclip

from src import capture_ui, config

# (nombre, requiere clic en 1a celda, teclas antes del Ctrl+C)
METODOS = [
    ("A: HOME + Ctrl+A",            False, "{HOME}|^a"),
    ("B: Ctrl+A",                   False, "^a"),
    ("C: clic 1a celda + Ctrl+A",   True,  "^a"),
    ("D: clic 1a celda + Ctrl+Sh+End", True, "^+{END}"),
    ("E: HOME + Ctrl+Shift+End",    True,  "{HOME}|^+{END}"),
    ("F: Ctrl+A x2",                False, "^a|^a"),
    ("G: solo Ctrl+C",              False, ""),
    ("H: Ctrl+Sh+End + Enter + Ctrl+A", True, "^+{END}|{ENTER}|^a"),
]


def _probar(grilla, cfg, nombre, primera_celda, secuencia) -> tuple[int, str]:
    pyperclip.copy("")
    try:
        if primera_celda:
            grilla.click_input(coords=(10, 10))
        else:
            grilla.click_input()
        time.sleep(0.4)
        for tecla in secuencia.split("|"):
            if tecla:
                grilla.type_keys(tecla)
                time.sleep(0.35)
        grilla.type_keys("^c")
    except Exception as e:
        return -1, f"error: {e}"
    time.sleep(cfg.app.espera_ui)
    texto = pyperclip.paste()
    return len(texto.splitlines()), texto


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esperadas", type=int, default=0, help="Filas esperadas (opcional)")
    ap.add_argument("--guardar", default="data/copia_ok.tsv", help="Donde guardar la mejor copia")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")

    grilla = capture_ui.grilla_principal(ventana)
    if grilla is None:
        print("[!] No encontre la grilla. Estas en la pantalla con resultados?")
        return 1

    # Cuantas filas tiene la grilla segun UIAutomation
    filas_uia = capture_ui._contar_filas(grilla)
    print(f"Filas segun UIAutomation: {filas_uia} (esperadas: {args.esperadas or '?'})\\n")

    resultados = []
    mejor_texto = ""
    mejor_lineas = 0
    for nombre, primera, secuencia in METODOS:
        lineas, texto = _probar(grilla, cfg, nombre, primera, secuencia)
        resultados.append((nombre, lineas))
        print(f"  {nombre:<36} -> {lineas} lineas")
        if lineas > mejor_lineas:
            mejor_lineas, mejor_texto = lineas, texto
        time.sleep(0.5)

    print("\\n=== RESUMEN ===")
    objetivo = args.esperadas or filas_uia
    for nombre, lineas in sorted(resultados, key=lambda x: -x[1]):
        marca = "  <-- MEJOR" if lineas == mejor_lineas else ""
        ok = " OK" if objetivo and lineas >= objetivo * 0.5 else ""
        print(f"  {lineas:>6} lineas  {nombre}{marca}{ok}")

    if mejor_texto.strip():
        Path(args.guardar).parent.mkdir(parents=True, exist_ok=True)
        Path(args.guardar).write_text(mejor_texto, encoding="utf-8")
        print(f"\\nMejor copia guardada en: {args.guardar} ({mejor_lineas} lineas)")
        print("Primeras 3 lineas:")
        for ln in mejor_texto.splitlines()[:3]:
            print("   ", ln)

    print("\\n>>> PEGA EN EL CHAT la tabla del RESUMEN (me dice que metodo usar).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
