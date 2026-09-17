#!/usr/bin/env python3
"""
consola.py  ·  que se pueda leer y mandar lo que sale al ejecutar

En Windows, doble clic en un `.py` abre una consola, ejecuta y **la cierra
en cuanto termina**. Da igual lo que haya salido: no se lee y no se puede
copiar.

Dos cosas, no una. La pausa deja mirar, pero 53 pruebas no caben en una
pantalla y lo de arriba se pierde igual. Así que además se guarda todo en
un archivo, y al final se dice dónde está: eso es lo que se puede mandar a
alguien para que lo mire.
"""

import io
import sys
from datetime import datetime
from pathlib import Path

import registro


class _Doble(io.TextIOBase):
    """Escribe en la pantalla y en el archivo a la vez."""

    def __init__(self, pantalla, archivo):
        self.pantalla, self.archivo = pantalla, archivo

    def write(self, texto):
        # Este archivo existe para MANDARLO a alguien, así que pasa por el
        # mismo limpiador que el registro. Una traza puede llevar dentro
        # la línea de código que leyó la sesión, o su contenido.
        texto = registro.limpiar_secretos(texto)
        self.pantalla.write(texto)
        if not self.archivo.closed:
            self.archivo.write(texto)
            # Sin esto, un cuelgue a mitad dejaría el archivo vacío, que
            # es justo cuando más falta hace saber por dónde iba.
            self.archivo.flush()
        return len(texto)

    def flush(self):
        # Python destruye este objeto al terminar, DESPUÉS de que el `with`
        # haya cerrado el archivo, y entonces llama a flush(). Sin la
        # comprobación salía un «I/O operation on closed file» al final de
        # una ejecución que había ido bien: ruido que parece un fallo.
        self.pantalla.flush()
        if not self.archivo.closed:
            self.archivo.flush()


def ejecutar(funcion, nombre: str) -> int:
    """
    Lanza `funcion()`, guarda todo lo que imprima y espera antes de salir.

    Devuelve el código de salida. La pausa se salta con `--sin-pausa`, que
    hace falta para lanzarlo desde otro script sin que se quede esperando
    a alguien que no está.
    """
    destino = Path(__file__).resolve().parent.parent / f"salida_{nombre}.txt"
    # Se mira ANTES de ejecutar nada. Varias pruebas reemplazan sys.argv
    # para probar la línea de órdenes, así que al terminar la bandera ya
    # no está: con --sin-pausa se quedaba esperando una tecla para
    # siempre, que es lo contrario de lo que pide esa bandera.
    sin_pausa = "--sin-pausa" in sys.argv
    codigo = 0
    anterior, anterior_err = sys.stdout, sys.stderr
    try:
        with open(destino, "w", encoding="utf-8") as archivo:
            archivo.write(f"{nombre} · {datetime.now():%Y-%m-%d %H:%M}\n")
            archivo.write(f"Python {sys.version.split()[0]} · "
                          f"{sys.platform}\n\n")
            sys.stdout = _Doble(anterior, archivo)
            # Las trazas van a stderr, y sin esto el archivo guardaba
            # «CRASH» sin decir por qué: justo lo que se quiere mandar.
            sys.stderr = _Doble(anterior_err, archivo)
            try:
                codigo = funcion() or 0
            except SystemExit as e:
                codigo = e.code if isinstance(e.code, int) else 1
            except Exception:
                import traceback
                traceback.print_exc()
                codigo = 1
    finally:
        sys.stdout, sys.stderr = anterior, anterior_err

    print(f"\nTodo esto está guardado en:\n  {destino}")
    if not sin_pausa:
        try:
            input("\nPulsa Intro para cerrar...")
        except (EOFError, KeyboardInterrupt):
            pass          # sin teclado: se cierra sin más
    return codigo
