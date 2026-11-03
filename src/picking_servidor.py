"""Servidor local de picking para los terminales RF (Zebra Android).

Levanta una app WEB (no hace falta APK) que corre en el navegador del Zebra.
El lector de codigos se integra solo: DataWedge de Zebra escribe el codigo como
si fuera teclado, y la pagina lo captura en el campo que tiene el foco.

Uso:
    python -m src.picking_servidor [--puerto 8080] [--db data/plan_b.sqlite]

Luego, en el Zebra (mismo WiFi), abrir:
    http://<IP-del-PC>:8080/

El flujo de picking es: escanear ubicacion -> escanear SKU/LPN -> cantidad ->
confirmar. Cada movimiento se guarda en SQLite (tabla 'picking') para reingresarlo
a Blue Yonder cuando vuelva.

NOTA: esto es un PROTOTIPO para validar el concepto con un solo Zebra.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DB_DEFECTO = "data/plan_b.sqlite"

PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Picking contingencia</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 12px;
         background: #0b1220; color: #e6edf7; font-size: 20px; }
  h1 { font-size: 22px; margin: 0 0 12px; }
  .paso { background: #16233a; border-radius: 12px; padding: 14px; margin-bottom: 12px;
          border-left: 6px solid #2b3d5c; }
  .paso.activo { border-left-color: #38bdf8; background: #1b2c48; }
  .paso.listo { border-left-color: #22c55e; }
  label { display: block; font-size: 15px; color: #93a4bf; margin-bottom: 6px; }
  input { width: 100%; font-size: 26px; padding: 14px; border-radius: 10px;
          border: 2px solid #2b3d5c; background: #0b1220; color: #e6edf7; }
  input:focus { outline: none; border-color: #38bdf8; }
  .dato { font-size: 26px; font-weight: 700; padding: 14px; min-height: 58px;
          border-radius: 10px; background: #0b1220; border: 2px dashed #2b3d5c; }
  .ok { color: #4ade80; }
  .err { color: #f87171; }
  .fila { display: flex; gap: 10px; }
  .fila > * { flex: 1; }
  button { width: 100%; font-size: 24px; font-weight: 700; padding: 18px;
           border: 0; border-radius: 12px; background: #2563eb; color: #fff;
           margin-top: 8px; }
  button:disabled { background: #334155; color: #94a3b8; }
  button.gris { background: #475569; }
  #msg { margin-top: 12px; padding: 12px; border-radius: 10px; min-height: 48px;
         font-size: 18px; background: #16233a; }
  .oculto { display: none; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; margin-top: 10px; }
  th, td { text-align: left; padding: 6px; border-bottom: 1px solid #2b3d5c; }
</style>
</head>
<body>
<h1>Picking — contingenciа</h1>

<div class="paso activo" id="p1">
  <label>1. Ubicacion</label>
  <input id="ubicacion" autocomplete="off" autofocus placeholder="escanee ubicacion">
</div>

<div class="paso" id="p2">
  <label>2. SKU o LPN</label>
  <input id="sku" autocomplete="off" placeholder="escanee SKU o LPN" disabled>
</div>

<div class="paso" id="p3">
  <label>3. Cantidad</label>
  <div class="fila">
    <input id="cantidad" type="number" inputmode="numeric" value="1" disabled>
    <button id="btnOk" disabled>CONFIRMAR</button>
  </div>
</div>

<div id="msg">Escanee una ubicacion para empezar.</div>

<div class="paso">
  <label>Ultimos movimientos</label>
  <table id="hist"><tbody></tbody></table>
</div>

<script>
const $ = id => document.getElementById(id);
const ubic = $('ubicacion'), sku = $('sku'), cant = $('cantidad'), msg = $('msg');
const btn = $('btnOk');

function aviso(texto, clase) {
  msg.className = clase || '';
  msg.textContent = texto;
}

function paso(n, activo) {
  const el = $('p' + n);
  el.classList.toggle('activo', activo);
  el.classList.toggle('listo', !activo && n < pasoActual);
}
let pasoActual = 1;

// DataWedge escribe el codigo y manda ENTER al final -> usamos 'change'
ubic.addEventListener('change', async () => {
  const v = ubic.value.trim();
  if (!v) return;
  const r = await fetch('/api/ubicacion?codigo=' + encodeURIComponent(v));
  const j = await r.json();
  if (!j.ok) { aviso('Ubicacion no encontrada: ' + v, 'err'); ubic.select(); return; }
  aviso('Ubicacion ' + v + ' — ' + j.skus + ' SKUs disponibles. Escanee el SKU.', 'ok');
  ubic.disabled = true; sku.disabled = false; sku.focus();
  pasoActual = 2; paso(1, false); paso(2, true);
});

sku.addEventListener('change', async () => {
  const v = sku.value.trim();
  if (!v) return;
  const r = await fetch('/api/sku?ubicacion=' + encodeURIComponent(ubic.value.trim()) +
                        '&codigo=' + encodeURIComponent(v));
  const j = await r.json();
  if (!j.ok) { aviso('SKU/LPN no encontrado en esa ubicacion: ' + v, 'err'); sku.select(); return; }
  aviso('OK: ' + j.descripcion + ' | disponible ' + j.disponible +
        ' | vence ' + j.caducidad, 'ok');
  sku.disabled = true; cant.disabled = false; btn.disabled = false; cant.focus();
  pasoActual = 3; paso(2, false); paso(3, true);
});

btn.addEventListener('click', async () => {
  const cuerpo = {
    ubicacion: ubic.value.trim(),
    codigo: sku.value.trim(),
    cantidad: parseInt(cant.value || '0', 10),
    usuario: 'RESIDENTE-STG',
  };
  const r = await fetch('/api/confirmar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cuerpo),
  });
  const j = await r.json();
  if (!j.ok) { aviso('Error: ' + j.error, 'err'); return; }
  aviso('Confirmado: ' + cuerpo.cantidad + ' x ' + j.sku + ' desde ' + cuerpo.ubicacion, 'ok');
  agregarHist(cuerpo, j);
  // reiniciar
  ubic.value = ''; sku.value = ''; cant.value = 1;
  ubic.disabled = false; sku.disabled = true; cant.disabled = true; btn.disabled = true;
  pasoActual = 1; paso(1, true); paso(2, false); paso(3, false);
  ubic.focus();
});

function agregarHist(c, j) {
  const tr = document.createElement('tr');
  tr.innerHTML = '<td>' + new Date().toLocaleTimeString() + '</td>' +
                 '<td>' + c.ubicacion + '</td>' +
                 '<td>' + j.sku + '</td>' +
                 '<td>' + c.cantidad + '</td>';
  $('hist').prepend(tr);
}
</script>
</body>
</html>
"""


def _conectar(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.execute("""
        CREATE TABLE IF NOT EXISTS picking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, ubicacion TEXT, sku TEXT, lpn TEXT,
            cantidad INTEGER, descripcion TEXT, lote TEXT, caducidad TEXT
        )
    """)
    con.commit()
    return con


def _a_fecha(texto: str):
    """Convierte 'dd/mm/aaaa HH:MM:SS' a datetime para ordenar FEFO de verdad."""
    if not texto:
        return datetime.max
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto.strip(), fmt)
        except ValueError:
            continue
    return datetime.max


def _buscar_sku(con: sqlite3.Connection, ubicacion: str, codigo: str) -> dict | None:
    """Busca por SKU o por LPN dentro de la ubicacion, eligiendo lo que VENCE ANTES.

    El SKU puede venir con ceros a la izquierda ("000622") y escanearse sin ellos
    ("622"), asi que se compara con ltrim.
    """
    cur = con.execute(
        """SELECT sku, lpn, descripcion, cantidad, fecha_caducidad
             FROM stock
            WHERE ubicacion = ?
              AND (ltrim(sku, '0') = ltrim(?, '0') OR ltrim(lpn, '0') = ltrim(?, '0'))""",
        (ubicacion, codigo, codigo),
    )
    filas = cur.fetchall()
    if not filas:
        return None
    # FEFO: la fecha viene como texto dd/mm/aaaa, hay que parsearla para ordenar
    # bien (como texto, "01/03/2027" quedaria antes que "01/12/2026", que es falso).
    elegida = min(filas, key=lambda f: _a_fecha(f[4]))
    return {
        "sku": elegida[0], "lpn": elegida[1], "descripcion": elegida[2],
        "disponible": elegida[3], "caducidad": elegida[4] or "",
    }


class Handler(BaseHTTPRequestHandler):
    db = DB_DEFECTO

    def log_message(self, fmt, *args):
        pass

    def _json(self, datos: dict, code: int = 200):
        cuerpo = json.dumps(datos).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _html(self, texto: str, code: int = 200):
        cuerpo = texto.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            self._html(PAGINA)
            return

        if u.path == "/api/ubicacion":
            codigo = qs.get("codigo", [""])[0].strip()
            with _conectar(self.db) as con:
                n = con.execute(
                    "SELECT COUNT(DISTINCT sku) FROM stock WHERE ubicacion = ?",
                    (codigo,),
                ).fetchone()[0]
            self._json({"ok": n > 0, "skus": n})
            return

        if u.path == "/api/sku":
            ubicacion = qs.get("ubicacion", [""])[0].strip()
            codigo = qs.get("codigo", [""])[0].strip()
            with _conectar(self.db) as con:
                dato = _buscar_sku(con, ubicacion, codigo)
            if not dato:
                self._json({"ok": False})
                return
            self._json({"ok": True, **dato})
            return

        self._json({"ok": False, "error": "ruta desconocida"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/confirmar":
            self._json({"ok": False, "error": "ruta desconocida"}, 404)
            return

        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(largo) or b"{}")

        ubicacion = str(cuerpo.get("ubicacion", "")).strip()
        codigo = str(cuerpo.get("codigo", "")).strip()
        cantidad = int(cuerpo.get("cantidad", 0))
        usuario = str(cuerpo.get("usuario", "")).strip()

        if not ubicacion or not codigo or cantidad <= 0:
            self._json({"ok": False, "error": "datos incompletos"}, 400)
            return

        with _conectar(self.db) as con:
            dato = _buscar_sku(con, ubicacion, codigo)
            if not dato:
                self._json({"ok": False, "error": "SKU/LPN no encontrado"}, 400)
                return
            if cantidad > dato["disponible"]:
                self._json(
                    {"ok": False,
                     "error": f"pide {cantidad} pero solo hay {dato['disponible']}"},
                    400,
                )
                return
            con.execute(
                """INSERT INTO picking
                   (fecha, usuario, ubicacion, sku, lpn, cantidad, descripcion,
                    lote, caducidad)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(timespec="seconds"), usuario, ubicacion,
                 dato["sku"], dato["lpn"], cantidad, dato["descripcion"],
                 dato["lpn"], dato["caducidad"]),
            )
            con.commit()

        self._json({"ok": True, "sku": dato["sku"], "lpn": dato["lpn"]})


def main() -> int:
    ap = argparse.ArgumentParser(description="Servidor local de picking (contingencia)")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--db", default=DB_DEFECTO)
    args = ap.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(
            f"No existe {args.db}. Carga primero el stock: "
            f"python -m src.plan_b_main --db {args.db} cargar --archivo <tsv>"
        )

    Handler.db = args.db
    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Handler)
    print(f"Picking en http://0.0.0.0:{args.puerto}/  (base: {args.db})")
    print("Abrir esa URL desde el Zebra (mismo WiFi). Ctrl+C para salir.")
    servidor.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
