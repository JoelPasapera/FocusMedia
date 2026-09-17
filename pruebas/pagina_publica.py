"""
Lo que se saca sin iniciar sesión
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def f51_privada_es_de_esta_cuenta():
    print("\n[F51] «Privada» tiene que ser de ESTA cuenta")

    # El fallo, visto funcionando: una cuenta PÚBLICA salía avisada como
    # privada mientras descargaba 89 de 303 seguidores sin problema. La
    # comprobación era `'"is_private":true' in html` sobre la página
    # ENTERA, y una página de perfil lleva JSON de muchas cuentas
    # —sugeridas, relacionadas—. Bastaba con que cualquiera fuera privada.
    publica_con_vecina_privada = (
        '{"id":"777","username":"yomira","is_private":false,"x":1}'
        ' relleno ' * 3 + '{"id":"999","username":"otra","is_private":true}')
    check(m.privada_en_html(publica_con_vecina_privada, "777", "yomira")
          is False, "una privada en la misma página no contagia a la tuya")

    check(m.privada_en_html('{"id":"777","is_private":true}', "777") is True,
          "y una privada de verdad se detecta")
    check(m.privada_en_html('{"username":"yomira","is_private":true}',
                            "", "yomira") is True,
          "atando por nombre de usuario cuando no hay id")

    # Si en la ventana caben dos valores, gana el MÁS CERCANO al ancla.
    # Mirar primero el «true» devolvía el del vecino: el mismo error otra
    # vez, en pequeño.
    cerca = ('{"id":"999","is_private":true},{"id":"777","is_private":false}')
    check(m.privada_en_html(cerca, "777") is False,
          "con dos valores cerca, manda el pegado a esta cuenta")

    # Y lo que no se puede atar NO se afirma. Es la misma regla que
    # la_sigo, tres líneas más abajo en el mismo return.
    check(m.privada_en_html('{"is_private":true}', "777", "yomira") is None,
          "sin poder atarlo a esta cuenta: None, «no consta»")
    check(m.privada_en_html("", "777") is None, "y una página vacía, igual")

    # El aviso distingue los TRES estados, no dos
    check("No consta" in (m.avisar_si_privada({"privada": None}) or ""),
          "y se avisa de que no consta, en vez de decir que es privada")
    check(m.avisar_si_privada({"privada": False}) is None,
          "de una pública no se avisa nada")


def f57_mirar_sin_sesion():
    print("\n[F57] Mirar sin sesión: qué ahorra y qué no")
    carpeta = prep(TEMPORAL("f57"))
    m._PRESUPUESTO = None

    PAGINA = ('<meta property="og:description" content="303 Followers, '
              '509 Following, 10 Posts - Ver fotos" />')
    MURO = "<html>Inicia sesión para continuar</html>"
    BLOQUE = ('{"username":"x","pk":"7","follower_count":969,'
              '"following_count":96}')

    class R:
        def __init__(self, texto, codigo=200):
            self.text, self.status_code = texto, codigo

    def responde(texto, codigo=200):
        class S:
            headers: dict = {}

            def get(self, *a, **k):
                return R(texto, codigo)
        m.sesion_anonima = lambda: S()

    # La página real trae un BLOQUE ESTRUCTURADO, no solo las metas, y sus
    # cifras son exactas mientras que la meta REDONDEA. Visto en un HTML
    # de verdad: og:description decía 970 y 98; el bloque, 969 y 96.
    # 'vigilar' compara totales, así que con cifras redondeadas un cambio
    # de dos personas es invisible y uno de redondeo parece un cambio.
    bloque = ('{"username":"ana","full_name":"Ana","pk":"4084018523",'
              '"follower_count":969,"following_count":96,'
              '"is_private":false,"is_verified":true}')
    d = m.perfil_de_la_pagina(bloque, "ana")
    check(d["seguidores"] == 969 and d["seguidos"] == 96,
          "del bloque salen las cifras exactas")
    check(d["id"] == "4084018523",
          "y el id numérico, que la meta no trae y el export tampoco")
    check(d["privada"] is False and d["verificada"] is True,
          "privada y verificada, sin la heurística de la ventana de texto")
    check(m.perfil_de_la_pagina("<html>nada</html>", "ana") == {},
          "sin bloque no se inventa nada")
    check(m.perfil_de_la_pagina("", "ana") == {},
          "ni con la página vacía")

    # Lo que no esté NO se rellena con ceros
    parcial = m.perfil_de_la_pagina('{"follower_count":10}')
    check("seguidos" not in parcial,
          "lo que falta se omite, no se pone a cero")

    # El parser de las metas es el MISMO que usa la vía con sesión: dos
    # parsers del mismo texto acabarían diciendo cosas distintas.
    check(m.cifras_de_la_pagina(PAGINA) == (303, 509, 10),
          "lee los tres totales de la página")
    check(m.cifras_de_la_pagina("") == (0, 0, 0), "y sin meta, ceros")

    responde(PAGINA)
    antes = m._presupuesto().get("hechas", 0)
    p = m.perfil_anonimo("x")
    check(p and p["seguidores"] == 303, "trae los totales sin sesión")
    # Y si solo hay metas, se dice que los totales NO son de fiar: están
    # redondeados, y quien decida sobre ellos tiene que saberlo.
    check(p["totales_fiables"] is False,
          "con solo metas, los totales se marcan como no fiables")
    check(p["la_sigo"] is None,
          "y sin sesión no consta la relación: None, no False")

    responde('{"username":"x","follower_count":969,'
             '"following_count":96,"pk":"7"}')
    exacto = m.perfil_anonimo("x")
    check(exacto["seguidores"] == 969 and exacto["totales_fiables"],
          "con el bloque, exactas y fiables")
    check(m._presupuesto().get("hechas", 0) == antes,
          "sin tocar el presupuesto de la sesión")
    # Pero NO es gratis: la IP es la misma, así que tiene su contador.
    # Van dos peticiones hasta aquí —las del parser puro no salen a la
    # red— y las dos tienen que estar contadas.
    check(m._presupuesto()["anonimas"] == 2,
          f"con su contador: la IP es media cuota "
          f"({m._presupuesto()['anonimas']})")

    # El muro de inicio de sesión no puede devolver ceros: serían mentira.
    responde(MURO)
    check(m.perfil_anonimo("x") is None,
          "con el muro devuelve None, no ceros")
    responde("", 429)
    check(m.perfil_anonimo("x") is None, "y un 429 tampoco cuela")

    # Su freno propio: al llegar al tope de la hora, deja de pedir
    responde(PAGINA)
    hora = m.datetime.now().strftime("%H")
    m._presupuesto()["anonimas_por_hora"] = {hora: m.TOPE_HORA_ANONIMO}
    check(m.perfil_anonimo("x") is None, "y se frena solo por horas")

    # solo_mirar: sin sesión si se puede, con sesión si no, y DICE cuál
    m._presupuesto()["anonimas_por_hora"] = {hora: 0}
    # El 429 de arriba dejó la vía en cuarentena, que es lo que tiene que
    # hacer. Se levanta para seguir probando lo de abajo.
    m._BLOQUEOS.clear()
    m.perfil = lambda s, u: {"username": u, "seguidores": 1, "seguidos": 1}

    responde(BLOQUE)
    p, gasto = m.solo_mirar(None, "x")
    check(p and not gasto and p["seguidores"] == 969,
          "con cifras exactas, mirar no gasta sesión")

    # Con SOLO metas no vale, aunque haya respuesta: están redondeadas, y
    # quien decide si toca descargar compara totales. Con aproximados
    # vería cambios que no hubo y se perdería los de una o dos personas.
    responde(PAGINA)
    p, gasto = m.solo_mirar(None, "x")
    check(gasto, "con cifras redondeadas se gasta sesión, y se dice")

    responde(MURO)
    p, gasto = m.solo_mirar(None, "x")
    check(p and gasto,
          "y con el muro también: se tira de la sesión")

    # La cabecera de la API no va en una petición de página normal: pedir
    # una página pública con x-ig-app-id encima es lo que no hace nadie.
    m.sesion_anonima = FUNCIONES_REALES["sesion_anonima"]
    cabeceras = m.sesion_anonima().headers
    check("x-ig-app-id" not in cabeceras,
          "la sesión anónima no manda cabeceras de la API")
    check("Cookie" not in cabeceras and not m.sesion_anonima().cookies,
          "y no lleva ninguna cookie")


def f58_pagina_real_sin_sesion():
    print("\n[F58] La página real de una cuenta pública, sin cookies")
    muestra = Path("pruebas/pagina_publica.html")
    if not muestra.exists():
        print("  (saltado: falta pruebas/pagina_publica.html)")
        return
    html = muestra.read_text(encoding="utf-8", errors="replace")

    # Es el HTML de verdad de una cuenta pública en incógnito. Con datos
    # inventados, el redondeo de las metas no aparece nunca: la meta y el
    # bloque dirían lo mismo. Hizo falta un archivo real para verlo.
    d = m.perfil_de_la_pagina(html)
    check(d["seguidores"] == 969 and d["seguidos"] == 96,
          f"cifras exactas del bloque ({d['seguidores']}/{d['seguidos']})")
    check(d["id"] == "4084018523", "el id numérico, que la meta no trae")
    check(d["privada"] is False, "y si es privada, sin heurísticas")
    check("Psicóloga" in d["biografia"], "la biografía, con sus tildes")
    check(d["foto"].startswith("https://"), "y la foto")

    # Las metas de la MISMA página redondean: 970 y 98.
    check(m.cifras_de_la_pagina(html)[:2] == (970, 98),
          "las metas de esa misma página dicen 970 y 98")

    # Con sesión se usaba la meta, así que en pantalla salía 970 mientras
    # Instagram decía 969. Ahora se toma el bloque, campo a campo.
    m._pedir_texto = lambda s, ruta, referer=None: html
    p = m.perfil_desde_html(None, "angie.albinco.18.26")
    check((p["seguidores"], p["seguidos"]) == (969, 96),
          f"la vía con sesión ya no redondea ({p['seguidores']})")
    # El bloque de esta página NO trae publicaciones; la meta sí. Con «si
    # falta todo, usa las metas» salían 0 teniendo 17 delante.
    check(p["publicaciones"] == 17,
          f"y lo que el bloque no trae sale de la meta ({p['publicaciones']})")
    check(p["totales_fiables"] is True, "marcados como fiables")

    # Y todo lo demás que la página trae y antes se tiraba.
    d = m.perfil_de_la_pagina(html, "angie.albinco.18.26")
    check(d.get("threads") == "angie.albinco.18.26",
          "la cuenta de Threads, si la tiene")
    check(d.get("memorial") is False and d.get("desactivada") is False,
          "y si es conmemorativa o está desactivada: explican por qué una "
          "cuenta deja de aparecer, y no se sabían de ninguna otra forma")
    check("enlace" not in d or isinstance(d["enlace"], str),
          "el enlace de la biografía cuando lo hay")
    # Con enlace y pronombres de verdad
    con_mas = ('{"username":"ana","follower_count":1,'
               '"pronouns":["she","her"],'
               '"bio_links":[{"url":"https://ejemplo.com","title":"web"}]}')
    e = m.perfil_de_la_pagina(con_mas, "ana")
    check(e["enlace"] == "https://ejemplo.com", "el enlace se extrae")
    check(e["pronombres"] == "she, her", "y los pronombres, juntos")

    # Lo que NO hay, y conviene que siga constando: la página pública no
    # trae likes, comentarios ni fechas de publicaciones.
    for ausente in ("like_count", "comment_count", "taken_at"):
        check(ausente not in html,
              f"la página no trae {ausente}: eso sigue costando sesión")
    check(p["id"] == "4084018523", "con el id que antes se adivinaba")


def f59_repaso_de_la_via_sin_sesion():
    print("\n[F59] Lo que se encontró repasando la vía sin sesión")
    import ast as _ast
    import shutil

    # 1. Dos claves iguales en un diccionario: gana la última, sin aviso.
    #    `totales_fiables` se escribió dos veces en el mismo literal, así
    #    que la corrección no hacía nada Y la prueba pasaba por casualidad.
    repetidas = []
    for archivo in sorted(Path(".").glob("*.py")):
        for nodo in _ast.walk(_ast.parse(archivo.read_text(encoding="utf-8"))):
            if not isinstance(nodo, _ast.Dict):
                continue
            claves = [k.value for k in nodo.keys
                      if isinstance(k, _ast.Constant)
                      and isinstance(k.value, str)]
            if len(claves) != len(set(claves)):
                repetidas.append(f"{archivo.name}:{nodo.lineno}")
    check(not repetidas, f"sin claves repetidas en diccionarios: {repetidas}")

    # 2. El bloque tiene que ser de ESTA cuenta. Una página lleva JSON de
    #    varias —sugeridas, relacionadas— y quedarse con el primero
    #    devolvía los datos del vecino. Es el fallo de 'privada' otra vez.
    dos = ('{"username":"sugerida","pk":"111","follower_count":5}'
           + "x" * 3000
           + '{"username":"la_tuya","pk":"999","follower_count":969,'
             '"following_count":96}')
    check(m.perfil_de_la_pagina(dos, "la_tuya")["seguidores"] == 969,
          "coge el bloque de la cuenta pedida")
    check(m.perfil_de_la_pagina(dos, "sugerida")["seguidores"] == 5,
          "y el de la otra si se pide la otra")
    check(m.perfil_de_la_pagina(dos, "nadie") == {},
          "si no puede atarlo, NO devuelve el del vecino")

    # 3. La vía sin sesión respeta el cortafuegos. Sin esto seguía pidiendo
    #    tras cinco 429 seguidos, que es justo lo que alarga un bloqueo.
    carpeta = prep(TEMPORAL("f59"))
    m._PRESUPUESTO = None
    m._BLOQUEOS.clear()

    class R:
        text, status_code = "", 429

    class S:
        headers: dict = {}

        def get(self, *a, **k):
            return R()

    m.sesion_anonima = lambda: S()
    for _ in range(5):
        m.perfil_anonimo("x")
    check(m._presupuesto()["anonimas"] == 1,
          f"tras un 429 no se insiste ({m._presupuesto()['anonimas']} de 5)")
    m._BLOQUEOS.clear()


def f1_foto_de_perfil():
    print("\n[F1] La foto de perfil: sale gratis y no puede estropear nada")

    class S:
        cookies = {}

        def __init__(self, cuerpo=JPEG_FALSO, codigo=200):
            self.cuerpo, self.codigo, self.pedidas = cuerpo, codigo, []

        def get(self, url, headers=None, params=None, timeout=None):
            self.pedidas.append(url)
            padre = self

            class R:
                status_code = padre.codigo
                content = padre.cuerpo
                text = HTML_CON_FOTO
            return R()

    # --- de dónde sale la URL, en las tres vías ---
    p = m.perfil_desde_html(S(), "cuenta.ejemplo")
    check(p["foto"].endswith("_nc_ht=scontent.cdninstagram.com"),
          "la página del perfil da la foto por og:image")
    check("&amp;" not in p["foto"],
          "y el &amp; se deshace: escapado, la URL no vale")

    m.pedir = lambda *a, **k: {"data": {"user": {
        "id": "9", "username": "t", "profile_pic_url": "https://cdn/n.jpg",
        "profile_pic_url_hd": "https://cdn/hd.jpg",
        "edge_followed_by": {"count": 5}, "edge_follow": {"count": 6}}}}
    check(m._perfil_desde_api(S(), "t")["foto"] == "https://cdn/hd.jpg",
          "la API da la buena de las dos cuando llegan las dos")

    # --- la descarga ---
    ses = S()
    # El gasto se mide PEGADO a la descarga: leer el perfil de arriba ya
    # costó una petición, y medir desde cero contaba esa y no esta.
    antes = m._presupuesto().get("hechas", 0)
    destino = m.guardar_foto(ses, "cuenta.ejemplo", "https://cdn/foto.jpg")
    check(destino is not None and destino.exists(), "guarda la foto en disco")
    check(destino.read_bytes() == JPEG_FALSO, "y guarda lo que llegó")

    # No es una petición a la API: no cuenta para el tope diario, porque va
    # al CDN de imágenes y no es lo que devuelve los 429.
    check(m._presupuesto().get("hechas", 0) == antes,
          "y no gasta presupuesto: el CDN no es la API")

    # --- lo que NO debe guardar ---
    check(m.guardar_foto(S(b"<html>error</html>"), "x", "https://c/a.jpg")
          is None, "una página de error no se escribe como .jpg")
    check(m.guardar_foto(S(JPEG_FALSO, 404), "x", "https://c/a.jpg") is None,
          "un 404 tampoco")
    check(m.guardar_foto(S(), "x", "http://c/a.jpg") is None,
          "ni una URL sin cifrar")
    check(m.guardar_foto(S(), "x", "") is None, "ni una URL vacía")
    check(m.guardar_foto(S(b"\xff\xd8" + b"0" * 5_000_000), "x",
                         "https://c/a.jpg") is None,
          "ni algo desmesurado para ser una foto de perfil")

    # --- cuándo se vuelve a bajar ---
    check(m.foto_al_dia("cuenta.ejemplo"), "recién bajada, no se repite")
    viejo = m.ruta_foto("cuenta.ejemplo")
    os.utime(viejo, (0, time.time() - (m.DIAS_FOTO + 1) * 86400))
    check(not m.foto_al_dia("cuenta.ejemplo"),
          f"pasados {m.DIAS_FOTO} días, sí")
    check(not m.foto_al_dia("cuenta_que_no_existe"),
          "y sin archivo, evidentemente")

    # --- es decoración: si falla, no puede tumbar la lectura del perfil ---
    class SinRed(S):
        def get(self, url, headers=None, params=None, timeout=None):
            if "cdn" in url or "scontent" in url:
                raise requests.RequestException("sin red")
            return super().get(url, headers, params, timeout)

    m.pedir = lambda *a, **k: (_ for _ in ()).throw(m.Bloqueado("429"))
    p = m.perfil(SinRed(), "cuenta.ejemplo")
    check(p["id"] == "51234567890",
          "si la foto no se puede bajar, el perfil se lee igual")


def f2_publicaciones_y_nombre():
    print("\n[F2] El tercer número y el nombre, que ya venían dentro")

    def html(desc, titulo):
        return ('<!DOCTYPE html><html><head>'
                f'<meta property="og:description" content="{desc}" />'
                f'<meta property="og:title" content="{titulo}" />'
                '<script>{"profile_id":"51234567890"}</script>'
                '</head><body></body></html>')

    class S:
        cookies = {}

        def __init__(self, pagina):
            self.pagina = pagina

        def get(self, url, headers=None, params=None, timeout=None):
            padre = self

            class R:
                status_code = 200
                text = padre.pagina
                content = b""
            return R()

    # El número de publicaciones estaba en la MISMA cadena de la que ya se
    # sacaban los otros dos, y se descartaba.
    p = m.perfil_desde_html(S(html(
        "4,820 Followers, 611 Following, 137 Posts - See Instagram photos",
        "Nombre Visible (@cuenta.ejemplo) • Instagram photos and videos")),
        "cuenta.ejemplo")
    check(p["publicaciones"] == 137,
          f"lo saca en inglés ({p['publicaciones']})")
    check(p["nombre"] == "Nombre Visible", f"y el nombre ({p['nombre']!r})")

    p = m.perfil_desde_html(S(html(
        "4.820 seguidores, 611 seguidos, 1.2K publicaciones - Ve fotos",
        "Nombre Visible (@cuenta.ejemplo) • Fotos y videos de Instagram")),
        "cuenta.ejemplo")
    check(p["publicaciones"] == 1200, "también en español y abreviado")

    # El motivo de usar og:title y no cortar og:description por "de": un
    # nombre con preposiciones dentro se partiría por la mitad.
    p = m.perfil_desde_html(S(html(
        "10 seguidores, 2 seguidos, 3 publicaciones - Ve fotos y videos de "
        "Instagram de Ana de la Cruz (@ana.cruz)",
        "Ana de la Cruz (@ana.cruz) • Instagram")), "ana.cruz")
    check(p["nombre"] == "Ana de la Cruz",
          f"un nombre con 'de' dentro llega entero ({p['nombre']!r})")

    p = m.perfil_desde_html(S(html("1 Followers, 1 Following, 1 Posts",
                                   "Ana &amp; Co (@ana.co) • Instagram")),
                            "ana.co")
    check(p["nombre"] == "Ana & Co", f"las entidades HTML se deshacen "
                                     f"({p['nombre']!r})")

    p = m.perfil_desde_html(S(html("1 Followers, 1 Following, 1 Posts",
                                   "ana.co (@ana.co) • Instagram photos")),
                            "ana.co")
    check(p["nombre"] == "", "si el título es el usuario, no hay nombre")

    # Sin el paréntesis no se sabe dónde acaba el nombre: mejor ninguno que
    # "ana.co • Instagram photos" metido en el campo del nombre.
    p = m.perfil_desde_html(S(html("1 Followers, 1 Following, 1 Posts",
                                   "ana.co • Instagram photos")), "ana.co")
    check(p["nombre"] == "", "y sin el paréntesis no se inventa uno")

    p = m.perfil_desde_html(S(html("sin números aquí", "x (@y) • z")), "y")
    check(p["publicaciones"] == 0, "si no llega, cero y sin romperse")

    m.pedir = lambda *a, **k: {"data": {"user": {
        "id": "9", "username": "t", "full_name": "Te",
        "edge_owner_to_timeline_media": {"count": 42},
        "edge_followed_by": {"count": 5}, "edge_follow": {"count": 6}}}}
    check(m._perfil_desde_api(S(""), "t")["publicaciones"] == 42,
          "la API lo trae en el mismo objeto que ya se leía")

    # --- lo que se guarda de la cuenta ---
    m.guardar_estado("t", {"username": "t", "nombre": "Te",
                           "publicaciones": 42, "biografia": "hola"})
    # Una lectura por la página no trae biografía. Si pisara lo guardado, se
    # perdería un dato que ya se había pagado con una petición.
    m.guardar_estado("t", {"username": "t", "nombre": "Te",
                           "publicaciones": 43})
    e = m.leer_estado("t")
    check(e["publicaciones"] == 43, "el estado se actualiza")
    check(e.get("biografia") == "hola", "y lo que no llega no se pierde")
    check(m.leer_estado("no_existe") == {}, "sin archivo devuelve vacío")

    # --- la serie diaria, con archivos ya escritos ---
    m.CARPETA.mkdir(parents=True, exist_ok=True)
    m._ruta_totales().write_text(
        "fecha,seguidores,seguidos\n2026-09-01,300,500\n", encoding="utf-8")
    filas = m._filas_totales()
    check(filas[0] == ["2026-09-01", "300", "500", ""],
          f"una fila vieja de tres columnas se lee entera ({filas[0]})")
    check(filas[0][3] != "0",
          "y sin publicaciones queda VACÍA: un cero sería una caída")

    m._anotar_conteo({"seguidores": 305, "seguidos": 500,
                      "publicaciones": 137})
    conteo = m._ultimo_conteo()
    check(conteo["publicaciones"] == 137, "el conteo del día las anota")
    check(conteo["seguidores"] == 305, "y sigue trayendo lo de siempre")
    check(m._filas_totales()[0][3] == "",
          "la fila vieja sigue vacía tras reescribir el archivo")

    m._anotar_conteo({"seguidores": 306, "seguidos": 500, "publicaciones": 0})
    check("publicaciones" not in (m._ultimo_conteo() or {}),
          "un cero del buscador se anota como 'no se sabe', no como cero")


def f7_el_crudo_del_perfil():
    print("\n[F7] La respuesta del perfil se guarda en vez de tirarse")
    prep(TEMPORAL("f7"))

    destino = m.guardar_crudo_perfil("t", "<html>una pagina</html>", "html")
    check(destino is not None and destino.exists(), "se guarda")
    check(destino.parent == m.carpeta_cuenta(),
          "dentro de la carpeta de la cuenta, no en la raíz")
    check(destino.read_text(encoding="utf-8") == "<html>una pagina</html>",
          "tal cual llegó, sin tocar")

    # Una al día: la página ocupa megas y cambia poco
    destino.write_text("<html>la de hoy</html>", encoding="utf-8")
    m.guardar_crudo_perfil("t", "<html>otra vez</html>", "html")
    check(destino.read_text(encoding="utf-8") == "<html>la de hoy</html>",
          "y no se reescribe dos veces el mismo día")

    check(m.guardar_crudo_perfil("t", "", "html") is None,
          "una respuesta vacía no crea archivo")


PRUEBAS = [
    f51_privada_es_de_esta_cuenta,
    f57_mirar_sin_sesion,
    f58_pagina_real_sin_sesion,
    f59_repaso_de_la_via_sin_sesion,
    f1_foto_de_perfil,
    f2_publicaciones_y_nombre,
    f7_el_crudo_del_perfil,
]
