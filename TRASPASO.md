# TRASPASO — Estado del proyecto al 2026-11-27

> **LÉEME PRIMERO si abres una conversación nueva.**
> Este documento tiene todo lo necesario para continuar sin perder contexto.
> El detalle técnico completo está en `AGENTS.md`; esto es el resumen operativo.

---

## 1. Qué es el proyecto (en una frase)

**Sistema de contingencia para el WMS Blue Yonder**: cuando el WMS se cae, la
bodega sigue pickeando, recibiendo y reaprovisionando usando este sistema en vez
de Blue Yonder.

- **Repo:** `github.com/Freddyohlo/proyecto2` (público)
- **Rama de trabajo:** `tools-inspeccion-detalle` ← **todo el código está acá**
  (`main` solo tiene los archivos que subió el usuario: PDFs, CSV, Excel)
- **Carpeta en el PC del usuario:** `C:\planb`

---

## 2. DÓNDE ESTAMOS AHORA (lo más importante)

### ✅ Instalado y funcionando en el PC del usuario

El usuario tiene **Windows** y **es el mismo PC donde está Blue Yonder**.
Ya se instaló todo y **los tests pasan**:

```
267 passed, 2 skipped in 19.91s
```

**Python 3.12.3** · venv en `C:\planb\.venv` · todas las dependencias instaladas
(incluido `pywinauto` y `pyautogui` porque es el mismo PC de Blue Yonder).

> Los **2 skipped** son los tests del PDF del sumario (el archivo no está en el
> repo). No es un fallo.

### ⚠️ Ojo con la versión de pandas

Se instaló **pandas 3.1.1** (muy nuevo). Los tests pasan, pero si aparece algún
`DeprecationWarning` o algo raro en el futuro, la primera sospecha es esta.
Bajar a `pandas<3` si da problemas:
```
pip install "pandas<3"
```

---

## 3. Cómo arrancarlo (comandos exactos)

Abrir CMD, y:

```cmd
cd C:\planb
.venv\Scripts\activate
```

**Cargar los datos del día:**

```cmd
python -m src.plan_b_main cargar --archivo "cuadratura.tsv"
python -m src.plan_b_main sumario --archivo "SUMARIO CARGA.pdf"
python -m src.plan_b_main picking --desde-sumario
```

**Levantar el servidor:**

```cmd
python -m src.picking_servidor --puerto 8080
```

**Abrir en el Zebra:** `http://<IP-del-PC>:8080/`

**Firewall (una vez, como administrador):**
```cmd
netsh advfirewall firewall add rule name="Plan B WMS" dir=in action=allow protocol=TCP localport=8080
```

---

## 4. Qué está construido (y qué no)

### ✅ Funcionando

| Módulo | Qué hace |
|---|---|
| `src/sumario.py` | Lee el **PDF del sumario de carga** (la venta) |
| `src/picking.py` | Tareas de picking con **reserva** y **FEFO** |
| `src/stock_vivo.py` | Stock con `cantidad - reservado - pickeado` |
| `src/recepcion.py` | Recibir tarja (GS1) y ubicar |
| `src/gs1.py` | Lector de código de barras GS1-128 |
| `src/reapro.py` | Reapro por mínimo + operador de grúa |
| `src/consulta.py` | **Consulta de stock** por código |
| `src/cuadratura.py` | **Cuadratura** + corte de las 19:00 |
| `src/informe_dia.py` | Informe del día (HTML + Excel) |
| `src/operarios.py` | Usuarios fijos, PIN, productividad |
| `src/picking_servidor.py` | Servidor web con todas las pantallas |

### Pantallas (menú actual)

```
OPERACIÓN
  Consulta de stock          /consulta
  Cuadratura de stock        /cuadratura
  Picking                    /picking
  Recepción de mercadería    /recepcion
  Reaprovisionamiento        /reapro
  Grúa                       /grua
  Pallet de armado           /pallet
  Contraste volante          /contraste

SISTEMA
  Estado del stock           /estado
  Operaciones de sistema — cola de trabajos   /cola

ADMINISTRACIÓN
  Cerrar el día
  Operarios                  /operarios
```

### Fuera del menú (otros áreas, NO son del alcance)

- `/chequeo` — chequeo por muestreo (**es de otra área de chequeadores**)
- `/consolidacion` — consolidación de pallets (**es de otra área**)

> El usuario fue explícito: **nosotros solo hacemos picking, reapro y recepción**.
> Consolidación y chequeo los ven otras áreas.

### ⏳ Pendiente

- **Reincorporación a Blue Yonder** — el usuario dijo: *"no te calientes con
  Blue Yonder, esto va a ser independiente"*. **NO es parte del trabajo.**
- Probar el flujo real con datos del día (falta que el usuario mande la
  cuadratura y el sumario actuales).
- Corte automático de las 19:00 (cron / Task Scheduler) — falta definir si es
  uno o dos cortes al día.

---

## 5. El flujo real del negocio (aprendido del usuario)

```
1. CUADRATURA (Blue Yonder, 19:00)  →  el stock real de la bodega
2. SUMARIO DE CARGA (PDF)           →  la venta del día (9 camiones, 92 pallets)
3. NETEO                            →  ¿alcanza el stock para el sumario?
4. PICKING                          →  el picker saca y deja en STAGING
5. CONSOLIDACIÓN (otra área)        →  arman los pallets de cada camión
6. DESPACHO (otra área)             →  contraste volante vs sumario
```

**Reglas de negocio confirmadas:**

- **Picking FEFO**: primero lo que vence antes.
- **La ubicación de picking es única por SKU** → escanear el QR del rack ya
  identifica el producto. **No se escanea el SKU al pickear.**
- **Reapro**: se dispara por mínimo, se repone **hasta el máximo aunque se
  exceda** (máx 200, quedan 5 → se reponen 200 → quedan 205).
- **El picking NO alcanza → se baja de ALMACENAMIENTO** para completar.
- **Producto nuevo** (que no está en la cuadratura) → se da de alta y entra a
  **ALMACENAMIENTO**, nunca a picking.
- **Cierre del día es TOTAL**: lo que no se pickeó se cierra, no se arrastra.
- **Usuarios fijos** (`PICK1..4`, `GRUA1..2`) con PIN; el supervisor les asigna
  el nombre del operario del día.

### Datos reales del PDF de sumario (verificados)

9 camiones · 92 pallets · 104 líneas · **5.701 cajas** · 35 SKUs

⚠️ **PALLETS MIXTOS**: solo la primera línea de cada pallet trae el número de
pallet. Las siguientes traen solo SKU + descripción + cantidad. El parser
arrastra el pallet actual.

---

## 6. Datos que necesitan los módulos

### Cuadratura (stock) — TSV de Blue Yonder
Pantalla **CCU Cuadratura de Stock** con:
- Checkbox **"Detalle"** activo (pasa de 8 a **22 columnas**)
- Combo de área **vacío** (trae TODAS las áreas)

Copiar con `Ctrl+A` / `Ctrl+C` → pegar en un `.tsv` (NO convertir a Excel).

Herramienta: `python tools/inspeccionar_detalle.py` (lo hace automático).

### Sumario (venta) — PDF
El que envían desde transporte. Ya probado y funciona.

---

## 7. Cómo darle archivos al agente (para probar)

**Opción 1 — GitHub** (la que usa el usuario):
`github.com/Freddyohlo/proyecto2` → rama `main` → Add file → Upload files

**Opción 2 — Página de carga** (solo si el agente levanta el servidor):
```python
# servidor minimo de carga en /workspace/upload_server.py (puerto 12000)
```

> ⚠️ El entorno del agente se reinicia y pierde dependencias y servidores. Si
> algo no responde, hay que reinstalar (`pip install -r requirements.txt
> pdfplumber pytest`) y volver a levantar el servidor.

---

## 8. Cómo trabajar con este usuario

Cosas que funcionaron bien:

1. **Ir paso a paso con CMD**, un comando a la vez, esperando la salida.
2. **Mostrar visualizaciones** (HTML/pantalla) antes de dar por cerrado algo.
3. **Encontrar y reportar bugs reales** — al usuario le importa que se detecten.
4. **Preguntar antes de asumir** el flujo del negocio. Varias veces corrigió
   supuestos equivocados (ej. "el picker no arma pallets, eso lo hacen los
   consolidadores").
5. **Respetar el alcance**: solo picking, reapro y recepción. Consolidación y
   chequeo son de otras áreas.

Estilo: español chileno informal ("compa"), respuestas claras y directas,
tablas comparativas, y explicar el "por qué" de las decisiones.

---

## 9. Historial de decisiones importantes

| Fecha | Decisión |
|---|---|
| 2026-10-21 | Detalle activo → 22 columnas. Áreas PICKING y ALMACENAMIENTO separadas |
| 2026-11-03 | TRUCK + SAP recibidos. Contraste venta vs stock |
| 2026-11-03 | LPN de tarja = SSCC GS1. Fechas de tarja con PUNTOS (bug corregido) |
| 2026-11-03 | Zebra: app web, no APK. DataWedge entrega escaneo como teclado |
| 2026-11-16 | **Sumario de carga (PDF) reemplaza al TRUCK** como fuente de venta |
| 2026-11-16 | Picker deja en STAGING; consolidadores arman pallets (otra área) |
| 2026-11-16 | Chequeo por muestreo es de OTRA área → fuera del menú |
| 2026-11-27 | Instalado en Windows del usuario. 267 tests pasan |

---

## 10. Bugs reales encontrados (para no repetirlos)

1. **FEFO invertido**: las fechas se comparaban como texto, así que
   `01/03/2027` quedaba antes que `01/12/2026` → elegía el lote que vencía
   **más tarde**. Hay que parsear a fecha.
2. **Fechas de la tarja con PUNTOS** (`31.10.2026`): el normalizador solo
   aceptaba barras → el vencimiento se perdía en silencio → FEFO ciego.
3. **Cantidad GS1 partida**: `198` se partía en `1` + AI(98) porque los AIs
   internos `90-99` se usaban como corte. No deben usarse.
4. **Pallets mixtos del sumario**: se perdían 12 líneas (79 cajas) porque solo
   la primera línea trae el nº de pallet.
5. **Cajas contadas doble**: `cajas_pickeadas` leía `stock.pickeado`, que
   también sube con el reapro. Hay que leerlo de la tabla de movimientos.
6. **Lotes fusionados**: al ingresar mercadería se fusionaba por
   ubicación+lote+SKU sin mirar el vencimiento → la fila quedaba con una sola
   fecha. El vencimiento debe ser parte de la clave.
7. **`/api/cola` reventaba** si la tabla `reapro` no existía (base nueva).

---

## 11. Próximos pasos sugeridos

1. **Probar con datos reales del día**: que el usuario mande la cuadratura
   actual y el sumario actual.
2. **Definir el corte de las 19:00**: ¿solo ese, o también a la mañana?
3. **Probar la captura automática** de la cuadratura en el PC del usuario
   (`python tools/inspeccionar_detalle.py`), ya que es el mismo PC de Blue Yonder.
4. **Probar el servidor en el Zebra real** y ajustar DataWedge si hace falta.
5. **Task Scheduler** para el corte automático de las 19:00.
