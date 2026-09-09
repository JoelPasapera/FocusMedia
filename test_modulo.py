"""
Banco de pruebas de instagram_listas.py v2.

Simula la API de Instagram para verificar el módulo sin tocar la red.
Los bloques [R1]..[R9] son regresiones: cada uno cubre uno de los nueve
fallos detectados en la v1, y debe fallar si alguien los reintroduce.

    python test_modulo.py
"""

import csv
import json
import re
import traceback
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
    informe = m.CARPETA / f"cambios_{m.OBJETIVO}_seguidores_2026-09-02.csv"
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
    r = leer(m.CARPETA / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
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
    r = leer(m.CARPETA / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv")
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
    inf = m.CARPETA / f"cambios_{m.OBJETIVO}_seguidores_2026-09-01.csv"
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

    rel = leer(m.CARPETA / "relaciones_t.csv")
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
    for col in ("privada", "verificada", "le_sigue", "la_sigue"):
        check(col in cab, f"columna '{col}' presente")

    check(filas[0]["privada"] == "si" and filas[1]["privada"] == "no",
          "booleanos como si/no")
    check(filas[0]["verificada"] == "si" and filas[1]["verificada"] == "no",
          "verificada correcta")
    check(filas[0]["la_sigue"] == "si",
          "ruta anidada friendship_status.following resuelta")
    check(filas[0]["le_sigue"] == "si" and filas[1]["le_sigue"] == "no",
          "ruta anidada friendship_status.followed_by resuelta")


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

    crudo = m.CARPETA / f"crudo_{m.OBJETIVO}_seguidos.json"
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

    ruta = m.CARPETA / "historial_seguidores_t.csv"
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

    p = m.perfil(S(), "yomira.milagros")
    check(p["seguidores"] == 5, "devuelve el perfil")
    check(visto["headers"].get("Referer", "").endswith("/yomira.milagros/"),
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
137 Posts - See Instagram photos and videos from Yomira (@yomira.milagros)" />
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

    p = m.perfil_desde_html(S(), "yomira.milagros")
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

    check(m.anadir_cuenta("yomira.milagros"), "añade una")
    check(m.anadir_cuenta("https://www.instagram.com/ale_viera13/"),
          "acepta una URL")
    check(not m.anadir_cuenta("@yomira.milagros"),
          "no duplica la misma con @")
    check(not m.anadir_cuenta("https://www.instagram.com/p/ABC/"),
          "rechaza lo que no es un perfil")
    check(m.leer_cuentas() == ["yomira.milagros", "ale_viera13"],
          f"quedan las dos, en orden ({m.leer_cuentas()})")

    check(m.quitar_cuenta("yomira.milagros"), "quita una")
    check(m.leer_cuentas() == ["ale_viera13"], "y queda la otra")
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
    ]

    # Ninguna prueba definida debe quedarse fuera de la lista por descuido.
    definidas = {n for n, o in list(globals().items())
                 if callable(o) and re.match(r"^(test_|[cnpqrsvehwxyz]\d+_)", n)}
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
