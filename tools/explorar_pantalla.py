"""Explora CUALQUIER pantalla de Blue Yonder y guarda su grilla (SOLO Windows, ya logueado).

Sirve para descubrir pantallas nuevas sin escribir codigo cada vez: navega por el
menu (o usa la pantalla actual), lista los campos de filtro, los nombres de columna
de la grilla, y copia los datos a un TSV.

Pensado para encontrar la pantalla de MINIMOS Y MAXIMOS (y cualquier otra).

Uso:
    # Navegar por una ruta y explorar
    python tools\\explorar_pantalla.py --ruta "Aplicaciones>Informes/Etiquetas>CCU Cuadratura de Stock"

    # Usar la pantalla en la que ya estas (no navega)
    python tools\\explorar_pantalla.py --sin-menu --nombre minimax

    # Solo listar los items del menu Aplicaciones (para descubrir rutas)
    python tools\\explorar_pantalla.py --listar-menu

El TSV se guarda en data/<nombre>_<fecha>.tsv
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

# Controles de navegacion que no son filtros (se omiten del volcado)
RUIDO_AUTOID = {
    "pnlMenu", "grpMenu", "AppExplorer", "btnPinMenu", "btnFavorites", "btnMenuClose",
    "lblCurAppTitle", "lblCurAppFlow", "tbLocate", "serviceUrl", "btnUserId",
    "btnWarehouseId", "picClientLogo", "picRPLogo", "loginSwitcher", "picLocate",
    "pnlLocate", "pnlBackground", "pnlGradient", "pnlHost", "controlHost",
    "pnlBannerBlue", "pnlBannerBlack", "pnlOpenAppsCntr1", "pnlAppHeader", "mcsToolBar",
}
TIPOS_FILTRO = ("Edit", "ComboBox", "CheckBox", "Button", "Text")


def _titulo(ventana) -> str:
    lbl = capture_ui._buscar(ventana, "lblCurAppTitle")
    flujo = capture_ui._buscar(ventana, "lblCurAppFlow")
    return (f"titulo={(lbl.window_text() if lbl else '?')!r}  "
            f"flujo={(flujo.window_text() if flujo else '?')!r}")


def listar_menu(ventana, cfg) -> None:
    """Abre el menu Aplicaciones y lista sus items (para descubrir rutas)."""
    print("Abriendo el menu 'Aplicaciones'...")
    item = capture_ui._buscar_menuitem("aplicaciones")
    if item is None:
        print("   [!] No encontre 'Aplicaciones' en el menu de arriba.")
        return
    item.click_input()
    time.sleep(cfg.app.espera_ui)
    print("\nItems del menu (MenuItem visibles):")
    from pywinauto import Desktop

    vistos = set()
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type != "MenuItem":
                        continue
                    t = c.window_text().strip()
                    if t and t not in vistos:
                        vistos.add(t)
                        print("   -", t)
                except Exception:
                    continue
        except Exception:
            continue
    try:
        ventana.type_keys("{ESC}")
    except Exception:
        pass


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
            # Omitir botones de navegacion de grilla (sin auto_id y con textos conocidos)
            if tipo == "Button" and not auto_id and texto in (
                "Primero", "Página anterior", "Anterior", "Siguiente",
                "Página siguiente", "Último", "Column Left", "Page Left",
                "Page Right", "Column Right", "Minimizar", "Restaurar", "Cerrar",
            ):
                continue
            print(f"   {tipo:<11} auto_id={auto_id!r:<24} texto={texto!r}")
        except Exception:
            continue


def nombres_columnas(ventana) -> list[str]:
    grilla = capture_ui._buscar(ventana, capture_ui.GRILLA, control_type="Table")
    if grilla is None:
        grilla = capture_ui._buscar(ventana, capture_ui.GRILLA)
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
    ap.add_argument("--ruta", default="", help="Ruta del menu: 'A>B>C'")
    ap.add_argument("--sin-menu", action="store_true", help="No navegar; usar la pantalla actual")
    ap.add_argument("--listar-menu", action="store_true", help="Listar los items del menu Aplicaciones")
    ap.add_argument("--nombre", default="pantalla", help="Nombre para el archivo de salida")
    ap.add_argument("--sin-buscar", action="store_true", help="No pulsar Buscar")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")
    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado: {_titulo(ventana)}\n")

    if args.listar_menu:
        listar_menu(ventana, cfg)
        return 0

    if args.ruta:
        niveles = [n.strip() for n in args.ruta.split(">") if n.strip()]
        ruta = [(n, n.lower()) for n in niveles]
        print(f"[1] Navegando: {' > '.join(niveles)} ...")
        try:
            capture_ui.ir_a_por_menu(cfg, ventana, ruta)
            print(f"   OK. {_titulo(ventana)}")
        except Exception as e:
            print(f"   [!] FALLO: {e}")
            return 1
    else:
        print("[1] Navegacion OMITIDA (pantalla actual).")

    volcar_filtros(ventana)

    print("\n[Columnas] HeaderItem de la grilla, en orden:")
    nombres = nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem.")

    if not args.sin_buscar:
        print("\n[Buscar] Pulsando 'Buscar' y esperando resultados...")
        try:
            capture_ui.pulsar_buscar(cfg, ventana)
            filas = capture_ui.esperar_resultados(cfg, ventana)
            print(f"   filas (DataItem): {filas}")
        except Exception as e:
            print(f"   [!] FALLO al buscar: {e}")

    print("\n[Copiar] Copiando la grilla (Ctrl+A/Ctrl+C)...")
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
    print(f"   Guardado en: {destino}")

    print("\n[Filas] Primeras 8:")
    for ln in lineas[:8]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: filtros, columnas y las primeras 8 filas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
