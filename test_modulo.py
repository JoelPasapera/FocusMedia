"""
Banco de pruebas de instagram_listas.py v2.

Simula la API de Instagram para verificar el módulo sin tocar la red.
Los bloques [R1]..[R9] son regresiones: cada uno cubre uno de los nueve
fallos detectados en la v1, y debe fallar si alguien los reintroduce.

    python test_modulo.py
"""

import csv
import io
import json
import re
import traceback
import contextlib
import os
import shutil
import time
import tempfile
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

import instagram_listas as m

# Los tests sustituyen funciones del módulo por dobles. Guardamos las reales
# ANTES de que ocurra y las restauramos entre pruebas: si no, una prueba
# hereda los dobles de la anterior y mide algo que no es lo que cree.
# Se capturan TODAS las funciones del módulo, no una lista escrita a mano:
# esa lista se quedó corta dos veces y una prueba heredó el doble de otra,
# midiendo algo distinto de lo que creía.
FUNCIONES_REALES = {n: o for n, o in vars(m).items()
                    if callable(o)
                    and getattr(o, "__module__", "") == m.__name__}
PEDIR_REAL = m.pedir


def restaurar_modulo():
    """Deja el módulo como estaba: sin dobles, sin bloqueos, sin gasto."""
    for nombre, funcion in FUNCIONES_REALES.items():
        setattr(m, nombre, funcion)
    # Carpeta nueva por prueba: el presupuesto y las vías aprendidas viven
    # en disco, y arrastrarlos hacía que una prueba midiera otra cosa.
    m.CARPETA = Path(tempfile.mkdtemp(prefix="aislado_"))
    m._PRESUPUESTO = None
    m._BLOQUEOS.clear()
    m._SESION_CACHE = None
    m._SESION_HASTA = 0.0
    m._VERIFICACION_OK = None
    m.CANCELAR = None
    m._IDS.clear()
    m._RECOLOCADAS.clear()

FALLOS = []


def check(cond, msg):
    print(("  OK    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLOS.append(msg)


def prep(ruta):
    p = Path(ruta)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True)
    m.CARPETA = p
    m.OBJETIVO = "t"
    # Cada cuenta tiene ya su carpeta dentro de salida/, y varias pruebas
    # escriben sus archivos de partida a mano. El código de verdad la crea
    # antes de escribir; aquí se crea al preparar.
    m.carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    m.PAUSA_MIN = m.PAUSA_MAX = 0
    m.DESCANSO_SEG = 0
    m.ESPERA_INICIAL = m.ESPERA_MAXIMA = 0
    m.MAX_REINTENTOS = 6
    return p


def leer(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def captura(tipo, dia, filas, completa=True):
    """Escribe una captura de prueba con sus metadatos."""
    ruta = m._ruta_captura(tipo, dia)
    # Formato antiguo de 3 columnas: prueba de paso la compatibilidad.
    m._escribir_csv(ruta, ["username", "nombre", "id"],
                    [[u, n, i] for u, n, i in filas])
    m._escribir_meta(ruta, completa, len(filas), len(filas),
                     "completa" if completa else "truncada")
    return ruta


# ----------------------------------------------------------------------
class FakeIG:
    """Instagram simulado: pagina de 50 en 50 y puede cortar cuando quieras."""

    def __init__(self, n_seguidores, n_seguidos, cortar_en=None):
        self.datos = {
            "followers": [self._u(i, "f") for i in range(n_seguidores)],
            "following": [self._u(i, "g") for i in range(n_seguidos)],
        }
        self.cortar_en = cortar_en or {}
        self.peticiones = 0

    @staticmethod
    def _u(i, p):
        return {"pk": f"{p}{i}", "username": f"{p}user{i}",
                "full_name": f"Nombre {p}{i}",
                "is_private": i % 2 == 0,
                "is_verified": i % 10 == 0,
                "friendship_status": {"following": True,
                                      "followed_by": i % 3 == 0}}

    def pedir(self, s, ruta, params=None, referer=None):
        self.peticiones += 1
        endpoint = "followers" if "followers" in ruta else "following"
        lista = self.datos[endpoint]

        params = params or {}
        inicio = int(params.get("max_id", 0))
        count = params.get("count", 50)

        limite = self.cortar_en.get(endpoint)
        if limite is not None and inicio >= limite:
            raise m.Bloqueado("simulado: demasiadas peticiones")

        trozo = lista[inicio:inicio + count]
        fin = inicio + len(trozo)
        return {"users": trozo,
                "next_max_id": str(fin) if fin < len(lista) else None}


PERFIL = {"id": "1", "username": "t", "nombre": "", "seguidores": 0,
          "seguidos": 0, "privada": False, "la_sigo": True}


def perfil(seguidores=0, seguidos=0):
    return dict(PERFIL, seguidores=seguidores, seguidos=seguidos)


# ======================================================================
# PRUEBAS FUNCIONALES
# ======================================================================

def test_descarga_completa():
    print("\n[1] Descarga completa: 500 seguidores / 2000 seguidos")
    prep("/tmp/t1")
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
    prep("/tmp/t2")
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
    prep("/tmp/t3")

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
    prep("/tmp/t4")
    m.pedir = FakeIG(0, 0).pedir
    m.descargar(None, perfil(0, 0), "seguidores")
    check(m._ruta_captura("seguidores").exists(), "cuenta con 0 seguidores")
    check(len(leer(m._ruta_captura("seguidores"))) == 0, "captura vacía válida")
    check(m.comparar("seguidos") is None, "sin capturas devuelve None")
    check(m._capturas("seguidores") == [m._ruta_captura("seguidores")],
          "_capturas ignora el parcial")

    prep("/tmp/t4b")
    m.pedir = FakeIG(0, 7).pedir
    m.descargar(None, perfil(0, 7), "seguidos")
    check(len(leer(m._ruta_captura("seguidos"))) == 7,
          "lista más corta que una página")

    prep("/tmp/t4c")
    r = captura("seguidores", "2026-09-01",
                [('co,ma', 'Con "comillas" y, coma', "9")])
    f = leer(r)[0]
    check(f["username"] == "co,ma", "comas dentro del campo")
    check(f["nombre"] == 'Con "comillas" y, coma', "comillas escapadas")


# ======================================================================
# REGRESIONES DE LOS NUEVE FALLOS
# ======================================================================

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
    check(e == "muerta", f"401 -> muerta (dio '{e}')")

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
    prep("/tmp/r2")

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

    prep("/tmp/r2b")

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
    prep("/tmp/r3")
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


def r4_cambio_de_username():
    print("\n[R4] Un cambio de username es la misma persona, no baja + alta")
    prep("/tmp/r4")
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
    prep("/tmp/r4b")
    for dia, us in (("2026-08-01", ["ana", "beto"]),
                    ("2026-09-01", ["ana", "beto_nuevo"])):
        m._escribir_csv(m._ruta_captura("seguidores", dia), m.CABECERA,
                        [[u, "", ""] for u in us])
    m.comparar("seguidores")
    r = leer(m.carpeta_cuenta()
             / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
    check(sorted(x["cambio"] for x in r) == ["entro", "salio"],
          "sin ids degrada a comparación por nombre, sin reventar")


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


def r6_sin_codigo_muerto():
    print("\n[R6] _una_pasada informa del motivo real, sin ramas muertas")
    import inspect
    src = inspect.getsource(m._una_pasada)
    check("terminado" not in src, "desapareció la variable 'terminado'")
    check('motivo = "truncada"' in src, "distingue el caso truncado")

    src_d = inspect.getsource(m.descargar)
    check("if terminado" not in src_d, "descargar() ya no tiene la rama muerta")

    prep("/tmp/r6")

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


def r8_bom_para_excel():
    print("\n[R8] Las capturas deben llevar BOM para Excel")
    prep("/tmp/r8")
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


def r9_relaciones_avisa_fechas():
    print("\n[R9] relaciones() debe avisar si cruza fechas distintas")
    prep("/tmp/r9")
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
    check(por.get("no_devuelve") == {"gato"}, "no_devuelve correcto")
    check(por.get("no_correspondido") == {"beto"}, "no_correspondido correcto")

    print("  --- misma fecha: no debe avisar ---")
    prep("/tmp/r9b")
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-02", [("ana", "", "1")])
    captura("seguidos", "2026-09-01", [("ana", "", "1")])
    captura("seguidos", "2026-09-02", [("ana", "", "1")])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.relaciones(m.comparar("seguidores"), m.comparar("seguidos"))
    check("fechas distintas" not in buf.getvalue(),
          "con la misma fecha no avisa")


def v1_decidir_disparadores():
    print("\n[V1] decidir(): los tres disparadores")
    prep("/tmp/v1")

    p = perfil(500, 2000)
    bajar, motivos = m.decidir(p)
    check(bajar == {"seguidores", "seguidos"},
          f"sin capturas -> baja ambas ({bajar})")

    # Con capturas de hoy y el mismo conteo: no hace falta nada
    prep("/tmp/v1b")
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
    prep("/tmp/v2")
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
    prep("/tmp/v3")
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
    prep("/tmp/v4")
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
    prep("/tmp/v5")

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
    prep("/tmp/v6")
    ig = FakeIG(500, 2000)
    m.pedir = ig.pedir
    m.crear_sesion = lambda forzar=False: None
    m.perfil = lambda s, u: perfil(500, 2000)

    m.cmd_contar(None)
    check(ig.peticiones == 0, "contar no toca el endpoint de listas")
    check(m._ultimo_conteo()["seguidores"] == 500, "pero sí anota el total")


def e1_campos_extra():
    print("\n[E1] Los campos extra se guardan sin peticiones adicionales")
    prep("/tmp/e1")
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
    prep("/tmp/e2")
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
    prep("/tmp/e3")

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
    prep("/tmp/e4")

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
    prep("/tmp/e5")
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
    prep("/tmp/e6")
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


def h1_trayectoria_basica():
    print("\n[H1] Trayectoria: cuándo apareció y cuándo se fue cada uno")
    prep("/tmp/h1")
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
    prep("/tmp/h2")
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
    prep("/tmp/h3")
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
    prep("/tmp/h4")
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
    prep("/tmp/h5")
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
    prep("/tmp/h6")
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
    prep("/tmp/h6b")
    captura("seguidores", "2026-09-01", [("ana", "", "1")], completa=False)
    check(m.construir_historial("seguidores") is None,
          "solo truncadas -> None, no un historial falso")

    # Huecos entre capturas
    prep("/tmp/h6c")
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-15", [("ana", "", "1")])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.mostrar_historial("seguidores")
    check("14 días" in buf.getvalue(),
          "avisa del hueco máximo entre capturas")

    # Capturas sin ids (formato viejo): cae al username sin romperse
    prep("/tmp/h6d")
    for dia in ("2026-09-01", "2026-09-02"):
        m._escribir_csv(m._ruta_captura("seguidores", dia),
                        ["username", "nombre", "id"], [["ana", "", ""]])
    h = m.construir_historial("seguidores")
    check(h is not None and len(h["personas"]) == 1,
          "sin ids sigue funcionando")
    check(list(h["personas"].values())[0]["id"] == "",
          "y deja la columna id vacía en vez de inventarla")


def x1_claves_homogeneas():
    print("\n[X1] Mezclar capturas con y sin ids no debe duplicar personas")
    prep("/tmp/x1")
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
    prep("/tmp/x1b")
    captura("seguidores", "2026-09-01", [("ana", "", "1")])
    captura("seguidores", "2026-09-02", [("ana_nueva", "", "1")])
    h = m.construir_historial("seguidores")
    check(h["usar_id"] is True, "con ids en todas, se usan los ids")
    check(len(h["personas"]) == 1, "el renombrado sigue siendo una persona")


def x2_captura_sin_metadatos():
    print("\n[X2] Una captura truncada SIN metadatos ya no envenena en silencio")
    prep("/tmp/x2")
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


def x3_captura_vacia():
    print("\n[X3] Una captura vacía marcada completa tampoco envenena")
    prep("/tmp/x3")
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
    prep("/tmp/x4")
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
    prep("/tmp/x5")
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
    prep("/tmp/x6")
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
    prep("/tmp/x7")
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
    prep("/tmp/x8")
    captura("seguidores", "2026-09-01", [("a", "", "1")])

    class Args:
        totales, historico, forzar = False, True, False
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cmd_comparar(Args())
    check("SEGUIDORES" in buf.getvalue(), "--historico sigue funcionando")


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


def z1_lista_de_vigilancia():
    print("\n[Z1] Leer la lista de vigilancia")
    prep("/tmp/z1")
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
    prep("/tmp/z2")
    m._ruta_vigilancia().write_text(
        "\n".join(f"cuenta{i}" for i in range(80)), encoding="utf-8")

    cuentas, avisos = m.leer_lista_vigilancia()
    check(len(cuentas) == m.MAX_VIGILANCIA,
          f"recorta a {m.MAX_VIGILANCIA} ({len(cuentas)})")
    check(any("petición" in a for a in avisos),
          "y avisa de que cada una cuesta una petición")


def z3_una_peticion_por_cuenta():
    print("\n[Z3] Exactamente una petición por cuenta, ni una más")
    prep("/tmp/z3")
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
    prep("/tmp/z4")
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
    prep("/tmp/z5")
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
    prep("/tmp/z6")
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
    prep("/tmp/z7")
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
    prep("/tmp/z8")
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


HTML_PERFIL = '''<!DOCTYPE html><html><head>
<meta property="og:description" content="4,820 Followers, 611 Following,
137 Posts - See Instagram photos and videos from Nombre (@cuenta.ejemplo)" />
<script>{"config":{},"profile_id":"51234567890","entry_data":{}}</script>
</head><body></body></html>'''


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
    prep("/tmp/w3d")
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


def p1_contador_diario():
    print("\n[P1] Se cuenta cada petición, por endpoint")
    prep("/tmp/p1")
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
    prep("/tmp/p2")
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
    prep("/tmp/p3")
    check(m.factor_prudencia() == 1.0, "sin bloqueos, ritmo normal")

    m.anotar_bloqueo_diario()
    check(m.factor_prudencia() == 2.0, "con un bloqueo, pausas al doble")

    m.anotar_bloqueo_diario()
    m.anotar_bloqueo_diario()
    check(m.factor_prudencia() == 3.0, "con tres, al triple")
    check(m._presupuesto()["bloqueos"] == 3, "y quedan registrados")


def p4_recordar_la_via_buena():
    print("\n[P4] Se recuerda qué vía funciona, entre ejecuciones")
    prep("/tmp/p4")
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
    prep("/tmp/p5")
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
    prep("/tmp/p6")

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

    check("3 de 250" in salida, f"muestra el gasto ({salida[:60]!r})")
    check("friendships/followers" in salida, "desglosado por endpoint")
    check("Bloqueos recibidos: 1" in salida, "y los bloqueos")
    check("x2" in salida, "avisa de que las pausas van al doble")
    check("página del perfil" in salida, "y qué vía se está usando")
    check(m.resumen_presupuesto().startswith("3/250"),
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
    prep("/tmp/q2")
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
    prep("/tmp/q2b")
    m._ruta_vigilancia().write_text("a\nb\nc\n", encoding="utf-8")
    m.anotar_bloqueo_diario()
    esperas.clear()
    m.cmd_detalles(Args())
    check(esperas and all(e >= m.PAUSA_DETALLE_MIN * 2 for e in esperas),
          f"tras un bloqueo, al doble ({[round(e, 1) for e in esperas]})")

    # Y no se pasa del presupuesto
    prep("/tmp/q2c")
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
    prep("/tmp/q3")
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
    prep("/tmp/q3b")
    bajadas.clear()
    m.cmd_vigilar(Args())
    check(sorted(bajadas) == ["seguidores", "seguidos"],
          f"con presupuesto, descarga ({bajadas})")


def q4_totales_no_fiables():
    print("\n[Q4] Sin totales fiables no se puede dar por completa")
    prep("/tmp/q4")
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
    prep("/tmp/q4b")
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
    prep("/tmp/q5")

    class S:
        cookies = {}

        def get(self, url, headers=None, params=None, timeout=None):
            class R:
                status_code = 200
                text = HTML_PERFIL
            return R()

    p = m.perfil_desde_html(S(), "x")
    check(p["la_sigo"] is None, "la página no afirma que la sigas")
    check(p["totales_fiables"] is True, "pero sus totales sí valen")


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


def n1_lista_de_cuentas():
    print("\n[N1] Registro de cuentas seguidas")
    prep("/tmp/n1")
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
    prep("/tmp/n2")
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
    prep("/tmp/n3")
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
    prep("/tmp/n4")
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
    prep("/tmp/n5")
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


def s1_400_no_se_reintenta():
    print("\n[S1] Un HTTP 400 no debe entrar en el bucle de esperas")
    prep("/tmp/s1")

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
    prep("/tmp/s2")
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
    prep("/tmp/s3")
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
    prep("/tmp/s3b")
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
    prep("/tmp/c3")
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


def c4_totales_solo_fiables_si_llegaron():
    print("\n[C4] Los totales no deben darse por buenos si no vinieron")
    prep("/tmp/c4")

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
    prep("/tmp/c5")
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


def r10_rutas_configurables():
    print("\n[R10] Reparar una ruta debe ser editar una línea, no código")
    prep("/tmp/r10")
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


def r11_volcado_de_fallo():
    print("\n[R11] Al romperse, se guarda con qué repararlo")
    prep("/tmp/r11")

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
    prep("/tmp/r11b")
    try:
        m.validar("lista", {"items": []}, "/api/v1/friendships/1/followers/")
    except m.RespuestaInesperada:
        pass
    volcados = list(m.CARPETA.glob("fallo_*.json"))
    check(len(volcados) == 1, "un cambio de forma también se vuelca")
    d = json.loads(volcados[0].read_text(encoding="utf-8"))
    check(d["tipo"] == "forma inesperada", "identificado como tal")
    check("campos_en_uso" in d, "con los nombres que se esperaban")


def r12_analisis_sin_red():
    print("\n[R12] Si Instagram cerrara la puerta, el análisis debe seguir")
    prep("/tmp/r12")
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


# ======================================================================
JPEG_FALSO = b"\xff\xd8\xff\xe0" + b"0" * 200
HTML_CON_FOTO = HTML_PERFIL.replace(
    "</head>",
    '<meta property="og:image" content="https://scontent.cdninstagram.com/'
    'v/foto.jpg?stp=dst-jpg&amp;_nc_ht=scontent.cdninstagram.com" />'
    "</head>")


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


def f3_una_carpeta_por_cuenta():
    print("\n[F3] Cada cuenta en su carpeta, «usuario - id»")
    carpeta = prep("/tmp/f3")

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
    carpeta = prep("/tmp/f4")

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
    carpeta2 = prep("/tmp/f4b")
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


def f5_relacion_con_la_cuenta():
    print("\n[F5] Quién sigue a la cuenta y a quién sigue ella")
    prep("/tmp/f5")

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
    prep("/tmp/f5b")
    captura("seguidores", [("ana", "1")])
    captura("seguidos", [("ana", "1")], completa=False)
    m.cruzar_capturas(callado=True)
    filas = leer(m._ruta_captura("seguidores", DIA))
    check(filas[0]["la_cuenta_le_sigue"] == "",
          "con una captura incompleta no se escribe nada: serían noes falsos")

    prep("/tmp/f5c")
    captura("seguidores", [("ana", "1")], dia="2026-09-09")
    captura("seguidos", [("beto", "2")], dia="2026-08-01")
    aviso = m.cruzar_capturas(callado=True)
    check("días distintos" in aviso, f"y avisa si son de días distintos")
    filas = leer(m._ruta_captura("seguidores", "2026-09-09"))
    check(filas[0]["la_cuenta_le_sigue"] == "",
          "tampoco se cruzan capturas de fechas distintas")


def f6_cambios_de_relacion():
    print("\n[F6] De qué TIPO fue cada cambio, respecto a la cuenta objetivo")
    prep("/tmp/f6")

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
    prep("/tmp/f6b")
    dia("2026-09-01", ["ana"], ["ana"])
    check(m.cambios_de_relacion() == [],
          "con un solo día no se inventa ningún cambio")

    prep("/tmp/f6c")
    dia("2026-09-01", ["ana"], ["ana"])
    r = m._ruta_captura("seguidores", "2026-09-08")
    m._escribir_csv(r, m.CABECERA, [])
    m._escribir_meta(r, False, 100, 0, "truncada")
    m._escribir_csv(m._ruta_captura("seguidos", "2026-09-08"), m.CABECERA, [])
    m._escribir_meta(m._ruta_captura("seguidos", "2026-09-08"),
                     True, 0, 0, "completa")
    check(m.cambios_de_relacion() == [],
          "una truncada no cuenta como día: diría que se fueron todos")


def f7_el_crudo_del_perfil():
    print("\n[F7] La respuesta del perfil se guarda en vez de tirarse")
    prep("/tmp/f7")

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


def f8_bandeja_de_novedades():
    print("\n[F8] Lo que encuentra 'vigilar' se acumula hasta que lo leas")
    prep("/tmp/f8")

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
    prep("/tmp/f9")
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
    prep("/tmp/f9b")
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
    prep("/tmp/f9c")
    m.anotar_novedad("t", ["una linea\ncon salto"])
    bloques = m.separar_novedades(
        m._ruta_novedades().read_text(encoding="utf-8"))
    check(len(bloques) == 1, f"un solo bloque ({len(bloques)})")


def f10_informe_html():
    print("\n[F10] Un archivo con todo dentro")
    import informe_html
    prep("/tmp/f10")

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
    prep("/tmp/f11")

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
    carpeta = prep("/tmp/f12")
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
    prep("/tmp/f13")
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
    prep("/tmp/f13b")
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
    prep("/tmp/f13c")
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
    prep("/tmp/f14")
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


def f16_plurales():
    print("\n[F16] Un solo sitio decide los plurales")
    check(m.plural(1, "mutuo") == "1 mutuo", "uno en singular")
    check(m.plural(0, "mutuo") == "0 mutuos", "cero en plural, como se habla")
    check(m.plural(13, "seguidor", "seguidores") == "13 seguidores",
          "y los irregulares se dan a mano")
    check(m.plural(-1, "bloqueo") == "-1 bloqueo", "el signo no lo cambia")

    # Es el defecto de «1 bloqueo(s)»: se corrigió en la ventana y se quedó
    # en el módulo. Que no vuelva a haber dos sitios donde arreglarlo.
    fuente = Path("instagram_listas.py").read_text(encoding="utf-8")
    check("(s)\"" not in fuente and "(s):" not in fuente,
          "no queda ningún «(s)» en los mensajes del módulo")


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
    prep("/tmp/f15")
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
    carpeta = prep("/tmp/f17")
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
    prep("/tmp/f18")
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

    carpeta = prep("/tmp/f19")
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
    prep("/tmp/f20")
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
    carpeta = prep("/tmp/f21")
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
    carpeta = prep("/tmp/f22")
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
    prep("/tmp/f23")

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
    prep("/tmp/f23b")
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

    prep("/tmp/f23c")
    m._PRESUPUESTO = None

    class Args:
        prudente, normal, fijar = True, False, None
    m.cmd_limite(Args())
    check(m._limite().get("prudente") is True, "el interruptor se guarda")
    Args.prudente, Args.normal = False, True
    m.cmd_limite(Args())
    check(m._limite().get("prudente") is False, "y se puede quitar")


def f24_el_volcado_no_pierde_nada():
    print("\n[F24] El volcado del presupuesto no se come contadores")
    prep("/tmp/f24")
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


def f25_registro():
    print("\n[F25] El registro se puede mandar sin la cuenta dentro")
    import registro as reg
    import shutil

    carpeta = Path("/tmp/f25")
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

    carpeta = Path("/tmp/f26")
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


def f27_escritura_atomica():
    print("\n[F27] Una captura a medias no puede existir")
    carpeta = prep("/tmp/f27")

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


def f28_ajustes_en_un_sitio():
    print("\n[F28] La configuración, en un solo archivo y con límites")
    carpeta = prep("/tmp/f28")
    serie = m.ajustes_de_serie()

    # Los límites no son adorno: todo el proyecto está hecho para no perder
    # la cuenta, y un archivo que aceptara «pausa 0» tiraría lo demás.
    check(m.acotar("pausa_min", 0) == 0.5, "una pausa de cero se sube al piso")
    check(m.acotar("tope_hora", 99999) == 500, "un tope absurdo se recorta")
    check(m.acotar("por_pagina", 500) == 50,
          "y por_pagina no pasa de 50, que es lo que pide la web")
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
    prep("/tmp/f28b")
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


def f33_sesiones_en_su_carpeta():
    print("\n[F33] Las sesiones, en su carpeta y sin activar nada sola")
    carpeta = prep("/tmp/f33")
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
    prep("/tmp/f33b")
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
    carpeta = prep("/tmp/f34")
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


def f36_copia_de_seguridad():
    print("\n[F36] Copia de lo que no se puede volver a descargar")
    import copia
    import zipfile

    carpeta = prep("/tmp/f36")
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
    prep("/tmp/f36b")
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
    carpeta = prep("/tmp/f37")
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
    prep("/tmp/f37b")
    m.recordar_id("t", "9")
    r = m._ruta_captura("seguidores", "2026-09-01")
    m._escribir_csv(r, m.CABECERA, [m._fila({"username": "a"}, m.CABECERA)])
    m._escribir_meta(r, True, 1, 1, "completa")
    ruta, _ = copia.crear("t")

    prep("/tmp/f37c")
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

    carpeta = prep("/tmp/f38")
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
    # acabó escrita a mano en LEEME.txt y esto no lo veía. Un documento
    # que miente sobre la versión es peor que uno que no la dice.
    revisados = 0
    for archivo in sorted(list(Path(".").glob("*.py"))
                          + list(Path(".").glob("*.txt"))
                          + list(Path(".").glob("*.md"))):
        if archivo.name == "version.py" or archivo.name.startswith("test_"):
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


def f39_comprobar_sin_cambiarse():
    print("\n[F39] Comprobar una sesión sin perder la que estás usando")
    carpeta = prep("/tmp/f39")
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
    prep("/tmp/f40")
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
    carpeta = prep("/tmp/f41")
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
    carpeta = prep("/tmp/f42")
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
    carpeta = prep("/tmp/f44")
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


def f45_el_leeme_no_miente():
    print("\n[F45] El LEEME no promete cosas que no existen")
    leeme = Path("LEEME.txt").read_text(encoding="utf-8")
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
    faltan = sorted(b for b in banderas
                    if f'"{b}"' not in fuente and b != "--version")
    check(not faltan, f"banderas citadas que no existen: {faltan}")

    listados = set(re.findall(r"^    (\S+\.py|\S+\.md)\s", leeme, re.M))
    hay = {a.name for a in Path(".").iterdir()}
    check(not (listados - hay),
          f"archivos listados que no están: {sorted(listados - hay)}")
    # Y al revés: un archivo nuevo que nadie apuntó en el LEEME
    sin_citar = sorted(a for a in hay
                       if a.endswith(".py") and a not in listados)
    check(not sin_citar, f"archivos del proyecto sin citar: {sin_citar}")


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


def f29_repaso_de_escritura_y_ajustes():
    print("\n[F29] Lo que se encontró repasando lo atómico y los ajustes")
    carpeta = prep("/tmp/f29")

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


if __name__ == "__main__":
    PRUEBAS = [
        test_descarga_completa, test_reanudacion, test_fusion_mismo_dia,
        test_bordes,
        r1_sesion_no_bloquea, r2_cursor_cero, r3_no_comparar_truncadas,
        r4_cambio_de_username, r5_errores_separados, r6_sin_codigo_muerto,
        r7_tiempos_documentados, r8_bom_para_excel, r9_relaciones_avisa_fechas,
        v1_decidir_disparadores, v2_neto_cero, v3_ignora_capturas_rotas,
        v4_conteo_y_log, v5_vigilar_end_to_end, v6_contar_no_dispara_descarga,
        e1_campos_extra, e2_campo_ausente, e3_reanudar_cabecera_antigua,
        e4_fusion_cabeceras_distintas, e5_resumen_de_campos, e6_inspeccionar,
        e7_comandos_intactos,
        h1_trayectoria_basica, h2_follow_unfollow, h3_excluye_truncadas,
        h4_cambio_de_nombre, h5_informe_csv, h6_bordes_historial,
        x1_claves_homogeneas, x2_captura_sin_metadatos, x3_captura_vacia,
        x4_bajada_real_sostenida, x5_fecha_duplicada, x6_sin_doble_lectura,
        x7_min_entradas, x8_nombres_distinguibles,
        y1_cortafuegos_tras_429, y2_401_no_amplifica, y3_sesion_se_reutiliza,
        y4_endpoint_de_verificacion_recordado, y5_referer_del_perfil,
        y6_gasto_total_de_una_sesion,
        z1_lista_de_vigilancia, z2_tope_duro, z3_una_peticion_por_cuenta,
        z4_no_repite_lo_ya_consultado, z5_para_al_primer_bloqueo,
        z6_solo_listar_no_gasta, z7_crear_lista_desde_capturas,
        z8_respeta_el_cortafuegos,
        w1_html_como_alternativa, w2_cadena_de_alternativas, w3_diagnostico,
        p1_contador_diario, p2_tope_diario, p3_prudencia_tras_bloqueo,
        p4_recordar_la_via_buena, p5_estimar_antes_de_gastar,
        p6_informe_del_gasto,
        q1_dos_procesos_no_se_pisan, q2_detalles_frena_tras_bloqueo,
        q3_vigilar_estima_antes, q4_totales_no_fiables,
        q5_privada_sin_saber_si_la_sigues, q6_cerrojo_huerfano,
        n1_lista_de_cuentas, n2_cada_cuenta_sus_archivos,
        n3_vigilar_todas_raciona, n4_cuenta_por_linea_de_comandos,
        n5_listado_de_cuentas,
        s1_400_no_se_reintenta, s2_descarga_para_en_seco_ante_400,
        s3_reintento_con_pagina_pequena,
        c1_contrato_acepta_lo_bueno, c2_contrato_caza_el_cambio_silencioso,
        c3_la_descarga_para_ante_un_cambio,
        c4_totales_solo_fiables_si_llegaron,
        c5_una_via_rota_pasa_a_la_siguiente, c6_listado_de_contratos,
        r10_rutas_configurables, r11_volcado_de_fallo, r12_analisis_sin_red,
        f1_foto_de_perfil, f2_publicaciones_y_nombre,
        f3_una_carpeta_por_cuenta, f4_los_archivos_de_antes_se_recogen,
        f5_relacion_con_la_cuenta, f6_cambios_de_relacion,
        f7_el_crudo_del_perfil, f8_bandeja_de_novedades,
        f9_el_aviso_no_miente, f10_informe_html, f11_repaso_del_informe,
        f12_indice_de_eventos, f13_podar_sin_perder_historial,
        f14_repaso_del_indice, f15_export_oficial, f16_plurales,
        f17_tope_que_se_mide, f18_ritmo_por_cuenta, f19_repaso_del_ritmo,
        f20_sesion_pegada, f21_varias_sesiones, f23_no_perder_la_cuenta,
        f24_el_volcado_no_pierde_nada, f25_registro, f26_repaso_del_registro,
        f27_escritura_atomica, f28_ajustes_en_un_sitio,
        f29_repaso_de_escritura_y_ajustes, f30_nombres_limpios,
        f31_el_reparto_aguanta, f32_ningun_nombre_suelto,
        f33_sesiones_en_su_carpeta, f34_elegir_cuenta,
        f35_por_que_falla_cada_navegador, f36_copia_de_seguridad,
        f37_repaso_copia_y_sesiones, f38_version,
        f39_comprobar_sin_cambiarse, f40_comprobar_cuenta_lo_que_gasta,
        f41_conectar_es_cambiar_y_comprobar, f42_comparar_dos_fechas,
        f43_los_botones_pasan_lo_que_hace_falta,
        f44_cruzar_dos_cuentas, f45_el_leeme_no_miente,
        f22_una_sola_a_la_vez,
    ]

    # Ninguna prueba definida debe quedarse fuera de la lista por descuido.
    definidas = {n for n, o in list(globals().items())
                 if callable(o) and re.match(r"^(test_|[cefhnpqrsvwxyz]\d+_)", n)}
    registradas = {f.__name__ for f in PRUEBAS}
    if definidas - registradas:
        print("PRUEBAS DEFINIDAS PERO NO REGISTRADAS: "
              + ", ".join(sorted(definidas - registradas)))
        sys.exit(1)

    for prueba in PRUEBAS:
        try:
            restaurar_modulo()
            prueba()
        except Exception:
            # Una excepción es un fallo, no un final silencioso de la suite.
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
