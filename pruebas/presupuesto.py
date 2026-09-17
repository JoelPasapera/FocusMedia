"""
Presupuesto, topes y frenos
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def p1_contador_diario():
    print("\n[P1] Se cuenta cada petición, por endpoint")
    prep(TEMPORAL("p1"))
    check(m.queda_presupuesto() == m.TOPE_DIARIO, "empieza entero")

    class R:
        status_code = 200

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            return R()

    ses = S()
    for _ in range(3):
        m.pedir(ses, "/api/v1/friendships/123/following/")
    m.pedir(ses, "/api/v1/users/web_profile_info/")

    p = m._presupuesto()
    check(p["hechas"] == 4, f"cuatro peticiones contadas ({p['hechas']})")
    check(p["por_endpoint"]["friendships/following"] == 3,
          "tres del endpoint de listas")
    check(p["por_endpoint"]["users/web_profile_info"] == 1, "una del perfil")
    check(m.queda_presupuesto() == m.TOPE_DIARIO - 4, "y el resto disponible")
    check(p["primera"] and p["ultima"], "anota la primera y la última hora")

    # Sobrevive al reinicio del proceso
    m._PRESUPUESTO = None
    check(m._presupuesto()["hechas"] == 4, "se guarda en disco y se relee")


def p2_tope_diario():
    print("\n[P2] Al llegar al tope no sale ni una petición más")
    prep(TEMPORAL("p2"))
    llamadas = [0]

    class R:
        status_code = 200

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            llamadas[0] += 1
            return R()

    ses = S()
    m.TOPE_DIARIO = 5
    try:
        for _ in range(5):
            m.pedir(ses, "/api/v1/x/")
        check(llamadas[0] == 5, "las cinco primeras salen")
        check(m.queda_presupuesto() == 0, "presupuesto agotado")

        try:
            m.pedir(ses, "/api/v1/x/")
            check(False, "debería negarse")
        except m.SinPresupuesto as e:
            check("tope diario" in str(e), "avisa del tope")
        check(llamadas[0] == 5, "y no llegó a salir a la red")

        # El tope NO es lo mismo que un bloqueo: esperar no lo arregla
        check(not issubclass(m.SinPresupuesto, m.Bloqueado),
              "es un error distinto de un bloqueo, para no reintentar")
    finally:
        m.TOPE_DIARIO = 250


def p3_prudencia_tras_bloqueo():
    print("\n[P3] Después de un bloqueo, el ritmo baja solo")
    prep(TEMPORAL("p3"))
    check(m.factor_prudencia() == 1.0, "sin bloqueos, ritmo normal")

    m.anotar_bloqueo_diario()
    check(m.factor_prudencia() == 2.0, "con un bloqueo, pausas al doble")

    m.anotar_bloqueo_diario()
    m.anotar_bloqueo_diario()
    check(m.factor_prudencia() == 3.0, "con tres, al triple")
    check(m._presupuesto()["bloqueos"] == 3, "y quedan registrados")


def p4_recordar_la_via_buena():
    print("\n[P4] Se recuerda qué vía funciona, entre ejecuciones")
    prep(TEMPORAL("p4"))
    check(m.via_recordada("perfil") is None, "al principio no sabe nada")

    m.recordar_via("perfil", "página del perfil")
    check(m.via_recordada("perfil") == "página del perfil", "lo recuerda")

    m._PRESUPUESTO = None
    check(m.via_recordada("perfil") == "página del perfil",
          "y sobrevive al reinicio")

    # Lo aprendido NO se borra al cambiar de día; el contador sí
    p = m._presupuesto()
    p["dia"] = "2020-01-01"
    p["hechas"] = 99
    m._guardar_presupuesto()
    m._PRESUPUESTO = None
    nuevo = m._presupuesto()
    check(nuevo["hechas"] == 0, "el contador se reinicia al cambiar de día")
    check(m.via_recordada("perfil") == "página del perfil",
          "pero lo aprendido no: redescubrirlo costaría peticiones")


def p5_estimar_antes_de_gastar():
    print("\n[P5] Se estima el coste antes de una descarga")
    prep(TEMPORAL("p5"))
    check(m.estimar_peticiones(302, 510) == 7 + 11,
          f"302+510 -> 18 páginas ({m.estimar_peticiones(302, 510)})")
    check(m.estimar_peticiones(302, 510, "seguidores") == 7,
          "solo una lista cuesta menos")
    check(m.estimar_peticiones(0, 0) == 2, "una cuenta vacía cuesta el mínimo")
    check(m.estimar_peticiones(50000, 0, "seguidores") == 1000,
          "una cuenta grande sale cara y se ve antes")

    # Una descarga que no cabe se rechaza antes de empezar
    m.TOPE_DIARIO = 10
    try:
        m._presupuesto()["hechas"] = 5
        m.crear_sesion = lambda forzar=False: None
        m.perfil = lambda s, u: {"id": "1", "username": u, "nombre": "",
                                 "seguidores": 5000, "seguidos": 0,
                                 "privada": False, "la_sigo": True}

        class Args:
            lista = "seguidores"

        try:
            m.cmd_bajar(Args())
            check(False, "debería negarse")
        except SystemExit as e:
            check("presupuesto" in str(e), f"se niega y explica ({e})")
    finally:
        m.TOPE_DIARIO = 250


def p6_informe_del_gasto():
    print("\n[P6] El informe del gasto")
    prep(TEMPORAL("p6"))

    class R:
        status_code = 200

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            return R()

    for _ in range(3):
        m.pedir(S(), "/api/v1/friendships/1/followers/")
    m.anotar_bloqueo_diario()
    m.recordar_via("perfil", "página del perfil")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_presupuesto(None)
    salida = buf.getvalue()

    # 175 y no 250: este escenario tiene un bloqueo, y desde la v11.7 un
    # bloqueo recorta el techo de HOY. Antes seguía enseñando el margen
    # entero mientras Instagram cortaba, que es dar permiso, no poner tope.
    check("3 de 175" in salida, f"muestra el gasto ({salida[:60]!r})")
    check("friendships/followers" in salida, "desglosado por endpoint")
    check("Bloqueos recibidos: 1" in salida, "y los bloqueos")
    check("x2" in salida, "avisa de que las pausas van al doble")
    check("página del perfil" in salida, "y qué vía se está usando")
    check(m.resumen_presupuesto().startswith("3/175"),
          f"el resumen corto ({m.resumen_presupuesto()})")


def q1_dos_procesos_no_se_pisan():
    print("\n[Q1] Dos procesos a la vez no deben perder peticiones")
    import subprocess
    import textwrap
    carpeta = Path(tempfile.mkdtemp())

    guion = Path(tempfile.gettempdir()) / "proceso_presupuesto.py"
    guion.write_text(textwrap.dedent(f'''
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(m.__file__).parent)!r})
        import instagram_listas as m
        m.CARPETA = Path(sys.argv[1]); m._PRESUPUESTO = None
        m._presupuesto()                     # ambos leen el mismo estado
        time.sleep(float(sys.argv[3]))
        for _ in range(int(sys.argv[2])):
            m.anotar_peticion("/api/v1/friendships/1/following/")
    '''), encoding="utf-8")

    a = subprocess.Popen([sys.executable, str(guion), str(carpeta), "10", "0.4"])
    b = subprocess.Popen([sys.executable, str(guion), str(carpeta), "5", "0.5"])
    a.wait()
    b.wait()

    disco = json.loads((carpeta / "presupuesto.json").read_text())
    check(disco["hechas"] == 15,
          f"10 + 5 = 15 peticiones contadas ({disco['hechas']})")
    check(disco["por_endpoint"]["friendships/following"] == 15,
          "y el reparto por endpoint también suma")
    check(not (carpeta / "presupuesto.json.lock").exists(),
          "el cerrojo se libera al terminar")


def q2_detalles_frena_tras_bloqueo():
    print("\n[Q2] 'detalles' baja el ritmo y respeta el presupuesto")
    prep(TEMPORAL("q2"))
    m._ruta_vigilancia().write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    m.crear_sesion = lambda forzar=False: None
    m.perfil_detallado = lambda s, u: {"username": u, "seguidores": "1",
                                       "publicaciones": "1"}

    esperas = []
    m._dormir = lambda seg: esperas.append(seg)

    class Args:
        crear = solo_listar = False

    m.cmd_detalles(Args())
    check(esperas and all(m.PAUSA_DETALLE_MIN <= e <= m.PAUSA_DETALLE_MAX
                          for e in esperas),
          f"sin bloqueos, pausas normales ({[round(e, 1) for e in esperas]})")

    # Con un bloqueo hoy, las pausas se duplican
    prep(TEMPORAL("q2b"))
    m._ruta_vigilancia().write_text("a\nb\nc\n", encoding="utf-8")
    m.anotar_bloqueo_diario()
    esperas.clear()
    m.cmd_detalles(Args())
    check(esperas and all(e >= m.PAUSA_DETALLE_MIN * 2 for e in esperas),
          f"tras un bloqueo, al doble ({[round(e, 1) for e in esperas]})")

    # Y no se pasa del presupuesto
    prep(TEMPORAL("q2c"))
    m._ruta_vigilancia().write_text(
        "\n".join(f"c{i}" for i in range(10)), encoding="utf-8")
    consultadas = []
    m.perfil_detallado = lambda s, u: (consultadas.append(u),
                                       {"username": u, "seguidores": "1",
                                        "publicaciones": "1"})[1]
    m.TOPE_DIARIO = 4
    try:
        m.cmd_detalles(Args())
        check(len(consultadas) == 4,
              f"solo consulta las que caben ({len(consultadas)} de 10)")
    finally:
        m.TOPE_DIARIO = 250


def q3_vigilar_estima_antes():
    print("\n[Q3] 'vigilar' comprueba el coste antes de descargar")
    prep(TEMPORAL("q3"))
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: {"id": "1", "username": u, "nombre": "",
                             "seguidores": 5000, "seguidos": 5000,
                             "privada": False, "la_sigo": True,
                             "totales_fiables": True}
    bajadas = []
    m.descargar = lambda s, p, tipo: bajadas.append(tipo)

    class Args:
        umbral, max_dias, solo_mirar = 1, 7, False

    m.TOPE_DIARIO = 20
    try:
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            m.cmd_vigilar(Args())
        salida = buf.getvalue()
        check(bajadas == [], f"no descarga si no cabe ({bajadas})")
        check("no cabe" in salida.lower() or "Harían falta" in salida,
              "y explica por qué")
        check("Mañana se retoma" in salida,
              "sin abortar el programa: mañana lo intenta solo")
        check("aplazado" in m._ruta_log().read_text(encoding="utf-8"),
              "queda anotado en la bitácora")
    finally:
        m.TOPE_DIARIO = 250

    # Con presupuesto de sobra sí descarga
    prep(TEMPORAL("q3b"))
    bajadas.clear()
    m.cmd_vigilar(Args())
    check(sorted(bajadas) == ["seguidores", "seguidos"],
          f"con presupuesto, descarga ({bajadas})")


def q4_totales_no_fiables():
    print("\n[Q4] Sin totales fiables no se puede dar por completa")
    prep(TEMPORAL("q4"))
    m.pedir = FakeIG(0, 30).pedir
    p = {"id": "1", "seguidores": 0, "seguidos": 0, "totales_fiables": False}
    m.descargar(None, p, "seguidos")

    meta = m._leer_meta(m._ruta_captura("seguidos"))
    check(meta["completa"] is None,
          f"la captura queda SIN verificar, no como completa ({meta['completa']})")
    check("no se pudo verificar" in meta["motivo"], "y se explica por qué")

    # El historial la trata como sospechosa de la v1, y avisa
    import io
    import contextlib
    m._escribir_csv(m._ruta_captura("seguidos", "2026-09-01"), m.CABECERA,
                    [[f"u{i}", "", str(i)] for i in range(30)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidos")
    check("Sin metadatos" in buf.getvalue() or "sin metadatos"
          in buf.getvalue(), "el historial avisa de las no verificadas")

    # Con totales fiables sí se marca completa
    prep(TEMPORAL("q4b"))
    m.pedir = FakeIG(0, 30).pedir
    m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": 30,
                       "totales_fiables": True}, "seguidos")
    check(m._leer_meta(m._ruta_captura("seguidos"))["completa"] is True,
          "con totales fiables sí se da por completa")


def q5_privada_sin_saber_si_la_sigues():
    print("\n[Q5] Cuenta privada por la vía HTML: avisa, no da por hecho")
    base = {"id": "1", "username": "x", "nombre": "", "seguidores": 10,
            "seguidos": 10, "totales_fiables": True}

    check(m.avisar_si_privada(dict(base, privada=False, la_sigo=None)) is None,
          "cuenta pública: sin aviso")

    aviso = m.avisar_si_privada(dict(base, privada=True, la_sigo=False))
    check(aviso and "NO la sigue" in aviso, "privada y no la sigues: claro")

    aviso = m.avisar_si_privada(dict(base, privada=True, la_sigo=None))
    check(aviso and "no consta" in aviso,
          f"privada y sin saberlo: avisa sin afirmar ({aviso[:50]})")
    check(aviso and "saldrá vacía" in aviso, "y dice qué pasará si no la sigues")

    check(m.avisar_si_privada(dict(base, privada=True, la_sigo=True)) is None,
          "privada pero la sigues: adelante")

    # La vía HTML nunca debe afirmar que la sigues
    prep(TEMPORAL("q5"))

    class S:
        cookies = {}

        def get(self, url, headers=None, params=None, timeout=None):
            class R:
                status_code = 200
                text = HTML_PERFIL
            return R()

    p = m.perfil_desde_html(S(), "x")
    check(p["la_sigo"] is None, "la página no afirma que la sigas")
    # Esta muestra solo trae las metas og:, que redondean —970 por 969—.
    # Decir que son fiables llevaría a comparar totales aproximados.
    check(p["totales_fiables"] is False,
          "sus totales vienen de las metas y esas redondean")


def q6_cerrojo_huerfano():
    print("\n[Q6] Un cerrojo abandonado no debe bloquear para siempre")
    carpeta = Path(tempfile.mkdtemp())
    m.CARPETA = carpeta
    m._PRESUPUESTO = None
    ruta = m._ruta_presupuesto()
    carpeta.mkdir(parents=True, exist_ok=True)

    viejo = ruta.with_name(ruta.name + ".lock")
    viejo.write_text("")
    os.utime(viejo, (time.time() - 60, time.time() - 60))   # 1 min de edad

    inicio = time.monotonic()
    m.anotar_peticion("/api/v1/x/")
    tardanza = time.monotonic() - inicio

    check(tardanza < 2, f"no se queda esperando ({tardanza:.2f}s)")
    check(m._presupuesto()["hechas"] == 1, "y la petición se anota igual")
    check(not viejo.exists(), "el cerrojo huérfano se limpia")


def f17_tope_que_se_mide():
    print("\n[F17] El tope se aprende en vez de suponerse")

    def dia(hechas, tope, bloqueos=0):
        return {"dia": "2026-09-01", "hechas": hechas, "tope": tope,
                "bloqueos": bloqueos}

    # 1. Un bloqueo es la única medida directa que existe: se baja de golpe
    r = m.ajustar_tope(dia(400, 400, bloqueos=1))
    check(r["tope"] == int(400 * m.CAIDA_TOPE), f"baja de golpe ({r['tope']})")
    check(r["borde"] == 400, "y anota dónde cortó")

    # 2. Día limpio y apurado: sube un paso
    r = m.ajustar_tope(dia(250, 250))
    check(r["tope"] == 250 + m.PASO_TOPE, f"sube un paso ({r['tope']})")

    # 3. Día limpio pero flojo: NO se toca. Es la regla que más importa: de
    #    un día en que no te acercaste no aprendes dónde está el borde.
    r = m.ajustar_tope(dia(30, 250))
    check(r["tope"] == 250, "un día flojo no cambia nada")
    check("no prueba nada" in r["motivo"], "y dice por qué")

    # 4. Pegado al borde conocido: se para. Sin esto habría un bloqueo cada
    #    dos semanas para siempre a cambio de nada.
    r = m.ajustar_tope(dia(360, 360), {"borde": 400})
    check(r["tope"] == 360, f"no empuja contra el borde sabido ({r['tope']})")
    check(r["pegados"] == 1, "y lleva la cuenta de los días pegado")

    # Pasado el plazo se vuelve a tantear, por si Instagram aflojó
    r = m.ajustar_tope(dia(360, 360),
                       {"borde": 400, "pegados": m.DIAS_REPROBAR - 1})
    check(r["tope"] == 360 + m.PASO_TOPE, "cada tanto se vuelve a probar")
    check(r["borde"] > 400, "subiendo el borde, no ignorándolo")

    # El borde se queda con el corte MÁS BAJO visto
    r = m.ajustar_tope(dia(300, 300, bloqueos=1), {"borde": 400})
    check(r["borde"] == 300, "el borde es el corte más bajo que hubo")
    r = m.ajustar_tope(dia(500, 500, bloqueos=1), {"borde": 300})
    check(r["borde"] == 300, "y no sube por un corte más alto")

    # Suelo y techo
    check(m.ajustar_tope(dia(60, 60, bloqueos=1))["tope"] == m.SUELO_TOPE,
          "no baja del suelo: dejaría de servir")
    check(m.ajustar_tope(dia(m.TECHO_TOPE, m.TECHO_TOPE))["tope"]
          == m.TECHO_TOPE, "ni sube del techo: no se mide sin freno")

    # --- y el día se cierra de verdad, una sola vez ---
    carpeta = prep(TEMPORAL("f17"))
    check(m.tope_diario() == m.TOPE_DIARIO, "sin medir, el de partida")

    m.cerrar_dia({"dia": "2026-09-01", "hechas": 250, "bloqueos": 0})
    check(m.tope_diario() == m.TOPE_DIARIO + m.PASO_TOPE,
          f"tras un día apurado sube ({m.tope_diario()})")
    m.cerrar_dia({"dia": "2026-09-01", "hechas": 250, "bloqueos": 0})
    check(m.tope_diario() == m.TOPE_DIARIO + m.PASO_TOPE,
          "cerrar dos veces el mismo día no cuenta dos veces")

    m.cerrar_dia({"dia": "2026-09-02", "hechas": 275, "bloqueos": 1})
    check(m.tope_diario() < m.TOPE_DIARIO, "y un bloqueo lo baja de verdad")
    check(len(m._limite()["historial"]) == 2, "queda el registro de los días")
    check(m._ruta_limite().parent == m.CARPETA,
          "el límite va en la raíz: es de la sesión, no de una cuenta")

    m.cerrar_dia({"dia": "2026-09-03", "hechas": 0, "bloqueos": 0})
    check(len(m._limite()["historial"]) == 2,
          "un día sin usar la herramienta no entra en el historial")


def f24_el_volcado_no_pierde_nada():
    print("\n[F24] El volcado del presupuesto no se come contadores")
    prep(TEMPORAL("f24"))
    m._PRESUPUESTO = None

    # El fallo: el volcado copiaba a mano tres claves y reemplazaba el
    # presupuesto en memoria por lo copiado. Cualquier contador nuevo se
    # anotaba y se perdía en la siguiente escritura. Se estaba comiendo
    # 'bloqueos_por_endpoint', que es de lo que depende no bajar el tope
    # por un bloqueo que no mide volumen.
    m.anotar_peticion("/api/v1/friendships/1/followers/")
    m.anotar_bloqueo_diario("lista_seguidores")
    m.anotar_rechazo("perfil")

    p = m._presupuesto()
    check(p.get("rechazos") == 1, "el rechazo sobrevive al volcado")
    check(p.get("bloqueos_por_endpoint", {}).get("perfil") == 1,
          "y el reparto de bloqueos por endpoint también")
    check(p.get("bloqueos_por_endpoint", {}).get("lista_seguidores") == 1,
          "los dos, cada uno en su sitio")
    check(sum((p.get("por_hora") or {}).values()) == 1,
          "y el reparto por horas, que es lo que frena las ráfagas")

    # Y lo que hay en el archivo es lo mismo que hay en memoria
    disco = json.loads(m._ruta_presupuesto().read_text(encoding="utf-8"))
    for clave in ("rechazos", "bloqueos_por_endpoint", "por_hora"):
        check(disco.get(clave) == p.get(clave),
              f"'{clave}' queda igual en disco que en memoria")

    # Sumar sobre lo que ya había, que es para lo que existe el volcado
    m.anotar_rechazo("perfil")
    check(m._presupuesto()["rechazos"] == 2, "y se suma, no se reemplaza")


def s1_400_no_se_reintenta():
    print("\n[S1] Un HTTP 400 no debe entrar en el bucle de esperas")
    prep(TEMPORAL("s1"))

    class R:
        status_code = 400
        text = '{"message":"bad request"}'

        def json(self):
            return {}

    class S:
        cookies = {}

        def get(self, *a, **k):
            return R()

    try:
        m.pedir(S(), "/api/v1/x/")
        check(False, "debería lanzar algo")
    except m.PeticionRechazada as e:
        check("400" in str(e), "se clasifica como petición rechazada")
        check("bad request" in str(e),
              f"e incluye lo que dice Instagram ({str(e)[-40:]})")
    except m.Bloqueado:
        check(False, "NO debe tratarse como bloqueo: se reintentaría")

    check(not issubclass(m.PeticionRechazada, m.Bloqueado),
          "es una excepción distinta, para no reintentarla")
    check(m.espera_pendiente("/api/v1/x/") == 0,
          "y no pone el endpoint en cuarentena: no es un bloqueo")


def s2_descarga_para_en_seco_ante_400():
    print("\n[S2] La descarga para en seco, sin esperar horas")
    prep(TEMPORAL("s2"))
    esperas = []
    m._dormir = lambda seg: esperas.append(seg)
    peticiones = [0]

    def pedir_400(s, ruta, params=None, referer=None):
        peticiones[0] += 1
        if peticiones[0] == 1:
            return {"users": [{"pk": f"u{i}", "username": f"u{i}",
                               "full_name": ""} for i in range(50)],
                    "next_max_id": "50"}
        raise m.PeticionRechazada("HTTP 400 en 'friendships/following'")

    m.pedir = pedir_400
    m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": 328,
                       "totales_fiables": True}, "seguidos")

    largas = [e for e in esperas if e >= 60]
    check(largas == [],
          f"ninguna espera de minutos ({[round(e) for e in largas]})")
    check(peticiones[0] <= 3,
          f"no insiste una y otra vez ({peticiones[0]} peticiones)")

    filas = leer(m._ruta_captura("seguidos"))
    check(len(filas) == 50, f"lo descargado se conserva ({len(filas)})")
    meta = m._leer_meta(m._ruta_captura("seguidos"))
    check(meta["completa"] is False, "marcada como incompleta, no como buena")

    # El cursor NO se guarda a propósito: si es él lo que Instagram rechaza,
    # retomarlo haría fallar la próxima ejecución en el mismo punto, siempre.
    # Empezar de cero y fusionar es lo que se recupera solo.
    check(not m._ruta_estado("seguidos").exists(),
          "el cursor rechazado no se guarda para reintentarlo")
    check(not m._ruta_parcial("seguidos").exists(),
          "y el parcial se cierra en captura")


def s3_reintento_con_pagina_pequena():
    print("\n[S3] Si 50 da 400, se prueba una vez con página pequeña")
    prep(TEMPORAL("s3"))
    m._dormir = lambda seg: None
    vistos = []

    def pedir_exigente(s, ruta, params=None, referer=None):
        vistos.append(params.get("count"))
        # La primera página va bien; con cursor solo acepta páginas cortas.
        if params.get("max_id") and params["count"] > m.POR_PAGINA_MINIMO:
            raise m.PeticionRechazada("HTTP 400")
        i = int(params.get("max_id", 0))
        n = params["count"]
        users = [{"pk": f"u{k}", "username": f"u{k}", "full_name": ""}
                 for k in range(i, min(i + n, 80))]
        fin = i + len(users)
        return {"users": users,
                "next_max_id": str(fin) if fin < 80 else None}

    m.pedir = pedir_exigente
    m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": 80,
                       "totales_fiables": True}, "seguidos")

    check(m.POR_PAGINA_MINIMO in vistos,
          f"llegó a probar con página pequeña ({vistos[:5]})")
    filas = leer(m._ruta_captura("seguidos"))
    check(len(filas) == 80, f"y así terminó la lista entera ({len(filas)})")
    check(m._leer_meta(m._ruta_captura("seguidos"))["completa"] is True,
          "la captura sale completa")

    # Si la página pequeña TAMBIÉN falla, se para y se marca incompleta
    prep(TEMPORAL("s3b"))
    m._dormir = lambda seg: None
    intentos = [0]

    def siempre_400(s, ruta, params=None, referer=None):
        intentos[0] += 1
        if not params.get("max_id"):
            return {"users": [{"pk": "a", "username": "a", "full_name": ""}],
                    "next_max_id": "1"}
        raise m.PeticionRechazada("HTTP 400")

    m.pedir = siempre_400
    m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": 100,
                       "totales_fiables": True}, "seguidos")
    check(intentos[0] == 3,
          f"una normal + dos intentos y para ({intentos[0]})")
    meta = m._leer_meta(m._ruta_captura("seguidos"))
    check(meta["completa"] is False, "la captura queda marcada como incompleta")
    check("rechaz" in meta["motivo"], f"explicando el motivo ({meta['motivo']})")


def f65_medir_lo_que_sirve_instagram():
    print("\n[F65] Cuánta gente sirve Instagram por página")
    prep("/tmp/f65")
    m.recordar_id("t", "1")

    pedidos = []

    def servidor(tope):
        def responde(s, ruta_usada, params=None, **k):
            pedido = (params or {}).get("count", 0)
            pedidos.append(pedido)
            n = min(pedido, tope)
            return {"users": [{"pk": str(i), "username": f"u{i}"}
                              for i in range(n)]}
        return responde

    # 1. Si el servidor corta en 50, no se sigue subiendo: una petición
    #    con una forma que no usa ningún navegador, a cambio de nada.
    pedidos.clear()
    m.pedir = servidor(50)
    r = m.medir_pagina(None, "1", "seguidores", [50, 100, 200])
    check(pedidos == [50, 100], f"para al encontrar el tope ({pedidos})")
    check(r[-1][2] is True, "y marca dónde cortó")

    # 2. Si sirve más, se sigue hasta donde se pidió.
    pedidos.clear()
    m.pedir = servidor(500)
    r = m.medir_pagina(None, "1", "seguidores", [50, 100, 200])
    check(pedidos == [50, 100, 200], f"si sirve más, se mide más ({pedidos})")
    check([ll for _, ll, _ in r] == [50, 100, 200], "y devuelve lo que llegó")

    # 3. Medir NO es descargar: no se guarda ninguna captura ni se toca el
    #    progreso de una descarga a medias.
    check(not list(m.carpeta_cuenta("t").glob("*.csv")),
          "medir no deja capturas")

    # 4. El ajuste tiene que admitir lo que se mida; antes topaba en 50 y
    #    no se habría podido aplicar.
    check(m.acotar("por_pagina", 200) == 200, "se puede subir a 200")
    # `DE_SERIE` se rellena al aplicar los ajustes, no al importar.
    m.aplicar_ajustes()
    check(m.DE_SERIE.get("por_pagina") == 50,
          f"pero de serie sigue siendo 50, lo que pide la web "
          f"({m.DE_SERIE.get('por_pagina')})")


def f66_el_tope_reacciona_hoy():
    print("\n[F66] Un día con bloqueos no puede seguir dando 250 de margen")
    prep("/tmp/f66")
    m._PRESUPUESTO = None

    # Visto en pantalla: «15/250 peticiones hoy, 5 bloqueos». El tope
    # aprendido solo se recalculaba al CERRAR el día, así que mientras
    # Instagram cortaba una de cada tres seguía enseñando todo el margen.
    # Eso no es un tope: es un número que da permiso.
    limpio = m.tope_diario()
    check(limpio == m.TOPE_DIARIO, f"sin bloqueos, el tope entero ({limpio})")

    m._presupuesto()["bloqueos"] = 1
    uno = m.tope_diario()
    check(uno < limpio, f"un bloqueo ya recorta ({limpio} -> {uno})")

    m._presupuesto()["bloqueos"] = 5
    cinco = m.tope_diario()
    check(cinco < uno, f"y cinco recortan mucho más ({cinco})")

    # Pero nunca a cero: con el tope a cero no se podría ni comprobar si
    # la cosa ya ha pasado, y eso deja sin salida.
    m._presupuesto()["bloqueos"] = 99
    check(m.tope_diario() == m.SUELO_TOPE,
          f"con suelo, no se baja de {m.SUELO_TOPE}")

    # Y el suelo nunca SUBE el tope: quien lo fije bajo a propósito no
    # puede acabar con más margen por haber recibido un bloqueo. Un freno
    # que afloja es peor que no tener freno.
    antes_tope = m.TOPE_DIARIO
    try:
        m.TOPE_DIARIO = 4
        m._limite()["tope"] = None
        m._presupuesto()["bloqueos"] = 1
        check(m.tope_diario() <= 4,
              f"un tope fijado bajo no lo sube el suelo ({m.tope_diario()})")
    finally:
        m.TOPE_DIARIO = antes_tope

    # Y lo APRENDIDO no se toca: eso se decide al cerrar el día, con el
    # día entero a la vista, no a mitad de una mala tarde.
    m._presupuesto()["bloqueos"] = 5
    antes = dict(m._limite())
    m.tope_diario()
    check(m._limite() == antes, "mirar el tope no cambia lo aprendido")


PRUEBAS = [
    f66_el_tope_reacciona_hoy,
    f65_medir_lo_que_sirve_instagram,
    p1_contador_diario,
    p2_tope_diario,
    p3_prudencia_tras_bloqueo,
    p4_recordar_la_via_buena,
    p5_estimar_antes_de_gastar,
    p6_informe_del_gasto,
    q1_dos_procesos_no_se_pisan,
    q2_detalles_frena_tras_bloqueo,
    q3_vigilar_estima_antes,
    q4_totales_no_fiables,
    q5_privada_sin_saber_si_la_sigues,
    q6_cerrojo_huerfano,
    f17_tope_que_se_mide,
    f24_el_volcado_no_pierde_nada,
    s1_400_no_se_reintenta,
    s2_descarga_para_en_seco_ante_400,
    s3_reintento_con_pagina_pequena,
]
