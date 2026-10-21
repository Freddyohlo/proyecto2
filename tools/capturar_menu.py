"""Captura TODO lo que aparece al abrir el menu de las tres barritas.

Vigila la pantalla durante N segundos y acumula TODOS los controles de la ventana
'Soluciones' y de las ventanas emergentes (los menus dibujados a mano aparecen
como Button, no como MenuItem). Asi se atrapan los items del menu.

Uso (en el PC con Blue Yonder logueado):
    python tools\\capturar_menu.py --segundos 25

Durante esos segundos: abre las tres barritas y navega por los submenus,
pasando por 'Informes/Etiquetas' -> 'CCU Cuadratura de Stock'.

El resultado se guarda en: data\\menu_capturado.txt
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from pywinauto import Desktop

# Tipos que suelen representar items de menu o botones en menus dibujados a mano.
TIPOS = {
    "MenuItem", "Menu", "MenuBar", "Button", "SplitButton", "ListItem",
    "TreeItem", "TabItem", "Text", "Pane",
}


def recolectar() -> dict[str, str]:
    """Items visibles ahora en la ventana Soluciones y en popups sin titulo."""
    encontrados: dict[str, str] = {}
    try:
        ventanas = Desktop(backend="uia").windows(top_level_only=True)
    except Exception:
        return encontrados

    for w in ventanas:
        try:
            titulo_ventana = w.window_text()
        except Exception:
            titulo_ventana = "<sin titulo>"

        # Nos interesan la ventana de la app y los popups (normalmente sin titulo).
        es_app = "Soluciones" in titulo_ventana
        es_popup = titulo_ventana.strip() == ""
        if not (es_app or es_popup):
            continue

        try:
            elementos = w.descendants()
        except Exception:
            continue

        for c in elementos:
            try:
                tipo = c.element_info.control_type
                if tipo not in TIPOS:
                    continue
                texto = c.window_text()
                if not texto.strip():
                    continue
                auto_id = c.element_info.automation_id or "-"
                try:
                    r = c.rectangle()
                    rect = f"L{r.left} T{r.top}"
                except Exception:
                    rect = ""
            except Exception:
                continue

            clave = f"{titulo_ventana}|{tipo}|{auto_id}|{texto}"
            encontrados[clave] = (
                f"[{titulo_ventana[:20]!r}] {tipo:<10} auto_id={auto_id!r:<14} "
                f"{texto[:55]!r:<57} {rect}"
            )
    return encontrados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=int, default=25)
    args = ap.parse_args()

    print(f"Vigilando durante {args.segundos} segundos.")
    print("AHORA: abre las tres barritas y navega hasta 'Informes/Etiquetas'"
          " -> 'CCU Cuadratura de Stock'. Deja los submenus visibles.\n")

    acumulado: dict[str, str] = {}
    fin = time.time() + args.segundos
    while time.time() < fin:
        acumulado.update(recolectar())
        restante = max(0, int(fin - time.time()))
        print(f"   capturando... quedan {restante}s (items: {len(acumulado)})", end="\r", flush=True)
        time.sleep(0.6)

    lineas = [f"Captura de menu - {datetime.now().isoformat()}", f"Total items: {len(acumulado)}", ""]
    lineas.extend(sorted(acumulado.values()))

    salida = Path("data") / "menu_capturado.txt"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text("\n".join(lineas), encoding="utf-8")

    print("\n\n" + "\n".join(lineas))
    print(f"\n>>> Guardado en: {salida.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
