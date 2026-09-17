"""
El proyecto mirado por fuera: nombres, README, versión
"""

from pruebas.comun import *  # noqa: F401,F403
from pruebas.comun import check, prep, m


def f16_plurales():
    print("\n[F16] Un solo sitio decide los plurales")
    check(m.plural(1, "mutuo") == "1 mutuo", "uno en singular")
    check(m.plural(0, "mutuo") == "0 mutuos", "cero en plural, como se habla")
    check(m.plural(13, "seguidor", "seguidores") == "13 seguidores",
          "y los irregulares se dan a mano")
    check(m.plural(-1, "bloqueo") == "-1 bloqueo", "el signo no lo cambia")

    # Es el defecto de «1 bloqueo(s)»: se corrigió en la ventana y se quedó
    # en el módulo. Que no vuelva a haber dos sitios donde arreglarlo.
    # Vigila TODOS los archivos, no solo el motor: los «(s)» se colaron
    # en analitica.py en cuanto hubo un archivo nuevo que esta prueba no
    # miraba. Un vigilante con lista fija deja de vigilar.
    for archivo in sorted(Path(".").glob("*.py")):
        if archivo.name.startswith("test_"):
            continue
        fuente = archivo.read_text(encoding="utf-8")
        check('(s)"' not in fuente and "(s):" not in fuente,
              f"sin «(s)» en los mensajes de {archivo.name}")


def f28_ajustes_en_un_sitio():
    print("\n[F28] La configuración, en un solo archivo y con límites")
    carpeta = prep(TEMPORAL("f28"))
    serie = m.ajustes_de_serie()

    # Los límites no son adorno: todo el proyecto está hecho para no perder
    # la cuenta, y un archivo que aceptara «pausa 0» tiraría lo demás.
    check(m.acotar("pausa_min", 0) == 0.5, "una pausa de cero se sube al piso")
    check(m.acotar("tope_hora", 99999) == 500, "un tope absurdo se recorta")
    # El techo sube a 200 para poder aplicar lo que mida `pagina`, pero
    # sigue habiendo techo: sin él, un 5000 escrito a mano haría cada
    # petición inconfundible.
    check(m.acotar("por_pagina", 5000) == 200,
          "por_pagina tiene techo, aunque ahora sea 200")
    m.aplicar_ajustes()
    check(m.DE_SERIE.get("por_pagina") == 50,
          "y de serie sigue pidiendo 50, que es lo que pide la web: subirlo "
          "es una decisión de quien lo usa, no del programa")
    check(m.acotar("tope_hora", "no soy un número") is None,
          "lo que no es número no se aplica")
    check(m.acotar("inventado", 3) is None, "ni una clave que no existe")
    check(isinstance(m.acotar("tope_hora", 90.7), int),
          "los enteros se guardan enteros")

    # Se recorta Y se dice: dejar el valor viejo en silencio sería peor
    _, avisos = m.guardar_ajustes({"tope_hora": 9999, "pausa_min": 2.5,
                                   "loquesea": 1})
    check(any("tope_hora" in a and "500" in a for a in avisos),
          "avisa de lo que recortó")
    check(any("loquesea" in a for a in avisos), "y de lo que no conoce")
    check(m.TOPE_HORA == 500 and m.PAUSA_MIN == 2.5,
          "y lo aplica de verdad a las constantes")

    # «De serie» tiene que seguir siendo el valor original, no el aplicado
    check(m.ajustes_de_serie()["tope_hora"] == serie["tope_hora"],
          "el valor de serie no cambia porque tú cambies el tuyo")

    # Relación entre dos: una pausa mínima mayor que la máxima daría
    # números al revés a random.uniform en vez de fallar
    m.guardar_ajustes({"pausa_min": 20, "pausa_max": 1})
    check(m.PAUSA_MAX >= m.PAUSA_MIN,
          f"la máxima nunca queda por debajo de la mínima "
          f"({m.PAUSA_MIN}-{m.PAUSA_MAX})")

    # Restaurar tiene que devolver los valores AHORA, no al reiniciar
    class Args:
        poner, restaurar = None, True
    m.cmd_ajustes(Args())
    check(m.TOPE_HORA == serie["tope_hora"] and m.PAUSA_MIN
          == serie["pausa_min"], "restaurar devuelve las constantes ya")
    check(not m._ruta_ajustes().exists(), "y quita el archivo")

    # Un archivo corrupto no puede dejar el programa sin arrancar
    m.escribir_atomico(m._ruta_ajustes(), "{esto no es json")
    check(m.leer_ajustes() == {}, "un archivo roto se ignora")
    check(m.aplicar_ajustes() == [], "y no cambia nada")

    # Lo que había en config_gui.json viene solo, una vez
    prep(TEMPORAL("f28b"))
    viejo = carpeta / "config_gui.json"
    m.escribir_atomico(viejo, json.dumps(
        {"objetivo": "x", "umbral": 5, "max_dias": 3}))
    traidos = m.migrar_config_gui(viejo)
    check(len(traidos) == 2, f"trae los dos duplicados ({traidos})")
    check(m.UMBRAL_CAMBIO == 5 and m.MAX_DIAS_SIN_BAJAR == 3,
          "y quedan aplicados")
    check(m.migrar_config_gui(viejo) == [],
          "y no se vuelven a traer, que pisarían lo que hayas cambiado")

    class Args2:
        poner, restaurar = None, True
    m.cmd_ajustes(Args2())


def f29_repaso_de_escritura_y_ajustes():
    print("\n[F29] Lo que se encontró repasando lo atómico y los ajustes")
    carpeta = prep(TEMPORAL("f29"))

    # 1. El temporal llevaba SIEMPRE el mismo nombre. La ventana y la tarea
    #    programada corren a la vez: los dos escribían el mismo temporal y
    #    uno renombraba el archivo a medias del otro.
    vistos = []
    real = m.os.replace
    m.os.replace = lambda t, d: (vistos.append(Path(t).name), real(t, d))[1]
    try:
        m.escribir_atomico(carpeta / "x.json", "{}")
    finally:
        m.os.replace = real
    check(str(os.getpid()) in vistos[0],
          f"el temporal lleva el número del proceso ({vistos[0]})")

    # 2. Los saltos de línea. write_text traducía a CRLF en Windows; con
    #    newline="" fijo, los .txt que se editan a mano se quedaban en LF.
    m.escribir_atomico(carpeta / "a.txt", "uno\ndos\n")
    check(b"\n" in (carpeta / "a.txt").read_bytes(),
          "el texto normal deja que el sistema traduzca los saltos")
    m._escribir_csv(carpeta / "b.csv", ["a"], [["1"]])
    crudo = (carpeta / "b.csv").read_bytes()
    check(b"\r\r\n" not in crudo,
          "y el CSV no duplica el retorno: csv ya escribe \\r\\n")
    check(crudo.startswith(b"\xef\xbb\xbf"), "con su BOM para Excel")

    # 3. El archivo de ajustes guardaba los catorce aunque no se tocaran,
    #    así que todos salían marcados como cambiados y la marca no decía
    #    nada.
    serie = m.ajustes_de_serie()
    m.guardar_ajustes({"tope_hora": 90,
                       "pausa_min": serie["pausa_min"],
                       "dias_foto": serie["dias_foto"]})
    guardado = m.leer_ajustes()
    check(list(guardado) == ["tope_hora"],
          f"solo se anota lo que se aparta de lo de serie ({guardado})")

    # Y quitar una línea del archivo tiene que devolver ese valor a su
    # sitio; si no, borrarla no haría nada y habría que adivinar por qué.
    m.escribir_atomico(m._ruta_ajustes(), json.dumps({"tope_hora": 90}))
    m.aplicar_ajustes()
    check(m.TOPE_HORA == 90, "se aplica lo que hay")
    m.escribir_atomico(m._ruta_ajustes(), json.dumps({"dias_foto": 3}))
    m.aplicar_ajustes()
    check(m.TOPE_HORA == serie["tope_hora"],
          "y lo que desaparece del archivo vuelve a su valor de serie")
    check(m.DIAS_FOTO == 3, "sin tocar lo que sí sigue puesto")

    # Sin nada apartado, no hace falta ni el archivo
    m.guardar_ajustes({k: v for k, v in serie.items()})
    check(not m._ruta_ajustes().exists(),
          "sin ningún cambio, el archivo se quita en vez de quedar vacío")

    class Args:
        poner, restaurar = None, True
    m.cmd_ajustes(Args())


def f31_el_reparto_aguanta():
    print("\n[F31] Los comandos viven fuera y todo sigue en su sitio")
    import ordenes

    # La mudanza no puede haber escondido nada: la ventana y el banco
    # llaman a los comandos por su nombre de siempre.
    for nombre in ("cmd_sesion", "cmd_contar", "cmd_bajar", "cmd_comparar",
                   "cmd_historial", "cmd_informe", "cmd_detalles", "main"):
        check(hasattr(m, nombre), f"'{nombre}' se sigue viendo desde el motor")
        check(getattr(m, nombre) is getattr(ordenes, nombre),
              f"y es el mismo objeto, no una copia ({nombre})")

    # UNA sola copia del motor. Un módulo que es programa y biblioteca a la
    # vez se carga dos veces si no se le pone remedio, y entonces habría dos
    # presupuestos, dos sesiones en caché y dos juegos de constantes.
    copias = [k for k, v in sys.modules.items()
              if getattr(v, "__file__", "") and
              str(v.__file__).endswith("instagram_listas.py")]
    check(len(copias) == 1, f"una sola copia del motor en memoria ({copias})")

    # Lo que se rompió al mudar y hay que vigilar: 'globals()' y 'global'
    # apuntaban al motor cuando el código vivía dentro, y aquí ya no.
    fuente = Path("ordenes.py").read_text(encoding="utf-8")
    # Mirando el CÓDIGO, no el texto: hay comentarios que explican
    # precisamente por qué no puede haber ninguno.
    codigo = [l for l in fuente.splitlines()
              if not l.lstrip().startswith("#")]
    check(not any("globals()" in l for l in codigo),
          "ningún globals() en los comandos: escribiría donde nadie lee")
    check(not re.search(r"^\s+global ", fuente, re.M),
          "ni ningún 'global': declararía uno propio de este archivo")

    # Y el motor no importa a los comandos arriba del todo, que sería un
    # ciclo. El puente está al final y con alias.
    motor_src = Path("instagram_listas.py").read_text(encoding="utf-8")
    arriba = motor_src[:motor_src.index("def ")]
    check("import ordenes" not in arriba,
          "el motor no importa los comandos al principio: sería un ciclo")


def f32_ningun_nombre_suelto():
    print("\n[F32] Ningún nombre sin definir esperando su turno")
    import ast as _ast
    import builtins as _b

    # El fallo que esto caza: al mudar los comandos, `main()` se quedó con
    # un OBJETIVO suelto en el mensaje de «cuenta no encontrada». Compila,
    # pasa las 117 pruebas, y revienta el día que Instagram no encuentre
    # una cuenta — o sea, cuando ya ha ido algo mal.
    #
    # Es la clase de fallo que ninguna prueba de comportamiento encuentra,
    # porque vive en una rama por la que no pasa nadie.
    # Lo que Python pone en cada módulo y también se ve dentro de una
    # función. Sin esto, usar __file__ daba una falsa alarma.
    DUNDERS = {"__file__", "__name__", "__doc__", "__package__", "__spec__"}

    def sueltos(archivo):
        t = _ast.parse(Path(archivo).read_text(encoding="utf-8"))
        arriba = {n.name for n in t.body
                  if isinstance(n, (_ast.FunctionDef, _ast.ClassDef))}
        for n in t.body:
            if isinstance(n, _ast.Assign):
                arriba |= {d.id for d in n.targets
                           if isinstance(d, _ast.Name)}
            elif isinstance(n, _ast.AnnAssign) and isinstance(n.target,
                                                              _ast.Name):
                arriba.add(n.target.id)
        importados = set()
        for n in _ast.walk(t):
            if isinstance(n, (_ast.Import, _ast.ImportFrom)):
                for a in n.names:
                    importados.add((a.asname or a.name).split(".")[0])
        malos = set()
        for fn in [n for n in t.body
                   if isinstance(n, (_ast.FunctionDef, _ast.ClassDef))]:
            propios = set()
            for x in _ast.walk(fn):
                if isinstance(x, _ast.Name) and isinstance(x.ctx, _ast.Store):
                    propios.add(x.id)
                elif isinstance(x, _ast.arg):
                    propios.add(x.arg)
                elif isinstance(x, (_ast.FunctionDef, _ast.ClassDef)) \
                        and x is not fn:
                    propios.add(x.name)
                elif isinstance(x, _ast.ExceptHandler) and x.name:
                    propios.add(x.name)
                elif isinstance(x, _ast.alias):
                    propios.add((x.asname or x.name).split(".")[0])
            for x in _ast.walk(fn):
                if isinstance(x, _ast.Name) and isinstance(x.ctx, _ast.Load) \
                        and x.id not in propios and x.id not in arriba \
                        and x.id not in importados \
                        and not hasattr(_b, x.id) \
                        and x.id not in DUNDERS:
                    malos.add(f"{fn.name}: {x.id}")
        return sorted(malos)

    # La lista se saca del disco, no se escribe a mano: 'copia.py' se
    # añadió al proyecto y esta prueba no lo miraba porque nadie se acordó
    # de apuntarlo. Un vigilante con lista fija deja de vigilar en cuanto
    # aparece algo nuevo.
    archivos = sorted(a.name for a in Path(".").glob("*.py")
                      if not a.name.startswith("test_"))
    check(len(archivos) >= 8,
          f"se revisan todos los del proyecto ({len(archivos)})")
    for archivo in archivos:
        encontrados = sueltos(archivo)
        check(not encontrados, f"{archivo}: {encontrados or 'limpio'}")


def f38_version():
    print("\n[F38] El programa sabe qué versión es")
    import copia
    import informe_html
    import version

    check(re.match(r"^\d+\.\d+$", version.VERSION),
          f"la versión tiene forma de versión ({version.VERSION})")
    check(re.match(r"^\d{4}-\d\d-\d\d$", version.FECHA),
          f"y su fecha ({version.FECHA})")
    check(m.VERSION == version.VERSION,
          "el motor la re-exporta, no guarda una copia suya")

    # La firma es lo que se pega en un informe de error: sin ella hay que
    # preguntar tres cosas antes de poder mirar nada.
    firma = m.firma()
    for trozo in (version.VERSION, "Python"):
        check(trozo in firma, f"la firma lleva {trozo}")

    # Donde tiene que verse
    datos = {"cuenta": "x", "listas": {}, "evolucion": {},
             "version": version.VERSION, "generado": "2026-09-12 10:00"}
    check(version.VERSION in informe_html.generar(datos),
          "el informe dice con qué versión se hizo")

    carpeta = prep(TEMPORAL("f38"))
    m.recordar_id("t", "1")
    r = m._ruta_captura("seguidores", "2026-09-01")
    m._escribir_csv(r, m.CABECERA, [m._fila({"username": "a"}, m.CABECERA)])
    m._escribir_meta(r, True, 1, 1, "completa")
    ruta, man = copia.crear("t")
    check(man["programa"] == version.VERSION,
          "la copia guarda con qué versión se hizo")
    check(man["version"] == copia.VERSION,
          "y aparte, la del FORMATO del zip, que es otra cosa")

    # Una copia de un formato más nuevo no se traga a medias
    import zipfile
    futura = carpeta / "futura.zip"
    with zipfile.ZipFile(futura, "w") as z:
        z.writestr(copia.MANIFIESTO, json.dumps(
            {"cuenta": "t", "version": copia.VERSION + 5,
             "programa": "99.0"}))
        z.writestr("algo.csv", "x")
    try:
        copia.restaurar(futura)
        check(False, "debería negarse")
    except ValueError as e:
        check("más nuevo" in str(e), "avisa de que viene de una más nueva")
        check("Actualiza" in str(e), "y dice qué hacer")

    # El número vive en UN sitio. Y se mira en TODO lo que se escribe, no
    # solo en los .py: la primera vez que se hizo esta prueba, la versión
    # acabó escrita a mano en el README y esto no lo veía. Un documento
    # que miente sobre la versión es peor que uno que no la dice.
    revisados = 0
    for archivo in sorted(list(Path(".").glob("*.py"))
                          + list(Path(".").glob("*.txt"))
                          + list(Path(".").glob("*.md"))):
        # `salida_pruebas_*.txt` es lo que dejan las pruebas al correr:
        # lleva dentro la versión porque la imprime el propio programa, y
        # no es un documento del proyecto que se pueda quedar viejo.
        if (archivo.name == "version.py"
                or archivo.name.startswith(("test_", "salida_pruebas_"))):
            continue
        texto = archivo.read_text(encoding="utf-8")
        # En PROJECT_CONTEXT.md las versiones son el historial: «(v7.3)»
        # cuenta lo que se hizo entonces y no envejece. Lo que no vale es
        # afirmar cuál es la de ahora.
        if archivo.name == "PROJECT_CONTEXT.md":
            texto = texto.replace(f"(v{version.VERSION})", "")
        revisados += 1
        # Buscando el número ENTERO, no el trozo: «7.3» está dentro de
        # «Safari/537.36», que es la cabecera de navegador del motor.
        # Detrás solo se rechaza un dígito, no un punto: «FocusMedia 7.3.»
        # al final de una frase tiene que contar, y «7.30» no.
        suelta = re.search(rf"(?<![\d.]){re.escape(version.VERSION)}"
                           r"(?!\d)", texto)
        check(not suelta,
              f"{archivo.name} no lleva la versión escrita a mano")
    check(revisados >= 10, f"se revisan también los documentos ({revisados})")


def f43_los_botones_pasan_lo_que_hace_falta():
    print("\n[F43] Cada botón pasa lo que su comando va a leer")
    import ast as _ast

    # La ventana llama a los comandos con un _Args hecho a mano. Si un
    # comando empieza a leer un argumento nuevo y alguna llamada no lo
    # pasa, eso es un AttributeError que solo aparece al pulsar ESE botón
    # —y solo si se llega a esa rama. Aquí se ve sin ejecutar nada.
    gui = _ast.parse(Path("instagram_gui.py").read_text(encoding="utf-8"))
    fuente = Path("ordenes.py").read_text(encoding="utf-8")

    def obligatorios(nombre):
        """Lo que el comando lee SIN defecto: getattr(...) no cuenta."""
        i = fuente.index(f"def {nombre}(")
        cuerpo = fuente[i:]
        j = cuerpo.find("\ndef ", 1)
        cuerpo = cuerpo[:j] if j > 0 else cuerpo
        return (set(re.findall(r"args\.(\w+)", cuerpo))
                - set(re.findall(r'getattr\(args,\s*"(\w+)"', cuerpo)))

    revisadas = 0
    for n in _ast.walk(gui):
        if not (isinstance(n, _ast.Call)
                and isinstance(n.func, _ast.Attribute)
                and n.func.attr == "_lanzar"):
            continue
        cmd = next((a.attr for a in n.args
                    if isinstance(a, _ast.Attribute)
                    and a.attr.startswith("cmd_")), None)
        args_call = next((a for a in n.args if isinstance(a, _ast.Call)
                          and getattr(a.func, "id", "") == "_Args"), None)
        if not cmd or not args_call:
            continue
        revisadas += 1
        faltan = (obligatorios(cmd) - {k.arg for k in args_call.keywords}
                  - {"cuenta"})
        check(not faltan, f"{cmd}: {sorted(faltan) or 'completo'}")
    check(revisadas >= 12, f"se revisan todas las llamadas ({revisadas})")


def f45_el_readme_no_miente():
    print("\n[F45] El README no promete cosas que no existen")
    # Un solo documento, no dos. LEEME.txt y README.md con lo mismo se
    # habrían separado en la primera versión que tocara uno de los dos.
    leeme = Path("README.md").read_text(encoding="utf-8")
    fuente = Path("ordenes.py").read_text(encoding="utf-8")

    # Una documentación que se queda vieja es peor que no tenerla: manda a
    # quien la lee a escribir cosas que fallan. Y se queda vieja SOLA, sin
    # que nadie toque el archivo, con solo renombrar un comando.
    reales = set(re.findall(r'add_parser\("(\w+)"', fuente))
    citados = set(re.findall(r"instagram_listas\.py (?:--cuenta \w+ )?(\w+)",
                             leeme))
    inventados = sorted(c for c in citados if c not in reales and c != "py")
    check(not inventados, f"comandos citados que no existen: {inventados}")
    check(len(citados) >= 8, f"y se citan unos cuantos ({len(citados)})")

    banderas = {b for b in re.findall(r"--[a-z][a-z-]*", leeme)
                if set(b) != {"-"}}
    # Las del lanzador de pruebas también cuentan: el README las explica y
    # no salen de ordenes.py. Antes solo se miraba ahí, así que una
    # bandera real quedaba marcada como inventada.
    lanzador = Path("pruebas/ejecutar.py").read_text(encoding="utf-8")
    faltan = sorted(b for b in banderas
                    if f'"{b}"' not in fuente and f'"{b}"' not in lanzador
                    and b != "--version")
    check(not faltan, f"banderas citadas que no existen: {faltan}")

    listados = set(re.findall(r"`(\S+\.py|\S+\.md)`", leeme))
    # Los de la raíz y los de pruebas/: el README cita archivos de las
    # dos, y mirar solo una marcaba como inexistente uno que sí está.
    hay = {a.name for a in Path(".").iterdir()}
    # Los de pruebas/ cuentan para «lo citado existe», pero NO para «todo
    # existe citado»: el README explica la carpeta y su tabla de temas, y
    # obligar a nombrar los once archivos sería ruido que nadie lee.
    de_pruebas = {f"pruebas/{a.name}" for a in Path("pruebas").iterdir()}
    hay |= de_pruebas
    check(not (listados - hay),
          f"archivos listados que no están: {sorted(listados - hay)}")
    # Y al revés: un archivo nuevo que nadie apuntó en el README
    sin_citar = sorted(a for a in hay - de_pruebas
                       if a.endswith(".py") and a not in listados)
    check(not sin_citar, f"archivos del proyecto sin citar: {sin_citar}")

    # Un enlace roto o una imagen que falta es lo PRIMERO que se ve al
    # abrir el repositorio, y no lo caza ninguna prueba de comportamiento.
    def ancla(titulo):
        """Cómo convierte un encabezado en ancla quien lo renderiza."""
        t = re.sub(r"[^\w\s-]", "", titulo.strip().lower(), flags=re.UNICODE)
        return re.sub(r"\s+", "-", t)

    anclas = {ancla(t) for t in re.findall(r"^#+\s+(.*)$", leeme, re.M)}
    enlaces = re.findall(r"\]\(#([^)]+)\)", leeme)
    rotos = [e for e in enlaces if e not in anclas]
    check(not rotos, f"enlaces internos rotos: {rotos}")
    check(len(enlaces) >= 3, f"y hay enlaces que comprobar ({len(enlaces)})")

    imagenes = (re.findall(r'<img src="([^"]+)"', leeme)
                + re.findall(r"!\[[^\]]*\]\((?!http)([^)]+)\)", leeme))
    faltan_img = [i for i in imagenes if not Path(i).exists()]
    check(not faltan_img, f"imágenes que no están: {faltan_img}")

    # Y la versión NO puede ir en una insignia: se quedaría vieja, y f38
    # ya prohíbe escribirla a mano en cualquier archivo.
    check("badge/version" not in leeme and "badge/v" not in leeme,
          "ninguna insignia con el número de versión")

    # El lanzador de Windows es .pyw, así que la comprobación de arriba
    # —que mira los .py— no lo ve. Sin consola, ese archivo es el único
    # camino de entrada de mucha gente.
    lanzador = Path("FocusMedia.pyw")
    check(lanzador.exists(), "existe el lanzador sin consola")
    check("FocusMedia.pyw" in leeme, "y el README lo menciona")
    codigo = lanzador.read_text(encoding="utf-8")
    # Las dos cosas que lo hacen útil, y que no se ven al ejecutarlo bien
    check("os.devnull" in codigo,
          "protege stdout y stderr: sin consola valen None")
    check("messagebox" in codigo,
          "y avisa en un cuadro si falla al arrancar: sin consola, un "
          "error sería «no pasa nada»")


def f52_lo_que_se_lee_en_pantalla():
    print("\n[F52] Lo que salió mal en una sesión de verdad")
    import ordenes

    # 1. «Cuenta privada y NO la sigues» cuando la_sigo era None. El mismo
    #    fallo que el de «privada»: None cayendo en la rama del False.
    fuente = Path("ordenes.py").read_text(encoding="utf-8")
    check('if p["la_sigo"] is True' in fuente
          and 'is False' in fuente,
          "los tres estados de la_sigo se distinguen, no dos")
    check("no consta si la sigues" in fuente,
          "y existe la frase para el caso que no se sabe")

    # 2. «Ya tienes dos descargas o más» tras UNA sola: contaba archivos, y
    #    una descarga deja dos —seguidores y seguidos—. Comparar necesita
    #    dos DÍAS.
    carpeta = prep(TEMPORAL("f52"))
    m.recordar_id("t", "1")
    for tipo in ("seguidores", "seguidos"):
        r = m._ruta_captura(tipo, "2026-09-14")
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": "ana", "id": "1"}, m.CABECERA)])
        m._escribir_meta(r, True, 1, 1, "completa")
    e = m.estado_de_cuenta("t")
    check(e["capturas"] == 2, "una descarga deja dos archivos")
    check(e["dias"] == 1,
          f"pero un solo día, que es lo que cuenta ({e['dias']})")
    r = m._ruta_captura("seguidores", "2026-09-15")
    m._escribir_csv(r, m.CABECERA,
                    [m._fila({"username": "ana", "id": "1"}, m.CABECERA)])
    m._escribir_meta(r, True, 1, 1, "completa")
    check(m.estado_de_cuenta("t")["dias"] == 2, "y con otro día, dos")

    # 3. El motor sirve a las dos caras: no puede nombrar solo la orden de
    #    terminal en mensajes que también lee quien usa la ventana.
    motor_src = Path("instagram_listas.py").read_text(encoding="utf-8")
    for mala in ("ejecutar 'bajar'", "ejecuta 'bajar'"):
        check(mala not in motor_src and mala not in fuente,
              f"ningún «{mala}» en mensajes que ve la ventana")

    gui = Path("instagram_gui.py").read_text(encoding="utf-8")
    check("Importar del navegador" not in gui,
          "y la guía nombra los botones como se llaman de verdad")
    for boton in ("Importar sesión", "Listas completas", "Contar"):
        check(boton in gui, f"«{boton}» existe tal cual")


def f61_las_pruebas_tambien_se_revisan():
    print("\n[F61] Los archivos de pruebas también son código")
    import ast as _ast
    import builtins as _b

    # Al repartir, `pruebas/` quedó fuera de todas las comprobaciones
    # estáticas: miraban la raíz y saltaban lo que empieza por test_.
    carpeta = Path("pruebas")
    check(carpeta.is_dir(), "existe la carpeta de pruebas")

    comun_ast = _ast.parse((carpeta / "comun.py").read_text(encoding="utf-8"))
    exportados = set()
    for n in comun_ast.body:
        if isinstance(n, (_ast.FunctionDef, _ast.ClassDef)):
            exportados.add(n.name)
        elif isinstance(n, _ast.Assign):
            exportados |= {t.id for t in n.targets
                           if isinstance(t, _ast.Name)}
        elif isinstance(n, (_ast.Import, _ast.ImportFrom)):
            for a in n.names:
                exportados.add((a.asname or a.name).split(".")[0])

    sueltos, choques, todas = [], [], []
    for archivo in sorted(carpeta.glob("*.py")):
        if archivo.name in ("comun.py", "__init__.py"):
            continue
        arbol = _ast.parse(archivo.read_text(encoding="utf-8"))
        propios = {n.name for n in arbol.body
                   if isinstance(n, (_ast.FunctionDef, _ast.ClassDef))}
        todas += [n for n in propios]
        choques += [f"{archivo.name}:{n}" for n in propios & exportados]
        for n in arbol.body:
            if isinstance(n, _ast.Assign):
                propios |= {x.id for x in n.targets
                            if isinstance(x, _ast.Name)}
            elif isinstance(n, (_ast.Import, _ast.ImportFrom)):
                for a in n.names:
                    propios.add((a.asname or a.name).split(".")[0])
        for fn in [n for n in arbol.body
                   if isinstance(n, _ast.FunctionDef)]:
            loc = set()
            for x in _ast.walk(fn):
                if isinstance(x, _ast.Name) and isinstance(x.ctx, _ast.Store):
                    loc.add(x.id)
                elif isinstance(x, _ast.arg):
                    loc.add(x.arg)
                elif isinstance(x, (_ast.FunctionDef, _ast.ClassDef)) \
                        and x is not fn:
                    loc.add(x.name)
                elif isinstance(x, _ast.ExceptHandler) and x.name:
                    loc.add(x.name)
                elif isinstance(x, _ast.alias):
                    loc.add((x.asname or x.name).split(".")[0])
            for x in _ast.walk(fn):
                if (isinstance(x, _ast.Name)
                        and isinstance(x.ctx, _ast.Load)
                        and x.id not in loc and x.id not in propios
                        and x.id not in exportados
                        and x.id not in ("__file__", "__name__", "__doc__")
                        and not hasattr(_b, x.id)):
                    sueltos.append(f"{archivo.name}:{fn.name}:{x.id}")

    check(not sueltos, f"sin nombres sueltos en pruebas/: {sueltos[:3]}")
    # Redefinir un ayudante de comun.py lo taparía solo en ese archivo, y
    # dos pruebas del mismo nombre harían que una no se ejecutara nunca.
    check(not choques, f"nadie redefine un ayudante común: {choques}")
    repetidas = sorted({n for n in todas if todas.count(n) > 1})
    check(not repetidas, f"ninguna prueba repetida entre archivos: "
                         f"{repetidas}")

    # En Windows, doble clic en un .py cierra la consola en cuanto
    # termina: no se lee nada y no se puede copiar. Los dos lanzadores
    # tienen que guardar su salida y esperar.
    for lanzador in ("test_modulo.py", "test_gui.py"):
        texto = Path(lanzador).read_text(encoding="utf-8")
        check("consola" in texto and "ejecutar(" in texto,
              f"{lanzador} guarda su salida y espera antes de cerrar")
    # Las de la ventana no pueden decidir si hay pantalla mirando DISPLAY:
    # es de X11, en Windows no existe, y allí tkinter funciona igual. Las
    # 53 se saltaban enteras justo en el sistema donde se usa el programa.
    gui = Path("test_gui.py").read_text(encoding="utf-8")
    arbol_gui = _ast.parse(gui)
    fn = next(n for n in _ast.walk(arbol_gui)
              if isinstance(n, _ast.FunctionDef) and n.name == "hay_pantalla")
    # Sobre las SENTENCIAS, sin el docstring: la explicación del arreglo
    # menciona os.environ, y tanto buscar en el archivo como volcar el
    # cuerpo entero hacían fallar la comprobación por su propio
    # comentario. Dos veces el mismo error, con dos disfraces.
    cuerpo = [n for n in fn.body
              if not (isinstance(n, _ast.Expr)
                      and isinstance(n.value, _ast.Constant)
                      and isinstance(n.value.value, str))]
    codigo = _ast.dump(_ast.Module(body=cuerpo, type_ignores=[]))
    check("environ" not in codigo,
          "hay_pantalla() no decide por una variable de entorno")
    check("Tk" in codigo,
          "sino intentando abrir una ventana, que vale en los tres "
          "sistemas")

    ayuda = Path("pruebas/consola.py").read_text(encoding="utf-8")
    check("closed" in ayuda,
          "el volcado comprueba que el archivo siga abierto: Python llama "
          "a flush() al destruir el objeto, ya cerrado, y salía un error "
          "al final de una ejecución correcta")
    check("--sin-pausa" in ayuda,
          "y se puede saltar la pausa para lanzarlo desde otro script")
    # La bandera se lee ANTES de ejecutar: varias pruebas reemplazan
    # sys.argv para probar la línea de órdenes, y al terminar ya no está.
    # Con --sin-pausa se quedaba esperando una tecla para siempre.
    i = ayuda.index("def ejecutar")
    antes = ayuda[i:ayuda.index("codigo = 0", i)]
    check("--sin-pausa" in antes,
          "y se lee antes de ejecutar nada, porque las pruebas tocan "
          "sys.argv")
    check("flush()" in ayuda,
          "el archivo se vuelca según se escribe: un cuelgue a mitad es "
          "justo cuando más falta hace saber por dónde iba")

    # Un script del proyecto no puede reventar con una traza por
    # ejecutarlo. `repartir.py` leía un archivo que ya se borró.
    reparto = Path("repartir.py")
    if reparto.exists():
        check("ORIGEN.exists()" in reparto.read_text(encoding="utf-8"),
              "repartir.py avisa en vez de reventar si ya no hay qué "
              "repartir")


def f55_repaso_del_proyecto():
    print("\n[F55] Cosas que solo se ven mirando el proyecto entero")
    import ast as _ast
    import builtins as _b

    archivos = [a for a in sorted(Path(".").glob("*.py"))
                if not a.name.startswith("test_")]

    # 1. Campos de TRES estados usados como booleano. None significa «no
    #    se sabe», y en un `if` se convierte en «no». Este proyecto ha
    #    cometido ese fallo con 'privada', con 'la_sigo' y con 'completa'.
    triestado = {"privada", "la_sigo", "completa"}
    sospechosos = []
    for archivo in archivos:
        arbol = _ast.parse(archivo.read_text(encoding="utf-8"))

        def mirar(nodo, linea):
            if (isinstance(nodo, _ast.Call)
                    and isinstance(nodo.func, _ast.Attribute)
                    and nodo.func.attr == "get" and len(nodo.args) == 1
                    and isinstance(nodo.args[0], _ast.Constant)
                    and nodo.args[0].value in triestado):
                sospechosos.append(f"{archivo.name}:{linea}")
            elif (isinstance(nodo, _ast.Subscript)
                  and isinstance(nodo.slice, _ast.Constant)
                  and nodo.slice.value in triestado):
                sospechosos.append(f"{archivo.name}:{linea}")

        for n in _ast.walk(arbol):
            if isinstance(n, _ast.If):
                prueba = n.test
                if isinstance(prueba, _ast.UnaryOp) and isinstance(
                        prueba.op, _ast.Not):
                    prueba = prueba.operand
                mirar(prueba, n.lineno)
            elif isinstance(n, _ast.IfExp):
                mirar(n.test, n.lineno)
    # Los dos que quedan están comprobados a mano y son correctos: uno
    # sale de una rama que ya descartó el False, el otro es el «si no es
    # privada no hay nada que avisar».
    check(len(sospechosos) <= 2,
          f"tres estados tratados como dos: {sospechosos}")

    # 2. Cadenas sueltas: un docstring que se quedó huérfano al escribir
    #    otro encima es código muerto que nadie ve.
    sueltas = []
    for archivo in archivos:
        arbol = _ast.parse(archivo.read_text(encoding="utf-8"))
        for ámbito in _ast.walk(arbol):
            if not isinstance(ámbito, (_ast.FunctionDef, _ast.ClassDef,
                                       _ast.Module)):
                continue
            for i, nodo in enumerate(ámbito.body):
                if (i > 0 and isinstance(nodo, _ast.Expr)
                        and isinstance(nodo.value, _ast.Constant)
                        and isinstance(nodo.value.value, str)):
                    sueltas.append(f"{archivo.name}:{nodo.lineno}")
    check(not sueltas, f"ninguna cadena suelta: {sueltas}")

    # 3. Argumentos por defecto mutables: se comparten entre llamadas y
    #    el fallo aparece en la segunda, lejos de donde se escribió.
    mutables = []
    for archivo in archivos:
        arbol = _ast.parse(archivo.read_text(encoding="utf-8"))
        for fn in _ast.walk(arbol):
            if isinstance(fn, _ast.FunctionDef):
                for d in fn.args.defaults + [x for x in fn.args.kw_defaults
                                             if x]:
                    if isinstance(d, (_ast.List, _ast.Dict, _ast.Set)):
                        mutables.append(f"{archivo.name}:{fn.name}")
    check(not mutables, f"sin defectos mutables: {mutables}")

    # 4. Importaciones huérfanas. Las dos del motor se quedaron sin uso al
    #    mudar la línea de órdenes, y nada lo dijo.
    for archivo in archivos:
        codigo = archivo.read_text(encoding="utf-8")
        arbol = _ast.parse(codigo)
        nombres = {n.id for n in _ast.walk(arbol)
                   if isinstance(n, _ast.Name)}
        nombres |= {n.value.id for n in _ast.walk(arbol)
                    if isinstance(n, _ast.Attribute)
                    and isinstance(n.value, _ast.Name)}
        muertas = []
        for n in _ast.walk(arbol):
            if not isinstance(n, (_ast.Import, _ast.ImportFrom)):
                continue
            if "noqa" in codigo.splitlines()[n.lineno - 1]:
                continue          # re-exportación a propósito
            for a in n.names:
                corto = (a.asname or a.name).split(".")[0]
                if corto not in ("*", "annotations") and corto not in nombres:
                    muertas.append(corto)
        check(not muertas, f"{archivo.name} sin importaciones muertas: "
                           f"{muertas}")


def r6_sin_codigo_muerto():
    print("\n[R6] _una_pasada informa del motivo real, sin ramas muertas")
    import inspect
    src = inspect.getsource(m._una_pasada)
    check("terminado" not in src, "desapareció la variable 'terminado'")
    check('motivo = "truncada"' in src, "distingue el caso truncado")

    src_d = inspect.getsource(m.descargar)
    check("if terminado" not in src_d, "descargar() ya no tiene la rama muerta")

    prep(TEMPORAL("r6"))

    class Trunca(FakeIG):
        def pedir(self, s, ruta, params=None, referer=None):
            self.peticiones += 1
            i = int((params or {}).get("max_id", 0))
            if i >= 1000:
                return {"users": [], "next_max_id": str(i + 50)}
            return super().pedir(s, ruta, params)

    m.pedir = Trunca(0, 2000).pedir
    m.descargar(None, perfil(0, 2000), "seguidos")
    meta = m._leer_meta(m._ruta_captura("seguidos"))
    check(meta["completa"] is False, "la captura truncada se marca incompleta")
    check(meta["obtenidos"] == 1000 and meta["esperados"] == 2000,
          "los metadatos registran cuánto faltó")


def r7_tiempos_documentados():
    print("\n[R7] Los tiempos de espera del docstring deben cuadrar")
    e, total = m.ESPERA_INICIAL, 0
    # valores reales del módulo, no los de prueba
    import importlib
    fresco = importlib.reload(m)
    e, total = fresco.ESPERA_INICIAL, 0
    for _ in range(fresco.MAX_REINTENTOS - 1):
        total += e
        e = min(e * 2, fresco.ESPERA_MAXIMA)
    horas = round(total / 3600, 1)
    # El docstring está en español y usa coma decimal.
    esperado = f"{horas}".replace(".", ",")
    check(esperado in fresco.__doc__,
          f"el docstring menciona las {esperado} h reales del peor caso")


def r10_rutas_configurables():
    print("\n[R10] Reparar una ruta debe ser editar una línea, no código")
    prep(TEMPORAL("r10"))
    m.recargar_config()
    check(m.ruta("lista_seguidores", id="9") ==
          "/api/v1/friendships/9/followers/", "de serie, la ruta conocida")
    check(m.param("cursor") == "max_id", "y el nombre del parámetro")
    check(m.campo("usuarios") == "users", "y el del campo de respuesta")

    # Instagram lo cambia todo: se repara sin tocar el programa
    m._ruta_config().write_text(json.dumps({
        "rutas": {"lista_seguidores": "/api/v2/seguidores/{id}/"},
        "params": {"cursor": "despues_de", "cantidad": "cuantos"},
        "campos": {"usuarios": "items", "cursor_siguiente": "siguiente"},
    }), encoding="utf-8")
    m.recargar_config()

    check(m.ruta("lista_seguidores", id="9") == "/api/v2/seguidores/9/",
          "la ruta nueva se aplica")
    check(m.param("cursor") == "despues_de", "el parámetro nuevo también")
    check(m.campo("usuarios") == "items", "y el campo nuevo")
    check(m.ruta("perfil") == "/api/v1/users/web_profile_info/",
          "lo que no se toca conserva su valor de serie")

    # Y la descarga entera funciona con los nombres nuevos
    pedidas = []

    def api_nueva(s, ruta_usada, params=None, referer=None):
        pedidas.append((ruta_usada, sorted(params or {})))
        i = int((params or {}).get("despues_de", 0))
        n = params["cuantos"]
        users = [{"pk": f"u{k}", "username": f"u{k}", "full_name": ""}
                 for k in range(i, min(i + n, 70))]
        fin = i + len(users)
        return {"items": users,
                "siguiente": str(fin) if fin < 70 else None}

    m.pedir = api_nueva
    m.descargar(None, {"id": "9", "seguidores": 70, "seguidos": 0,
                       "totales_fiables": True}, "seguidores")
    filas = leer(m._ruta_captura("seguidores"))
    check(len(filas) == 70,
          f"la descarga funciona con la API cambiada ({len(filas)})")
    check(pedidas[0][0] == "/api/v2/seguidores/9/", "usando la ruta nueva")
    check("cuantos" in pedidas[0][1], "y los parámetros nuevos")

    # El contrato se reconstruye con los nombres nuevos, no exige los viejos
    m.validar("lista", {"items": [{"pk": "1", "username": "a"}]})
    check(True, "el contrato valida con el nombre nuevo del campo")
    try:
        m.validar("lista", {"users": [{"pk": "1", "username": "a"}]})
        check(False, "y ya no acepta el viejo")
    except m.RespuestaInesperada:
        check(True, "y rechaza el nombre viejo, que ahora sería el raro")

    m._ruta_config().unlink()
    m.recargar_config()


PRUEBAS = [
    f16_plurales,
    f28_ajustes_en_un_sitio,
    f29_repaso_de_escritura_y_ajustes,
    f31_el_reparto_aguanta,
    f32_ningun_nombre_suelto,
    f38_version,
    f43_los_botones_pasan_lo_que_hace_falta,
    f45_el_readme_no_miente,
    f52_lo_que_se_lee_en_pantalla,
    f55_repaso_del_proyecto,
    f61_las_pruebas_tambien_se_revisan,
    r6_sin_codigo_muerto,
    r7_tiempos_documentados,
    r10_rutas_configurables,
]
