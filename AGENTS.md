# AGENTS.md — Memoria del proyecto

> **Documento maestro de contexto.** Reúne todo lo trabajado hasta 2026-10-29:
> el proyecto previo ("Reporte Diario Blue Yonder"), la integración validada con
> Blue Yonder, el informe de picking y el **Plan B (contingencia offline)**.
> Si arrancas en un chat nuevo, lee esto primero.

---

## 1. Qué es este proyecto

**Sistema de contingencia (plan B) para el WMS Blue Yonder** (cliente de escritorio).
Cuando Blue Yonder se cae, permite **seguir operando el picking y el
reaprovisionamiento de forma offline**, usando Excel/TSV como entrada y salida.

- Corre en **una sola PC** (un único administrador que distribuye el trabajo).
- Los usuarios de la operación **no son técnicos**: la UI debe ser simple y familiar.
- Referencia de integración: proyecto previo **"Reporte Diario Blue Yonder"**.
- **Blue Yonder NO tiene API.** El acceso real es **automatización de UI** (pywinauto)
  y captura de la grilla por portapapeles (**Ctrl+A / Ctrl+C → TSV**).

---

## 2. Proyecto previo: "Reporte Diario Blue Yonder" (fuente de la integración)

- Objetivo: cada día **10:00 am** en un PC Windows dedicado, entrar a Blue Yonder,
  capturar la grilla, generar un **dashboard HTML** y enviarlo por correo (Gmail/Workspace, SMTP).
- Stack: Python 3.11+, pandas, jinja2, keyring, pywinauto/pyautogui, Task Scheduler.
- Repo: `github.com/Freddyohlo/proyecto2` (público). Rama de trabajo: **`tools-inspeccion-detalle`**.

### Estructura de `src/`
- `config.py` — carga `config.toml` (dataclasses: App, Credenciales, Columna, Reporte, Correo)
- `parser.py` — TSV → DataFrame; descarta filas con < columnas o con patrones
- `capture_ui.py` — automatización UI completa (login → menú → área → Buscar → copiar grilla)
- `credentials.py` — keyring (Windows Credential Manager) + fallback env `BY_<SERV>_<USER>`
- `dashboard.py` + `templates/dashboard.html.j2` — HTML del reporte diario
- `mailer.py` — SMTP
- `main.py` — orquestador (`--desde-archivo` / `--desde-ultimo` / `--desde-portapapeles` / `--sin-correo`)
- `informe_picking.py` + `informe_picking_main.py` — informe de productividad de picking (INFORME 2)
- `inventario.py`, `minmax.py`, `plan_b_html.py`, `plan_b_main.py` — Plan B
- `tools/` — inspección y pruebas de UI (ver §10)

### Cómo funciona `capture_ui.capturar()` (reutilizable para el Plan B)
1. `buscar_ventana_login()` → ventana con `txtUsername` visible
2. `iniciar_sesion()` → set_text usuario/clave (de keyring) + ENTER
3. `buscar_ventana_app()` → ventana **"Soluciones"** (o con `pnlMenu`)
4. `ir_a_ccu_cuadratura()` → MenuItem por texto: `Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock`
5. `elegir_area()` → combo `arecod` = "AREA VALORADO"
6. `pulsar_buscar()` + `esperar_resultados()` (cuenta DataItem de la grilla)
7. `copiar_grilla()` → clic en grilla → HOME → Ctrl+A → Ctrl+C → pyperclip (reintenta 5x)

> **Nota técnica clave:** `Desktop.windows()` devuelve `UIAWrapper` que **NO** expone
> `child_window()`; los controles se buscan con `.descendants()` comparando
> `element_info.automation_id`.

---

## 3. Deuda técnica detectada en el repo previo (corregir en el nuevo)

- **NO hay `.gitignore`** → en el plan B hay que crearlo (excluir `.venv`, `__pycache__`, `output`, `logs`, `data`, `config.toml`). *(Ya creado en este repo.)*
- Se commiteó `src/__pycache__/*.pyc` (basura) → agregar a `.gitignore`.
- Se commiteó `config.toml` (aunque **SIN secretos reales**: solo placeholders) → en el nuevo, solo `config.example.toml`.

---

## 4. Integración validada con Blue Yonder

### Login (probado 2026-09-24)
- Ventana login: **"Blue Yonder solutions"** → `txtUsername`, `txtPassword`,
  `btnOK` ("Sign in"), `cmbServer`, `btnGo`, `cbWhId`.
- Ventana principal: **"Soluciones"**.
- Credenciales cifradas en **Windows Credential Manager** vía keyring
  (servicio `blueyonder`, usuario `RESIDENTE-STG`).
  Comandos: `python -m src.set_credentials` (guardar) y `--probar` (verificar).

### Captura de grilla
- Clic en la grilla → HOME → Ctrl+A → Ctrl+C → TSV al portapapeles.
- **El primer intento suele quedar vacío** → reintentar hasta 5 veces.
- Las celdas vienen con espacios de relleno → `.strip()`.
- Validación: contar `DataItem` de la grilla (`esperar_resultados`).
- Resultado de prueba: **530 filas válidas, 0 descartadas**.

### Controles reales (PC usuario, Win 10.0.26200)
- Grilla de datos: `"GridView:Parent=Control"` (Table, Title "MainView").
- Pantalla: `lblCurAppTitle` = "CCU Cuadratura de Stock"; breadcrumb `lblCurAppFlow`.
- Filtros: `arecod` (combo), `stoloc`, `prtnum`, `lodnum`, `invsts`, `short_dsc`,
  `hld_flg` ("Detalle"). Botón "Buscar"/"Borrar" **por title** (sin auto_id).
- Usuario `btnUserId` (RESIDENTE-STG); bodega `btnWarehouseId` (CD8000).
- Menú clásico `MenuBar` ("Aplicación"). El menú de las tres barritas se **descartó**.

---

## 5. Cuadratura de Stock — columnas

### Sin Detalle (8 columnas)
`area_sap | stoloc | prtnum | lngdsc | untqty | invsts | cantidad_lpn | arecod`
= AREA SAP | Ubicación | Nº artículo (SKU) | Descripción | Cantidad |
  Estado de inventario | Cantidad de LPN | Área

> Esta vista **NO** trae lote ni vencimiento (aunque el filtro `lodnum` exista).

### Con "Detalle" (`hld_flg`) activo — ✅ RESUELTO 2026-10-21
Al activar el checkbox **"Detalle"** y pulsar Buscar, la grilla pasa de 8 a **22 columnas**.
**EL STOCK QUE USAMOS SALE DE AQUÍ** (confirmado por el usuario). Orden:

| # | Columna | Nota |
|---|---------|------|
| 1 | Zona de trabajo | zona lógica (ej. ZTPMOD) |
| 2 | Código de zona de recogida | zona de picking (ej. ZSPCJ) |
| 3 | AREA SAP | ej. PT01 |
| 4 | Ubicación | ej. 60-001 |
| 5 | Estado de ubicación | Llena / Parcialmente lleno ← pista de capacidad |
| 6 | LPN | ej. CD800000000HNRN |
| 7 | LPN de detalle | ej. D0000007RPCI |
| 8 | Número de artículo | SKU |
| 9 | Código de espacio | coincide con el SKU en los ejemplos |
| 10 | Descripción | |
| 11 | **Cantidad** | **CANTIDAD EN STOCK (a totalizar)** |
| 12 | Cantidad pendiente | |
| 13 | Cantidad confirmada | |
| 14 | **Fecha FIFO** | 🔑 FEFO |
| 15 | Fecha de fabricación | |
| 16 | **Fecha de caducidad** | 🔑 FEFO (vencimiento) |
| 17 | Fecha de recepción | |
| 18 | Estado de inventario | Disponible / ... |
| 19 | Nombre de perfil de antigüedad | |
| 20 | **Días hasta su caducidad** | 🔑 FEFO (ya calculado) |
| 21 | Última fecha de movimiento | |
| 22 | Área | ej. AREA VALORADO |

**LOGRO:** FEFO es 100% viable (Fecha FIFO / caducidad / días). El reaprovisionamiento
también: `Estado de ubicación` (Llena/Parcialmente lleno) da pistas de capacidad.

> **Bug resuelto:** `get_toggle_state()` devuelve 0/1/2; el **2 es INDETERMINADO**, no
> "marcado". Hay que forzar a 1 con `ctrl.click()` (no `click_input`). El primer
> `click_input` deja el estado en 0; el segundo intento con `.click()` lo pone en 1.

---

## 6. Áreas: PICKING y ALMACENAMIENTO son SEPARADAS — ✅ RESUELTO 2026-10-21

El combo `arecod` (**vacío = TODAS**) contiene, entre otras:

- **AREA PICKING** ← 🟢 ubicación(es) de picking (donde se pickea)
- **AREA ALMACENAMIENTO** ← 🔵 ubicaciones en altura (de donde se reaprovisiona)
- AREA VALORADO, AREA VENCIMIENTO, AREA RETENIDO, AREA REVISION, AREA TRASVASO,
  AREA REEMPAQUE-MERMA, AREA STAGE DESPACHO, AREA STAGE RECEPCION,
  AREA ANDEN DE DESPACHO, ANDEN DE RECEPCION, MIX-MIXTOS, COBRO INTERUNIDAD,
  AREA LOGICA, áreas "*- Logical" (ADJS, CADJ, DADJ, DKIT, SHIP, etc. — lógicas, no físicas)

**Conclusión:** con el combo de área **VACÍO** se capturan TODAS las áreas en una sola
pasada. El plan B filtra por `area = "AREA PICKING"` / `"AREA ALMACENAMIENTO"`.

> ⚠️ **Nota sobre `tools/listar_areas.py`:** el volcado de controles (`[2]`) es MUY ruidoso:
> además del combo, imprime ListItem de otros paneles (nombres de USUARIOS y de DISPOSITIVOS
> de la app). **No registrar esos nombres** (datos personales). Reducir el volcado.

---

## 7. INFORME 2: "CCU Caja Pickeada" (productividad de picking)

**Objetivo:** informe de avance del picking por hora — cajas pickeadas por hora,
nº de pickeadores por hora, rendimiento (cajas/pickeador), % de avance vs la **META**
del día, y proyección de hora de término. Si pasan de las **7 a.m.**, estimar a qué hora
terminan (después se retiran pickeadores).

- **La META / venta total de cajas se INGRESA MANUAL** (confirmado por el usuario).
- Salida: **HTML (principal) + Excel (básico)**. Tabla + gráficos.
- Ruta menú: `Aplicaciones > Informes/Etiquetas > CCU Caja Pickeada`.
- Es una grilla copiable (Ctrl+A/Ctrl+C) filtrada por fecha.

### Particularidades de esta pantalla (distinta a la cuadratura)
- NO tiene campo de fecha directo: usa **CRITERIOS** (`cmboCriteria`, `btnNewCriteria`,
  `btnEditCriteria`, `btnRemoveCriteria`, `lblCriteriaList`) y **PERFILES**
  (`cmboProfile`, `btnEditProfile`, `lblProfileList`, `btnExpand`).
- ✅ RESUELTO: las casillas "Desde"/"Hasta" **NO son CheckBox** — son **Pane** dibujados a mano:
  - `auto_id='fecha_desde'` (Pane, texto='22/10/2026', L102 T242)
  - `auto_id='fecha_hasta'` (Pane, texto='22/10/2026', L401 T242)
  - Se activan haciendo **clic sobre el pane**; la fecha se escribe dentro (clic → Ctrl+A → texto → TAB).
  - Por ahora: basta con hacer clic en las 2 casillas.
- Botones: 'Buscar', 'Borrar', 'Reg. anterior', 'Reg. siguiente', 'Actualizar',
  'Cuadrícula', 'Establecer gráfico', 'Gráfico'. Otros auto_id: `usr_id` (Edit), `tbLocate`.
- La pantalla se abre desde cero al navegar el menú → puede **resetear el filtro**.
  Mejor: si ya se está en la pantalla, **NO re-navegar** (usar `--sin-menu`).
- **PENDIENTE:** hallar el control exacto del check dentro del pane (hoy se resuelve con clic).

### Columnas reales (RESUELTO 2026-10-22, 2221 filas/día) — 22 columnas
Una fila por **viaje/trip**:

| # | Columna | Nota |
|---|---------|------|
| 1 | año | |
| 2 | mes | |
| 3 | hora | 🔑 agrupar por hora (00..23) |
| 4 | trip_number | |
| 5 | Fecha de OC de comprador | |
| 6 | Nuevo tipo de pedido | ej. 3028-NORPONIENTE |
| 7 | Número de OC de comprador | |
| 8 | Número de departamento | |
| 9 | Número de lote de programación | |
| 10 | Id. de almacén | CD8000 |
| 11 | Tipo de trabajo | ej. "Recoger Sub-LPN" |
| 12 | Nivel LPN | ¿vacío? → CONFIRMAR |
| 13 | Id. de lista | ej. LST000001973968 |
| 14 | **Id. de usuario de última recogida** | 🔑 PICKHEADOR (ej. AJMARTINH) |
| 15 | h_inicio | 22/10/2026 00:19:28 |
| 16 | h_termino | 22/10/2026 00:27:01 |
| 17 | **cajas** | 🔑 MÉTRICA (ej. 102, 40, 121) |
| 18 | lineas | ej. 6, 10, 3 |
| 19 | **descripcion** | 🔑 NOMBRE del pickeador |
| 20 | **empresa** | 🔑 empresa de picking (SAEP, HUMAN-NET) |
| 21 | LPN | ej. CD8000000014LYE |
| 22 | zona_de_trabajo | ZT PET MEDIANO, ZT PET GRANDE, ZT VNR330 |

Métrica: **cajas por hora**; pickeadores = usuarios distintos (usuario/descripcion) por hora.

### Reporte deseado
- ⚠️ La **hora de trabajo se toma de `h_inicio` / `h_termino`, NO de la columna `hora`.**
  Motivo (aclarado por el usuario): el picking de un día se trabaja con **turnos que cruzan
  la medianoche** — hay pickeadores que entran el 21-10 para el picking del 22-10.
- Por hora: cajas, nº pickeadores, viajes, **horas-hombre** (suma de `h_termino - h_inicio`)
  y cajas por hora-hombre. + acumulado y % de la meta.
- Proyección de hora de término; si pasa de las 07:00 avisar.
- Salida: HTML (principal) + Excel (básico). Tabla + gráficos (barras por hora, acumulado vs meta).
- Por ahora: dato duro general (por hora). Más adelante: desglose por pickeador individual.

### ✅ IMPLEMENTADO (2026-10-22)
- `src/informe_picking.py` — motor: `leer_tsv` (normaliza 21→22 col), `resumen_por_hora`
  (por `h_inicio`, con horas-hombre), `proyectar` (meta manual + hora límite), SVG propios,
  `generar_html` / `generar_excel`.
- `src/informe_picking_main.py` — CLI:
  `python -m src.informe_picking_main --meta 12000 [--desde-archivo F | --desde-portapapeles | --capturar]`
  Opciones: `--hora-limite` (def. 07:00), `--fecha`, `--titulo`.
- `templates/informe_picking.html.j2` — panel de indicadores + 2 gráficos SVG + tabla.
- `src/capture_ui.py` — `capturar_caja_pickeada()` (navega, clic en panes `fecha_desde`/`hasta`,
  Buscar, copia) e `ir_a_por_menu()` (navegación genérica).
- `requirements.txt` — se agregó `openpyxl`.
- Salidas: `output/informe_picking_<fecha>.html` y `.xlsx`.

---

## 8. PLAN B — contingencia offline

### Decisión del usuario (2026-10-29)
- La **meta** del informe: manual (ya hecho).
- Los **min/máx**: hay una pantalla de Blue Yonder que los tiene → hay que recopilar
  **DOS capturas** (cuadratura de cantidades + min/máx) y hacerlas conversar.
- No se puede pasar el stock: el Excel pesa >3 MB. Alternativas acordadas:
  subirlo a GitHub (acepta 100 MB), comprimirlo (.zip ~300 KB), o **NO** convertirlo a
  Excel (el programa lee el `.tsv` directo, que pesa ~1 MB).
- **NOTA:** el agente **NO necesita el archivo real**; construye contra el esquema de 22
  columnas y el usuario prueba en su PC (igual que con el informe).

### Módulos nuevos
- `src/inventario.py` — `leer_detalle(tsv)` (22 col, normaliza, tipa numéricos/fechas),
  `Inventario.guardar/cargar` (SQLite tabla `stock`), `buscar`, `stock_de`, `resumen_sku`
  (separa PICKING/ALMACENAMIENTO), `fefo` (ordena por vencimiento).
- `src/minmax.py` — `leer_minmax` (mapeo de columnas configurable), `MinMax.guardar/cargar`
  (tabla `minmax`), `calcular_reposicion(stock, minmax)` → regla: si picking < mínimo,
  reponer = **máximo** (sin descontar lo que hay), y valida si el almacén alcanza (`cubre`).
- `src/plan_b_main.py` — CLI: `cargar | minmax | buscar | sku | reposicion | informe`
  (todos aceptan `--db`, default `data/plan_b.sqlite`).
- `src/plan_b_html.py` + `templates/plan_b.html.j2` — informe HTML (tarjetas, stock por
  área, tabla de reposición con filas rojas si no alcanza el stock).
- `tools/explorar_pantalla.py` — explorador GENÉRICO de pantallas: `--ruta "A>B>C"`,
  `--sin-menu`, `--listar-menu`.

### Comandos
```bash
python -m src.plan_b_main cargar   --archivo data/raw_detalle_<fecha>.tsv
python -m src.plan_b_main minmax   --archivo data/minmax.tsv
python -m src.plan_b_main buscar   --texto 856473
python -m src.plan_b_main sku      --sku 856473
python -m src.plan_b_main reposicion
python -m src.plan_b_main informe
```

### Fases
| Fase | Estado |
|------|--------|
| 0 Captura del stock (Detalle) | ✅ existe (`inspeccionar_detalle.py`) |
| 1 Visor offline (SQLite + consultas) | ✅ implementado |
| 3 Reaprovisionamiento (mín/máx) | ✅ implementado (falta capacidad) |
| 2 Picking FEFO | 🟡 falta: asignación FEFO (la venta/TRUCK ya está) |
| 4 Reincorporación al sistema | 🟡 **resuelto en el diseño**: BY se reincorpora solo; la informacion manual se reingresa a mano, pero queda RESPALDADA por nuestro sistema |
| 5 Recepción (tránsito → recibir → ubicar) | 🟡 prototipo con tarja real (`src/recepcion.py`) |
| 6 Contraste venta vs stock vs tránsito | ✅ implementado (`src/contraste.py`) |
| 7 Picking en terminales RF Zebra | 🟡 prototipo web funcionando (`src/picking_servidor.py`) |

---

## 9. Fuentes de datos y pantallas (Plan B)

Documento maestro: `docs/PLAN_B_diseno_completo.md`.

### 5 fuentes de datos
| # | Fuente | Qué aporta | Origen | Estado |
|---|--------|-----------|--------|--------|
| 1 | **Cuadratura de Stock** (Detalle) | stock real, lote, vencimiento (FEFO) | Blue Yonder | ✅ |
| 2 | **Operaciones de reabastecimiento** | mínimo y máximo por ubicación | Blue Yonder | ✅ |
| 3 | **Mantenimiento de ubicaciones** | capacidad máx/usada/pendiente, tipo, zona, recogible, reabastecimiento (73 col, 11.939 filas) | Blue Yonder | 🟡 copiado en ajuste |
| 4 | **TRUCK** (programa externo) | la **VENTA** (demanda) | Externo | ✅ formato real recibido |
| 5 | **Mercadería en tránsito** (con nº de OCA) | lo que viene en camino | **SAP** | ✅ formato real recibido |

> ⚠️ TRUCK y SAP son **EXTERNOS** (no se capturan de Blue Yonder).

### ✅ FORMATO REAL DE LOS ARCHIVOS EXTERNOS (2026-11-03)

Ambos llegaron por GitHub (rama `main` del repo). **Llave de cruce: el SKU**
(`cuadratura.prtnum` = `TRUCK.PRODUCTO` = `SAP.Material`), normalizado con
`externos.clave_sku()` (quita ceros a la izquierda: "000622" == "622").
Se verificó que las descripciones coinciden, así que la llave es correcta.

**VENTA — TRUCK** (`ExcelPreventaBIARRIAG (75).csv`)
- CSV con **separador `;`** y encoding **UTF-8**. 44 columnas.
- ⚠️ Trae **miles de filas totalmente vacías al final** (33.127 de 33.521 en la
  muestra) → hay que descartarlas.
- Columnas útiles: `PRODUCTO` (SKU), `DESCRIPCION.4` (descripción), `CANTIDAD`
  (cajas), `UNIDAD` (CJ/CU), `FECHA` (dd/mm/aaaa), `ESTADO` (ING/LIQ),
  `CATEGORIA`, `MARCA`, `TAMAÑO`, `CAMION`, `VIAJE`, `PLANILLA`, `ID-CLIENTE`,
  `RAZON SOCIAL`.

**TRÁNSITO — SAP** (`IFAC SAP TRANSITO DE PRODUCTOS.xlsx`)
- Excel `.xlsx`, **hoja `Data`**, 52 columnas.
- Columnas útiles: `Material` (SKU), `Texto breve material` (descripción),
  `Cantidad Entrega` (cajas), `Cantidad Pallet`, `OCA(Orden de Carga)` 🔑,
  `Id.1 / OCA`, `Nº de transporte`, `Centro Origen/Destino`, `Fecha`,
  `Clase de movimiento` (101 = traslado), `Stat.global transp.` (6/7),
  `Grupo de artículos`, `Sociedad`.

**Módulos que los leen** (`src/externos.py`)
- `leer_venta(bytes|str)` → `Venta`; `demanda_por_sku()`, `.guardar/.cargar`.
- `leer_transito(bytes)` → `Transito`; `por_oca()`, `en_camino_por_sku()`, `.guardar/.cargar`.
- `clave_sku(valor)` → llave normalizada.
- Tablas SQLite: `venta` y `transito` (además de `stock` y `minmax`).

**Contraste** (`src/contraste.py`)
- `calcular(stock, venta, transito)` → por SKU: `demanda`, `picking`, `almacen`,
  `transito`, `disponible`, `falta`, `cubre`.
- `disponible = picking + almacen + transito`; `falta = max(0, demanda - disponible)`.
- `.quiebres` (SKUs que no alcanzan), `.resumen()` (% cubierto), `.sin_stock`, `.sin_venta`.

### Comandos nuevos
```bash
python -m src.plan_b_main venta      --archivo "ExcelPreventaBIARRIAG (75).csv"
python -m src.plan_b_main transito   --archivo "IFAC SAP TRANSITO DE PRODUCTOS.xlsx"
python -m src.plan_b_main contraste  [--exportar contraste.csv]
```

> **Valor demostrado (prueba 2026-11-03):** con la venta real + el tránsito real,
> el contraste detectó 109 SKUs en quiebre, pero **24 de ellos se cubrían
> justamente con la mercadería en tránsito de SAP** (ej. KUNSTMANN TOROBAYO KEG30L:
> demanda 21, stock 0, tránsito 1040). Ese es el aporte del módulo.

### 5 procesos
1. **Contraste** Venta vs Stock → ¿alcanza para abastecer? (TRUCK vs cuadratura)
2. **Picking FEFO** → primero lo que vence antes
3. **Reaprovisionamiento** → bajo mínimo → reponer hasta máximo (usa capacidad)
4. **Recepción** (NUEVO) → en tránsito → recibir (cantidad, lote, vencimiento) →
   ubicar (sugerir por capacidad) → actualizar stock → disponible para picking
5. **Reincorporación** → exportar lo hecho offline al volver Blue Yonder

### Rutas de menú confirmadas
- Cuadratura: `Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock`
- Mín/máx: `Aplicaciones > Reabastecimiento > Operaciones de reabastecimiento`
- Ubicaciones: `Aplicaciones > Configuración del sistema > Instalación > Mantenimiento de ubicaciones`
- Recepción (áreas a capturar): `EXPR Expected Receipts`, `ANDEN DE RECEPCION`,
  `AREA STAGE RECEPCION`, `WIP Expected Receipts`, `WEXP Production Expected Receipts`

### Otros módulos vistos en el menú
CCU Caja Pickeada, CCU Pedidos Cortados, CCU Operaciones de Unitarios, CCU Status Carga,
Cambio de Zonas, CCU Interfaz Venta, CCU Fleetloader Nuevo, CCU Cuadratura de Stock.

### Pantalla de mín/máx — ✅ ENCONTRADA (2026-10-29)
- Ruta: `Aplicaciones > Reabastecimiento > Operaciones de reabastecimiento`
  (⚠️ el submenú se llama **"Operaciones de reabastecimiento"**, NO "Opciones";
  auto_id del MenuItem = **294**). Luego pulsar Buscar → **1.122 filas**.
- **Columnas reales (18):** Id. de almacén | Número de artículo | Ubicación | Zona de
  movimiento | Estado de inventario | Porcentaje | **Máximo de unidades** | **Mínimo de unidades** |
  Máximo de ubicaciones para artículo | Completo | Último intento de reabastecimiento |
  Última modificación de | Número de reabastecimiento | Porcentaje de incremento |
  Unidad de incremento | Porcentaje de liberación | is_purged | Código de zona de movimiento
- → **MÁXIMO = col 7, MÍNIMO = col 8, SKU = col 2, Ubicación = col 3.**
- Fila real: `CD8000 | 000622 | KEG-04 | ZM PICKING | Disponible | Unchecked | 168 | 160 | ...`
- Herramienta: `tools/inspeccionar_reabastecimiento.py` → `data/reabastecimiento_<fecha>.tsv`
- Carga: `python -m src.plan_b_main minmax --archivo <tsv>` (`--formato reabastecimiento` por defecto).

### Pantalla alternativa: "Mantenimiento de ubicaciones" (2026-10-29)
El usuario encontró otra ruta con la MISMA info y más detalle de ubicación:
`Aplicaciones > Configuración del sistema > Instalación > Mantenimiento de ubicaciones`.
Herramienta: `tools/inspeccionar_ubicaciones.py` (navega + Buscar + extrae).

### ⚠️ PROBLEMA ABIERTO: copiar la grilla de reabastecimiento
Ctrl+A/Ctrl+C solo copia **1 fila de 1.122** en esa pantalla (grilla **DevExpress**).
La grilla SÍ se encuentra (se cuentan 1.122 DataItem) y el Buscar SÍ se pulsa:
el problema es SOLO la selección/copiado.

Mitigaciones implementadas:
- `capture_ui.grilla_principal()`: elige la tabla con **MÁS filas** (había varias con el
  mismo auto_id: una chica de filtros y la grande de datos).
- `copiar_grilla()`: **8 estrategias**, priorizando `Ctrl+Shift+End`, con reintentos y
  verificación contra `filas_esperadas`.
- `tools/diagnosticar_copia_grilla.py`: prueba cada método y reporta cuántas líneas trae cada uno.
- Respaldo por UIAutomation: `_celdas_visibles()` descarta celdas de tamaño cero/(0,0);
  `_filas_desde_celdas()` agrupa por top (tolerancia 6px) y ordena por left;
  `_quitar_columna_numeros()` elimina la columna de nº de fila si es 0,1,2,...;
  `extraer_grilla_por_uia()` hace scroll (PGDN) y acumula filas nuevas deduplicadas.
- **PENDIENTE:** que el usuario corra el diagnóstico y diga qué método copia las 1.122
  (y probar la extracción UIA corregida en el PC).

---

## 10. Herramientas del repo (rama `tools-inspeccion-detalle`)

### Terminales RF (Zebra Android) — picking de contingencia
- `src/stock_vivo.py` — **stock vivo**: la foto de la cuadratura + reservas +
  pickeado. `disponible = cantidad - reservado - pickeado`. `reservar()` es
  atomico (la condicion va en el UPDATE): dos Zebra no pueden ganar la ultima
  caja. `liberar()`, `rebajar()`, `filas_disponibles()` (orden FEFO en SQL),
  `resumen()`, `estado()`. SQLite en modo WAL. La tabla `stock` (la foto) NO se
  toca: queda como respaldo de lo que decia Blue Yonder.
- `docs/PLAN_B_dispositivos_RF.md` — análisis de arquitectura (opciones web vs
  Velocity/telnet, riesgos, plan).
- `src/picking.py` — **destina** las tareas de picking desde la venta:
  `destinar(db, demanda)` elige ubicacion/lote por **FEFO** y **RESERVA** el
  stock; devuelve `(creadas, reservadas, faltantes)`. `confirmar()` rebaja y
  libera; si el pick es parcial, re-encola lo que falta; `saltar()` libera la
  reserva. `tarea_pendiente()`, `obtener_tarea()`, `resumen_tareas()`.
- `src/picking_servidor.py` — servidor web del picking guiado:
  `python -m src.picking_servidor --puerto 8080 --db data/plan_b.sqlite`
  El sistema **dirige** ("ve a C01-01-01-01, saca N cajas"); el picker **escanea
  el QR del rack** y el sistema **verifica**. Si coincide, el picker **digita la
  cantidad**. NO se escanea SKU al pickear (la ubicación de picking es única por
  SKU). Guarda cada pick en la tabla `picking`. Si saca menos de lo pedido, la
  tarea queda `parcial` y **lo que falta se re-encola** como tarea nueva.
  `parsear_ubicacion()` acepta el QR en varios formatos.

### Recepción (entrada de mercadería)
- `docs/PLAN_B_recepcion.md` — diseno del flujo (recibir → ubicar) con la tarja real
  + propuestas de optimizacion.
- **TARJA REAL (imagen `IMG_20261103_045905.jpg`, leida por OCR):**
  LPN/SSCC `278043001201264701` | SKU `700809` | GATO DULCE-DC-VNR1500CCX8-TR |
  elaboracion `31.10.2026 08:10` | vencimiento `04.06.2027` | cajas reales `198` |
  cajas/pallet `60` | perfil antiguedad `999` | usuario `RESIDENTE-STG`.
  - 🔑 El LPN de la tarja es un **SSCC GS1** (18 digitos, con digito de control que
    VALIDA). Se puede detectar un escaneo malo. `recepcion.sscc_valido()`.
  - 🔑 La tarja imprime las fechas **con PUNTOS** (`31.10.2026`), no barras.
    Era un BUG: se perdia el vencimiento en silencio -> FEFO ciego. Corregido.
  - 🔑 **CAJAS REALES (198) vs CAJAS/PALLET (60)** = 3.3 pallets. Sirve para
    detectar pallet incompleto.
  - El LPN es **la identidad del bulto en cada tramo**: cambia al llegar al picking
    (el picking tiene su propio LPN). Por eso no calzaba con la cuadratura.
  - ✅ NO se valida contra el transito de SAP: si la mercaderia llega, se recibe
    y despues se cuadra (criterio del usuario).
- `recibir_y_ubicar()` — optimizacion: si la tarja ya trae la ubicacion, se recibe
  y se ubica en UN paso (boton "RECIBIR Y UBICAR").
- 🎯 **GS1-128 CONFIRMADO**: el codigo de barras de la tarja trae TODOS los datos
  (el usuario confirmo que al escanearlos se llenan solos). `src/gs1.py` parsea
  los Application Identifiers: 00=SSCC, 17=vencimiento, 11=elaboracion, 30=cantidad,
  10=lote, 01=GTIN. Fechas en YYMMDD (pivote YY<70 -> 20YY; dia 00 = ultimo del mes).
  `recepcion.desde_escaneo()` arma la recepcion desde el escaneo. La pantalla
  prellena cantidad, vencimiento y elaboracion con un solo escaneo.
  - BUG encontrado: al cortar los AIs variables sin separador, "198" se partia en
    "1"+AI(98) y la cantidad salia 1. Los AIs internos 90-99 NO se usan como corte.
  - El SKU TAMBIEN viene dentro del codigo (confirmado por el usuario). Como no se
    pudo obtener el texto crudo, `recepcion.identificar_sku()` lo descubre solo:
    (a) ancla en el SSCC (se reconoce por su digito de control: `gs1.ubicar_sscc`),
    (b) junta candidatos (AIs 240/241/90-99 + numeros post-SSCC),
    (c) elige el que EXISTE en el stock cargado. Si ninguno calza, usa el mas
    probable y avisa (`origen: "codigo"`).
  - El codigo sin separador FNC1 es ambiguo: `gs1.parsear` genera TODAS las
    interpretaciones y elige la de mayor puntaje (`_puntaje`).
  - Resultado: UN escaneo llena todo (SKU, cantidad, vencimiento, elaboracion).
    PENDIENTE: con un escaneo real, fijar el AI exacto del SKU.
- Portada con menu en `/` (Pickear / Recibir / Ver estado); picking en `/picking`.
- `src/recepcion.py` — `recibir()` (idempotente por LPN), `ubicar()` (conserva
  lote y vencimiento), `sugerir_ubicacion()`, `pendientes()`, `resumen()`.
  Pantalla: `http://<IP>:8080/recepcion`.
  ⚠️ La tarja trae el vencimiento **solo impreso** (no por sistema): sin el, FEFO
  no puede ordenar. El sistema lo avisa si falta.
  ⚠️ El LPN de la tarja (18 digitos) NO coincide con los de la cuadratura
  (`CD8000...` de 14, o `D000...` de 11): falta confirmar a cual corresponde.

### Informe del día e informes
- `src/informe_dia.py` — **informe del día de contingencia**: consolida stock vivo,
  tareas, recepción, SKU nuevos, pickeado por SKU y ubicaciones tocadas.
  `recopilar(db, fecha)`, `generar_html()`, `generar_excel()`, `alertas()`.
- `templates/informe_dia.html.j2` — HTML del informe (imprimible).
- **Botón "GENERAR INFORMES"** en la portada (`/`): genera y ofrece los enlaces
  al HTML y al Excel (`POST /api/informe/generar`; se sirven en `/informes/<archivo>`).
- CLI: `python -m src.plan_b_main informe-dia [--fecha AAAA-MM-DD]`.
- **Botón "CERRAR EL DÍA"** en la portada: libera las reservas que quedaron
  colgando (tareas pendientes que no se pickearon) y genera el informe de cierre.
  `picking.cerrar_dia()` marca las pendientes como `cerrada` y libera su reserva.
  NO toca lo pickeado (eso ya salió físicamente). Sin esto, las reservas se
  arrastran al día siguiente y el disponible queda artificialmente bajo.

### SKU nuevos (producto que va llegando)
- Llega mercadería que **no venía en la cuadratura** (producto nuevo). En vez de
  rechazarla, se da de alta: `recepcion.crear_sku()` → tabla `sku_nuevos` + entra
  al stock vivo. `recepcion.skus_nuevos()`.
- ⚠️ **REGLA (usuario): el producto nuevo entra a ALMACENAMIENTO, NUNCA a PICKING.**
  Un producto que recién llega no tiene ubicación de picking asignada: primero se
  guarda en altura y después el reaprovisionamiento lo baja al picking. Hay tests
  que lo blindan (`test_sku_nuevo_entra_a_almacenamiento_no_a_picking`).
- En la pantalla de recepción aparece el botón **"+ DAR DE ALTA ESTE SKU"** cuando
  el SKU escaneado no está en el stock (`origen: "codigo"`).
- CLI: `python -m src.plan_b_main recepcion --sku-nuevo 700809 --cantidad 198 ...`.

### Inspección / exploración de pantallas
- `tools/inspeccionar_ui.py` — lista los `auto_id` de la ventana (calibración UI)
- `tools/probar_captura.py` — login + copia de la grilla (sin correo)
- `tools/probar_login.py` — prueba solo el login automático
- `tools/probar_menu_arriba.py`, `tools/probar_navegacion.py` — navegación por menú
- `tools/capturar_menu.py`, `tools/capturar_pantalla.py` — capturas de pantalla
- `tools/diagnosticar_copia.py`, `tools/diagnosticar_menu.py` — diagnósticos
- `tools/diagnosticar_copia_grilla.py`, `tools/diagnosticar_copia_grilla_deep.py` — copiado de grillas
- `tools/inspeccionar_detalle.py` — navega, activa "Detalle", captura y guarda el TSV
- `tools/listar_areas.py` — lista las opciones del combo de área (⚠️ ruidoso, ver §6)
- `tools/volcar_pantalla.py` — vuelca todos los controles (calibración de auto_id)
- `tools/analizar_tsv.py` — analiza el TSV capturado (sin Windows)
- `tools/inspeccionar_caja_pickeada.py` / `..._deep.py` — pantalla "CCU Caja Pickeada"
- `tools/inspeccionar_reabastecimiento.py` — pantalla de mín/máx
- `tools/inspeccionar_ubicaciones.py` — "Mantenimiento de ubicaciones"
- `tools/explorar_pantalla.py` — explorador GENÉRICO (`--ruta "A>B>C"`, `--listar-menu`)

---

## 11. Estado del prototipo

- **153 tests pasan** en Linux: `tests/test_dashboard.py`, `test_parser.py`,
  `test_informe_picking.py` (18), `test_plan_b.py` (12), `test_externos.py` (11),
  `test_picking_servidor.py` (12), `test_stock_vivo.py` (19), `test_recepcion.py` (26), `test_gs1.py` (27), `test_informe_dia.py` (19).
- Probado end-to-end: `cargar → minmax → buscar → sku → reposicion → informe` ✅
- Probado con **archivos reales** (2026-11-03): `venta` (TRUCK) → `transito` (SAP) →
  `contraste` ✅ (394 líneas de venta, 2.227 de tránsito).
- Probado el **picking guiado** end-to-end (venta real → tareas FEFO → servidor) ✅:
  35 tareas, 34 ubicaciones, FEFO respetado, verificación de QR acepta/rechaza bien.
- Cómo probar sin la app (aquí / Linux):
```bash
python -m src.main --desde-archivo data/muestra.tsv --sin-correo   # dashboard
python -m src.main --desde-portapapeles --sin-correo               # TSV del portapapeles
PYTHONPATH=. python -m pytest tests/ -q                            # tests
```

---

## 12. Pendiente de recibir / confirmar

- [ ] Archivo del proyecto anterior (sin credenciales) — *(el repo ya está disponible)*
- [ ] Capturas/video de los menús de Blue Yonder
- [ ] Excel de inventario de ejemplo (datos ficticios)
- [ ] Columnas exactas del Excel (¿incluye ubicaciones de almacenamiento? ¿máximos?)
- [ ] Cómo reingresan los datos a Blue Yonder al volver el sistema
- [x] Origen de los pedidos durante la contingencia → **TRUCK** (formato recibido) ✅
- [x] Archivo de tránsito (SAP, con nº de OCA) → **formato recibido** ✅
- [ ] Volumen: nº SKUs, ubicaciones, pedidos/día
- [ ] SO / permisos admin / offline / impresión
- [ ] **"La última noticia"** que el usuario mencionó (por confirmar)
- [ ] Flujo físico de recepción, y cómo se reingresan los datos
- [ ] Destinatarios exactos del correo (proyecto previo)

---

## 13. Seguridad

- **NO guardar contraseñas en el repo.** Usar variables de entorno / gestor de secretos.
- Las credenciales del PC dedicado se configuran **localmente** en esa máquina
  (Windows Credential Manager vía keyring).
- En el repo: solo `config.example.toml` (sin secretos). `config.toml` va en `.gitignore`.
