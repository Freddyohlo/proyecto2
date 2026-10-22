"""Genera el informe de productividad de picking desde 'CCU Caja Pickeada'.

La hora de trabajo se toma de `h_inicio` (no de la columna `hora`), para no
confundir los turnos que cruzan la medianoche.

Modo de uso:
  # Con un TSV ya capturado
  python -m src.informe_picking_main --desde-archivo data/caja_pickeada_2026-10-22.tsv --meta 12000

  # Reutiliza el data/caja_pickeada_*.tsv mas reciente
  python -m src.informe_picking_main --meta 12000

  # Desde el portapapeles
  python -m src.informe_picking_main --desde-portapapeles --meta 12000

  # Capturando en vivo de Blue Yonder (SOLO en el PC Windows con la app)
  python -m src.informe_picking_main --capturar --meta 12000

Salidas (por defecto en output/):
  output/informe_picking_<fecha>.html
  output/informe_picking_<fecha>.xlsx
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from . import informe_picking as ip


def _texto_entrada(args) -> str:
    if args.desde_archivo:
        return Path(args.desde_archivo).read_text(encoding="utf-8")
    if args.desde_portapapeles:
        import pyperclip

        return pyperclip.paste()
    if args.capturar:
        from . import capture_ui, config

        cfg = config.cargar(args.config)
        return capture_ui.capturar_caja_pickeada(cfg)

    crudos = sorted(Path("data").glob("caja_pickeada_*.tsv"))
    if not crudos:
        raise FileNotFoundError(
            "No hay data/caja_pickeada_*.tsv. Captura primero con "
            "tools/inspeccionar_caja_pickeada.py o usa --desde-archivo."
        )
    print(f"Usando el crudo mas reciente: {crudos[-1]}")
    return crudos[-1].read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Informe de productividad de picking")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--desde-archivo", help="TSV de entrada")
    ap.add_argument("--desde-portapapeles", action="store_true")
    ap.add_argument("--capturar", action="store_true",
                    help="Capturar en vivo de Blue Yonder (solo Windows)")
    ap.add_argument("--meta", type=int, required=True,
                    help="Meta / venta total de cajas del dia (se ingresa a mano)")
    ap.add_argument("--hora-limite", default="07:00",
                    help="Hora limite antes de que se retiren pickeadores (default 07:00)")
    ap.add_argument("--titulo", default="Avance de Picking")
    ap.add_argument("--fecha", default=None, help="Fecha del informe (default: hoy)")
    args = ap.parse_args()

    texto = _texto_entrada(args)
    lectura = ip.leer_tsv(texto)
    print(f"Filas validas: {lectura.filas} | descartadas: {lectura.descartadas} "
          f"| normalizadas: {lectura.anomalias} | sin fechas: {lectura.sin_fechas}")
    if lectura.filas == 0:
        print("[!] No hay filas con hora de inicio valida. Revisa la captura.")
        return 1

    resumen = ip.resumen_por_hora(lectura.dataframe)
    proy = ip.proyectar(resumen, meta=args.meta, hora_limite=args.hora_limite)

    print(f"\nTotal pickeado: {proy.total_cajas} / {proy.meta} ({proy.pct_avance}%)")
    print(f"Viajes: {proy.total_viajes} | Cajas por viaje: {proy.cajas_por_viaje}")
    print(f"Ritmo: {proy.tasa_actual} cajas/hora | Termino estimado: {proy.hora_termino}")
    print(f"{proy.alerta}\n")

    print("Detalle por hora real (segun h_inicio):")
    print(resumen[["etiqueta", "cajas", "pickeadores", "viajes",
                   "cajas_por_pickeador", "cajas_por_viaje"]].to_string(index=False))

    fecha = args.fecha or datetime.now().strftime("%Y-%m-%d")
    salida = Path("output")
    salida.mkdir(exist_ok=True)
    html = ip.generar_html(resumen, proy, args.meta, args.titulo, fecha,
                           salida / f"informe_picking_{fecha}.html")
    xlsx = ip.generar_excel(resumen, proy, args.meta, salida / f"informe_picking_{fecha}.xlsx")

    # Rutas ABSOLUTAS y en formato file:// para abrirlas con un clic
    print("\n=== ARCHIVOS GENERADOS (haz clic o copia y pega en el navegador) ===")
    print(f"HTML : {html.resolve()}")
    print(f"       {html.resolve().as_uri()}")
    print(f"Excel: {xlsx.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
