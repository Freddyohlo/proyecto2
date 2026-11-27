"""Analiza un TSV capturado de la cuadratura (con Detalle) para entender la estructura.

NO necesita Windows: trabaja sobre el archivo .tsv ya capturado.

Sirve para descubrir como se distinguen las ubicaciones de PICKING y de
ALMACENAMIENTO, que valores toman las zonas y los estados, y el rango de
cantidades por ubicacion.

Uso:
    python tools\\analizar_tsv.py data\\raw_detalle_2026-10-21.tsv
    python tools\\analizar_tsv.py                 # usa el raw_detalle_*.tsv mas reciente
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

COLUMNAS = [
    "zona_trabajo", "zona_recogida", "area_sap", "ubicacion", "estado_ubicacion",
    "lpn", "lpn_detalle", "sku", "cod_espacio", "descripcion", "cantidad",
    "cant_pendiente", "cant_confirmada", "fecha_fifo", "fecha_fabricacion",
    "fecha_caducidad", "fecha_recepcion", "estado_inv", "perfil_antiguedad",
    "dias_caducidad", "ult_movimiento", "area",
]


def _resolver_archivo(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    crudos = sorted(Path("data").glob("raw_detalle_*.tsv"))
    if not crudos:
        crudos = sorted(Path("data").glob("raw_*.tsv"))
    if not crudos:
        raise FileNotFoundError("No hay data/raw_*.tsv. Pasa la ruta del TSV como argumento.")
    return crudos[-1]


def _leer(ruta: Path) -> list[dict]:
    filas = []
    for ln in ruta.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        celdas = [c.strip() for c in ln.split("\t")]
        if len(celdas) < len(COLUMNAS):
            continue
        filas.append(dict(zip(COLUMNAS, celdas)))
    return filas


def _contar(filas: list[dict], col: str, top: int = 25) -> Counter:
    return Counter(f.get(col, "") for f in filas).most_common(top)


def main() -> int:
    ruta = _resolver_archivo(sys.argv)
    print(f"Archivo: {ruta}")
    filas = _leer(ruta)
    print(f"Filas leidas: {len(filas)}\n")
    if not filas:
        return 1

    print("=" * 70)
    print("CONTEO POR COLUMNA CLAVE (valores mas frecuentes)")
    print("=" * 70)
    for col in ("area", "zona_trabajo", "zona_recogida", "area_sap",
                "estado_ubicacion", "estado_inv", "perfil_antiguedad",
                "cod_espacio"):
        print(f"\n--- {col} ---")
        for valor, n in _contar(filas, col, top=30):
            print(f"   {n:5d}  {valor!r}")

    print("\n" + "=" * 70)
    print("UBICACIONES: cuantas y como se reparten")
    print("=" * 70)
    ubic = Counter(f["ubicacion"] for f in filas)
    print(f"Ubicaciones distintas: {len(ubic)}")
    print("Prefijos de ubicacion (2 primeros caracteres):")
    prefijos = Counter(f["ubicacion"][:3] for f in filas)
    for p, n in prefijos.most_common(30):
        print(f"   {n:5d}  {p!r}")
    print("\nEjemplos de ubicacion por zona de trabajo:")
    por_zona = defaultdict(set)
    for f in filas:
        por_zona[f["zona_trabajo"]].add(f["ubicacion"])
    for zona, ubs in list(por_zona.items())[:10]:
        muestra = sorted(ubs)[:8]
        print(f"   zona {zona!r}: {len(ubs)} ubicaciones, ej: {muestra}")

    print("\n" + "=" * 70)
    print("SKU: se repite un SKU en varias ubicaciones?")
    print("=" * 70)
    por_sku = defaultdict(list)
    for f in filas:
        por_sku[f["sku"]].append((f["ubicacion"], f["cantidad"], f["area"], f["zona_trabajo"]))
    multi = {k: v for k, v in por_sku.items() if len(v) > 1}
    print(f"SKUs distintos: {len(por_sku)} | SKUs en >1 fila: {len(multi)}")
    for sku, det in list(multi.items())[:8]:
        print(f"   SKU {sku!r}:")
        for u, c, a, z in det[:6]:
            print(f"      ubic={u!r} cant={c!r} area={a!r} zona={z!r}")

    print("\n" + "=" * 70)
    print("FEFO: rango de fechas de caducidad")
    print("=" * 70)
    cads = sorted(f["fecha_caducidad"] for f in filas if f["fecha_caducidad"])
    if cads:
        print(f"   Min: {cads[0]}   Max: {cads[-1]}   ({len(cads)} con fecha)")

    print("\n>>> PEGA TODO ESTO EN EL CHAT (me dice como separar picking/almacenamiento).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
