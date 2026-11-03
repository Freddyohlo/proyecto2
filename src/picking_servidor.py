"""Servidor de picking GUIADO para los terminales RF (Zebra Android).

Levanta una app WEB (no hace falta APK) que corre en el navegador del Zebra.
El lector se integra solo: DataWedge (Chrome) o Enterprise Browser escriben el
codigo como si fuera teclado y la pagina lo captura.

COMO FUNCIONA EL PICKING (confirmado por el usuario, 2026-11-03):
  - El sistema DIRIGE: "ve a la ubicacion X y saca N cajas".
  - El picker escanea el QR del rack (que trae SOLO la ubicacion) y el sistema
    VERIFICA que sea la ubicacion correcta.
  - NO se escanea el SKU al pickear: la ubicacion de picking es unica por SKU,
    asi que la ubicacion ya identifica el producto.
  - Los codigos de barras de producto y LPN se escanean SOLO EN RECEPCION.

Uso:
    python -m src.picking_servidor --puerto 8080 --db data/plan_b.sqlite

Y en el Zebra (mismo WiFi):
    http://<IP-del-PC>:8080/
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
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 12px;
         background: #0b1220; color: #e6edf7; font-size: 20px; }
  h1 { font-size: 20px; margin: 0 0 10px; color: #93a4bf; font-weight: 600; }

  #progreso { font-size: 16px; color: #93a4bf; margin-bottom: 10px; }

  .tarjeta { background: #16233a; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
  .destino { border-left: 8px solid #38bdf8; }
  .destino .etq { font-size: 15px; color: #93a4bf; }
  .destino .valor { font-size: 52px; font-weight: 800; line-height: 1.05; margin: 4px 0; }
  .destino .prod { font-size: 19px; color: #cbd8ea; }
  .destino .cant { font-size: 34px; font-weight: 800; color: #4ade80; margin-top: 6px; }
  .destino .lote { font-size: 15px; color: #93a4bf; margin-top: 6px; }

  input { width: 100%; font-size: 26px; padding: 16px; border-radius: 12px;
          border: 2px solid #2b3d5c; background: #0b1220; color: #e6edf7; }
  input:focus { outline: none; border-color: #38bdf8; }

  #pasoCant { margin-top: 12px; }
  #pasoCant .etq { font-size: 15px; color: #93a4bf; margin-bottom: 8px; }
  #cantidad { font-size: 40px; font-weight: 800; text-align: center; }

  button { width: 100%; font-size: 26px; font-weight: 800; padding: 20px;
           border: 0; border-radius: 12px; color: #fff; margin-top: 10px; }
  #btnOk { background: #16a34a; }
  #btnOk:disabled { background: #334155; color: #94a3b8; }
  .gris { background: #475569; font-size: 18px; padding: 14px; }

  #msg { padding: 14px; border-radius: 12px; min-height: 52px; font-size: 18px;
         background: #16233a; margin-bottom: 12px; }
  #msg.ok { background: #14532d; color: #bbf7d0; }
  #msg.err { background: #7f1d1d; color: #fecaca; }

  #hecho { text-align: center; padding: 40px 10px; }
  #hecho .big { font-size: 64px; }
  .oculto { display: none; }
</style>
</head>
<body>

<h1>Picking — contingencia</h1>
<div id="progreso"></div>

<div id="msg">Cargando tarea...</div>

<div id="trabajo" class="oculto">
  <div class="tarjeta destino">
    <div class="etq">Vaya a la ubicacion</div>
    <div class="valor" id="dUbic">—</div>
    <div class="prod" id="dProd">—</div>
    <div class="cant" id="dCant">—</div>
    <div class="lote" id="dLote"></div>
  </div>

  <div class="tarjeta">
    <div class="etq" style="font-size:15px;color:#93a4bf;margin-bottom:8px;">
      Escanee el QR del rack para confirmar
    </div>
    <input id="scan" autocomplete="off" placeholder="escaneando..." autofocus>

    <div id="pasoCant" class="oculto">
      <div class="etq">Cantidad pickeada</div>
      <input id="cantidad" type="number" inputmode="numeric" min="1"
             autocomplete="off" placeholder="0">
    </div>

    <button id="btnOk" disabled>CONFIRMAR PICK</button>
    <button id="btnSaltar" class="gris">Saltar tarea</button>
  </div>
</div>

<div id="hecho" class="oculto">
  <div class="big">✅</div>
  <div>No quedan tareas pendientes.</div>
</div>

<script>
const $ = id => document.getElementById(id);
const scan = $('scan'), msg = $('msg'), btnOk = $('btnOk'), btnSaltar = $('btnSaltar');
const pasoCant = $('pasoCant'), cant = $('cantidad');
let tarea = null;

function aviso(texto, clase) {
  msg.className = clase || '';
  msg.textContent = texto;
}

async function cargarTarea() {
  const r = await fetch('/api/tarea');
  const j = await r.json();
  if (!j.ok) {
    $('trabajo').classList.add('oculto');
    $('hecho').classList.remove('oculto');
    $('progreso').textContent = '';
    return;
  }
  tarea = j.tarea;
  $('hecho').classList.add('oculto');
  $('trabajo').classList.remove('oculto');
  $('dUbic').textContent = tarea.ubicacion;
  $('dProd').textContent = tarea.descripcion || tarea.sku;
  $('dCant').textContent = tarea.cantidad + ' cajas';
  $('dLote').textContent = (tarea.lote ? 'Lote ' + tarea.lote : '') +
                           (tarea.caducidad ? '  |  vence ' + tarea.caducidad : '');
  $('progreso').textContent = 'Tarea ' + (j.hechas + 1) + ' de ' + j.total;
  scan.value = ''; scan.disabled = false; btnOk.disabled = true;
  pasoCant.classList.add('oculto'); cant.value = '';
  aviso('Vaya a ' + tarea.ubicacion + ' y escanee el QR del rack.');
  scan.focus();
}

// El escaner escribe el codigo y manda ENTER -> 'change'
scan.addEventListener('change', () => {
  const v = scan.value.trim();
  if (!v || !tarea) return;
  // El QR trae solo la ubicacion; verificamos contra la ubicacion esperada
  fetch('/api/verificar?ubicacion=' + encodeURIComponent(tarea.ubicacion) +
        '&codigo=' + encodeURIComponent(v))
    .then(r => r.json())
    .then(j => {
      if (!j.ok) {
        aviso('❌ Ubicacion equivocada: ' + (j.leida || v) +
              '. Deberia ser ' + tarea.ubicacion + '.', 'err');
        scan.select();
        return;
      }
      aviso('✅ Ubicacion correcta. Digite la cantidad.', 'ok');
      scan.disabled = true;
      pasoCant.classList.remove('oculto');
      cant.focus();
    });
});

// Al escribir la cantidad se valida contra lo pedido
cant.addEventListener('input', () => {
  const n = parseInt(cant.value || '0', 10);
  if (n <= 0) { btnOk.disabled = true; return; }
  if (n > tarea.cantidad) {
    aviso('⚠️ Pedido ' + tarea.cantidad + ' cajas; digitaste ' + n + '.', 'err');
    btnOk.disabled = true;
    return;
  }
  if (n < tarea.cantidad) {
    aviso('Faltante: pide ' + tarea.cantidad + ' y digitaste ' + n + '.', '');
  } else {
    aviso('Cantidad completa. Confirme el pick.', 'ok');
  }
  btnOk.disabled = false;
});

btnOk.addEventListener('click', async () => {
  const n = parseInt(cant.value || '0', 10);
  const r = await fetch('/api/confirmar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: tarea.id, cantidad: n, usuario: 'RESIDENTE-STG'}),
  });
  const j = await r.json();
  if (!j.ok) { aviso('Error: ' + j.error, 'err'); return; }
  aviso('Confirmado: ' + j.cantidad + ' x ' + (tarea.descripcion || tarea.sku), 'ok');
  setTimeout(cargarTarea, 400);
});

btnSaltar.addEventListener('click', async () => {
  await fetch('/api/saltar', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: tarea.id, usuario: 'RESIDENTE-STG'}),
  });
  cargarTarea();
});

cargarTarea();
</script>
</body>
</html>
"""


def parsear_ubicacion(escaneo: str) -> str:
    """Extrae el codigo de ubicacion de lo que devuelve el QR del rack.

    El usuario confirmo que el QR trae SOLO la ubicacion, pero se toleran
    variantes por si el formato cambia:
      "60-001"                          -> "60-001"
      "LOC:60-001" / "UBIC:60-001"      -> "60-001"
      "https://host/ub?loc=60-001"      -> "60-001"
      " 60-001 "                        -> "60-001"
    Si no se reconoce nada, devuelve el texto tal cual (mejor intentar que fallar).
    """
    if not escaneo:
        return ""
    texto = str(escaneo).strip()

    if "://" in texto or "?" in texto:
        consulta = parse_qs(urlparse(texto).query)
        for clave in ("loc", "ubicacion", "location", "ubic"):
            if consulta.get(clave):
                return consulta[clave][0].strip()

    if ":" in texto and "://" not in texto:
        prefijo, _, resto = texto.partition(":")
        if prefijo.strip().upper() in ("LOC", "UBIC", "UBICACION", "LOCATION", "STOLOC"):
            return resto.strip()

    if "|" in texto:
        return texto.split("|")[0].strip()

    return texto


def _conectar(db: str) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS picking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, usuario TEXT, ubicacion TEXT, sku TEXT, lpn TEXT,
            cantidad INTEGER, descripcion TEXT, lote TEXT, caducidad TEXT
        )
    """)
    con.commit()
    return con


def _primera_tarea(con: sqlite3.Connection) -> dict | None:
    fila = con.execute(
        "SELECT * FROM tareas WHERE estado = 'pendiente' ORDER BY id LIMIT 1"
    ).fetchone()
    if fila is None:
        return None
    total = con.execute("SELECT COUNT(*) FROM tareas").fetchone()[0]
    hechas = con.execute("SELECT COUNT(*) FROM tareas WHERE estado = 'ok'").fetchone()[0]
    return {**dict(fila), "total": total, "hechas": hechas}


class Handler(BaseHTTPRequestHandler):
    db = DB_DEFECTO

    def log_message(self, fmt, *args):
        pass

    def _json(self, datos: dict, code: int = 200):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
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

    def _cuerpo(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo) or b"{}")

    # ------------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            self._html(PAGINA)
            return

        if u.path == "/api/tarea":
            with _conectar(self.db) as con:
                t = _primera_tarea(con)
            if t is None:
                self._json({"ok": False})
                return
            self._json({"ok": True, "tarea": {
                "id": t["id"], "ubicacion": t["ubicacion"], "sku": t["sku"],
                "descripcion": t["descripcion"], "cantidad": t["cantidad"],
                "lote": t["lote"], "caducidad": t["caducidad"],
            }, "total": t["total"], "hechas": t["hechas"]})
            return

        if u.path == "/api/verificar":
            esperada = qs.get("ubicacion", [""])[0].strip()
            leida = parsear_ubicacion(qs.get("codigo", [""])[0])
            self._json({"ok": leida == esperada, "leida": leida,
                        "esperada": esperada})
            return

        self._json({"ok": False, "error": "ruta desconocida"}, 404)

    # ------------------------------------------------------------------
    def do_POST(self):
        u = urlparse(self.path)

        if u.path == "/api/confirmar":
            datos = self._cuerpo()
            try:
                id_tarea = int(datos.get("id", 0))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "id invalido"}, 400)
                return
            usuario = str(datos.get("usuario", "")).strip()

            with _conectar(self.db) as con:
                t = con.execute("SELECT * FROM tareas WHERE id = ?", (id_tarea,)).fetchone()
                if t is None:
                    self._json({"ok": False, "error": "tarea inexistente"}, 404)
                    return
                if t["estado"] != "pendiente":
                    self._json({"ok": False, "error": "la tarea ya no esta pendiente"}, 400)
                    return

                # La cantidad la digita el picker; si no la manda, se asume la pedida.
                pedida = int(t["cantidad"])
                try:
                    digitada = int(datos.get("cantidad", pedida))
                except (TypeError, ValueError):
                    self._json({"ok": False, "error": "cantidad invalida"}, 400)
                    return
                if digitada <= 0:
                    self._json({"ok": False, "error": "la cantidad debe ser mayor que 0"}, 400)
                    return
                if digitada > pedida:
                    self._json(
                        {"ok": False,
                         "error": f"pedido {pedida} y se digito {digitada}"},
                        400,
                    )
                    return

                con.execute(
                    """INSERT INTO picking
                       (fecha, usuario, ubicacion, sku, lpn, cantidad, descripcion,
                        lote, caducidad)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (datetime.now().isoformat(timespec="seconds"), usuario,
                     t["ubicacion"], t["sku"], t["lote"], digitada,
                     t["descripcion"], t["lote"], t["caducidad"]),
                )
                # Si pickeo menos de lo pedido, la tarea queda marcada como parcial.
                estado = "ok" if digitada == pedida else "parcial"
                con.execute(
                    """UPDATE tareas SET estado = ?, fecha_ok = ?, usuario = ?,
                       cantidad_ok = ? WHERE id = ?""",
                    (estado, datetime.now().isoformat(timespec="seconds"),
                     usuario, digitada, id_tarea),
                )
                # Lo que quedo sin pickear no se pierde: se re-encola como tarea nueva.
                if digitada < pedida:
                    con.execute(
                        """INSERT INTO tareas
                           (ubicacion, sku, descripcion, cantidad, lote, caducidad, area)
                           VALUES (?,?,?,?,?,?,?)""",
                        (t["ubicacion"], t["sku"], t["descripcion"],
                         pedida - digitada, t["lote"], t["caducidad"], t["area"]),
                    )
                con.commit()
            self._json({"ok": True, "cantidad": digitada, "sku": t["sku"],
                        "estado": estado, "pedida": pedida})
            return

        if u.path == "/api/saltar":
            datos = self._cuerpo()
            id_tarea = int(datos.get("id", 0))
            usuario = str(datos.get("usuario", "")).strip()
            with _conectar(self.db) as con:
                con.execute(
                    "UPDATE tareas SET estado = 'saltada', usuario = ? WHERE id = ?",
                    (usuario, id_tarea),
                )
                con.commit()
            self._json({"ok": True})
            return

        self._json({"ok": False, "error": "ruta desconocida"}, 404)


def main() -> int:
    ap = argparse.ArgumentParser(description="Picking guiado de contingencia")
    ap.add_argument("--puerto", type=int, default=8080)
    ap.add_argument("--db", default=DB_DEFECTO)
    args = ap.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"No existe {args.db}. Carga primero el stock.")

    Handler.db = args.db
    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Handler)
    print(f"Picking guiado en http://0.0.0.0:{args.puerto}/  (base: {args.db})")
    print("Abrir esa URL desde el Zebra (mismo WiFi). Ctrl+C para salir.")
    servidor.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
