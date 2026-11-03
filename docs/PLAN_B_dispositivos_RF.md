# Plan B — Terminales RF Zebra (Android) para pickear

> Análisis de arquitectura. Fecha: 2026-11-03 (revisado con datos reales del cliente).
> Pregunta: ¿podemos usar los TRF Zebra que hoy hacen el picking para pickear
> contra nuestro sistema de contingencia?

---

## 0. Correcciones importantes (datos aportados por el usuario)

Tres supuestos míos estaban **mal** y cambian la recomendación:

| Supuesto mío | Realidad | Impacto |
|---|---|---|
| "Cuando cae el sistema quedamos offline" | **NO.** La caída del WMS es **independiente del WiFi**. Hay puntos de acceso cada pocos metros. | ✅ **Simplifica todo**: no hace falta trabajar sin red ni guardar datos en el dispositivo. |
| "Velocity es un producto de Blue Yonder" | **NO.** Velocity es el **emulador de terminal (telnet) de Wavelink/Ivanti**. | Cambia la arquitectura: es la capa que habla con BY, y **se le puede cambiar el host**. |
| "Habría que ver si tienen navegador" | **Sí tienen**: Chrome **y** Enterprise Browser. | Habilita la app web sin fricción. |

### Equipos confirmados
- **Zebra MC3400** → Android 13 / 14.
- **Zebra MC330L** (familia MC3300x) → Android 10 / 11 / 13 / 14.
- Ambos soportan **Chrome** y **Enterprise Browser** (navegador industrial de Zebra,
  HTML5 + API nativa de escaneo).
- Ambos corren **Velocity** (emulador telnet) con un menú + login para pickear.

### Los racks tienen **código QR con la ubicación**
Es lo que los pickeadores pistolean para ubicarse. → El escaneo de ubicación ya
existe en la operación; nuestro sistema solo tiene que **leer ese mismo QR**.

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
navegador del Zebra (que ya tiene WiFi) → nuestra pantalla → escanea el QR de la
ubicación → escanea SKU/LPN → confirma.

```
   [PC contingencia: servidor web + SQLite]  ◄── WiFi ──  [Zebra: Chrome/EB]
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

### 4.4 El formato del QR de ubicación  ❓ A CONFIRMAR
Hay que saber **qué contiene** el QR de los racks:
- ¿El código pelado (`60-001`)?
- ¿Con prefijo (`LOC:60-001`)?
- ¿Una URL o JSON?

**Mitigación:** el parser de ubicación debe ser tolerante (ver `picking_servidor.py`).

### 4.5 Política de IT
Instalar apps o cambiar perfiles en equipos corporativos puede chocar con TI.

**Mitigación:** validar con TI antes de construir. La Opción A es la de menor
fricción (no instala nada: es una URL).

---

## 5. Qué falta confirmar

- [ ] **¿Qué contiene el QR** de la ubicación? (formato exacto)
- [ ] ¿El QR del rack se puede leer con la cámara o con el láser del Zebra?
- [ ] ¿El SKU y el LPN **tienen código de barras**? ¿formato?
- [ ] ¿TI permite una URL/app web en esos equipos?
- [ ] ¿Cuántos Zebra hay en total (MC3400 / MC330L)?
- [ ] ¿Los pickeadores están acostumbrados a escanear SKU, o eligen de una lista?
- [ ] ¿El PC de contingencia puede tener IP fija en la red de la bodega?
- [ ] ¿Hay algún MDM (Avalanche) para desplegar el perfil de Velocity (Opción B)?

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
