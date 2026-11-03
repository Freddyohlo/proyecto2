"""Informe del dia de contingencia.

Consolida TODO lo que paso mientras Blue Yonder estuvo caido:
  - Stock vivo: cuanto hay, cuanto reservado, cuanto pickeado
  - Picking: tareas hechas, parciales, saltadas, y cajas pickeadas
  - Recepcion: que llego, que se ubico, que quedo pendiente
  - Faltantes: SKU que la venta pedia y no se alcanzaron a cubrir
  - Movimientos: el detalle para reingresar a Blue Yonder

Es el respaldo escrito de la operacion: si algo se discute despues, esto lo
resuelve. Se genera como HTML (para leer/imprimir) y Excel (para trabajar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import picking as pk
from . import recepcion as rc
from . import stock_vivo as sv


@dataclass
class ResumenDia:
    fecha: str = ""
    generado: str = ""
    stock: dict = field(default_factory=dict)
    tareas: dict = field(default_factory=dict)
    recepcion: dict = field(default_factory=dict)
    picking_mov: pd.DataFrame = field(default_factory=pd.DataFrame)
    recepcion_mov: pd.DataFrame = field(default_factory=pd.DataFrame)
    skus_nuevos: pd.DataFrame = field(default_factory=pd.DataFrame)
    por_sku: pd.DataFrame = field(default_factory=pd.DataFrame)
    ubicaciones: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def cajas_pickeadas(self) -> int:
        return int(self.stock.get("pickeado", 0))

    @property
    def cajas_recibidas(self) -> int:
        return int(self.recepcion.get("cajas", 0))

    def alertas(self) -> list[dict]:
        """Cosas que conviene mirar antes de cerrar el dia."""
        a = []
        if self.recepcion.get("sin_vencimiento"):
            a.append({"nivel": "warn",
                      "texto": f"{self.recepcion['sin_vencimiento']} recepciones sin "
                               f"fecha de vencimiento (FEFO no puede ordenarlas)"})
        if self.recepcion.get("pendientes"):
            a.append({"nivel": "warn",
                      "texto": f"{self.recepcion['pendientes']} recepciones sin ubicar"})
        if self.tareas.get("parcial", {}).get("tareas"):
            a.append({"nivel": "warn",
                      "texto": f"{self.tareas['parcial']['tareas']} picks parciales "
                               f"(quedaron cajas sin pickear)"})
        if self.tareas.get("saltada", {}).get("tareas"):
            a.append({"nivel": "warn",
                      "texto": f"{self.tareas['saltada']['tareas']} tareas saltadas"})
        if not self.skus_nuevos.empty:
            a.append({"nivel": "info",
                      "texto": f"{len(self.skus_nuevos)} SKU nuevos que no venian en "
                               f"la cuadratura"})
        if not a:
            a.append({"nivel": "ok", "texto": "Sin observaciones"})
        return a


def recopilar(db: str | Path, fecha: str = "") -> ResumenDia:
    """Junta todo lo que paso en el dia."""
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")

    with sv.abrir(db) as con:
        rc.preparar_tablas(con)
        pk.preparar_tablas(con)
        con.commit()          # asegura que las tablas existan antes de leerlas

        picking_mov = pd.read_sql_query(
            """SELECT fecha, usuario, ubicacion, sku, lpn, cantidad, descripcion,
                      caducidad FROM picking ORDER BY id""", con)

        recep_mov = pd.read_sql_query(
            """SELECT fecha, lpn, sku, descripcion, cantidad, ubicacion_final,
                      fecha_vencimiento, estado
                 FROM recepcion ORDER BY id""", con)

        # Cajas movidas por SKU (lo pickeado)
        por_sku = pd.read_sql_query(
            """SELECT sku, descripcion, SUM(cantidad) AS cajas, COUNT(*) AS picks
                 FROM picking GROUP BY sku ORDER BY cajas DESC""", con)

        # Ubicaciones que se tocaron (para reingresar a Blue Yonder)
        ubicaciones = pd.read_sql_query(
            """SELECT ubicacion, COUNT(*) AS picks, SUM(cantidad) AS cajas
                 FROM picking GROUP BY ubicacion ORDER BY cajas DESC""", con)

    return ResumenDia(
        fecha=fecha,
        generado=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        stock=sv.resumen(db),
        tareas=pk.resumen_tareas(db),
        recepcion=rc.resumen(db),
        picking_mov=picking_mov,
        recepcion_mov=recep_mov,
        skus_nuevos=rc.skus_nuevos(db),
        por_sku=por_sku,
        ubicaciones=ubicaciones,
    )


def generar_excel(d: ResumenDia, destino: str | Path) -> Path:
    """Excel con una hoja por tema (para trabajar el dato)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    resumen = pd.DataFrame([
        {"concepto": "Fecha", "valor": d.fecha},
        {"concepto": "Stock total (foto)", "valor": d.stock.get("total", 0)},
        {"concepto": "Reservado", "valor": d.stock.get("reservado", 0)},
        {"concepto": "Pickeado", "valor": d.stock.get("pickeado", 0)},
        {"concepto": "Disponible", "valor": d.stock.get("disponible", 0)},
        {"concepto": "Cajas recibidas", "valor": d.cajas_recibidas},
        {"concepto": "Recepciones", "valor": d.recepcion.get("recepciones", 0)},
        {"concepto": "Recepciones sin ubicar", "valor": d.recepcion.get("pendientes", 0)},
    ])

    with pd.ExcelWriter(destino, engine="openpyxl") as xw:
        resumen.to_excel(xw, sheet_name="Resumen", index=False)
        if not d.tareas:
            pd.DataFrame([{"sin_tareas": True}]).to_excel(xw, sheet_name="Tareas", index=False)
        else:
            pd.DataFrame([
                {"estado": k, "tareas": v["tareas"], "cajas": v["cajas"]}
                for k, v in d.tareas.items()
            ]).to_excel(xw, sheet_name="Tareas", index=False)
        d.por_sku.to_excel(xw, sheet_name="Pickeado por SKU", index=False)
        d.ubicaciones.to_excel(xw, sheet_name="Por ubicacion", index=False)
        d.picking_mov.to_excel(xw, sheet_name="Movimientos picking", index=False)
        d.recepcion_mov.to_excel(xw, sheet_name="Recepcion", index=False)
        if not d.skus_nuevos.empty:
            d.skus_nuevos.to_excel(xw, sheet_name="SKU nuevos", index=False)
    return destino


def generar_html(d: ResumenDia, destino: str | Path,
                 plantilla: str | Path = "templates/informe_dia.html.j2") -> Path:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    plantilla = Path(plantilla)

    env = Environment(
        loader=FileSystemLoader(str(plantilla.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template(plantilla.name)

    html = tmpl.render(
        d=d,
        tareas=d.tareas,
        stock=d.stock,
        recep=d.recepcion,
        alertas=d.alertas(),
        por_sku=d.por_sku.head(40).to_dict("records"),
        ubicaciones=d.ubicaciones.head(40).to_dict("records"),
        picking_mov=d.picking_mov.tail(60).to_dict("records"),
        recepcion_mov=d.recepcion_mov.to_dict("records"),
        skus_nuevos=d.skus_nuevos.to_dict("records"),
    )
    destino.write_text(html, encoding="utf-8")
    return destino
