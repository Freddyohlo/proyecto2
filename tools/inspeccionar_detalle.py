"""Inspecciona la grilla de 'CCU Cuadratura de Stock' con la opcion DETALLE activa.

SOLO funciona en el PC Windows con Blue Yonder (ya logueado).

Hace TODO el flujo por si solo:
  1. Busca la ventana principal de Blue Yonder.
  2. NAVEGA EL MENU: Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock.
  3. Selecciona el area (por defecto "AREA VALORADO"; se puede cambiar con --area).
  4. Marca el checkbox "Detalle" (hld_flg) si esta disponible.
  5. Pulsa "Buscar" y espera resultados.
  6. Vuelca los NOMBRES de columna (HeaderItem) de la grilla, en orden.
  7. Copia la grilla (Ctrl+A/Ctrl+C) y la guarda en data/raw_detalle_<fecha>.tsv
  8. Muestra las primeras 5 filas.

Si algun paso falla, imprime un diagnostico con los controles visibles para
poder ajustar los auto_id.

Uso (en el PC, ya logueado en Blue Yonder; da igual en que pantalla estes):
    python tools\\inspeccionar_detalle.py
    python tools\\inspeccionar_detalle.py --area "AREA VALORADO"
    python tools\\inspeccionar_detalle.py --sin-menu     # no navegar; usar la pantalla actual
    python tools\\inspeccionar_detalle.py --sin-detalle  # no marcar Detalle
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
COMBO_AREA = "arecod"


def diagnostico(ventana, etiqueta: str = "") -> None:
    print(f"\n--- DIAGNOSTICO {etiqueta} (controles clave de la ventana) ---")
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


def _seleccionar_area(ventana, area: str) -> bool:
    """Elige `area` en el combo arecod. Prueba select() y, si falla, abre y elige por texto."""
    combo = capture_ui._buscar(ventana, COMBO_AREA, control_type="ComboBox")
    if combo is None:
        combo = capture_ui._buscar(ventana, COMBO_AREA)
    if combo is None:
        print(f"   [!] No encontre el combo de area {COMBO_AREA!r}.")
        return False
    try:
        combo.select(area)
        print(f"   (area seleccionada por select(): {area!r})")
        time.sleep(1.0)
        return True
    except Exception:
        pass
    try:
        capture_ui._clic(combo)
        time.sleep(1.0)
        opcion = capture_ui._buscar_texto(ventana, area.lower())
        if opcion is None:
            print(f"   [!] No encontre la opcion {area!r} en el desplegable.")
            try:
                combo.type_keys("{ESC}")
            except Exception:
                pass
            return False
        capture_ui._clic(opcion)
        print(f"   (area elegida por clic: {area!r})")
        time.sleep(1.0)
        return True
    except Exception as e:
        print(f"   [!] No pude elegir el area: {e}")
        return False


def _click_detalle(ventana) -> bool:
    """Deja el checkbox 'Detalle' en estado ACTIVO (toggle_state == 1).

    Importante: get_toggle_state() puede devolver 0 (apagado), 1 (encendido) o
    2 (INDETERMINADO). Un '2' NO es 'marcado': hay que hacer clic para llevarlo
    a 1. Este fue el error que dejaba 'Detalle' sin activar de verdad.
    """
    ctrl = capture_ui._buscar(ventana, CHECK_DETALLE, control_type="CheckBox")
    if ctrl is None:
        ctrl = capture_ui._buscar(ventana, CHECK_DETALLE)
    if ctrl is None:
        ctrl = capture_ui._buscar_texto(ventana, "detalle", tipos=("CheckBox",))
    if ctrl is None:
        print(f"   [!] No encontre el checkbox 'Detalle' ({CHECK_DETALLE!r}).")
        return False

    try:
        estado = ctrl.get_toggle_state()
    except Exception as e:
        print(f"   [!] No pude leer el estado de 'Detalle': {e}")
        return False
    print(f"   (estado de 'Detalle': {estado}  [0=off, 1=on, 2=indeterminado])")

    # Estrategias de clic, por si la primera no cambia el estado.
    def _toggle(metodo: str) -> None:
        if metodo == "click_input":
            ctrl.click_input()
        elif metodo == "click":
            ctrl.click()
        elif metodo == "space":
            ctrl.set_focus()
            ctrl.type_keys(" ")
        elif metodo == "mousedown":
            ctrl.set_focus()
            ctrl.type_keys("{SPACE}")

    metodos = ["click_input", "click", "space", "mousedown"]
    for intento, metodo in enumerate(metodos, 1):
        if estado == 1:
            print("   ('Detalle' ACTIVO ✓)")
            return True
        print(f"   (intento {intento}: 'Detalle' no activo -> metodo {metodo!r})")
        try:
            _toggle(metodo)
        except Exception as e:
            print(f"      [!] {metodo} fallo: {e}")
            continue
        time.sleep(1.2)
        try:
            estado = ctrl.get_toggle_state()
        except Exception:
            estado = -1
        print(f"      (estado tras {metodo!r}: {estado})")

    if estado == 1:
        print("   ('Detalle' ACTIVO ✓)")
        return True
    print(f"   [!] No logre dejar 'Detalle' activo (quedo en {estado}).")
    return False


def _prender_detalle_y_verificar(cfg, ventana) -> None:
    """Compara las columnas antes y despues de activar 'Detalle' y pulsa Buscar.

    Esto permite verificar por evidencia (no solo por el toggle_state) si el
    modo Detalle quedo realmente encendido.
    """
    antes = _nombres_columnas(ventana)
    print(f"   columnas ANTES de 'Detalle': {len(antes)}")
    _click_detalle(ventana)
    try:
        capture_ui.pulsar_buscar(cfg, ventana)
        filas = capture_ui.esperar_resultados(cfg, ventana)
        print(f"   filas (DataItem): {filas}")
    except Exception as e:
        print(f"   [!] FALLO al buscar: {e}")
    despues = _nombres_columnas(ventana)
    print(f"   columnas DESPUES de 'Detalle': {len(despues)}")
    if len(despues) > len(antes):
        nuevas = [c for c in despues if c not in antes]
        print(f"   >>> DETALLE ACTIVADO: aparecieron {len(nuevas)} columnas nuevas: {nuevas}")
    else:
        print("   >>> OJO: las columnas no cambiaron; 'Detalle' no surtio efecto.")


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
    ap.add_argument("--area", default="AREA VALORADO", help="Area a seleccionar")
    ap.add_argument("--sin-menu", action="store_true",
                    help="No navegar el menu; usar la pantalla actual")
    ap.add_argument("--sin-detalle", action="store_true", help="No marcar Detalle")
    ap.add_argument("--sin-buscar", action="store_true",
                    help="No pulsar Buscar; solo leer la pantalla actual")
    args = ap.parse_args()

    cfg = config.cargar("config.toml")

    print("Buscando la ventana principal de Blue Yonder...")
    ventana = capture_ui.buscar_ventana_app()
    print(f"Ventana: {ventana.window_text()!r}")
    print(f"Estado actual: {titulo_actual(ventana)}\n")

    # [1] Navegar el menu
    if not args.sin_menu:
        print("[1] Navegando el menu: Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock...")
        try:
            capture_ui.ir_a_ccu_cuadratura(cfg, ventana)
            print(f"   OK. {titulo_actual(ventana)}")
        except Exception as e:
            print(f"   [!] FALLO la navegacion: {type(e).__name__}: {e}")
            diagnostico(ventana, "tras fallar el menu")
            print("\n>>> PEGA TODO ESTO EN EL CHAT (asi veo los nombres reales de los controles).")
            return 1
    else:
        print("[1] Navegacion por menu OMITIDA (--sin-menu).")

    # [2] Seleccionar area
    print(f"\n[2] Seleccionando area {args.area!r} en el combo {COMBO_AREA!r}...")
    if not _seleccionar_area(ventana, args.area):
        diagnostico(ventana, "al elegir area")

    # [3]+[4] Marcar Detalle y buscar, verificando que las columnas cambien
    if not args.sin_detalle and not args.sin_buscar:
        print("\n[3] Activando 'Detalle' y buscando (con verificacion)...")
        _prender_detalle_y_verificar(cfg, ventana)
    else:
        if not args.sin_detalle:
            print("\n[3] Activando 'Detalle'...")
            _click_detalle(ventana)
        else:
            print("\n[3] 'Detalle' OMITIDO (--sin-detalle).")
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
    nombres = _nombres_columnas(ventana)
    if nombres:
        for i, n in enumerate(nombres, 1):
            print(f"   {i:2d}. {n}")
    else:
        print("   [!] No se obtuvieron HeaderItem (la grilla puede no exponer encabezado).")

    # [6] Copiar grilla
    print("\n[6] Copiando la grilla (Ctrl+A/Ctrl+C)...")
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

    print("[7] Primeras 5 filas:")
    for ln in lineas[:5]:
        print("   ", ln)

    print("\n>>> PEGA EN EL CHAT: la lista de columnas ([5]) y las 5 filas ([7]).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
