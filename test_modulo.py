#!/usr/bin/env python3
"""
test_modulo.py  ·  lanza las pruebas del motor

Las pruebas viven en `pruebas/`, repartidas por temas. Esto sigue aquí
porque es lo que todo el mundo escribe y lo que dice el README:

    python test_modulo.py              todas
    python test_modulo.py sesion       solo ese tema
    python test_modulo.py --temas      qué temas hay
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pruebas.consola import ejecutar   # noqa: E402
from pruebas.ejecutar import main      # noqa: E402

if __name__ == "__main__":
    # Por `ejecutar`: en Windows, doble clic cierra la ventana en cuanto
    # termina y no da tiempo ni a leer el resumen.
    sys.exit(ejecutar(lambda: main([a for a in sys.argv[1:]
                                    if a != "--sin-pausa"]),
                      "pruebas_motor"))
