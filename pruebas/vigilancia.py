"""
Vigilar varias cuentas, ritmo y programación
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def z1_lista_de_vigilancia():
    print("\n[Z1] Leer la lista de vigilancia")
    prep(TEMPORAL("z1"))
    check(m.leer_lista_vigilancia() == ([], ["No existe vigilancia_t.txt."]),
          "sin archivo lo dice, no revienta")

    m._ruta_vigilancia().write_text("\n".join([
        "# un comentario",
        "ana",
        "@beto",
        "https://www.instagram.com/carla/",
        "  dani  # con nota al lado",
        "",
        "ana",                       # repetida
        "no vale esto",              # imposible
        "https://www.instagram.com/p/ABC/",
    ]), encoding="utf-8")

    cuentas, avisos = m.leer_lista_vigilancia()
    check(cuentas == ["ana", "beto", "carla", "dani"],
          f"acepta @, URL y comentarios; sin repetir ({cuentas})")
    check(len(avisos) == 2, f"avisa de las dos líneas inválidas ({avisos})")


def z2_tope_duro():
    print("\n[Z2] El tope de cuentas no se puede saltar")
    prep(TEMPORAL("z2"))
    m._ruta_vigilancia().write_text(
        "\n".join(f"cuenta{i}" for i in range(80)), encoding="utf-8")

    cuentas, avisos = m.leer_lista_vigilancia()
    check(len(cuentas) == m.MAX_VIGILANCIA,
          f"recorta a {m.MAX_VIGILANCIA} ({len(cuentas)})")
    check(any("petición" in a for a in avisos),
          "y avisa de que cada una cuesta una petición")


def z3_una_peticion_por_cuenta():
    print("\n[Z3] Exactamente una petición por cuenta, ni una más")
    prep(TEMPORAL("z3"))
    m.PAUSA_DETALLE_MIN = m.PAUSA_DETALLE_MAX = 0
    m._ruta_vigilancia().write_text("ana\nbeto\ncarla\n", encoding="utf-8")

    pedidas = []

    def falso(s, ruta, params=None, referer=None):
        pedidas.append(params.get("username"))
        return {"data": {"user": {
            "username": params["username"], "full_name": "N", "id": "1",
            "biography": "hola\nqué tal", "external_url": "http://x.com",
            "edge_owner_to_timeline_media": {"count": 42},
            "edge_followed_by": {"count": 100},
            "edge_follow": {"count": 50},
            "is_private": False, "is_verified": True,
            "followed_by_viewer": True, "follows_viewer": False}}}

    m.pedir = falso
    m.crear_sesion = lambda forzar=False: None

    class Args:
        crear = solo_listar = False

    m.cmd_detalles(Args())
    check(pedidas == ["ana", "beto", "carla"],
          f"tres cuentas, tres peticiones ({pedidas})")

    filas = leer(m._ruta_detalles())
    check(len(filas) == 3, "tres filas guardadas")
    check(filas[0]["seguidores"] == "100", "extrae los seguidores")
    check(filas[0]["publicaciones"] == "42", "y las publicaciones")
    check(filas[0]["biografia"] == "hola qué tal",
          f"la biografía sin saltos de línea ({filas[0]['biografia']!r})")
    check(filas[0]["verificada"] == "si", "los booleanos como si/no")
    check(filas[0]["enlace"] == "http://x.com", "el enlace externo")


def z4_no_repite_lo_ya_consultado():
    print("\n[Z4] No se vuelve a gastar en quien ya se consultó hoy")
    prep(TEMPORAL("z4"))
    m.PAUSA_DETALLE_MIN = m.PAUSA_DETALLE_MAX = 0
    m._ruta_vigilancia().write_text("ana\nbeto\n", encoding="utf-8")

    pedidas = []

    def falso(s, ruta, params=None, referer=None):
        pedidas.append(params.get("username"))
        return {"data": {"user": {"username": params["username"],
                                  "full_name": "", "id": "1",
                                  "biography": "", "external_url": "",
                                  "edge_followed_by": {"count": 1},
                                  "edge_follow": {"count": 1},
                                  "edge_owner_to_timeline_media": {"count": 1},
                                  "is_private": False}}}

    m.pedir = falso
    m.crear_sesion = lambda forzar=False: None

    class Args:
        crear = solo_listar = False

    m.cmd_detalles(Args())
    check(len(pedidas) == 2, "la primera vez consulta las dos")

    pedidas.clear()
    m.cmd_detalles(Args())
    check(pedidas == [], f"la segunda vez no gasta nada ({pedidas})")

    # Si se añade una nueva, solo se consulta esa
    m._ruta_vigilancia().write_text("ana\nbeto\ncarla\n", encoding="utf-8")
    m.cmd_detalles(Args())
    check(pedidas == ["carla"], f"solo la nueva ({pedidas})")


def z5_para_al_primer_bloqueo():
    print("\n[Z5] Al primer bloqueo se para, sin reintentar")
    prep(TEMPORAL("z5"))
    m.PAUSA_DETALLE_MIN = m.PAUSA_DETALLE_MAX = 0
    m._ruta_vigilancia().write_text(
        "\n".join(f"c{i}" for i in range(10)), encoding="utf-8")

    pedidas = []

    def falso(s, ruta, params=None, referer=None):
        pedidas.append(params.get("username"))
        if len(pedidas) >= 4:
            raise m.Bloqueado("simulado: 429")
        return {"data": {"user": {"username": params["username"],
                                  "full_name": "", "id": "1",
                                  "biography": "", "external_url": "",
                                  "edge_followed_by": {"count": 1},
                                  "edge_follow": {"count": 1},
                                  "edge_owner_to_timeline_media": {"count": 1},
                                  "is_private": False}}}

    m.pedir = falso
    m.crear_sesion = lambda forzar=False: None

    class Args:
        crear = solo_listar = False

    m.cmd_detalles(Args())
    check(len(pedidas) == 4,
          f"para en seco, no insiste con las 6 restantes ({len(pedidas)})")

    filas = leer(m._ruta_detalles())
    check(len(filas) == 3, f"conserva las 3 que sí salieron ({len(filas)})")

    # Al reintentar más tarde, retoma donde iba
    pedidas.clear()

    def bueno(s, ruta, params=None, referer=None):
        pedidas.append(params.get("username"))
        return {"data": {"user": {"username": params["username"],
                                  "full_name": "", "id": "1",
                                  "biography": "", "external_url": "",
                                  "edge_followed_by": {"count": 1},
                                  "edge_follow": {"count": 1},
                                  "edge_owner_to_timeline_media": {"count": 1},
                                  "is_private": False}}}

    m.pedir = bueno
    m.cmd_detalles(Args())
    check(pedidas == [f"c{i}" for i in range(3, 10)],
          f"retoma en la cuarta, sin repetir las tres ({pedidas[:3]}...)")


def z6_solo_listar_no_gasta():
    print("\n[Z6] --solo-listar no hace ninguna petición")
    prep(TEMPORAL("z6"))
    m._ruta_vigilancia().write_text("ana\nbeto\n", encoding="utf-8")

    pedidas = []
    m.pedir = lambda *a, **k: pedidas.append(1)
    sesiones = []
    m.crear_sesion = lambda forzar=False: sesiones.append(1)

    class Args:
        crear = False
        solo_listar = True

    m.cmd_detalles(Args())
    check(pedidas == [], "ninguna petición")
    check(sesiones == [], "ni siquiera abre sesión")


def z7_crear_lista_desde_capturas():
    print("\n[Z7] La lista se siembra con lo que ya sabemos")
    prep(TEMPORAL("z7"))
    # dani entra y sale; beto se fue
    ids = {"ana": "1", "beto": "2", "dani": "4"}
    for dia, us in (("2026-09-01", ["ana", "beto", "dani"]),
                    ("2026-09-02", ["ana", "beto"]),
                    ("2026-09-03", ["ana", "dani"])):
        captura("seguidores", dia, [(u, "", ids[u]) for u in us])

    pedidas = []
    m.pedir = lambda *a, **k: pedidas.append(1)

    class Args:
        crear = True
        solo_listar = False

    m.cmd_detalles(Args())
    check(pedidas == [], "crear la lista no gasta peticiones")

    texto = m._ruta_vigilancia().read_text(encoding="utf-8")
    check("dani" in texto, "propone a quien entra y sale")
    check("beto" in texto, "y a quien se fue")
    check("entra y sale" in texto, "explicando por qué está cada uno")
    check("UNA PETICIÓN" in texto, "y avisa del coste en la cabecera")

    cuentas, _ = m.leer_lista_vigilancia()
    check("ana" not in cuentas, "no propone a quien lleva ahí siempre")

    # No debe pisar una lista que el usuario ya editó
    m._ruta_vigilancia().write_text("solo_esta\n", encoding="utf-8")
    m.cmd_detalles(Args())
    check(m.leer_lista_vigilancia()[0] == ["solo_esta"],
          "no sobrescribe una lista existente")


def z8_respeta_el_cortafuegos():
    print("\n[Z8] Durante un enfriamiento no sale ni una petición")
    prep(TEMPORAL("z8"))
    m._ruta_vigilancia().write_text("ana\nbeto\n", encoding="utf-8")
    m.crear_sesion = lambda forzar=False: None

    llamadas = [0]

    class R:
        status_code = 200

        def json(self):
            llamadas[0] += 1
            return {"data": {"user": None}}

    class S:
        cookies = {}

        def get(self, *a, **k):
            llamadas[0] += 1
            return R()

    m.crear_sesion = lambda forzar=False: S()
    m._marcar_bloqueo("/api/v1/users/web_profile_info/", 900)

    class Args:
        crear = solo_listar = False

    m.cmd_detalles(Args())
    check(llamadas[0] == 0,
          f"el cortafuegos corta antes de salir a la red ({llamadas[0]})")
    m._BLOQUEOS.clear()


def n1_lista_de_cuentas():
    print("\n[N1] Registro de cuentas seguidas")
    prep(TEMPORAL("n1"))
    check(m.leer_cuentas() == [], "al principio, ninguna")

    check(m.anadir_cuenta("cuenta.ejemplo"), "añade una")
    check(m.anadir_cuenta("https://www.instagram.com/otra_cuenta/"),
          "acepta una URL")
    check(not m.anadir_cuenta("@cuenta.ejemplo"),
          "no duplica la misma con @")
    check(not m.anadir_cuenta("https://www.instagram.com/p/ABC/"),
          "rechaza lo que no es un perfil")
    check(m.leer_cuentas() == ["cuenta.ejemplo", "otra_cuenta"],
          f"quedan las dos, en orden ({m.leer_cuentas()})")

    check(m.quitar_cuenta("cuenta.ejemplo"), "quita una")
    check(m.leer_cuentas() == ["otra_cuenta"], "y queda la otra")
    check(not m.quitar_cuenta("noexiste"), "quitar lo que no está no falla")


def n2_cada_cuenta_sus_archivos():
    print("\n[N2] Los datos de cada cuenta no se mezclan")
    prep(TEMPORAL("n2"))
    for cuenta, n in (("una", 10), ("otra", 25)):
        with m.con_cuenta(cuenta):
            m.pedir = FakeIG(0, n).pedir
            m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": n,
                               "totales_fiables": True}, "seguidos")

    check(sorted(m.leer_cuentas()) == ["otra", "una"],
          "las dos quedan registradas solas al descargarlas")
    with m.con_cuenta("una"):
        check(len(leer(m._ruta_captura("seguidos"))) == 10, "'una' tiene 10")
    with m.con_cuenta("otra"):
        check(len(leer(m._ruta_captura("seguidos"))) == 25, "'otra' tiene 25")

    check(m.OBJETIVO == "t", f"con_cuenta deja OBJETIVO como estaba ({m.OBJETIVO})")

    # Aunque falle dentro, OBJETIVO debe volver a su sitio
    try:
        with m.con_cuenta("tercera"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    check(m.OBJETIVO == "t", "también si algo revienta dentro")

    e = m.estado_de_cuenta("otra")
    check(e["capturas"] == 1 and e["cuenta"] == "otra",
          f"el estado por cuenta cuadra ({e['capturas']})")


def n3_vigilar_todas_raciona():
    print("\n[N3] 'vigilar --todas' reparte y aplaza, no paraleliza")
    prep(TEMPORAL("n3"))
    for c in ("chica", "mediana", "enorme"):
        m.anadir_cuenta(c)

    tamanos = {"chica": (50, 0), "mediana": (400, 0), "enorme": (9000, 0)}
    orden_perfil, bajadas = [], []

    def perfil_falso(s, u):
        orden_perfil.append(u)
        seg, sig = tamanos[u]
        return {"id": "1", "username": u, "nombre": "", "seguidores": seg,
                "seguidos": sig, "privada": False, "la_sigo": True,
                "totales_fiables": True}

    m.perfil = perfil_falso
    m.crear_sesion = lambda forzar=False: None
    m.descargar = lambda s, p, tipo: bajadas.append((m.OBJETIVO, tipo))

    class Args:
        umbral, max_dias, solo_mirar, todas = 1, 7, False, True

    m.TOPE_DIARIO = 20
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.cmd_vigilar(Args())
        salida = buf.getvalue()
    finally:
        m.TOPE_DIARIO = 250

    check(sorted(orden_perfil) == ["chica", "enorme", "mediana"],
          f"mira las tres, 1 petición cada una ({orden_perfil})")

    nombres = [b[0] for b in bajadas]
    check("chica" in nombres, "descarga la más barata")
    check("enorme" not in nombres,
          f"y NO la que no cabe ({nombres})")
    check("Aplazadas" in salida and "enorme" in salida.split("Para mañana")[-1],
          "la aplaza y lo dice")
    check("aplazadas" in m._ruta_log().read_text(encoding="utf-8"),
          "queda en la bitácora para mañana")


def n4_cuenta_por_linea_de_comandos():
    print("\n[N4] --cuenta cambia el objetivo solo para esa ejecución")
    prep(TEMPORAL("n4"))
    original = m.OBJETIVO
    vistas = []
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: (vistas.append(u),
                             {"id": "1", "username": u, "nombre": "",
                              "seguidores": 1, "seguidos": 1, "privada": False,
                              "la_sigo": True, "totales_fiables": True})[1]

    sys.argv = ["x", "--cuenta", "https://www.instagram.com/otra.cuenta/",
                "contar"]
    m.main()
    check(vistas == ["otra.cuenta"],
          f"usa la cuenta indicada, limpiando la URL ({vistas})")

    sys.argv = ["x", "--cuenta", "no/vale", "contar"]
    try:
        m.main()
        check(False, "debería rechazarla")
    except SystemExit as e:
        check("no parece" in str(e), "y rechaza lo que no es un usuario")
    m.OBJETIVO = original


def n5_listado_de_cuentas():
    print("\n[N5] El listado de cuentas no gasta peticiones")
    prep(TEMPORAL("n5"))
    peticiones = []
    m.pedir = lambda *a, **k: peticiones.append(1)
    m.anadir_cuenta("una")
    with m.con_cuenta("una"):
        r = m._ruta_captura("seguidos", "2026-09-05")
        m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
        m._escribir_meta(r, True, 1, 1, "completa")

    import io
    import contextlib

    class Args:
        anadir = quitar = None

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_cuentas(Args())
    salida = buf.getvalue()

    check(peticiones == [], "ninguna petición")
    check("una" in salida and "2026-09-05" in salida,
          "muestra la cuenta y su última captura")
    check("repartir" in salida, "y recuerda que el presupuesto es compartido")


def f18_ritmo_por_cuenta():
    print("\n[F18] Cada cuenta a su ritmo, sin romper el neto cero")
    from datetime import date as _d

    hoy = _d(2026, 9, 10)

    # Reaccionar rápido a la señal, retirarse despacio: misma asimetría que
    # el tope diario, y por el mismo motivo.
    e = {}
    for _ in range(6):
        e = m.ajustar_ritmo(e, False, hoy)
    check(e["cadencia"] == m.MAX_DIAS_SIN_BAJAR,
          f"sin cambios se separa hasta el techo ({e['cadencia']})")

    e = m.ajustar_ritmo(e, True, hoy)
    check(e["cadencia"] == m.MAX_DIAS_SIN_BAJAR // 2,
          f"y en cuanto se mueve vuelve a la mitad ({e['cadencia']})")
    check(e["cambio"] == "2026-09-10", "anotando cuándo fue")

    # EL TECHO NO SE NEGOCIA. Es la garantía del neto cero de la v2.1: si se
    # van tres y entran tres, el total no cambia y solo la descarga forzada
    # lo pilla. Un ritmo más lento la rompería en silencio.
    e = {"cadencia": 999}
    for _ in range(20):
        e = m.ajustar_ritmo(e, False, hoy)
    check(e["cadencia"] <= m.MAX_DIAS_SIN_BAJAR,
          f"nunca por encima del máximo sin bajar ({e['cadencia']})")
    # Nueve días sin mirar: con el techo puesto toca; sin él, la cadencia
    # de 999 diría que faltan siglos.
    check(m.retraso({"cadencia": 999, "mirada": "2026-09-01"}, hoy) == 2,
          "una cadencia absurda guardada a mano se recorta al techo igual")

    # Cuándo toca, y en qué orden cuando el presupuesto no llega
    check(m.retraso({"cadencia": 3, "mirada": "2026-09-09"}, hoy) < 0,
          "mirada ayer con cadencia 3: todavía no toca")
    check(m.retraso({"cadencia": 3, "mirada": "2026-09-07"}, hoy) >= 0,
          "hace tres días: toca")
    check(m.retraso({}, hoy) > 0, "una cuenta nueva toca desde el principio")

    atrasadas = sorted(
        [("mucho", {"cadencia": 1, "mirada": "2026-09-01"}),
         ("poco", {"cadencia": 1, "mirada": "2026-09-08"})],
        key=lambda x: -m.retraso(x[1], hoy))
    check(atrasadas[0][0] == "mucho",
          "primero la que más lo necesita: si no llega para todas, que se "
          "quede fuera la que menos falta hace")

    # --- lo que de verdad se gana ---
    activas, dormidas = {"cadencia": 1}, {"cadencia": 1}
    for _ in range(10):
        activas = m.ajustar_ritmo(activas, True, hoy)
        dormidas = m.ajustar_ritmo(dormidas, False, hoy)
    coste = 1 / activas["cadencia"] + 1 / dormidas["cadencia"]
    check(coste < 1.5,
          f"una activa y una dormida cuestan {coste:.2f} sondeos al día en "
          "vez de 2")

    # Y se guarda y se relee entero
    prep(TEMPORAL("f18"))
    m.guardar_ritmo({"una": {"cadencia": 4, "mirada": "2026-09-01"}})
    check(m.leer_ritmo()["una"]["cadencia"] == 4, "se guarda y se relee")
    check(m._ruta_ritmo().parent == m.CARPETA,
          "en la raíz: es el plan de la ronda, no un dato de una cuenta")


def f19_repaso_del_ritmo():
    print("\n[F19] Lo que se encontró repasando el tope y el ritmo")

    # --- 1. Un corte tras tres peticiones no mide ningún volumen ---------
    # Es lo que hace 'web_profile_info': corta a la PRIMERA para esta
    # sesión. Sin distinguirlo, el tope bajaba un 40% por algo que no
    # tenía nada que ver con cuántas peticiones aguanta el que trabaja.
    dia = {"dia": "2026-09-01", "hechas": 300, "bloqueos": 1,
           "por_endpoint": {"perfil": 3, "lista_seguidores": 297},
           "bloqueos_por_endpoint": {"perfil": 1}}
    check(m.bloqueos_de_volumen(dia) == 0,
          "un bloqueo tras 3 peticiones a ese endpoint no cuenta")

    dia["bloqueos_por_endpoint"] = {"lista_seguidores": 1}
    check(m.bloqueos_de_volumen(dia) == 1,
          "y uno tras 297 sí: eso sí es un límite de ritmo")

    viejo = {"dia": "x", "hechas": 300, "bloqueos": 2}
    check(m.bloqueos_de_volumen(viejo) == 2,
          "de los días de antes se cuentan todos: no se puede saber más")

    carpeta = prep(TEMPORAL("f19"))
    m.cerrar_dia({"dia": "2026-09-01", "hechas": 250, "bloqueos": 1,
                  "por_endpoint": {"perfil": 2},
                  "bloqueos_por_endpoint": {"perfil": 1}})
    check(m.tope_diario() > m.TOPE_DIARIO,
          f"un día apurado con un corte que no mide volumen SUBE el tope "
          f"({m.tope_diario()})")

    # --- 2 y 3. El ritmo de las que no se pudieron bajar y de las muertas
    hoy = date.today()
    e = m.ajustar_ritmo({}, True, hoy)
    check(e.get("mirada") == f"{hoy:%Y-%m-%d}",
          "mirarla queda anotado aunque luego no quepa bajarla: si no, "
          "mañana vuelve a salir atrasada y se gasta otro sondeo")

    dormida = {"cadencia": 1}
    for _ in range(8):
        dormida = m.ajustar_ritmo(dormida, False, hoy)
    check(dormida["cadencia"] == m.MAX_DIAS_SIN_BAJAR,
          "una cuenta que ya no existe se separa hasta el techo en vez de "
          "costar una petición al día para siempre")

    # --- 4. Fijar el tope a mano no deja archivos a medias
    class Args:
        fijar = 300
    m.cmd_limite(Args())
    check(m.tope_diario() == 300, "se puede fijar a mano")
    check(not list(carpeta.glob("*.tmp")), "y sin dejar restos por el camino")


def f50_salud_y_programar():
    print("\n[F50] La vista de salud y la tarea programada")
    import analitica as an

    # Lo que decide qué sube arriba es puro, así que se comprueba con
    # diccionarios inventados en vez de montando medio proyecto.
    check(not an.avisos_de_salud({"sesion_activa": 1, "sesion_comprobada": 1,
                                  "tope": 250, "gastado_hoy": 5}),
          "con todo en orden no avisa de nada")

    avisos = dict((t, g) for g, t in an.avisos_de_salud(
        {"sesion_activa": 1, "rechazos_hoy": 2, "capturas_incompletas": 1,
         "sin_copia": True, "errores_registro": 3}, m.plural))
    # Un 401 está pasando AHORA; no tener copia es algo que dolerá
    # después. Mezclarlos en una lista plana es lo que convierte un
    # informe en un volcado.
    graves = [t for t, g in avisos.items() if g == "alto"]
    check(len(graves) == 1 and "401" in graves[0],
          f"el rechazo sube como grave ({graves})")
    check(any("copia" in t for t in avisos), "y la falta de copia avisa")

    # Sin sesión es lo más grave de todo: nada que use internet funciona
    solo = an.avisos_de_salud({"sesion_activa": False})
    check(solo[0][0] == "alto" and "sesión" in solo[0][1],
          "sin sesión, eso va primero")

    # Los plurales no vuelven por la puerta de atrás de un archivo nuevo
    textos = " ".join(t for _, t in an.avisos_de_salud(
        {"sesion_activa": 1, "bloqueos_hoy": 1, "capturas_incompletas": 1,
         "errores_registro": 1, "cadena_rota": 1}, m.plural))
    check("(s)" not in textos and "(es)" not in textos,
          f"sin «(s)» en los avisos: {textos[:40]}")
    # Y el VERBO también concuerda: plural() solo sabe de nombres, así que
    # «1 captura cambiaron» pasaba la regla de los (s) y se leía fatal.
    una = " ".join(t for _, t in an.avisos_de_salud({"cadena_rota": 1},
                                                    m.plural))
    check("1 captura cambió" in una, f"una captura, en singular: {una[:40]}")
    varias = " ".join(t for _, t in an.avisos_de_salud({"cadena_rota": 3},
                                                       m.plural))
    check("3 capturas cambiaron" in varias, "y tres, en plural")

    # La orden de la tarea programada apunta a donde debe
    import ordenes
    orden = ordenes._orden_de_la_tarea(45)
    check("instagram_listas.py" in orden and "vigilar --todas" in orden,
          "la tarea ejecuta la vigilancia de todas")
    check("--retraso 45" in orden,
          "con retraso al azar: saltar siempre en el mismo segundo es de "
          "lo que distingue un programa de una persona")

    # Dentro de un .exe no hay ningún .py al lado que ejecutar: la tarea
    # tiene que apuntar al propio ejecutable, que atiende la línea de
    # órdenes cuando le pasan argumentos.
    sys.frozen = True
    try:
        empaquetado = ordenes._orden_de_la_tarea(45)
    finally:
        del sys.frozen
    check(".py" not in empaquetado,
          f"empaquetado apunta al .exe, no a un .py ({empaquetado[:40]})")
    check("vigilar --todas" in empaquetado, "y sigue vigilando todas")

    lanzador = Path("FocusMedia.pyw").read_text(encoding="utf-8")
    check("len(sys.argv) > 1" in lanzador,
          "y el lanzador atiende la línea de órdenes si le pasan argumentos")


PRUEBAS = [
    z1_lista_de_vigilancia,
    z2_tope_duro,
    z3_una_peticion_por_cuenta,
    z4_no_repite_lo_ya_consultado,
    z5_para_al_primer_bloqueo,
    z6_solo_listar_no_gasta,
    z7_crear_lista_desde_capturas,
    z8_respeta_el_cortafuegos,
    n1_lista_de_cuentas,
    n2_cada_cuenta_sus_archivos,
    n3_vigilar_todas_raciona,
    n4_cuenta_por_linea_de_comandos,
    n5_listado_de_cuentas,
    f18_ritmo_por_cuenta,
    f19_repaso_del_ritmo,
    f50_salud_y_programar,
]
