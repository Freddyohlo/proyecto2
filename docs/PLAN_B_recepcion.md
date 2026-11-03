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

Lo que sale **por sistema**:

```
lpn:       278043001201264701      (18 digitos)
sku:       700809
ubicacion: C16-01-01-01
cantidad:  198
almacen:   CD8000
```

Lo que **solo sale impreso en la tarja**:

```
fecha de elaboracion
fecha de vencimiento     <-- IMPRESCINDIBLE
```

### ⚠️ El vencimiento es crítico
Sin fecha de vencimiento, **FEFO no puede ordenar el lote**: no sabe si esa caja
debe salir antes o después que otra del mismo SKU. Por eso:

- Si se recibe **sin** vencimiento, el sistema lo **avisa** (`aviso_vencimiento`)
  y el registro queda marcado en el resumen como "sin vencimiento".
- No se inventa una fecha ni se deja pasar en silencio.

### Sobre el LPN
El LPN de la tarja (`278043001201264701`) **no coincide en formato** con ninguno
de los que vimos en la cuadratura:

| Origen | Formato | Ejemplo |
|---|---|---|
| Cuadratura — `LPN` | 14, alfanumérico | `CD800000000HNRN` |
| Cuadratura — `LPN de detalle` | 11, alfanumérico | `D0000007RPCI` |
| **Tarja** | **18, numérico** | `278043001201264701` |

**Decisión: se guarda tal cual viene.** No se intenta interpretar su estructura
(se probó la hipótesis del día juliano y no cierra). Adivinar el formato sería
peor que guardarlo crudo.

> **Pendiente de confirmar:** ¿a cuál de los dos LPN de la cuadratura corresponde
> el de la tarja? Es lo que permitiría cruzar la recepción con el stock capturado.

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

## 4. Uso

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
