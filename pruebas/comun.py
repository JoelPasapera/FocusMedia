"""
comun.py  ·  lo que comparten todas las pruebas

El marcador, las carpetas limpias y los ayudantes. Vive
aparte para que cada archivo de pruebas solo contenga
pruebas.
"""

import csv
import io
import json
import re
import traceback
import contextlib
import os
import shutil
import time
import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path
import requests
import instagram_listas as m
FUNCIONES_REALES = {n: o for n, o in vars(m).items()
                    if callable(o)
                    and getattr(o, "__module__", "") == m.__name__}
PEDIR_REAL = m.pedir
FALLOS = []
class FakeIG:
    """Instagram simulado: pagina de 50 en 50 y puede cortar cuando quieras."""

    def __init__(self, n_seguidores, n_seguidos, cortar_en=None):
        self.datos = {
            "followers": [self._u(i, "f") for i in range(n_seguidores)],
            "following": [self._u(i, "g") for i in range(n_seguidos)],
        }
        self.cortar_en = cortar_en or {}
        self.peticiones = 0

    @staticmethod
    def _u(i, p):
        return {"pk": f"{p}{i}", "username": f"{p}user{i}",
                "full_name": f"Nombre {p}{i}",
                "is_private": i % 2 == 0,
                "is_verified": i % 10 == 0,
                "friendship_status": {"following": True,
                                      "followed_by": i % 3 == 0}}

    def pedir(self, s, ruta, params=None, referer=None):
        self.peticiones += 1
        endpoint = "followers" if "followers" in ruta else "following"
        lista = self.datos[endpoint]

        params = params or {}
        inicio = int(params.get("max_id", 0))
        count = params.get("count", 50)

        limite = self.cortar_en.get(endpoint)
        if limite is not None and inicio >= limite:
            raise m.Bloqueado("simulado: demasiadas peticiones")

        trozo = lista[inicio:inicio + count]
        fin = inicio + len(trozo)
        return {"users": trozo,
                "next_max_id": str(fin) if fin < len(lista) else None}
PERFIL = {"id": "1", "username": "t", "nombre": "", "seguidores": 0,
          "seguidos": 0, "privada": False, "la_sigo": True}
HTML_PERFIL = '''<!DOCTYPE html><html><head>
<meta property="og:description" content="4,820 Followers, 611 Following,
137 Posts - See Instagram photos and videos from Nombre (@cuenta.ejemplo)" />
<script>{"config":{},"profile_id":"51234567890","entry_data":{}}</script>
</head><body></body></html>'''
JPEG_FALSO = b"\xff\xd8\xff\xe0" + b"0" * 200
HTML_CON_FOTO = HTML_PERFIL.replace(
    "</head>",
    '<meta property="og:image" content="https://scontent.cdninstagram.com/'
    'v/foto.jpg?stp=dst-jpg&amp;_nc_ht=scontent.cdninstagram.com" />'
    "</head>")


def TEMPORAL(nombre: str) -> str:
    """
    Una ruta temporal que vale en los tres sistemas.

    Antes estaba «/tmp/...» escrito a mano. En Windows eso se convierte en
    C:\\tmp, que ensucia la raíz del disco y en equipos con restricciones
    ni siquiera se puede crear: la captura de pantalla de las pruebas
    fallaba por eso.
    """
    return str(Path(tempfile.gettempdir()) / "focusmedia_pruebas" / nombre)


def restaurar_modulo():
    """Deja el módulo como estaba: sin dobles, sin bloqueos, sin gasto."""
    for nombre, funcion in FUNCIONES_REALES.items():
        setattr(m, nombre, funcion)
    # Carpeta nueva por prueba: el presupuesto y las vías aprendidas viven
    # en disco, y arrastrarlos hacía que una prueba midiera otra cosa.
    m.CARPETA = Path(tempfile.mkdtemp(prefix="aislado_"))
    m._PRESUPUESTO = None
    m._BLOQUEOS.clear()
    m._SESION_CACHE = None
    m._SESION_HASTA = 0.0
    m._VERIFICACION_OK = None
    m.CANCELAR = None
    m._IDS.clear()
    m._RECOLOCADAS.clear()
def check(cond, msg):
    print(("  OK    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLOS.append(msg)
def prep(ruta):
    p = Path(ruta)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    m.CARPETA = p
    m.OBJETIVO = "t"
    # Cada cuenta tiene ya su carpeta dentro de salida/, y varias pruebas
    # escriben sus archivos de partida a mano. El código de verdad la crea
    # antes de escribir; aquí se crea al preparar.
    m.carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    m.PAUSA_MIN = m.PAUSA_MAX = 0
    m.DESCANSO_SEG = 0
    m.ESPERA_INICIAL = m.ESPERA_MAXIMA = 0
    m.MAX_REINTENTOS = 6
    return p
def leer(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
def captura(tipo, dia, filas, completa=True):
    """Escribe una captura de prueba con sus metadatos."""
    ruta = m._ruta_captura(tipo, dia)
    # Formato antiguo de 3 columnas: prueba de paso la compatibilidad.
    m._escribir_csv(ruta, ["username", "nombre", "id"],
                    [[u, n, i] for u, n, i in filas])
    m._escribir_meta(ruta, completa, len(filas), len(filas),
                     "completa" if completa else "truncada")
    return ruta
def perfil(seguidores=0, seguidos=0):
    return dict(PERFIL, seguidores=seguidores, seguidos=seguidos)
