# Plan B — Cómo levantarlo en tu PC

> Guía corta para dejar el sistema andando y probarlo desde un Zebra.
> **Funciona igual en Windows y en Linux.**

---

## ¿Windows o Linux? — da lo mismo

Todo el sistema es **Python puro + SQLite**. No usa nada específico de un sistema
operativo:

| Parte | Requiere |
|---|---|
| Servidor web, pantallas, base de datos | **Python 3.11+** (da igual el SO) |
| Leer el sumario (PDF) | `pdfplumber` (da igual el SO) |
| Informes HTML/Excel | `jinja2`, `openpyxl` (da igual el SO) |
| **Capturar la grilla de Blue Yonder** | ⚠️ **Solo Windows** (pywinauto) |

**La única diferencia:** la **captura automática** de la grilla de Blue Yonder
necesita **Windows** (pywinauto maneja ventanas de Windows). Pero eso es un
**paso opcional**: si prefieres, copias la grilla con `Ctrl+A` / `Ctrl+C` a mano
y la guardas en un `.tsv` — funciona igual en cualquier sistema.

> **Recomendación concreta:** si el PC que va a correr esto **es el mismo donde
> está Blue Yonder**, usa **Windows** para aprovechar la captura automática. Si es
> un PC aparte, cualquiera de los dos sirve.

---

## 1. Instalar Python

### Windows
1. Bajar de **python.org/downloads** (versión 3.11 o superior).
2. En el instalador, marcar **"Add Python to PATH"** ← importante.
3. Verificar en la consola:
```cmd
python --version
```

### Linux
```bash
sudo apt install python3 python3-venv python3-pip
python3 --version
```

---

## 2. Bajar el proyecto

### Con git (recomendado, permite actualizar después)
```bash
git clone https://github.com/Freddyohlo/proyecto2.git
cd proyecto2
git checkout tools-inspeccion-detalle
```

### Sin git
Descargar el ZIP desde GitHub → **Code** → **Download ZIP**, descomprimir.

---

## 3. Instalar dependencias

### Windows
```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pdfplumber
```

### Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pdfplumber
```

> Si vas a usar la **captura automática** de Blue Yonder (solo Windows), además:
> ```cmd
> pip install pywinauto pyautogui
> ```

---

## 4. Saber la IP del PC

Los Zebra necesitan la IP del PC para conectarse.

### Windows
```cmd
ipconfig
```
Buscar **"Dirección IPv4"** (algo como `192.168.1.50`).

### Linux
```bash
hostname -I
```

**Recomendado:** ponerle **IP fija** a ese PC, para que no cambie y no haya que
reconfigurar los Zebra.
- Windows: Configuración → Red → Propiedades → IP manual
- Linux: NetworkManager → IPv4 → Manual

---

## 5. Cargar los datos del día

Abre la consola **en la carpeta del proyecto** (con el entorno activado):

```bash
# a) El stock (cuadratura con "Detalle" activo, guardada como .tsv)
python -m src.plan_b_main cargar --archivo "cuadratura.tsv"

# b) La venta (PDF del sumario de carga)
python -m src.plan_b_main sumario --archivo "SUMARIO CARGA.pdf"

# c) Generar las tareas de picking (reserva el stock y dice si falta algo)
python -m src.plan_b_main picking --desde-sumario
```

Al final te dice cuántas tareas generó y **si algún SKU no alcanza**.

---

## 6. Levantar el servidor

```bash
python -m src.picking_servidor --puerto 8080
```

**Deja esa ventana abierta.** Mientras esté abierta, el sistema funciona.

### Para que quede corriendo de fondo

**Windows** (abrir otra consola y ejecutar):
```cmd
start /b python -m src.picking_servidor --puerto 8080 > servidor.log 2>&1
```

**Linux:**
```bash
nohup python -m src.picking_servidor --puerto 8080 > servidor.log 2>&1 &
```

---

## 7. Abrirlo desde el Zebra

En el navegador del Zebra (Chrome o Enterprise Browser):

```
http://<IP-del-PC>:8080/
```

Vas a ver el menú:

```
OPERACIÓN
  Consulta de stock      -> buscar un código: cuánto hay y dónde
  Cuadratura de stock    -> foto real: libre vs comprometido
  Picking                -> el operario escanea y confirma
  Recepción de mercadería-> escanear la tarja (GS1)
  Reaprovisionamiento    -> qué está bajo el mínimo
  Grúa                   -> tareas de bajada
  Pallet de armado       -> el pallet completo con sus SKU
  Contraste volante      -> verificar el volante contra el sumario

SISTEMA
  Estado del stock
  Operaciones de sistema — cola de trabajos

ADMINISTRACIÓN
  Cerrar el día
  Operarios
```

**Usuarios y PIN por defecto:** `PICK1`=1111, `PICK2`=2222, `PICK3`=3333,
`PICK4`=4444, `GRUA1`=1111, `GRUA2`=2222.

---

## 8. Asignar los nombres de los operarios del día

Desde la pantalla **Operarios** (o por consola):

```bash
python -m src.plan_b_main operarios --asignar PICK1 --nombre Juan
python -m src.plan_b_main operarios --asignar GRUA1 --nombre Carlos
```

Para ver la productividad:

```bash
python -m src.plan_b_main operarios --productividad
```

---

## 9. El corte de las 19:00

Desde la pantalla **Cuadratura de stock** → botón **"Guardar corte del día"**.

O por consola:
```bash
python -m src.plan_b_main cuadratura --guardar --nota "Corte 19:00"
```

Deja guardada la foto del día para comparar después.

---

## 10. Cerrar el día

Desde el menú, botón **CERRAR EL DÍA**. Libera lo que no se pickeó y genera el
informe de cierre.

---

## Problemas comunes

### "No puedo abrir la página desde el Zebra"

**1. ¿El servidor está corriendo?** Desde el propio PC:
```
http://localhost:8080/
```
Si tampoco abre ahí, el servidor no está levantado.

**2. ¿Están en la misma red?** El Zebra y el PC deben estar en el mismo WiFi.

**3. Firewall.** Es lo más habitual.

**Windows** — permitir el puerto (ejecutar como administrador):
```cmd
netsh advfirewall firewall add rule name="Plan B WMS" dir=in action=allow protocol=TCP localport=8080
```

**Linux:**
```bash
sudo ufw allow 8080/tcp
```

### "El escaneo no llena nada"
El lector debe mandar **ENTER** al final del código. Se configura en **DataWedge**
(la app de Zebra).

### "Dice que el SKU no está en el stock"
Es normal si el producto recién llega: usa el botón **"+ DAR DE ALTA ESTE SKU"**
en la pantalla de recepción.

### "Se cerró el servidor"
Levántalo de nuevo. **Los datos NO se pierden**: están en `data/plan_b.sqlite`.

---

## Respaldo de los datos

Todo vive en **un solo archivo**: `data/plan_b.sqlite`.

### Windows
```cmd
copy data\plan_b.sqlite respaldo_2026-11-16.sqlite
```

### Linux
```bash
cp data/plan_b.sqlite respaldo_$(date +%F).sqlite
```

Conviene copiarlo al final del día.

---

## Resumen: qué instalar según tu caso

| Caso | Sistema | Necesitas |
|---|---|---|
| PC aparte (solo servidor) | **Windows o Linux** | Python + dependencias. Nada más. |
| El mismo PC de Blue Yonder | **Windows** | Además `pywinauto` para capturar la grilla solo |
| Quieres capturar a mano | Cualquiera | Copias Ctrl+A/Ctrl+C y guardas el .tsv |
