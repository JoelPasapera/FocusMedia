#!/usr/bin/env python3
"""
ejecutar.py  ·  lanza las pruebas del motor

    python test_modulo.py              todas
    python test_modulo.py sesion       solo ese tema
    python test_modulo.py --temas      qué temas hay

El resumen final es el de siempre. Lo que cambia es que se puede correr un
tema suelto mientras se toca esa parte, en vez de esperar a las 146.
"""

import importlib
import re
import sys
import traceback

from pruebas import comun

TEMAS = ["sesion", "presupuesto", "capturas", "analisis", "vigilancia",
         "pagina_publica", "salidas", "proyecto"]


def _comprobar_registradas(modulo, nombre: str) -> None:
    """
    Ninguna prueba escrita puede quedarse fuera de su lista PRUEBAS.

    Venía en el ejecutor de siempre, y con el reparto hace más falta: una
    prueba olvidada en un archivo de veinte pasa más desapercibida que en
    uno de seis mil líneas.
    """
    definidas = {n for n, o in vars(modulo).items()
                 if callable(o)
                 and re.match(r"^(test_|[a-z]+\d+_)", n)
                 and getattr(o, "__module__", "") == modulo.__name__}
    olvidadas = sorted(definidas - {f.__name__ for f in modulo.PRUEBAS})
    if olvidadas:
        print(f"PRUEBAS ESCRITAS PERO NO REGISTRADAS en {nombre}: "
              + ", ".join(olvidadas))
        raise SystemExit(1)


def main(argv: list) -> int:
    if "--temas" in argv:
        for t in TEMAS:
            modulo = importlib.import_module(f"pruebas.{t}")
            doc = (modulo.__doc__ or "").strip().splitlines()
            print(f"  {t:<16} {len(modulo.PRUEBAS):>3}   "
                  f"{doc[0] if doc else ''}")
        return 0

    pedidos = [a for a in argv if not a.startswith("-")]
    desconocidos = [p for p in pedidos if p not in TEMAS]
    if desconocidos:
        print(f"No existe ese tema: {desconocidos}")
        print(f"Hay: {', '.join(TEMAS)}")
        return 2

    total = 0
    for nombre in pedidos or TEMAS:
        modulo = importlib.import_module(f"pruebas.{nombre}")
        _comprobar_registradas(modulo, nombre)
        total += len(modulo.PRUEBAS)
        for prueba in modulo.PRUEBAS:
            try:
                # Antes de CADA prueba, no de cada tema: una que deje el
                # módulo parcheado no puede contaminar a la siguiente.
                comun.restaurar_modulo()
                prueba()
            except Exception:
                comun.FALLOS.append(f"{prueba.__name__} lanzó una excepción")
                print(f"  CRASH  {prueba.__name__}")
                traceback.print_exc()

    print("\n" + "=" * 62)
    print(f"{total} pruebas, {len(comun.FALLOS)} fallos")
    for fallo in comun.FALLOS:
        print(f"  - {fallo}")
    if not comun.FALLOS:
        print("Todas las comprobaciones pasaron.")
    return 1 if comun.FALLOS else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
