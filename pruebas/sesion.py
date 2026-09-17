"""
La sesión: cookies, verificación, cortafuegos
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def y1_cortafuegos_tras_429():
    print("\n[Y1] Tras un 429 no debe salir NI UNA petición más")
    m._BLOQUEOS.clear()
    llamadas = [0]

    class R:
        def __init__(self, c):
            self.status_code = c

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            llamadas[0] += 1
            return R(429)

    ses = S()
    try:
        m.pedir(ses, "/api/v1/x/")
        check(False, "debería lanzar Bloqueado")
    except m.Bloqueado as e:
        check("429" in str(e), "el primer 429 se reporta")
    check(llamadas[0] == 1, "y llegó a hacerse la petición")

    check(m.espera_pendiente("/api/v1/x/") > 800,
          "ese endpoint queda en cuarentena ~15 min")
    check(m.espera_pendiente("/api/v1/otro/") == 0,
          "pero los demás endpoints siguen libres")

    # Las siguientes ni salen a la red
    for _ in range(5):
        try:
            m.pedir(ses, "/api/v1/x/")
        except m.Bloqueado as e:
            mensaje = str(e)
    check(llamadas[0] == 1,
          f"ninguna petición más durante el enfriamiento ({llamadas[0]})")
    check("min;" in mensaje, f"y dice cuánto falta ({mensaje[:60]})")

    m._BLOQUEOS.clear()
    check(m.espera_pendiente("/api/v1/x/") == 0,
          "al limpiar el estado se puede otra vez")


def y2_401_no_amplifica():
    print("\n[Y2] Un 401 ya no dispara tres peticiones de sondeo")
    m._BLOQUEOS.clear()
    llamadas = []

    class R:
        status_code = 401

        def json(self):
            return {}

    class S:
        cookies = {"ds_user_id": "1"}

        def get(self, url, **k):
            llamadas.append(url)
            return R()

    try:
        m.pedir(S(), "/api/v1/x/")
    except m.Bloqueado as e:
        check("Puede ser" in str(e), "se trata como bloqueo, con plazo claro")
    except m.SesionInvalida:
        check(False, "no debería darla por muerta sin pruebas")

    check(len(llamadas) == 1,
          f"una sola petición, no cuatro ({len(llamadas)})")
    check(m.espera_pendiente("/api/v1/x/") > 200,
          "y deja ese endpoint en cuarentena corta")
    m._BLOQUEOS.clear()


def y3_sesion_se_reutiliza():
    print("\n[Y3] La sesión no se re-verifica en cada acción")
    m._BLOQUEOS.clear()
    m._SESION_CACHE = None
    m._SESION_HASTA = 0.0
    m._VERIFICACION_OK = None

    verificaciones = [0]
    original = m.comprobar_sesion
    m.comprobar_sesion = lambda s: (verificaciones.__setitem__(
        0, verificaciones[0] + 1), ("yo", "viva"))[1]
    m._cookies_guardadas = lambda: {"sessionid": "x", "ds_user_id": "1"}
    m._cookies_del_navegador = lambda: {"sessionid": "x", "ds_user_id": "1"}
    m._guardar_cookies = lambda c: None

    s1 = m.crear_sesion()
    check(verificaciones[0] == 1, "la primera vez sí verifica")

    s2 = m.crear_sesion()
    s3 = m.crear_sesion()
    check(verificaciones[0] == 1,
          f"las siguientes reutilizan ({verificaciones[0]} verificaciones)")
    check(s1 is s2 is s3, "y es la misma sesión")

    m.crear_sesion(forzar=True)
    check(verificaciones[0] == 2, "'Importar sesión' sí fuerza una nueva")

    m.comprobar_sesion = original
    m._SESION_CACHE = None


def y4_endpoint_de_verificacion_recordado():
    print("\n[Y4] No repetir los endpoints que ya se sabe que fallan")
    m._VERIFICACION_OK = None
    m._BLOQUEOS.clear()
    pedidas = []

    class R:
        def __init__(self, c, d=None):
            self.status_code, self._d = c, d or {}

        def json(self):
            return self._d

    class S:
        cookies = {"ds_user_id": "42"}

        def get(self, url, timeout=None):
            pedidas.append(url)
            if "friendships" in url:
                return R(200, {"users": []})
            return R(404)          # los dos primeros no existen

    u, e = m.comprobar_sesion(S())
    check(e == "viva" and u == "#42", "encuentra el que funciona")
    primera_vuelta = len(pedidas)
    check(primera_vuelta == 3, f"probó los tres ({primera_vuelta})")

    pedidas.clear()
    u, e = m.comprobar_sesion(S())
    check(e == "viva", "sigue funcionando")
    check(len(pedidas) == 1,
          f"la segunda vez va directo al bueno ({len(pedidas)} peticiones)")
    check("friendships" in pedidas[0], "y es el correcto")
    m._VERIFICACION_OK = None


def y5_referer_del_perfil():
    print("\n[Y5] El perfil se pide con el Referer que manda el navegador")
    m._BLOQUEOS.clear()
    visto = {}

    class R:
        status_code = 200

        def json(self):
            return {"data": {"user": {
                "id": "1", "username": "x", "full_name": "",
                "edge_followed_by": {"count": 5},
                "edge_follow": {"count": 7},
                "is_private": False, "followed_by_viewer": True}}}

    class S:
        cookies = {}

        def get(self, url, params=None, headers=None, timeout=None):
            visto["url"] = url
            visto["headers"] = headers or {}
            return R()

    p = m.perfil(S(), "cuenta.ejemplo")
    check(p["seguidores"] == 5, "devuelve el perfil")
    check(visto["headers"].get("Referer", "").endswith("/cuenta.ejemplo/"),
          f"con el Referer del perfil ({visto['headers'].get('Referer')})")


def y6_gasto_total_de_una_sesion():
    print("\n[Y6] Cuántas peticiones cuesta ahora abrir y contar")
    m._BLOQUEOS.clear()
    m._SESION_CACHE = None
    m._SESION_HASTA = 0.0
    m._VERIFICACION_OK = None
    pedidas = []

    class R:
        def __init__(self, c, d=None):
            self.status_code, self._d = c, d or {}

        def json(self):
            return self._d

    class Cookies(dict):
        def set(self, k, v, domain=None):
            self[k] = v

    class S:
        def __init__(self):
            self.headers = {}
            self.cookies = Cookies({"ds_user_id": "42"})

        def get(self, url, params=None, headers=None, timeout=None):
            pedidas.append(url)
            if "friendships" in url:
                return R(200, {"users": []})
            if "web_profile_info" in url:
                return R(200, {"data": {"user": {
                    "id": "9", "username": "x", "full_name": "",
                    "edge_followed_by": {"count": 5},
                    "edge_follow": {"count": 7},
                    "is_private": False, "followed_by_viewer": True}}})
            return R(404)

    ses = S()
    m._cookies_guardadas = lambda: {"sessionid": "x", "ds_user_id": "42"}
    m._cookies_del_navegador = lambda: {"sessionid": "x", "ds_user_id": "42"}
    m._guardar_cookies = lambda c: None
    original = requests.Session
    requests.Session = lambda: ses
    try:
        m.crear_sesion(forzar=True)      # "Importar sesión"
        importar = len(pedidas)
        m.crear_sesion()                 # "Contar" reutiliza
        m.perfil(ses, "alguien")
        total = len(pedidas)

        # Con la vía ya aprendida, la siguiente verificación no sondea
        pedidas.clear()
        m._SESION_CACHE = None
        m._VERIFICACION_OK = None
        m.crear_sesion(forzar=True)
        reaprendida = len(pedidas)
    finally:
        requests.Session = original

    check(importar == 3,
          f"la primera vez prueba los tres endpoints ({importar})")
    check(total == 4, f"contar añade solo 1: el perfil (total {total})")
    check(reaprendida == 1,
          f"ya aprendida, la verificación cuesta 1 ({reaprendida})")
    print(f"        antes eran 7 para lo mismo; ahora {total}")
    m._SESION_CACHE = None


def r1_sesion_no_bloquea():
    print("\n[R1] Sesión no verificable no debe bloquear el arranque")

    class Resp:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {}

    class Ses:
        def __init__(self, codes):
            self.codes = codes
            self.cookies = {"ds_user_id": "42"}

        def get(self, url, timeout=None):
            return Resp(self.codes.pop(0) if self.codes else 404)

    # Todos los endpoints caídos -> desconocida, NUNCA muerta
    u, e = m.comprobar_sesion(Ses([404, 404, 404]))
    check(e == "desconocida", f"todos 404 -> desconocida (dio '{e}')")

    # Un 401 explícito sí es sesión muerta
    u, e = m.comprobar_sesion(Ses([401, 401, 401]))
    # «rechazada» y no «muerta»: un 401 dice que Instagram frena AHORA, no
    # que las cookies estén caducadas. Confundirlo hacía reimportar las
    # mismas cookies y cobrar otro 401 por el mismo sitio.
    check(e == "rechazada", f"401 -> rechazada (dio '{e}')")

    # El primer endpoint cae pero el segundo responde -> viva
    class SesMixta(Ses):
        def get(self, url, timeout=None):
            if "current_user" in url:
                return Resp(404)
            r = Resp(200)
            r.json = lambda: {"user": {"username": "yo"}}
            return r

    u, e = m.comprobar_sesion(SesMixta([]))
    check(e == "viva" and u == "yo", "cae el 1º pero responde el 2º -> viva")

    # El tercero (friendships) también sirve como prueba de vida
    class SesTercera(Ses):
        def get(self, url, timeout=None):
            if "friendships" not in url:
                return Resp(500)
            r = Resp(200)
            r.json = lambda: {"users": []}
            return r

    u, e = m.comprobar_sesion(SesTercera([]))
    check(e == "viva" and u == "#42",
          "solo responde friendships -> viva, marcado como id")

    # Red caída del todo -> desconocida, no muerta
    class SesSinRed(Ses):
        def get(self, url, timeout=None):
            raise requests.ConnectionError("sin red")

    u, e = m.comprobar_sesion(SesSinRed([]))
    check(e == "desconocida", f"sin red -> desconocida (dio '{e}')")


def r2_cursor_cero():
    print("\n[R2] Un cursor 0 no debe cortar la descarga")
    prep(TEMPORAL("r2"))

    class IG0:
        def pedir(self, s, ruta, params=None, referer=None):
            cur = (params or {}).get("max_id")
            if cur is None:
                return {"users": [{"pk": "a", "username": "a", "full_name": ""}],
                        "next_max_id": 0}          # entero 0, falsy
            return {"users": [{"pk": "b", "username": "b", "full_name": ""}],
                    "next_max_id": None}

    m.pedir = IG0().pedir
    m.descargar(None, perfil(2, 0), "seguidores")
    n = len(leer(m._ruta_captura("seguidores")))
    check(n == 2, f"cursor entero 0 -> sigue paginando (obtuvo {n} de 2)")

    prep(TEMPORAL("r2b"))

    class IGStr0(IG0):
        def pedir(self, s, ruta, params=None, referer=None):
            cur = (params or {}).get("max_id")
            if cur is None:
                return {"users": [{"pk": "a", "username": "a", "full_name": ""}],
                        "next_max_id": "0"}        # cadena "0"
            return {"users": [{"pk": "b", "username": "b", "full_name": ""}],
                    "next_max_id": None}

    m.pedir = IGStr0().pedir
    m.descargar(None, perfil(2, 0), "seguidores")
    n = len(leer(m._ruta_captura("seguidores")))
    check(n == 2, f'cursor cadena "0" -> sigue paginando (obtuvo {n} de 2)')


def r3_no_comparar_truncadas():
    print("\n[R3] No comparar capturas incompletas sin --forzar")
    prep(TEMPORAL("r3"))
    captura("seguidores", "2026-09-01",
            [(f"u{i}", "", str(i)) for i in range(1000)], completa=False)
    captura("seguidores", "2026-09-02",
            [(f"u{i}", "", str(i)) for i in range(2000)], completa=True)

    m.comparar("seguidores")
    informe = (m.carpeta_cuenta()
               / f"cambios_{m.OBJETIVO}_seguidores_2026-09-02.csv")
    check(not informe.exists(),
          "no genera informe cuando una captura está incompleta")

    m.comparar("seguidores", forzar=True)
    check(informe.exists(), "con --forzar sí lo genera")
    check(len(leer(informe)) == 1000, "y avisa de que no es fiable")


def w1_html_como_alternativa():
    print("\n[W1] Leer el perfil de su página cuando la API falla")
    m._BLOQUEOS.clear()

    class S:
        cookies = {}

        def get(self, url, headers=None, params=None, timeout=None):
            class R:
                status_code = 200
                text = HTML_PERFIL
            return R()

    p = m.perfil_desde_html(S(), "cuenta.ejemplo")
    check(p["id"] == "51234567890", f"saca el identificador ({p['id']})")
    check(p["seguidores"] == 4820, f"y los seguidores ({p['seguidores']})")
    check(p["seguidos"] == 611, f"y los seguidos ({p['seguidos']})")
    check(p["origen"] == "página del perfil", "dice de dónde salió")

    # Números abreviados y en español
    check(m._numero("4,820") == 4820, "4,820 -> 4820")
    check(m._numero("4.820") == 4820, "4.820 -> 4820")
    check(m._numero("1.2M") == 1200000, "1.2M -> 1200000 (no 12M)")
    check(m._numero("1,2M") == 1200000, "1,2M en español -> 1200000")
    check(m._numero("15K") == 15000, "15K -> 15000")
    check(m._numero("1.234.567") == 1234567, "1.234.567 -> 1234567")
    check(m._numero("2M") == 2000000, "2M sin decimales")
    check(m._numero("basura") == 0, "lo que no se entiende -> 0")
    check(m._numero("") == 0, "cadena vacía -> 0")

    # Sin identificador debe fallar claro, no devolver basura
    class SinId(S):
        def get(self, *a, **k):
            class R:
                status_code = 200
                text = "<html>nada</html>"
            return R()

    try:
        m.perfil_desde_html(SinId(), "x")
        check(False, "debería lanzar NoEncontrado")
    except m.NoEncontrado:
        check(True, "sin identificador lanza NoEncontrado")


def w2_cadena_de_alternativas():
    print("\n[W2] Si la API falla, se prueban las otras vías")
    m._BLOQUEOS.clear()
    usadas = []

    def api_bloqueada(s, ruta, params=None, referer=None):
        usadas.append("api")
        raise m.Bloqueado("HTTP 429")

    m.pedir = api_bloqueada
    m.perfil_desde_html = lambda s, u: (usadas.append("html"),
                                        {"id": "9", "username": u,
                                         "nombre": "", "seguidores": 10,
                                         "seguidos": 20, "privada": False,
                                         "la_sigo": True,
                                         "origen": "página del perfil"})[1]

    p = m.perfil(None, "alguien")
    check(usadas == ["api", "html"],
          f"prueba la API y cae a la página ({usadas})")
    check(p["id"] == "9", "y devuelve el perfil igualmente")
    check(m.via_recordada("perfil") == "página del perfil",
          "recuerda cuál funcionó")

    # La segunda vez ya no gasta una petición en fallar a propósito
    usadas.clear()
    m.perfil(None, "alguien")
    check(usadas == ["html"],
          f"va directo a la vía buena ({usadas})")

    # Carpeta nueva = se olvida lo aprendido, que vive en disco
    m.CARPETA = Path(tempfile.mkdtemp(prefix="w2_"))
    m._PRESUPUESTO = None
    usadas.clear()
    m.perfil_desde_html = lambda s, u: (usadas.append("html"),
                                        (_ for _ in ()).throw(
                                            m.Bloqueado("429")))[1]
    m.perfil_desde_busqueda = lambda s, u: (usadas.append("buscador"),
                                            {"id": "7", "username": u,
                                             "nombre": "", "seguidores": 0,
                                             "seguidos": 0, "privada": False,
                                             "la_sigo": True,
                                             "origen": "buscador"})[1]
    p = m.perfil(None, "alguien")
    check(usadas == ["api", "html", "buscador"], f"llega al buscador ({usadas})")
    check(p["id"] == "7", "y sirve")

    # Si fallan las tres, un solo error que las resume
    m.perfil_desde_busqueda = lambda s, u: (_ for _ in ()).throw(
        m.Bloqueado("429"))
    try:
        m.perfil(None, "alguien")
        check(False, "debería fallar")
    except m.Bloqueado as e:
        check("ninguna vía" in str(e), "el error resume los tres intentos")

    # Un perfil inexistente NO debe reintentar por las otras vías
    usadas.clear()
    m.pedir = lambda s, r, params=None, referer=None: (
        usadas.append("api"), {"data": {"user": None}})[1]
    try:
        m.perfil(None, "noexiste")
        check(False, "debería lanzar NoEncontrado")
    except m.NoEncontrado:
        check(usadas == ["api"],
              f"no insiste si la cuenta no existe ({usadas})")


def w3_diagnostico():
    print("\n[W3] El diagnóstico mide sin suponer")
    prep(TEMPORAL("w3d"))
    m._BLOQUEOS.clear()
    m.PAUSA_DETALLE_MIN = m.PAUSA_DETALLE_MAX = 0

    class Cookies(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    class S:
        cookies = Cookies({"ds_user_id": "42"})

    m.crear_sesion = lambda forzar=False: S()
    m._dormir = lambda s: None

    def pedir_mixto(s, ruta, params=None, referer=None):
        if "web_profile_info" in ruta:
            raise m.Bloqueado("HTTP 429 en 'users/web_profile_info'")
        if "current_user" in ruta:
            raise m.NoEncontrado("404")
        if "topsearch" in ruta:
            raise m.Bloqueado("HTTP 429")
        return {"users": []}

    m.pedir = pedir_mixto
    m.perfil_desde_html = lambda s, u: {"id": "9"}

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_diagnostico(None)
    salida = buf.getvalue()

    check("OK" in salida, "marca lo que funciona")
    check("BLOQUEADO" in salida, "y distingue lo bloqueado de lo que falla")
    check("Funcionan 2 de 5" in salida,
          f"cuenta bien ({[l for l in salida.splitlines() if 'Funcionan' in l]})")
    check("Puedes descargar las listas" in salida,
          "y concluye que se puede seguir: listas y perfil responden")

    # Si el endpoint de listas cae, el veredicto cambia
    def todo_roto(s, ruta, params=None, referer=None):
        raise m.Bloqueado("HTTP 429")

    m.pedir = todo_roto
    m.perfil_desde_html = lambda s, u: (_ for _ in ()).throw(
        m.Bloqueado("429"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_diagnostico(None)
    check("No responde nada" in buf.getvalue(),
          "si no responde nada, lo dice claro")


def r5_errores_separados():
    print("\n[R5] Perfil inexistente no debe decir 'sesión no válida'")

    class R:
        status_code = 200

        def json(self):
            return {"data": {"user": None}}

    class S:
        def get(self, *a, **k):
            return R()

    m_pedir = m.pedir
    m.pedir = lambda s, ruta, params=None, referer=None: {"data": {"user": None}}
    try:
        m.perfil(S(), "noexiste")
        check(False, "debería lanzar NoEncontrado")
    except m.NoEncontrado:
        check(True, "perfil inexistente -> NoEncontrado")
    except m.SesionInvalida:
        check(False, "sigue lanzando SesionInvalida")
    m.pedir = m_pedir

    class R404:
        status_code = 404

        def json(self):
            return {}

    class S404:
        cookies = {}

        def get(self, *a, **k):
            return R404()

    try:
        PEDIR_REAL(S404(), "/api/v1/x/")
        check(False, "404 debería lanzar NoEncontrado")
    except m.NoEncontrado:
        check(True, "HTTP 404 -> NoEncontrado")
    except m.SesionInvalida:
        check(False, "404 sigue lanzando SesionInvalida")


def r11_volcado_de_fallo():
    print("\n[R11] Al romperse, se guarda con qué repararlo")
    prep(TEMPORAL("r11"))

    class R:
        status_code = 400
        text = '{"message":"checkpoint_required","extra":"detalles largos"}'
        headers = {"content-type": "application/json",
                   "set-cookie": "sessionid=SECRETO; Path=/",
                   "x-ratelimit": "0"}

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            return R()

    try:
        m.pedir(S(), "/api/v1/x/", {"count": 50})
    except m.PeticionRechazada:
        pass

    volcados = list(m.CARPETA.glob("fallo_*.json"))
    check(len(volcados) == 1, f"se genera un archivo ({len(volcados)})")

    d = json.loads(volcados[0].read_text(encoding="utf-8"))
    check(d["codigo_http"] == 400, "con el código")
    check("checkpoint_required" in d["respuesta"], "y la respuesta completa")
    check(d["parametros"] == {"count": 50}, "y lo que se pidió")
    check("rutas_en_uso" in d, "y qué rutas estaba usando")

    # Lo más importante: NUNCA la sesión
    crudo = volcados[0].read_text(encoding="utf-8")
    check("SECRETO" not in crudo,
          "la cookie de sesión NO se guarda: el archivo puede compartirse")
    check("set-cookie" not in crudo.lower(), "ni la cabecera que la trae")
    check("x-ratelimit" in crudo, "pero sí las cabeceras útiles")

    # También al cambiar la forma
    prep(TEMPORAL("r11b"))
    try:
        m.validar("lista", {"items": []}, "/api/v1/friendships/1/followers/")
    except m.RespuestaInesperada:
        pass
    volcados = list(m.CARPETA.glob("fallo_*.json"))
    check(len(volcados) == 1, "un cambio de forma también se vuelca")
    d = json.loads(volcados[0].read_text(encoding="utf-8"))
    check(d["tipo"] == "forma inesperada", "identificado como tal")
    check("campos_en_uso" in d, "con los nombres que se esperaban")


def f20_sesion_pegada():
    print("\n[F20] Pegar la sesión a mano, si el navegador no la suelta")
    SES = "9982027586%3A4JbZbUkGXwBpUO%3A1%3AAYjRbzJ7zjjcW2Qp"

    # Acepta lo que la gente pega de verdad, como el campo de la cuenta
    for etiqueta, texto in (
            ("el valor a secas", SES),
            ("con su nombre", f"sessionid={SES}"),
            ("entre comillas", f'"{SES}"'),
            ("con espacios", f"  sessionid = {SES}  "),
            ("una cookie por línea", f"csrftoken=TOK\nsessionid={SES}"),
            ("el JSON del propio archivo",
             '{"guardado": "x", "cookies": {"sessionid": "%s"}}' % SES)):
        c = m.leer_cookies_pegadas(texto)
        check(c.get("sessionid") == SES, f"{etiqueta}")

    entera = (f"Cookie: ig_did=ABC; mid=XYZ; csrftoken=TOK; "
              f"ds_user_id=9982027586; sessionid={SES}")
    c = m.leer_cookies_pegadas(entera)
    check(c.get("sessionid") == SES and c.get("csrftoken") == "TOK",
          "la cabecera Cookie entera, tal cual se copia del navegador")
    check(c.get("mid") == "XYZ" and c.get("ig_did") == "ABC",
          "y se queda con las demás, que ayudan a parecer un navegador")

    # El id de la cuenta NO hay que pedirlo: va dentro del sessionid
    check(m.leer_cookies_pegadas(SES)["ds_user_id"] == "9982027586",
          "el id sale del propio sessionid, delante del %3A")
    check("ds_user_id" not in m.leer_cookies_pegadas("raro%3Aloquesea"),
          "y si ahí no hay un número, no se inventa uno")

    check(m.leer_cookies_pegadas("no tengo ni idea de qué pegar") == {},
          "lo que no lleva sesión no cuela")
    check(m.leer_cookies_pegadas("") == {} and
          m.leer_cookies_pegadas(None) == {}, "ni lo vacío")
    check(m.leer_cookies_pegadas("csrftoken=TOK") == {},
          "ni las cookies sueltas sin la que importa")

    # --- guardar tira la sesión en caché -------------------------------
    prep(TEMPORAL("f20"))
    m._SESION_CACHE = "la de antes"
    m._SESION_HASTA = time.monotonic() + 600
    m._VERIFICACION_OK = "algo"
    cookies = m.guardar_sesion_pegada(f"sessionid={SES}")

    check(cookies.get("sessionid") == SES, "se guarda")
    check(m._cookies_guardadas().get("sessionid") == SES,
          "y queda en el archivo de sesión")
    # La sesión se reutiliza 10 minutos sin verificar (v2.9): sin tirarla,
    # la cookie recién pegada no se usaría hasta dentro de un rato y
    # parecería que no ha servido de nada.
    check(m._SESION_CACHE is None,
          "la sesión en caché se tira: si no, seguiría usando la vieja")
    check(m._VERIFICACION_OK is None, "y la vía verificada también")

    check(m.guardar_sesion_pegada("basura") == {},
          "una palabra corta no pasa por sesión, ni toca el archivo")
    # Pero si algún día cambia el formato, un token largo sigue valiendo:
    # rechazar de más sería peor que aceptar de más.
    largo = "x" * 40
    check(m.leer_cookies_pegadas(largo).get("sessionid") == largo,
          "y un token largo sin separador sí pasa, por si cambia el formato")


def f21_varias_sesiones():
    print("\n[F21] Varias sesiones guardadas, una activa")
    carpeta = prep(TEMPORAL("f21"))
    m.ARCHIVO_SESION = carpeta / "sesion_instagram.json"
    A = "111111%3AaaaAAA%3A1%3Azzz"
    B = "222222%3AbbbBBB%3A1%3Ayyy"

    m.guardar_sesion_pegada(f"sessionid={A}", "principal")
    m.guardar_sesion_pegada(f"sessionid={B}", "secundaria")
    datos = m.leer_sesiones()
    check(sorted(datos["cuentas"]) == ["111111", "222222"],
          "se guardan las dos, con el id de cada cuenta como clave")
    check(datos["activa"] == "222222", "la última pegada queda activa")
    check(m._cookies_guardadas()["sessionid"] == B,
          "y es la que se usa de verdad")

    check(m.activar_sesion("111111"), "se puede cambiar")
    check(m._cookies_guardadas()["sessionid"] == A, "y cambia de verdad")
    check(m.leer_sesiones()["activa"] == "111111", "queda anotado")
    check(not m.activar_sesion("no-existe"), "una que no existe no cuela")

    # Cambiar de sesión NO da presupuesto nuevo, y es a propósito: el
    # límite es de la sesión Y de la IP, y la IP no cambia por cambiar de
    # cuenta. Que el contador siga contando es lo que impide usar esto para
    # multiplicar peticiones.
    m._presupuesto()["hechas"] = 200
    antes = m.queda_presupuesto()
    m.activar_sesion("222222")
    check(m.queda_presupuesto() == antes,
          "cambiar de sesión no devuelve presupuesto: es del sitio")

    # Pegar de nuevo la misma cuenta la actualiza, no la duplica: el caso
    # corriente es que caducó y se pega otra.
    m.guardar_sesion_pegada(f"sessionid=222222%3AnuevaCookie%3A1%3Aqqq")
    check(len(m.leer_sesiones()["cuentas"]) == 2, "no se duplica la cuenta")
    check("nuevaCookie" in m._cookies_guardadas()["sessionid"],
          "y se queda con la cookie nueva")
    check(m.leer_sesiones()["cuentas"]["222222"]["etiqueta"] == "secundaria",
          "conservando el nombre que se le puso")

    check(m.quitar_sesion("222222"), "se puede borrar")
    check(m.leer_sesiones()["activa"] == "111111",
          "y al borrar la activa se pasa a otra, no se queda sin ninguna")
    m.quitar_sesion("111111")
    check(not m.ARCHIVO_SESION.exists(),
          "borrada la última, no queda sesión en disco")


def f22_una_sola_a_la_vez():
    print("\n[F22] La cookie activa es UNA, y viaja sola")
    carpeta = prep(TEMPORAL("f22"))
    m.ARCHIVO_SESION = carpeta / "sesion_instagram.json"
    A = "111111%3AaaaAAA%3A1%3Azzz"
    B = "222222%3AbbbBBB%3A1%3Ayyy"
    m.guardar_sesion_pegada(f"sessionid={A}")
    m.guardar_sesion_pegada(f"sessionid={B}")

    # En el archivo que lee crear_sesion() solo puede haber una: mezclar
    # cookies de dos cuentas en la misma petición no es «usar dos», es
    # mandar una petición incoherente.
    en_uso = json.loads(m.ARCHIVO_SESION.read_text(encoding="utf-8"))
    check(list(en_uso["cookies"]).count("sessionid") == 1,
          "un solo sessionid en la sesión que se usa")
    check(A not in json.dumps(en_uso), "y no se cuela la de la otra cuenta")


def f23_no_perder_la_cuenta():
    print("\n[F23] Lo que protege a la cuenta, no lo que la apura")
    prep(TEMPORAL("f23"))

    # --- un 401 no es un 429: es el escalón anterior al checkpoint ------
    m.anotar_rechazo("perfil")
    check(m._presupuesto()["rechazos"] == 1, "el rechazo se cuenta aparte")
    check(m._presupuesto()["bloqueos"] == 1,
          "y también como bloqueo, para que las pausas se doblen")
    check(m.factor_prudencia() == 2.0, "las pausas se doblan de verdad")

    # Al segundo se para en seco: insistir cuando no te reconocen la
    # sesión es lo que convierte un mal día en una cuenta cerrada.
    m.anotar_rechazo("perfil")
    try:
        m.pedir(None, "/api/v1/x/")
        check(False, "debería haberse parado")
    except m.SinPresupuesto as e:
        check("no está reconociendo la sesión" in str(e),
              "se para y dice que NO es un límite de ritmo")
        check("navegador" in str(e),
              "y qué hacer: abrir Instagram y mirar si hay algo")

    # --- una ráfaga no es lo mismo que un día de trabajo ----------------
    prep(TEMPORAL("f23b"))
    m._PRESUPUESTO = None       # carpeta nueva, contadores nuevos
    p = m._presupuesto()
    hora = m.datetime.now().strftime("%H")
    p["por_hora"] = {hora: m.TOPE_HORA}
    try:
        m.pedir(None, "/api/v1/x/")
        check(False, "debería frenar por la hora")
    except m.Bloqueado as e:
        check("en esta hora" in str(e),
              "250 peticiones en diez minutos no es lo mismo que en un día")
    p["por_hora"] = {hora: 0}
    check(m.queda_presupuesto() > 0, "y en la hora siguiente se sigue")

    # --- modo prudente: el tope solo baja -------------------------------
    dia = {"dia": "x", "hechas": 250, "tope": 250, "bloqueos": 0}
    check(m.ajustar_tope(dia)["tope"] > 250, "en normal, tantea hacia arriba")
    check(m.ajustar_tope(dia, {"prudente": True})["tope"] == 250,
          "en prudente NO sube: quien ya perdió una cuenta no quiere que un "
          "programa tantee con la siguiente")
    bajado = m.ajustar_tope(dict(dia, bloqueos=1), {"prudente": True})
    check(bajado["tope"] < 250, "pero sigue bajando cuando toca")
    check(bajado["prudente"] is True, "y no se pierde el modo por el camino")

    prep(TEMPORAL("f23c"))
    m._PRESUPUESTO = None

    class Args:
        prudente, normal, fijar = True, False, None
    m.cmd_limite(Args())
    check(m._limite().get("prudente") is True, "el interruptor se guarda")
    Args.prudente, Args.normal = False, True
    m.cmd_limite(Args())
    check(m._limite().get("prudente") is False, "y se puede quitar")


def f33_sesiones_en_su_carpeta():
    print("\n[F33] Las sesiones, en su carpeta y sin activar nada sola")
    carpeta = prep(TEMPORAL("f33"))
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"

    check(m._ruta_sesiones().parent == m.CARPETA_SESIONES,
          "la tienda vive al lado de la activa, en la misma carpeta")

    # --- lo que estaba suelto en la raíz se recoge ---------------------
    raiz = m.CARPETA_SESIONES.parent
    A = "111111%3AaaaAAA%3A1%3Azzz"
    (raiz / "sesion_instagram.json").write_text(
        json.dumps({"cookies": {"sessionid": A}}), encoding="utf-8")
    movidos = m.migrar_sesiones()
    check(movidos == ["sesion_instagram.json"], f"se mueve ({movidos})")
    check(m._cookies_guardadas()["sessionid"] == A, "y se sigue leyendo")
    check(not (raiz / "sesion_instagram.json").exists(),
          "sin dejar copia en la raíz, que es lo que se quería evitar")
    check(m.migrar_sesiones() == [], "y no se repite")

    # Mover una sesión no es como mover un CSV: si el destino ya existe, no
    # se pisa. Perderla obliga a sacarla otra vez del navegador.
    (raiz / "sesion_instagram.json").write_text(
        json.dumps({"cookies": {"sessionid": "otra%3Adistinta"}}),
        encoding="utf-8")
    m.migrar_sesiones()
    check(m._cookies_guardadas()["sessionid"] == A,
          "si ya hay una en la carpeta, la de la raíz no la pisa")
    (raiz / "sesion_instagram.json").unlink()

    # --- la búsqueda: se guardan todas, pero NO se cambia la que se usa -
    B = "222222%3AbbbBBB%3A1%3Ayyy"
    C = "333333%3AcccCCC%3A1%3Axxx"
    m.guardar_sesion_pegada(f"sessionid={B}", "la que estaba en uso")
    antes = m.leer_sesiones()["activa"]

    hallazgos = [
        {"navegador": "firefox", "cookies": m.leer_cookies_pegadas(A),
         "id": "111111", "motivo": ""},
        {"navegador": "chrome", "cookies": {}, "id": "",
         "motivo": "cookies cifradas"},
        {"navegador": "brave", "cookies": m.leer_cookies_pegadas(C),
         "id": "333333", "motivo": ""},
    ]
    guardadas = m.registrar_hallazgos(hallazgos)
    check(sorted(guardadas) == ["111111", "333333"],
          f"guarda las dos que traían sesión ({guardadas})")
    check("222222" in m.leer_sesiones()["cuentas"],
          "sin borrar la que ya estaba")
    check(m.leer_sesiones()["activa"] == antes,
          "y NO cambia la que se usa: encontrar tres cuentas y ponerse a "
          "usar otra sin avisar sería para desconfiar")
    check(m.leer_sesiones()["cuentas"]["111111"]["etiqueta"] == "firefox",
          "cada una queda etiquetada con el navegador donde estaba")

    # Si no había ninguna, sí se activa la primera: quedarse sin sesión
    # habiendo encontrado una no ayuda a nadie.
    prep(TEMPORAL("f33b"))
    m.CARPETA_SESIONES = Path("/tmp/f33b/sesiones")
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    m.registrar_hallazgos(hallazgos)
    check(m.leer_sesiones()["activa"] in ("111111", "333333"),
          "sin ninguna previa, se activa una de las encontradas")

    # --- la carpeta está en .gitignore, que es lo que la hace segura ----
    ignorado = Path(".gitignore").read_text(encoding="utf-8")
    check("sesiones/" in ignorado,
          "la CARPETA entera está ignorada, no archivo por archivo")


def f34_elegir_cuenta():
    print("\n[F34] Las cuentas se pueden reconocer para poder elegirlas")
    carpeta = prep(TEMPORAL("f34"))
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"

    m.guardar_sesion_pegada("sessionid=111111%3Aa%3A1%3Az", "firefox")
    m.guardar_sesion_pegada("sessionid=222222%3Ab%3A1%3Ay", "pegada a mano")

    # Sin nombre, el id: al menos es estable y distingue una de otra.
    disponibles = {s["clave"]: s for s in m.sesiones_disponibles()}
    check(disponibles["111111"]["titulo"] == "cuenta id 111111",
          "sin comprobar, se enseña el id")
    check(disponibles["111111"]["de_donde"] == "firefox",
          "y de dónde salió, que es la otra pista para reconocerla")
    check(not disponibles["111111"]["comprobada"], "y que no se ha probado")

    # El nombre se aprende al comprobar la sesión, y ya no se olvida.
    m.anotar_usuario_de_sesion("111111", "cuentazer")
    disponibles = {s["clave"]: s for s in m.sesiones_disponibles()}
    check(disponibles["111111"]["titulo"] == "@cuentazer",
          "una vez comprobada, se enseña el nombre")
    check(disponibles["111111"]["comprobada"], "y cuándo se comprobó")

    # La activa va primero: es la que se mira antes.
    m.activar_sesion("111111")
    primera = m.sesiones_disponibles()[0]
    check(primera["clave"] == "111111" and primera["activa"],
          "la que se usa encabeza la lista")

    # Anotar el mismo nombre dos veces no reescribe el archivo cada vez
    antes = m.leer_sesiones()["cuentas"]["111111"]["comprobada"]
    m.anotar_usuario_de_sesion("111111", "cuentazer")
    check(m.leer_sesiones()["cuentas"]["111111"]["comprobada"] == antes,
          "y no se reescribe si no ha cambiado nada")
    m.anotar_usuario_de_sesion("no-existe", "x")
    check(True, "anotar sobre una que no existe no revienta")


def f35_por_que_falla_cada_navegador():
    print("\n[F35] «No lo tienes» y «no te deja» no son lo mismo")

    # Mensajes REALES de browser_cookie3, de una búsqueda en Windows.
    reales = {
        "Could not find LibreWolf profile directory": "no_instalado",
        "Failed to find cookies for Chromium browser": "no_instalado",
        "Can not find Safari cookie file": "no_instalado",
        # Un fallo de la propia biblioteca cuando el navegador no está:
        # para quien mira, sigue siendo «no lo tienes».
        "join() argument must be str, bytes, or os.PathLike object, not "
        "NoneType": "no_instalado",
        # Y el que de verdad importa: Chrome en Windows.
        "This operation requires admin. Please run as admin.": "cifradas",
        "Failed to decrypt the cipher text": "cifradas",
        "Permission denied": "cifradas",
        "database is locked": "bloqueado",
    }
    for mensaje, esperado in reales.items():
        check(m.clasificar_fallo(mensaje) == esperado,
              f"{esperado:<13} <- {mensaje[:42]}")
    check(m.clasificar_fallo("") == "otro" and
          m.clasificar_fallo(None) == "otro", "lo desconocido no se inventa")

    # El agrupado: arriba lo que hay, luego lo que se puede arreglar, y en
    # una línea lo que ni está. Diez líneas iguales no dejan ver cuál es
    # la que importa.
    hallazgos = [
        {"navegador": "firefox", "cookies": {"sessionid": "x"}, "id": "1",
         "clase": "encontrada", "motivo": ""},
        {"navegador": "chrome", "cookies": {}, "id": "",
         "clase": "cifradas", "motivo": "requires admin"},
        {"navegador": "edge", "cookies": {}, "id": "",
         "clase": "sin_sesion", "motivo": ""},
        {"navegador": "brave", "cookies": {}, "id": "",
         "clase": "no_instalado", "motivo": ""},
        {"navegador": "opera", "cookies": {}, "id": "",
         "clase": "no_instalado", "motivo": ""},
    ]
    r = m.resumir_busqueda(hallazgos)
    check([h["navegador"] for h in r["encontradas"]] == ["firefox"],
          "las encontradas, primero")
    check(sorted(h["navegador"] for h in r["accionables"])
          == ["chrome", "edge"],
          "lo accionable aparte: instalado pero sin dar la sesión")
    check(r["ausentes"] == ["brave", "opera"],
          "y los que ni están, juntos en una línea")

    # Cada clase accionable tiene que decir QUÉ hacer, no solo qué pasó
    for clase in ("cifradas", "bloqueado", "sin_sesion"):
        check(len(m.CONSEJOS.get(clase, "")) > 20,
              f"'{clase}' explica qué hacer")
    check("sessionid" in m.CONSEJOS["cifradas"],
          "y el caso de Chrome dice la salida: pegarla a mano")


def f39_comprobar_sin_cambiarse():
    print("\n[F39] Comprobar una sesión sin perder la que estás usando")
    carpeta = prep(TEMPORAL("f39"))
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    A = "111111%3Aaaa%3A1%3Az"
    B = "222222%3Abbb%3A1%3Ay"
    m.guardar_sesion_pegada(f"sessionid={A}", "la de siempre")
    m.guardar_sesion_pegada(f"sessionid={B}", "la otra")
    m.activar_sesion("111111")

    # La sesión se construye aparte, con SUS cookies
    s = m.sesion_con({"sessionid": B, "csrftoken": "TOK"})
    galletas = {c.name: c.value for c in s.cookies}
    check(galletas.get("sessionid") == B, "lleva las cookies que se le dan")
    check(s.headers.get("x-csrftoken") == "TOK",
          "y el csrftoken como cabecera, que es para lo que sirve")
    check("Instagram" in s.headers["User-Agent"] or
          "Mozilla" in s.headers["User-Agent"], "con cabeceras de navegador")

    # Comprobar la OTRA no puede tocar la activa. Antes, para saber de
    # quién era una sesión había que activarla, y eso tiraba la que
    # estabas usando junto con su verificación.
    m.comprobar_sesion = lambda ses: ("otracuenta", "ok")
    m._SESION_CACHE, m._SESION_HASTA = "viva", time.monotonic() + 600
    usuario, estado = m.comprobar_guardada("222222")

    check(usuario == "otracuenta" and estado == "ok", "devuelve de quién es")
    check(m.leer_sesiones()["activa"] == "111111",
          "y la activa sigue siendo la que era")
    check(m._SESION_CACHE == "viva",
          "sin tirar la sesión en uso ni su verificación")
    check(m.leer_sesiones()["cuentas"]["222222"]["usuario"] == "otracuenta",
          "el nombre queda anotado: es lo que hace legible la lista")

    check(m.comprobar_guardada("no-existe")[0] is None,
          "una que no existe no revienta")


def f40_comprobar_cuenta_lo_que_gasta():
    print("\n[F40] Comprobar una sesión cuenta lo que gasta")
    prep(TEMPORAL("f40"))
    m._PRESUPUESTO = None

    class R:
        status_code = 200

        def json(self):
            return {"user": {"username": "cuentazer"}}

    class S:
        cookies = {"ds_user_id": "111"}
        headers: dict = {}

        def get(self, *a, **k):
            return R()

    # comprobar_sesion pide con s.get() directo y NO por pedir(), a
    # propósito: aquí se quiere observar el 401 en vez de tratarlo como un
    # corte. Pero tiene que contar igual. Daba igual mientras pasaba una
    # vez cada diez minutos; con un botón que comprueba varias seguidas,
    # el presupuesto mentiría.
    antes = m._presupuesto().get("hechas", 0)
    usuario, estado = m.comprobar_sesion(S())
    gastadas = m._presupuesto()["hechas"] - antes
    check(usuario == "cuentazer", "comprueba y devuelve el nombre")
    check(gastadas >= 1, f"y anota lo que ha gastado ({gastadas})")
    check(m._presupuesto().get("por_endpoint"),
          "con su endpoint, que es lo que distingue un bloqueo de volumen")

    # Y si no queda presupuesto, no se salta el tope por esta puerta
    m._presupuesto()["hechas"] = m.tope_diario()
    antes = m._presupuesto()["hechas"]
    m.comprobar_sesion(S())
    check(m._presupuesto()["hechas"] == antes,
          "sin presupuesto no pide: no hay puerta de atrás al tope")


def f41_conectar_es_cambiar_y_comprobar():
    print("\n[F41] Conectar deja la sesión lista, no a medias")
    carpeta = prep(TEMPORAL("f41"))
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    m.guardar_sesion_pegada("sessionid=111111%3Aa%3A1%3Az", "firefox")
    m.guardar_sesion_pegada("sessionid=222222%3Ab%3A1%3Ay", "chrome")
    m.activar_sesion("111111")
    m.comprobar_sesion = lambda ses: ("otracuenta", "ok")

    # Lo que hace el botón: activar y comprobar, en ese orden. Activar sin
    # comprobar te dejaba con la cabecera diciendo «Sin sesión» y sin saber
    # si aquello servía.
    class Args:
        comprobar_estas = ["222222"]
        pegar = listar = usar = quitar = buscar = comprobar = etiqueta = None

    m.activar_sesion("222222")
    m.cmd_sesion(Args())

    check(m.leer_sesiones()["activa"] == "222222", "queda activa")
    ficha = m.leer_sesiones()["cuentas"]["222222"]
    check(ficha.get("usuario") == "otracuenta", "y comprobada, con nombre")
    check(m._cookies_guardadas()["sessionid"].startswith("222222"),
          "y es la que se usa de verdad")

    # De donde lee la cabecera: de lo guardado, no de una frase impresa
    activa = next(s for s in m.sesiones_disponibles() if s["activa"])
    check(activa["titulo"] == "@otracuenta",
          "el estado sale de lo guardado, no de leer la consola")


def f60_un_401_no_es_una_cookie_caducada():
    print("\n[F60] Un 401 no significa que las cookies estén mal")
    import ast as _ast

    # Pasó de verdad: la sesión funcionaba en el navegador y el programa
    # dijo «caducó», reimportó las MISMAS cookies del navegador, cobró
    # otro 401 y acabó en «no sirve (muerta)». Insistir durante un freno
    # por otra puerta es justo lo que lo alarga.
    check(issubclass(m.SesionInvalida, m.ErrorPrevisto),
          "una sesión rechazada es algo previsto, no un fallo")
    for clase in (m.Bloqueado, m.NoEncontrado, m.PeticionRechazada,
                  m.SinPresupuesto, m.RespuestaInesperada):
        check(issubclass(clase, m.ErrorPrevisto),
              f"{clase.__name__} también")

    fuente = Path("instagram_listas.py").read_text(encoding="utf-8")
    check('"rechazada"' in fuente and '(None, "muerta")' not in fuente,
          "el veredicto es «rechazada», no «muerta»")
    # Y NO se reimporta sola: las del navegador son las mismas.
    check("return crear_sesion(forzar=True)" not in fuente,
          "no se reimporta automáticamente tras un rechazo")

    # El 401 de la verificación cuenta como rechazo. Sin esto se saltaba
    # la parada del día que existe desde la v6.0 justo para no escalar.
    i = fuente.index("def comprobar_sesion")
    cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
    check("anotar_rechazo" in cuerpo,
          "y un 401 al verificar cuenta como rechazo del día")

    # En la ventana, lo previsto se recoge ANTES que lo genérico; si no,
    # nunca entraría y seguiría saliendo la traza.
    gui = _ast.parse(Path("instagram_gui.py").read_text(encoding="utf-8"))
    ordenes_except = []
    for nodo in _ast.walk(gui):
        if not isinstance(nodo, _ast.Try):
            continue
        tipos = [h.type.attr if isinstance(h.type, _ast.Attribute)
                 else (h.type.id if isinstance(h.type, _ast.Name) else "todo")
                 for h in nodo.handlers]
        if "ErrorPrevisto" in tipos and "Exception" in tipos:
            ordenes_except.append(
                tipos.index("ErrorPrevisto") < tipos.index("Exception"))
    check(ordenes_except and all(ordenes_except),
          "lo previsto se recoge antes que lo genérico")


def f62_el_volcado_no_lleva_credenciales():
    print("\n[F62] Un fallo_*.json se anuncia compartible: que lo sea")
    carpeta = prep(TEMPORAL("f62"))
    m.OBJETIVO = "t"

    # El cuerpo de la respuesta entraba TAL CUAL. El filtro solo quitaba
    # cabeceras por su nombre, así que un secreto dentro del cuerpo, de
    # los parámetros o del detalle se guardaba entero en un archivo que el
    # propio programa dice que se puede mandar a cualquiera.
    m.volcar_fallo("x", ruta_usada="/api/x",
                   cuerpo={"sessionid": "SECRETO_REUTILIZABLE"},
                   detalle="sessionid=SEGUNDO",
                   params={"p": "csrftoken=TERCERO"},
                   cabeceras={"X-Raro": "sessionid=CUARTO"})
    volcados = list(carpeta.rglob("fallo_*.json"))
    check(volcados, "se escribe el volcado")
    texto = volcados[0].read_text(encoding="utf-8")
    for secreto in ("SECRETO_REUTILIZABLE", "SEGUNDO", "TERCERO", "CUARTO"):
        check(secreto not in texto, f"no se escapa {secreto}")
    # Y lo que SÍ tiene que quedarse: sin esto el volcado no sirve.
    check("/api/x" in texto, "la ruta sí se conserva: es lo que se mira")

    # El id de la cuenta no abre nada y es lo que dice de quién era el
    # error: no se oculta a propósito.
    import registro
    check("998877" in registro.limpiar_secretos("ds_user_id=998877"),
          "el ds_user_id se conserva, que no es una credencial")

    # Dos fallos en el mismo segundo no pueden pisarse: el primero suele
    # ser el que explica la causa.
    for _ in range(3):
        m.volcar_fallo("x", ruta_usada="/api/y")
    check(len(list(carpeta.rglob("fallo_*.json"))) == 4,
          f"cuatro volcados, cuatro archivos "
          f"({len(list(carpeta.rglob('fallo_*.json')))})")


def f64_nada_que_se_comparte_lleva_secretos():
    print("\n[F64] Los archivos pensados para compartir, limpios")
    import registro
    carpeta = prep(TEMPORAL("f64"))
    m.OBJETIVO = "t"
    m.recordar_id("t", "1")

    # 1. La página del perfil que se guarda para mirarla sin gastar
    #    peticiones lleva un csrf_token DENTRO. Comprobado sobre una
    #    página real de Instagram, y eso era sin sesión.
    pagina = ('<html>{"csrf_token":"h5HckwiEw6z_jy6jAnmh",'
              '"config":{"viewer":{"username":"x"}},'
              '"follower_count":969}</html>')
    ruta = m.guardar_crudo_perfil("t", pagina, "html")
    if ruta:
        guardado = ruta.read_text(encoding="utf-8")
        check("h5HckwiEw6z_jy6jAnmh" not in guardado,
              "el token no se guarda en crudo_perfil_*.html")
        check("969" in guardado,
              "y los datos sí: sin ellos el archivo no serviría")

    # 2. Las formas en que un secreto puede venir escrito. Las de JSON y
    #    URL-encoded se escapaban: el patrón exigía el separador pegado a
    #    la clave, y en JSON queda «"sessionid":» con la comilla en medio.
    formas = ['{"sessionid": "S3CR3T0"}', "sessionid=S3CR3T0",
              'sessionid%3DS3CR3T0', '{"csrf_token":"S3CR3T0"}',
              '{"authorization":"Bearer S3CR3T0"}',
              '{"lsd":"S3CR3T0"}', "9982027586%3AS3CR3T0abc%3A1"]
    for forma in formas:
        check("S3CR3T0" not in registro.limpiar_secretos(forma),
              f"se oculta en «{forma[:30]}»")

    # 3. Y lo que NO debe ocultarse, porque hace falta para diagnosticar.
    for inocente in ("ds_user_id=998877", "count=50", "/api/v1/friendships/"):
        check(registro.limpiar_secretos(inocente) == inocente,
              f"«{inocente}» se conserva entero")


PRUEBAS = [
    f62_el_volcado_no_lleva_credenciales,
    f64_nada_que_se_comparte_lleva_secretos,
    y1_cortafuegos_tras_429,
    y2_401_no_amplifica,
    y3_sesion_se_reutiliza,
    y4_endpoint_de_verificacion_recordado,
    y5_referer_del_perfil,
    y6_gasto_total_de_una_sesion,
    r1_sesion_no_bloquea,
    r2_cursor_cero,
    r3_no_comparar_truncadas,
    w1_html_como_alternativa,
    w2_cadena_de_alternativas,
    w3_diagnostico,
    r5_errores_separados,
    r11_volcado_de_fallo,
    f20_sesion_pegada,
    f21_varias_sesiones,
    f22_una_sola_a_la_vez,
    f23_no_perder_la_cuenta,
    f33_sesiones_en_su_carpeta,
    f34_elegir_cuenta,
    f35_por_que_falla_cada_navegador,
    f39_comprobar_sin_cambiarse,
    f40_comprobar_cuenta_lo_que_gasta,
    f41_conectar_es_cambiar_y_comprobar,
    f60_un_401_no_es_una_cookie_caducada,
]
