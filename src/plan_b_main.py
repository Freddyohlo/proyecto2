"""Plan B — CLI del sistema de contingencia offline.

Comandos:
  cargar      Carga el TSV de la cuadratura (con Detalle) a la base local
  minmax      Carga el archivo de minimos/maximos a la base local
  buscar      Busca por SKU / descripcion / ubicacion
  sku         Ficha de un SKU (stock en picking y almacenamiento, FEFO)
  reposicion  Calcula que reponer (ubicaciones de picking bajo el minimo)
  informe     Genera un HTML con el estado del inventario y la reposicion

Ejemplos:
  python -m src.plan_b_main cargar --archivo data/raw_detalle_2026-10-21.tsv
  python -m src.plan_b_main minmax --archivo data/minmax.tsv --col-ubicacion ubicacion \
      --col-sku sku --col-minimo min --col-maximo max
  python -m src.plan_b_main buscar --texto 856473
  python -m src.plan_b_main sku --sku 856473
  python -m src.plan_b_main reposicion
  python -m src.plan_b_main informe
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from . import inventario as inv
from . import minmax as mm

DB = "data/plan_b.sqlite"


def _cargar_db(ruta: str | Path = DB) -> inv.Inventario:
    ruta = Path(ruta)
    if not ruta.exists():
        raise SystemExit(
            f"No existe {ruta}. Corre primero: "
            f"python -m src.plan_b_main --db {ruta} cargar --archivo <tsv>"
        )
    return inv.Inventario.cargar(ruta)


def cmd_cargar(args) -> int:
    if not args.archivo:
        raise SystemExit("Indica --archivo con el TSV de la cuadratura (con Detalle).")
    texto = Path(args.archivo).read_text(encoding="utf-8")
    inventario = inv.leer_detalle(texto)
    print(f"Filas validas: {inventario.filas} | descartadas: {inventario.descartadas} "
          f"| normalizadas: {inventario.anomalias}")
    if inventario.dataframe.empty:
        print("[!] No hay filas. Revisa el archivo.")
        return 1
    ruta = inventario.guardar(args.db)
    print(f"Base guardada en: {ruta.resolve()}")
    print("\nResumen por area:")
    print(inventario.dataframe.groupby("area")["cantidad"].agg(["count", "sum"]).to_string())
    return 0


def cmd_minmax(args) -> int:
    if not args.archivo:
        raise SystemExit("Indica --archivo con el TSV/CSV de minimos y maximos.")
    m = mm.leer_minmax_archivo(
        args.archivo,
        col_ubicacion=args.col_ubicacion,
        col_sku=args.col_sku,
        col_minimo=args.col_minimo,
        col_maximo=args.col_maximo,
    )
    ruta = m.guardar(args.db)
    print(f"{len(m.dataframe)} registros de minimos/maximos guardados en: {ruta.resolve()}")
    print(m.dataframe.head(8).to_string(index=False))
    return 0


def cmd_buscar(args) -> int:
    inventario = _cargar_db(args.db)
    df = inventario.buscar(args.texto, limite=args.limite)
    if df.empty:
        print("Sin resultados.")
        return 0
    print(f"{len(df)} resultados:")
    cols = ["ubicacion", "sku", "descripcion", "cantidad", "area", "fecha_caducidad"]
    print(df[cols].to_string(index=False))
    return 0


def cmd_sku(args) -> int:
    inventario = _cargar_db(args.db)
    r = inventario.resumen_sku(args.sku)
    if not r["descripcion"]:
        print(f"SKU {args.sku} no encontrado.")
        return 1
    print(f"SKU: {r['sku']}  —  {r['descripcion']}")
    print(f"  En PICKING:        {r['en_picking']}")
    print(f"  En ALMACENAMIENTO: {r['en_almacenamiento']}")
    print(f"  TOTAL:             {r['total']}")
    print(f"  Ubicaciones: {r['ubicaciones']} | Lotes (LPN): {r['lotes']}")
    print("\nDetalle FEFO (picking primero, por vencimiento):")
    fefo = inventario.fefo(args.sku)
    cols = ["area", "ubicacion", "lpn", "cantidad", "fecha_caducidad", "dias_caducidad"]
    print(fefo[cols].to_string(index=False) if not fefo.empty else "  (sin stock)")
    return 0


def cmd_reposicion(args) -> int:
    inventario = _cargar_db(args.db)
    ruta = Path(args.db)
    try:
        m = mm.MinMax.cargar(ruta)
    except Exception:
        raise SystemExit("No hay minimos/maximos cargados. Corre: python -m src.plan_b_main minmax --archivo <f>")
    items = mm.calcular_reposicion(inventario, m)
    if not items:
        print("No hay ubicaciones bajo el minimo (o no cruzan con los minimos cargados).")
        return 0
    df = mm.reposicion_a_dataframe(items)
    print(f"{len(df)} ubicaciones bajo el minimo. Reposiciones a realizar:\n")
    print(df.to_string(index=False))
    faltan = df[~df["cubre"]]
    if not faltan.empty:
        print(f"\n⚠️ {len(faltan)} reposiciones NO alcanzan con el stock de almacenamiento.")
    return 0


def cmd_informe(args) -> int:
    from . import plan_b_html

    inventario = _cargar_db(args.db)
    ruta = Path(args.db)
    repos: list[mm.NecesidadReposicion] = []
    try:
        m = mm.MinMax.cargar(ruta)
        repos = mm.calcular_reposicion(inventario, m)
    except Exception:
        pass

    salida = Path("output")
    salida.mkdir(exist_ok=True)
    fecha = args.fecha or datetime.now().strftime("%Y-%m-%d")
    destino = plan_b_html.generar(inventario, repos, salida / f"plan_b_{fecha}.html")
    print(f"Informe generado: {destino.resolve()}")
    print(f"                  {destino.resolve().as_uri()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan B — contingencia offline de Blue Yonder")
    ap.add_argument("--db", default=DB, help=f"Base SQLite (default {DB})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("cargar", help="Carga el TSV de la cuadratura")
    p.add_argument("--archivo", required=True)
    p.set_defaults(func=cmd_cargar)

    p = sub.add_parser("minmax", help="Carga minimos/maximos")
    p.add_argument("--archivo", required=True)
    p.add_argument("--col-ubicacion", default="ubicacion")
    p.add_argument("--col-sku", default="sku")
    p.add_argument("--col-minimo", default="minimo")
    p.add_argument("--col-maximo", default="maximo")
    p.set_defaults(func=cmd_minmax)

    p = sub.add_parser("buscar", help="Busca por SKU/descripcion/ubicacion")
    p.add_argument("--texto", required=True)
    p.add_argument("--limite", type=int, default=50)
    p.set_defaults(func=cmd_buscar)

    p = sub.add_parser("sku", help="Ficha de un SKU")
    p.add_argument("--sku", required=True)
    p.set_defaults(func=cmd_sku)

    p = sub.add_parser("reposicion", help="Calcula que reponer")
    p.set_defaults(func=cmd_reposicion)

    p = sub.add_parser("informe", help="Genera el HTML del Plan B")
    p.add_argument("--fecha", default=None)
    p.set_defaults(func=cmd_informe)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
