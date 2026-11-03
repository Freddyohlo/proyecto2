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

## 4b. ✅ EL CÓDIGO DE BARRAS TRAE TODOS LOS DATOS (GS1-128)

**Confirmado por el usuario:** al escanear el código de barras de la tarja,
**los demás datos se llenan solos**.

La tarja usa **GS1-128**, el estándar mundial de logística. El código no trae solo
el LPN: trae **varios datos juntos**, cada uno marcado con un *Application
Identifier* (AI).

### Cómo viene el código

```
(00)278043001201264701  → el pallet (SSCC)
(17)270604              → vencimiento 04/06/2027
(11)261031              → elaboración 31/10/2026
(30)198                 → 198 cajas
```

El lector lo entrega como **un solo texto**; el sistema lo reparte solo.

### Los AIs que usamos

| AI | Qué es | En la tarja |
|---|---|---|
| `00` | SSCC (el pallet) | ✅ |
| `01` / `02` | GTIN (el producto) | si viene |
| `10` | Lote | si viene |
| `11` | Elaboración (YYMMDD) | ✅ |
| `13` | Empaque | si viene |
| `17` | **Vencimiento** (YYMMDD) | ✅ |
| `30` / `37` | Cantidad de cajas | ✅ |

### Reglas GS1 que hay que respetar

- **Fechas en `YYMMDD`**: `270604` = 04/06/2027. El año usa pivote: `YY < 70` → `20YY`.
- **Día `00` = último día del mes**: `270600` = 30/06/2027.
- **AIs variables** terminan en separador (FNC1). Muchos lectores **no lo mandan**,
  así que hay que cortar por el siguiente AI válido.

### ⚠️ Bug real encontrado al implementar
Al cortar los AIs variables sin separador, el valor `198` se partía en `1` + AI `98`
(los internos `90-99`), así que **la cantidad salía 1 en vez de 198**.
Corregido: los AIs internos `90-99` **no** se usan como corte.

### Resultado en pantalla

```
Antes:  escanear LPN + digitar SKU + cantidad + vencimiento + elaboración + ubicación
Ahora:  escanear la tarja  →  el sistema llena cantidad, vencimiento y elaboración
                             el operario solo pone SKU y ubicación
```

Con `recibir_y_ubicar()`, si la ubicación viene en la tarja, es **un solo toque**.

### Módulo
`src/gs1.py` — `parsear()` (tolera con/sin paréntesis, con/sin separador, y el
SSCC pelado de las tarjas viejas), `_fecha_gs1()`, `es_gs1()`.

### ✅ El SKU también viene dentro del código

**Confirmado por el usuario.** Como no se pudo obtener el texto crudo de un
escaneo, el sistema **descubre solo** cuál de los números es el SKU, sin adivinar
el formato:

1. **Ancla en el SSCC.** El SSCC se reconoce sin saber el formato del resto porque
   tiene **dígito de control**: se prueban ventanas de 18 dígitos y la que valida
   es el SSCC. Eso marca dónde empiezan los demás datos.
2. **Candidatos.** Se juntan los AIs típicos del código de producto (`240`, `241`,
   `90-99`) y los números que vienen después del SSCC.
3. **Desambiguación con el stock.** De todos los números, el que **existe en
   nuestra cuadratura** es el SKU. El catálogo de SKU es el que decide, no una
   suposición.

Si ningún candidato calza con el stock, se usa el más probable y **se avisa**
(`origen: "codigo"` + `aviso`), en vez de fallar en silencio.

### ⚠️ El código sin separadores es ambiguo
Muchos lectores no mandan el separador FNC1. En ese caso no se sabe dónde corta un
valor variable. En vez de tomar la primera lectura, el parser genera **todas las
interpretaciones posibles** y elige la de **mayor puntaje** (premia un SSCC válido,
fechas interpretables y cantidades razonables; castiga valores absurdos).

### Resultado final

```
Antes:  escanear LPN + digitar SKU + cantidad + vencimiento + elaboración + ubicación
Ahora:  UN escaneo  →  el sistema llena TODO  →  confirmar
```

> **Pendiente:** con el texto crudo de un escaneo real se puede fijar el AI exacto
> del SKU y dejar de usar la heurística. Mientras tanto, funciona y avisa cuando
> no está seguro.

---

## 5. Optimizaciones propuestas (para hacerlo práctico)

### ✅ Ya implementadas

**0. Leer el código GS1-128 (LA MÁS GRANDE)** ✅ *implementada*
El código de barras de la tarja trae cantidad, vencimiento y elaboración. El
sistema los lee y **llena los campos solo**. Es la diferencia entre 6 toques y 2.

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
