"""Captura los controles de la pantalla actual (SOLO en el PC Windows).

Sirve para descubrir los auto_id de los menus y botones de Blue Yonder.
Hace una cuenta regresiva y luego vuelca TODAS las ventanas abiertas con sus
controles utiles (botones, items de menu, combos, etc).

Uso (en el PC con Blue Yonder YA logueado):
    python tools\\capturar_pantalla.py            # 8 segundos de espera
    python tools\\capturar_pantalla.py --segundos 15

Durante la cuenta regresiva, abre el menu / pantalla que quieras capturar.
"""

from __future__ import annotations

import argparse
import time

from pywinauto import Desktop

TIPOS_UTILES = {
    "Button", "MenuItem", "Menu", "MenuBar", "ComboBox", "Edit", "CheckBox",
    "RadioButton", "Table", "DataGrid", "List", "ListItem", "Tree", "TreeItem",
    "Tab", "TabItem", "Text", "Pane", "Document", "SplitButton",
}


def volcar_ventana(w, todos_los_tipos: bool = False) -> None:
    print(f"\n=== Ventana: {w.window_text()!r} ===")
    try:
        descendientes = w.descendants()
    except Exception as e:
        print(f"   (no se pudo leer: {e})")
        return

    for c in descendientes:
        try:
            tipo = c.element_info.control_type
        except Exception:
            continue
        if not todos_los_tipos and tipo not in TIPOS_UTILES:
            continue
        try:
            auto_id = c.element_info.automation_id or "-"
        except Exception:
            auto_id = "-"
        try:
            titulo = c.window_text()
        except Exception:
            titulo = ""
        try:
            r = c.rectangle()
            rect = f"L{r.left} T{r.top} R{r.right} B{r.bottom}"
        except Exception:
            rect = ""
        print(f"   {tipo:<12} | auto_id={auto_id!r:<22} | {titulo[:45]!r:<47} | {rect}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=int, default=12, help="Cuenta regresiva antes de capturar")
    ap.add_argument("--todo", action="store_true",
                    help="Muestra TODOS los tipos de control (por defecto, solo los utiles)")
    args = ap.parse_args()

    print(f"Tienes {args.segundos} segundos. ABRE el menu y DEJALO ABIERTO/VISIBLE ahora.")
    for i in range(args.segundos, 0, -1):
        print(f"   {i}...", end="\r", flush=True)
        time.sleep(1)
    print("   Capturando ahora!                    ")

    escritorio = Desktop(backend="uia")
    ventanas = escritorio.windows(top_level_only=True)
    print(f"\nVentanas abiertas: {len(ventanas)}")
    for i, w in enumerate(ventanas):
        try:
            texto = w.window_text()
        except Exception:
            texto = "<sin titulo>"
        print(f"  [{i}] {texto!r}")

    print("\n########## CONTROLES DE CADA VENTANA ##########")
    for w in ventanas:
        # Se incluyen tambien las ventanas sin titulo: los menus emergentes
        # (popups) suelen no tener titulo y es donde estan los MenuItem.
        volcar_ventana(w, todos_los_tipos=args.todo)

    print("\n########## FIN ##########")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
