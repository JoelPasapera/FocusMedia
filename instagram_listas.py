#!/usr/bin/env python3
"""
instagram_listas.py  ·  v2
===========================

Descarga y compara las listas de SEGUIDORES y SEGUIDOS de una cuenta de
Instagram, usando la sesión que ya tienes abierta en tu navegador.

    pip install requests browser_cookie3

    python instagram_listas.py sesion       # importa las cookies (una vez)
    python instagram_listas.py inspeccionar # qué campos manda Instagram
    python instagram_listas.py contar       # solo los totales (1 petición)
    python instagram_listas.py vigilar      # comprueba y baja si hace falta
    python instagram_listas.py bajar        # descarga las listas completas
    python instagram_listas.py comparar     # entró / salió entre 2 capturas
    python instagram_listas.py historial    # trayectoria de cada persona
    python instagram_listas.py detalles     # perfil completo de unas pocas

'comparar --totales' da la evolución del NÚMERO; 'historial' da la
trayectoria de cada PERSONA. Son cosas distintas.

Nunca pide ni guarda tu contraseña: toma la sesión del navegador.

Perfil detallado
----------------
`detalles` consulta biografía, publicaciones, seguidores y enlace de las
cuentas de salida/vigilancia_<cuenta>.txt. Cuesta UNA PETICIÓN POR CUENTA,
contra el mismo endpoint que suele dar 429, así que va con tope duro
(MAX_VIGILANCIA), pausas de 4-9 s y parada al primer bloqueo sin reintentar.
`detalles --crear` genera la lista con candidatos sacados de tus capturas:
quienes entran y salen repetidamente y quienes se fueron hace poco.

Historial por persona
---------------------
`historial` cruza TODAS las capturas que tengas guardadas y reconstruye la
trayectoria de cada persona: cuándo apareció, cuándo se fue, y cuántas veces
ha entrado y salido. Cero peticiones: es cálculo local sobre lo que ya está
en disco.

Lo interesante es la última columna. Alguien con varias entradas está
haciendo follow-unfollow. Las capturas truncadas se EXCLUYEN del cálculo: si
entrara una incompleta, los que faltaban en ella parecerían haberse ido y
vuelto, justo el patrón que se busca.

El detalle llega hasta donde llegan tus capturas: quien entre y salga entre
dos de ellas no aparecerá. Con `vigilar` a diario, el detalle es diario.

Campos extra, gratis
--------------------
Cada página de la lista trae más datos por persona de los que hacen falta
para el nombre: si la cuenta es privada, si está verificada, si tiene foto
por defecto, la relación contigo. Todo eso viaja en la MISMA respuesta, así
que guardarlo no cuesta ninguna petición extra: se define en CAMPOS_EXTRA.

Los campos que Instagram manda no están documentados y cambian. Por eso está
`inspeccionar`: gasta una petición, guarda la respuesta cruda en un JSON y
lista los campos reales, marcando los que ya se guardan y los que hay
disponibles sin usar. Si un campo esperado no llega, su columna queda vacía
y no se rompe nada.

Vigilancia automática
---------------------
`vigilar` está pensado para el Task Scheduler. Gasta UNA petición para leer
los totales y solo lanza la descarga completa (~50 peticiones) si detecta
algo. Dispara en tres casos:

  * los totales se movieron al menos --umbral (por defecto 1)
  * han pasado --max-dias desde la última captura (por defecto 7)
  * no hay ninguna captura utilizable todavía

El segundo caso NO es un extra: si se van 3 personas y entran otras 3, el
total no cambia y el conteo por sí solo no lo vería nunca. La descarga
periódica forzada es lo que cierra ese agujero.

Cada pasada deja una línea en salida/vigilancia_<cuenta>.log, para que puedas
revisar qué hizo mientras no mirabas.

Por qué es rápido
-----------------
Usa los mismos endpoints /api/v1/ que el cliente web de Instagram, que
devuelven ~50 perfiles por petición. Las librerías que van por GraphQL
sacan 12, así que esto es ~4 veces menos peticiones para lo mismo.

Por qué aguanta los cortes
--------------------------
Tras CADA página guarda el cursor en un archivo de estado y vuelca las filas
al CSV. Si Instagram corta, si te quedas sin luz o si pulsas Ctrl+C, al
volver a ejecutar continúa exactamente donde iba.

Cuánto tarda
------------
Para ~2.500 registros son unas 50 peticiones: pocos minutos si no hay cortes.
Si Instagram bloquea, espera y reintenta con esperas crecientes (10, 20 y 40
min, luego 1 h). En el peor caso son hasta 3,2 HORAS dormido antes de
rendirse. Déjalo corriendo, o baja MAX_REINTENTOS si prefieres que abandone
antes: el progreso se guarda igual y se retoma en la siguiente ejecución.

Cambios de la v2
----------------
  1. La comprobación de sesión ya no depende de un único endpoint y no
     bloquea el arranque si no puede verificarla.
  2. El cursor se compara contra None, no por veracidad (un 0 cortaba).
  3. Las capturas incompletas quedan marcadas y comparar() se niega a
     usarlas sin --forzar.
  4. La comparación va por id de usuario, así que detecta los cambios de
     nombre en vez de contarlos como baja + alta.
  5. Errores separados: sesión caída, no encontrado y bloqueo.
  6. _una_pasada informa del motivo real de la parada (sin código muerto).
  7. Tiempos de espera documentados de verdad.
  8. Las capturas llevan BOM para que Excel respete los acentos.
  9. relaciones() avisa si cruza capturas de fechas distintas.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import random
import re
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Falta requests.  Ejecuta:  pip install requests")


# ======================================================================
# CONFIGURACIÓN
# ======================================================================

OBJETIVO = "cuenta_objetivo"     # cuenta cuyas listas quieres bajar

# firefox / chrome / chromium / edge / brave / opera / opera_gx / vivaldi /
# librewolf / safari / arc
NAVEGADOR = "firefox"

CARPETA = Path(__file__).parent / "salida"
ARCHIVO_SESION = Path(__file__).parent / "sesion_instagram.json"

POR_PAGINA = 50                  # lo que pide la propia web de Instagram
POR_PAGINA_MINIMO = 12           # de reserva: si 50 da 400, se prueba con esto
PAUSA_MIN = 1.5                  # segundos entre páginas
PAUSA_MAX = 3.5
DESCANSO_CADA = 40               # páginas
DESCANSO_SEG = 45                # pausa larga cada DESCANSO_CADA páginas

ESPERA_INICIAL = 600             # 10 min tras el primer bloqueo
ESPERA_MAXIMA = 3600             # tope de 1 hora
MAX_REINTENTOS = 6               # ojo: hasta 3,2 h dormido en el peor caso

UMBRAL_COMPLETA = 0.90           # menos del 90% de lo esperado = truncada
PAGINAS_VACIAS = 3               # vacías seguidas para dar la lista por rota
MAX_LISTAR = 30                  # nombres a imprimir por categoría
CAIDA_SOSPECHOSA = 0.70          # captura por debajo del 70% de la mediana
CAIDA_MINIMA = 10                # ...y con al menos esta bajada absoluta

# --- vigilancia ---
UMBRAL_CAMBIO = 1                # diferencia en los totales que dispara bajar
MAX_DIAS_SIN_BAJAR = 7           # descarga completa forzada cada N días

APP_ID = "936619743392459"       # id de la app web de Instagram
BASE = "https://www.instagram.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

COOKIES_UTILES = ("sessionid", "csrftoken", "ds_user_id", "mid", "ig_did")

# Campos que Instagram ya manda en la MISMA respuesta de las listas y que
# antes se tiraban. Guardarlos no cuesta ninguna petición extra.
# La ruta admite puntos para bajar a diccionarios anidados.
# Si un campo no viene, la columna queda vacía: nada se rompe.
CAMPOS_EXTRA = [
    ("privada", "is_private"),
    ("verificada", "is_verified"),
    ("foto_defecto", "has_anonymous_profile_picture"),
    ("le_sigue", "friendship_status.followed_by"),
    ("la_sigue", "friendship_status.following"),
]

CABECERA = ["username", "nombre", "id"] + [n for n, _ in CAMPOS_EXTRA]

# --- perfil detallado -------------------------------------------------
# Esto cuesta UNA PETICIÓN POR PERSONA, contra el mismo endpoint que ya
# provocó un 429. Por eso hay tope duro, pausas largas y parada al primer
# bloqueo, sin reintentos.
MAX_VIGILANCIA = 25              # tope de cuentas en la lista de vigilancia
PAUSA_DETALLE_MIN = 4.0          # segundos entre perfiles
PAUSA_DETALLE_MAX = 9.0

CAMPOS_DETALLE = [
    ("username", "username"),
    ("nombre", "full_name"),
    ("id", "id"),
    ("publicaciones", "edge_owner_to_timeline_media.count"),
    ("seguidores", "edge_followed_by.count"),
    ("seguidos", "edge_follow.count"),
    ("biografia", "biography"),
    ("enlace", "external_url"),
    ("categoria", "category_name"),
    ("privada", "is_private"),
    ("verificada", "is_verified"),
    ("la_sigo", "followed_by_viewer"),
    ("me_sigue", "follows_viewer"),
]
CABECERA_DETALLE = [n for n, _ in CAMPOS_DETALLE] + ["consultado"]


# Nombres de usuario de Instagram: letras, números, punto y guión bajo.
PATRON_USUARIO = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# Primeros tramos de una URL que NO son un perfil.
NO_ES_PERFIL = {"p", "reel", "reels", "tv", "explore", "direct", "accounts",
                "challenge", "about", "legal"}
# Tramos que van ANTES del nombre de usuario.
ANTES_DEL_USUARIO = {"stories", "s"}


def limpiar_usuario(texto: str) -> str:
    """
    Saca el nombre de usuario de lo que la gente pega de verdad.

    Acepta la URL del perfil (con o sin https, con o sin barra final, con
    parámetros), el nombre con @ delante, y espacios sobrantes. Devuelve
    cadena vacía si no hay un perfil ahí dentro.

        https://www.instagram.com/persona.ejemplo/  ->  persona.ejemplo
        @persona.ejemplo                            ->  persona.ejemplo
        instagram.com/p/ABC123/                     ->  ''  (es una publicación)
    """
    t = (texto or "").strip()
    if not t:
        return ""

    hallado = re.search(r"instagram\.com/(.*)", t, re.I)
    if hallado:
        cola = hallado.group(1).split("?")[0].split("#")[0]
        partes = [p for p in cola.split("/") if p]
        if not partes:
            return ""
        primera = partes[0].lower()
        if primera in NO_ES_PERFIL:
            return ""
        if primera in ANTES_DEL_USUARIO:
            t = partes[1] if len(partes) > 1 else ""
        else:
            t = partes[0]

    return t.split("?")[0].split("#")[0].strip("/ ").lstrip("@").strip()

# Gancho de cancelación. La interfaz gráfica lo apunta a una función que
# devuelve True cuando el usuario pulsa "Parar". Se comprueba entre páginas
# y durante las esperas largas, y lanza KeyboardInterrupt, que es el camino
# de parada que el módulo ya tenía probado: guarda el progreso y sale limpio.
CANCELAR = None

# --- control de gasto de peticiones -----------------------------------
# Aprendido de la primera ejecución real: se gastaban 7 peticiones para
# hacer 1, repitiendo endpoints que ya se sabía que fallaban. Instagram
# respondió con un 429 a los dos minutos.
_SESION_CACHE = None             # sesión ya verificada, reutilizable
_SESION_HASTA = 0.0
CACHE_SESION = 600               # 10 min sin volver a verificar

_VERIFICACION_OK = None          # endpoint de verificación que sí funciona

# El enfriamiento es POR ENDPOINT. Medido en la práctica: web_profile_info
# devuelve 429 a la PRIMERA petición mientras friendships responde 200. Un
# cortafuegos global dejaba inutilizable todo lo que sí funcionaba.
_BLOQUEOS: dict = {}
ESPERA_TRAS_429 = 900            # 15 min


def _clave_endpoint(ruta: str) -> str:
    """Agrupa por endpoint ignorando los ids: friendships/123/following."""
    partes = [p for p in ruta.split("/") if p and not p.isdigit()]
    return "/".join(partes[2:]) if len(partes) > 2 else ruta


def _marcar_bloqueo(ruta: str, segundos: int = ESPERA_TRAS_429) -> None:
    _BLOQUEOS[_clave_endpoint(ruta)] = time.monotonic() + segundos


def espera_pendiente(ruta: str | None = None) -> int:
    """Segundos que faltan para poder pedir. 0 si se puede ya."""
    if ruta is not None:
        hasta = _BLOQUEOS.get(_clave_endpoint(ruta), 0)
        return max(0, int(hasta - time.monotonic()))
    if not _BLOQUEOS:
        return 0
    return max(0, int(max(_BLOQUEOS.values()) - time.monotonic()))


def _revisar_cancelacion() -> None:
    if CANCELAR is not None and CANCELAR():
        raise KeyboardInterrupt("cancelado por el usuario")


def _dormir(segundos: float) -> None:
    """Espera troceada, para poder cancelar sin aguantar los 10 minutos."""
    fin = time.monotonic() + segundos
    while True:
        _revisar_cancelacion()
        queda = fin - time.monotonic()
        if queda <= 0:
            return
        time.sleep(min(queda, 0.5))


# ======================================================================
# ERRORES
# ======================================================================

class Bloqueado(Exception):
    """Instagram cortó por límite de peticiones. Reintentable."""


class SesionInvalida(Exception):
    """Las cookies no valen o caducaron. Hay que reiniciar sesión."""


class NoEncontrado(Exception):
    """El perfil o el recurso no existe. La sesión está bien."""


class PeticionRechazada(Exception):
    """
    Instagram dice que la petición está mal (HTTP 400 y similares).

    NO se reintenta: esperar no arregla una petición mal formada. Antes
    caía en el mismo saco que los bloqueos y el programa se pasaba hasta
    tres horas esperando algo que nunca iba a funcionar.
    """


# ======================================================================
# SESIÓN
# ======================================================================

def _guardar_cookies(cookies: dict) -> None:
    ARCHIVO_SESION.write_text(
        json.dumps({"guardado": datetime.now().isoformat(timespec="seconds"),
                    "cookies": cookies},
                   indent=2),
        encoding="utf-8",
    )
    try:
        ARCHIVO_SESION.chmod(0o600)      # en Windows no hace nada, no pasa nada
    except OSError:
        pass


def _cookies_guardadas() -> dict | None:
    if not ARCHIVO_SESION.exists():
        return None
    try:
        datos = json.loads(ARCHIVO_SESION.read_text(encoding="utf-8"))
        cookies = datos.get("cookies") or {}
        return cookies if cookies.get("sessionid") else None
    except (json.JSONDecodeError, OSError):
        return None


def _cookies_del_navegador() -> dict:
    try:
        import browser_cookie3
    except ImportError:
        sys.exit("Falta browser_cookie3.  Ejecuta:  pip install browser_cookie3")

    if not hasattr(browser_cookie3, NAVEGADOR):
        sys.exit(f"browser_cookie3 no soporta '{NAVEGADOR}'.")

    print(f"Leyendo cookies de {NAVEGADOR}...")
    try:
        jar = getattr(browser_cookie3, NAVEGADOR)(domain_name="instagram.com")
    except Exception as e:
        sys.exit(
            f"No se pudieron leer las cookies de {NAVEGADOR}: {e}\n"
            "Cierra el navegador por completo e inténtalo otra vez.\n"
            "En Windows, Chrome y Edge suelen fallar por el cifrado de "
            "cookies; usa Firefox."
        )

    cookies = {c.name: c.value for c in jar if c.name in COOKIES_UTILES}
    if not cookies.get("sessionid"):
        sys.exit(
            f"No hay sesión de Instagram en {NAVEGADOR}.\n"
            "Abre instagram.com, inicia sesión y vuelve a intentarlo."
        )
    return cookies


def comprobar_sesion(s: requests.Session) -> tuple[str | None, str]:
    """
    Devuelve (usuario, estado) con estado en {"viva", "muerta", "desconocida"}.

    Prueba varios endpoints porque son APIs internas y cualquiera puede
    desaparecer. "desconocida" significa que no se pudo determinar, y NUNCA
    debe tratarse como sesión caída: bloquearía el módulo con cookies buenas.
    """
    mi_id = s.cookies.get("ds_user_id")

    intentos = [
        (ruta("sesion_actual"),
         lambda d: (d.get("user") or {}).get(campo("nombre_usuario"))),
    ]
    if mi_id:
        intentos += [
            (ruta("usuario_info", id=mi_id),
             lambda d: (d.get("user") or {}).get(campo("nombre_usuario"))),
            # Este último ejercita el mismo endpoint que usaremos para bajar
            # las listas: si responde, sabemos que lo que importa funciona.
            (ruta("lista_seguidos", id=mi_id) + f"?{param('cantidad')}=1",
             lambda d: f"#{mi_id}" if campo("usuarios") in d else None),
        ]

    # Se prueba primero el que ya funcionó: repetir los 404 conocidos era
    # tirar dos peticiones por cada operación.
    global _VERIFICACION_OK
    preferida = _VERIFICACION_OK or via_recordada("sesion")
    if preferida:
        intentos.sort(key=lambda x: x[0] != preferida)

    visto_401 = False
    # 'endpoint', no 'ruta': ruta() es la función que compone direcciones y
    # una variable con ese nombre la tapaba dentro de este bucle.
    for endpoint, extraer in intentos:
        try:
            r = s.get(BASE + endpoint, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code == 200:
            try:
                usuario = extraer(r.json())
            except (ValueError, AttributeError, TypeError):
                continue
            if usuario:
                _VERIFICACION_OK = endpoint
                recordar_via("sesion", endpoint)
                return str(usuario), "viva"
        elif r.status_code in (401, 403):
            visto_401 = True

    return (None, "muerta") if visto_401 else (None, "desconocida")


def crear_sesion(forzar: bool = False) -> requests.Session:
    """
    Devuelve una sesión lista para usar.

    Se reutiliza durante CACHE_SESION sin volver a verificar: cada
    verificación cuesta peticiones, y la interfaz llama a esto en cada
    acción. Verificar siete veces lo mismo fue lo que provocó el primer 429.
    """
    global _SESION_CACHE, _SESION_HASTA
    if (not forzar and _SESION_CACHE is not None
            and time.monotonic() < _SESION_HASTA):
        return _SESION_CACHE

    cookies = None if forzar else _cookies_guardadas()
    reutilizada = cookies is not None

    if cookies is None:
        cookies = _cookies_del_navegador()

    s = requests.Session()
    # web_profile_info es el endpoint más vigilado: rechaza peticiones que
    # no parecen de un navegador. Estas son las cabeceras que manda Chrome.
    s.headers.update({
        "User-Agent": UA,
        "x-ig-app-id": APP_ID,
        "x-asbd-id": "129477",
        "x-ig-www-claim": "0",
        "x-requested-with": "XMLHttpRequest",
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Referer": BASE + "/",
    })
    if cookies.get("csrftoken"):
        s.headers["x-csrftoken"] = cookies["csrftoken"]
    for nombre, valor in cookies.items():
        s.cookies.set(nombre, valor, domain=".instagram.com")

    usuario, estado = comprobar_sesion(s)

    if estado == "muerta":
        if reutilizada:
            print("La sesión guardada caducó. Reimportando del navegador...")
            return crear_sesion(forzar=True)
        raise SesionInvalida(
            "Instagram rechazó estas cookies.\n"
            "Abre instagram.com en el navegador, inicia sesión y reintenta."
        )

    _guardar_cookies(cookies)

    origen = "  (reutilizada)" if reutilizada else "  (del navegador)"
    if estado == "viva" and usuario.startswith("#"):
        # Solo se confirmó el id: el endpoint que da el nombre no respondió.
        # La sesión funciona igual; lo que importa es que las listas van.
        print(f"Sesión activa, cuenta id {usuario[1:]}{origen}")
        print("  (no se pudo leer tu nombre de usuario, pero el endpoint de "
              "listas responde, que es lo que hace falta)")
    elif estado == "viva":
        print(f"Sesión activa como @{usuario}{origen}")
    else:
        print("Aviso: no se pudo confirmar la sesión; los endpoints de "
              "comprobación no respondieron.")
        print("Se continúa igualmente, porque las cookies pueden ser válidas. "
              "Si lo siguiente falla, reinicia sesión en el navegador.")

    _SESION_CACHE = s
    _SESION_HASTA = time.monotonic() + CACHE_SESION
    return s


# ======================================================================
# PRESUPUESTO DE PETICIONES
# ======================================================================
# El cuello de botella de este proyecto no es el código, es cuántas
# peticiones aguanta Instagram antes de cortar. Sin contarlas se trabaja a
# ciegas: los tres bloqueos de los primeros días se descubrieron por la
# traza del error, no por ningún aviso previo.

TOPE_DIARIO = 250                # peticiones por día antes de negarse
AVISO_AL = 0.70                  # a partir de aquí se avisa

_PRESUPUESTO: dict | None = None  # copia en memoria del archivo
# Incrementos aún no volcados a disco. Existen porque la ventana y la tarea
# programada corren a la vez: si cada proceso escribiera su copia entera, el
# último en guardar borraría lo que contó el otro. Se guardan los DELTAS y se
# suman a lo que haya en el archivo en ese momento.
_PENDIENTE = {"hechas": 0, "bloqueos": 0, "por_endpoint": {}}


class SinPresupuesto(Exception):
    """Se agotó el tope diario. No se arregla esperando un rato."""


def _ruta_presupuesto() -> Path:
    # No lleva el nombre de la cuenta objetivo: el límite es de la sesión
    # con la que entras, no de a quién mires.
    return CARPETA / "presupuesto.json"


class _cerrojo:
    """
    Exclusión entre procesos con un archivo .lock.

    Se hace con os.O_EXCL en vez de fcntl o msvcrt para que funcione igual
    en Windows y en Linux. Si no se consigue, se sigue de todas formas:
    perder una anotación es mejor que dejar colgado el trabajo.
    """

    def __init__(self, ruta: Path, intentos: int = 40):
        self.archivo = ruta.with_name(ruta.name + ".lock")
        self.intentos = intentos
        self.tomado = False

    def __enter__(self):
        for _ in range(self.intentos):
            try:
                fd = os.open(str(self.archivo),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.tomado = True
                return self
            except FileExistsError:
                try:
                    # Cerrojo huérfano de un proceso que murió a medias.
                    if time.time() - self.archivo.stat().st_mtime > 10:
                        self.archivo.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.01)
            except OSError:
                return self          # sin permisos: seguimos sin cerrojo
        return self

    def __exit__(self, *_):
        if self.tomado:
            try:
                self.archivo.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _leer_de_disco() -> dict:
    try:
        return json.loads(_ruta_presupuesto().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _presupuesto() -> dict:
    """Contadores de hoy. Se reinician solos al cambiar de día."""
    global _PRESUPUESTO
    hoy = f"{date.today():%Y-%m-%d}"

    if _PRESUPUESTO is None:
        _PRESUPUESTO = _leer_de_disco()

    if _PRESUPUESTO.get("dia") != hoy:
        # 'aprendido' NO se reinicia: saber qué endpoint funciona no caduca
        # a medianoche, y volver a descubrirlo cuesta peticiones.
        _PRESUPUESTO = {"dia": hoy, "hechas": 0, "bloqueos": 0,
                        "por_endpoint": {}, "primera": None, "ultima": None,
                        "aprendido": _PRESUPUESTO.get("aprendido", {})}
    return _PRESUPUESTO


def _guardar_presupuesto() -> None:
    """
    Vuelca al archivo sumando los incrementos sobre lo que haya AHORA.

    Nunca se escribe la copia en memoria tal cual: otro proceso puede haber
    anotado peticiones mientras tanto y se perderían.
    """
    global _PRESUPUESTO
    p = _presupuesto()
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        with _cerrojo(_ruta_presupuesto()):
            disco = _leer_de_disco()
            if disco.get("dia") != p["dia"]:
                disco = {"dia": p["dia"], "hechas": 0, "bloqueos": 0,
                         "por_endpoint": {}, "primera": None, "ultima": None,
                         "aprendido": {}}

            disco["hechas"] = disco.get("hechas", 0) + _PENDIENTE["hechas"]
            disco["bloqueos"] = (disco.get("bloqueos", 0)
                                 + _PENDIENTE["bloqueos"])
            reparto = disco.setdefault("por_endpoint", {})
            for clave, n in _PENDIENTE["por_endpoint"].items():
                reparto[clave] = reparto.get(clave, 0) + n
            disco["primera"] = disco.get("primera") or p.get("primera")
            disco["ultima"] = p.get("ultima") or disco.get("ultima")
            disco.setdefault("aprendido", {}).update(p.get("aprendido", {}))

            _ruta_presupuesto().write_text(
                json.dumps(disco, indent=2, ensure_ascii=False),
                encoding="utf-8")

        _PENDIENTE["hechas"] = 0
        _PENDIENTE["bloqueos"] = 0
        _PENDIENTE["por_endpoint"] = {}
        _PRESUPUESTO = disco      # la verdad es la del archivo, no la nuestra
    except OSError:
        pass                     # no poder anotarlo no debe frenar el trabajo


def anotar_peticion(ruta: str) -> None:
    p = _presupuesto()
    clave = _clave_endpoint(ruta)
    p["hechas"] = p.get("hechas", 0) + 1
    p["por_endpoint"][clave] = p["por_endpoint"].get(clave, 0) + 1
    _PENDIENTE["hechas"] += 1
    _PENDIENTE["por_endpoint"][clave] = (
        _PENDIENTE["por_endpoint"].get(clave, 0) + 1)
    ahora = datetime.now().strftime("%H:%M")
    p["primera"] = p["primera"] or ahora
    p["ultima"] = ahora
    _guardar_presupuesto()


def anotar_bloqueo_diario() -> None:
    p = _presupuesto()
    p["bloqueos"] = p.get("bloqueos", 0) + 1
    _PENDIENTE["bloqueos"] += 1
    _guardar_presupuesto()


def queda_presupuesto() -> int:
    return max(0, TOPE_DIARIO - _presupuesto().get("hechas", 0))


def factor_prudencia() -> float:
    """
    Multiplica las pausas si hoy ya nos han cortado.

    Seguir al mismo ritmo después de un bloqueo es pedir el siguiente.
    """
    bloqueos = _presupuesto().get("bloqueos", 0)
    if bloqueos >= 3:
        return 3.0
    if bloqueos >= 1:
        return 2.0
    return 1.0


def recordar_via(asunto: str, valor: str) -> None:
    """Guarda qué camino funcionó, para no volver a probar los que no."""
    p = _presupuesto()
    if p.setdefault("aprendido", {}).get(asunto) != valor:
        p["aprendido"][asunto] = valor
        _guardar_presupuesto()


def via_recordada(asunto: str) -> str | None:
    return _presupuesto().get("aprendido", {}).get(asunto)


def estimar_peticiones(seguidores: int, seguidos: int,
                       cuales: str = "ambas") -> int:
    """Cuántas peticiones costaría bajar esas listas."""
    total = 0
    if cuales in ("ambas", "seguidores"):
        total += max(1, -(-seguidores // POR_PAGINA))
    if cuales in ("ambas", "seguidos"):
        total += max(1, -(-seguidos // POR_PAGINA))
    return total


def resumen_presupuesto() -> str:
    p = _presupuesto()
    hechas = p.get("hechas", 0)
    texto = f"{hechas}/{TOPE_DIARIO} peticiones hoy"
    if p.get("bloqueos"):
        texto += f", {p['bloqueos']} bloqueo(s)"
    return texto




# ======================================================================
# RUTAS Y NOMBRES CONFIGURABLES
# ======================================================================
# Todo lo que Instagram puede cambiar y nos rompería está aquí, en un
# sitio y como DATOS. El día que cambie, repararlo es editar una línea de
# salida/rutas.json — sin tocar código y sin esperar a una versión nueva.
#
# Son tres cosas distintas y las tres pueden cambiar por separado:
#   rutas    la dirección del endpoint
#   params   cómo se llaman los parámetros que se le mandan
#   campos   cómo se llaman los datos que devuelve

RUTAS_BASE = {
    "lista_seguidores": "/api/v1/friendships/{id}/followers/",
    "lista_seguidos": "/api/v1/friendships/{id}/following/",
    "perfil": "/api/v1/users/web_profile_info/",
    "sesion_actual": "/api/v1/accounts/current_user/",
    "usuario_info": "/api/v1/users/{id}/info/",
    "buscador": "/api/v1/fbsearch/topsearch/",
    "pagina_perfil": "/{usuario}/",
}

PARAMS_BASE = {
    "cursor": "max_id",
    "cantidad": "count",
    "usuario": "username",
    "consulta": "query",
}

CAMPOS_BASE = {
    "usuarios": "users",
    "cursor_siguiente": "next_max_id",
    "nombre_usuario": "username",
    "identificador": "pk",
    "identificador_alt": "id",
    "perfil_raiz": "data.user",
    "seguidores_total": "edge_followed_by.count",
    "seguidos_total": "edge_follow.count",
}

_CONFIG: dict | None = None


def _ruta_config() -> Path:
    return CARPETA / "rutas.json"


def config() -> dict:
    """Rutas, parámetros y campos en uso. Lo del archivo pisa a lo de serie."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = {"rutas": dict(RUTAS_BASE), "params": dict(PARAMS_BASE),
                   "campos": dict(CAMPOS_BASE)}
        try:
            guardado = json.loads(_ruta_config().read_text(encoding="utf-8"))
            for seccion in ("rutas", "params", "campos"):
                if isinstance(guardado.get(seccion), dict):
                    _CONFIG[seccion].update(guardado[seccion])
        except (OSError, json.JSONDecodeError):
            pass          # sin archivo o ilegible: valores de serie
        _construir_contratos()
    return _CONFIG


def ruta(clave: str, **partes) -> str:
    plantilla = config()["rutas"].get(clave, RUTAS_BASE.get(clave, ""))
    return plantilla.format(**partes) if partes else plantilla


def param(clave: str) -> str:
    return config()["params"].get(clave, PARAMS_BASE.get(clave, clave))


def campo(clave: str) -> str:
    return config()["campos"].get(clave, CAMPOS_BASE.get(clave, clave))


def recargar_config() -> None:
    """Vuelve a leer rutas.json. Útil tras editarlo sin cerrar el programa."""
    global _CONFIG
    _CONFIG = None
    config()


def escribir_config_ejemplo() -> Path:
    """Deja el archivo con los valores actuales, listo para editar."""
    CARPETA.mkdir(parents=True, exist_ok=True)
    destino = _ruta_config()
    if not destino.exists():
        c = config()
        destino.write_text(json.dumps({
            "_ayuda": [
                "Todo lo que Instagram puede cambiar y aquí se puede",
                "reparar sin tocar código. Edita solo lo que haga falta;",
                "lo que borres vuelve a su valor de serie.",
                "Tras editar, reinicia el programa.",
            ],
            "rutas": c["rutas"], "params": c["params"], "campos": c["campos"],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    return destino


# ======================================================================
# CONTRATOS DE RESPUESTA
# ======================================================================
# Antes solo se miraba el código HTTP. Un 200 con la estructura cambiada
# pasaba por bueno y producía datos incorrectos EN SILENCIO, que es peor
# que romperse: romperse se nota.
#
# Los contratos comprueban que esté lo que hace falta y con el tipo
# correcto. NUNCA fallan porque Instagram añada campos: eso pasa a menudo
# y no rompe nada.

class RespuestaInesperada(Exception):
    """
    Instagram contestó, pero con otra forma. No se reintenta: esperar no
    devuelve una estructura que ha cambiado.
    """


AUSENTE = object()

MAX_CUERPO_VOLCADO = 8000        # caracteres guardados de la respuesta


def volcar_fallo(tipo: str, ruta_usada: str, codigo: int | None = None,
                 detalle: str = "", cuerpo=None, params: dict | None = None,
                 cabeceras: dict | None = None) -> Path | None:
    """
    Guarda la petición y la respuesta completas cuando algo se rompe.

    Existe porque 160 caracteres de mensaje no bastan para reparar nada.
    Con esto, quien lo arregle —tú, o yo en otra sesión— tiene el material.

    NUNCA se guardan cookies ni cabeceras de sesión: el archivo puede
    acabar compartido, y ahí va tu cuenta entera.
    """
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        sello = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        destino = CARPETA / f"fallo_{sello}.json"

        if isinstance(cuerpo, (dict, list)):
            texto = json.dumps(cuerpo, ensure_ascii=False)[:MAX_CUERPO_VOLCADO]
        else:
            texto = str(cuerpo or "")[:MAX_CUERPO_VOLCADO]

        seguras = {k: v for k, v in (cabeceras or {}).items()
                   if k.lower() not in ("cookie", "set-cookie",
                                        "authorization", "x-csrftoken")}

        destino.write_text(json.dumps({
            "cuando": datetime.now().isoformat(timespec="seconds"),
            "tipo": tipo,
            "ruta": ruta_usada,
            "parametros": params or {},
            "codigo_http": codigo,
            "detalle": detalle,
            "respuesta": texto,
            "cabeceras_respuesta": seguras,
            "rutas_en_uso": config()["rutas"],
            "campos_en_uso": config()["campos"],
            "nota": "Sin cookies ni cabeceras de sesión. Se puede compartir.",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Detalle completo guardado en {destino.name}")
        return destino
    except OSError:
        return None


def _buscar(datos, ruta: str):
    """Valor en una ruta con puntos, o AUSENTE si no está."""
    actual = datos
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return AUSENTE
        actual = actual[parte]
    return actual


class Contrato:
    """
    Lo mínimo que debe traer una respuesta para poder fiarse de ella.

    `alternativas_elemento` acepta varias rutas de las que basta una:
    Instagram usa 'pk' en unos endpoints e 'id' en otros para lo mismo.
    """

    def __init__(self, nombre: str, campos=(), coleccion: str | None = None,
                 campos_elemento=(), alternativas_elemento=()):
        self.nombre = nombre
        self.campos = campos
        self.coleccion = coleccion
        self.campos_elemento = campos_elemento
        self.alternativas_elemento = alternativas_elemento

    def _fallo(self, motivo: str, datos) -> None:
        # Enseñar lo que SÍ llegó es lo que hace barata la reparación.
        claves = (", ".join(sorted(datos)[:8]) if isinstance(datos, dict)
                  else type(datos).__name__)
        raise RespuestaInesperada(
            f"la respuesta de '{self.nombre}' no tiene la forma esperada: "
            f"{motivo}. Lo que llegó: [{claves}]. "
            "Instagram cambió ese endpoint; hay que ajustar el contrato.")

    @staticmethod
    def _nombres(tipos) -> str:
        if not isinstance(tipos, tuple):
            tipos = (tipos,)
        return " o ".join(t.__name__ for t in tipos)

    def _exigir(self, datos, ruta, tipos, donde=""):
        valor = _buscar(datos, ruta)
        if valor is AUSENTE:
            self._fallo(f"falta '{ruta}'{donde}", datos)
        if not isinstance(valor, tipos):
            self._fallo(f"'{ruta}'{donde} debería ser {self._nombres(tipos)} "
                        f"y es {type(valor).__name__}", datos)

    def validar(self, datos) -> None:
        if not isinstance(datos, dict):
            self._fallo(f"se esperaba un objeto y llegó "
                        f"{type(datos).__name__}", datos)

        for ruta, tipos in self.campos:
            self._exigir(datos, ruta, tipos)

        if not self.coleccion:
            return

        elementos = _buscar(datos, self.coleccion)
        if elementos is AUSENTE or not isinstance(elementos, list):
            self._fallo(f"'{self.coleccion}' debería ser una lista", datos)
        if not elementos:
            return               # lista vacía es legítima: fin de página

        # Basta con revisar el primero: si el formato cambió, cambió para
        # todos, y revisar cincuenta por página no aporta nada.
        primero = elementos[0]
        if not isinstance(primero, dict):
            self._fallo(f"los elementos de '{self.coleccion}' no son objetos",
                        datos)

        donde = f" en los elementos de '{self.coleccion}'"
        for ruta, tipos in self.campos_elemento:
            self._exigir(primero, ruta, tipos, donde)

        for rutas, tipos in self.alternativas_elemento:
            if not any(isinstance(_buscar(primero, r), tipos) for r in rutas):
                self._fallo(f"falta {' o '.join(rutas)}{donde}", primero)


CONTRATOS: dict = {}


def _construir_contratos() -> None:
    """
    Los contratos se arman con los nombres de campo configurados.

    Así, renombrar 'users' en rutas.json arregla a la vez la lectura y la
    validación: si no, el contrato seguiría exigiendo el nombre viejo.
    """
    usuarios = campo("usuarios")
    nombre = campo("nombre_usuario")
    ident, ident_alt = campo("identificador"), campo("identificador_alt")
    raiz = campo("perfil_raiz")

    CONTRATOS.clear()
    CONTRATOS.update({
        "lista": Contrato(
            "página de seguidores o seguidos",
            coleccion=usuarios,
            campos_elemento=[(nombre, str)],
            alternativas_elemento=[((ident, ident_alt), (str, int))]),

        "perfil": Contrato(
            "perfil por la API",
            campos=[(raiz, dict), (f"{raiz}.{ident_alt}", (str, int)),
                    (f"{raiz}.{nombre}", str)]),

        "busqueda": Contrato(
            "resultado del buscador",
            coleccion=usuarios,
            campos_elemento=[(f"user.{nombre}", str)],
            alternativas_elemento=[((f"user.{ident}", f"user.{ident_alt}"),
                                    (str, int))]),
    })


def validar(clave: str, datos: dict, ruta_usada: str = "") -> dict:
    """Comprueba el contrato y devuelve los datos, para poder encadenar."""
    config()                    # asegura que los contratos estén armados
    contrato = CONTRATOS.get(clave)
    if contrato:
        try:
            contrato.validar(datos)
        except RespuestaInesperada as e:
            volcar_fallo("forma inesperada", ruta_usada or clave,
                         detalle=str(e), cuerpo=datos)
            raise
    return datos


def pedir(s: requests.Session, ruta: str, params: dict | None = None,
          referer: str | None = None) -> dict:
    """GET a la API interna. Lanza Bloqueado, SesionInvalida o NoEncontrado."""
    if queda_presupuesto() <= 0:
        raise SinPresupuesto(
            f"tope diario alcanzado ({TOPE_DIARIO} peticiones). Se reinicia "
            "mañana; súbelo en TOPE_DIARIO si de verdad hace falta.")

    queda = espera_pendiente(ruta)
    if queda > 0:
        raise Bloqueado(
            f"'{_clave_endpoint(ruta)}' bloqueado hace poco. Faltan "
            f"{queda // 60 + 1} min; insistir ahora solo lo alarga.")

    anotar_peticion(ruta)
    cabeceras = {"Referer": referer} if referer else None
    try:
        r = s.get(BASE + ruta, params=params, headers=cabeceras, timeout=30)
    except requests.RequestException as e:
        raise Bloqueado(f"error de red: {e}") from e

    if r.status_code == 429:
        _marcar_bloqueo(ruta)
        anotar_bloqueo_diario()
        raise Bloqueado(
            f"HTTP 429 en '{_clave_endpoint(ruta)}'. Ese endpoint queda en "
            f"cuarentena {ESPERA_TRAS_429 // 60} min; los demás siguen.")

    if r.status_code in (401, 403):
        # Instagram usa 401 tanto para "sesión caída" como para "frena".
        # Antes se sondeaba con 3 peticiones más para distinguirlo: acelerar
        # justo cuando te piden frenar. Ahora se trata como bloqueo, que es
        # lo más probable y lo único seguro; si de verdad caducó, la próxima
        # verificación de sesión lo detectará sin gastar nada extra.
        _marcar_bloqueo(ruta, 300)
        raise Bloqueado(f"petición rechazada (HTTP {r.status_code}). "
                        "Puede ser límite de peticiones o sesión caducada; "
                        "espera 5 minutos y, si sigue, reimporta la sesión.")

    if r.status_code == 404:
        raise NoEncontrado("Instagram devolvió 404")
    if r.status_code >= 500:
        raise Bloqueado(f"Instagram devolvió HTTP {r.status_code}")
    if r.status_code != 200:
        # Se incluye lo que contesta Instagram: sin eso, un 400 es un
        # callejón sin salida y no hay forma de saber qué le molestó.
        detalle = (r.text or "")[:160].replace("\n", " ").strip()
        volcar_fallo("HTTP inesperado", ruta, codigo=r.status_code,
                     detalle=detalle, cuerpo=r.text, params=params,
                     cabeceras=dict(getattr(r, "headers", {}) or {}))
        raise PeticionRechazada(
            f"HTTP {r.status_code} en '{_clave_endpoint(ruta)}'"
            + (f" — Instagram dice: {detalle}" if detalle else ""))

    try:
        return r.json()
    except ValueError as e:
        raise Bloqueado("la respuesta no era JSON (¿te pidió un captcha?)") from e


def _pedir_texto(s: requests.Session, ruta: str,
                 referer: str | None = None) -> str:
    """Descarga una página normal (HTML), no la API interna."""
    if queda_presupuesto() <= 0:
        raise SinPresupuesto(f"tope diario alcanzado ({TOPE_DIARIO}).")
    queda = espera_pendiente(ruta)
    if queda > 0:
        raise Bloqueado(f"'{_clave_endpoint(ruta)}' en cuarentena "
                        f"{queda // 60 + 1} min más.")
    anotar_peticion(ruta)
    cabeceras = {"Accept": "text/html,application/xhtml+xml",
                 "Sec-Fetch-Dest": "document",
                 "Sec-Fetch-Mode": "navigate"}
    if referer:
        cabeceras["Referer"] = referer
    try:
        r = s.get(BASE + ruta, headers=cabeceras, timeout=30)
    except requests.RequestException as e:
        raise Bloqueado(f"error de red: {e}") from e
    if r.status_code == 429:
        _marcar_bloqueo(ruta)
        anotar_bloqueo_diario()
        raise Bloqueado(f"HTTP 429 al abrir {ruta}")
    if r.status_code == 404:
        raise NoEncontrado(f"la página {ruta} no existe")
    if r.status_code != 200:
        raise Bloqueado(f"HTTP {r.status_code} al abrir {ruta}")
    return r.text


def _numero(texto: str) -> int:
    """
    '4,820' o '4.820' -> 4820.  '1.2M' o '1,2M' -> 1200000.

    El punto es separador de miles o coma decimal según haya sufijo o no:
    tratarlo siempre igual convertía 1.2M en doce millones, y ese número
    alimenta la detección de capturas truncadas.
    """
    t = texto.strip().replace(" ", "").replace("\u202f", "")
    if not t:
        return 0

    if t[-1].upper() in "KM":
        multiplicador = 1000 if t[-1].upper() == "K" else 1000000
        try:
            return int(float(t[:-1].replace(",", ".")) * multiplicador)
        except ValueError:
            return 0

    try:
        return int(t.replace(",", "").replace(".", ""))
    except ValueError:
        return 0


def perfil_desde_html(s: requests.Session, username: str) -> dict:
    """
    Saca el perfil de la PÁGINA del usuario, como haría un navegador.

    Existe porque /api/v1/users/web_profile_info/ devuelve 429 a la primera
    petición aunque el resto de la API responda. La página normal no está
    tan vigilada.
    """
    html = _pedir_texto(s, ruta("pagina_perfil", usuario=username),
                        referer=BASE + "/")

    uid = ""
    for patron in (r'"profile_id"\s*:\s*"(\d+)"',
                   r'"user_id"\s*:\s*"(\d+)"',
                   r'profilePage_(\d+)',
                   r'"owner"\s*:\s*\{\s*"id"\s*:\s*"(\d+)"'):
        hallado = re.search(patron, html)
        if hallado:
            uid = hallado.group(1)
            break
    if not uid:
        raise NoEncontrado(
            f"no se encontró el identificador de '{username}' en la página")

    # La meta og:description trae los tres números de golpe.
    seguidores = seguidos = 0
    meta = re.search(r'property="og:description"\s+content="([^"]+)"', html)
    if meta:
        texto = meta.group(1)
        f = re.search(r"([\d.,KMkm]+)\s*(?:Followers|seguidores)", texto, re.I)
        g = re.search(r"([\d.,KMkm]+)\s*(?:Following|seguidos|siguiendo)",
                      texto, re.I)
        seguidores = _numero(f.group(1)) if f else 0
        seguidos = _numero(g.group(1)) if g else 0

    privada = '"is_private":true' in html.replace(" ", "")
    return {
        "id": uid,
        "username": username,
        "nombre": "",
        "seguidores": seguidores,
        "seguidos": seguidos,
        "privada": privada,
        # Desde la página no se puede saber. None = "no consta", que NO es
        # lo mismo que False: así quien decida puede avisar en vez de dar
        # por hecho que sí la sigues.
        "la_sigo": None,
        "totales_fiables": bool(seguidores or seguidos),
        "origen": "página del perfil",
    }


def perfil_desde_busqueda(s: requests.Session, username: str) -> dict:
    """Último recurso: el buscador. Da el id, pero no los totales."""
    destino = ruta("buscador")
    d = validar("busqueda", pedir(s, destino, {param("consulta"): username}),
                destino)
    for entrada in d.get(campo("usuarios")) or []:
        u = entrada.get("user") or {}
        if str(u.get("username", "")).lower() == username.lower():
            return {
                "id": str(u.get("pk") or u.get("id") or ""),
                "username": u.get("username", username),
                "nombre": u.get("full_name", ""),
                "seguidores": 0,
                "seguidos": 0,
                "privada": bool(u.get("is_private")),
                "la_sigo": None,
                "totales_fiables": False,   # el buscador no los trae
                "origen": "buscador (sin totales)",
            }
    raise NoEncontrado(f"el buscador no encontró '{username}'")


def perfil(s: requests.Session, username: str) -> dict:
    """
    Datos básicos del perfil, por el primer camino que funcione.

    Se prueban tres rutas porque la mejor está muy vigilada: en la práctica
    devuelve 429 mientras el resto de la API responde con normalidad.

    La que funcionó queda recordada y se prueba primero la próxima vez. Sin
    eso se gastaba una petición en fallar a propósito en cada operación, y
    el registro se llenaba de un error que no lo era.
    """
    rutas = [
        ("web_profile_info", _perfil_desde_api),
        ("página del perfil", perfil_desde_html),
        ("buscador", perfil_desde_busqueda),
    ]
    recordada = via_recordada("perfil")
    if recordada:
        rutas.sort(key=lambda x: x[0] != recordada)

    problemas = []
    for nombre, funcion in rutas:
        try:
            p = funcion(s, username)
        except NoEncontrado:
            raise                    # el perfil no existe: no hay que insistir
        except (Bloqueado, SinPresupuesto, RespuestaInesperada) as e:
            # Si una vía cambió de forma, se prueba la siguiente: para eso
            # están. Pero queda anotado en el resumen del error.
            problemas.append(f"{nombre}: {e}")
            continue
        recordar_via("perfil", nombre)
        if nombre != "web_profile_info":
            print(f"  (datos obtenidos por {nombre})")
        return p

    raise Bloqueado("no se pudo leer el perfil por ninguna vía:\n    "
                    + "\n    ".join(problemas))


def _perfil_desde_api(s: requests.Session, username: str) -> dict:
    """La vía buena cuando funciona: un solo GET con todo."""
    # El navegador manda el Referer del propio perfil al pedir esto.
    destino = ruta("perfil")
    d = pedir(s, destino, {param("usuario"): username},
              referer=BASE + ruta("pagina_perfil", usuario=username))
    if _buscar(d, campo("perfil_raiz")) in (AUSENTE, None):
        raise NoEncontrado(f"el perfil '{username}' no existe o no es visible")
    validar("perfil", d, destino)
    u = _buscar(d, campo("perfil_raiz"))

    # Los totales solo se dan por fiables si de verdad llegaron. Antes se
    # marcaban fiables siempre, así que un cambio de nombre en esos campos
    # habría reportado 0 seguidores como dato bueno.
    seguidores = _buscar(u, campo("seguidores_total"))
    seguidos = _buscar(u, campo("seguidos_total"))
    fiables = isinstance(seguidores, int) and isinstance(seguidos, int)

    return {
        "id": str(u[campo("identificador_alt")]),
        "username": u[campo("nombre_usuario")],
        "nombre": u.get("full_name", ""),
        "seguidores": seguidores if fiables else 0,
        "seguidos": seguidos if fiables else 0,
        "privada": bool(u.get("is_private")),
        "la_sigo": bool(u.get("followed_by_viewer")),
        "totales_fiables": fiables,
        "origen": "web_profile_info",
    }


# ======================================================================
# ARCHIVOS
# ======================================================================

def _ruta_parcial(tipo: str) -> Path:
    return CARPETA / f"{OBJETIVO}_{tipo}_parcial.csv"


def _ruta_estado(tipo: str) -> Path:
    return CARPETA / f".estado_{OBJETIVO}_{tipo}.json"


def _ruta_captura(tipo: str, dia: str | None = None) -> Path:
    dia = dia or f"{date.today():%Y-%m-%d}"
    return CARPETA / f"{OBJETIVO}_{tipo}_{dia}.csv"


def _ruta_meta(captura: Path) -> Path:
    return captura.with_name("." + captura.stem + ".meta.json")


def _leer_csv(ruta: Path) -> list[dict]:
    """Filas de un CSV de perfiles. Devuelve [] si no existe."""
    if not ruta.exists():
        return []
    filas = []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        for fila in csv.DictReader(f):
            if fila.get("username") or fila.get("id"):
                filas.append(fila)
    return filas


def _escribir_csv(ruta: Path, cabecera: list, filas: list) -> None:
    """Escribe un CSV completo con BOM, para que Excel respete los acentos."""
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)


def _cabecera_de(ruta: Path) -> list:
    """
    Cabecera real de un CSV ya existente.

    Importa para no corromper archivos: un parcial empezado con la cabecera
    antigua de 3 columnas debe seguir escribiéndose con 3 columnas, aunque
    esta versión del módulo conozca más campos.
    """
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f), [])


def _valor(u: dict, ruta: str) -> str:
    """
    Saca un campo del usuario siguiendo una ruta con puntos.
    Si no existe, devuelve cadena vacía en vez de fallar.
    """
    actual = u
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return ""
        actual = actual[parte]
    if isinstance(actual, bool):
        return "si" if actual else "no"
    if actual is None:
        return ""
    return str(actual)


def _dict_usuario(u: dict) -> dict:
    """Convierte un usuario de la API en el diccionario que guardamos."""
    fila = {"username": u.get("username", ""),
            "nombre": u.get("full_name", ""),
            "id": str(u.get("pk") or u.get("id") or "")}
    for nombre, ruta in CAMPOS_EXTRA:
        fila[nombre] = _valor(u, ruta)
    return fila


def _fila(d: dict, cabecera: list) -> list:
    """Ordena un diccionario según la cabecera dada, rellenando huecos."""
    return [d.get(c, "") or "" for c in cabecera]


def _resumen_campos(filas: list) -> list:
    """Cuenta las señales útiles, solo de las columnas que traen datos."""
    lineas = []
    total = len(filas)
    for nombre, _ in CAMPOS_EXTRA:
        valores = [f.get(nombre) for f in filas]
        con_dato = [v for v in valores if v in ("si", "no")]
        if not con_dato:
            continue                            # Instagram no manda ese campo
        cuantos = sum(1 for v in con_dato if v == "si")
        lineas.append(f"{nombre}: {cuantos} de {total}")
    return lineas


def _leer_estado(tipo: str) -> dict | None:
    ruta = _ruta_estado(tipo)
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _escribir_estado(tipo: str, cursor: str, pagina: int, total: int) -> None:
    _ruta_estado(tipo).write_text(
        json.dumps({"cursor": cursor, "pagina": pagina,
                    "total_esperado": total,
                    "actualizado": datetime.now().isoformat(timespec="seconds")},
                   indent=2),
        encoding="utf-8",
    )


def _escribir_meta(captura: Path, completa: bool, esperados: int,
                   obtenidos: int, motivo: str) -> None:
    _ruta_meta(captura).write_text(
        json.dumps({"completa": completa, "esperados": esperados,
                    "obtenidos": obtenidos, "motivo": motivo,
                    "cerrada": datetime.now().isoformat(timespec="seconds")},
                   indent=2),
        encoding="utf-8",
    )


def _leer_meta(captura: Path) -> dict:
    """Metadatos de una captura. Sin archivo -> completa = None (desconocido)."""
    ruta = _ruta_meta(captura)
    if not ruta.exists():
        return {"completa": None, "motivo": "sin metadatos"}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"completa": None, "motivo": "metadatos ilegibles"}


# ======================================================================
# DESCARGA
# ======================================================================

def _una_pasada(s: requests.Session, uid: str, tipo: str,
                total: int) -> tuple[int, str]:
    """
    Recorre las páginas escribiendo al CSV parcial.
    Devuelve (cuántos hay, motivo) con motivo en {"completa", "truncada"}.
    Lanza Bloqueado si Instagram corta (el progreso queda guardado).
    """
    parcial = _ruta_parcial(tipo)

    vistos = {f["id"] for f in _leer_csv(parcial) if f.get("id")}
    estado = _leer_estado(tipo)
    cursor = (estado or {}).get("cursor", "")
    pagina = (estado or {}).get("pagina", 0)

    if vistos:
        print(f"  Retomando: {len(vistos)} ya guardados.")

    nuevo = not parcial.exists()
    # Un parcial empezado con una cabecera antigua se sigue escribiendo con
    # ella; si no, el CSV quedaría con filas de distinta anchura.
    cabecera = CABECERA if nuevo else (_cabecera_de(parcial) or CABECERA)
    vacias_seguidas = 0
    motivo = "completa"

    # El parcial es un archivo de trabajo interno: utf-8 plano, sin BOM,
    # porque se abre en modo añadir. El BOM se pone al cerrar la captura.
    with open(parcial, "a", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        if nuevo:
            escritor.writerow(cabecera)
            f.flush()

        pagina_actual = POR_PAGINA
        while True:
            _revisar_cancelacion()
            clave_ruta = ("lista_seguidores" if tipo == "seguidores"
                          else "lista_seguidos")
            destino_ruta = ruta(clave_ruta, id=uid)
            params = {param("cantidad"): pagina_actual}
            if cursor:
                params[param("cursor")] = cursor

            try:
                d = validar("lista", pedir(s, destino_ruta, params),
                            destino_ruta)
            except PeticionRechazada as e:
                # Con cursor, un 400 suele ser el tamaño de página: algunas
                # listas dejan de aceptar 50 a partir de cierto punto. Se
                # prueba UNA vez con una página pequeña; si tampoco, se para.
                if (not cursor
                        or params[param("cantidad")] == POR_PAGINA_MINIMO):
                    print()
                    print(f"  {e}")
                    motivo = "rechazada"
                    break
                print(f"\n  {e}")
                print(f"  Reintentando esa página con {POR_PAGINA_MINIMO} "
                      "en vez de {POR_PAGINA}...".replace(
                          "{POR_PAGINA}", str(POR_PAGINA)))
                params[param("cantidad")] = POR_PAGINA_MINIMO
                try:
                    d = validar("lista", pedir(s, destino_ruta, params),
                                destino_ruta)
                except PeticionRechazada as e2:
                    print(f"  Tampoco: {e2}")
                    motivo = "rechazada"
                    break
                # Funcionó: nos quedamos con la página pequeña a partir de aquí
                pagina_actual = POR_PAGINA_MINIMO
            pagina += 1

            usuarios = d.get(campo("usuarios")) or []
            for u in usuarios:
                fila = _dict_usuario(u)
                if not fila["id"] or fila["id"] in vistos:
                    continue
                escritor.writerow(_fila(fila, cabecera))
                vistos.add(fila["id"])
            f.flush()

            # Contra None, no por veracidad: un cursor 0 o "0" es válido.
            crudo = d.get(campo("cursor_siguiente"))
            cursor = "" if crudo is None else str(crudo)
            if cursor:
                _escribir_estado(tipo, cursor, pagina, total)

            print(f"  {len(vistos)}/{total or '?'}   (página {pagina})    ",
                  end="\r", flush=True)

            if usuarios:
                vacias_seguidas = 0
            else:
                vacias_seguidas += 1
                if vacias_seguidas >= PAGINAS_VACIAS:
                    print()
                    print("  Instagram dejó de devolver resultados.")
                    motivo = "truncada"
                    break

            if not cursor:
                break

            prudencia = factor_prudencia()
            _dormir(random.uniform(PAUSA_MIN, PAUSA_MAX) * prudencia)
            if pagina % DESCANSO_CADA == 0:
                espera = DESCANSO_SEG * prudencia
                print(f"\n  Descanso de {espera:.0f}s tras {pagina} páginas"
                      + ("  (ritmo reducido: hoy ya hubo bloqueos)"
                         if prudencia > 1 else "") + "...")
                _dormir(espera)

    print()
    return len(vistos), motivo


def _cuantos_llevamos(tipo: str) -> int:
    """Registros ya guardados en el parcial (vale también tras un corte)."""
    return len(_leer_csv(_ruta_parcial(tipo)))


def _cerrar_captura(tipo: str, total: int, motivo: str,
                    fiable: bool = True) -> Path:
    """Convierte el CSV parcial en la captura del día y la etiqueta."""
    parcial = _ruta_parcial(tipo)
    destino = _ruta_captura(tipo)
    filas = _leer_csv(parcial)

    # La cabecera final es la unión de las dos, por si el parcial y la captura
    # de hoy se escribieron con versiones distintas del módulo.
    cabecera = _cabecera_de(parcial) or CABECERA
    cabecera = cabecera + [c for c in _cabecera_de(destino) if c not in cabecera]

    # Si ya hay una captura de hoy (p.ej. una pasada anterior truncada),
    # fusionamos por id en vez de pisarla.
    if destino.exists():
        vistos = {f["id"] for f in filas if f.get("id")}
        recuperadas = [f for f in _leer_csv(destino)
                       if f.get("id") and f["id"] not in vistos]
        if recuperadas:
            print(f"  Fusionado con la captura de hoy: "
                  f"+{len(recuperadas)} que no salieron esta vez.")
            filas += recuperadas
            if motivo == "truncada":
                motivo = "truncada (fusionada con la pasada anterior)"

    _escribir_csv(destino, cabecera, [_fila(f, cabecera) for f in filas])
    parcial.unlink(missing_ok=True)
    _ruta_estado(tipo).unlink(missing_ok=True)

    n = len(filas)
    corta = bool(total) and n < total * UMBRAL_COMPLETA

    if not fiable and motivo == "completa":
        # Sin totales de referencia no se puede afirmar que esté completa.
        # Marcarla como buena sería un fallo silencioso: el historial la
        # daría por válida y las bajas falsas parecerían reales.
        completa, motivo_final = None, ("no se pudo verificar: los totales "
                                        "de la cuenta no se leyeron")
    elif motivo == "rechazada":
        completa, motivo_final = False, ("Instagram rechazó la petición a "
                                          "mitad; no se pudo terminar")
    elif motivo == "completa" and not corta:
        completa, motivo_final = True, "completa"
    elif corta:
        completa, motivo_final = False, f"solo {n} de ~{total} esperados"
    else:
        completa, motivo_final = False, motivo

    _escribir_meta(destino, completa, total, n, motivo_final)
    anadir_cuenta(OBJETIVO)          # se registra sola la primera vez

    print(f"  Captura guardada: {destino.name}  ({n} registros)")
    for linea in _resumen_campos(filas):
        print(f"    {linea}")
    if completa is None:
        print(f"  AVISO: {motivo_final}.")
        print("  Queda marcada como no verificada; 'historial' avisará de "
              "ella.")
    elif not completa:
        print(f"  AVISO: captura INCOMPLETA ({motivo_final}).")
        print("  Queda marcada como tal y 'comparar' no la usará.")
        print("  Vuelve a ejecutar 'bajar' en unas horas: se fusiona con esta.")
    return destino


def descargar(s: requests.Session, p: dict, tipo: str) -> None:
    """Descarga una lista con reintentos y espera creciente."""
    total = p["seguidores"] if tipo == "seguidores" else p["seguidos"]
    fiable = p.get("totales_fiables", True)
    print(f"\n{tipo.upper()}  (esperados: {total})")

    CARPETA.mkdir(parents=True, exist_ok=True)
    espera = ESPERA_INICIAL
    hechos = 0

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            hechos, motivo = _una_pasada(s, p["id"], tipo, total)
            _cerrar_captura(tipo, total, motivo, fiable)
            return
        except (SinPresupuesto, PeticionRechazada, RespuestaInesperada):
            raise                    # esperar no lo arregla; sale limpio
        except Bloqueado as e:
            hechos = _cuantos_llevamos(tipo)
            print(f"\n  Cortado: {e}")
        except KeyboardInterrupt:
            print("\n  Interrumpido. El progreso está guardado.")
            raise

        if intento == MAX_REINTENTOS:
            break

        print(f"  Llevamos {hechos}/{total or '?'}. Esperando "
              f"{espera // 60} min (intento {intento + 1}/{MAX_REINTENTOS})...")
        try:
            _dormir(espera)
        except KeyboardInterrupt:
            print("\n  Interrumpido. El progreso está guardado.")
            raise
        espera = min(espera * 2, ESPERA_MAXIMA)

    print(f"\n  Parado en {hechos}/{total or '?'}. El progreso está guardado; "
          "vuelve a ejecutar 'bajar' más tarde y seguirá desde ahí.")


# ======================================================================
# COMPARACIÓN
# ======================================================================

def _capturas(tipo: str) -> list[Path]:
    """Capturas fechadas, de la más antigua a la más reciente."""
    patron = f"{OBJETIVO}_{tipo}_"
    encontradas = []
    for ruta in CARPETA.glob(f"{patron}*.csv"):
        cola = ruta.stem[len(patron):]
        if len(cola) != 10:                      # descarta '_parcial'
            continue
        try:
            datetime.strptime(cola, "%Y-%m-%d")
        except ValueError:
            continue
        encontradas.append(ruta)
    return sorted(encontradas)                   # ISO ordena por fecha


def _fecha_de(ruta: Path) -> str:
    return ruta.stem.rsplit("_", 1)[-1]


def _filas_con_id(filas: list) -> bool:
    """¿Todas las filas traen id? Una sola sin él obliga a claves por nombre."""
    return all(f.get("id") for f in filas) if filas else True


def _indice_de_filas(filas: list, usar_id: bool) -> dict:
    """
    {clave: {"username", "nombre"}}. La clave es el id, o "@usuario" si se
    pide lo contrario.

    Es importante poder forzarlo: si en una serie de capturas unas traen ids
    y otras no, mezclar los dos criterios haría que la misma persona
    apareciera dos veces, una "yéndose" y otra "entrando".
    """
    indice = {}
    for f in filas:
        clave = f["id"] if usar_id and f.get("id") else "@" + f.get("username", "")
        indice[clave] = {"username": f.get("username", ""),
                         "nombre": f.get("nombre", "")}
    return indice


def _indexar(ruta: Path) -> tuple[dict, bool]:
    """Índice de una captura suelta. Devuelve también si pudo usar ids."""
    filas = _leer_csv(ruta)
    con_id = _filas_con_id(filas)
    return _indice_de_filas(filas, con_id), con_id


def _listar(titulo: str, claves: list, indice: dict) -> None:
    if not claves:
        return
    print(f"\n  {titulo}:")
    for c in claves[:MAX_LISTAR]:
        d = indice[c]
        print(f"    {d['username']}"
              + (f"   ({d['nombre']})" if d["nombre"] else ""))
    if len(claves) > MAX_LISTAR:
        print(f"    ... y {len(claves) - MAX_LISTAR} más (están en el CSV)")


def comparar(tipo: str, forzar: bool = False) -> dict | None:
    """
    Compara las dos últimas capturas.
    Devuelve {"indice", "fecha", "completa"} de la más reciente, o None.
    """
    archivos = _capturas(tipo)

    if not archivos:
        print(f"\n{tipo.upper()}: no hay ninguna captura todavía.")
        return None

    ultima = archivos[-1]
    indice_ult, id_ult = _indexar(ultima)
    resultado = {"indice": indice_ult, "fecha": _fecha_de(ultima),
                 "completa": _leer_meta(ultima).get("completa")}

    if len(archivos) == 1:
        print(f"\n{tipo.upper()}: solo hay una captura "
              f"({_fecha_de(ultima)}, {len(indice_ult)} registros).")
        print("  Ejecuta 'bajar' otro día para poder comparar.")
        return resultado

    r_antes, r_ahora = archivos[-2], archivos[-1]
    meta_antes, meta_ahora = _leer_meta(r_antes), _leer_meta(r_ahora)

    print(f"\n{tipo.upper()}   {_fecha_de(r_antes)} -> {_fecha_de(r_ahora)}")

    # Una captura truncada produce cientos de altas y bajas falsas.
    rotas = [(r, m) for r, m in ((r_antes, meta_antes), (r_ahora, meta_ahora))
             if m.get("completa") is False]
    if rotas and not forzar:
        print("  COMPARACIÓN CANCELADA: hay capturas incompletas.")
        for r, m in rotas:
            print(f"    - {_fecha_de(r)}: {m.get('motivo', '?')}")
        print("  Compararlas daría altas y bajas que no ocurrieron.")
        print("  Ejecuta 'bajar' para completarlas, o usa --forzar si aun así")
        print("  quieres el informe sabiendo que no es fiable.")
        return resultado
    if rotas:
        print("  ATENCIÓN: comparando capturas incompletas (--forzar).")
        print("  Las altas y bajas de abajo NO son fiables.")

    if meta_antes.get("completa") is None or meta_ahora.get("completa") is None:
        print("  Nota: alguna captura no tiene metadatos (creada con la v1). "
              "Si salió truncada, este informe exagerará los cambios.")

    antes, id_antes = _indexar(r_antes)
    ahora, id_ahora = indice_ult, id_ult      # ya leída arriba, no releer
    if not (id_antes and id_ahora):
        print("  Nota: alguna captura no guarda ids; se compara por nombre de "
              "usuario, así que un cambio de nombre saldrá como baja + alta.")

    entraron = sorted(set(ahora) - set(antes), key=lambda c: ahora[c]["username"])
    salieron = sorted(set(antes) - set(ahora), key=lambda c: antes[c]["username"])
    renombrados = sorted(
        (c for c in set(antes) & set(ahora)
         if antes[c]["username"] != ahora[c]["username"]),
        key=lambda c: ahora[c]["username"])
    neto = len(ahora) - len(antes)

    print(f"  Antes: {len(antes)}    Ahora: {len(ahora)}    Neto: {neto:+d}")
    print(f"  Entraron: {len(entraron)}    Salieron: {len(salieron)}"
          + (f"    Cambiaron de nombre: {len(renombrados)}"
             if renombrados else ""))
    if neto == 0 and (entraron or salieron):
        print("  (el total no cambió, pero las personas sí)")

    _listar("ENTRARON", entraron, ahora)
    _listar("SALIERON", salieron, antes)
    if renombrados:
        print("\n  CAMBIARON DE NOMBRE (misma persona, mismo id):")
        for c in renombrados[:MAX_LISTAR]:
            print(f"    {antes[c]['username']}  ->  {ahora[c]['username']}")
        if len(renombrados) > MAX_LISTAR:
            print(f"    ... y {len(renombrados) - MAX_LISTAR} más")

    # Lleva el nombre de la cuenta: sin él, comparar dos cuentas el mismo
    # día dejaba un solo archivo y la segunda pisaba a la primera.
    informe = CARPETA / f"cambios_{OBJETIVO}_{tipo}_{_fecha_de(r_ahora)}.csv"
    filas = [["entro", ahora[c]["username"], ahora[c]["nombre"], ""]
             for c in entraron]
    filas += [["salio", antes[c]["username"], antes[c]["nombre"], ""]
              for c in salieron]
    filas += [["renombro", ahora[c]["username"], ahora[c]["nombre"],
               antes[c]["username"]] for c in renombrados]
    _escribir_csv(informe,
                  ["cambio", "username", "nombre", "username_anterior"], filas)
    print(f"\n  Informe: {informe.name}")

    return resultado


def relaciones(seguidores: dict | None, seguidos: dict | None) -> None:
    """Cruce entre las últimas capturas de ambas listas."""
    if not seguidores or not seguidos:
        return

    print("\nRELACIONES")
    if seguidores["fecha"] != seguidos["fecha"]:
        print(f"  ATENCIÓN: se cruzan capturas de fechas distintas "
              f"(seguidores {seguidores['fecha']}, "
              f"seguidos {seguidos['fecha']}).")
        print("  Ejecuta 'bajar' para tener ambas del mismo día.")
    else:
        print(f"  Capturas del {seguidores['fecha']}.")

    rotas = [n for n, d in (("seguidores", seguidores), ("seguidos", seguidos))
             if d["completa"] is False]
    if rotas:
        print(f"  ATENCIÓN: {' y '.join(rotas)} están incompletas; "
              "los números de abajo se quedan cortos.")

    a, b = seguidores["indice"], seguidos["indice"]
    mutuos = sorted(set(a) & set(b), key=lambda c: a[c]["username"])
    no_devuelven = sorted(set(b) - set(a), key=lambda c: b[c]["username"])
    no_correspondidos = sorted(set(a) - set(b), key=lambda c: a[c]["username"])

    print(f"  Mutuos: {len(mutuos)}")
    print(f"  Sigue y no le devuelven el follow: {len(no_devuelven)}")
    print(f"  Le siguen y no les devuelve el follow: {len(no_correspondidos)}")

    _listar("NO LE DEVUELVEN EL FOLLOW", no_devuelven, b)

    informe = CARPETA / f"relaciones_{OBJETIVO}.csv"
    filas = [["mutuo", a[c]["username"], a[c]["nombre"]] for c in mutuos]
    filas += [["no_devuelve", b[c]["username"], b[c]["nombre"]]
              for c in no_devuelven]
    filas += [["no_correspondido", a[c]["username"], a[c]["nombre"]]
              for c in no_correspondidos]
    _escribir_csv(informe, ["relacion", "username", "nombre"], filas)
    print(f"\n  Informe: {informe.name}")


def tendencia_totales() -> None:
    """
    Cuántos había en cada captura, para ver la evolución del número.

    Ojo con el nombre: esto NO es 'historial'. Aquí solo salen totales;
    'historial' es la trayectoria de cada persona.
    """
    for tipo in ("seguidores", "seguidos"):
        archivos = _capturas(tipo)
        if not archivos:
            continue
        print(f"\n{tipo.upper()}")
        previo = None
        for ruta in archivos:
            n = len(_leer_csv(ruta))
            meta = _leer_meta(ruta)
            if meta.get("completa") is False:
                # No se compara contra una incompleta: el delta sería falso.
                print(f"  {_fecha_de(ruta)}   {n}   INCOMPLETA")
                continue
            marca = "" if meta.get("completa") else "   (sin metadatos)"
            delta = f"  ({n - previo:+d})" if previo is not None else ""
            print(f"  {_fecha_de(ruta)}   {n}{delta}{marca}")
            previo = n


# ======================================================================
# HISTORIAL POR PERSONA
# ======================================================================

def _sospechosas(serie: list) -> tuple[list, list]:
    """
    Separa las capturas cuyo tamaño se desploma respecto a la mediana.

    Una captura truncada o vacía haría parecer que cientos de personas se
    fueron y volvieron, que es justo el patrón que este análisis busca. Se
    compara contra la MEDIANA y no contra la anterior: así una bajada real
    y sostenida (que mueve la mediana) no se confunde con un fallo puntual.

    Hacen falta las DOS condiciones, relativa y absoluta. Solo con la
    relativa, en una lista de 3 personas que pierde 1 el 33% parecería un
    desplome, cuando es un cambio perfectamente normal.
    """
    if len(serie) < 2:
        return serie, []

    tamanos = [len(i) for _, i in serie]
    referencia = statistics.median(tamanos)
    if referencia <= 0:
        return serie, []

    buenas, malas = [], []
    for (fecha, indice), n in zip(serie, tamanos):
        if n < referencia * CAIDA_SOSPECHOSA and referencia - n >= CAIDA_MINIMA:
            malas.append((fecha, n, int(referencia)))
        else:
            buenas.append((fecha, indice))
    return buenas, malas


def _serie_capturas(tipo: str, incluir_sospechosas: bool = False) -> dict:
    """
    Prepara la serie de capturas para el historial, validándola antes.

    Descarta las marcadas como incompletas, avisa de las que no tienen
    metadatos y aparta las que se desploman de tamaño. Además decide UNA
    clave para toda la serie: si alguna captura no trae ids, todas pasan a
    indexarse por nombre de usuario, porque mezclar criterios duplicaría
    personas.
    """
    crudas, truncadas, sin_meta = [], [], []

    for ruta in _capturas(tipo):
        meta = _leer_meta(ruta)
        if meta.get("completa") is False:
            truncadas.append(_fecha_de(ruta))
            continue
        if meta.get("completa") is None:
            sin_meta.append(_fecha_de(ruta))
        crudas.append((_fecha_de(ruta), _leer_csv(ruta)))

    usar_id = all(_filas_con_id(filas) for _, filas in crudas)
    serie = [(fecha, _indice_de_filas(filas, usar_id))
             for fecha, filas in crudas]

    if incluir_sospechosas:
        buenas, malas = serie, []
    else:
        buenas, malas = _sospechosas(serie)

    return {"serie": buenas, "truncadas": truncadas, "sin_meta": sin_meta,
            "sospechosas": malas, "usar_id": usar_id}


def construir_historial(tipo: str,
                        incluir_sospechosas: bool = False) -> dict | None:
    """
    Cruza todas las capturas y reconstruye la trayectoria de cada persona.

    Devuelve un diccionario con la serie usada, los avisos y las personas,
    o None si no queda ninguna captura utilizable.
    Cada persona lleva: cuándo apareció, cuándo se fue, cuántas veces ha
    entrado y salido, y los nombres de usuario que ha tenido.
    """
    info = _serie_capturas(tipo, incluir_sospechosas)
    serie = info["serie"]
    if not serie:
        return None

    fechas = [f for f, _ in serie]
    claves = set()
    for _, idx in serie:
        claves |= set(idx)

    personas = {}
    for c in claves:
        presencia = [c in idx for _, idx in serie]

        nombres, ultimo = [], None
        for _, idx in serie:
            if c in idx:
                ultimo = idx[c]
                if not nombres or nombres[-1] != ultimo["username"]:
                    nombres.append(ultimo["username"])

        # Una "entrada" es aparecer viniendo de no estar (o estar ya en la
        # primera captura). Una "salida" es desaparecer habiendo estado.
        entradas = sum(1 for i, p in enumerate(presencia)
                       if p and (i == 0 or not presencia[i - 1]))
        salidas = sum(1 for i, p in enumerate(presencia)
                      if not p and i > 0 and presencia[i - 1])
        presentes = [f for f, p in zip(fechas, presencia) if p]

        personas[c] = {
            "username": ultimo["username"],
            "nombre": ultimo["nombre"],
            "id": "" if c.startswith("@") else c,
            "primera": presentes[0],
            "ultima": presentes[-1],
            "presente": presencia[-1],
            "capturas": sum(presencia),
            "entradas": entradas,
            "salidas": salidas,
            "nombres": nombres,
        }

    return {"fechas": fechas, "personas": personas,
            "truncadas": info["truncadas"], "sin_meta": info["sin_meta"],
            "sospechosas": info["sospechosas"], "usar_id": info["usar_id"]}


def _informe_historial(tipo: str, h: dict) -> Path:
    filas = []
    for p in sorted(h["personas"].values(),
                    key=lambda x: (-x["entradas"], x["username"])):
        filas.append([
            p["username"], p["nombre"], p["id"],
            p["primera"], p["ultima"],
            "presente" if p["presente"] else "ausente",
            p["capturas"], p["entradas"], p["salidas"],
            " -> ".join(p["nombres"][:-1]) if len(p["nombres"]) > 1 else "",
        ])
    ruta = CARPETA / f"historial_{tipo}_{OBJETIVO}.csv"
    _escribir_csv(ruta, ["username", "nombre", "id", "primera_vez",
                         "ultima_vez", "estado", "capturas_presente",
                         "entradas", "salidas", "nombres_anteriores"], filas)
    return ruta


def mostrar_historial(tipo: str, min_entradas: int = 2,
                      incluir_sospechosas: bool = False) -> None:
    """Imprime el resumen del historial y deja el CSV completo."""
    if min_entradas < 2:
        print(f"  (--min-entradas {min_entradas} no tiene sentido para 'ida y "
              "vuelta': todo el mundo entra al menos una vez. Se usa 2.)")
        min_entradas = 2

    h = construir_historial(tipo, incluir_sospechosas)
    if h is None:
        print(f"\n{tipo.upper()}: no hay capturas utilizables.")
        return

    fechas, personas = h["fechas"], h["personas"]
    print(f"\n{tipo.upper()}  —  {len(fechas)} capturas "
          f"({fechas[0]} ... {fechas[-1]})")

    # --- avisos de integridad, antes de cualquier número ---
    if h["truncadas"]:
        print(f"  Excluidas por incompletas: {', '.join(h['truncadas'])}")
    if h["sospechosas"]:
        print("  Excluidas por caída brusca de tamaño (probable descarga "
              "truncada):")
        for fecha, n, ref in h["sospechosas"]:
            print(f"    {fecha}: {n} registros frente a ~{ref} habituales")
        print("    Si la bajada fue real, repite con --incluir-sospechosas.")
    if h["sin_meta"]:
        print(f"  Sin metadatos (creadas por una versión antigua): "
              f"{', '.join(h['sin_meta'])}")
        print("    No se puede saber si estaban completas. La comprobación de "
              "tamaño de arriba es la única red.")
    if not h["usar_id"]:
        print("  Alguna captura no guarda ids: se indexa por nombre de "
              "usuario.")
        print("    Quien se haya cambiado el nombre contará como una baja y "
              "un alta.")

    if len(fechas) == 1:
        print(f"  Solo hay una captura, así que aún no hay trayectoria que "
              f"contar ({len(personas)} personas).")
        print("  Ejecuta 'bajar' o 'vigilar' otro día para empezar a comparar.")
        return

    presentes = [p for p in personas.values() if p["presente"]]
    idos = [p for p in personas.values() if not p["presente"]]
    repetidores = sorted((p for p in personas.values()
                          if p["entradas"] >= min_entradas),
                         key=lambda x: (-x["entradas"], x["username"]))
    renombrados = [p for p in personas.values() if len(p["nombres"]) > 1]
    desde_el_principio = [p for p in presentes
                          if p["primera"] == fechas[0] and p["salidas"] == 0]

    print(f"  Personas distintas vistas: {len(personas)}")
    print(f"  Presentes ahora: {len(presentes)}")
    print(f"  Se fueron y no han vuelto: {len(idos)}")
    print(f"  Han entrado {min_entradas} veces o más: {len(repetidores)}")
    print(f"  Ahí desde la primera captura, sin irse: "
          f"{len(desde_el_principio)}")
    if renombrados:
        print(f"  Han cambiado de nombre: {len(renombrados)}")

    if repetidores:
        print("\n  IDA Y VUELTA (entran y salen repetidamente):")
        for p in repetidores[:MAX_LISTAR]:
            estado = "presente" if p["presente"] else "ausente"
            print(f"    {p['username']:24} {p['entradas']} entradas, "
                  f"{p['salidas']} salidas   ahora {estado}")
        if len(repetidores) > MAX_LISTAR:
            print(f"    ... y {len(repetidores) - MAX_LISTAR} más")

    if idos:
        print("\n  SE FUERON (por fecha de salida, los más recientes):")
        for p in sorted(idos, key=lambda x: x["ultima"], reverse=True)[:MAX_LISTAR]:
            print(f"    {p['username']:24} visto por última vez el {p['ultima']}")
        if len(idos) > MAX_LISTAR:
            print(f"    ... y {len(idos) - MAX_LISTAR} más")

    ruta = _informe_historial(tipo, h)
    print(f"\n  Informe completo: {ruta.name}")

    if len(fechas) > 1:
        huecos = _mayor_hueco(fechas)
        if huecos > 1:
            print(f"\n  Nota: entre capturas llegan a pasar {huecos} días. "
                  "Quien entre y salga")
            print("  dentro de ese hueco no aparecerá aquí. Con 'vigilar' a "
                  "diario el detalle es diario.")


def _mayor_hueco(fechas: list) -> int:
    """Días máximos entre dos capturas consecutivas."""
    mayor = 0
    for a, b in zip(fechas, fechas[1:]):
        try:
            d1 = datetime.strptime(a, "%Y-%m-%d").date()
            d2 = datetime.strptime(b, "%Y-%m-%d").date()
        except ValueError:
            continue
        mayor = max(mayor, (d2 - d1).days)
    return mayor


def cmd_historial(args) -> None:
    if not CARPETA.exists():
        sys.exit(f"No existe '{CARPETA.name}'. Ejecuta 'bajar' primero.")
    tipos = (["seguidores", "seguidos"] if args.lista == "ambas"
             else [args.lista])
    for tipo in tipos:
        mostrar_historial(tipo, args.min_entradas, args.incluir_sospechosas)


# ======================================================================
# VARIAS CUENTAS OBJETIVO
# ======================================================================
# Los archivos ya llevan el nombre de la cuenta, así que conviven sin
# mezclarse. Lo que faltaba era la lista y el reparto.
#
# OJO: seguir más cuentas NO va más rápido. El límite es de tu sesión, no
# de a quién mires: cinco objetivos son cinco veces más peticiones por el
# mismo sitio. Por eso 'vigilar --todas' RACIONA en vez de paralelizar.

def _ruta_cuentas() -> Path:
    return CARPETA / "cuentas.txt"


def leer_cuentas() -> list:
    """Cuentas que se están siguiendo, en el orden del archivo."""
    ruta = _ruta_cuentas()
    if not ruta.exists():
        return []
    vistas, cuentas = set(), []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        nombre = limpiar_usuario(linea.split("#")[0])
        if not nombre or not PATRON_USUARIO.match(nombre):
            continue
        if nombre.lower() in vistas:
            continue
        vistas.add(nombre.lower())
        cuentas.append(nombre)
    return cuentas


def anadir_cuenta(nombre: str) -> bool:
    """Registra una cuenta. Devuelve True si era nueva."""
    nombre = limpiar_usuario(nombre)
    if not nombre or not PATRON_USUARIO.match(nombre):
        return False
    if nombre.lower() in {c.lower() for c in leer_cuentas()}:
        return False
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = _ruta_cuentas()
    if not ruta.exists():
        ruta.write_text("# Cuentas que sigues. Una por línea.\n"
                        "# Se añaden solas al descargarlas por primera vez.\n",
                        encoding="utf-8")
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(nombre + "\n")
    return True


def quitar_cuenta(nombre: str) -> bool:
    """Deja de seguirla. No borra sus capturas."""
    nombre = limpiar_usuario(nombre)
    quedan = [c for c in leer_cuentas() if c.lower() != nombre.lower()]
    if len(quedan) == len(leer_cuentas()):
        return False
    _ruta_cuentas().write_text(
        "# Cuentas que sigues. Una por línea.\n" + "\n".join(quedan) + "\n",
        encoding="utf-8")
    return True


@contextlib.contextmanager
def con_cuenta(nombre: str):
    """
    Trabaja sobre otra cuenta y devuelve OBJETIVO a su sitio al salir.

    Casi todo el módulo lee el global OBJETIVO para componer las rutas;
    esto evita tener que pasarlo por veinte funciones.
    """
    global OBJETIVO
    anterior = OBJETIVO
    OBJETIVO = nombre
    try:
        yield nombre
    finally:
        OBJETIVO = anterior


def estado_de_cuenta(nombre: str) -> dict:
    """Qué hay guardado de una cuenta, sin gastar peticiones."""
    with con_cuenta(nombre):
        capturas = {t: _capturas(t) for t in ("seguidores", "seguidos")}
        ultima = None
        for lista in capturas.values():
            if lista:
                fecha = _fecha_de(lista[-1])
                ultima = fecha if ultima is None else max(ultima, fecha)
        return {
            "cuenta": nombre,
            "capturas": sum(len(v) for v in capturas.values()),
            "ultima": ultima,
            "pendiente": any(_ruta_parcial(t).exists()
                             for t in ("seguidores", "seguidos")),
            "conteo": _ultimo_conteo(),
        }


def cmd_cuentas(args) -> None:
    """Ver, añadir o quitar cuentas seguidas. No gasta peticiones."""
    if args.anadir:
        for nombre in args.anadir:
            limpio = limpiar_usuario(nombre)
            if anadir_cuenta(nombre):
                print(f"  añadida: {limpio}")
            else:
                print(f"  ya estaba o no vale: {nombre}")
        return

    if args.quitar:
        for nombre in args.quitar:
            print(f"  {'quitada' if quitar_cuenta(nombre) else 'no estaba'}: "
                  f"{limpiar_usuario(nombre)}")
        print("  (sus capturas siguen en la carpeta)")
        return

    cuentas = leer_cuentas()
    if not cuentas:
        print("\nNo sigues ninguna cuenta todavía.")
        print("Se añaden solas al descargarlas, o con:  cuentas --anadir X")
        return

    print(f"\n{len(cuentas)} cuentas seguidas:")
    print(f"  {'cuenta':<24} {'capturas':>8}  última        estado")
    print("  " + "-" * 58)
    for nombre in cuentas:
        e = estado_de_cuenta(nombre)
        estado = "descarga a medias" if e["pendiente"] else ""
        print(f"  {nombre:<24} {e['capturas']:>8}  "
              f"{e['ultima'] or '—':<12}  {estado}")

    print(f"\n  Quedan {queda_presupuesto()} peticiones hoy para repartir "
          "entre todas.")




def _ruta_totales() -> Path:
    return CARPETA / f"totales_{OBJETIVO}.csv"


def _ruta_log() -> Path:
    return CARPETA / f"vigilancia_{OBJETIVO}.log"


def _log(mensaje: str) -> None:
    """Deja rastro de cada pasada, para revisar qué hizo mientras no mirabas."""
    CARPETA.mkdir(parents=True, exist_ok=True)
    sello = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(_ruta_log(), "a", encoding="utf-8") as f:
        f.write(f"{sello}  {mensaje}\n")


def _filas_totales() -> list[list]:
    ruta = _ruta_totales()
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        lector = csv.reader(f)
        next(lector, None)
        return [fila for fila in lector if len(fila) >= 3]


def _ultimo_conteo() -> dict | None:
    """Último recuento anotado, o None si es la primera vez."""
    filas = _filas_totales()
    if not filas:
        return None
    fecha, seguidores, seguidos = filas[-1][:3]
    try:
        return {"fecha": fecha, "seguidores": int(seguidores),
                "seguidos": int(seguidos)}
    except ValueError:
        return None


def _anotar_conteo(p: dict) -> None:
    """
    Anota el recuento del día. Si ya hay una fila de hoy, la reemplaza:
    ejecutar 'vigilar' dos veces no debe crear dos puntos para el mismo día.
    """
    CARPETA.mkdir(parents=True, exist_ok=True)
    hoy = f"{date.today():%Y-%m-%d}"
    filas = [f for f in _filas_totales() if f[0] != hoy]
    filas.append([hoy, p["seguidores"], p["seguidos"]])
    _escribir_csv(_ruta_totales(), ["fecha", "seguidores", "seguidos"], filas)


def _ultima_captura_util(tipo: str) -> tuple[Path | None, date | None]:
    """Captura más reciente que NO esté marcada como incompleta."""
    for ruta in reversed(_capturas(tipo)):
        if _leer_meta(ruta).get("completa") is False:
            continue
        try:
            return ruta, datetime.strptime(_fecha_de(ruta), "%Y-%m-%d").date()
        except ValueError:
            continue
    return None, None


def decidir(p: dict, umbral: int = UMBRAL_CAMBIO,
            max_dias: int = MAX_DIAS_SIN_BAJAR) -> tuple[set, list]:
    """
    Decide qué listas hay que bajar. Devuelve (listas, motivos).

    Tres disparadores:
      - los totales se movieron al menos `umbral`
      - han pasado `max_dias` desde la última captura utilizable
        (imprescindible: si se van 3 y entran 3, el total no cambia y
         el conteo por sí solo nunca lo detectaría)
      - no hay captura utilizable todavía
    """
    previo = _ultimo_conteo()
    hoy = date.today()
    bajar, motivos = set(), []

    for tipo in ("seguidores", "seguidos"):
        _, fecha = _ultima_captura_util(tipo)

        if fecha is None:
            bajar.add(tipo)
            motivos.append(f"{tipo}: no hay ninguna captura utilizable")
            continue

        dias = (hoy - fecha).days
        if dias >= max_dias:
            bajar.add(tipo)
            motivos.append(f"{tipo}: {dias} días desde la última captura")

        if previo:
            delta = p[tipo] - previo[tipo]
            if abs(delta) >= umbral:
                bajar.add(tipo)
                motivos.append(f"{tipo}: {delta:+d} desde el último conteo")

    return bajar, motivos


def cmd_vigilar_todas(args) -> None:
    """
    Recorre todas las cuentas seguidas repartiendo el presupuesto.

    NO va en paralelo, y es a propósito: el límite es de la sesión, así que
    lanzarlas a la vez solo haría llegar las mismas peticiones más juntas,
    que es exactamente lo que provoca los bloqueos. Se hace por turnos, y
    lo que no cabe hoy se queda para mañana con prioridad.
    """
    cuentas = leer_cuentas()
    if not cuentas:
        print("No sigues ninguna cuenta. Añádelas con 'cuentas --anadir X'.")
        return

    s = crear_sesion()
    print(f"\n{len(cuentas)} cuentas. Presupuesto disponible: "
          f"{queda_presupuesto()} peticiones.\n")

    candidatas, sin_cambios, fallidas = [], [], []

    # Primera vuelta: solo mirar. Una petición por cuenta.
    for nombre in cuentas:
        _revisar_cancelacion()
        with con_cuenta(nombre):
            print(f"  {nombre:<24}", end=" ", flush=True)
            try:
                p = perfil(s, nombre)
            except NoEncontrado as e:
                print(f"no accesible ({e})")
                fallidas.append(nombre)
                continue
            except (Bloqueado, SinPresupuesto) as e:
                print(f"cortado: {e}")
                fallidas.append(nombre)
                break                # si corta con una, cortará con todas

            bajar, motivos = decidir(p, args.umbral, args.max_dias)
            _anotar_conteo(p)

            if not bajar:
                print(f"{p['seguidores']}/{p['seguidos']}   sin cambios")
                sin_cambios.append(nombre)
                continue

            cuales = "ambas" if len(bajar) == 2 else list(bajar)[0]
            coste = (estimar_peticiones(p["seguidores"], p["seguidos"], cuales)
                     if p.get("totales_fiables", True) else 999)
            print(f"{p['seguidores']}/{p['seguidos']}   "
                  f"toca bajar {cuales} (~{coste})")
            candidatas.append({"nombre": nombre, "perfil": p, "bajar": bajar,
                               "cuales": cuales, "coste": coste,
                               "motivos": motivos})

    if not candidatas:
        print(f"\nNada que descargar. {len(sin_cambios)} sin cambios"
              + (f", {len(fallidas)} no accesibles." if fallidas else "."))
        _log(f"todas: {len(sin_cambios)} sin cambios, "
             f"{len(fallidas)} fallidas")
        return

    # Segunda vuelta: descargar mientras quepa. Primero las más baratas,
    # para que un objetivo enorme no se coma el turno de los demás.
    candidatas.sort(key=lambda c: c["coste"])
    print(f"\n{len(candidatas)} por descargar. "
          f"Quedan {queda_presupuesto()} peticiones.\n")

    hechas, aplazadas = [], []
    for c in candidatas:
        disponible = queda_presupuesto()
        if c["coste"] > disponible:
            print(f"  {c['nombre']:<24} aplazada: ~{c['coste']} y quedan "
                  f"{disponible}")
            aplazadas.append(c["nombre"])
            continue
        with con_cuenta(c["nombre"]):
            print(f"\n--- {c['nombre']} ---")
            try:
                for tipo in ("seguidores", "seguidos"):
                    if tipo in c["bajar"]:
                        descargar(s, c["perfil"], tipo)
                hechas.append(c["nombre"])
            except SinPresupuesto:
                print("  Se acabó el presupuesto a mitad. El progreso queda "
                      "guardado.")
                aplazadas.append(c["nombre"])
                break

    print("\n" + "=" * 62)
    print(f"Descargadas: {len(hechas)}   Sin cambios: {len(sin_cambios)}   "
          f"Aplazadas: {len(aplazadas)}")
    if aplazadas:
        print(f"  Para mañana: {', '.join(aplazadas)}")
    _log(f"todas: bajadas {hechas}, aplazadas {aplazadas}, "
         f"sin cambios {len(sin_cambios)}")


def cmd_vigilar(args) -> None:
    """Comprueba los totales con UNA petición y baja solo si hace falta."""
    if getattr(args, "todas", False):
        return cmd_vigilar_todas(args)
    s = crear_sesion()
    p = perfil(s, OBJETIVO)

    previo = _ultimo_conteo()
    def delta(tipo):
        return f"{p[tipo] - previo[tipo]:+d}" if previo else "primer conteo"

    print(f"\n@{p['username']}")
    print(f"  Seguidores: {p['seguidores']}   ({delta('seguidores')})")
    print(f"  Seguidos:   {p['seguidos']}   ({delta('seguidos')})")

    bajar, motivos = decidir(p, args.umbral, args.max_dias)
    _anotar_conteo(p)

    resumen = (f"seguidores={p['seguidores']} ({delta('seguidores')})  "
               f"seguidos={p['seguidos']} ({delta('seguidos')})")

    if not bajar:
        print("\n  Sin cambios. No se descarga nada (ha costado 1 petición).")
        _log(f"{resumen}  ->  sin cambios")
        return

    print("\n  Hay que descargar:")
    for m_ in motivos:
        print(f"    - {m_}")

    if args.solo_mirar:
        print("\n  (--solo-mirar: no se descarga)")
        _log(f"{resumen}  ->  haría falta bajar {sorted(bajar)} (solo-mirar)")
        return

    problema = avisar_si_privada(p)
    if problema and p.get("la_sigo") is False:
        print(f"\n  {problema}")
        _log(f"{resumen}  ->  ABORTADO: cuenta privada no seguida")
        return
    if problema:
        print(f"\n  Aviso: {problema}")

    cuales = "ambas" if len(bajar) == 2 else list(bajar)[0]
    cabe, explicacion = comprobar_coste(p, cuales)
    print(f"  {explicacion}")
    if not cabe:
        print("  No se descarga hoy. Mañana se retoma solo.")
        _log(f"{resumen}  ->  aplazado: no cabe en el presupuesto")
        return

    try:
        for tipo in ("seguidores", "seguidos"):
            if tipo in bajar:
                descargar(s, p, tipo)
    except KeyboardInterrupt:
        _log(f"{resumen}  ->  interrumpido a mitad")
        raise

    print("\n" + "=" * 62)
    print("QUÉ CAMBIÓ")
    seguidores = comparar("seguidores") if "seguidores" in bajar else None
    seguidos = comparar("seguidos") if "seguidos" in bajar else None
    if seguidores and seguidos:
        relaciones(seguidores, seguidos)

    _log(f"{resumen}  ->  bajado {sorted(bajar)}")


# ======================================================================
# PERFIL DETALLADO (lista de vigilancia)
# ======================================================================

def _ruta_vigilancia() -> Path:
    return CARPETA / f"vigilancia_{OBJETIVO}.txt"


def _ruta_detalles(dia: str | None = None) -> Path:
    dia = dia or f"{date.today():%Y-%m-%d}"
    return CARPETA / f"detalles_{OBJETIVO}_{dia}.csv"


def leer_lista_vigilancia() -> tuple[list, list]:
    """
    Lee la lista de cuentas a vigilar. Devuelve (cuentas, avisos).

    Formato: una por línea, admite URLs y @. Las líneas que empiezan por #
    se ignoran. Se recorta al tope: cada cuenta es una petición.
    """
    ruta = _ruta_vigilancia()
    if not ruta.exists():
        return [], [f"No existe {ruta.name}."]

    cuentas, vistas, avisos = [], set(), []
    for cruda in ruta.read_text(encoding="utf-8").splitlines():
        linea = cruda.split("#")[0].strip()
        if not linea:
            continue
        # Misma limpieza que usa la interfaz: acepta URL, @ y nombre suelto,
        # y descarta enlaces a publicaciones o secciones.
        nombre = limpiar_usuario(linea)
        if not nombre or not PATRON_USUARIO.match(nombre):
            avisos.append(f"se ignora una línea que no es un usuario: {cruda[:40]!r}")
            continue
        if nombre.lower() in vistas:
            continue
        vistas.add(nombre.lower())
        cuentas.append(nombre)

    if len(cuentas) > MAX_VIGILANCIA:
        avisos.append(f"la lista tiene {len(cuentas)} cuentas; se usan las "
                      f"primeras {MAX_VIGILANCIA}. Cada una es una petición.")
        cuentas = cuentas[:MAX_VIGILANCIA]
    return cuentas, avisos


def crear_lista_vigilancia() -> Path:
    """
    Escribe una plantilla con candidatos sacados de lo que ya hay en disco:
    los que entran y salen repetidamente, y los que se fueron hace poco.
    Sin peticiones: todo sale de las capturas.
    """
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = _ruta_vigilancia()
    if ruta.exists():
        return ruta

    candidatos, notas = [], []
    for tipo in ("seguidores", "seguidos"):
        h = construir_historial(tipo)
        if not h:
            continue
        personas = h["personas"].values()
        repetidores = sorted((p for p in personas if p["entradas"] >= 2),
                             key=lambda x: -x["entradas"])
        idos = sorted((p for p in personas if not p["presente"]),
                      key=lambda x: x["ultima"], reverse=True)
        for p in repetidores[:10]:
            candidatos.append((p["username"],
                               f"entra y sale ({p['entradas']} veces, {tipo})"))
        for p in idos[:10]:
            candidatos.append((p["username"],
                               f"se fue el {p['ultima']} ({tipo})"))

    vistos, lineas = set(), []
    for usuario, motivo in candidatos:
        if usuario.lower() in vistos:
            continue
        vistos.add(usuario.lower())
        lineas.append(f"{usuario}    # {motivo}")
        if len(lineas) >= MAX_VIGILANCIA:
            break

    if not lineas:
        notas.append("# Todavía no hay capturas de las que sacar candidatos.")
        notas.append("# Escribe abajo las cuentas que quieras seguir de cerca.")

    ruta.write_text("\n".join([
        "# Cuentas a vigilar de cerca.",
        "# Una por línea. Vale el nombre de usuario, con @ o la URL del perfil.",
        "# Lo que va detrás de # es un comentario.",
        "#",
        f"# CADA CUENTA CUESTA UNA PETICIÓN. Tope: {MAX_VIGILANCIA}.",
        "# Bórralas o coméntalas para no gastarlas.",
        "",
        *notas,
        *lineas,
        "",
    ]), encoding="utf-8")
    return ruta


def perfil_detallado(s: requests.Session, username: str) -> dict:
    """Todos los datos públicos del perfil. Una petición."""
    destino = ruta("perfil")
    d = pedir(s, destino, {param("usuario"): username},
              referer=BASE + ruta("pagina_perfil", usuario=username))
    if _buscar(d, campo("perfil_raiz")) in (AUSENTE, None):
        raise NoEncontrado(f"'{username}' no existe o no es visible")
    validar("perfil", d, destino)
    u = _buscar(d, campo("perfil_raiz"))
    fila = {nombre: _valor(u, ruta) for nombre, ruta in CAMPOS_DETALLE}
    fila["biografia"] = " ".join(fila["biografia"].split())   # sin saltos
    fila["consultado"] = f"{date.today():%Y-%m-%d}"
    return fila


def cmd_detalles(args) -> None:
    """
    Consulta el perfil completo de las cuentas de la lista de vigilancia.

    Una petición por cuenta, con pausas largas, tope duro y parada al primer
    bloqueo. No reintenta: si Instagram corta, es que hay que dejarlo.
    """
    CARPETA.mkdir(parents=True, exist_ok=True)

    if args.crear:
        ruta = crear_lista_vigilancia()
        cuentas, _ = leer_lista_vigilancia()
        print(f"Lista en {ruta.name}"
              + (f" con {len(cuentas)} candidatos sacados de tus capturas."
                 if cuentas else " (vacía: añade cuentas a mano)."))
        print("Ábrela, deja solo las que te interesen y vuelve a ejecutar.")
        return

    cuentas, avisos = leer_lista_vigilancia()
    for a in avisos:
        print(f"  Aviso: {a}")
    if not cuentas:
        print("No hay cuentas que consultar.")
        print("Ejecuta 'detalles --crear' para generar la lista.")
        return

    destino = _ruta_detalles()
    ya = {f["username"].lower() for f in _leer_csv(destino)
          if f.get("username")}
    pendientes = [c for c in cuentas if c.lower() not in ya]

    prudencia = factor_prudencia()
    minima = PAUSA_DETALLE_MIN * prudencia
    maxima = PAUSA_DETALLE_MAX * prudencia

    print(f"Lista de vigilancia: {len(cuentas)} cuentas.")
    if ya:
        print(f"  {len(ya)} ya consultadas hoy, se saltan.")
    print(f"  Van a costar {len(pendientes)} peticiones, "
          f"a una cada {minima:.0f}-{maxima:.0f} s.")
    if prudencia > 1:
        print(f"  Ritmo reducido x{prudencia:.0f}: hoy ya hubo bloqueos.")

    disponible = queda_presupuesto()
    print(f"  Quedan {disponible} peticiones hoy.")
    if len(pendientes) > disponible:
        print(f"  No caben las {len(pendientes)}. Se consultarán las "
              f"{disponible} primeras; el resto, mañana.")
        pendientes = pendientes[:disponible]
        if not pendientes:
            print("  Hoy no queda presupuesto. Vuelve mañana.")
            return

    if args.solo_listar:
        for c in pendientes:
            print(f"    {c}")
        print("  (--solo-listar: no se consulta nada)")
        return

    if not pendientes:
        print("  Nada que hacer: ya están todas.")
        return

    s = crear_sesion()
    filas = _leer_csv(destino)
    hechas, fallidas = 0, []

    try:
        for i, cuenta in enumerate(pendientes, 1):
            _revisar_cancelacion()
            print(f"  [{i}/{len(pendientes)}] {cuenta}", end="  ", flush=True)
            try:
                fila = perfil_detallado(s, cuenta)
            except NoEncontrado:
                print("no existe o no es visible")
                fallidas.append(cuenta)
                continue
            filas.append(fila)
            hechas += 1
            print(f"{fila['seguidores']} seguidores, "
                  f"{fila['publicaciones']} publicaciones")
            _escribir_csv(destino, CABECERA_DETALLE,
                          [_fila(f, CABECERA_DETALLE) for f in filas])
            if i < len(pendientes):
                _dormir(random.uniform(minima, maxima))
    except Bloqueado as e:
        print(f"\n  Cortado: {e}")
        print(f"  Se guardaron {hechas}. Vuelve a ejecutar más tarde: "
              "las ya consultadas hoy se saltan.")
        return
    except KeyboardInterrupt:
        print(f"\n  Parado. Se guardaron {hechas}.")
        raise

    print(f"\n  {hechas} perfiles en {destino.name}")
    if fallidas:
        print(f"  No se pudieron consultar: {', '.join(fallidas)}")


# ======================================================================
# COMANDOS
# ======================================================================

def cmd_sesion(_) -> None:
    crear_sesion(forzar=True)
    print("Listo. Ya puedes ejecutar 'contar' o 'bajar'.")


def cmd_contar(_) -> None:
    s = crear_sesion()
    p = perfil(s, OBJETIVO)
    previo = _ultimo_conteo()

    print(f"\n@{p['username']}  {p['nombre']}")
    for tipo in ("seguidores", "seguidos"):
        cambio = f"   ({p[tipo] - previo[tipo]:+d})" if previo else ""
        print(f"  {tipo.capitalize():12} {p[tipo]}{cambio}")
    if p["privada"]:
        print("  Cuenta privada" + ("" if p["la_sigo"] else " y NO la sigues"))

    _anotar_conteo(p)
    print(f"\n  Anotado en {_ruta_totales().name}")


def _aplanar(u: dict, prefijo: str = "") -> dict:
    """Aplana un nivel de anidamiento: friendship_status.following, etc."""
    plano = {}
    for k, v in u.items():
        clave = f"{prefijo}{k}"
        if isinstance(v, dict) and v and all(not isinstance(x, (dict, list))
                                             for x in v.values()):
            plano.update(_aplanar(v, clave + "."))
        else:
            plano[clave] = v
    return plano


def _tipo_legible(v) -> str:
    if isinstance(v, bool):
        return "sí/no"
    if isinstance(v, (int, float)):
        return "número"
    if isinstance(v, str):
        return "texto"
    if isinstance(v, list):
        return "lista"
    if isinstance(v, dict):
        return "objeto"
    return "vacío"


def _ejemplo(v) -> str:
    if isinstance(v, bool):
        return "si" if v else "no"
    texto = "" if v is None else str(v)
    return texto[:40] + "..." if len(texto) > 40 else texto


def cmd_inspeccionar(args) -> None:
    """
    Gasta UNA petición, guarda la respuesta cruda y lista los campos reales.

    Existe porque los campos que manda Instagram no están documentados y
    cambian. En vez de suponer cuáles hay, se miran.
    """
    s = crear_sesion()
    p = perfil(s, OBJETIVO)
    endpoint = "followers" if args.lista == "seguidores" else "following"

    d = pedir(s, f"/api/v1/friendships/{p['id']}/{endpoint}/",
              {"count": POR_PAGINA})

    CARPETA.mkdir(parents=True, exist_ok=True)
    crudo = CARPETA / f"crudo_{OBJETIVO}_{args.lista}.json"
    crudo.write_text(json.dumps(d, indent=2, ensure_ascii=False),
                     encoding="utf-8")

    usuarios = d.get("users") or []
    print(f"\nRespuesta cruda guardada en {crudo.name}")
    print(f"Muestra: {len(usuarios)} usuarios de {args.lista} de @{OBJETIVO}")

    otras = [k for k in d if k != "users"]
    if otras:
        print("\nCampos de la respuesta (fuera de 'users'):")
        for k in otras:
            print(f"  {k} = {_ejemplo(d[k])}")

    if not usuarios:
        print("\nLa respuesta no traía usuarios; no hay campos que analizar.")
        return

    planos = [_aplanar(u) for u in usuarios]
    claves = sorted({k for u in planos for k in u})
    guardados = {"username", "full_name", "pk", "id"}
    guardados |= {ruta for _, ruta in CAMPOS_EXTRA}

    print(f"\n{'CAMPO':38} {'PRESENTE':>9}  {'TIPO':8} EJEMPLO")
    print("-" * 78)
    nuevos = []
    for k in claves:
        con = [u[k] for u in planos if k in u and u[k] is not None]
        if not con:
            continue
        marca = "*" if k in guardados else " "
        print(f"{marca}{k:37} {len(con):>4}/{len(planos):<4} "
              f"{_tipo_legible(con[0]):8} {_ejemplo(con[0])}")
        if k not in guardados and isinstance(con[0], (bool, int, str)):
            nuevos.append(k)

    print("-" * 78)
    print("*  = el módulo ya lo guarda en las capturas")

    faltan = [ruta for _, ruta in CAMPOS_EXTRA
              if not any(ruta in u for u in planos)]
    if faltan:
        print(f"\nCampos que el módulo espera y NO llegaron: {', '.join(faltan)}")
        print("Sus columnas saldrán vacías. Quítalos de CAMPOS_EXTRA si molesta.")

    if nuevos:
        print(f"\nCampos disponibles que NO se están guardando ({len(nuevos)}):")
        print("  " + ", ".join(nuevos[:20]))
        print("\nPara guardar alguno, añádelo a CAMPOS_EXTRA arriba del archivo:")
        print(f'    ("mi_columna", "{nuevos[0]}"),')
        print("Se guardará desde la siguiente descarga, sin peticiones extra.")


def cmd_contratos(args) -> None:
    """Qué se espera de cada respuesta y por qué rutas. Sin peticiones."""
    if getattr(args, "crear", False):
        destino = escribir_config_ejemplo()
        print(f"\nConfiguración en {destino}")
        print("Edita solo lo que haga falta y reinicia el programa.")
        print("Lo que borres vuelve a su valor de serie.")
        return

    c = config()
    archivo = _ruta_config()
    print(f"\nRUTAS  {'(de ' + archivo.name + ')' if archivo.exists() else '(de serie)'}")
    for clave, valor in c["rutas"].items():
        marca = " *" if valor != RUTAS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    print("\nNOMBRES DE PARÁMETROS")
    for clave, valor in c["params"].items():
        marca = " *" if valor != PARAMS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    print("\nNOMBRES DE CAMPOS EN LA RESPUESTA")
    for clave, valor in c["campos"].items():
        marca = " *" if valor != CAMPOS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    if not archivo.exists():
        print("\n  Para poder cambiarlos:  contratos --crear")
        print(f"  Escribe {archivo.name} y ahí se edita sin tocar código.")
    else:
        print("\n  * = cambiado respecto al valor de serie")

    print("\nLo que este programa necesita de cada respuesta de Instagram.")
    print("Si algo cambia de forma, aquí se ve qué se estaba esperando.\n")
    for clave, c in CONTRATOS.items():
        print(f"  {clave}  ({c.nombre})")
        for ruta, tipos in c.campos:
            print(f"      {ruta:34} {Contrato._nombres(tipos)}")
        if c.coleccion:
            print(f"      {c.coleccion:34} lista")
            for ruta, tipos in c.campos_elemento:
                print(f"        · {ruta:32} {Contrato._nombres(tipos)}")
            for rutas, tipos in c.alternativas_elemento:
                print(f"        · {' o '.join(rutas):32} "
                      f"{Contrato._nombres(tipos)}")
        print()
    print("  Los campos que Instagram añada NO rompen nada: solo se exige")
    print("  que esté lo de arriba.")


def cmd_diagnostico(args) -> None:
    """
    Prueba cada endpoint por separado y dice cuál responde.

    Existe porque suponer qué falla sale caro: se descubrió que
    web_profile_info devuelve 429 a la PRIMERA petición mientras friendships
    contesta 200. Sin medirlo, eso parecía "me han limitado la cuenta".
    """
    s = crear_sesion()
    mi_id = s.cookies.get("ds_user_id") or "0"
    objetivo = OBJETIVO

    # Cada prueba comprueba también la FORMA, no solo que conteste: un 200
    # con la estructura cambiada es peor que un error, porque pasa por bueno.
    pruebas = [
        ("Tu propia lista de seguidos (lo que usa la descarga)",
         lambda: validar("lista", pedir(
             s, ruta("lista_seguidos", id=mi_id),
             {param("cantidad"): 1}))),
        ("Tus datos de cuenta",
         lambda: pedir(s, ruta("sesion_actual"))),
        ("Perfil por API (web_profile_info)",
         lambda: validar("perfil", pedir(
             s, ruta("perfil"), {param("usuario"): objetivo},
             referer=BASE + ruta("pagina_perfil", usuario=objetivo)))),
        ("Perfil por su página web",
         lambda: perfil_desde_html(s, objetivo)),
        ("Buscador",
         lambda: perfil_desde_busqueda(s, objetivo)),
    ]

    print(f"\nProbando {len(pruebas)} vías, una cada 5 s. Cuenta: @{objetivo}")
    print("-" * 62)
    funcionan, cambiadas = [], []

    for i, (nombre, probar) in enumerate(pruebas):
        _revisar_cancelacion()
        print(f"  {nombre:52}", end=" ", flush=True)
        try:
            probar()
            print("OK")
            funcionan.append(nombre)
        except NoEncontrado as e:
            print(f"no encontrado ({e})")
        except RespuestaInesperada as e:
            # Es el caso que más importa detectar: contesta, pero ya no
            # sirve. Se enseña el detalle para poder ajustar el contrato.
            print("CAMBIÓ DE FORMA")
            print(f"      {e}")
            cambiadas.append(nombre)
        except Bloqueado as e:
            texto = str(e)
            print("BLOQUEADO" if "429" in texto else f"falla ({texto[:40]})")
        except Exception as e:                       # noqa: BLE001
            print(f"error ({type(e).__name__})")
        if i < len(pruebas) - 1:
            _dormir(5)

    print("-" * 62)
    if not funcionan:
        print("No responde nada. La sesión puede haber caducado: vuelve a")
        print("importarla desde el navegador.")
        return

    print(f"Funcionan {len(funcionan)} de {len(pruebas)}:")
    for f in funcionan:
        print(f"  - {f}")
    if cambiadas:
        print(f"\nCambiaron de forma ({len(cambiadas)}): "
              f"{', '.join(cambiadas)}")
        print("  Contestan, pero ya no traen lo que hace falta. Eso no se")
        print("  arregla esperando: hay que ajustar el contrato en CONTRATOS.")

    descarga = any("descarga" in f for f in funcionan)
    perfil_ok = any("Perfil" in f for f in funcionan)
    print()
    if descarga and perfil_ok:
        print("Todo lo necesario responde. Puedes descargar las listas.")
    elif descarga:
        print("El endpoint de listas responde, pero no se puede leer el")
        print("perfil por ninguna vía. Sin el identificador de la cuenta no")
        print("se puede empezar. Prueba dentro de un rato.")
    else:
        print("El endpoint de listas NO responde. Con eso bloqueado no hay")
        print("descarga posible: espera unas horas antes de reintentar.")


def comprobar_coste(p: dict, cuales: str) -> tuple[bool, str]:
    """
    ¿Cabe esta descarga en lo que queda hoy? Devuelve (cabe, explicación).

    Lo usan 'bajar' y 'vigilar'. Antes solo lo hacía 'bajar', y 'vigilar' es
    precisamente el que se ejecuta solo, sin nadie mirando.
    """
    disponible = queda_presupuesto()
    if not p.get("totales_fiables", True):
        return True, (f"No se pudieron leer los totales ({p.get('origen')}), "
                      "así que no se puede estimar el coste ni detectar si la "
                      f"descarga sale truncada. Quedan {disponible} peticiones.")

    coste = estimar_peticiones(p["seguidores"], p["seguidos"], cuales)
    if coste > disponible:
        return False, (f"Harían falta ~{coste} peticiones y quedan "
                       f"{disponible}. Baja una lista sola con --lista, o "
                       f"sube TOPE_DIARIO si de verdad hace falta.")
    aviso = f"Coste estimado: ~{coste} peticiones. Te quedan {disponible} hoy."
    if coste > disponible * 0.5:
        aviso += "  Se va a comer más de la mitad de lo que queda."
    return True, aviso


def avisar_si_privada(p: dict) -> str | None:
    """Mensaje si la cuenta puede no ser accesible. None si todo bien."""
    if not p.get("privada"):
        return None
    if p.get("la_sigo") is False:
        return ("La cuenta es privada y esta sesión NO la sigue. Síguela y "
                "espera a que te acepte.")
    if p.get("la_sigo") is None:
        return ("La cuenta es privada y no consta si la sigues (los datos "
                "vinieron de la página, que no lo dice). Si no la sigues, la "
                "descarga saldrá vacía.")
    return None


def cmd_presupuesto(args) -> None:
    """Cuántas peticiones se han gastado hoy y en qué."""
    p = _presupuesto()
    hechas = p.get("hechas", 0)
    print(f"\nDía {p.get('dia')}")
    print(f"  Peticiones: {hechas} de {TOPE_DIARIO}  "
          f"(quedan {queda_presupuesto()})")
    if p.get("primera"):
        print(f"  Entre las {p['primera']} y las {p['ultima']}")
    if p.get("bloqueos"):
        print(f"  Bloqueos recibidos: {p['bloqueos']}   "
              f"-> las pausas van x{factor_prudencia():.0f}")

    if p.get("por_endpoint"):
        print("\n  Reparto:")
        for clave, n in sorted(p["por_endpoint"].items(),
                               key=lambda x: -x[1]):
            print(f"    {n:>5}  {clave}")

    aprendido = p.get("aprendido", {})
    if aprendido:
        print("\n  Vías que funcionan (no se vuelven a probar las otras):")
        for asunto, valor in aprendido.items():
            print(f"    {asunto}: {valor}")

    if hechas >= TOPE_DIARIO * AVISO_AL:
        print("\n  Vas justo. Deja las descargas grandes para mañana.")


def cmd_bajar(args) -> None:
    s = crear_sesion()
    p = perfil(s, OBJETIVO)

    print(f"\n@{p['username']} — {p['seguidores']} seguidores, "
          f"{p['seguidos']} seguidos")

    cabe, explicacion = comprobar_coste(p, args.lista)
    print(f"  {explicacion}")
    if not cabe:
        sys.exit(f"No cabe en el presupuesto de hoy ({TOPE_DIARIO}).")

    problema = avisar_si_privada(p)
    if problema:
        if p.get("la_sigo") is False:
            sys.exit(problema)
        print(f"  Aviso: {problema}")

    tipos = [args.lista] if args.lista != "ambas" else ["seguidores", "seguidos"]
    try:
        for tipo in tipos:
            descargar(s, p, tipo)
    except KeyboardInterrupt:
        sys.exit("\nCortado por ti. Vuelve a ejecutar 'bajar' para continuar.")
    print("\nHecho.")


def cmd_comparar(args) -> None:
    if not CARPETA.exists():
        sys.exit(f"No existe '{CARPETA.name}'. Ejecuta 'bajar' primero.")
    if args.totales or args.historico:
        tendencia_totales()
        return
    seguidores = comparar("seguidores", args.forzar)
    seguidos = comparar("seguidos", args.forzar)
    relaciones(seguidores, seguidos)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Seguidores y seguidos de Instagram: descarga y comparación.")
    ap.add_argument("--cuenta", help="cuenta objetivo, solo para esta "
                                     "ejecución (por defecto, OBJETIVO)")
    sub = ap.add_subparsers(dest="comando", required=True)

    p_cta = sub.add_parser("cuentas",
                           help="ver, añadir o quitar cuentas seguidas")
    p_cta.add_argument("--anadir", nargs="+", metavar="CUENTA")
    p_cta.add_argument("--quitar", nargs="+", metavar="CUENTA")
    p_cta.set_defaults(func=cmd_cuentas)

    sub.add_parser("sesion", help="importa las cookies del navegador"
                   ).set_defaults(func=cmd_sesion)

    sub.add_parser("contar", help="solo los totales (1 petición)"
                   ).set_defaults(func=cmd_contar)

    p_bajar = sub.add_parser("bajar", help="descarga las listas completas")
    p_bajar.add_argument("--lista", choices=["ambas", "seguidores", "seguidos"],
                         default="ambas")
    p_bajar.set_defaults(func=cmd_bajar)

    p_ins = sub.add_parser("inspeccionar",
                           help="1 petición: muestra qué campos manda Instagram")
    p_ins.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores")
    p_ins.set_defaults(func=cmd_inspeccionar)

    p_vig = sub.add_parser("vigilar",
                           help="comprueba con 1 petición y baja solo si hace falta")
    p_vig.add_argument("--umbral", type=int, default=UMBRAL_CAMBIO,
                       help=f"cambio en los totales que dispara la descarga "
                            f"(por defecto {UMBRAL_CAMBIO})")
    p_vig.add_argument("--max-dias", type=int, default=MAX_DIAS_SIN_BAJAR,
                       dest="max_dias",
                       help=f"forzar descarga completa cada N días aunque los "
                            f"totales no cambien (por defecto "
                            f"{MAX_DIAS_SIN_BAJAR})")
    p_vig.add_argument("--solo-mirar", action="store_true", dest="solo_mirar",
                       help="informar de si haría falta bajar, sin bajar")
    p_vig.add_argument("--todas", action="store_true",
                       help="recorrer TODAS las cuentas seguidas, por turnos "
                            "y repartiendo el presupuesto (no en paralelo)")
    p_vig.set_defaults(func=cmd_vigilar)

    p_hist = sub.add_parser("historial",
                            help="trayectoria de cada persona a lo largo de "
                                 "todas las capturas")
    p_hist.add_argument("--lista", choices=["ambas", "seguidores", "seguidos"],
                        default="ambas")
    p_hist.add_argument("--min-entradas", type=int, default=2,
                        dest="min_entradas",
                        help="a partir de cuántas entradas se considera "
                             "'ida y vuelta' (mínimo y por defecto 2)")
    p_hist.add_argument("--incluir-sospechosas", action="store_true",
                        dest="incluir_sospechosas",
                        help="usar también las capturas cuyo tamaño se "
                             "desploma (solo si la bajada fue real)")
    p_hist.set_defaults(func=cmd_historial)

    sub.add_parser("presupuesto",
                   help="cuántas peticiones llevas hoy y en qué"
                   ).set_defaults(func=cmd_presupuesto)

    p_con = sub.add_parser("contratos",
                           help="rutas, parámetros y forma esperada "
                                "(0 peticiones)")
    p_con.add_argument("--crear", action="store_true",
                       help="escribir salida/rutas.json para poder editarlo")
    p_con.set_defaults(func=cmd_contratos)

    sub.add_parser("diagnostico",
                   help="prueba cada endpoint y dice cuál responde"
                   ).set_defaults(func=cmd_diagnostico)

    p_det = sub.add_parser("detalles",
                           help="perfil completo de la lista de vigilancia "
                                "(1 petición POR CUENTA)")
    p_det.add_argument("--crear", action="store_true",
                       help="generar la lista con candidatos de tus capturas")
    p_det.add_argument("--solo-listar", action="store_true",
                       dest="solo_listar",
                       help="ver a quién se consultaría, sin consultar")
    p_det.set_defaults(func=cmd_detalles)

    p_cmp = sub.add_parser("comparar", help="qué cambió entre dos capturas")
    p_cmp.add_argument("--totales", action="store_true",
                       help="solo la evolución del NÚMERO de seguidores "
                            "(para la trayectoria de cada persona, usa el "
                            "comando 'historial')")
    p_cmp.add_argument("--historico", action="store_true",
                       help=argparse.SUPPRESS)   # alias antiguo
    p_cmp.add_argument("--forzar", action="store_true",
                       help="comparar aunque haya capturas incompletas")
    p_cmp.set_defaults(func=cmd_comparar)

    args = ap.parse_args()

    global OBJETIVO
    if getattr(args, "cuenta", None):
        limpio = limpiar_usuario(args.cuenta)
        if not limpio or not PATRON_USUARIO.match(limpio):
            sys.exit(f"'{args.cuenta}' no parece un nombre de usuario.")
        OBJETIVO = limpio

    try:
        args.func(args)
    except RespuestaInesperada as e:
        sys.exit(f"\nRespuesta con otra forma: {e}\n"
                 "Esto es un cambio de Instagram, no un fallo tuyo. "
                 "Ejecuta 'diagnostico' para ver qué sigue funcionando.")
    except PeticionRechazada as e:
        sys.exit(f"\nPetición rechazada: {e}\n"
                 "Esto no se arregla esperando. Si se repite, ejecuta "
                 "'diagnostico'.")
    except SinPresupuesto as e:
        sys.exit(f"\nSin presupuesto: {e}")
    except SesionInvalida as e:
        sys.exit(f"\nSesión no válida: {e}")
    except NoEncontrado as e:
        sys.exit(f"\nNo encontrado: {e}\n"
                 f"Revisa que OBJETIVO ('{OBJETIVO}') esté bien escrito.")
    except KeyboardInterrupt:
        sys.exit("\nCortado.")


if __name__ == "__main__":
    main()
