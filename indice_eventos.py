#!/usr/bin/env python3
"""
indice_eventos.py  ·  la trayectoria de cada persona, sin releerlo todo

El problema que resuelve
------------------------
`historial` cruzaba TODAS las capturas en cada consulta, parseando cada
CSV entero. Con dos capturas es instantáneo. Con una diaria durante un
año son ~730 archivos y millones de filas parseadas cada vez que pulsas
el botón, y eso no se arregla optimizando el bucle: hay que dejar de
recalcular.

Aquí se guarda el resultado y se amplía con lo que llega nuevo.

Por qué presencia y no eventos
------------------------------
La tentación era guardar «entró el día X, salió el día Y». Pero un
evento depende de DOS capturas consecutivas, así que insertar, quitar o
descartar una captura obliga a recalcular sus vecinas, y eso se enreda
enseguida.

La presencia —«estaba en estas capturas»— es independiente por captura:
se añade una y no hay que tocar nada de lo anterior. Las entradas y las
salidas salen luego de mirar los huecos, que es un cálculo trivial.

Además sobrevive a que se borren capturas viejas para ahorrar disco: lo
aprendido de ellas se queda, y por eso `podar` es seguro.

Cómo se guarda
--------------
Por TRAMOS de índices, no por lista de fechas. Una persona que lleva un
año sin moverse son 365 fechas... o un solo tramo [0, 364]. Y así es la
mayoría de la gente, así que el archivo baja de megas a kilobytes.

    {"version": 1, "usar_id": true,
     "fechas": ["2026-09-01", ...],          # capturas procesadas, en orden
     "tamanos": [216, ...],                  # para detectar desplomes
     "capturas": {"archivo.csv": [mtime, tam]},
     "gente": {"<clave>": {"t": [[0, 5], [8, 12]],
                           "u": [[0, "ana", "Ana L."]]}}}

`u` solo anota los índices en los que el nombre CAMBIÓ: casi todo el mundo
tiene una sola entrada ahí dentro.
"""

from __future__ import annotations

VERSION = 1


def nuevo(usar_id: bool = True) -> dict:
    """Un índice vacío."""
    return {"version": VERSION, "usar_id": bool(usar_id), "fechas": [],
            "tamanos": [], "capturas": {}, "gente": {}}


def sirve(indice: dict, usar_id: bool) -> bool:
    """
    ¿Se puede seguir usando este índice?

    La clave (id o nombre de usuario) se decide para TODA la serie: si una
    captura nueva no trae ids, todo pasa a indexarse por nombre y lo
    guardado ya no vale. Mezclar los dos criterios duplicaría a cada
    persona, una «yéndose» y otra «entrando».
    """
    return (isinstance(indice, dict)
            and indice.get("version") == VERSION
            and bool(indice.get("usar_id")) == bool(usar_id))


def anadir_captura(indice: dict, fecha: str, gente: dict,
                   archivo: str = "", firma=None) -> None:
    """
    Añade una captura al final. `gente` es {clave: {username, nombre}}.

    Solo se añade al FINAL: las capturas se procesan por fecha y una que
    llegara con fecha anterior descolocaría los tramos de todos. Quien
    llama debe reconstruir desde cero en ese caso.
    """
    i = len(indice["fechas"])
    indice["fechas"].append(fecha)
    indice["tamanos"].append(len(gente))
    if archivo:
        indice["capturas"][archivo] = firma

    for clave, quien in gente.items():
        ficha = indice["gente"].get(clave)
        if ficha is None:
            ficha = {"t": [], "u": []}
            indice["gente"][clave] = ficha

        tramos = ficha["t"]
        if tramos and tramos[-1][1] == i - 1:
            tramos[-1][1] = i           # seguía ahí: se alarga el tramo
        else:
            tramos.append([i, i])       # vuelve, o es la primera vez

        usuario = quien.get("username", "")
        nombre = quien.get("nombre", "")
        if not ficha["u"] or ficha["u"][-1][1:] != [usuario, nombre]:
            ficha["u"].append([i, usuario, nombre])


def _posiciones(total: int, excluir: set) -> list:
    """
    Índice original -> posición en la serie sin las descartadas, o None.

    Las capturas descartadas se QUITAN de la serie, no se marcan como
    ausencias: si no, una captura mala partiría en dos la presencia de todo
    el mundo y saldrían cientos de idas y vueltas que no ocurrieron.
    """
    posiciones, siguiente = [], 0
    for i in range(total):
        if i in excluir:
            posiciones.append(None)
        else:
            posiciones.append(siguiente)
            siguiente += 1
    return posiciones


def _tramos_filtrados(tramos: list, posiciones: list) -> list:
    """
    Los tramos, ya en posiciones de la serie filtrada y pegados.

    Quitar capturas de DENTRO de un tramo lo deja contiguo igualmente: al
    eliminar un elemento, todo lo que va detrás se corre una posición. Así
    que basta con el primero y el último que sobrevivan, sin recorrer el
    tramo entero — que es exactamente lo que los tramos existen para evitar.
    La primera versión sí lo recorría: con 2.500 personas por 365 días,
    900.000 pasos en cada consulta.
    """
    salida = []
    for inicio, fin in tramos:
        a = inicio
        while a <= fin and posiciones[a] is None:
            a += 1
        if a > fin:
            continue                    # el tramo entero se descartó
        b = fin
        while posiciones[b] is None:
            b -= 1
        # Si al quitar una captura los dos tramos quedan pegados, son uno:
        # esa persona no se fue, es que no se la miró ese día.
        if salida and salida[-1][1] + 1 == posiciones[a]:
            salida[-1][1] = posiciones[b]
        else:
            salida.append([posiciones[a], posiciones[b]])
    return salida


def derivar(indice: dict, excluir: set | None = None) -> dict:
    """
    La trayectoria de cada persona. {fechas, personas}.

    `excluir` son índices de capturas que no se quieren usar (las que se
    desploman de tamaño). Se calcula sobre `tamanos`, que ya está aquí, sin
    volver a abrir un solo CSV.
    """
    excluir = excluir or set()
    total = len(indice.get("fechas", []))
    posiciones = _posiciones(total, excluir)
    fechas = [f for i, f in enumerate(indice.get("fechas", []))
              if posiciones[i] is not None]
    if not fechas:
        return {"fechas": [], "personas": {}}

    ultima = len(fechas) - 1
    personas = {}
    for clave, ficha in indice.get("gente", {}).items():
        tramos = _tramos_filtrados(ficha.get("t", []), posiciones)
        if not tramos:
            continue                    # solo estaba en capturas descartadas

        # El nombre en vigor es el del último cambio anotado en un índice
        # que siga contando. Así un cambio ocurrido en una captura
        # descartada no se cuela en la cadena.
        cadena, usuario, nombre = [], "", ""
        for i, u, n in ficha.get("u", []):
            if posiciones[i] is None or posiciones[i] > tramos[-1][1]:
                continue
            usuario, nombre = u, n
            if not cadena or cadena[-1] != u:
                cadena.append(u)

        presentes = sum(fin - ini + 1 for ini, fin in tramos)
        personas[clave] = {
            "username": usuario,
            "nombre": nombre,
            "id": "" if str(clave).startswith("@") else clave,
            "primera": fechas[tramos[0][0]],
            "ultima": fechas[tramos[-1][1]],
            "presente": tramos[-1][1] == ultima,
            "capturas": presentes,
            # Cada tramo empieza con una entrada, incluida la primera: eso
            # es lo que hacía el cálculo de siempre.
            "entradas": len(tramos),
            # Y cada tramo que no llega al final es una salida.
            "salidas": sum(1 for _, fin in tramos if fin < ultima),
            "nombres": cadena,
        }
    return {"fechas": fechas, "personas": personas}
