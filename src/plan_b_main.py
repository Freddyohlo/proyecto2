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
        raise SystemExit("Indica --archivo con el TSV de reabastecimiento o de minimos/maximos.")
    if args.formato == "reabastecimiento":
        # Formato real de la pantalla 'Operaciones de reabastecimiento'
        m = mm.cargar_reabastecimiento(args.archivo)
    else:
        m = mm.leer_minmax_archivo(
            args.archivo,
            col_ubicacion=args.col_ubicacion,
            col_sku=args.col_sku,
            col_minimo=args.col_minimo,
            col_maximo=args.col_maximo,
        )
    if m.dataframe.empty:
        print("[!] No se leyeron registros. Revisa el archivo o el --formato.")
        return 1
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


def cmd_venta(args) -> int:
    from . import externos

    v = externos.cargar_venta_desde_archivo(args.archivo)
    print(f"Venta (TRUCK): {v.filas} lineas validas | descartadas: {v.descartadas}")
    if v.dataframe.empty:
        print("[!] No se leyeron lineas. Revisa el CSV.")
        return 1
    ruta = v.guardar(args.db)
    print(f"Guardado en: {ruta.resolve()}")
    print("\nDemanda por SKU (top 10):")
    print(v.demanda_por_sku().head(10).to_string(index=False))
    return 0


def cmd_transito(args) -> int:
    from . import externos

    t = externos.cargar_transito_desde_archivo(args.archivo)
    print(f"Transito (SAP): {t.filas} lineas validas | descartadas: {t.descartadas}")
    if t.dataframe.empty:
        print("[!] No se leyeron lineas. Revisa el Excel.")
        return 1
    ruta = t.guardar(args.db)
    print(f"Guardado en: {ruta.resolve()}")
    print("\nTransito por OCA (top 10):")
    print(t.por_oca().head(10).to_string(index=False))
    return 0


def cmd_contraste(args) -> int:
    from . import contraste, externos

    inventario = _cargar_db(args.db)
    ruta = Path(args.db)
    try:
        venta = externos.Venta.cargar(ruta)
    except Exception:
        venta = None
    try:
        transito = externos.Transito.cargar(ruta)
    except Exception:
        transito = None

    if venta is None:
        raise SystemExit("No hay venta cargada. Corre: python -m src.plan_b_main venta --archivo <csv>")

    c = contraste.calcular(inventario, venta, transito)
    r = c.resumen()
    print(f"Contraste VENTA vs STOCK{' vs TRANSITO' if transito else ''}")
    print(f"  SKUs con demanda : {r['skus']}")
    print(f"  Demanda total    : {r['demanda']} cajas")
    print(f"  Cubierto         : {r['cubierto']} ({r['pct_cubierto']}%)")
    print(f"  Falta            : {r['falta']} cajas")
    print(f"  SKUs en quiebre  : {r['quiebres']}")

    q = c.quiebres
    if not q.empty:
        print(f"\n⚠️ Quiebres (top {min(20, len(q))}):")
        print(q.head(20)[["sku", "descripcion", "demanda", "picking",
                          "almacen", "transito", "falta"]].to_string(index=False))

    if args.exportar:
        destino = Path(args.exportar)
        destino.parent.mkdir(parents=True, exist_ok=True)
        c.dataframe.to_csv(destino, index=False, sep=";", encoding="utf-8-sig")
        print(f"\nDetalle exportado: {destino.resolve()}")
    return 0


def cmd_picking(args) -> int:
    from . import externos, picking, stock_vivo

    ruta = Path(args.db)
    try:
        venta = externos.Venta.cargar(ruta)
    except Exception:
        venta = None
    if venta is None or venta.dataframe.empty:
        raise SystemExit(
            "No hay venta cargada. Corre: "
            "python -m src.plan_b_main venta --archivo <csv de TRUCK>"
        )

    # Asegura el stock vivo (foto + reservas + pickeado)
    filas = stock_vivo.inicializar(ruta, forzar=args.reiniciar_stock)
    if filas == 0:
        raise SystemExit("No hay stock. Corre primero: plan_b_main cargar --archivo <tsv>")

    demanda = venta.demanda_por_sku()
    creadas, reservadas, faltantes = picking.destinar(
        ruta, demanda, incluir_almacenamiento=args.con_almacenamiento
    )
    if creadas == 0:
        print("[!] No se generaron tareas. Revisa el stock disponible.")
        return 1

    print(f"Tareas destinadas: {creadas}  |  cajas RESERVADAS: {reservadas}")
    print(f"  (incluye almacenamiento: {args.con_almacenamiento})")

    if not faltantes.empty:
        print(f"\n⚠️ {len(faltantes)} SKUs sin stock suficiente "
              f"({int(faltantes['faltante'].sum())} cajas). Insumo para reaprovisionamiento:")
        print(faltantes.head(15).to_string(index=False))

    print("\nStock vivo:")
    r = stock_vivo.resumen(ruta)
    print(f"  total {r['total']} | reservado {r['reservado']} | "
          f"pickeado {r['pickeado']} | disponible {r['disponible']}")

    print("\nPrimeras tareas (en orden FEFO):")
    with stock_vivo.abrir(ruta) as con:
        filas = con.execute(
            """SELECT ubicacion, cantidad, descripcion, lote, caducidad
                 FROM tareas WHERE estado = 'pendiente' ORDER BY id LIMIT 10"""
        ).fetchall()
    for f in filas:
        print(f"  {f['ubicacion']:14} {f['cantidad']:>5} x {str(f['descripcion'])[:30]:32} "
              f"lote {str(f['lote'])[:14]:16} vence {f['caducidad']}")

    print(f"\nServidor de picking: python -m src.picking_servidor --db {ruta}")
    return 0


def cmd_stock_vivo(args) -> int:
    from . import stock_vivo

    ruta = Path(args.db)
    if args.reiniciar:
        n = stock_vivo.inicializar(ruta, forzar=True)
        print(f"Stock vivo reiniciado desde la foto: {n} filas.")
    else:
        n = stock_vivo.inicializar(ruta)
        print(f"Stock vivo: {n} filas.")

    r = stock_vivo.resumen(ruta)
    print(f"\n  Total (foto) : {r['total']}")
    print(f"  Reservado    : {r['reservado']}")
    print(f"  Pickeado     : {r['pickeado']}")
    print(f"  Disponible   : {r['disponible']}")

    if args.detalle:
        df = stock_vivo.estado(ruta)
        con_mov = df[(df["reservado"] > 0) | (df["pickeado"] > 0)]
        print(f"\nFilas con movimiento ({len(con_mov)}):")
        print(con_mov.head(30).to_string(index=False))
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
    p.add_argument("--formato", default="reabastecimiento",
                   choices=["reabastecimiento", "generico"],
                   help="'reabastecimiento' = TSV de la pantalla de reabastecimiento "
                        "(18 columnas); 'generico' = TSV/CSV con columnas configurables")
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

    p = sub.add_parser("venta", help="Carga la venta/demanda desde el CSV de TRUCK")
    p.add_argument("--archivo", required=True)
    p.set_defaults(func=cmd_venta)

    p = sub.add_parser("transito", help="Carga el transito desde el Excel de SAP")
    p.add_argument("--archivo", required=True)
    p.set_defaults(func=cmd_transito)

    p = sub.add_parser("contraste", help="Cruza venta vs stock vs transito (quiebres)")
    p.add_argument("--exportar", default=None, help="Ruta CSV donde exportar el detalle")
    p.set_defaults(func=cmd_contraste)

    p = sub.add_parser("picking", help="Destina tareas de picking (reserva el stock)")
    p.add_argument("--con-almacenamiento", action="store_true",
                   help="Permitir tambien picking desde AREA ALMACENAMIENTO")
    p.add_argument("--reiniciar-stock", action="store_true",
                   help="Reinicia el stock vivo desde la foto antes de destinar")
    p.set_defaults(func=cmd_picking)

    p = sub.add_parser("stock-vivo", help="Muestra el stock vivo (reservado/pickeado)")
    p.add_argument("--reiniciar", action="store_true",
                   help="Reinicia el stock vivo desde la foto de la cuadratura")
    p.add_argument("--detalle", action="store_true",
                   help="Muestra las filas con movimiento")
    p.set_defaults(func=cmd_stock_vivo)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
