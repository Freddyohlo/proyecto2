"""Explora la pantalla 'Opciones de reabastecimiento' (minimos/maximos).

SOLO funciona en el PC Windows con Blue Yonder (ya logueado).

Ruta del menu (indicada por el usuario):
    Aplicaciones > Reabastecimiento > Opciones de reabastecimiento
Luego: pulsar "Buscar" y sale la grilla con la informacion.

Hace TODO el flujo por si solo:
  1. Busca la ventana principal de Blue Yonder.
  2. NAVEGA EL MENU: Aplicaciones > Reabastecimiento > Opciones de reabastecimiento.
  3. Vuelca los controles de FILTRO de la pantalla.
  4. Pulsa "Buscar" y espera resultados.
  5. Vuelca los NOMBRES de columna (HeaderItem) de la grilla, en orden.
  6. Copia la grilla (Ctrl+A/Ctrl+C) y la guarda en data/reabastecimiento_<fecha>.tsv
  7. Muestra las primeras 10 filas.

Uso (en el PC, ya logueado; da igual en que pantalla estes):
    python tools\\inspeccionar_reabastecimiento.py
    python tools\\inspeccionar_reabastecimiento.py --sin-menu     # usar la pantalla actual
    python tools\\inspeccionar_reabastecimiento.py --sin-buscar   # solo leer lo que hay
    python tools\\inspeccionar_reabastecimiento.py --nombre minmax
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

# Ruta confirmada por el usuario
RUTA_MENU = [
    ("Aplicaciones", "aplicaciones"),
    ("Reabastecimiento", "reabastecimiento"),
    ("Opciones de reabastecimiento", "opciones de reabastecimiento"),
]

# Controles de navegacion que no son filtros (se omiten del volcado)
RUIDO_AUTOID = {
    "pnlMenu", "grpMenu", "AppExplorer", "btnPinMenu", "btnFavorites", "btnMenuClose",
    "lblCurAppTitle", "lblCurAppFlow", "tbLocate", "serviceUrl", "btnUserId",
    "btnWarehouseId", "picClientLogo", "picRPLogo", "loginSwitcher", "picLocate",
    "pnlLocate", "pnlBackground", "pnlGradient", "pnlHost", "controlHost",
    "pnlBannerBlue", "pnlBannerBlack", "pnlOpenAppsCntr1", "pnlAppHeader", "mcsToolBar",
}
TIPOS_FILTRO = ("Edit", "ComboBox", "CheckBox", "Button", "Text")


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
    return (f"titulo={(lbl.window_text() if lbl else '?')!r}  "
            f"flujo={(flujo.window_text() if flujo else '?')!r}")


def volcar_filtros(ventana) -> None:
    print("\n[Filtros] Controles utiles de la pantalla:")
    for c in ventana.descendants():
        try:
            tipo = c.element_info.control_type
            if tipo not in TIPOS_FILTRO:
                continue
            auto_id = c.element_info.automation_id or ""
            if auto_id in RUIDO_AUTOID:
                continue
            texto = c.window_text().replace("\n", " ")[:46]
            # Omitir botones de navegacion de grilla (sin auto_id, textos conocidos)
            if tipo == "Button" and not auto_id and texto in (
                "Primero", "Página anterior", "Anterior", "Siguiente",
                "Página siguiente", "Último", "Column Left", "Page Left",
                "Page Right", "Column Right", "Minimizar", "Restaurar", "Cerrar",
                "Reg. anterior", "Reg. siguiente", "Actualizar", "Cuadrícula",
            ):
                continue
            print(f"   {tipo:<11} auto_id={auto_id!r:<24} texto={texto!r}")
        except Exception:
            continue


def nombres_columnas(ventana) -> list[str]:
    grilla = capture_ui._buscar(ventana, GRILLA, control_type="Table")
    if grilla is None:
        grilla = capture_ui._buscar(ventana, GRILLA)
    if grilla is None:
        return []
    nombres = []
    for c in grilla.descendants():
        try:
            if c.element_info.control_type != "HeaderItem":
                continue
            t = c.window_text().strip()
            if t:
                nombres.append(t)
        except Exception:
            continue
    return nombres


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-menu", action="store_true", help="No navegar; usar la pantalla actual")
    ap.add_argument("--sin-buscar", action="store_true", help="No pulsar Buscar")
    ap.add_argument("--nombre", default="reabastecimiento", help="Nombre del TSV de salida")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado: {titulo_actual(ventana)}\n")

    if not args.sin_menu:
        print("[1] Navegando: Aplicaciones > Reabastecimiento > Opciones de reabastecimiento...")
        try:
            capture_ui.ir_a_por_menu(cfg, ventana, RUTA_MENU)
            print(f"   OK. {titulo_actual(ventana)}")
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {type(e).__name__}: {e}")
            diagnostico(ventana, "tras fallar el menu")
            print("\n>>> PEGA TODO ESTO EN EL CHAT.")
            return 1
    else:
        print("[1] Navegacion por menu OMITIDA (--sin-menu).")

    volcar_filtros(ventana)

    if not args.sin_buscar:
        print("\n[2] Pulsando 'Buscar' y esperando resultados...")
        try:
            capture_ui.pulsar_buscar(cfg, ventana)
            filas = capture_ui.esperar_resultados(cfg, ventana)
            print(f"   filas (DataItem): {filas}")
        except Exception as e:
            print(f"   [!] FALLO al buscar: {e}")
            diagnostico(ventana, "al buscar")
    else:
        print("\n[2] 'Buscar' OMITIDO (--sin-buscar).")

    print("\n[3] Nombres de columna (HeaderItem) de la grilla, en orden:")
    nombres = nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem.")

    print("\n[4] Copiando la grilla (Ctrl+A/Ctrl+C)...")
    try:
        texto = capture_ui.copiar_grilla(cfg, ventana)
    except Exception as e:
        print(f"   [!] No se pudo copiar: {e}")
        return 1
    lineas = texto.splitlines()
    print(f"   OK: {len(lineas)} lineas.")

    Path("data").mkdir(exist_ok=True)
    destino = Path(f"data/{args.nombre}_{datetime.now():%Y-%m-%d}.tsv")
    destino.write_text(texto, encoding="utf-8")
    print(f"   Guardado en: {destino}\n")

    print("[5] Primeras 10 filas:")
    for ln in lineas[:10]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: filtros, columnas y las 10 filas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
