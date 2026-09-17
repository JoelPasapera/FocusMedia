#!/usr/bin/env python3
"""
instagram_listas.py  ·  v2
==========================

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

import contextlib
import csv
import hashlib
import io
import json
import os
import random
import re
import statistics
import sys
from html import unescape

import indice_eventos
# Re-exportadas: la ventana y los comandos las usan como
# `m.firma()` y `m.VERSION`, aunque aquí dentro no se llamen.
from version import FECHA, VERSION, firma  # noqa: F401
import export_instagram
import time
from datetime import date, datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Falta requests.  Ejecuta:  pip install requests")

# Se usa para limpiar secretos de TODO lo que se escribe en los volcados
# de error: el limpiador vive ahí y no se duplica aquí.
import registro                                          # noqa: E402


# ======================================================================
# CONFIGURACIÓN
# ======================================================================

OBJETIVO = "cuenta_objetivo"     # cuenta cuyas listas quieres bajar

# firefox / chrome / chromium / edge / brave / opera / opera_gx / vivaldi /
# librewolf / safari / arc
NAVEGADOR = "firefox"

CARPETA = Path(__file__).parent / "salida"

# Las sesiones, en su propia carpeta. Antes andaban sueltas en la raíz del
# proyecto, junto al código: una cookie de sesión equivale a estar dentro de
# la cuenta, y ahí es demasiado fácil que se cuele en un commit o en un zip.
# La carpeta entera está en .gitignore, no cada archivo por su nombre.
CARPETA_SESIONES = Path(__file__).parent / "sesiones"
ARCHIVO_SESION = CARPETA_SESIONES / "activa.json"

# Todos los que browser_cookie3 sabe leer. En Windows, Chrome y los que
# derivan de él cifran sus cookies y casi nunca se dejan; Firefox sí.
NAVEGADORES = ("firefox", "librewolf", "chrome", "chromium", "edge", "brave",
               "opera", "opera_gx", "vivaldi", "safari", "arc")

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
]

# Estas dos NO vienen de Instagram: se CALCULAN cruzando las dos listas de la
# propia cuenta. Antes salían de 'friendship_status', y eso era un error de
# concepto además de un campo que ya no llega: friendship_status describe la
# relación con la cuenta de la SESIÓN, no con la cuenta que se vigila. Al
# mirar los seguidos de otra persona contestaban a otra pregunta.
#
# El cruce sí contesta a la buena, y sale gratis: quien está en 'seguidores'
# sigue a la cuenta, y quien está en 'seguidos' es seguido por ella.
CAMPOS_CRUZADOS = ["sigue_a_la_cuenta", "la_cuenta_le_sigue"]

# Los tres estados posibles de una persona respecto a la cuenta, y qué
# significan en español.
#
# El informe de relaciones los llamaba «no_devuelve» y «no_correspondido»,
# que en español son casi sinónimos: nadie podía saber cuál era cuál sin
# leer el código. Y el proyecto ya tenía estos otros nombres para lo mismo
# en `estado_relacion_en()`. Dos vocabularios para tres estados es cómo se
# acaba comparando manzanas con peras.
#
# La explicación vive AQUÍ y la leen la tabla y el informe: una leyenda
# copiada en dos sitios se separa en el primer matiz que se corrija.
def leyenda_relacion(cuenta: str = "") -> dict:
    """
    Qué significa cada relación, dicho con el nombre de la cuenta dentro.

    «La cuenta» obligaba a traducir mentalmente en cada línea. Con
    @nombre_real puesto, cada frase se lee como lo que es: una afirmación
    sobre la persona de esa fila.

    Las tres frases tienen la MISMA forma —sujeto, sigue, pero— para que
    se puedan comparar de un vistazo en vez de leerlas una a una.

    Y esto es lo único que decide cómo se llaman estas tres cosas: lo leen
    la tabla, el informe y la consola. Antes había tres textos distintos
    para los mismos tres estados, y el de la consola ni siquiera coincidía
    con el de la tabla.
    """
    quien = f"@{cuenta}" if cuenta else "la cuenta"
    return {
        "mutuo": f"se siguen los dos",
        "solo_sigue_a_la_cuenta":
            f"sigue a {quien}, pero {quien} no le sigue",
        "solo_la_cuenta_le_sigue":
            f"{quien} le sigue, pero no sigue a {quien}",
    }


LEYENDA_RELACION = leyenda_relacion()
# Cómo se leen las columnas fuera del CSV. Lo que no esté aquí sale con los
# guiones bajos cambiados por espacios, así que una columna nueva se lee
# bien sin tocar esta lista.
TOPE_FILAS_INFORME = 5000       # como el visor de tablas

ETIQUETAS_INFORME = {
    "username": "usuario",
    "sigue_a_la_cuenta": "sigue a la cuenta",
    "la_cuenta_le_sigue": "la cuenta le sigue",
    "foto_defecto": "foto por defecto",
    "biografia": "biografía",
    "categoria": "categoría",
    "le_sigue": "le sigue (a tu sesión)",
    "la_sigue": "la sigue (tu sesión)",
}

CABECERA = (["username", "nombre", "id"]
            + [n for n, _ in CAMPOS_EXTRA] + CAMPOS_CRUZADOS)

CABECERA_TOTALES = ["fecha", "seguidores", "seguidos", "publicaciones"]

# Cada cuántos días se vuelve a bajar la foto de perfil de la cuenta que se
# vigila. No es una petición a la API (va al CDN), pero tampoco hay motivo
# para pedirla en cada conteo: una cara no cambia todas las semanas.
DIAS_FOTO = 7

# --- perfil detallado -------------------------------------------------
# Esto cuesta UNA PETICIÓN POR PERSONA, contra el mismo endpoint que ya
# provocó un 429. Por eso hay tope duro, pausas largas y parada al primer
# bloqueo, sin reintentos.
MAX_LISTADO = 40                 # nombres antes de remitir al CSV
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


def limpiar_nombre(texto) -> str:
    """
    El nombre visible de un perfil, sin lo que sobra a los lados.

    Instagram devuelve muchos con espacios al final, y algunos con
    caracteres invisibles: separadores de ancho cero y marcas de variación
    que van pegadas a los emojis. Sin quitarlos salía «Lore☺ , 1
    publicación», con el espacio delante de la coma a la vista.

    Solo se tocan los extremos: por dentro, el nombre es de quien lo puso.
    """
    limpio = str(texto or "")
    for invisible in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00a0"):
        limpio = limpio.strip(invisible)
    return limpio.strip()


def limpiar_usuario(texto: str) -> str:
    """
    Saca el nombre de usuario de lo que la gente pega de verdad.

    Acepta la URL del perfil (con o sin https, con o sin barra final, con
    parámetros), el nombre con @ delante, y espacios sobrantes. Devuelve
    cadena vacía si no hay un perfil ahí dentro.

        https://www.instagram.com/cuenta.ejemplo/  ->  cuenta.ejemplo
        @cuenta.ejemplo                             ->  cuenta.ejemplo
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

class ErrorPrevisto(Exception):
    """
    Lo que puede pasar y ya viene explicado: no es un fallo del programa.

    Se agrupan para que quien los recoja enseñe el mensaje en vez de una
    traza de Python con rutas de archivos, que fue lo que llegó a salir en
    la consola de la ventana ante una sesión rechazada.
    """


class Bloqueado(ErrorPrevisto):
    """Instagram ha cortado. Hay que esperar, no insistir."""


class SesionInvalida(ErrorPrevisto):
    """Las cookies no valen o caducaron. Hay que reiniciar sesión."""


class NoEncontrado(ErrorPrevisto):
    """El perfil o el recurso no existe. La sesión está bien."""


class PeticionRechazada(ErrorPrevisto):
    """
    Instagram dice que la petición está mal (HTTP 400 y similares).

    NO se reintenta: esperar no arregla una petición mal formada. Antes
    caía en el mismo saco que los bloqueos y el programa se pasaba hasta
    tres horas esperando algo que nunca iba a funcionar.
    """


# ======================================================================
# SESIÓN
# ======================================================================

def _guardar_cookies(cookies: dict, registrar: bool = True) -> None:
    """
    Deja la sesión activa en disco, y de paso la anota en el almacén.

    Es el único sitio por el que pasa una sesión al guardarse, venga del
    navegador o pegada a mano, así que es el sitio donde registrarla. El
    parámetro existe para que activar una ya guardada no se registre a sí
    misma otra vez.
    """
    CARPETA_SESIONES.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        # Solo su dueño. En Windows no hace nada, y no pasa nada.
        CARPETA_SESIONES.chmod(0o700)
    escribir_atomico(ARCHIVO_SESION, json.dumps(
        {"guardado": datetime.now().isoformat(timespec="seconds"),
         "cookies": cookies}, indent=2))
    if registrar:
        try:
            registrar_sesion(cookies)
        except Exception:
            pass                # el almacén es comodidad, no una pieza
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


def leer_cookies_pegadas(texto: str) -> dict:
    """
    Saca las cookies de lo que la gente pega de verdad.

    Acepta el valor suelto, `sessionid=...`, la cabecera Cookie entera con
    todo dentro, o un JSON. Es el mismo criterio que `limpiar_usuario()` con
    los enlaces de perfil (v2.8): quien pega no tiene por qué saber qué
    trozo hace falta, y que el campo lo rechace en silencio es un fallo de
    diseño, no del usuario.

    De todas, la única imprescindible es `sessionid`. El `ds_user_id` no hay
    ni que pedirlo: **va dentro del propio sessionid**, delante del `%3A`.
    """
    texto = (texto or "").strip()
    if not texto:
        return {}

    cookies = {}
    if texto.startswith("{"):
        try:
            datos = json.loads(texto)
            if isinstance(datos.get("cookies"), dict):
                datos = datos["cookies"]      # el propio sesion_*.json
            for nombre in COOKIES_UTILES:
                if datos.get(nombre):
                    cookies[nombre] = str(datos[nombre]).strip()
        except (ValueError, AttributeError):
            pass

    if not cookies:
        # 'Cookie: a=1; b=2', una por línea, o el valor a secas.
        for trozo in re.split(r"[;\n\r]+", texto):
            if "=" not in trozo:
                continue
            nombre, _, valor = trozo.partition("=")
            nombre = nombre.strip().lstrip("Cookie:").strip()
            valor = valor.strip().strip('"\'')
            if nombre in COOKIES_UTILES and valor:
                cookies[nombre] = valor

    if not cookies and "=" not in texto and len(texto.split()) == 1:
        suelto = texto.strip('"\'')
        # Una palabra suelta solo pasa por sesión si LO PARECE: con el
        # separador dentro, o al menos larga como un token. Sin esto,
        # escribir «hola» se guardaba como sesión y el error salía
        # después, lejos y sin relación con lo que se había hecho.
        if "%3A" in suelto or ":" in suelto or len(suelto) >= 20:
            cookies["sessionid"] = suelto

    sesion = cookies.get("sessionid", "")
    if not sesion:
        return {}

    # El id de la cuenta va delante del separador, que viaja escapado como
    # %3A porque la cookie está en una URL.
    if not cookies.get("ds_user_id"):
        cabeza = re.split(r"%3A|:", sesion, maxsplit=1)[0]
        if cabeza.isdigit():
            cookies["ds_user_id"] = cabeza
    return cookies


def guardar_sesion_pegada(texto: str, etiqueta: str = "") -> dict:
    """
    Guarda una sesión escrita a mano. Devuelve las cookies entendidas.

    Existe porque Chrome y Edge en Windows cifran las cookies y casi nunca
    se pueden leer: sin esto, quien use esos navegadores se queda sin vía.

    NO comprueba que funcione — eso cuesta una petición y lo hace
    `comprobar_sesion()`, que ya existe y prueba tres endpoints.
    """
    global _SESION_CACHE, _SESION_HASTA, _VERIFICACION_OK
    cookies = leer_cookies_pegadas(texto)
    if not cookies:
        return {}
    _guardar_cookies(cookies)
    if etiqueta:
        registrar_sesion(cookies, etiqueta)
    # La sesión se reutiliza 10 minutos sin verificar (v2.9). Si no se tira
    # la que hay, la cookie recién pegada no se usaría hasta dentro de un
    # rato y parecería que no ha servido de nada.
    _SESION_CACHE, _SESION_HASTA = None, 0.0
    _VERIFICACION_OK = None
    return cookies


def _ruta_sesiones() -> Path:
    return ARCHIVO_SESION.with_name("guardadas.json")


def leer_sesiones() -> dict:
    """Las sesiones guardadas: {"activa": id, "cuentas": {id: {...}}}."""
    try:
        d = json.loads(_ruta_sesiones().read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("cuentas"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"activa": "", "cuentas": {}}


def _guardar_sesiones(datos: dict) -> None:
    try:
        destino = _ruta_sesiones()
        escribir_atomico(destino, json.dumps(datos, indent=2))
        destino.chmod(0o600)         # en Windows no hace nada, y no pasa nada
    except OSError:
        pass


def _clave_de(cookies: dict) -> str:
    """Con qué se identifica una sesión: el id de su cuenta."""
    return str(cookies.get("ds_user_id") or "")[:32] or "sin-id"


def registrar_sesion(cookies: dict, etiqueta: str = "") -> str:
    """
    Mete una sesión en el almacén y la deja activa. Devuelve su clave.

    Si esa cuenta ya estaba, se le actualizan las cookies en vez de
    duplicarla: el caso corriente es que la sesión caducó y se pega otra.
    """
    if not cookies.get("sessionid"):
        return ""
    datos = leer_sesiones()
    clave = _clave_de(cookies)
    antes = datos["cuentas"].get(clave) or {}
    datos["cuentas"][clave] = {
        "etiqueta": etiqueta or antes.get("etiqueta", ""),
        "guardado": datetime.now().isoformat(timespec="seconds"),
        "cookies": cookies,
    }
    datos["activa"] = clave
    _guardar_sesiones(datos)
    return clave


def anotar_usuario_de_sesion(clave: str, usuario: str = "") -> None:
    """
    Anota que una sesión se comprobó, y de quién es si se supo.

    La fecha se sella SIEMPRE, aunque el nombre no cambie: si no, volver a
    comprobar una sesión dejaba puesta la fecha de la vez anterior, y eso
    es una fecha que miente. Escribir este archivo es barato; una fecha
    falsa sale cara el día que uno intenta entender qué pasó.
    """
    datos = leer_sesiones()
    ficha = datos["cuentas"].get(clave)
    if not ficha:
        return
    if usuario:
        ficha["usuario"] = usuario
    ficha["comprobada"] = datetime.now().isoformat(timespec="minutes")
    _guardar_sesiones(datos)


def sesiones_disponibles() -> list:
    """
    Las sesiones guardadas, listas para enseñar y elegir. 0 peticiones.

    Cada una con lo que hace falta para reconocerla: el nombre de usuario
    si ya se supo, de dónde salió y si está comprobada. La activa primero,
    que es la que se mira antes.
    """
    datos = leer_sesiones()
    activa = datos.get("activa", "")
    fuera = []
    for clave, d in datos["cuentas"].items():
        usuario = d.get("usuario") or ""
        fuera.append({
            "clave": clave,
            "activa": clave == activa,
            "usuario": usuario,
            # Se enseña el nombre si se sabe; si no, el id, que al menos es
            # estable y distingue una cuenta de otra.
            "titulo": f"@{usuario}" if usuario else f"cuenta id {clave}",
            "de_donde": d.get("etiqueta", ""),
            "comprobada": d.get("comprobada", ""),
            "guardada": (d.get("guardado") or "")[:16].replace("T", " "),
        })
    fuera.sort(key=lambda x: (not x["activa"], x["titulo"].lower()))
    return fuera


def activar_sesion(clave: str) -> bool:
    """
    Pone una de las guardadas como la que se usa. NO comprueba que funcione.

    Cambiar de sesión **no da presupuesto nuevo**: el contador del día es
    uno solo y a propósito. El límite es de la sesión y de la IP —está
    escrito en este proyecto desde la v3.5— y la IP no cambia por cambiar
    de cuenta. Repartir las mismas peticiones entre varias cuentas desde el
    mismo sitio no es más margen: es el patrón que Meta busca.
    """
    global _SESION_CACHE, _SESION_HASTA, _VERIFICACION_OK
    datos = leer_sesiones()
    guardada = datos["cuentas"].get(clave)
    if not guardada or not (guardada.get("cookies") or {}).get("sessionid"):
        return False
    # Si las cookies son las mismas, no hay nada que tirar. Verificar
    # cuesta peticiones, y esto se llama al apuntar de nuevo a la que ya
    # estaba: al buscar sesiones, o al pulsar «Usar» sobre la activa.
    cambian = (_cookies_guardadas() or {}) != guardada["cookies"]

    datos["activa"] = clave
    _guardar_sesiones(datos)
    _guardar_cookies(guardada["cookies"], registrar=False)
    if cambian:
        _SESION_CACHE, _SESION_HASTA = None, 0.0
        _VERIFICACION_OK = None
    return True


def quitar_sesion(clave: str) -> bool:
    """Borra una sesión guardada. Si era la activa, deja de haber activa."""
    datos = leer_sesiones()
    if clave not in datos["cuentas"]:
        return False
    del datos["cuentas"][clave]
    if datos.get("activa") == clave:
        datos["activa"] = next(iter(datos["cuentas"]), "")
        if datos["activa"]:
            _guardar_cookies(
                datos["cuentas"][datos["activa"]]["cookies"], registrar=False)
        else:
            ARCHIVO_SESION.unlink(missing_ok=True)
    _guardar_sesiones(datos)
    return True


def migrar_sesiones() -> list:
    """
    Trae a la carpeta lo que estuviera suelto en la raíz. Una sola vez.

    Mover una sesión no es como mover un CSV: si se pierde por el camino
    hay que volver a sacarla del navegador. Se mueve solo si el destino no
    existe, y lo que no se pueda mover se queda donde está.
    """
    traidos = []
    raiz = CARPETA_SESIONES.parent
    for antes, ahora in ((raiz / "sesion_instagram.json", ARCHIVO_SESION),
                         (raiz / "sesiones.json", _ruta_sesiones())):
        if antes.exists() and not ahora.exists():
            try:
                ahora.parent.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    ahora.parent.chmod(0o700)
                antes.replace(ahora)
                traidos.append(antes.name)
            except OSError:
                pass
    return traidos


# Los motivos por los que un navegador no suelta sus cookies no son
# equivalentes, y tratarlos igual es lo que convierte la búsqueda en diez
# líneas de ruido donde no se distingue lo que importa.
#
#   no_instalado  no está en el equipo. No hay nada que hacer ni que leer.
#   cifradas      SÍ está, y tiene las cookies protegidas. Esto es lo único
#                 accionable, y es el caso de Chrome en Windows.
#   sin_sesion    está y se lee, pero ahí no hay sesión de Instagram.
_SENALES = (
    ("no_instalado", ("failed to find cookies", "could not find",
                      "can not find", "no such file", "not found",
                      "argument must be str")),
    ("cifradas", ("requires admin", "as admin", "decrypt", "cifr",
                  "permission", "denied", "dpapi", "keyring",
                  "unprotect")),
    ("bloqueado", ("locked", "in use", "being used", "database is locked")),
)


def clasificar_fallo(mensaje: str) -> str:
    """
    Por qué no se pudo leer ese navegador. Función pura.

    «No está instalado» y «está instalado pero no me deja» piden cosas
    distintas de quien está delante: la primera, nada; la segunda, pegar la
    cookie a mano. Decir «no se pudo» a las dos deja al usuario sin saber
    cuál de sus navegadores mirar.
    """
    texto = (mensaje or "").lower()
    for clase, marcas in _SENALES:
        if any(m in texto for m in marcas):
            return clase
    return "otro"


CONSEJOS = {
    "cifradas": ("tiene las cookies protegidas. Ciérralo del todo y "
                 "reintenta; si sigue, usa «Añadir otra a mano»: F12 → "
                 "Aplicación → Cookies → instagram.com → sessionid"),
    "bloqueado": "está abierto ahora mismo. Ciérralo del todo y reintenta",
    "sin_sesion": "no tiene ninguna sesión de Instagram abierta",
    "otro": "no se pudo leer",
}


def resumir_busqueda(hallazgos: list) -> dict:
    """
    Agrupa lo encontrado para poder contarlo en tres líneas y no en diez.

    Lo que importa arriba: las que hay. Después, las que se podrían tener
    si se hace algo. Y al final, en una sola línea, las que ni están.
    """
    encontradas = [h for h in hallazgos if h.get("cookies")]
    accionables, ausentes = [], []
    for h in hallazgos:
        if h.get("cookies"):
            continue
        (ausentes if h.get("clase") == "no_instalado"
         else accionables).append(h)
    return {"encontradas": encontradas, "accionables": accionables,
            "ausentes": [h["navegador"] for h in ausentes]}


def buscar_sesiones(navegadores=None) -> list:
    """
    Recorre los navegadores del equipo y devuelve lo que encuentre.

    Cero peticiones: son archivos de cookies del propio ordenador, no se
    habla con Instagram. Cada navegador puede tener una cuenta distinta
    abierta, y eso es justo lo que hace útil mirarlos todos.

    Devuelve una lista de {navegador, cookies, id, motivo} — también los
    que fallaron, con su motivo. Un navegador que no está instalado y uno
    que tiene las cookies cifradas son cosas distintas, y decir «no se
    pudo» para las dos no ayuda a nadie.
    """
    try:
        import browser_cookie3
    except ImportError:
        return [{"navegador": "-", "cookies": {}, "id": "",
                 "clase": "otro",
                 "motivo": "falta browser_cookie3: pip install "
                           "browser_cookie3"}]

    hallazgos = []
    for nombre in (navegadores or NAVEGADORES):
        lector = getattr(browser_cookie3, nombre, None)
        if lector is None:
            continue                    # esta versión no lo conoce
        try:
            jar = lector(domain_name="instagram.com")
        except Exception as e:
            # El motivo se recorta: browser_cookie3 devuelve trazas largas
            # y aquí solo hace falta distinguir «no está» de
            # «está cifrado».
            motivo = str(e).splitlines()[0][:90]
            hallazgos.append({"navegador": nombre, "cookies": {}, "id": "",
                              "clase": clasificar_fallo(motivo),
                              "motivo": motivo})
            continue

        cookies = {c.name: c.value for c in jar if c.name in COOKIES_UTILES}
        if not cookies.get("sessionid"):
            hallazgos.append({"navegador": nombre, "cookies": {}, "id": "",
                              "clase": "sin_sesion",
                              "motivo": CONSEJOS["sin_sesion"]})
            continue
        # El id va dentro del propio sessionid; no hace falta pedirlo.
        completas = leer_cookies_pegadas(json.dumps(cookies))
        hallazgos.append({"navegador": nombre, "cookies": completas,
                          "id": completas.get("ds_user_id", ""),
                          "clase": "encontrada", "motivo": ""})
    return hallazgos


def registrar_hallazgos(hallazgos: list) -> list:
    """
    Guarda las sesiones encontradas. NO cambia la que está en uso.

    Encontrar tres cuentas y ponerse a usar otra sin avisar sería de las
    cosas que hacen desconfiar de un programa. Se guardan y se eligen a
    mano; solo si no había ninguna se activa la primera.
    """
    activa_antes = leer_sesiones().get("activa", "")
    guardadas = []
    for h in hallazgos:
        if not h.get("cookies", {}).get("sessionid"):
            continue
        clave = registrar_sesion(h["cookies"], h["navegador"])
        if clave:
            guardadas.append(clave)
    if not guardadas:
        return guardadas

    # registrar_sesion deja activa la última; hay que devolver la que
    # había. Pero SOLO si de verdad cambió: activar_sesion tira la sesión
    # en caché y la verificación hecha, así que llamarla sin necesidad
    # obligaría a comprobar otra vez — y comprobar cuesta peticiones.
    # Buscar sesiones no puede salir caro.
    ahora = leer_sesiones()
    quiere = activa_antes if activa_antes in ahora["cuentas"] else guardadas[0]
    if ahora.get("activa") != quiere:
        activar_sesion(quiere)
    elif activa_antes:
        # La activa no cambió, pero registrar_sesion ya reescribió el
        # puntero: basta con dejarlo apuntando donde estaba.
        ahora["activa"] = activa_antes
        _guardar_sesiones(ahora)
    return guardadas


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
    Devuelve (usuario, estado) con estado en {"viva", "rechazada",
    "desconocida"}.

    «rechazada» y no «muerta»: un 401 aquí significa que Instagram está
    diciendo que no AHORA, no que las cookies estén caducadas. Son cosas
    distintas y confundirlas sale caro — con la sesión funcionando en el
    navegador, esto llegó a decir «caducó» y a mandar reimportar las
    mismas cookies, que es insistir durante un bloqueo por otra puerta.

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
        # Estas peticiones NO pasan por pedir(), y es a propósito: aquí se
        # quiere OBSERVAR el 401 en vez de tratarlo como un corte. Pero
        # cuentan igual, que si no el presupuesto miente. Daba igual
        # mientras esto ocurría una vez cada diez minutos; desde que se
        # pueden comprobar varias sesiones seguidas, ya no.
        if queda_presupuesto() <= 0:
            break
        anotar_peticion(endpoint)
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
            # Cuenta como rechazo, que es lo que es. Sin esto, los 401 de
            # la verificación se saltaban la parada del día que existe
            # desde la v6.0 justo para no escalar a checkpoint.
            anotar_rechazo(_clave_endpoint(endpoint))

    return (None, "rechazada") if visto_401 else (None, "desconocida")


def sesion_con(cookies: dict) -> requests.Session:
    """
    Una sesión lista para pedir, con estas cookies. No toca la activa.

    Se sacó de `crear_sesion` para poder comprobar una sesión guardada sin
    cambiarse a ella: antes, para saber de quién era una, había que
    activarla — y eso tiraba la que estabas usando y su verificación.
    """
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
    return s


def comprobar_guardada(clave: str) -> tuple:
    """
    Mira si una sesión guardada sirve, y de quién es. Cuesta 1 petición.

    Sin cambiarse a ella: es lo que permite comprobar las tres que
    encontraste sin perder la que estás usando. Y de paso le pone nombre,
    que es lo que hace que la lista se pueda leer.
    """
    guardada = leer_sesiones()["cuentas"].get(clave) or {}
    cookies = guardada.get("cookies") or {}
    if not cookies.get("sessionid"):
        return None, "sin cookies"
    usuario, estado = comprobar_sesion(sesion_con(cookies))
    if usuario and not str(usuario).startswith("#"):
        anotar_usuario_de_sesion(clave, usuario)
    elif estado == "ok":
        # Sirve, pero solo se pudo confirmar el id. Se sella igual que
        # está comprobada: es la mitad de lo que hacía falta saber, y
        # evita volver a gastar una petición en lo mismo.
        anotar_usuario_de_sesion(clave)
    return usuario, estado


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

    s = sesion_con(cookies)
    usuario, estado = comprobar_sesion(s)

    if estado == "rechazada":
        # NO se reimporta. Las cookies del navegador son las mismas que
        # acaban de ser rechazadas, así que volver a leerlas solo gasta
        # otra ronda de peticiones y otro 401 — que es exactamente lo que
        # alarga un bloqueo. En el caso que lo destapó, la sesión seguía
        # funcionando en el navegador.
        raise SesionInvalida(
            "Instagram está rechazando las peticiones de esta sesión "
            "(HTTP 401/403).\n"
            "    Eso NO significa que tus cookies estén mal: la sesión "
            "puede seguir\n"
            "    funcionando en el navegador. Suele ser un freno "
            "temporal.\n"
            "    Abre instagram.com y mira si hay algo que confirmar; "
            "luego espera\n"
            "    un rato antes de reintentar. Insistir ahora lo alarga."
        )

    _guardar_cookies(cookies)
    if usuario and not str(usuario).startswith("#"):
        # El nombre se descubre al verificar y hasta ahora se tiraba. Con
        # varias sesiones guardadas, elegir entre «cuenta id 9982027586» y
        # «cuenta id 5551234» no es elegir. Con @nombre, sí.
        anotar_usuario_de_sesion(_clave_de(cookies), usuario)

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

TOPE_DIARIO = 250                # el tope de partida, antes de medir nada

# El tope real no lo sabe nadie: 250 fue un número puesto a ojo. Y los
# bloqueos que ha habido vinieron de 'web_profile_info', no del endpoint de
# listas, que la documentación de este proyecto llama «lo más fiable».
#
# Así que se busca como se busca cualquier límite desconocido sin conocerlo:
# subir despacio mientras no pase nada y bajar de golpe en cuanto pase. Es
# lo que hace TCP con el ancho de banda, y por el mismo motivo — converge
# por debajo del límite de verdad en vez de rondarlo.
PASO_TOPE = 25                   # cuánto sube tras un día limpio y apurado
CAIDA_TOPE = 0.6                 # a cuánto se queda tras un bloqueo
SUELO_TOPE = 50                  # nunca por debajo: dejaría de servir
TECHO_TOPE = 1000                # nunca por encima: no se mide sin freno
APURADO = 0.8                    # un día cuenta como prueba si llegó aquí
MINIMO_PARA_CULPAR = 10          # peticiones antes de culpar al volumen

# Un 429 dice «frena». Un 401 o un 403 dicen «no te reconozco», que es el
# escalón anterior al checkpoint y a la cuenta cerrada. Insistir ahí es lo
# que convierte un mal día en una cuenta perdida, así que a los rechazos se
# les trata mucho peor que a los cortes de ritmo.
RECHAZOS_PARA_PARAR = 2          # rechazos en un día antes de parar del todo
TOPE_HORA = 120                  # peticiones en una hora, pase lo que pase

# Las peticiones SIN sesión tienen su propio contador, y no es un capricho:
# no gastan el presupuesto de la sesión, pero salen por la MISMA IP, que es
# la otra mitad del límite de Instagram. Meterlas en el contador de siempre
# haría creer que cuestan sesión; dejarlas sin contar haría creer que no
# cuestan nada. Ni una cosa ni la otra.
TOPE_HORA_ANONIMO = 60           # páginas públicas por hora
MARGEN_BORDE = 0.9               # hasta dónde se acerca al borde conocido
DIAS_REPROBAR = 30               # cada cuánto se vuelve a tantear
AVISO_AL = 0.70                  # a partir de aquí se avisa

_PRESUPUESTO: dict | None = None  # copia en memoria del archivo
# Incrementos aún no volcados a disco. Existen porque la ventana y la tarea
# programada corren a la vez: si cada proceso escribiera su copia entera, el
# último en guardar borraría lo que contó el otro. Se guardan los DELTAS y se
# suman a lo que haya en el archivo en ese momento.
_PENDIENTE = {"hechas": 0, "bloqueos": 0, "por_endpoint": {}}


class SinPresupuesto(ErrorPrevisto):
    """Se agotó el tope diario. No se arregla esperando un rato."""


# ======================================================================
# AJUSTES
# ======================================================================
# La configuración estaba en tres sitios: config_gui.json, rutas.json y una
# docena de constantes aquí dentro. Para cambiar el ritmo había que editar
# Python, que es tanto como decir que no se podía cambiar.
#
# Aquí queda uno solo. `rutas.json` NO se mezcla y es a propósito: eso no es
# configuración, es la reparación de cuando Instagram cambia un nombre, y
# tiene su propia ayuda dentro.
#
# Cada ajuste lleva su MÍNIMO Y SU MÁXIMO, y esto no es decoración. Todo el
# proyecto está construido para no perder la cuenta; un archivo que
# permitiera `pausa_min: 0` o `tope_hora: 99999` sería la forma más rápida
# de tirar por la borda lo demás. Se puede mover, dentro de lo razonable.
#
#   clave: (constante, mínimo, máximo, grupo, para qué sirve)
AJUSTABLES = {
    "pausa_min": ("PAUSA_MIN", 0.5, 30, "ritmo",
                  "segundos mínimos entre páginas"),
    "pausa_max": ("PAUSA_MAX", 0.5, 60, "ritmo",
                  "segundos máximos entre páginas"),
    "descanso_cada": ("DESCANSO_CADA", 5, 500, "ritmo",
                      "cada cuántas páginas se descansa"),
    "descanso_seg": ("DESCANSO_SEG", 5, 600, "ritmo",
                     "cuánto dura ese descanso"),
    # El máximo era 50, lo que pide la web. Se sube a 200 para poder
    # aplicar lo que mida `pagina`, pero el valor de serie SIGUE siendo 50:
    # subirlo ahorra peticiones a cambio de parecerse menos a un navegador,
    # y esa es una decisión de quien lo usa, no del programa.
    "por_pagina": ("POR_PAGINA", 10, 200, "ritmo",
                   "personas por petición (50 es lo que pide la web)"),
    "tope_diario": ("TOPE_DIARIO", 20, 1000, "presupuesto",
                    "peticiones al día de partida, antes de aprenderlo"),
    "tope_hora_anonimo": ("TOPE_HORA_ANONIMO", 0, 300, "presupuesto",
                          "páginas públicas por hora; 0 lo apaga del todo"),
    "tope_hora": ("TOPE_HORA", 10, 500, "presupuesto",
                  "peticiones en una hora, para no ir a ráfagas"),
    "rechazos_para_parar": ("RECHAZOS_PARA_PARAR", 1, 10, "presupuesto",
                            "401/403 en un día antes de parar del todo"),
    "umbral_cambio": ("UMBRAL_CAMBIO", 1, 100, "vigilancia",
                      "diferencia en los totales que dispara bajar"),
    "max_dias_sin_bajar": ("MAX_DIAS_SIN_BAJAR", 1, 60, "vigilancia",
                           "descarga forzada cada N días aunque no cambie"),
    "max_vigilancia": ("MAX_VIGILANCIA", 1, 200, "vigilancia",
                       "tope de cuentas en la lista de vigilancia"),
    "dias_foto": ("DIAS_FOTO", 1, 365, "datos",
                  "cada cuánto se refresca la foto de perfil"),
    "dias_a_diario": ("DIAS_A_DIARIO", 7, 3650, "datos",
                      "días que 'podar' conserva capturas diarias"),
    "tope_filas_informe": ("TOPE_FILAS_INFORME", 100, 100_000, "datos",
                           "filas por tabla en el informe HTML"),
}


# Foto de los valores originales. Sin ella, «de serie» se leía de los
# globales, que para entonces ya podían estar cambiados por el propio
# archivo: decía que el valor de serie era el que acababas de poner tú.
#
# Se hace en la PRIMERA consulta y no al importar: la mitad de estas
# constantes se declaran más abajo en el archivo, y al importar todavía no
# existen. En la primera consulta el módulo ya está entero.
DE_SERIE: dict = {}


def _de_serie() -> dict:
    """
    Los valores originales, ya acotados a sus propios límites.

    Se acotan porque si no, un valor de serie fuera de su margen —por un
    descuido en el código, o porque algo lo cambió antes del retrato—
    haría que «restaurar» dejara puesto un valor ilegal. Lo de serie
    cumple las mismas reglas que lo que escribe quien lo usa.
    """
    if not DE_SERIE:
        for clave, datos in AJUSTABLES.items():
            crudo = globals()[datos[0]]
            acotado = acotar(clave, crudo)
            DE_SERIE[clave] = crudo if acotado is None else acotado
    return DE_SERIE


def _ruta_ajustes() -> Path:
    return CARPETA / "ajustes.json"


def ajustes_de_serie() -> dict:
    """Los valores con los que viene el programa."""
    return dict(_de_serie())


def acotar(clave: str, valor):
    """
    El valor dentro de sus límites, o None si no es ni un número.

    Recorta en vez de rechazar: quien escribe 5000 en el tope por hora
    quiere «mucho», y dejarle el que había sin decir nada sería peor que
    darle el máximo y contárselo.
    """
    if clave not in AJUSTABLES:
        return None
    _, minimo, maximo, _, _ = AJUSTABLES[clave]
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    # El tipo se deduce de los LÍMITES, que están escritos aquí y nadie
    # puede cambiar en marcha, y no del valor que haya ahora. Deducirlo del
    # valor era frágil: basta con que algo lo ponga a 0 —entero— para
    # que un 2.5 perfectamente válido se redondee a 2.
    if isinstance(minimo, int) and isinstance(maximo, int):
        numero = int(round(numero))
    return max(minimo, min(maximo, numero))


def leer_ajustes() -> dict:
    """Lo que hay escrito en el archivo, sin aplicar ni validar."""
    try:
        d = json.loads(_ruta_ajustes().read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if k in AJUSTABLES} \
            if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def aplicar_ajustes() -> list:
    """
    Mete los ajustes del archivo en las constantes. Devuelve qué cambió.

    Se cambian los globales en vez de consultar el archivo en cada uso: las
    constantes siguen siendo los valores de serie Y el esquema, y no hay
    que tocar los cuarenta sitios que las leen. Ocurre una vez, en un sitio
    con nombre, y queda anotado en el registro.
    """
    serie = _de_serie()     # se retrata antes de tocar nada
    cambios = []
    guardados = leer_ajustes()
    # Lo que ya no esté en el archivo vuelve a su valor de serie: si no,
    # quitar una línea del archivo no tendría ningún efecto y habría que
    # adivinar por qué.
    for clave, valor in serie.items():
        if clave not in guardados and globals()[AJUSTABLES[clave][0]] != valor:
            globals()[AJUSTABLES[clave][0]] = valor
    for clave, valor in guardados.items():
        acotado = acotar(clave, valor)
        if acotado is None:
            continue
        constante = AJUSTABLES[clave][0]
        if globals()[constante] != acotado:
            cambios.append(f"{clave}: {globals()[constante]} -> {acotado}")
            globals()[constante] = acotado

    # Relación entre dos: una pausa mínima mayor que la máxima haría que
    # random.uniform devolviera cosas raras en vez de fallar.
    if PAUSA_MIN > PAUSA_MAX:
        globals()["PAUSA_MAX"] = PAUSA_MIN
        cambios.append(f"pausa_max subida a {PAUSA_MIN}: no puede ser menor "
                       "que la mínima")
    return cambios


def guardar_ajustes(nuevos: dict) -> tuple[dict, list]:
    """
    Guarda y aplica. Devuelve (lo aplicado, avisos de lo que se recortó).
    """
    guardados = leer_ajustes()
    avisos = []
    for clave, valor in (nuevos or {}).items():
        if clave not in AJUSTABLES:
            avisos.append(f"'{clave}' no es un ajuste conocido")
            continue
        acotado = acotar(clave, valor)
        if acotado is None:
            avisos.append(f"'{clave}': '{valor}' no es un número")
            continue
        if float(acotado) != float(valor):
            _, minimo, maximo, _, _ = AJUSTABLES[clave]
            avisos.append(f"'{clave}' se queda en {acotado} "
                          f"(el margen va de {minimo} a {maximo})")
        guardados[clave] = acotado

    # Solo se anota lo que se APARTA de lo de serie. Guardar los catorce
    # aunque no se hayan tocado deja un archivo donde todo aparece como
    # «cambiado», y entonces la marca deja de significar nada.
    serie = _de_serie()
    guardados = {k: v for k, v in guardados.items()
                 if float(v) != float(serie[k])}
    try:
        if guardados:
            escribir_atomico(
                _ruta_ajustes(),
                json.dumps(guardados, indent=2, ensure_ascii=False))
        else:
            with contextlib.suppress(OSError):
                _ruta_ajustes().unlink(missing_ok=True)
    except OSError:
        avisos.append("no se pudo escribir el archivo de ajustes")
    aplicar_ajustes()
    return guardados, avisos


def migrar_config_gui(ruta: Path) -> list:
    """
    Trae a ajustes.json lo que había en config_gui.json. Una sola vez.

    Aquel archivo tenía 'umbral' y 'max_dias', que eran los mismos valores
    que UMBRAL_CAMBIO y MAX_DIAS_SIN_BAJAR aquí dentro. Dos sitios para el
    mismo número es cómo acaban discrepando.
    """
    equivalencias = {"umbral": "umbral_cambio",
                     "max_dias": "max_dias_sin_bajar"}
    try:
        viejo = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return []
    traer = {nuevo: viejo[antes] for antes, nuevo in equivalencias.items()
             if antes in viejo and nuevo not in leer_ajustes()}
    if not traer:
        return []
    guardar_ajustes(traer)
    return [f"{k}={v}" for k, v in traer.items()]




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
        cerrar_dia(_PRESUPUESTO)
        # 'aprendido' NO se reinicia: saber qué endpoint funciona no caduca
        # a medianoche, y volver a descubrirlo cuesta peticiones.
        _PRESUPUESTO = {"dia": hoy, "hechas": 0, "bloqueos": 0,
                        "rechazos": 0, "por_hora": {},
                        "anonimas": 0, "anonimas_por_hora": {},
                        "por_endpoint": {}, "primera": None, "ultima": None,
                        "aprendido": _PRESUPUESTO.get("aprendido", {})}
    return _PRESUPUESTO


# Lo que se acumula entre procesos: números que se suman y repartos que se
# suman clave a clave. Tenerlo declarado en un sitio es lo que evita que
# una cuenta nueva se pierda en el volcado, que es justo lo que pasó con
# 'bloqueos_por_endpoint': se anotaba en memoria y el guardado la tiraba.
CONTADORES = ("hechas", "bloqueos", "rechazos", "anonimas")
REPARTOS = ("por_endpoint", "bloqueos_por_endpoint", "por_hora",
            "anonimas_por_hora")


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
                disco = {"dia": p["dia"], "primera": None, "ultima": None,
                         "aprendido": {}}

            for nombre in CONTADORES:
                disco[nombre] = (disco.get(nombre, 0)
                                 + _PENDIENTE.get(nombre, 0))
            for nombre in REPARTOS:
                destino = disco.setdefault(nombre, {})
                for clave, n in (_PENDIENTE.get(nombre) or {}).items():
                    destino[clave] = destino.get(clave, 0) + n

            disco["primera"] = disco.get("primera") or p.get("primera")
            disco["ultima"] = p.get("ultima") or disco.get("ultima")
            disco.setdefault("aprendido", {}).update(p.get("aprendido", {}))

            # Sin fsync: esto se escribe en cada petición y el coste se
            # notaría. Un contador perdido se rehace; una captura no.
            escribir_atomico(
                _ruta_presupuesto(),
                json.dumps(disco, indent=2, ensure_ascii=False),
                durable=False)

        for nombre in CONTADORES:
            _PENDIENTE[nombre] = 0
        for nombre in REPARTOS:
            _PENDIENTE[nombre] = {}
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
    por_hora = p.setdefault("por_hora", {})
    por_hora[ahora[:2]] = por_hora.get(ahora[:2], 0) + 1
    pend = _PENDIENTE.setdefault("por_hora", {})
    pend[ahora[:2]] = pend.get(ahora[:2], 0) + 1
    _guardar_presupuesto()


def anotar_bloqueo_diario(clave: str = "") -> None:
    """
    Anota un bloqueo, y de qué endpoint vino.

    De qué endpoint importa mucho: 'web_profile_info' corta a la PRIMERA
    petición para esta sesión —está documentado desde la v2.9— y eso no
    dice nada sobre cuántas peticiones aguanta el endpoint de listas, que
    es el que hace el trabajo. Sin distinguirlos, el tope diario bajaba un
    40% por un bloqueo que no tenía nada que ver con el volumen.
    """
    p = _presupuesto()
    p["bloqueos"] = p.get("bloqueos", 0) + 1
    _PENDIENTE["bloqueos"] += 1
    if clave:
        por = p.setdefault("bloqueos_por_endpoint", {})
        por[clave] = por.get(clave, 0) + 1
        pend = _PENDIENTE.setdefault("bloqueos_por_endpoint", {})
        pend[clave] = pend.get(clave, 0) + 1
    _guardar_presupuesto()


def anotar_rechazo(clave: str = "") -> None:
    """
    Anota un 401/403: Instagram no está reconociendo la sesión.

    Va aparte de los bloqueos de ritmo a propósito. Un 429 se pasa
    esperando; un rechazo repetido no se pasa esperando, escala. Antes esto
    solo ponía cinco minutos de cuarentena en un endpoint: ni contaba para
    el día, ni doblaba las pausas, ni frenaba el tope, que seguía subiendo
    mientras Instagram decía que no.
    """
    p = _presupuesto()
    p["rechazos"] = p.get("rechazos", 0) + 1
    p["bloqueos"] = p.get("bloqueos", 0) + 1     # también frena las pausas
    _PENDIENTE["bloqueos"] = _PENDIENTE.get("bloqueos", 0) + 1
    _PENDIENTE["rechazos"] = _PENDIENTE.get("rechazos", 0) + 1
    if clave:
        por = p.setdefault("bloqueos_por_endpoint", {})
        por[clave] = por.get(clave, 0) + 1
        pend = _PENDIENTE.setdefault("bloqueos_por_endpoint", {})
        pend[clave] = pend.get(clave, 0) + 1
    _guardar_presupuesto()


def parado_por_rechazos() -> int:
    """Cuántos rechazos van hoy. A partir de RECHAZOS_PARA_PARAR, se para."""
    return int(_presupuesto().get("rechazos", 0))


def bloqueos_de_volumen(dia: dict) -> int:
    """
    Cuántos bloqueos del día miden de verdad un límite de VOLUMEN.

    Un corte tras tres peticiones a ese endpoint no es un límite de ritmo:
    es que ese endpoint está vetado para esta sesión, pase lo que pase. Un
    corte tras trescientas sí lo es. La regla es general y medible, y no
    hay que escribir el nombre de ningún endpoint en el código.
    """
    por_endpoint = dia.get("por_endpoint") or {}
    bloqueos = dia.get("bloqueos_por_endpoint")
    if bloqueos is None:
        # Días de antes de que se anotara el endpoint: se cuentan todos,
        # que es lo que se hacía y no se puede saber más.
        return int(dia.get("bloqueos") or 0)
    return sum(n for clave, n in bloqueos.items()
               if por_endpoint.get(clave, 0) >= MINIMO_PARA_CULPAR)


def _ruta_limite() -> Path:
    # En la raíz: el límite es de la SESIÓN y de la IP, no de la cuenta que
    # se esté mirando. Mirar a otra persona no te da peticiones nuevas.
    return CARPETA / "limite.json"


def _limite() -> dict:
    try:
        d = json.loads(_ruta_limite().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def tope_diario() -> int:
    """
    El tope en uso: el aprendido, recortado por lo que va pasando HOY.

    El tope aprendido solo se recalculaba al cerrar el día, así que en una
    jornada con bloqueos seguía diciendo 250 mientras Instagram cortaba una
    de cada tres peticiones. Eso no es un tope: es un número que da
    permiso.

    AIMD baja de golpe ante un bloqueo, y esa es exactamente la reacción
    que hacía falta aquí; solo que llegaba mañana. Ahora cada bloqueo del
    día recorta el techo de hoy, sin tocar lo aprendido —eso sigue
    decidiéndose al cerrar, con el día entero a la vista—.
    """
    aprendido = _limite().get("tope")
    base = (aprendido if isinstance(aprendido, int)
            and SUELO_TOPE <= aprendido <= TECHO_TOPE else TOPE_DIARIO)

    bloqueos = _presupuesto().get("bloqueos", 0)
    if not bloqueos:
        return base
    # Cada bloqueo recorta un 30%, con suelo: tres bloqueos dejan el techo
    # en un tercio, y a partir de ahí manda el suelo. No se baja de
    # SUELO_TOPE porque un tope de cero impediría hasta comprobar si la
    # cosa ha pasado.
    recortado = int(base * (0.7 ** min(bloqueos, 6)))
    # El suelo no puede SUBIR el tope: quien lo haya fijado bajo a
    # propósito —«limite --fijar 20»— no puede acabar con 50 por haber
    # recibido un bloqueo. Un freno que afloja es peor que ninguno.
    return max(min(SUELO_TOPE, base), recortado)


def ajustar_tope(dia: dict, estado: dict | None = None) -> dict:
    """
    Qué tope toca mañana, visto cómo fue el día que cierra. Es pura.

    Es AIMD —subir despacio, bajar de golpe— con un añadido que AIMD no
    tiene y aquí hace falta: **cuando encuentra el borde, deja de
    empujarlo**. TCP sondea sin parar porque el ancho de banda cambia cada
    segundo; el límite de Instagram no. Sin el freno, esto provocaba un
    bloqueo cada dos semanas para siempre a cambio de nada.

    Cuatro casos:

    - Hubo bloqueos: se baja de golpe y se anota el borde. Un bloqueo es la
      única medida directa del límite que existe, y hay que creérsela.
    - Día limpio y apurado, con sitio bajo el borde: se sube un paso.
    - Día limpio y apurado, ya pegado al borde: **no se toca**. Ya se sabe
      dónde está; volver a comprobarlo solo cuesta bloqueos.
    - Día limpio pero flojo: tampoco. De un día en que no te acercaste no
      aprendes dónde está el borde, y subir por eso sería volver a suponer,
      que es justo lo que este experimento viene a quitar.

    Cada `DIAS_REPROBAR` días pegado al borde sin incidentes, se sube el
    borde un poco y se vuelve a probar: por si Instagram ha aflojado.
    """
    estado = dict(estado or {})
    tope = int(dia.get("tope") or TOPE_DIARIO)
    hechas = int(dia.get("hechas") or 0)
    bloqueos = int(dia.get("bloqueos") or 0)
    borde = estado.get("borde")
    pegados = int(estado.get("pegados") or 0)

    if bloqueos:
        # El borde es el número MÁS BAJO que alguna vez cortó.
        borde = hechas if not borde else min(borde, hechas)
        return {"tope": max(SUELO_TOPE, int(tope * CAIDA_TOPE)),
                "borde": borde, "pegados": 0,
                "prudente": bool(estado.get("prudente")),
                "motivo": f"{plural(bloqueos, 'bloqueo')} con {hechas} "
                          f"peticiones; el borde está en {borde}"}

    if estado.get("prudente"):
        # Quien ya ha perdido una cuenta no quiere que un programa vaya
        # tanteando cuánto aguanta la siguiente. En prudente el tope solo
        # baja: los bloqueos siguen contando y las subidas no.
        return {"tope": tope, "borde": borde, "pegados": pegados,
                "prudente": True,
                "motivo": f"modo prudente: no se tantea hacia arriba "
                          f"({hechas} de {tope})"}

    if hechas < tope * APURADO:
        return {"tope": tope, "borde": borde, "pegados": pegados,
                "prudente": bool(estado.get("prudente")),
                "motivo": f"día limpio pero flojo ({hechas} de {tope}): "
                          "no prueba nada"}

    seguro = int(borde * MARGEN_BORDE) if borde else TECHO_TOPE
    if tope + PASO_TOPE <= min(seguro, TECHO_TOPE):
        return {"tope": tope + PASO_TOPE, "borde": borde, "pegados": 0,
                "prudente": False,
                "motivo": f"día limpio apurando el tope ({hechas} de {tope})"}

    pegados += 1
    if borde and pegados >= DIAS_REPROBAR:
        # Se prueba otra vez, por si el límite de Instagram ha subido.
        return {"tope": tope + PASO_TOPE, "borde": int(borde * 1.1),
                "pegados": 0, "prudente": False,
                "motivo": f"{plural(pegados, 'día')} pegado al borde sin "
                          "incidentes: se vuelve a probar"}
    return {"tope": tope, "borde": borde, "pegados": pegados,
            "prudente": bool(estado.get("prudente")),
            "motivo": f"pegado al borde conocido ({borde}); no se empuja"}


def cerrar_dia(dia: dict) -> None:
    """
    Guarda el día que termina y ajusta el tope. Idempotente.

    Sin esto no hay nada que medir: el contador se reiniciaba a medianoche
    y lo del día anterior se perdía entero.
    """
    if not dia.get("dia") or not dia.get("hechas"):
        return
    limite = _limite()
    historial = limite.get("historial") or []
    if historial and historial[-1].get("dia") == dia["dia"]:
        return                      # ya cerrado, quizá por el otro proceso

    cerrado = {"dia": dia["dia"], "hechas": dia.get("hechas", 0),
               "bloqueos": bloqueos_de_volumen(dia),
               "todos_los_bloqueos": dia.get("bloqueos", 0),
               "tope": limite.get("tope") or TOPE_DIARIO}
    ajuste = ajustar_tope(cerrado, limite)
    cerrado["motivo"] = ajuste["motivo"]
    historial.append(cerrado)

    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        escribir_atomico(_ruta_limite(), json.dumps(
            {"tope": ajuste["tope"], "borde": ajuste["borde"],
             "pegados": ajuste["pegados"],
             "prudente": bool(ajuste.get("prudente")),
             "historial": historial[-120:]},
            ensure_ascii=False, indent=2))
    except OSError:
        pass


def anotar_anonima() -> None:
    """Anota una petición sin sesión. No toca el presupuesto de la sesión."""
    p = _presupuesto()
    hora = datetime.now().strftime("%H")
    por = p.setdefault("anonimas_por_hora", {})
    por[hora] = por.get(hora, 0) + 1
    p["anonimas"] = p.get("anonimas", 0) + 1
    pend = _PENDIENTE.setdefault("anonimas_por_hora", {})
    pend[hora] = pend.get(hora, 0) + 1
    _PENDIENTE["anonimas"] = _PENDIENTE.get("anonimas", 0) + 1
    _guardar_presupuesto()


def anonimas_de_la_hora() -> int:
    p = _presupuesto()
    hora = datetime.now().strftime("%H")
    return int((p.get("anonimas_por_hora") or {}).get(hora, 0))


def _peticiones_de_la_hora() -> int:
    """
    Cuántas van en la hora en curso.

    El tope diario no distingue entre gastar 250 peticiones repartidas por
    el día y gastarlas en diez minutos, y para quien las recibe son dos
    cosas muy distintas. Un repartidor de ráfagas es lo que no parece una
    persona usando la aplicación.
    """
    p = _presupuesto()
    hora = datetime.now().strftime("%H")
    return int((p.get("por_hora") or {}).get(hora, 0))


def queda_presupuesto() -> int:
    return max(0, tope_diario() - _presupuesto().get("hechas", 0))


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
    texto = f"{hechas}/{tope_diario()} peticiones hoy"
    if p.get("bloqueos"):
        texto += ", " + plural(p["bloqueos"], "bloqueo")
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
    "publicaciones_total": "edge_owner_to_timeline_media.count",
    "foto_perfil": "profile_pic_url",
    "foto_perfil_hd": "profile_pic_url_hd",
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
        escribir_atomico(destino, json.dumps({
            "_ayuda": [
                "Todo lo que Instagram puede cambiar y aquí se puede",
                "reparar sin tocar código. Edita solo lo que haga falta;",
                "lo que borres vuelve a su valor de serie.",
                "Tras editar, reinicia el programa.",
            ],
            "rutas": c["rutas"], "params": c["params"], "campos": c["campos"],
        }, indent=2, ensure_ascii=False))
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

class RespuestaInesperada(ErrorPrevisto):
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
        # Con segundos, dos fallos del mismo segundo se pisaban y el
        # primer diagnóstico —normalmente el que explica la causa— se
        # perdía. Con microsegundos y el pid no colisionan ni entre
        # procesos.
        sello = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        destino = CARPETA / f"fallo_{sello}_{os.getpid()}.json"

        if isinstance(cuerpo, (dict, list)):
            texto = json.dumps(cuerpo, ensure_ascii=False)[:MAX_CUERPO_VOLCADO]
        else:
            texto = str(cuerpo or "")[:MAX_CUERPO_VOLCADO]

        # Quitar cabeceras por su NOMBRE no basta: un secreto puede venir
        # dentro del cuerpo, de los parámetros o del detalle. Este archivo
        # se anuncia como compartible, así que todo lo que se escriba pasa
        # por el mismo limpiador. Comprobado: un {"sessionid": "..."} en
        # el cuerpo acababa entero en el fallo_*.json.
        seguras = {k: registro.limpiar_secretos(str(v))
                   for k, v in (cabeceras or {}).items()
                   if k.lower() not in ("cookie", "set-cookie",
                                        "authorization", "x-csrftoken")}
        texto = registro.limpiar_secretos(texto)

        escribir_atomico(destino, json.dumps({
            "cuando": datetime.now().isoformat(timespec="seconds"),
            "tipo": tipo,
            "ruta": registro.limpiar_secretos(str(ruta_usada or "")),
            # Solo el texto pasa por el limpiador: pasar TODO por str()
            # convertía `count: 50` en `"50"` y cambiaba lo que el volcado
            # dice que se pidió. Un número no puede llevar un secreto.
            "parametros": {k: (registro.limpiar_secretos(v)
                               if isinstance(v, str) else v)
                           for k, v in (params or {}).items()},
            "codigo_http": codigo,
            "detalle": registro.limpiar_secretos(str(detalle or "")),
            "respuesta": texto,
            "cabeceras_respuesta": seguras,
            "rutas_en_uso": config()["rutas"],
            "campos_en_uso": config()["campos"],
            "nota": "Sin cookies ni cabeceras de sesión. Se puede compartir.",
        }, indent=2, ensure_ascii=False))
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
    if parado_por_rechazos() >= RECHAZOS_PARA_PARAR:
        raise SinPresupuesto(
            f"{plural(parado_por_rechazos(), 'rechazo')} hoy (HTTP 401/403). "
            "Se para hasta mañana.\n"
            "    Eso no es un límite de ritmo: Instagram no está "
            "reconociendo la sesión.\n"
            "    Abre Instagram en el navegador con esa cuenta y mira si "
            "hay algo que confirmar.\n"
            "    Insistir ahora es lo que convierte esto en una cuenta "
            "cerrada.")

    en_esta_hora = _peticiones_de_la_hora()
    if en_esta_hora >= TOPE_HORA:
        raise Bloqueado(
            f"{plural(en_esta_hora, 'petición', 'peticiones')} en esta hora "
            f"(tope {TOPE_HORA}). Se sigue en la siguiente.")

    if queda_presupuesto() <= 0:
        raise SinPresupuesto(
            f"tope diario alcanzado ({tope_diario()} peticiones). Se "
            "reinicia mañana; mira 'limite' para saber por qué está ahí.")

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
        anotar_bloqueo_diario(_clave_endpoint(ruta))
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
        anotar_rechazo(_clave_endpoint(ruta))
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
        raise SinPresupuesto(f"tope diario alcanzado ({tope_diario()}).")
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
        anotar_bloqueo_diario(_clave_endpoint(ruta))
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


def privada_en_html(html: str, uid: str = "", username: str = ""):
    """
    Si la cuenta es privada, según su página. True, False o None.

    Antes esto era `'"is_private":true' in html`, buscando en la página
    ENTERA. Y una página de perfil lleva JSON embebido de muchas cuentas
    —sugeridas, relacionadas—, así que bastaba con que **cualquiera** de
    ellas fuera privada para marcar la tuya. Visto en una cuenta pública
    que salía como privada mientras se descargaba sin problema.

    Ahora se busca el valor PEGADO al id o al nombre de esta cuenta, en
    una ventana corta de texto. Si no se puede atar a ella, se devuelve
    None: «no consta», que no es lo mismo que «no». Es la misma regla que
    aplica `la_sigo` tres líneas más abajo, y la que lleva todo el
    proyecto.
    """
    plano = re.sub(r"\s+", "", html or "")
    anclas = [a for a in (f'"id":"{uid}"', f'"pk":"{uid}"',
                          f'"username":"{username}"') if uid or username]
    for ancla in anclas:
        desde = 0
        while True:
            i = plano.find(ancla, desde)
            if i < 0:
                break
            # El MÁS CERCANO al ancla, no cualquiera de la ventana: si en
            # esos 400 caracteres caben dos usuarios, mirar primero el
            # «true» devolvía el de al lado. Es el mismo error que esto
            # viene a arreglar, en pequeño.
            ventana, base = plano[max(0, i - 400):i + 400], max(0, i - 400)
            candidatos = [(abs(base + m_.start() - i), m_.group(1))
                          for m_ in re.finditer(r'"is_private":(true|false)',
                                                ventana)]
            if candidatos:
                return min(candidatos)[1] == "true"
            desde = i + 1
    return None


def perfil_de_la_pagina(html: str, username: str = "") -> dict:
    """
    El bloque estructurado del perfil que la página trae dentro.

    Descubierto mirando el HTML real de una cuenta pública en incógnito:
    además de las metas, la página lleva un JSON con `follower_count`,
    `pk`, `is_private`, `is_verified` y la biografía.

    Importa más de lo que parece, porque **la meta REDONDEA**. En la
    página mirada, og:description decía «970 seguidores, 98 siguiendo» y
    el bloque decía 969 y 96. Y `vigilar` compara totales para saber si
    algo se movió: con cifras redondeadas, un cambio de dos personas es
    invisible, y uno de redondeo parece un cambio que no hubo.

    Devuelve solo lo que encuentra. Lo que no esté no se inventa.
    """
    if not html:
        return {}
    # El bloque de ESTA cuenta, no el primero que aparezca. Una página
    # lleva JSON de varias —sugeridas, relacionadas— y quedarse con el
    # primero devolvía los datos del vecino: es el mismo fallo que tuvo
    # 'privada' en la v9.1, y la lección no se había aplicado aquí.
    i = _bloque_de(html, username)
    if i < 0:
        return {}
    # Los escapes son de un JSON dentro de otro; se deshacen para poder
    # leerlo con expresiones simples en vez de intentar parsearlo entero,
    # que dependería de dónde empieza y acaba el bloque.
    cerca = html[max(0, i - 1500):i + 900].replace('\\"', '"')

    def numero(clave):
        m = re.search(rf'"{clave}"\s*:\s*(\d+)', cerca)
        return int(m.group(1)) if m else None

    def texto(clave):
        m = re.search(rf'"{clave}"\s*:\s*"((?:[^"\\]|\\.)*)"', cerca)
        return _sin_escapes(m.group(1)) if m else None

    def booleano(clave):
        m = re.search(rf'"{clave}"\s*:\s*(true|false)', cerca)
        return m.group(1) == "true" if m else None

    # El enlace de la biografía viene en una lista de objetos; interesa el
    # primero, que es el que Instagram enseña bajo el nombre.
    enlace = ""
    lista = re.search(r'"bio_links"\s*:\s*\[(.*?)\]', cerca, re.S)
    if lista:
        url = re.search(r'"url"\s*:\s*"((?:[^"\\]|\\.)*)"', lista.group(1))
        if url:
            enlace = _sin_escapes(url.group(1))

    fuera = {"seguidores": numero("follower_count"),
             "seguidos": numero("following_count"),
             "publicaciones": numero("media_count"),
             "id": texto("pk"), "username": texto("username"),
             "nombre": limpiar_nombre(texto("full_name")),
             "privada": booleano("is_private"),
             "verificada": booleano("is_verified"),
             "biografia": texto("biography"),
             "enlace": enlace,
             "foto": texto("profile_pic_url"),
             "pronombres": _lista_de_textos(cerca, "pronouns"),
             # Dos estados que explican por qué una cuenta deja de
             # aparecer, y que no se podían saber de ninguna otra forma.
             "memorial": booleano("is_memorialized"),
             "desactivada": booleano("is_unpublished"),
             "threads": texto("text_post_app_badge_label")}
    return {k: v for k, v in fuera.items() if v is not None and v != ""}


def _bloque_de(html: str, username: str) -> int:
    """
    Dónde empieza el bloque de datos de esta cuenta. -1 si no se ata.

    Se busca el `follower_count` que tenga cerca el nombre de usuario
    pedido. Sin nombre se acepta el primero, que es lo que vale cuando la
    página solo trae una cuenta; pero si hay nombre y ninguno lo lleva
    cerca, NO se devuelve otro: es mejor no dar datos que dar los de
    otra persona.
    """
    posiciones = [m_.start() for m_ in re.finditer("follower_count", html)]
    if not posiciones:
        return -1
    if not username:
        return posiciones[0]
    for i in posiciones:
        cerca = html[max(0, i - 1500):i + 900]
        if f'username\\":\\"{username}' in cerca or \
                f'"username":"{username}"' in cerca:
            return i
    return -1


def _lista_de_textos(zona: str, clave: str) -> str:
    """Los textos de una lista JSON, juntos y separados por comas."""
    lista = re.search(rf'"{clave}"\s*:\s*\[(.*?)\]', zona, re.S)
    if not lista:
        return ""
    return ", ".join(_sin_escapes(t)
                     for t in re.findall(r'"((?:[^"\\]|\\.)*)"',
                                         lista.group(1)))


def _sin_escapes(texto: str) -> str:
    r"""Deshace los \uXXXX y las barras de un JSON leído a mano."""
    try:
        return json.loads(f'"{texto}"')
    except ValueError:
        return texto


def cifras_de_la_pagina(html: str) -> tuple:
    """
    Seguidores, seguidos y publicaciones de la meta og:description.

    Sale de `perfil_desde_html` para que la vía sin sesión la use también:
    dos parsers del mismo texto acabarían diciendo cosas distintas, que es
    el error que este proyecto ya ha cometido tres veces.
    """
    meta = re.search(r'property="og:description"\s+content="([^"]+)"',
                     html or "")
    if not meta:
        return 0, 0, 0
    texto = meta.group(1)
    f = re.search(r"([\d.,KMkm]+)\s*(?:Followers|seguidores)", texto, re.I)
    g = re.search(r"([\d.,KMkm]+)\s*(?:Following|seguidos|siguiendo)",
                  texto, re.I)
    b = re.search(r"([\d.,KMkm]+)\s*(?:Posts|publicaciones)", texto, re.I)
    return (_numero(f.group(1)) if f else 0,
            _numero(g.group(1)) if g else 0,
            _numero(b.group(1)) if b else 0)


def sesion_anonima() -> requests.Session:
    """
    Una sesión SIN cookies, para pedir la página pública de un perfil.

    Sin cabeceras de la API: pedir una página normal con `x-ig-app-id`
    encima es justo lo que no hace un navegador cualquiera. Aquí se busca
    parecer lo que se es —alguien abriendo una página pública— y no
    disimular nada.
    """
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    })
    return s


def solo_mirar(s, username: str) -> tuple:
    """
    Los totales de una cuenta, por la vía más barata que funcione.

    Primero sin sesión, que no gasta presupuesto; si Instagram responde
    con el muro de inicio de sesión —que es lo normal si se insiste—, se
    tira de la sesión como siempre.

    Devuelve (perfil, gastó_sesión). Lo segundo importa: quien llama tiene
    que saber si acaba de gastar una petición de las buenas o no.
    """
    # Se apaga poniendo su tope a 0 en los ajustes. Un interruptor aparte
    # sería una segunda forma de decir lo mismo, y entonces hay que mirar
    # las dos para saber si está encendido.
    if TOPE_HORA_ANONIMO > 0:
        p = perfil_anonimo(username)
        # Solo sirve si los totales son EXACTOS. Los de las metas están
        # redondeados, y quien decide si toca descargar compara totales:
        # con cifras aproximadas vería cambios que no hubo y se perdería
        # los de una o dos personas. Mejor gastar la petición de sesión.
        if p and p.get("totales_fiables"):
            return p, False
    return perfil(s, username), True


def perfil_anonimo(username: str) -> dict | None:
    """
    Cifras de una cuenta pública SIN gastar presupuesto de la sesión.

    Solo los tres totales. No hay listas ni relación: eso nunca ha estado
    disponible sin autenticar y no lo va a estar.

    Lo que esto NO es
    -----------------
    No es gratis. La cuota de Instagram es de la sesión **y de la IP**, y
    la IP es la misma; lo que se ahorra es el presupuesto de la sesión, no
    el riesgo. Por eso lleva su propio contador y su propio freno, y por
    eso `vigilar` lo usa para mirar y sigue usando la sesión para bajar.

    Devuelve None si Instagram responde con el muro de inicio de sesión,
    que es lo normal cuando se insiste. Quien llama decide si tira de
    sesión: aquí no se reintenta.
    """
    if anonimas_de_la_hora() >= TOPE_HORA_ANONIMO:
        return None
    destino = ruta("pagina_perfil", usuario=username)
    # El mismo cortafuegos que el resto: si acaban de cortar esta vía, no
    # se insiste. Sin esto seguía pidiendo tras cinco 429 seguidos, que es
    # justo lo que alarga un bloqueo — y el proyecto tiene una pieza para
    # eso desde la v2.9.
    if espera_pendiente(destino):
        return None
    try:
        s = sesion_anonima()
        anotar_anonima()
        r = s.get(BASE + destino, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code in (429, 401, 403):
        _marcar_bloqueo(destino)
        return None
    if r.status_code != 200:
        return None

    # Primero el bloque estructurado, que trae las cifras EXACTAS y además
    # el id, la privacidad y la biografía. La meta og:description redondea
    # —970 por 969— y con eso 'vigilar' no puede ver un cambio pequeño.
    d = perfil_de_la_pagina(r.text, username)
    if not d.get("seguidores") and not d.get("seguidos"):
        seguidores, seguidos, publicaciones = cifras_de_la_pagina(r.text)
        if not (seguidores or seguidos or publicaciones):
            # Ni bloque ni metas: lo que ha llegado es el muro de inicio
            # de sesión o una página vacía. No se devuelven ceros: serían
            # mentira, y dispararían las alarmas de desplome de la v3.3.
            return None
        d = {"seguidores": seguidores, "seguidos": seguidos,
             "publicaciones": publicaciones, "redondeado": True}

    d.setdefault("username", username)
    d.setdefault("publicaciones", 0)
    # `la_sigo` no se sabe sin sesión, y None es «no consta»: la regla de
    # siempre. Los totales sí son de fiar cuando vienen del bloque.
    d.update({"la_sigo": None, "via": "anonima",
              "totales_fiables": not d.get("redondeado")})
    return d


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

    # La meta og:description trae los tres números de golpe. El de
    # publicaciones estaba descrito aquí desde el principio y no se recogía:
    # ya venía en la cadena que este mismo re.search acaba de encontrar.
    # El bloque estructurado primero: trae las cifras EXACTAS. La meta
    # og:description redondea —970 por 969, 98 por 96— y esa diferencia
    # se veía en pantalla mientras la propia página de Instagram decía
    # otra cosa. Las metas quedan de respaldo.
    bloque = perfil_de_la_pagina(html, username)
    de_meta = cifras_de_la_pagina(html)
    # Campo a campo, no todo o nada: en la página mirada el bloque traía
    # seguidores y seguidos pero NO las publicaciones, y con «si falta
    # todo, usa las metas» salían 0 publicaciones teniendo 17 delante.
    seguidores, seguidos, publicaciones = (
        bloque.get(clave) if bloque.get(clave) is not None else de_meta[i]
        for i, clave in enumerate(("seguidores", "seguidos",
                                   "publicaciones")))
    # Solo se afirman fiables los que vinieron del bloque; los de la meta
    # están redondeados y quien decida sobre ellos tiene que saberlo.
    redondeado = bloque.get("seguidores") is None

    # El nombre sale de og:title, que es "Nombre (@usuario) • Instagram...".
    # De og:description también se podría, pero habría que cortar por "from"
    # o por "de", y un nombre como "Ana de la Cruz" se partiría por la mitad.
    # Aquí el paréntesis marca el final sin depender del idioma — y por eso
    # se exige: sin él no se sabe dónde acaba el nombre y empieza la
    # coletilla, así que es mejor no dar ninguno.
    nombre = ""
    titulo = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    if titulo:
        crudo = unescape(titulo.group(1))
        if "(@" in crudo:
            nombre = limpiar_nombre(crudo.split("(@")[0])
            if nombre.lstrip("@").lower() == username.lower():
                nombre = ""      # el título era el usuario: no hay nombre

    guardar_crudo_perfil(username, html, "html")

    privada = privada_en_html(html, uid, username)

    # La foto sale de la misma página, en la meta que usan las vistas previas
    # de enlaces. El &amp; hay que deshacerlo o la URL no vale: viene escapada
    # porque está dentro de un atributo HTML.
    foto = re.search(r'property="og:image"\s+content="([^"]+)"', html)
    return {
        "id": uid,
        "username": username,
        "nombre": nombre,
        "seguidores": seguidores,
        "seguidos": seguidos,
        "publicaciones": publicaciones,
        # El bloque lo dice sin ambigüedad; la heurística de ventana de
        # texto solo se usa si no hay bloque. Y si tampoco se puede atar,
        # queda None: «no consta», que no es «no».
        "privada": bloque.get("privada", privada),
        "verificada": bloque.get("verificada"),
        "biografia": bloque.get("biografia", ""),
        "totales_fiables": not redondeado,
        # Desde la página no se puede saber. None = "no consta", que NO es
        # lo mismo que False: así quien decida puede avisar en vez de dar
        # por hecho que sí la sigues.
        "la_sigo": None,
        "foto": bloque.get("foto") or (
            foto.group(1).replace("&amp;", "&") if foto else ""),
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
                "nombre": limpiar_nombre(u.get("full_name")),
                "seguidores": 0,
                "seguidos": 0,
                "publicaciones": 0,
                "privada": bool(u.get("is_private")),
                "la_sigo": None,
                "totales_fiables": False,   # el buscador no los trae
                "foto": u.get(campo("foto_perfil")) or "",
                "origen": "buscador (sin totales)",
            }
    raise NoEncontrado(f"el buscador no encontró '{username}'")


def ruta_estado(cuenta: str) -> Path:
    """Lo último que se supo de una cuenta."""
    return carpeta_cuenta(cuenta) / f"perfil_{cuenta}.json"


def leer_estado(cuenta: str) -> dict:
    """Lo guardado de esa cuenta. Cero peticiones y funciona sin red."""
    try:
        datos = json.loads(ruta_estado(cuenta).read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_estado(cuenta: str, p: dict) -> None:
    """
    Guarda lo que se acaba de saber de la cuenta, sin perder lo de antes.

    No es una captura ni una serie: es el estado de ahora, para que la
    ventana pueda enseñar el nombre y las publicaciones sin salir a la red.
    Todo esto ya venía en la respuesta del perfil, así que cuesta cero
    peticiones.

    **Se fusiona, no se pisa.** Las tres vías traen cantidades distintas: la
    API lo trae todo y la página del perfil no trae biografía. Si una
    lectura por la página sobrescribiera con vacío lo que trajo la API, se
    perdería un dato que ya se había pagado.
    """
    guardado = leer_estado(cuenta)
    for clave in ("username", "nombre", "publicaciones", "seguidores",
                  "seguidos", "biografia", "enlace", "categoria",
                  "verificada", "id", "pronombres", "memorial",
                  "desactivada", "threads"):
        valor = p.get(clave)
        if valor not in (None, "", 0):
            guardado[clave] = valor
    # `privada` es del momento y se pisa, pero SOLO si consta. Antes iba
    # `bool(p.get("privada"))`, que convertía «no se sabe» en «no»: el
    # mismo fallo que se arregló en la v9.1, aquí guardándolo en disco.
    if p.get("privada") is not None:
        guardado["privada"] = bool(p["privada"])
    guardado["visto"] = f"{datetime.now():%Y-%m-%d %H:%M}"
    try:
        carpeta_cuenta(cuenta).mkdir(parents=True, exist_ok=True)
        escribir_atomico(ruta_estado(cuenta), json.dumps(
            guardado, indent=2, ensure_ascii=False))
    except OSError:
        pass                    # es una comodidad, no una pieza


def guardar_crudo_perfil(cuenta: str, contenido: str, ext: str) -> Path | None:
    """
    Guarda la respuesta del perfil tal como llegó, una vez al día.

    Ya se ha descargado y se le han pasado cuatro expresiones regulares antes
    de tirarla. Guardarla no cuesta ninguna petición y convierte el
    «¿qué más se
    podría sacar de aquí?» en una pregunta que se contesta abriendo un
    archivo en vez de gastando otra.

    **Esto NO es como fallo_*.json.** Aquel está pensado para compartirse y
    hay prueba de que no lleva cookies. Este es la página entera pedida CON
    tu sesión, y puede llevar dentro datos de ella. Se queda en salida/, que
    está en .gitignore, y no se comparte.
    """
    if not contenido:
        return None
    destino = carpeta_cuenta(cuenta) / f"crudo_perfil_{cuenta}.{ext}"
    try:
        # Una al día basta: la página cambia poco y ocupa un par de megas.
        if destino.exists():
            guardada = datetime.fromtimestamp(destino.stat().st_mtime).date()
            if guardada == date.today():
                return destino
        carpeta_cuenta(cuenta).mkdir(parents=True, exist_ok=True)
        # La página de Instagram lleva un csrf_token dentro —comprobado en
        # una página REAL, y eso era sin sesión—. Se guarda para poder
        # mirar la respuesta sin gastar peticiones, y sin el token sirve
        # igual: nadie necesita el secreto para ver la estructura.
        escribir_atomico(destino, registro.limpiar_secretos(contenido))
        print(f"  (respuesta del perfil guardada en {destino.name}; "
              "no la compartas, lleva tu sesión dentro)")
        return destino
    except OSError:
        return None                 # es un extra; nunca puede tumbar nada


def ruta_foto(cuenta: str) -> Path:
    """Dónde se guarda la foto de perfil de una cuenta."""
    return carpeta_cuenta(cuenta) / f"foto_{cuenta}.jpg"


def foto_al_dia(cuenta: str, dias: int = DIAS_FOTO) -> bool:
    """¿Hay copia guardada y reciente, como para no volver a bajarla?"""
    archivo = ruta_foto(cuenta)
    try:
        if archivo.stat().st_size == 0:
            return False
        return (time.time() - archivo.stat().st_mtime) < dias * 86400
    except OSError:
        return False


def guardar_foto(s: requests.Session, cuenta: str, url: str) -> Path | None:
    """
    Guarda la foto del perfil en salida/foto_<cuenta>.jpg.

    NO es una petición a la API y no entra en el presupuesto: va al CDN de
    imágenes, que es otra infraestructura y no es lo que devuelve los 429.
    Es exactamente el archivo que tu navegador baja al abrir el perfil.

    Las cookies no viajan ahí: son del dominio instagram.com y esto es
    cdninstagram.com, así que requests no las manda. Sale gratis y conviene
    que sea así.

    Es decoración. Falla en silencio, no se reintenta nunca y devuelve None:
    insistir por una foto sería gastar riesgo en lo único que no es un dato.
    """
    if not url or not str(url).lower().startswith("https://"):
        return None
    try:
        r = s.get(url, timeout=15,
                  headers={"Accept": "image/*", "Sec-Fetch-Dest": "image"})
        cuerpo = r.content if r.status_code == 200 else b""
    except (requests.RequestException, OSError):
        return None

    # Que sea una imagen de verdad y de un tamaño razonable. Si Instagram
    # contesta con una página de error, escribirla como .jpg dejaría un
    # archivo roto que luego hay que explicar.
    if not cuerpo or len(cuerpo) > 4_000_000:
        return None
    if not (cuerpo[:2] == b"\xff\xd8" or cuerpo[:8].startswith(b"\x89PNG")):
        return None

    try:
        carpeta_cuenta(cuenta).mkdir(parents=True, exist_ok=True)
        destino = ruta_foto(cuenta)
        # Antes de pisarla: si la de antes era otra, se guarda con su
        # fecha. Una foto de perfil cambiada no se puede volver a
        # descargar —Instagram deja de servirla— y este proyecto guarda
        # justo lo que no se recupera. Ocupan unos pocos KB y no cuestan
        # ni una petición: la descarga ya se ha hecho.
        anterior = destino.read_bytes() if destino.exists() else b""
        if anterior and anterior != cuerpo:
            # Se compara por CONTENIDO, no por URL: el CDN cambia la URL
            # continuamente sirviendo la misma imagen, y comparar enlaces
            # daría un «cambió de foto» cada semana.
            archivo = destino.with_name(
                f"foto_{cuenta}_{date.today():%Y-%m-%d}.jpg")
            if not archivo.exists():
                escribir_atomico(archivo, anterior)
            # Un cambio de foto es una señal, no decoración: una cuenta
            # que cambia de imagen puede haber cambiado de manos. Se anota
            # aparte y NO por guardar_estado(), que solo acepta una lista
            # fija de claves y se habría comido esta sin decir nada.
            with contextlib.suppress(Exception):
                estado = leer_estado(cuenta)
                estado["foto_cambio"] = f"{date.today()}"
                estado["fotos"] = len(list(destino.parent.glob(
                    f"foto_{cuenta}_*.jpg"))) + 1
                escribir_atomico(ruta_estado(cuenta), json.dumps(
                    estado, indent=2, ensure_ascii=False))
        escribir_atomico(destino, cuerpo)
        return destino
    except OSError:
        return None


def fotos_guardadas(cuenta: str) -> list:
    """
    Las fotos de perfil que se conservan, de la más vieja a la actual.

    La última es `foto_<cuenta>.jpg`, la de ahora; las demás llevan la
    fecha en la que dejaron de estar puestas.
    """
    carpeta = carpeta_cuenta(cuenta)
    if not carpeta.is_dir():
        return []
    viejas = sorted(carpeta.glob(f"foto_{cuenta}_*.jpg"))
    actual = ruta_foto(cuenta)
    return viejas + ([actual] if actual.exists() else [])


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
        recordar_id(username, p.get("id"))
        if nombre != "web_profile_info":
            print(f"  (datos obtenidos por {nombre})")
        # La foto se refresca aquí y no en cada comando: es el único sitio
        # que conoce la URL, y así 'contar', 'bajar' y 'vigilar' la mantienen
        # al día sin que ninguno tenga que acordarse. Solo si la guardada ya
        # tiene sus días: una cara no cambia todas las semanas.
        if not foto_al_dia(username):
            antes = leer_estado(username).get("foto_cambio")
            guardar_foto(s, username, p.get("foto", ""))
            if leer_estado(username).get("foto_cambio") != antes:
                print("  La foto de perfil ha cambiado. La anterior queda "
                      "guardada con su fecha.")
        # Y por lo mismo, aquí se anota lo que se acaba de saber: el nombre y
        # las publicaciones venían en la misma respuesta y antes se tiraban.
        guardar_estado(username, p)
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
    guardar_crudo_perfil(username, json.dumps(d, indent=2,
                                              ensure_ascii=False), "json")
    u = _buscar(d, campo("perfil_raiz"))

    # Los totales solo se dan por fiables si de verdad llegaron. Antes se
    # marcaban fiables siempre, así que un cambio de nombre en esos campos
    # habría reportado 0 seguidores como dato bueno.
    seguidores = _buscar(u, campo("seguidores_total"))
    seguidos = _buscar(u, campo("seguidos_total"))
    fiables = isinstance(seguidores, int) and isinstance(seguidos, int)

    publicaciones = _buscar(u, campo("publicaciones_total"))
    if not isinstance(publicaciones, int):
        publicaciones = 0

    return {
        "id": str(u[campo("identificador_alt")]),
        "username": u[campo("nombre_usuario")],
        "nombre": limpiar_nombre(u.get("full_name")),
        "seguidores": seguidores if fiables else 0,
        "seguidos": seguidos if fiables else 0,
        "publicaciones": publicaciones,
        "privada": bool(u.get("is_private")),
        "la_sigo": bool(u.get("followed_by_viewer")),
        "totales_fiables": fiables,
        # La foto venía ya dentro de esta misma respuesta. Cuesta cero
        # peticiones y no entra en ningún contrato: si un día no llega, no
        # pasa nada — es lo único del programa que no es un dato.
        "foto": (u.get(campo("foto_perfil_hd"))
                 or u.get(campo("foto_perfil")) or ""),
        "origen": "web_profile_info",
    }


# ======================================================================
# ARCHIVOS
# ======================================================================

# Cada cuenta tiene su carpeta, «usuario - id». Antes todo caía junto en
# salida/ y con cinco objetivos seguidos eran cientos de archivos mezclados
# cuyo único orden era el prefijo del nombre.
#
# El id solo se sabe leyendo el perfil, y las órdenes de análisis no leen
# ninguno — es la garantía de que funcionan sin red. Así que la carpeta se
# encuentra también sin él: por su propio nombre, que ya lo lleva dentro.
_IDS: dict = {}                  # cuenta -> id numérico, en esta ejecución
_RECOLOCADAS: set = set()        # cuentas ya recogidas de la raíz

# Lo que pertenece a una cuenta. Los nombres de archivo NO cambian: siguen
# llevando la cuenta dentro, así que un CSV que se saque de su carpeta se
# sigue explicando solo, y todo lo que ya sabía leerlos sigue igual.
PATRONES_DE_CUENTA = (
    "{c}_seguidores_*", "{c}_seguidos_*",
    ".{c}_seguidores_*", ".{c}_seguidos_*",     # los .meta.json van ocultos
    ".estado_{c}_*.json", "perfil_{c}.json", "foto_{c}.jpg",
    "totales_{c}.csv", "vigilancia_{c}.log", "vigilancia_{c}.txt",
    "cambios_{c}_*.csv", "relaciones_{c}.csv",
    "historial_seguidores_{c}.csv", "historial_seguidos_{c}.csv",
    "detalles_{c}_*.csv", "crudo_{c}_*.json",
)


def _dir_existente(cuenta: str) -> Path | None:
    """La carpeta de esa cuenta si ya está creada, lleve el id o no."""
    try:
        for hijo in CARPETA.iterdir():
            if hijo.is_dir() and hijo.name.split(" - ")[0] == cuenta:
                return hijo
    except OSError:
        pass
    return None


def _ruta_carpeta(cuenta: str) -> Path:
    """La carpeta que le toca, sin mover nada."""
    existente = _dir_existente(cuenta)
    if existente:
        return existente
    identificador = _IDS.get(cuenta)
    return CARPETA / (f"{cuenta} - {identificador}" if identificador
                      else cuenta)


def recordar_id(cuenta: str, identificador) -> None:
    """
    Anota el id de una cuenta y, si su carpeta no lo llevaba, la renombra.

    Pasa cuando había datos de antes de que existieran las carpetas: se
    recogen antes de saber el id, y el nombre se completa en cuanto el
    primer perfil lo dice.
    """
    identificador = str(identificador or "").strip()
    if not identificador or not cuenta:
        return
    _IDS[cuenta] = identificador
    actual = _dir_existente(cuenta)
    destino = CARPETA / f"{cuenta} - {identificador}"
    if actual and actual != destino and not destino.exists():
        try:
            actual.rename(destino)
        except OSError:
            pass                 # con la carpeta abierta en el explorador


def _recolocar(cuenta: str) -> None:
    """
    Recoge en su carpeta los archivos sueltos de una cuenta, una sola vez.

    Se hace también al LEER, y no solo al escribir: si no, quien abriera la
    ventana con datos de antes vería «sin capturas» hasta la siguiente
    descarga, con sus archivos ahí al lado.
    """
    if not cuenta or cuenta in _RECOLOCADAS:
        return
    _RECOLOCADAS.add(cuenta)

    sueltos = []
    for patron in PATRONES_DE_CUENTA:
        sueltos += [r for r in CARPETA.glob(patron.format(c=cuenta))
                    if r.is_file()]
    if not sueltos:
        return

    # Si entre lo suelto está el perfil, el id sale de ahí y la carpeta nace
    # ya con su nombre definitivo en vez de renombrarse después.
    if cuenta not in _IDS:
        try:
            datos = json.loads((CARPETA / f"perfil_{cuenta}.json")
                               .read_text(encoding="utf-8"))
            if datos.get("id"):
                _IDS[cuenta] = str(datos["id"])
        except (OSError, ValueError, AttributeError):
            pass

    destino = _ruta_carpeta(cuenta)
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for ruta in sueltos:
        try:
            # Si ya hay uno con ese nombre dentro, manda el de dentro: es el
            # nuevo. Mover encima borraría lo que ya se había recolocado.
            if not (destino / ruta.name).exists():
                ruta.rename(destino / ruta.name)
        except OSError:
            pass


def carpeta_cuenta(cuenta: str | None = None) -> Path:
    """La carpeta de una cuenta, ya recogida. Cero peticiones."""
    cuenta = cuenta or OBJETIVO
    _recolocar(cuenta)
    return _ruta_carpeta(cuenta)


def _ruta_parcial(tipo: str) -> Path:
    return carpeta_cuenta() / f"{OBJETIVO}_{tipo}_parcial.csv"


def _ruta_estado(tipo: str) -> Path:
    return carpeta_cuenta() / f".estado_{OBJETIVO}_{tipo}.json"


def _ruta_captura(tipo: str, dia: str | None = None) -> Path:
    dia = dia or f"{date.today():%Y-%m-%d}"
    return carpeta_cuenta() / f"{OBJETIVO}_{tipo}_{dia}.csv"


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


def escribir_atomico(ruta: Path, contenido, encoding: str = "utf-8",
                     durable: bool = True, saltos=None) -> None:
    """
    Escribe al lado y renombra de golpe: o está lo viejo, o está lo nuevo.

    Nunca queda un archivo a medias. Un `open(ruta, "w")` trunca el archivo
    ANTES de escribir, así que un corte a mitad de una lista de 2.500 deja
    la captura cortada y con pinta de buena. Y quien la lea no tiene forma
    de saberlo.

    `durable` añade un `fsync` antes de renombrar. Sin él esto sobrevive a
    que el programa se caiga, pero no a que se vaya la luz. Se desactiva
    solo donde se escribe muchas veces por segundo, que es el contador de
    peticiones, y ahí no hay nada irrecuperable.

    (No se sincroniza la carpeta, que haría falta para que el propio
    renombrado sobreviva a un apagón. Sin eso lo que se pierde es la
    ACTUALIZACIÓN, no el archivo: queda el de antes, entero. Y en Windows
    no se puede abrir una carpeta para sincronizarla.)

    El temporal lleva el número del proceso porque **la ventana y la tarea
    programada corren a la vez**. Con un nombre fijo, los dos escriben el
    mismo temporal y uno acaba renombrando el archivo a medias del otro:
    exactamente el problema que el contador de peticiones ya tuvo y que
    resolvió con cerrojo.

    Y va en la MISMA carpeta a propósito: `os.replace` solo es atómico
    dentro del mismo sistema de archivos.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
    binario = isinstance(contenido, (bytes, bytearray))
    try:
        if binario:
            with open(temporal, "wb") as f:
                f.write(contenido)
                if durable:
                    f.flush()
                    os.fsync(f.fileno())
        else:
            # saltos=None deja que el sistema traduzca los saltos de línea,
            # que es lo que hacía write_text: en Windows los .txt que se
            # editan a mano deben quedar con CRLF. El CSV pasa "" porque el
            # módulo csv ya escribe \r\n y traducir daría \r\r\n.
            with open(temporal, "w", encoding=encoding, newline=saltos) as f:
                f.write(contenido)
                if durable:
                    f.flush()
                    os.fsync(f.fileno())
        os.replace(temporal, ruta)
    except OSError:
        # Sin esto, un disco lleno deja un .tmp por cada intento fallido.
        with contextlib.suppress(OSError):
            temporal.unlink()
        raise


def _escribir_csv(ruta: Path, cabecera: list, filas: list) -> None:
    """
    Escribe un CSV completo con BOM, para que Excel respete los acentos.

    Se arma entero en memoria y se vuelca de una vez: una captura de 2.500
    personas son unos 200 KB, y a cambio deja de existir el estado
    intermedio en el que el archivo está a medias.
    """
    memoria = io.StringIO(newline="")
    w = csv.writer(memoria)
    w.writerow(cabecera)
    w.writerows(filas)
    escribir_atomico(ruta, memoria.getvalue(),
                     encoding="utf-8-sig", saltos="")


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
    # También aquí: son las 2.500 filas del CSV, y un espacio al final
    # descoloca cualquier columna que Excel intente alinear.
    fila = {"username": u.get("username", ""),
            "nombre": limpiar_nombre(u.get("full_name")),
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
    carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    escribir_atomico(_ruta_estado(tipo), json.dumps(
        {"cursor": cursor, "pagina": pagina, "total_esperado": total,
         "actualizado": datetime.now().isoformat(timespec="seconds")},
        indent=2))


def huella_de_captura(ruta: Path) -> str:
    """
    Huella SHA-256 de lo que Instagram dijo en esa captura.

    Se sella lo OBSERVADO, no el archivo: las columnas de CAMPOS_CRUZADOS
    las calcula este programa a partir de las dos listas, y se rellenan
    después. Sellar los bytes haría que rellenar un dato derivado
    pareciera una manipulación, y entonces la alarma sonaría tanto que
    nadie la miraría.

    Las filas se ordenan antes de sellar, así que volver a guardar la
    misma captura en otro orden da la misma huella. Cambiar quién estaba,
    o cualquier dato que vino de Instagram, la cambia.
    """
    filas = _leer_csv(ruta)
    if not filas:
        return ""
    campos = sorted({c for f in filas for c in f} - set(CAMPOS_CRUZADOS))
    lineas = [",".join(campos)]
    for f in sorted(filas, key=lambda x: (str(x.get("id") or ""),
                                          str(x.get("username") or ""))):
        lineas.append("\x1f".join(str(f.get(c, "") or "") for c in campos))
    return hashlib.sha256("\x1e".join(lineas).encode("utf-8")).hexdigest()


def _eslabon(huella: str, anterior: str) -> str:
    """Encadena una huella con la de la captura anterior."""
    return hashlib.sha256(f"{anterior}:{huella}".encode("utf-8")).hexdigest()


def sellar(captura: Path) -> dict:
    """
    Sella una captura con su huella y la encadena a la anterior.

    Encadenar es lo que hace que no se pueda cambiar una captura vieja y
    dejarlo todo cuadrado: cada eslabón depende del anterior, así que
    tocar la de agosto invalida septiembre, octubre y todo lo que venga.
    """
    tipo = "seguidores" if "_seguidores_" in captura.name else "seguidos"
    previas = [r for r in _capturas(tipo) if _fecha_de(r) < _fecha_de(captura)]
    anterior = (_leer_meta(previas[-1]).get("cadena", "") if previas else "")
    huella = huella_de_captura(captura)
    return {"huella": huella, "anterior": anterior,
            "cadena": _eslabon(huella, anterior),
            "sellada": datetime.now().isoformat(timespec="seconds")}


def resellar(captura: Path, motivo: str) -> None:
    """
    Vuelve a sellar una captura que el propio programa ha reescrito.

    Solo pasa al cruzar las listas, que rellena columnas calculadas. Como
    la huella cubre únicamente lo observado, la huella NO debería cambiar;
    si cambia, se anota y se ve al verificar. Un reselle silencioso sería
    una puerta abierta del tamaño de la casa.
    """
    meta = _leer_meta(captura)
    nueva = huella_de_captura(captura)
    if not meta.get("huella"):
        return                      # nunca estuvo sellada; no se inventa
    if nueva == meta["huella"]:
        return                      # lo esperado: no cambió lo observado
    historial = meta.get("reescrituras") or []
    historial.append({"cuando": datetime.now().isoformat(timespec="seconds"),
                      "motivo": motivo, "antes": meta["huella"][:16],
                      "ahora": nueva[:16]})
    meta.update({"huella": nueva,
                 "cadena": _eslabon(nueva, meta.get("anterior", "")),
                 "reescrituras": historial})
    escribir_atomico(_ruta_meta(captura),
                     json.dumps(meta, indent=2, ensure_ascii=False))


def verificar_cadena(tipo: str) -> dict:
    """
    Recorre las capturas y comprueba que ninguna cambió. 0 peticiones.

    Devuelve {"bien", "rotas", "descolocadas", "sin_sellar", "cabeza"}.

    "rotas" es contenido que cambió. "descolocadas" es contenido intacto
    cuyo eslabón no encaja, y eso tiene dos causas que esto no distingue:
    una restauración que rellena un hueco, o una captura anterior
    reescrita y resellada. Se separan de "rotas" porque los datos de esa
    captura están enteros; quién lo mira sabe si restauró algo.

    Lo que esto demuestra, y lo que no
    ----------------------------------
    Detecta que una captura se editó, se corrompió o desapareció, y que
    alguien intentó cambiar una vieja sin rehacer las siguientes.

    NO demuestra nada frente a quien pueda escribir en la carpeta y sepa
    cómo funciona esto: puede reescribir la captura, su sello y todos los
    eslabones siguientes. Para eso hace falta que **la cabeza esté
    guardada en un sitio al que esa persona no llegue** — apuntada en otro
    equipo, mandada por correo, subida a un repositorio. Por eso el
    comando la imprime en vez de dejarla solo en un archivo.
    """
    bien, rotas, descolocadas, sin_sellar = [], [], [], []
    anterior = ""        # lo que dicen los sellos guardados
    real = ""            # lo que sale de RECALCULAR sobre los archivos
    for ruta in _capturas(tipo):
        fecha = _fecha_de(ruta)
        meta = _leer_meta(ruta)
        ahora = huella_de_captura(ruta)
        # La cabeza se recalcula SIEMPRE, mirando los archivos, y nunca se
        # copia del último sello. Era el fallo de la primera versión:
        # editar una captura vieja y volver a sellarla dejaba la cabeza
        # idéntica, así que guardarla fuera no servía de nada. Ahora
        # cualquier cambio, en cualquier captura, la mueve.
        real = _eslabon(ahora, real)

        if not meta.get("huella"):
            # De antes de los sellos. No consta que esté mal: consta que
            # no se selló. Es la misma regla que «sin metadatos no es
            # incompleta».
            sin_sellar.append(fecha)
            anterior = meta.get("cadena", anterior)
            continue
        esperado = _eslabon(meta["huella"], meta.get("anterior", ""))
        if ahora != meta["huella"]:
            rotas.append((fecha, "el contenido no coincide con su sello"))
        elif meta.get("anterior", "") != anterior:
            # Su contenido está INTACTO; lo que no cuadra es con lo de
            # antes. Dos cosas dan esta misma señal y la cadena NO puede
            # distinguirlas: restaurar una copia que rellena un hueco, y
            # que alguien reescribiera una captura anterior y la volviera
            # a sellar. Se separa de «rota» porque los datos de ESTA están
            # enteros, y quien mira sabe si restauró algo o no.
            descolocadas.append(fecha)
        elif meta.get("cadena") != esperado:
            rotas.append((fecha, "el sello está mal formado"))
        else:
            bien.append(fecha)
        anterior = meta.get("cadena", "")
    return {"bien": bien, "rotas": rotas, "descolocadas": descolocadas,
            "sin_sellar": sin_sellar, "cabeza": real}


def _escribir_meta(captura: Path, completa: bool, esperados: int,
                   obtenidos: int, motivo: str) -> None:
    captura.parent.mkdir(parents=True, exist_ok=True)
    datos = {"completa": completa, "esperados": esperados,
             "obtenidos": obtenidos, "motivo": motivo,
             "cerrada": datetime.now().isoformat(timespec="seconds")}
    # El sello va aquí porque es el único sitio por el que pasa una
    # captura al cerrarse, venga de una descarga o de una reanudación.
    with contextlib.suppress(Exception):
        datos.update(sellar(captura))
    escribir_atomico(_ruta_meta(captura),
                     json.dumps(datos, indent=2, ensure_ascii=False))


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

def medir_pagina(s: requests.Session, uid: str, tipo: str,
                 tamanos: list) -> list:
    """
    Cuánta gente devuelve Instagram por cada tamaño de página pedido.

    Una petición por tamaño, y PARA en cuanto encuentra el tope: si pides
    100 y llegan 50, pedir 200 ya no aporta nada y sería una petición rara
    a cambio de nada.

    No guarda ninguna captura ni toca el progreso de una descarga a medias:
    es una medición, no una descarga. Cada página se pide desde el
    principio, sin cursor.

    Devuelve [(pedido, llegaron, cortado)] en el orden en que se probó.
    """
    clave_ruta = ("lista_seguidores" if tipo == "seguidores"
                  else "lista_seguidos")
    fuera = []
    for pedido in tamanos:
        d = validar("lista", pedir(s, ruta(clave_ruta, id=uid),
                                   {param("cantidad"): pedido}),
                    ruta(clave_ruta, id=uid))
        llegaron = len(d.get(campo("usuarios")) or [])
        cortado = llegaron < pedido
        fuera.append((pedido, llegaron, cortado))
        if cortado:
            # El servidor ha puesto su tope. Seguir subiendo solo añade
            # peticiones con una forma que no usa ningún navegador.
            break
    return fuera


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
    # Cursores ya usados. Uno repetido significa que la paginación se ha
    # quedado enganchada, y el freno de páginas vacías no sirve para eso:
    # vienen LLENAS, con la misma gente.
    vistos_cursores = {cursor} if cursor else set()
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

            # Un cursor repetido es una página repetida, y giraría para
            # siempre gastando presupuesto. No se ha visto pasar; se corta
            # porque el coste de equivocarse es el día entero.
            if cursor and cursor in vistos_cursores:
                _escribir_estado(tipo, "", pagina, total)
                raise RespuestaInesperada(
                    "Instagram ha devuelto un cursor que ya se había usado "
                    f"(página {pagina}).\n    Se corta para no dar vueltas: "
                    "lo bajado se conserva y la próxima vez sigue desde ahí.")
            if cursor:
                vistos_cursores.add(cursor)
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
        print("  Vuelve a descargar las listas en unas horas: se fusiona "
              "con esta.")
    return destino


def descargar(s: requests.Session, p: dict, tipo: str) -> None:
    """Descarga una lista con reintentos y espera creciente."""
    total = p["seguidores"] if tipo == "seguidores" else p["seguidos"]
    fiable = p.get("totales_fiables", True)
    print(f"\n{tipo.upper()}  (esperados: {total})")

    # La carpeta de la cuenta, no solo salida/: el CSV parcial se abre en
    # modo añadir y sin ella no hay dónde escribir la primera página.
    carpeta_cuenta().mkdir(parents=True, exist_ok=True)
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
          "vuelve a descargar más tarde y seguirá desde ahí.")


# ======================================================================
# COMPARACIÓN
# ======================================================================

def _capturas(tipo: str) -> list[Path]:
    """Capturas fechadas, de la más antigua a la más reciente."""
    patron = f"{OBJETIVO}_{tipo}_"
    encontradas = []
    for ruta in carpeta_cuenta().glob(f"{patron}*.csv"):
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


def cruzar_dos(a: dict, b: dict) -> dict:
    """
    Qué hay en común entre dos listas. Función pura: dos índices -> tres.

    Vigilar varias cuentas y no poder cruzarlas deja sin responder lo que
    justifica vigilarlas: quién te sigue a ti y no a la otra, a quién
    llegáis los dos, y quién se fue de una y apareció en la otra.

    Cruza por CLAVE, que es el id cuando lo hay. Cruzar por nombre de
    usuario haría que un cambio de nombre pareciera dos personas
    distintas, que es el error que este proyecto arrastró hasta la v3.1.
    """
    solo_a = sorted(set(a) - set(b), key=lambda c: a[c]["username"].lower())
    solo_b = sorted(set(b) - set(a), key=lambda c: b[c]["username"].lower())
    ambas = sorted(set(a) & set(b), key=lambda c: a[c]["username"].lower())
    return {"solo_a": solo_a, "solo_b": solo_b, "ambas": ambas}


def _capturas_de_cuenta(cuenta: str) -> list:
    """Las capturas de otra cuenta, sin cambiar la que está en curso."""
    with con_cuenta(cuenta):
        return _capturas("seguidores") + _capturas("seguidos")


def ultima_utilizable(tipo: str, forzar: bool = False) -> tuple:
    """
    La captura más reciente que se puede usar, y por qué si no la hay.

    Una truncada produciría cientos de diferencias falsas al cruzar, igual
    que al comparar. Se aplica el mismo criterio, que ya estaba escrito.
    """
    archivos = _capturas(tipo)
    if not archivos:
        return None, "no hay ninguna captura"
    ruta = archivos[-1]
    meta = _leer_meta(ruta)
    if meta.get("completa") is False and not forzar:
        return None, (f"la última ({_fecha_de(ruta)}) está incompleta: "
                      f"{meta.get('motivo', '?')}")
    return ruta, ""


def comun(cuenta_a: str, cuenta_b: str, tipo: str = "seguidores",
          forzar: bool = False) -> dict | None:
    """Cruza la misma lista de dos cuentas. 0 peticiones."""
    datos = {}
    for etiqueta, cuenta in (("a", cuenta_a), ("b", cuenta_b)):
        with con_cuenta(cuenta):
            ruta, motivo = ultima_utilizable(tipo, forzar)
            if ruta is None:
                print(f"\n@{cuenta}: {motivo}.")
                return None
            indice, con_id = _indexar(ruta)
            datos[etiqueta] = {"cuenta": cuenta, "ruta": ruta,
                               "indice": indice, "con_id": con_id,
                               "fecha": _fecha_de(ruta)}

    a, b = datos["a"], datos["b"]
    print(f"\n{tipo.upper()} EN COMÚN   @{a['cuenta']} ({a['fecha']}, "
          f"{len(a['indice'])})  x  @{b['cuenta']} ({b['fecha']}, "
          f"{len(b['indice'])})")

    dias = abs(dias_desde(a["fecha"], date.fromisoformat(b["fecha"])))
    if dias > MAX_DIAS_SIN_BAJAR:
        # Cruzar la foto de agosto de una con la de septiembre de la otra
        # da diferencias que son del calendario, no de las cuentas.
        print(f"  ATENCIÓN: las capturas se llevan {plural(dias, 'día')}. "
              "Parte de lo que salga")
        print("  será de esa distancia y no de las cuentas. Baja las dos el "
              "mismo día para un cruce limpio.")
    if not (a["con_id"] and b["con_id"]):
        print("  Nota: alguna captura no guarda ids; se cruza por nombre de "
              "usuario, así que un cambio de nombre parecerá otra persona.")

    r = cruzar_dos(a["indice"], b["indice"])
    total = len(set(a["indice"]) | set(b["indice"]))
    print(f"  En las dos: {len(r['ambas'])}    "
          f"Solo @{a['cuenta']}: {len(r['solo_a'])}    "
          f"Solo @{b['cuenta']}: {len(r['solo_b'])}")
    if total:
        print(f"  Solapamiento: {len(r['ambas']) * 100 // total}% de las "
              f"{total} personas distintas entre las dos.")

    for titulo, claves, fuente in (
            ("EN LAS DOS", r["ambas"], a["indice"]),
            (f"SOLO @{a['cuenta']}", r["solo_a"], a["indice"]),
            (f"SOLO @{b['cuenta']}", r["solo_b"], b["indice"])):
        if not claves:
            continue
        print(f"\n  {titulo}: {len(claves)}")
        for clave in claves[:MAX_LISTADO]:
            print(f"    {fuente[clave]['username']}")
        if len(claves) > MAX_LISTADO:
            print(f"    ... y {len(claves) - MAX_LISTADO} más "
                  "(están todas en el CSV)")

    destino = (carpeta_cuenta(cuenta_a)
               / f"comun_{cuenta_a}_{cuenta_b}_{tipo}_{a['fecha']}.csv")
    filas = ([["en las dos", a["indice"][c]["username"], c]
              for c in r["ambas"]]
             + [[f"solo {cuenta_a}", a["indice"][c]["username"], c]
                for c in r["solo_a"]]
             + [[f"solo {cuenta_b}", b["indice"][c]["username"], c]
                for c in r["solo_b"]])
    # La columna se llama 'username' y no 'usuario' a propósito: es la
    # convención de todos los CSV del proyecto, y _leer_csv descarta las
    # filas que no la llevan. Un CSV que el propio programa no sabe leer
    # no sirve de mucho.
    _escribir_csv(destino, ["donde", "username", "clave"], filas)
    print(f"\n  Guardado: {destino.name}")
    return r


def construir_grafo(cuentas: list, tipo: str = "seguidores",
                    forzar: bool = False) -> dict:
    """
    El grafo de quién aparece en el círculo de qué cuentas. 0 peticiones.

    QUÉ GRAFO ES ESTE, que importa más que el formato
    -------------------------------------------------
    Es **bipartito**: hay aristas entre tus cuentas objetivo y las
    personas, y **ninguna entre personas**. No se sabe quién sigue a quién
    dentro de ese grupo, porque eso serían las listas de cada una de esas
    miles de personas: decenas de miles de peticiones y la cuenta cerrada
    antes de la mitad.

    Así que sirve para lo que sirve un grafo bipartito: solapamiento de
    audiencias, quién aparece en varias a la vez, qué cuentas se parecen
    entre sí. NO sirve para detectar comunidades dentro de tus seguidores
    ni para medir intermediación entre ellos, aunque Gephi calcule esos
    números igual — los calcularía sobre aristas que no existen.
    """
    nodos, aristas, fuera, sin_id = {}, [], [], []
    for cuenta in cuentas:
        with con_cuenta(cuenta):
            ruta, motivo = ultima_utilizable(tipo, forzar)
            if ruta is None:
                fuera.append((cuenta, motivo))
                continue
            indice, con_id = _indexar(ruta)
            fecha = _fecha_de(ruta)
        if not con_id:
            # Sin ids, la clave es el nombre de usuario. Si OTRA cuenta sí
            # los tiene, la misma persona sale con dos claves: dos nodos
            # distintos, los dos con en_cuantas=1. O sea que el grafo
            # mentiría justo en lo que se le pregunta — quién hace de
            # puente.
            sin_id.append(cuenta)

        clave_obj = f"cuenta:{cuenta}"
        nodos[clave_obj] = {"etiqueta": cuenta, "clase": "objetivo",
                            "fecha": fecha, "en_cuantas": 0}
        for clave, quien in indice.items():
            nodo = nodos.setdefault(f"persona:{clave}", {
                "etiqueta": quien.get("username", clave),
                "clase": "persona", "fecha": "", "en_cuantas": 0})
            nodo["en_cuantas"] += 1
            # El sentido importa: en 'seguidores' la persona apunta a la
            # cuenta; en 'seguidos', al revés. Un grafo dirigido con las
            # flechas al azar no dice nada.
            aristas.append((f"persona:{clave}", clave_obj)
                           if tipo == "seguidores"
                           else (clave_obj, f"persona:{clave}"))
    # Mezclar capturas con ids y sin ellos parte a la misma persona en dos.
    # Se mira si de verdad hay mezcla: con TODAS sin ids el grafo es
    # coherente, solo frágil ante los cambios de nombre.
    mezcla = sin_id and len(sin_id) < len([c for c in cuentas
                                           if c not in dict(fuera)])
    return {"nodos": nodos, "aristas": aristas, "fuera": fuera, "tipo": tipo,
            "sin_id": sin_id, "mezcla_de_claves": bool(mezcla)}


def a_graphml(grafo: dict) -> str:
    """El grafo en GraphML, que es lo que abre Gephi. Función pura."""
    def escapar(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
              '  <key id="etiqueta" for="node" attr.name="label" '
              'attr.type="string"/>',
              '  <key id="clase" for="node" attr.name="clase" '
              'attr.type="string"/>',
              '  <key id="en_cuantas" for="node" attr.name="en_cuantas" '
              'attr.type="int"/>',
              '  <key id="fecha" for="node" attr.name="fecha" '
              'attr.type="string"/>',
              '  <graph id="FocusMedia" edgedefault="directed">']
    for clave, d in grafo["nodos"].items():
        partes.append(f'    <node id="{escapar(clave)}">')
        partes.append(f'      <data key="etiqueta">'
                      f'{escapar(d["etiqueta"])}</data>')
        partes.append(f'      <data key="clase">{escapar(d["clase"])}</data>')
        partes.append(f'      <data key="en_cuantas">{d["en_cuantas"]}</data>')
        partes.append(f'      <data key="fecha">{escapar(d["fecha"])}</data>')
        partes.append('    </node>')
    for i, (origen, destino) in enumerate(grafo["aristas"]):
        partes.append(f'    <edge id="e{i}" source="{escapar(origen)}" '
                      f'target="{escapar(destino)}"/>')
    partes.append('  </graph>')
    partes.append('</graphml>')
    return "\n".join(partes) + "\n"


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


def elegir_capturas(fechas: list, desde=None, hasta=None) -> tuple:
    """
    Qué dos capturas comparar. Función pura: (fechas, desde, hasta) -> par.

    Hasta aquí solo se podían comparar **las dos últimas**. Con meses de
    historial guardado, eso deja sin responder la pregunta que uno quiere
    hacerle: «¿qué pasó en agosto?», «¿quién se fue entre el 1 y el 15?».

    Devuelve (antes, ahora, avisos). Las reglas:

    - sin nada         las dos últimas, como siempre
    - solo `desde`     de ahí hasta la última
    - solo `hasta`     qué cambió ESE día: la anterior contra ella
    - las dos          justo esas

    Una fecha pedida casi nunca cae en un día con captura, así que se
    resuelve a la más cercana **hacia atrás** —«cómo estaba el 1 de
    agosto» es la última foto tomada hasta entonces— y se dice cuál se
    usó. Elegir por el usuario está bien; hacerlo en silencio, no.
    """
    fechas = sorted(fechas)
    avisos = []
    if len(fechas) < 2:
        return None, (fechas[-1] if fechas else None), avisos

    def resolver(pedida, etiqueta):
        if pedida in fechas:
            return pedida
        antes = [f for f in fechas if f <= pedida]
        if antes:
            avisos.append(f"no hay captura del {pedida}; para «{etiqueta}» "
                          f"se usa la del {antes[-1]}")
            return antes[-1]
        avisos.append(f"no hay ninguna captura del {pedida} ni anterior; "
                      f"para «{etiqueta}» se usa la primera, del {fechas[0]}")
        return fechas[0]

    if desde and hasta:
        a, b = resolver(desde, "desde"), resolver(hasta, "hasta")
    elif desde:
        a, b = resolver(desde, "desde"), fechas[-1]
    elif hasta:
        b = resolver(hasta, "hasta")
        previas = [f for f in fechas if f < b]
        a = previas[-1] if previas else None
    else:
        a, b = fechas[-2], fechas[-1]

    if a and b and a > b:
        # Se ponen en orden en vez de rechazarlo: quien escribe las fechas
        # al revés quiere ese intervalo, no un error.
        avisos.append(f"las fechas venían al revés; se comparan "
                      f"{b} -> {a}")
        a, b = b, a
    if a == b:
        avisos.append(f"desde y hasta caen en la misma captura ({a}); "
                      "no hay nada que comparar")
        a = None
    return a, b, avisos


def comparar(tipo: str, forzar: bool = False,
             desde=None, hasta=None) -> dict | None:
    """
    Compara dos capturas: las dos últimas, o el intervalo que se pida.
    Devuelve {"indice", "fecha", "completa"} de la más reciente de las dos.
    """
    archivos = _capturas(tipo)

    if not archivos:
        print(f"\n{tipo.upper()}: no hay ninguna captura todavía.")
        return None

    por_fecha = {_fecha_de(r): r for r in archivos}
    f_antes, f_ahora, avisos = elegir_capturas(list(por_fecha), desde, hasta)

    ultima = por_fecha[f_ahora]
    indice_ult, id_ult = _indexar(ultima)
    resultado = {"indice": indice_ult, "fecha": f_ahora,
                 "completa": _leer_meta(ultima).get("completa")}

    for aviso in avisos:
        print(f"  {aviso}")

    if f_antes is None:
        if len(archivos) == 1:
            print(f"\n{tipo.upper()}: solo hay una captura "
                  f"({f_ahora}, {len(indice_ult)} registros).")
            print("  Descarga las listas otro día para poder comparar.")
        else:
            print(f"\n{tipo.upper()}: no hay dos capturas que comparar en "
                  "ese intervalo.")
        return resultado

    r_antes, r_ahora = por_fecha[f_antes], ultima
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
        print("  Vuelve a descargarlas, o usa --forzar si aun así")
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
    informe = (carpeta_cuenta()
               / f"cambios_{OBJETIVO}_{tipo}_{_fecha_de(r_ahora)}.csv")
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


def _dias_con_par() -> list[str]:
    """Fechas con captura utilizable de las DOS listas."""
    utiles = {}
    for tipo in ("seguidores", "seguidos"):
        utiles[tipo] = {_fecha_de(r) for r in _capturas(tipo)
                        if _leer_meta(r).get("completa") is not False}
    return sorted(utiles["seguidores"] & utiles["seguidos"])


def estado_relacion_en(dia: str) -> dict:
    """
    Cómo estaba cada persona con LA CUENTA OBJETIVO ese día.

    Todo aquí es respecto a la cuenta que se vigila. La cuenta de la sesión
    solo sirve para poder mirar; no aparece en ninguno de estos estados.

    No se lee de las columnas cruzadas sino de en qué lista está cada uno:
    así funciona igual sobre capturas viejas, de antes de que esas columnas
    existieran.
    """
    filas, indices = {}, {}
    for tipo in ("seguidores", "seguidos"):
        filas[tipo] = _leer_csv(_ruta_captura(tipo, dia))
    # La clave se decide UNA vez para las dos listas: si una trae ids y la
    # otra no, mezclar criterios duplicaría a cada persona.
    con_id = all(_filas_con_id(f) for f in filas.values())
    for tipo in filas:
        indices[tipo] = _indice_de_filas(filas[tipo], con_id)

    a, b = indices["seguidores"], indices["seguidos"]
    estado = {}
    for clave in set(a) | set(b):
        quien = a.get(clave) or b.get(clave)
        if clave in a and clave in b:
            como = "mutuo"
        elif clave in a:
            como = "solo_sigue_a_la_cuenta"
        else:
            como = "solo_la_cuenta_le_sigue"
        estado[clave] = dict(quien, estado=como)
    return estado


# Qué significa pasar de un estado a otro. 'fuera' = no está en ninguna de
# las dos listas de la cuenta objetivo.
CAMBIOS_DE_RELACION = {
    ("mutuo", "solo_la_cuenta_le_sigue"): "dejó de seguir a la cuenta",
    ("mutuo", "solo_sigue_a_la_cuenta"): "la cuenta dejó de seguirle",
    ("mutuo", "fuera"): "era mutuo y desapareció",
    ("fuera", "mutuo"): "nuevo mutuo",
    ("solo_sigue_a_la_cuenta", "mutuo"): "la cuenta le devolvió el follow",
    ("solo_la_cuenta_le_sigue", "mutuo"): "le devolvió el follow a la cuenta",
    ("fuera", "solo_sigue_a_la_cuenta"): "empezó a seguir a la cuenta",
    ("solo_sigue_a_la_cuenta", "fuera"): "dejó de seguir a la cuenta",
    ("fuera", "solo_la_cuenta_le_sigue"): "la cuenta empezó a seguirle",
    ("solo_la_cuenta_le_sigue", "fuera"): "la cuenta dejó de seguirle",
}

# Los que hay que leer sí o sí: cambian una relación establecida.
ROTURAS = ("dejó de seguir a la cuenta", "la cuenta dejó de seguirle",
           "era mutuo y desapareció")


def calcular_cambios_de_relacion() -> tuple[list, list]:
    """
    Los cambios de relación y los dos días comparados. Sin imprimir nada.

    Va aparte del que imprime a propósito: tener dos copias del mismo
    cálculo es cómo la lista de vigilancia acabó con su copia (peor)
    del análisis de nombres, en la v3.0. Una sola, y encima de ella lo demás.
    """
    dias = _dias_con_par()
    if len(dias) < 2:
        return [], dias
    antes, ahora = estado_relacion_en(dias[-2]), estado_relacion_en(dias[-1])
    filas = []
    for clave in set(antes) | set(ahora):
        de = antes.get(clave, {}).get("estado", "fuera")
        a = ahora.get(clave, {}).get("estado", "fuera")
        if de == a:
            continue
        quien = ahora.get(clave) or antes.get(clave)
        filas.append({
            "username": quien.get("username", ""),
            "nombre": quien.get("nombre", ""),
            "antes": de, "ahora": a,
            "cambio": CAMBIOS_DE_RELACION.get((de, a), f"{de} -> {a}"),
        })
    filas.sort(key=lambda f: (f["cambio"], f["username"]))
    return filas, dias


def _movimiento_de_lista(tipo: str) -> tuple[list, list]:
    """
    Quién entró y salió de una lista, entre sus dos últimas capturas.

    Hace falta para avisar cuando 'vigilar' solo bajó UNA de las dos: ahí no
    se puede clasificar la relación, pero sí decir quién se movió.
    """
    utiles = [r for r in _capturas(tipo)
              if _leer_meta(r).get("completa") is not False]
    if len(utiles) < 2:
        return [], []
    antes, con_a = _indexar(utiles[-2])
    ahora, con_b = _indexar(utiles[-1])
    if con_a != con_b:
        # Una con ids y otra sin ellos: las claves no son comparables y
        # saldría media lista entrando y saliendo. Mejor no decir nada.
        return [], []
    entraron = sorted(ahora[c]["username"] for c in set(ahora) - set(antes))
    salieron = sorted(antes[c]["username"] for c in set(antes) - set(ahora))
    return entraron, salieron


def cambios_de_relacion() -> list:
    """
    Cómo cambió la relación de cada persona CON LA CUENTA OBJETIVO.

    'comparar' dice quién entró y quién salió de cada lista por separado.
    Eso deja fuera de qué tipo fue cada movimiento: un mutuo que deja de
    seguir a la cuenta y un seguidor cualquiera que se va salen exactamente
    igual, y no son lo mismo.

    Cero peticiones: se calcula sobre lo que ya está en disco. Necesita dos
    días con las DOS listas completas, porque el estado de una persona solo
    se sabe mirando las dos a la vez.
    """
    filas, dias = calcular_cambios_de_relacion()
    if len(dias) < 2:
        print("\nRELACIÓN CON LA CUENTA")
        print("  Hacen falta dos días con las dos listas completas; "
              f"hay {len(dias)}.")
        return []

    print("\nRELACIÓN CON LA CUENTA")
    print(f"  Entre el {dias[-2]} y el {dias[-1]}.")
    if not filas:
        print("  Nadie cambió de relación.")
        return filas

    roturas = [f for f in filas if f["cambio"] in ROTURAS]
    for titulo in ROTURAS:
        de_este = [f for f in roturas if f["cambio"] == titulo]
        if de_este:
            print(f"\n  {titulo.upper()}: {len(de_este)}")
            for f in de_este[:MAX_LISTAR]:
                print(f"    {f['username']}"
                      + (f"   ({f['nombre']})" if f["nombre"] else ""))
            if len(de_este) > MAX_LISTAR:
                print(f"    ... y {len(de_este) - MAX_LISTAR} más")

    resto = len(filas) - len(roturas)
    if resto:
        print(f"\n  Otros {resto} cambios (altas y bajas sin relación "
              "establecida) están en el informe.")

    informe = carpeta_cuenta() / f"relacion_{OBJETIVO}_{dias[-1]}.csv"
    cabecera = ["username", "nombre", "antes", "ahora", "cambio"]
    _escribir_csv(informe, cabecera, [_fila(f, cabecera) for f in filas])
    print(f"\n  Informe: {informe.name}")
    return filas


def cruzar_capturas(callado: bool = False) -> str:
    """
    Rellena en las capturas quién sigue a la cuenta y a quién sigue ella.

    Cero peticiones: la respuesta ya está en las dos listas descargadas.
    Quien aparece en 'seguidores' sigue a la cuenta; quien aparece en
    'seguidos' es seguido por ella; quien está en las dos es mutuo.

    Dos condiciones, y son las que hacen que el dato valga algo:

    - **Las dos capturas del mismo día.** Cruzar seguidores de hoy con
      seguidos de hace un mes marcaría como seguidos a quienes la cuenta ya
      dejó de seguir. Es el fallo nº 9 de la v1, que entonces solo
      se avisaba.
    - **Las dos completas.** Con una truncada, todo el que falte en ella sale
      como 'no', y serían cientos de noes falsos escritos en el archivo.

    Si no se cumplen, las columnas se quedan vacías. Una columna en blanco se
    ve y se pregunta; un 'no' inventado se cree.
    """
    def decir(texto):
        if not callado:
            print(texto)
        return texto

    rutas, metas = {}, {}
    for tipo in ("seguidores", "seguidos"):
        capturas = _capturas(tipo)
        if not capturas:
            return decir(f"  Cruce: no hay capturas de {tipo} todavía.")
        rutas[tipo] = capturas[-1]
        metas[tipo] = _leer_meta(capturas[-1])

    if _fecha_de(rutas["seguidores"]) != _fecha_de(rutas["seguidos"]):
        return decir("  Cruce: las capturas son de días distintos "
                     f"({_fecha_de(rutas['seguidores'])} y "
                     f"{_fecha_de(rutas['seguidos'])}). Descarga las dos para "
                     "tener las dos del mismo día.")

    rotas = [t for t in rutas if metas[t].get("completa") is False]
    if rotas:
        return decir(f"  Cruce: {' y '.join(rotas)} sin completar; las "
                     "columnas se quedan vacías para no inventar noes.")

    filas = {t: _leer_csv(rutas[t]) for t in rutas}
    con_id = all(_filas_con_id(f) for f in filas.values())
    clave = (lambda f: str(f.get("id") or "")) if con_id \
        else (lambda f: str(f.get("username", "")).lower())
    presentes = {t: {clave(f) for f in filas[t]} for t in filas}

    # En cada lista una de las dos respuestas es evidente por estar ahí, y la
    # otra es la que sale del cruce.
    conocidas = {"seguidores": ("sigue_a_la_cuenta", "la_cuenta_le_sigue",
                                "seguidos"),
                 "seguidos": ("la_cuenta_le_sigue", "sigue_a_la_cuenta",
                              "seguidores")}
    mutuos = 0
    for tipo, (evidente, cruzada, otra) in conocidas.items():
        for fila in filas[tipo]:
            fila[evidente] = "si"
            hay = clave(fila) in presentes[otra]
            fila[cruzada] = "si" if hay else "no"
            if hay and tipo == "seguidores":
                mutuos += 1
        cabecera = _cabecera_de(rutas[tipo]) or list(CABECERA)
        for columna in CAMPOS_CRUZADOS:
            if columna not in cabecera:
                cabecera.append(columna)
        # (se resella justo debajo: reescribir sin decirlo rompería la
        #  cadena y parecería una manipulación)
        _escribir_csv(rutas[tipo], cabecera,
                      [_fila(f, cabecera) for f in filas[tipo]])
        resellar(rutas[tipo], "cruce de listas")

    aviso = "" if con_id else ("  (cruzado por nombre de usuario: falta\n"
                              "   algún id)\n")
    return decir(f"{aviso}  Cruce hecho sobre las capturas del "
                 f"{_fecha_de(rutas['seguidores'])}: "
                 + plural(mutuos, "mutuo") + " de "
                 + plural(len(filas["seguidores"]), "seguidor",
                          "seguidores") + ".")


def relaciones(seguidores: dict | None, seguidos: dict | None) -> None:
    """Cruce entre las últimas capturas de ambas listas."""
    if not seguidores or not seguidos:
        return

    print("\nRELACIONES")
    if seguidores["fecha"] != seguidos["fecha"]:
        print(f"  ATENCIÓN: se cruzan capturas de fechas distintas "
              f"(seguidores {seguidores['fecha']}, "
              f"seguidos {seguidos['fecha']}).")
        print("  Descarga las dos listas el mismo día.")
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

    # Los mismos textos que la tabla y el informe. Antes esto tenía su
    # propia forma de decirlo —«sigue y no le devuelven el follow»— que no
    # coincidía con ninguna de las otras dos: tres vocabularios para tres
    # estados, y ninguno servía para entender los otros.
    leyenda = leyenda_relacion(OBJETIVO)
    for clave, cuantos in (("mutuo", len(mutuos)),
                           ("solo_la_cuenta_le_sigue", len(no_devuelven)),
                           ("solo_sigue_a_la_cuenta", len(no_correspondidos))):
        print(f"  {cuantos:>5}  {clave:<24} {leyenda[clave]}")

    _listar("NO SIGUEN DE VUELTA A @" + OBJETIVO.upper(),
            no_devuelven, b)

    informe = carpeta_cuenta() / f"relaciones_{OBJETIVO}.csv"
    # Los mismos nombres que usa estado_relacion_en(), no otros.
    filas = [["mutuo", a[c]["username"], a[c]["nombre"]] for c in mutuos]
    filas += [["solo_la_cuenta_le_sigue", b[c]["username"], b[c]["nombre"]]
              for c in no_devuelven]
    filas += [["solo_sigue_a_la_cuenta", a[c]["username"], a[c]["nombre"]]
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
            # `is None` y no truthiness: aquí solo llegan True o None
            # porque el False sale arriba, pero atarlo a esa rama es dejar
            # una mina para quien la mueva.
            marca = "   (sin metadatos)" if meta.get("completa") is None \
                else ""
            delta = f"  ({n - previo:+d})" if previo is not None else ""
            print(f"  {_fecha_de(ruta)}   {n}{delta}{marca}")
            previo = n


# ======================================================================
# HISTORIAL POR PERSONA
# ======================================================================

def _desplomes(indice: dict) -> tuple[set, list]:
    """
    Qué capturas se desploman de tamaño. Devuelve (índices, detalle).

    Una captura truncada o vacía haría parecer que cientos de personas se
    fueron y volvieron, que es justo el patrón que este análisis busca. Se
    compara contra la MEDIANA y no contra la anterior: así una bajada real
    y sostenida (que mueve la mediana) no se confunde con un fallo puntual.

    Hacen falta las DOS condiciones, relativa y absoluta. Solo con la
    relativa, en una lista de 3 personas que pierde 1 el 33% parecería un
    desplome, cuando es un cambio perfectamente normal.

    Ahora se calcula sobre los tamaños guardados en el índice, así que no
    hay que abrir ni un CSV para saberlo.
    """
    tamanos = indice.get("tamanos") or []
    if len(tamanos) < 2:
        return set(), []
    referencia = statistics.median(tamanos)
    if referencia <= 0:
        return set(), []

    fuera, detalle = set(), []
    for i, n in enumerate(tamanos):
        if n < referencia * CAIDA_SOSPECHOSA and referencia - n >= CAIDA_MINIMA:
            fuera.add(i)
            detalle.append((indice["fechas"][i], n, int(referencia)))
    return fuera, detalle


DIAS_A_DIARIO = 30              # cuánto se guarda día a día antes de podar


def podar(dias: int = DIAS_A_DIARIO, hacerlo: bool = False) -> list:
    """
    Quita capturas viejas dejando una por semana. Devuelve lo que quita.

    Esto solo es seguro porque existe el índice: lo que se aprendió de una
    captura se queda cuando ella desaparece. Sin él, borrar un CSV sería
    borrar ese trozo de historia.

    Tres reglas, y las tres están para no perder nada que importe:

    - Solo se toca lo que YA está en el índice. Una captura sin procesar
      todavía tiene toda su información dentro y solo dentro.
    - Los últimos `dias` días se quedan enteros: es lo que se compara.
    - Más atrás se guarda una por semana, la más reciente de cada una, y
      NUNCA la última de la lista.

    Por defecto no borra nada: dice qué haría. Borrar los datos de alguien
    porque un programa lo decidió solo es lo que no se hace.
    """
    hoy = date.today()
    fuera = []
    for tipo in ("seguidores", "seguidos"):
        indice = cargar_indice(tipo)
        procesadas = set((indice.get("capturas") or {}))
        capturas = _capturas(tipo)
        if len(capturas) < 2:
            continue

        por_semana = {}
        for ruta in capturas[:-1]:              # la última no se toca jamás
            if ruta.name not in procesadas:
                continue                        # aún no está en el índice
            try:
                cuando = datetime.strptime(_fecha_de(ruta), "%Y-%m-%d").date()
            except ValueError:
                continue
            if (hoy - cuando).days <= dias:
                continue                        # tramo reciente, intacto
            por_semana.setdefault(cuando.isocalendar()[:2], []).append(ruta)

        for _, ese_grupo in por_semana.items():
            # Se guarda la más reciente de la semana; el resto sobra.
            for ruta in sorted(ese_grupo, key=_fecha_de)[:-1]:
                fuera.append(ruta)

    if hacerlo:
        for ruta in fuera:
            try:
                _ruta_meta(ruta).unlink(missing_ok=True)
                ruta.unlink()
            except OSError:
                pass
    return fuera




def _ruta_indice(tipo: str) -> Path:
    return carpeta_cuenta() / f".indice_{OBJETIVO}_{tipo}.json"


def _firma(ruta: Path) -> list:
    """Con qué se sabe si una captura ya procesada ha cambiado."""
    try:
        e = ruta.stat()
        return [int(e.st_mtime), e.st_size]
    except OSError:
        return [0, 0]


def cargar_indice(tipo: str) -> dict:
    try:
        return json.loads(_ruta_indice(tipo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def actualizar_indice(tipo: str) -> dict:
    """
    El índice al día, leyendo del disco SOLO las capturas nuevas.

    Aquí está el ahorro: antes se abrían y parseaban las 730 capturas del
    año en cada consulta; ahora, la de hoy.

    Se reconstruye entero solo cuando hace falta de verdad: si cambió el
    criterio de clave, si una captura ya procesada cambió de contenido, o si
    aparece una con fecha anterior a la última (eso descolocaría los tramos
    de todo el mundo). Que una captura vieja DESAPAREZCA no obliga a nada:
    lo que se aprendió de ella se queda, y eso es lo que permite borrar
    capturas antiguas sin perder el historial.
    """
    capturas = []
    for ruta in _capturas(tipo):
        meta = _leer_meta(ruta)
        if meta.get("completa") is False:
            continue                    # una truncada nunca entra al índice
        capturas.append(ruta)

    indice = cargar_indice(tipo)
    conocidas = (indice.get("capturas") or {}) if indice else {}
    en_disco = {r.name for r in capturas}
    nuevas = [r for r in capturas if r.name not in conocidas]
    cambiadas = [r for r in capturas
                 if r.name in conocidas and conocidas[r.name] != _firma(r)]
    # Una captura que ya estaba indexada y que AHORA se marca truncada tiene
    # que salir, o seguiría contando en el historial para siempre. Sacar una
    # del medio no se puede hacer a trozos: se rehace. Que haya
    # desaparecido del disco es otra cosa y no obliga a nada — eso es
    # justamente lo que permite podar.
    degradadas = [n for n in conocidas if n not in en_disco
                  and (carpeta_cuenta() / n).exists()]

    # La clave se decide con TODAS: si a una sola le faltan ids, la serie
    # entera pasa a indexarse por nombre de usuario.
    filas_nuevas = {r: _leer_csv(r) for r in nuevas}
    usar_id = all(_filas_con_id(f) for f in filas_nuevas.values())
    if indice and usar_id and not indice.get("usar_id"):
        usar_id = False                 # ya venía degradado de antes

    fechas = indice.get("fechas") or []
    desordenadas = [r for r in nuevas if fechas and _fecha_de(r) < fechas[-1]]

    if (not indice_eventos.sirve(indice, usar_id)
            or cambiadas or desordenadas or degradadas):
        indice = indice_eventos.nuevo(usar_id)
        nuevas = capturas
        filas_nuevas = {r: _leer_csv(r) for r in nuevas}
        usar_id = all(_filas_con_id(f) for f in filas_nuevas.values())
        indice["usar_id"] = usar_id

    for ruta in sorted(nuevas, key=_fecha_de):
        filas = filas_nuevas.get(ruta) or _leer_csv(ruta)
        indice_eventos.anadir_captura(
            indice, _fecha_de(ruta),
            _indice_de_filas(filas, indice["usar_id"]),
            ruta.name, _firma(ruta))

    if nuevas:
        try:
            carpeta_cuenta().mkdir(parents=True, exist_ok=True)
            # Se escribe al lado y se cambia de nombre de golpe. La tarea
            # programada y la ventana pueden coincidir, y un lector que
            # pillara el archivo a medias lo daría por ilegible y lo
            # reconstruiría entero: 7 segundos por un descuido de dos
            # líneas. Es el mismo problema del contador de peticiones (q1).
            escribir_atomico(_ruta_indice(tipo),
                             json.dumps(indice, ensure_ascii=False))
        except OSError:
            pass                        # sin poder guardarlo se recalcula
    return indice


def construir_historial(tipo: str,
                        incluir_sospechosas: bool = False) -> dict | None:
    """
    La trayectoria de cada persona: cuándo apareció, cuándo se fue, cuántas
    veces ha entrado y salido, y los nombres que ha tenido.

    Ya no cruza todas las capturas: las lee UNA vez, cuando son nuevas, y
    después trabaja sobre el índice. Con dos capturas daba igual; con las
    ~730 de un año de vigilancia diaria, es la diferencia entre esperar y
    no esperar.
    """
    truncadas, sin_meta = [], []
    for ruta in _capturas(tipo):
        meta = _leer_meta(ruta)
        if meta.get("completa") is False:
            truncadas.append(_fecha_de(ruta))
        elif meta.get("completa") is None:
            sin_meta.append(_fecha_de(ruta))

    indice = actualizar_indice(tipo)
    if not indice.get("fechas"):
        return None

    fuera, sospechosas = (set(), []) if incluir_sospechosas \
        else _desplomes(indice)
    derivado = indice_eventos.derivar(indice, fuera)
    if not derivado["fechas"]:
        return None

    return {"fechas": derivado["fechas"], "personas": derivado["personas"],
            "truncadas": truncadas, "sin_meta": sin_meta,
            "sospechosas": sospechosas, "usar_id": indice["usar_id"]}


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
    ruta = carpeta_cuenta() / f"historial_{tipo}_{OBJETIVO}.csv"
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
        print("  Descarga o vigila otro día para empezar a comparar.")
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
        escribir_atomico(
            ruta, "# Cuentas que sigues. Una por línea.\n"
                  "# Se añaden solas al descargarlas por primera vez.\n")
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(nombre + "\n")
    return True


def quitar_cuenta(nombre: str) -> bool:
    """Deja de seguirla. No borra sus capturas."""
    nombre = limpiar_usuario(nombre)
    quedan = [c for c in leer_cuentas() if c.lower() != nombre.lower()]
    if len(quedan) == len(leer_cuentas()):
        return False
    escribir_atomico(
        _ruta_cuentas(),
        "# Cuentas que sigues. Una por línea.\n" + "\n".join(quedan) + "\n")
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
            # Comparar necesita dos DÍAS, no dos archivos. Bajar una vez
            # deja dos capturas —seguidores y seguidos— y el consejo
            # ofrecía comparar cuando no había con qué.
            "dias": len({_fecha_de(r) for v in capturas.values()
                         for r in v}),
            "ultima": ultima,
            "pendiente": any(_ruta_parcial(t).exists()
                             for t in ("seguidores", "seguidos")),
            "conteo": _ultimo_conteo(),
        }






def _ruta_totales() -> Path:
    return carpeta_cuenta() / f"totales_{OBJETIVO}.csv"


# ======================================================================
# NOVEDADES
# ======================================================================
# 'vigilar' está pensado para correr solo desde el Task Scheduler, y hasta
# ahora, cuando detectaba algo, escribía una línea en un log que nadie abre.
# Esto es la diferencia entre una herramienta que ejecutas y una que trabaja
# mientras no miras: lo que encuentra se acumula aquí hasta que lo leas.
#
# Va en la RAÍZ y no en la carpeta de cada cuenta a propósito: es la bandeja
# que se abre, no un dato de una cuenta. Con cinco objetivos vigilados, lo
# último que quieres es tener que mirar en cinco sitios.

def _ruta_novedades() -> Path:
    return CARPETA / "novedades.txt"


def _ruta_novedades_vistas() -> Path:
    return CARPETA / ".novedades_vistas.json"


def separar_novedades(texto: str) -> list:
    """
    Parte el archivo en bloques {sello, texto}.

    Una línea sin sangrar empieza un bloque; las sangradas son su contenido.
    Función pura: se puede comprobar sin tocar el disco.
    """
    bloques = []
    for linea in (texto or "").splitlines():
        if not linea.strip():
            continue
        if linea[:1].isspace() and bloques:
            bloques[-1]["texto"].append(linea.strip())
        else:
            bloques.append({"sello": linea[:19], "cabecera": linea.strip(),
                            "texto": []})
    return bloques


def anotar_novedad(cuenta: str, lineas: list) -> None:
    """Añade un bloque a la bandeja. Nunca borra lo anterior."""
    if not lineas:
        return
    sello = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        with open(_ruta_novedades(), "a", encoding="utf-8") as f:
            f.write(f"{sello}  @{cuenta}\n")
            for linea in lineas:
                # Un salto dentro de una línea partiría el bloque en dos, y
                # el trozo de abajo pasaría por una novedad suelta.
                f.write("    " + str(linea).replace("\n", " ") + "\n")
    except OSError:
        pass                    # el aviso es un extra, no puede tumbar nada


def _bloques_de_la_bandeja() -> list:
    try:
        return separar_novedades(_ruta_novedades().read_text(encoding="utf-8"))
    except OSError:
        return []


def _marca_de_lectura() -> dict:
    try:
        marca = json.loads(
            _ruta_novedades_vistas().read_text(encoding="utf-8"))
        return marca if isinstance(marca, dict) else {}
    except (OSError, ValueError):
        return {}


def novedades_pendientes() -> list:
    """
    Bloques posteriores a la última vez que se leyeron. 0 peticiones.

    Se cuenta por POSICIÓN y no por sello. El sello llega al segundo, y dos
    cuentas anotadas en la misma pasada de 'vigilar --todas' empatan: con el
    sello, la segunda se daba por leída sin haberse enseñado nunca.

    El sello se guarda igual, como comprobación: si el archivo se ha editado
    a mano y ya no cuadra, se vuelve a él, que es lo único fiable entonces.
    """
    bloques = _bloques_de_la_bandeja()
    marca = _marca_de_lectura()
    vistos, hasta = marca.get("vistos", 0), marca.get("hasta", "")
    if isinstance(vistos, int) and 0 < vistos <= len(bloques) \
            and bloques[vistos - 1]["sello"] == hasta:
        return bloques[vistos:]
    return [b for b in bloques if b["sello"] > hasta]


def marcar_novedades_vistas() -> None:
    """Deja anotado hasta dónde se ha leído."""
    bloques = _bloques_de_la_bandeja()
    if not bloques:
        return
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        escribir_atomico(_ruta_novedades_vistas(), json.dumps(
            {"vistos": len(bloques), "hasta": bloques[-1]["sello"]}))
    except OSError:
        pass


def avisar_al_sistema(titulo: str, cuerpo: str) -> bool:
    """
    Aviso del sistema operativo. Best-effort: si no sale, no pasa nada.

    En Windows se usa el globo de NotifyIcon, que va con el .NET de toda la
    vida y no necesita instalar nada. Se lanza sin esperarlo: una tarea
    programada no puede quedarse colgada de un aviso que nadie va a cerrar.

    La bandeja de novedades es lo fiable; esto es la comodidad de enterarte
    en el momento.
    """
    if sys.platform != "win32":
        return False
    limpio = (lambda t: str(t).replace("'", " ").replace("\n", " ")[:180])
    guion = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.Visible = $true;"
        f"$n.ShowBalloonTip(10000, '{limpio(titulo)}', '{limpio(cuerpo)}',"
        " 'Info');"
        "Start-Sleep -Seconds 8; $n.Dispose()"
    )
    try:
        import subprocess
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-Command", guion],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _ruta_log() -> Path:
    return carpeta_cuenta() / f"vigilancia_{OBJETIVO}.log"


def _log(mensaje: str) -> None:
    """Deja rastro de cada pasada, para revisar qué hizo mientras no mirabas."""
    carpeta_cuenta().mkdir(parents=True, exist_ok=True)
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
        # Las filas escritas antes de que existiera la columna de
        # publicaciones tienen tres campos. Se completan con vacío y NO con
        # cero: cero es un dato, y dibujaría una caída a plomo el día que se
        # añadió la columna. Vacío es lo que de verdad pasa: no se sabe.
        return [(fila + [""])[:4] for fila in lector if len(fila) >= 3]


def _ultimo_conteo() -> dict | None:
    """Último recuento anotado, o None si es la primera vez."""
    filas = _filas_totales()
    if not filas:
        return None
    fecha, seguidores, seguidos, publicaciones = filas[-1]
    try:
        conteo = {"fecha": fecha, "seguidores": int(seguidores),
                  "seguidos": int(seguidos)}
    except ValueError:
        return None
    try:
        conteo["publicaciones"] = int(publicaciones)
    except ValueError:
        pass                # las filas de antes no lo traen, y no pasa nada
    return conteo


def _anotar_conteo(p: dict) -> None:
    """
    Anota el recuento del día. Si ya hay una fila de hoy, la reemplaza:
    ejecutar 'vigilar' dos veces no debe crear dos puntos para el mismo día.
    """
    carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    hoy = f"{date.today():%Y-%m-%d}"
    filas = [f for f in _filas_totales() if f[0] != hoy]
    # Un 0 aquí significa "no se pudo saber" (el buscador no trae el
    # recuento), no "esta cuenta no ha publicado nada". Se anota vacío.
    filas.append([hoy, p["seguidores"], p["seguidos"],
                  p.get("publicaciones") or ""])
    _escribir_csv(_ruta_totales(), CABECERA_TOTALES, filas)


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


def _ruta_ritmo() -> Path:
    # En la raíz: es el plan de la ronda entera, se lee de una vez y va
    # contra el mismo presupuesto compartido.
    return CARPETA / "ritmo.json"


def leer_ritmo() -> dict:
    try:
        d = json.loads(_ruta_ritmo().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_ritmo(ritmo: dict) -> None:
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        escribir_atomico(_ruta_ritmo(),
                         json.dumps(ritmo, ensure_ascii=False, indent=2))
    except OSError:
        pass


def dias_desde(fecha: str, hoy: date | None = None) -> int:
    """Días desde una fecha ISO. Muy grande si no se entiende o no hay."""
    try:
        return ((hoy or date.today()) - date.fromisoformat(fecha)).days
    except (ValueError, TypeError):
        return 9999


def retraso(estado: dict, hoy: date | None = None,
            tope_dias: int = MAX_DIAS_SIN_BAJAR) -> int:
    """
    Cuántos días de más lleva sin mirarse. Negativo = todavía no toca.

    Sirve para dos cosas a la vez: decidir si toca (>= 0) y ordenar la
    ronda, poniendo delante a las que más lo necesitan cuando el
    presupuesto no llega para todas.
    """
    cadencia = min(int(estado.get("cadencia") or 1), tope_dias)
    return dias_desde(estado.get("mirada", ""), hoy) - cadencia


def ajustar_ritmo(estado: dict, hubo_cambio: bool, hoy: date | None = None,
                  tope_dias: int = MAX_DIAS_SIN_BAJAR) -> dict:
    """
    Cada cuánto conviene mirar esta cuenta, visto lo que pasó al mirarla.

    Misma asimetría que el tope diario, y por el mismo motivo: **reaccionar
    rápido a la señal y retirarse despacio**. Si se movió, se vuelve a la
    mitad de golpe; si no, se separa un día. Una cuenta dormida acaba
    mirándose una vez por semana en vez de treinta veces al mes.

    El techo es `MAX_DIAS_SIN_BAJAR` y no es negociable. Esa es la garantía
    del «neto cero» de la v2.1: si se van tres y entran tres el total no
    cambia, y solo la descarga forzada periódica lo pilla. Un ritmo más
    lento que ella la rompería en silencio, que es la peor forma de
    romperse.
    """
    hoy = hoy or date.today()
    cadencia = int(estado.get("cadencia") or 1)
    if hubo_cambio:
        cadencia = max(1, cadencia // 2)
    else:
        cadencia = min(tope_dias, cadencia + 1)
    nuevo = dict(estado)
    nuevo["cadencia"] = cadencia
    nuevo["mirada"] = f"{hoy:%Y-%m-%d}"
    if hubo_cambio:
        nuevo["cambio"] = f"{hoy:%Y-%m-%d}"
    return nuevo






def _resumir_para_novedad(p: dict, previo: dict | None, bajadas: set) -> list:
    """
    Qué contarle a quien no estaba mirando. Lista vacía = no hubo nada.

    Dos cosas que costaron un fallo cada una:

    1. Los cambios de relación solo valen si la pareja de capturas más
       reciente es de HOY. 'vigilar' suele bajar solo la lista que se movió,
       y entonces la última pareja completa es de días atrás: se estarían
       contando como novedad de hoy unos cambios viejos, y encima repetidos
       en cada pasada hasta que hubiera pareja nueva.
    2. Si no hubo nada, no se anota nada. Una bandeja que se llena de «sin
       cambios» deja de leerse, y entonces no sirve para lo único que hace.
    """
    lineas = []
    dias = _dias_con_par()
    al_dia = bool(dias) and dias[-1] == f"{date.today():%Y-%m-%d}"

    if al_dia:
        # Lo mejor que se puede decir: de qué TIPO fue cada cambio.
        cambios, _ = calcular_cambios_de_relacion()
        por_tipo = {}
        for c in cambios:
            por_tipo.setdefault(c["cambio"], []).append(c["username"])
        for cambio in ROTURAS + ("nuevo mutuo",):
            quienes = por_tipo.get(cambio, [])
            if quienes:
                lineas.append(f"{len(quienes)} {cambio}: "
                              + ", ".join(quienes[:8])
                              + (" ..." if len(quienes) > 8 else ""))
    else:
        # Solo se bajó una lista: no se puede clasificar la relación, pero
        # sí decir quién se movió en la que sí se bajó.
        for tipo in sorted(bajadas):
            entraron, salieron = _movimiento_de_lista(tipo)
            if entraron or salieron:
                lineas.append(f"{tipo}: entraron {len(entraron)}, "
                              f"salieron {len(salieron)}")
                for etiqueta, quienes in (("entraron", entraron),
                                          ("salieron", salieron)):
                    if quienes:
                        lineas.append(f"  {etiqueta}: "
                                      + ", ".join(quienes[:8])
                                      + (" ..." if len(quienes) > 8 else ""))

    def delta(tipo):
        return p[tipo] - previo[tipo] if previo else None

    movidos = [t for t in ("seguidores", "seguidos") if delta(t)]
    if not lineas and not movidos and previo:
        return []               # de verdad no pasó nada: no se anota

    def texto_delta(tipo):
        d = delta(tipo)
        return f"{d:+d}" if d is not None else "primer conteo"

    lineas.append(f"seguidores {p['seguidores']} "
                  f"({texto_delta('seguidores')}), "
                  f"seguidos {p['seguidos']} ({texto_delta('seguidos')})")
    lineas.append(f"descargado: {', '.join(sorted(bajadas))}")
    return lineas




# ======================================================================
# PERFIL DETALLADO (lista de vigilancia)
# ======================================================================

def _ruta_vigilancia() -> Path:
    return carpeta_cuenta() / f"vigilancia_{OBJETIVO}.txt"


def _ruta_detalles(dia: str | None = None) -> Path:
    dia = dia or f"{date.today():%Y-%m-%d}"
    return carpeta_cuenta() / f"detalles_{OBJETIVO}_{dia}.csv"


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
    carpeta_cuenta().mkdir(parents=True, exist_ok=True)
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

    escribir_atomico(ruta, "\n".join([
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




# ======================================================================
# COMANDOS
# ======================================================================





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
                       f"mira 'limite' para ver por qué está ahí.")
    aviso = f"Coste estimado: ~{coste} peticiones. Te quedan {disponible} hoy."
    if coste > disponible * 0.5:
        aviso += "  Se va a comer más de la mitad de lo que queda."
    return True, aviso


def avisar_si_privada(p: dict) -> str | None:
    """
    Qué advertir sobre la privacidad de la cuenta, si hay que advertir
    algo.

    Tres estados, no dos: privada, pública, y **no consta**. El tercero
    existe porque la página del perfil no siempre deja atar ese dato a
    esta cuenta, y decir «es privada» por si acaso fue exactamente el
    fallo que hubo: una cuenta pública salía marcada como privada
    mientras se descargaba sin problema, porque en la página había otra
    que sí lo era.
    """
    if p.get("privada") is None:
        return ("No consta si la cuenta es privada: los datos vinieron de "
                "la página y ahí ese dato no se pudo atar a esta cuenta. "
                "Si lo fuera y no la siguieras, la descarga saldría vacía.")
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
    return None




TOPE_ARCHIVO_EXPORT = 80_000_000    # ningún JSON de listas pesa tanto


def abrir_export(ruta: Path) -> dict:
    """
    Saca del ZIP (o de la carpeta ya descomprimida) los archivos que sirven.

    Se buscan POR NOMBRE en cualquier punto de dentro: la ruta ha cambiado
    entre versiones del export y el nombre no. Y solo se leen los que
    interesan, que son cuatro: un export completo trae cientos de megas de
    fotos que aquí no pintan nada.
    """
    encontrados = {}
    if ruta.is_dir():
        for hijo in ruta.rglob("*.json"):
            if export_instagram.clasificar(hijo.name):
                try:
                    if hijo.stat().st_size > TOPE_ARCHIVO_EXPORT:
                        continue
                    encontrados[hijo.name] = hijo.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
        return encontrados

    import zipfile
    with zipfile.ZipFile(ruta) as z:
        for dentro in z.namelist():
            if not export_instagram.clasificar(dentro):
                continue
            info = z.getinfo(dentro)
            if info.file_size > TOPE_ARCHIVO_EXPORT:
                continue
            try:
                encontrados[dentro] = z.read(dentro).decode("utf-8")
            except (OSError, UnicodeDecodeError, zipfile.BadZipFile):
                continue
    return encontrados


def ruta_enriquecimiento(cuenta: str) -> Path:
    return carpeta_cuenta(cuenta) / f"export_{cuenta}.json"




def plural(n: int, uno: str, muchos: str = "") -> str:
    """
    '1 bloqueo', '3 bloqueos'.

    El «bloqueo(s)» con paréntesis es del programador, no de quien lee. Ya
    se corrigió una vez en la ventana y se quedó en el módulo, así que
    mejor un sitio y no cinco.
    """
    return f"{n} {uno if abs(n) == 1 else (muchos or uno + 's')}"


def columnas_vacias(filas: list, columnas: list) -> set:
    """
    Las columnas sin un solo dato en ninguna fila.

    Pasa de verdad: Instagram puede dejar de mandar un campo, o el cruce no
    haberse hecho, y entonces esa columna sale en blanco. Una columna vacía
    parece una avería de la aplicación en vez de un dato que no llegó, así
    que tanto la ventana como el informe lo dicen.

    Vive aquí y no en cada sitio que la usa: dos copias del mismo cálculo es
    exactamente lo que ya salió mal dos veces en este proyecto.
    """
    return {c for c in columnas
            if not any(str(f.get(c, "")).strip() for f in filas)}


def _foto_en_base64(cuenta: str) -> str:
    """La foto como data URI, para que el informe no dependa de nada."""
    try:
        import base64
        datos = ruta_foto(cuenta).read_bytes()
        if not datos or len(datos) > 4_000_000:
            return ""
        # El tipo sale de los bytes, no del nombre del archivo: guardar_foto
        # acepta las dos cosas, y llamar PNG a un JPEG es mentira aunque el
        # navegador lo adivine.
        tipo = "png" if datos[:8].startswith(b"\x89PNG") else "jpeg"
        return (f"data:image/{tipo};base64,"
                + base64.b64encode(datos).decode("ascii"))
    except (OSError, ValueError):
        return ""


def recopilar_informe() -> dict:
    """
    Todo lo que hace falta para el informe, leído del disco. 0 peticiones.

    Va aparte de la generación del HTML a propósito: esto sabe dónde están
    las cosas, y `informe_html.generar()` sabe darles forma. Ninguna de las
    dos tiene que saber de la otra.
    """
    estado = leer_estado(OBJETIVO)
    datos = {
        "cuenta": OBJETIVO,
        "nombre": estado.get("nombre", ""),
        "publicaciones": estado.get("publicaciones"),
        "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": VERSION,
        "foto": _foto_en_base64(OBJETIVO),
        "listas": {}, "evolucion": {}, "avisos": [],
        "etiquetas": ETIQUETAS_INFORME,
        "leyenda_relacion": dict(LEYENDA_RELACION),
        "relaciones": [],
    }

    # Quién es mutuo y quién no, si ya se ha calculado. Sale del CSV que
    # deja 'comparar': no se recalcula aquí, que sería hacer dos veces lo
    # mismo y arriesgarse a que las dos no digan igual.
    ruta_rel = carpeta_cuenta() / f"relaciones_{OBJETIVO}.csv"
    if ruta_rel.exists():
        datos["relaciones"] = [
            f for f in _leer_csv(ruta_rel)[:TOPE_FILAS_INFORME]
            if f.get("relacion")]

    for tipo in ("seguidores", "seguidos"):
        capturas = _capturas(tipo)
        serie = []
        for ruta in capturas:
            meta = _leer_meta(ruta)
            if meta.get("completa") is False:
                continue            # una truncada torcería la línea
            if isinstance(meta.get("obtenidos"), int):
                serie.append((_fecha_de(ruta), meta["obtenidos"]))
        datos["evolucion"][tipo] = serie

        if not capturas:
            continue
        ultima = capturas[-1]
        meta = _leer_meta(ultima)
        filas = _leer_csv(ultima)
        columnas = _cabecera_de(ultima) or list(CABECERA)
        # Un tope, como el visor: con una cuenta enorme, meter 40.000 filas
        # dentro del HTML da un archivo que el navegador no abre.
        recortadas = filas[:TOPE_FILAS_INFORME]
        if len(filas) > len(recortadas):
            datos["avisos"].append(
                f"La tabla de {tipo} enseña las primeras "
                f"{TOPE_FILAS_INFORME} de {len(filas)} filas. El CSV completo "
                "está en la carpeta.")
        datos["listas"][tipo] = {
            "fecha": _fecha_de(ultima),
            "completa": meta.get("completa"),
            "total": len(filas),
            "columnas": columnas,
            "filas": recortadas,
            "vacias": sorted(columnas_vacias(filas, columnas)),
        }
        for columna in columnas_vacias(filas, columnas):
            if columna in CAMPOS_CRUZADOS:
                datos["avisos"].append(
                    f"En {tipo} no consta la relación con la cuenta. Se "
                    "rellena con «Qué cambió» cuando haya las dos listas "
                    "completas del mismo día.")
                break
        if meta.get("completa") is False:
            datos["avisos"].append(
                f"La captura de {tipo} del {_fecha_de(ultima)} está "
                "INCOMPLETA: las cifras y las tablas se quedan cortas.")
        elif meta.get("completa") is None:
            datos["avisos"].append(
                f"La captura de {tipo} del {_fecha_de(ultima)} no tiene "
                "metadatos, así que no consta si está completa.")

    if not datos["listas"]:
        datos["avisos"].append(
            "No hay ninguna captura de esta cuenta todavía.")

    cambios, dias = calcular_cambios_de_relacion()
    datos["cambios"] = cambios
    if len(dias) >= 2:
        datos["comparado"] = [dias[-2], dias[-1]]
    return datos














# La línea de órdenes vive en ordenes.py desde la v6.7.
#
# El alias no es un adorno: al ejecutar `python instagram_listas.py`, este
# módulo se llama __main__, así que el `import instagram_listas` de dentro
# de ordenes cargaría una SEGUNDA copia del motor — con su propio
# presupuesto, sus propias constantes y su propia sesión en caché. Con el
# alias hay una sola, se ejecute como programa o se importe como
# biblioteca.
def _traer_ordenes():
    import sys
    sys.modules.setdefault("instagram_listas", sys.modules[__name__])
    import ordenes
    return ordenes


# Se re-exportan por su nombre de siempre: la ventana y el banco de pruebas
# llaman a `m.cmd_contar`, y no tienen por qué enterarse de la mudanza.
_ORDENES = _traer_ordenes()
for _nombre in dir(_ORDENES):
    if _nombre.startswith("cmd_") or _nombre == "main":
        globals()[_nombre] = getattr(_ORDENES, _nombre)


if __name__ == "__main__":
    main()
