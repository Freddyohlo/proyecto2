"""Explora la pantalla 'CCU Caja Pickeada' y guarda su grilla.

SOLO funciona en el PC Windows con Blue Yonder (ya logueado).

Hace TODO el flujo por si solo:
  1. Busca la ventana principal de Blue Yonder.
  2. NAVEGA EL MENU: Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada.
  3. Vuelca los controles de FILTRO (para descubrir el campo de fecha).
  4. Opcional: escribe una fecha en el campo de fecha (--fecha).
  5. Pulsa "Buscar" y espera resultados.
  6. Vuelca los NOMBRES de columna (HeaderItem) de la grilla, en orden.
  7. Copia la grilla (Ctrl+A/Ctrl+C) y la guarda en data/caja_pickeada_<fecha>.tsv
  8. Muestra las primeras 8 filas.

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

# Textos para navegar el menu (se buscan como MenuItem por texto, sin distinguir mayusculas)
RUTA_MENU = [
    ("Aplicaciones", "aplicaciones"),
    ("Informes/Etiquetas", "informes/etiquetas"),
    ("CCU Caja Pickeada", "caja pickeada"),
]

# auto_id de controles que NO son filtros (para excluirlos del volcado)
NO_FILTRO = {"pnlMenu", "grpMenu", "AppExplorer", "btnPinMenu", "btnFavorites",
             "btnMenuClose", "lblCurAppTitle", "lblCurAppFlow"}


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
    """Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada (por texto de MenuItem)."""
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


def volcar_filtros(ventana) -> None:
    """Muestra los controles de filtro (Edit/ComboBox/Button) que no son del menu."""
    print("\n[3] Controles de FILTRO de la pantalla (busca aqui el campo de fecha):")
    for c in ventana.descendants():
        try:
            tipo = c.element_info.control_type
            if tipo not in ("Edit", "ComboBox", "CheckBox", "Button", "Text"):
                continue
            auto_id = c.element_info.automation_id or ""
            if auto_id in NO_FILTRO:
                continue
            texto = c.window_text().replace("\n", " ")[:50]
            print(f"   {tipo:<12} auto_id={auto_id!r:<26} texto={texto!r}")
        except Exception:
            continue


def escribir_fecha(ventana, fecha: str) -> bool:
    """Intenta escribir la fecha en el primer campo Edit con pinta de fecha.

    Estrategia: buscar Edits cuyo auto_id contenga 'dat', 'fec', 'date', 'dt';
    si no hay, probar el primer Edit que no sea un filtro conocido.
    """
    candidatos = []
    for c in ventana.descendants():
        try:
            if c.element_info.control_type != "Edit":
                continue
            auto_id = (c.element_info.automation_id or "").lower()
            candidatos.append((auto_id, c))
        except Exception:
            continue
    if not candidatos:
        print("   [!] No encontre campos Edit para la fecha.")
        return False

    palabras = ("dat", "fec", "date", "dt", "hora", "time")
    elegido = None
    for auto_id, c in candidatos:
        if any(p in auto_id for p in palabras):
            elegido = (auto_id, c)
            break
    if elegido is None:
        print(f"   [!] No identifique un campo de fecha entre: {[a for a, _ in candidatos]}")
        print("       Usa --sin-buscar y escribe la fecha a mano para ver el resultado.")
        return False

    auto_id, c = elegido
    try:
        c.set_focus()
        c.set_text(fecha)
        print(f"   (fecha {fecha!r} escrita en el campo {auto_id!r})")
        return True
    except Exception as e:
        print(f"   [!] No pude escribir la fecha en {auto_id!r}: {e}")
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
    ap.add_argument("--fecha", default="", help="Fecha a filtrar (ej. 22/10/2026)")
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

    # [2] Fecha
    if args.fecha:
        print(f"\n[2] Escribiendo la fecha {args.fecha!r}...")
        escribir_fecha(ventana, args.fecha)

    # [3] Volcar filtros
    volcar_filtros(ventana)

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
        texto = capture_ui.copiar_grilla(cfg, ventana)
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

    print("[7] Primeras 8 filas:")
    for ln in lineas[:8]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: los filtros ([3]), las columnas ([5]) y las 8 filas ([7]).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
