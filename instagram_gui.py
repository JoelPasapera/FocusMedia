#!/usr/bin/env python3
"""
instagram_gui.py  ·  interfaz gráfica de instagram_listas.py

    pip install customtkinter requests browser_cookie3
    python instagram_gui.py

La CLI sigue funcionando igual. No la sustituye: 'vigilar' tiene que poder
ejecutarse sin ventana desde el Task Scheduler, y una tarea programada no
puede abrir interfaces.

Cómo está montado
-----------------
El trabajo pesado (descargas de minutos u horas) corre en un HILO APARTE. Si
corriera en el hilo de la ventana, Windows la marcaría como "no responde" y
parecería colgada.

El módulo comunica por print(). El hilo redirige su salida a una cola, y la
ventana la vacía cada 100 ms con after(). Tkinter no admite que se le toque
desde otro hilo, así que el hilo NUNCA escribe en los widgets: solo deja
texto en la cola.

Cancelar usa el gancho instagram_listas.CANCELAR, que el módulo comprueba
entre páginas y durante las esperas. Lanza KeyboardInterrupt, el mismo camino
de parada ya probado: guarda el progreso y sale limpio.
"""

from __future__ import annotations

import contextlib
import json
import csv
import queue
import re
from datetime import date
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import sys
import threading
import traceback
from pathlib import Path

try:
    import customtkinter as ctk
except ImportError:
    sys.exit("Falta customtkinter.  Ejecuta:  pip install customtkinter")

import instagram_listas as m
import registro

# La limpieza vive en el módulo: la usan también la lista de
# vigilancia y la CLI. Aquí solo se reexporta.
limpiar_usuario = m.limpiar_usuario
PATRON_USUARIO = m.PATRON_USUARIO


ARCHIVO_CONFIG = Path(__file__).parent / "config_gui.json"
CARPETA_MARCA = Path(__file__).parent / "marca"
NOMBRE = "FocusMedia"

# "  1234/5678   (página 25)" -> progreso
PATRON_PROGRESO = re.compile(r"(\d+)/(\d+)\s+\(página")

# ======================================================================
# LÓGICA SIN INTERFAZ (probable sin pantalla)
# ======================================================================

class SalidaACola:
    """Sustituye a sys.stdout y manda cada línea a una cola."""

    def __init__(self, cola: queue.Queue):
        self.cola = cola
        self._resto = ""

    def write(self, texto: str) -> int:
        self._resto += texto
        # El módulo usa \r para las líneas de progreso: cuentan como salto.
        while True:
            corte = min((i for i in (self._resto.find("\n"),
                                     self._resto.find("\r")) if i >= 0),
                        default=-1)
            if corte < 0:
                break
            self.cola.put(("linea", self._resto[:corte]))
            self._resto = self._resto[corte + 1:]
        return len(texto)

    def flush(self) -> None:
        if self._resto:
            self.cola.put(("linea", self._resto))
            self._resto = ""


class Trabajador:
    """
    Ejecuta una función en segundo plano y va dejando su salida en una cola.

    Solo admite una tarea a la vez: el módulo redirige sys.stdout, que es
    global, así que dos tareas simultáneas mezclarían su salida.
    """

    def __init__(self):
        self.cola: queue.Queue = queue.Queue()
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()

    def ocupado(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def cancelar(self) -> None:
        self._parar.set()

    def esperar(self, limite: float = 3.0) -> bool:
        """Espera a que la tarea termine. True si acabó dentro del plazo."""
        if self._hilo is None:
            return True
        self._hilo.join(limite)
        return not self._hilo.is_alive()

    def lanzar(self, nombre: str, funcion, *args, **kwargs) -> bool:
        """Arranca la tarea. Devuelve False si ya había una en marcha."""
        if self.ocupado():
            return False
        self._parar.clear()
        self._hilo = threading.Thread(
            target=self._envolver, args=(nombre, funcion, args, kwargs),
            daemon=True)
        self._hilo.start()
        return True

    def _envolver(self, nombre, funcion, args, kwargs) -> None:
        self.cola.put(("inicio", nombre))
        anterior_stdout = sys.stdout
        anterior_cancelar = m.CANCELAR
        salida = SalidaACola(self.cola)
        sys.stdout = salida
        m.CANCELAR = self._parar.is_set
        try:
            funcion(*args, **kwargs)
            salida.flush()
            self.cola.put(("fin", nombre))
        except KeyboardInterrupt:
            salida.flush()
            self.cola.put(("cancelado", nombre))
        except SystemExit as e:
            # El módulo usa sys.exit() para errores de usuario.
            salida.flush()
            self.cola.put(("error", str(e) or "operación abortada"))
        except Exception as e:
            salida.flush()
            self.cola.put(("linea", traceback.format_exc()))
            self.cola.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            sys.stdout = anterior_stdout
            m.CANCELAR = anterior_cancelar


class Ajustes:
    """Configuración persistente, para no editar el .py a mano."""

    # Solo lo que es de ESTA ventana: qué cuenta se estaba mirando y con
    # qué navegador. El ritmo, los topes y los días viven en ajustes.json,
    # que es del motor y también lo usa la línea de órdenes. Tener 'umbral'
    # en los dos sitios era tener dos números para lo mismo.
    CAMPOS = {
        "objetivo": "cuenta_objetivo",
        "navegador": "firefox",
        "min_entradas": 2,
    }

    def __init__(self, ruta: Path | None = None):
        # Se lee el global AL LLAMAR, no al definir la función: como valor
        # por defecto quedaba congelado al importar el módulo y cambiarlo
        # después no tenía ningún efecto.
        self.ruta = ruta or ARCHIVO_CONFIG
        self.datos = dict(self.CAMPOS)
        self.cargar()

    def cargar(self) -> None:
        if not self.ruta.exists():
            return
        try:
            guardado = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return                       # config corrupta: valores por defecto
        for k in self.CAMPOS:
            if k in guardado:
                self.datos[k] = guardado[k]

    def guardar(self) -> None:
        try:
            m.escribir_atomico(self.ruta, json.dumps(self.datos, indent=2))
        except OSError:
            pass                         # no poder guardar no debe romper nada

    def aplicar_al_modulo(self) -> None:
        m.OBJETIVO = limpiar_usuario(self.datos["objetivo"])
        m.NAVEGADOR = str(self.datos["navegador"])

    def valido(self) -> str | None:
        """Devuelve el motivo por el que no se puede trabajar, o None."""
        crudo = str(self.datos["objetivo"]).strip()
        if not crudo or crudo == "cuenta_objetivo":
            return ("Escribe arriba la cuenta que quieres mirar. "
                    "Vale el nombre de usuario o el enlace del perfil.")
        cuenta = limpiar_usuario(crudo)
        if not cuenta:
            if "instagram.com" in crudo.lower():
                return ("Ese enlace no es de un perfil, es de una publicación "
                        "o una sección. Pega el enlace del perfil, o el "
                        "nombre de usuario a secas.")
            return "No se entiende qué cuenta es. Prueba con el nombre de usuario."
        if not PATRON_USUARIO.match(cuenta):
            return (f"'{cuenta}' no parece un nombre de usuario. Solo llevan "
                    "letras, números, puntos y guiones bajos.")
        return None


def leer_progreso(linea: str) -> float | None:
    """Saca la fracción de avance de una línea de progreso del módulo."""
    hallado = PATRON_PROGRESO.search(linea)
    if not hallado:
        return None
    hechos, total = int(hallado.group(1)), int(hallado.group(2))
    if total <= 0:
        return None
    return min(hechos / total, 1.0)


# ======================================================================
# TEMA
# ======================================================================

# Paleta de instrumental: azul-negro frío, no negro neutro. Los cuatro
# colores de estado no decoran, transportan información que esta herramienta
# genera de verdad (bloqueo, truncado, captura buena, reposo).
# Cuatro superficies, no una. El fallo del diseño anterior era que todo
# usaba el mismo panel, así que nada destacaba sobre nada.
CANVAS = "#0B0F14"      # el fondo
PANEL = "#121821"       # la banda de lectura y el lateral
RAISED = "#1A2330"      # campos y estados sobre panel
LINE = "#223041"        # filetes
SELECCION = "#2A3B4E"   # la opción elegida de un control de varias
ESTRIA = "#151C26"      # filas alternas de la tabla
TEXTO = "#DDE4EE"
DIM = "#6F7D91"
APAGADO = "#38424F"     # lo que ahora mismo no se puede pulsar
ACENTO = "#4FB3D9"      # solo para lo que mide: progreso y gráfica
ACENTO_2 = "#8C7BD8"    # la segunda serie de la gráfica
COLOR_BIEN = "#63C68A"
COLOR_AVISO = "#E0A93F"
COLOR_ERROR = "#EB6A63"

# Escala tipográfica. Antes había siete tamaños (10, 11, 12, 13, 15, 17, 34)
# repartidos a ojo por el archivo, y cuatro de ellos hacían el mismo trabajo:
# a un palmo de la pantalla, 10 y 11 no se distinguen, así que la diferencia
# no informaba de nada y solo se notaba que 10 px cuesta leerlo. Seis pasos,
# cada uno con un papel, y el 10 fuera.
TAM_MICRO = 11          # el coste de una acción, la nota de una medida
TAM_CUERPO = 12         # el texto normal de la interfaz
TAM_ACCION = 13         # lo que se pulsa y lo que se escribe
TAM_TITULO = 15         # el titular de la banda cuando no hay datos
TAM_MARCA = 17          # el nombre del producto
TAM_CIFRA = 34          # las medidas: son el producto de la herramienta

# El logo tiene tres niveles de detalle según el tamaño (ver hacer_logo.py).
# Elegir el archivo por su tamaño NATIVO, y no reducir el grande, es lo que
# evita que la red de nodos se convierta en una mancha.
TAMANOS_MARCA = (16, 32, 48, 64, 128, 256, 512)


def _familia(*candidatas: str) -> str:
    """Primera tipografía disponible. Windows primero, respaldo después."""
    try:
        import tkinter.font as tkfont
        disponibles = set(tkfont.families())
    except Exception:
        return candidatas[-1]
    for c in candidatas:
        if c in disponibles:
            return c
    return candidatas[-1]


# ======================================================================
# GEOMETRÍA DE LA GRÁFICA
# ======================================================================
# Fuera de la clase y sin tocar tkinter: así se puede comprobar el trazado
# con números, sin abrir una ventana ni mirarla a ojo.

def _a_dia(fecha: str) -> int | None:
    """La fecha de una captura como número de día. None si no se entiende."""
    try:
        return date.fromisoformat(fecha).toordinal()
    except (ValueError, TypeError, AttributeError):
        return None


def _coordenadas(serie: list, dominio: tuple, izq: float, der: float,
                 arriba: float, abajo: float) -> list:
    """
    (fecha, valor) -> (x, y) en píxeles.

    El eje X va POR FECHA, no por posición en la lista. Antes se repartían
    los puntos a intervalos iguales, así que doce días sin mirar y un día
    medían lo mismo: la línea contaba un ritmo que no ocurrió, y esta
    herramienta existe precisamente para enseñar el ritmo.

    El dominio de tiempo se pasa desde fuera y es el mismo para las dos
    listas. Cada una tiene sus propias capturas, y con ejes distintos dos
    puntos en la misma vertical serían días distintos.

    La escala vertical sí es de cada serie: 300 seguidores y 2.000 seguidos
    en la misma escala dejan la primera línea plana contra el suelo, y los
    movimientos pequeños son justo lo que hay que ver.
    """
    dias = [_a_dia(f) for f, _ in serie]
    ancho_tiempo = dominio[1] - dominio[0]
    if any(d is None for d in dias) or ancho_tiempo <= 0:
        # Sin fechas utilizables, o todas del mismo día: reparto uniforme.
        pasos = max(len(serie) - 1, 1)
        xs = [izq + (der - izq) * i / pasos for i in range(len(serie))]
    else:
        xs = [izq + (der - izq) * (d - dominio[0]) / ancho_tiempo
              for d in dias]

    valores = [v for _, v in serie]
    bajo, alto = min(valores), max(valores)
    if alto == bajo:
        # Una serie sin cambios: al medio, y sin dividir por cero.
        ys = [(arriba + abajo) / 2] * len(valores)
    else:
        ys = [abajo - (v - bajo) / (alto - bajo) * (abajo - arriba)
              for v in valores]
    return list(zip(xs, ys))


# ======================================================================
# VISOR DE TABLAS
# ======================================================================

# Los CSV llevan los nombres que usa el código. En pantalla no: quien mira
# la tabla no tiene por qué saber cómo se llama el campo por dentro. Lo que
# no esté aquí se enseña con los guiones bajos cambiados por espacios, así
# que una columna nueva sale legible sin tocar esta lista.
ETIQUETAS_COLUMNA = {
    "username": "usuario",
    "sigue_a_la_cuenta": "sigue a la cuenta",
    "la_cuenta_le_sigue": "la cuenta le sigue",
    # Capturas de antes: venían de friendship_status, que era la relación con
    # la cuenta de la sesión. Se dice, para no leerlas como las de ahora.
    "le_sigue": "le sigue (a tu sesión)",
    "la_sigue": "la sigue (tu sesión)",
    "biografia": "biografía",
    "categoria": "categoría",
    "foto_defecto": "foto por defecto",
    "primera_vez": "primera vez",
    "ultima_vez": "última vez",
    "capturas_presente": "capturas presente",
    "nombres_anteriores": "nombres anteriores",
}


def _etiqueta_columna(col: str) -> str:
    """El nombre de una columna tal como se lee en pantalla."""
    return ETIQUETAS_COLUMNA.get(col, col.replace("_", " "))


def _titulo_legible(ruta: Path) -> str:
    """Nombre de archivo -> algo que se entienda en el desplegable."""
    nombre = ruta.stem
    for prefijo, etiqueta in (("cambios_", "Cambios"),
                              ("historial_", "Historial"),
                              ("relaciones_", "Relaciones"),
                              ("detalles_", "Perfiles"),
                              ("totales_", "Totales")):
        if nombre.startswith(prefijo):
            resto = nombre[len(prefijo):].replace("_", " · ")
            return f"{etiqueta} · {resto}"
    partes = nombre.split("_")
    if len(partes) >= 3 and partes[-2] in ("seguidores", "seguidos"):
        return f"{partes[-2].capitalize()} · {partes[-1]} · {'_'.join(partes[:-2])}"
    return nombre


class VentanaTabla(ctk.CTkToplevel):
    """
    Ve los CSV sin salir de la aplicación, con búsqueda por columna.

    Va en ventana aparte a propósito: así puedes dejarla abierta mientras
    descargas, y el CSV sigue en la carpeta para lo que quieras hacer
    después con él.
    """

    TOPE_FILAS = 5000        # más que eso no se ve, se analiza en el CSV

    def __init__(self, padre, sans: str, mono: str):
        super().__init__(padre)
        self.title(f"{NOMBRE} · Tablas")
        self.geometry("1100x640")
        self.minsize(760, 420)
        self.configure(fg_color=CANVAS)
        self.sans, self.mono = sans, mono

        self.filas: list[dict] = []
        self.columnas: list[str] = []
        self.filtros: dict = {}
        self._pendiente = None
        self._orden = (None, False)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._barra()
        self._tabla()
        self._refrescar_archivos()
        # Escape cierra también aquí: es la ventana en la que más tiempo se
        # pasa, y volver al ratón solo para cerrarla se nota.
        with contextlib.suppress(Exception):
            self.bind("<Escape>", lambda _e: self.destroy())

    # ------------------------------------------------------------------
    def _barra(self) -> None:
        barra = ctk.CTkFrame(self, corner_radius=0, fg_color=PANEL, height=56)
        barra.grid(row=0, column=0, sticky="ew")
        barra.grid_columnconfigure(1, weight=1)
        barra.grid_propagate(False)

        ctk.CTkLabel(barra, text="Archivo", text_color=DIM,
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).grid(
            row=0, column=0, padx=(16, 10), pady=14)

        self.selector = ctk.CTkComboBox(
            barra, values=[], height=30, corner_radius=6, fg_color=CANVAS,
            border_color=LINE, text_color=TEXTO, button_color=CANVAS,
            button_hover_color=RAISED, dropdown_fg_color=RAISED,
            dropdown_text_color=TEXTO, dropdown_hover_color=PANEL,
            command=lambda _v: self._cargar(),
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        self.selector.grid(row=0, column=1, sticky="ew", padx=(0, 14))

        for texto, orden in (("Recargar", self._refrescar_archivos),
                             ("Limpiar filtros", self._limpiar_filtros)):
            ctk.CTkButton(barra, text=texto, command=orden, width=110,
                          height=30, corner_radius=6, fg_color="transparent",
                          border_width=1, border_color=LINE, text_color=DIM,
                          hover_color=RAISED,
                          font=ctk.CTkFont(self.sans, TAM_MICRO)).grid(
                row=0, column=2 if texto == "Recargar" else 3, padx=(0, 8))

        self.etiqueta_filas = ctk.CTkLabel(
            barra, text="", text_color=DIM,
            font=ctk.CTkFont(self.mono, TAM_MICRO))
        self.etiqueta_filas.grid(row=0, column=4, padx=(6, 16))

    def _tabla(self) -> None:
        self.marco_filtros = ctk.CTkFrame(self, corner_radius=0,
                                          fg_color=CANVAS, height=40)
        self.marco_filtros.grid(row=1, column=0, sticky="ew", padx=12,
                                pady=(10, 0))

        contenedor = ctk.CTkFrame(self, corner_radius=8, fg_color=PANEL,
                                  border_width=1, border_color=LINE)
        contenedor.grid(row=2, column=0, sticky="nsew", padx=12, pady=10)
        contenedor.grid_columnconfigure(0, weight=1)
        contenedor.grid_rowconfigure(0, weight=1)

        # ttk.Treeview y no un montón de etiquetas: aguanta miles de filas
        # sin que la ventana se arrastre.
        estilo = ttk.Style()
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure("Tabla.Treeview", background=PANEL,
                         fieldbackground=PANEL, foreground=TEXTO,
                         borderwidth=0, rowheight=26,
                         font=(self.mono, TAM_MICRO))
        estilo.configure("Tabla.Treeview.Heading", background=RAISED,
                         foreground=TEXTO, borderwidth=0, relief="flat",
                         font=(self.sans, TAM_MICRO, "bold"))
        estilo.map("Tabla.Treeview.Heading",
                   background=[("active", LINE)])
        estilo.map("Tabla.Treeview",
                   background=[("selected", LINE)],
                   foreground=[("selected", TEXTO)])
        estilo.configure("Tabla.Vertical.TScrollbar", background=RAISED,
                         troughcolor=PANEL, bordercolor=PANEL,
                         arrowcolor=DIM, borderwidth=0)
        estilo.configure("Tabla.Horizontal.TScrollbar", background=RAISED,
                         troughcolor=PANEL, bordercolor=PANEL,
                         arrowcolor=DIM, borderwidth=0)
        for nombre in ("Tabla.Vertical.TScrollbar",
                       "Tabla.Horizontal.TScrollbar"):
            estilo.map(nombre, background=[("active", LINE)])

        self.arbol = ttk.Treeview(contenedor, show="headings",
                                  style="Tabla.Treeview", selectmode="browse")
        # Franjas alternas: con doce columnas, seguir una fila hasta el final
        # sin perder el renglón es la mitad del trabajo de leer una tabla.
        self.arbol.tag_configure("impar", background=ESTRIA)
        self.arbol.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        vertical = ttk.Scrollbar(contenedor, orient="vertical",
                                 style="Tabla.Vertical.TScrollbar",
                                 command=self.arbol.yview)
        vertical.grid(row=0, column=1, sticky="ns", pady=8, padx=(0, 8))
        horizontal = ttk.Scrollbar(contenedor, orient="horizontal",
                                   style="Tabla.Horizontal.TScrollbar",
                                   command=self.arbol.xview)
        horizontal.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.arbol.configure(yscrollcommand=vertical.set,
                             xscrollcommand=horizontal.set)

    # ------------------------------------------------------------------
    def archivos(self) -> list:
        """CSV de todas las carpetas, los de la cuenta actual primero."""
        try:
            # rglob y no glob: ahora cada cuenta tiene su carpeta dentro de
            # salida/. Se siguen viendo todas, para poder comparar una con
            # otra sin cambiar de objetivo.
            todos = sorted(m.CARPETA.rglob("*.csv"),
                           key=lambda r: r.stat().st_mtime, reverse=True)
        except OSError:
            return []
        cuenta = limpiar_usuario(self.master.campo_objetivo.get()) \
            if hasattr(self.master, "campo_objetivo") else ""
        if not cuenta:
            return todos
        propios = [r for r in todos if cuenta.lower() in r.stem.lower()]
        return propios + [r for r in todos if r not in propios]

    def _refrescar_archivos(self) -> None:
        self._archivos = self.archivos()
        etiquetas = [_titulo_legible(r) for r in self._archivos]
        self.selector.configure(values=etiquetas or ["(no hay archivos)"])
        if etiquetas:
            if self.selector.get() not in etiquetas:
                self.selector.set(etiquetas[0])
            self._cargar()
        else:
            self.selector.set("(no hay archivos)")
            self._pintar([])

    def _ruta_elegida(self) -> Path | None:
        elegido = self.selector.get()
        for ruta in getattr(self, "_archivos", []):
            if _titulo_legible(ruta) == elegido:
                return ruta
        return None

    def _cargar(self) -> None:
        ruta = self._ruta_elegida()
        self.filas, self.columnas = [], []
        if ruta and ruta.exists():
            try:
                with open(ruta, newline="", encoding="utf-8-sig") as f:
                    lector = csv.DictReader(f)
                    self.columnas = list(lector.fieldnames or [])
                    for i, fila in enumerate(lector):
                        if i >= self.TOPE_FILAS:
                            break
                        self.filas.append(fila)
            except OSError:
                pass
        self._orden = (None, False)
        self._montar_columnas()
        self._aplicar_filtros()

    def _montar_columnas(self) -> None:
        for hijo in self.marco_filtros.winfo_children():
            hijo.destroy()
        self.filtros = {}

        self.arbol["columns"] = self.columnas
        vacias = m.columnas_vacias(self.filas, self.columnas)
        for i, col in enumerate(self.columnas):
            etiqueta = _etiqueta_columna(col)
            if col in vacias:
                # Decirlo es la diferencia entre «esto está roto» y
                # «Instagram dejó de mandar este dato».
                ancho, titulo = 120, f"{etiqueta} (sin datos)"
            else:
                # El nombre es la segunda columna más útil y se cortaba:
                # «Facultad de Psico…». Se le da sitio, como a la
                # biografía.
                ancho = (260 if col in ("biografia", "enlace")
                         else 220 if col == "nombre" else 150)
                titulo = etiqueta
            self.arbol.heading(col, text=titulo, anchor="w",
                               command=lambda c=col: self._ordenar(c))
            self.arbol.column(col, width=ancho, minwidth=70, anchor="w")

            self.marco_filtros.grid_columnconfigure(i, weight=1)
            caja = ctk.CTkEntry(
                self.marco_filtros, height=28, corner_radius=6,
                fg_color=PANEL, border_color=LINE, text_color=TEXTO,
                # Solo el nombre de la columna: «buscar en la cuenta le
                # sigue» no cabe y se cortaba a media palabra. La fila ya
                # se lee como lo que es, encima de las cabeceras y al lado
                # de «Limpiar filtros».
                placeholder_text=etiqueta,
                font=ctk.CTkFont(self.mono, TAM_MICRO))
            caja.grid(row=0, column=i, sticky="ew", padx=(0, 6))
            caja.bind("<KeyRelease>", lambda _e: self._filtrar_pronto())
            self.filtros[col] = caja

    def _filtrar_pronto(self) -> None:
        """Espera a que dejes de teclear: filtrar en cada tecla se arrastra."""
        if self._pendiente:
            try:
                self.after_cancel(self._pendiente)
            except Exception:
                pass
        self._pendiente = self.after(180, self._aplicar_filtros)

    def _limpiar_filtros(self) -> None:
        for caja in self.filtros.values():
            caja.delete(0, "end")
        self._aplicar_filtros()

    def filtrar(self, filas: list, criterios: dict) -> list:
        """Filas que contienen cada texto en su columna. Sin distinguir mayúsculas."""
        resultado = filas
        for col, texto in criterios.items():
            texto = (texto or "").strip().lower()
            if not texto:
                continue
            resultado = [f for f in resultado
                         if texto in str(f.get(col, "")).lower()]
        return resultado

    def _aplicar_filtros(self) -> None:
        criterios = {c: caja.get() for c, caja in self.filtros.items()}
        visibles = self.filtrar(self.filas, criterios)

        col, invertido = self._orden
        if col:
            def clave(f):
                v = str(f.get(col, ""))
                try:
                    return (0, float(v.replace(" ", "")), "")
                except ValueError:
                    return (1, 0.0, v.lower())
            visibles = sorted(visibles, key=clave, reverse=invertido)

        self._pintar(visibles)

    def _pintar(self, visibles: list) -> None:
        self.arbol.delete(*self.arbol.get_children())
        for i, fila in enumerate(visibles):
            self.arbol.insert("", "end",
                              values=[fila.get(c, "") for c in self.columnas],
                              tags=() if i % 2 == 0 else ("impar",))
        total = len(self.filas)
        if len(visibles) == total:
            self.etiqueta_filas.configure(text=f"{total} filas")
        else:
            self.etiqueta_filas.configure(
                text=f"{len(visibles)} de {total} filas")

    def _ordenar(self, col: str) -> None:
        actual, invertido = self._orden
        self._orden = (col, not invertido if actual == col else False)
        self._aplicar_filtros()


class Ventana(ctk.CTk):
    """
    La consola es el elemento principal: esta herramienta consiste en mirar
    un proceso largo que se bloquea solo. Todo lo demás queda en voz baja.
    """

    def __init__(self):
        super().__init__()
        self.title(NOMBRE)
        self._poner_icono()
        self.geometry("1120x740")
        self.minsize(940, 600)
        self.configure(fg_color=CANVAS)

        self.sans = _familia("Segoe UI", "Inter", "DejaVu Sans")
        self.mono = _familia("Cascadia Mono", "Consolas", "JetBrains Mono",
                             "DejaVu Sans Mono")

        self.ajustes = Ajustes()
        self.trabajador = Trabajador()
        self.botones_accion: list[ctk.CTkButton] = []
        self._fuentes: dict = {}
        # Lo primero de todo: montar la ventana también puede fallar, y esos
        # eran justo los errores que no dejaban rastro. Ponerlo al final
        # dejaba sin cubrir la parte que más falla.
        self._arrancar_registro()
        self._ultima_fue_progreso = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._cabecera()
        self._principal()      # crea la etiqueta de pista
        self._lateral()        # los botones la usan al pasar el ratón
        self._vaciar_cola()

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._estado_sesion()
        self._refrescar_gasto()
        self._refrescar_cuentas()
        self._refrescar_disco()
        self._log("Tres pasos para empezar:", DIM)
        self._log("  1. Escribe arriba la cuenta. Vale el nombre de usuario "
                  "o el enlace del perfil.", DIM)
        self._log("  2. Pulsa «Importar del navegador». No pide contraseña: "
                  "usa la sesión que ya tienes abierta.", DIM)
        self._log("  3. Pulsa «Contar» para comprobar que funciona. Gasta "
                  "una sola petición.", DIM)
        atados = self._hacer_navegable()
        registro.anotar(f"{atados} controles navegables con teclado")

        self._aviso_navegador()
        self._mostrar_novedades()
        if not getattr(self, "_registro_ok", True):
            self._log("No se pudo abrir el registro; el trabajo sigue "
                      "igual.", DIM)

    # Controles que se pueden usar con el teclado. Se recorre la ventana una
    # vez al final en vez de tocar los treinta sitios donde se crean.
    TECLEABLES = ("CTkButton", "CTkEntry", "CTkComboBox", "CTkOptionMenu",
                  "CTkSegmentedButton", "CTkCheckBox", "CTkTextbox")

    def _hacer_navegable(self, raiz=None) -> int:
        """
        Deja ver dónde está el teclado, y poder pulsar con él.

        El informe HTML tiene foco visible desde la v5.2 y la ventana no:
        se puede recorrer con el tabulador pero no se ve dónde estás, que
        es lo mismo que no poder recorrerla. Está en los pendientes desde
        la v4.2.

        El acento marca el foco por el mismo motivo por el que marca el
        progreso: los dos dicen «aquí», que es información y no adorno.

        Todo va envuelto: CustomTkinter no promete que sus botones acepten
        foco, y si su versión no coopera esto no hace nada en vez de
        romperse. Vale más una ventana sin anillo que una ventana rota.
        """
        atados = 0
        for hijo in (raiz or self).winfo_children():
            if type(hijo).__name__ in self.TECLEABLES:
                atados += 1 if self._atar_foco(hijo) else 0
            atados += self._hacer_navegable(hijo)
        return atados

    def _atar_foco(self, w) -> bool:
        """Anillo al entrar, y Intro o espacio para pulsar. Nunca lanza."""
        try:
            previo = (w.cget("border_color"), w.cget("border_width"))
        except Exception:
            previo = (LINE, 0)

        def entrar(_=None):
            with contextlib.suppress(Exception):
                w.configure(border_color=ACENTO,
                            border_width=max(2, int(previo[1] or 0)))

        def salir(_=None):
            with contextlib.suppress(Exception):
                w.configure(border_color=previo[0], border_width=previo[1])

        try:
            w.bind("<FocusIn>", entrar, add="+")
            w.bind("<FocusOut>", salir, add="+")
        except Exception:
            return False

        if type(w).__name__ != "CTkButton":
            return True

        # Un botón que recibe el foco y no se puede pulsar con el teclado
        # no sirve de nada, así que las dos cosas van juntas. CTk no expone
        # 'takefocus', y se pide por debajo, a la clase de Tk de la que
        # hereda: es API pública de Tk, no un truco sobre lo privado.
        def pulsar(_=None):
            with contextlib.suppress(Exception):
                w.invoke()
            return "break"

        with contextlib.suppress(Exception):
            tk.Frame.configure(w, takefocus=True)
            tk.Frame.bind(w, "<FocusIn>", entrar, add="+")
            tk.Frame.bind(w, "<FocusOut>", salir, add="+")
            tk.Frame.bind(w, "<Return>", pulsar, add="+")
            tk.Frame.bind(w, "<space>", pulsar, add="+")
        return True

    def _cabe_en_pantalla(self, ventana, ancho: int, alto: int) -> None:
        """
        Tamaño que de verdad cabe, y mínimo por debajo del cual no baja.

        El cuadro de sesiones medía 760 de alto fijos. En una pantalla de
        730 el pie —con los botones— se quedaba literalmente fuera, y no
        había forma de llegar a él. Una ventana no puede pedir más sitio
        del que hay.
        """
        try:
            alto = min(alto, ventana.winfo_screenheight() - 90)
            ancho = min(ancho, ventana.winfo_screenwidth() - 60)
        except Exception:
            pass
        ventana.geometry(f"{ancho}x{alto}")
        ventana.minsize(min(ancho, 520), min(alto, 380))

    def _atajos_de_ventana(self, ventana, aceptar=None) -> None:
        """
        Escape cierra, Intro acepta. En todas las ventanas que se abren.

        Una ventana modal que solo se cierra con el ratón es de las cosas
        que no se notan hasta que tienes las manos en el teclado.
        """
        with contextlib.suppress(Exception):
            ventana.bind("<Escape>", lambda _e: ventana.destroy())
            if aceptar:
                ventana.bind("<Return>", lambda _e: aceptar())

    def accion_ajustes(self) -> None:
        """
        Los ajustes, con su valor, el de serie y su margen.

        Cada uno enseña entre qué y qué se puede mover, y no es adorno:
        todo el programa está hecho para no perder la cuenta, y un campo
        que aceptara «pausa 0» tiraría lo demás por la borda. Se recorta y
        se dice, en vez de rechazar en silencio.
        """
        ventana = ctk.CTkToplevel(self)
        ventana.title("Ajustes")
        self._cabe_en_pantalla(ventana, 700, 620)
        ventana.configure(fg_color=CANVAS)
        ventana.transient(self)

        ctk.CTkLabel(
            ventana, text="Ajustes", text_color=TEXTO, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_TITULO)).pack(
            fill="x", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            ventana, anchor="w", text_color=DIM, wraplength=640,
            justify="left",
            text=(f"Están en {m._ruta_ajustes().name}. Lo que quede fuera "
                  "del margen se recorta al límite y se avisa."),
            font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=22, pady=(0, 10))

        lista = ctk.CTkScrollableFrame(ventana, fg_color=PANEL,
                                       corner_radius=8)
        lista.pack(fill="both", expand=True, padx=22)

        serie = m.ajustes_de_serie()
        campos, grupo_actual = {}, ""
        for clave, (constante, minimo, maximo, grupo, para) in sorted(
                m.AJUSTABLES.items(), key=lambda kv: (kv[1][3], kv[0])):
            if grupo != grupo_actual:
                grupo_actual = grupo
                ctk.CTkLabel(
                    lista, text=grupo.upper(), text_color=DIM, anchor="w",
                    font=ctk.CTkFont(self.sans, TAM_MICRO,
                                     weight="bold")).pack(
                    fill="x", padx=14, pady=(12, 4))

            fila = ctk.CTkFrame(lista, fg_color="transparent")
            fila.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(
                fila, text=clave.replace("_", " "), anchor="w", width=170,
                text_color=TEXTO,
                font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(side="left")
            caja = ctk.CTkEntry(
                fila, width=90, height=28, corner_radius=6, fg_color=RAISED,
                border_color=LINE, text_color=TEXTO,
                font=ctk.CTkFont(self.mono, TAM_CUERPO))
            caja.insert(0, str(getattr(m, constante)))
            caja.pack(side="left", padx=(0, 10))
            campos[clave] = caja
            ctk.CTkLabel(
                fila, anchor="w", text_color=DIM,
                text=f"de serie {serie[clave]}, entre {minimo} y {maximo}",
                font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(side="left")
            ctk.CTkLabel(
                lista, text="   " + para, anchor="w", text_color=DIM,
                font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
                fill="x", padx=14)

        pie = ctk.CTkFrame(ventana, fg_color="transparent")
        pie.pack(fill="x", padx=22, pady=(10, 16))

        def guardar():
            _, avisos = m.guardar_ajustes(
                {c: caja.get() for c, caja in campos.items()})
            for aviso in avisos:
                self._log("  " + aviso, COLOR_AVISO)
            self._log("Ajustes guardados.", COLOR_BIEN)
            registro.anotar("ajustes guardados desde la ventana")
            ventana.destroy()

        def restaurar():
            class _A:
                poner, restaurar = None, True
            m.cmd_ajustes(_A())
            for clave, caja in campos.items():
                caja.delete(0, "end")
                caja.insert(0, str(serie[clave]))
            self._log("Ajustes de serie restaurados.", DIM)

        ctk.CTkButton(pie, text="Guardar", command=guardar, height=32,
                      corner_radius=6, fg_color=SELECCION,
                      hover_color=RAISED, text_color=TEXTO,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="right")
        ctk.CTkButton(pie, text="Valores de serie", command=restaurar,
                      height=32, width=140, corner_radius=6,
                      fg_color="transparent", hover_color=RAISED,
                      text_color=DIM,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="right", padx=(0, 8))

        self._atajos_de_ventana(ventana, guardar)
        self._hacer_navegable(ventana)
        self._panel_ajustes = ventana
        ventana.after(120, lambda: (ventana.lift(), ventana.focus_force()))

    def accion_comparar_fechas(self) -> None:
        """
        Comparar dos fechas cualesquiera, no solo las dos últimas.

        Con meses guardados, «¿qué pasó en agosto?» es la pregunta que uno
        le quiere hacer a un historial, y hasta ahora no se podía hacer.
        """
        if self.trabajador.ocupado():
            self._log("Hay una tarea en marcha. Espera a que termine.", DIM)
            return

        fechas = sorted({m._fecha_de(r) for tipo in ("seguidores", "seguidos")
                         for r in m._capturas(tipo)})
        if len(fechas) < 2:
            self._log("Hacen falta dos capturas para comparar fechas. "
                      "Ejecuta «Listas completas» otro día.", DIM)
            return

        ventana = ctk.CTkToplevel(self)
        ventana.title("Comparar fechas")
        ventana.configure(fg_color=CANVAS)
        ventana.transient(self)
        self._cabe_en_pantalla(ventana, 520, 330)

        ctk.CTkLabel(
            ventana, text="Comparar dos fechas", text_color=TEXTO, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_TITULO)).pack(
            fill="x", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            ventana, anchor="w", justify="left", wraplength=460,
            text_color=DIM,
            text=f"Hay {len(fechas)} capturas, de la del {fechas[0]} a la "
                 f"del {fechas[-1]}. Si eliges un día sin captura se usa la "
                 "más cercana hacia atrás, y se dice cuál.",
            font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=22, pady=(0, 14))

        campos = ctk.CTkFrame(ventana, fg_color="transparent")
        campos.pack(fill="x", padx=22)
        elegidas = {}
        for etiqueta, clave, valor in (("Desde", "desde", fechas[0]),
                                       ("Hasta", "hasta", fechas[-1])):
            fila = ctk.CTkFrame(campos, fg_color="transparent")
            fila.pack(fill="x", pady=3)
            ctk.CTkLabel(
                fila, text=etiqueta, text_color=DIM, width=60, anchor="w",
                font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(side="left")
            caja = ctk.CTkComboBox(
                fila, values=fechas, height=32, corner_radius=6,
                fg_color=PANEL, border_color=LINE, button_color=RAISED,
                button_hover_color=SELECCION, text_color=TEXTO,
                dropdown_fg_color=PANEL, dropdown_text_color=TEXTO,
                font=ctk.CTkFont(self.mono, TAM_CUERPO))
            caja.set(valor)
            caja.pack(side="left", fill="x", expand=True)
            elegidas[clave] = caja

        pie = ctk.CTkFrame(ventana, fg_color="transparent")
        pie.pack(side="bottom", fill="x", padx=22, pady=(0, 18))

        def lanzar():
            desde, hasta = elegidas["desde"].get(), elegidas["hasta"].get()
            ventana.destroy()
            self._lanzar(f"Comparando {desde} con {hasta}", m.cmd_comparar,
                         _Args(totales=False, historico=False, forzar=False,
                               desde=desde, hasta=hasta),
                         accion="comparar")

        ctk.CTkButton(pie, text="Comparar", command=lanzar, height=34,
                      corner_radius=6, fg_color=SELECCION,
                      hover_color=RAISED, text_color=TEXTO,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="left")
        ctk.CTkLabel(
            pie, text="0 peticiones: lee lo que ya está descargado",
            text_color=DIM,
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            side="left", padx=(12, 0))
        ctk.CTkButton(pie, text="Cerrar", command=ventana.destroy, height=34,
                      width=90, corner_radius=6, fg_color="transparent",
                      hover_color=RAISED, text_color=DIM,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="right")

        self._atajos_de_ventana(ventana, lanzar)
        self._hacer_navegable(ventana)
        self._comparar_fechas = ventana
        ventana.after(120, lambda: (ventana.lift(), ventana.focus_force()))

    def accion_comun(self) -> None:
        """
        Cruzar dos de las cuentas que sigues. 0 peticiones.

        Vigilar varias y no poder cruzarlas deja sin responder lo que
        justifica vigilarlas: quién te sigue a ti y no a la otra, y a
        quién llegáis los dos.
        """
        if self.trabajador.ocupado():
            self._log("Hay una tarea en marcha. Espera a que termine.", DIM)
            return

        cuentas = sorted(c for c in m.leer_cuentas()
                         if m._capturas_de_cuenta(c))
        if len(cuentas) < 2:
            self._log("Hacen falta dos cuentas con capturas. Descarga otra "
                      "con «Listas completas».", DIM)
            return

        ventana = ctk.CTkToplevel(self)
        ventana.title("Comparar cuentas")
        ventana.configure(fg_color=CANVAS)
        ventana.transient(self)
        self._cabe_en_pantalla(ventana, 540, 360)

        ctk.CTkLabel(
            ventana, text="Qué comparten dos cuentas", text_color=TEXTO,
            anchor="w", font=ctk.CTkFont(self.sans, TAM_TITULO)).pack(
            fill="x", padx=22, pady=(18, 2))
        ctk.CTkLabel(
            ventana, anchor="w", justify="left", wraplength=480,
            text_color=DIM,
            text="Cruza la última captura de cada una: quién está en las "
                 "dos, y quién solo en una. Si las capturas son de días "
                 "muy distintos, se avisa.",
            font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=22, pady=(0, 14))

        campos = ctk.CTkFrame(ventana, fg_color="transparent")
        campos.pack(fill="x", padx=22)
        elegidas = {}
        for etiqueta, clave, valores, valor in (
                ("Cuenta", "a", cuentas, cuentas[0]),
                ("y", "b", cuentas, cuentas[1]),
                ("Lista", "lista", ["seguidores", "seguidos"],
                 "seguidores")):
            fila = ctk.CTkFrame(campos, fg_color="transparent")
            fila.pack(fill="x", pady=3)
            ctk.CTkLabel(
                fila, text=etiqueta, text_color=DIM, width=60, anchor="w",
                font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(side="left")
            caja = ctk.CTkComboBox(
                fila, values=valores, height=32, corner_radius=6,
                fg_color=PANEL, border_color=LINE, button_color=RAISED,
                button_hover_color=SELECCION, text_color=TEXTO,
                dropdown_fg_color=PANEL, dropdown_text_color=TEXTO,
                font=ctk.CTkFont(self.sans, TAM_CUERPO))
            caja.set(valor)
            caja.pack(side="left", fill="x", expand=True)
            elegidas[clave] = caja

        pie = ctk.CTkFrame(ventana, fg_color="transparent")
        pie.pack(side="bottom", fill="x", padx=22, pady=(0, 18))

        def lanzar():
            a, b = elegidas["a"].get(), elegidas["b"].get()
            if a == b:
                self._log("Son la misma cuenta.", COLOR_AVISO)
                return
            ventana.destroy()
            self._lanzar(f"Cruzando @{a} con @{b}", m.cmd_comun,
                         _Args(a=a, b=b, lista=elegidas["lista"].get(),
                               forzar=False), accion="comun")

        ctk.CTkButton(pie, text="Cruzar", command=lanzar, height=34,
                      corner_radius=6, fg_color=SELECCION,
                      hover_color=RAISED, text_color=TEXTO,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="left")
        ctk.CTkLabel(
            pie, text="0 peticiones: lee lo que ya está descargado",
            text_color=DIM,
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            side="left", padx=(12, 0))
        ctk.CTkButton(pie, text="Cerrar", command=ventana.destroy, height=34,
                      width=90, corner_radius=6, fg_color="transparent",
                      hover_color=RAISED, text_color=DIM,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="right")

        self._atajos_de_ventana(ventana, lanzar)
        self._hacer_navegable(ventana)
        self._comun = ventana
        ventana.after(120, lambda: (ventana.lift(), ventana.focus_force()))

    def accion_registro(self) -> None:
        """
        El registro, dentro de la aplicación y legible.

        Un archivo de texto en una carpeta se abre una vez y nunca más. Si
        el registro está para enterarse de lo que pasó, tiene que poder
        mirarse aquí, con los errores destacados y un filtro para no leer
        mil líneas buscando una.
        """
        entradas = registro.leer()
        ventana = ctk.CTkToplevel(self)
        ventana.title("Registro")
        self._cabe_en_pantalla(ventana, 980, 620)
        ventana.configure(fg_color=CANVAS)
        ventana.transient(self)

        barra = ctk.CTkFrame(ventana, fg_color="transparent")
        barra.pack(fill="x", padx=18, pady=(16, 8))

        cuenta = registro.resumen(entradas)
        # Lo que hay que saber antes de leer nada: si hay errores o no.
        resumen = "  ".join(
            f"{n} {nivel.lower()}" for nivel, n in
            sorted(cuenta.items(), key=lambda kv: -kv[1]))
        ctk.CTkLabel(
            barra, text=resumen or "el registro está vacío", anchor="w",
            text_color=COLOR_ERROR if cuenta.get("ERROR") else DIM,
            font=ctk.CTkFont(self.mono, TAM_CUERPO)).pack(side="left")

        solo_fallos = ctk.CTkCheckBox(
            barra, text="solo errores y avisos", checkbox_height=16,
            checkbox_width=16, corner_radius=4, border_width=1,
            fg_color=ACENTO, hover_color=ACENTO, border_color=LINE,
            text_color=DIM, font=ctk.CTkFont(self.sans, TAM_CUERPO))
        solo_fallos.pack(side="right", padx=(12, 0))

        buscar = ctk.CTkEntry(
            barra, width=240, height=30, corner_radius=6, fg_color=RAISED,
            border_color=LINE, text_color=TEXTO,
            placeholder_text="buscar en el registro",
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        buscar.pack(side="right")

        caja = ctk.CTkTextbox(
            ventana, corner_radius=8, fg_color=PANEL, border_width=1,
            border_color=LINE, text_color=TEXTO, wrap="none",
            font=ctk.CTkFont(self.mono, TAM_MICRO))
        caja.pack(fill="both", expand=True, padx=18)
        for nivel, color in (("ERROR", COLOR_ERROR), ("WARNING", COLOR_AVISO),
                             ("INFO", TEXTO), ("DEBUG", DIM)):
            caja.tag_config(nivel, foreground=color)
        caja.tag_config("sello", foreground=DIM)

        def pintar(*_):
            texto = buscar.get().strip().lower()
            solo = bool(solo_fallos.get())
            caja.configure(state="normal")
            caja.delete("1.0", "end")
            vistas = 0
            for e in entradas:
                if solo and e["nivel"] not in ("ERROR", "WARNING"):
                    continue
                if texto and texto not in (e["mensaje"] + e["nivel"]).lower():
                    continue
                vistas += 1
                caja.insert("end", e["sello"][11:] + "  ", "sello")
                caja.insert("end", f"{e['nivel']:<7} ", e["nivel"])
                caja.insert("end", e["mensaje"] + "\n", e["nivel"])
            if not vistas:
                caja.insert("end", "  nada que enseñar con ese filtro\n",
                            "DEBUG")
            caja.configure(state="disabled")
            caja.see("end")          # lo último es lo que interesa

        buscar.bind("<KeyRelease>", pintar)
        solo_fallos.configure(command=pintar)
        pintar()

        pie = ctk.CTkFrame(ventana, fg_color="transparent")
        pie.pack(fill="x", padx=18, pady=(8, 16))
        ruta = registro.ruta()
        ctk.CTkLabel(
            pie, anchor="w", text_color=DIM,
            text=(f"{ruta.name} · rota cada "
                  f"{registro.TAMANO // 1000} KB, {registro.COPIAS} copias · "
                  "sin cookies dentro, pero sí los nombres de las cuentas "
                  "que miras" if ruta else "sin archivo de registro"),
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(side="left")
        ctk.CTkButton(
            pie, text="Cerrar", command=ventana.destroy, width=90, height=30,
            corner_radius=6, fg_color=SELECCION, hover_color=RAISED,
            text_color=TEXTO,
            font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(side="right")

        self._atajos_de_ventana(ventana)
        self._hacer_navegable(ventana)
        self._visor_registro = ventana
        ventana.after(120, lambda: (ventana.lift(), ventana.focus_force()))

    def _arrancar_registro(self) -> None:
        """
        Deja el registro listo y recoge lo que hoy se pierde.

        El importante es el de Tk: se traga las excepciones de sus
        callbacks y las manda a stderr, que en una ventana sin consola no
        existe. Se rompía algo, no pasaba nada visible, y no quedaba rastro
        en ninguna parte.
        """
        ruta = registro.arrancar(m.CARPETA)
        for movido in m.migrar_sesiones():
            registro.anotar(f"sesión movida a su carpeta  {movido}")
        for cambio in m.aplicar_ajustes():
            registro.anotar(f"ajuste aplicado  {cambio}")
        for traido in m.migrar_config_gui(ARCHIVO_CONFIG):
            registro.anotar(f"traído de config_gui.json  {traido}")
        registro.instalar_enganches(self._aviso_de_fallo)
        registro.anotar(m.firma())
        registro.anotar("ventana abierta")

        def en_callback(tipo, valor, traza):
            registro.excepcion("error no recogido en la ventana",
                               (tipo, valor, traza))
            self._aviso_de_fallo(f"{tipo.__name__}: {valor}")

        self.report_callback_exception = en_callback
        # Se guarda para decirlo LUEGO: aquí la consola todavía no existe,
        # y avisar de que el registro falló reventando la ventana sería un
        # chiste malo.
        self._registro_ok = ruta is not None

    def _aviso_de_fallo(self, resumen: str) -> None:
        """
        Un error inesperado no puede quedarse solo dentro de un archivo.

        Quien está delante tiene que enterarse de que ha pasado algo y de
        dónde mirarlo; si no, el registro solo sirve para después.
        """
        try:
            self._log("Ha fallado algo inesperado: "
                      + registro.limpiar_secretos(resumen)[:160],
                      COLOR_ERROR)
            self._log("  El detalle está en «Registro», abajo.", DIM)
        except Exception:
            pass

    def _mostrar_novedades(self) -> None:
        """
        Lo que «Vigilar» encontró mientras la ventana estaba cerrada.

        Es el otro extremo del aviso: la tarea programada lo anota en la
        bandeja y aquí se lee. Sin esto, enterarse dependía de acordarse de
        abrir un archivo de texto, que es justo lo que no pasa.

        Se marcan como vistas al enseñarlas: la bandeja no se vacía, pero la
        próxima vez solo sale lo que haya llegado después.
        """
        try:
            pendientes = m.novedades_pendientes()
        except Exception:
            return
        if not pendientes:
            return
        self._log("")
        self._log(f"Novedades desde la última vez ({len(pendientes)}):")
        for bloque in pendientes[-6:]:
            self._log(f"  {bloque['cabecera']}", DIM)
            for linea in bloque["texto"]:
                self._log(f"      {linea}")
        if len(pendientes) > 6:
            self._log(f"  ... y {len(pendientes) - 6} más en "
                      f"{m._ruta_novedades().name}", DIM)
        try:
            m.marcar_novedades_vistas()
        except Exception:
            pass

    def _poner_icono(self) -> None:
        """
        Icono de la ventana y de la barra de tareas.

        En Windows manda el .ico (lleva todos los tamaños dentro y es lo que
        usa la barra de tareas); en el resto, el PNG. Si falta la carpeta de
        marca, la aplicación funciona igual: es decoración, no una pieza.
        """
        try:
            if sys.platform == "win32":
                ico = CARPETA_MARCA / "focusmedia.ico"
                if ico.exists():
                    self.iconbitmap(str(ico))
                    return
            png = CARPETA_MARCA / "focusmedia.png"
            if png.exists():
                self._icono = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icono)
        except Exception:
            pass

    def _escala(self) -> float:
        """
        Cuántos píxeles reales vale uno lógico en esta pantalla.

        Windows al 150% dibuja un widget de 28 con 42 píxeles de verdad, y
        eso decide qué archivo del logo hay que cargar y a qué tamaño hay
        que recortar la foto para que no se vea borrosa.
        """
        try:
            return ctk.ScalingTracker.get_widget_scaling(self)
        except Exception:
            return 1.0

    def _fuente(self, familia: str, tam: int):
        """
        Una fuente que se puede medir, guardada.

        Crear una fuente cuesta, y la gráfica se repinta cada vez que cambia
        el tamaño de la ventana.
        """
        clave = (familia, tam)
        if clave not in self._fuentes:
            self._fuentes[clave] = tkfont.Font(family=familia, size=tam)
        return self._fuentes[clave]

    def _imagen_marca(self, lado: int):
        """
        El logo al tamaño pedido, tomando el archivo que le corresponde.

        La cabecera pedía 26 px y cargaba el PNG de 64, que lleva dibujada la
        red de tres nodos. Reducir 64 a 26 no enseña tres nodos: enseña una
        mancha. El logo está generado en tres niveles de detalle justo para
        no tener que hacer eso.
        """
        fisicos = lado * self._escala()
        nativo = next((t for t in TAMANOS_MARCA if t >= fisicos),
                      TAMANOS_MARCA[-1])
        ruta = CARPETA_MARCA / f"focusmedia_{nativo}.png"
        if not ruta.exists():
            return None
        try:
            from PIL import Image
            return ctk.CTkImage(Image.open(ruta), size=(lado, lado))
        except Exception:
            return None          # sin Pillow, la ventana va igual

    # ------------------------------------------------------------------
    def _cabecera(self) -> None:
        barra = ctk.CTkFrame(self, height=52, corner_radius=0,
                             fg_color=PANEL, border_width=0)
        barra.grid(row=0, column=0, columnspan=2, sticky="ew")
        barra.grid_columnconfigure(1, weight=1)
        barra.grid_propagate(False)

        titulo = ctk.CTkFrame(barra, fg_color="transparent")
        titulo.grid(row=0, column=0, padx=(20, 0), pady=10, sticky="w")

        self._marca = self._imagen_marca(28)
        if self._marca is not None:
            ctk.CTkLabel(titulo, image=self._marca, text="").pack(
                side="left", padx=(0, 10))

        # Sin coletilla descriptiva: la ventana entera ya va de eso, y
        # quitar lo que no hace ningún trabajo es la mitad del diseño.
        ctk.CTkLabel(
            titulo, text=NOMBRE, text_color=TEXTO,
            font=ctk.CTkFont(self.sans, TAM_MARCA, weight="bold")).pack(
            side="left")
        # Pequeña y al lado del nombre: hace falta para pedir ayuda con
        # sentido, y no compite con nada.
        ctk.CTkLabel(
            titulo, text=m.VERSION, text_color=DIM,
            font=ctk.CTkFont(self.mono, TAM_MICRO)).pack(
            side="left", padx=(8, 0), pady=(6, 0))

        derecha = ctk.CTkFrame(barra, fg_color="transparent")
        derecha.grid(row=0, column=2, padx=22, sticky="e")
        self.etiqueta_gasto = ctk.CTkLabel(
            derecha, text="", text_color=DIM,
            font=ctk.CTkFont(self.mono, TAM_MICRO))
        self.etiqueta_gasto.pack(side="left", padx=(0, 18))
        self.punto = ctk.CTkLabel(derecha, text="\u25cf", text_color=DIM,
                                  font=ctk.CTkFont(self.sans, TAM_ACCION))
        self.punto.pack(side="left", padx=(0, 7))
        self.etiqueta_sesion = ctk.CTkLabel(
            derecha, text="", text_color=DIM,
            font=ctk.CTkFont(self.sans, TAM_CUERPO), cursor="hand2")
        self.etiqueta_sesion.pack(side="left")

        # Se pulsa para cambiar de cuenta. Es donde se mira para saber con
        # cuál se está trabajando, así que es donde se busca cambiarla; que
        # el único camino fuera un botón del lateral es esconderlo.
        for parte in (self.punto, self.etiqueta_sesion):
            parte.bind("<Button-1>", lambda _e: self.accion_pegar_sesion())
            parte.configure(cursor="hand2")

        ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=LINE).grid(
            row=0, column=0, columnspan=2, sticky="sew")

    # ------------------------------------------------------------------
    def _boton_lateral(self, padre, texto, orden, pista, coste):
        """
        Una acción del lateral, con su coste en peticiones a la derecha.

        El coste es el dato más importante de esta herramienta: hay acciones
        que no gastan nada y otras que gastan cincuenta. Tenerlo escondido
        en un texto al pasar el ratón era esconder justo lo que decide si
        pulsas o no.
        """
        fila = ctk.CTkFrame(padre, fg_color="transparent", height=32)
        fila.pack(fill="x", padx=8, pady=1)
        fila.pack_propagate(False)

        b = ctk.CTkButton(
            fila, text=texto, command=orden, height=32, anchor="w",
            corner_radius=4, fg_color="transparent", hover_color=RAISED,
            text_color=TEXTO, text_color_disabled=APAGADO,
            font=ctk.CTkFont(self.sans, TAM_ACCION))
        b.place(x=0, y=0, relwidth=1, relheight=1)

        # Marca de acento a la izquierda al pasar el ratón: un instrumento
        # señala, no ilumina un rectángulo entero.
        marca = ctk.CTkFrame(fila, width=3, height=20, corner_radius=0,
                             fg_color="transparent")
        marca.place(x=0, y=6)

        # Lo que no gasta nada se queda en gris; lo que sale a la red se lee.
        # El coste era el dato más importante de la ventana y era también lo
        # más pequeño y lo más apagado: la jerarquía decía lo contrario
        # de la documentación. Se separa por contraste y no por color,
        # que aquí está reservado para el estado real.
        etiqueta = ctk.CTkLabel(fila, text=coste,
                                font=ctk.CTkFont(self.mono, TAM_MICRO))
        # El color de reposo viaja con la etiqueta: al desbloquear hay que
        # devolverle EL SUYO, no un gris para todas.
        etiqueta.color_reposo = DIM if coste == "0" else TEXTO
        etiqueta.configure(text_color=etiqueta.color_reposo)
        etiqueta.place(relx=1.0, rely=0.5, anchor="e", x=-10)

        def entrar(_e, t=pista, mk=marca):
            self.etiqueta_pista.configure(text=t, text_color=DIM)
            mk.configure(fg_color=ACENTO)

        def salir(_e, mk=marca):
            self._mostrar_sugerencia()
            mk.configure(fg_color="transparent")

        for w in (b, etiqueta, marca):
            w.bind("<Enter>", entrar)
            w.bind("<Leave>", salir)
        etiqueta.bind("<Button-1>", lambda _e: orden())

        self.botones_accion.append(b)
        self.etiquetas_coste.append(etiqueta)
        return b

    def _grupo(self, padre, titulo, explicacion) -> None:
        ctk.CTkLabel(
            padre, text=titulo, text_color=TEXTO, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_CUERPO, weight="bold")).pack(
            fill="x", padx=20, pady=(11, 0))
        ctk.CTkLabel(padre, text=explicacion, text_color=DIM, anchor="w",
                     wraplength=192, justify="left",
                     font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            fill="x", padx=20, pady=(0, 3))

    def _lateral(self) -> None:
        marco = ctk.CTkFrame(self, width=228, corner_radius=0,
                             fg_color=PANEL)
        marco.grid(row=1, column=0, sticky="nsew")
        marco.grid_propagate(False)
        self.etiquetas_coste = []

        # "Parar" se coloca ANTES que las acciones: al empaquetar, lo que va
        # primero reserva su sitio. Si se pone al final, las acciones se
        # comen el espacio y el botón se sale de la ventana.
        pie = ctk.CTkFrame(marco, fg_color="transparent")
        pie.pack(side="bottom", fill="x", padx=12, pady=(8, 12))
        self.boton_parar = ctk.CTkButton(
            pie, text="Parar", command=self.accion_parar, height=34,
            corner_radius=6, fg_color="transparent", border_width=1,
            border_color=LINE, text_color=DIM, hover_color=RAISED,
            font=ctk.CTkFont(self.sans, TAM_ACCION), state="disabled")
        self.boton_parar.pack(fill="x")

        # Las acciones van en un área desplazable: con la ventana pequeña,
        # antes quedaban fuera del alcance sin manera de llegar a ellas.
        lateral = ctk.CTkScrollableFrame(
            marco, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=LINE, scrollbar_button_hover_color=RAISED)
        lateral.pack(side="top", fill="both", expand=True)

        ctk.CTkLabel(
            lateral, text="Los números son peticiones a Instagram.",
            text_color=DIM, anchor="w", wraplength=192, justify="left",
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            fill="x", padx=20, pady=(10, 2))

        self._boton_lateral(lateral, "Guía y ayuda", self.accion_ayuda,
                            "Qué hace cada cosa, en qué orden, y qué mirar "
                            "si algo falla. No gasta nada.", "0")

        self._grupo(lateral, "Conectar", "usa la sesión de tu navegador")
        self._boton_lateral(lateral, "Importar sesión", self.accion_sesion,
                            "Toma las cookies de tu navegador. No pide "
                            "contraseña ni la guarda en ningún sitio.",
                            "0")
        self._boton_lateral(lateral, "Sesiones",
                            self.accion_pegar_sesion,
                            "Guarda varias sesiones y cambia entre ellas. "
                            "Útil con Chrome o Edge en Windows, que cifran "
                            "sus cookies y no se dejan leer.", "0")
        self._boton_lateral(lateral, "Gasto de hoy", self.accion_presupuesto,
                            "Cuántas peticiones llevas, en qué se han ido y "
                            "qué vías está usando. No gasta nada.",
                            "0")
        self._boton_lateral(lateral, "Diagnóstico", self.accion_diagnostico,
                            "Prueba cada vía y comprueba que sigue trayendo "
                            "lo que hace falta. Úsalo si algo falla.", "5")
        self._boton_lateral(lateral, "Qué espera de Instagram",
                            self.accion_contratos,
                            "Rutas, parámetros y forma de las respuestas. Si "
                            "Instagram cambia algo, se repara aquí sin tocar "
                            "código.", "0")

        self._grupo(lateral, "Consultar", "miran, pero no descargan nada")
        self._boton_lateral(lateral, "Contar", self.accion_contar,
                            "Cuántos seguidores y seguidos tiene la cuenta, "
                            "ahora mismo. Lo más barato que hay.",
                            "1")
        self._boton_lateral(lateral, "Inspeccionar campos",
                            self.accion_inspeccionar,
                            "Qué datos manda Instagram por cada persona. "
                            "Sirve para saber qué se puede guardar.",
                            "1")

        self._grupo(lateral, "Descargar", "lo que tarda; se puede parar")
        self._boton_lateral(lateral, "Listas completas", self.accion_bajar,
                            "Baja quién sigue a la cuenta y a quién sigue. "
                            "Si se corta, la próxima vez sigue donde iba.",
                            "~50")
        self._boton_lateral(lateral, "Vigilar todas",
                            self.accion_vigilar_todas,
                            "Recorre todas las cuentas que sigues, por turnos, "
                            "repartiendo el presupuesto del día. No va en "
                            "paralelo: eso provocaría bloqueos.", "1+ c/u")
        self._boton_lateral(lateral, "Vigilar", self.accion_vigilar,
                            "Mira los totales con 1 petición y solo descarga "
                            "si algo cambió. Pensado para dejarlo programado.",
                            "1+")

        self._grupo(lateral, "Analizar", "sobre lo que ya tienes en disco")
        self._boton_lateral(lateral, "Qué cambió", self.accion_comparar,
                            "Quién entró y quién salió entre las dos últimas "
                            "descargas. Hacen falta dos de días distintos.",
                            "0")
        self._boton_lateral(lateral, "Historial", self.accion_historial,
                            "La trayectoria de cada persona: cuándo llegó, "
                            "cuándo se fue, quién entra y sale sin parar.",
                            "0")
        self._boton_lateral(lateral, "Comparar cuentas", self.accion_comun,
                            "Qué audiencia comparten dos de las cuentas que "
                            "sigues: quién está en las dos y quién solo en "
                            "una.", "0")
        self._boton_lateral(lateral, "Comparar fechas",
                            self.accion_comparar_fechas,
                            "Qué cambió entre dos días cualesquiera de tu "
                            "historial, no solo entre las dos últimas "
                            "capturas.", "0")
        self._boton_lateral(lateral, "Copia de seguridad",
                            self.accion_copia,
                            "Guarda en un zip todo lo descargado de esta "
                            "cuenta. Una captura de hace tres semanas no se "
                            "puede volver a descargar: esa lista ya no "
                            "existe.", "0")
        self._boton_lateral(lateral, "Informe HTML", self.accion_informe,
                            "Un archivo con todo dentro: las tablas, la "
                            "evolución y los cambios. Se abre con doble clic "
                            "y no necesita internet.", "0")
        self._boton_lateral(lateral, "Perfiles detallados",
                            self.accion_detalles,
                            "Biografía, publicaciones y enlaces de unas pocas "
                            "cuentas que tú elijas. Cuidado: 1 por cuenta.",
                            "1 c/u")

        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=LINE).grid(
            row=1, column=0, sticky="nse")

    def _principal(self) -> None:
        zona = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        zona.grid(row=1, column=1, sticky="nsew")
        zona.grid_columnconfigure(0, weight=1)
        zona.grid_rowconfigure(3, weight=1)

        # --- franja de ajustes ---
        franja = ctk.CTkFrame(zona, corner_radius=0, fg_color=CANVAS)
        franja.grid(row=0, column=0, sticky="ew")
        franja.grid_columnconfigure(2, weight=3)
        franja.grid_columnconfigure(5, weight=2)

        ctk.CTkLabel(franja, text="Cuenta", text_color=DIM,
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).grid(
            row=0, column=0, padx=(22, 10), pady=(18, 10), sticky="w")

        self._avatar(franja)

        # Desplegable editable: se eligen las cuentas ya seguidas, o se
        # escribe una nueva. Escribir a mano el nombre cada vez era la
        # única forma de cambiar de objetivo.
        self.campo_objetivo = ctk.CTkComboBox(
            franja, values=[], height=32, corner_radius=6, fg_color=RAISED,
            border_color=LINE, text_color=TEXTO, button_color=PANEL,
            button_hover_color=RAISED, dropdown_fg_color=RAISED,
            dropdown_text_color=TEXTO, dropdown_hover_color=PANEL,
            command=lambda _v: self._normalizar_cuenta(),
            font=ctk.CTkFont(self.mono, TAM_ACCION))
        inicial = str(self.ajustes.datos["objetivo"])
        # 'cuenta_objetivo' es el valor de relleno del módulo, no algo que
        # el usuario deba ver ni corregir.
        self.campo_objetivo.set("" if inicial == "cuenta_objetivo" else inicial)
        self.campo_objetivo.grid(row=0, column=2, padx=(0, 22), sticky="ew")
        for evento in ("<FocusOut>", "<Return>"):
            self.campo_objetivo.bind(evento,
                                     lambda _e: self._normalizar_cuenta())
        # Al teclear solo se repinta la foto y el pie. La validación entera
        # en cada tecla llenaría la consola de avisos sobre un nombre a medio
        # escribir; esto solo mira el disco, y ni eso si no hay nada.
        def _al_teclear(_e):
            cuenta = limpiar_usuario(self.campo_objetivo.get())
            self._refrescar_avatar(cuenta)
            self._refrescar_perfil(cuenta)

        self.campo_objetivo.bind("<KeyRelease>", _al_teclear)

        ctk.CTkLabel(franja, text="Listas", text_color=DIM,
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).grid(
            row=0, column=3, padx=(0, 10), sticky="w")
        # Entre PANEL y RAISED hay ocho puntos de luminosidad: en la pantalla
        # no se veía cuál de las tres estaba elegida, y esto decide qué
        # descarga «Listas completas». La elegida sube hasta SELECCION, que
        # sí se distingue de un vistazo.
        self.campo_lista = ctk.CTkSegmentedButton(
            franja, values=["ambas", "seguidores", "seguidos"], height=32,
            corner_radius=6, fg_color=PANEL, selected_color=SELECCION,
            selected_hover_color=SELECCION, unselected_color=PANEL,
            unselected_hover_color=RAISED, text_color=TEXTO,
            border_width=1, font=ctk.CTkFont(self.sans, TAM_CUERPO))
        self.campo_lista.set("ambas")
        self.campo_lista.grid(row=0, column=4, padx=(0, 22), sticky="w")

        ctk.CTkLabel(franja, text="Navegador", text_color=DIM,
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).grid(
            row=0, column=5, padx=(0, 10), sticky="e")
        self.campo_navegador = ctk.CTkOptionMenu(
            franja, height=32, corner_radius=6, width=124,
            values=["firefox", "chrome", "chromium", "edge", "brave",
                    "opera", "opera_gx", "vivaldi", "librewolf", "safari",
                    "arc"],
            fg_color=PANEL, button_color=PANEL, button_hover_color=RAISED,
            text_color=TEXTO, font=ctk.CTkFont(self.sans, TAM_CUERPO),
            command=self._aviso_navegador)
        self.campo_navegador.set(str(self.ajustes.datos["navegador"]))
        self.campo_navegador.grid(row=0, column=6, padx=(0, 22), sticky="e")

        # Debajo del campo: quién es esa cuenta, en voz baja. Va aquí y no en
        # la banda de medidas porque no es una medida — es la identidad, y su
        # sitio es junto a la foto y al nombre de usuario, no entre las
        # cifras que sí se mueven.
        self.etiqueta_perfil = ctk.CTkLabel(
            franja, text="", text_color=DIM, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_MICRO))
        self.etiqueta_perfil.grid(row=1, column=2, padx=(0, 22),
                                  pady=(0, 2), sticky="w")

        self.campo_sospechosas = ctk.CTkCheckBox(
            franja, text="Incluir capturas dudosas en el análisis",
            checkbox_height=16, checkbox_width=16, corner_radius=4,
            border_width=1, fg_color=ACENTO, hover_color=ACENTO,
            border_color=LINE, text_color=DIM,
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        self.campo_sospechosas.grid(row=2, column=0, columnspan=5,
                                    padx=(22, 0), pady=(4, 16), sticky="w")

        self._panel_disco(zona)

        # --- qué hacer ahora ---
        # Va aquí y no en el lateral: es la pregunta que tienes delante de
        # nueve botones, y en el centro se lee sin buscarla.
        # Sin caja ni flecha: un filete de acento a la izquierda basta para
        # decir «esto te lo dice el sistema». La flecha pegada al texto es
        # de las marcas más reconocibles de plantilla.
        guia = ctk.CTkFrame(zona, corner_radius=0, fg_color=CANVAS, height=44)
        guia.grid(row=2, column=0, sticky="ew")
        guia.grid_columnconfigure(1, weight=1)
        guia.grid_rowconfigure(0, weight=1)
        guia.grid_propagate(False)

        # CTkFrame mide 200 px de alto por defecto: sin fijarlo, la fila se
        # estiraba y el texto quedaba centrado FUERA de la banda.
        self.flecha = ctk.CTkFrame(guia, width=3, height=22, corner_radius=0,
                                   fg_color=ACENTO)
        self.flecha.grid(row=0, column=0, sticky="", padx=(22, 14))
        self.etiqueta_pista = ctk.CTkLabel(
            guia, text="", text_color=DIM, anchor="w", justify="left",
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        self.etiqueta_pista.grid(row=0, column=1, sticky="w", padx=(0, 22))
        self.etiqueta_pista.configure(anchor="w")

        # --- consola: el elemento principal ---
        # El único elemento con marco de toda la ventana: así se sabe sin
        # pensarlo cuál es la superficie de trabajo.
        marco = ctk.CTkFrame(zona, corner_radius=10, fg_color=PANEL,
                             border_width=1, border_color=LINE)
        marco.grid(row=3, column=0, sticky="nsew", padx=22, pady=(14, 14))
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)

        titulo = ctk.CTkFrame(marco, fg_color="transparent", height=38)
        titulo.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        titulo.grid_columnconfigure(0, weight=1)

        self.etiqueta_estado = ctk.CTkLabel(
            titulo, text="En reposo", text_color=DIM, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        self.etiqueta_estado.grid(row=0, column=0, sticky="w")

        # Tres botones con el mismo borde y el mismo ancho de 94 px decían que
        # las tres cosas son equivalentes y del mismo tamaño, y no lo son. El
        # marco de la consola ya delimita esta zona: meter un borde dentro de
        # otro borde es justo el kit de tarjetas que este diseño evita. Se
        # quedan como herramientas: sin caja, cada una con su ancho, y se
        # encienden al pasar el ratón.
        for columna, (texto, ancho, orden) in enumerate((
                ("Ver tablas", 88, self.accion_tablas),
                ("Limpiar", 74, self.accion_limpiar),
                ("Ajustes", 78, self.accion_ajustes),
                ("Registro", 82, self.accion_registro),
                ("Abrir carpeta", 104, self.accion_abrir_carpeta)), start=1):
            ctk.CTkButton(titulo, text=texto, command=orden, width=ancho,
                          height=26, corner_radius=5, fg_color="transparent",
                          hover_color=RAISED, text_color=DIM,
                          font=ctk.CTkFont(self.sans, TAM_MICRO)).grid(
                row=0, column=columna, padx=(6, 0))

        # Encima se manda, debajo se lee. El filete lo dice sin etiquetas.
        ctk.CTkFrame(marco, height=1, corner_radius=0, fg_color=LINE).grid(
            row=0, column=0, sticky="sew", padx=10)

        self.consola = ctk.CTkTextbox(
            marco, wrap="word", corner_radius=0, fg_color=PANEL,
            text_color=TEXTO, border_width=0, activate_scrollbars=True,
            font=ctk.CTkFont(self.mono, TAM_CUERPO))
        self.consola.grid(row=1, column=0, sticky="nsew", padx=10,
                          pady=(6, 12))
        self.consola.configure(state="disabled")
        for etiqueta, color in (("error", COLOR_ERROR),
                                ("aviso", COLOR_AVISO),
                                ("bien", COLOR_BIEN), ("dim", DIM)):
            self.consola.tag_config(etiqueta, foreground=color)

        # --- barra de estado ---
        estado = ctk.CTkFrame(zona, corner_radius=0, fg_color="transparent",
                              height=34)
        estado.grid(row=4, column=0, sticky="ew", padx=22, pady=(0, 16))
        estado.grid_columnconfigure(0, weight=1)

        self.barra = ctk.CTkProgressBar(
            estado, height=4, corner_radius=2, fg_color=RAISED,
            progress_color=RAISED)     # invisible mientras no haya tarea
        self.barra.set(0)
        self.barra.grid(row=0, column=0, sticky="ew", padx=(0, 16))

        self.etiqueta_cifras = ctk.CTkLabel(
            estado, text="", text_color=DIM,
            font=ctk.CTkFont(self.mono, TAM_MICRO))
        self.etiqueta_cifras.grid(row=0, column=1, sticky="e")

    def _avatar(self, franja) -> None:
        """
        La foto de la cuenta, al lado de donde se escribe su nombre.

        Sirve para lo de siempre: confirmar de un vistazo que estás mirando a
        quien creías. Con el nombre escrito a mano y cuentas que se parecen
        (@ana.lopez y @ana_lopez), eso no es adorno.

        Desde aquí NUNCA se sale a la red. Solo se lee lo que el módulo dejó
        en disco al leer el perfil: descargar en el hilo de la ventana la
        dejaría congelada, y hacerlo al teclear gastaría en cada errata.
        """
        # Ocupa las DOS filas: arriba el usuario, abajo el nombre y las
        # publicaciones. Sola en la fila de controles se leía como un tercer
        # botón entre «Cuenta» y el campo, y el pie quedaba descolgado. Así
        # la foto sujeta el bloque entero, que es el trabajo que hace una
        # foto de perfil en cualquier sitio donde aparece.
        #
        # Y por eso puede ser más grande sin que la franja crezca ni un
        # píxel: entre las dos filas hay unos 65 y ella ocupa 44. Centrada y
        # no pegada arriba, que aguanta mejor que las letras midan otra cosa
        # en Windows.
        self._lado_avatar = int(44 * self._escala())
        self.avatar = tk.Canvas(franja, width=self._lado_avatar,
                                height=self._lado_avatar, bg=CANVAS,
                                highlightthickness=0, bd=0)
        self.avatar.grid(row=0, column=1, rowspan=2, padx=(0, 14),
                         pady=(14, 2))
        self._foto_dibujada = None

    def _foto_de(self, cuenta: str):
        """
        La foto guardada de esa cuenta, recortada en círculo.

        None si no hay ninguna todavía, si el archivo está roto o si falta
        Pillow: en los tres casos se dibuja el disco con la inicial y no
        pasa nada más.
        """
        if not cuenta:
            return None
        archivo = m.ruta_foto(cuenta)
        try:
            clave = (cuenta, archivo.stat().st_mtime)
        except OSError:
            self._foto_dibujada = None
            return None

        # Recortar y enmascarar cuesta lo suyo, y esto se repinta en cada
        # refresco. La fecha del archivo va en la clave: si «Contar» acaba
        # de bajar una foto nueva, se rehace; si no, se reutiliza.
        recordada = self._foto_dibujada
        if recordada and recordada[0] == clave:
            return recordada[1]

        try:
            from PIL import Image, ImageDraw, ImageOps, ImageTk
        except ImportError:
            return None
        try:
            lado = self._lado_avatar
            # Se recorta y se enmascara al cuádruple y luego se reduce: el
            # borde del círculo sale limpio en vez de dentado.
            grande = lado * 4
            foto = ImageOps.fit(Image.open(archivo).convert("RGB"),
                                (grande, grande), Image.LANCZOS)
            mascara = Image.new("L", (grande, grande), 0)
            ImageDraw.Draw(mascara).ellipse((0, 0, grande - 1, grande - 1),
                                            fill=255)
            foto.putalpha(mascara)
            imagen = ImageTk.PhotoImage(
                foto.resize((lado, lado), Image.LANCZOS))
        except Exception:
            return None                 # un archivo roto no tumba la ventana

        self._foto_dibujada = (clave, imagen)
        return imagen

    def _refrescar_avatar(self, cuenta: str) -> None:
        lado = self._lado_avatar
        caja = (1, 1, lado - 2, lado - 2)
        self.avatar.delete("all")

        imagen = self._foto_de(cuenta)
        if imagen is not None:
            self.avatar.create_image(lado / 2, lado / 2, image=imagen)
            # Un filete alrededor, del mismo color que los demás: sin él, una
            # foto de fondo claro se recorta contra el fondo de la ventana y
            # el círculo deja de leerse como un círculo.
            self.avatar.create_oval(*caja, outline=LINE, width=1)
            return

        # Todavía sin foto: un disco con la inicial. Aparece en cuanto
        # escribes el nombre, sin pedirle nada a Instagram, y lo sustituye la
        # cara de verdad después del primer «Contar».
        self.avatar.create_oval(*caja, fill=RAISED, outline=LINE, width=1)
        if cuenta:
            self.avatar.create_text(
                lado / 2, lado / 2 + 1, text=cuenta[0].upper(), fill=DIM,
                font=(self.sans, int(lado * 0.42)))

    def _refrescar_perfil(self, cuenta: str) -> None:
        """
        Nombre y publicaciones de la cuenta, bajo el campo.

        Sale de lo que el módulo anotó al leer el perfil, no de la red: los
        dos venían dentro de la misma respuesta que «Contar» ya pedía.
        """
        estado = m.leer_estado(cuenta) if cuenta else {}
        partes = []
        # También al enseñarlo: lo que ya esté guardado de antes viene sin
        # limpiar, y no se va a volver a pedir solo por eso.
        nombre = m.limpiar_nombre(estado.get("nombre"))
        if nombre:
            partes.append(nombre)
        publicaciones = estado.get("publicaciones")
        if isinstance(publicaciones, int) and publicaciones:
            partes.append(f"{publicaciones:,}".replace(",", " ")
                          + (" publicación" if publicaciones == 1
                             else " publicaciones"))
        self.etiqueta_perfil.configure(text=", ".join(partes))

    # ------------------------------------------------------------------
    def _sugerencia(self) -> str:
        """
        Qué conviene hacer ahora, deducido del estado real.

        Es la pregunta que de verdad tiene el usuario delante de nueve
        botones. Antes solo se contestaba pasando el ratón por encima.
        """
        cuenta = limpiar_usuario(self.campo_objetivo.get())
        if not cuenta:
            # La invitación de arriba ya pide la cuenta. Repetirlo aquí sería
            # dos elementos haciendo el mismo trabajo; esto hace otro.
            return ("Pasa el ratón por cualquier acción para ver qué hace y "
                    "cuánto cuesta.")
        if not m.ARCHIVO_SESION.exists():
            return "Siguiente paso: «Importar sesión»."

        e = getattr(self, "_resumen", {})
        if e.get("pendiente"):
            return ("Quedó una descarga a medias. «Listas completas» sigue "
                    "desde donde iba.")
        if not e.get("capturas"):
            return ("Siguiente paso: «Contar», para comprobar que responde "
                    "sin gastar casi nada.")
        if e.get("incompletas") and self.campo_sospechosas.get():
            return ("CUIDADO: hay capturas incompletas y «Incluir capturas "
                    "dudosas» está activado. Desmárcalo o el análisis "
                    "inventará altas y bajas.")
        if e.get("incompletas"):
            return ("Alguna descarga salió incompleta. Repite «Listas "
                    "completas» dentro de un rato: se fusiona con lo que hay.")
        if e.get("capturas", 0) < 2:
            return ("Ya tienes una descarga. Repite «Listas completas» otro "
                    "día y podrás ver qué cambió.")
        return "Ya puedes usar «Qué cambió» y «Historial». No gastan nada."

    def _refrescar_gasto(self) -> None:
        """
        Cuánto llevas gastado hoy, siempre a la vista.

        Es el recurso escaso de esta herramienta; tenerlo escondido en un
        archivo era la razón de que los bloqueos siempre pillaran por
        sorpresa.
        """
        presupuesto = m._presupuesto()
        hechas = presupuesto.get("hechas", 0)
        tope = m.tope_diario()
        proporcion = hechas / max(tope, 1)
        color = (COLOR_ERROR if proporcion >= 0.9
                 else COLOR_AVISO if proporcion >= m.AVISO_AL else DIM)
        # Sin cadena de puntos medios y sin «bloqueo(s)»: una frase corta que
        # se lee tal cual. El paréntesis del plural es del programador, no de
        # quien está mirando si puede pulsar o no.
        texto = f"{hechas}/{tope} peticiones hoy"
        bloqueos = presupuesto.get("bloqueos", 0)
        if bloqueos:
            texto += f", {bloqueos} bloqueo{'s' if bloqueos > 1 else ''}"
        self.etiqueta_gasto.configure(text=texto, text_color=color)

    def _mostrar_sugerencia(self) -> None:
        texto = self._sugerencia()
        peligro = texto.startswith("CUIDADO")
        self.etiqueta_pista.configure(
            text=texto, text_color=COLOR_AVISO if peligro else DIM)
        self.flecha.configure(fg_color=COLOR_AVISO if peligro else ACENTO)

    def _guiar(self, accion: str) -> None:
        """
        Qué se puede hacer ahora, según lo que se acaba de hacer.

        La guía de arranque funcionó bien, así que la conversación sigue:
        en vez de dejarte delante de diez botones, cada acción termina
        diciendo cuáles tienen sentido a continuación y por qué.
        """
        e = getattr(self, "_resumen", {})
        capturas = e.get("capturas", 0)
        lineas: list[tuple[str, str | None]] = []

        if accion == "sesion":
            lineas = [
                ("Sesión lista. Ahora:", None),
                ("  «Contar» (1 petición) para comprobar que la cuenta "
                 "responde. Es lo más barato.", None),
                ("  Si algo falla, «Diagnóstico» (5) dice qué endpoint está "
                 "bloqueado.", DIM)]

        elif accion == "contar":
            if capturas:
                lineas = [("Ya sabes el tamaño actual. Compáralo con tus "
                           "capturas en «Qué cambió».", None)]
            else:
                lineas = [
                    ("Funciona. Ahora puedes:", None),
                    ("  «Listas completas» para bajar quién sigue a la cuenta "
                     "y a quién sigue ella.", None),
                    ("  «Inspeccionar campos» (1) si quieres ver antes qué "
                     "datos manda Instagram por cada persona.", DIM)]

        elif accion == "bajar":
            if capturas >= 2:
                lineas = [
                    ("Ya tienes dos descargas o más, así que:", None),
                    ("  «Qué cambió» compara las dos últimas: quién entró y "
                     "quién salió.", None),
                    ("  «Historial» va más atrás: cuándo llegó cada persona y "
                     "quién entra y sale sin parar.", None),
                    ("  Las dos son gratis: trabajan sobre lo que ya está en "
                     "disco.", DIM)]
            else:
                lineas = [
                    ("Ya tienes la primera foto. Para que sirva de algo hace "
                     "falta una segunda:", None),
                    ("  Repite «Listas completas» otro día y podrás comparar.",
                     None),
                    ("  O deja «Vigilar» programado y lo hará solo.", DIM)]

        elif accion == "vigilar_todas":
            lineas = [
                ("Lo que quedó aplazado se retomará mañana, con prioridad.",
                 DIM),
                ("  Si aplaza mucho, sigue menos cuentas o sube el tope "
                 "diario: el presupuesto se reparte entre todas.", DIM)]

        elif accion == "vigilar":
            lineas = [
                ("«Vigilar» gasta 1 petición para mirar los totales y solo "
                 "descarga si algo cambió.", DIM),
                ("Es el que conviene dejar programado a diario.", DIM)]

        elif accion == "comun":
            lineas = [
                ("El CSV con todas está en la carpeta de la primera cuenta; "
                 "«Ver tablas» lo abre.", None),
                ("  Para un cruce limpio, baja las dos cuentas el mismo "
                 "día.", DIM)]

        elif accion == "copia":
            lineas = [
                ("La copia está en la carpeta de salida; «Abrir carpeta» "
                 "te lleva.", None),
                ("  Llévala a otro disco: aquí no sirve de nada si el disco "
                 "es el que falla.", DIM),
                ("  No lleva sesiones dentro, así que se puede mover sin "
                 "cuidado.", DIM)]

        elif accion == "informe":
            lineas = [
                ("El informe está en la carpeta de la cuenta; «Abrir "
                 "carpeta» te lleva.", None),
                ("  Se abre con doble clic y lleva los datos dentro: se "
                 "puede mandar o guardar tal cual.", DIM),
                ("  No necesita internet ni le pide nada a nadie.", DIM)]

        elif accion == "comparar":
            lineas = [
                ("La lista completa de altas y bajas está en el CSV; "
                 "«Abrir carpeta» te lleva.", None),
                ("  «Historial» ve más atrás que las dos últimas capturas.",
                 DIM)]

        elif accion == "historial":
            lineas = [
                ("Si viste gente que entra y sale, «Perfiles detallados» te "
                 "cuenta quiénes son.", None),
                ("  La primera vez crea una lista con candidatos; la editas "
                 "y vuelves a pulsar.", DIM)]

        elif accion == "inspeccionar":
            lineas = [
                ("Los campos marcados con * ya se guardan en cada descarga.",
                 DIM),
                ("  Si ves alguno útil sin marcar, se puede añadir sin gastar "
                 "peticiones extra.", DIM)]

        elif accion == "contratos":
            lineas = [
                ("Se ha dejado salida/rutas.json listo para editar. Si algún "
                 "día Instagram cambia una ruta o un nombre, se arregla ahí.",
                 DIM),
                ("  Los campos que añadan no rompen nada: solo se exige lo "
                 "de arriba.", DIM),
                ("  Y aunque la descarga dejara de funcionar, «Qué cambió», "
                 "«Historial» y «Ver tablas» siguen sirviendo: no tocan la "
                 "red.", DIM)]

        elif accion == "diagnostico":
            lineas = [
                ("Lo que salga «OK» funciona. Si «Tu propia lista de "
                 "seguidos» responde, la descarga es posible.", DIM)]

        elif accion == "detalles":
            lineas = [
                ("Los perfiles quedan en detalles_<cuenta>_<fecha>.csv.", DIM),
                ("  Se saltan los ya consultados hoy, así que puedes repetir "
                 "sin gastar de más.", DIM)]

        if lineas:
            self._log("")
            for texto, color in lineas:
                self._log(texto, color)

    def accion_ayuda(self) -> None:
        """Referencia completa, sin gastar nada."""
        self.accion_limpiar()
        p = self._log

        p(f"GUÍA DE {NOMBRE.upper()}", None)
        p("")
        p("Para qué sirve", None)
        p("  Guarda una foto de quién sigue a una cuenta y a quién sigue "
          "ella.", DIM)
        p("  Repitiéndolo otro día, te dice quién entró y quién salió.", DIM)
        p("")
        p("El orden normal", None)
        p("  1. Importar sesión      una vez, o cuando caduque", DIM)
        p("  2. Contar               comprueba que todo responde", DIM)
        p("  3. Listas completas     la descarga; tarda unos minutos", DIM)
        p("  4. otro día, repetir 3", DIM)
        p("  5. Qué cambió           ya tienes con qué comparar", DIM)
        p("")
        p("Qué hace cada botón", None)
        for nombre, coste, texto in (
                ("Importar sesión", "0",
                 "toma las cookies de tu navegador; nunca pide contraseña"),
                ("Gasto de hoy", "0",
                 "cuántas peticiones llevas y en qué se han ido"),
                ("Diagnóstico", "5",
                 "prueba cada vía y dice cuál responde; úsalo si algo falla"),
                ("Contar", "1",
                 "cuántos seguidores y seguidos tiene ahora mismo"),
                ("Inspeccionar campos", "1",
                 "qué datos manda Instagram por cada persona"),
                ("Listas completas", "~50",
                 "la descarga de verdad; se puede parar y retomar"),
                ("Vigilar", "1+",
                 "mira los totales y solo descarga si cambió algo"),
                ("Qué cambió", "0",
                 "quién entró y quién salió entre las dos últimas capturas"),
                ("Historial", "0",
                 "trayectoria de cada persona a lo largo de todas"),
                ("Perfiles detallados", "1 c/u",
                 "biografía y cifras de unas pocas cuentas que tú elijas")):
            p(f"  {nombre:22} {coste:>6}   {texto}", DIM)
        p("")
        p("Ver los datos", None)
        p("  «Ver tablas» abre los CSV dentro de la aplicación, con una "
          "casilla de", DIM)
        p("  búsqueda por cada columna. Los archivos siguen en la carpeta "
          "para", DIM)
        p("  abrirlos en Excel cuando quieras.", DIM)
        p("")
        p("Lo que conviene saber", None)
        p("  Las peticiones son el recurso escaso. Instagram corta si te "
          "pasas,", DIM)
        p("  y el contador de arriba a la derecha te dice cómo vas.", DIM)
        p("  Si una descarga se corta, no pierdes nada: la próxima sigue "
          "desde ahí.", DIM)
        p("  Una captura marcada «incompleta» no se usa para comparar: daría "
          "bajas", DIM)
        p("  que nunca ocurrieron.", DIM)
        p("  «Salió» puede ser un unfollow, una cuenta borrada, suspendida o "
          "un", DIM)
        p("  bloqueo. Desde fuera se ven igual.", DIM)
        p("")
        p("Si Instagram cambia algo", None)
        p("  «Diagnóstico» dice qué vía responde y cuál cambió de forma.",
          DIM)
        p("  «Qué espera de Instagram» deja salida/rutas.json editable: "
          "rutas,", DIM)
        p("  nombres de parámetros y de campos se arreglan ahí, sin tocar "
          "código.", DIM)
        p("  Cuando algo falla se guarda un archivo fallo_*.json con el "
          "detalle", DIM)
        p("  completo. No lleva tu sesión dentro: se puede compartir.", DIM)
        p("  El análisis de lo ya descargado no necesita red: «Qué cambió», "
          "«Historial»", DIM)
        p("  y «Ver tablas» funcionan aunque Instagram deje de responder.",
          DIM)
        p("")
        p("Si algo va mal", None)
        p("  429 o «bloqueado»    espera; el propio programa se niega a "
          "insistir", DIM)
        p("  la sesión no vale    vuelve a «Importar sesión»", DIM)
        p("  Chrome o Edge        en Windows cifran las cookies; usa Firefox",
          DIM)
        p("  cuenta privada       hay que seguirla con la cuenta de la sesión",
          DIM)
        p("")
        self._mostrar_sugerencia()

    def _serie(self, tipo: str) -> list:
        """
        Cuántos había en cada captura. De los metadatos, así que es barato.

        Es el dato característico de esta herramienta: no interesa el número
        de hoy, interesa cómo se ha movido.
        """
        serie = []
        for ruta in m._capturas(tipo):
            meta = m._leer_meta(ruta)
            if meta.get("completa") is False:
                continue          # una truncada falsearía la línea
            n = meta.get("obtenidos")
            if isinstance(n, int):
                serie.append((m._fecha_de(ruta), n))
        return serie

    def _pintar_grafica(self) -> None:
        """
        Cómo se ha movido cada lista, un trazo por lista.

        Aquí es donde gasto la audacia del diseño: mirar cómo se mueve un
        número en el tiempo ES el trabajo, y el dato ya lo teníamos guardado
        sin usar.

        Las dos comparten el eje de tiempo y no la escala vertical: lo que
        hay que comparar es CUÁNDO se movió cada una, no si 300 es más que
        2.000, que ya lo dicen las cifras de al lado.
        """
        c = self.grafica
        c.delete("all")
        ancho = max(c.winfo_width(), 240)
        alto = max(c.winfo_height(), 54)

        series = {t: self._serie(t) for t in ("seguidores", "seguidos")}
        # Lo que se puede dibujar no depende del total de capturas, sino de
        # que ALGUNA lista tenga dos suyas. Con una de seguidores y una de
        # seguidos había dos capturas y ninguna línea posible, así que salía
        # «falta otra captura» dos veces mientras la banda de al lado decía
        # «capturas: 2»: parecía que la ventana se contradecía.
        if not any(len(v) >= 2 for v in series.values()):
            c.create_text(2, alto / 2, anchor="w", fill=DIM, width=ancho - 4,
                          font=(self.sans, TAM_MICRO),
                          text="con dos capturas de una misma lista se "
                               "dibuja la evolución")
            return

        # Un solo eje de tiempo para las dos filas, con todas las fechas.
        dias = [d for v in series.values()
                for d in (_a_dia(f) for f, _ in v) if d is not None]
        dominio = (min(dias), max(dias)) if dias else (0, 0)

        # Dos trazos, uno debajo del otro, cada uno con su nombre y su
        # último movimiento. Antes eran dos líneas sueltas en la misma caja,
        # sin nada que dijera cuál era cuál: dos colores sin leyenda no son
        # información, y compartir la escala vertical escondía justo los
        # cambios de tres o cuatro personas que hay que ver.

        # Las dos columnas se MIDEN. Estaban fijadas a ojo en 76 y 46 px, y
        # con Segoe UI en Windows «seguidores» ocupa más de 76: el nombre se
        # comía el texto de al lado. Medir lo resuelve para cualquier
        # tipografía y cualquier escala de pantalla.
        sans = self._fuente(self.sans, TAM_MICRO)
        mono = self._fuente(self.mono, TAM_MICRO)
        cambios = {t: v[-1][1] - v[-2][1]
                   for t, v in series.items() if len(v) >= 2}
        columna_nombre = max(sans.measure(t) for t in series) + 12
        columna_delta = max((mono.measure(f"{cambio:+d}")
                             for cambio in cambios.values()), default=0) + 12
        fila = alto / 2
        for n, (tipo, color) in enumerate((("seguidores", ACENTO),
                                           ("seguidos", ACENTO_2))):
            datos = series[tipo]
            centro = fila * n + fila / 2
            c.create_text(2, centro, anchor="w", fill=DIM,
                          font=(self.sans, TAM_MICRO), text=tipo)
            if len(datos) < 2:
                c.create_text(columna_nombre, centro, anchor="w", fill=DIM,
                              font=(self.sans, TAM_MICRO),
                              text="falta otra captura")
                continue

            puntos = _coordenadas(datos, dominio, columna_nombre,
                                  ancho - columna_delta,
                                  centro - fila * 0.30, centro + fila * 0.30)
            # Sin smooth: una curva pasa por valores que nunca se midieron.
            # Entre dos capturas no se sabe qué pasó, y un instrumento no
            # rellena ese hueco con una suposición bonita.
            c.create_line(*[v for par in puntos for v in par], fill=color,
                          width=2, capstyle="round", joinstyle="round")
            x, y = puntos[-1]
            c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color,
                          outline=PANEL, width=2)

            c.create_text(ancho - 2, centro, anchor="e", fill=TEXTO,
                          font=(self.mono, TAM_MICRO),
                          text=f"{cambios[tipo]:+d}")

    def _lectura(self, padre, columna: int, etiqueta: str):
        """Una medida de la banda: cifra grande, nombre pequeño, estado."""
        celda = ctk.CTkFrame(padre, fg_color="transparent")
        celda.grid(row=0, column=columna, sticky="nsew")
        self.celdas_marco.append(celda)

        # Filete de verdad entre medidas. Antes dejaba un hueco de 1 px
        # esperando que se viera, pero era del mismo color que el fondo:
        # el recurso que debía decir «son tres medidas» no se dibujaba.
        if columna:
            ctk.CTkFrame(celda, width=1, corner_radius=0,
                         fg_color=LINE).place(relx=0, rely=0.22,
                                              relheight=0.56)

        cifra = ctk.CTkLabel(celda, text="—", text_color=TEXTO, anchor="w",
                             font=ctk.CTkFont(self.mono, TAM_CIFRA))
        cifra.pack(fill="x", padx=(24, 20), pady=(16, 0))
        ctk.CTkLabel(celda, text=etiqueta, text_color=DIM, anchor="w",
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=(24, 20), pady=(2, 0))
        detalle = ctk.CTkLabel(celda, text="", text_color=DIM,
                               anchor="w", wraplength=200, justify="left",
                               font=ctk.CTkFont(self.sans, TAM_MICRO))
        detalle.pack(fill="x", padx=(24, 20), pady=(4, 16))
        return cifra, detalle

    def _panel_disco(self, zona) -> None:
        """
        Banda de lectura: una sola superficie dividida por filetes.

        Antes eran tres tarjetas redondeadas idénticas — el kit de tarjetas
        que aparece en cualquier panel del mundo. Las medidas de un mismo
        instrumento no son tres objetos separados: son una lectura.
        """
        banda = ctk.CTkFrame(zona, corner_radius=0, fg_color=PANEL)
        banda.grid(row=1, column=0, sticky="ew")
        for i in range(3):
            banda.grid_columnconfigure(i, weight=1, uniform="lectura")
        banda.grid_columnconfigure(3, weight=2, uniform="")

        self.celdas_marco = []
        self.celdas = {c: self._lectura(banda, i, c) for i, c in
                       enumerate(("seguidores", "seguidos", "capturas"))}
        self.banda = banda

        # Primer arranque: una invitación, no tres huecos con la misma frase
        # repetida. Una pantalla vacía es una invitación a actuar.
        self.vacio = ctk.CTkFrame(banda, fg_color="transparent")
        ctk.CTkLabel(self.vacio, text="", text_color=TEXTO, anchor="w",
                     font=ctk.CTkFont(self.sans, TAM_TITULO)).pack(
            fill="x", padx=24, pady=(20, 2))
        ctk.CTkLabel(self.vacio, text="", text_color=DIM, anchor="w",
                     justify="left",
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=24, pady=(0, 20))
        self.vacio_titulo, self.vacio_texto = self.vacio.winfo_children()

        marco_g = ctk.CTkFrame(banda, fg_color="transparent")
        marco_g.grid(row=0, column=3, sticky="nsew")
        ctk.CTkFrame(marco_g, width=1, corner_radius=0,
                     fg_color=LINE).place(relx=0, rely=0.22, relheight=0.56)
        self.celdas_marco.append(marco_g)
        ctk.CTkLabel(marco_g, text="evolución", text_color=DIM, anchor="w",
                     font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=20, pady=(14, 2))
        self.grafica = tk.Canvas(marco_g, height=56, bg=PANEL,
                                 highlightthickness=0, bd=0)
        self.grafica.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.grafica.bind("<Configure>", lambda _e: self._pintar_grafica())

        ctk.CTkFrame(zona, height=1, corner_radius=0, fg_color=LINE).grid(
            row=1, column=0, sticky="sew")

    def _contar(self, ruta) -> int:
        """Cuántos registros hay. Usa los metadatos si existen: son exactos."""
        meta = m._leer_meta(ruta)
        if isinstance(meta.get("obtenidos"), int):
            return meta["obtenidos"]
        try:
            with open(ruta, encoding="utf-8-sig") as f:
                return max(sum(1 for _ in f) - 1, 0)
        except OSError:
            return 0

    def _refrescar_cuentas(self) -> None:
        """Rellena el desplegable con las cuentas que ya sigues."""
        try:
            cuentas = m.leer_cuentas()
        except Exception:
            cuentas = []
        actual = self.campo_objetivo.get()
        if actual and actual not in cuentas:
            cuentas = cuentas + [actual]
        self.campo_objetivo.configure(values=cuentas or [""])

    def _mostrar_vacio(self, titulo: str, texto: str) -> None:
        for marco in self.celdas_marco:
            marco.grid_remove()
        self.vacio_titulo.configure(text=titulo)
        self.vacio_texto.configure(text=texto)
        self.vacio.grid(row=0, column=0, columnspan=4, sticky="nsew")

    def _mostrar_lectura(self) -> None:
        self.vacio.grid_remove()
        for i, marco in enumerate(self.celdas_marco):
            marco.grid(row=0, column=i, sticky="nsew")

    def _refrescar_disco(self) -> None:
        """Relee la carpeta. Barato: no parsea los CSV, mira los metadatos."""
        cuenta = limpiar_usuario(self.campo_objetivo.get())
        # El título dice a quién se está mirando, como cualquier programa
        # que abre documentos. Con dos ventanas abiertas o desde la barra
        # de tareas, «FocusMedia» a secas no distingue una de otra.
        self.title(f"@{cuenta} — {NOMBRE}"
                   if cuenta and cuenta != "cuenta_objetivo" else NOMBRE)
        # Aquí pasan las tres cosas que enseñan la foto: escribir el nombre
        # (esto se llama al validar el campo) y terminar «Contar» o «Listas
        # completas» (se llama al recoger el fin de la tarea).
        visible = "" if cuenta == "cuenta_objetivo" else cuenta
        self._refrescar_avatar(visible)
        self._refrescar_perfil(visible)
        self._resumen = {"capturas": 0, "pendiente": False,
                         "incompletas": False}
        if not cuenta or cuenta == "cuenta_objetivo":
            for cifra, detalle in self.celdas.values():
                cifra.configure(text="—", text_color=TEXTO)
                detalle.configure(text="", text_color=DIM)
            self._mostrar_vacio(
                "Escribe arriba la cuenta que quieres seguir",
                "Aquí verás cuántos seguidores tiene, a cuántos sigue, y "
                "cómo se mueven esos números con los días.")
            self._mostrar_sugerencia()
            return

        anterior = m.OBJETIVO
        m.OBJETIVO = cuenta
        try:
            total_capturas, primera = 0, None
            for tipo in ("seguidores", "seguidos"):
                cifra, detalle = self.celdas[tipo]
                capturas = m._capturas(tipo)
                total_capturas += len(capturas)
                if capturas and (primera is None
                                 or m._fecha_de(capturas[0]) < primera):
                    primera = m._fecha_de(capturas[0])

                pendiente = m._ruta_parcial(tipo).exists()
                if pendiente:
                    self._resumen["pendiente"] = True
                if not capturas:
                    cifra.configure(text="—", text_color=TEXTO)
                    detalle.configure(
                        text="descarga a medias, se retomará" if pendiente
                        else "sin capturas", text_color=DIM)
                    continue

                ultima = capturas[-1]
                meta = m._leer_meta(ultima)
                completa = meta.get("completa")
                cifra.configure(
                    text=f"{self._contar(ultima):,}".replace(",", " "),
                    text_color=COLOR_AVISO if completa is False else TEXTO)
                if completa is False:
                    self._resumen["incompletas"] = True
                nota = ("incompleta" if completa is False
                        else "sin metadatos" if completa is None
                        else "completa")
                if pendiente:
                    nota += " · hay descarga a medias"
                detalle.configure(text=f"{m._fecha_de(ultima)} · {nota}",
                                  text_color=COLOR_AVISO
                                  if completa is False else DIM)

            cifra, detalle = self.celdas["capturas"]
            cifra.configure(text=str(total_capturas) if total_capturas else "—",
                            text_color=TEXTO)
            if total_capturas >= 2:
                detalle.configure(text=f"desde el {primera}", text_color=DIM)
            elif total_capturas == 1:
                detalle.configure(text="con dos ya se pueden comparar",
                                  text_color=DIM)
            else:
                detalle.configure(text="sin capturas", text_color=DIM)
            self._resumen["capturas"] = total_capturas
            if total_capturas:
                self._mostrar_lectura()
            else:
                self._mostrar_vacio(
                    f"Todavía no has descargado nada de @{cuenta}",
                    "Pulsa «Contar» para comprobar que responde, y luego "
                    "«Listas completas» para guardar la primera foto.")
        finally:
            m.OBJETIVO = anterior
        self._mostrar_sugerencia()

    def _normalizar_cuenta(self) -> None:
        """
        Reescribe el campo con el nombre de usuario limpio, para que veas qué
        se entendió. Pegar el enlace del perfil es lo natural; que el campo
        lo rechace en silencio y no te lo diga hasta pulsar una acción era
        un fallo de diseño.
        """
        crudo = self.campo_objetivo.get().strip()
        if crudo == getattr(self, "_cuenta_validada", None):
            return                      # el foco cambió, el texto no
        self._cuenta_validada = crudo

        if not crudo:
            self.campo_objetivo.configure(border_color=LINE)
            self._refrescar_disco()
            return

        limpio = limpiar_usuario(crudo)
        if limpio and limpio != crudo:
            self.campo_objetivo.set(limpio)
            self._cuenta_validada = limpio
            self._log(f"Entendido: la cuenta es @{limpio}", DIM)

        self._cuenta_validada = self.campo_objetivo.get().strip()
        self.ajustes.datos["objetivo"] = self.campo_objetivo.get()
        problema = self.ajustes.valido()
        self.campo_objetivo.configure(
            border_color=COLOR_AVISO if problema else LINE)
        if problema:
            self._log(problema, COLOR_AVISO)
        elif not m.ARCHIVO_SESION.exists():
            self._log("Ahora pulsa «Importar del navegador» para tomar la "
                      "sesión. No hace falta contraseña.", DIM)
        self._refrescar_disco()

    def _aviso_navegador(self, valor: str = "") -> None:
        """Chrome y Edge cifran las cookies en Windows y suelen fallar."""
        navegador = valor or self.campo_navegador.get()
        if sys.platform == "win32" and navegador in ("chrome", "edge"):
            self._log(f"Aviso: en Windows, {navegador} cifra las cookies y "
                      "casi nunca se pueden leer. Si falla al importar la "
                      "sesión, inicia sesión en Firefox y elígelo aquí.",
                      COLOR_AVISO)

    def _refrescar_estado_sesion(self) -> None:
        """Pone en la cabecera quién está activa, según lo guardado."""
        try:
            activa = next((s for s in m.sesiones_disponibles()
                           if s["activa"]), None)
        except Exception:
            activa = None
        # El nombre va PELADO: _estado_sesion ya pone el «@» al escribirlo,
        # y el «#» delante es su forma de decir «esto es un id, no un
        # nombre». Pasarle uno ya con arroba daba «@@cuentazer».
        if not activa:
            self._estado_sesion()
        elif activa["usuario"]:
            self._estado_sesion(activa["usuario"])
        else:
            self._estado_sesion("#" + activa["clave"])

    def _estado_sesion(self, usuario: str | None = None) -> None:
        """
        Pinta quién está conectado. `usuario` va SIN arroba.

        El «@» lo pone esta función, y un «#» delante significa «esto es
        un id, no un nombre». Pasarle uno ya con arroba daba
        «@@cuentazer»: el contrato solo estaba en la cabeza de quien lo
        escribió.

        Solo se afirma lo que se sabe. Que exista el archivo no prueba que
        la sesión siga viva: eso solo lo confirma una petición real.
        """
        if usuario and usuario.startswith("#"):
            # Solo se confirmó el id: un número con @ delante parecería un
            # nombre de usuario que no existe.
            self.punto.configure(text_color=COLOR_BIEN)
            self.etiqueta_sesion.configure(
                text=f"Sesión activa, id {usuario[1:]}", text_color=TEXTO)
        elif usuario:
            self.punto.configure(text_color=COLOR_BIEN)
            # Si hay más de una guardada se dice: si no, nadie se entera de
            # que puede cambiar sin abrir el cuadro a ver qué hay.
            try:
                otras = max(0, len(m.sesiones_disponibles()) - 1)
            except Exception:
                otras = 0
            self.etiqueta_sesion.configure(
                text=f"Sesión activa como @{usuario}"
                     + (f"  (+{otras})" if otras else ""),
                text_color=TEXTO)
        elif m.ARCHIVO_SESION.exists():
            self.punto.configure(text_color=ACENTO)
            self.etiqueta_sesion.configure(text="Sesión guardada",
                                           text_color=DIM)
        else:
            self.punto.configure(text_color=DIM)
            self.etiqueta_sesion.configure(text="Sin sesión", text_color=DIM)

    def _log(self, texto: str, color: str | None = None,
             progreso: bool = False) -> None:
        if texto and texto == getattr(self, "_ultima_linea", None) \
                and not progreso:
            return                      # no repetir el mismo aviso seguido
        self._ultima_linea = texto
        etiqueta = {COLOR_ERROR: "error", COLOR_AVISO: "aviso",
                    COLOR_BIEN: "bien", DIM: "dim"}.get(color or "")
        self.consola.configure(state="normal")
        # Las líneas de progreso se reescriben en el sitio, como en una
        # terminal: si no, una descarga de 40 páginas dejaría 40 filas casi
        # idénticas y taparía lo que de verdad importa.
        if progreso and self._ultima_fue_progreso:
            self.consola.delete("end-2l linestart", "end-1l linestart")
        self.consola.insert("end", texto + "\n", etiqueta if etiqueta else ())
        self._ultima_fue_progreso = progreso
        self.consola.see("end")
        self.consola.configure(state="disabled")

    def _color_de(self, linea: str) -> str | None:
        bajo = linea.lower()
        if any(p in bajo for p in ("aviso:", "atención:", "cancelada",
                                   "sospechos", "incompleta",
                                   "cambió de forma", "otra forma")):
            return COLOR_AVISO
        if any(p in bajo for p in ("error", "no válid", "no encontrado",
                                   "cortado:", "abortado")):
            return COLOR_ERROR
        if any(p in bajo for p in ("captura guardada", "hecho.", "listo",
                                   "sesión activa", "terminado")):
            return COLOR_BIEN
        return None

    def _vaciar_cola(self) -> None:
        """Único punto donde se tocan los widgets. Corre en el hilo de Tk."""
        try:
            while True:
                tipo, dato = self.trabajador.cola.get_nowait()
                if tipo == "linea":
                    avance = leer_progreso(dato)
                    if dato.strip():
                        self._log(dato, self._color_de(dato),
                                  progreso=avance is not None)
                    if avance is not None:
                        self.barra.set(avance)
                        self.etiqueta_cifras.configure(text=dato.strip())
                        self._refrescar_gasto()
                    if "Sesión activa como @" in dato:
                        self._estado_sesion(
                            dato.split("@", 1)[1].split()[0].strip())
                    elif "Sesión activa, cuenta id " in dato:
                        self._estado_sesion(
                            "#" + dato.split("cuenta id ", 1)[1].split()[0])
                elif tipo == "inicio":
                    self._bloquear(True, "En curso")
                elif tipo == "fin":
                    self.barra.set(1)
                    self._bloquear(False, "Terminado")
                    # La cabecera aprendía quién era LEYENDO la consola,
                    # buscando la frase «Sesión activa como @». Cualquier
                    # camino que no imprimiera esa frase exacta dejaba
                    # puesto «Sin sesión» con la sesión funcionando. Se lee
                    # de lo guardado, que es donde está el dato.
                    self._refrescar_estado_sesion()
                    self._refrescar_cuentas()
                    self._refrescar_disco()
                    self._refrescar_gasto()
                    self._guiar(getattr(self, "_accion_actual", ""))
                elif tipo == "cancelado":
                    self._log("Parado. El progreso está guardado; la próxima "
                              "descarga sigue desde aquí.", COLOR_AVISO)
                    self._bloquear(False, "Parado")
                    self._refrescar_disco()
                    self._refrescar_gasto()
                elif tipo == "error":
                    self._log(dato, COLOR_ERROR)
                    self._bloquear(False, "Con errores")
                    self._refrescar_disco()
                    self._refrescar_gasto()
        except queue.Empty:
            pass
        # Se guarda el identificador para poder cancelarlo al cerrar: si no,
        # este after() se dispararía sobre widgets ya destruidos.
        self._tarea_cola = self.after(100, self._vaciar_cola)

    def _reiniciar_barra(self) -> None:
        if self.winfo_exists():
            self.barra.set(0)
            self.barra.configure(progress_color=RAISED)
            self.etiqueta_cifras.configure(text="")

    def _bloquear(self, ocupado: bool, estado: str) -> None:
        self.barra.configure(progress_color=ACENTO if ocupado else RAISED)
        for b in self.botones_accion:
            b.configure(state="disabled" if ocupado else "normal")
        for e in getattr(self, "etiquetas_coste", []):
            e.configure(text_color=APAGADO if ocupado
                        else getattr(e, "color_reposo", DIM))
        self.boton_parar.configure(
            state="normal" if ocupado else "disabled",
            text_color=COLOR_ERROR if ocupado else DIM,
            border_color=COLOR_ERROR if ocupado else LINE)
        self.etiqueta_estado.configure(
            text=estado,
            text_color=TEXTO if ocupado else DIM)
        if not ocupado:
            self._tarea_barra = self.after(1400, self._reiniciar_barra)

    # ------------------------------------------------------------------
    def _preparar(self, exigir_cuenta: bool = True) -> bool:
        """Vuelca los campos a los ajustes y valida antes de lanzar."""
        if self.trabajador.ocupado():
            self._log("Ya hay una tarea en marcha. Espera o pulsa Parar.",
                      COLOR_AVISO)
            return False

        self.ajustes.datos["objetivo"] = self.campo_objetivo.get()
        self.ajustes.datos["navegador"] = self.campo_navegador.get()
        self.ajustes.guardar()

        if exigir_cuenta:
            problema = self.ajustes.valido()
            if problema:
                self._log(problema, COLOR_ERROR)
                return False

        self.ajustes.aplicar_al_modulo()
        self.barra.set(0)
        return True

    def _lanzar(self, nombre: str, funcion, *args, accion: str = "") -> None:
        # Queda anotado qué se estaba haciendo: sin eso, un informe de error
        # dice que reventó pero no durante qué.
        registro.anotar(f"acción '{accion or nombre}'",
                        cuenta=limpiar_usuario(self.campo_objetivo.get())
                        or "-")
        self._log("")
        self._log(nombre, DIM)
        self._accion_actual = accion
        self.trabajador.lanzar(nombre, funcion, *args)

    # --- acciones -----------------------------------------------------
    def accion_sesion(self) -> None:
        if self._preparar(exigir_cuenta=False):
            self._lanzar("Importando sesión del navegador",
                         lambda: m.crear_sesion(forzar=True),
                         accion="sesion")

    def accion_pegar_sesion(self) -> None:
        """
        Pegar la sesión a mano, para cuando el navegador no la suelta.

        Chrome y Edge en Windows cifran sus cookies y casi nunca se pueden
        leer. Hasta ahora, quien usara esos navegadores se quedaba sin vía.
        """
        if self.trabajador.ocupado():
            self._log("Hay una tarea en marcha. Espera a que termine.", DIM)
            return

        ventana = ctk.CTkToplevel(self)
        ventana.title("Sesiones")
        ventana.configure(fg_color=CANVAS)
        ventana.transient(self)
        self._cabe_en_pantalla(ventana, 640, 760)

        # El pie va FUERA de lo que se desplaza y se coloca primero, para
        # que se quede con su sitio: los botones tienen que estar siempre
        # a la vista, no al final de un recorrido. Todo lo demás va dentro
        # de una zona desplazable, que es lo que faltaba.
        pie = ctk.CTkFrame(ventana, fg_color="transparent", height=62)
        pie.pack(side="bottom", fill="x", padx=22, pady=(8, 14))
        pie.pack_propagate(False)
        cuerpo = ctk.CTkScrollableFrame(ventana, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=4, pady=(14, 0))

        ctk.CTkLabel(
            cuerpo, text="Sesiones de Instagram", text_color=TEXTO,
            anchor="w", font=ctk.CTkFont(self.sans, TAM_TITULO)).pack(
            fill="x", padx=22, pady=(20, 4))

        lista = ctk.CTkFrame(cuerpo, fg_color="transparent")
        lista.pack(fill="x", padx=14)

        marcadas: dict = {}

        def pintar_lista():
            """
            Una fila por cuenta, con casilla para poder comprobarlas.

            Comprobar es lo que le pone NOMBRE a una sesión: hasta que no
            se hace, la lista son números. Por eso la casilla va aquí y no
            en otro sitio — es la acción que hace legible lo de arriba.
            """
            for hijo in lista.winfo_children():
                hijo.destroy()
            marcadas.clear()
            disponibles = m.sesiones_disponibles()
            if not disponibles:
                ctk.CTkLabel(
                    lista, anchor="w", text_color=DIM,
                    text="Todavía no hay ninguna. Búscalas abajo, o pega "
                         "una a mano.",
                    font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
                    fill="x", pady=6)
                return

            for s in disponibles:
                fila = ctk.CTkFrame(
                    lista, fg_color=RAISED if s["activa"] else "transparent",
                    corner_radius=6)
                fila.pack(fill="x", pady=2)

                casilla = ctk.CTkCheckBox(
                    fila, text="", width=22, checkbox_height=16,
                    checkbox_width=16, corner_radius=4, border_width=1,
                    fg_color=ACENTO, hover_color=ACENTO, border_color=LINE)
                casilla.pack(side="left", padx=(10, 0))
                if not s["comprobada"]:
                    casilla.select()     # lo que falta por saber, marcado
                marcadas[s["clave"]] = casilla

                texto = ctk.CTkFrame(fila, fg_color="transparent")
                texto.pack(side="left", fill="x", expand=True, pady=6)
                ctk.CTkLabel(
                    texto, anchor="w",
                    text=("●  " if s["activa"] else "○  ") + s["titulo"],
                    text_color=COLOR_BIEN if s["activa"] else TEXTO,
                    font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(fill="x")

                detalle = [s["de_donde"]] if s["de_donde"] else []
                detalle.append("comprobada" if s["comprobada"]
                               else "sin comprobar")
                ctk.CTkLabel(
                    texto, anchor="w", text="      " + " · ".join(detalle),
                    text_color=DIM,
                    font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(fill="x")

                ctk.CTkButton(
                    fila, text="Quitar", width=64, height=26,
                    corner_radius=5, fg_color="transparent",
                    hover_color=CANVAS, text_color=DIM,
                    font=ctk.CTkFont(self.sans, TAM_MICRO),
                    command=lambda c=s["clave"]: (m.quitar_sesion(c),
                                                  pintar_lista())).pack(
                    side="right", padx=(0, 10))
                # En TODAS las filas, también en la activa: «cambiar a
                # esta» y «dejarla lista para trabajar» no son lo mismo, y
                # lo segundo es lo que se quiere. La activa puede estar
                # puesta y sin comprobar, que es justo cuando la cabecera
                # dice «Sin sesión» y uno no sabe qué hacer.
                ctk.CTkButton(
                    fila, text="Conectar", width=80, height=26,
                    corner_radius=5, fg_color=SELECCION,
                    hover_color=RAISED, text_color=TEXTO,
                    font=ctk.CTkFont(self.sans, TAM_MICRO),
                    command=lambda c=s["clave"]: conectar(c)).pack(
                    side="right", padx=(0, 6))

        def marcar_todas():
            todas_puestas = all(c.get() for c in marcadas.values())
            for c in marcadas.values():
                c.deselect() if todas_puestas else c.select()

        def comprobar_marcadas():
            elegidas = [k for k, c in marcadas.items() if c.get()]
            if not elegidas:
                self._log("No hay ninguna marcada para comprobar.", DIM)
                return
            ventana.destroy()
            self._lanzar(
                "Comprobando " + m.plural(len(elegidas), "sesión",
                                          "sesiones"),
                m.cmd_sesion,
                _Args(comprobar_estas=elegidas, pegar=None, listar=False,
                      usar=None, quitar=None, buscar=False, comprobar=False,
                      etiqueta=None), accion="sesion")

        def conectar(clave):
            """
            Cambia a esa sesión y la deja lista para trabajar.

            Cambiar sin comprobar te dejaba a medias: la cabecera seguía
            diciendo «Sin sesión» y no quedaba claro si servía. Aquí las
            dos cosas van juntas, que es lo que se quiere al pulsar.
            """
            if not m.activar_sesion(clave):
                return
            quien = next((s for s in m.sesiones_disponibles()
                          if s["clave"] == clave), None)
            ventana.destroy()
            self._log("Conectando con "
                      + (quien["titulo"] if quien else clave) + "…", DIM)
            self._lanzar("Conectando", m.cmd_sesion,
                         _Args(comprobar_estas=[clave], pegar=None,
                               listar=False, usar=None, quitar=None,
                               buscar=False, comprobar=False, etiqueta=None),
                         accion="sesion")

        pintar_lista()

        acciones = ctk.CTkFrame(cuerpo, fg_color="transparent")
        acciones.pack(fill="x", padx=22, pady=(8, 0))
        ctk.CTkButton(
            acciones, text="Todas", command=marcar_todas, width=70,
            height=30, corner_radius=6, fg_color="transparent",
            hover_color=RAISED, text_color=DIM, border_width=1,
            border_color=LINE,
            font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(side="left")
        ctk.CTkButton(
            acciones, text="Comprobar las marcadas",
            command=comprobar_marcadas, height=30, corner_radius=6,
            fg_color=SELECCION, hover_color=RAISED, text_color=TEXTO,
            font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="left", padx=(8, 0))
        ctk.CTkLabel(
            acciones, text="1 petición por cada una, hasta 3 si "
                            "la primera vía no responde",
            text_color=DIM,
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            side="left", padx=(10, 0))
        ctk.CTkLabel(
            cuerpo, anchor="w", text_color=DIM, wraplength=560,
            justify="left",
            text="Comprobar una sesión descubre de qué cuenta es: hasta "
                 "entonces solo se sabe su número. «Conectar» cambia a esa "
                 "cuenta y la deja lista, y cuesta lo mismo.",
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            fill="x", padx=22, pady=(4, 0))

        def buscar():
            self._log("Mirando los navegadores del equipo…", DIM)
            self.update_idletasks()
            try:
                hallazgos = m.buscar_sesiones()
            except Exception as e:
                self._log(f"No se pudo mirar: {e}", COLOR_ERROR)
                return
            r = m.resumir_busqueda(hallazgos)
            for h in r["encontradas"]:
                self._log(f"  {h['navegador']}: sesión de la cuenta "
                          f"id {h['id']}", COLOR_BIEN)
            # Lo accionable, aparte y con qué hacer. Mezclarlo con los
            # navegadores que ni están hacía que no se distinguiera «no lo
            # tienes» de «lo tienes y no te deja».
            for h in r["accionables"]:
                self._log(f"  {h['navegador']}: "
                          + m.CONSEJOS.get(h["clase"], h["motivo"]),
                          COLOR_AVISO if h["clase"] in ("cifradas",
                                                        "bloqueado") else DIM)
            if r["ausentes"]:
                self._log("  No instalados: " + ", ".join(r["ausentes"]), DIM)
            guardadas = m.registrar_hallazgos(hallazgos)
            if guardadas:
                self._log(f"Guardadas {len(guardadas)}. La que se usa no ha "
                          "cambiado; se elige arriba.", DIM)
                pintar_lista()
            else:
                self._log("Ninguna sesión abierta encontrada. Pega una a "
                          "mano abajo.", DIM)

        ctk.CTkButton(
            cuerpo, text="Buscar en los navegadores del equipo",
            command=buscar, height=32, corner_radius=6, fg_color=SELECCION,
            hover_color=RAISED, text_color=TEXTO,
            font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            fill="x", padx=22, pady=(12, 0))
        ctk.CTkLabel(
            cuerpo, anchor="w", text_color=DIM, wraplength=560,
            justify="left",
            text="No gasta ninguna petición: lee los archivos de cookies del "
                 "propio equipo. Cada navegador puede tener una cuenta "
                 "distinta abierta.",
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            fill="x", padx=22, pady=(4, 0))

        ctk.CTkLabel(
            cuerpo, text="Añadir una a mano", text_color=TEXTO, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            fill="x", padx=22, pady=(16, 2))
        ctk.CTkLabel(
            cuerpo, anchor="w", justify="left", wraplength=560,
            text="Para cuando un navegador que SÍ tienes no suelta su "
                 "sesión, como Chrome en Windows.",
            text_color=DIM, font=ctk.CTkFont(self.sans, TAM_CUERPO)).pack(
            fill="x", padx=22, pady=(0, 10))

        # Cada campo con su rótulo encima. Antes había dos cajas seguidas y
        # la de abajo, que es la que importa, no tenía ninguno: un hueco
        # grande y en blanco del que no se sabía qué esperaba.
        ctk.CTkLabel(
            cuerpo, text="Nombre para reconocerla  ·  opcional",
            text_color=DIM, anchor="w",
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(
            fill="x", padx=22)
        etiqueta_campo = ctk.CTkEntry(
            cuerpo, height=30, corner_radius=6, fg_color=PANEL,
            border_color=LINE, text_color=TEXTO,
            placeholder_text="por ejemplo: la de Chrome",
            font=ctk.CTkFont(self.sans, TAM_CUERPO))
        etiqueta_campo.pack(fill="x", padx=22, pady=(2, 10))

        ctk.CTkLabel(
            cuerpo, anchor="w", justify="left", wraplength=560,
            text_color=DIM,
            text="Pega aquí la cookie  ·  en el navegador: F12 → Aplicación "
                 "→ Cookies → instagram.com → copia el valor de «sessionid»",
            font=ctk.CTkFont(self.sans, TAM_MICRO)).pack(fill="x", padx=22)
        caja = ctk.CTkTextbox(
            cuerpo, height=80, corner_radius=8, fg_color=PANEL,
            border_width=1, border_color=LINE, text_color=TEXTO,
            font=ctk.CTkFont(self.mono, TAM_MICRO))
        caja.pack(fill="x", padx=22, pady=(2, 0))

        aviso = ctk.CTkLabel(
            cuerpo, anchor="w", justify="left", wraplength=560,
            text="Cada cookie equivale a estar dentro de esa cuenta: no las "
                 "compartas. Se usa UNA a la vez, y cambiar de sesión no da "
                 "presupuesto nuevo: el límite es de la sesión y de la IP.",
            text_color=COLOR_AVISO, font=ctk.CTkFont(self.sans, TAM_MICRO))
        aviso.pack(fill="x", padx=22, pady=(10, 6))

        def guardar():
            texto = caja.get("1.0", "end")
            try:
                cookies = m.guardar_sesion_pegada(
                    texto, etiqueta_campo.get().strip())
            except Exception as e:
                aviso.configure(text=f"No se pudo guardar: {e}",
                                text_color=COLOR_ERROR)
                return
            if not cookies:
                aviso.configure(
                    text="La caja de abajo está vacía o no lleva una "
                         "sesión dentro. Para las de arriba no hace falta "
                         "añadir nada: ya están guardadas.",
                    text_color=COLOR_AVISO)
                return
            ventana.destroy()
            # El valor NO se escribe nunca en la consola: es la cuenta
            # entera y la consola se copia y se pega para pedir ayuda.
            quien = cookies.get("ds_user_id")
            self._log("Sesión guardada"
                      + (f" (cuenta id {quien})" if quien else "")
                      + ". Comprobando que funciona…", COLOR_BIEN)
            self._estado_sesion("#" + quien if quien else None)
            self._lanzar("Comprobando la sesión", m.cmd_sesion,
                         _Args(comprobar=True), accion="sesion")

        # «Añadir» pertenece a la caja de pegar, no al cuadro entero.
        # Puesto abajo a la derecha se leía como el botón principal, y al
        # pulsarlo con la caja vacía contestaba «ahí no hay ninguna
        # sesión» — cuando lo que se quería era confirmar lo de arriba,
        # que ya estaba guardado. Ahora cada acción está donde actúa.
        ctk.CTkButton(pie, text="Añadir esta", command=guardar, height=34,
                      corner_radius=6, fg_color=SELECCION,
                      hover_color=RAISED, text_color=TEXTO,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="left")
        ctk.CTkButton(pie, text="Cerrar", command=ventana.destroy,
                      height=34, width=100, corner_radius=6,
                      fg_color="transparent", hover_color=RAISED,
                      text_color=DIM,
                      font=ctk.CTkFont(self.sans, TAM_ACCION)).pack(
            side="right")

        self._atajos_de_ventana(ventana)
        self._hacer_navegable(ventana)
        self._pegar_sesion = ventana
        ventana.after(120, lambda: (ventana.lift(), ventana.focus_force(),
                                    caja.focus_set()))

    def accion_inspeccionar(self) -> None:
        if not self._preparar():
            return
        lista = self.campo_lista.get()
        self._lanzar("Inspeccionando campos", m.cmd_inspeccionar,
                     _Args(lista="seguidores" if lista == "ambas" else lista),
                     accion="inspeccionar")

    def accion_presupuesto(self) -> None:
        if self._preparar(exigir_cuenta=False):
            self._lanzar("Gasto de hoy", m.cmd_presupuesto, None)

    def accion_diagnostico(self) -> None:
        if self._preparar():
            self._log("Prueba cada vía por separado, una cada 5 segundos. "
                      "Sirve para saber qué está bloqueado y qué no.", DIM)
            self._lanzar("Diagnóstico", m.cmd_diagnostico, None,
                         accion="diagnostico")

    def accion_contratos(self) -> None:
        if self._preparar(exigir_cuenta=False):
            self._lanzar("Qué espera de Instagram", m.cmd_contratos,
                         _Args(crear=True), accion="contratos")

    def accion_contar(self) -> None:
        if self._preparar():
            self._lanzar("Contando", m.cmd_contar, None, accion="contar")

    def accion_vigilar(self) -> None:
        if not self._preparar():
            return
        self._lanzar("Vigilando", m.cmd_vigilar, _Args(
            umbral=m.UMBRAL_CAMBIO,
            max_dias=m.MAX_DIAS_SIN_BAJAR,
            solo_mirar=False), accion="vigilar")

    def accion_vigilar_todas(self) -> None:
        if not self._preparar(exigir_cuenta=False):
            return
        cuentas = m.leer_cuentas()
        if not cuentas:
            self._log("Todavía no sigues ninguna cuenta. Se registran solas "
                      "al descargarlas por primera vez.", COLOR_AVISO)
            return
        self._log(f"{len(cuentas)} cuentas: {', '.join(cuentas[:8])}"
                  + ("..." if len(cuentas) > 8 else ""), DIM)
        self._log("Se miran una a una (1 petición cada una) y solo se "
                  "descargan las que cambiaron, mientras quede presupuesto.",
                  DIM)
        self._lanzar("Vigilando todas", m.cmd_vigilar, _Args(
            umbral=m.UMBRAL_CAMBIO,
            max_dias=m.MAX_DIAS_SIN_BAJAR,
            solo_mirar=False, todas=True), accion="vigilar_todas")

    def accion_bajar(self) -> None:
        if not self._preparar():
            return
        self._log("Puede tardar. Se puede parar cuando quieras: el progreso "
                  "se guarda y la próxima vez sigue desde ahí.", DIM)
        self._lanzar("Descargando listas", m.cmd_bajar,
                     _Args(lista=self.campo_lista.get()), accion="bajar")

    def accion_comparar(self) -> None:
        if self._preparar():
            self._lanzar("Comparando capturas", m.cmd_comparar, _Args(
                totales=False, historico=False,
                forzar=bool(self.campo_sospechosas.get())),
                accion="comparar")

    def accion_historial(self) -> None:
        if self._preparar():
            self._lanzar("Reconstruyendo el historial", m.cmd_historial,
                         _Args(
                             lista=self.campo_lista.get(),
                             min_entradas=int(
                                 self.ajustes.datos["min_entradas"]),
                             incluir_sospechosas=bool(
                                 self.campo_sospechosas.get())),
                         accion="historial")

    def accion_copia(self) -> None:
        """
        Guarda los datos de la cuenta en un zip.

        Restaurar NO está aquí a propósito: puede pisar archivos, y las
        cosas que borran o sobrescriben no van en un botón. Mismo criterio
        que 'podar'. Se hace desde la línea de órdenes, donde hay que
        escribir --reemplazar para que pise algo.
        """
        if not self._preparar():
            return
        self._lanzar("Guardando una copia", m.cmd_copia,
                     _Args(en=None, restaurar=None, reemplazar=False,
                           cuenta=None), accion="copia")

    def accion_informe(self) -> None:
        if self._preparar():
            self._lanzar("Generando el informe", m.cmd_informe, _Args(),
                         accion="informe")

    def accion_detalles(self) -> None:
        """
        Lo primero es enseñar el coste. Este comando gasta una petición por
        cuenta contra el endpoint que ya provocó un 429; que se lance sin
        que sepas cuántas van a salir sería una trampa.
        """
        if not self._preparar():
            return
        self.ajustes.aplicar_al_modulo()

        if not m._ruta_vigilancia().exists():
            self._lanzar("Creando la lista de vigilancia", m.cmd_detalles,
                         _Args(crear=True, solo_listar=False))
            self._log("Abre el archivo, deja solo las cuentas que te "
                      "interesen y vuelve a pulsar. Botón «Abrir carpeta».",
                      COLOR_AVISO)
            return

        cuentas, avisos = m.leer_lista_vigilancia()
        for a in avisos:
            self._log(f"Aviso: {a}", COLOR_AVISO)
        if not cuentas:
            self._log("La lista está vacía. Ábrela y añade cuentas.",
                      COLOR_AVISO)
            return

        ya = {f["username"].lower() for f in m._leer_csv(m._ruta_detalles())
              if f.get("username")}
        faltan = [c for c in cuentas if c.lower() not in ya]
        if not faltan:
            self._log("Ya están todas consultadas hoy. No hace falta gastar "
                      "nada.", COLOR_BIEN)
            return

        self._log(f"Van a salir {len(faltan)} peticiones, una por cuenta, "
                  f"con pausas de {m.PAUSA_DETALLE_MIN:.0f}-"
                  f"{m.PAUSA_DETALLE_MAX:.0f} s. Puedes parar cuando quieras.",
                  COLOR_AVISO)
        self._lanzar("Consultando perfiles", m.cmd_detalles,
                     _Args(crear=False, solo_listar=False), accion="detalles")

    def accion_parar(self) -> None:
        self.trabajador.cancelar()
        self.etiqueta_estado.configure(text="Parando")
        self._log("Parando en cuanto termine la página en curso.", COLOR_AVISO)

    def accion_tablas(self) -> None:
        """
        Abre el visor. Si ya está abierto, lo trae al frente en vez de
        abrir una segunda: dos ventanas iguales solo confunden.
        """
        ventana = getattr(self, "_visor", None)
        if ventana is not None and ventana.winfo_exists():
            ventana._refrescar_archivos()
            ventana.lift()
            ventana.focus()
            return
        self._visor = VentanaTabla(self, self.sans, self.mono)

    def accion_limpiar(self) -> None:
        self.consola.configure(state="normal")
        self.consola.delete("1.0", "end")
        self.consola.configure(state="disabled")
        self._ultima_fue_progreso = False

    def accion_abrir_carpeta(self) -> None:
        """
        Abre la carpeta de la cuenta, o salida/ si todavía no hay ninguna.

        Cada cuenta tiene la suya; llevar siempre a la raíz obligaría a
        buscar entre todas para llegar a lo que se acaba de descargar.
        """
        self.ajustes.aplicar_al_modulo()
        cuenta = limpiar_usuario(self.campo_objetivo.get())
        propia = m.carpeta_cuenta(cuenta) if cuenta else None
        carpeta = propia if propia and propia.exists() else m.CARPETA
        carpeta.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import os
                os.startfile(carpeta)               # noqa: S606
            else:
                import subprocess
                subprocess.Popen(
                    ["open" if sys.platform == "darwin" else "xdg-open",
                     str(carpeta)])
        except Exception:
            self._log(f"Carpeta: {carpeta}", DIM)

    def _cerrar(self) -> None:
        # Si hay una descarga en marcha, se cancela y se le dan unos segundos
        # para que cierre el CSV y guarde el cursor. Sin esta espera, la
        # última página escrita podría quedar a medias.
        if self.trabajador.ocupado():
            self.etiqueta_estado.configure(text="Cerrando")
            self.update_idletasks()
            self.trabajador.cancelar()
            self.trabajador.esperar(3.0)

        visor = getattr(self, "_visor", None)
        if visor is not None and visor.winfo_exists():
            visor.destroy()

        for tarea in (getattr(self, "_tarea_cola", None),
                      getattr(self, "_tarea_barra", None)):
            if tarea:
                try:
                    self.after_cancel(tarea)
                except Exception:
                    pass

        self.ajustes.datos["objetivo"] = self.campo_objetivo.get()
        self.ajustes.datos["navegador"] = self.campo_navegador.get()
        self.ajustes.guardar()
        self.destroy()


class _Args:
    """Imita el objeto de argparse que esperan los comandos del módulo."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def main() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    Ventana().mainloop()


if __name__ == "__main__":
    main()
