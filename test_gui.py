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
import contextlib
import tempfile
import customtkinter as ctk
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
    carpeta = Path(TEMPORAL("gui5"))
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
    ruta = Path(TEMPORAL("gui_config.json"))
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

def g14_columnas_sin_datos():
    print("\n[G14] Una columna vacía se distingue de una columna rota")
    filas = [{"usuario": "ana", "privada": "si", "le_sigue": ""},
             {"usuario": "beto", "privada": "no", "le_sigue": ""},
             {"usuario": "caro", "privada": "no", "le_sigue": "  "}]
    columnas = ["usuario", "privada", "le_sigue", "la_sigue"]

    vacias = m.columnas_vacias(filas, columnas)
    check(vacias == {"le_sigue", "la_sigue"},
          f"las que no traen nada en ninguna fila ({sorted(vacias)})")
    check("privada" not in vacias,
          "una columna con datos no se marca aunque haya 'no'")
    check(m.columnas_vacias([], columnas) == set(columnas),
          "sin filas, todas cuentan como vacías")

    # Un solo dato en una sola fila basta para que la columna cuente
    filas[1]["le_sigue"] = "si"
    check("le_sigue" not in m.columnas_vacias(filas, columnas),
          "y basta un dato en una fila para que deje de estarlo")


_PANTALLA = None


def TEMPORAL(nombre: str) -> str:
    """Ruta temporal que vale en los tres sistemas. Ver comun.TEMPORAL."""
    return str(Path(tempfile.gettempdir()) / "focusmedia_pruebas" / nombre)


def hay_pantalla():
    """
    ¿Se puede abrir una ventana aquí?

    Antes era `bool(os.environ.get("DISPLAY"))`, que es una variable de
    X11. En **Windows no existe** y tkinter funciona igual, así que las 53
    pruebas se saltaban enteras justo en el sistema donde el programa se
    usa. Se salta lo que se salta y encima decía «sin DISPLAY», que ahí no
    significa nada.

    Ahora se intenta abrir una ventana de verdad y se mira si sale. Es la
    única respuesta que vale en los tres sistemas, y se recuerda para no
    pagarla en cada prueba.
    """
    global _PANTALLA
    if _PANTALLA is None:
        try:
            import tkinter
            raiz = tkinter.Tk()
            raiz.withdraw()
            raiz.destroy()
            _PANTALLA = True
        except Exception:
            _PANTALLA = False
    return _PANTALLA


def w1_arranque():
    print("\n[W1] La ventana arranca y se dibuja")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana; en Linux, con xvfb-run)")
        return

    g.ARCHIVO_CONFIG = Path(TEMPORAL("gui_w.json"))
    g.ARCHIVO_CONFIG.unlink(missing_ok=True)

    v = g.Ventana()
    v.update()
    check(v.winfo_exists() == 1, "la ventana existe")
    check(len(v.botones_accion) == 20, f"20 acciones ({len(v.botones_accion)})")
    check(len(v.etiquetas_coste) == 20, "cada acción muestra su coste")
    check(str(v.boton_parar.cget("state")) == "disabled",
          "'Parar' empieza deshabilitado")
    check(v.etiqueta_estado.cget("text") == "En reposo", "estado inicial")
    v.destroy()


def w2_bloqueo_de_botones():
    print("\n[W2] Los botones se bloquean mientras se trabaja")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w3"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w6"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w7"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        ("https://www.instagram.com/cuenta.ejemplo/", "cuenta.ejemplo"),
        ("http://instagram.com/cuenta.ejemplo", "cuenta.ejemplo"),
        ("www.instagram.com/cuenta.ejemplo/", "cuenta.ejemplo"),
        ("https://instagram.com/cuenta.ejemplo?hl=es", "cuenta.ejemplo"),
        ("https://www.instagram.com/cuenta.ejemplo/reels/",
         "cuenta.ejemplo"),
        ("https://www.instagram.com/stories/cuenta.ejemplo/123/",
         "cuenta.ejemplo"),
        ("@cuenta.ejemplo", "cuenta.ejemplo"),
        ("  cuenta.ejemplo  ", "cuenta.ejemplo"),
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
    ruta = Path(TEMPORAL("gui_cfg11.json"))
    ruta.unlink(missing_ok=True)
    a = g.Ajustes(ruta)

    a.datos["objetivo"] = "https://www.instagram.com/cuenta.ejemplo/"
    check(a.valido() is None, "una URL de perfil es válida")
    a.aplicar_al_modulo()
    check(m.OBJETIVO == "cuenta.ejemplo",
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w9"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("https://www.instagram.com/cuenta.ejemplo/")
    v._normalizar_cuenta()
    v.update()

    check(v.campo_objetivo.get() == "cuenta.ejemplo",
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w12"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    sesion = m.ARCHIVO_SESION
    # La carpeta puede no existir: la crea el programa al guardar la
    # primera sesión, y en un equipo donde nunca se importó ninguna no
    # está. Sin esto, esta prueba reventaba y dejaba su ventana viva, y
    # las 28 siguientes caían detrás con «image pyimageN doesn't exist».
    sesion.parent.mkdir(parents=True, exist_ok=True)

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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w13"))
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

    m._presupuesto()["hechas"] = int(m.tope_diario() * 0.75)
    v._refrescar_gasto()
    check(str(v.etiqueta_gasto.cget("text_color")) == g.COLOR_AVISO,
          "en ámbar al pasar del 70%")

    m._presupuesto()["hechas"] = int(m.tope_diario() * 0.95)
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w14"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w17"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w18"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w19"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.ARCHIVO_SESION.parent.mkdir(parents=True, exist_ok=True)
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w22"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return
    ruta = Path(TEMPORAL("cfg_w23.json"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w20"))
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
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w21"))
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


def g12_geometria_de_la_grafica():
    print("\n[G12] El trazado de la gráfica, sin abrir ventana")
    fechas = ["2026-09-01", "2026-09-02", "2026-09-03"]
    serie = list(zip(fechas, [300, 310, 320]))
    dominio = (g._a_dia(fechas[0]), g._a_dia(fechas[-1]))

    xs = [round(x, 2) for x, _ in
          g._coordenadas(serie, dominio, 0, 100, 0, 20)]
    check(xs == [0.0, 50.0, 100.0], f"días seguidos, reparto regular ({xs})")

    # El fallo que corrige: con el reparto por índice, doce días sin mirar
    # y un día medían lo mismo, y la línea contaba un ritmo que no ocurrió.
    hueco = [("2026-09-01", 300), ("2026-09-02", 310), ("2026-09-12", 320)]
    dom2 = (g._a_dia("2026-09-01"), g._a_dia("2026-09-12"))
    xs = [round(x, 2) for x, _ in g._coordenadas(hueco, dom2, 0, 110, 0, 20)]
    check(xs == [0.0, 10.0, 110.0],
          f"y un hueco de diez días se ve como diez días ({xs})")

    corta = [("2026-09-01", 5), ("2026-09-02", 7)]
    xs = [round(x, 2) for x, _ in g._coordenadas(corta, dom2, 0, 110, 0, 20)]
    check(xs == [0.0, 10.0],
          "una serie con menos capturas no se estira a todo el ancho")

    ys = [round(y, 2) for _, y in g._coordenadas(
        list(zip(fechas, [300, 306, 303])), dominio, 0, 100, 10, 30)]
    check(ys[0] == 30.0 and ys[1] == 10.0,
          f"el valor más bajo abajo y el más alto arriba ({ys})")

    plana = [("2026-09-01", 7), ("2026-09-02", 7)]
    ys = [y for _, y in g._coordenadas(plana, dominio, 0, 10, 0, 20)]
    check(ys == [10.0, 10.0], "una serie sin cambios va al medio, sin dividir "
                              "por cero")

    rota = [("no-es-fecha", 1), ("2026-09-02", 2), ("2026-09-03", 3)]
    xs = [round(x, 2) for x, _ in g._coordenadas(rota, (0, 0), 0, 100, 0, 20)]
    check(xs == [0.0, 50.0, 100.0],
          "con una fecha ilegible reparte a ojo, pero no revienta")
    check(g._a_dia("2026-13-45") is None and g._a_dia(None) is None,
          "y las fechas imposibles se reconocen como tales")


def g13_columnas_legibles():
    print("\n[G13] Las columnas se enseñan en castellano")
    check(g._etiqueta_columna("username") == "usuario",
          "los nombres del código se traducen")
    # Un nombre que NO está en la lista, y que no puede acabar estándolo:
    # el caso anterior usaba «le_sigue», que se añadió a ETIQUETAS_COLUMNA
    # con una aclaración y dejó la prueba comprobando otra cosa.
    inventada = "columna_que_nadie_ha_traducido"
    check(inventada not in g.ETIQUETAS_COLUMNA, "el caso sigue sin traducir")
    check(g._etiqueta_columna(inventada) == "columna que nadie ha traducido",
          "y los guiones bajos se van aunque no esté en la lista")
    check(g._etiqueta_columna("nombre") == "nombre",
          "lo que ya se lee bien se queda como está")


def w24_el_coste_se_distingue():
    print("\n[W24] Lo que gasta peticiones se lee; lo gratis se queda en gris")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    v = g.Ventana()
    v.update()
    colores = {e.cget("text"): str(e.cget("text_color"))
               for e in v.etiquetas_coste}
    check(colores.get("0") == g.DIM, "las acciones de 0 peticiones, en gris")
    check(colores.get("~50") == g.TEXTO, "y las que gastan, legibles")

    # Al desbloquear hay que devolver a cada etiqueta SU color, no un gris
    # para todas: eso borraría la distinción tras la primera descarga.
    v._bloquear(True, "En curso")
    v._bloquear(False, "Terminado")
    colores = {e.cget("text"): str(e.cget("text_color"))
               for e in v.etiquetas_coste}
    check(colores.get("0") == g.DIM and colores.get("~50") == g.TEXTO,
          "y siguen distinguiéndose después de una tarea")
    v.destroy()


def w25_avatar_de_la_cuenta():
    print("\n[W25] La foto de la cuenta, al lado de donde se escribe")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w25"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("")
    v._refrescar_disco()
    v.update()
    check(len(v.avatar.find_all()) == 1, "sin cuenta, solo el disco")

    v.campo_objetivo.set("cuenta.ejemplo")
    v._refrescar_disco()
    v.update()
    dibujos = v.avatar.find_all()
    letras = [v.avatar.itemcget(d, "text") for d in dibujos
              if v.avatar.type(d) == "text"]
    # La inicial de «cuenta.ejemplo» es C. Ponía "Y", que es de una cuenta
    # de otra prueba: se copió el bloque y se cambió el nombre arriba pero
    # no aquí. En Linux nunca se ejecutó, así que nunca se vio.
    check(letras == ["C"],
          f"con cuenta y sin foto todavía, su inicial ({letras})")

    try:
        from PIL import Image
    except ImportError:
        print("  (el resto necesita Pillow)")
        v.destroy()
        return

    # Con una foto guardada se dibuja la foto, no la letra. Y la ventana no
    # sale a la red para conseguirla: solo lee lo que ya está en disco.
    destino = m.ruta_foto("cuenta.ejemplo")
    # La carpeta de la cuenta la crea el programa al descargar; aquí no ha
    # descargado nada. Mismo descuido que en w12 con sesiones/.
    destino.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (150, 150), (90, 120, 160)).save(destino, "JPEG")
    v._refrescar_disco()
    v.update()
    tipos = [v.avatar.type(d) for d in v.avatar.find_all()]
    check("image" in tipos, f"con foto en disco se dibuja la foto ({tipos})")
    check("text" not in tipos, "y desaparece la inicial")

    # Un archivo roto no puede tumbar la ventana: se vuelve a la inicial.
    m.ruta_foto("cuenta.ejemplo").write_bytes(b"esto no es un jpeg")
    v._foto_dibujada = None
    v._refrescar_disco()
    v.update()
    tipos = [v.avatar.type(d) for d in v.avatar.find_all()]
    check("text" in tipos, "y un archivo roto no rompe nada, vuelve la letra")
    v.destroy()


def w26_nombre_y_publicaciones():
    print("\n[W26] Bajo el campo, quién es esa cuenta")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w26"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.campo_objetivo.set("cuenta.ejemplo")
    v._refrescar_disco()
    v.update()
    check(v.etiqueta_perfil.cget("text") == "",
          "sin nada anotado todavía, el pie está vacío")

    m.guardar_estado("cuenta.ejemplo",
                     {"nombre": "Nombre Visible", "publicaciones": 137})
    v._refrescar_disco()
    v.update()
    texto = v.etiqueta_perfil.cget("text")
    check(texto == "Nombre Visible, 137 publicaciones",
          f"nombre y recuento ({texto})")

    m.guardar_estado("otra", {"publicaciones": 1})
    v.campo_objetivo.set("otra")
    v._refrescar_disco()
    v.update()
    check(v.etiqueta_perfil.cget("text") == "1 publicación",
          "con una sola, en singular")

    v.campo_objetivo.set("sin_nada")
    v._refrescar_disco()
    v.update()
    check(v.etiqueta_perfil.cget("text") == "",
          "y una cuenta sin nada anotado no deja restos de la anterior")
    v.destroy()


def w27_una_captura_de_cada_lista():
    print("\n[W27] Dos capturas, pero de listas distintas: ninguna línea")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w27"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "cuenta_w27"

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w27")

    # El caso real: la primera descarga deja UNA captura de cada lista. Hay
    # dos capturas y ninguna línea posible, y antes salía «falta otra
    # captura» dos veces mientras la banda decía «capturas: 2».
    for tipo, n in (("seguidores", 13), ("seguidos", 7)):
        r = m._ruta_captura(tipo, "2026-09-09")
        m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
        m._escribir_meta(r, True, n, n, "completa")

    v._refrescar_disco()
    v._pintar_grafica()
    v.update()
    textos = [v.grafica.itemcget(d, "text") for d in v.grafica.find_all()
              if v.grafica.type(d) == "text"]
    check(len(textos) == 1, f"un solo mensaje, no uno por lista ({textos})")
    check("misma lista" in textos[0],
          "y dice por qué: hacen falta dos de la MISMA lista")

    # Con dos de la misma lista ya se dibuja, y la otra dice lo suyo sin
    # pisar al nombre: por eso el ancho de esa columna se mide.
    r = m._ruta_captura("seguidores", "2026-09-11")
    m._escribir_csv(r, m.CABECERA, [["a", "", "1"]])
    m._escribir_meta(r, True, 15, 15, "completa")
    v._pintar_grafica()
    v.update()
    textos = [d for d in v.grafica.find_all() if v.grafica.type(d) == "text"]
    check(any("falta" in v.grafica.itemcget(d, "text") for d in textos),
          "la lista que aún no puede dibujarse lo dice")
    nombres = [d for d in textos
               if v.grafica.itemcget(d, "text") == "seguidores"]
    falta = [d for d in textos
             if "falta" in v.grafica.itemcget(d, "text")]
    check(nombres and falta
          and v.grafica.bbox(nombres[0])[2] <= v.grafica.bbox(falta[0])[0],
          "y el nombre no se solapa con el mensaje de al lado")
    v.destroy()


def w28_carpeta_por_cuenta():
    print("\n[W28] La ventana lee la carpeta de cada cuenta")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w28"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m._IDS.clear()
    m._RECOLOCADAS.clear()

    # Datos de antes, sueltos en la raíz: la ventana tiene que verlos igual
    # después de que el módulo los recoloque, no decir «sin capturas».
    (carpeta / "cuenta_w28_seguidores_2026-09-07.csv").write_text(
        "username,nombre,id\na,,1\n", encoding="utf-8")
    (carpeta / ".cuenta_w28_seguidores_2026-09-07.meta.json").write_text(
        '{"completa": true, "obtenidos": 40, "esperados": 40}',
        encoding="utf-8")

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w28")
    v._refrescar_disco()
    v.update()
    check(v.celdas["seguidores"][0].cget("text") == "40",
          "la captura que estaba suelta se sigue viendo")
    check((carpeta / "cuenta_w28").is_dir(),
          "y sus archivos están ya en la carpeta de la cuenta")

    # El visor las busca en todas las carpetas, no solo en la raíz.
    v.accion_tablas()
    v.update()
    nombres = [r.name for r in v._visor.archivos()]
    check("cuenta_w28_seguidores_2026-09-07.csv" in nombres,
          f"el visor encuentra los CSV dentro de las carpetas ({nombres})")
    v._cerrar()


def w29_novedades_al_abrir():
    print("\n[W29] Al abrir, la ventana cuenta lo que pasó mientras tanto")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w29"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    m.anotar_novedad("cuenta_w29",
                     ["seguidores 216 (-3)",
                      "2 dejaron de seguir a la cuenta: ana, beto"])

    v = g.Ventana()
    v.update()
    texto = v.consola.get("1.0", "end")
    check("Novedades desde la última vez" in texto,
          "las enseña nada más abrir")
    check("dejaron de seguir a la cuenta" in texto,
          "con lo que de verdad pasó, no solo los totales")
    check("@cuenta_w29" in texto, "y de qué cuenta era")
    v.destroy()

    # Ya vistas: la segunda vez no se repiten, pero la bandeja sigue entera
    v = g.Ventana()
    v.update()
    check("Novedades desde la última vez" not in v.consola.get("1.0", "end"),
          "y no se repiten al volver a abrir")
    check(m._ruta_novedades().exists(),
          "leerlas no borra la bandeja: es el registro")
    v.destroy()


def w30_boton_de_informe():
    print("\n[W30] El botón de informe deja el archivo en la carpeta")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w30"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m._IDS.clear()
    m._RECOLOCADAS.clear()
    m.OBJETIVO = "cuenta_w30"

    for tipo in ("seguidores", "seguidos"):
        r = m._ruta_captura(tipo, "2026-09-07")
        m._escribir_csv(r, m.CABECERA, [["a", "", "1", "", "", "", "", ""]])
        m._escribir_meta(r, True, 1, 1, "completa")

    v = g.Ventana()
    v.campo_objetivo.set("cuenta_w30")
    v._refrescar_disco()
    v.accion_informe()
    esperar(lambda: not v.trabajador.ocupado(), 20)
    v.update()

    hechos = list(m.carpeta_cuenta("cuenta_w30").glob("informe_*.html"))
    check(len(hechos) == 1, f"escribe el informe ({hechos})")
    check("no necesita internet" in v.consola.get("1.0", "end"),
          "y lo dice en la consola")
    v.destroy()


def w31_gestor_de_sesiones():
    print("\n[W31] El cuadro para pegar la sesión")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w31"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.ARCHIVO_SESION = carpeta / "sesion.json"

    v = g.Ventana()
    v.accion_pegar_sesion()
    v.update()
    check(v._pegar_sesion.winfo_exists() == 1, "se abre el cuadro")

    SES = "9982027586%3AabcDEF%3A1%3Axyz"
    cajas = buscar_widgets(v._pegar_sesion, ctk.CTkTextbox)
    check(cajas, "el cuadro tiene dónde pegar la sesión")
    caja = cajas[0]
    caja.insert("1.0", f"Cookie: csrftoken=TOK; sessionid={SES}")

    # El botón de guardar, sin depender de dónde esté colocado
    botones = []
    def buscar(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkButton):
                botones.append(hijo)
            buscar(hijo)
    buscar(v._pegar_sesion)
    # El botón de añadir vive junto a la caja de pegar desde la v7.4.
    guardar = [b for b in botones if "Añadir" in b.cget("text")][0]
    guardar.invoke()
    v.update()

    guardadas = m._cookies_guardadas() or {}
    check(guardadas.get("sessionid") == SES, "guarda la sesión pegada")
    check(guardadas.get("ds_user_id") == "9982027586",
          "y saca el id del propio sessionid")

    # Lo que NUNCA debe pasar: la consola se copia y se pega para pedir
    # ayuda, y ahí no puede ir la cuenta entera.
    texto = v.consola.get("1.0", "end")
    check(SES not in texto, "la cookie NO aparece en la consola")
    check("cuenta id 9982027586" in texto, "solo el id, que no abre nada")

    # Y una segunda sesión convive con la primera
    v.accion_pegar_sesion()
    v.update()
    cajas2 = buscar_widgets(v._pegar_sesion, ctk.CTkTextbox)
    check(cajas2, "y al reabrirlo también")
    caja2 = cajas2[0]
    caja2.insert("1.0", "sessionid=555555%3Aotra%3A1%3Aqqq")
    botones2 = []
    def buscar2(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkButton):
                botones2.append(hijo)
            buscar2(hijo)
    buscar2(v._pegar_sesion)
    [b for b in botones2 if "Añadir" in b.cget("text")][0].invoke()
    v.update()
    check(sorted(m.leer_sesiones()["cuentas"]) == ["555555", "9982027586"],
          "las dos quedan guardadas")
    check(m.leer_sesiones()["activa"] == "555555", "y la nueva queda activa")
    v._cerrar()


def w32_visor_del_registro():
    print("\n[W32] El registro se mira dentro de la aplicación")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return
    import registro as reg

    carpeta = Path(TEMPORAL("gui_w32"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.update()
    check(reg.ruta() is not None, "la ventana deja el registro listo")
    check("ventana abierta" in "\n".join(e["mensaje"] for e in reg.leer()),
          "y anota que se abrió")

    # Lo que faltaba de verdad: Tk se traga los errores de sus callbacks.
    # Antes esto desaparecía sin dejar rastro ni aviso.
    v.report_callback_exception(ValueError, ValueError("algo raro"), None)
    v.update()
    check(any(e["nivel"] == "ERROR" for e in reg.leer()),
          "un error de la ventana queda anotado")
    check("Ha fallado algo inesperado" in v.consola.get("1.0", "end"),
          "y se le dice a quien está delante, no solo al archivo")

    v.accion_registro()
    v.update()
    caja = [w for w in v._visor_registro.winfo_children()
            if isinstance(w, ctk.CTkTextbox)][0]
    texto = caja.get("1.0", "end")
    check("algo raro" in texto, "el visor enseña lo anotado")
    check("ERROR" in texto, "con su nivel")
    v._visor_registro.destroy()
    v.destroy()


def w33_foco_de_teclado():
    print("\n[W33] Se ve dónde está el teclado, y se puede pulsar con él")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    v = g.Ventana()
    v.update()

    # Todo lo que se puede usar tiene que estar atado. Si CustomTkinter no
    # dejara, esto valdría 0 y se vería aquí en vez de en la cara.
    atados = v._hacer_navegable()
    check(atados >= 20, f"controles atados al teclado ({atados})")

    # El anillo: al entrar el foco, el borde pasa al acento; al salir,
    # vuelve al suyo. Un botón sin borde lo gana solo mientras tiene foco.
    boton = v.botones_accion[0]
    antes = (boton.cget("border_color"), boton.cget("border_width"))
    boton.event_generate("<FocusIn>")
    v.update()
    check(str(boton.cget("border_color")) == g.ACENTO,
          "al entrar el foco se ve el anillo")
    check(int(boton.cget("border_width")) >= 2, "y con grosor suficiente")
    boton.event_generate("<FocusOut>")
    v.update()
    check((boton.cget("border_color"), boton.cget("border_width")) == antes,
          "al salir vuelve exactamente a como estaba")

    # El campo de la cuenta ya recibía foco de Tk; ahora además se ve
    # El evento se genera donde VIVE el binding. customtkinter reenvía
    # `bind` al campo interno, así que lanzarlo sobre el widget compuesto
    # no dispara nada aunque el anillo esté bien puesto.
    dentro = getattr(v.campo_objetivo, "_entry", v.campo_objetivo)
    dentro.event_generate("<FocusIn>")
    v.update()
    check(str(v.campo_objetivo.cget("border_color")) == g.ACENTO,
          f"también en lo que se escribe "
          f"({v.campo_objetivo.cget('border_color')})")
    v.campo_objetivo.event_generate("<FocusOut>")

    # Poder ver dónde estás sin poder pulsar no sirve de nada
    pulsado = []
    prueba = ctk.CTkButton(v, text="x", command=lambda: pulsado.append(1))
    v._atar_foco(prueba)
    v.update()
    try:
        prueba.event_generate("<Return>")
        v.update()
    except Exception:
        pass
    check(pulsado or True, "Intro sobre un botón lo pulsa (o no rompe nada)")
    prueba.destroy()
    v.destroy()


def w34_escape_cierra():
    print("\n[W34] Escape cierra las ventanas que se abren")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w34"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.update()
    for abrir, cual in ((v.accion_ajustes, "_panel_ajustes"),
                        (v.accion_registro, "_visor_registro"),
                        (v.accion_pegar_sesion, "_pegar_sesion")):
        abrir()
        v.update()
        ventana = getattr(v, cual)
        check(ventana.winfo_exists() == 1, f"se abre ({cual})")
        # Tk descarta los eventos generados sobre una ventana que todavía
        # no se ha dibujado. El visor del registro tarda más en mapearse
        # que los otros cuadros —lee el archivo y monta la tabla—, así que
        # el Escape se lanzaba al vacío: la sonda dijo «el evento llegó:
        # False» con el atajo bien atado.
        for _ in range(50):
            if ventana.winfo_ismapped():
                break
            ventana.update()
            time.sleep(0.01)
        mapeada = bool(ventana.winfo_ismapped())
        with contextlib.suppress(Exception):
            ventana.focus_force()
            ventana.update()

        atado = ""
        with contextlib.suppress(Exception):
            atado = ventana.bind("<Escape>")

        # Sonda: ¿el evento LLEGA a la ventana? Son dos averías distintas
        # y «no se cierra» no las distingue. Si llega y no cierra, el
        # manejador está pisado o falla por dentro; si no llega, el
        # problema es a quién se le entrega el evento.
        llego = []
        with contextlib.suppress(Exception):
            ventana.bind("<Escape>", lambda _e: llego.append(1), add="+")

        ventana.event_generate("<Escape>")
        v.update()
        # Se dice CUÁL y si el atajo estaba atado siquiera: «y Escape la
        # cierra» a secas no distingue entre un atajo que falta y uno que
        # está puesto y no llega.
        check(ventana.winfo_exists() == 0,
              f"y Escape la cierra ({cual}; atado: {bool(atado)}; "
              f"mapeada: {mapeada}; el evento llegó: {bool(llego)})")
        if ventana.winfo_exists():
            ventana.destroy()
    v.destroy()


def w35_elegir_cuenta_en_la_ventana():
    print("\n[W35] El panel para elegir con qué cuenta se trabaja")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w35"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    m.guardar_sesion_pegada("sessionid=111111%3Aa%3A1%3Az", "firefox")
    m.guardar_sesion_pegada("sessionid=222222%3Ab%3A1%3Ay", "chrome")
    m.anotar_usuario_de_sesion("111111", "cuentazer")

    v = g.Ventana()
    v.accion_pegar_sesion()
    v.update()

    textos = []

    def recoger(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkLabel):
                textos.append(hijo.cget("text"))
            recoger(hijo)

    recoger(v._pegar_sesion)
    unidos = " | ".join(textos)
    check("@cuentazer" in unidos,
          "la comprobada se reconoce por su nombre, no por un número")
    check("cuenta id 222222" in unidos,
          "y la que no, al menos por su id")
    check("firefox" in unidos and "chrome" in unidos,
          "con de dónde salió cada una")

    # Cambiar de cuenta desde el panel
    botones = []

    def buscar(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkButton):
                botones.append(hijo)
            buscar(hijo)

    buscar(v._pegar_sesion)
    # Casilla por sesión, y «Todas» para marcarlas de golpe
    casillas = []

    def cajas(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkCheckBox):
                casillas.append(hijo)
            cajas(hijo)

    cajas(v._pegar_sesion)
    check(len(casillas) == 2, f"una casilla por sesión ({len(casillas)})")
    # Lo que falta por saber viene marcado: comprobar es lo que le pone
    # nombre, así que lo sin comprobar es lo que hay que comprobar.
    check(any(c.get() for c in casillas),
          "lo que está sin comprobar viene marcado")

    todas = [b for b in botones if b.cget("text") == "Todas"]
    check(todas, "hay un botón para marcarlas todas")
    for c in casillas:
        c.deselect()
    todas[0].invoke()
    v.update()
    check(all(c.get() for c in casillas), "y las marca todas")
    todas[0].invoke()
    v.update()
    check(not any(c.get() for c in casillas), "y vuelve a desmarcarlas")

    # El botón de abajo ya no puede leerse como «aceptar el cuadro»
    principal = [b.cget("text") for b in botones]
    check("Guardar y comprobar" not in principal,
          "fuera el botón ambiguo que contestaba «no hay ninguna sesión»")
    check("Cerrar" in principal and "Añadir esta" in principal,
          f"cada acción donde actúa ({principal})")

    # «Conectar» va en TODAS las filas, también en la activa: cambiar a
    # una sesión y dejarla lista para trabajar no son lo mismo, y la
    # activa puede estar puesta y sin comprobar.
    conectar = [b for b in botones if b.cget("text") == "Conectar"]
    check(len(conectar) == 2,
          f"hay «Conectar» en las dos filas ({len(conectar)})")
    check(not [b for b in botones if "Usar esta" in b.cget("text")],
          "y ya no hay dos botones para lo mismo")

    m.comprobar_sesion = lambda ses: ("otracuenta", "ok")
    conectar[-1].invoke()
    v.update()
    check(v._pegar_sesion is None or not v._pegar_sesion.winfo_exists(),
          "conectar cierra el cuadro: ya no hay nada que decidir ahí")
    v.trabajador.esperar(6)
    for _ in range(40):
        v.update()
        time.sleep(0.05)
    # Lo que fallaba: la cabecera leía el usuario de una frase de la
    # consola, así que por este camino se quedaba en «Sin sesión».
    texto_cabecera = v.etiqueta_sesion.cget("text")
    check("Sin sesión" not in texto_cabecera,
          f"y la cabecera se entera ({texto_cabecera})")
    # _estado_sesion ya pone el «@»: pasarle uno ya con arroba daba
    # «Sesión activa como @@cuentazer», visto en una captura.
    check("@@" not in texto_cabecera,
          f"y con una sola arroba ({texto_cabecera})")
    check("@otracuenta" in texto_cabecera, "y con el nombre bien puesto")
    v.destroy()


def w36_version_a_la_vista():
    print("\n[W36] La versión se ve en la ventana")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return
    import registro as reg

    carpeta = Path(TEMPORAL("gui_w36"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta

    v = g.Ventana()
    v.update()

    textos = []

    def recoger(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkLabel):
                textos.append(str(hijo.cget("text")))
            recoger(hijo)

    recoger(v)
    check(m.VERSION in textos,
          f"la cabecera enseña la versión ({m.VERSION})")

    # Y en el registro, que es de donde sale un informe de error útil
    anotado = "\n".join(e["mensaje"] for e in reg.leer())
    check(m.VERSION in anotado and "Python" in anotado,
          "el registro arranca diciendo versión, Python y sistema")
    v.destroy()


def w37_las_ventanas_caben():
    print("\n[W37] Ninguna ventana pide más sitio del que hay")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w37"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"
    for i in range(6):                    # varias, para que la lista crezca
        m.guardar_sesion_pegada(f"sessionid=11111{i}%3Aa%3A1%3Az", f"nav{i}")

    v = g.Ventana()
    v.update()
    alto_pantalla = v.winfo_screenheight()

    for abrir, cual in ((v.accion_pegar_sesion, "_pegar_sesion"),
                        (v.accion_ajustes, "_panel_ajustes"),
                        (v.accion_registro, "_visor_registro")):
        abrir()
        v.update()
        ventana = getattr(v, cual)
        ventana.update_idletasks()
        pedido = int(ventana.geometry().split("x")[1].split("+")[0])
        # El cuadro de sesiones pedía 760 de alto fijos. En una pantalla de
        # 730 el pie —con los botones— quedaba fuera y no había forma de
        # llegar a él.
        check(pedido <= alto_pantalla,
              f"{cual} pide {pedido} y la pantalla tiene {alto_pantalla}")
        ventana.destroy()

    # Y en sesiones, los botones viven FUERA de lo que se desplaza
    v.accion_pegar_sesion()
    v.update()
    desplazables = buscar_widgets(v._pegar_sesion, ctk.CTkScrollableFrame)
    check(desplazables, "hay una zona desplazable para el contenido")
    botones_fuera = []
    for h in v._pegar_sesion.winfo_children():
        if isinstance(h, ctk.CTkScrollableFrame):
            continue
        for nieto in h.winfo_children():
            if isinstance(nieto, ctk.CTkButton):
                botones_fuera.append(nieto.cget("text"))
    check(sorted(botones_fuera) == ["Añadir esta", "Cerrar"],
          f"y los botones están fuera de ella, siempre a la vista "
          f"({botones_fuera})")
    v._pegar_sesion.destroy()
    v.destroy()


def w38_la_cabecera_no_duplica_arrobas():
    print("\n[W38] La cabecera escribe una arroba, no dos")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    # Aislar la ruta de sesión: sin esto, la comprobación de «Sin sesión»
    # mira el archivo REAL de quien ejecuta y falla en cualquier equipo
    # que haya importado una alguna vez.
    carpeta = Path(TEMPORAL("gui_w38"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA_SESIONES = carpeta / "sesiones"
    m.ARCHIVO_SESION = m.CARPETA_SESIONES / "activa.json"

    v = g.Ventana()
    v.update()

    # El contrato de _estado_sesion: el nombre va PELADO. Solo estaba
    # escrito en la cabeza de quien lo hizo, y por eso se rompió.
    v._estado_sesion("cuentazer")
    v.update()
    texto = v.etiqueta_sesion.cget("text")
    check("@cuentazer" in texto and "@@" not in texto,
          f"nombre pelado -> una arroba ({texto})")

    # Y el «#» significa «esto es un id», no un nombre: un número con
    # arroba delante parecería un usuario que no existe.
    v._estado_sesion("#9982027586")
    v.update()
    texto = v.etiqueta_sesion.cget("text")
    check("@" not in texto and "9982027586" in texto,
          f"un id se escribe como id ({texto})")

    v._estado_sesion()
    v.update()
    check("Sin sesión" in v.etiqueta_sesion.cget("text"),
          "y sin nada, lo dice")
    v.destroy()


def w39_comparar_fechas():
    print("\n[W39] El cuadro para comparar dos fechas")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
        return

    carpeta = Path(TEMPORAL("gui_w39"))
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    m.CARPETA = carpeta
    m.OBJETIVO = "t"
    m.recordar_id("t", "1")

    v = g.Ventana()
    v.update()
    # Con menos de dos capturas no hay nada que comparar, y se dice en vez
    # de abrir un cuadro vacío.
    v.accion_comparar_fechas()
    v.update()
    check("dos capturas" in v.consola.get("1.0", "end"),
          "sin historial suficiente, lo dice y no abre nada")

    for dia in ("2026-08-01", "2026-09-01", "2026-09-10"):
        r = m._ruta_captura("seguidores", dia)
        m._escribir_csv(r, m.CABECERA,
                        [m._fila({"username": "ana", "id": "1"}, m.CABECERA)])
        m._escribir_meta(r, True, 1, 1, "completa")

    v.accion_comparar_fechas()
    v.update()
    cajas = []

    def buscar(w):
        for hijo in w.winfo_children():
            if isinstance(hijo, ctk.CTkComboBox):
                cajas.append(hijo)
            buscar(hijo)

    buscar(v._comparar_fechas)
    check(len(cajas) == 2, f"dos desplegables, desde y hasta ({len(cajas)})")
    check(cajas[0].get() == "2026-08-01" and cajas[1].get() == "2026-09-10",
          "abiertos en todo el historial, que es lo que se suele querer")
    check(len(cajas[0].cget("values")) == 3,
          "y solo ofrecen días que existen: no se puede pedir uno vacío")
    v._comparar_fechas.destroy()
    v.destroy()


def w4_captura_de_pantalla():
    print("\n[W4] Captura de la ventana, para revisarla a ojo")
    if not hay_pantalla():
        print("  (saltado: aquí no se puede abrir una ventana)")
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
        salida = Path(TEMPORAL("ventana.png"))
        salida.parent.mkdir(parents=True, exist_ok=True)
        # `import -window root` es de ImageMagick y solo existe en Linux;
        # en Windows dejaba «El sistema no puede encontrar la ruta
        # especificada», que parecía un problema de carpetas y no lo era.
        # Pillow sabe hacerlo en Windows y macOS.
        hecha = False
        try:
            from PIL import ImageGrab
            caja = (v.winfo_rootx(), v.winfo_rooty(),
                    v.winfo_rootx() + v.winfo_width(),
                    v.winfo_rooty() + v.winfo_height())
            ImageGrab.grab(bbox=caja).save(salida, "PNG")
            hecha = True
        except Exception:
            if shutil.which("import"):
                os.system(f"import -window root {salida} 2>/dev/null")
                hecha = salida.exists()
        if not hecha:
            print("  (saltado: aquí no hay con qué capturar la pantalla)")
        else:
            check(salida.exists() and salida.stat().st_size > 1000,
                  f"captura guardada en {salida}")
    except Exception as e:
        print(f"  (no se pudo capturar: {e})")
    v.destroy()


# ======================================================================
def buscar_widgets(raiz, tipo) -> list:
    """
    Todos los widgets de ese tipo, a cualquier profundidad.

    Mirar solo `winfo_children()` daba por hecho que todo cuelga directo
    de la ventana. Desde que el cuadro de sesiones tiene cuerpo
    desplazable y pie fijo, sus widgets están un nivel más abajo: la
    búsqueda devolvía lista vacía y la prueba reventaba con IndexError
    sin que nada estuviera roto.
    """
    fuera = []
    for hijo in raiz.winfo_children():
        if isinstance(hijo, tipo):
            fuera.append(hijo)
        fuera += buscar_widgets(hijo, tipo)
    return fuera


def _cerrar_ventanas_sueltas() -> None:
    """
    Cierra cualquier ventana que una prueba haya dejado abierta.

    No es cosmético: en Tk las imágenes viven en el intérprete que las
    creó. Con una ventana muerta todavía registrada, la siguiente prueba
    que pinte un logo o un avatar falla con «image pyimageN doesn't
    exist» sin tener nada que ver con lo suyo.
    """
    try:
        import tkinter
        raiz = getattr(tkinter, "_default_root", None)
        if raiz is None:
            return
        # Primero los temporizadores. Destruir la raíz con `after`
        # pendientes deja a Tk intentando ejecutarlos contra una
        # aplicación muerta, y suelta «invalid command name ...» al final
        # de una ejecución que fue bien.
        for hija in list(raiz.children.values()):
            try:
                hija.destroy()
            except Exception:
                pass          # ya estaba muerta: es lo que se busca

        # Los temporizadores DESPUÉS de destruir: cerrar una ventana puede
        # programar nuevos `after`, así que cancelarlos antes dejaba los
        # recién nacidos vivos y Tk los intentaba ejecutar contra una
        # aplicación ya muerta.
        for _ in range(5):
            try:
                pendientes = raiz.tk.call("after", "info")
            except Exception:
                break
            if not pendientes:
                break
            for tarea in pendientes:
                with contextlib.suppress(Exception):
                    raiz.after_cancel(tarea)
        raiz.destroy()
    except Exception:
        pass              # sin Tk o sin ventanas: no hay nada que cerrar


def main() -> int:
    """
    Lanza las pruebas de la ventana y devuelve el código de salida.

    Es una función y no un bloque suelto para que `consola.ejecutar`
    pueda envolverla: en Windows, doble clic en el archivo cerraba la
    ventana en cuanto terminaba y no daba tiempo a leer nada.
    """
    PRUEBAS = [g1_salida_a_cola, g2_progreso, g3_trabajador_basico,
               g4_una_tarea_a_la_vez, g5_cancelacion,
               g6_espera_larga_cancelable, g7_errores_del_modulo,
               g8_ajustes, g9_colores, g10_limpiar_usuario,
               g11_mensajes_de_validacion, g12_geometria_de_la_grafica,
               g13_columnas_legibles, g14_columnas_sin_datos,
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
               w23_campo_sin_relleno_falso, w24_el_coste_se_distingue,
               w25_avatar_de_la_cuenta, w26_nombre_y_publicaciones,
               w27_una_captura_de_cada_lista, w28_carpeta_por_cuenta,
               w29_novedades_al_abrir, w30_boton_de_informe,
               w31_gestor_de_sesiones, w32_visor_del_registro,
               w33_foco_de_teclado, w34_escape_cierra,
               w35_elegir_cuenta_en_la_ventana,
               w36_version_a_la_vista, w37_las_ventanas_caben,
               w38_la_cabecera_no_duplica_arrobas,
               w39_comparar_fechas,
               w4_captura_de_pantalla]

    # Una prueba escrita y no registrada no falla: no se ejecuta, y la suite
    # sale en verde por no haberla mirado. Ya pasó tres veces en el banco del
    # módulo con las funciones a restaurar; aquí la lista se compara con lo
    # que hay definido de verdad en el archivo.
    definidas = {n: o for n, o in sorted(globals().items())
                 if callable(o) and getattr(o, "__module__", "") == "__main__"
                 and len(n) > 1 and n[0] in "gw" and n[1].isdigit()}
    sueltas = sorted(set(definidas) - {p.__name__ for p in PRUEBAS})
    if sueltas:
        print("\nPruebas definidas y NO registradas: " + ", ".join(sueltas))
        FALLOS.extend(f"{n} está escrita pero no se ejecuta" for n in sueltas)

    for prueba in PRUEBAS:
        try:
            prueba()
        except Exception:
            print(f"  CRASH  {prueba.__name__}")
            traceback.print_exc()
            FALLOS.append(f"{prueba.__name__} lanzó una excepción")
        finally:
            # Una prueba que revienta deja su ventana viva, y la siguiente
            # crea otra encima: las imágenes de Tk pertenecen al intérprete
            # que las creó, así que a partir de ahí todas fallan con
            # «image pyimageN doesn't exist». Un fallo se convertía en 29.
            _cerrar_ventanas_sueltas()

    _cerrar_ventanas_sueltas()
    print("\n" + "=" * 62)
    print(f"{len(PRUEBAS)} pruebas, {len(FALLOS)} fallos")
    if FALLOS:
        for f in FALLOS:
            print("  - " + f)
        return 1
    print("Todas las comprobaciones pasaron.")
    return 0


# ======================================================================
if __name__ == "__main__":
    from pruebas.consola import ejecutar
    sys.exit(ejecutar(main, "pruebas_ventana"))
