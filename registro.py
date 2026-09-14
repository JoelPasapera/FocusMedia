#!/usr/bin/env python3
"""
registro.py  ·  qué ha pasado, para poder arreglar lo que no se ve

Hasta ahora había `fallo_*.json` para cuando Instagram cambia de forma, que
está bien pensado y se puede compartir. Pero una excepción inesperada **en
la ventana** no dejaba rastro: Tk se traga los errores de sus callbacks y
los escribe en stderr, y en una ventana sin consola —o en un .exe— eso es
el vacío. Se rompía algo, la persona veía que no pasaba nada, y no había
forma de saber qué.

Tres decisiones
---------------
1. **Nunca escribe una cookie.** El registro es justo lo que alguien copia
   y manda para pedir ayuda. Un `sessionid` ahí dentro es la cuenta entera
   en manos de quien lo lea. Todo lo que se anota pasa por
   `limpiar_secretos()`, que es una función pura y por eso se puede
   comprobar de verdad.

2. **Rota por tamaño.** Un registro que crece sin freno acaba ocupando
   gigas o, peor, se borra entero de vez en cuando y con él lo que hacía
   falta. Cinco archivos de un mega: siempre hay historia reciente y nunca
   pasa de cinco megas.

3. **Nunca tumba el programa.** Si no se puede escribir el registro, el
   trabajo sigue. Un sistema de diagnóstico que rompe lo que vigila no es
   un sistema de diagnóstico.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import threading
import traceback
from pathlib import Path

ARCHIVO = "registro.log"
TAMANO = 1_000_000               # un mega por archivo
COPIAS = 4                       # y cuatro anteriores: cinco megas de tope
FORMATO = "%Y-%m-%d %H:%M:%S"

_LOG = logging.getLogger("focusmedia")
_RUTA: Path | None = None
_ENGANCHADO = False
_AL_FALLAR = None

# Lo que no puede salir nunca. El valor de la cookie se sustituye entero:
# no vale con acortarlo, porque un trozo de sessionid sigue siendo una
# pista y no sirve para nada al depurar.
_SECRETOS = (
    # 'ds_user_id' NO está aquí a propósito: es el número de la cuenta, no
    # abre nada, y es justo lo que hace falta para saber de quién era el
    # error. La consola ya lo enseña por lo mismo.
    re.compile(r"\b(sessionid|csrftoken|mid|ig_did)"
               r"(\s*[=:]\s*)(['\"]?)([^;,\s'\"}]+)", re.I),
    # Un sessionid suelto, sin su nombre delante: dígitos y el separador.
    re.compile(r"\b\d{5,}%3A[A-Za-z0-9_\-%]{6,}"),
    re.compile(r"\b\d{5,}:[A-Za-z0-9_\-]{10,}"),
)


def limpiar_secretos(texto: str) -> str:
    """
    Quita de un texto cualquier cosa que abra una sesión. Función pura.

    Se le pasa TODO lo que se escribe, incluidas las trazas de error: una
    excepción de `requests` puede llevar la cabecera entera dentro.
    """
    if not texto:
        return ""
    limpio = _SECRETOS[0].sub(r"\1\2\3<oculto>", str(texto))
    for patron in _SECRETOS[1:]:
        limpio = patron.sub("<oculto>", limpio)
    return limpio


class _Filtro(logging.Filter):
    """Limpia el mensaje justo antes de escribirlo, pase por donde pase."""

    def filter(self, entrada: logging.LogRecord) -> bool:
        entrada.msg = limpiar_secretos(entrada.getMessage())
        entrada.args = ()
        if entrada.exc_info and entrada.exc_info[0] is not None:
            entrada.exc_text = limpiar_secretos(
                "".join(traceback.format_exception(*entrada.exc_info)))
        entrada.exc_info = None
        return True


def arrancar(carpeta: Path, depurar: bool = False) -> Path | None:
    """Deja el registro listo. Devuelve su ruta, o None si no se pudo."""
    global _RUTA
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / ARCHIVO
        _LOG.handlers.clear()
        _LOG.setLevel(logging.DEBUG if depurar else logging.INFO)
        _LOG.propagate = False
        salida = logging.handlers.RotatingFileHandler(
            ruta, maxBytes=TAMANO, backupCount=COPIAS, encoding="utf-8")
        salida.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt=FORMATO))
        salida.addFilter(_Filtro())
        _LOG.addHandler(salida)
        _RUTA = ruta
        return ruta
    except (OSError, ValueError):
        _RUTA = None
        return None


def ruta() -> Path | None:
    return _RUTA


def anotar(mensaje: str, nivel: str = "info", **extra) -> None:
    """Escribe una línea. Nunca lanza."""
    try:
        if extra:
            mensaje += "  " + "  ".join(f"{k}={v}" for k, v in extra.items())
        getattr(_LOG, nivel, _LOG.info)(mensaje)
    except Exception:
        pass


def excepcion(contexto: str, datos=None) -> None:
    """
    Anota una excepción con su traza.

    `datos` es un (tipo, valor, traza) ya recogido. Tk se lo pasa a su
    manejador, y usar ese es más fiable que preguntarle a `sys.exc_info()`
    qué se está tratando ahora mismo.
    """
    try:
        _LOG.error(contexto, exc_info=datos or sys.exc_info())
    except Exception:
        pass


def instalar_enganches(al_fallar=None) -> None:
    """
    Recoge los errores que hoy se pierden: los de fuera de todo try.

    Tres sitios, y el segundo es el que faltaba de verdad:

    - `sys.excepthook`, para la línea de órdenes.
    - `threading.excepthook`, para el hilo de trabajo.
    - El de Tk se instala aparte, desde la ventana, porque hay que
      engancharlo al objeto ventana y aquí no se importa tkinter.

    `al_fallar` recibe un resumen corto para poder enseñárselo a quien esté
    delante: un registro que solo escribe en un archivo que nadie abre no
    resuelve nada.
    """
    global _ENGANCHADO, _AL_FALLAR
    _AL_FALLAR = al_fallar
    if _ENGANCHADO:
        # Ya están puestos. Volver a ponerlos los ENCADENA sobre los de
        # antes, y entonces un solo error se anota tantas veces como
        # ventanas se hayan abierto en este proceso.
        return
    _ENGANCHADO = True
    anterior = sys.excepthook

    def mio(tipo, valor, traza):
        try:
            _LOG.error("error no recogido",
                       exc_info=(tipo, valor, traza))
            if _AL_FALLAR:
                _AL_FALLAR(f"{tipo.__name__}: {limpiar_secretos(valor)}")
        except Exception:
            pass
        anterior(tipo, valor, traza)

    sys.excepthook = mio

    def en_hilo(datos):
        try:
            _LOG.error(f"error no recogido en el hilo {datos.thread.name}",
                       exc_info=(datos.exc_type, datos.exc_value,
                                 datos.exc_traceback))
            if _AL_FALLAR:
                _AL_FALLAR(f"{datos.exc_type.__name__}: "
                           f"{limpiar_secretos(datos.exc_value)}")
        except Exception:
            pass

    threading.excepthook = en_hilo


def leer(maximo: int = 800) -> list:
    """
    Las últimas entradas, ya troceadas: {sello, nivel, de, mensaje}.

    Lee también las copias rotadas, de la más vieja a la más nueva, para
    que un error de hace tres días no desaparezca por haber trabajado
    mucho ayer.
    """
    if not _RUTA:
        return []
    textos = []
    for i in range(COPIAS, 0, -1):
        copia = _RUTA.with_name(f"{_RUTA.name}.{i}")
        if copia.exists():
            textos.append(_leer_archivo(copia))
    textos.append(_leer_archivo(_RUTA))

    entradas = []
    for linea in "\n".join(textos).splitlines():
        trozos = linea.split(" | ", 3)
        if len(trozos) == 4 and re.match(r"^\d{4}-\d\d-\d\d ", trozos[0]):
            entradas.append({"sello": trozos[0], "nivel": trozos[1].strip(),
                             "de": trozos[2].strip(), "mensaje": trozos[3]})
        elif entradas:
            # Las trazas van en varias líneas: son parte de la anterior.
            entradas[-1]["mensaje"] += "\n" + linea
    return entradas[-maximo:]


def _leer_archivo(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def resumen(entradas: list) -> dict:
    """Cuántas de cada nivel, para poder decirlo en una línea."""
    cuenta = {}
    for e in entradas:
        cuenta[e["nivel"]] = cuenta.get(e["nivel"], 0) + 1
    return cuenta
