"""Genera el informe de productividad de picking desde la pantalla 'CCU Caja Pickeada'.

Modo de uso:
  # Con un TSV ya capturado (recomendado; funciona en cualquier PC)
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
    ap.add_argument("--hora-actual", type=int, default=None,
                    help="Hora actual (0-23) para la proyeccion; por defecto la ultima con datos")
    ap.add_argument("--titulo", default="Avance de Picking")
    ap.add_argument("--fecha", default=None, help="Fecha del informe (default: hoy)")
    args = ap.parse_args()

    texto = _texto_entrada(args)
    lectura = ip.leer_tsv(texto)
    print(f"Filas leidas: {lectura.filas} | descartadas: {lectura.descartadas} "
          f"| normalizadas: {lectura.anomalias}")

    resumen = ip.resumen_por_hora(lectura.dataframe)
    if resumen.empty:
        print("[!] No hay datos agrupables. Revisa la captura.")
        return 1

    proy = ip.proyectar(
        resumen, meta=args.meta,
        hora_limite=args.hora_limite, hora_actual=args.hora_actual,
    )
    print(f"\nTotal pickeado: {proy.total_cajas} / {proy.meta} ({proy.pct_avance}%)")
    print(f"Ritmo: {proy.tasa_actual} cajas/hora | Termino estimado: {proy.hora_termino}")
    print(f"{proy.alerta}\n")

    print("Detalle por hora:")
    print(resumen.to_string(index=False))

    fecha = args.fecha or datetime.now().strftime("%Y-%m-%d")
    salida = Path("output")
    salida.mkdir(exist_ok=True)
    html = ip.generar_html(resumen, proy, args.titulo, fecha,
                           salida / f"informe_picking_{fecha}.html")
    xlsx = ip.generar_excel(resumen, proy, salida / f"informe_picking_{fecha}.xlsx")
    print(f"\nHTML:  {html}")
    print(f"Excel: {xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
