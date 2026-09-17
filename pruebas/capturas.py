"""
Capturas: formato, metadatos, fusión
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def e1_campos_extra():
    print("\n[E1] Los campos extra se guardan sin peticiones adicionales")
    prep(TEMPORAL("e1"))
    ig = FakeIG(0, 10)
    m.pedir = ig.pedir
    m.descargar(None, perfil(0, 10), "seguidos")

    filas = leer(m._ruta_captura("seguidos"))
    check(len(filas) == 10, "10 registros")
    check(ig.peticiones == 1, f"1 sola petición ({ig.peticiones})")

    cab = m._cabecera_de(m._ruta_captura("seguidos"))
    check(cab[:3] == ["username", "nombre", "id"],
          "las 3 columnas de siempre siguen primero")
    for col in ("privada", "verificada", "foto_defecto",
                "sigue_a_la_cuenta", "la_cuenta_le_sigue"):
        check(col in cab, f"columna '{col}' presente")

    check(filas[0]["privada"] == "si" and filas[1]["privada"] == "no",
          "booleanos como si/no")
    check(filas[0]["verificada"] == "si" and filas[1]["verificada"] == "no",
          "verificada correcta")

    # Las dos de relación ya no salen de la respuesta: se calculan cruzando
    # las dos listas, así que recién descargada una sola quedan vacías.
    check(filas[0]["sigue_a_la_cuenta"] == "",
          "la relación con la cuenta no se inventa desde una sola lista")

    # Y una ruta anidada se sigue resolviendo, que es lo que esta prueba
    # cubría con friendship_status.
    check(m._valor({"a": {"b": True}}, "a.b") == "si",
          "una ruta con puntos se resuelve")
    check(m._valor({"a": {}}, "a.b") == "", "y si no está, queda vacía")


def e2_campo_ausente():
    print("\n[E2] Un campo que Instagram no manda deja la columna vacía")
    prep(TEMPORAL("e2"))
    m.pedir = FakeIG(0, 3).pedir      # no manda has_anonymous_profile_picture
    m.descargar(None, perfil(0, 3), "seguidos")

    filas = leer(m._ruta_captura("seguidos"))
    check("foto_defecto" in filas[0], "la columna existe igualmente")
    check(all(f["foto_defecto"] == "" for f in filas),
          "y queda vacía, sin inventarse un valor")
    check(all(f["username"] for f in filas), "el resto de columnas intactas")

    # Un usuario con campos raros o nulos no debe reventar
    check(m._valor({"a": None}, "a") == "", "valor None -> vacío")
    check(m._valor({}, "x.y.z") == "", "ruta inexistente -> vacío")
    check(m._valor({"x": "no-es-dict"}, "x.y") == "", "ruta imposible -> vacío")
    check(m._valor({"n": 42}, "n") == "42", "números como texto")


def e3_reanudar_cabecera_antigua():
    print("\n[E3] Reanudar un parcial de 3 columnas no corrompe el CSV")
    prep(TEMPORAL("e3"))

    # Simulamos un parcial dejado a medias por la versión anterior
    parcial = m._ruta_parcial("seguidos")
    with open(parcial, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "nombre", "id"])
        for i in range(50):
            w.writerow([f"guser{i}", f"Nombre g{i}", f"g{i}"])
    m._escribir_estado("seguidos", "50", 1, 100)

    m.pedir = FakeIG(0, 100).pedir
    m.descargar(None, perfil(0, 100), "seguidos")

    cap = m._ruta_captura("seguidos")
    filas = leer(cap)
    check(len(filas) == 100, f"100 registros tras reanudar (hay {len(filas)})")

    # Todas las filas deben tener el mismo número de columnas que la cabecera
    with open(cap, newline="", encoding="utf-8-sig") as f:
        crudas = list(csv.reader(f))
    anchuras = {len(fila) for fila in crudas}
    check(len(anchuras) == 1,
          f"todas las filas con la misma anchura ({anchuras})")
    check(crudas[0] == ["username", "nombre", "id"],
          "conserva la cabecera antigua en vez de mezclar formatos")
    check(filas[0]["username"] == "guser0" and filas[-1]["username"] == "guser99",
          "principio y final correctos")


def e4_fusion_cabeceras_distintas():
    print("\n[E4] Fusionar una captura antigua con una descarga nueva")
    prep(TEMPORAL("e4"))

    # Captura de hoy en formato viejo, truncada
    hoy = f"{date.today():%Y-%m-%d}"
    captura("seguidos", hoy, [(f"guser{i}", f"Nombre g{i}", f"g{i}")
                              for i in range(30)], completa=False)

    class Ventana(FakeIG):
        def pedir(self, s, ruta, params=None, referer=None):
            self.peticiones += 1
            i = max(int((params or {}).get("max_id", 0)), 20)
            trozo = self.datos["following"][i:i + 50]
            return {"users": trozo,
                    "next_max_id": str(i + len(trozo)) if i + len(trozo) < 60
                    else None}

    m.pedir = Ventana(0, 60).pedir
    m.descargar(None, perfil(0, 60), "seguidos")

    cap = m._ruta_captura("seguidos")
    filas = leer(cap)
    ids = {f["id"] for f in filas}
    check(len(filas) == 60 and len(ids) == 60,
          f"60 sin duplicados tras fusionar (hay {len(filas)})")
    check("g0" in ids and "g59" in ids, "conserva lo viejo y lo nuevo")

    cab = m._cabecera_de(cap)
    check("verificada" in cab, "la cabecera se amplía con las columnas nuevas")

    with open(cap, newline="", encoding="utf-8-sig") as f:
        anchuras = {len(fila) for fila in csv.reader(f)}
    check(len(anchuras) == 1, f"CSV consistente ({anchuras})")

    viejo = next(f for f in filas if f["id"] == "g0")
    nuevo = next(f for f in filas if f["id"] == "g59")
    check(viejo["verificada"] == "", "las filas viejas quedan vacías, no falsas")
    check(nuevo["verificada"] in ("si", "no"), "las nuevas sí traen el dato")


def e5_resumen_de_campos():
    print("\n[E5] Resumen de señales tras la descarga")
    prep(TEMPORAL("e5"))
    m.pedir = FakeIG(0, 20).pedir
    m.descargar(None, perfil(0, 20), "seguidos")

    filas = leer(m._ruta_captura("seguidos"))
    lineas = m._resumen_campos(filas)
    texto = " | ".join(lineas)
    check(any("privada" in x for x in lineas), f"cuenta las privadas ({texto})")
    check(any("verificada" in x for x in lineas), "cuenta las verificadas")
    check(not any("foto_defecto" in x for x in lineas),
          "omite los campos que Instagram no manda")
    check("10 de 20" in texto, f"el recuento cuadra ({texto})")


def e6_inspeccionar():
    print("\n[E6] inspeccionar: 1 petición y lista de campos reales")
    prep(TEMPORAL("e6"))
    ig = FakeIG(0, 30)

    m.pedir = lambda s, ruta, params=None, referer=None: ig.pedir(s, ruta, params)
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: perfil(0, 30)

    class Args:
        lista = "seguidos"

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_inspeccionar(Args())
    salida = buf.getvalue()

    check(ig.peticiones == 1, f"gasta 1 petición ({ig.peticiones})")

    crudo = m.carpeta_cuenta() / f"crudo_{m.OBJETIVO}_seguidos.json"
    check(crudo.exists(), "guarda la respuesta cruda en JSON")
    datos = json.loads(crudo.read_text(encoding="utf-8"))
    check("users" in datos and len(datos["users"]) == 30,
          "el JSON crudo es la respuesta íntegra")

    check("is_verified" in salida, "lista los campos que llegaron")
    check("friendship_status.following" in salida,
          "aplana los campos anidados")
    check("has_anonymous_profile_picture" in salida,
          "avisa de los campos esperados que NO llegaron")
    check("next_max_id" in salida, "muestra los campos fuera de 'users'")

    # Respuesta sin usuarios: no debe reventar
    m.pedir = lambda s, ruta, params=None, referer=None: {"users": [], "next_max_id": None}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_inspeccionar(Args())
    check("no traía usuarios" in buf.getvalue(),
          "respuesta vacía -> mensaje claro, sin excepción")


def e7_comandos_intactos():
    print("\n[E7] Todos los comandos existen y no se han fusionado")
    esperados = ["sesion", "contar", "bajar", "vigilar", "comparar",
                 "inspeccionar", "historial", "detalles", "diagnostico",
                 "presupuesto", "contratos"]

    for nombre in esperados:
        fn = getattr(m, f"cmd_{nombre}", None)
        check(callable(fn), f"cmd_{nombre} existe y es invocable")

    # Que dos comandos compartan cuerpo significa que una edición se comió
    # una línea 'def'. Ya ha pasado; esta prueba lo caza al instante.
    cuerpos = {n: getattr(m, f"cmd_{n}").__code__.co_code for n in esperados}
    check(len(set(cuerpos.values())) == len(esperados),
          "cada comando tiene su propio cuerpo")

    import contextlib
    import io
    sys.argv = ["instagram_listas.py"]
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf), contextlib.suppress(SystemExit):
        m.main()
    ayuda = buf.getvalue()
    for nombre in esperados:
        check(nombre in ayuda, f"'{nombre}' aparece en la ayuda de la CLI")


def x1_claves_homogeneas():
    print("\n[X1] Mezclar capturas con y sin ids no debe duplicar personas")
    prep(TEMPORAL("x1"))
    # La misma persona: una captura vieja sin id y una nueva con id
    m._escribir_csv(m._ruta_captura("seguidores", "2026-09-01"),
                    ["username", "nombre", "id"], [["ana", "", ""]])
    m._escribir_csv(m._ruta_captura("seguidores", "2026-09-02"),
                    ["username", "nombre", "id"], [["ana", "", "1"]])

    h = m.construir_historial("seguidores")
    check(len(h["personas"]) == 1,
          f"ana aparece una sola vez (aparece {len(h['personas'])})")
    check(h["usar_id"] is False, "la serie entera cae a claves por nombre")
    p = list(h["personas"].values())[0]
    check(p["entradas"] == 1 and p["salidas"] == 0,
          "sin baja ni alta inventadas")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    check("no guarda ids" in buf.getvalue(), "y avisa de la degradación")

    # Con todas las capturas con ids, se usan los ids
    prep(TEMPORAL("x1b"))
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-02", [("ana_nueva", "", "1")])
    h = m.construir_historial("seguidores")
    check(h["usar_id"] is True, "con ids en todas, se usan los ids")
    check(len(h["personas"]) == 1, "el renombrado sigue siendo una persona")


def x2_captura_sin_metadatos():
    print("\n[X2] Una captura truncada SIN metadatos ya no envenena en silencio")
    prep(TEMPORAL("x2"))
    todos = [(f"u{i}", "", str(i)) for i in range(100)]
    captura("seguidores", "2026-09-01", todos)
    # Escrita como lo haría la v1: sin .meta.json y truncada
    m._escribir_csv(m._ruta_captura("seguidores", "2026-09-02"),
                    ["username", "nombre", "id"],
                    [[u, n, i] for u, n, i in todos[:10]])
    captura("seguidores", "2026-09-03", todos)

    h = m.construir_historial("seguidores")
    check(h["fechas"] == ["2026-09-01", "2026-09-03"],
          f"la caída brusca queda fuera ({h['fechas']})")
    check(len(h["sospechosas"]) == 1, "se registra como sospechosa")
    check(h["sospechosas"][0][0] == "2026-09-02", "identifica cuál")
    falsos = [p for p in h["personas"].values() if p["entradas"] > 1]
    check(falsos == [], "cero falsos ida y vuelta (había 90 antes)")

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    salida = buf.getvalue()
    check("caída brusca" in salida, "lo dice en pantalla")
    check("10 registros frente a ~100" in salida, "con las cifras concretas")
    check("Sin metadatos" in salida, "y avisa de que no tenía metadatos")

    # Con --incluir-sospechosas vuelve a entrar, si el usuario insiste
    h2 = m.construir_historial("seguidores", incluir_sospechosas=True)
    check(len(h2["fechas"]) == 3, "--incluir-sospechosas la readmite")
    check(len([p for p in h2["personas"].values() if p["entradas"] > 1]) == 90,
          "y entonces sí salen los 90, como es de esperar")


def test_descarga_completa():
    print("\n[1] Descarga completa: 500 seguidores / 2000 seguidos")
    prep(TEMPORAL("t1"))
    ig = FakeIG(500, 2000)
    m.pedir = ig.pedir
    p = perfil(500, 2000)

    m.descargar(None, p, "seguidores")
    m.descargar(None, p, "seguidos")

    fs, fg = m._ruta_captura("seguidores"), m._ruta_captura("seguidos")
    check(fs.exists() and fg.exists(), "se crearon ambas capturas")

    a, b = leer(fs), leer(fg)
    check(len(a) == 500, f"500 seguidores (salieron {len(a)})")
    check(len(b) == 2000, f"2000 seguidos (salieron {len(b)})")
    check(len({f["id"] for f in b}) == 2000, "sin duplicados")
    check(b[0]["username"] == "guser0" and b[-1]["username"] == "guser1999",
          "primer y último registro correctos")
    check(b[0]["nombre"] == "Nombre g0", "el nombre se guarda")
    check(not m._ruta_estado("seguidos").exists(), "el estado se borró")
    check(not m._ruta_parcial("seguidos").exists(), "el parcial se borró")
    check(m._leer_meta(fg)["completa"] is True, "marcada como completa")

    esperadas = (500 + 49) // 50 + (2000 + 49) // 50
    check(ig.peticiones == esperadas,
          f"{esperadas} peticiones para 2500 registros "
          f"(GraphQL necesitaría {(2500 + 11) // 12})")


def test_reanudacion():
    print("\n[2] Corte a mitad y reanudación")
    prep(TEMPORAL("t2"))
    m.MAX_REINTENTOS = 1
    m.pedir = FakeIG(0, 2000, cortar_en={"following": 600}).pedir
    p = perfil(0, 2000)

    m.descargar(None, p, "seguidos")

    check(m._ruta_parcial("seguidos").exists(), "el parcial sobrevive al corte")
    check(m._ruta_estado("seguidos").exists(), "el estado sobrevive al corte")
    check(len(leer(m._ruta_parcial("seguidos"))) == 600, "600 antes del corte")
    cur = json.loads(m._ruta_estado("seguidos").read_text())["cursor"]
    check(cur == "600", f"el cursor apunta al 600 (apunta a {cur})")

    print("  --- segunda ejecución, ya sin corte ---")
    ig2 = FakeIG(0, 2000)
    m.pedir = ig2.pedir
    m.MAX_REINTENTOS = 6
    m.descargar(None, p, "seguidos")

    final = leer(m._ruta_captura("seguidos"))
    ids = [f["id"] for f in final]
    check(len(final) == 2000, f"2000 tras reanudar (hay {len(final)})")
    check(ids == [f"g{i}" for i in range(2000)], "orden y contenido intactos")
    check(ig2.peticiones == 28,
          f"solo pidió lo que faltaba ({ig2.peticiones} de 40 páginas)")


def test_fusion_mismo_dia():
    print("\n[3] Dos pasadas truncadas el mismo día se fusionan")
    prep(TEMPORAL("t3"))

    class Ventana(FakeIG):
        def __init__(self, n, desde, hasta):
            super().__init__(0, n)
            self.desde, self.hasta = desde, hasta

        def pedir(self, s, ruta, params=None, referer=None):
            self.peticiones += 1
            i = max(int((params or {}).get("max_id", 0)), self.desde)
            if i >= self.hasta:
                return {"users": [], "next_max_id": None}
            trozo = self.datos["following"][i:i + 50]
            return {"users": trozo, "next_max_id": str(i + len(trozo))}

    p = perfil(0, 2000)
    m.pedir = Ventana(2000, 0, 1000).pedir
    m.descargar(None, p, "seguidos")
    check(len(leer(m._ruta_captura("seguidos"))) == 1000, "primera pasada: 1000")

    m.pedir = Ventana(2000, 900, 2000).pedir
    m.descargar(None, p, "seguidos")

    filas = leer(m._ruta_captura("seguidos"))
    ids = {f["id"] for f in filas}
    check(len(filas) == 2000 and len(ids) == 2000,
          f"tras fusionar hay 2000 sin duplicados (hay {len(filas)})")
    check("g0" in ids and "g1999" in ids, "conserva principio y final")


def test_bordes():
    print("\n[4] Casos borde")
    prep(TEMPORAL("t4"))
    m.pedir = FakeIG(0, 0).pedir
    m.descargar(None, perfil(0, 0), "seguidores")
    check(m._ruta_captura("seguidores").exists(), "cuenta con 0 seguidores")
    check(len(leer(m._ruta_captura("seguidores"))) == 0, "captura vacía válida")
    check(m.comparar("seguidos") is None, "sin capturas devuelve None")
    check(m._capturas("seguidores") == [m._ruta_captura("seguidores")],
          "_capturas ignora el parcial")

    prep(TEMPORAL("t4b"))
    m.pedir = FakeIG(0, 7).pedir
    m.descargar(None, perfil(0, 7), "seguidos")
    check(len(leer(m._ruta_captura("seguidos"))) == 7,
          "lista más corta que una página")

    prep(TEMPORAL("t4c"))
    r = captura("seguidores", "2026-09-01",
                [('co,ma', 'Con "comillas" y, coma', "9")])
    f = leer(r)[0]
    check(f["username"] == "co,ma", "comas dentro del campo")
    check(f["nombre"] == 'Con "comillas" y, coma', "comillas escapadas")


def x3_captura_vacia():
    print("\n[X3] Una captura vacía marcada completa tampoco envenena")
    prep(TEMPORAL("x3"))
    gente = [(f"u{i}", "", str(i)) for i in range(20)]
    captura("seguidores", "2026-09-01", gente)
    captura("seguidores", "2026-09-02", [])          # vacía y "completa"
    captura("seguidores", "2026-09-03", gente)

    h = m.construir_historial("seguidores")
    falsos = [p for p in h["personas"].values() if p["entradas"] > 1]
    check(falsos == [], "cero falsos (había 20 antes)")
    check(len(h["sospechosas"]) == 1, "la vacía se aparta")


def x4_bajada_real_sostenida():
    print("\n[X4] Una bajada REAL y sostenida no debe descartarse")
    prep(TEMPORAL("x4"))
    # 100 -> 100 -> 30 -> 30 -> 30: purga real, no truncado
    for dia, n in (("2026-09-01", 100), ("2026-09-02", 100),
                   ("2026-09-03", 30), ("2026-09-04", 30),
                   ("2026-09-05", 30)):
        captura("seguidores", dia, [(f"u{i}", "", str(i)) for i in range(n)])

    h = m.construir_historial("seguidores")
    check(len(h["fechas"]) == 5,
          f"se conservan las 5 capturas ({len(h['fechas'])})")
    check(h["sospechosas"] == [], "nada marcado como sospechoso")
    idos = [p for p in h["personas"].values() if not p["presente"]]
    check(len(idos) == 70, f"y se ven las 70 bajas reales ({len(idos)})")


def x5_fecha_duplicada():
    print("\n[X5] Ejecutar vigilar dos veces el mismo día no duplica la fila")
    prep(TEMPORAL("x5"))
    m._anotar_conteo({"seguidores": 500, "seguidos": 2000})
    m._anotar_conteo({"seguidores": 503, "seguidos": 1998})

    filas = m._filas_totales()
    check(len(filas) == 1, f"una sola fila para hoy (hay {len(filas)})")
    check(filas[0][1] == "503", "y conserva el valor más reciente")

    u = m._ultimo_conteo()
    check(u["seguidores"] == 503 and u["seguidos"] == 1998,
          "el último conteo es el correcto")


def x6_sin_doble_lectura():
    print("\n[X6] comparar no debe leer dos veces el mismo archivo")
    prep(TEMPORAL("x6"))
    captura("seguidores", "2026-09-01", [("a", "", "1")])
    captura("seguidores", "2026-09-02", [("a", "", "1"), ("b", "", "2")])

    lecturas = []
    original = m._leer_csv
    m._leer_csv = lambda r: (lecturas.append(r.name), original(r))[1]
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        m.comparar("seguidores")
    m._leer_csv = original

    from collections import Counter
    veces = Counter(lecturas)
    check(max(veces.values()) == 1,
          f"cada captura se lee una vez ({dict(veces)})")


def x7_min_entradas():
    print("\n[X7] --min-entradas por debajo de 2 se corrige")
    prep(TEMPORAL("x7"))
    captura("seguidores", "2026-09-01", [("a", "", "1")])
    captura("seguidores", "2026-09-02", [("a", "", "1")])

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores", min_entradas=1)
    salida = buf.getvalue()
    check("no tiene sentido" in salida, "avisa de que 1 no sirve")
    check("Han entrado 2 veces o más: 0" in salida,
          "usa 2 y no marca a nadie")
    check("1 veces" not in salida, "ya no imprime '1 veces'")


def x8_nombres_distinguibles():
    print("\n[X8] 'tendencia de totales' e 'historial' ya no chocan")
    check(hasattr(m, "tendencia_totales"), "existe tendencia_totales()")
    check(not hasattr(m, "historico"), "historico() ya no existe")
    check(hasattr(m, "construir_historial"), "historial sigue en su sitio")

    import io
    import contextlib
    sys.argv = ["x", "comparar", "--help"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
        m.main()
    ayuda = buf.getvalue()
    check("--totales" in ayuda, "la opción nueva se llama --totales")
    check("historial" in ayuda, "y remite al comando historial")

    # El alias antiguo debe seguir funcionando
    prep(TEMPORAL("x8"))
    captura("seguidores", "2026-09-01", [("a", "", "1")])

    class Args:
        totales, historico, forzar = False, True, False
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_comparar(Args())
    check("SEGUIDORES" in buf.getvalue(), "--historico sigue funcionando")


def c1_contrato_acepta_lo_bueno():
    print("\n[C1] Una respuesta correcta pasa, aunque traiga campos de más")
    buena = {"users": [{"pk": "1", "username": "ana", "full_name": "Ana",
                        "campo_nuevo_de_instagram": {"lo": "que sea"}}],
             "next_max_id": "50", "big_list": True, "status": "ok"}
    m.validar("lista", buena)
    check(True, "pasa con campos añadidos: eso ocurre a menudo y no rompe")

    check(m.validar("lista", {"users": []}) == {"users": []},
          "una lista vacía es legítima: es el fin de página")

    con_id = {"users": [{"id": 99, "username": "b"}]}
    m.validar("lista", con_id)
    check(True, "acepta 'id' donde otros endpoints mandan 'pk'")

    m.validar("perfil", {"data": {"user": {"id": "9", "username": "x"}}})
    check(True, "el perfil mínimo pasa")

    check(m.validar("desconocido", {"lo": "que sea"}) is not None,
          "una clave sin contrato no bloquea nada")


def c2_contrato_caza_el_cambio_silencioso():
    print("\n[C2] Un 200 con otra forma debe fallar, no pasar por bueno")

    def esperar(clave, datos, trozo):
        try:
            m.validar(clave, datos)
            check(False, f"debería rechazar: {trozo}")
        except m.RespuestaInesperada as e:
            check(trozo in str(e), f"lo detecta y lo explica: {trozo}")

    esperar("lista", {"resultado": []}, "users")
    esperar("lista", {"users": {"no": "es lista"}}, "lista")
    esperar("lista", {"users": [{"pk": "1"}]}, "username")
    esperar("lista", {"users": [{"username": "a"}]}, "pk o id")
    esperar("lista", {"users": [{"pk": "1", "username": 42}]}, "str")
    esperar("perfil", {"data": {}}, "data.user")
    esperar("perfil", {"data": {"user": {"username": "x"}}}, "data.user.id")

    # El mensaje debe decir qué SÍ llegó: sin eso, reparar es adivinar
    try:
        m.validar("lista", {"items": [], "status": "ok"})
    except m.RespuestaInesperada as e:
        check("items" in str(e) and "status" in str(e),
              f"enseña las claves que llegaron ({str(e)[-60:]})")
        check("ajustar el contrato" in str(e), "y dice qué hacer")


def c3_la_descarga_para_ante_un_cambio():
    print("\n[C3] Ante un cambio de forma, la descarga para sin inventarse nada")
    prep(TEMPORAL("c3"))
    m._dormir = lambda seg: None
    peticiones = [0]

    def pedir_raro(s, ruta, params=None, referer=None):
        peticiones[0] += 1
        if peticiones[0] == 1:
            return {"users": [{"pk": f"u{i}", "username": f"u{i}",
                               "full_name": ""} for i in range(50)],
                    "next_max_id": "50"}
        # Instagram "mejora" el endpoint: ahora la lista se llama 'items'
        return {"items": [{"pk": "x", "username": "x"}], "next_max_id": None}

    m.pedir = pedir_raro
    try:
        m.descargar(None, {"id": "1", "seguidores": 0, "seguidos": 200,
                           "totales_fiables": True}, "seguidos")
        check(False, "debería parar")
    except m.RespuestaInesperada:
        check(True, "para en cuanto la forma cambia")

    check(peticiones[0] == 2, f"sin insistir ({peticiones[0]} peticiones)")
    parcial = m._leer_csv(m._ruta_parcial("seguidos"))
    check(len(parcial) == 50, "conserva lo que sí era válido")
    check(not any("x" == f["id"] for f in parcial),
          "y NO guarda nada de la respuesta que no entendía")


def r4_cambio_de_username():
    print("\n[R4] Un cambio de username es la misma persona, no baja + alta")
    prep(TEMPORAL("r4"))
    captura("seguidores", "2026-08-01", [("ana", "", "1"), ("beto", "", "2")])
    captura("seguidores", "2026-09-01",
            [("ana", "", "1"), ("beto_nuevo", "", "2")])

    m.comparar("seguidores")
    r = leer(m.carpeta_cuenta()
             / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
    tipos = [x["cambio"] for x in r]
    check(tipos == ["renombro"], f"un solo cambio, de tipo renombro ({tipos})")
    check(r[0]["username"] == "beto_nuevo" and
          r[0]["username_anterior"] == "beto", "registra el nombre anterior")

    print("  --- capturas sin ids (formato v1): cae al username ---")
    prep(TEMPORAL("r4b"))
    for dia, us in (("2026-08-01", ["ana", "beto"]),
                    ("2026-09-01", ["ana", "beto_nuevo"])):
        m._escribir_csv(m._ruta_captura("seguidores", dia), m.CABECERA,
                        [[u, "", ""] for u in us])
    m.comparar("seguidores")
    r = leer(m.carpeta_cuenta()
             / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
    check(sorted(x["cambio"] for x in r) == ["entro", "salio"],
          "sin ids degrada a comparación por nombre, sin reventar")


def r8_bom_para_excel():
    print("\n[R8] Las capturas deben llevar BOM para Excel")
    prep(TEMPORAL("r8"))
    m.pedir = FakeIG(0, 3).pedir
    m.descargar(None, perfil(0, 3), "seguidos")

    cap = m._ruta_captura("seguidos")
    crudo = cap.read_bytes()
    check(crudo.startswith(b"\xef\xbb\xbf"), "la captura empieza con BOM")
    check(crudo.count(b"\xef\xbb\xbf") == 1, "un solo BOM, no uno por línea")
    check(len(leer(cap)) == 3, "y se relee correctamente pese al BOM")

    captura("seguidores", "2026-08-01", [("a", "Añó", "1")])
    captura("seguidores", "2026-09-01", [("b", "Bé", "2")])
    m.comparar("seguidores")
    inf = (m.carpeta_cuenta()
           / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
    check(inf.read_bytes().startswith(b"\xef\xbb\xbf"),
          "los informes también llevan BOM")
    check(leer(inf)[0]["nombre"] in ("Bé", "Añó"), "los acentos sobreviven")


def c4_totales_solo_fiables_si_llegaron():
    print("\n[C4] Los totales no deben darse por buenos si no vinieron")
    prep(TEMPORAL("c4"))

    completo = {"data": {"user": {
        "id": "9", "username": "x", "full_name": "",
        "edge_followed_by": {"count": 300}, "edge_follow": {"count": 500},
        "is_private": False, "followed_by_viewer": True}}}
    m.pedir = lambda s, r, params=None, referer=None: completo
    p = m._perfil_desde_api(None, "x")
    check(p["seguidores"] == 300 and p["totales_fiables"] is True,
          "con los contadores presentes, fiables")

    # Instagram renombra los contadores: antes esto reportaba 0 como bueno
    sin_contadores = {"data": {"user": {
        "id": "9", "username": "x", "full_name": "",
        "seguidores_totales": 300,
        "is_private": False, "followed_by_viewer": True}}}
    m.pedir = lambda s, r, params=None, referer=None: sin_contadores
    p = m._perfil_desde_api(None, "x")
    check(p["totales_fiables"] is False,
          "sin los contadores, NO fiables (antes decía que sí)")
    check(p["id"] == "9" and p["username"] == "x",
          "pero el identificador sirve igual: la descarga puede seguir")


def c5_una_via_rota_pasa_a_la_siguiente():
    print("\n[C5] Si una vía cambia de forma, se usa la siguiente")
    prep(TEMPORAL("c5"))
    usadas = []

    def api_cambiada(s, ruta, params=None, referer=None):
        usadas.append("api")
        return {"data": {"user": {"identificador": "9"}}}   # sin 'id'

    m.pedir = api_cambiada
    m.perfil_desde_html = lambda s, u: (usadas.append("html"),
                                        {"id": "9", "username": u,
                                         "nombre": "", "seguidores": 10,
                                         "seguidos": 20, "privada": False,
                                         "la_sigo": None,
                                         "totales_fiables": True,
                                         "origen": "página del perfil"})[1]
    p = m.perfil(None, "alguien")
    check(usadas == ["api", "html"],
          f"la API cambió de forma y entra la página ({usadas})")
    check(p["id"] == "9", "y se obtiene el perfil igualmente")
    check(m.via_recordada("perfil") == "página del perfil",
          "queda recordada la que sí funciona")


def c6_listado_de_contratos():
    print("\n[C6] Se puede consultar qué se espera, sin gastar nada")
    peticiones = []
    m.pedir = lambda *a, **k: peticiones.append(1)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_contratos(None)
    salida = buf.getvalue()

    check(peticiones == [], "ninguna petición")
    for esperado in ("lista", "users", "username", "pk o id", "data.user"):
        check(esperado in salida, f"documenta «{esperado}»")
    check("NO rompen" in salida,
          "y aclara que añadir campos no rompe nada")


def f3_una_carpeta_por_cuenta():
    print("\n[F3] Cada cuenta en su carpeta, «usuario - id»")
    carpeta = prep(TEMPORAL("f3"))

    with m.con_cuenta("una"):
        m.recordar_id("una", "12345")
        m._escribir_csv(m._ruta_captura("seguidores", "2026-09-01"),
                        m.CABECERA, [["a", "", "1"]])
    with m.con_cuenta("otra"):
        m.recordar_id("otra", "67890")
        m._escribir_csv(m._ruta_captura("seguidores", "2026-09-01"),
                        m.CABECERA, [["b", "", "2"]])

    # (prep deja además la carpeta de 't', la cuenta de las pruebas)
    nombres = sorted(d.name for d in carpeta.iterdir() if d.is_dir())
    check("una - 12345" in nombres and "otra - 67890" in nombres,
          f"una carpeta por cuenta, con su id ({nombres})")
    check(not list(carpeta.glob("*.csv")),
          "y en la raíz de salida no queda suelto ningún CSV de cuenta")

    with m.con_cuenta("una"):
        check(len(m._capturas("seguidores")) == 1, "cada una ve la suya")
    with m.con_cuenta("otra"):
        check(len(m._capturas("seguidores")) == 1, "y solo la suya")

    # Lo general se queda en la raíz: no es de nadie en particular.
    m.anadir_cuenta("una")
    check(m._ruta_cuentas().parent == carpeta,
          "cuentas.txt sigue en la raíz, que es un archivo general")
    check(m._ruta_presupuesto().parent == carpeta, "y el presupuesto")
    check(m._ruta_config().parent == carpeta, "y rutas.json")


def f4_los_archivos_de_antes_se_recogen():
    print("\n[F4] Lo que ya estaba suelto se recoge en su carpeta")
    carpeta = prep(TEMPORAL("f4"))

    # Cómo estaba el disco antes de que existieran las carpetas.
    for nombre, contenido in (
            ("vieja_seguidores_2026-09-01.csv", "username,nombre,id\na,,1\n"),
            (".vieja_seguidores_2026-09-01.meta.json", '{"completa": true}'),
            ("totales_vieja.csv", "fecha,seguidores,seguidos\n"),
            ("historial_seguidores_vieja.csv", "x\n"),
            ("vigilancia_vieja.txt", "alguien\n"),
            ("perfil_vieja.json", '{"id": "999", "nombre": "V"}')):
        (carpeta / nombre).write_text(contenido, encoding="utf-8")

    with m.con_cuenta("vieja"):
        destino = m.carpeta_cuenta()

    check(destino.name == "vieja - 999",
          f"el id sale del perfil que ya estaba guardado ({destino.name})")
    movidos = sorted(r.name for r in destino.iterdir())
    check(len(movidos) == 6, f"se recogen los seis archivos ({movidos})")
    check(not list(carpeta.glob("*_seguidores_*.csv")),
          "y no queda ninguno suelto en la raíz")

    with m.con_cuenta("vieja"):
        check(len(m._capturas("seguidores")) == 1,
              "la captura de antes se sigue viendo tras la mudanza")

    # Sin perfil guardado no se sabe el id: la carpeta nace con el usuario y
    # se completa cuando el primer perfil lo dice.
    carpeta2 = prep(TEMPORAL("f4b"))
    (carpeta2 / "sinid_seguidos_2026-09-01.csv").write_text("a\n",
                                                            encoding="utf-8")
    with m.con_cuenta("sinid"):
        check(m.carpeta_cuenta().name == "sinid",
              "sin id, la carpeta lleva solo el usuario")
        m.recordar_id("sinid", "777")
        check(m.carpeta_cuenta().name == "sinid - 777",
              "y se renombra en cuanto se sabe")
        check((carpeta2 / "sinid - 777" / "sinid_seguidos_2026-09-01.csv")
              .exists(), "con sus archivos dentro, sin perder ninguno")


def f27_escritura_atomica():
    print("\n[F27] Una captura a medias no puede existir")
    carpeta = prep(TEMPORAL("f27"))

    # Lo de siempre: escribir bien
    ruta = carpeta / "prueba.csv"
    m._escribir_csv(ruta, ["a", "b"], [["1", "2"], ["3", "4"]])
    check(len(leer(ruta)) == 2, "escribe lo que tiene que escribir")
    check(ruta.read_text(encoding="utf-8-sig").startswith("a,b"),
          "con su cabecera")
    check(not list(carpeta.glob("*.tmp")), "y sin dejar temporales")

    # Y ahora lo que importa: que se corte a mitad. Con open(ruta,"w") el
    # archivo se trunca ANTES de escribir, así que quedaría cortado y con
    # pinta de bueno. Aquí el original tiene que seguir intacto.
    antes = ruta.read_text(encoding="utf-8-sig")
    real = m.os.replace

    def morir(*_):
        raise OSError("se fue la luz justo aquí")

    m.os.replace = morir
    try:
        m._escribir_csv(ruta, ["a", "b"], [["9", "9"]] * 500)
    except OSError:
        pass
    finally:
        m.os.replace = real

    check(ruta.read_text(encoding="utf-8-sig") == antes,
          "cortada la escritura, la captura anterior queda ENTERA")
    check(not list(carpeta.glob("*.tmp")),
          "y el temporal se limpia: si no, uno por cada intento fallido")

    # Lo mismo con lo demás que se escribe de una pieza
    destino = carpeta / "cosa.json"
    m.escribir_atomico(destino, '{"a": 1}')
    check(json.loads(destino.read_text(encoding="utf-8")) == {"a": 1},
          "el ayudante vale para texto")
    m.escribir_atomico(carpeta / "cosa.bin", b"\x00\x01binario")
    check((carpeta / "cosa.bin").read_bytes() == b"\x00\x01binario",
          "y para bytes, que es como se guarda la foto")

    # El nombre del temporal no puede comerse la extensión: '.meta.json'
    # con with_suffix se convertiría en '.meta.tmp' y machacaría otra cosa.
    m.escribir_atomico(carpeta / "x.meta.json", "{}")
    check((carpeta / "x.meta.json").exists(), "nombres con dos puntos, bien")

    # Y la carpeta se crea si no está
    hondo = carpeta / "una" / "otra" / "z.csv"
    m._escribir_csv(hondo, ["a"], [["1"]])
    check(hondo.exists(), "crea las carpetas que falten")

    # La captura y sus metadatos: si se cae entre las dos, queda la captura
    # entera SIN metadatos, que es «no consta si está completa». Eso ya no
    # es suerte: es lo que se quiere, y por eso el CSV va primero.
    r = m._ruta_captura("seguidores", "2026-09-09")
    m._escribir_csv(r, m.CABECERA, [m._fila({"username": "ana"}, m.CABECERA)])
    check(m._leer_meta(r).get("completa") is None,
          "sin metadatos, no consta que esté completa")
    check(len(m._leer_csv(r)) == 1, "pero la captura se lee entera")


def f30_nombres_limpios():
    print("\n[F30] El nombre visible, sin lo que sobra a los lados")
    # Visto en una captura: «Lore☺ , 1 publicación», con el espacio
    # delante de la coma. Instagram devuelve muchos nombres con espacios
    # al final y
    # algunos con caracteres invisibles pegados a los emojis.
    check(m.limpiar_nombre("Lore\u263a ") == "Lore\u263a",
          "el espacio del final se va")
    check(m.limpiar_nombre("  Ana  ") == "Ana", "y el del principio")
    check(m.limpiar_nombre("Nombre\u200b") == "Nombre",
          "y el separador de ancho cero, que no se ve pero ocupa")
    check(m.limpiar_nombre("Ana\u00a0") == "Ana",
          "y el espacio duro, que tampoco se ve")
    check(m.limpiar_nombre("Ana  Lopez") == "Ana  Lopez",
          "pero por dentro no se toca: el nombre es de quien lo puso")
    check(m.limpiar_nombre(None) == "" and m.limpiar_nombre("") == "",
          "y lo vacío no revienta")

    # Se limpia en el ORIGEN, así que también sale limpio del CSV
    fila = m._dict_usuario({"username": "x", "full_name": "Lore ", "pk": "1"})
    check(fila["nombre"] == "Lore",
          "las filas del CSV salen ya limpias, no solo la ventana")


def f63_un_cursor_repetido_no_gira_para_siempre():
    print("\n[F63] Un cursor que se repite corta la descarga")
    carpeta = prep(TEMPORAL("f63"))
    m.recordar_id("t", "1")

    # Instagram devolviendo SIEMPRE el mismo cursor, con páginas llenas.
    # El freno de páginas vacías no sirve aquí: vienen con gente, así que
    # `vacias_seguidas` nunca llega al límite y el bucle giraría para
    # siempre gastando el presupuesto del día.
    llamadas = [0]

    def siempre_igual(*a, **k):
        llamadas[0] += 1
        if llamadas[0] > 60:
            raise AssertionError("bucle infinito: no cortó")
        return {"users": [{"pk": str(llamadas[0]), "username": f"u{llamadas[0]}"}],
                "next_max_id": "CURSOR_PEGADO"}

    m.pedir = siempre_igual
    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            m._una_pasada(None, "1", "seguidores", 500)
    except m.RespuestaInesperada as e:
        check("ya se había usado" in str(e),
              f"corta y dice por qué ({str(e)[:40]})")
    except AssertionError as e:
        check(False, str(e))
    else:
        check(False, "no cortó y terminó como si nada")

    check(llamadas[0] <= 3,
          f"y corta enseguida, no tras decenas de peticiones ({llamadas[0]})")


PRUEBAS = [
    f63_un_cursor_repetido_no_gira_para_siempre,
    e1_campos_extra,
    e2_campo_ausente,
    e3_reanudar_cabecera_antigua,
    e4_fusion_cabeceras_distintas,
    e5_resumen_de_campos,
    e6_inspeccionar,
    e7_comandos_intactos,
    x1_claves_homogeneas,
    x2_captura_sin_metadatos,
    test_descarga_completa,
    test_reanudacion,
    test_fusion_mismo_dia,
    test_bordes,
    x3_captura_vacia,
    x4_bajada_real_sostenida,
    x5_fecha_duplicada,
    x6_sin_doble_lectura,
    x7_min_entradas,
    x8_nombres_distinguibles,
    c1_contrato_acepta_lo_bueno,
    c2_contrato_caza_el_cambio_silencioso,
    c3_la_descarga_para_ante_un_cambio,
    r4_cambio_de_username,
    r8_bom_para_excel,
    c4_totales_solo_fiables_si_llegaron,
    c5_una_via_rota_pasa_a_la_siguiente,
    c6_listado_de_contratos,
    f3_una_carpeta_por_cuenta,
    f4_los_archivos_de_antes_se_recogen,
    f27_escritura_atomica,
    f30_nombres_limpios,
]
