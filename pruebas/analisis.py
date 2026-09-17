"""
Comparar, historial, relaciones y estudio
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def h1_trayectoria_basica():
    print("\n[H1] Trayectoria: cuándo apareció y cuándo se fue cada uno")
    prep(TEMPORAL("h1"))
    # ana está siempre; beto se va; carla llega tarde
    captura("seguidores", "2026-09-01", [("ana", "", "1"), ("beto", "", "2")])
    captura("seguidores", "2026-09-02", [("ana", "", "1"), ("beto", "", "2")])
    captura("seguidores", "2026-09-03", [("ana", "", "1"), ("carla", "", "3")])

    h = m.construir_historial("seguidores")
    check(h["fechas"] == ["2026-09-01", "2026-09-02", "2026-09-03"],
          "las capturas se ordenan por fecha")
    check(len(h["personas"]) == 3, "tres personas distintas vistas")

    ana, beto, carla = h["personas"]["1"], h["personas"]["2"], h["personas"]["3"]
    check(ana["presente"] and ana["capturas"] == 3, "ana presente en las 3")
    check(ana["entradas"] == 1 and ana["salidas"] == 0, "ana: 1 entrada, 0 salidas")
    check(not beto["presente"], "beto ya no está")
    check(beto["ultima"] == "2026-09-02", "beto visto por última vez el día 2")
    check(beto["salidas"] == 1, "beto: 1 salida")
    check(carla["primera"] == "2026-09-03" and carla["presente"],
          "carla llegó el día 3 y sigue")


def h2_follow_unfollow():
    print("\n[H2] Detectar quien entra y sale repetidamente")
    prep(TEMPORAL("h2"))
    # dani hace follow-unfollow tres veces; ana está siempre
    guion = [("2026-09-01", ["ana", "dani"]),
             ("2026-09-02", ["ana"]),
             ("2026-09-03", ["ana", "dani"]),
             ("2026-09-04", ["ana"]),
             ("2026-09-05", ["ana", "dani"])]
    ids = {"ana": "1", "dani": "4"}
    for dia, us in guion:
        captura("seguidores", dia, [(u, "", ids[u]) for u in us])

    h = m.construir_historial("seguidores")
    dani, ana = h["personas"]["4"], h["personas"]["1"]

    check(dani["entradas"] == 3, f"dani: 3 entradas (dio {dani['entradas']})")
    check(dani["salidas"] == 2, f"dani: 2 salidas (dio {dani['salidas']})")
    check(dani["capturas"] == 3, "presente en 3 de las 5 capturas")
    check(dani["presente"], "y ahora mismo está")
    check(ana["entradas"] == 1 and ana["salidas"] == 0,
          "ana no se contamina: 1 entrada, 0 salidas")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    salida = buf.getvalue()
    check("IDA Y VUELTA" in salida and "dani" in salida,
          "dani aparece en la lista de ida y vuelta")
    check("Han entrado 2 veces o más: 1" in salida,
          "cuenta un solo repetidor")


def h3_excluye_truncadas():
    print("\n[H3] Una captura truncada NO debe falsear el historial")
    prep(TEMPORAL("h3"))
    todos = [(f"u{i}", "", str(i)) for i in range(100)]
    captura("seguidores", "2026-09-01", todos)
    # El día 2 la descarga se truncó y solo salieron 10
    captura("seguidores", "2026-09-02", todos[:10], completa=False)
    captura("seguidores", "2026-09-03", todos)

    h = m.construir_historial("seguidores")
    check(h["fechas"] == ["2026-09-01", "2026-09-03"],
          f"la truncada queda fuera ({h['fechas']})")
    check(h["truncadas"] == ["2026-09-02"], "y se informa de cuál se saltó")

    repetidores = [p for p in h["personas"].values() if p["entradas"] > 1]
    check(repetidores == [],
          f"nadie parece haber ido y vuelto ({len(repetidores)} falsos)")
    check(all(p["salidas"] == 0 for p in h["personas"].values()),
          "ninguna salida inventada")

    # Comprobación de contraste: si SÍ se incluyera, habría 90 falsos
    m._escribir_meta(m._ruta_captura("seguidores", "2026-09-02"),
                     True, 100, 10, "completa")
    h2 = m.construir_historial("seguidores")
    check(len(h2["sospechosas"]) == 1,
          "aunque la marquen completa, el tamaño la delata igual")
    h3 = m.construir_historial("seguidores", incluir_sospechosas=True)
    falsos = [p for p in h3["personas"].values() if p["entradas"] > 1]
    check(len(falsos) == 90,
          f"contraste: forzando su inclusión habría 90 falsos ({len(falsos)})")


def h4_cambio_de_nombre():
    print("\n[H4] El historial sigue a la persona aunque cambie de nombre")
    prep(TEMPORAL("h4"))
    captura("seguidores", "2026-09-01", [("beto", "", "2")])
    captura("seguidores", "2026-09-02", [("beto_nuevo", "", "2")])
    captura("seguidores", "2026-09-03", [("beto_final", "", "2")])

    h = m.construir_historial("seguidores")
    check(len(h["personas"]) == 1, "una sola persona, no tres")
    p = h["personas"]["2"]
    check(p["username"] == "beto_final", "usa el nombre más reciente")
    check(p["nombres"] == ["beto", "beto_nuevo", "beto_final"],
          f"guarda la cadena de nombres ({p['nombres']})")
    check(p["entradas"] == 1 and p["salidas"] == 0,
          "no cuenta el renombrado como baja y alta")


def h5_informe_csv():
    print("\n[H5] El informe CSV")
    prep(TEMPORAL("h5"))
    captura("seguidores", "2026-09-01", [("ana", "Ana Ñ", "1"), ("beto", "", "2")])
    captura("seguidores", "2026-09-02", [("ana", "Ana Ñ", "1")])
    captura("seguidores", "2026-09-03", [("ana", "Ana Ñ", "1"), ("beto", "", "2")])

    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        m.mostrar_historial("seguidores")

    ruta = m.carpeta_cuenta() / "historial_seguidores_t.csv"
    check(ruta.exists(), "se genera el informe")
    check(ruta.read_bytes().startswith(b"\xef\xbb\xbf"), "con BOM para Excel")

    filas = {f["username"]: f for f in leer(ruta)}
    check(filas["beto"]["entradas"] == "2", "beto: 2 entradas")
    check(filas["beto"]["salidas"] == "1", "beto: 1 salida")
    check(filas["beto"]["estado"] == "presente", "beto está ahora")
    check(filas["ana"]["capturas_presente"] == "3", "ana en las 3 capturas")
    check(filas["ana"]["nombre"] == "Ana Ñ", "los acentos sobreviven")
    check(list(filas)[0] == "beto", "ordena por número de entradas")


def h6_bordes_historial():
    print("\n[H6] Casos borde del historial")
    prep(TEMPORAL("h6"))
    check(m.construir_historial("seguidores") is None, "sin capturas -> None")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    check("no hay capturas utilizables" in buf.getvalue(),
          "y lo dice sin reventar")

    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    check("una captura" in buf.getvalue().lower(),
          "una captura -> avisa de que aún no hay trayectoria")

    # Todas las capturas truncadas
    prep(TEMPORAL("h6b"))
    captura("seguidores", "2026-09-01", [("ana", "", "1")], completa=False)
    check(m.construir_historial("seguidores") is None,
          "solo truncadas -> None, no un historial falso")

    # Huecos entre capturas
    prep(TEMPORAL("h6c"))
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-15", [("ana", "", "1")])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    check("14 días" in buf.getvalue(),
          "avisa del hueco máximo entre capturas")

    # Capturas sin ids (formato viejo): cae al username sin romperse
    prep(TEMPORAL("h6d"))
    for dia in ("2026-09-01", "2026-09-02"):
        m._escribir_csv(m._ruta_captura("seguidores", dia),
                        ["username", "nombre", "id"], [["ana", "", ""]])
    h = m.construir_historial("seguidores")
    check(h is not None and len(h["personas"]) == 1,
          "sin ids sigue funcionando")
    check(list(h["personas"].values())[0]["id"] == "",
          "y deja la columna id vacía en vez de inventarla")


def v1_decidir_disparadores():
    print("\n[V1] decidir(): los tres disparadores")
    prep(TEMPORAL("v1"))

    p = perfil(500, 2000)
    bajar, motivos = m.decidir(p)
    check(bajar == {"seguidores", "seguidos"},
          f"sin capturas -> baja ambas ({bajar})")

    # Con capturas de hoy y el mismo conteo: no hace falta nada
    prep(TEMPORAL("v1b"))
    hoy = f"{date.today():%Y-%m-%d}"
    captura("seguidores", hoy, [(f"f{i}", "", str(i)) for i in range(500)])
    captura("seguidos", hoy, [(f"g{i}", "", str(i)) for i in range(2000)])
    m._anotar_conteo(p)
    bajar, _ = m.decidir(p)
    check(bajar == set(), f"todo al día -> no baja nada ({bajar})")

    # Solo se mueven los seguidores: no rebajar los 2000 seguidos
    bajar, motivos = m.decidir(perfil(503, 2000))
    check(bajar == {"seguidores"},
          f"solo cambia una lista -> solo esa se baja ({bajar})")
    check(any("+3" in x for x in motivos), f"el motivo indica el delta ({motivos})")

    # Umbral: un cambio menor que el umbral no dispara
    bajar, _ = m.decidir(perfil(502, 2000), umbral=5)
    check(bajar == set(), f"cambio por debajo del umbral -> nada ({bajar})")
    bajar, _ = m.decidir(perfil(510, 2000), umbral=5)
    check(bajar == {"seguidores"}, "cambio por encima del umbral -> baja")


def v2_neto_cero():
    print("\n[V2] Movimiento neto cero: el agujero del conteo")
    prep(TEMPORAL("v2"))
    p = perfil(500, 2000)
    hoy = date.today()

    # Captura de hace 3 días y el mismo total de siempre
    viejo = f"{hoy - timedelta(days=3):%Y-%m-%d}"
    captura("seguidores", viejo, [(f"f{i}", "", str(i)) for i in range(500)])
    captura("seguidos", viejo, [(f"g{i}", "", str(i)) for i in range(2000)])
    m._anotar_conteo(p)

    bajar, _ = m.decidir(p, max_dias=7)
    check(bajar == set(), "a los 3 días y sin cambios de total: no baja")

    bajar, motivos = m.decidir(p, max_dias=3)
    check(bajar == {"seguidores", "seguidos"},
          f"al llegar a max_dias baja igualmente ({bajar})")
    check(any("3 días" in x for x in motivos),
          f"y explica que es por antigüedad ({motivos})")


def v3_ignora_capturas_rotas():
    print("\n[V3] Una captura incompleta no cuenta como reciente")
    prep(TEMPORAL("v3"))
    hoy = f"{date.today():%Y-%m-%d}"
    captura("seguidores", hoy, [("a", "", "1")], completa=False)
    captura("seguidos", hoy, [("b", "", "2")], completa=True)
    m._anotar_conteo(perfil(1, 1))

    bajar, motivos = m.decidir(perfil(1, 1))
    check("seguidores" in bajar,
          f"la incompleta se vuelve a bajar aunque sea de hoy ({bajar})")
    check("seguidos" not in bajar, "la completa de hoy se deja en paz")


def v4_conteo_y_log():
    print("\n[V4] Registro de totales y bitácora")
    prep(TEMPORAL("v4"))
    check(m._ultimo_conteo() is None, "sin historial -> None")

    m._anotar_conteo(perfil(500, 2000))
    u = m._ultimo_conteo()
    check(u["seguidores"] == 500 and u["seguidos"] == 2000, "anota y relee")

    m._anotar_conteo(perfil(505, 1998))
    u = m._ultimo_conteo()
    check(u["seguidores"] == 505, "el último conteo es el más reciente")
    check(len(m._filas_totales()) == 1,
          "dos conteos el mismo día dejan una sola fila")

    # Filas de días distintos sí se acumulan
    m._escribir_csv(m._ruta_totales(), ["fecha", "seguidores", "seguidos"],
                    [["2026-01-01", 400, 1900]] + m._filas_totales())
    m._anotar_conteo(perfil(510, 1990))
    check(len(m._filas_totales()) == 2, "días distintos sí se acumulan")

    crudo = m._ruta_totales().read_bytes()
    check(crudo.startswith(b"\xef\xbb\xbf") and crudo.count(b"\xef\xbb\xbf") == 1,
          "el registro de totales lleva un solo BOM")

    m._log("prueba de bitácora")
    m._log("segunda línea")
    lineas = m._ruta_log().read_text(encoding="utf-8").strip().splitlines()
    check(len(lineas) == 2, "la bitácora acumula líneas")
    check("prueba de bitácora" in lineas[0], "y guarda el mensaje")

    # Un archivo de totales corrupto no debe reventar
    m._escribir_csv(m._ruta_totales(), ["fecha", "seguidores", "seguidos"],
                    [["2026-09-01", "no-es-un-numero", "x"]])
    check(m._ultimo_conteo() is None, "totales corruptos -> None, sin reventar")


def v5_vigilar_end_to_end():
    print("\n[V5] vigilar completo, de punta a punta")
    prep(TEMPORAL("v5"))

    class Args:
        umbral, max_dias, solo_mirar = 1, 7, False

    ig = FakeIG(3, 5)
    m.pedir = ig.pedir
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: perfil(3, 5)

    print("  --- primera pasada: no hay nada, debe bajar ---")
    m.cmd_vigilar(Args())
    check(m._ruta_captura("seguidores").exists()
          and m._ruta_captura("seguidos").exists(),
          "la primera pasada descarga ambas listas")
    peticiones_tras_bajar = ig.peticiones

    print("  --- segunda pasada: nada cambió, no debe bajar ---")
    m.cmd_vigilar(Args())
    check(ig.peticiones == peticiones_tras_bajar,
          f"sin cambios no gasta peticiones de descarga "
          f"({ig.peticiones - peticiones_tras_bajar} extra)")

    log = m._ruta_log().read_text(encoding="utf-8")
    check("sin cambios" in log, "la bitácora registra la pasada en vacío")
    check(len(log.strip().splitlines()) == 2, "una línea por pasada")

    print("  --- tercera pasada con --solo-mirar ---")
    m.perfil = lambda s, u: perfil(9, 5)
    class ArgsMirar(Args):
        solo_mirar = True
    antes = ig.peticiones
    m.cmd_vigilar(ArgsMirar())
    check(ig.peticiones == antes, "--solo-mirar no descarga nada")
    check("solo-mirar" in m._ruta_log().read_text(encoding="utf-8"),
          "y lo deja anotado")


def v6_contar_no_dispara_descarga():
    print("\n[V6] 'contar' sigue costando una sola petición")
    prep(TEMPORAL("v6"))
    ig = FakeIG(500, 2000)
    m.pedir = ig.pedir
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: perfil(500, 2000)

    m.cmd_contar(None)
    check(ig.peticiones == 0, "contar no toca el endpoint de listas")
    check(m._ultimo_conteo()["seguidores"] == 500, "pero sí anota el total")


def f5_relacion_con_la_cuenta():
    print("\n[F5] Quién sigue a la cuenta y a quién sigue ella")
    prep(TEMPORAL("f5"))

    def captura(tipo, usuarios, dia="2026-09-09", completa=True):
        r = m._ruta_captura(tipo, dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": u, "nombre": "", "id": i},
                                 m.CABECERA) for u, i in usuarios])
        m._escribir_meta(r, completa, len(usuarios), len(usuarios), "x")
        return r

    # ana y beto siguen a la cuenta; la cuenta sigue a beto y a caro.
    # Mutuo solo beto.
    captura("seguidores", [("ana", "1"), ("beto", "2")])
    captura("seguidos", [("beto", "2"), ("caro", "3")])
    m.cruzar_capturas(callado=True)

    DIA = "2026-09-09"
    por_nombre = {f["username"]: f
                  for f in leer(m._ruta_captura("seguidores", DIA))}
    check(por_nombre["ana"]["sigue_a_la_cuenta"] == "si",
          "quien está en seguidores sigue a la cuenta")
    check(por_nombre["ana"]["la_cuenta_le_sigue"] == "no",
          "y la cuenta no le devuelve el follow")
    check(por_nombre["beto"]["la_cuenta_le_sigue"] == "si",
          "beto sí es mutuo")

    seguidos = {f["username"]: f
                for f in leer(m._ruta_captura("seguidos", DIA))}
    check(seguidos["caro"]["la_cuenta_le_sigue"] == "si"
          and seguidos["caro"]["sigue_a_la_cuenta"] == "no",
          "la cuenta sigue a caro y caro no le devuelve el follow")
    check(seguidos["beto"]["sigue_a_la_cuenta"] == "si",
          "y beto sale mutuo también en la otra lista")

    # Volver a cruzar no debe cambiar nada ni duplicar columnas
    m.cruzar_capturas(callado=True)
    cab = m._cabecera_de(m._ruta_captura("seguidores", DIA))
    check(cab.count("sigue_a_la_cuenta") == 1, "cruzar dos veces no duplica")

    # --- las dos condiciones que evitan escribir un 'no' falso ---
    prep(TEMPORAL("f5b"))
    captura("seguidores", [("ana", "1")])
    captura("seguidos", [("ana", "1")], completa=False)
    m.cruzar_capturas(callado=True)
    filas = leer(m._ruta_captura("seguidores", DIA))
    check(filas[0]["la_cuenta_le_sigue"] == "",
          "con una captura incompleta no se escribe nada: serían noes falsos")

    prep(TEMPORAL("f5c"))
    captura("seguidores", [("ana", "1")], dia="2026-09-09")
    captura("seguidos", [("beto", "2")], dia="2026-08-01")
    aviso = m.cruzar_capturas(callado=True)
    check("días distintos" in aviso, f"y avisa si son de días distintos")
    filas = leer(m._ruta_captura("seguidores", "2026-09-09"))
    check(filas[0]["la_cuenta_le_sigue"] == "",
          "tampoco se cruzan capturas de fechas distintas")


def f6_cambios_de_relacion():
    print("\n[F6] De qué TIPO fue cada cambio, respecto a la cuenta objetivo")
    prep(TEMPORAL("f6"))

    def dia(fecha, seguidores, seguidos):
        for tipo, gente in (("seguidores", seguidores),
                            ("seguidos", seguidos)):
            r = m._ruta_captura(tipo, fecha)
            m._escribir_csv(r, m.CABECERA,
                            [m._fila({"username": u, "nombre": "", "id": u[0]},
                                     m.CABECERA) for u in gente])
            m._escribir_meta(r, True, len(gente), len(gente), "completa")

    # ana: mutua -> deja de seguir a la cuenta (la cuenta la sigue todavía)
    # beto: mutuo -> la cuenta deja de seguirle (él sigue ahí)
    # caro: mutua -> desaparece del todo
    # dani: solo seguía a la cuenta -> la cuenta le devuelve el follow
    # eva: nueva mutua
    dia("2026-09-01", ["ana", "beto", "caro", "dani"],
        ["ana", "beto", "caro"])
    dia("2026-09-08", ["beto", "dani", "eva"],
        ["ana", "dani", "eva"])

    cambios = {f["username"]: f["cambio"] for f in m.cambios_de_relacion()}
    check(cambios.get("ana") == "dejó de seguir a la cuenta",
          f"la que dejó de seguir a la cuenta ({cambios.get('ana')})")
    check(cambios.get("beto") == "la cuenta dejó de seguirle",
          f"y aquel al que la cuenta dejó de seguir ({cambios.get('beto')})")
    check(cambios.get("caro") == "era mutuo y desapareció",
          f"el que se fue del todo ({cambios.get('caro')})")
    check(cambios.get("dani") == "la cuenta le devolvió el follow",
          f"el follow devuelto ({cambios.get('dani')})")
    check(cambios.get("eva") == "nuevo mutuo",
          f"y la nueva mutua ({cambios.get('eva')})")

    # Es lo que 'comparar' no distingue: ana, beto y caro se ven todos igual
    # en «entró/salió», y no son lo mismo.
    informe = m.carpeta_cuenta() / "relacion_t_2026-09-08.csv"
    check(informe.exists(), "deja informe")
    check({f["cambio"] for f in leer(informe)} == set(cambios.values()),
          "con los mismos cambios que se imprimieron")

    # Sin dos días completos de las dos listas no se puede decir nada
    prep(TEMPORAL("f6b"))
    dia("2026-09-01", ["ana"], ["ana"])
    check(m.cambios_de_relacion() == [],
          "con un solo día no se inventa ningún cambio")

    prep(TEMPORAL("f6c"))
    dia("2026-09-01", ["ana"], ["ana"])
    r = m._ruta_captura("seguidores", "2026-09-08")
    m._escribir_csv(r, m.CABECERA, [])
    m._escribir_meta(r, False, 100, 0, "truncada")
    m._escribir_csv(m._ruta_captura("seguidos", "2026-09-08"), m.CABECERA, [])
    m._escribir_meta(m._ruta_captura("seguidos", "2026-09-08"),
                     True, 0, 0, "completa")
    check(m.cambios_de_relacion() == [],
          "una truncada no cuenta como día: diría que se fueron todos")


def f12_indice_de_eventos():
    print("\n[F12] El índice: mismo resultado, sin releerlo todo")
    import indice_eventos as ie

    # --- la estructura, sin tocar disco ---
    idx = ie.nuevo(True)
    for i, (fecha, gente) in enumerate((
            ("2026-09-01", {"1": {"username": "ana", "nombre": "A"},
                            "2": {"username": "beto", "nombre": "B"}}),
            ("2026-09-02", {"1": {"username": "ana", "nombre": "A"}}),
            ("2026-09-03", {"1": {"username": "ana2", "nombre": "A"},
                            "2": {"username": "beto", "nombre": "B"}}))):
        ie.anadir_captura(idx, fecha, gente)

    check(idx["gente"]["1"]["t"] == [[0, 2]],
          f"quien no se mueve ocupa UN tramo ({idx['gente']['1']['t']})")
    check(idx["gente"]["2"]["t"] == [[0, 0], [2, 2]],
          f"y quien se va y vuelve, dos ({idx['gente']['2']['t']})")

    p = ie.derivar(idx)["personas"]
    check(p["2"]["entradas"] == 2 and p["2"]["salidas"] == 1,
          f"entradas y salidas de quien va y viene ({p['2']})")
    check(p["1"]["nombres"] == ["ana", "ana2"], "la cadena de nombres")
    check(p["1"]["capturas"] == 3 and p["1"]["presente"] is True,
          "y el recuento de presencias")

    # Quitar una captura del medio NO parte a nadie en dos: esa persona no
    # se fue, es que ese día no se la miró.
    p = ie.derivar(idx, {1})["personas"]
    check(p["2"]["entradas"] == 1 and p["2"]["salidas"] == 0,
          f"sin la captura mala, beto no se fue nunca ({p['2']})")
    check(len(ie.derivar(idx, {1})["fechas"]) == 2, "y la serie se acorta")

    # --- lo incremental tiene que dar lo mismo que reconstruir ---
    carpeta = prep(TEMPORAL("f12"))
    dias = ["2026-09-0" + str(i) for i in range(1, 8)]
    for i, dia in enumerate(dias):
        gente = ["ana", "beto", "caro"][: 2 + (i % 2)]
        if i == 4:
            gente = ["ana"]             # un desplome, para el filtro
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": u, "nombre": u.upper(),
                                  "id": u[0]}, m.CABECERA) for u in gente])
        m._escribir_meta(r, True, len(gente), len(gente), "completa")
        # Se consulta en CADA paso: así el índice se amplía de uno en uno.
        m.construir_historial("seguidores")

    poco_a_poco = m.construir_historial("seguidores")
    m._ruta_indice("seguidores").unlink()          # y ahora desde cero
    de_una_vez = m.construir_historial("seguidores")
    check(poco_a_poco == de_una_vez,
          "ampliar día a día da EXACTAMENTE lo mismo que reconstruir")

    # --- borrar capturas viejas no borra el historial ---
    antes = m.construir_historial("seguidores")
    for r in m._capturas("seguidores")[:3]:
        m._ruta_meta(r).unlink()
        r.unlink()
    despues = m.construir_historial("seguidores")
    check(despues["fechas"] == antes["fechas"],
          "las fechas de las capturas borradas siguen en el historial")
    check(despues["personas"] == antes["personas"],
          "y la trayectoria de cada persona, intacta")

    # --- pero si una captura CAMBIA, hay que rehacerlo ---
    ultima = m._capturas("seguidores")[-1]
    filas = m._leer_csv(ultima)
    filas.append({"username": "nueva", "nombre": "N", "id": "n"})
    m._escribir_csv(ultima, m.CABECERA,
                    [m._fila(f, m.CABECERA) for f in filas])
    rehecho = m.construir_historial("seguidores")
    check("n" in rehecho["personas"] or any(
        p["username"] == "nueva" for p in rehecho["personas"].values()),
        "una captura modificada se vuelve a procesar")

    # --- y si deja de haber ids, la clave cambia y el índice no vale ---
    check(ie.sirve({"version": ie.VERSION, "usar_id": True}, True), "sirve")
    check(not ie.sirve({"version": ie.VERSION, "usar_id": True}, False),
          "un índice por id no vale si la serie pasa a nombres de usuario")
    check(not ie.sirve({"version": 0, "usar_id": True}, True),
          "ni uno de una versión anterior")


def f13_podar_sin_perder_historial():
    print("\n[F13] Podar capturas viejas sin perder la historia")
    prep(TEMPORAL("f13"))
    hoy = date.today()

    def captura(cuando, gente, con_meta=True):
        r = m._ruta_captura("seguidores", f"{cuando:%Y-%m-%d}")
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": u, "nombre": "", "id": u},
                                 m.CABECERA) for u in gente])
        if con_meta:
            m._escribir_meta(r, True, len(gente), len(gente), "completa")
        return r

    # Diez semanas de capturas diarias, y algunas de este mes
    for k in range(70, 0, -1):
        captura(hoy - timedelta(days=k), ["ana", "beto"])
    captura(hoy, ["ana"])

    antes = m.construir_historial("seguidores")
    class Args:
        dias, hacerlo = 30, True
    m.cmd_podar(Args())
    despues = m.construir_historial("seguidores")

    check(despues["fechas"] == antes["fechas"],
          "el historial conserva TODAS las fechas, también las podadas")
    check(despues["personas"] == antes["personas"],
          "y la trayectoria de cada persona no cambia")

    quedan = [m._fecha_de(r) for r in m._capturas("seguidores")]
    check(f"{hoy:%Y-%m-%d}" in quedan, "la última nunca se toca")
    recientes = sum(1 for f in quedan
                    if (hoy - date.fromisoformat(f)).days <= 30)
    check(recientes == 31, f"los últimos 30 días, enteros ({recientes})")
    check(len(quedan) < 45, f"y más atrás, una por semana ({len(quedan)})")

    # Por defecto no borra: decirlo y hacerlo son cosas distintas
    prep(TEMPORAL("f13b"))
    for k in range(70, 0, -1):
        captura(hoy - timedelta(days=k), ["ana"])
    captura(hoy, ["ana"])
    m.construir_historial("seguidores")
    cuantas = len(m._capturas("seguidores"))
    check(len(m.podar(30, hacerlo=False)) > 0, "dice qué sobra")
    check(len(m._capturas("seguidores")) == cuantas,
          "pero sin --hacerlo no borra ni una")

    # Y lo que el índice no ha aprendido todavía, no se toca: su información
    # está ahí dentro y solo ahí.
    prep(TEMPORAL("f13c"))
    for k in range(70, 60, -1):
        captura(hoy - timedelta(days=k), ["ana"])
    captura(hoy, ["ana"])
    check(m.podar(30, hacerlo=False) == [],
          "sin índice construido no se borra nada")


def f14_repaso_del_indice():
    print("\n[F14] Lo que se encontró repasando el índice")
    import indice_eventos as ie

    # --- descartar una captura de DENTRO de un tramo largo no parte a nadie
    idx = ie.nuevo(True)
    for d in range(6):
        ie.anadir_captura(idx, f"2026-09-0{d + 1}",
                          {"1": {"username": "ana", "nombre": "A"}})
    check(idx["gente"]["1"]["t"] == [[0, 5]], "seis capturas, un solo tramo")

    p = ie.derivar(idx, {2})["personas"]["1"]
    check(p["entradas"] == 1 and p["salidas"] == 0,
          f"quitar una del medio no la parte en dos ({p['entradas']} "
          f"entradas)")
    check(p["capturas"] == 5, "y cuenta una presencia menos")
    check(ie.derivar(idx, {0})["personas"]["1"]["primera"] == "2026-09-02",
          "quitar la primera mueve el comienzo")
    check(ie.derivar(idx, {5})["personas"]["1"]["presente"] is True,
          "y quitar la última deja presente a quien seguía estando")

    # --- una captura ya indexada que DESPUÉS se marca truncada
    prep(TEMPORAL("f14"))
    for dia, gente in (("2026-09-01", ["ana", "beto"]),
                       ("2026-09-02", ["ana", "beto"]),
                       ("2026-09-03", ["ana"])):
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": u, "nombre": "", "id": u},
                                 m.CABECERA) for u in gente])
        m._escribir_meta(r, True, len(gente), len(gente), "completa")

    antes = m.construir_historial("seguidores")
    check(len(antes["fechas"]) == 3, "las tres cuentan")

    # Se descubre que la última estaba truncada
    m._escribir_meta(m._ruta_captura("seguidores", "2026-09-03"),
                     False, 2, 1, "solo 1 de 2")
    despues = m.construir_historial("seguidores")
    check(len(despues["fechas"]) == 2,
          f"la truncada sale del historial ({despues['fechas']})")
    check(despues["personas"]["beto"]["presente"] is True,
          "y beto vuelve a constar presente: no se había ido")

    # --- el índice se escribe entero o no se escribe
    indice = m._ruta_indice("seguidores")
    check(indice.exists() and json.loads(indice.read_text(encoding="utf-8")),
          "el índice queda legible")
    check(not list(m.carpeta_cuenta().glob("*.tmp")),
          "y no deja archivos a medias por el camino")


def f42_comparar_dos_fechas():
    print("\n[F42] Comparar dos fechas cualesquiera, no solo las dos últimas")
    F = ["2026-08-01", "2026-08-15", "2026-09-01", "2026-09-10"]

    # --- la elección de fechas, que es pura --------------------------
    check(m.elegir_capturas(F)[:2] == ("2026-09-01", "2026-09-10"),
          "sin pedir nada, las dos últimas como siempre")
    check(m.elegir_capturas(F, desde="2026-08-01")[:2]
          == ("2026-08-01", "2026-09-10"), "solo desde: de ahí hasta hoy")
    check(m.elegir_capturas(F, hasta="2026-09-01")[:2]
          == ("2026-08-15", "2026-09-01"),
          "solo hasta: qué cambió ESE día, contra la anterior")
    check(m.elegir_capturas(F, "2026-08-01", "2026-09-01")[:2]
          == ("2026-08-01", "2026-09-01"), "las dos: justo esas")

    # Una fecha pedida casi nunca cae en un día con captura
    a, b, avisos = m.elegir_capturas(F, desde="2026-08-20")
    check(a == "2026-08-15", "se resuelve hacia atrás: la última foto hasta "
                             "entonces es cómo estaba ese día")
    check(avisos and "2026-08-15" in avisos[0],
          "y se DICE cuál se usó: elegir por el usuario está bien, "
          "hacerlo en silencio no")

    a, b, avisos = m.elegir_capturas(F, desde="2026-01-01")
    check(a == F[0] and avisos, "antes de todo el historial: la primera")

    # Al revés se ordenan, en vez de rechazarlo: quien las escribe al
    # revés quiere ese intervalo, no un error.
    a, b, avisos = m.elegir_capturas(F, "2026-09-01", "2026-08-01")
    check((a, b) == ("2026-08-01", "2026-09-01"), "las fechas al revés se "
                                                  "ponen en orden")
    check(avisos and "al revés" in avisos[0], "diciéndolo")

    a, b, avisos = m.elegir_capturas(F, "2026-09-10", "2026-09-10")
    check(a is None and avisos, "la misma dos veces no compara nada")
    check(m.elegir_capturas(["2026-09-10"])[0] is None,
          "con una sola captura, no hay par")
    check(m.elegir_capturas([])[1] is None, "y sin ninguna, tampoco revienta")

    # --- y de punta a punta, sobre capturas de verdad -----------------
    carpeta = prep(TEMPORAL("f42"))
    m.recordar_id("t", "1")
    ids = {"ana": "1", "luis": "2", "eva": "3", "raul": "4", "sofia": "5"}
    gente = {"2026-08-01": ["ana", "luis", "eva"],
             "2026-08-15": ["ana", "luis", "eva", "raul"],
             "2026-09-01": ["ana", "eva", "raul"],
             "2026-09-10": ["ana", "eva", "raul", "sofia"]}
    for dia, nombres in gente.items():
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": n, "id": ids[n]}, m.CABECERA)
                         for n in nombres])
        m._escribir_meta(r, True, len(nombres), len(nombres), "completa")

    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        r = m.comparar("seguidores", desde="2026-08-01", hasta="2026-09-01")
    texto = salida.getvalue()
    check("2026-08-01 -> 2026-09-01" in texto, "compara el intervalo pedido")
    # En agosto se fue luis y entró raul, y el total no se movió: es
    # exactamente el cambio de neto cero que el proyecto persigue desde
    # la v2.1, y que solo se ve comparando las personas.
    check("Neto: +0" in texto and "el total no cambió" in texto,
          "y ve el cambio de neto cero dentro del intervalo")
    check("luis" in texto and "raul" in texto, "diciendo quién")
    check(r["fecha"] == "2026-09-01",
          "el resultado describe el final del intervalo pedido")

    # Sin pedir nada, se comporta igual que siempre
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        r = m.comparar("seguidores")
    check("2026-09-01 -> 2026-09-10" in salida.getvalue(),
          "sin fechas, las dos últimas: no cambia lo que ya funcionaba")


def f44_cruzar_dos_cuentas():
    print("\n[F44] Qué comparten dos cuentas")

    # --- el cruce, que es puro -----------------------------------------
    a = {"1": {"username": "ana"}, "2": {"username": "luis"},
         "3": {"username": "eva"}}
    b = {"3": {"username": "eva"}, "4": {"username": "sofia"}}
    r = m.cruzar_dos(a, b)
    check([a[c]["username"] for c in r["solo_a"]] == ["ana", "luis"],
          "quién está solo en la primera")
    check([b[c]["username"] for c in r["solo_b"]] == ["sofia"],
          "quién solo en la segunda")
    check([a[c]["username"] for c in r["ambas"]] == ["eva"], "y en las dos")
    check(m.cruzar_dos({}, {}) == {"solo_a": [], "solo_b": [], "ambas": []},
          "dos listas vacías no revientan")

    # Cruza por CLAVE, no por nombre: la misma persona con otro nombre de
    # usuario sigue siendo la misma. Es el error que el proyecto arrastró
    # hasta la v3.1.
    renombrada = {"3": {"username": "eva_nueva"}}
    check(m.cruzar_dos(a, renombrada)["ambas"] == ["3"],
          "un cambio de nombre no la convierte en otra persona")

    # --- y de punta a punta --------------------------------------------
    carpeta = prep(TEMPORAL("f44"))
    for cuenta, personas in (("marca_a", {"ana": "1", "luis": "2",
                                          "eva": "3"}),
                             ("marca_b", {"eva": "3", "sofia": "4"})):
        m.recordar_id(cuenta, cuenta[-1])
        with m.con_cuenta(cuenta):
            r = m._ruta_captura("seguidores", "2026-09-10")
            m._escribir_csv(r, m.CABECERA,
                            [m._fila({"username": n, "id": i}, m.CABECERA)
                             for n, i in personas.items()])
            m._escribir_meta(r, True, len(personas), len(personas),
                             "completa")

    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        r = m.comun("marca_a", "marca_b")
    texto = salida.getvalue()
    check(r and len(r["ambas"]) == 1, "cruza las capturas de verdad")
    check("Solapamiento: 25%" in texto,
          f"y dice cuánto se solapan {texto.splitlines()[2:3]}")
    csv = list(m.carpeta_cuenta("marca_a").glob("comun_*.csv"))
    check(csv, "deja un CSV con todas, no solo las que caben en pantalla")
    check(len(m._leer_csv(csv[0])) == 4, "con las cuatro personas")

    # Después de cruzar, la cuenta en curso tiene que seguir siendo la de
    # antes: con_cuenta existe para eso y hay que respetarlo.
    check(m.OBJETIVO == "t", f"no se queda apuntando a otra ({m.OBJETIVO})")

    # --- lo que no se puede cruzar --------------------------------------
    with m.con_cuenta("marca_b"):
        ruta = m._ruta_captura("seguidores", "2026-09-10")
        m._escribir_meta(ruta, False, 100, 2, "cortada")
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        r = m.comun("marca_a", "marca_b")
    check(r is None and "incompleta" in salida.getvalue(),
          "una captura truncada no se cruza: daría diferencias falsas")

    # Fechas muy separadas: se cruza, pero se avisa
    with m.con_cuenta("marca_b"):
        vieja = m._ruta_captura("seguidores", "2026-01-01")
        m._escribir_csv(vieja, m.CABECERA,
                        [m._fila({"username": "x", "id": "9"}, m.CABECERA)])
        m._escribir_meta(vieja, True, 1, 1, "completa")
        m._ruta_captura("seguidores", "2026-09-10").unlink()
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        m.comun("marca_a", "marca_b")
    check("se llevan" in salida.getvalue(),
          "cruzar la foto de enero con la de septiembre se avisa: parte de "
          "la diferencia es del calendario, no de las cuentas")


def f46_cadena_de_integridad():
    print("\n[F46] Se puede demostrar que una captura no se tocó")
    import json as _json
    carpeta = prep(TEMPORAL("f46"))
    m.recordar_id("t", "1")

    def guardar(dia, gente):
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": n, "id": str(i)}, m.CABECERA)
                         for i, n in enumerate(gente)])
        m._escribir_meta(r, True, len(gente), len(gente), "completa")
        return r

    guardar("2026-08-01", ["ana", "luis"])
    guardar("2026-09-01", ["ana", "eva"])
    guardar("2026-09-10", ["ana", "eva", "raul"])

    v = m.verificar_cadena("seguidores")
    check(len(v["bien"]) == 3 and not v["rotas"], "las tres, intactas")
    cabeza = v["cabeza"]
    check(len(cabeza) == 64, "y una cabeza que resume el historial entero")

    # Volver a guardar lo mismo en otro orden NO es una manipulación: la
    # huella cubre QUIÉN estaba, no cómo quedó ordenado el archivo.
    r = m._ruta_captura("seguidores", "2026-09-01")
    filas = list(reversed(m._leer_csv(r)))
    m._escribir_csv(r, m.CABECERA, [m._fila(f, m.CABECERA) for f in filas])
    check(not m.verificar_cadena("seguidores")["rotas"],
          "reordenar las filas no cuenta como cambio")

    # Y rellenar una columna CALCULADA tampoco: la hace este programa.
    filas = m._leer_csv(r)
    for f in filas:
        f["sigue_a_la_cuenta"] = "si"
    m._escribir_csv(r, m.CABECERA, [m._fila(f, m.CABECERA) for f in filas])
    check(not m.verificar_cadena("seguidores")["rotas"],
          "rellenar una columna calculada tampoco: no vino de Instagram")

    # Lo que sí es un cambio
    filas = m._leer_csv(r)
    filas[0]["username"] = "impostor"
    m._escribir_csv(r, m.CABECERA, [m._fila(f, m.CABECERA) for f in filas])
    v = m.verificar_cadena("seguidores")
    check([f for f, _ in v["rotas"]] == ["2026-09-01"],
          f"cambiar a una persona sí se ve ({v['rotas']})")

    # El ataque que justifica encadenar: editar Y resellar bien. La
    # captura vuelve a cuadrar consigo misma, pero rompe la siguiente.
    meta = m._leer_meta(r)
    h = m.huella_de_captura(r)
    meta.update({"huella": h, "cadena": m._eslabon(h, meta["anterior"])})
    m.escribir_atomico(m._ruta_meta(r), _json.dumps(meta, indent=2))
    v = m.verificar_cadena("seguidores")
    # La siguiente conserva su contenido, así que sale como DESCOLOCADA y
    # no como rota. La cadena no puede distinguir esto de una restauración
    # legítima —las dos cambian lo que va antes— y por eso la garantía de
    # verdad está en la cabeza guardada fuera, no en la etiqueta.
    check(v["descolocadas"] == ["2026-09-10"],
          f"resellar lo editado descoloca la SIGUIENTE ({v['descolocadas']})")
    check(not v["rotas"], "sin marcarla como rota: sus datos están enteros")

    # Y lo que hace que guardar la cabeza fuera sirva de algo. La primera
    # versión la leía del último sello, que el atacante no necesita tocar:
    # la cabeza salía idéntica y anclarla no valía nada.
    check(v["cabeza"] != cabeza,
          "la cabeza cambia: se recalcula de los archivos, no se copia "
          "del último sello")

    # Una captura de antes de los sellos no es una captura corrupta
    vieja = m._ruta_captura("seguidores", "2026-07-01")
    m._escribir_csv(vieja, m.CABECERA,
                    [m._fila({"username": "x", "id": "9"}, m.CABECERA)])
    v = m.verificar_cadena("seguidores")
    check(v["sin_sellar"] == ["2026-07-01"],
          "sin sellar no es lo mismo que rota, y se cuenta aparte")


def f47_grafo_de_varias_cuentas():
    print("\n[F47] El grafo de quién aparece en el círculo de qué cuentas")
    import xml.etree.ElementTree as ET
    prep(TEMPORAL("f47"))

    audiencias = {"marca_a": ["ana", "luis", "eva", "raul"],
                  "marca_b": ["eva", "raul", "sofia"],
                  "marca_c": ["raul", "sofia", "tito"]}
    for cuenta, gente in audiencias.items():
        m.recordar_id(cuenta, cuenta[-1])
        with m.con_cuenta(cuenta):
            r = m._ruta_captura("seguidores", "2026-09-10")
            m._escribir_csv(r, m.CABECERA,
                            [m._fila({"username": n, "id": n[0]}, m.CABECERA)
                             for n in gente])
            m._escribir_meta(r, True, len(gente), len(gente), "completa")

    g = m.construir_grafo(list(audiencias))
    personas = {n["etiqueta"]: n for n in g["nodos"].values()
                if n["clase"] == "persona"}
    check(len(personas) == 6, f"una persona por individuo ({len(personas)})")
    check(personas["raul"]["en_cuantas"] == 3,
          "quien está en las tres, cuenta 3")
    check(personas["ana"]["en_cuantas"] == 1, "y quien está en una, 1")
    check(len(g["aristas"]) == 10, f"y las aristas ({len(g['aristas'])})")

    # El sentido de la flecha no es decorativo: en 'seguidores' la persona
    # apunta a la cuenta, y al revés en 'seguidos'.
    origen, destino = g["aristas"][0]
    check(origen.startswith("persona:") and destino.startswith("cuenta:"),
          "en seguidores, la persona apunta a la cuenta")
    with m.con_cuenta("marca_a"):
        r = m._ruta_captura("seguidos", "2026-09-10")
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": "ana", "id": "a"},
                                 m.CABECERA)])
        m._escribir_meta(r, True, 1, 1, "completa")
    g2 = m.construir_grafo(["marca_a"], "seguidos")
    origen2, destino2 = g2["aristas"][0]
    check(origen2.startswith("cuenta:") and destino2.startswith("persona:"),
          "y en seguidos, la cuenta apunta a la persona")

    # GraphML válido de verdad, no una cadena con pinta de XML
    xml = m.a_graphml(g)
    arbol = ET.fromstring(xml)
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    check(len(arbol.findall(".//g:node", ns)) == 9, "nueve nodos en el XML")
    check(len(arbol.findall(".//g:edge", ns)) == 10, "y diez aristas")
    check(arbol.find(".//g:graph", ns).get("edgedefault") == "directed",
          "dirigido, que es lo que hace útil el sentido")

    # Un nombre con caracteres de XML no puede romper el archivo
    feo = {"nodos": {"persona:1": {"etiqueta": 'Ana & <b>"Lu"</b>',
                                   "clase": "persona", "fecha": "",
                                   "en_cuantas": 1}},
           "aristas": [], "fuera": [], "tipo": "seguidores"}
    ET.fromstring(m.a_graphml(feo))
    check(True, "un nombre con & < > y comillas no rompe el XML")

    # Una cuenta con la última captura incompleta se queda fuera y se dice
    with m.con_cuenta("marca_b"):
        m._escribir_meta(m._ruta_captura("seguidores", "2026-09-10"),
                         False, 100, 3, "cortada")
    g = m.construir_grafo(list(audiencias))
    check([c for c, _ in g["fuera"]] == ["marca_b"],
          "una captura truncada deja su cuenta fuera, no la mete a medias")


def f48_repaso_sellos_y_grafo():
    print("\n[F48] Lo que se encontró repasando los sellos y el grafo")
    prep(TEMPORAL("f48"))
    m.recordar_id("t", "1")

    def guardar(dia, gente):
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": n, "id": str(i)}, m.CABECERA)
                         for i, n in enumerate(gente)])
        m._escribir_meta(r, True, len(gente), len(gente), "completa")

    # 1. Restaurar una copia que rellena un hueco NO es manipulación. El
    #    contenido está intacto; lo que cambió es qué hay antes. Llamarlo
    #    «rota» es la clase de falsa alarma que hace que nadie mire
    #    ninguna alarma.
    guardar("2026-09-01", ["ana"])
    guardar("2026-09-10", ["ana", "eva"])
    guardar("2026-08-01", ["solo", "yo"])        # llega de una copia
    v = m.verificar_cadena("seguidores")
    check(not v["rotas"],
          f"nada roto: los datos están enteros ({v['rotas']})")
    check(v["descolocadas"] == ["2026-09-01"],
          f"se marca como descolocada, aparte ({v['descolocadas']})")

    # Y editar de verdad SÍ es rota, no descolocada
    r = m._ruta_captura("seguidores", "2026-09-10")
    filas = m._leer_csv(r)
    filas[0]["username"] = "impostor"
    m._escribir_csv(r, m.CABECERA, [m._fila(f, m.CABECERA) for f in filas])
    v = m.verificar_cadena("seguidores")
    check([f for f, _ in v["rotas"]] == ["2026-09-10"],
          "editar el contenido sigue saliendo como rota")

    # 2. El grafo con unas capturas con ids y otras sin ellos parte a la
    #    misma persona en dos nodos, los dos con en_cuantas=1. O sea que
    #    miente justo en lo que se le pregunta: quién hace de puente.
    prep(TEMPORAL("f48b"))
    for cuenta, con_id in (("marca_a", True), ("marca_b", False)):
        m.recordar_id(cuenta, cuenta[-1])
        with m.con_cuenta(cuenta):
            ruta = m._ruta_captura("seguidores", "2026-09-10")
            fila = {"username": "ana", "id": "77"} if con_id \
                else {"username": "ana"}
            m._escribir_csv(ruta, m.CABECERA, [m._fila(fila, m.CABECERA)])
            m._escribir_meta(ruta, True, 1, 1, "completa")

    g = m.construir_grafo(["marca_a", "marca_b"])
    check(g["mezcla_de_claves"],
          "se detecta que unas capturas llevan ids y otras no")
    check(g["sin_id"] == ["marca_b"], "y cuál es la que falta")

    # Con TODAS sin ids el grafo es coherente: solo frágil ante cambios de
    # nombre. No es lo mismo y no se avisa igual.
    prep(TEMPORAL("f48c"))
    for cuenta in ("marca_a", "marca_b"):
        m.recordar_id(cuenta, cuenta[-1])
        with m.con_cuenta(cuenta):
            ruta = m._ruta_captura("seguidores", "2026-09-10")
            m._escribir_csv(ruta, m.CABECERA,
                            [m._fila({"username": "ana"}, m.CABECERA)])
            m._escribir_meta(ruta, True, 1, 1, "completa")
    g = m.construir_grafo(["marca_a", "marca_b"])
    check(not g["mezcla_de_claves"],
          "con todas sin ids no hay mezcla: el grafo cuadra consigo mismo")
    personas = [n for n in g["nodos"].values() if n["clase"] == "persona"]
    check(len(personas) == 1 and personas[0]["en_cuantas"] == 2,
          "y ana sale una vez, en las dos cuentas")


def f49_estudio_sin_peticiones():
    print("\n[F49] Lo que el disco ya puede responder")
    import analitica as an

    # Historial inventado: no hace falta montar capturas para comprobar
    # funciones puras, que es justo para lo que se escribieron así.
    t = {"fechas": ["2026-07-01", "2026-08-01", "2026-08-15", "2026-09-01"],
         "personas": {
             "1": {"username": "ya_estaba", "primera": "2026-07-01",
                   "ultima": "2026-09-01", "presente": True, "entradas": 1},
             "2": {"username": "agosto_sigue", "primera": "2026-08-01",
                   "ultima": "2026-09-01", "presente": True, "entradas": 1},
             "3": {"username": "agosto_se_fue", "primera": "2026-08-01",
                   "ultima": "2026-08-15", "presente": False, "entradas": 1},
             "4": {"username": "vuelve", "primera": "2026-08-01",
                   "ultima": "2026-09-01", "presente": True, "entradas": 2},
         }}

    c = {d["mes"]: d for d in an.cohortes(t)}
    check(list(c) == ["2026-08"],
          f"solo cohorte de agosto: julio es la primera captura ({list(c)})")
    # Quien ya estaba el primer día NO entró ese mes: estaba. Contarlo
    # inflaría la primera cohorte con gente que puede llevar años.
    check(c["2026-08"]["entraron"] == 3, "los tres que entraron en agosto")
    check(c["2026-08"]["siguen"] == 2 and c["2026-08"]["retencion"] == 67,
          "y cuántos siguen")

    p = an.permanencia(t)
    check(p["casos"] == 1, f"solo se mide a quien YA se fue ({p['casos']})")
    check(p["mediana"] == 14, f"catorce días ({p.get('mediana')})")

    # Y a quien va y viene NO se le resta la última fecha de la primera:
    # eso contaría como dentro todo el tiempo que estuvo fuera. Dos
    # semanas en julio y dos en septiembre daban 69 días de permanencia
    # cuando fueron 14.
    ida_y_vuelta = {
        "fechas": ["2026-06-01", "2026-07-01", "2026-07-08",
                   "2026-09-01", "2026-09-08"],
        "personas": {
            "1": {"username": "vuelve", "primera": "2026-07-01",
                  "ultima": "2026-09-08", "presente": False, "entradas": 2},
            "2": {"username": "normal", "primera": "2026-07-01",
                  "ultima": "2026-07-08", "presente": False, "entradas": 1}}}
    p2 = an.permanencia(ida_y_vuelta)
    check(p2["casos"] == 1 and p2["mediana"] == 7,
          f"quien va y viene no infla la mediana ({p2['mediana']})")
    check(p2["aparte"] == 1, "y se cuenta aparte, no se esconde")
    # Contar a los que siguen dentro bajaría la cifra: su permanencia
    # todavía no ha terminado. Es el error clásico de medir duraciones
    # con casos abiertos.
    check(an.permanencia({"fechas": ["2026-09-01"], "personas": {}})["casos"]
          == 0, "con una sola captura no se mide nada")

    r = an.recurrentes(t)
    check([x["username"] for x in r] == ["vuelve"], "quién se fue y volvió")

    # La composición distingue «0%» de «no se sabe», que es la regla de
    # este proyecto desde la v2.x.
    comp = an.composicion([{"privada": "si", "verificada": ""},
                           {"privada": "no", "verificada": "no"}])
    check(comp["privada"]["porcentaje"] == 50, "porcentaje sobre lo que hay")
    check(comp["verificada"]["sin_dato"] == 1, "y cuántas no traían el dato")
    vacio = an.composicion([{"privada": ""}, {"privada": ""}])
    check(vacio["privada"]["porcentaje"] is None,
          "una columna vacía da None, no 0%: no es lo mismo")
    check(an.composicion([])["total"] == 0, "una lista vacía no revienta")

    # Huecos: sostienen todo lo demás
    h = an.huecos(["2026-09-01", "2026-09-02", "2026-09-20"])
    check(len(h) == 1 and h[0]["dias"] == 17,
          f"detecta el hueco y mide los días de dentro ({h[0]['dias']})")

    # Publicar contra crecer, con el formato REAL de totales.csv, que es
    # una lista y no un diccionario: ese CSV no tiene columna 'username' y
    # el lector de perfiles lo descartaría entero.
    totales = [[f"2026-09-{d:02d}", str(100 + d * 2), "30",
                str(10 + d // 2)] for d in range(1, 15)]
    pc = an.publicar_vs_crecer(totales)
    check(pc["tramos"] == 13,
          f"lee el formato de totales.csv ({pc['tramos']})")
    check(pc["bastante"], "con trece tramos hay bastante para comparar")
    pocos = an.publicar_vs_crecer(totales[:4])
    check(not pocos["bastante"],
          "con tres tramos NO: la diferencia sería ruido, y se dice")


def f54_leyenda_de_relaciones():
    print("\n[F54] Las tres relaciones se explican, y en un solo sitio")
    import informe_html

    # El informe las llamaba «no_devuelve» y «no_correspondido», que en
    # español son casi sinónimos: no había forma de saber cuál era cuál
    # sin leer el código. Y el proyecto ya tenía OTROS nombres para lo mismo en
    # estado_relacion_en(). Dos vocabularios para tres estados.
    tres = {"mutuo", "solo_sigue_a_la_cuenta", "solo_la_cuenta_le_sigue"}
    check(set(m.LEYENDA_RELACION) == tres,
          "un solo vocabulario, el que ya usaba el resto del proyecto")
    fuente = Path("instagram_listas.py").read_text(encoding="utf-8")
    for viejo_nombre in ('"no_devuelve"', '"no_correspondido"'):
        check(viejo_nombre not in fuente,
              f"no queda ningún {viejo_nombre}")

    # Los estados que escribe estado_relacion_en() tienen que ser
    # exactamente los que explica la leyenda: si se separan, el informe
    # explicaría palabras que no aparecen.
    for estado in m.LEYENDA_RELACION:
        if estado == "mutuo":
            continue
        check(f'"{estado}"' in fuente, f"«{estado}» se usa de verdad")

    # Con el nombre real de la cuenta dentro: «la cuenta» obligaba a
    # traducir mentalmente en cada línea.
    con_nombre = m.leyenda_relacion("mr_psychoanalyst")
    check("@mr_psychoanalyst" in con_nombre["solo_sigue_a_la_cuenta"],
          "la leyenda usa el nombre real, no «la cuenta»")
    check("la cuenta" in m.leyenda_relacion()["solo_sigue_a_la_cuenta"],
          "y sin nombre, dice «la cuenta»")

    # Las dos frases que se confunden tienen la MISMA forma, para poder
    # compararlas de un vistazo en vez de leerlas enteras.
    a = con_nombre["solo_sigue_a_la_cuenta"]
    b = con_nombre["solo_la_cuenta_le_sigue"]
    check(a.count("pero") == b.count("pero") == 1,
          "las dos se leen con la misma estructura")
    check(a != b, "y dicen cosas distintas")

    # La consola de relaciones usa ESTOS textos y no los suyos propios.
    # Antes decía «sigue y no le devuelven el follow», que no coincidía
    # con nada de lo que se veía en la tabla.
    fuente_motor = Path("instagram_listas.py").read_text(encoding="utf-8")
    check("Sigue y no le devuelven el follow" not in fuente_motor,
          "sin un tercer vocabulario en la consola")
    check("leyenda_relacion(OBJETIVO)" in fuente_motor,
          "la consola lee la misma leyenda")

    # La leyenda vive en el motor y la leen los tres sitios. Copiada se
    # separaría en el primer matiz que se corrigiera.
    html = informe_html.generar({
        "cuenta": "t", "listas": {}, "evolucion": {}, "generado": "x",
        "leyenda_relacion": dict(m.LEYENDA_RELACION),
        "relaciones": [{"relacion": "mutuo", "username": "ana",
                        "nombre": "Ana"},
                       {"relacion": "solo_sigue_a_la_cuenta",
                        "username": "luis", "nombre": "Luis & <b>"}]})
    check("<h2>Relaciones</h2>" in html, "el informe trae la sección")
    for texto in m.LEYENDA_RELACION.values():
        if "mutuo" in html and texto in html:
            continue
    check(m.LEYENDA_RELACION["mutuo"] in html,
          "con la explicación, no solo la palabra")
    check("&lt;b&gt;" in html, "y los nombres raros van escapados")

    # El JS del informe no puede tocar la tabla nueva. Usaba
    # `querySelectorAll("th")` sobre TODO el documento, así que al añadir
    # la tabla de relaciones sus encabezados quedaban enganchados al
    # ordenador de la otra: pulsar uno habría reordenado la tabla de
    # listas por una columna que no existe en ella.
    import re as _re
    js = _re.search(r"<script>(.*?)</script>", html, _re.S)
    check(js, "el informe lleva su JS dentro")
    for selector in _re.findall(r'querySelectorAll\(\s*"([^"]+)"',
                                js.group(1)):
        check(not selector.strip().startswith(("th", "table", "td", "tr")),
              f"ningún selector suelto de tabla: «{selector}»")

    # Y ningún id repetido, que rompería getElementById en silencio
    ids = _re.findall(r'id="([^"]+)"', html)
    check(len(ids) == len(set(ids)), f"sin ids duplicados ({ids})")

    # Sin relaciones calculadas no se inventa una sección vacía
    check("<h2>Relaciones</h2>" not in informe_html.generar(
        {"cuenta": "t", "listas": {}, "evolucion": {}, "generado": "x"}),
        "sin datos, no aparece la sección")


def r9_relaciones_avisa_fechas():
    print("\n[R9] relaciones() debe avisar si cruza fechas distintas")
    prep(TEMPORAL("r9"))
    captura("seguidores", "2026-08-01", [("ana", "", "1")])
    captura("seguidores", "2026-08-02", [("ana", "", "1"), ("beto", "", "2")])
    captura("seguidos", "2026-09-01", [("ana", "", "1")])
    captura("seguidos", "2026-09-02", [("ana", "", "1"), ("gato", "", "3")])

    seg = m.comparar("seguidores")
    sig = m.comparar("seguidos")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.relaciones(seg, sig)
    salida = buf.getvalue()
    check("fechas distintas" in salida, "avisa del cruce de fechas")

    rel = leer(m.carpeta_cuenta() / "relaciones_t.csv")
    por = {}
    for x in rel:
        por.setdefault(x["relacion"], set()).add(x["username"])
    check(por.get("mutuo") == {"ana"}, f"mutuos correctos ({por.get('mutuo')})")
    # Los nombres son los de estado_relacion_en(), no otros: «no_devuelve»
    # y «no_correspondido» eran sinónimos y nadie sabía cuál era cuál.
    check(por.get("solo_la_cuenta_le_sigue") == {"gato"},
          "la cuenta le sigue y no le devuelven")
    check(por.get("solo_sigue_a_la_cuenta") == {"beto"},
          "le siguen y la cuenta no devuelve")

    print("  --- misma fecha: no debe avisar ---")
    prep(TEMPORAL("r9b"))
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-02", [("ana", "", "1")])
    captura("seguidos", "2026-09-01", [("ana", "", "1")])
    captura("seguidos", "2026-09-02", [("ana", "", "1")])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.relaciones(m.comparar("seguidores"), m.comparar("seguidos"))
    check("fechas distintas" not in buf.getvalue(),
          "con la misma fecha no avisa")


def r12_analisis_sin_red():
    print("\n[R12] Si Instagram cerrara la puerta, el análisis debe seguir")
    prep(TEMPORAL("r12"))
    for dia, n in (("2026-09-05", 300), ("2026-09-06", 305),
                   ("2026-09-07", 310)):
        for tipo in ("seguidores", "seguidos"):
            r = m._ruta_captura(tipo, dia)
            m._escribir_csv(r, m.CABECERA,
                            [[f"u{i}", "N", str(i)] for i in range(n)])
            m._escribir_meta(r, True, n, n, "completa")

    # Se corta TODA salida a la red
    def sin_red(*a, **k):
        raise RuntimeError("Instagram no responde")

    m.pedir = sin_red
    m._pedir_texto = sin_red
    m.crear_sesion = sin_red

    import io
    import contextlib

    def corre(fn, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(args)
        return buf.getvalue()

    salida = corre(m.cmd_comparar, type("A", (), {
        "totales": False, "historico": False, "forzar": False})())
    check("SEGUIDORES" in salida, "comparar funciona sin red")
    check("Entraron" in salida, "y produce el análisis de verdad")

    salida = corre(m.cmd_historial, type("A", (), {
        "lista": "ambas", "min_entradas": 2,
        "incluir_sospechosas": False})())
    check("capturas" in salida, "historial funciona sin red")

    for nombre, fn, args in (("presupuesto", m.cmd_presupuesto, None),
                             ("contratos", m.cmd_contratos,
                              type("A", (), {"crear": False})()),
                             ("cuentas", m.cmd_cuentas,
                              type("A", (), {"anadir": None,
                                             "quitar": None})())):
        try:
            corre(fn, args)
            check(True, f"{nombre} funciona sin red")
        except Exception as e:
            check(False, f"{nombre} falla: {type(e).__name__}")


PRUEBAS = [
    h1_trayectoria_basica,
    h2_follow_unfollow,
    h3_excluye_truncadas,
    h4_cambio_de_nombre,
    h5_informe_csv,
    h6_bordes_historial,
    v1_decidir_disparadores,
    v2_neto_cero,
    v3_ignora_capturas_rotas,
    v4_conteo_y_log,
    v5_vigilar_end_to_end,
    v6_contar_no_dispara_descarga,
    f5_relacion_con_la_cuenta,
    f6_cambios_de_relacion,
    f12_indice_de_eventos,
    f13_podar_sin_perder_historial,
    f14_repaso_del_indice,
    f42_comparar_dos_fechas,
    f44_cruzar_dos_cuentas,
    f46_cadena_de_integridad,
    f47_grafo_de_varias_cuentas,
    f48_repaso_sellos_y_grafo,
    f49_estudio_sin_peticiones,
    f54_leyenda_de_relaciones,
    r9_relaciones_avisa_fechas,
    r12_analisis_sin_red,
]
