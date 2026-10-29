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


def extraer_grilla_por_uia(ventana, max_filas: int = 20000, progreso_cada: int = 200) -> str:
    """Respaldo INFALIBLE: lee las celdas de la grilla directamente por UIAutomation.

    No depende del portapapeles ni del teclado (que algunas grillas DevExpress
    ignoran). Es mas lento, pero funciona siempre que la grilla exponga sus celdas
    como DataItem con sus textos.

    Devuelve el contenido en formato TSV (una linea por fila).
    """
    grilla = grilla_principal(ventana)
    if grilla is None:
        raise RuntimeError("No encontre la grilla ('GridView:Parent=Control').")

    # Recolecta celdas (DataItem) con su posicion para reconstruir filas/columnas
    celdas = []
    try:
        for c in grilla.descendants():
            try:
                if c.element_info.control_type != "DataItem":
                    continue
                rect = c.rectangle()
                celdas.append((rect.top, rect.left, c.window_text()))
            except Exception:
                continue
    except Exception:
        pass

    if not celdas:
        raise RuntimeError("La grilla no expone celdas (DataItem) para extraer por UIA.")

    # Agrupa por fila (mismo 'top') y ordena por 'left'
    filas: dict[int, list[tuple[int, str]]] = {}
    for top, left, texto in celdas:
        # tolerancia: agrupa tops cercanos en la misma fila
        clave = None
        for k in filas:
            if abs(k - top) <= 2:
                clave = k
                break
        if clave is None:
            clave = top
            filas[clave] = []
        filas[clave].append((left, texto))

    lineas = []
    for i, top in enumerate(sorted(filas)):
        if i >= max_filas:
            break
        valores = [t for _, t in sorted(filas[top], key=lambda x: x[0])]
        lineas.append("\t".join(v.strip() for v in valores))
        if progreso_cada and i and i % progreso_cada == 0:
            print(f"      ... {i} filas extraidas")
    return "\n".join(lineas)


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
            texto_uia = extraer_grilla_por_uia(ventana)
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
