"""Carga de configuracion del proyecto (config.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Columna:
    clave: str
    titulo: str
    tipo: str = "texto"  # "texto" | "numero"


@dataclass
class App:
    nombre: str = "Blue Yonder"
    exe: str = ""
    espera_ui: float = 2.0


@dataclass
class Credenciales:
    servicio: str = "blueyonder"
    usuario: str = ""


@dataclass
class Reporte:
    titulo: str = "Reporte Diario"
    agrupar_por: str | None = None
    totalizar: str | None = None
    # Si la grilla copiada trae fila de encabezado, indicar cuantas saltar.
    saltar_encabezado: int = 0
    # Descarta filas donde <columna> contenga alguno de estos textos (ej: "TOTAL").
    ignorar_si_contiene: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Correo:
    host: str = ""
    puerto: int = 587
    seguridad: str = "starttls"
    remitente: str = ""
    servicio_keyring: str = ""
    usuario_keyring: str = ""
    destinatarios: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)


@dataclass
class Config:
    app: App = field(default_factory=App)
    credenciales: Credenciales = field(default_factory=Credenciales)
    columnas: list[Columna] = field(default_factory=list)
    reporte: Reporte = field(default_factory=Reporte)
    correo: Correo = field(default_factory=Correo)


def cargar(ruta: str | Path = "config.toml") -> Config:
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontro {ruta}. Copia config.example.toml a config.toml y ajustalo."
        )
    datos = tomllib.loads(ruta.read_text(encoding="utf-8"))

    cfg = Config()
    cfg.app = App(**datos.get("app", {}))
    cfg.credenciales = Credenciales(**datos.get("credenciales", {}))
    cfg.columnas = [Columna(**c) for c in datos.get("columnas", [])]
    cfg.reporte = Reporte(**datos.get("reporte", {}))
    cfg.correo = Correo(**datos.get("correo", {}))
    return cfg
