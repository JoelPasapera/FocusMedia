#!/usr/bin/env python3
"""
export_instagram.py  ·  leer la exportación oficial de Instagram

Instagram deja descargar tus propios datos desde Accounts Center. Ese ZIP
no cuesta ninguna petición, no pasa por la API interna y no puede provocar
un bloqueo. Es la única fuente de este proyecto con riesgo cero.

Lo que hay que tener claro
--------------------------
1. **Solo sirve para TU cuenta.** No para las que vigilas.
2. **No trae el id numérico**, solo el nombre de usuario. Y este proyecto
   deduplica por id justamente porque los nombres cambian (fallo nº 4 de la
   v2). La clave se decide UNA vez para toda la serie: meter aquí una
   captura sin ids degradaría el historial entero de esa cuenta.

Por eso lo que se importa **NO es una captura**. Es un enriquecimiento
aparte: añade lo que la vía de scraping no puede dar y no toca la serie.

3. **Instagram excluye cuentas del export** (desactivadas, suspendidas,
   sensibles) aunque sigan apareciendo en la aplicación. Es un truncado
   silencioso, y este proyecto lleva desde la v1 peleándose con esos.

Formato
-------
    connections/followers_and_following/
        following.json          clave "relationships_following"
        followers_1.json        clave "relationships_followers"
        followers_2.json        (los seguidores se parten en varios)
        recently_unfollowed_profiles.json
        pending_follow_requests.json

Y cada entrada:

    {"title": "", "media_list_data": [],
     "string_list_data": [{"href": "https://www.instagram.com/usuario",
                           "value": "usuario", "timestamp": 1704067200}]}

Se acepta también el archivo como lista suelta, sin la clave de arriba:
las dos formas circulan según la versión del export.

Nada de esto está verificado contra un ZIP real, así que el lector NO da
por sentado lo que hay: `resumen()` enseña los campos que llegaron de
verdad, como hace `inspeccionar` con la API. Si Instagram trae un id algún
día, saldrá en esa lista en vez de pasar desapercibido.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

# Qué archivo es qué. Se buscan por nombre en cualquier punto del ZIP:
# la ruta ha cambiado entre versiones y el nombre no.
ARCHIVOS = {
    "following": ("following", "relationships_following"),
    "followers": ("followers", "relationships_followers"),
    "dejadas": ("recently_unfollowed_profiles", "relationships_unfollowed"),
    "pendientes": ("pending_follow_requests", "relationships_follow_requests"),
}

# 'followers_1.json', 'followers.json', 'following.json'...
_NUMERADO = re.compile(r"^(.+?)(?:_\d+)?$")


def clasificar(nombre: str) -> str | None:
    """Qué tipo de lista es ese archivo, o None si no nos interesa."""
    base = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    if not base.lower().endswith(".json"):
        return None
    hallado = _NUMERADO.match(base[:-5].lower())
    if not hallado:
        return None
    limpio = hallado.group(1)
    for tipo, (patron, _) in ARCHIVOS.items():
        if limpio == patron:
            return tipo
    return None


def _entradas(datos) -> list:
    """La lista de entradas, venga con clave o como lista suelta."""
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for valor in datos.values():
            if isinstance(valor, list):
                return valor
    return []


def interpretar(texto: str) -> list:
    """
    Un archivo del export -> lista de personas.

    Cada una lleva lo que de verdad venía, no lo que se esperaba: si
    Instagram añade campos, aparecen en 'extra' y se pueden ver con
    `resumen()` en vez de perderse en silencio.
    """
    try:
        datos = json.loads(texto)
    except ValueError:
        return []

    gente = []
    for entrada in _entradas(datos):
        if not isinstance(entrada, dict):
            continue
        cadena = entrada.get("string_list_data") or []
        if not cadena or not isinstance(cadena[0], dict):
            continue
        primero = cadena[0]
        usuario = str(primero.get("value") or "").strip()
        if not usuario:
            continue
        extra = {k: v for k, v in primero.items()
                 if k not in ("value", "href", "timestamp")}
        gente.append({
            "username": usuario,
            "href": primero.get("href", ""),
            "timestamp": primero.get("timestamp"),
            "titulo": entrada.get("title", ""),
            "extra": extra,
        })
    return gente


def _fecha(sello) -> str:
    try:
        return f"{datetime.fromtimestamp(int(sello)):%Y-%m-%d}"
    except (ValueError, TypeError, OSError, OverflowError):
        return ""


def leer(archivos: dict) -> dict:
    """
    {nombre de archivo: texto} -> {tipo: [personas]}.

    Los seguidores vienen partidos en varios archivos y hay que juntarlos:
    quedarse solo con `followers_1.json` es el error más repetido con estos
    exports, y no se nota porque la lista parece correcta, solo corta.
    """
    salida = {}
    for nombre, texto in sorted(archivos.items()):
        tipo = clasificar(nombre)
        if tipo:
            salida.setdefault(tipo, []).extend(interpretar(texto))
    return salida


def resumen(archivos: dict) -> dict:
    """
    Qué hay de verdad dentro del export, antes de creerse nada.

    Contesta las tres preguntas que deciden si esto sirve: cuánta gente
    trae, si hay algún identificador numérico, y qué son esas marcas de
    tiempo. Es lo mismo que hace `inspeccionar` con la API: mirar en vez de
    suponer.
    """
    encontrados = {}
    for nombre in sorted(archivos):
        tipo = clasificar(nombre)
        if tipo:
            encontrados.setdefault(tipo, []).append(
                nombre.replace("\\", "/").rsplit("/", 1)[-1])

    listas = leer(archivos)
    campos, ids, sellos = set(), set(), []
    for gente in listas.values():
        for quien in gente:
            campos |= set(quien["extra"])
            for clave, valor in quien["extra"].items():
                if str(valor).isdigit() and len(str(valor)) >= 6:
                    ids.add(clave)
            if isinstance(quien["timestamp"], int) and quien["timestamp"] > 0:
                sellos.append(quien["timestamp"])

    fechas = sorted(_fecha(s) for s in sellos)
    total = sum(len(v) for v in listas.values())
    return {
        "archivos": encontrados,
        "cuantos": {t: len(v) for t, v in listas.items()},
        "campos_extra": sorted(campos),
        "posibles_ids": sorted(ids),
        "con_sello": len(sellos),
        "sin_sello": total - len(sellos),
        "primera_fecha": fechas[0] if fechas else "",
        "ultima_fecha": fechas[-1] if fechas else "",
    }


def enriquecimiento(archivos: dict) -> dict:
    """
    Lo que se guarda: por usuario, desde cuándo y en qué lista estaba.

    NO es una captura y no entra en la serie. Solo añade lo que la vía de
    scraping no puede dar: la fecha en que empezó cada relación, y las dos
    listas que la API no expone.
    """
    listas = leer(archivos)
    desde = {}
    for tipo in ("followers", "following"):
        for quien in listas.get(tipo, []):
            fecha = _fecha(quien["timestamp"])
            if not fecha:
                continue
            ficha = desde.setdefault(quien["username"], {})
            ficha["te_sigue_desde" if tipo == "followers"
                  else "le_sigues_desde"] = fecha
    return {
        "desde": desde,
        "dejadas": [q["username"] for q in listas.get("dejadas", [])],
        "pendientes": [q["username"] for q in listas.get("pendientes", [])],
        "cuantos": {t: len(v) for t, v in listas.items()},
    }
