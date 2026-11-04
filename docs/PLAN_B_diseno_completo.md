# Plan B — Diseño completo (documento maestro)

> Sistema de contingencia offline para Blue Yonder (WMS de escritorio).
> Cuando el WMS se cae, la operación sigue funcionando con datos capturados
> previamente y archivos externos.

---

## 1. El problema

Cuando Blue Yonder se cae, la bodega se detiene: no hay stock visible, no hay
picking, no hay recepción. Este sistema replica la operación **offline**.

## 2. Las 5 fuentes de datos

| # | Fuente | Qué aporta | Origen | Estado |
|---|--------|-----------|--------|--------|
| 1 | **Cuadratura de Stock** (con "Detalle") | Stock real por ubicación + lote + vencimiento (FEFO) | Blue Yonder | ✅ captura funcionando |
| 2 | **Operaciones de reabastecimiento** | Mínimo y máximo por ubicación | Blue Yonder | ✅ columnas mapeadas |
| 3 | **Mantenimiento de ubicaciones** | Capacidad máx/usada/pendiente, tipo, zona, recogible, reabastecimiento | Blue Yonder | 🟡 pantalla encontrada, copiado en ajuste |
| 4 | **TRUCK** (programa externo) | La **VENTA** = demanda = qué se necesita | Externo (TRUCK) | ⏳ falta archivo de ejemplo |
| 5 | **Mercadería en tránsito** (con **nº de OCA**) | Lo que viene en camino (OC de compra) | **SAP** | ⏳ falta archivo de ejemplo |

> ⚠️ **Importante:** las fuentes 4 y 5 son **EXTERNAS** (no se capturan de Blue Yonder).
> La mercadería en tránsito viene de **SAP**, con el **número de OCA** (orden de compra).

### Rutas de menú en Blue Yonder (confirmadas)
- Cuadratura: `Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock`
- Mín/máx:   `Aplicaciones > Reabastecimiento > Operaciones de reabastecimiento`
- Ubicaciones:`Aplicaciones > Configuración del sistema > Instalación > Mantenimiento de ubicaciones`
- Áreas de recepción (para capturar): `EXPR Expected Receipts`, `ANDEN DE RECEPCION`,
  `AREA STAGE RECEPCION`, `WIP Expected Receipts`, `WEXP Production Expected Receipts`

---

## 3. Los 5 procesos

```
   ┌─────────────┐
   │   TRUCK     │  la VENTA (demanda)
   └──────┬──────┘
          │  ¿alcanza el stock?
          ▼
   ┌─────────────┐     ┌──────────────────┐
   │  CONTRASTE  │◄────│  STOCK (cuadratura)│
   │ venta/stock │     └──────────────────┘
   └──────┬──────┘
          │
          ├──► [PICKING FEFO] ─────────────► cajas pickeadas
          │         │
          │         │ se agota la ubicación
          │         ▼
          ├──► [REAPROVISIONAMIENTO] ──────► reponer hasta máximo
          │         (usa mín/máx + capacidad)
          │
          └──► ¿falta stock total?
                    │
                    ▼
              [RECEPCIÓN] ◄──── en tránsito (llega el camión)
                    │
                    ├──► registrar cantidad, lote, vencimiento
                    ├──► [UBICAR] usar capacidad disponible
                    └──► actualizar stock ──► vuelve a estar disponible para picking
```

### 3.1 Contraste Venta vs Stock
Compara lo que **necesita** (TRUCK) contra lo que **hay** (cuadratura) para saber si
se puede abastecer. Detecta quiebres antes de que ocurran.

### 3.2 Picking FEFO
- Criterio: primero lo que vence antes (`Fecha de caducidad` / `Días hasta su caducidad`)
- Ubicación de picking única por SKU
- Si se agota → reaprovisionamiento

### 3.3 Reaprovisionamiento
- Dispara cuando el stock de la ubicación de picking < **mínimo**
- Repone desde `AREA ALMACENAMIENTO`
- Repone **hasta el máximo** (aunque se exceda)
- La **capacidad** de la ubicación valida que quepa

### 3.4 Recepción (módulo nuevo)
- **En tránsito**: lo que viene. **Origen: SAP**, identificado por el **nº de OCA**
  (orden de compra). Aporta: OCA, SKU, cantidad esperada, ETA/proveedor.
- **Recepción**: lo que llegó (cantidad, lote, vencimiento, estado, faltante/sobrante)
- **Ubicación**: dónde ponerlo (sugerida por capacidad + mín/máx)
- **Actualización**: entra al stock local → el picking ya lo ve

### 3.5 Reincorporación (al volver el sistema)
Exportar lo hecho offline para reingresarlo a Blue Yonder.

---

## 4. Reglas de negocio (confirmadas)

**Picking**
- FEFO. Ubicación de picking única por SKU. SKU determina la ubicación.
- Si el picking queda en 0 → se busca en almacenamiento (altura).

**Reaprovisionamiento**
- Dispara por **stock mínimo** en la ubicación de picking.
- Repone desde **almacenamiento**.
- Repone **hasta el máximo**, aunque exceda (máx 200, quedan 20 → +200 → 220).
- Lo hace una persona distinta al picker (por confirmar).

**Recepción** (por definir con el usuario)

---

## 5. Arquitectura técnica

```
src/
  capture_ui.py      automatización de UI (login, menú, copiar/extraer grillas)
  inventario.py      stock offline (SQLite): leer, buscar, FEFO, resumen por SKU
  minmax.py          mínimos/máximos + cálculo de reposición
  ubicaciones.py     capacidad y tipo de ubicación (PENDIENTE)
  truck.py           venta/demanda desde el programa TRUCK (PENDIENTE)
  recepcion.py       en tránsito + recepción + ubicación (PENDIENTE)
  picking.py         asignación FEFO + confirmación (PENDIENTE)
  contraste.py       venta vs stock (PENDIENTE)
  plan_b_html.py     informes HTML
  plan_b_main.py     CLI del Plan B
templates/
  plan_b.html.j2     informe HTML del Plan B
tools/
  inspeccionar_*.py  exploradores de pantallas de Blue Yonder
  diagnosticar_*.py  diagnósticos de copiado de grillas
data/
  plan_b.sqlite      base local (tablas: stock, minmax, ubicaciones, venta, transito)
```

### Persistencia
SQLite local (`data/plan_b.sqlite`). Tablas previstas:
`stock`, `minmax`, `ubicaciones`, `venta`, `transito`, `recepcion`, `picking`.

---

## 6. Estado por fase

| Fase | Qué | Estado |
|------|-----|--------|
| 0 | Captura de stock (cuadratura con Detalle) | ✅ |
| 1 | Visor offline (SQLite + consultas + FEFO) | ✅ |
| 3 | Reaprovisionamiento (mín/máx) | ✅ (falta capacidad) |
| — | Ubicaciones (capacidad/tipo) | 🟡 pantalla lista, copiado en ajuste |
| 2 | Picking FEFO | ⏳ falta: origen de pedidos (TRUCK) |
| 6 | Contraste venta vs stock | ⏳ falta: archivo TRUCK |
| 5 | Recepción (tránsito → recibir → ubicar) | ⏳ falta: archivo de tránsito |
| 4 | Reincorporación al sistema | ⏳ falta: cómo se reingresa |

---

## 7. Pendientes

### Archivos que enviará el usuario
- [ ] Archivo tipo de **TRUCK** (la venta / demanda)
- [ ] Archivo tipo de **mercadería en tránsito** (de **SAP**, con **nº de OCA**)

### Definiciones
- [ ] Flujo físico de recepción (andén → conteo → ubicación)
- [ ] ¿El tránsito se sabe con anticipación (OC/ETA) o al llegar?
- [ ] ¿Cómo se obtiene el archivo de SAP? (export manual, reporte, carpeta compartida)
- [ ] ¿El nº de OCA sirve para cruzar tránsito ↔ recepción real?
- [ ] ¿Quién decide dónde ubicar?
- [ ] ¿Se registra lote/vencimiento al recibir?
- [ ] Cómo se reingresan los datos al volver el sistema
- [ ] **"La última noticia"** que el usuario mencionó (por confirmar)

### Técnico abierto
- [ ] Copiar grillas grandes de DevExpress (11.939 filas en ubicaciones)
  → en prueba: pyautogui (teclas reales) + extracción UIA paginada
