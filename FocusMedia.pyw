#!/usr/bin/env python3
"""
FocusMedia.pyw  ·  abrir la ventana sin la consola negra detrás

En Windows, un `.pyw` lo ejecuta `pythonw.exe`, que no abre consola. Doble
clic aquí y sale solo la ventana.

Por qué un archivo aparte y no renombrar instagram_gui.py
---------------------------------------------------------
Porque `test_gui.py` hace `import instagram_gui`, y un módulo `.pyw` no se
importa. Renombrarlo habría dejado las pruebas de la ventana sin nada que
probar, que es un precio absurdo por quitar una ventana negra.

Las dos trampas de no tener consola
-----------------------------------
1. **`sys.stdout` y `sys.stderr` valen None.** Comprobado qué aguanta y
   qué no: `print()` sobrevive —Python se calla y sigue— y también
   `redirect_stdout`, que es lo que usa la ventana. Lo que revienta es
   `sys.stdout.write()` y `.flush()` llamados a pelo, y el manejador de
   excepciones de serie, que escribe en stderr.

   Este proyecto no hace ninguna de esas cosas, así que la protección no
   es para su código: es para el que no controla —customtkinter,
   requests, browser_cookie3— y para los enganches de error. Cuesta dos
   líneas y evita un fallo que, sin consola, sería invisible.

2. **Si algo falla antes de que exista la ventana, no se ve NADA.** Sin
   consola, un `pip install` que falta convierte el doble clic en «no pasa
   nada», que es la peor respuesta posible. Se recoge y se enseña en un
   cuadro del sistema, que no necesita que el programa haya arrancado.
"""

import os
import sys
from pathlib import Path

# Lo PRIMERO, antes de importar nada que pueda imprimir.
for flujo in ("stdout", "stderr"):
    if getattr(sys, flujo, None) is None:
        setattr(sys, flujo, open(os.devnull, "w", encoding="utf-8"))

# Doble clic desde otra carpeta: el programa vive donde vive este archivo.
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
os.chdir(AQUI)


def avisar(titulo: str, mensaje: str) -> None:
    """Un cuadro del sistema. Es lo único que se ve si no hay consola."""
    try:
        import tkinter
        from tkinter import messagebox
        raiz = tkinter.Tk()
        raiz.withdraw()
        messagebox.showerror(titulo, mensaje)
        raiz.destroy()
    except Exception:
        pass            # sin tkinter no hay nada que hacer, y ya se verá


def main() -> None:
    # Con argumentos, la línea de órdenes; sin ellos, la ventana. Un .exe
    # empaquetado no tiene al lado ningún .py que ejecutar, así que sin
    # esto la tarea programada apuntaría a un archivo que no existe y el
    # ejecutable solo serviría para abrir la ventana.
    if len(sys.argv) > 1:
        import instagram_listas
        instagram_listas.main()
        return

    try:
        import instagram_gui
    except ImportError as e:
        avisar("FocusMedia no puede arrancar",
               f"Falta una biblioteca: {e}\n\n"
               "Instálalas con:\n"
               "    pip install customtkinter requests browser_cookie3 "
               "pillow")
        return
    except Exception as e:
        avisar("FocusMedia no puede arrancar", f"{type(e).__name__}: {e}")
        return

    try:
        instagram_gui.main()
    except Exception as e:
        # A partir de aquí el registro ya está puesto y tiene la traza
        # entera; aquí solo hace falta que la persona se entere.
        avisar("FocusMedia se ha cerrado",
               f"{type(e).__name__}: {e}\n\n"
               "El detalle está en salida/registro.log")


if __name__ == "__main__":
    main()
