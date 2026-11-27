"""Explora y captura la pantalla 'CCU Caja Pickeada' (SOLO Windows, ya logueado).

Flujo:
  1. Busca la ventana principal de Blue Yonder.
  2. Navega: Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada.
  3. Activa las casillas de fecha **haciendo clic en los panes** `fecha_desde`
     y `fecha_hasta` (no son CheckBox: son Pane dibujados a mano).
  4. Opcional: escribe la fecha (--fecha) en esos campos.
  5. Pulsa "Buscar" y espera resultados.
  6. Vuelca los NOMBRES de columna (HeaderItem) de la grilla.
  7. Copia la grilla (Ctrl+A/Ctrl+C) y la guarda en data/caja_pickeada_<fecha>.tsv
  8. Muestra las primeras 10 filas.

Uso (en el PC, ya logueado; da igual en que pantalla estes):
    python tools\\inspeccionar_caja_pickeada.py
    python tools\\inspeccionar_caja_pickeada.py --fecha 22/10/2026
    python tools\\inspeccionar_caja_pickeada.py --sin-menu     # usar la pantalla actual
    python tools\\inspeccionar_caja_pickeada.py --sin-buscar   # solo leer lo que hay
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

GRILLA = capture_ui.GRILLA
PANE_DESDE = "fecha_desde"
PANE_HASTA = "fecha_hasta"

RUTA_MENU = [
    ("Aplicaciones", "aplicaciones"),
    ("Informes/Etiquetas", "informes/etiquetas"),
    ("CCU Caja Pickeada", "caja pickeada"),
]


def diagnostico(ventana, etiqueta: str = "") -> None:
    print(f"\n--- DIAGNOSTICO {etiqueta} ---")
    try:
        for linea in capture_ui.listar_controles(ventana)[:120]:
            print("   ", linea)
    except Exception as e:
        print("   (no se pudo listar:", e, ")")


def titulo_actual(ventana) -> str:
    lbl = capture_ui._buscar(ventana, "lblCurAppTitle")
    flujo = capture_ui._buscar(ventana, "lblCurAppFlow")
    t = lbl.window_text() if lbl else "?"
    f = flujo.window_text() if flujo else "?"
    return f"titulo={t!r}  flujo={f!r}"


def navegar(ventana, cfg) -> None:
    try:
        ventana.set_focus()
        time.sleep(0.5)
    except Exception:
        pass
    for nivel, texto in RUTA_MENU:
        item = capture_ui._buscar_menuitem(texto)
        if item is None:
            raise RuntimeError(f"No encontre el MenuItem {nivel!r} en el menu de arriba.")
        item.click_input()
        time.sleep(cfg.app.espera_ui)


def _pane(ventana, auto_id: str):
    """Busca el Pane por auto_id (o por texto si no lo encuentra)."""
    return capture_ui._buscar(ventana, auto_id)


def _clic_pane(ventana, auto_id: str) -> bool:
    """Hace clic en el pane de fecha (eso activa la casilla 'Desde'/'Hasta')."""
    pane = _pane(ventana, auto_id)
    if pane is None:
        print(f"   [!] No encontre el pane {auto_id!r}.")
        return False
    try:
        capture_ui._clic(pane)
        time.sleep(0.8)
        print(f"   (clic en {auto_id!r} -> casilla activada)")
        return True
    except Exception as e:
        print(f"   [!] No pude hacer clic en {auto_id!r}: {e}")
        return False


def _escribir_fecha_pane(ventana, auto_id: str, fecha: str) -> bool:
    """Escribe la fecha en el pane. Estrategia: clic, Ctrl+A, escribir, Tab."""
    pane = _pane(ventana, auto_id)
    if pane is None:
        print(f"   [!] No encontre el pane {auto_id!r}.")
        return False
    try:
        capture_ui._clic(pane)
        time.sleep(0.4)
        pane.type_keys("^a")
        time.sleep(0.2)
        pane.type_keys(fecha)
        time.sleep(0.2)
        pane.type_keys("{TAB}")
        time.sleep(0.4)
        print(f"   (fecha {fecha!r} escrita en {auto_id!r})")
        return True
    except Exception as e:
        print(f"   [!] No pude escribir en {auto_id!r}: {e}")
        return False


def nombres_columnas(ventana) -> list[str]:
    grilla = capture_ui._buscar(ventana, GRILLA, control_type="Table")
    if grilla is None:
        grilla = capture_ui._buscar(ventana, GRILLA)
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
    ap.add_argument("--fecha", default="", help="Fecha a filtrar (ej. 22/10/2026). Vacio = la que ya tenga")
    ap.add_argument("--sin-menu", action="store_true", help="No navegar; usar la pantalla actual")
    ap.add_argument("--sin-buscar", action="store_true", help="No pulsar Buscar")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado actual: {titulo_actual(ventana)}\n")

    if not args.sin_menu:
        print("[1] Navegando: Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada...")
        try:
            navegar(ventana, cfg)
            print(f"   OK. {titulo_actual(ventana)}")
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {type(e).__name__}: {e}")
            diagnostico(ventana, "tras fallar el menu")
            print("\n>>> PEGA TODO ESTO EN EL CHAT.")
            return 1
    else:
        print("[1] Navegacion por menu OMITIDA (--sin-menu).")

    # [2] Activar casillas de fecha (clic en los panes)
    print("\n[2] Activando casillas de fecha (clic en los panes)...")
    print("   (estos panes NO son CheckBox; el check se activa con el clic)")
    _clic_pane(ventana, PANE_DESDE)
    _clic_pane(ventana, PANE_HASTA)

    # [3] Escribir la fecha si se indico
    if args.fecha:
        print(f"\n[3] Escribiendo la fecha {args.fecha!r} en Desde y Hasta...")
        _escribir_fecha_pane(ventana, PANE_DESDE, args.fecha)
        _escribir_fecha_pane(ventana, PANE_HASTA, args.fecha)
    else:
        print("\n[3] Fecha OMITIDA: se usara la que la pantalla tenga por defecto.")

    # [4] Buscar
    if not args.sin_buscar:
        print("\n[4] Pulsando 'Buscar' y esperando resultados...")
        try:
            capture_ui.pulsar_buscar(cfg, ventana)
            filas = capture_ui.esperar_resultados(cfg, ventana)
            print(f"   filas (DataItem): {filas}")
        except Exception as e:
            print(f"   [!] FALLO al buscar: {e}")
            diagnostico(ventana, "al buscar")
    else:
        print("\n[4] 'Buscar' OMITIDO (--sin-buscar).")

    # [5] Columnas
    print("\n[5] Nombres de columna (HeaderItem) de la grilla, en orden:")
    nombres = nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem.")

    # [6] Copiar
    print("\n[6] Copiando la grilla (Ctrl+A/Ctrl+C)...")
    try:
        texto = capture_ui.copiar_grilla(cfg, ventana, filas_esperadas=filas)
    except Exception as e:
        print(f"   [!] No se pudo copiar: {e}")
        return 1
    lineas = texto.splitlines()
    print(f"   OK: {len(lineas)} lineas.")

    Path("data").mkdir(exist_ok=True)
    sufijo = datetime.now().strftime("%Y-%m-%d")
    destino = Path(f"data/caja_pickeada_{sufijo}.tsv")
    destino.write_text(texto, encoding="utf-8")
    print(f"   Guardado en: {destino}\n")

    print("[7] Primeras 10 filas:")
    for ln in lineas[:10]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: las columnas ([5]) y las 10 filas ([7]).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
