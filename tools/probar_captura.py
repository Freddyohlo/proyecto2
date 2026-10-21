"""Prueba TODO el flujo de captura de punta a punta (SOLO en Windows).

Hace: login -> menu Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock
      -> combo area = AREA VALORADO -> Buscar -> copiar grilla -> parsear.

Deja Blue Yonder en la pantalla de LOGIN antes de ejecutar.
El crudo queda en data\\raw_AAAA-MM-DD.tsv

Uso:
    python tools\\probar_captura.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import capture_ui, config, parser


def main() -> int:
    cfg = config.cargar("config.toml")

    print("Iniciando captura completa (login -> informe -> copiar grilla)...")
    texto = capture_ui.capturar(cfg)

    Path("data").mkdir(exist_ok=True)
    hoy = datetime.now().strftime("%Y-%m-%d")
    crudo = Path(f"data/raw_{hoy}.tsv")
    crudo.write_text(texto, encoding="utf-8")
    print(f"\nCrudo guardado en: {crudo}")

    resultado = parser.parsear_texto(texto, cfg.columnas, cfg.reporte)
    print(f"Filas validas: {resultado.filas_validas} | descartadas: {resultado.filas_descartadas}")
    print("\nPrimeras 5 filas:")
    print(resultado.dataframe.head(5).to_string(index=False))
    print("\nOK: la captura de punta a punta funciona.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
