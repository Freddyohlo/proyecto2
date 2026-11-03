# Plan B — Uso de los terminales RF Zebra (Android) para pickear

> Análisis de arquitectura previo a implementar. Fecha: 2026-11-03.
> Pregunta del usuario: ¿podemos usar los TRF Zebra (Android) que hoy hacen el
> picking para pickear contra nuestro sistema de contingencia? ¿Conviene una APK?

---

## 1. Respuesta corta

**Sí, es viable, y es una buena idea.** Pero conviene separar dos cosas que se
confunden fácil:

| Capa | Pregunta | Respuesta |
|------|----------|-----------|
| **Dispositivo** | ¿Podemos usar los Zebra? | ✅ **Sí.** Son Android y traen DataWedge de fábrica. |
| **Sistema** | ¿Sirve el camino actual (RF contra Blue Yonder)? | ❌ **No.** Si BY está caído, su servidor RF también. |

O sea: durante la contingencia los Zebra son **hardware disponible sin servidor**.
La oportunidad es **apuntarlos a nuestro servidor** en vez del de BY.

**Y la recomendación importante: NO hace falta una APK.** Se resuelve con una
**aplicación web** (PWA) que corre en el navegador del propio Zebra. Explico por qué.

---

## 2. Lo que confirmé técnicamente

### 2.1 Los Zebra Android traen DataWedge de fábrica
Zebra incluye **DataWedge** en todos sus computadores móviles Android. DataWedge
captura el escaneo y lo entrega de dos formas:

- **Keystroke (HID)**: el código escaneado se escribe como si fuera un teclado en
  el campo que tenga el foco. **No requiere programar nada.**
- **Intent**: se envía a una app concreta. Útil con *Enterprise Browser* de Zebra.

→ **Consecuencia clave:** una **página web** en el navegador del Zebra recibe los
escaneos sin escribir una línea de Android. Solo hay que configurar DataWedge una
vez por dispositivo (perfil → keystroke habilitado).

### 2.2 El RF de Blue Yonder es MOCA sobre Telnet/SSH
El RF de BY no es una app nativa: son **pantallas MOCA** servidas por
Telnet/SSH, y el dispositivo corre un **emulador de terminal**.
Existen emuladores Android de terceros (ej. *Smart RF Plus*) que se conectan al
servidor MOCA/MTF por telnet.

→ **Consecuencia:** los Zebra actuales son **terminales tontos apuntando a BY**.
Cuando BY cae, no tienen a qué conectarse. **Ese es exactamente el hueco** que
nuestro Plan B puede llenar: darles un servidor propio.

### 2.3 BY tiene API REST… pero no la podemos usar
Existe la *Blue Yonder Warehouse Management API* (REST) para inventario y tareas.
**Pero** el acceso depende del contrato/versión del cliente, y el usuario ya
confirmó que **en esta instalación no hay API disponible** (se accede por UI
automation). Por lo tanto **no** es una base sobre la que construir la contingencia.

### 2.4 Sobre "Velocity"
No pude confirmar un producto de Blue Yonder llamado exactamente "Velocity".
Lo que sí existe y es el camino móvil de BY: **Orchestrator app**, **Warehouse
Operator App** y **WES (Warehouse Execution System)**.
→ **A confirmar con el usuario** qué es "la implementación por velocity" en su
empresa (¿el layer móvil de BY? ¿un partner? ¿un nombre interno?).

---

## 3. Arquitecturas posibles

### Opción 0 — Listas en papel (el más barato)
Generar PDF/Excel de picking desde el Plan B; el picker trabaja en papel; el
administrador digita el resultado.

- ✅ Cero infraestructura, cero riesgo técnico, funciona hoy.
- ❌ No hay validación de escaneo; errores de transcripción; lento.
- **Sirve como respaldo del respaldo.** Conviene implementarlo igual.

### Opción 1 — App web (PWA) en los Zebra actuales  ⭐ RECOMENDADA
El PC de contingencia levanta un **servidor web local** en la LAN de la bodega.
El picker abre el navegador del Zebra → nuestra pantalla de picking → DataWedge
mete los escaneos como teclado → todo se guarda en SQLite local.

- ✅ **No hay que escribir ni distribuir una APK.**
- ✅ Se actualiza sola (es web): se cambia en el PC y listo.
- ✅ Usa los dispositivos que ya están en la operación.
- ✅ Reutiliza el stack que ya tenemos (Python + SQLite + HTML).
- ❌ Depende de WiFi de la bodega hasta el PC (hay que asegurar cobertura).
- ❌ La UI debe ser "dedo grande": botones grandes, alto contraste, sin zoom.
- ❌ Configurar DataWedge una vez por dispositivo.

### Opción 2 — APK (Capacitor/Ionic + plugin DataWedge oficial)
Envolver la misma app web en una APK nativa, usando el plugin oficial de Ionic
para DataWedge.

- ✅ Se ve/instala como app "de verdad"; control total del escaneo por Intent.
- ✅ Puede guardar datos en el dispositivo (útil si el WiFi es malo).
- ❌ Hay que compilar, firmar y **distribuir** la APK en N dispositivos.
- ❌ Cada cambio = reinstalar en cada Zebra (o MDM).
- ❌ Más superficie de mantenimiento (Android SDK, versiones, fragmentación).
- **Solo vale la pena** si se necesita trabajar sin WiFi o desplegar por MDM.

### Opción 3 — Integrarse al RF real de BY
Usar el MOCA/REST de BY como corresponde.

- ✅ Es la solución "correcta" de largo plazo.
- ❌ **No sirve para contingencia**: requiere que BY esté arriba.

---

## 4. Recomendación

1. **Empezar por la Opción 1 (app web)** sobre los Zebra existentes.
   Es la que da el 90% del valor con el 10% del esfuerzo.
2. **Dejar la Opción 0 (papel)** implementada como respaldo por si el WiFi falla.
3. **No ir a APK** salvo que aparezca una necesidad concreta (offline en
   dispositivo o despliegue por MDM).

### Decisión de arquitectura de fondo: centralizado, NO en el dispositivo
El sistema debe ser **centralizado**: un solo servidor (el PC del administrador) y
los Zebra como **clientes**. 

**Por qué:** si cada Zebra guardara su propio stock (APK autocontenida), tendríamos
N estados de inventario divergentes y habría que sincronizarlos entre sí *y* con
BY. Eso es un problema mucho más difícil y riesgoso que la caída original. Un solo
origen de verdad evita ese infierno.

---

## 5. Riesgos y mitigaciones

### 5.1 Doble descuento al volver BY  ⚠️ EL MÁS GRAVE
Si se pickea offline y BY sigue creyendo que el stock está, al volver el sistema
alguien podría volver a pickear lo mismo → **doble picking / stock fantasma**.

**Mitigación:**
- Registrar **cada** movimiento offline con: SKU, ubicación, LPN/lote, cantidad,
  usuario, fecha-hora y pedido. Sin eso no se puede reproducir.
- Al volver BY: **congelar** los SKU/ubicaciones tocados, reingresar los
  movimientos y recién entonces liberar.
- Cuadrar contra un conteo físico de las ubicaciones afectadas antes de liberar.

### 5.2 Integridad FEFO
Offline podríamos elegir un lote que BY no habría elegido (BY puede tener
retenciones, reservas o bloqueos que nosotros no vemos).

**Mitigación:** capturar siempre LPN/lote en el pick y reingresar el lote exacto,
no "el que BY habría elegido".

### 5.3 Cobertura WiFi y disponibilidad del servidor
Los Zebra se mueven entre racks; el servidor es un solo PC.

**Mitigación:** verificar cobertura en los pasillos críticos, IP fija para el PC,
y **no** apagar/suspender ese PC (misma regla que el PC del reporte diario).

### 5.4 Configuración de dispositivos
Hay que configurar DataWedge en cada Zebra.

**Mitigación:** el perfil de DataWedge se puede exportar/importar como archivo de
configuración y desplegar en bloque (o por MDM si existe).

### 5.5 Seguridad e identidad
Cada pick debe quedar a nombre de una persona (para el reingreso y para el
informe de productividad).

**Mitigación:** login simple en la app (usuario/clave o **escaneo de credencial**
si los carnets tienen código de barras).

### 5.6 Política de IT
Instalar/configurar apps o usar el navegador en equipos corporativos puede chocar
con las reglas de TI.

**Mitigación:** validar con TI **antes** de construir. La Opción 1 (web) es la que
menos fricción tiene justamente por esto.

### 5.7 Dato faltante: los códigos de barra
Para escanear necesitamos que los códigos existan y sean legibles.

**A verificar:**
- ¿Las **ubicaciones** tienen etiqueta con código de barras? ¿Qué formato?
- ¿Los **SKU** tienen código de barras y coincide con `prtnum`?
- ¿Los **LPN** tienen código de barras (para FEFO/lote)?

---

## 6. Qué necesito confirmar antes de construir

- [ ] **Modelo exacto** de los Zebra (TC21 / TC52 / TC78 / otro) y versión de Android.
- [ ] ¿Tienen **navegador** (Chrome) disponible? ¿O solo Enterprise Browser?
- [ ] ¿Hay **WiFi** en los pasillos de picking y hasta dónde llega?
- [ ] ¿El PC de contingencia puede tener **IP fija** en esa red?
- [ ] ¿Qué es **"velocity"** exactamente en su operación?
- [ ] ¿TI permite una app web / APK en esos equipos?
- [ ] **Códigos de barras**: ¿ubicación, SKU y LPN los tienen? ¿formato?
- [ ] ¿Cuántos Zebra hay (para dimensionar la configuración)?

---

## 7. Plan de implementación propuesto (por pasos)

1. **Servidor local de picking** (Python, en el PC): sirve la UI web y guarda en
   SQLite. Reutiliza `inventario.py` y `contraste.py`.
2. **Pantalla de picking** (HTML táctil): escanear ubicación → escanear SKU/LPN →
   cantidad → confirmar. Sugerencia FEFO visible.
3. **Probar en UN Zebra** con DataWedge (keystroke) apuntando al PC.
4. **Lista de reingreso**: exportar los movimientos offline en un formato claro
   para reingresar a BY al volver.
5. **Respaldo en papel** (Opción 0) por si el WiFi falla.
6. (Opcional, futuro) envolver en APK solo si aparece la necesidad.

> El paso 1–2 se puede construir y probar **sin** los Zebra (navegador normal),
> igual que hicimos con el informe y el Plan B.

---

## 8. Fuentes consultadas

- Zebra — DataWedge (software de captura en dispositivos Android):
  https://www.zebra.com/us/en/software/mobile-computer-software/datawedge.html
- Ionic — plugin oficial Zebra DataWedge (para Capacitor/APK):
  https://ionic.io/docs/zebra-datawedge
- Smart RF Plus — emulador RF Android para BY (confirma que el RF es MOCA/telnet):
  https://www.smart-is.com/what-we-do/smart-product/rf
- Blue Yonder — movilidad y automatización:
  https://blueyonder.com/solutions/mobility-and-automation
- RFgen — riesgos de operar inventario offline (desincronización con el ERP):
  https://www.rfgen.com/blog/offline-inventory-management-in-warehouses
