"""
Informe, registro, copias y exportación
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def f8_bandeja_de_novedades():
    print("\n[F8] Lo que encuentra 'vigilar' se acumula hasta que lo leas")
    prep(TEMPORAL("f8"))

    # El troceado es puro: se comprueba sin tocar disco.
    texto = ("2026-09-01 08:00:00  @una\n"
             "    seguidores 100 (-3)\n"
             "    2 dejaron de seguir a la cuenta: ana, beto\n"
             "2026-09-02 08:00:00  @otra\n"
             "    seguidores 50 (+1)\n")
    bloques = m.separar_novedades(texto)
    check(len(bloques) == 2, f"un bloque por pasada ({len(bloques)})")
    check(bloques[0]["sello"] == "2026-09-01 08:00:00", "con su sello")
    check(len(bloques[0]["texto"]) == 2, "y sus líneas sangradas dentro")
    check(m.separar_novedades("") == [], "un archivo vacío no da bloques")

    # Ciclo completo: anotar, leer lo pendiente, marcar, y no repetirlo
    m.anotar_novedad("una", ["seguidores 100 (-3)", "se fue ana"])
    check(len(m.novedades_pendientes()) == 1, "lo anotado queda pendiente")
    check(m._ruta_novedades().parent == m.CARPETA,
          "la bandeja va en la raíz: es lo que se abre, no un dato de nadie")

    m.marcar_novedades_vistas()
    check(m.novedades_pendientes() == [], "tras leerlas, no vuelven a salir")

    m.anotar_novedad("otra", ["algo nuevo"])
    pendientes = m.novedades_pendientes()
    check(len(pendientes) == 1 and "@otra" in pendientes[0]["cabecera"],
          "y lo que llega después sí")

    # La bandeja no se borra nunca: es el registro
    guardado = m._ruta_novedades().read_text(encoding="utf-8")
    check(guardado.count("@una") == 1 and guardado.count("@otra") == 1,
          "leerlas no borra el archivo")

    # El caso que rompía: dos cuentas anotadas en el MISMO segundo, que es
    # lo que hace 'vigilar --todas'. Con el sello como marca, la segunda se
    # daba por leída sin haberse enseñado nunca.
    m.marcar_novedades_vistas()
    m.anotar_novedad("p", ["a"])
    m.anotar_novedad("q", ["b"])
    check(len(m.novedades_pendientes()) == 2,
          "dos avisos en el mismo segundo salen los dos")

    m.anotar_novedad("x", [])
    check(len(m.separar_novedades(
        m._ruta_novedades().read_text(encoding="utf-8"))) == 4,
        "sin nada que contar no se anota un bloque vacío")

    if sys.platform != "win32":
        check(m.avisar_al_sistema("t", "x") is False,
              "fuera de Windows el aviso del sistema no se intenta")


def f9_el_aviso_no_miente():
    print("\n[F9] El aviso: ni noticias viejas ni bandeja de ruido")
    prep(TEMPORAL("f9"))
    hoy = f"{date.today():%Y-%m-%d}"

    def captura(tipo, gente, dia):
        r = m._ruta_captura(tipo, dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": u, "nombre": "", "id": u[0]},
                                 m.CABECERA) for u in gente])
        m._escribir_meta(r, True, len(gente), len(gente), "completa")

    # Dos días viejos con las dos listas: ahí SÍ hubo cambios de relación.
    captura("seguidores", ["ana", "beto"], "2026-08-01")
    captura("seguidos", ["ana", "beto"], "2026-08-01")
    captura("seguidores", ["beto"], "2026-08-02")
    captura("seguidos", ["ana", "beto"], "2026-08-02")

    # Y hoy solo se baja UNA lista, como hace 'vigilar' casi siempre.
    captura("seguidores", ["beto", "caro"], hoy)

    p = {"seguidores": 2, "seguidos": 2}
    lineas = m._resumir_para_novedad(p, {"seguidores": 1, "seguidos": 2},
                                     {"seguidores"})
    texto = " | ".join(lineas)
    check("dejó de seguir a la cuenta" not in texto,
          f"no cuela como novedad de hoy un cambio de agosto ({texto})")
    check("entraron 1" in texto and "salieron 0" in texto,
          f"pero sí dice quién se movió en la que sí se bajó ({texto})")
    check("caro" in texto, "y con nombres, que es lo que se quiere leer")

    # Con las dos listas de hoy sí se puede clasificar
    captura("seguidos", ["beto"], hoy)
    lineas = m._resumir_para_novedad(p, {"seguidores": 1, "seguidos": 2},
                                     {"seguidores", "seguidos"})
    texto = " | ".join(lineas)
    check("la cuenta dejó de seguirle" in texto,
          f"con las dos listas del día, el tipo de cambio ({texto})")

    # Nada que contar -> ni bandeja ni globo
    prep(TEMPORAL("f9b"))
    captura("seguidores", ["ana"], "2026-08-01")
    captura("seguidos", ["ana"], "2026-08-01")
    captura("seguidores", ["ana"], hoy)
    captura("seguidos", ["ana"], hoy)
    check(m._resumir_para_novedad({"seguidores": 1, "seguidos": 1},
                                  {"seguidores": 1, "seguidos": 1},
                                  {"seguidores"}) == [],
          "sin cambios no se anota nada: una bandeja de ruido no se lee")

    # Salvo la primera vez, que no hay con qué comparar y sí interesa
    check(m._resumir_para_novedad({"seguidores": 1, "seguidos": 1}, None,
                                  {"seguidores"}) != [],
          "el primer conteo sí se anota")

    # Y un salto de línea no puede partir un bloque en dos
    prep(TEMPORAL("f9c"))
    m.anotar_novedad("t", ["una linea\ncon salto"])
    bloques = m.separar_novedades(
        m._ruta_novedades().read_text(encoding="utf-8"))
    check(len(bloques) == 1, f"un solo bloque ({len(bloques)})")


def f10_informe_html():
    print("\n[F10] Un archivo con todo dentro")
    import informe_html
    prep(TEMPORAL("f10"))

    IDS = {"ana": "11", "beto": "22", "eva": "55"}
    for dia, (segs, seguidos) in (
            ("2026-09-01", (["ana", "beto"], ["ana", "beto"])),
            ("2026-09-08", (["beto", "eva"], ["ana", "beto"]))):
        for tipo, gente in (("seguidores", segs), ("seguidos", seguidos)):
            r = m._ruta_captura(tipo, dia)
            m._escribir_csv(r, m.CABECERA,
                            [m._fila({"username": u, "nombre": f"{u} & <Cía>",
                                      "id": IDS[u]}, m.CABECERA)
                             for u in gente])
            m._escribir_meta(r, True, len(gente), len(gente), "completa")

    m.guardar_estado("t", {"nombre": "Nombre & <Visible>",
                           "publicaciones": 137})
    datos = m.recopilar_informe()
    check(datos["listas"]["seguidores"]["total"] == 2, "recoge las filas")
    check(len(datos["evolucion"]["seguidores"]) == 2, "y la serie completa")
    check(any(c["cambio"] == "dejó de seguir a la cuenta"
              for c in datos["cambios"]), "y los cambios de relación")

    pagina = informe_html.generar(datos)

    # Autocontenido: si pidiera algo fuera, dejaría de funcionar sin
    # conexión y además avisaría a un tercero cada vez que se abre.
    check("http://" not in pagina and "https://" not in pagina,
          "no sale ni una petición a internet")
    check(pagina.count("<script>") == 1 and "<style>" in pagina,
          "el JavaScript y el CSS van dentro")

    # Un nombre con '<' dentro no puede cerrar la etiqueta antes de tiempo
    # Solo puede haber un cierre de <script>: el de verdad. Si un dato
    # colara un '</script>', habría dos y el resto se volcaría como HTML.
    check(pagina.count("</script>") == 1,
          "la etiqueta del guión cierra una sola vez, donde debe")
    check("<Cía>" not in pagina,
          "ningún '<' de los datos llega crudo al HTML")
    check("&amp;amp;" not in pagina, "y no se escapa dos veces")

    check("dejó de seguir a la cuenta" in pagina,
          "el informe cuenta los cambios de relación")
    check("<polyline" in pagina, "y dibuja la evolución, sin JavaScript")

    # Sobre nada, tampoco revienta
    vacio = informe_html.generar({"cuenta": "x", "listas": {},
                                  "evolucion": {}})
    check("Con dos capturas" in vacio, "sin datos, invita en vez de fallar")

    # Y el comando deja el archivo donde toca
    m.cmd_informe(None)
    hechos = list(m.carpeta_cuenta().glob("informe_t_*.html"))
    check(len(hechos) == 1, f"el comando escribe el archivo ({hechos})")


def f11_repaso_del_informe():
    print("\n[F11] Lo que se encontró repasando el informe")
    import informe_html
    prep(TEMPORAL("f11"))

    # Una foto PNG no puede anunciarse como JPEG
    m.carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    m.ruta_foto("t").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    check(m._foto_en_base64("t").startswith("data:image/png"),
          "el tipo de la foto sale de sus bytes, no del nombre")
    m.ruta_foto("t").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 50)
    check(m._foto_en_base64("t").startswith("data:image/jpeg"),
          "y un JPEG se anuncia como JPEG")

    # Columnas de relación sin rellenar: se dice, no se enseña un hueco
    for tipo in ("seguidores", "seguidos"):
        r = m._ruta_captura(tipo, "2026-09-08")
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": "ana", "nombre": "", "id": "1"},
                                 m.CABECERA)])
        m._escribir_meta(r, True, 1, 1, "completa")
    datos = m.recopilar_informe()
    check("sigue_a_la_cuenta" in datos["listas"]["seguidores"]["vacias"],
          "detecta la columna sin datos")
    check(any("no consta la relación" in a for a in datos["avisos"]),
          "y lo avisa en el informe")
    check("(sin datos)" in informe_html.generar(datos),
          "la tabla lo dice en la cabecera")

    # Tope de filas: un HTML de 40.000 filas no lo abre ningún navegador
    m.TOPE_FILAS_INFORME = 2
    r = m._ruta_captura("seguidores", "2026-09-09")
    m._escribir_csv(r, m.CABECERA,
                    [m._fila({"username": f"u{i}", "nombre": "", "id": str(i)},
                             m.CABECERA) for i in range(5)])
    m._escribir_meta(r, True, 5, 5, "completa")
    datos = m.recopilar_informe()
    check(len(datos["listas"]["seguidores"]["filas"]) == 2, "recorta la tabla")
    check(datos["listas"]["seguidores"]["total"] == 5,
          "pero la cifra sigue siendo la de verdad")
    check(any("primeras 2 de 5" in a for a in datos["avisos"]),
          "y dice que está recortada, con el CSV entero al lado")
    m.TOPE_FILAS_INFORME = 5000

    # Lo importante primero, aunque sea menos
    pagina = informe_html.generar({
        "cuenta": "x", "listas": {}, "evolucion": {},
        "comparado": ["2026-09-01", "2026-09-08"],
        "cambios": [{"username": "a", "cambio": "empezó a seguir a la "
                                                "cuenta"},
                    {"username": "b", "cambio": "empezó a seguir a la "
                                                "cuenta"},
                    {"username": "c", "cambio": "dejó de seguir a la "
                                                "cuenta"}]})
    titulos = re.findall(r"<h3>([^<]*)<span", pagina)
    check(titulos and titulos[0] == "dejó de seguir a la cuenta",
          f"una rotura va antes que dos altas corrientes ({titulos})")
    check("entre el 2026-09-01 y el 2026-09-08" in pagina,
          "y se dice entre qué dos días se comparó")


def f25_registro():
    print("\n[F25] El registro se puede mandar sin la cuenta dentro")
    import registro as reg
    import shutil

    carpeta = Path(TEMPORAL("f25"))
    shutil.rmtree(carpeta, ignore_errors=True)
    check(reg.arrancar(carpeta) is not None, "se abre")

    SES = "9982027586%3A4JbZbUkGXwBpUO%3A1%3AAYjRbzJ7"

    # Lo que NUNCA puede salir. El registro es justo lo que alguien copia y
    # manda para pedir ayuda: un sessionid ahí es la cuenta entera.
    for etiqueta, texto in (
            ("con su nombre", f"sessionid={SES}"),
            ("en un JSON", f'"sessionid": "{SES}"'),
            ("suelto en una URL", f"fallo al pedir {SES} otra vez"),
            ("la cabecera entera",
             f"Cookie: csrftoken=abc123def456; sessionid={SES}")):
        limpio = reg.limpiar_secretos(texto)
        check(SES not in limpio and "abc123def456" not in limpio,
              f"no se escapa {etiqueta}")
    check("hola" in reg.limpiar_secretos("hola"),
          "y lo que no es secreto se queda como está")
    check(reg.limpiar_secretos("") == "" and reg.limpiar_secretos(None) == "",
          "lo vacío no revienta")

    # Ni siquiera dentro de la traza de una excepción, que es por donde se
    # cuela la cabecera de requests.
    reg.anotar(f"probando {SES}")
    try:
        raise ValueError(f"reventó con {SES} dentro")
    except ValueError:
        reg.excepcion("al descargar")

    texto = (carpeta / reg.ARCHIVO).read_text(encoding="utf-8")
    check(SES not in texto, "el archivo no contiene la cookie")
    check("Traceback" in texto, "pero sí la traza, que es para lo que sirve")

    entradas = reg.leer()
    check(len(entradas) == 2, f"se lee troceado ({len(entradas)})")
    check(entradas[-1]["nivel"] == "ERROR", "con su nivel")
    check("\n" in entradas[-1]["mensaje"],
          "y la traza va pegada a su entrada, no suelta en líneas")
    check(reg.resumen(entradas) == {"INFO": 1, "ERROR": 1}, "y se resume")

    # Rota por tamaño: un registro que crece sin freno acaba borrándose
    # entero, y con él lo que hacía falta.
    reg.TAMANO, antes = 2000, reg.TAMANO
    reg.arrancar(carpeta)
    for i in range(400):
        reg.anotar(f"línea de relleno número {i} " + "x" * 60)
    copias = list(carpeta.glob(reg.ARCHIVO + ".*"))
    check(copias, f"rota en varios archivos ({len(copias)})")
    check(len(copias) <= reg.COPIAS,
          f"y no guarda más de {reg.COPIAS} copias")
    check((carpeta / reg.ARCHIVO).stat().st_size < reg.TAMANO * 2,
          "el archivo en uso no crece sin freno")
    check(len(reg.leer()) > 1, "y se siguen leyendo las copias rotadas")
    reg.TAMANO = antes

    # No poder escribir el registro no puede parar el trabajo
    check(reg.arrancar(Path("/proc/no/se/puede")) is None,
          "si no se puede abrir, lo dice")
    reg.anotar("esto no debe reventar")
    reg.excepcion("ni esto")


def f26_repaso_del_registro():
    print("\n[F26] Lo que se encontró repasando el registro")
    import registro as reg
    import shutil

    carpeta = Path(TEMPORAL("f26"))
    shutil.rmtree(carpeta, ignore_errors=True)
    reg.arrancar(carpeta)

    # 1. Poner los enganches otra vez los ENCADENABA sobre los de antes: en
    #    un proceso con cuatro ventanas abiertas, un solo error se anotaba
    #    cuatro veces y disparaba cuatro avisos.
    # Se parte de limpio: si no, el enganche puesto de verdad al principio
    # sigue en la cadena y la prueba mediría eso en vez de esto.
    original = sys.excepthook
    reg._ENGANCHADO = False
    sys.excepthook = sys.__excepthook__
    avisos = []
    for _ in range(4):
        reg.instalar_enganches(avisos.append)
    enganchado = sys.excepthook           # el que quedó puesto de verdad
    try:
        raise ValueError("uno solo")
    except ValueError:
        datos = sys.exc_info()
    # El enganche llama al de antes, que imprimiría la traza en la salida
    # de la prueba; se desvía mientras dura.
    with open(os.devnull, "w") as nada, contextlib.redirect_stderr(nada):
        enganchado(*datos)
    sys.excepthook = original
    check(len(avisos) == 1, f"un error, un aviso ({len(avisos)})")
    texto = (carpeta / reg.ARCHIVO).read_text(encoding="utf-8")
    check(texto.count("error no recogido") == 1,
          "y una sola línea en el archivo")

    # 2. El id de la cuenta NO es un secreto: no abre nada y es lo que hace
    #    falta para saber de quién era el error. Ocultarlo era pasarse.
    check("9982027586" in reg.limpiar_secretos("ds_user_id=9982027586"),
          "el id de la cuenta se ve")
    check("<oculto>" in reg.limpiar_secretos(
        "sessionid=9982027586%3AabcDEF"), "pero la cookie entera no")

    # 3. Sin frontera de palabra, 'mid' casaba dentro de otras palabras
    check(reg.limpiar_secretos("pyramid=3") == "pyramid=3",
          "no se tacha lo que solo TERMINA como una cookie")
    check("<oculto>" in reg.limpiar_secretos("mid=amI2rQALAAHvsBylA1jP"),
          "y la de verdad sí")

    # 4. Anotar una excepción que ya viene dada, como hace Tk
    reg.excepcion("desde Tk", (ValueError, ValueError("de fuera"), None))
    check("de fuera" in (carpeta / reg.ARCHIVO).read_text(encoding="utf-8"),
          "se puede anotar una excepción que se recibe, no solo la actual")

    # Y sin ninguna excepción viva tampoco revienta
    reg.excepcion("sin nada que anotar")
    check(True, "anotar sin excepción activa no rompe nada")


def f36_copia_de_seguridad():
    print("\n[F36] Copia de lo que no se puede volver a descargar")
    import copia
    import zipfile

    carpeta = prep(TEMPORAL("f36"))
    m.recordar_id("t", "123")
    for dia in ("2026-09-01", "2026-09-08"):
        for tipo in ("seguidores", "seguidos"):
            r = m._ruta_captura(tipo, dia)
            m._escribir_csv(r, m.CABECERA,
                            [m._fila({"username": "ana", "id": "1"},
                                     m.CABECERA)])
            m._escribir_meta(r, True, 1, 1, "completa")
    m.construir_historial("seguidores")          # deja el índice, oculto
    m.escribir_atomico(m.ruta_foto("t"), b"\xff\xd8foto")
    m.escribir_atomico(m.carpeta_cuenta() / "crudo_perfil_t.html",
                       "<html>con la sesión dentro</html>")

    ruta, man = copia.crear("t")
    dentro = zipfile.ZipFile(ruta).namelist()

    # Lo que tiene que entrar: también los ocultos. El índice y los
    # cursores empiezan por punto, y sin ellos la copia tendría los datos
    # pero no lo aprendido de ellos.
    check(any(n.startswith(".indice") for n in dentro),
          "entra el índice, que es un archivo oculto")
    check(man["capturas"] == 4, f"y las cuatro capturas ({man['capturas']})")

    # Lo que NO puede entrar: una copia se lleva a un disco externo o se
    # manda, y ahí una cookie de sesión es la cuenta entera viajando.
    check(not any("crudo_perfil" in n for n in dentro),
          "NO entra el crudo del perfil: puede llevar la sesión dentro")
    check(not any("sesion" in n.lower() for n in dentro),
          "ni nada que se llame sesión")
    check(man["cuenta"] == "t" and man["creada"],
          "el manifiesto dice de quién es y de cuándo, sin abrirla entera")

    # --- restaurar en un equipo vacío ---------------------------------
    prep(TEMPORAL("f36b"))
    m._IDS.clear()
    m._RECOLOCADAS.clear()
    r = copia.restaurar(ruta)
    check(len(r["traidos"]) == man["archivos"], "se traen todos")
    m.OBJETIVO = "t"
    check(len(m.construir_historial("seguidores")["fechas"]) == 2,
          "y el historial se reconstruye entero desde la copia")

    # --- restaurar encima NO puede pisar ------------------------------
    mio = m.carpeta_cuenta("t") / "t_seguidores_2026-09-01.csv"
    mio.write_text("ESTO ES MAS NUEVO", encoding="utf-8")
    r = copia.restaurar(ruta)
    check(not r["traidos"] and len(r["saltados"]) == man["archivos"],
          "no pisa nada de lo que ya hay")
    check(mio.read_text(encoding="utf-8") == "ESTO ES MAS NUEVO",
          "lo del disco puede ser más nuevo que la copia, y se respeta")
    r = copia.restaurar(ruta, reemplazar=True)
    check(mio.read_text(encoding="utf-8") != "ESTO ES MAS NUEVO",
          "y solo se pisa si se pide a propósito")

    # --- lo que no es una copia ---------------------------------------
    otro = Path("/tmp/f36b/otro.zip")
    with zipfile.ZipFile(otro, "w") as z:
        z.writestr("hola.txt", "x")
    check(copia.leer_manifiesto(otro) == {}, "un zip cualquiera no cuela")
    try:
        copia.restaurar(otro)
        check(False, "debería negarse")
    except ValueError as e:
        check("copia.json" in str(e), "y dice por qué")

    # Un zip con rutas hacia fuera no escribe fuera de su carpeta
    malo = Path("/tmp/f36b/malo.zip")
    with zipfile.ZipFile(malo, "w") as z:
        z.writestr(copia.MANIFIESTO, json.dumps({"cuenta": "t",
                                                 "version": 1}))
        z.writestr("../../fuera.txt", "no deberia estar aqui")
    r = copia.restaurar(malo)
    check(r["rotos"] == ["../../fuera.txt"],
          "una ruta que sale de la carpeta se ignora, no se escribe")


def f37_repaso_copia_y_sesiones():
    print("\n[F37] Lo que se encontró repasando la copia y las sesiones")
    import copia
    import zipfile

    # --- 1. Buscar sesiones no puede costar peticiones -----------------
    carpeta = prep(TEMPORAL("f37"))
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    m.guardar_sesion_pegada("sessionid=111111%3Aa%3A1%3Az", "la de siempre")

    m._SESION_CACHE, m._SESION_HASTA = "viva", time.monotonic() + 600
    m._VERIFICACION_OK = "perfil"
    m.registrar_hallazgos([{
        "navegador": "chrome", "clase": "encontrada", "motivo": "",
        "cookies": m.leer_cookies_pegadas("222222%3Ab%3A1%3Ay"),
        "id": "222222"}])

    check(m.leer_sesiones()["activa"] == "111111",
          "encontrar otras no cambia la que se usa")
    # Lo que costaba: al devolver el puntero a su sitio se tiraba la
    # sesión verificada, y volver a verificarla son peticiones. Buscar
    # sesiones no puede salir caro.
    check(m._SESION_CACHE == "viva",
          "y no tira la sesión ya verificada: verificar cuesta peticiones")
    check(m._VERIFICACION_OK == "perfil", "ni la vía que se había aprendido")
    check("222222" in m.leer_sesiones()["cuentas"], "pero sí guarda la nueva")

    # Cambiar de cuenta de verdad SÍ tiene que tirarla: son otras cookies
    m.activar_sesion("222222")
    check(m._SESION_CACHE is None,
          "cambiar de cuenta sí tira la sesión: ya son otras cookies")

    # --- 2. Restaurar escribe de forma atómica -------------------------
    prep(TEMPORAL("f37b"))
    m.recordar_id("t", "9")
    r = m._ruta_captura("seguidores", "2026-09-01")
    m._escribir_csv(r, m.CABECERA, [m._fila({"username": "a"}, m.CABECERA)])
    m._escribir_meta(r, True, 1, 1, "completa")
    ruta, _ = copia.crear("t")

    prep(TEMPORAL("f37c"))
    m._IDS.clear()
    m._RECOLOCADAS.clear()
    real = m.os.replace
    intentos = []
    m.os.replace = lambda a, b: (intentos.append(1), real(a, b))[1]
    try:
        copia.restaurar(ruta)
    finally:
        m.os.replace = real
    check(intentos, "restaurar pasa por la escritura atómica del motor")
    check(not list(m.carpeta_cuenta("t").glob("*.tmp")),
          "y no deja temporales")

    # --- 3. Un zip roto da un mensaje, no una traza --------------------
    roto = Path("/tmp/f37c/roto.zip")
    roto.write_bytes(b"esto no es un zip ni de lejos")
    check(copia.leer_manifiesto(roto) == {}, "un archivo cualquiera no cuela")
    try:
        copia.restaurar(roto)
        check(False, "debería negarse")
    except ValueError as e:
        check("copia" in str(e).lower(),
              f"y lo dice en una frase, no con una traza ({e})")

    # --- 4. El temporal de la copia lleva el número del proceso --------
    fuente = Path("copia.py").read_text(encoding="utf-8")
    check("os.getpid()" in fuente,
          "el temporal del zip lleva el pid: dos procesos no se pisan")


def f15_export_oficial():
    print("\n[F15] Leer la exportación oficial de Instagram")
    import export_instagram as ex
    import zipfile

    def entrada(u, ts=None, **extra):
        d = {"href": f"https://www.instagram.com/{u}", "value": u}
        if ts is not None:
            d["timestamp"] = ts
        d.update(extra)
        return {"title": "", "media_list_data": [], "string_list_data": [d]}

    # --- qué archivo es qué ---
    check(ex.clasificar("connections/followers_and_following/"
                        "followers_1.json") == "followers",
          "reconoce los seguidores partidos en varios")
    check(ex.clasificar("x/following.json") == "following", "y los seguidos")
    check(ex.clasificar("following.html") is None,
          "un export en HTML no se cuela por el nombre")
    check(ex.clasificar("media/posts_1.json") is None,
          "ni el resto del ZIP, que pesa cientos de megas")

    # --- las dos formas que circulan ---
    con_clave = json.dumps({"relationships_followers": [entrada("ana", 100)]})
    lista_suelta = json.dumps([entrada("beto", 200)])
    check(len(ex.interpretar(con_clave)) == 1, "con la clave del principio")
    check(len(ex.interpretar(lista_suelta)) == 1, "y como lista suelta")
    check(ex.interpretar("{no es json") == [], "un archivo roto da vacío")
    check(ex.interpretar(json.dumps([{"string_list_data": []}])) == [],
          "y una entrada sin datos se salta, no revienta")

    # --- juntar los trozos: quedarse con followers_1 es EL error típico ---
    archivos = {
        "connections/followers_and_following/followers_1.json":
            json.dumps({"relationships_followers": [entrada("ana", 1000),
                                                    entrada("beto", 2000)]}),
        "connections/followers_and_following/followers_2.json":
            json.dumps({"relationships_followers": [entrada("caro", 3000)]}),
        "connections/followers_and_following/following.json":
            json.dumps([entrada("ana", 1500)]),
        "media/posts_1.json": json.dumps({"otra": "cosa"}),
    }
    listas = ex.leer(archivos)
    check(len(listas["followers"]) == 3,
          f"junta los dos archivos de seguidores ({len(listas['followers'])})")
    check("dejadas" not in listas, "y no inventa listas que no venían")

    # --- el resumen contesta las tres preguntas que importan ---
    r = ex.resumen(archivos)
    check(r["posibles_ids"] == [],
          "avisa de que NO hay id numérico, que es lo que decide todo")
    check(r["con_sello"] == 4 and r["sin_sello"] == 0, "cuenta los sellos")
    check(r["primera_fecha"] and r["ultima_fecha"], "y su rango de fechas")

    # Si algún día Instagram añadiera un id, tiene que SALIR, no perderse
    con_id = {"followers_1.json": json.dumps(
        [entrada("ana", 1000, user_id="51234567890")])}
    check(ex.resumen(con_id)["posibles_ids"] == ["user_id"],
          "un identificador nuevo se detecta en vez de tirarse")

    # --- lo que se guarda, y lo que NO ---
    prep(TEMPORAL("f15"))
    z = Path("/tmp/f15/export.zip")
    with zipfile.ZipFile(z, "w") as f:
        base = "connections/followers_and_following/"
        for nombre, texto in archivos.items():
            f.writestr(nombre, texto)
        f.writestr(base + "recently_unfollowed_profiles.json",
                   json.dumps({"relationships_unfollowed": [entrada("eva")]}))

    abiertos = m.abrir_export(z)
    check(len(abiertos) == 4, f"abre solo lo que sirve ({len(abiertos)})")

    datos = ex.enriquecimiento(abiertos)
    check(datos["desde"]["ana"].get("te_sigue_desde"), "anota desde cuándo")
    check(datos["desde"]["ana"].get("le_sigues_desde"),
          "y en las dos direcciones si está en las dos listas")
    check(datos["dejadas"] == ["eva"],
          "y trae las que la API no da: recién dejadas de seguir")

    class Args:
        archivo, guardar = str(z), True
    m.cmd_importar(Args())
    check(m.ruta_enriquecimiento("t").exists(), "guarda el enriquecimiento")

    # Lo importante: NO es una captura y no puede degradar la serie
    check(m._capturas("seguidores") == [],
          "el export NO se convierte en captura: sin id degradaría "
          "el historial entero a claves por nombre")


def f56_el_sello_del_export():
    print("\n[F56] ¿El «timestamp» del export es la fecha del follow?")
    import export_instagram as ex

    # El lector guardaba ese campo como «te_sigue_desde», que es AFIRMAR
    # que lo es. Nadie lo había comprobado. Se contrasta con lo único que
    # puede desmentirlo: las capturas propias.
    def exportado(fechas):
        return {"desde": {f"u{i}": {"te_sigue_desde": f}
                          for i, f in enumerate(fechas)}}

    def visto(desde_cuando, cuantos):
        return {"personas": {str(i): {"username": f"u{i}",
                                      "primera": desde_cuando}
                             for i in range(cuantos)}}

    # 1. Repartidas por el calendario y anteriores a lo que vimos: es lo
    #    que se vería si fuera la fecha del follow.
    fechas = [f"2024-{1 + i % 9:02d}-1{i % 9}" for i in range(20)]
    r = ex.contrastar(exportado(fechas), visto("2026-01-01", 20))
    check(r["veredicto"] == "compatible", f"compatible ({r['veredicto']})")

    # 2. POSTERIORES a la primera captura donde ya aparecía esa persona.
    #    No se puede empezar a seguir a alguien después de que ya te
    #    siguiera: eso lo zanja.
    r = ex.contrastar(exportado(["2026-08-01"] * 20), visto("2025-01-01", 20))
    check(r["veredicto"] == "no_es_la_fecha_del_follow",
          f"lo imposible lo zanja ({r['veredicto']})")
    check(r["imposibles"] == 20 and r["ejemplos"],
          "y enseña ejemplos concretos, no solo el número")

    # 3. Todas el mismo día, aunque no sean imposibles: eso es la fecha en
    #    que se generó el export, o la de una migración de Meta.
    r = ex.contrastar(exportado(["2020-01-15"] * 20), visto("2026-01-01", 20))
    check(r["veredicto"] == "sospechoso_todas_el_mismo_dia",
          f"amontonadas en un día, sospechoso ({r['veredicto']})")

    # 4. Y con poco que cotejar NO se opina. Decir «parece correcto» tras
    #    mirar tres personas sería el mismo error que en «publicar y
    #    crecer».
    r = ex.contrastar(exportado(["2024-01-01"] * 3), visto("2026-01-01", 3))
    check(r["veredicto"] == "sin_datos",
          f"con tres no se opina ({r['veredicto']})")
    check(ex.contrastar({}, {})["veredicto"] == "sin_datos",
          "y sin nada, tampoco revienta")


def f53_la_foto_vieja_no_se_pierde():
    print("\n[F53] Una foto de perfil cambiada no se puede recuperar")
    carpeta = prep(TEMPORAL("f53"))
    m.recordar_id("t", "1")
    UNA = b"\xff\xd8" + b"primera foto" * 20
    OTRA = b"\xff\xd8" + b"segunda foto" * 20

    class R:
        def __init__(self, c):
            self.status_code, self.content = 200, c

    class S:
        def __init__(self, c):
            self.c = c

        def get(self, *a, **k):
            return R(self.c)

    m.guardar_foto(S(UNA), "t", "https://x/1.jpg")
    check([f.name for f in m.fotos_guardadas("t")] == ["foto_t.jpg"],
          "la primera se guarda como la actual")

    # El CDN cambia la URL constantemente sirviendo la MISMA imagen.
    # Comparar enlaces daría un «cambió de foto» cada semana, así que se
    # compara el contenido.
    m.guardar_foto(S(UNA), "t", "https://x/otra-url-misma-imagen.jpg")
    check(len(m.fotos_guardadas("t")) == 1,
          "otra URL con la misma imagen no cuenta como cambio")

    m.guardar_foto(S(OTRA), "t", "https://x/2.jpg")
    fotos = m.fotos_guardadas("t")
    check(len(fotos) == 2,
          f"al cambiar de verdad se guardan las dos ({len(fotos)})")
    check(fotos[-1].name == "foto_t.jpg", "la actual sigue llamándose igual")
    check(fotos[0].read_bytes() == UNA,
          "y la vieja se conserva ENTERA: Instagram deja de servirla y no "
          "se puede volver a descargar")
    check(fotos[1].read_bytes() == OTRA, "la actual es la nueva")
    check(m.leer_estado("t").get("foto_cambio"),
          "queda anotado cuándo cambió: una cuenta que cambia de imagen "
          "puede haber cambiado de manos")

    # Y lo que no es una imagen no se guarda ni pisa lo que hay
    m.guardar_foto(S(b"<html>error</html>"), "t", "https://x/3.jpg")
    check(m.ruta_foto("t").read_bytes() == OTRA,
          "una respuesta que no es imagen no pisa la buena")


PRUEBAS = [
    f8_bandeja_de_novedades,
    f9_el_aviso_no_miente,
    f10_informe_html,
    f11_repaso_del_informe,
    f25_registro,
    f26_repaso_del_registro,
    f36_copia_de_seguridad,
    f37_repaso_copia_y_sesiones,
    f15_export_oficial,
    f56_el_sello_del_export,
    f53_la_foto_vieja_no_se_pierde,
]
