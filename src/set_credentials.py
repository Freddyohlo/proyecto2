"""Utilidad interactiva para guardar credenciales en el almacen del sistema.

La contrasena se guarda cifrada en el Administrador de credenciales de Windows
(via keyring). No queda en ningun archivo de texto.

Uso:
  python -m src.set_credentials          # usa servicio/usuario de config.toml
  python -m src.set_credentials --probar # verifica que la credencial guardada se lee
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import config, credentials


def _guardar(args) -> int:
    cfg = config.cargar(args.config)
    servicio = args.servicio or cfg.credenciales.servicio
    usuario = args.usuario or cfg.credenciales.usuario

    print(f"Se guardara la credencial de Blue Yonder:")
    print(f"   servicio = {servicio!r}")
    print(f"   usuario  = {usuario!r}")
    if not usuario:
        print("El usuario esta vacio. Configuralo en config.toml o pasa --usuario.", file=sys.stderr)
        return 1

    password = getpass.getpass("Contrasena (no se vera al escribir): ")
    if not password:
        print("La contrasena es obligatoria.", file=sys.stderr)
        return 1
    confirmar = getpass.getpass("Repite la contrasena: ")
    if password != confirmar:
        print("Las contrasenas no coinciden. Intenta de nuevo.", file=sys.stderr)
        return 1

    credentials.set_password(servicio, usuario, password)

    # Verificacion inmediata
    guardada = credentials.get_password(servicio, usuario)
    if guardada == password:
        print(f"OK: credencial guardada y verificada para {usuario!r}.")
        return 0
    print("ERROR: la credencial no se pudo leer de vuelta.", file=sys.stderr)
    return 1


def _probar(args) -> int:
    cfg = config.cargar(args.config)
    servicio = args.servicio or cfg.credenciales.servicio
    usuario = args.usuario or cfg.credenciales.usuario
    try:
        valor = credentials.get_password(servicio, usuario)
    except LookupError:
        print(f"NO hay credencial guardada para servicio={servicio!r} usuario={usuario!r}.")
        return 1
    print(f"OK: hay una credencial guardada para {usuario!r} (longitud: {len(valor)}).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--servicio", help="Override del servicio (si no, usa config.toml)")
    ap.add_argument("--usuario", help="Override del usuario (si no, usa config.toml)")
    ap.add_argument("--probar", action="store_true", help="Solo verifica la credencial guardada")
    args = ap.parse_args()

    return _probar(args) if args.probar else _guardar(args)


if __name__ == "__main__":
    raise SystemExit(main())
