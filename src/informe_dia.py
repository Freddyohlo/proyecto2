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
    reapro_mov: pd.DataFrame = field(default_factory=pd.DataFrame)
    reapro: dict = field(default_factory=dict)
    skus_nuevos: pd.DataFrame = field(default_factory=pd.DataFrame)
    productividad: list = field(default_factory=list)
    por_sku: pd.DataFrame = field(default_factory=pd.DataFrame)
    ubicaciones: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def cajas_pickeadas(self) -> int:
        """Cajas que salieron por picking.

        Se leen de la TABLA de movimientos, NO de `stock.pickeado`: ese contador
        del stock vivo tambien sube cuando la grua mueve mercaderia (reapro), asi
        que sumarlo aparte contaria dos veces.
        """
        if self.picking_mov.empty:
            return 0
        return int(pd.to_numeric(self.picking_mov["cantidad"],
                                 errors="coerce").fillna(0).sum())

    @property
    def cajas_recibidas(self) -> int:
        return int(self.recepcion.get("cajas", 0))

    @property
    def cajas_reapro(self) -> int:
        """Cajas bajadas de almacenamiento a picking por la grua."""
        return int(self.reapro.get("cajas", 0))

    @property
    def movimientos_totales(self) -> int:
        """TODOS los movimientos de la jornada: picks + reapros + recepciones.

        Es el dato que le interesa al supervisor: "durante la jornada hubo N
        movimientos". Cada tarea de picking confirmada, cada bajada de grua y
        cada recepcion cuentan como un movimiento.
        """
        picks = int(self.tareas.get("ok", {}).get("tareas", 0))
        picks += int(self.tareas.get("parcial", {}).get("tareas", 0))
        return picks + int(self.reapro.get("tareas", 0)) + int(
            self.recepcion.get("movimientos",
                               self.recepcion.get("recepciones", 0)))

    @property
    def cajas_movidas(self) -> int:
        """Cajas movidas en total (pickeadas + bajadas + recibidas)."""
        return self.cajas_pickeadas + self.cajas_reapro + self.cajas_recibidas

    def desglose_movimientos(self) -> list[dict]:
        """Los movimientos del dia, separados por tipo."""
        picks = int(self.tareas.get("ok", {}).get("tareas", 0))
        picks += int(self.tareas.get("parcial", {}).get("tareas", 0))
        return [
            {"tipo": "Picking", "movimientos": picks,
             "cajas": self.cajas_pickeadas},
            {"tipo": "Reaprovisionamiento (grua)",
             "movimientos": int(self.reapro.get("tareas", 0)),
             "cajas": self.cajas_reapro},
            {"tipo": "Recepcion (recibir + ubicar)",
             "movimientos": int(self.recepcion.get("movimientos",
                                                    self.recepcion.get("recepciones", 0))),
             "cajas": self.cajas_recibidas},
        ]

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
        if self.reapro.get("pendientes"):
            a.append({"nivel": "warn",
                      "texto": f"{self.reapro['pendientes']} reaprovisionamientos sin "
                               f"confirmar (la grua no los bajo)"})
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

        # Reaprovisionamiento (movimientos de grua)
        try:
            reapro_mov = pd.read_sql_query(
                """SELECT fecha, operador, sku, descripcion, origen, destino,
                          cantidad, estado FROM reapro ORDER BY id""", con)
            reapro_res = {
                "tareas": int(reapro_mov["cantidad"].count()),
                "cajas": int(reapro_mov["cantidad"].sum()) if len(reapro_mov) else 0,
                "pendientes": int((reapro_mov["estado"] == "pendiente").sum())
                if len(reapro_mov) else 0,
                "hechas": int((reapro_mov["estado"] == "ok").sum())
                if len(reapro_mov) else 0,
            }
        except Exception:
            reapro_mov = pd.DataFrame(columns=["fecha", "operador", "sku",
                                               "descripcion", "origen", "destino",
                                               "cantidad", "estado"])
            reapro_res = {"tareas": 0, "cajas": 0, "pendientes": 0, "hechas": 0}

        # Cajas movidas por SKU (lo pickeado)
        por_sku = pd.read_sql_query(
            """SELECT sku, descripcion, SUM(cantidad) AS cajas, COUNT(*) AS picks
                 FROM picking GROUP BY sku ORDER BY cajas DESC""", con)

        # Ubicaciones que se tocaron (para reingresar a Blue Yonder)
        ubicaciones = pd.read_sql_query(
            """SELECT ubicacion, COUNT(*) AS picks, SUM(cantidad) AS cajas
                 FROM picking GROUP BY ubicacion ORDER BY cajas DESC""", con)

    from . import operarios as ops

    return ResumenDia(
        productividad=ops.productividad(db, "picking"),
        fecha=fecha,
        generado=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        stock=sv.resumen(db),
        tareas=pk.resumen_tareas(db),
        recepcion=rc.resumen(db),
        picking_mov=picking_mov,
        recepcion_mov=recep_mov,
        reapro_mov=reapro_mov,
        reapro=reapro_res,
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
        {"concepto": "MOVIMIENTOS DE LA JORNADA", "valor": d.movimientos_totales},
        {"concepto": "Cajas movidas (total)", "valor": d.cajas_movidas},
        {"concepto": "Stock total (foto)", "valor": d.stock.get("total", 0)},
        {"concepto": "Reservado", "valor": d.stock.get("reservado", 0)},
        {"concepto": "Pickeado", "valor": d.stock.get("pickeado", 0)},
        {"concepto": "Disponible", "valor": d.stock.get("disponible", 0)},
        {"concepto": "Cajas recibidas", "valor": d.cajas_recibidas},
        {"concepto": "Recepciones", "valor": d.recepcion.get("recepciones", 0)},
        {"concepto": "Recepciones sin ubicar", "valor": d.recepcion.get("pendientes", 0)},
        {"concepto": "Movimientos de reapro", "valor": d.reapro.get("tareas", 0)},
        {"concepto": "Cajas bajadas de almacen", "valor": d.cajas_reapro},
    ])

    with pd.ExcelWriter(destino, engine="openpyxl") as xw:
        resumen.to_excel(xw, sheet_name="Resumen", index=False)
        pd.DataFrame(d.desglose_movimientos()).to_excel(
            xw, sheet_name="Movimientos", index=False)
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
        if not d.reapro_mov.empty:
            d.reapro_mov.to_excel(xw, sheet_name="Reaprovisionamiento", index=False)
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
        productividad=[p for p in d.productividad if p["movimientos"]],
        recepcion_mov=d.recepcion_mov.to_dict("records"),
        reapro=d.reapro,
        reapro_mov=d.reapro_mov.to_dict("records"),
        skus_nuevos=d.skus_nuevos.to_dict("records"),
    )
    destino.write_text(html, encoding="utf-8")
    return destino
