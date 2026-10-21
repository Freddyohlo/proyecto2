# Guía: login en Blue Yonder y captura de la grilla (paso a paso)

Esta guía se ejecuta **en el PC Windows dedicado** donde está instalado Blue Yonder.
Aquí (Linux) no se puede probar la app; por eso hay que calibrar la UI en ese PC.

El objetivo es conseguir que el robot haga esto, sin intervención humana:

```
abrir Blue Yonder  ->  escribir usuario y clave  ->  pulsar Aceptar
   ->  navegar por los menús hasta la grilla  ->  Ctrl+A, Ctrl+C
   ->  leer el portapapeles (TSV)  ->  seguir con el dashboard y el correo
```

---

## Paso 0 — Requisitos previos en el PC

1. Blue Yonder instalado y funcionando (puedes entrar a mano).
2. Python 3.11 o superior instalado, marcando **"Add Python to PATH"**.

En una terminal (PowerShell o CMD), dentro de la carpeta del proyecto:

```powershell
pip install -r requirements.txt
pip install pyautogui pywinauto
```

3. Comprueba que Blue Yonder abre con su ruta conocida. Anótala, por ejemplo:
   `C:\Program Files\Blue Yonder\Cliente\cliente.exe`

---

## Paso 1 — Descubrir los controles de la ventana (clave del login)

La automatización necesita "direcciones" de los campos (llamados `auto_id`), que
son distintos en cada instalación. Para descubrirlos usamos dos caminos:

### Opción A — `inspect.exe` (recomendada)

1. Descarga/instala **Windows SDK** o **Accessibility Insights for Windows**
   (Microsoft, gratis). Trae la herramienta `inspect.exe`.
2. Abre Blue Yonder y déjalo en la pantalla de **login**.
3. Abre `inspect.exe`. Pasa el ratón sobre el campo de **Usuario**.
4. En `inspect.exe`, busca la propiedad **`AutomationId`**. Anótala (ej: `txtUsuario`).
5. Repite con: campo **Contraseña** (`txtPassword`), botón **Aceptar/Aceptar` (`btnAceptar`).
6. Luego avanza a la **pantalla de la grilla** y anota el `AutomationId` de la
   tabla/grilla (ej: `grdResultados`).

### Opción B — el script que ya incluí

Con Blue Yonder abierto en la pantalla de login, ejecuta:

```powershell
python tools\inspeccionar_ui.py --titulo "Blue Yonder"
```

Esto imprime **todos los controles** de la ventana con sus identificadores.
Busca las líneas con `Edit` (campos de texto), `Button` (botones) y `Table`
(la grilla) y anota sus `auto_id`.

> Truco: si el título de la ventana no coincide, ejecuta sin `--titulo` y
> `inspeccionar_ui.py` se enganchará a la ventana que esté en primer plano.

---

## Paso 2 — Configurar el archivo `config.toml`

Copia el ejemplo y edítalo:

```powershell
copy config.example.toml config.toml
```

Ajusta al menos:

```toml
[app]
nombre = "Blue Yonder"
exe = "C:\\Program Files\\Blue Yonder\\Cliente\\cliente.exe"   # ruta real
espera_ui = 2.0

[credenciales]
servicio = "blueyonder"
usuario = "cuenta_servicio"   # el usuario con que entra el robot
```

---

## Paso 3 — Ajustar el código del login a los `auto_id` reales

Abre `src/capture_ui.py` y actualiza estas líneas con los `auto_id` que anotaste
en el Paso 1:

```python
# src/capture_ui.py  ->  funcion iniciar_sesion
ventana.child_window(auto_id="txtUsuario", control_type="Edit").set_text(usuario)
ventana.child_window(auto_id="txtPassword", control_type="Edit").set_text(password)
ventana.child_window(title="Aceptar", control_type="Button").click_input()
```

Y en `navegar_a_grilla` y `copiar_grilla`, ajusta el menú y el `auto_id` de la grilla:

```python
# src/capture_ui.py  ->  funcion navegar_a_grilla
ventana.menu_select("Consultas->Stock->Disponibilidad")   # el menú real

# src/capture_ui.py  ->  funcion copiar_grilla
grilla = ventana.child_window(auto_id="grdResultados", control_type="Table")
```

> Si el menú no responde a `menu_select`, se puede navegar con clics:
> `ventana.child_window(title="Consultas", control_type="MenuItem").click_input()`

---

## Paso 4 — Guardar las credenciales (una sola vez)

El robot **nunca** guarda la contraseña en texto plano. Se guarda cifrada en el
**Administrador de credenciales de Windows**:

```powershell
python -m src.set_credentials
# Servicio (ej: blueyonder): blueyonder
# Usuario: cuenta_servicio
# Contrasena: ********
```

Cuando el robot haga login, pedirá esa credencial al sistema operativo.

---

## Paso 5 — Probar la captura (sin enviar correo todavía)

Ejecuta solo la parte de captura y parseo:

```powershell
python tools\probar_captura.py
```

Este script:
1. Abre Blue Yonder, hace login y navega hasta la grilla.
2. Hace Ctrl+A / Ctrl+C.
3. Muestra cuántas filas leyó y las primeras 5.
4. Guarda el crudo en `data\raw_AAAA-MM-DD.tsv`.

Si imprime filas correctamente, **el login y la captura funcionan**. 🎉

Si algo falla, revisa la sección "Solución de problemas" al final.

---

## Paso 6 — Probar el pipeline completo (dashboard + correo)

```powershell
python -m src.main
```

Genera `output\reporte_AAAA-MM-DD.html` y lo envía por correo.

Para probar **sin enviar correo**:

```powershell
python -m src.main --sin-correo
```

Para probar con un TSV ya guardado (sin abrir la app):

```powershell
python -m src.main --desde-archivo data\raw_2026-09-23.tsv
```

---

## Paso 7 — Configurar el correo (Gmail corporativo / Google Workspace)

En `config.toml`:

```toml
[correo]
host = "smtp.gmail.com"
puerto = 587
seguridad = "starttls"
remitente = "reportes@tuempresa.com"
servicio_keyring = "smtp_reporte"
usuario_keyring = "reportes@tuempresa.com"
destinatarios = ["jefe@tuempresa.com", "operaciones@tuempresa.com"]
cc = []
```

### ⚠️ Importante: Gmail no acepta tu contraseña normal desde scripts

Google bloquea el login SMTP con la contraseña de la cuenta. Hay que generar una
**Contraseña de aplicación**:

1. Entra a **https://myaccount.google.com/security** con la cuenta corporativa.
2. Activa la **Verificación en dos pasos** (si no está activa).
3. Ve a **Contraseñas de aplicaciones** (Application passwords).
4. Crea una para "Correo" / "Otra (personalizado)". Google te da **16 caracteres**.
5. Ese valor es el que guardas como contraseña:

```powershell
python -m src.set_credentials
# Servicio: smtp_reporte
# Usuario:  reportes@tuempresa.com
# Contrasena: <los 16 caracteres de la contrasena de aplicacion>
```

> Si tu cuenta es **Google Workspace corporativo**, el administrador de TI puede
> tener **deshabilitadas** las contraseñas de aplicación. En ese caso hay dos
> alternativas:
> - Pedir al admin que habilite SMTP/App Passwords para esa cuenta.
> - Usar **OAuth2** (más complejo) o un **relay SMTP interno** de la empresa.

---

## Paso 8 — Programar la tarea diaria a las 10:00 am

1. Abre el **Programador de tareas** (Task Scheduler).
2. **Crear tarea básica**:
   - Nombre: `Reporte Diario Blue Yonder`
   - Desencadenador: **Diariamente**, hora **10:00**
   - Acción: **Iniciar un programa**
     - Programa: `C:\ruta\al\venv\Scripts\python.exe`
     - Argumentos: `-m src.main`
     - Iniciar en: `C:\ruta\al\proyecto`
3. En las propiedades de la tarea:
   - ✅ **Ejecutar aunque el usuario no haya iniciado sesión**
   - ✅ **Ejecutar con privilegios más altos**
   - En "Condiciones": ❌ desmarca "Detener si el equipo pasa a energía de batería"
4. Configura el PC para que **no entre en suspensión** (Configuración → Sistema →
   Energía). Si se suspende, la tarea no corre.

> Para probar el disparo sin esperar a las 10:00, haz clic derecho en la tarea →
> **Ejecutar**.

---

## Solución de problemas

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| `No hay credencial para servicio=...` | No guardaste la credencial | Repite el Paso 4 |
| `El portapapeles quedó vacío` | Ctrl+A/Ctrl+C no llegó a la grilla | Enfoca bien la grilla; revisa `auto_id` |
| La ventana de login no se encuentra | Título o `auto_id` distintos | Usa `inspeccionar_ui.py` para ver los reales |
| `SMTP AUTH extension not supported` | Servidor sin autenticación | Normalmente no aplica a Gmail |
| Error 535 de Gmail | Usaste la contraseña normal | Genera **Contraseña de aplicación** (Paso 7) |
| El robot no corre a las 10:00 | PC suspendido / tarea sin sesión | Ver Paso 8 |
| La app tarda en abrir | `espera_ui` muy corto | Sube `espera_ui` en `config.toml` |

---

## Orden recomendado para el primer día

1. Paso 1 (descubrir `auto_id`)
2. Paso 2 y 3 (configurar y ajustar el código)
3. Paso 4 (guardar credencial de Blue Yonder)
4. Paso 5 (probar captura) → **este es el momento clave**
5. Paso 7 (guardar credencial SMTP de Gmail)
6. Paso 6 (pipeline completo)
7. Paso 8 (programar la tarea)
