"""Herramienta de calibracion de la UI (SOLO en el PC Windows con Blue Yonder).

Sirve para descubrir los identificadores (auto_id) de los controles que usaremos
en capture_ui.py.

Uso:
  # 1) Lista TODAS las ventanas abiertas con su numero
  python tools\\inspeccionar_ui.py --listar

  # 2) Inspecciona la ventana numero 2 (el numero sale del paso 1)
  python tools\\inspeccionar_ui.py --ventana 2

  # 3) Inspecciona la ventana numero 2 mostrando TODOS los controles (volcado largo)
  python tools\\inspeccionar_ui.py --ventana 2 --todo

Sugerencia: ejecuta primero --listar, identifica el numero de la ventana de
Blue Yonder (login) y luego usa --ventana N.
"""

from __future__ import annotations

import argparse

from pywinauto import Desktop

# Tipos de control que nos interesan para automatizar
TIPOS_CLAVE = {
    "Edit", "Button", "CheckBox", "RadioButton", "ComboBox",
    "Table", "DataGrid", "List", "ListItem", "Tree", "TreeItem",
    "MenuItem", "TabItem", "Document", "Text",
}


def listar_ventanas(escritorio: Desktop) -> list:
    ventanas = escritorio.windows(top_level_only=True)
    print(f"Total de ventanas de nivel superior: {len(ventanas)}")
    for i, w in enumerate(ventanas):
        try:
            texto = w.window_text()
            clase = w.element_info.control_type if hasattr(w, "element_info") else "?"
        except Exception:
            texto, clase = "<error>", "?"
        print(f"  [{i}] ({clase}) {texto!r}")
    return ventanas


def volcar_controles(ventana, todo: bool) -> None:
    ventana.wait("exists ready", timeout=30)
    if todo:
        ventana.print_control_identifiers(depth=6)
        return

    print("\n--- Controles clave (Edit / Button / Table / etc.) ---")
    print("Busca aqui el auto_id de los campos de usuario, clave y de la grilla.\n")
    try:
        descendientes = ventana.descendants()
    except Exception as e:
        print(f"No se pudieron leer los descendientes: {e}")
        return

    for c in descendientes:
        try:
            tipo = c.element_info.control_type
        except Exception:
            tipo = "?"
        if tipo not in TIPOS_CLAVE:
            continue
        try:
            auto_id = c.element_info.automation_id or ""
        except Exception:
            auto_id = ""
        try:
            titulo = c.window_text()
        except Exception:
            titulo = ""
        rect = c.rectangle()
        print(f"  {tipo:<12} auto_id={auto_id!r:<28} titulo={titulo[:40]!r:<44} "
              f"L{rect.left} T{rect.top} R{rect.right} B{rect.bottom}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true", help="Lista todas las ventanas y termina")
    ap.add_argument("--ventana", type=int, default=None, help="Numero de ventana a inspeccionar")
    ap.add_argument("--todo", action="store_true", help="Volcado completo de controles")
    args = ap.parse_args()

    escritorio = Desktop(backend="uia")
    ventanas = listar_ventanas(escritorio)

    if args.listar or args.ventana is None:
        if args.ventana is None:
            print("\nAhora ejecuta:  python tools\\inspeccionar_ui.py --ventana N")
        return 0

    if not (0 <= args.ventana < len(ventanas)):
        print(f"Numero de ventana invalido. Debe estar entre 0 y {len(ventanas) - 1}.")
        return 1

    ventana = ventanas[args.ventana]
    print(f"\n=== Inspeccionando [{args.ventana}]: {ventana.window_text()!r} ===")
    volcar_controles(ventana, args.todo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
