"""Envio del reporte por correo (SMTP)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import Config, Correo
from . import credentials


def _conectar(c: Correo) -> smtplib.SMTP:
    contexto = ssl.create_default_context()

    if c.seguridad == "ssl":
        servidor: smtplib.SMTP = smtplib.SMTP_SSL(c.host, c.puerto, context=contexto)
    else:
        servidor = smtplib.SMTP(c.host, c.puerto)
        if c.seguridad == "starttls":
            servidor.starttls(context=contexto)

    # Algunos servidores internos no requieren autenticacion.
    if servidor.has_extn("auth") and c.usuario_keyring:
        password = credentials.get_password(c.servicio_keyring, c.usuario_keyring)
        servidor.login(c.usuario_keyring, password)
    return servidor


def enviar(cfg: Config, asunto: str, cuerpo_html: str, adjuntos: list[Path] | None = None) -> None:
    c = cfg.correo
    if not c.destinatarios:
        raise ValueError("No hay destinatarios configurados en [correo].destinatarios")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = c.remitente
    msg["To"] = ", ".join(c.destinatarios)
    if c.cc:
        msg["Cc"] = ", ".join(c.cc)

    msg.set_content("Este reporte requiere un cliente de correo con soporte HTML.")
    msg.add_alternative(cuerpo_html, subtype="html")

    for ruta in adjuntos or []:
        ruta = Path(ruta)
        msg.add_attachment(
            ruta.read_bytes(),
            maintype="text",
            subtype="html",
            filename=ruta.name,
        )

    destinatarios_todos = c.destinatarios + c.cc
    with _conectar(c) as servidor:
        servidor.send_message(msg, to_addrs=destinatarios_todos)
