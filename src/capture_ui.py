"""Automatizacion de la interfaz de escritorio de Blue Yonder.

IMPORTANTE: este modulo SOLO funciona en el PC Windows donde esta instalada la
aplicacion. Aqui (Linux) no se puede probar.

Flujo: login -> abrir menu (tres barritas) -> "Informes/Etiquetas" ->
"CCU Cuadratura de Stock" -> combo area = "AREA VALORADO" -> Buscar ->
seleccionar la grilla y Ctrl+A / Ctrl+C.

Nota tecnica: al listar ventanas con Desktop.windows() pywinauto devuelve
UIAWrapper, que NO expone child_window(). Por eso los controles se buscan con
.descendants() comparando por auto_id.
"""

from __future__ import annotations

import time

import pyperclip

from .config import Config
from . import credentials

# --- Identificadores reales del PC del usuario (ver AGENTS.md) ---
VENTANA_LOGIN = "Blue Yonder"
VENTANA_APP = "Soluciones"
CAMPO_USUARIO = "txtUsername"
CAMPO_PASSWORD = "txtPassword"
BTN_MENU = "btnPinMenu"            # las tres barritas
BTN_FAVORITOS = "btnFavorites"     # la estrella
BTN_MENU_ITEM_CCU = "1705808"      # "CCU Cuadratura de Stock" dentro del menu
COMBO_AREA = "arecod"
GRILLA = "GridView:Parent=Control"
TEXTO_GRUPO = "informes/etiquetas"
TEXTO_CCU = "ccu cuadratura de stock"
TEXTO_AREA = "area valorado"


# --------------------------------------------------------------------------
# Utilidades de busqueda
# --------------------------------------------------------------------------
def _buscar(ventana, auto_id: str, control_type: str | None = None, solo_visible: bool = False):
    """Busca un control por auto_id recorriendo la ventana. Devuelve el primero o None.

    Si `solo_visible`, se descartan los controles ocultos/deshabilitados (utiles
    para evitar ventanas fantasma de ejecuciones anteriores).
    """
    for c in ventana.descendants():
        try:
            if c.element_info.automation_id != auto_id:
                continue
            if control_type and c.element_info.control_type != control_type:
                continue
            if solo_visible:
                try:
                    if not c.is_visible() or not c.is_enabled():
                        continue
                except Exception:
                    continue
            return c
        except Exception:
            continue
    return None


def _buscar_texto(ventana, texto: str, tipos: tuple[str, ...] = ("Button", "MenuItem", "Text")):
    """Busca el primer control cuyo texto contenga `texto` (sin distinguir mayusculas)."""
    objetivo = texto.lower()
    for c in ventana.descendants():
        try:
            if c.element_info.control_type not in tipos:
                continue
            if objetivo in c.window_text().lower():
                return c
        except Exception:
            continue
    return None


def listar_controles(ventana) -> list[str]:
    salida = []
    for c in ventana.descendants():
        try:
            salida.append(
                f"{c.element_info.control_type} | "
                f"{c.element_info.automation_id or '-'} | {c.window_text()[:40]!r}"
            )
        except Exception:
            continue
    return salida


def _esperar_campo(ventana, auto_id: str, timeout: float = 30.0, control_type: str | None = "Edit"):
    """Espera a que un campo exista, este VISIBLE y HABILITADO. Devuelve el control.

    Evita errores ElementNotVisible / ElementNotEnabled cuando la app aun esta
    terminando de dibujar la pantalla (o hay ventanas fantasma de corridas previas).
    """
    fin = time.time() + timeout
    while time.time() < fin:
        control = _buscar(ventana, auto_id, control_type=control_type, solo_visible=True)
        if control is not None:
            return control
        time.sleep(0.5)
    raise RuntimeError(f"El campo {auto_id!r} no quedo visible/habilitado a tiempo.")


def _clic(control) -> None:
    # Los wrappers de pywinauto (ButtonWrapper) no tienen .wait(); solo se usan
    # click_input(). Se ignora si el control no esta habilitado.
    try:
        if hasattr(control, "is_enabled") and not control.is_enabled():
            raise RuntimeError("el control no esta habilitado")
    except RuntimeError:
        raise
    except Exception:
        pass
    control.click_input()


# --------------------------------------------------------------------------
# Ventanas
# --------------------------------------------------------------------------
def buscar_ventana_login(timeout: float = 30.0):
    """Ventana de login (la que tiene el campo txtUsername)."""
    from pywinauto import Desktop

    fin = time.time() + timeout
    while time.time() < fin:
        for w in Desktop(backend="uia").windows(title_re=f".*{VENTANA_LOGIN}.*", top_level_only=True):
            try:
                # Solo ventanas visibles y con el campo de usuario visible:
                # asi se descartan ventanas fantasma de corridas anteriores.
                if not w.is_visible():
                    continue
                if _buscar(w, CAMPO_USUARIO, solo_visible=True) is not None:
                    return w
            except Exception:
                continue
        time.sleep(1)
    raise RuntimeError(
        "No encontre la ventana de login de Blue Yonder (campo 'txtUsername' visible). "
        "Verifica que la app este abierta en la pantalla de login."
    )


def buscar_ventana_app(timeout: float = 60.0):
    """Ventana principal de la app (la que tiene el menu 'pnlMenu' o el titulo 'Soluciones')."""
    from pywinauto import Desktop

    fin = time.time() + timeout
    while time.time() < fin:
        for w in Desktop(backend="uia").windows(top_level_only=True):
            try:
                titulo = w.window_text()
                if VENTANA_APP in titulo or _buscar(w, "pnlMenu") is not None:
                    return w
            except Exception:
                continue
        time.sleep(1)
    raise RuntimeError("No encontre la ventana principal de la aplicacion ('Soluciones').")


# --------------------------------------------------------------------------
# Pasos
# --------------------------------------------------------------------------
def iniciar_sesion(cfg: Config, ventana) -> None:
    """Flujo real: al abrir, el foco esta en el usuario.
    1. escribir usuario (txtUsername)  2. pasar a contrasena (txtPassword)
    3. escribir contrasena             4. Enter
    """
    usuario = cfg.credenciales.usuario
    password = credentials.get_password(cfg.credenciales.servicio, usuario)

    campo_usuario = _esperar_campo(ventana, CAMPO_USUARIO)
    campo_usuario.set_focus()
    campo_usuario.set_text(usuario)

    campo_password = _esperar_campo(ventana, CAMPO_PASSWORD)
    campo_password.set_focus()
    campo_password.set_text(password)

    campo_password.type_keys("{ENTER}")


def abrir_menu(cfg: Config, ventana) -> None:
    """Abre el menu de las tres barritas.

    El auto_id del boton puede variar segun el estado (abierto/cerrado), por eso
    se prueban varios candidatos en orden.
    """
    # El boton alterna entre 'btnMenuClose' (menu cerrado) y 'btnPinMenu' (abierto).
    candidatos = ["btnMenuClose", BTN_MENU, BTN_FAVORITOS]
    for auto_id in candidatos:
        boton = _buscar(ventana, auto_id)
        if boton is not None:
            print(f"   (clic en el boton de menu: {auto_id!r})")
            _clic(boton)
            time.sleep(cfg.app.espera_ui)
            return
    raise RuntimeError(
        "No encontre el boton del menu. Candidatos probados: " + ", ".join(candidatos)
    )


def _buscar_menuitem(texto: str):
    """Primer MenuItem visible (en cualquier ventana) cuyo texto contenga `texto`."""
    from pywinauto import Desktop

    objetivo = texto.lower()
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type != "MenuItem":
                        continue
                    if objetivo in c.window_text().lower():
                        return c
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _buscar_menuitem_exacto(texto: str):
    """Busca un MenuItem por texto EXACTO (case-insensitive); si no, cae a 'contiene'.

    Es clave cuando un nombre esta contenido en otro: p.ej. 'Reabastecimiento' vs
    'Opciones de reabastecimiento'. Primero intenta la igualdad exacta.
    """
    from pywinauto import Desktop

    objetivo = texto.strip().lower()
    candidato_parcial = None
    for w in Desktop(backend="uia").windows(top_level_only=True):
        try:
            for c in w.descendants():
                try:
                    if c.element_info.control_type != "MenuItem":
                        continue
                    t = c.window_text().strip().lower()
                    if t == objetivo:
                        return c
                    if candidato_parcial is None and objetivo in t:
                        candidato_parcial = c
                except Exception:
                    continue
        except Exception:
            continue
    return candidato_parcial


def ir_a_ccu_cuadratura(cfg: Config, ventana) -> None:
    """Navega el menu clasico de arriba: Aplicaciones > Informes/Etiquetas > CCU Cuadratura de Stock."""
    ir_a_por_menu(cfg, ventana, [
        ("Aplicaciones", "aplicaciones"),
        ("Informes/Etiquetas", "informes/etiquetas"),
        ("CCU Cuadratura de Stock", "cuadratura"),
    ])


def ir_a_por_menu(cfg: Config, ventana, ruta: list[tuple[str, str]]) -> None:
    """Navega el menu clasico de arriba siguiendo `ruta`.

    `ruta` es una lista de (nombre_legible, texto_a_buscar). Cada nivel se busca
    como MenuItem (primero por texto EXACTO y luego por coincidencia parcial) y se
    hace clic. El match exacto evita confundir 'Reabastecimiento' con
    'Opciones de reabastecimiento'.
    """
    try:
        ventana.set_focus()
        time.sleep(0.5)
    except Exception:
        pass

    for nivel, texto in ruta:
        item = _buscar_menuitem_exacto(texto)
        if item is None:
            raise RuntimeError(f"No encontre el MenuItem {nivel!r} en el menu de arriba.")
        item.click_input()
        time.sleep(cfg.app.espera_ui)


def elegir_area(cfg: Config, ventana) -> None:
    """Selecciona 'AREA VALORADO' en el combo area (arecod)."""
    combo = _buscar(ventana, COMBO_AREA)
    if combo is None:
        raise RuntimeError("No encontre el combo de area 'arecod'.")
    seleccionado = False
    try:
        combo.select("AREA VALORADO")
        seleccionado = True
    except Exception:
        pass
    if not seleccionado:
        # Alternativa: abrir el combo y elegir por texto
        combo.click_input()
        time.sleep(0.5)
        opcion = _buscar_texto(ventana, "area valorado")
        if opcion is None:
            raise RuntimeError("No encontre la opcion 'AREA VALORADO' en el combo de area.")
        _clic(opcion)
    time.sleep(cfg.app.espera_ui)


def pulsar_buscar(cfg: Config, ventana) -> None:
    """Pulsa el boton 'Buscar'."""
    boton = _buscar_texto(ventana, "buscar", tipos=("Button",))
    if boton is None:
        raise RuntimeError("No encontre el boton 'Buscar'.")
    _clic(boton)
    # La consulta puede tardar en traer todos los registros; se espera aparte
    # en esperar_resultados().
    time.sleep(cfg.app.espera_ui)


def _contar_filas(grilla) -> int:
    contador = 0
    try:
        for c in grilla.descendants():
            try:
                if c.element_info.control_type == "DataItem":
                    contador += 1
            except Exception:
                continue
    except Exception:
        return 0
    return contador


def _todas_las_grillas(ventana) -> list:
    """Todas las tablas con el auto_id de la grilla de datos."""
    encontradas = []
    for c in ventana.descendants():
        try:
            if c.element_info.control_type != "Table":
                continue
            if c.element_info.automation_id != GRILLA:
                continue
            encontradas.append(c)
        except Exception:
            continue
    return encontradas


def grilla_principal(ventana):
    """Devuelve la grilla de DATOS (la que tiene mas filas).

    En varias pantallas de Blue Yonder hay mas de una tabla con el mismo auto_id:
    una pequena (filtros/encabezado) y la grande de resultados. Elegir la primera
    a ciegas copia la tabla equivocada; por eso se elige la de mas filas.
    """
    grillas = _todas_las_grillas(ventana)
    if not grillas:
        return _buscar(ventana, GRILLA, control_type="Table") or _buscar(ventana, GRILLA)
    if len(grillas) == 1:
        return grillas[0]
    return max(grillas, key=_contar_filas)


def _filas_grilla(ventana) -> int:
    """Cuenta las filas (DataItem) que tiene la grilla de datos ahora."""
    grilla = grilla_principal(ventana)
    if grilla is None:
        return 0
    return _contar_filas(grilla)


def esperar_resultados(cfg: Config, ventana, timeout: float = 60.0) -> int:
    """Espera a que la grilla tenga filas (la consulta termino). Devuelve cuantas."""
    fin = time.time() + timeout
    filas = 0
    while time.time() < fin:
        filas = _filas_grilla(ventana)
        if filas > 0:
            # esperar un poco mas para que termine de pintar todas
            time.sleep(cfg.app.espera_ui)
            return _filas_grilla(ventana)
        time.sleep(1)
    return filas


def _copiar_por_rango_uia(grilla, filas: int) -> str:
    """Respaldo: selecciona la grilla entera por patron UIA y copia.

    Algunas grillas DevExpress exponen el patron Selection con select() sobre un
    rango de celdas. Se intenta marcar todas las celdas y luego Ctrl+C.
    """
    try:
        cells = []
        for c in grilla.descendants():
            try:
                if c.element_info.control_type == "DataItem":
                    cells.append(c)
            except Exception:
                continue
        if not cells:
            return ""
        # Marca la primera, la ultima y todo el rango intermedio con click+shift
        primero = cells[0]
        ultimo = cells[-1]
        primero.click_input()
        time.sleep(0.3)
        try:
            ultimo.click_input(coords=(1, 1))
        except Exception:
            pass
        time.sleep(0.3)
        grilla.type_keys("^a")
        time.sleep(0.4)
        grilla.type_keys("^c")
        time.sleep(0.8)
        return pyperclip.paste()
    except Exception:
        return ""


def _texto_celda(c) -> str:
    """Texto de una celda, probando varias fuentes (window_text suele venir vacio)."""
    for fuente in ("window_text", "name", "value", "legacy"):
        try:
            if fuente == "window_text":
                t = c.window_text()
            elif fuente == "name":
                t = c.element_info.name
            elif fuente == "value":
                t = c.iface_value.CurrentValue
            else:
                t = c.legacy_properties().get("Value", "")
            if t and str(t).strip():
                return str(t).strip()
        except Exception:
            continue
    return ""


def _celdas_visibles(grilla) -> list[tuple[int, int, str]]:
    """Celdas (DataItem) con posicion VALIDA: (top, left, texto).

    Se descartan las celdas con rectangulo degenerado (0,0) o tamano cero: son
    filas/columnas virtualizadas que aun no se dibujaron y ensucian la extraccion.
    """
    celdas = []
    try:
        for c in grilla.descendants():
            try:
                if c.element_info.control_type != "DataItem":
                    continue
                r = c.rectangle()
                if r.width() <= 1 or r.height() <= 1:
                    continue
                if r.top <= 0 and r.left <= 0:
                    continue
                celdas.append((r.top, r.left, _texto_celda(c)))
            except Exception:
                continue
    except Exception:
        pass
    return celdas


def _filas_desde_celdas(celdas: list[tuple[int, int, str]]) -> list[list[str]]:
    """Agrupa celdas en filas por su 'top' (con tolerancia segun la altura)."""
    if not celdas:
        return []
    alturas = sorted({t for t, _, _ in celdas})
    tol = 6
    grupos: list[tuple[int, list[tuple[int, str]]]] = []
    for top, left, texto in sorted(celdas):
        puesto = False
        for i, (t, items) in enumerate(grupos):
            if abs(t - top) <= tol:
                items.append((left, texto))
                puesto = True
                break
        if not puesto:
            grupos.append((top, [(left, texto)]))
    filas = []
    for _, items in sorted(grupos, key=lambda g: g[0]):
        filas.append([t.strip() for _, t in sorted(items, key=lambda x: x[0])])
    return filas


def _quitar_columna_numeros(filas: list[list[str]]) -> list[list[str]]:
    """Quita la columna de numero de fila (0,1,2,...) si esta presente."""
    if not filas or len(filas) < 3:
        return filas
    ancho = min(len(f) for f in filas)
    for col in range(min(2, ancho)):
        valores = [f[col] for f in filas if len(f) > col]
        if not valores or not all(v.isdigit() for v in valores):
            continue
        nums = [int(v) for v in valores]
        if nums == list(range(nums[0], nums[0] + len(nums))):
            return [f[:col] + f[col + 1:] for f in filas]
    return filas


def extraer_grilla_por_uia(ventana, filas_esperadas: int = 0, max_filas: int = 50000,
                           max_paginas: int = 500) -> str:
    """Respaldo INFALIBLE: lee las celdas de la grilla directamente por UIAutomation.

    No depende del portapapeles ni del teclado (que algunas grillas DevExpress
    ignoran). Si la grilla pagina (muestra N filas por pantalla), se avanza con
    PgDn / Ctrl+PgDn acumulando las filas nuevas (deduplicadas por contenido).

    Devuelve el contenido en formato TSV (una linea por fila).
    """
    grilla = grilla_principal(ventana)
    if grilla is None:
        raise RuntimeError("No encontre la grilla ('GridView:Parent=Control').")

    vistos: set[tuple] = set()
    ordenadas: list[list[str]] = []

    def acumular() -> int:
        filas = _filas_desde_celdas(_celdas_visibles(grilla))
        nuevos = 0
        for f in filas:
            if not any(v for v in f):
                continue
            clave = tuple(f)
            if clave in vistos:
                continue
            vistos.add(clave)
            ordenadas.append(f)
            nuevos += 1
        return nuevos

    base = acumular()
    print(f"      (pagina 1: {base} filas nuevas; total {len(ordenadas)})")

    sin_avance = 0
    for pagina in range(2, max_paginas + 1):
        if filas_esperadas and len(ordenadas) >= filas_esperadas:
            break
        avanzado = False
        for tecla in ("{PGDN}", "^{PGDN}", "{DOWN}"):
            try:
                grilla.type_keys(tecla)
            except Exception:
                continue
            time.sleep(0.8)
            nuevos = acumular()
            if nuevos > 0:
                avanzado = True
                break
        if pagina % 5 == 0 or not avanzado:
            print(f"      (pagina {pagina}: total {len(ordenadas)} filas)")
        if not avanzado:
            sin_avance += 1
            if sin_avance >= 3:
                break
        else:
            sin_avance = 0

    filas = _quitar_columna_numeros(ordenadas)[:max_filas]
    return "\n".join("\t".join(f) for f in filas)


def copiar_grilla_pyautogui(cfg: Config, ventana, filas_esperadas: int = 0) -> str:
    """Copia la grilla con teclas REALES del sistema (pyautogui / SendInput).

    Las grillas DevExpress ignoran los mensajes de teclado de pywinauto, pero SI
    responden al input real del sistema. Se hace clic en la grilla, Ctrl+A y Ctrl+C.
    """
    try:
        import pyautogui
    except ImportError:
        raise RuntimeError("pyautogui no instalado (pip install pyautogui)")
    grilla = grilla_principal(ventana)
    if grilla is None:
        raise RuntimeError("No encontre la grilla.")
    mejor = ""
    for intento in range(1, 4):
        pyperclip.copy("")
        try:
            grilla.click_input()
            time.sleep(0.6)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.8)
            pyautogui.hotkey("ctrl", "c")
        except Exception:
            pass
        time.sleep(cfg.app.espera_ui)
        texto = pyperclip.paste()
        if len(texto.splitlines()) > len(mejor.splitlines()):
            mejor = texto
        if texto.strip() and (filas_esperadas <= 0
                              or len(texto.splitlines()) >= filas_esperadas * 0.5):
            print(f"   (copia pyautogui OK: {len(texto.splitlines())} lineas)")
            return texto
        print(f"   (pyautogui intento {intento}: {len(texto.splitlines())} lineas)")
    return mejor


def copiar_grilla(cfg: Config, ventana, filas_esperadas: int = 0) -> str:
    """Copia la grilla de DATOS completa.

    En estas grillas (DevExpress) Ctrl+A NO siempre selecciona todo: hay que
    extender la seleccion con Ctrl+Shift+End. Por eso se prueban varias
    estrategias y se verifica contra `filas_esperadas`:

      A) clic -> HOME -> Ctrl+A -> Ctrl+C
      B) clic -> Ctrl+A -> Ctrl+C
      C) clic en 1a celda -> Ctrl+A -> Ctrl+C
      D) clic en 1a celda -> Ctrl+Shift+End -> Ctrl+C        <- suele ser la buena
      E) clic en 1a celda -> HOME -> Ctrl+Shift+End -> Ctrl+C
      F) clic -> Ctrl+A -> Ctrl+A -> Ctrl+C
      G) clic -> Ctrl+C   (copia la seleccion actual)
      H) clic en 1a celda -> Ctrl+Shift+End -> Enter -> Ctrl+A -> Ctrl+C

    Devuelve la mejor copia obtenida y avisa si no alcanzo `filas_esperadas`.
    """
    grilla = grilla_principal(ventana)
    if grilla is None:
        raise RuntimeError("No encontre la grilla ('GridView:Parent=Control').")

    def _secuencia(estrategia: str) -> None:
        # Foco dentro de la grilla
        if estrategia in ("C", "D", "E", "H"):
            grilla.click_input(coords=(10, 10))
        else:
            grilla.click_input()
        time.sleep(0.4)

        if estrategia == "A":
            grilla.type_keys("{HOME}"); time.sleep(0.3); grilla.type_keys("^a")
        elif estrategia == "B":
            grilla.type_keys("^a")
        elif estrategia == "C":
            grilla.type_keys("^a")
        elif estrategia == "D":
            grilla.type_keys("^+{END}")           # Ctrl+Shift+End
        elif estrategia == "E":
            grilla.type_keys("{HOME}"); time.sleep(0.3); grilla.type_keys("^+{END}")
        elif estrategia == "F":
            grilla.type_keys("^a"); time.sleep(0.3); grilla.type_keys("^a")
        elif estrategia == "G":
            pass
        elif estrategia == "H":
            grilla.type_keys("^+{END}"); time.sleep(0.3); grilla.type_keys("{ENTER}")
            time.sleep(0.3); grilla.type_keys("^a")
        time.sleep(0.5)
        grilla.type_keys("^c")

    def _copiar_con(estrategia: str) -> str:
        pyperclip.copy("")
        try:
            _secuencia(estrategia)
        except Exception:
            pass
        time.sleep(cfg.app.espera_ui)
        return pyperclip.paste()

    def _suficiente(texto: str) -> bool:
        if not texto.strip():
            return False
        if filas_esperadas <= 0:
            return True
        return len(texto.splitlines()) >= max(filas_esperadas * 0.5, 1)

    mejor = ""
    # 0) Primero: teclas REALES del sistema (DevExpress las respeta)
    try:
        texto_real = copiar_grilla_pyautogui(cfg, ventana, filas_esperadas)
        if len(texto_real.splitlines()) > len(mejor.splitlines()):
            mejor = texto_real
        if _suficiente(texto_real):
            return texto_real
    except Exception as e:
        print(f"   (pyautogui no disponible: {e})")

    for ronda in range(1, 4):
        for estrategia in ("D", "E", "A", "B", "C", "F", "G", "H"):
            texto = _copiar_con(estrategia)
            if len(texto.splitlines()) > len(mejor.splitlines()):
                mejor = texto
            if _suficiente(texto):
                print(f"   (copia OK con estrategia {estrategia}: "
                      f"{len(texto.splitlines())} lineas)")
                return texto
        print(f"   (ronda {ronda}: copia incompleta "
              f"({len(mejor.splitlines())} lineas de {filas_esperadas} esperadas), "
              f"reintentando...)")
        time.sleep(1.5)

    # Ultimo recurso: si el portapapeles no alcanza, leer las celdas por UIAutomation
    if filas_esperadas > 0 and len(mejor.splitlines()) < filas_esperadas * 0.5:
        print("   (el portapapeles no alcanza; extrayendo las celdas por UIAutomation...)")
        try:
            texto_uia = extraer_grilla_por_uia(ventana, filas_esperadas=filas_esperadas)
            if len(texto_uia.splitlines()) > len(mejor.splitlines()):
                print(f"   (extraccion UIA OK: {len(texto_uia.splitlines())} lineas)")
                return texto_uia
        except Exception as e:
            print(f"   [!] La extraccion UIA tambien fallo: {e}")

    if mejor.strip():
        print(f"   [!] Se devuelve la mejor copia obtenida: "
              f"{len(mejor.splitlines())} lineas (esperadas {filas_esperadas}).")
        return mejor
    raise RuntimeError("No se pudo copiar ni extraer la grilla.")


# --------------------------------------------------------------------------
# Flujo completo
# --------------------------------------------------------------------------
def capturar(cfg: Config) -> str:
    ventana_login = buscar_ventana_login()
    iniciar_sesion(cfg, ventana_login)
    time.sleep(cfg.app.espera_ui * 2)

    ventana = buscar_ventana_app()
    ir_a_ccu_cuadratura(cfg, ventana)
    elegir_area(cfg, ventana)
    pulsar_buscar(cfg, ventana)
    filas = esperar_resultados(cfg, ventana)
    if filas == 0:
        raise RuntimeError("La grilla no trajo resultados (0 filas) tras pulsar Buscar.")
    print(f"   ({filas} filas en la grilla)")
    return copiar_grilla(cfg, ventana, filas_esperadas=filas)


# --------------------------------------------------------------------------
# Captura de 'CCU Caja Pickeada' (informe de productividad)
# --------------------------------------------------------------------------
PANE_FECHA_DESDE = "fecha_desde"
PANE_FECHA_HASTA = "fecha_hasta"
RUTA_CAJA_PICKEADA = [
    ("Aplicaciones", "aplicaciones"),
    ("Informes/Etiquetas", "informes/etiquetas"),
    ("CCU Caja Pickeada", "caja pickeada"),
]


def _clic_pane_fecha(ventana, auto_id: str) -> bool:
    """Hace clic en el pane de fecha (activa la casilla 'Desde'/'Hasta')."""
    pane = _buscar(ventana, auto_id)
    if pane is None:
        return False
    try:
        _clic(pane)
        time.sleep(0.8)
        return True
    except Exception:
        return False


def capturar_caja_pickeada(cfg: Config, navegar: bool = True) -> str:
    """Navega a 'CCU Caja Pickeada', activa las casillas de fecha y copia la grilla.

    `navegar=False` usa la pantalla actual (util cuando ya estas en ella, porque
    re-navegar puede resetear el filtro de fecha).
    """
    ventana = buscar_ventana_app()
    if navegar:
        ir_a_por_menu(cfg, ventana, RUTA_CAJA_PICKEADA)

    # Activar casillas de fecha (son Pane dibujados a mano, no CheckBox)
    _clic_pane_fecha(ventana, PANE_FECHA_DESDE)
    _clic_pane_fecha(ventana, PANE_FECHA_HASTA)

    pulsar_buscar(cfg, ventana)
    filas = esperar_resultados(cfg, ventana)
    if filas == 0:
        raise RuntimeError("La grilla no trajo resultados (0 filas) tras pulsar Buscar.")
    print(f"   ({filas} filas en la grilla)")
    return copiar_grilla(cfg, ventana, filas_esperadas=filas)
