# AGENTS.md — Memoria del proyecto

## Resumen del proyecto
Automatizar un **reporte diario** que hoy se arma manualmente a partir de información
extraída de **Blue Yonder** (aplicación de escritorio, sin API).

## Objetivo
Todos los días a las **10:00 am**:
1. Extraer información desde Blue Yonder (app de escritorio, Windows).
2. Procesar los datos (limpiar, agrupar, calcular métricas).
3. Generar un **dashboard en HTML** (gráficos + tablas).
4. Enviar el reporte por **correo electrónico** a los destinatarios definidos.

## Entorno de ejecución
- Correrá en un **PC local/Windows dedicado** (no en la nube).
- Ese PC tiene **credenciales propias** para Blue Yonder (cuenta de servicio).
- Debe quedarse encendido 24/7 y sin suspensión automática (para que dispare el cron a las 10:00).

## Restricciones / Hechos conocidos
- Blue Yonder **no tiene API**.
- Es una **aplicación de escritorio** → la automatización debe correr en esa misma máquina.
- Estrategias de extracción posibles (en orden de preferencia):
  1. Exportación nativa de la app (Excel/CSV/PDF) — BEST
  2. Reportes programables/batch dentro de la app
  3. Consulta directa a base de datos (si IT da acceso — Blue Yonder suele usar SQL Server)
  4. Automatización de UI (pywinauto / pyautogui) o Power Automate Desktop
  5. OCR / captura de pantalla (último recurso)

## DESCUBRIMIENTO CLAVE (resuelto)
- Blue Yonder NO tiene exportacion nativa. El proceso actual es **copiar y pegar** la grilla a Excel.
- En la grilla **Ctrl+A + Ctrl+C funciona** y copia TODA la tabla al portapapeles en **formato TSV**.
- Gracias a esto NO hace falta OCR ni leer celdas una a una: `pyperclip.paste()` + pandas resuelve la captura.
- Ejemplo de fila copiada (8 columnas, separadas por tabulacion):
  `PT01  60-267  856473  1865-DOUBLE_BARREL-CS-VNR750-C  33  Disponible  1  AREA VALORADO`
  -> planta | ubicacion | sku | descripcion | cantidad | estado | flag | area

## Estado del prototipo (funcional, probado)
Modulos en `src/`:
- `config.py` — carga `config.toml`
- `parser.py` — TSV -> DataFrame (con filtros de encabezado/totales)
- `dashboard.py` + `templates/dashboard.html.j2` — genera el HTML
- `mailer.py` — envio SMTP (HTML + adjunto)
- `credentials.py` / `set_credentials.py` — credenciales via keyring (Windows Credential Manager)
- `capture_ui.py` — automatizacion de la UI (pywinauto) — **PENDIENTE probar en el PC Windows**
- `main.py` — orquestador
Tests en `tests/` (8 pasando).

## PENDIENTE — probar en el PC dedicado (Windows)
- [ ] Instalar la app y probar `capture_ui.capturar()` de punta a punta
- [ ] Ajustar `[app].exe`, auto_id/titles de los campos de login y de la grilla
- [ ] Definir el flujo de navegacion real (menus hasta la pantalla de la grilla)
- [ ] Definir si la grilla copiada trae encabezado o filas de TOTAL (usar `saltar_encabezado` / `ignorar_si_contiene`)
- [ ] Programar el Task Scheduler a las 10:00 am

## DECISIONES CONFIRMADAS POR EL USUARIO
- Correo: **Gmail corporativo / Google Workspace** (SMTP smtp.gmail.com:587 STARTTLS).
  Requiere **Contrasena de aplicacion** (Google bloquea la clave normal por SMTP).
  Ojo: en Workspace el admin puede tenerlas deshabilitadas -> alternativa OAuth2 o relay interno.
- Columnas confirmadas: planta | ubicacion | sku | descripcion | cantidad | estado | flag | area.
- **NO hay fila de TOTAL** en la grilla copiada -> `ignorar_si_contiene` no hace falta.
- El valor de interes es **cantidad** (columna a totalizar).
- Corre en un **PC Windows dedicado**, con credenciales propias (cuenta de servicio).
- Código en **Python** (confirmado por el usuario).

## DOCUMENTACION / HERRAMIENTAS AGREGADAS
- `docs/GUIA_LOGIN_Y_CAPTURA.md` — guia paso a paso del login y la captura (8 pasos).
- `tools/inspeccionar_ui.py` — imprime los controles/auto_id de la ventana (calibracion UI).
- `tools/probar_captura.py` — prueba solo login + copia de la grilla (sin correo).

## AUTO_ID REALES (PC del usuario, Windows 10.0.26200.9550, Blue Yonder solutions)
- Ventana: 'Blue Yonder solutions' (en el PC hay habitualmente 2 ventanas con el MISMO titulo).
- Campo usuario:   auto_id = "txtUsername"
- Campo clave:     auto_id = "txtPassword"
- Boton entrar:    auto_id = "btnOK"   (texto "Sign in")
- Desplegable servicio/servidor: auto_id = "cmbServer"
- Boton:           auto_id = "btnGo"   (texto "Go")
- Desplegable:     auto_id = "cbWhId"  (posible almacen/bodega)
- Otros: btnClose ("Please choose a service and provide your login")
- PENDIENTE: confirmar el flujo manual de login (si hay que elegir servicio y pulsar Go antes de escribir usuario/clave).

## HITOS LOGRADOS EN EL PC DEL USUARIO
- [x] pywinauto funciona y detecta la ventana 'Blue Yonder solutions'.
- [x] **LOGIN AUTOMATICO FUNCIONA**: el robot escribe usuario (txtUsername),
      contrasena (txtPassword) y pulsa Enter -> entra al sistema. Probado 2026-09-24.
- [x] **CREDENCIAL CIFRADA**: guardada en el Administrador de credenciales de Windows
      (keyring, servicio 'blueyonder', usuario RESIDENTE-STG). El login ya NO pide la clave.
      Probado 2026-09-24: `python tools/probar_login.py` entra solo, sin intervencion.
      Comandos: `python -m src.set_credentials` (guardar) y `--probar` (verificar).

## CONTROLES DESCUBIERTOS — PANTALLA PRINCIPAL / GRILLA
La ventana de la app se llama **'Soluciones'** (no 'Blue Yonder solutions': esa era el login).
- Grilla (tabla de datos):  auto_id = "GridView:Parent=Control"  (control_type Table, titulo "MainView")
- Combo de area:            auto_id = "arecod"   (elegir "AREA VALORADO")
- Boton Buscar:             control_type Button, titulo 'Buscar'  (SIN auto_id -> usar title)
- Boton Borrar:             Button 'Borrar' (sin auto_id)
- Acceso directo favoritos: auto_id = "btnFavorites"  (texto "CD8000_PRD")
- Titulo de la pantalla:    auto_id = "lblCurAppTitle" (texto "CCU Cuadratura de Stock")
- Breadcrumb:               auto_id = "lblCurAppFlow" (texto "Informes/Etiquetas > ")
- Boton usuario:             btnUserId ("RESIDENTE-STG"); bodega: btnWarehouseId ("CD8000")
- Campos de filtro: arecod (combo), stoloc (edit), prtnum (edit), lodnum (edit),
  invsts (combo), short_dsc (edit), hld_flg (checkbox "Detalle")

## FLUJO MANUAL DEL USUARIO (para automatizar)
1. Login (ya automatizado).
2. Menu CLASICO DE ARRIBA (MenuBar 'Aplicación'), NO las barritas:
   Aplicaciones -> Informes/Etiquetas -> CCU Cuadratura de Stock.
   (Los items salen como MenuItem con sus textos exactos; funcionan por texto.)
3. Combo "area" (arecod) -> seleccionar "AREA VALORADO".
4. Boton "Buscar".
5. Clic en la grilla -> Ctrl+A -> Ctrl+C (datos en TSV).

## COLUMNAS REALES DE LA GRILLA (confirmadas por el Header de la tabla)
El HeaderItem de la grilla revelo los nombres reales en este orden:
area_sap | stoloc | prtnum | lngdsc | untqty | invsts | cantidad_lpn | arecod
= AREA SAP | Ubicación | Número de artículo | Descripción | Cantidad |
  Estado de inventario | Cantidad de LPN | Área
Coincide con el TSV copiado (8 columnas). La columna que digo "flag" es
"Cantidad de LPN"; la numerica a totalizar es "Cantidad" (untqty).

## HITO MAYOR: CAPTURA DE PUNTA A PUNTA AUTOMATICA (2026-09-24)
`python tools/probar_captura.py` con la app en la pantalla de login hace TODO solo:
login -> menu -> combo area -> Buscar -> espera resultados -> copia la grilla.
Resultado: 530 filas validas, 0 descartadas. Crudo en data/raw_AAAA-MM-DD.tsv.
IMPORTANTE: el primer intento de copia suele quedar vacio; el reintento (hasta 5)
lo resuelve. Es normal ver "(intento 1: portapapeles vacio, reintentando...)".
La captura se valida contando DataItem de la grilla (esperar_resultados).

## HITO: COPIA DE LA GRILLA FUNCIONA (2026-09-24)
Estrategia validada con `python tools/diagnosticar_copia.py`:
  clic en la grilla -> HOME -> Ctrl+A -> Ctrl+C  == 544 lineas copiadas OK.
OJO: las celdas vienen con espacios de relleno; el parser ahora hace .strip().
Los pasos 2 (combo area) y 3 (Buscar) del flujo tambien funcionan.

## HITO: NAVEGACION POR MENU FUNCIONA (2026-09-24)
`python tools/probar_menu_arriba.py` navego Aplicaciones > Informes/Etiquetas >
CCU Cuadratura de Stock y la pantalla quedo con titulo='CCU Cuadratura de Stock'
y flujo='Informes/Etiquetas > '. La funcion `ir_a_ccu_cuadratura` usa este camino
(busca MenuItem por texto). El paso por las tres barritas quedo DESCARTADO.

## MENU PRINCIPAL CAPTURADO (MenuBar 'Aplicacion')
Menu clasico: Archivo, Ver, Herramientas, Aplicaciones, Abrir aplicaciones, Acciones, Ayuda.
Menu de aplicaciones (el de las tres barritas) = panel izquierdo, NO es MenuItem sino Button:
- Panes del menu: "pnlMenu", "grpMenu", "AppExplorer"
- Boton de las tres barritas: auto_id="btnPinMenu" (texto 'CD8000_PRD')
- Boton favoritos (estrella): auto_id="btnFavorites" ('CD8000_PRD')
- Boton cerrar menu: auto_id="btnMenuClose"
- El item buscado: Button text 'CCU Cuadratura de Stock' con auto_id='1705808' (dentro del menu, L17 T381)
- OJO: hay OTRO Button 'CCU Cuadratura de Stock' auto_id='12977232' en L120 T93 (es la pestana de app abierta)
  -> desambiguar por auto_id '1705808' (el del menu) o por estar dentro de pnlMenu/grpMenu
- Breadcrumb confirma grupo: lblCurAppFlow = 'Informes/Etiquetas > '
- Otros items del menu: CCU Caja Pickeada, CCU Pedidos Cortados, CCU Operaciones de Unitarios,
  CCU Status Carga, CCU Caja Pickeada, Cambio de Zonas, CCU Interfaz Venta, CCU Fleetloader Nuevo, etc.

## PENDIENTE — definiciones por hacer
- [ ] Destinatarios exactos del correo (lista)
- [ ] Flujo de menus/pasos hasta la pantalla de la grilla (siguiente gran paso)
- [ ] Formato visual deseado del dashboard

## Como probar sin la app (aqui / Linux)
```
python -m src.main --desde-archivo data/muestra.tsv --sin-correo   # genera dashboard
python -m src.main --desde-portapapeles --sin-correo               # toma el TSV del portapapeles
PYTHONPATH=. python -m pytest tests/ -q                            # tests
```

## Seguridad
- NO guardar contraseñas en el repo. Usar variables de entorno / gestor de secretos.
- Las credenciales del PC dedicado se configuran localmente en esa máquina.

## Stack tentativo (por confirmar cuando se conozca el método de extracción)
- Python (automatización + generación de reporte)
- Alternativa UI sin código: Power Automate Desktop
- Programación: Task Scheduler (Windows) o cron
