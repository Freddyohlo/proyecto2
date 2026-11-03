# Plan B — Recepción de mercadería

> Estado: 2026-11-03. Primer acercamiento con la tarja real.

---

## 1. Los dos momentos

Igual que en picking, recepción tiene **dos pasos**:

```
   1. RECIBIR                       2. UBICAR
   ────────────                     ─────────
   Llega el camion.                 Se lleva a su ubicacion
   Se escanea el LPN de la tarja.   definitiva.
        │                                │
   Entra al stock vivo              Sale de RECEPCION y entra
   con area RECEPCION.              a AREA ALMACENAMIENTO,
   Disponible para ubicar.          con LOTE y VENCIMIENTO.
                                         │
                                    Ya es candidata para
                                    reaprovisionamiento.
```

**Por qué separarlos:** entre que llega el camión y que alguien lo ubica puede
pasar tiempo. Si no se registra la recepción, esa mercadería "no existe" para el
sistema — y justamente en contingencia es cuando más importa saber qué llegó.

---

## 2. Datos de la tarja (real, aportada por el usuario)

Imagen: `IMG_20261103_045905.jpg` (leída por OCR). Contenido completo:

```
278043001201264701                          <- SSCC / LPN (codigo de barras)
BlueYonder  ·  CCU  ·  Transportes CCU Limitada

DESCRIPCION DEL PRODUCTO:  GATO DULCE-DC-VNR1500CCX8-TR
CODIGO DE PRODUCTO:        700809
FECHA DE ELABORACION:      31.10.2026 08:10
FECHA DE VENCIMIENTO:      04.06.2027
CAJAS REALES:              198
CAJAS / PALLET:            60
PERFIL DE ANTIGUEDAD:      999
SSCC:                      278043001201264701
USUARIO IMPRESION:         RESIDENTE-STG
```

### 🔑 Hallazgo 1: el LPN de la tarja es un SSCC estándar GS1

El "LPN" de la tarja **no es un número inventado**: es un **SSCC** (Serial Shipping
Container Code), el estándar GS1 para identificar bultos/pallets.

```
278043001201264701
├── 2            digito de extension
├── 7804300120126470   prefijo GS1 + serie
└── 1            digito de control (modulo 10)
```

**El dígito de control valida.** Eso permite:
- **Detectar escaneos malos** automáticamente (si no cuadra, la lectura vino mal).
- Saber que el LPN es **único por pallet**, no un código interno de bodega.

> El sistema lo valida y **avisa** si no cuadra, pero **no bloquea**: un dígito
> raro no debe impedir recibir mercadería que está físicamente en el andén.

### 🔑 Hallazgo 2: la tarja imprime las fechas con PUNTOS

`31.10.2026` y `04.06.2027` — con **puntos**, no barras.

**Esto era un bug real:** el normalizador solo aceptaba barras y guiones, así que
la fecha se descartaba **en silencio** → el lote entraba **sin vencimiento** →
**FEFO quedaba ciego**. Corregido y con test.

### 🔑 Hallazgo 3: CAJAS REALES vs CAJAS/PALLET

La tarja trae dos cantidades distintas:
- **CAJAS REALES: 198** ← lo que realmente trae el pallet
- **CAJAS / PALLET: 60** ← el estándar por pallet completo

`198 / 60 = 3.3 pallets` (3 completos de 60 + 18 sueltas). Sirve para **validar**
que el pallet venga completo y para saber cuántos pallets llegaron.

### Sobre el LPN (aclarado por el usuario)
> El LPN de la tarja corresponde al **pallet hasta que llega al picking**. El
> picking tiene **LPN propio**: cuando el pallet llega al picking, **cambia** el LPN.

O sea: **el LPN es la identidad del bulto en cada tramo**, no del producto. Por eso
no calzaba con los LPN de la cuadratura: son de etapas distintas del flujo.

### ⚠️ El vencimiento es crítico
Sin fecha de vencimiento, **FEFO no puede ordenar el lote**. Por eso:

- Si se recibe **sin** vencimiento, el sistema lo **avisa** y lo marca en el resumen.
- No se inventa una fecha ni se deja pasar en silencio.

### ✅ No se valida contra el tránsito de SAP
Criterio del usuario, y es correcto: **si la mercadería está llegando, es porque
llega**. El sistema **recibe sin bloquear** y después se cuadra contra SAP. Validar
contra el tránsito convertiría una ayuda en un obstáculo justo en contingencia.

---

## 3. Reglas implementadas

| Regla | Por qué |
|---|---|
| **Idempotente por LPN** | Si el operario escanea la tarja dos veces, NO se duplica el ingreso (devuelve el registro existente, código 409). |
| **Suma si ya existe** | Si se recibe el mismo LPN+SKU+ubicación de nuevo, se acumula en la fila en vez de crear otra. |
| **Conserva lote y vencimiento** | Al ubicar, el LPN y el vencimiento viajan con la mercadería. Sin eso FEFO queda ciego. |
| **Avisa si falta el vencimiento** | No se inventa: se marca para corregir después. |
| **No se puede ubicar dos veces** | La segunda vez se rechaza (ya está en estado `ubicado`). |
| **Sugerencia de ubicación** | 1) donde ya se guarda ese SKU (no dispersar); 2) donde haya capacidad libre. |

---

## 5. Optimizaciones propuestas (para hacerlo práctico)

### ✅ Ya implementadas

**1. Recibir + ubicar en un solo paso**
La tarja ya trae la ubicación (`C16-01-01-01`). Hacer que el operario confirme dos
veces es trabajo de más. Con `recibir_y_ubicar()` (botón "RECIBIR Y UBICAR") se
hace en **un toque**. Sigue existiendo el flujo de dos pasos para cuando no se sepa
la ubicación todavía.

**2. Validar el SSCC en vez de solo guardarlo**
Detecta escaneos malos al instante. Aviso, no bloqueo.

**3. Precargar el SKU desde el tránsito de SAP** (sugerencia, no validación)
Cuando se escanea el LPN, si ese SKU aparece en el tránsito de SAP, el sistema
puede **rellenar el SKU solo**. Ahorra digitación sin bloquear nada. *(A evaluar:
depende de que el LPN de la tarja esté en el tránsito, que probablemente no.)*

**4. Aceptar las fechas como vienen (con puntos)**
Menos correcciones a mano, y sin riesgo de perder el vencimiento.

### 💡 Propuestas a evaluar

**5. Recepción sin teclado: solo escanear**
Hoy hay que digitar SKU, cantidad, fechas y ubicación. Si la tarja tuviera **un
código de barras con todos los datos** (tipo GS1-128 con AI), se escanearía **una
vez** y el sistema llenaría todo. Vale la pena preguntar a CCU si la tarja puede
llevar ese código: es la optimización más grande que veo.

**6. Etiqueta de ubicación sugerida al ubicar**
Cuando el sistema sugiere dónde poner un SKU, imprimir/mostrar la etiqueta de esa
ubicación. Evita que el operario la escriba mal.

**7. Cierre de turno en un toque**
Un botón "cerrar recepción del día" que exporte el resumen (recibidos, ubicados,
pendientes, sin vencimiento). Hoy ya está el comando, pero falta el botón.

**8. Detectar pallet incompleto automáticamente**
Con `CAJAS REALES` vs `CAJAS/PALLET` se puede avisar si el pallet llegó incompleto
(ej. 198 de 240 esperadas). Hoy se guarda el dato; falta la alerta.

**9. Un solo servidor, dos pantallas, un menú**
Hoy `/` es picking y `/recepcion` es recepción. Conviene una **portada** que
pregunte "¿Qué vas a hacer?" (Pickear / Recibir / Ubicar) — más simple para el
operario, que no debería tener que recordar URLs.

---

## 6. Uso

### Línea de comandos
```bash
# Paso 1: recibir
python -m src.plan_b_main recepcion --recibir \
    --lpn 278043001201264701 --sku 700809 --cantidad 198 \
    --elaboracion 05/10/2026 --vencimiento 05/10/2027 \
    --ubicacion C16-01-01-01 --almacen CD8000 --usuario RECEPTOR

# Sugerir donde ponerlo
python -m src.plan_b_main recepcion --sugerir 700809

# Paso 2: ubicar
python -m src.plan_b_main recepcion --ubicar 1 --destino C16-02-03-04

# Estado
python -m src.plan_b_main recepcion
```

### Pantalla para el Zebra
```
http://<IP-del-PC>:8080/recepcion
```

Flujo en pantalla: escanear LPN → completar SKU, cantidad, elaboración y
vencimiento → RECIBIR → la mercadería aparece en "Pendientes de ubicar" →
tocar la fila → escribir destino → UBICAR.

---

## 5. Módulos

- `src/recepcion.py` — `recibir()`, `ubicar()`, `sugerir_ubicacion()`,
  `pendientes()`, `resumen()`, `normalizar_fecha()`. Tablas `recepcion` y
  `ubicaciones`.
- `src/stock_vivo.py` — se agregó `ingresar()` (suma si ya existe la fila) y las
  áreas `RECEPCION` / `AREA_ALMACENAMIENTO`.
- `src/picking_servidor.py` — endpoints `/recepcion` y `/api/recepcion/*`.
- `src/plan_b_main.py` — comando `recepcion`.

---

## 6. Pendiente

- [ ] **Confirmar a qué LPN de la cuadratura corresponde el de la tarja** (el
      `LPN` o el `LPN de detalle`).
- [ ] Confirmar si el vencimiento impreso es **fecha fija** o **días de vida útil**.
- [ ] Definir el flujo físico: ¿dónde se recibe? ¿andén → conteo → ubicación?
- [ ] ¿Quién decide la ubicación final: el operador o una sugerencia del sistema?
- [ ] ¿La cantidad de la tarja se valida contra lo que viene en el tránsito de SAP?
      (hay `OCA` en SAP y la tarja no la trae — ¿se cruzan por otro lado?)
- [ ] Capturar las áreas de recepción de Blue Yonder: `EXPR Expected Receipts`,
      `ANDEN DE RECEPCION`, `AREA STAGE RECEPCION`, `WIP Expected Receipts`.
