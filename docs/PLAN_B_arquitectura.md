# Plan B — Sistema de contingencia para Blue Yonder

## Problema
Cuando el WMS **Blue Yonder** se cae, la operación de bodega se detiene: no hay
forma de saber el stock ni de generar picking. Este proyecto construye un
**sistema de contingencia offline** que permite seguir operando durante la caída.

## Idea central
```
   [Blue Yonder ARRIBA]                        [Blue Yonder CAÍDO]
        │                                             │
        │ (1 vez al día / programado)                 │
        ▼                                             ▼
  Captura del grid "CCU Cuadratura       ──►  Archivo de inventario  ──►  PLAN B
  de Stock" con DETALLE activo                 (Excel/CSV/TSV)         (offline)
        │                                             ▲
        └── automatizable con capture_ui ─────────────┘
                                                     │
                                            Al volver el sistema:
                                            se reingresan los datos
```

**Clave:** la captura del inventario **sí se puede automatizar** (reutilizando
`capture_ui.py` del proyecto anterior). El Plan B solo necesita ese archivo y
trabaja **100% offline**, sin tocar Blue Yonder.

## Datos ya resueltos
- Fuente: pantalla **`CCU Cuadratura de Stock`** (Aplicaciones > Informes/Etiquetas).
- Marcar checkbox **`hld_flg` ("Detalle")** expande la grilla de **8 → 22 columnas**.
- Dejar el combo de área **`arecod` vacío** trae **TODAS las áreas**.
- Áreas relevantes: **AREA PICKING** y **AREA ALMACENAMIENTO** (separadas ✅).

### Columnas con Detalle (22)
`Zona de trabajo | Código de zona de recogida | AREA SAP | Ubicación | Estado de ubicación |
LPN | LPN de detalle | Número de artículo | Código de espacio | Descripción | Cantidad |
Cantidad pendiente | Cantidad confirmada | Fecha FIFO | Fecha de fabricación | Fecha de caducidad |
Fecha de recepción | Estado de inventario | Nombre de perfil de antigüedad | Días hasta su caducidad |
Última fecha de movimiento | Área`

Cubre: **FEFO** (Fecha FIFO / caducidad / días), **lote** (LPN), **stock** (Cantidad),
**tipo** (Área / zonas).

## Mecánica de la operación (reglas confirmadas)
- **Picking:** FEFO; la ubicación de picking es única por SKU; si se agota, se cubre con reapro.
- **Reapro:** se dispara por **stock mínimo** en la ubicación de picking; se repone desde
  **ALMACENAMIENTO**; se repone **hasta el máximo** aunque se exceda (ej. máx 200, quedan 20 → +200 → 220).
- Reapro lo hace una persona distinta al picker (por confirmar).

## Arquitectura propuesta (por fases)

| Fase | Qué hace | Depende de |
|------|----------|-----------|
| **0. Captura** | Script diario que guarda el grid con Detalle (todas las áreas) | `capture_ui` (existe ✅) |
| **1. Visor offline** | Lee el archivo, permite consultar stock por SKU/ubicación/lote | captura ✅ |
| **2. Picking FEFO** | Carga pedidos → asignación FEFO → lista de picking → confirmar | falta: origen de pedidos |
| **3. Reaprovisionamiento** | Detecta bajo mínimo → calcula reposición hasta máximo → tareas | falta: mín/máx |
| **4. Reincorporación** | Exporta resultado para reingresar al sistema | falta: cómo se reingresa |

## Pendientes (para continuar)
1. 🔴 **Mínimos y máximos por ubicación**: ¿dónde viven? (no están en las 22 columnas)
2. 🔴 **Origen de los PEDIDOS** durante la contingencia
3. 🔴 **Reincorporación**: cómo se reingresan los datos al volver el sistema
4. 🟡 Confirmar si `Estado de ubicación` (Llena/Parcialmente lleno) implica capacidad
5. 🟡 Correr `tools/analizar_tsv.py` sobre el TSV con TODAS las áreas para ver
   zonas, prefijos de ubicación y si un SKU aparece en varias ubicaciones

## Herramientas del repo (rama `tools-inspeccion-detalle`)
- `tools/inspeccionar_detalle.py` — navega menú, activa Detalle, captura y guarda el TSV
- `tools/listar_areas.py` — lista las opciones del combo de área
- `tools/volcar_pantalla.py` — vuelca todos los controles (calibración de auto_id)
- `tools/analizar_tsv.py` — analiza el TSV capturado (sin Windows)
