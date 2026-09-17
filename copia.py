#!/usr/bin/env python3
"""
copia.py  ·  guardar lo que no se puede volver a descargar

Un CSV de seguidores de hace tres semanas **no se recupera con ninguna
petición**: esa lista ya no existe en ningún sitio. Ni Instagram la tiene
ni la tiene nadie. Es el único dato de este proyecto que, si se pierde, se
pierde de verdad.

Y hasta ahora no había copia de nada.

Qué entra
---------
La carpeta de la cuenta entera: capturas, metadatos, índice, cursores,
totales, informes, la foto y lo aprendido del perfil. También los archivos
ocultos, que son justamente el índice y los cursores de reanudación.

Qué NO entra, y por qué
-----------------------
**Las sesiones.** Una copia es algo que se lleva a un disco externo, se
manda o se sube a algún sitio; una cookie de sesión ahí dentro es la cuenta
entera viajando. Las sesiones ni están en la carpeta de la cuenta ni se
tocan aquí.

**`crudo_perfil_*.html`**, por lo mismo: es la página pedida CON la sesión y
puede llevar datos de ella. Además se recupera con una petición, así que no
cumple el criterio de esto — guardar lo irrecuperable.

Restaurar no pisa nada
----------------------
Por defecto solo se traen los archivos que faltan. Lo que ya está en el
disco se queda: puede ser más nuevo que la copia, y una restauración que
machaca en silencio es una forma elegante de perder lo que venías a
proteger.
"""

from __future__ import annotations

import fnmatch
import json
import zipfile
from datetime import datetime
from pathlib import Path

import instagram_listas as motor

MANIFIESTO = "copia.json"
VERSION = 1

# Lo que se queda fuera. El crudo del perfil puede llevar la sesión dentro,
# y los .tmp son restos de una escritura a medias que no vale la pena
# guardar.
EXCLUIDOS = ("crudo_perfil_*", "*.tmp")


def archivos_de(carpeta: Path) -> list:
    """
    Lo que entra en la copia, ordenado. Incluye los ocultos.

    Los ocultos importan: el índice de eventos y los cursores de
    reanudación empiezan por punto, y sin ellos la copia tendría los datos
    pero no lo aprendido de ellos.
    """
    if not carpeta.is_dir():
        return []
    dentro = []
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file():
            continue
        if any(fnmatch.fnmatch(ruta.name, p) for p in EXCLUIDOS):
            continue
        dentro.append(ruta)
    return dentro


def crear(cuenta: str, destino: Path | None = None) -> tuple:
    """
    Hace la copia de una cuenta. Devuelve (ruta, manifiesto).

    El manifiesto va DENTRO del zip. Es lo que separa una copia de un
    montón de archivos comprimidos: sin él, dentro de un año hay que
    descomprimirlo entero para saber de quién es y de cuándo.
    """
    carpeta = motor.carpeta_cuenta(cuenta)
    dentro = archivos_de(carpeta)
    if not dentro:
        raise FileNotFoundError(f"no hay nada guardado de @{cuenta}")

    manifiesto = {
        # 'version' es la del FORMATO de la copia; 'programa', la del
        # FocusMedia que la hizo. Son cosas distintas: el formato solo
        # cambia si cambia la estructura del zip.
        "version": VERSION,
        "programa": motor.VERSION,
        "cuenta": cuenta,
        "carpeta": carpeta.name,
        "creada": datetime.now().isoformat(timespec="seconds"),
        "archivos": len(dentro),
        "bytes": sum(r.stat().st_size for r in dentro),
        "capturas": len([r for r in dentro if r.suffix == ".csv"]),
    }

    if destino is None:
        destino = (motor.CARPETA
                   / f"copia_{cuenta}_{datetime.now():%Y-%m-%d}.zip")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Se escribe al lado y se renombra, como todo lo demás: una copia a
    # medias que parece buena es peor que no tener copia.
    import os
    temporal = destino.with_name(f"{destino.name}.{os.getpid()}")
    try:
        with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(MANIFIESTO, json.dumps(manifiesto, indent=2,
                                              ensure_ascii=False))
            for ruta in dentro:
                z.write(ruta, str(ruta.relative_to(carpeta)))
        temporal.replace(destino)
    except OSError:
        temporal.unlink(missing_ok=True)
        raise
    return destino, manifiesto


def leer_manifiesto(archivo: Path) -> dict:
    """De quién es esta copia y de cuándo, sin descomprimirla entera."""
    try:
        with zipfile.ZipFile(archivo) as z:
            return json.loads(z.read(MANIFIESTO).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}


def restaurar(archivo: Path, cuenta: str | None = None,
              reemplazar: bool = False) -> dict:
    """
    Devuelve una copia al disco. Por defecto NO pisa lo que ya esté.

    `cuenta` permite traerla a otro nombre; si no, va a la suya.
    """
    archivo = Path(archivo)
    manifiesto = leer_manifiesto(archivo)
    if not manifiesto:
        raise ValueError("esto no parece una copia de FocusMedia: "
                         f"le falta {MANIFIESTO}")

    if int(manifiesto.get("version", 1)) > VERSION:
        raise ValueError(
            f"esta copia la hizo FocusMedia {manifiesto.get('programa', '?')}"
            f", con un formato más nuevo (v{manifiesto['version']}) del que "
            f"esta versión sabe leer (v{VERSION}).\n"
            "    Actualiza antes de restaurarla: traerla a medias sería "
            "peor que no traerla.")

    destino = motor.carpeta_cuenta(cuenta or manifiesto["cuenta"])
    destino.mkdir(parents=True, exist_ok=True)
    traidos, saltados, rotos = [], [], []

    try:
        z = zipfile.ZipFile(archivo)
    except (OSError, zipfile.BadZipFile) as e:
        raise ValueError(f"no se puede abrir la copia: {e}") from e

    with z:
        # El zip lleva un CRC por entrada: si algo se corrompió en el
        # disco externo o en el correo, se sabe ANTES de escribir nada.
        malo = z.testzip()
        if malo:
            raise ValueError(f"la copia está dañada: {malo}")

        for nombre in z.namelist():
            if nombre == MANIFIESTO or nombre.endswith("/"):
                continue
            # Un zip puede traer rutas hacia fuera de su carpeta. No se
            # confía en el nombre: se limpia y se comprueba dónde cae.
            limpio = Path(nombre.replace("\\", "/"))
            if limpio.is_absolute() or ".." in limpio.parts:
                rotos.append(nombre)
                continue
            salida = destino / limpio
            if salida.exists() and not reemplazar:
                saltados.append(nombre)
                continue
            # Por el ayudante del motor, como todo lo demás: restaurar es
            # justo cuando peor viene dejar un archivo a medias.
            motor.escribir_atomico(salida, z.read(nombre))
            traidos.append(nombre)

    return {"cuenta": manifiesto["cuenta"], "destino": destino,
            "traidos": traidos, "saltados": saltados, "rotos": rotos,
            "creada": manifiesto.get("creada", "")}
