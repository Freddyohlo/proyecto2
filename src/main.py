"""Orquestador del reporte diario.

Flujo completo:
  1. Obtener los datos (automatizando Blue Yonder, o desde un archivo de prueba).
  2. Parsear el TSV.
  3. Generar el dashboard HTML.
  4. Enviarlo por correo.

Modo de uso:
  python -m src.main                      # flujo real (automatiza la app; solo Windows)
  python -m src.main --desde-archivo f.tsv  # usa un TSV ya guardado (pruebas)
  python -m src.main --sin-correo          # genera el dashboard pero no envia email
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from . import config, dashboard, parser


def obtener_texto(args) -> str:
    if args.desde_archivo:
        return Path(args.desde_archivo).read_text(encoding="utf-8")
    if args.desde_ultimo:
        crudos = sorted(Path("data").glob("raw_*.tsv"))
        if not crudos:
            raise FileNotFoundError("No hay archivos data/raw_*.tsv para reutilizar.")
        print(f"Usando el crudo mas reciente: {crudos[-1]}")
        return crudos[-1].read_text(encoding="utf-8")
    if args.desde_portapapeles:
        import pyperclip

        return pyperclip.paste()

    from . import capture_ui  # import tardio: solo disponible en Windows

    cfg = config.cargar(args.config)
    return capture_ui.capturar(cfg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Reporte diario Blue Yonder")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--desde-archivo", help="TSV de entrada (omite la captura de UI)")
    ap.add_argument("--desde-ultimo", action="store_true",
                    help="Reutiliza el data/raw_*.tsv mas reciente (omite la captura de UI)")
    ap.add_argument("--desde-portapapeles", action="store_true",
                    help="Toma el TSV del portapapeles (util para pruebas)")
    ap.add_argument("--sin-correo", action="store_true", help="No enviar email")
    args = ap.parse_args()

    cfg = config.cargar(args.config)

    texto = obtener_texto(args)
    resultado = parser.parsear_texto(texto, cfg.columnas, cfg.reporte)
    print(f"Filas validas: {resultado.filas_validas} | descartadas: {resultado.filas_descartadas}")

    # Guardar copia cruda y procesada del dia
    hoy = datetime.now().strftime("%Y-%m-%d")
    Path("data").mkdir(exist_ok=True)
    Path(f"data/raw_{hoy}.tsv").write_text(texto, encoding="utf-8")
    resultado.dataframe.to_csv(f"data/procesado_{hoy}.csv", index=False, encoding="utf-8")

    salida = dashboard.generar(
        resultado.dataframe, cfg, Path(f"output/reporte_{hoy}.html")
    )
    print(f"Dashboard generado: {salida}")

    if args.sin_correo:
        print("Envio de correo omitido (--sin-correo).")
        return 0

    from . import mailer

    cuerpo = salida.read_text(encoding="utf-8")
    asunto = f"{cfg.reporte.titulo} - {hoy}"
    mailer.enviar(cfg, asunto, cuerpo, adjuntos=[salida])
    print(f"Correo enviado a: {', '.join(cfg.correo.destinatarios)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
