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

from . import picking as pk

DB_DEFECTO = "data/plan_b.sqlite"

PAGINA_MENU = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contingencia</title>
<style>
  :root {
    --fondo:#f1f5f9; --panel:#ffffff; --borde:#cbd5e1;
    --texto:#0f172a; --suave:#64748b; --acento:#1e40af;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
         margin:0; background:var(--fondo); color:var(--texto); }
  header { background:#ffffff; border-bottom:1px solid var(--borde); padding:18px 24px; }
  header h1 { margin:0; font-size:20px; font-weight:600; letter-spacing:-.01em; }
  header p { margin:4px 0 0; font-size:13px; color:var(--suave); }
  .wrap { max-width:1000px; margin:0 auto; padding:24px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--suave); font-weight:600; margin:0 0 12px; }
  .grid { display:grid; grid-template-columns:repeat(2, 1fr); gap:14px; }
  @media (max-width:640px) { .grid { grid-template-columns:1fr; } }
  a.op { display:block; text-decoration:none; color:var(--texto); background:var(--panel);
         border:1px solid var(--borde); border-radius:8px; padding:18px 20px;
         transition:.12s; }
  a.op:hover { border-color:var(--acento); box-shadow:0 2px 8px rgba(30,64,175,.10); }
  a.op .t { font-size:16px; font-weight:600; }
  a.op .d { font-size:13px; color:var(--suave); margin-top:4px; }
  a.op .ico { float:right; font-size:18px; color:var(--suave); }
  .seccion { margin-top:26px; }
  .panel { background:var(--panel); border:1px solid var(--borde); border-radius:8px;
           padding:18px 20px; }
  .panel table { width:100%; border-collapse:collapse; font-size:13px; }
  .panel th, .panel td { text-align:left; padding:7px 8px;
                         border-bottom:1px solid #e2e8f0; }
  .panel th { color:var(--suave); font-weight:600; }
  .panel td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .btn { display:inline-block; margin:12px 8px 0 0; padding:10px 16px; font-size:14px;
         border-radius:6px; border:1px solid var(--borde); background:#f8fafc;
         color:var(--texto); text-decoration:none; cursor:pointer; }
  .btn:hover { background:#e2e8f0; }
  .alerta { padding:10px 14px; border-radius:6px; font-size:13px; margin-bottom:10px; }
  .alerta.ok { background:#dcfce7; color:#166534; border:1px solid #86efac; }
  .alerta.warn { background:#fef3c7; color:#92400e; border:1px solid #fcd34d; }
  .alerta.err { background:#fee2e2; color:#991b1b; border:1px solid #fca5a5; }
  .oculto { display:none; }
  footer { color:var(--suave); font-size:12px; text-align:center; padding:24px; }
</style>
</head>
<body>

<header>
  <h1>Sistema de contingencia — WMS</h1>
  <p>Blue Yonder fuera de servicio · operación de bodega</p>
</header>

<div class="wrap">

  <div class="seccion">
    <h2>Operación</h2>
    <div class="grid">
      <a class="op" href="/picking">
        <span class="ico">→</span>
        <div class="t">Picking</div>
        <div class="d">Ir a la ubicación indicada y confirmar el retiro</div>
      </a>
      <a class="op" href="/recepcion">
        <span class="ico">→</span>
        <div class="t">Recepción de mercadería</div>
        <div class="d">Escanear la tarja del pallet que llegó</div>
      </a>
      <a class="op" href="/reapro">
        <span class="ico">→</span>
        <div class="t">Reaprovisionamiento</div>
        <div class="d">Ver qué está bajo el mínimo y bajar de almacén</div>
      </a>
      <a class="op" href="/grua">
        <span class="ico">→</span>
        <div class="t">Grúa</div>
        <div class="d">Tareas de bajada asignadas al operador de grúa</div>
      </a>
    </div>
  </div>

  <div class="seccion">
    <h2>Sistema</h2>
    <div class="grid">
      <a class="op" href="/estado">
        <span class="ico">→</span>
        <div class="t">Estado del stock</div>
        <div class="d">Existencias, reservas y movimientos del día</div>
      </a>
      <a class="op" href="/cola">
        <span class="ico">→</span>
        <div class="t">Operaciones de sistema — cola de trabajos</div>
        <div class="d">Panorama del avance de los trabajos</div>
      </a>
    </div>
  </div>

  <div class="seccion">
    <h2>Administración</h2>
    <div class="grid">
      <a class="op" href="#" onclick="cerrarDia(); return false;">
        <span class="ico">→</span>
        <div class="t">Cerrar el día</div>
        <div class="d">Libera lo no pickeado y genera el informe de cierre</div>
      </a>
      <a class="op" href="/operarios">
        <span class="ico">→</span>
        <div class="t">Operarios</div>
        <div class="d">Asignar los usuarios fijos a los operarios del día</div>
      </a>
    </div>
  </div>

  <div id="cajaInforme" class="seccion oculto">
    <div class="panel">
      <div id="avisoInforme" style="font-size:14px;"></div>
      <div id="enlaces"></div>
    </div>
  </div>

</div>

<footer>Documento generado por el sistema de contingencia</footer>

<script>
async function cerrarDia() {
  if (!confirm('¿Cerrar el día? Se liberan las cajas que quedaron sin pickear y ' +
               'se genera el informe de cierre.')) return;
  const r = await fetch('/api/dia/cerrar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({usuario: 'SUPERVISOR'}),
  });
  const j = await r.json();
  if (!j.ok) { alert('Error: ' + j.error); return; }
  document.getElementById('avisoInforme').innerHTML =
    '<div class="alerta ok">Día ' + j.fecha + ' cerrado — ' +
    j.tareas_cerradas + ' tareas cerradas, ' + j.cajas_liberadas +
    ' cajas liberadas, ' + j.cajas_pickeadas + ' cajas pickeadas.</div>';
  document.getElementById('enlaces').innerHTML =
    '<a class="btn" href="' + j.html + '" target="_blank">Ver informe (HTML)</a>' +
    '<a class="btn" href="' + j.excel + '" target="_blank">Descargar Excel</a>';
  document.getElementById('cajaInforme').classList.remove('oculto');
}
</script>
</body>
</html>
"""

PAGINA_GRUA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Grua — reaprovisionamiento</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: system-ui, sans-serif; margin:0; padding:12px;
         background:#0b1220; color:#e6edf7; font-size:20px; position:relative; }
  h1 { font-size:20px; margin:0 0 10px; color:#93a4bf; font-weight:600; }
  .tarjeta { background:#16233a; border-radius:14px; padding:16px; margin-bottom:12px; }
  .de { font-size:16px; color:#93a4bf; }
  .ubic { font-size:40px; font-weight:800; line-height:1.1; margin:2px 0; }
  .flecha { font-size:28px; color:#38bdf8; text-align:center; margin:6px 0; }
  .prod { font-size:18px; color:#cbd8ea; }
  .cant { font-size:34px; font-weight:800; color:#4ade80; margin-top:8px; }
  button { width:100%; font-size:24px; font-weight:800; padding:20px; border:0;
           border-radius:12px; color:#fff; background:#16a34a; margin-top:10px; }
  button:disabled { background:#334155; color:#94a3b8; }
  #msg { padding:14px; border-radius:12px; min-height:50px; font-size:17px;
         background:#16233a; margin-bottom:12px; }
  #msg.ok { background:#14532d; color:#bbf7d0; }
  #msg.err { background:#7f1d1d; color:#fecaca; }
  .oculto { display:none; }
</style>
</head>
<body>
<a href="/" style="position:absolute;top:10px;right:12px;color:#93a4bf;
   text-decoration:none;font-size:14px;border:1px solid #2b3d5c;border-radius:8px;
   padding:6px 10px;background:#16233a;">← Menú</a>
<h1 id="titulo">Grua — reaprovisionamiento</h1>

<div id="login">
  <div class="tarjeta">
    <div style="font-size:16px;color:#93a4bf;margin-bottom:10px;">¿Quién eres?</div>
    <div id="operadores" style="display:flex;gap:8px;flex-wrap:wrap;"></div>
    <div style="font-size:16px;color:#93a4bf;margin:14px 0 8px;">Tu PIN</div>
    <input id="pin" type="password" inputmode="numeric" maxlength="6"
           style="width:100%;font-size:32px;font-weight:800;text-align:center;
                  letter-spacing:.3em;padding:14px;border-radius:12px;
                  border:2px solid #2b3d5c;background:#0b1220;color:#e6edf7;">
    <button id="btnEntrar" disabled>ENTRAR</button>
  </div>
</div>

<div id="msg" class="oculto">Cargando tarea...</div>

<div id="trabajo" class="oculto">
  <div class="tarjeta">
    <div class="de">Baje de</div>
    <div class="ubic" id="dOrigen">—</div>
    <div class="flecha">▼</div>
    <div class="de">y deje en el picking</div>
    <div class="ubic" id="dDestino">—</div>
    <div class="prod" id="dProd">—</div>
    <div class="cant" id="dCant">—</div>
  </div>
  <div class="tarjeta">
    <div style="font-size:15px;color:#93a4bf;margin-bottom:8px;">Cantidad bajada</div>
    <input id="cant" type="number" inputmode="numeric"
           style="width:100%;font-size:36px;font-weight:800;text-align:center;padding:12px;
                  border-radius:10px;border:2px solid #2b3d5c;background:#0b1220;color:#e6edf7;">
    <button id="btnOk">CONFIRMAR BAJADA</button>
  </div>
</div>

<div id="hecho" class="oculto" style="text-align:center;padding:40px 10px;">
  <div style="font-size:60px;">✅</div>
  <div>No quedan tareas de reapro.</div>
</div>

<script>
const $ = id => document.getElementById(id);
let tarea = null;
let operador = '';
function aviso(t, c) {
  $('msg').className = c || '';
  $('msg').textContent = t;
  $('msg').classList.remove('oculto');
}

async function cargarOperadores() {
  const r = await fetch('/api/reapro/operadores');
  const j = await r.json();
  const caja = $('operadores');
  caja.innerHTML = '';
  (j.operadores || []).forEach(o => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = o.etiqueta;
    b.style.cssText = 'flex:1;min-width:140px;background:#1e293b;color:#e6edf7;' +
      'border:2px solid #2b3d5c;border-radius:10px;padding:16px;font-size:18px;' +
      'font-weight:700;margin-top:0;';
    b.onclick = () => {
      operador = o.codigo;
      [...caja.children].forEach(c => c.style.borderColor = '#2b3d5c');
      b.style.borderColor = '#38bdf8';
      $('btnEntrar').disabled = !$('pin').value.trim();
      $('pin').focus();
    };
    caja.appendChild(b);
  });
}

$('pin').addEventListener('input', () => {
  $('btnEntrar').disabled = !(operador && $('pin').value.trim());
});

$('btnEntrar').addEventListener('click', async () => {
  const r = await fetch('/api/reapro/entrar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({operador: operador, pin: $('pin').value.trim()}),
  });
  const j = await r.json();
  if (!j.ok) {
    $('msg').className = 'err';
    $('msg').textContent = j.error || 'PIN incorrecto';
    $('pin').value = '';
    return;
  }
  $('login').classList.add('oculto');
  $('titulo').textContent = 'Grua — ' + (j.nombre || operador);
  $('pin').value = '';
  cargar();
});

async function cargar() {
  const r = await fetch('/api/reapro/tarea?operador=' + encodeURIComponent(operador));
  const j = await r.json();
  if (!j.ok) {
    $('trabajo').classList.add('oculto');
    $('hecho').classList.remove('oculto');
    return;
  }
  tarea = j.tarea;
  $('trabajo').classList.remove('oculto');
  $('hecho').classList.add('oculto');
  $('dOrigen').textContent = tarea.origen;
  $('dDestino').textContent = tarea.destino;
  $('dProd').textContent = tarea.descripcion || tarea.sku;
  $('dCant').textContent = tarea.cantidad + ' cajas';
  $('cant').value = tarea.cantidad;
  $('btnOk').disabled = false;
  aviso('Tarea ' + (j.hechas + 1) + ' de ' + j.total + '. Baje y confirme.');
  if (tarea.operador_nombre) $('titulo').textContent = 'Grua — ' + tarea.operador_nombre;
}

$('btnOk').addEventListener('click', async () => {
  const n = parseInt($('cant').value || '0', 10);
  if (n <= 0) { aviso('Cantidad invalida', 'err'); return; }
  const r = await fetch('/api/reapro/confirmar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: tarea.id, cantidad: n, usuario: operador}),
  });
  const j = await r.json();
  if (!j.ok) { aviso('Error: ' + j.error, 'err'); return; }
  aviso('✅ ' + j.cantidad + ' cajas de ' + j.origen + ' a ' + j.destino, 'ok');
  setTimeout(cargar, 400);
});

cargarOperadores();
</script>
</body>
</html>
"""


# Estilo comun a todas las pantallas de escritorio (no las del Zebra)
ESTILO_OFICINA = """
  :root { --fondo:#f1f5f9; --panel:#fff; --borde:#cbd5e1; --texto:#0f172a;
          --suave:#64748b; --acento:#1e40af; }
  * { box-sizing:border-box; }
  body { font-family:-apple-system, Segoe UI, Roboto, Arial, sans-serif; margin:0;
         background:var(--fondo); color:var(--texto); }
  header { background:#fff; border-bottom:1px solid var(--borde); padding:16px 24px;
           display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  header h1 { margin:0; font-size:19px; font-weight:600; }
  .volver { text-decoration:none; color:var(--acento); font-size:13px; font-weight:600;
            border:1px solid var(--borde); border-radius:6px; padding:8px 14px;
            background:#fff; }
  .volver:hover { background:#eff6ff; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
       color:var(--suave); font-weight:600; margin:22px 0 12px; }
  h2:first-child { margin-top:0; }
  .panel { background:var(--panel); border:1px solid var(--borde); border-radius:8px;
           padding:18px 20px; margin-bottom:16px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:8px; border-bottom:1px solid #e2e8f0; }
  th { color:var(--suave); font-weight:600; background:#f8fafc; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .card { background:#fff; border:1px solid var(--borde); border-radius:8px; padding:14px 16px; }
  .card .lbl { font-size:11px; text-transform:uppercase; letter-spacing:.05em;
               color:var(--suave); }
  .card .val { font-size:24px; font-weight:700; margin-top:4px;
               font-variant-numeric:tabular-nums; }
  .card .val small { font-size:12px; font-weight:400; color:var(--suave); }
  .barra { height:10px; background:#e2e8f0; border-radius:5px; overflow:hidden; margin-top:6px; }
  .barra > i { display:block; height:100%; background:var(--acento); }
  .btn { display:inline-block; padding:10px 16px; font-size:14px; border-radius:6px;
         border:1px solid var(--borde); background:#f8fafc; color:var(--texto);
         cursor:pointer; text-decoration:none; }
  .btn:hover { background:#e2e8f0; }
  .btn.pri { background:var(--acento); color:#fff; border-color:var(--acento); }
  input, select { font-size:14px; padding:9px 11px; border:1px solid var(--borde);
                  border-radius:6px; width:100%; background:#fff; color:var(--texto); }
  .alerta { padding:10px 14px; border-radius:6px; font-size:13px; margin-bottom:12px; }
  .alerta.ok { background:#dcfce7; color:#166534; border:1px solid #86efac; }
  .alerta.warn { background:#fef3c7; color:#92400e; border:1px solid #fcd34d; }
  .alerta.err { background:#fee2e2; color:#991b1b; border:1px solid #fca5a5; }
  footer { color:var(--suave); font-size:12px; text-align:center; padding:24px; }
"""

CABECERA = """
<header>
  <a class="volver" href="/">← Volver al menú</a>
  <h1>{titulo}</h1>
</header>
"""

PAGINA_ESTADO = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estado del stock</title><style>""" + ESTILO_OFICINA + """</style></head>
<body>
""" + CABECERA.format(titulo="Estado del stock") + """
<div class="wrap">
  <div class="cards" id="cards"></div>
  <h2>Movimientos del día</h2>
  <div class="panel"><table id="mov"><tbody></tbody></table></div>
  <h2>Tareas de picking</h2>
  <div class="panel"><table id="tareas"><tbody></tbody></table></div>
  <h2>Recepción</h2>
  <div class="panel"><table id="recep"><tbody></tbody></table></div>
</div>
<footer>Sistema de contingencia</footer>
<script>
function card(lbl, val, sub) {
  return '<div class="card"><div class="lbl">' + lbl + '</div>' +
         '<div class="val">' + val + (sub ? ' <small>' + sub + '</small>' : '') +
         '</div></div>';
}
function fila(a, b, c) {
  return '<tr><td>' + a + '</td><td class="num">' + b +
         '</td><td class="num">' + (c === undefined ? '' : c) + '</td></tr>';
}
async function cargar() {
  const r = await fetch('/api/estado');
  const j = await r.json();
  const s = j.stock || {}, t = j.tareas || {}, rec = j.recepcion || {};
  document.getElementById('cards').innerHTML =
    card('Cajas pickeadas', s.pickeado || 0) +
    card('Cajas recibidas', rec.cajas || 0) +
    card('Reservado', s.reservado || 0, 'en tareas') +
    card('Disponible', s.disponible || 0) +
    card('Recepciones', rec.recepciones || 0) +
    card('Sin ubicar', rec.pendientes || 0);
  let mt = '';
  mt += fila('Picking', (t.ok ? t.ok.tareas : 0) + (t.parcial ? t.parcial.tareas : 0),
             (t.ok ? t.ok.cajas : 0) + (t.parcial ? t.parcial.cajas : 0));
  mt += fila('Reaprovisionamiento', rec.movimientos ? '' : '', '');
  document.getElementById('mov').querySelector('tbody').innerHTML = mt;
  let tt = '<tr><th>Estado</th><th>Tareas</th><th>Cajas</th></tr>';
  for (const [k, v] of Object.entries(t)) {
    tt += fila(k, v.tareas, v.cajas);
  }
  if (!Object.keys(t).length) tt += '<tr><td colspan="3">Sin tareas.</td></tr>';
  document.getElementById('tareas').querySelector('tbody').innerHTML = tt;
  document.getElementById('recep').querySelector('tbody').innerHTML =
    '<tr><th>Concepto</th><th>Total</th><th></th></tr>' +
    fila('Recepciones', rec.recepciones || 0, '') +
    fila('Cajas recibidas', rec.cajas || 0, '') +
    fila('Pendientes de ubicar', rec.pendientes || 0, '') +
    fila('Sin vencimiento', rec.sin_vencimiento || 0, '');
}
cargar();
</script>
</body></html>
"""

PAGINA_COLA = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Cola de trabajos</title><style>""" + ESTILO_OFICINA + """</style></head>
<body>
""" + CABECERA.format(titulo="Operaciones de sistema — cola de trabajos") + """
<div class="wrap">
  <div id="avisos"></div>
  <div class="cards" id="resumen"></div>

  <h2>Avance de los trabajos</h2>
  <div class="panel" id="avance"></div>

  <h2>Cola de picking</h2>
  <div class="panel"><table id="cola"><tbody></tbody></table></div>

  <h2>Cola de reaprovisionamiento</h2>
  <div class="panel"><table id="colaReapro"><tbody></tbody></table></div>

  <h2>Productividad por operario</h2>
  <div class="panel"><table id="prod"><tbody></tbody></table></div>
</div>
<footer>Se actualiza solo cada 30 segundos</footer>
<script>
function card(lbl, val, sub) {
  return '<div class="card"><div class="lbl">' + lbl + '</div>' +
         '<div class="val">' + val + (sub ? ' <small>' + sub + '</small>' : '') +
         '</div></div>';
}
async function cargar() {
  const r = await fetch('/api/cola');
  const j = await r.json();

  document.getElementById('resumen').innerHTML =
    card('Movimientos del día', j.movimientos_totales) +
    card('Cajas movidas', j.cajas_movidas) +
    card('Tareas pendientes', j.picking.pendientes, 'picking') +
    card('Reapro pendientes', j.reapro.pendientes, 'grúa');

  let av = '';
  (j.desglose || []).forEach(m => {
    const tot = j.movimientos_totales || 1;
    const pct = Math.round(m.movimientos / tot * 100);
    av += '<div style="margin-bottom:12px;">' +
      '<div style="display:flex;justify-content:space-between;font-size:13px;">' +
      '<span>' + m.tipo + '</span><span class="num">' + m.movimientos +
      ' mov · ' + m.cajas + ' cajas</span></div>' +
      '<div class="barra"><i style="width:' + pct + '%"></i></div></div>';
  });
  document.getElementById('avance').innerHTML = av || 'Sin movimientos.';

  let c = '<tr><th>Ubicación</th><th>SKU</th><th>Cantidad</th><th>Usuario</th></tr>';
  (j.cola_picking || []).forEach(t => {
    c += '<tr><td>' + t.ubicacion + '</td><td>' + t.sku +
         '</td><td class="num">' + t.cantidad + '</td><td>' +
         (t.usuario || '—') + '</td></tr>';
  });
  if (!(j.cola_picking || []).length) c += '<tr><td colspan="4">Cola vacía.</td></tr>';
  document.getElementById('cola').querySelector('tbody').innerHTML = c;

  let cr = '<tr><th>Origen</th><th>Destino</th><th>Cantidad</th><th>Operador</th></tr>';
  (j.cola_reapro || []).forEach(t => {
    cr += '<tr><td>' + (t.origen || '—') + '</td><td>' + t.destino +
          '</td><td class="num">' + t.cantidad + '</td><td>' +
          (t.operador || '—') + '</td></tr>';
  });
  if (!(j.cola_reapro || []).length) cr += '<tr><td colspan="4">Cola vacía.</td></tr>';
  document.getElementById('colaReapro').querySelector('tbody').innerHTML = cr;

  let p = '<tr><th>Operario</th><th>Movimientos</th><th>Cajas</th></tr>';
  (j.productividad || []).forEach(x => {
    p += '<tr><td>' + x.etiqueta + '</td><td class="num">' + x.movimientos +
         '</td><td class="num">' + x.cajas + '</td></tr>';
  });
  document.getElementById('prod').querySelector('tbody').innerHTML = p;
}
cargar();
</script>
</body></html>
"""

PAGINA_OPERARIOS = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operarios</title><style>""" + ESTILO_OFICINA + """</style></head>
<body>
""" + CABECERA.format(titulo="Operarios") + """
<div class="wrap">
  <div id="aviso"></div>
  <h2>Picking</h2>
  <div class="panel"><table id="tp"><tbody></tbody></table></div>
  <h2>Grúa</h2>
  <div class="panel"><table id="tg"><tbody></tbody></table></div>
  <p style="font-size:13px;color:#64748b;max-width:640px;">
    Los usuarios son fijos. Escriba el nombre del operario que usará cada uno hoy.
    Al final del día, la productividad se mide con esos nombres.
  </p>
</div>
<footer>Sistema de contingencia</footer>
<script>
function tabla(id, ops) {
  let h = '<tr><th>Usuario</th><th>Nombre del operario</th><th>PIN</th><th></th></tr>';
  ops.forEach(o => {
    h += '<tr><td style="font-weight:600;">' + o.codigo + '</td>' +
      '<td><input id="n_' + o.codigo + '" value="' + (o.nombre || '') +
      '" placeholder="sin asignar"></td>' +
      '<td style="width:110px;"><input id="p_' + o.codigo + '" value="' +
      (o.pin || '') + '" maxlength="6"></td>' +
      '<td style="width:90px;"><button class="btn" onclick="guardar(\'' +
      o.codigo + '\',\'' + o.rol + '\')">Guardar</button></td></tr>';
  });
  document.getElementById(id).querySelector('tbody').innerHTML = h;
}
async function cargar() {
  const r = await fetch('/api/operarios');
  const j = await r.json();
  const ops = j.operadores || [];
  tabla('tp', ops.filter(o => o.rol === 'picking'));
  tabla('tg', ops.filter(o => o.rol === 'grua'));
}
async function guardar(codigo, rol) {
  const r = await fetch('/api/operarios/asignar', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({codigo: codigo, rol: rol,
      nombre: document.getElementById('n_' + codigo).value,
      pin: document.getElementById('p_' + codigo).value}),
  });
  const j = await r.json();
  document.getElementById('aviso').innerHTML = j.ok
    ? '<div class="alerta ok">Guardado: ' + codigo + '</div>'
    : '<div class="alerta err">' + (j.error || 'Error') + '</div>';
  cargar();
}
cargar();
</script>
</body></html>
"""

PAGINA_REAPRO = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Reaprovisionamiento</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 12px;
         background: #0b1220; color: #e6edf7; font-size: 17px; position: relative; }
  h1 { font-size: 20px; margin: 0 0 10px; color: #93a4bf; font-weight: 600; }
  .tarjeta { background:#16233a; border-radius:14px; padding:16px; margin-bottom:12px; }
  table { width:100%; border-collapse: collapse; font-size:14px; }
  th, td { text-align:left; padding:7px 6px; border-bottom:1px solid #2b3d5c; }
  th { color:#93a4bf; font-weight:600; }
  td.num { text-align:right; font-variant-numeric: tabular-nums; }
  .bajo { color:#fca5a5; font-weight:700; }
  .ok { color:#4ade80; }
  button { width:100%; font-size:22px; font-weight:800; padding:18px; border:0;
           border-radius:12px; color:#fff; background:#7c3aed; margin-top:10px; }
  button:disabled { background:#334155; color:#94a3b8; }
  #msg { padding:14px; border-radius:12px; min-height:50px; font-size:16px;
         background:#16233a; margin-bottom:12px; }
  #msg.ok { background:#14532d; color:#bbf7d0; }
  #msg.err { background:#7f1d1d; color:#fecaca; }
  input { width:100%; font-size:18px; padding:12px; border-radius:10px;
          border:2px solid #2b3d5c; background:#0b1220; color:#e6edf7; }
</style>
</head>
<body>
<a href="/" style="position:absolute;top:10px;right:12px;color:#93a4bf;
   text-decoration:none;font-size:14px;border:1px solid #2b3d5c;border-radius:8px;
   padding:6px 10px;background:#16233a;">← Menú</a>
<h1>Reaprovisionamiento — almacen a picking</h1>
<div id="msg">Cargando lo que esta bajo el minimo...</div>

<div class="tarjeta">
  <div style="font-size:15px;color:#93a4bf;margin-bottom:8px;">
    Ubicaciones de picking BAJO EL MINIMO
  </div>
  <table id="tabla"><tbody></tbody></table>
</div>

<div class="tarjeta">
  <div style="font-size:15px;color:#93a4bf;margin-bottom:8px;">Asignar a operador de grua</div>
  <input id="operador" placeholder="usuario del operador (ej. GRUA1)">
  <button id="btnGenerar" disabled>GENERAR Y DESTINAR</button>
</div>

<script>
const $ = id => document.getElementById(id);
function aviso(t, c) { $('msg').className = c || ''; $('msg').textContent = t; }

let operadorElegido = '';

async function cargarOperadores() {
  const r = await fetch('/api/reapro/operadores');
  const j = await r.json();
  const caja = $('operadores');
  caja.innerHTML = '';
  (j.operadores || []).forEach(o => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = o.etiqueta;
    b.style.cssText = 'flex:1;min-width:130px;background:#1e293b;color:#e6edf7;' +
      'border:2px solid #2b3d5c;border-radius:10px;padding:14px;font-size:17px;' +
      'font-weight:700;margin-top:0;';
    b.onclick = () => {
      operadorElegido = o.codigo;
      [...caja.children].forEach(c => c.style.borderColor = '#2b3d5c');
      b.style.borderColor = '#38bdf8';
      $('btnGenerar').disabled = false;
    };
    caja.appendChild(b);
  });
}

async function cargar() {
  const r = await fetch('/api/reapro/necesidades');
  const j = await r.json();
  const tb = $('tabla').querySelector('tbody');
  tb.innerHTML = '';
  const n = j.necesidades || [];
  if (!n.length) {
    tb.innerHTML = '<tr><td>Todo sobre el minimo. No hay nada que reponer.</td></tr>';
    aviso('Nada bajo el minimo.', 'ok');
    $('btnGenerar').disabled = true;
    return;
  }
  n.forEach(x => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + x.ubicacion + '<br><small style="color:#93a4bf">' +
      (x.descripcion || x.sku) + '</small></td>' +
      '<td class="num"><span class="bajo">' + x.stock_actual + '</span> / ' +
      x.minimo + '</td>' +
      '<td class="num">' + x.reponer + '</td>' +
      '<td class="num ' + (x.cubre ? 'ok' : 'bajo') + '">' +
      (x.cubre ? x.disponible_origen : '⚠️ ' + x.disponible_origen) + '</td>';
    tb.appendChild(tr);
  });
  aviso(n.length + ' ubicaciones bajo el minimo. Asigne un operador y genere.',
        '');
  $('btnGenerar').disabled = false;
}

$('btnGenerar').addEventListener('click', async () => {
  const r = await fetch('/api/reapro/destinar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({operador: operadorElegido, usuario: 'SUPERVISOR'}),
  });
  const j = await r.json();
  if (!j.ok) { aviso('Error: ' + j.error, 'err'); return; }
  let t = '✅ ' + j.creadas + ' tareas creadas (' + j.cajas +
          ' cajas) para ' + (j.operador || 'el operador') + '.';
  if (j.sin_stock_suficiente && j.sin_stock_suficiente.length)
    t += ' ⚠️ Sin stock suficiente para: ' + j.sin_stock_suficiente.join(', ');
  aviso(t, 'ok');
  cargar();
});

cargar();
</script>
</body>
</html>
"""

PAGINA_RECEPCION = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Recepcion contingencia</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 12px;
         background: #0b1220; color: #e6edf7; font-size: 20px; position: relative; }
  h1 { font-size: 20px; margin: 0 0 10px; color: #93a4bf; font-weight: 600; }
  .tarjeta { background: #16233a; border-radius: 14px; padding: 16px; margin-bottom: 12px; }
  .etq { font-size: 15px; color: #93a4bf; margin-bottom: 6px; }
  input { width: 100%; font-size: 24px; padding: 14px; border-radius: 12px;
          border: 2px solid #2b3d5c; background: #0b1220; color: #e6edf7; }
  input:focus { outline: none; border-color: #38bdf8; }
  .fila { display: flex; gap: 10px; }
  .fila > * { flex: 1; }
  button { width: 100%; font-size: 24px; font-weight: 800; padding: 18px;
           border: 0; border-radius: 12px; color: #fff; margin-top: 10px; }
  #btnRecibir { background: #16a34a; }
  #btnRecibir:disabled { background: #334155; color: #94a3b8; }
  .gris { background: #475569; font-size: 17px; padding: 13px; }
  #msg { padding: 14px; border-radius: 12px; min-height: 52px; font-size: 18px;
         background: #16233a; margin-bottom: 12px; }
  #msg.ok { background: #14532d; color: #bbf7d0; }
  #msg.err { background: #7f1d1d; color: #fecaca; }
  #msg.aviso { background: #78350f; color: #fde68a; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; margin-top: 8px; }
  th, td { text-align: left; padding: 6px; border-bottom: 1px solid #2b3d5c; }
  .oculto { display: none; }
</style>
</head>
<body>

<a href="/" style="position:absolute;top:10px;right:12px;color:#93a4bf;
   text-decoration:none;font-size:14px;border:1px solid #2b3d5c;border-radius:8px;
   padding:6px 10px;background:#16233a;">← Menú</a>
<h1>Recepcion — contingencia</h1>
<div id="msg">Escanee el LPN de la tarja.</div>

<div class="tarjeta">
  <div class="etq">Escanee el codigo de barras de la tarja</div>
  <input id="lpn" autocomplete="off" autofocus placeholder="escaneando...">
  <div id="trajo" class="oculto" style="margin-top:8px;font-size:15px;color:#4ade80;"></div>

  <div id="resto" class="oculto" style="margin-top:12px;">
    <div class="etq">SKU</div>
    <input id="sku" autocomplete="off">

    <div class="etq" style="margin-top:10px;">Cantidad</div>
    <input id="cantidad" type="number" inputmode="numeric" min="1">

    <div class="fila" style="margin-top:10px;">
      <div>
        <div class="etq">Elaboracion</div>
        <input id="elaboracion" placeholder="dd/mm/aaaa">
      </div>
      <div>
        <div class="etq">Vencimiento</div>
        <input id="vencimiento" placeholder="dd/mm/aaaa">
      </div>
    </div>

    <div class="fila" style="margin-top:10px;">
      <div>
        <div class="etq">Cajas / pallet</div>
        <input id="cajasPallet" type="number" inputmode="numeric" placeholder="60">
      </div>
      <div>
        <div class="etq">Perfil antiguedad</div>
        <input id="perfil" placeholder="999">
      </div>
    </div>

    <div class="etq" style="margin-top:10px;">Descripcion</div>
    <input id="descripcion" placeholder="del producto">

    <div class="etq" style="margin-top:10px;">Ubicacion (de la tarja)</div>
    <input id="ubicacion" placeholder="ej. C16-01-01-01">
  </div>

  <button id="btnRecibir" disabled>RECIBIR</button>
  <button id="btnRecibirUbicar" class="gris" disabled>RECIBIR Y UBICAR (un paso)</button>
  <button id="btnSkuNuevo" class="gris oculto">+ DAR DE ALTA ESTE SKU (producto nuevo)</button>
</div>

<div class="tarjeta">
  <div class="etq">Pendientes de ubicar</div>
  <table id="pend"><tbody></tbody></table>
</div>

<div class="tarjeta">
  <div class="etq">Ubicar mercaderia</div>
  <div class="fila">
    <input id="destino" placeholder="ubicacion final">
    <button id="btnUbicar" class="gris" style="margin-top:0;">UBICAR</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const lpn = $('lpn'), sku = $('sku'), cant = $('cantidad'), msg = $('msg');
const elab = $('elaboracion'), venc = $('vencimiento'), ubic = $('ubicacion');
const cajasPallet = $('cajasPallet'), perfil = $('perfil'), desc = $('descripcion');
const btn = $('btnRecibir'), btnRU = $('btnRecibirUbicar'), destino = $('destino');
const btnNuevo = $('btnSkuNuevo');
let idSeleccion = null;

function aviso(t, c) { msg.className = c || ''; msg.textContent = t; }

// Paso 1: escanear la tarja. El codigo GS1-128 trae los datos y se llenan solos.
lpn.addEventListener('change', async () => {
  const v = lpn.value.trim();
  if (!v) return;
  $('resto').classList.remove('oculto');

  const r = await fetch('/api/recepcion/escanear?codigo=' + encodeURIComponent(v));
  const j = await r.json();
  const g = (j.gs1 || {});

  let llenos = [];
  const sd = (j.sku_detectado || {});
  if (sd.sku) { sku.value = sd.sku; llenos.push('SKU ' + sd.sku +
    (sd.origen === 'stock' ? ' (confirmado en stock)' : '')); }
  // Si el SKU no esta en la cuadratura, es producto nuevo: se puede dar de alta
  btnNuevo.classList.toggle('oculto', !(sd.sku && sd.origen === 'codigo'));
  if (g.cantidad) { cant.value = g.cantidad; llenos.push('cantidad ' + g.cantidad); }
  if (g.fecha_vencimiento) { venc.value = g.fecha_vencimiento; llenos.push('vence ' + g.fecha_vencimiento); }
  if (g.fecha_elaboracion) { elab.value = g.fecha_elaboracion; llenos.push('elab ' + g.fecha_elaboracion); }
  if (g.lote) { llenos.push('lote ' + g.lote); }

  if (llenos.length) {
    $('trajo').textContent = '✅ El codigo trajo: ' + llenos.join(' | ') +
      (sd.aviso ? '  ⚠️ ' + sd.aviso : '');
    $('trajo').classList.remove('oculto');
    aviso(sku.value ? 'Revise la cantidad y la ubicacion, y confirme.'
                    : 'Complete el SKU y la ubicacion, y confirme.', 'ok');
  } else {
    $('trajo').classList.add('oculto');
    aviso('El codigo no trajo mas datos. Complete a mano.', 'aviso');
  }
  // Si ya estan todos los datos, se puede recibir y ubicar directo
  actualizarBotones();
  (sku.value ? ubic : sku).focus();
});

// Habilita RECIBIR cuando estan los datos minimos
function actualizarBotones() {
  const listo = lpn.value.trim() && sku.value.trim() && parseInt(cant.value || '0') > 0;
  btn.disabled = !listo;
  btnRU.disabled = !(listo && ubic.value.trim());   // el paso unico necesita ubicacion
}
['input','change'].forEach(ev => {
  [sku, cant, ubic, lpn].forEach(el => el.addEventListener(ev, actualizarBotones));
});

function cuerpoRecepcion() {
  return {
    escaneo: lpn.value.trim(),      // el codigo crudo: el servidor lo parsea
    lpn: lpn.value.trim(), sku: sku.value.trim(),
    cantidad: parseInt(cant.value || '0', 10),
    elaboracion: elab.value.trim(), vencimiento: venc.value.trim(),
    ubicacion: ubic.value.trim(),
    cajas_pallet: parseInt(cajasPallet.value || '0', 10),
    perfil_antiguedad: perfil.value.trim(),
    descripcion: desc.value.trim(),
    usuario: 'RECEPTOR',
  };
}

function limpiar() {
  [lpn, sku, cant, elab, venc, ubic, cajasPallet, perfil, desc].forEach(el => el.value = '');
  btn.disabled = true; btnRU.disabled = true;
  $('resto').classList.add('oculto'); lpn.focus();
}

btnRU.addEventListener('click', async () => {
  const r = await fetch('/api/recepcion/recibir-y-ubicar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cuerpoRecepcion()),
  });
  const j = await r.json();
  if (!j.ok) { aviso('❌ ' + j.error, 'err'); return; }
  aviso('✅ Recibido y ubicado: ' + j.cantidad + ' cajas de ' + j.sku +
        ' en ' + j.ubicacion, 'ok');
  limpiar(); cargarPendientes();
});

btn.addEventListener('click', async () => {
  const cuerpo = cuerpoRecepcion();
  const r = await fetch('/api/recepcion/recibir', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cuerpo),
  });
  const j = await r.json();
  if (!j.ok) { aviso('❌ ' + j.error, 'err'); return; }
  if (j.avisos && j.avisos.length) {
    aviso('⚠️ Recibido: ' + j.cantidad + ' cajas de ' + j.sku + ' — ' + j.avisos.join('; '),
          'aviso');
  } else {
    aviso('✅ Recibido: ' + j.cantidad + ' cajas de ' + j.sku +
          (j.pallets ? ' (' + j.pallets + ' pallets)' : ''), 'ok');
  }
  limpiar(); cargarPendientes();
});

async function cargarPendientes() {
  const r = await fetch('/api/recepcion/pendientes');
  const j = await r.json();
  const tb = $('pend').querySelector('tbody');
  tb.innerHTML = '';
  (j.pendientes || []).forEach(p => {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + p.lpn + '</td><td>' + p.sku + '</td>' +
                   '<td>' + p.cantidad + '</td><td>' + (p.fecha_vencimiento || '—') + '</td>';
    tr.style.cursor = 'pointer';
    tr.onclick = () => {
      idSeleccion = p.id;
      destino.value = p.ubicacion_sugerida || '';
      destino.focus();
      aviso('Ubicar LPN ' + p.lpn + ' (' + p.cantidad + ' cajas). Destino?', '');
    };
    tb.appendChild(tr);
  });
  if (!tb.children.length) tb.innerHTML = '<tr><td colspan="4">(nada pendiente)</td></tr>';
}

btnNuevo.addEventListener('click', async () => {
  if (!sku.value.trim()) { aviso('Primero escanee la tarja.', 'err'); return; }
  const r = await fetch('/api/recepcion/sku-nuevo', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      sku: sku.value.trim(), descripcion: desc.value.trim(),
      ubicacion: ubic.value.trim(), cantidad: parseInt(cant.value || '0', 10),
      lpn: lpn.value.trim(), vencimiento: venc.value.trim(), usuario: 'RECEPTOR',
    }),
  });
  const j = await r.json();
  if (!j.ok) { aviso('❌ ' + j.error, 'err'); return; }
  aviso('✅ SKU ' + j.sku + ' dado de alta con ' + j.cantidad +
        ' cajas en ' + j.ubicacion, 'ok');
  btnNuevo.classList.add('oculto');
  limpiar(); cargarPendientes();
});

$('btnUbicar').addEventListener('click', async () => {
  if (!idSeleccion) { aviso('Toque primero una fila de la lista.', 'err'); return; }
  if (!destino.value.trim()) { aviso('Escriba la ubicacion final.', 'err'); return; }
  const r = await fetch('/api/recepcion/ubicar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: idSeleccion, ubicacion: destino.value.trim(),
                          usuario: 'RECEPTOR'}),
  });
  const j = await r.json();
  if (!j.ok) { aviso('❌ ' + j.error, 'err'); return; }
  aviso('✅ ' + j.cantidad + ' cajas de ' + j.sku + ' ubicadas en ' + j.ubicacion, 'ok');
  idSeleccion = null; destino.value = '';
  cargarPendientes();
});

cargarPendientes();
</script>
</body>
</html>
"""

PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Picking contingencia</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 12px;
         background: #0b1220; color: #e6edf7; font-size: 20px; position: relative; }
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

<a href="/" style="position:absolute;top:10px;right:12px;color:#93a4bf;
   text-decoration:none;font-size:14px;border:1px solid #2b3d5c;border-radius:8px;
   padding:6px 10px;background:#16233a;">← Menú</a>
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
    <button id="btnTerminar" class="gris" style="background:#b45309;">TERMINAR TURNO</button>
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
let usuario = '';

async function cargarOperadoresP() {
  const r = await fetch('/api/operarios?rol=picking');
  const j = await r.json();
  const caja = $('operadoresP');
  caja.innerHTML = '';
  (j.operadores || []).forEach(o => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = o.etiqueta;
    b.style.cssText = 'flex:1;min-width:120px;background:#1e293b;color:#e6edf7;' +
      'border:2px solid #2b3d5c;border-radius:10px;padding:14px;font-size:17px;' +
      'font-weight:700;margin-top:0;';
    b.onclick = () => {
      usuario = o.codigo;
      [...caja.children].forEach(c => c.style.borderColor = '#2b3d5c');
      b.style.borderColor = '#38bdf8';
      $('btnEntrarP').disabled = !$('pinP').value.trim();
      $('pinP').focus();
    };
    caja.appendChild(b);
  });
}

$('pinP').addEventListener('input', () => {
  $('btnEntrarP').disabled = !(usuario && $('pinP').value.trim());
});

$('btnEntrarP').addEventListener('click', async () => {
  const r = await fetch('/api/entrar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({operador: usuario, pin: $('pinP').value.trim()}),
  });
  const j = await r.json();
  if (!j.ok) {
    $('msg').className = 'err';
    $('msg').textContent = j.error || 'PIN incorrecto';
    $('pinP').value = '';
    return;
  }
  $('loginP').classList.add('oculto');
  document.querySelector('h1').textContent = 'Picking — ' + (j.nombre || usuario);
  $('pinP').value = '';
  cargarTarea();
});

$('btnTerminar').addEventListener('click', async () => {
  if (!confirm('Terminar el turno? Las tareas que no alcanzaste a pickear ' +
               'quedan libres para otro operario.')) return;
  const r = await fetch('/api/picking/terminar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({usuario: usuario}),
  });
  const j = await r.json();
  if (!j.ok) { aviso('Error: ' + j.error, 'err'); return; }
  aviso('✅ Turno terminado. ' + j.liberadas + ' tareas liberadas (' +
        j.cajas_liberadas + ' cajas). Quedan ' + j.quedan_pendientes +
        ' pendientes en total.', 'ok');
  $('trabajo').classList.add('oculto');
  $('hecho').classList.remove('oculto');
});

function aviso(texto, clase) {
  msg.className = clase || '';
  msg.textContent = texto;
}

async function cargarTarea() {
  const r = await fetch('/api/tarea?usuario=' + encodeURIComponent(usuario));
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

cargarOperadoresP();
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
    con = sqlite3.connect(db, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    pk.preparar_tablas(con)
    con.commit()
    return con


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
            self._html(PAGINA_MENU)
            return

        if u.path == "/picking":
            self._html(PAGINA)
            return

        if u.path.startswith("/informes/"):
            from urllib.parse import unquote
            nombre = Path(unquote(u.path[len("/informes/"):])).name
            archivo = Path("output") / nombre
            if not archivo.exists():
                self._json({"ok": False, "error": "no existe"}, 404)
                return
            datos = archivo.read_bytes()
            tipo = ("application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet" if archivo.suffix == ".xlsx" else "text/html")
            self.send_response(200)
            self.send_header("Content-Type", tipo + "; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Content-Disposition",
                             f'attachment; filename="{archivo.name}"'
                             if archivo.suffix == ".xlsx" else "inline")
            self.end_headers()
            self.wfile.write(datos)
            return

        if u.path == "/api/estado":
            from . import recepcion as rc
            from . import stock_vivo as sv
            self._json({
                "ok": True,
                "stock": sv.resumen(self.db),
                "tareas": pk.resumen_tareas(self.db),
                "recepcion": rc.resumen(self.db),
            })
            return

        if u.path == "/api/tarea":
            usuario = qs.get("usuario", [""])[0].strip()
            t = pk.tarea_pendiente(self.db, usuario)
            if t is None:
                self._json({"ok": False})
                return
            # Si la tarea no tiene duenio, la toma este usuario (queda registrado)
            if usuario and not str(t.get("usuario") or "").strip():
                pk.tomar_tarea(self.db, t["id"], usuario)
                t["usuario"] = usuario
            self._json({"ok": True, "tarea": {
                "id": t["id"], "ubicacion": t["ubicacion"], "sku": t["sku"],
                "descripcion": t["descripcion"], "cantidad": t["cantidad"],
                "lote": t["lote"], "caducidad": t["caducidad"],
            }, "total": t["total"], "hechas": t["hechas"]})
            return

        if u.path == "/recepcion":
            self._html(PAGINA_RECEPCION)
            return

        if u.path == "/reapro":
            self._html(PAGINA_REAPRO)
            return

        if u.path == "/estado":
            self._html(PAGINA_ESTADO)
            return

        if u.path == "/cola":
            self._html(PAGINA_COLA)
            return

        if u.path == "/operarios":
            self._html(PAGINA_OPERARIOS)
            return

        if u.path == "/api/cola":
            from . import informe_dia, operarios, reapro
            fecha = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
            d = informe_dia.recopilar(self.db, fecha)
            with _conectar(self.db) as con:
                cola_p = [dict(f) for f in con.execute(
                    """SELECT ubicacion, sku, cantidad, usuario FROM tareas
                        WHERE estado = 'pendiente' ORDER BY id LIMIT 60""").fetchall()]
                cola_r = [dict(f) for f in con.execute(
                    """SELECT origen, destino, cantidad, operador FROM reapro
                        WHERE estado = 'pendiente' ORDER BY id LIMIT 60""").fetchall()]
            self._json({
                "ok": True,
                "movimientos_totales": d.movimientos_totales,
                "cajas_movidas": d.cajas_movidas,
                "desglose": d.desglose_movimientos(),
                "picking": {"pendientes": d.tareas.get("pendiente", {}).get("tareas", 0)},
                "reapro": {"pendientes": d.reapro.get("pendientes", 0)},
                "cola_picking": cola_p, "cola_reapro": cola_r,
                "productividad": [p for p in operarios.productividad(self.db, "picking")
                                  if p["movimientos"]],
            })
            return

        if u.path == "/grua":
            self._html(PAGINA_GRUA)
            return

        if u.path == "/api/reapro/tarea":
            from . import reapro
            t = reapro.tarea_pendiente(self.db, qs.get("operador", [""])[0])
            if t is None:
                self._json({"ok": False})
                return
            from . import reapro as _rp
            self._json({"ok": True, "tarea": {
                "id": t["id"], "origen": t["origen"], "destino": t["destino"],
                "sku": t["sku"], "descripcion": t["descripcion"],
                "cantidad": t["cantidad"],
                "operador": t.get("operador", ""),
                "operador_nombre": _rp.nombre_operador(t.get("operador", "")),
            }, "total": t["total"], "hechas": t["hechas"]})
            return

        if u.path in ("/api/reapro/operadores", "/api/operarios"):
            from . import operarios
            rol = qs.get("rol", ["grua" if u.path.endswith("reapro/operadores") else ""])[0]
            with _conectar(self.db) as con:
                pines = {str(f["codigo"]): str(f["pin"] or "")
                         for f in con.execute("SELECT codigo, pin FROM operarios")}
            self._json({"ok": True, "operadores": [
                {"codigo": o["codigo"], "nombre": o["nombre"], "rol": o["rol"],
                 "pin": pines.get(o["codigo"], ""),
                 "etiqueta": f"{o['codigo']} — {o['nombre']}" if o["nombre"] else o["codigo"]}
                for o in operarios.listar(self.db, rol)]})
            return

        if u.path == "/api/productividad":
            from . import operarios
            rol = qs.get("rol", ["picking"])[0]
            self._json({"ok": True, "rol": rol,
                        "productividad": operarios.productividad(self.db, rol)})
            return

        if u.path == "/api/reapro/necesidades":
            from . import reapro
            items = reapro.calcular(self.db)
            self._json({"ok": True, "necesidades": [{
                "ubicacion": n.ubicacion_picking, "sku": n.sku,
                "descripcion": n.descripcion, "stock_actual": n.stock_actual,
                "minimo": n.minimo, "maximo": n.maximo, "reponer": n.reponer,
                "disponible_origen": n.disponible_origen, "cubre": n.cubre,
            } for n in items]})
            return

        if u.path == "/api/recepcion/escanear":
            from . import gs1, recepcion as rc
            codigo = qs.get("codigo", [""])[0]
            e = gs1.parsear(codigo)
            # El SKU viene dentro del codigo: se detecta cruzando con el stock.
            sku = rc.identificar_sku(self.db, codigo)
            self._json({"ok": True, "gs1": e.resumen(),
                        "desglose": gs1.describir(codigo),
                        "sku_detectado": sku,
                        "es_gs1": gs1.es_gs1(codigo)})
            return

        if u.path == "/api/recepcion/pendientes":
            from . import recepcion as rc
            pend = rc.pendientes(self.db)
            self._json({"ok": True, "pendientes": pend.to_dict("records")})
            return

        if u.path == "/api/recepcion/sugerir":
            from . import recepcion as rc
            s = rc.sugerir_ubicacion(self.db, qs.get("sku", [""])[0])
            self._json(s)
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

        if u.path in ("/api/reapro/entrar", "/api/entrar"):
            from . import operarios
            datos = self._cuerpo()
            cod = str(datos.get("operador", datos.get("usuario", ""))).strip()
            pin = str(datos.get("pin", "")).strip()
            if not operarios.verificar_pin(self.db, cod, pin):
                self._json({"ok": False, "error": "PIN incorrecto"}, 401)
                return
            self._json({"ok": True, "operador": cod,
                        "nombre": operarios.nombre(self.db, cod)})
            return

        if u.path == "/api/picking/terminar":
            datos = self._cuerpo()
            r = pk.terminar_turno(self.db, str(datos.get("usuario", "")).strip())
            self._json(r)
            return

        if u.path == "/api/operarios/asignar":
            from . import operarios
            datos = self._cuerpo()
            r = operarios.asignar(self.db,
                                  str(datos.get("codigo", "")).strip(),
                                  str(datos.get("nombre", "")).strip(),
                                  str(datos.get("rol", "")).strip(),
                                  str(datos.get("pin", "")).strip())
            self._json(r)
            return


        if u.path == "/api/reapro/confirmar":
            from . import reapro
            datos = self._cuerpo()
            r = reapro.confirmar(self.db, int(datos.get("id", 0)),
                                 int(datos.get("cantidad", 0) or 0),
                                 str(datos.get("usuario", "")).strip())
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
            self._json(r)
            return

        if u.path == "/api/reapro/destinar":
            from . import reapro
            datos = self._cuerpo()
            r = reapro.destinar(self.db,
                                operador=str(datos.get("operador", "")).strip(),
                                usuario=str(datos.get("usuario", "")).strip())
            self._json(r)
            return

        if u.path == "/api/dia/cerrar":
            from . import informe_dia
            from datetime import datetime as _dt
            datos = self._cuerpo()
            fecha = _dt.now().strftime("%Y-%m-%d")
            # 1) Liberar las reservas que quedaron colgando
            cierre = pk.cerrar_dia(self.db, str(datos.get("usuario", "")).strip())
            # 2) Generar el informe de cierre
            d = informe_dia.recopilar(self.db, fecha)
            salida = Path("output")
            salida.mkdir(exist_ok=True)
            html = informe_dia.generar_html(d, salida / f"informe_dia_{fecha}.html")
            xlsx = informe_dia.generar_excel(d, salida / f"informe_dia_{fecha}.xlsx")
            self._json({"ok": True, "fecha": fecha,
                        "tareas_cerradas": cierre["tareas_cerradas"],
                        "cajas_liberadas": cierre["cajas_liberadas"],
                        "cajas_pickeadas": d.cajas_pickeadas,
                        "cajas_recibidas": d.cajas_recibidas,
                        "html": "/informes/" + html.name,
                        "excel": "/informes/" + xlsx.name})
            return

        if u.path == "/api/informe/generar":
            from . import informe_dia
            from datetime import datetime as _dt
            fecha = _dt.now().strftime("%Y-%m-%d")
            d = informe_dia.recopilar(self.db, fecha)
            salida = Path("output")
            salida.mkdir(exist_ok=True)
            html = informe_dia.generar_html(d, salida / f"informe_dia_{fecha}.html")
            xlsx = informe_dia.generar_excel(d, salida / f"informe_dia_{fecha}.xlsx")
            self._json({"ok": True, "fecha": fecha,
                        "cajas_pickeadas": d.cajas_pickeadas,
                        "cajas_recibidas": d.cajas_recibidas,
                        "html": "/informes/" + html.name,
                        "excel": "/informes/" + xlsx.name})
            return

        if u.path == "/api/confirmar":
            datos = self._cuerpo()
            try:
                id_tarea = int(datos.get("id", 0))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "id invalido"}, 400)
                return
            usuario = str(datos.get("usuario", "")).strip()

            # La cantidad la digita el picker; si no la manda, se asume la pedida.
            tarea = pk.obtener_tarea(self.db, id_tarea)
            pedida = int(tarea["cantidad"]) if tarea else 0
            try:
                digitada = int(datos.get("cantidad", pedida))
            except (TypeError, ValueError):
                self._json({"ok": False, "error": "cantidad invalida"}, 400)
                return

            r = pk.confirmar(self.db, id_tarea, digitada, usuario)
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
            self._json(r)
            return

        if u.path in ("/api/recepcion/recibir", "/api/recepcion/recibir-y-ubicar"):
            from . import recepcion as rc
            datos = self._cuerpo()
            escaneo = str(datos.get("escaneo", "")).strip()
            if escaneo:
                # El codigo de barras de la tarja trae los datos: se llenan solos.
                sku_pantalla = str(datos.get("sku", "")).strip()
                if not sku_pantalla:
                    sku_pantalla = rc.identificar_sku(self.db, escaneo).get("sku", "")
                recep = rc.desde_escaneo(
                    escaneo,
                    sku=sku_pantalla,
                    cantidad=int(datos.get("cantidad", 0) or 0),
                    ubicacion=str(datos.get("ubicacion", "")).strip(),
                    almacen=str(datos.get("almacen", "")).strip(),
                    descripcion=str(datos.get("descripcion", "")).strip(),
                    usuario=str(datos.get("usuario", "")).strip(),
                )
                # Si el codigo no traia cantidad, y tampoco la pantalla: no hay.
                if not recep.cantidad:
                    self._json({"ok": False,
                                "error": "el codigo no trae cantidad y no se digito"},
                               400)
                    return
                if u.path.endswith("recibir-y-ubicar"):
                    r = rc.recibir_y_ubicar(
                        self.db, recep,
                        str(datos.get("ubicacion_final", "")).strip())
                else:
                    r = rc.recibir(self.db, recep)
                if not r["ok"]:
                    self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                    return
                self._json({**r, "desde_escaneo": True})
                return

            recep = rc.Recepcion(
                lpn=str(datos.get("lpn", "")).strip(),
                sku=str(datos.get("sku", "")).strip(),
                cantidad=int(datos.get("cantidad", 0) or 0),
                ubicacion=str(datos.get("ubicacion", "")).strip(),
                almacen=str(datos.get("almacen", "")).strip(),
                descripcion=str(datos.get("descripcion", "")).strip(),
                fecha_elaboracion=str(datos.get("elaboracion", "")).strip(),
                fecha_vencimiento=str(datos.get("vencimiento", "")).strip(),
                cajas_pallet=int(datos.get("cajas_pallet", 0) or 0),
                perfil_antiguedad=str(datos.get("perfil_antiguedad", "")).strip(),
                usuario=str(datos.get("usuario", "")).strip(),
            )
            if u.path.endswith("recibir-y-ubicar"):
                r = rc.recibir_y_ubicar(self.db, recep,
                                        str(datos.get("ubicacion_final", "")).strip())
            else:
                r = rc.recibir(self.db, recep)
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
            self._json(r)
            return

        if u.path == "/api/recepcion/sku-nuevo":
            from . import recepcion as rc
            datos = self._cuerpo()
            r = rc.crear_sku(
                self.db,
                sku=str(datos.get("sku", "")).strip(),
                descripcion=str(datos.get("descripcion", "")).strip(),
                ubicacion=str(datos.get("ubicacion", "")).strip(),
                cantidad=int(datos.get("cantidad", 0) or 0),
                lpn=str(datos.get("lpn", "")).strip(),
                fecha_vencimiento=str(datos.get("vencimiento", "")).strip(),
                usuario=str(datos.get("usuario", "")).strip(),
            )
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
            self._json(r)
            return

        if u.path == "/api/recepcion/ubicar":
            from . import recepcion as rc
            datos = self._cuerpo()
            r = rc.ubicar(self.db, int(datos.get("id", 0)),
                          str(datos.get("ubicacion", "")).strip(),
                          str(datos.get("usuario", "")).strip())
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
            self._json(r)
            return

        if u.path == "/api/saltar":
            datos = self._cuerpo()
            id_tarea = int(datos.get("id", 0))
            usuario = str(datos.get("usuario", "")).strip()
            r = pk.saltar(self.db, id_tarea, usuario)
            if not r["ok"]:
                self._json({"ok": False, "error": r["error"]}, r.get("code", 400))
                return
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
