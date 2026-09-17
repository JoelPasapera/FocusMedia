#!/usr/bin/env python3
"""
repartir.py  ·  parte las pruebas del motor en pruebas/ por temas

De un solo uso, igual que `mudanza.py` en la v6.7. Se conserva porque el
reparto se puede querer rehacer, y porque documenta cómo se hizo.

Mueve cada función ENTERA, byte a byte, localizándola con `ast`. No se
reescribe ni una línea de ninguna prueba: dividir el arnés de seguridad
reescribiéndolo a mano es la forma más rápida de romperlo sin enterarse.
"""

import ast
import re
from pathlib import Path

ORIGEN = Path("test_modulo_original.py")   # ya repartido; se
# conserva el script porque documenta cómo se hizo y permite
# rehacerlo si alguna vez se quiere otro reparto.
DESTINO = Path("pruebas")

# Qué va en cada archivo. Por TEMA, no por la letra con la que nacieron:
# las letras son cronológicas y no dicen nada a quien llega nuevo.
TEMAS = {
    "sesion": {
        "titulo": "La sesión: cookies, verificación, cortafuegos",
        "tests": ["y1", "y2", "y3", "y4", "y5", "y6", "r1", "r2", "r3",
                  "w1", "w2", "w3", "r5", "r11", "f20", "f21", "f22", "f23", "f33",
                  "f34", "f35", "f39", "f40", "f41", "f60"],
    },
    "presupuesto": {
        "titulo": "Presupuesto, topes y frenos",
        "tests": ["p1", "p2", "p3", "p4", "p5", "p6", "q1", "q2", "q3",
                  "q4", "q5", "q6", "f17", "f24", "s1", "s2", "s3"],
    },
    "capturas": {
        "titulo": "Capturas: formato, metadatos, fusión",
        "tests": ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "x1", "x2",
                  "test_descarga_completa", "test_reanudacion",
                  "test_fusion_mismo_dia", "test_bordes",
                  "x3", "x4", "x5", "x6", "x7", "x8", "c1", "c2", "c3", "r4", "r8",
                  "c4", "c5", "c6", "f3", "f4", "f27", "f30"],
    },
    "analisis": {
        "titulo": "Comparar, historial, relaciones y estudio",
        "tests": ["h1", "h2", "h3", "h4", "h5", "h6", "v1", "v2", "v3",
                  "v4", "v5", "v6", "f5", "f6", "f12", "f13", "f14",
                  "f42", "f44", "f46", "f47", "f48", "f49", "f54", "r9", "r12"],
    },
    "vigilancia": {
        "titulo": "Vigilar varias cuentas, ritmo y programación",
        "tests": ["z1", "z2", "z3", "z4", "z5", "z6", "z7", "z8", "n1",
                  "n2", "n3", "n4", "n5", "f18", "f19", "f50"],
    },
    "pagina_publica": {
        "titulo": "Lo que se saca sin iniciar sesión",
        "tests": ["f51", "f57", "f58", "f59", "f1", "f2", "f7"],
    },
    "salidas": {
        "titulo": "Informe, registro, copias y exportación",
        "tests": ["f8", "f9", "f10", "f11", "f25", "f26", "f36", "f37",
                  "f15", "f56", "f53"],
    },
    "proyecto": {
        "titulo": "El proyecto mirado por fuera: nombres, README, versión",
        "tests": ["f16", "f28", "f29", "f31", "f32", "f38", "f43", "f45",
                  "f52", "f55", "r6", "r7", "r10"],
    },
}


def main() -> None:
    if not ORIGEN.exists():
        # El reparto ya está hecho y el archivo de partida se borró. Esto
        # se queda porque documenta cómo se hizo, pero no puede reventar
        # con una traza de Python por ejecutarlo: es un archivo del
        # proyecto y alguien lo va a lanzar por curiosidad.
        raise SystemExit(
            f"No hay '{ORIGEN}': el reparto ya está hecho.\n"
            "    Las pruebas viven en pruebas/. Este script se conserva\n"
            "    porque documenta cómo se repartieron y permite rehacerlo\n"
            "    con otra agrupación: para eso, recupera el archivo único\n"
            "    de un zip anterior y vuelve a lanzarlo.")
    fuente = ORIGEN.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    lineas = fuente.splitlines(keepends=True)

    def texto_de(nodo) -> str:
        return "".join(lineas[nodo.lineno - 1:nodo.end_lineno])

    funciones, ayudantes, cabecera = {}, [], []
    for nodo in arbol.body:
        if isinstance(nodo, ast.FunctionDef):
            if re.match(r"^[a-z]+\d+_", nodo.name):
                funciones[re.match(r"^([a-z]+\d+)_", nodo.name).group(1)] = (
                    nodo.name, texto_de(nodo))
            elif nodo.name.startswith("test_"):
                # Las cuatro más viejas no llevan prefijo de letra. Son
                # pruebas igual: dejarlas entre los ayudantes las habría
                # sacado de la cuenta sin que nadie lo notara.
                funciones[nodo.name] = (nodo.name, texto_de(nodo))
            else:
                ayudantes.append(texto_de(nodo))
        elif isinstance(nodo, (ast.Import, ast.ImportFrom, ast.Assign,
                               ast.ClassDef)):
            cabecera.append(texto_de(nodo))

    asignadas = {c for t in TEMAS.values() for c in t["tests"]}
    huerfanas = sorted(set(funciones) - asignadas)
    fantasmas = sorted(asignadas - set(funciones))
    if fantasmas:
        raise SystemExit(f"Se piden pruebas que no existen: {fantasmas}")
    if huerfanas:
        # No se pierde ninguna: lo que nadie reclamó va a 'varios' y se
        # dice, en vez de desaparecer en silencio.
        print(f"  Sin tema asignado, van a 'varios': {huerfanas}")
        TEMAS["varios"] = {"titulo": "Sin clasificar todavía",
                           "tests": huerfanas}

    DESTINO.mkdir(exist_ok=True)
    (DESTINO / "__init__.py").write_text(
        '"""Las pruebas del motor, por temas."""\n', encoding="utf-8")

    comun = ['"""\n',
             'comun.py  ·  lo que comparten todas las pruebas\n',
             '\n',
             'El marcador, las carpetas limpias y los ayudantes. Vive\n',
             'aparte para que cada archivo de pruebas solo contenga\n',
             'pruebas.\n',
             '"""\n\n']
    comun += cabecera + ["\n\n"] + ayudantes
    (DESTINO / "comun.py").write_text("".join(comun), encoding="utf-8")

    orden = []
    for nombre, datos in TEMAS.items():
        cuerpo = [f'"""\n{datos["titulo"]}\n"""\n\n',
                  "from pruebas.comun import *  # noqa: F401,F403\n",
                  "from pruebas.comun import check, prep, m\n\n\n"]
        nombres = []
        for clave in datos["tests"]:
            fn, texto = funciones[clave]
            cuerpo.append(texto + "\n\n")
            nombres.append(fn)
        cuerpo.append("PRUEBAS = [\n")
        for fn in nombres:
            cuerpo.append(f"    {fn},\n")
        cuerpo.append("]\n")
        (DESTINO / f"{nombre}.py").write_text("".join(cuerpo),
                                              encoding="utf-8")
        orden.append(nombre)
        print(f"  pruebas/{nombre}.py  ({len(nombres)} pruebas)")
    print(f"\n  {sum(len(t['tests']) for t in TEMAS.values())} repartidas")


if __name__ == "__main__":
    main()
