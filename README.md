# Reporte Diario Blue Yonder

Automatiza el reporte diario: extrae la informacion de **Blue Yonder** (app de
escritorio), genera un **dashboard HTML** y lo envia por **correo electronico**,
todos los dias a las 10:00 am desde un PC Windows dedicado.

## Como funciona

```
Blue Yonder (grilla)  --Ctrl+A/Ctrl+C-->  portapapeles (TSV)
        |                                          |
   pyautogui/pywinauto                       parser (pandas)
   (captura la UI)                                 |
                                  dashboard HTML + CSV
                                                   |
                                          correo SMTP (HTML + adjunto)
```

El sistema no expone API ni exportacion; el unico canal es la grilla. La copia
de la grilla con `Ctrl+A` / `Ctrl+C` entrega toda la tabla en formato TSV, que
Python procesa directamente.

## Requisitos

- Python 3.11+
- En el PC de Blue Yonder (Windows): `pyautogui`, `pywinauto`

```
pip install -r requirements.txt
pip install pyautogui pywinauto   # solo en el PC Windows
```

## Guia de puesta en marcha (login + captura)

La guia detallada paso a paso esta en **[`docs/GUIA_LOGIN_Y_CAPTURA.md`](docs/GUIA_LOGIN_Y_CAPTURA.md)**:
descubrir los controles de la app, ajustar el login, guardar credenciales, probar
la captura, configurar Gmail y programar la tarea de las 10:00 am.

Herramientas de apoyo (solo Windows):

```
python tools/inspeccionar_ui.py --titulo "Blue Yonder"   # ver auto_id de los controles
python tools/probar_captura.py                           # probar login + copia de la grilla
```

## Configuracion

```
cp config.example.toml config.toml
```

Edita `config.toml`:
- `[app]` ruta al ejecutable de Blue Yonder
- `[columnas]` nombres y tipo (texto/numero) de cada columna, en orden
- `[reporte]` agrupacion, total, filtros de encabezado/totales
- `[correo]` servidor SMTP y destinatarios

### Credenciales (nunca en el repo)

Se guardan cifradas en el Administrador de credenciales de Windows:

```
python -m src.set_credentials      # pide servicio, usuario y contrasena
```

Alternativa: variables de entorno `BY_<SERVICIO>_<USUARIO>`.

## Uso

```
# Flujo real (automatiza la app; solo en Windows)
python -m src.main

# Probar sin la app
python -m src.main --desde-archivo data/muestra.tsv --sin-correo
python -m src.main --desde-portapapeles --sin-correo

# Tests
PYTHONPATH=. python -m pytest tests/ -q
```

## Programar a las 10:00 am (Windows)

Programador de tareas -> Crear tarea basica -> Diariamente 10:00 ->
Iniciar programa:

```
Programa:   C:\ruta\al\venv\Scripts\python.exe
Argumentos: -m src.main
Iniciar en: C:\ruta\al\proyecto
```

Importante: el PC debe permanecer encendido y sin suspension automatica.

## Seguridad

- Las contrasenas viven en el almacen del sistema (keyring), no en archivos.
- `config.toml`, `data/`, `output/` y `logs/` estan en `.gitignore`.
