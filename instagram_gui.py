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

import json
import csv
import queue
import re
import tkinter as tk
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

    CAMPOS = {
        "objetivo": "cuenta_objetivo",
        "navegador": "firefox",
        "umbral": 1,
        "max_dias": 7,
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
            self.ruta.write_text(json.dumps(self.datos, indent=2),
                                 encoding="utf-8")
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
TEXTO = "#DDE4EE"
DIM = "#6F7D91"
ACENTO = "#4FB3D9"      # solo para lo que mide: progreso y gráfica
COLOR_BIEN = "#63C68A"
COLOR_AVISO = "#E0A93F"
COLOR_ERROR = "#EB6A63"


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
# VISOR DE TABLAS
# ======================================================================

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

    # ------------------------------------------------------------------
    def _barra(self) -> None:
        barra = ctk.CTkFrame(self, corner_radius=0, fg_color=PANEL, height=56)
        barra.grid(row=0, column=0, sticky="ew")
        barra.grid_columnconfigure(1, weight=1)
        barra.grid_propagate(False)

        ctk.CTkLabel(barra, text="Archivo", text_color=DIM,
                     font=ctk.CTkFont(self.sans, 12)).grid(
            row=0, column=0, padx=(16, 10), pady=14)

        self.selector = ctk.CTkComboBox(
            barra, values=[], height=30, corner_radius=6, fg_color=CANVAS,
            border_color=LINE, text_color=TEXTO, button_color=CANVAS,
            button_hover_color=RAISED, dropdown_fg_color=RAISED,
            dropdown_text_color=TEXTO, dropdown_hover_color=PANEL,
            command=lambda _v: self._cargar(),
            font=ctk.CTkFont(self.sans, 12))
        self.selector.grid(row=0, column=1, sticky="ew", padx=(0, 14))

        for texto, orden in (("Recargar", self._refrescar_archivos),
                             ("Limpiar filtros", self._limpiar_filtros)):
            ctk.CTkButton(barra, text=texto, command=orden, width=110,
                          height=30, corner_radius=6, fg_color="transparent",
                          border_width=1, border_color=LINE, text_color=DIM,
                          hover_color=RAISED,
                          font=ctk.CTkFont(self.sans, 11)).grid(
                row=0, column=2 if texto == "Recargar" else 3, padx=(0, 8))

        self.etiqueta_filas = ctk.CTkLabel(
            barra, text="", text_color=DIM,
            font=ctk.CTkFont(self.mono, 11))
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
                         borderwidth=0, rowheight=24,
                         font=(self.mono, 10))
        estilo.configure("Tabla.Treeview.Heading", background=RAISED,
                         foreground=TEXTO, borderwidth=0, relief="flat",
                         font=(self.sans, 10, "bold"))
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
        """CSV de la carpeta, los de la cuenta actual primero."""
        try:
            todos = sorted(m.CARPETA.glob("*.csv"),
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
        for i, col in enumerate(self.columnas):
            ancho = 260 if col in ("biografia", "enlace") else 150
            self.arbol.heading(col, text=col, anchor="w",
                               command=lambda c=col: self._ordenar(c))
            self.arbol.column(col, width=ancho, minwidth=70, anchor="w")

            self.marco_filtros.grid_columnconfigure(i, weight=1)
            caja = ctk.CTkEntry(
                self.marco_filtros, height=28, corner_radius=6,
                fg_color=PANEL, border_color=LINE, text_color=TEXTO,
                placeholder_text=f"buscar en {col}",
                font=ctk.CTkFont(self.mono, 11))
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
        for fila in visibles:
            self.arbol.insert("", "end",
                              values=[fila.get(c, "") for c in self.columnas])
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
        self._aviso_navegador()

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

    # ------------------------------------------------------------------
    def _cabecera(self) -> None:
        barra = ctk.CTkFrame(self, height=52, corner_radius=0,
                             fg_color=PANEL, border_width=0)
        barra.grid(row=0, column=0, columnspan=2, sticky="ew")
        barra.grid_columnconfigure(1, weight=1)
        barra.grid_propagate(False)

        titulo = ctk.CTkFrame(barra, fg_color="transparent")
        titulo.grid(row=0, column=0, padx=(20, 0), pady=10, sticky="w")

        marca = CARPETA_MARCA / "focusmedia_64.png"
        if marca.exists():
            try:
                from PIL import Image
                self._marca = ctk.CTkImage(Image.open(marca), size=(26, 26))
                ctk.CTkLabel(titulo, image=self._marca, text="").pack(
                    side="left", padx=(0, 10))
            except Exception:
                pass                 # sin Pillow, solo el nombre

        # Sin coletilla descriptiva: la ventana entera ya va de eso, y
        # quitar lo que no hace ningún trabajo es la mitad del diseño.
        ctk.CTkLabel(titulo, text=NOMBRE, text_color=TEXTO,
                     font=ctk.CTkFont(self.sans, 17, weight="bold")).pack(
            side="left")

        derecha = ctk.CTkFrame(barra, fg_color="transparent")
        derecha.grid(row=0, column=2, padx=22, sticky="e")
        self.etiqueta_gasto = ctk.CTkLabel(
            derecha, text="", text_color=DIM,
            font=ctk.CTkFont(self.mono, 11))
        self.etiqueta_gasto.pack(side="left", padx=(0, 18))
        self.punto = ctk.CTkLabel(derecha, text="\u25cf", text_color=DIM,
                                  font=ctk.CTkFont(self.sans, 13))
        self.punto.pack(side="left", padx=(0, 7))
        self.etiqueta_sesion = ctk.CTkLabel(
            derecha, text="", text_color=DIM,
            font=ctk.CTkFont(self.sans, 12))
        self.etiqueta_sesion.pack(side="left")

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
            text_color=TEXTO, text_color_disabled="#38424F",
            font=ctk.CTkFont(self.sans, 13))
        b.place(x=0, y=0, relwidth=1, relheight=1)

        # Marca de acento a la izquierda al pasar el ratón: un instrumento
        # señala, no ilumina un rectángulo entero.
        marca = ctk.CTkFrame(fila, width=3, height=20, corner_radius=0,
                             fg_color="transparent")
        marca.place(x=0, y=6)

        etiqueta = ctk.CTkLabel(fila, text=coste, text_color=DIM,
                                font=ctk.CTkFont(self.mono, 10))
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
        ctk.CTkLabel(padre, text=titulo, text_color=TEXTO, anchor="w",
                     font=ctk.CTkFont(self.sans, 12, weight="bold")).pack(
            fill="x", padx=20, pady=(11, 0))
        ctk.CTkLabel(padre, text=explicacion, text_color=DIM, anchor="w",
                     wraplength=192, justify="left",
                     font=ctk.CTkFont(self.sans, 10)).pack(
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
            font=ctk.CTkFont(self.sans, 13), state="disabled")
        self.boton_parar.pack(fill="x")

        # Las acciones van en un área desplazable: con la ventana pequeña,
        # antes quedaban fuera del alcance sin manera de llegar a ellas.
        lateral = ctk.CTkScrollableFrame(
            marco, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=LINE, scrollbar_button_hover_color=RAISED)
        lateral.pack(side="top", fill="both", expand=True)

        ctk.CTkLabel(lateral, text="Los números son peticiones a Instagram.",
                     text_color=DIM, anchor="w", wraplength=192,
                     justify="left", font=ctk.CTkFont(self.sans, 10)).pack(
            fill="x", padx=20, pady=(10, 2))

        self._boton_lateral(lateral, "Guía y ayuda", self.accion_ayuda,
                            "Qué hace cada cosa, en qué orden, y qué mirar "
                            "si algo falla. No gasta nada.", "0")

        self._grupo(lateral, "Conectar", "usa la sesión de tu navegador")
        self._boton_lateral(lateral, "Importar sesión", self.accion_sesion,
                            "Toma las cookies de tu navegador. No pide "
                            "contraseña ni la guarda en ningún sitio.",
                            "0")
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
        franja.grid_columnconfigure(1, weight=3)
        franja.grid_columnconfigure(4, weight=2)

        ctk.CTkLabel(franja, text="Cuenta", text_color=DIM,
                     font=ctk.CTkFont(self.sans, 12)).grid(
            row=0, column=0, padx=(22, 10), pady=(18, 10), sticky="w")
        # Desplegable editable: se eligen las cuentas ya seguidas, o se
        # escribe una nueva. Escribir a mano el nombre cada vez era la
        # única forma de cambiar de objetivo.
        self.campo_objetivo = ctk.CTkComboBox(
            franja, values=[], height=32, corner_radius=6, fg_color=RAISED,
            border_color=LINE, text_color=TEXTO, button_color=PANEL,
            button_hover_color=RAISED, dropdown_fg_color=RAISED,
            dropdown_text_color=TEXTO, dropdown_hover_color=PANEL,
            command=lambda _v: self._normalizar_cuenta(),
            font=ctk.CTkFont(self.mono, 13))
        inicial = str(self.ajustes.datos["objetivo"])
        # 'cuenta_objetivo' es el valor de relleno del módulo, no algo que
        # el usuario deba ver ni corregir.
        self.campo_objetivo.set("" if inicial == "cuenta_objetivo" else inicial)
        self.campo_objetivo.grid(row=0, column=1, padx=(0, 22), sticky="ew")
        for evento in ("<FocusOut>", "<Return>"):
            self.campo_objetivo.bind(evento,
                                     lambda _e: self._normalizar_cuenta())

        ctk.CTkLabel(franja, text="Listas", text_color=DIM,
                     font=ctk.CTkFont(self.sans, 12)).grid(
            row=0, column=2, padx=(0, 10), sticky="w")
        self.campo_lista = ctk.CTkSegmentedButton(
            franja, values=["ambas", "seguidores", "seguidos"], height=32,
            corner_radius=6, fg_color=PANEL, selected_color=RAISED,
            selected_hover_color=RAISED, unselected_color=PANEL,
            unselected_hover_color=RAISED, text_color=TEXTO,
            border_width=1, font=ctk.CTkFont(self.sans, 12))
        self.campo_lista.set("ambas")
        self.campo_lista.grid(row=0, column=3, padx=(0, 22), sticky="w")

        ctk.CTkLabel(franja, text="Navegador", text_color=DIM,
                     font=ctk.CTkFont(self.sans, 12)).grid(
            row=0, column=4, padx=(0, 10), sticky="e")
        self.campo_navegador = ctk.CTkOptionMenu(
            franja, height=32, corner_radius=6, width=124,
            values=["firefox", "chrome", "chromium", "edge", "brave",
                    "opera", "opera_gx", "vivaldi", "librewolf", "safari",
                    "arc"],
            fg_color=PANEL, button_color=PANEL, button_hover_color=RAISED,
            text_color=TEXTO, font=ctk.CTkFont(self.sans, 12),
            command=self._aviso_navegador)
        self.campo_navegador.set(str(self.ajustes.datos["navegador"]))
        self.campo_navegador.grid(row=0, column=5, padx=(0, 22), sticky="e")

        self.campo_sospechosas = ctk.CTkCheckBox(
            franja, text="Incluir capturas dudosas en el análisis",
            checkbox_height=16, checkbox_width=16, corner_radius=4,
            border_width=1, fg_color=ACENTO, hover_color=ACENTO,
            border_color=LINE, text_color=DIM,
            font=ctk.CTkFont(self.sans, 12))
        self.campo_sospechosas.grid(row=1, column=0, columnspan=4,
                                    padx=(22, 0), pady=(0, 16), sticky="w")

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
            font=ctk.CTkFont(self.sans, 12))
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
            font=ctk.CTkFont(self.sans, 12))
        self.etiqueta_estado.grid(row=0, column=0, sticky="w")

        for texto, orden in (("Ver tablas", self.accion_tablas),
                             ("Limpiar", self.accion_limpiar),
                             ("Abrir carpeta", self.accion_abrir_carpeta)):
            ctk.CTkButton(titulo, text=texto, command=orden, width=94,
                          height=26, corner_radius=6, fg_color="transparent",
                          hover_color=RAISED, text_color=DIM, border_width=1,
                          border_color=LINE,
                          font=ctk.CTkFont(self.sans, 11)).grid(
                row=0, column={"Ver tablas": 1, "Limpiar": 2}.get(texto, 3),
                padx=(0, 6))

        self.consola = ctk.CTkTextbox(
            marco, wrap="word", corner_radius=0, fg_color=PANEL,
            text_color=TEXTO, border_width=0, activate_scrollbars=True,
            font=ctk.CTkFont(self.mono, 12))
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
            font=ctk.CTkFont(self.mono, 11))
        self.etiqueta_cifras.grid(row=0, column=1, sticky="e")

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
        hechas = m._presupuesto().get("hechas", 0)
        proporcion = hechas / max(m.TOPE_DIARIO, 1)
        color = (COLOR_ERROR if proporcion >= 0.9
                 else COLOR_AVISO if proporcion >= m.AVISO_AL else DIM)
        texto = f"{hechas}/{m.TOPE_DIARIO} hoy"
        if m._presupuesto().get("bloqueos"):
            texto += f"  ·  {m._presupuesto()['bloqueos']} bloqueo(s)"
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
        La evolución de ambas listas en un trazo pequeño.

        Aquí es donde gasto la audacia del diseño: mirar cómo se mueve un
        número en el tiempo ES el trabajo, y el dato ya lo teníamos guardado
        sin usar.
        """
        c = self.grafica
        c.delete("all")
        ancho = max(c.winfo_width(), 220)
        alto = max(c.winfo_height(), 54)

        series = {t: self._serie(t) for t in ("seguidores", "seguidos")}
        puntos_totales = sum(len(v) for v in series.values())

        if puntos_totales < 2:
            c.create_text(6, alto / 2, anchor="w", fill=DIM,
                          font=(self.sans, 10),
                          text="con dos capturas se dibuja la evolución")
            return

        todos = [n for v in series.values() for _, n in v]
        bajo, alto_v = min(todos), max(todos)
        rango = max(alto_v - bajo, 1)
        margen = 10

        for tipo, color in (("seguidores", ACENTO), ("seguidos", "#8C7BD8")):
            datos = series[tipo]
            if len(datos) < 2:
                continue
            paso = (ancho - margen - 14) / (len(datos) - 1)
            coords = []
            for i, (_, n) in enumerate(datos):
                x = margen + i * paso
                y = alto - margen - (n - bajo) / rango * (alto - margen * 2)
                coords += [x, y]
            c.create_line(*coords, fill=color, width=2,
                          capstyle="round", joinstyle="round",
                          smooth=True)
            # El último punto marcado: es el valor de ahora.
            c.create_oval(coords[-2] - 3, coords[-1] - 3,
                          coords[-2] + 3, coords[-1] + 3,
                          fill=color, outline=PANEL, width=2)

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
                             font=ctk.CTkFont(self.mono, 34))
        cifra.pack(fill="x", padx=(24, 20), pady=(16, 0))
        ctk.CTkLabel(celda, text=etiqueta, text_color=DIM, anchor="w",
                     font=ctk.CTkFont(self.sans, 12)).pack(
            fill="x", padx=(24, 20), pady=(2, 0))
        detalle = ctk.CTkLabel(celda, text="", text_color=DIM,
                               anchor="w", wraplength=200, justify="left",
                               font=ctk.CTkFont(self.sans, 11))
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
                     font=ctk.CTkFont(self.sans, 15)).pack(
            fill="x", padx=24, pady=(20, 2))
        ctk.CTkLabel(self.vacio, text="", text_color=DIM, anchor="w",
                     justify="left",
                     font=ctk.CTkFont(self.sans, 12)).pack(
            fill="x", padx=24, pady=(0, 20))
        self.vacio_titulo, self.vacio_texto = self.vacio.winfo_children()

        marco_g = ctk.CTkFrame(banda, fg_color="transparent")
        marco_g.grid(row=0, column=3, sticky="nsew")
        ctk.CTkFrame(marco_g, width=1, corner_radius=0,
                     fg_color=LINE).place(relx=0, rely=0.22, relheight=0.56)
        self.celdas_marco.append(marco_g)
        ctk.CTkLabel(marco_g, text="evolución", text_color=DIM, anchor="w",
                     font=ctk.CTkFont(self.sans, 12)).pack(
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

    def _estado_sesion(self, usuario: str | None = None) -> None:
        """
        Solo se afirma lo que se sabe. Que exista el archivo no prueba que
        la sesión siga viva: eso solo lo confirma una petición real.
        """
        if usuario and usuario.startswith("#"):
            # Solo se confirmó el id: un número con @ delante parecería un
            # nombre de usuario que no existe.
            self.punto.configure(text_color=COLOR_BIEN)
            self.etiqueta_sesion.configure(
                text=f"Sesión activa · id {usuario[1:]}", text_color=TEXTO)
        elif usuario:
            self.punto.configure(text_color=COLOR_BIEN)
            self.etiqueta_sesion.configure(text=f"Sesión activa · @{usuario}",
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
            e.configure(text_color="#3A4454" if ocupado else DIM)
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
            umbral=int(self.ajustes.datos["umbral"]),
            max_dias=int(self.ajustes.datos["max_dias"]),
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
            umbral=int(self.ajustes.datos["umbral"]),
            max_dias=int(self.ajustes.datos["max_dias"]),
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
        self.ajustes.aplicar_al_modulo()
        carpeta = m.CARPETA
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
