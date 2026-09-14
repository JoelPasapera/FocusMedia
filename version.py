#!/usr/bin/env python3
"""
version.py  ·  qué versión es esto

Un archivo entero para dos líneas, y con motivo: lo necesitan el motor, la
ventana, el informe, la copia y el registro. Si viviera dentro de
`instagram_listas.py`, los módulos puros —`informe_html`,
`indice_eventos`— tendrían que importar el motor entero para saber un
número, y dejarían de ser puros. Aquí no depende de nada y nada le crea un
ciclo.

Hasta ahora el programa no sabía cuál era. Eso significaba que un informe
de error no estaba anclado a nada («falla esto» — ¿en cuál?), que no se
podía saber si el zip que uno tiene es el último, y que una copia de
seguridad no decía con qué se hizo.

No confundir con las versiones de FORMATO
-----------------------------------------
`indice_eventos.VERSION` y `copia.VERSION` son otra cosa: dicen cómo está
escrito un archivo, y solo cambian cuando cambia su estructura. Esta dice
qué programa lo escribió. Mezclarlas obligaría a invalidar todos los
índices cada vez que se corrige una errata.
"""

VERSION = "7.3"
FECHA = "2026-09-12"


def firma() -> str:
    """
    La línea que va en un informe de error: versión, Python y sistema.

    Es lo primero que hace falta saber cuando alguien dice «me falla», y
    lo que nadie recuerda de memoria.
    """
    import platform
    import sys
    return (f"FocusMedia {VERSION} ({FECHA}) · "
            f"Python {sys.version.split()[0]} · "
            f"{platform.system()} {platform.release()}")
