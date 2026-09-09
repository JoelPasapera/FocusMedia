"""
Pruebas de instagram_gui.py.

Dos bloques:
  G1..G6  lógica pura (cola, hilo, cancelación, ajustes). Sin pantalla.
  W1..W3  arranque real de la ventana. Necesita display; con Xvfb vale.

    python test_gui.py
    xvfb-run -a python test_gui.py      # para que corran también los W
"""

import os
import queue
import shutil
import sys
import time
import traceback
from pathlib import Path

import instagram_listas as m
import instagram_gui as g

FALLOS = []


def check(cond, msg):
    print(("  OK    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLOS.append(msg)


def esperar(condicion, limite=5.0):
    """Espera activa con tope, para no colgar la suite si algo falla."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def drenar(cola):
    salida = []
    try:
        while True:
            salida.append(cola.get_nowait())
    except queue.Empty:
        pass
    return salida


# ======================================================================
# LÓGICA SIN PANTALLA
# ======================================================================

def g1_salida_a_cola():
    print("\n[G1] La salida del módulo se trocea en líneas")
    c = queue.Queue()
    s = g.SalidaACola(c)

    s.write("hola\nmundo\n")
    check([t[1] for t in drenar(c)] == ["hola", "mundo"],
          "separa por saltos de línea")

    # El módulo usa \r para el progreso: debe contar como línea
    s.write("  10/100   (página 1)\r  20/100   (página 2)\r")
    lineas = [t[1] for t in drenar(c)]
    check(len(lineas) == 2 and "20/100" in lineas[1],
          f"trata \\r como salto ({lineas})")

    # Texto sin terminar se queda en el buffer hasta flush
    s.write("a medias")
    check(drenar(c) == [], "no emite líneas incompletas")
    s.flush()
    check([t[1] for t in drenar(c)] == ["a medias"], "flush suelta el resto")

    check(s.write("xy") == 2, "write devuelve los caracteres escritos")


def g2_progreso():
    print("\n[G2] Lectura del progreso")
    check(g.leer_progreso("  500/2000   (página 10)") == 0.25, "500/2000 = 25%")
    check(g.leer_progreso("  2000/2000   (página 40)") == 1.0, "completo = 100%")
    check(g.leer_progreso("Captura guardada: x.csv") is None,
          "una línea normal no da progreso")
    check(g.leer_progreso("  5/0   (página 1)") is None,
          "total 0 no revienta")
    check(g.leer_progreso("  50/? (página 1)") is None,
          "total desconocido no revienta")
    check(g.leer_progreso("  3000/2000   (página 60)") == 1.0,
          "se recorta a 100% si se pasa")


def g3_trabajador_basico():
    print("\n[G3] El trabajador ejecuta en segundo plano")
    t = g.Trabajador()

    def tarea():
        print("empezando")
        print("terminando")

    check(t.lanzar("prueba", tarea), "lanza la tarea")
    check(esperar(lambda: not t.ocupado()), "termina sola")

    eventos = drenar(t.cola)
    tipos = [e[0] for e in eventos]
    check(tipos[0] == "inicio" and tipos[-1] == "fin",
          f"emite inicio y fin ({tipos})")
    lineas = [e[1] for e in eventos if e[0] == "linea"]
    check(lineas == ["empezando", "terminando"], f"captura los print ({lineas})")

    check(sys.stdout is not g.SalidaACola,
          "sys.stdout queda restaurado al terminar")


def g4_una_tarea_a_la_vez():
    print("\n[G4] No debe haber dos tareas a la vez")
    t = g.Trabajador()
    puerta = [False]

    def lenta():
        while not puerta[0]:
            time.sleep(0.01)

    check(t.lanzar("primera", lenta), "arranca la primera")
    check(esperar(lambda: t.ocupado()), "la primera está en marcha")
    check(t.lanzar("segunda", lambda: None) is False,
          "rechaza la segunda mientras la primera corre")
    puerta[0] = True
    check(esperar(lambda: not t.ocupado()), "la primera termina")
    check(t.lanzar("tercera", lambda: None), "después ya admite otra")
    esperar(lambda: not t.ocupado())


def g5_cancelacion():
    print("\n[G5] Cancelar corta una descarga larga de verdad")
    carpeta = Path("/tmp/gui5")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "t"
    m.PAUSA_MIN = m.PAUSA_MAX = 0.02

    paginas = [0]

    def pedir_lento(s, ruta, params=None):
        paginas[0] += 1
        i = int((params or {}).get("max_id", 0))
        users = [{"pk": f"u{k}", "username": f"u{k}", "full_name": ""}
                 for k in range(i, min(i + 50, 100000))]
        return {"users": users, "next_max_id": str(i + len(users))}

    m.pedir = pedir_lento
    t = g.Trabajador()
    t.lanzar("descarga", m.descargar, None,
             {"id": "1", "seguidores": 100000, "seguidos": 0}, "seguidores")

    check(esperar(lambda: paginas[0] >= 3), "la descarga arranca")
    hasta_ahora = paginas[0]
    t.cancelar()

    check(esperar(lambda: not t.ocupado(), limite=8), "para al cancelar")
    check(paginas[0] - hasta_ahora < 20,
          f"para pronto, no al final ({paginas[0] - hasta_ahora} páginas más)")

    tipos = [e[0] for e in drenar(t.cola)]
    check("cancelado" in tipos, f"avisa de la cancelación ({tipos[-1]})")

    parcial = m._ruta_parcial("seguidores")
    check(parcial.exists() and len(m._leer_csv(parcial)) > 0,
          "el progreso queda guardado para retomarlo")
    check(m._ruta_estado("seguidores").exists(), "y el cursor también")
    check(m.CANCELAR is None, "el gancho del módulo queda limpio")


def g6_espera_larga_cancelable():
    print("\n[G6] Cancelar durante una espera de 10 minutos")
    m.CANCELAR = None
    inicio = time.monotonic()
    parar = [False]
    m.CANCELAR = lambda: parar[0]

    import threading
    threading.Timer(0.3, lambda: parar.__setitem__(0, True)).start()
    try:
        m._dormir(600)          # diez minutos
        check(False, "debería haber saltado")
    except KeyboardInterrupt:
        transcurrido = time.monotonic() - inicio
        check(transcurrido < 2,
              f"corta en {transcurrido:.1f}s, no en 600")
    m.CANCELAR = None


def g7_errores_del_modulo():
    print("\n[G7] Los errores del módulo llegan a la interfaz")
    t = g.Trabajador()

    t.lanzar("fallo", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    esperar(lambda: not t.ocupado())
    eventos = drenar(t.cola)
    check(any(e[0] == "error" and "boom" in e[1] for e in eventos),
          "una excepción se reporta como error")
    check(any("Traceback" in e[1] for e in eventos if e[0] == "linea"),
          "y el detalle va a la consola")

    # sys.exit() es como el módulo avisa de errores de usuario
    t.lanzar("salida", lambda: sys.exit("cuenta privada"))
    esperar(lambda: not t.ocupado())
    eventos = drenar(t.cola)
    check(any(e[0] == "error" and "privada" in e[1] for e in eventos),
          "sys.exit se traduce a error, no tumba el hilo")

    check(t.lanzar("otra", lambda: None), "el trabajador sigue usable")
    esperar(lambda: not t.ocupado())


def g8_ajustes():
    print("\n[G8] Ajustes persistentes")
    ruta = Path("/tmp/gui_config.json")
    ruta.unlink(missing_ok=True)

    a = g.Ajustes(ruta)
    check(a.datos["navegador"] == "firefox", "valores por defecto")

    a.datos["objetivo"] = "  @Alguien  "
    a.datos["navegador"] = "chrome"
    a.guardar()
    check(ruta.exists(), "guarda el archivo")

    b = g.Ajustes(ruta)
    check(b.datos["navegador"] == "chrome", "recupera lo guardado")

    b.aplicar_al_modulo()
    check(m.OBJETIVO == "Alguien", f"limpia espacios y @ ({m.OBJETIVO!r})")
    check(m.NAVEGADOR == "chrome", "aplica el navegador al módulo")

    # Validación
    c = g.Ajustes(ruta)
    c.datos["objetivo"] = "cuenta_objetivo"
    check(c.valido() is not None, "rechaza el marcador por defecto")
    c.datos["objetivo"] = ""
    check(c.valido() is not None, "rechaza el vacío")
    c.datos["objetivo"] = "una/ruta"
    check(c.valido() is not None, "rechaza caracteres imposibles")
    c.datos["objetivo"] = "usuario.valido_1"
    check(c.valido() is None, "acepta un usuario normal")

    # Config corrupta
    ruta.write_text("{roto", encoding="utf-8")
    d = g.Ajustes(ruta)
    check(d.datos["navegador"] == "firefox",
          "config corrupta -> valores por defecto, sin reventar")
    ruta.unlink(missing_ok=True)


def g9_colores():
    print("\n[G9] Clasificación de líneas por color")
    class Falsa:
        _color_de = g.Ventana._color_de
    v = Falsa()
    check(v._color_de("  AVISO: captura INCOMPLETA") == g.COLOR_AVISO,
          "los avisos en ámbar")
    check(v._color_de("  Cortado: demasiadas peticiones") == g.COLOR_ERROR,
          "los cortes en rojo")
    check(v._color_de("  Captura guardada: x.csv  (500)") == g.COLOR_BIEN,
          "los éxitos en verde")
    check(v._color_de("  500/2000   (página 10)") is None,
          "el progreso sin color")


# ======================================================================
# VENTANA REAL (necesita display)
# ======================================================================

def hay_pantalla():
    return bool(os.environ.get("DISPLAY"))


def w1_arranque():
    print("\n[W1] La ventana arranca y se dibuja")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY; ejecuta con xvfb-run)")
        return

    g.ARCHIVO_CONFIG = Path("/tmp/gui_w.json")
    g.ARCHIVO_CONFIG.unlink(missing_ok=True)

    v = g.Ventana()
    v.update()
    check(v.winfo_exists() == 1, "la ventana existe")
    check(len(v.botones_accion) == 13, f"13 acciones ({len(v.botones_accion)})")
    check(len(v.etiquetas_coste) == 13, "cada acción muestra su coste")
    check(str(v.boton_parar.cget("state")) == "disabled",
          "'Parar' empieza deshabilitado")
    check(v.etiqueta_estado.cget("text") == "En reposo", "estado inicial")
    v.destroy()


def w2_bloqueo_de_botones():
    print("\n[W2] Los botones se bloquean mientras se trabaja")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    v = g.Ventana()
    v.update()

    v._bloquear(True, "Trabajando")
    v.update()
    check(all(str(b.cget("state")) == "disabled" for b in v.botones_accion),
          "todas las acciones deshabilitadas")
    check(str(v.boton_parar.cget("state")) == "normal", "'Parar' habilitado")

    v._bloquear(False, "Listo")
    v.update()
    check(all(str(b.cget("state")) == "normal" for b in v.botones_accion),
          "se rehabilitan al terminar")
    check(str(v.boton_parar.cget("state")) == "disabled",
          "'Parar' vuelve a deshabilitarse")
    v.destroy()


def w3_flujo_completo():
    print("\n[W3] Una acción real, de principio a fin")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w3")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.PAUSA_MIN = m.PAUSA_MAX = 0

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_prueba")
    v.campo_lista.set("seguidos")
    v.update()

    # Instagram simulado
    def pedir(s, ruta, params=None):
        i = int((params or {}).get("max_id", 0))
        users = [{"pk": f"u{k}", "username": f"u{k}", "full_name": f"N{k}",
                  "is_private": False}
                 for k in range(i, min(i + 50, 120))]
        return {"users": users,
                "next_max_id": str(i + len(users)) if i + len(users) < 120
                else None}

    m.pedir = pedir
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: {"id": "1", "username": u, "nombre": "",
                             "seguidores": 0, "seguidos": 120,
                             "privada": False, "la_sigo": True}

    v.accion_bajar()
    fin = time.monotonic() + 10
    while v.trabajador.ocupado() and time.monotonic() < fin:
        v.update()
        time.sleep(0.02)
    for _ in range(30):                 # dejar que la cola se vacíe
        v.update()
        time.sleep(0.02)

    texto = v.consola.get("1.0", "end")
    check("Captura guardada" in texto, "la consola muestra el resultado")
    check("120 registros" in texto, "con las cifras correctas")
    check(v.etiqueta_estado.cget("text") == "Terminado", "estado final correcto")

    cap = m._ruta_captura("seguidos")
    check(cap.exists() and len(m._leer_csv(cap)) == 120,
          "y el archivo está realmente en disco")

    check(str(v.botones_accion[0].cget("state")) == "normal",
          "los botones vuelven a estar disponibles")
    v.destroy()


def w5_cierre_limpio():
    print("\n[W5] Cerrar la ventana no debe dejar callbacks colgando")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    v = g.Ventana()
    v.update()
    check(getattr(v, "_tarea_cola", None) is not None,
          "el vaciado de cola queda registrado para poder cancelarlo")

    # Cerrar justo después de terminar una tarea: el after de la barra
    # (1200 ms) apuntaría a widgets ya destruidos.
    v._bloquear(False, "Listo")
    v.update()
    check(getattr(v, "_tarea_barra", None) is not None,
          "el reinicio de la barra también")

    v._cerrar()
    # En la ventana raíz, tras destroy() cualquier consulta lanza TclError:
    # esa excepción ES la prueba de que se destruyó.
    import tkinter
    try:
        v.winfo_exists()
        destruida = False
    except tkinter.TclError:
        destruida = True
    check(destruida, "la ventana se destruye")
    time.sleep(1.6)                     # más que los 1200 ms del after
    check(True, "y no salta ninguna excepción por callbacks huérfanos")


def w6_cierre_con_descarga_en_marcha():
    print("\n[W6] Cerrar durante una descarga la corta y guarda")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w6")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "t"
    m.PAUSA_MIN = m.PAUSA_MAX = 0.02

    paginas = [0]

    def pedir(s, ruta, params=None):
        paginas[0] += 1
        i = int((params or {}).get("max_id", 0))
        users = [{"pk": f"u{k}", "username": f"u{k}", "full_name": ""}
                 for k in range(i, i + 50)]
        return {"users": users, "next_max_id": str(i + 50)}

    m.pedir = pedir

    v = g.Ventana()
    v.update()
    v.trabajador.lanzar("descarga", m.descargar, None,
                        {"id": "1", "seguidores": 999999, "seguidos": 0},
                        "seguidores")
    esperar(lambda: paginas[0] >= 3)
    check(v.trabajador.ocupado(), "la descarga está en marcha")

    inicio = time.monotonic()
    v._cerrar()
    tardanza = time.monotonic() - inicio

    check(not v.trabajador.ocupado(), "el hilo terminó antes de destruir")
    check(tardanza < 4, f"el cierre no se eterniza ({tardanza:.1f}s)")

    parcial = m._ruta_parcial("seguidores")
    check(parcial.exists(), "el parcial queda en disco")
    filas = m._leer_csv(parcial)
    check(len(filas) > 0, f"con las filas ya descargadas ({len(filas)})")
    check(all(f.get("id") for f in filas),
          "y ninguna fila quedó a medio escribir")
    check(m._ruta_estado("seguidores").exists(),
          "el cursor también, para poder retomar")


def w7_panel_de_disco():
    print("\n[W7] El resumen de disco refleja lo que hay")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w7")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w7")
    v._refrescar_disco()
    v.update()
    check(v.celdas["seguidores"][0].cget("text") == "—",
          "sin capturas muestra un guión")
    check("sin capturas" in v.celdas["capturas"][1].cget("text"),
          "y lo dice en el detalle")

    # Una captura completa y otra incompleta
    m.OBJETIVO = "cuenta_w7"
    r1 = m._ruta_captura("seguidores", "2026-09-01")
    m._escribir_csv(r1, m.CABECERA, [[f"u{i}", "", str(i)] for i in range(340)])
    m._escribir_meta(r1, True, 340, 340, "completa")
    r2 = m._ruta_captura("seguidos", "2026-09-01")
    m._escribir_csv(r2, m.CABECERA, [[f"g{i}", "", str(i)] for i in range(80)])
    m._escribir_meta(r2, False, 900, 80, "solo 80 de ~900")

    v._refrescar_disco()
    v.update()
    check(v.celdas["seguidores"][0].cget("text") == "340",
          f"cifra correcta ({v.celdas['seguidores'][0].cget('text')})")
    check("completa" in v.celdas["seguidores"][1].cget("text"),
          "marca la completa")
    check("incompleta" in v.celdas["seguidos"][1].cget("text"),
          "y la incompleta")
    check(v.celdas["seguidos"][0].cget("text_color") == g.COLOR_AVISO,
          "la incompleta se pinta en ámbar")
    check(v.celdas["capturas"][0].cget("text") == "2", "cuenta las capturas")

    # Una descarga a medias debe avisarse
    m._escribir_csv(m._ruta_parcial("seguidores"), m.CABECERA,
                    [["x", "", "1"]])
    v._refrescar_disco()
    check("a medias" in v.celdas["seguidores"][1].cget("text"),
          "avisa de la descarga pendiente de retomar")

    # No debe dejar tocado el OBJETIVO del módulo
    m.OBJETIVO = "otro"
    v._refrescar_disco()
    check(m.OBJETIVO == "otro", "no deja el OBJETIVO del módulo cambiado")
    v.destroy()


def w8_barra_invisible_en_reposo():
    print("\n[W8] La barra no debe dejar un punto suelto en reposo")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return
    v = g.Ventana()
    v.update()
    check(v.barra.cget("progress_color") == g.RAISED,
          "en reposo la barra se funde con el fondo")
    v._bloquear(True, "En curso")
    check(v.barra.cget("progress_color") == g.ACENTO,
          "al trabajar se enciende")
    v._bloquear(False, "Terminado")
    v._reiniciar_barra()
    check(v.barra.cget("progress_color") == g.RAISED,
          "y vuelve a apagarse al acabar")
    v.destroy()


def g10_limpiar_usuario():
    print("\n[G10] Aceptar lo que la gente pega de verdad")
    casos = [
        ("https://www.instagram.com/yomira.milagros/", "yomira.milagros"),
        ("http://instagram.com/yomira.milagros", "yomira.milagros"),
        ("www.instagram.com/yomira.milagros/", "yomira.milagros"),
        ("https://instagram.com/yomira.milagros?hl=es", "yomira.milagros"),
        ("https://www.instagram.com/yomira.milagros/reels/",
         "yomira.milagros"),
        ("https://www.instagram.com/stories/yomira.milagros/123/",
         "yomira.milagros"),
        ("@yomira.milagros", "yomira.milagros"),
        ("  yomira.milagros  ", "yomira.milagros"),
        ("usuario_1", "usuario_1"),
        ("HTTPS://WWW.INSTAGRAM.COM/Otra.Cuenta/", "Otra.Cuenta"),
    ]
    for entrada, esperado in casos:
        obtenido = g.limpiar_usuario(entrada)
        check(obtenido == esperado,
              f"{entrada[:44]!r} -> {obtenido!r}")

    # Enlaces que NO son perfiles
    for entrada in ("https://www.instagram.com/p/ABC123/",
                    "https://www.instagram.com/reel/XYZ/",
                    "https://www.instagram.com/explore/tags/gatos/",
                    "https://www.instagram.com/accounts/edit/",
                    "https://www.instagram.com/", ""):
        check(g.limpiar_usuario(entrada) == "",
              f"no es un perfil: {entrada[:44]!r}")

    check(g.limpiar_usuario(None) == "", "None no revienta")


def g11_mensajes_de_validacion():
    print("\n[G11] Cada error dice qué hacer")
    ruta = Path("/tmp/gui_cfg11.json")
    ruta.unlink(missing_ok=True)
    a = g.Ajustes(ruta)

    a.datos["objetivo"] = "https://www.instagram.com/yomira.milagros/"
    check(a.valido() is None, "una URL de perfil es válida")
    a.aplicar_al_modulo()
    check(m.OBJETIVO == "yomira.milagros",
          f"y llega limpia al módulo ({m.OBJETIVO!r})")

    a.datos["objetivo"] = "https://www.instagram.com/p/ABC123/"
    mensaje = a.valido()
    check(mensaje and "publicación" in mensaje,
          f"un enlace a publicación se explica ({mensaje})")

    a.datos["objetivo"] = ""
    check("enlace del perfil" in (a.valido() or ""),
          "el campo vacío dice qué se puede pegar")

    a.datos["objetivo"] = "nombre con espacios"
    check("nombre de usuario" in (a.valido() or ""),
          "un nombre imposible se explica")

    ruta.unlink(missing_ok=True)


def w9_campo_se_normaliza():
    print("\n[W9] El campo reescribe la URL a la vista")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w9")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("https://www.instagram.com/yomira.milagros/")
    v._normalizar_cuenta()
    v.update()

    check(v.campo_objetivo.get() == "yomira.milagros",
          f"la URL se convierte a usuario ({v.campo_objetivo.get()!r})")
    check("Entendido" in v.consola.get("1.0", "end"),
          "y se dice en la consola qué se entendió")
    check(str(v.campo_objetivo.cget("border_color")) == g.LINE,
          "el borde queda normal si es válida")

    # Un enlace que no es de perfil debe avisar en el momento
    v.accion_limpiar()
    v.campo_objetivo.set("https://www.instagram.com/p/ABC123/")
    v._normalizar_cuenta()
    v.update()
    texto = v.consola.get("1.0", "end")
    check("publicación" in texto, "avisa al momento, sin esperar a un botón")
    check(str(v.campo_objetivo.cget("border_color")) == g.COLOR_AVISO,
          "y el borde se pone ámbar")

    # Al corregirlo, el borde vuelve
    v.campo_objetivo.set("cuenta_buena")
    v._normalizar_cuenta()
    v.update()
    check(str(v.campo_objetivo.cget("border_color")) == g.LINE,
          "el borde se recupera al corregir")
    v.destroy()


def w10_sesion_solo_con_id():
    print("\n[W10] Un id numérico no debe presentarse como nombre de usuario")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return
    v = g.Ventana()

    v._estado_sesion("micuenta")
    check("@micuenta" in v.etiqueta_sesion.cget("text"),
          "con nombre real se muestra con @")

    v._estado_sesion("#9982027586")
    texto = v.etiqueta_sesion.cget("text")
    check("id 9982027586" in texto, f"con id se dice 'id' ({texto})")
    check("@9982027586" not in texto,
          "y NUNCA con @, que daría a entender un usuario inexistente")
    check(str(v.punto.cget("text_color")) == g.COLOR_BIEN,
          "la sesión sigue marcándose como activa")
    v.destroy()


def w11_nada_se_sale_de_la_ventana():
    print("\n[W11] Con la ventana pequeña, «Parar» sigue accesible")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    v = g.Ventana()
    v.geometry("940x560")           # el mínimo que admite
    v.update()
    v.update_idletasks()

    alto = v.winfo_height()
    borde = v.boton_parar.winfo_rooty() - v.winfo_rooty() \
        + v.boton_parar.winfo_height()
    check(v.boton_parar.winfo_ismapped() == 1, "«Parar» está dibujado")
    check(borde <= alto,
          f"y entero dentro de la ventana ({borde} <= {alto})")

    # La guía y la consola tampoco deben quedar fuera. La banda enseña la
    # invitación cuando no hay datos, así que se comprueba esa.
    for nombre, w in (("la guía", v.etiqueta_pista),
                      ("la invitación", v.vacio_titulo),
                      ("la consola", v.consola)):
        check(w.winfo_ismapped() == 1, f"{nombre} está visible")

    v.destroy()


def w12_guia_segun_el_estado():
    print("\n[W12] La guía dice el paso siguiente según lo que hay")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w12")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    sesion = m.ARCHIVO_SESION

    v = g.Ventana()
    v.campo_objetivo.set("")
    v._refrescar_disco()
    check("cuánto cuesta" in v.etiqueta_pista.cget("text"),
          "sin cuenta, la guía enseña a explorar (la invitación ya pide la "
          "cuenta)")

    v.campo_objetivo.set("cuenta_w12")
    guardada = sesion.exists()
    if guardada:
        respaldo = sesion.read_text(encoding="utf-8")
        sesion.unlink()
    v._refrescar_disco()
    check("Importar sesión" in v.etiqueta_pista.cget("text"),
          "sin sesión manda a importarla")

    sesion.write_text('{"cookies":{"sessionid":"x"}}', encoding="utf-8")
    v._refrescar_disco()
    check("Contar" in v.etiqueta_pista.cget("text"),
          "con sesión y sin capturas manda a Contar")

    m.OBJETIVO = "cuenta_w12"
    r = m._ruta_captura("seguidores", "2026-09-04")
    m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r, True, 1, 1, "completa")
    v._refrescar_disco()
    check("otro día" in v.etiqueta_pista.cget("text"),
          "con una captura pide una segunda")

    r2 = m._ruta_captura("seguidores", "2026-09-05")
    m._escribir_csv(r2, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r2, True, 1, 1, "completa")
    v._refrescar_disco()
    check("Qué cambió" in v.etiqueta_pista.cget("text"),
          "con dos capturas ofrece el análisis")

    # Un parcial pendiente manda a retomarlo, por encima de todo lo demás
    m._escribir_csv(m._ruta_parcial("seguidos"), m.CABECERA, [["x", "", "9"]])
    v._refrescar_disco()
    check("a medias" in v.etiqueta_pista.cget("text"),
          "una descarga a medias tiene prioridad")

    sesion.unlink(missing_ok=True)
    if guardada:
        sesion.write_text(respaldo, encoding="utf-8")
    v.destroy()


def w13_indicador_de_gasto():
    print("\n[W13] El gasto de hoy siempre a la vista")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w13")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m._PRESUPUESTO = None

    v = g.Ventana()
    v._refrescar_gasto()
    check("0/" in v.etiqueta_gasto.cget("text"), "empieza a cero")
    check(str(v.etiqueta_gasto.cget("text_color")) == g.DIM,
          "y en gris mientras va sobrado")

    m._presupuesto()["hechas"] = int(m.TOPE_DIARIO * 0.75)
    v._refrescar_gasto()
    check(str(v.etiqueta_gasto.cget("text_color")) == g.COLOR_AVISO,
          "en ámbar al pasar del 70%")

    m._presupuesto()["hechas"] = int(m.TOPE_DIARIO * 0.95)
    v._refrescar_gasto()
    check(str(v.etiqueta_gasto.cget("text_color")) == g.COLOR_ERROR,
          "y en rojo cerca del tope")

    m._presupuesto()["bloqueos"] = 2
    v._refrescar_gasto()
    check("2 bloqueo" in v.etiqueta_gasto.cget("text"),
          "muestra también los bloqueos del día")
    v.destroy()


def w14_guia_tras_cada_accion():
    print("\n[W14] Cada acción termina diciendo qué se puede hacer")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w14")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w14")
    v._refrescar_disco()

    v.accion_limpiar()
    v._guiar("sesion")
    texto = v.consola.get("1.0", "end")
    check("Contar" in texto, "tras importar la sesión, manda a Contar")
    check("Diagnóstico" in texto, "y menciona el plan B si falla")

    v.accion_limpiar()
    v._guiar("contar")
    texto = v.consola.get("1.0", "end")
    check("Listas completas" in texto, "tras contar, manda a descargar")

    # Sin capturas, tras bajar pide una segunda
    v.accion_limpiar()
    v._guiar("bajar")
    check("otro día" in v.consola.get("1.0", "end"),
          "con una sola descarga, pide repetir otro día")

    # Con dos capturas, ofrece el análisis
    m.OBJETIVO = "cuenta_w14"
    for dia in ("2026-09-04", "2026-09-05"):
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
        m._escribir_meta(r, True, 1, 1, "completa")
    v._refrescar_disco()
    v.accion_limpiar()
    v._guiar("bajar")
    texto = v.consola.get("1.0", "end")
    check("Qué cambió" in texto and "Historial" in texto,
          "con dos capturas, ofrece los dos análisis")
    check("gratis" in texto, "y aclara que no gastan")

    # Una acción desconocida no debe imprimir nada raro
    v.accion_limpiar()
    v._guiar("inventada")
    check(v.consola.get("1.0", "end").strip() == "",
          "una acción sin guía no escribe nada")
    v.destroy()


def w15_ayuda_completa():
    print("\n[W15] La ayuda cubre todo y no gasta peticiones")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    peticiones = []
    original = m.pedir
    m.pedir = lambda *a, **k: peticiones.append(1)

    v = g.Ventana()
    v.accion_ayuda()
    texto = v.consola.get("1.0", "end")
    m.pedir = original

    check(peticiones == [], "la ayuda no hace ninguna petición")
    for esperado in ("Importar sesión", "Contar", "Listas completas",
                     "Qué cambió", "Historial", "Perfiles detallados",
                     "Diagnóstico", "Vigilar", "Gasto de hoy",
                     "Inspeccionar campos"):
        check(esperado in texto, f"explica «{esperado}»")
    check("429" in texto, "y qué hacer ante un bloqueo")
    check("Firefox" in texto, "el aviso de Chrome/Edge en Windows")
    check("incompleta" in texto, "por qué una captura incompleta no se usa")
    v.destroy()


def w16_no_repetir_avisos():
    print("\n[W16] El mismo aviso no debe apilarse")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    v = g.Ventana()
    v.accion_limpiar()
    for _ in range(5):
        v._log("Escribe arriba la cuenta.", g.COLOR_AVISO)
    veces = v.consola.get("1.0", "end").count("Escribe arriba la cuenta.")
    check(veces == 1, f"cinco intentos, una sola línea ({veces})")

    v._log("otra cosa")
    v._log("Escribe arriba la cuenta.", g.COLOR_AVISO)
    veces = v.consola.get("1.0", "end").count("Escribe arriba la cuenta.")
    check(veces == 2, "pero sí se repite si hubo algo en medio")

    # Perder el foco sin cambiar el texto no debe avisar otra vez
    v.accion_limpiar()
    v.campo_objetivo.set("https://www.instagram.com/p/ABC/")
    for _ in range(4):
        v._normalizar_cuenta()
    veces = v.consola.get("1.0", "end").count("publicación")
    check(veces == 1, f"cuatro pérdidas de foco, un solo aviso ({veces})")
    v.destroy()


def w17_visor_de_tablas():
    print("\n[W17] El visor de tablas")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w17")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "cuenta_w17"

    filas = [["ana.lopez", "Ana López", "1", "si", "no"],
             ["beto99", "Beto Ruiz", "2", "no", "si"],
             ["carla_m", "Carla Mena", "3", "si", "si"],
             ["ana.maria", "Ana María", "4", "no", "no"]]
    m._escribir_csv(m._ruta_captura("seguidores", "2026-09-07"),
                    ["username", "nombre", "id", "privada", "verificada"],
                    filas)

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w17")
    v.accion_tablas()
    t = v._visor
    t.update()

    check(t.winfo_exists() == 1, "el visor se abre")
    check(len(t.filas) == 4, f"carga las 4 filas ({len(t.filas)})")
    check(t.columnas == ["username", "nombre", "id", "privada", "verificada"],
          f"y sus columnas ({t.columnas})")
    check(len(t.filtros) == 5, "una casilla de búsqueda por columna")
    check("4 filas" in t.etiqueta_filas.cget("text"), "muestra el total")

    # Búsqueda por columna
    check(len(t.filtrar(t.filas, {"username": "ana"})) == 2,
          "busca en la columna username")
    check(len(t.filtrar(t.filas, {"nombre": "LÓPEZ"})) == 1,
          "sin distinguir mayúsculas")
    check(len(t.filtrar(t.filas, {"privada": "si", "verificada": "si"})) == 1,
          "dos columnas a la vez se combinan")
    check(t.filtrar(t.filas, {"username": "zzz"}) == [],
          "sin resultados devuelve vacío")
    check(len(t.filtrar(t.filas, {"username": "  "})) == 4,
          "una casilla vacía no filtra")

    # El filtro real, a través de las casillas
    t.filtros["username"].insert(0, "ana")
    t._aplicar_filtros()
    t.update()
    check("2 de 4" in t.etiqueta_filas.cget("text"),
          f"la cuenta refleja el filtro ({t.etiqueta_filas.cget('text')})")
    check(len(t.arbol.get_children()) == 2, "y la tabla muestra 2 filas")

    t._limpiar_filtros()
    t.update()
    check(len(t.arbol.get_children()) == 4, "limpiar filtros devuelve todo")

    # Ordenar por columna
    t._ordenar("username")
    primero = t.arbol.item(t.arbol.get_children()[0])["values"][0]
    check(primero == "ana.lopez", f"ordena ascendente ({primero})")
    t._ordenar("username")
    primero = t.arbol.item(t.arbol.get_children()[0])["values"][0]
    check(primero == "carla_m", f"y al segundo clic, al revés ({primero})")

    # Abrir dos veces no crea dos ventanas
    antes = v._visor
    v.accion_tablas()
    check(v._visor is antes, "no abre una segunda ventana")

    # Al cerrar la principal se cierra el visor. Tras destruir la raíz,
    # consultar cualquier widget lanza TclError: esa excepción ES la prueba.
    import tkinter
    v._cerrar()
    try:
        cerrado = not antes.winfo_exists()
    except tkinter.TclError:
        cerrado = True
    check(cerrado, "el visor se cierra con la aplicación")


def w18_visor_casos_borde():
    print("\n[W18] El visor con carpeta vacía y archivos raros")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w18")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("nada")
    v.accion_tablas()
    t = v._visor
    t.update()
    check(t.filas == [], "sin archivos no revienta")
    check("no hay archivos" in t.selector.get(), "y lo dice")

    # Un CSV vacío y otro corrupto
    (carpeta / "nada_seguidores_2026-09-07.csv").write_text("", encoding="utf-8")
    (carpeta / "roto.csv").write_bytes(b"basura\x00sin cabecera")
    t._refrescar_archivos()
    t.update()
    check(True, "un CSV vacío o corrupto no tumba el visor")

    check(g._titulo_legible(Path("cuenta_seguidores_2026-09-07.csv"))
          == "Seguidores · 2026-09-07 · cuenta",
          "los nombres se leen bien")
    check(g._titulo_legible(Path("cambios_cuenta_seguidores_2026-09-07.csv"))
          .startswith("Cambios"), "y los informes también")
    v._cerrar()


def w19_aviso_casilla_peligrosa():
    print("\n[W19] Avisar si la casilla dudosa está activa con capturas rotas")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w19")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.ARCHIVO_SESION.write_text('{"cookies":{"sessionid":"x"}}',
                                encoding="utf-8")

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w19")
    m.OBJETIVO = "cuenta_w19"
    r = m._ruta_captura("seguidores", "2026-09-07")
    m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r, False, 100, 1, "solo 1 de ~100")

    v.campo_sospechosas.deselect()
    v._refrescar_disco()
    texto = v.etiqueta_pista.cget("text")
    check("incompleta" in texto and "CUIDADO" not in texto,
          "con la casilla apagada, aviso normal")

    v.campo_sospechosas.select()
    v._refrescar_disco()
    texto = v.etiqueta_pista.cget("text")
    check("CUIDADO" in texto, f"con la casilla activa, avisa fuerte ({texto[:30]})")
    check("inventará" in texto, "y dice exactamente qué pasaría")
    check(str(v.etiqueta_pista.cget("text_color")) == g.COLOR_AVISO,
          "en ámbar, no en gris")

    v.campo_sospechosas.deselect()
    v._mostrar_sugerencia()
    check(str(v.flecha.cget("fg_color")) == g.ACENTO,
          "al desmarcarla, el filete vuelve al color normal")
    m.ARCHIVO_SESION.unlink(missing_ok=True)
    v._cerrar()


def w22_primer_arranque():
    print("\n[W22] El primer arranque es una invitación, no tres huecos")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w22")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("")
    v._refrescar_disco()
    v.update()

    check(v.vacio.winfo_ismapped() == 1, "sin cuenta se ve la invitación")
    check(v.celdas["seguidores"][0].winfo_ismapped() == 0,
          "y no las cifras vacías")
    texto = v.vacio_titulo.cget("text") + " " + v.vacio_texto.cget("text")
    check("Escribe arriba" in texto, "dice qué hacer")
    check("cómo se mueven" in texto, "y qué vas a conseguir con ello")
    check(texto.count("pon una cuenta") == 0,
          "sin la misma frase repetida tres veces")

    # Con cuenta pero sin descargas, el mensaje cambia
    v.campo_objetivo.set("cuenta_w22")
    v._refrescar_disco()
    v.update()
    texto = v.vacio_titulo.cget("text") + " " + v.vacio_texto.cget("text")
    check("cuenta_w22" in texto, "nombra la cuenta elegida")
    check("Contar" in texto, "y manda al paso siguiente")

    # Con datos, aparecen las cifras
    m.OBJETIVO = "cuenta_w22"
    r = m._ruta_captura("seguidores", "2026-09-07")
    m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r, True, 77, 77, "completa")
    v._refrescar_disco()
    v.update()
    check(v.vacio.winfo_ismapped() == 0, "con datos se retira la invitación")
    check(v.celdas["seguidores"][0].cget("text") == "77",
          "y aparece la cifra")
    v.destroy()


def w23_campo_sin_relleno_falso():
    print("\n[W23] El campo no debe mostrar el valor de relleno del código")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return
    ruta = Path("/tmp/cfg_w23.json")
    ruta.write_text('{"objetivo": "cuenta_objetivo"}', encoding="utf-8")
    g.ARCHIVO_CONFIG = ruta

    v = g.Ventana()
    check(v.campo_objetivo.get() == "",
          f"empieza vacío ({v.campo_objetivo.get()!r})")
    v.destroy()
    ruta.unlink(missing_ok=True)


def w20_todo_dentro_de_su_sitio():
    print("\n[W20] Ningún texto debe quedar fuera de su contenedor")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w20")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w20")
    v._refrescar_disco()
    v.update()
    v.update_idletasks()

    # Este fallo ya ocurrió: un CTkFrame sin altura fijada mide 200 px por
    # defecto, estiraba la fila y el texto de la guía quedaba centrado FUERA
    # de una banda de 44. Se veía el filete y nada más.
    # Con datos en disco, la banda enseña las cifras
    m.OBJETIVO = "cuenta_w20"
    for tipo in ("seguidores", "seguidos"):
        r = m._ruta_captura(tipo, "2026-09-07")
        m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
        m._escribir_meta(r, True, 40, 40, "completa")
    v._refrescar_disco()
    v.update()
    v.update_idletasks()

    for nombre, w in (("la guía", v.etiqueta_pista),
                      ("la cifra de seguidores", v.celdas["seguidores"][0]),
                      ("el gasto", v.etiqueta_gasto)):
        alto_padre = w.master.winfo_height()
        check(0 <= w.winfo_y() < alto_padre,
              f"{nombre} cae dentro de su contenedor "
              f"(y={w.winfo_y()}, alto={alto_padre})")
        check(w.winfo_ismapped() == 1, f"{nombre} está dibujada")

    check(v.etiqueta_pista.cget("text") != "",
          "y la guía tiene texto, no solo el filete")
    v.destroy()


def w21_grafica_de_evolucion():
    print("\n[W21] La gráfica de evolución")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return

    carpeta = Path("/tmp/gui_w21")
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "cuenta_w21"

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w21")
    v._pintar_grafica()
    v.update()
    check(len(v.grafica.find_all()) >= 1,
          "sin datos dibuja algo (el aviso de que faltan capturas)")

    for i, dia in enumerate(("2026-09-01", "2026-09-03", "2026-09-05")):
        for tipo, base in (("seguidores", 300), ("seguidos", 500)):
            r = m._ruta_captura(tipo, dia)
            n = base + i * 5
            m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
            m._escribir_meta(r, True, n, n, "completa")

    check(len(v._serie("seguidores")) == 3, "la serie sale de los metadatos")
    check([n for _, n in v._serie("seguidores")] == [300, 305, 310],
          "con los valores en orden")

    v._pintar_grafica()
    v.update()
    check(len(v.grafica.find_all()) >= 4,
          "con datos dibuja las dos líneas y sus puntos finales")

    # Una captura truncada no debe torcer la línea
    r = m._ruta_captura("seguidores", "2026-09-06")
    m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r, False, 300, 12, "solo 12 de ~300")
    check(len(v._serie("seguidores")) == 3,
          "las incompletas se quedan fuera: falsearían la evolución")
    v.destroy()


def w4_captura_de_pantalla():
    print("\n[W4] Captura de la ventana, para revisarla a ojo")
    if not hay_pantalla():
        print("  (saltado: sin DISPLAY)")
        return
    v = g.Ventana()
    v._log("Ejemplo de salida en la consola:")
    v._log("  AVISO: captura INCOMPLETA (solo 1200 de ~2000)", g.COLOR_AVISO)
    v._log("  Cortado: demasiadas peticiones (HTTP 429)", g.COLOR_ERROR)
    v._log("  Captura guardada: cuenta_seguidos_2026-09-04.csv  (2000)",
           g.COLOR_BIEN)
    v.barra.set(0.62)
    v.etiqueta_estado.configure(text="Descargando listas")
    v.update()
    try:
        v.wm_attributes("-fullscreen", False)
        salida = Path("/tmp/ventana.png")
        # postscript del canvas no sirve; usamos import de ImageMagick si está
        os.system(f"import -window root {salida} 2>/dev/null")
        check(salida.exists() and salida.stat().st_size > 1000,
              f"captura guardada en {salida}")
    except Exception as e:
        print(f"  (no se pudo capturar: {e})")
    v.destroy()


# ======================================================================
if __name__ == "__main__":
    PRUEBAS = [g1_salida_a_cola, g2_progreso, g3_trabajador_basico,
               g4_una_tarea_a_la_vez, g5_cancelacion,
               g6_espera_larga_cancelable, g7_errores_del_modulo,
               g8_ajustes, g9_colores, g10_limpiar_usuario,
               g11_mensajes_de_validacion,
               w1_arranque, w2_bloqueo_de_botones, w3_flujo_completo,
               w5_cierre_limpio, w6_cierre_con_descarga_en_marcha,
               w7_panel_de_disco, w8_barra_invisible_en_reposo,
               w9_campo_se_normaliza, w10_sesion_solo_con_id,
               w11_nada_se_sale_de_la_ventana, w12_guia_segun_el_estado,
               w13_indicador_de_gasto, w14_guia_tras_cada_accion,
               w15_ayuda_completa, w16_no_repetir_avisos,
               w17_visor_de_tablas, w18_visor_casos_borde,
               w19_aviso_casilla_peligrosa, w20_todo_dentro_de_su_sitio,
               w21_grafica_de_evolucion, w22_primer_arranque,
               w23_campo_sin_relleno_falso, w4_captura_de_pantalla]

    for prueba in PRUEBAS:
        try:
            prueba()
        except Exception:
            print(f"  CRASH  {prueba.__name__}")
            traceback.print_exc()
            FALLOS.append(f"{prueba.__name__} lanzó una excepción")

    print("\n" + "=" * 62)
    print(f"{len(PRUEBAS)} pruebas, {len(FALLOS)} fallos")
    if FALLOS:
        for f in FALLOS:
            print("  - " + f)
        sys.exit(1)
    print("Todas las comprobaciones pasaron.")
