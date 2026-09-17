#!/usr/bin/env python3
"""
analitica.py  ·  preguntas que el disco ya puede responder

Cero peticiones. Todo lo de aquí sale del índice de presencia y de la
serie de totales, que ya están guardados. No se habla con Instagram.

Lo que hay y lo que no
----------------------
Hay: quién estaba en cada captura, desde cuándo y hasta cuándo, y por día
los totales de seguidores, seguidos y publicaciones. Por persona, además:
si su cuenta es privada, si está verificada y si tiene la foto por
defecto.

NO hay likes ni comentarios, y conviene decirlo aquí porque es lo primero
que se pregunta. Este proyecto nunca los ha descargado. Sacarlos costaría
cientos de peticiones por cuenta contra endpoints más vigilados que el de
listas, así que no es una pregunta de coste cero: es la más cara de
todas.

Todas las funciones son puras: reciben datos y devuelven datos. Por eso
se pueden comprobar con historiales inventados, sin montar capturas.
"""

from __future__ import annotations

from datetime import date


def _mes(fecha: str) -> str:
    return fecha[:7]


def cohortes(trayectorias: dict) -> list:
    """
    De los que entraron cada mes, cuántos siguen.

    Es la pregunta que este historial puede responder y nadie más:
    Instagram enseña cuántos seguidores tienes, no cuántos de los de
    agosto siguen contigo en diciembre.

    Solo cuentan los que entraron DESPUÉS de la primera captura. Quien ya
    estaba el primer día no «entró» ese mes: estaba, y no se sabe desde
    cuándo. Meterlos inflaría la primera cohorte con gente que puede
    llevar años.
    """
    fechas = trayectorias.get("fechas") or []
    if not fechas:
        return []
    por_mes: dict = {}
    for persona in (trayectorias.get("personas") or {}).values():
        if persona.get("primera") == fechas[0]:
            continue           # ya estaba: no se sabe desde cuándo
        mes = _mes(persona["primera"])
        d = por_mes.setdefault(mes, {"mes": mes, "entraron": 0, "siguen": 0})
        d["entraron"] += 1
        if persona.get("presente"):
            d["siguen"] += 1
    salida = [dict(d, retencion=round(d["siguen"] * 100 / d["entraron"]))
              for d in por_mes.values() if d["entraron"]]
    return sorted(salida, key=lambda d: d["mes"])


def permanencia(trayectorias: dict) -> dict:
    """
    Cuánto dura la gente que se acaba yendo. En días, no en capturas.

    Tres exclusiones, y las tres cambian el número:

    - **Los que siguen dentro.** Su permanencia aún no ha terminado, y
      contarla sesgaría el resultado hacia abajo: es el error clásico de
      medir duraciones con casos abiertos.
    - **Los que ya estaban en la primera captura.** Arrastran una
      antigüedad desconocida.
    - **Los que se fueron y volvieron.** Solo se tiene su primera y su
      última fecha, así que restar una de otra contaría como dentro todo
      el tiempo que estuvieron fuera. Alguien que estuvo dos semanas en
      julio y dos en septiembre salía con 69 días de permanencia cuando
      estuvo 14. Van aparte, en `recurrentes()`.
    """
    fechas = trayectorias.get("fechas") or []
    if len(fechas) < 2:
        return {"casos": 0}
    dias, aparte = [], 0
    for persona in (trayectorias.get("personas") or {}).values():
        if (not persona.get("presente")
                and persona.get("primera") != fechas[0]
                and (persona.get("entradas") or 1) > 1):
            aparte += 1
        if (persona.get("presente")
                or persona.get("primera") == fechas[0]
                or (persona.get("entradas") or 1) > 1):
            continue
        dias.append((date.fromisoformat(persona["ultima"])
                     - date.fromisoformat(persona["primera"])).days)
    if not dias:
        return {"casos": 0, "aparte": aparte}
    dias.sort()
    mitad = len(dias) // 2
    mediana = (dias[mitad] if len(dias) % 2
               else (dias[mitad - 1] + dias[mitad]) / 2)
    return {"casos": len(dias), "mediana": mediana,
            "aparte": aparte,
            "media": round(sum(dias) / len(dias), 1),
            "menos_de_7": sum(1 for d in dias if d < 7),
            "mas_de_90": sum(1 for d in dias if d > 90),
            "min": dias[0], "max": dias[-1]}


def recurrentes(trayectorias: dict) -> list:
    """
    Quién se fue y volvió. `entradas` cuenta cada estancia, así que dos o
    más son idas y vueltas.
    """
    fuera = []
    for clave, persona in (trayectorias.get("personas") or {}).items():
        if (persona.get("entradas") or 1) > 1:
            fuera.append({"clave": clave,
                          "username": persona.get("username") or str(clave),
                          "veces": persona["entradas"]})
    return sorted(fuera, key=lambda d: (-d["veces"], d["username"].lower()))


def composicion(filas: list) -> dict:
    """
    Qué proporción de una lista es privada, verificada o sin foto.

    Se devuelve también cuántas filas NO traían el dato. Un «0%» calculado
    sobre una columna vacía no es un 0%: es que no se sabe, y este
    proyecto lleva versiones distinguiendo las dos cosas.
    """
    total = len(filas)
    fuera: dict = {"total": total}
    for campo in ("privada", "verificada", "foto_defecto"):
        con_dato = [f for f in filas if str(f.get(campo, "")).strip() != ""]
        sies = sum(1 for f in con_dato if str(f.get(campo)).lower()
                   in ("si", "sí", "true", "1"))
        fuera[campo] = {
            "si": sies, "con_dato": len(con_dato),
            "sin_dato": total - len(con_dato),
            "porcentaje": (round(sies * 100 / len(con_dato))
                           if con_dato else None),
        }
    return fuera


def publicar_vs_crecer(totales: list) -> dict:
    """
    Los días que se publica, ¿se gana más gente? Correlación, no causa.

    `totales` son las filas de totales.csv, con fecha, seguidores y
    publicaciones. Se comparan tramos entre capturas consecutivas: si
    entre dos el número de publicaciones subió, ese tramo «tuvo
    publicación».

    El número que sale es una diferencia de medias, y eso es todo lo que
    es. Puede haber publicado porque estaba creciendo, y no al revés.
    """
    # Llegan como [fecha, seguidores, seguidos, publicaciones]: el CSV de
    # totales no tiene columna 'username', así que el lector de perfiles
    # lo descartaría entero. Se usa _filas_totales(), que es el suyo.
    filas = [f for f in totales
             if len(f) >= 4 and str(f[1]).strip().isdigit()
             and str(f[3]).strip().isdigit()]
    filas.sort(key=lambda f: f[0])
    con, sin = [], []
    for antes, ahora in zip(filas, filas[1:]):
        dias = (date.fromisoformat(ahora[0])
                - date.fromisoformat(antes[0])).days or 1
        delta = (int(ahora[1]) - int(antes[1])) / dias
        (con if int(ahora[3]) > int(antes[3]) else sin).append(delta)
    if not con or not sin:
        return {"tramos": len(con) + len(sin), "con": len(con),
                "sin": len(sin), "bastante": False}
    media_con = sum(con) / len(con)
    media_sin = sum(sin) / len(sin)
    return {"tramos": len(con) + len(sin), "con": len(con), "sin": len(sin),
            "media_con": round(media_con, 2), "media_sin": round(media_sin, 2),
            "diferencia": round(media_con - media_sin, 2),
            # Con cuatro tramos de cada lado, la diferencia es ruido. El
            # umbral no hace el dato bueno: evita presentarlo como si lo
            # fuera.
            "bastante": len(con) >= 5 and len(sin) >= 5}


def huecos(fechas: list, tope: int = 1) -> list:
    """
    Días sin captura entre una y la siguiente. Sostiene todo lo demás.

    Una cohorte calculada sobre un historial con agujeros miente: alguien
    que entró y se fue dentro del hueco no aparece, y quien cambió de
    estado parece haberlo hecho el día que se volvió a mirar.
    """
    fuera = []
    for antes, ahora in zip(sorted(fechas), sorted(fechas)[1:]):
        dias = (date.fromisoformat(ahora) - date.fromisoformat(antes)).days
        if dias > tope:
            fuera.append({"desde": antes, "hasta": ahora, "dias": dias - 1})
    return fuera


def _plural(n, uno, muchos=""):
    """Respaldo mínimo. El motor pasa el suyo, que es el bueno."""
    return f"{n} {uno if abs(n) == 1 else (muchos or uno + 's')}"


def avisos_de_salud(d: dict, plural=None) -> list:
    """
    Qué merece atención, de lo que se ha recogido. Función pura.

    Un informe que lo enseña todo por igual no es un informe: es un
    volcado. Esto decide qué sube arriba, y por eso se puede comprobar con
    diccionarios inventados en vez de montando medio proyecto.

    Cada aviso es (gravedad, texto). Gravedad "alto" es algo que está
    pasando ahora; "medio" es algo que pasará si nadie mira.

    `plural` se recibe en vez de importarse para que este módulo siga sin
    depender del motor. Los «(s)» se corrigieron en la v5.5 y no van a
    volver por la puerta de atrás de un archivo nuevo.
    """
    plural = plural or _plural
    fuera = []

    if not d.get("sesion_activa"):
        fuera.append(("alto", "no hay ninguna sesión activa: nada que use "
                              "internet va a funcionar"))
    elif not d.get("sesion_comprobada"):
        fuera.append(("medio", "la sesión activa no se ha comprobado nunca; "
                               "no se sabe si sirve"))

    if d.get("rechazos_hoy"):
        fuera.append(("alto",
                      plural(d["rechazos_hoy"], "rechazo")
                      + " HTTP 401/403 hoy: Instagram no reconoce la sesión"))
    if d.get("bloqueos_hoy"):
        fuera.append(("medio", plural(d["bloqueos_hoy"], "bloqueo")
                      + " hoy; las pausas van más largas"))

    gastado, tope = d.get("gastado_hoy", 0), d.get("tope") or 1
    if gastado >= tope:
        fuera.append(("medio", "el presupuesto de hoy está agotado"))

    if d.get("capturas_incompletas"):
        fuera.append(("medio", plural(d["capturas_incompletas"], "captura")
                  + " sin terminar: comparar las salta"))
    if d.get("cadena_rota"):
        # El verbo también concuerda: «1 captura cambiaron» se leía fatal
        # y plural() solo sabe de nombres.
        fuera.append(("alto", plural(d["cadena_rota"], "captura")
                      + (" cambió" if d["cadena_rota"] == 1
                         else " cambiaron")
                      + " después de guardarse"))
    peor = d.get("mayor_hueco") or 0
    if peor > (d.get("max_dias_sin_bajar") or 7):
        fuera.append(("medio", f"hay un hueco de {peor} días sin captura; "
                               "lo medido sobre él es aproximado"))

    if d.get("errores_registro"):
        fuera.append(("medio",
                      plural(d["errores_registro"], "error", "errores")
                      + " en el registro: mira «Registro»"))

    if d.get("sin_copia"):
        # Lo único irrecuperable del proyecto. No tener copia no rompe
        # nada hoy, y por eso es exactamente lo que se olvida.
        fuera.append(("medio", "no hay ninguna copia de seguridad; las "
                               "capturas viejas no se pueden volver a "
                               "descargar"))
    elif (d.get("dias_sin_copia") or 0) > 30:
        fuera.append(("medio", f"la última copia es de hace "
                               f"{d['dias_sin_copia']} días"))

    orden = {"alto": 0, "medio": 1}
    return sorted(fuera, key=lambda x: orden.get(x[0], 9))
