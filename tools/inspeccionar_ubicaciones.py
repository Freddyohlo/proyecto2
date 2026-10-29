"""Explora 'Configuracion del sistema > Instalacion > Mantenimiento de ubicaciones'.

SOLO Windows, ya logueado. Esta pantalla trae el detalle de las ubicaciones
(minimos/maximos por ubicacion) y es alternativa a 'Operaciones de reabastecimiento'.

Ruta: Aplicaciones > Configuracion del sistema > Instalacion > Mantenimiento de ubicaciones
Luego: pulsar "Buscar".

Uso:
    python tools\\inspeccionar_ubicaciones.py
    python tools\\inspeccionar_ubicaciones.py --sin-menu     # usar la pantalla actual
    python tools\\inspeccionar_ubicaciones.py --nombre ubicaciones
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config

# Ruta confirmada por el usuario (2026-10-29)
RUTA = [
    ("Aplicaciones", "aplicaciones"),
    ("Configuracion del sistema", "configuraci"),
    ("Instalacion", "instalaci"),
    ("Mantenimiento de ubicaciones", "mantenimiento de ubicaciones"),
]

RUIDO_AUTOID = {
    "pnlMenu", "grpMenu", "AppExplorer", "btnPinMenu", "btnFavorites", "btnMenuClose",
    "lblCurAppTitle", "lblCurAppFlow", "tbLocate", "serviceUrl", "btnUserId",
    "btnWarehouseId", "picClientLogo", "picRPLogo", "loginSwitcher", "picLocate",
    "pnlLocate", "pnlBackground", "pnlGradient", "pnlHost", "controlHost",
    "pnlBannerBlue", "pnlBannerBlack", "pnlOpenAppsCntr1", "pnlAppHeader", "mcsToolBar",
}
TIPOS_FILTRO = ("Edit", "ComboBox", "CheckBox", "Button", "Text")


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
    grilla = capture_ui.grilla_principal(ventana)
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
    ap.add_argument("--nombre", default="ubicaciones", help="Nombre del TSV de salida")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado: {titulo_actual(ventana)}\n")

    if not args.sin_menu:
        print("[1] Navegando: Aplicaciones > Configuracion del sistema > "
              "Instalacion > Mantenimiento de ubicaciones...")
        try:
            capture_ui.ir_a_por_menu(cfg, ventana, RUTA)
            print(f"   OK. {titulo_actual(ventana)}")
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {type(e).__name__}: {e}")
            try:
                for linea in capture_ui.listar_controles(ventana)[:120]:
                    print("   ", linea)
            except Exception:
                pass
            return 1
    else:
        print("[1] Navegacion por menu OMITIDA (--sin-menu).")

    volcar_filtros(ventana)
    filas = 0

    if not args.sin_buscar:
        print("\n[2] Pulsando 'Buscar' y esperando resultados...")
        try:
            capture_ui.pulsar_buscar(cfg, ventana)
            filas = capture_ui.esperar_resultados(cfg, ventana)
            print(f"   filas (DataItem): {filas}")
        except Exception as e:
            print(f"   [!] FALLO al buscar: {e}")
    else:
        print("\n[2] 'Buscar' OMITIDO (--sin-buscar).")

    print("\n[3] Nombres de columna (HeaderItem) de la grilla, en orden:")
    nombres = nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem.")

    print("\n[4] Extrayendo/copiando la grilla...")
    try:
        texto = capture_ui.copiar_grilla(cfg, ventana, filas_esperadas=filas)
    except Exception as e:
        print(f"   [!] No se pudo extraer: {e}")
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
