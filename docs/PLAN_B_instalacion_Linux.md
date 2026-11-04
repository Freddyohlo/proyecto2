# Plan B — Cómo levantarlo en tu PC (Linux)

> Guía corta para dejar el sistema andando en el PC dedicado y probarlo desde
> un Zebra. El usuario tiene **Linux** en el PC, así que esta guía es para Linux.

---

## 1. Qué necesitas

- Un PC con **Linux** (el dedicado).
- **Python 3.11 o superior**.
- Estar en la **misma red** que los Zebra (por WiFi).
- Los archivos de datos del día:
  - La **cuadratura** (TSV, con Detalle activo).
  - Los **mín/máx** (TSV de "Operaciones de reabastecimiento") — opcional, solo
    si vas a usar el reapro.
  - La **venta** (CSV de TRUCK) — para generar el picking.

---

## 2. Instalación (una sola vez)

```bash
# 1) Copiar el proyecto al PC
git clone https://github.com/Freddyohlo/proyecto2.git
cd proyecto2
git checkout tools-inspeccion-detalle

# 2) Crear un entorno de Python (recomendado)
python3 -m venv .venv
source .venv/bin/activate

# 3) Instalar dependencias
pip install -r requirements.txt
```

> Si el PC no tiene internet, copia el proyecto en un pendrive y en el PC corre
> `pip install -r requirements.txt` con el pendrive de paquetes, o usa
> `pip download` en una máquina con internet.

---

## 3. Saber la IP del PC

```bash
hostname -I
```

Anota la IP (algo como `192.168.1.50`). Es la que van a abrir los Zebra.

**Recomendado:** ponerle IP fija a ese PC, para que no cambie y no haya que
reconfigurar los Zebra. Se hace en la configuración de red de Linux
(NetworkManager → IPv4 → Manual).

---

## 4. Cargar los datos del día

```bash
# a) El stock (cuadratura con Detalle)
python -m src.plan_b_main cargar --archivo data/cuadratura.tsv

# b) La venta (CSV de TRUCK)
python -m src.plan_b_main venta --archivo "data/venta.csv"

# c) Generar las tareas de picking (reserva el stock)
python -m src.plan_b_main picking

# d) (Opcional) Mín/máx, si vas a usar el reapro
python -m src.plan_b_main minmax --archivo data/reabastecimiento.tsv
```

Al final de `picking` te dice cuántas tareas generó y cuántas cajas reservó.

---

## 5. Levantar el servidor

```bash
python -m src.picking_servidor --puerto 8080
```

Deja esa ventana abierta. El servidor queda escuchando.

> **Ojo:** mientras esa ventana esté abierta, el servidor funciona. Si la
> cierras, se cae. Para que quede corriendo de fondo:
> ```bash
> nohup python -m src.picking_servidor --puerto 8080 > servidor.log 2>&1 &
> ```

---

## 6. Abrirlo desde el Zebra

En el navegador del Zebra (Chrome o Enterprise Browser), abrir:

```
http://<IP-del-PC>:8080/
```

Vas a ver el menú:

```
[ PICKEAR ]           -> el operario escanea y confirma
[ RECIBIR MERCADERÍA ] -> escanear la tarja (GS1)
[ REAPROVISIONAR ]    -> el supervisor ve qué está bajo el mínimo
[ VER ESTADO ]        -> resumen del día
[ GENERAR INFORMES ]  -> informe HTML y Excel
[ CERRAR EL DÍA ]     -> cierre total
```

**Usuarios:** `PICK1`..`PICK4` y `GRUA1`..`GRUA2`. PIN por defecto:
`PICK1`=1111, `PICK2`=2222, `PICK3`=3333, `PICK4`=4444, `GRUA1`=1111, `GRUA2`=2222.

---

## 7. Asignar los nombres de los operarios del día

Como los usuarios son fijos, el supervisor les pone el nombre del operario real:

```bash
python -m src.plan_b_main operarios --asignar PICK1 --nombre Juan
python -m src.plan_b_main operarios --asignar GRUA1 --nombre Carlos
```

Después, para ver la productividad del día:

```bash
python -m src.plan_b_main operarios --productividad
```

```
Productividad — picking:
  PICK1 — Juan              12 mov      480 cajas
  PICK2 — Pedro              9 mov      310 cajas
```

---

## 8. Cerrar el día

Al terminar la jornada, desde el menú (botón **CERRAR EL DÍA**) o por consola:

```bash
python -m src.plan_b_main informe-dia
```

Eso genera el informe y, si se hizo desde el botón, además libera lo no pickeado.

---

## 9. Problemas comunes

**"No puedo abrir la página desde el Zebra"**
- Verifica que el Zebra esté en la misma red WiFi.
- Prueba desde el propio PC: `curl http://localhost:8080/` (si no responde, el
  servidor no está corriendo).
- Revisa el firewall de Linux: puede estar bloqueando el puerto 8080.
  ```bash
  sudo ufw allow 8080/tcp
  ```

**"El escaneo no llena nada"**
- El lector debe estar configurado para mandar **ENTER** al final del código
  (es lo normal). Si no, hay que configurarlo en DataWedge.

**"Dice que el SKU no está en el stock"**
- Es normal si es producto que recién llega: usa el botón
  **"+ DAR DE ALTA ESTE SKU"**.

**"Se me cerró el servidor"**
- Levántalo de nuevo. Los datos NO se pierden: están en `data/plan_b.sqlite`.

---

## 10. Respaldo de los datos

Todo vive en **un solo archivo**: `data/plan_b.sqlite`.

```bash
cp data/plan_b.sqlite respaldo_$(date +%F).sqlite
```

Conviene copiarlo al final del día, o programarlo con `cron`.
