# Plan B — Terminales RF Zebra (Android) para pickear

> Análisis de arquitectura. Fecha: 2026-11-03 (revisado con datos reales del cliente).
> Pregunta: ¿podemos usar los TRF Zebra que hoy hacen el picking para pickear
> contra nuestro sistema de contingencia?

---

## 3. Correcciones importantes (datos aportados por el usuario)

| Supuesto mío | Realidad | Impacto |
|---|---|---|
| "Cuando cae el sistema quedamos offline" | **NO.** La caída del WMS es **independiente del WiFi**. Hay puntos de acceso cada pocos metros. | ✅ **Simplifica todo**: no hace falta trabajar sin red ni guardar datos en el dispositivo. |
| "Velocity es un producto de Blue Yonder" | **NO.** Velocity es el **emulador de terminal (telnet) de Wavelink/Ivanti**. | Cambia la arquitectura: es la capa que habla con BY, y **se le puede cambiar el host**. |
| "Hay que escanear SKU y LPN al pickear" | **NO.** El QR del rack trae **solo la ubicación**, y la **ubicación de picking es única por SKU**. | 🔑 **El escaneo ya identifica el producto.** No se escanea SKU al pickear. |
| "Los productos tienen código de barras, habrá que escanearlos" | Sí tienen, pero **se escanean solo en RECEPCIÓN** (ahí está la tarja con cantidad y LPN). | El flujo de picking queda más simple. |

### Flujo de picking real (confirmado)
```
   El sistema DIRIGE:  "ve a la ubicacion C01-01-01-01, saca N cajas"
        │
   El picker va y ESCANEA EL QR DEL RACK  (el QR trae solo la ubicacion)
        │
   El sistema VERIFICA que sea la ubicacion correcta  ✅ / ❌
        │
   Si coincide, el sistema deja DIGITAR LA CANTIDAD
        │
   Confirma el pick  (si saca menos, el resto se re-encola)
```
**No se escanea el SKU**: como la ubicación de picking es única por SKU, escanear la
ubicación ya identifica el producto. El escaneo sirve para **verificar que el picker
está parado en el lugar correcto**, no para elegir el producto.

**Cantidad**: la digita el picker. Si saca menos de lo pedido, la tarea queda
`parcial` y **lo que falta se re-encola** como tarea nueva (no se pierde).

### Equipos confirmados
- **Zebra MC3400** → Android 13 / 14.
- **Zebra MC330L** (familia MC3300x) → Android 10 / 11 / 13 / 14.
- Ambos con **Chrome** y **Enterprise Browser**.
- El QR del rack **se lee con el láser** del Zebra.
- **No se involucra a TI**: es un proyecto de los operadores WMS.
- Hay un **PC dedicado** al proyecto → se le puede poner **IP fija**. ✅

---

## 1. Cómo funciona hoy (y por qué se cae)

```
   [Blue Yonder ARRIBA]                       [Blue Yonder CAÍDO]
        │                                            │
   Zebra (Velocity, telnet) ──► servidor BY     Zebra (Velocity) ──► ¿? nada
        │                                            │
   WiFi: OK (independiente)                    WiFi: SIGUE OK ✅
```

**La clave:** el WiFi sigue funcionando. Lo que muere es el **servidor de BY**.
Los Zebra quedan encendidos, conectados y con navegador — **sin servidor**.

→ **La oportunidad:** darles **nuestro servidor** durante la caída.

---

## 2. Dos arquitecturas viables

### Opción A — App WEB en Chrome / Enterprise Browser  ⭐ RECOMENDADA

El PC de contingencia levanta un servidor web en la LAN. El picker abre el
navegador del Zebra (que ya tiene WiFi) → el sistema le dice a qué ubicación ir →
escanea el QR del rack (verificación) → confirma.

```
   [PC contingencia: servidor web + SQLite]  ◄── WiFi ──  [Zebra: Chrome/EB]
                    │
        genera tareas (FEFO)  ──►  "ve a X, saca N cajas"
```

- ✅ **No hay que escribir ni distribuir una APK.** Es HTML/JS.
- ✅ Se actualiza sola: se cambia en el PC y listo.
- ✅ Reutiliza el stack que ya tenemos (Python + SQLite + HTML).
- ✅ Con **Enterprise Browser** se puede usar su **API nativa de escaneo**
  (`EB.Barcode`) en vez del teclado — más robusto. Con Chrome, DataWedge keystroke.
- ✅ UI táctil moderna y controlada por nosotros.
- ❌ El picker aprende un flujo nuevo (pero es simple: 3 pasos).

### Opción B — Apuntar **Velocity** a NUESTRO servidor telnet  🎯 SIN REENTRENAMIENTO

Velocity es un emulador telnet: se le configura **IP + puerto + tipo de emulación**.
Se puede crear un **perfil de host alterno** que apunte a **nuestro PC** y servir
pantallas tipo RF (VT220) desde ahí.

- ✅ **Los pickers usan la MISMA app de siempre.** Cero reentrenamiento.
- ✅ Mismo "look and feel" de terminal al que están acostumbrados.
- ✅ No hay que instalar nada en los Zebra.
- ❌ Hay que **programar un servidor telnet** que dibuje pantallas VT220
  (escape sequences, teclas de función) — más trabajo y más frágil que web.
- ❌ La UX es de terminal (texto), no táctil.
- ❌ Cambiar el perfil de host requiere despliegue por IT (Avalanche/MDM).

### Opción C — Listas en papel (respaldo del respaldo)
Generar PDF/Excel de picking desde el Plan B; el picker trabaja en papel.

- ✅ Cero infraestructura, funciona siempre.
- ❌ Sin validación de escaneo; errores de transcripción; lento.
- **Conviene tenerlo igual**, por si el PC de contingencia se cae.

---

## 3. Recomendación

**Primaria: Opción A (app web).** Es la que da el 90% del valor con el 10% del
esfuerzo, y ya está prototipada y probada.

**Respaldo: Opción C (papel)** para el peor caso.

**Opción B (telnet) queda como carta fuerte a evaluar** si la adopción de los
pickers es un problema: es la única que **no les cambia nada**. Vale la pena
prototiparla barato para medir el esfuerzo real.

> **Sugerencia:** implementar A primero (rápido, visible), y en paralelo evaluar B
> con un prototipo mínimo. Si B sale simple, es la mejor experiencia para el
> operario; si no, A ya está resuelto.

### Decisión de fondo: CENTRALIZADO, nunca en el dispositivo
Un solo servidor (el PC de contingencia), los Zebra como clientes.
Si cada Zebra guardara su propio stock, tendríamos N inventarios divergentes que
sincronizar entre sí *y* con BY. Eso es peor que la caída original.

---

## 4. Riesgos y mitigaciones

### 4.1 Doble descuento al volver BY  ⚠️ EL MÁS GRAVE
Si se pickea offline y BY sigue creyendo que el stock está, al volver el sistema
alguien podría volver a pickear lo mismo → **stock fantasma**.

**Mitigación:**
- Registrar **cada** movimiento con SKU, ubicación, LPN/lote, cantidad, usuario y
  fecha-hora. Sin eso no se puede reingresar.
- Al volver BY: **congelar** los SKU/ubicaciones tocados, reingresar los
  movimientos y recién entonces liberar.
- Cuadrar contra conteo físico de las ubicaciones afectadas antes de liberar.

### 4.2 Integridad FEFO
Offline podríamos elegir un lote que BY no habría elegido (retenciones, reservas,
bloqueos que no vemos).

**Mitigación:** capturar siempre LPN/lote en el pick y reingresar el lote exacto.

### 4.3 Dependencia del PC de contingencia
Ahora todo depende de **una sola máquina**.

**Mitigación:** IP fija, sin suspensión, respaldo del SQLite, y Opción C (papel)
como red de seguridad.

### 4.4 El formato del QR de ubicación  ✅ RESUELTO
El usuario confirmó que el QR **trae solo la ubicación** y se lee con el láser.
Igual, el parser (`parsear_ubicacion`) tolera variantes por si el formato cambia:
código pelado, `LOC:`/`UBIC:`, URL con `?loc=`, y `valor|campo`.

### 4.5 Política de IT  ✅ DESCARTADO
El usuario indicó que **no se involucra a TI**: es un proyecto de los operadores WMS.
Eso quita el bloqueo, aunque conviene dejar el sistema lo menos invasivo posible
(una URL en el navegador, sin instalar nada) para que siga siendo así.

### 4.6 Nuevo riesgo: SKU en varias ubicaciones
El modelo asume **una ubicación de picking por SKU**. Si un SKU tuviera picking en
varias ubicaciones, "escanear la ubicación" ya no identificaría el producto.

**Mitigación:** el generador de tareas (`picking.py`) **no asume** una sola: recorre
los lotes ordenados por FEFO y genera una tarea por cada ubicación/lote que toque.
Si aparece el caso, ya está cubierto.

---

## 5. Qué falta confirmar

- [ ] ¿Los pickeadores están acostumbrados a escanear el rack, o a escribir la ubicación?
- [ ] ¿El PC de contingencia puede tener IP fija en la red de la bodega?
- [ ] ¿Hay algún MDM (Avalanche) para desplegar el perfil de Velocity (Opción B)?
- [ ] ¿Cuántos Zebra hay en total (MC3400 / MC330L)?
- [ ] ¿Se quiere imprimir/exportar la lista de tareas además de verla en el Zebra?

---

## 6. Plan de implementación

1. **Servidor local de picking** (Python en el PC): sirve la UI y guarda en SQLite.
   ✅ *Prototipo hecho* (`src/picking_servidor.py`).
2. **Ajustar al QR real**: parsear el código de ubicación como venga.
3. **Probar en UN Zebra** (Chrome y Enterprise Browser) apuntando al PC.
4. **Lista de reingreso** para devolver los movimientos a BY al volver.
5. **Respaldo en papel** (Opción C).
6. **Evaluar Opción B** (telnet/Velocity) con un prototipo mínimo.

> Los pasos 1–2 se prueban **sin** los Zebra (navegador normal), igual que hicimos
> con el informe y el Plan B.

---

## 7. Fuentes

- Wavelink/Ivanti **Velocity** — emulador de terminal (telnet) para Android,
  se configura con **IP + puerto + tipo de emulación** (host profile):
  https://help.ivanti.com/wl/help/en_us/velcon/1.2/admin/configuringhostprofiles.htm
- Zebra **Enterprise Browser** — soporte por dispositivo (incluye MC3400 Android 13/14):
  https://www.zebra.com/us/en/support-downloads/software/mobile-computer-software/enterprise-browser.html
- Zebra **DataWedge** — captura de escaneo (keystroke/intent) en Android:
  https://www.zebra.com/us/en/software/mobile-computer-software/datawedge.html
- Smart RF Plus — emulador RF Android para BY (confirma que el RF es MOCA/telnet):
  https://www.smart-is.com/what-we-do/smart-product/rf
- RFgen — riesgos de operar inventario offline (desincronización con el ERP):
  https://www.rfgen.com/blog/offline-inventory-management-in-warehouses
