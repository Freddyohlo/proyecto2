"""Prueba SOLO el login automatico de Blue Yonder (SOLO en el PC Windows).

Abre la app, escribe usuario y contrasena y pulsa Enter. Si algo no cuadra,
imprime la lista de controles de la ventana para diagnosticar.

Uso (en el PC con Blue Yonder):
    python tools\\probar_login.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pywinauto import Desktop

from src import capture_ui, config, credentials


def elegir_ventana(timeout: float = 30.0):
    """Devuelve la ventana de Blue Yonder, priorizando la que tenga campos de login."""
    fin = time.time() + timeout
    while time.time() < fin:
        candidatas = list(Desktop(backend="uia").windows(
            title_re=".*Blue Yonder.*", top_level_only=True))
        for w in candidatas:
            if capture_ui._buscar(w, "txtUsername") is not None:
                return w
        time.sleep(1)

    # No aparecio el campo: mostremos que ventanas hay para diagnosticar
    print("No encontre el campo 'txtUsername'. Ventanas 'Blue Yonder' encontradas:")
    candidatas = list(Desktop(backend="uia").windows(
        title_re=".*Blue Yonder.*", top_level_only=True))
    for i, w in enumerate(candidatas):
        print(f"\n--- Ventana [{i}]: {w.window_text()!r} ---")
        for linea in capture_ui.listar_controles(w)[:40]:
            print("   ", linea)
    raise RuntimeError(
        "No encontre el campo 'txtUsername' en ninguna ventana de Blue Yonder."
    )


def main() -> int:
    cfg = config.cargar("config.toml")

    ventana = elegir_ventana()
    print(f"Ventana encontrada: {ventana.window_text()!r}")

    usuario = cfg.credenciales.usuario
    try:
        password = credentials.get_password(cfg.credenciales.servicio, usuario)
        print(f"Credencial recuperada para usuario {usuario!r}.")
    except LookupError:
        import getpass

        print(f"No hay credencial guardada para {usuario!r}. La pido ahora (no se guardara).")
        password = getpass.getpass("Contrasena: ")

    campo_usuario = capture_ui._buscar(ventana, "txtUsername")
    campo_usuario.set_focus()
    campo_usuario.set_text(usuario)
    print("Usuario escrito.")

    campo_password = capture_ui._buscar(ventana, "txtPassword")
    campo_password.set_focus()
    campo_password.set_text(password)
    print("Contrasena escrita.")

    campo_password.type_keys("{ENTER}")
    print("Enter pulsado. Esperando...")
    time.sleep(cfg.app.espera_ui * 3)

    print("\nRevisa la pantalla: si entraste a Blue Yonder, el login funciona. OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
