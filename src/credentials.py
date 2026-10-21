"""Acceso a credenciales.

En Windows usa el Administrador de credenciales (via `keyring`), de modo que
las contrasenas NUNCA quedan en texto plano en el codigo ni en archivos del repo.
Alternativa: variables de entorno, con el prefijo BY_.
"""

from __future__ import annotations

import os

import keyring


def set_password(servicio: str, usuario: str, password: str) -> None:
    """Guarda (una sola vez) una credencial en el almacen del sistema."""
    keyring.set_password(servicio, usuario, password)


def get_password(servicio: str, usuario: str) -> str:
    """Recupera una credencial.

    Orden de busqueda:
      1. Variable de entorno  BY_<SERVICIO>_<USUARIO>  (mayusculas)
      2. Administrador de credenciales del sistema (keyring)
    """
    var = "BY_" + f"{servicio}_{usuario}".upper().replace("-", "_").replace("@", "_").replace(".", "_")
    if var in os.environ:
        return os.environ[var]
    valor = keyring.get_password(servicio, usuario)
    if valor is None:
        raise LookupError(
            f"No hay credencial para servicio={servicio!r} usuario={usuario!r}. "
            f"Guardala con: python -m src.set_credentials"
        )
    return valor
