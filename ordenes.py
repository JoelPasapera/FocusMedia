#!/usr/bin/env python3
"""
ordenes.py  ·  lo que se puede pedir desde la línea de órdenes

Estaba dentro de instagram_listas.py, que llegó a 5.631 líneas haciendo de
todo: hablar con Instagram, gobernar el presupuesto, guardar archivos,
analizar y además atender la línea de órdenes.

Este corte es el más limpio de los tres que había sobre la mesa, y no es
una opinión: se midió. Los comandos usan 69 funciones del motor y **nadie
los usa a ellos**. Eso es una hoja, solo que arriba en vez de abajo, y
sacarla no crea ninguna dependencia nueva.

Todo lo del motor se usa por `motor.`, y a propósito. Con `from ... import`
los nombres quedarían atados al valor que tuvieran al importar, y este
proyecto cambia varios en marcha —la cuenta objetivo, la carpeta, los topes
que se aprenden— y las pruebas sustituyen funciones enteras. Un atajo ahí
habría hecho que el banco de pruebas midiera otra cosa.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import random
import sys
from datetime import date, datetime
from pathlib import Path

import instagram_listas as motor
import analitica
import copia
import export_instagram
import registro


def cmd_ajustes(args) -> None:
    """Qué ajustes hay, cuáles están cambiados y dentro de qué margen."""
    if getattr(args, "restaurar", False):
        with contextlib.suppress(OSError):
            motor._ruta_ajustes().unlink(missing_ok=True)
        # Y volver a poner los valores AHORA: borrar el archivo sin esto
        # dejaba los ajustes viejos en pie hasta el siguiente arranque.
        # Lo hace el motor: desde aquí, `globals()` sería el de este
        # archivo y los ajustes se habrían quedado puestos donde nadie los
        # lee. Además ya sabe hacerlo, porque devuelve a su valor de serie
        # todo lo que no esté en el archivo.
        motor.aplicar_ajustes()
        print("\nAjustes de serie restaurados.")
        return

    if getattr(args, "poner", None):
        pares = {}
        for trozo in args.poner:
            clave, _, valor = str(trozo).partition("=")
            pares[clave.strip()] = valor.strip()
        _, avisos = motor.guardar_ajustes(pares)
        for aviso in avisos:
            print(f"  {aviso}")
        print("\nGuardado en", motor._ruta_ajustes().name)

    guardados = motor.leer_ajustes()
    serie = motor.ajustes_de_serie()
    grupo_actual = ""
    for clave, (constante, minimo, maximo, grupo, para) in\
            sorted(motor.AJUSTABLES.items(), key=lambda kv: (kv[1][3], kv[0])):
        if grupo != grupo_actual:
            grupo_actual = grupo
            print(f"\n{grupo.upper()}")
        marca = "*" if clave in guardados else " "
        print(f" {marca} {clave:<20} {getattr(motor, constante):>8}   "
              f"(de serie {serie[clave]}, entre {minimo} y {maximo})")
        print(f"     {para}")
    if guardados:
        print("\n  * = cambiado en " + motor._ruta_ajustes().name)
    print("  Cambiar: ajustes --poner tope_hora=90 pausa_min=2")
    print("  Todo vuelve a su sitio con: ajustes --restaurar")


def cmd_podar(args) -> None:
    """Enseña o hace la poda de capturas viejas. 0 peticiones."""
    for tipo in ("seguidores", "seguidos"):
        motor.actualizar_indice(tipo)         # nada se borra sin estar aprendido

    fuera = motor.podar(args.dias, args.hacerlo)
    if not fuera:
        print(f"\nNada que podar: no hay capturas de más de "
              f"{args.dias} días con otra de su misma semana.")
        return

    ahorro = (0 if args.hacerlo
              else sum(r.stat().st_size for r in fuera if r.exists()))
    print(f"\n{len(fuera)} capturas sobran (una por semana es suficiente "
          f"pasados {args.dias} días):")
    for ruta in fuera[:12]:
        print(f"  {ruta.name}")
    if len(fuera) > 12:
        print(f"  ... y {len(fuera) - 12} más")

    if args.hacerlo:
        print("\n  Borradas. El historial no cambia: el índice ya\n"
              "  las sabía.")
    else:
        print(f"\n  Liberarían {ahorro / 1e6:.1f} MB. No se ha borrado nada.")
        print("  Añade --hacerlo para borrarlas de verdad.")


def cmd_historial(args) -> None:
    if not motor.CARPETA.exists():
        sys.exit(f"No existe '{motor.CARPETA.name}'. Descarga las listas "
                 "primero.")
    tipos = (["seguidores", "seguidos"] if args.lista == "ambas"
             else [args.lista])
    for tipo in tipos:
        motor.mostrar_historial(tipo, args.min_entradas, args.incluir_sospechosas)


def cmd_cuentas(args) -> None:
    """Ver, añadir o quitar cuentas seguidas. No gasta peticiones."""
    if args.anadir:
        for nombre in args.anadir:
            limpio = motor.limpiar_usuario(nombre)
            if motor.anadir_cuenta(nombre):
                print(f"  añadida: {limpio}")
            else:
                print(f"  ya estaba o no vale: {nombre}")
        return

    if args.quitar:
        for nombre in args.quitar:
            print(f"  {'quitada' if motor.quitar_cuenta(nombre) else 'no estaba'}: "
                  f"{motor.limpiar_usuario(nombre)}")
        print("  (sus capturas siguen en la carpeta)")
        return

    cuentas = motor.leer_cuentas()
    if not cuentas:
        print("\nNo sigues ninguna cuenta todavía.")
        print("Se añaden solas al descargarlas, o con:  cuentas --anadir X")
        return

    print(f"\n{len(cuentas)} cuentas seguidas:")
    print(f"  {'cuenta':<24} {'capturas':>8}  última        estado")
    print("  " + "-" * 58)
    for nombre in cuentas:
        e = motor.estado_de_cuenta(nombre)
        estado = "descarga a medias" if e["pendiente"] else ""
        print(f"  {nombre:<24} {e['capturas']:>8}  "
              f"{e['ultima'] or '—':<12}  {estado}")

    print(f"\n  Quedan {motor.queda_presupuesto()} peticiones hoy para repartir "
          "entre todas.")


def cmd_ritmo(_) -> None:
    """Cada cuánto se mira cada cuenta y por qué. 0 peticiones."""
    ritmo = motor.leer_ritmo()
    cuentas = motor.leer_cuentas()
    if not cuentas:
        print("\nNo sigues ninguna cuenta.")
        return

    print(f"\n{'CUENTA':<24} {'CADA':>5} {'MIRADA':>11} "
          f"{'CAMBIÓ':>11}  ESTADO")
    print("-" * 74)
    ahorro = 0
    for nombre in sorted(cuentas):
        e = ritmo.get(nombre, {})
        cadencia = min(int(e.get("cadencia") or 1), motor.MAX_DIAS_SIN_BAJAR)
        ahorro += cadencia - 1
        falta = -motor.retraso(e)
        estado = ("toca hoy" if falta <= 0
                  else "faltan " + motor.plural(falta, "día"))
        print(f"{nombre:<24} {cadencia:>4}d {e.get('mirada', '—'):>11} "
              f"{e.get('cambio', '—'):>11}  {estado}")

    print(f"\n  {motor.plural(len(cuentas), 'cuenta')}. Mirarlas todas a diario "
          + "costaría "
          + motor.plural(len(cuentas), "petición", "peticiones") + " al día.")
    reparto = sum(1 / min(int((ritmo.get(n) or {}).get("cadencia") or 1),
                          motor.MAX_DIAS_SIN_BAJAR) for n in cuentas)
    print(f"  Con este ritmo salen {reparto:.1f} al día de media.")
    print(f"  El techo es {motor.MAX_DIAS_SIN_BAJAR} días: más lento rompería la "
          "descarga forzada")
    print("  que existe para pillar los cambios de neto cero.")


def cmd_vigilar_todas(args) -> None:
    """
    Recorre todas las cuentas seguidas repartiendo el presupuesto.

    NO va en paralelo, y es a propósito: el límite es de la sesión, así que
    lanzarlas a la vez solo haría llegar las mismas peticiones más juntas,
    que es exactamente lo que provoca los bloqueos. Se hace por turnos, y
    lo que no cabe hoy se queda para mañana con prioridad.
    """
    cuentas = motor.leer_cuentas()
    if not cuentas:
        print("No sigues ninguna cuenta. Añádelas con 'cuentas --anadir X'.")
        return

    ritmo = motor.leer_ritmo()
    if getattr(args, "todas_ya", False):
        toca = list(cuentas)
        saltadas = []
    else:
        # Cada cuenta tiene su ritmo: las que se mueven se miran a diario y
        # las dormidas cada varios días. Mirar veinte cuentas quietas todos
        # los días son veinte peticiones tiradas, y son las mismas que
        # faltan para vigilar veinte más.
        toca = [n for n in cuentas if motor.retraso(ritmo.get(n, {})) >= 0]
        saltadas = [n for n in cuentas if n not in toca]
        # Primero las que más lo necesitan: si el presupuesto no llega para
        # todas, que se quede fuera la que menos falta hace.
        toca.sort(key=lambda n: -motor.retraso(ritmo.get(n, {})))

    if saltadas:
        print(f"  {motor.plural(len(saltadas), 'cuenta')} sin tocar todavía: "
              + ", ".join(saltadas[:6])
              + (" ..." if len(saltadas) > 6 else ""))
    if not toca:
        print("\nNinguna cuenta toca hoy. 'ritmo' dice cuándo toca cada una.")
        return

    s = motor.crear_sesion()
    print(f"\n{motor.plural(len(toca), 'cuenta')} por mirar. Presupuesto "
          f"disponible: {motor.queda_presupuesto()} peticiones.\n")

    candidatas, sin_cambios, fallidas = [], [], []
    sin_sesion = 0

    # Primera vuelta: solo mirar. Una petición por cuenta, o ninguna si la
    # cuenta es pública y la página se deja leer sin sesión.
    for nombre in toca:
        motor._revisar_cancelacion()
        with motor.con_cuenta(nombre):
            print(f"  {nombre:<24}", end=" ", flush=True)
            try:
                # Mirar no necesita sesión: los totales están en la
                # página pública. Bajar sí. Así una ronda de vigilancia
                # sobre cuentas públicas puede costar CERO peticiones de
                # sesión, que es el gasto recurrente del proyecto.
                p, gasto = motor.solo_mirar(s, nombre)
                if not gasto:
                    sin_sesion += 1
            except motor.NoEncontrado as e:
                print(f"no accesible ({e})")
                fallidas.append(nombre)
                # Una cuenta borrada o cerrada no va a volver mañana: se
                # separa como cualquiera que no se mueve. Si no, se le
                # gastaría una petición al día para siempre.
                ritmo[nombre] = motor.ajustar_ritmo(ritmo.get(nombre, {}), False)
                continue
            except (motor.Bloqueado, motor.SinPresupuesto) as e:
                print(f"cortado: {e}")
                fallidas.append(nombre)
                # Aquí NO se toca el ritmo: que nos corten a nosotros no
                # dice nada de esta cuenta, y separarla sería castigarla
                # por algo que no ha hecho.
                break                # si corta con una, cortará con todas

            bajar, motivos = motor.decidir(p, args.umbral, args.max_dias)
            # El conteo de la pasada anterior hay que leerlo AQUÍ: la línea
            # siguiente lo reemplaza por el de hoy, y leerlo después daba
            # siempre "+0" en el aviso, pasara lo que pasara.
            previo_cuenta = motor._ultimo_conteo()
            motor._anotar_conteo(p)

            if not bajar:
                print(f"{p['seguidores']}/{p['seguidos']}   sin cambios")
                sin_cambios.append(nombre)
                continue

            cuales = "ambas" if len(bajar) == 2 else list(bajar)[0]
            coste = (motor.estimar_peticiones(p["seguidores"], p["seguidos"], cuales)
                     if p.get("totales_fiables", True) else 999)
            print(f"{p['seguidores']}/{p['seguidos']}   "
                  f"toca bajar {cuales} (~{coste})")
            candidatas.append({"nombre": nombre, "perfil": p, "bajar": bajar,
                               "cuales": cuales, "coste": coste,
                               "motivos": motivos,
                               "previo": previo_cuenta})

    if sin_sesion:
        print(f"\n  {motor.plural(sin_sesion, 'cuenta')} se pudieron mirar "
              "sin gastar sesión (página pública).")

    for nombre in sin_cambios:
        ritmo[nombre] = motor.ajustar_ritmo(ritmo.get(nombre, {}), False)
    # A las que sí cambiaron se les anota YA que se han mirado. Si luego no
    # cabe bajarlas en el presupuesto, se quedaban sin marcar y mañana
    # volvían a salir como atrasadas: una petición de sondeo tirada cada
    # día hasta que hubiera sitio.
    for c in candidatas:
        ritmo[c["nombre"]] = motor.ajustar_ritmo(ritmo.get(c["nombre"], {}), True)
    motor.guardar_ritmo(ritmo)

    if not candidatas:
        print(f"\nNada que descargar. {len(sin_cambios)} sin cambios"
              + (f", {len(fallidas)} no accesibles." if fallidas else "."))
        motor._log(f"todas: {len(sin_cambios)} sin cambios, "
             f"{len(fallidas)} fallidas")
        return

    # Segunda vuelta: descargar mientras quepa. Primero las más baratas,
    # para que un objetivo enorme no se coma el turno de los demás.
    candidatas.sort(key=lambda c: c["coste"])
    print(f"\n{len(candidatas)} por descargar. "
          f"Quedan {motor.queda_presupuesto()} peticiones.\n")

    hechas, aplazadas, con_novedad = [], [], []
    for c in candidatas:
        disponible = motor.queda_presupuesto()
        if c["coste"] > disponible:
            print(f"  {c['nombre']:<24} aplazada: ~{c['coste']} y quedan "
                  f"{disponible}")
            aplazadas.append(c["nombre"])
            continue
        with motor.con_cuenta(c["nombre"]):
            print(f"\n--- {c['nombre']} ---")
            try:
                for tipo in ("seguidores", "seguidos"):
                    if tipo in c["bajar"]:
                        motor.descargar(s, c["perfil"], tipo)
                hechas.append(c["nombre"])
                motor.cruzar_capturas(callado=True)
                lineas = motor._resumir_para_novedad(c["perfil"], c.get("previo"),
                                               c["bajar"])
                if lineas:
                    motor.anotar_novedad(c["nombre"], lineas)
                    con_novedad.append(c["nombre"])
                # Que haya novedad es la mejor señal de si esta cuenta se
                # mueve: es exactamente lo que se acaba de comprobar.
                ritmo[c["nombre"]] = motor.ajustar_ritmo(
                    ritmo.get(c["nombre"], {}), bool(lineas))
                motor.guardar_ritmo(ritmo)
            except motor.SinPresupuesto:
                print("  Se acabó el presupuesto a mitad. El progreso queda "
                      "guardado.")
                aplazadas.append(c["nombre"])
                break

    print("\n" + "=" * 62)
    print(f"Descargadas: {len(hechas)}   Sin cambios: {len(sin_cambios)}   "
          f"Aplazadas: {len(aplazadas)}")
    if aplazadas:
        print(f"  Para mañana: {', '.join(aplazadas)}")
    motor._log(f"todas: bajadas {hechas}, aplazadas {aplazadas}, "
         f"sin cambios {len(sin_cambios)}")
    if con_novedad:
        # Un aviso por pasada y no uno por cuenta: cinco globos seguidos no
        # se leen, se cierran.
        motor.avisar_al_sistema("FocusMedia",
                          "Novedades en "
                          + motor.plural(len(con_novedad), "cuenta") + ": "
                          + ", ".join(con_novedad[:5]))


def cmd_vigilar(args) -> None:
    """Comprueba los totales con UNA petición y baja solo si hace falta."""
    espera = getattr(args, "retraso", 0)
    if espera > 0:
        # Una tarea programada que salta siempre en el mismo segundo es de
        # las cosas que distinguen un programa de una persona. El retraso
        # se anuncia porque si no, parece que se ha colgado.
        segundos = random.randint(0, espera * 60)
        print(f"Esperando {segundos // 60} min {segundos % 60} s antes de "
              "empezar (retraso al azar).")
        motor._dormir(segundos)

    if getattr(args, "todas", False):
        return cmd_vigilar_todas(args)
    s = motor.crear_sesion()
    p = motor.perfil(s, motor.OBJETIVO)

    previo = motor._ultimo_conteo()
    def delta(tipo):
        return f"{p[tipo] - previo[tipo]:+d}" if previo else "primer conteo"

    print(f"\n@{p['username']}")
    print(f"  Seguidores: {p['seguidores']}   ({delta('seguidores')})")
    print(f"  Seguidos:   {p['seguidos']}   ({delta('seguidos')})")

    bajar, motivos = motor.decidir(p, args.umbral, args.max_dias)
    motor._anotar_conteo(p)

    resumen = (f"seguidores={p['seguidores']} ({delta('seguidores')})  "
               f"seguidos={p['seguidos']} ({delta('seguidos')})")

    if not bajar:
        print("\n  Sin cambios. No se descarga nada (ha costado 1 petición).")
        motor._log(f"{resumen}  ->  sin cambios")
        return

    print("\n  Hay que descargar:")
    for m_ in motivos:
        print(f"    - {m_}")

    if args.solo_mirar:
        print("\n  (--solo-mirar: no se descarga)")
        motor._log(f"{resumen}  ->  haría falta bajar {sorted(bajar)} (solo-mirar)")
        return

    problema = motor.avisar_si_privada(p)
    if problema and p.get("la_sigo") is False:
        print(f"\n  {problema}")
        motor._log(f"{resumen}  ->  ABORTADO: cuenta privada no seguida")
        return
    if problema:
        print(f"\n  Aviso: {problema}")

    cuales = "ambas" if len(bajar) == 2 else list(bajar)[0]
    cabe, explicacion = motor.comprobar_coste(p, cuales)
    print(f"  {explicacion}")
    if not cabe:
        print("  No se descarga hoy. Mañana se retoma solo.")
        motor._log(f"{resumen}  ->  aplazado: no cabe en el presupuesto")
        return

    try:
        for tipo in ("seguidores", "seguidos"):
            if tipo in bajar:
                motor.descargar(s, p, tipo)
    except KeyboardInterrupt:
        motor._log(f"{resumen}  ->  interrumpido a mitad")
        raise

    print("\n" + "=" * 62)
    print("QUÉ CAMBIÓ")
    seguidores = motor.comparar("seguidores") if "seguidores" in bajar else None
    seguidos = motor.comparar("seguidos") if "seguidos" in bajar else None
    if seguidores and seguidos:
        motor.relaciones(seguidores, seguidos)
        motor.cruzar_capturas()

    motor._log(f"{resumen}  ->  bajado {sorted(bajar)}")

    # Lo encontrado se guarda en la bandeja y se avisa. Es lo que faltaba
    # para que 'vigilar' sirva de verdad desatendido: hasta ahora dejaba
    # una línea en un log que nadie abre.
    lineas = motor._resumir_para_novedad(p, previo, bajar)
    if lineas:
        motor.anotar_novedad(motor.OBJETIVO, lineas)
        motor.avisar_al_sistema(f"FocusMedia · @{motor.OBJETIVO}", lineas[0])
        print(f"\n  Anotado en {motor._ruta_novedades().name}.")
    else:
        print("\n  Nada que avisar: la descarga no encontró cambios.")


def cmd_detalles(args) -> None:
    """
    Consulta el perfil completo de las cuentas de la lista de vigilancia.

    Una petición por cuenta, con pausas largas, tope duro y parada al primer
    bloqueo. No reintenta: si Instagram corta, es que hay que dejarlo.
    """
    motor.CARPETA.mkdir(parents=True, exist_ok=True)

    if args.crear:
        ruta = motor.crear_lista_vigilancia()
        cuentas, _ = motor.leer_lista_vigilancia()
        print(f"Lista en {ruta.name}"
              + (f" con {len(cuentas)} candidatos sacados de tus capturas."
                 if cuentas else " (vacía: añade cuentas a mano)."))
        print("Ábrela, deja solo las que te interesen y vuelve a ejecutar.")
        return

    cuentas, avisos = motor.leer_lista_vigilancia()
    for a in avisos:
        print(f"  Aviso: {a}")
    if not cuentas:
        print("No hay cuentas que consultar.")
        print("Ejecuta 'detalles --crear' para generar la lista.")
        return

    destino = motor._ruta_detalles()
    ya = {f["username"].lower() for f in motor._leer_csv(destino)
          if f.get("username")}
    pendientes = [c for c in cuentas if c.lower() not in ya]

    prudencia = motor.factor_prudencia()
    minima = motor.PAUSA_DETALLE_MIN * prudencia
    maxima = motor.PAUSA_DETALLE_MAX * prudencia

    print(f"Lista de vigilancia: {len(cuentas)} cuentas.")
    if ya:
        print(f"  {len(ya)} ya consultadas hoy, se saltan.")
    print(f"  Van a costar {len(pendientes)} peticiones, "
          f"a una cada {minima:.0f}-{maxima:.0f} s.")
    if prudencia > 1:
        print(f"  Ritmo reducido x{prudencia:.0f}: hoy ya hubo bloqueos.")

    disponible = motor.queda_presupuesto()
    print(f"  Quedan {disponible} peticiones hoy.")
    if len(pendientes) > disponible:
        print(f"  No caben las {len(pendientes)}. Se consultarán las "
              f"{disponible} primeras; el resto, mañana.")
        pendientes = pendientes[:disponible]
        if not pendientes:
            print("  Hoy no queda presupuesto. Vuelve mañana.")
            return

    if args.solo_listar:
        for c in pendientes:
            print(f"    {c}")
        print("  (--solo-listar: no se consulta nada)")
        return

    if not pendientes:
        print("  Nada que hacer: ya están todas.")
        return

    s = motor.crear_sesion()
    filas = motor._leer_csv(destino)
    hechas, fallidas = 0, []

    try:
        for i, cuenta in enumerate(pendientes, 1):
            motor._revisar_cancelacion()
            print(f"  [{i}/{len(pendientes)}] {cuenta}", end="  ", flush=True)
            try:
                fila = motor.perfil_detallado(s, cuenta)
            except motor.NoEncontrado:
                print("no existe o no es visible")
                fallidas.append(cuenta)
                continue
            filas.append(fila)
            hechas += 1
            print(f"{fila['seguidores']} seguidores, "
                  f"{fila['publicaciones']} publicaciones")
            motor._escribir_csv(destino, motor.CABECERA_DETALLE,
                          [motor._fila(f, motor.CABECERA_DETALLE) for f in filas])
            if i < len(pendientes):
                motor._dormir(random.uniform(minima, maxima))
    except motor.Bloqueado as e:
        print(f"\n  Cortado: {e}")
        print(f"  Se guardaron {hechas}. Vuelve a ejecutar más tarde: "
              "las ya consultadas hoy se saltan.")
        return
    except KeyboardInterrupt:
        print(f"\n  Parado. Se guardaron {hechas}.")
        raise

    print(f"\n  {hechas} perfiles en {destino.name}")
    if fallidas:
        print(f"  No se pudieron consultar: {', '.join(fallidas)}")


def cmd_sesion(args=None) -> None:
    pegada = getattr(args, "pegar", None)
    if pegada:
        cookies = motor.guardar_sesion_pegada(pegada,
                                        getattr(args, "etiqueta", "") or "")
        if not cookies:
            sys.exit("Ahí no hay ninguna sesión. Busca 'sessionid' en las "
                     "cookies de instagram.com y pega su valor.")
        quien = cookies.get("ds_user_id")
        # El valor NO se imprime: es la cuenta entera.
        print("Sesión guardada"
              + (f" (cuenta id {quien})" if quien else "") + ".")
        motor.crear_sesion()
        print("Listo. Ya puedes ejecutar 'contar' o 'bajar'.")
        return

    if getattr(args, "buscar", False):
        motor.migrar_sesiones()
        print("\nMirando los navegadores del equipo...")
        hallazgos = motor.buscar_sesiones()
        r = motor.resumir_busqueda(hallazgos)

        for h in r["encontradas"]:
            print(f"  {h['navegador']:<12} sesión de la cuenta id {h['id']}")
        if not r["encontradas"]:
            print("  ninguna sesión abierta encontrada")

        # Lo único sobre lo que se puede hacer algo va aparte y con qué
        # hacer. Antes se mezclaba con los navegadores que ni están, y
        # entonces no se distinguía «no lo tienes» de «lo tienes y no te
        # deja», que piden cosas muy distintas.
        for h in r["accionables"]:
            print(f"\n  {h['navegador']}: "
                  + motor.CONSEJOS.get(h["clase"], h["motivo"]))
        if r["ausentes"]:
            print(f"\n  No instalados: {', '.join(r['ausentes'])}")

        if not r["encontradas"]:
            return
        guardadas = motor.registrar_hallazgos(hallazgos)
        print(f"\n{motor.plural(len(guardadas), 'sesión', 'sesiones')} "
              f"guardadas en {motor.CARPETA_SESIONES.name}/.")
        print("  La que se usa NO ha cambiado. Se elige con "
              "'sesion --usar ID'.")
        return

    if getattr(args, "listar", False):
        datos = motor.leer_sesiones()
        if not datos["cuentas"]:
            print("\nNo hay ninguna sesión guardada.")
            return
        print(f"\n{motor.plural(len(datos['cuentas']), 'sesión', 'sesiones')} "
              "guardadas:")
        for clave, d in datos["cuentas"].items():
            marca = "*" if clave == datos.get("activa") else " "
            etiqueta = d.get("etiqueta") or ""
            print(f"  {marca} {clave:<14} {etiqueta:<16} "
                  f"guardada el {d.get('guardado', '')[:16]}")
        print("\n  * = la que se usa. Cambiar con: sesion --usar ID")
        print("  Cambiar de sesión NO da presupuesto nuevo: el límite es de")
        print("  la sesión Y de la IP, y la IP no cambia.")
        return

    usar = getattr(args, "usar", None)
    if usar:
        if not motor.activar_sesion(usar):
            sys.exit(f"No hay ninguna sesión guardada con id '{usar}'. "
                     "Míralas con 'sesion --listar'.")
        print(f"Ahora se usa la sesión {usar}.")
        motor.crear_sesion()
        print("Listo.")
        return

    quitar = getattr(args, "quitar", None)
    if quitar:
        if not motor.quitar_sesion(quitar):
            sys.exit(f"No hay ninguna sesión guardada con id '{quitar}'.")
        print(f"Sesión {quitar} borrada.")
        return

    cuales = getattr(args, "comprobar_estas", None)
    if cuales:
        # Comprobar es lo que le pone NOMBRE a cada sesión: hasta que no se
        # hace, la lista son números. Cuesta una petición por cuenta y se
        # dice antes de gastarla.
        for clave in cuales:
            usuario, estado = motor.comprobar_guardada(clave)
            if usuario and not str(usuario).startswith("#"):
                print(f"  {clave}: @{usuario}")
            elif estado == "ok":
                print(f"  {clave}: sirve, pero no dice el nombre")
            else:
                print(f"  {clave}: no sirve ({estado})")
        return

    if getattr(args, "comprobar", False):
        # Comprobar la que hay, sin volver al navegador: si se forzara,
        # se pisaría una sesión escrita a mano con la del navegador, que
        # es justo la que no funcionaba.
        motor.crear_sesion()
    else:
        motor.crear_sesion(forzar=True)
    print("Listo. Ya puedes ejecutar 'contar' o 'bajar'.")


def cmd_contar(_) -> None:
    # Sin sesión también se puede: los datos del perfil están en la página
    # pública. Antes esto exigía sesión para algo que no la necesita, y
    # dejaba a quien aún no la había importado sin poder comprobar nada.
    p = None
    if not motor._cookies_guardadas():
        # Sin sesión guardada se prueba la página pública, que no la
        # necesita. Si tampoco responde, se sigue por el camino de
        # siempre: rendirse aquí quitaría la vía que ya funcionaba.
        p = motor.perfil_anonimo(motor.OBJETIVO)
        if p:
            print("  (sin sesión: leído de la página pública de la cuenta)")
    if p is None:
        s = motor.crear_sesion()
        p = motor.perfil(s, motor.OBJETIVO)
    previo = motor._ultimo_conteo()

    print(f"\n@{p['username']}  {p['nombre']}")
    for tipo in ("seguidores", "seguidos"):
        cambio = f"   ({p[tipo] - previo[tipo]:+d})" if previo else ""
        print(f"  {tipo.capitalize():14}{p[tipo]}{cambio}")
    if p.get("publicaciones"):
        antes = (previo or {}).get("publicaciones")
        cambio = f"   ({p['publicaciones'] - antes:+d})" if antes else ""
        print(f"  {'Publicaciones':14}{p['publicaciones']}{cambio}")
    # Todo lo que la página trae y hasta ahora se tiraba. Cada línea sale
    # solo si hay dato: una etiqueta con el hueco vacío no informa de
    # nada y encima parece un fallo.
    for clave, etiqueta in (("id", "Id"), ("enlace", "Enlace"),
                            ("pronombres", "Pronombres"),
                            ("threads", "Threads")):
        if p.get(clave):
            print(f"  {etiqueta:14}{str(p[clave])[:56]}")
    if p.get("verificada"):
        print(f"  {'Verificada':14}sí")
    if p.get("memorial"):
        print(f"  {'Memorial':14}sí (cuenta conmemorativa)")
    if p.get("desactivada"):
        print(f"  {'Desactivada':14}sí")
    if p.get("foto") and not motor.foto_al_dia(motor.OBJETIVO):
        # La URL viene en la propia página, así que la foto también se
        # puede guardar sin sesión. Y si cambió, la anterior se archiva.
        if motor.guardar_foto(motor.sesion_anonima(), motor.OBJETIVO,
                              p["foto"]):
            print(f"  {'Foto':14}guardada")
    if p.get("biografia"):
        lineas_bio = str(p["biografia"]).splitlines()
        print(f"  {'Biografía':14}{lineas_bio[0][:56]}")
        for extra in lineas_bio[1:4]:
            print(f"  {'':14}{extra[:56]}")
    if p.get("totales_fiables") is False:
        # Las metas redondean. Decirlo, porque quien mire esas cifras va a
        # compararlas con las de Instagram y no van a cuadrar.
        print("  (cifras aproximadas: vinieron de las etiquetas de la "
              "página, que redondean)")
    if p["privada"]:
        # `la_sigo` vale None cuando los datos vinieron de la página, que
        # no lo dice. Con `if p["la_sigo"]` eso caía en «NO la sigues»:
        # afirmar lo que no se sabe, el mismo fallo que el de «privada».
        if p["la_sigo"] is True:
            print("  Cuenta privada (y la sigues)")
        elif p["la_sigo"] is False:
            print("  Cuenta privada y NO la sigues")
        else:
            print("  Cuenta privada; no consta si la sigues")

    motor._anotar_conteo(p)
    print(f"\n  Anotado en {motor._ruta_totales().name}")


def cmd_inspeccionar(args) -> None:
    """
    Gasta UNA petición, guarda la respuesta cruda y lista los campos reales.

    Existe porque los campos que manda Instagram no están documentados y
    cambian. En vez de suponer cuáles hay, se miran.
    """
    s = motor.crear_sesion()
    p = motor.perfil(s, motor.OBJETIVO)
    endpoint = "followers" if args.lista == "seguidores" else "following"

    d = motor.pedir(s, f"/api/v1/friendships/{p['id']}/{endpoint}/",
              {"count": motor.POR_PAGINA})

    motor.carpeta_cuenta().mkdir(parents=True, exist_ok=True)
    crudo = motor.carpeta_cuenta() / f"crudo_{motor.OBJETIVO}_{args.lista}.json"
    # Respuesta cruda de la API, con sesión. Se guarda para poder mirar
    # qué campos manda Instagram; el token que pudiera traer no hace falta
    # para eso, y este archivo se comparte al pedir ayuda.
    motor.escribir_atomico(crudo, motor.registro.limpiar_secretos(
        json.dumps(d, indent=2, ensure_ascii=False)))

    usuarios = d.get("users") or []
    print(f"\nRespuesta cruda guardada en {crudo.name}")
    print(f"Muestra: {len(usuarios)} usuarios de {args.lista} de @{motor.OBJETIVO}")

    otras = [k for k in d if k != "users"]
    if otras:
        print("\nCampos de la respuesta (fuera de 'users'):")
        for k in otras:
            print(f"  {k} = {motor._ejemplo(d[k])}")

    if not usuarios:
        print("\nLa respuesta no traía usuarios; no hay campos que analizar.")
        return

    planos = [motor._aplanar(u) for u in usuarios]
    claves = sorted({k for u in planos for k in u})
    guardados = {"username", "full_name", "pk", "id"}
    guardados |= {ruta for _, ruta in motor.CAMPOS_EXTRA}

    print(f"\n{'CAMPO':38} {'PRESENTE':>9}  {'TIPO':8} EJEMPLO")
    print("-" * 78)
    nuevos = []
    for k in claves:
        con = [u[k] for u in planos if k in u and u[k] is not None]
        if not con:
            continue
        marca = "*" if k in guardados else " "
        print(f"{marca}{k:37} {len(con):>4}/{len(planos):<4} "
              f"{motor._tipo_legible(con[0]):8} {motor._ejemplo(con[0])}")
        if k not in guardados and isinstance(con[0], (bool, int, str)):
            nuevos.append(k)

    print("-" * 78)
    print("*  = el módulo ya lo guarda en las capturas")

    faltan = [ruta for _, ruta in motor.CAMPOS_EXTRA
              if not any(ruta in u for u in planos)]
    if faltan:
        print(f"\nCampos que el módulo espera y NO llegaron: {', '.join(faltan)}")
        print("Sus columnas saldrán vacías. Quítalos de CAMPOS_EXTRA si molesta.")

    if nuevos:
        print(f"\nCampos disponibles que NO se están guardando ({len(nuevos)}):")
        print("  " + ", ".join(nuevos[:20]))
        print("\nPara guardar alguno, añádelo a CAMPOS_EXTRA arriba del archivo:")
        print(f'    ("mi_columna", "{nuevos[0]}"),')
        print("Se guardará desde la siguiente descarga, sin peticiones extra.")


def cmd_contratos(args) -> None:
    """Qué se espera de cada respuesta y por qué rutas. Sin peticiones."""
    if getattr(args, "crear", False):
        destino = motor.escribir_config_ejemplo()
        print(f"\nConfiguración en {destino}")
        print("Edita solo lo que haga falta y reinicia el programa.")
        print("Lo que borres vuelve a su valor de serie.")
        return

    c = motor.config()
    archivo = motor._ruta_config()
    print(f"\nRUTAS  {'(de ' + archivo.name + ')' if archivo.exists() else '(de serie)'}")
    for clave, valor in c["rutas"].items():
        marca = " *" if valor != motor.RUTAS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    print("\nNOMBRES DE PARÁMETROS")
    for clave, valor in c["params"].items():
        marca = " *" if valor != motor.PARAMS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    print("\nNOMBRES DE CAMPOS EN LA RESPUESTA")
    for clave, valor in c["campos"].items():
        marca = " *" if valor != motor.CAMPOS_BASE.get(clave) else "  "
        print(f" {marca} {clave:20} {valor}")

    if not archivo.exists():
        print("\n  Para poder cambiarlos:  contratos --crear")
        print(f"  Escribe {archivo.name} y ahí se edita sin tocar código.")
    else:
        print("\n  * = cambiado respecto al valor de serie")

    print("\nLo que este programa necesita de cada respuesta de Instagram.")
    print("Si algo cambia de forma, aquí se ve qué se estaba esperando.\n")
    for clave, c in motor.CONTRATOS.items():
        print(f"  {clave}  ({c.nombre})")
        for ruta, tipos in c.campos:
            print(f"      {ruta:34} {motor.Contrato._nombres(tipos)}")
        if c.coleccion:
            print(f"      {c.coleccion:34} lista")
            for ruta, tipos in c.campos_elemento:
                print(f"        · {ruta:32} {motor.Contrato._nombres(tipos)}")
            for rutas, tipos in c.alternativas_elemento:
                print(f"        · {' o '.join(rutas):32} "
                      f"{motor.Contrato._nombres(tipos)}")
        print()
    print("  Los campos que Instagram añada NO rompen nada: solo se exige")
    print("  que esté lo de arriba.")


def cmd_diagnostico(args) -> None:
    """
    Prueba cada endpoint por separado y dice cuál responde.

    Existe porque suponer qué falla sale caro: se descubrió que
    web_profile_info devuelve 429 a la PRIMERA petición mientras friendships
    contesta 200. Sin medirlo, eso parecía "me han limitado la cuenta".
    """
    s = motor.crear_sesion()
    mi_id = s.cookies.get("ds_user_id") or "0"
    objetivo = motor.OBJETIVO

    # Cada prueba comprueba también la FORMA, no solo que conteste: un 200
    # con la estructura cambiada es peor que un error, porque pasa por bueno.
    pruebas = [
        ("Tu propia lista de seguidos (lo que usa la descarga)",
         lambda: motor.validar("lista", motor.pedir(
             s, motor.ruta("lista_seguidos", id=mi_id),
             {motor.param("cantidad"): 1}))),
        ("Tus datos de cuenta",
         lambda: motor.pedir(s, motor.ruta("sesion_actual"))),
        ("Perfil por API (web_profile_info)",
         lambda: motor.validar("perfil", motor.pedir(
             s, motor.ruta("perfil"), {motor.param("usuario"): objetivo},
             referer=motor.BASE + motor.ruta("pagina_perfil", usuario=objetivo)))),
        ("Perfil por su página web",
         lambda: motor.perfil_desde_html(s, objetivo)),
        ("Buscador",
         lambda: motor.perfil_desde_busqueda(s, objetivo)),
    ]

    print(f"\nProbando {len(pruebas)} vías, una cada 5 s. Cuenta: @{objetivo}")
    print("-" * 62)
    funcionan, cambiadas = [], []

    for i, (nombre, probar) in enumerate(pruebas):
        motor._revisar_cancelacion()
        print(f"  {nombre:52}", end=" ", flush=True)
        try:
            probar()
            print("OK")
            funcionan.append(nombre)
        except motor.NoEncontrado as e:
            print(f"no encontrado ({e})")
        except motor.RespuestaInesperada as e:
            # Es el caso que más importa detectar: contesta, pero ya no
            # sirve. Se enseña el detalle para poder ajustar el contrato.
            print("CAMBIÓ DE FORMA")
            print(f"      {e}")
            cambiadas.append(nombre)
        except motor.Bloqueado as e:
            texto = str(e)
            print("BLOQUEADO" if "429" in texto else f"falla ({texto[:40]})")
        except Exception as e:                       # noqa: BLE001
            print(f"error ({type(e).__name__})")
        if i < len(pruebas) - 1:
            motor._dormir(5)

    print("-" * 62)
    if not funcionan:
        print("No responde nada. La sesión puede haber caducado: vuelve a")
        print("importarla desde el navegador.")
        return

    print(f"Funcionan {len(funcionan)} de {len(pruebas)}:")
    for f in funcionan:
        print(f"  - {f}")
    if cambiadas:
        print(f"\nCambiaron de forma ({len(cambiadas)}): "
              f"{', '.join(cambiadas)}")
        print("  Contestan, pero ya no traen lo que hace falta. Eso no se")
        print("  arregla esperando: hay que ajustar el contrato en CONTRATOS.")

    descarga = any("descarga" in f for f in funcionan)
    perfil_ok = any("Perfil" in f for f in funcionan)
    print()
    if descarga and perfil_ok:
        print("Todo lo necesario responde. Puedes descargar las listas.")
    elif descarga:
        print("El endpoint de listas responde, pero no se puede leer el")
        print("perfil por ninguna vía. Sin el identificador de la cuenta no")
        print("se puede empezar. Prueba dentro de un rato.")
    else:
        print("El endpoint de listas NO responde. Con eso bloqueado no hay")
        print("descarga posible: espera unas horas antes de reintentar.")


def cmd_presupuesto(args) -> None:
    """Cuántas peticiones se han gastado hoy y en qué."""
    p = motor._presupuesto()
    hechas = p.get("hechas", 0)
    print(f"\nDía {p.get('dia')}")
    print(f"  Peticiones: {hechas} de {motor.tope_diario()}  "
          f"(quedan {motor.queda_presupuesto()})")
    if p.get("primera"):
        print(f"  Entre las {p['primera']} y las {p['ultima']}")
    if p.get("bloqueos"):
        print(f"  Bloqueos recibidos: {p['bloqueos']}   "
              f"-> las pausas van x{motor.factor_prudencia():.0f}")

    if p.get("por_endpoint"):
        print("\n  Reparto:")
        for clave, n in sorted(p["por_endpoint"].items(),
                               key=lambda x: -x[1]):
            print(f"    {n:>5}  {clave}")

    aprendido = p.get("aprendido", {})
    if aprendido:
        print("\n  Vías que funcionan (no se vuelven a probar las otras):")
        for asunto, valor in aprendido.items():
            print(f"    {asunto}: {valor}")

    if hechas >= motor.tope_diario() * motor.AVISO_AL:
        print("\n  Vas justo. Deja las descargas grandes para mañana.")


def _veredicto_del_sello(archivos: dict) -> None:
    """
    Contrasta el `timestamp` del export contra el historial propio.

    El lector guarda ese campo como «te_sigue_desde», que es AFIRMAR que
    es la fecha del follow. Nadie lo había comprobado nunca. Esto lo
    comprueba con lo único que puede desmentirlo: las capturas de aquí.
    """
    enriquecido = export_instagram.enriquecimiento(archivos)
    trayectorias = motor.construir_historial("seguidores") or {}
    v = export_instagram.contrastar(enriquecido, trayectorias)

    print("\n¿EL «timestamp» ES LA FECHA DEL FOLLOW?")
    print("  " + motor.plural(v["con_sello"], "sello") + ", "
          + motor.plural(v["fechas_distintas"], "fecha distinta",
                         "fechas distintas")
          + (f", del {v['desde']} al {v['hasta']}" if v["desde"] else ""))
    print(f"  Cotejables con tu historial: {v['cotejables']}")

    if v["veredicto"] == "sin_datos":
        print("  No hay bastante para decir nada. Hacen falta al menos diez")
        print("  personas que estén en el export Y en tus capturas; descarga")
        print("  las listas y vuelve a importar.")
    elif v["veredicto"] == "no_es_la_fecha_del_follow":
        print(f"  NO lo es: {v['imposibles']} sellos son POSTERIORES a la "
              "primera captura")
        print("  en la que esa persona ya aparecía. No se puede empezar a "
              "seguir a")
        print("  alguien después de que ya te siguiera.")
        for e in v["ejemplos"]:
            print(f"    {e}")
    elif v["veredicto"] == "sospechoso_todas_el_mismo_dia":
        print("  Probablemente NO: casi todos los sellos caen en la misma "
              "fecha.")
        print("  Eso es la fecha en que se generó el export o en que Meta "
              "migró los")
        print("  datos, no la de cada relación.")
    else:
        print("  Compatible: se reparten por el calendario y ninguno es "
              "posterior")
        print("  a cuando ya veíamos a esa persona. No lo demuestra, pero "
              "es lo que")
        print("  se vería si lo fuera.")


def cmd_importar(args) -> None:
    """
    Lee la exportación oficial de Instagram. 0 peticiones, riesgo cero.

    Por defecto solo MIRA y cuenta lo que hay. Guardar es otra orden, y va
    aparte a propósito: hasta no ver un ZIP real no se sabe si el sello de
    tiempo es la fecha del follow o cualquier otra cosa.
    """
    ruta = Path(args.archivo).expanduser()
    if not ruta.exists():
        sys.exit(f"No existe '{ruta}'.")

    try:
        archivos = motor.abrir_export(ruta)
    except Exception as e:
        sys.exit(f"No se pudo abrir '{ruta.name}': {e}")

    if not archivos:
        print(f"\nEn '{ruta.name}' no hay ninguna lista de seguidores.")
        print("  Comprueba dos cosas al pedir el export:")
        print("    - formato JSON, no HTML")
        print("    - marcada la sección «Followers and following»")
        return

    r = export_instagram.resumen(archivos)
    print(f"\nDENTRO DE {ruta.name}")
    for tipo, nombres in r["archivos"].items():
        print(f"  {tipo:12} {r['cuantos'].get(tipo, 0):>6} en "
              + motor.plural(len(nombres), "archivo") + ": "
              + ", ".join(nombres[:4]))

    print("\nQUÉ TRAE CADA PERSONA")
    print("  username, href, timestamp")
    if r["campos_extra"]:
        print(f"  y además: {', '.join(r['campos_extra'])}")
    else:
        print("  y nada más: NO hay id numérico, solo el nombre de usuario.")
    if r["posibles_ids"]:
        print(f"  OJO: {', '.join(r['posibles_ids'])} parecen "
              "identificadores. Merece la pena mirarlos.")

    print("\nLAS MARCAS DE TIEMPO")
    if r["con_sello"]:
        print(f"  {r['con_sello']} con sello, {r['sin_sello']} sin él.")
        print(f"  Van del {r['primera_fecha']} al {r['ultima_fecha']}.")
        # Antes esto pedía juzgar a ojo: «si ese rango cuadra con cuándo te
        # siguió la gente...». Se puede medir, y pedir que lo adivine quien
        # mira es lo que este proyecto lleva versiones quitando.
        _veredicto_del_sello(archivos)
    else:
        print("  Ninguna. Sin ellas, el export solo aporta las listas.")

    if not args.guardar:
        print("\n  No se ha guardado nada. Añade --guardar para hacerlo.")
        return

    if not motor.OBJETIVO or motor.OBJETIVO == "cuenta_objetivo":
        sys.exit("Falta la cuenta: usa --cuenta X. El export es de TU "
                 "cuenta, no de las que vigilas.")

    datos = export_instagram.enriquecimiento(archivos)
    datos["importado"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    datos["origen"] = ruta.name
    destino = motor.ruta_enriquecimiento(motor.OBJETIVO)
    destino.parent.mkdir(parents=True, exist_ok=True)
    motor.escribir_atomico(destino,
                     json.dumps(datos, ensure_ascii=False, indent=2))

    print(f"\n  Guardado en {destino.name} como enriquecimiento de "
          f"@{motor.OBJETIVO}.")
    print("  NO es una captura y no entra en la serie: sin id numérico,")
    print("  meterlo ahí degradaría el historial entero a claves por")
    print("  nombre de usuario, y los nombres cambian.")


def cmd_informe(_) -> None:
    """Escribe el informe HTML. 0 peticiones."""
    import informe_html

    datos = motor.recopilar_informe()
    destino = motor.carpeta_cuenta() / f"informe_{motor.OBJETIVO}_{date.today()}.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    motor.escribir_atomico(destino, informe_html.generar(datos))

    filas = sum(d.get("total", 0) for d in datos["listas"].values())
    print(f"\n  Informe: {destino}")
    print(f"  {filas} filas, {len(datos.get('cambios') or [])} cambios de "
          "relación. Se abre con doble clic; no necesita internet.")


def cmd_limite(args) -> None:
    """Qué tope está en uso, por qué, y cómo se ha ido moviendo."""
    limite = motor._limite()
    if args.fijar:
        nuevo = max(motor.SUELO_TOPE, min(motor.TECHO_TOPE, args.fijar))
        limite["tope"] = nuevo
        motor.CARPETA.mkdir(parents=True, exist_ok=True)
        motor.escribir_atomico(motor._ruta_limite(),
                         json.dumps(limite, ensure_ascii=False, indent=2))
        print(f"\nTope fijado a {nuevo}. Seguirá ajustándose solo "
              "desde ahí.")
        return

    if args.prudente or args.normal:
        limite["prudente"] = bool(args.prudente)
        motor.CARPETA.mkdir(parents=True, exist_ok=True)
        motor.escribir_atomico(motor._ruta_limite(),
                         json.dumps(limite, ensure_ascii=False, indent=2))
        print("\nModo prudente ACTIVADO: el tope solo bajará."
              if args.prudente else
              "\nModo normal: el tope vuelve a tantear hacia arriba.")
        return

    print(f"\nTOPE EN USO: {motor.tope_diario()} peticiones al día"
          + ("   (modo prudente: solo baja)"
             if limite.get("prudente") else ""))
    print(f"  Tope por hora: {motor.TOPE_HORA}. Se para el día tras "
          + motor.plural(motor.RECHAZOS_PARA_PARAR, "rechazo") + " (HTTP 401/403).")
    historial = limite.get("historial") or []
    if not historial:
        print(f"  Todavía sin medir: es el valor de partida ({motor.TOPE_DIARIO}).")
        print("  Se ajusta solo al cerrarse cada día.")
        return

    print(f"\n  {'DÍA':12} {'HECHAS':>7} {'TOPE':>6} {'BLOQ':>5}  POR QUÉ")
    print("  " + "-" * 68)
    for d in historial[-14:]:
        print(f"  {d['dia']:12} {d.get('hechas', 0):>7} "
              f"{d.get('tope', 0):>6} {d.get('bloqueos', 0):>5}  "
              f"{d.get('motivo', '')}")

    limpios = sum(1 for d in historial if not d.get("bloqueos"))
    print(f"\n  {motor.plural(len(historial), 'día')} medidos, {limpios} sin "
          "bloqueos.")
    print("  Sube " + motor.plural(motor.PASO_TOPE, "petición", "peticiones")
          + " tras un día limpio y apurado.")
    print(f"  Tras un bloqueo cae al {int(motor.CAIDA_TOPE * 100)}% y anota el "
          "borde; luego deja de empujarlo.")
    print("  Un día flojo no cambia nada: no prueba dónde está el borde.")


def cmd_copia(args) -> None:
    """
    Guarda o restaura los datos de una cuenta. 0 peticiones.

    Una captura de hace tres semanas no se recupera con ninguna petición:
    esa lista ya no existe en ningún sitio.
    """
    if args.restaurar:
        archivo = Path(args.restaurar).expanduser()
        if not archivo.exists():
            sys.exit(f"No existe '{archivo}'.")
        man = copia.leer_manifiesto(archivo)
        if not man:
            sys.exit(f"'{archivo.name}' no parece una copia de FocusMedia.")
        print(f"\nCopia de @{man['cuenta']}, hecha el "
              f"{man.get('creada', '')[:16].replace('T', ' ')}: "
              f"{man.get('archivos', 0)} archivos.")
        try:
            r = copia.restaurar(archivo, args.cuenta, args.reemplazar)
        except ValueError as e:
            sys.exit(f"\n{e}")

        print(f"  Traídos {len(r['traidos'])} a {r['destino'].name}/")
        if r["saltados"]:
            print(f"  Respetados {len(r['saltados'])} que ya estaban. "
                  "Pueden ser más nuevos que la copia;")
            print("  añade --reemplazar solo si de verdad quieres pisarlos.")
        if r["rotos"]:
            print(f"  Ignoradas {len(r['rotos'])} rutas raras del zip.")
        return

    try:
        ruta, man = copia.crear(motor.OBJETIVO, args.en)
    except (FileNotFoundError, OSError) as e:
        sys.exit(f"\nNo se pudo: {e}")
    print(f"\nCopia de @{man['cuenta']}: {ruta}")
    print(f"  {man['archivos']} archivos, {man['capturas']} capturas, "
          f"{man['bytes'] / 1e6:.1f} MB sin comprimir.")
    print("  No lleva sesiones dentro: se puede llevar a otro equipo.")


def cmd_comun(args) -> None:
    """Qué audiencia comparten dos cuentas que ya tienes descargadas."""
    conocidas = motor.leer_cuentas()
    for cuenta in (args.a, args.b):
        if cuenta not in conocidas:
            print(f"  Aviso: @{cuenta} no está en cuentas.txt; se mira "
                  "igual por si tienes capturas suyas.")
    if args.a == args.b:
        sys.exit("Son la misma cuenta.")
    motor.comun(args.a, args.b, args.lista, args.forzar)


def cmd_grafo(args) -> None:
    """Exporta a GraphML quién aparece en el círculo de qué cuentas."""
    cuentas = args.cuentas or sorted(motor.leer_cuentas())
    if len(cuentas) < 2:
        sys.exit("Hacen falta al menos dos cuentas con capturas.\n"
                 "Las que sigues salen con 'cuentas'.")

    g = motor.construir_grafo(cuentas, args.lista, args.forzar)
    for cuenta, motivo in g["fuera"]:
        print(f"  @{cuenta} se queda fuera: {motivo}")
    dentro = [n for n in g["nodos"].values() if n["clase"] == "objetivo"]
    if len(dentro) < 2:
        sys.exit("\nNo quedan dos cuentas utilizables.")

    if g["mezcla_de_claves"]:
        # Antes de enseñar ningún número: con esta mezcla, el número que
        # más importa —en cuántas está cada persona— es falso por abajo.
        print("\n  ATENCIÓN: " + ", ".join(f"@{c}" for c in g["sin_id"])
              + " no guarda ids y las demás sí.")
        print("  La misma persona sale como DOS nodos, y los puentes de "
              "abajo salen de menos.")
        print("  Vuelve a bajar esa(s) lista(s) para que el grafo cuadre.")
    elif g["sin_id"]:
        print("\n  Nota: ninguna captura guarda ids, así que se cruza por "
              "nombre de usuario:")
        print("  quien se haya cambiado el nombre aparecerá como otra "
              "persona.")

    personas = [n for n in g["nodos"].values() if n["clase"] == "persona"]
    print(f"\nGRAFO   {len(dentro)} cuentas  x  {len(personas)} personas  "
          f"x  {len(g['aristas'])} aristas")

    # Lo que de verdad se le pregunta a esto: quién está en varias.
    puentes = sorted((n for n in personas if n["en_cuantas"] > 1),
                     key=lambda n: (-n["en_cuantas"], n["etiqueta"].lower()))
    if puentes:
        print(f"\n  EN VARIAS A LA VEZ: {len(puentes)} "
              f"({len(puentes) * 100 // max(len(personas), 1)}% del total)")
        for n in puentes[:motor.MAX_LISTADO]:
            print(f"    {n['etiqueta']:<28} en {n['en_cuantas']}")
        if len(puentes) > motor.MAX_LISTADO:
            print(f"    ... y {len(puentes) - motor.MAX_LISTADO} más")
    else:
        print("\n  Nadie aparece en más de una: las audiencias no se tocan.")

    destino = motor.CARPETA / f"grafo_{args.lista}_{date.today()}.graphml"
    motor.escribir_atomico(destino, motor.a_graphml(g))
    print(f"\n  Guardado: {destino.name}")
    print("  Se abre con Gephi, yEd o Cytoscape. Cada nodo lleva 'clase' "
          "(objetivo o\n  persona) y 'en_cuantas', que es lo que conviene "
          "usar para el tamaño.")
    print("\n  Ojo con lo que se le pide: NO hay aristas entre personas "
          "—eso serían\n  las listas de cada una, decenas de miles de "
          "peticiones—, así que las\n  comunidades y la intermediación "
          "que calcule Gephi saldrían de aristas\n  que no existen. Para "
          "solapamiento de audiencias sí vale.")


def cmd_estudio(args) -> None:
    """
    Lo que el disco ya puede responder, sin gastar una sola petición.

    No hay likes ni comentarios: este proyecto nunca los ha descargado.
    Todo lo de aquí sale del índice de presencia y de la serie de totales.
    """
    tipo = args.lista
    t = motor.construir_historial(tipo, args.incluir_sospechosas) or {}
    fechas = t.get("fechas") or []
    if len(fechas) < 2:
        sys.exit("Hacen falta al menos dos capturas. Descarga otro día.")

    print(f"\nESTUDIO DE {tipo.upper()}   @{motor.OBJETIVO}   "
          f"{len(fechas)} capturas, del {fechas[0]} al {fechas[-1]}")

    # --- Lo primero, la salud: lo demás se apoya en esto --------------
    agujeros = analitica.huecos(fechas, args.tope_hueco)
    if agujeros:
        peor = max(agujeros, key=lambda h: h["dias"])
        print(f"\n  HUECOS: {len(agujeros)}, el mayor de "
              f"{motor.plural(peor['dias'], 'día')} "
              f"({peor['desde']} -> {peor['hasta']})")
        print("  Todo lo de abajo se mide sobre este calendario: quien "
              "entró y se fue")
        print("  dentro de un hueco no aparece, y los cambios salen "
              "fechados el día")
        print("  que se volvió a mirar.")

    # --- Cohortes: lo que nadie más puede decirte ---------------------
    c = analitica.cohortes(t)
    if c:
        print("\n  DE LOS QUE ENTRARON CADA MES, CUÁNTOS SIGUEN")
        for fila in c[-12:]:
            barra = "#" * (fila["retencion"] // 5)
            print(f"    {fila['mes']}   {fila['entraron']:>5} entraron   "
                  f"{fila['siguen']:>5} siguen   {fila['retencion']:>3}% "
                  f"{barra}")
        print("    (no cuenta a quien ya estaba en la primera captura: "
              "estaba, pero")
        print("     no se sabe desde cuándo)")

    # --- Permanencia --------------------------------------------------
    p = analitica.permanencia(t)
    if p["casos"]:
        print(f"\n  CUÁNTO DURA QUIEN SE ACABA YENDO   ({p['casos']} casos)")
        print(f"    Mediana: {motor.plural(int(p['mediana']), 'día')}    "
              f"Media: {p['media']}    "
              f"De {p['min']} a {p['max']}")
        print(f"    Menos de una semana: {p['menos_de_7']}    "
              f"Más de tres meses: {p['mas_de_90']}")
        print("    (solo los que YA se fueron y estuvieron una sola vez: "
              "contar a los que")
        print("     siguen dentro bajaría la cifra, y de los que van y "
              "vienen solo se")
        print("     sabe la primera y la última fecha, así que contaría "
              "el tiempo fuera)")
        if p.get("aparte"):
            print(f"    {motor.plural(p['aparte'], 'persona')} con idas y "
                  "venidas quedan fuera de esta media.")

    # --- Los que vuelven ----------------------------------------------
    r = analitica.recurrentes(t)
    if r:
        print(f"\n  SE FUERON Y VOLVIERON: {len(r)}")
        for fila in r[:motor.MAX_LISTADO]:
            print(f"    {fila['username']:<28} {fila['veces']} estancias")
        if len(r) > motor.MAX_LISTADO:
            print(f"    ... y {len(r) - motor.MAX_LISTADO} más")

    # --- Composición de la audiencia ----------------------------------
    # La última UTILIZABLE, no la última a secas: una captura truncada
    # daría los porcentajes de media lista y con pinta de buenos. Es el
    # mismo criterio que usan comparar y cruzar.
    ruta, motivo = motor.ultima_utilizable(tipo, args.incluir_sospechosas)
    if ruta is None:
        print(f"\n  CÓMO ES ESA GENTE: no se puede decir ({motivo})")
    else:
        comp = analitica.composicion(motor._leer_csv(ruta))
        print(f"\n  CÓMO ES ESA GENTE   ({comp['total']} en la captura del "
              f"{motor._fecha_de(ruta)})")
        for campo, etiqueta in (("privada", "privadas"),
                                ("verificada", "verificadas"),
                                ("foto_defecto", "sin foto de perfil")):
            d = comp[campo]
            if d["porcentaje"] is None:
                print(f"    {etiqueta:<20} sin datos en esta captura")
            else:
                extra = (f"  ({d['sin_dato']} sin dato)"
                         if d["sin_dato"] else "")
                print(f"    {etiqueta:<20} {d['porcentaje']:>3}%  "
                      f"({d['si']} de {d['con_dato']}){extra}")

    # --- Publicar contra crecer ---------------------------------------
    totales = motor._filas_totales()
    pc = analitica.publicar_vs_crecer(totales)
    if pc["tramos"]:
        print("\n  PUBLICAR Y CRECER")
        if not pc["bastante"]:
            print(f"    Todavía no hay bastante: {pc['con']} tramos con "
                  f"publicación y {pc['sin']} sin.")
            print("    Hacen falta al menos 5 de cada para que la "
                  "diferencia no sea ruido.")
        else:
            print(f"    Con publicación nueva: {pc['media_con']:+} "
                  "seguidores al día")
            print(f"    Sin publicación:       {pc['media_sin']:+} "
                  "seguidores al día")
            print(f"    Diferencia: {pc['diferencia']:+}")
            print("    Es una diferencia de medias, y nada más. Puede que "
                  "publiques")
            print("    porque estás creciendo, y no al revés.")

    print("\n  Nada de esto ha gastado una petición: sale del índice y de "
          "los totales.")


def _recoger_salud() -> dict:
    """Junta en un diccionario lo que hoy exige cinco comandos."""
    presupuesto = motor._presupuesto()
    limite = motor._limite()
    sesiones = motor.sesiones_disponibles()
    activa = next((x for x in sesiones if x["activa"]), None)

    incompletas = huecos = rotas = 0
    fechas_todas: list = []
    for tipo in ("seguidores", "seguidos"):
        for ruta in motor._capturas(tipo):
            if motor._leer_meta(ruta).get("completa") is False:
                incompletas += 1
            fechas_todas.append(motor._fecha_de(ruta))
        rotas += len(motor.verificar_cadena(tipo)["rotas"])
    if fechas_todas:
        agujeros = analitica.huecos(sorted(set(fechas_todas)),
                                    motor.MAX_DIAS_SIN_BAJAR)
        huecos = max((h["dias"] for h in agujeros), default=0)

    # Se miran TODOS los zip, no solo los que siguen el nombre de serie:
    # quien pasó --en mia.zip también hizo una copia. La fecha sale del
    # archivo y no del nombre, que puede ser cualquier cosa.
    copias = sorted(motor.CARPETA.glob("*.zip"),
                    key=lambda r: r.stat().st_mtime)
    copias = [r for r in copias if copia.leer_manifiesto(r)]
    dias_copia = None
    if copias:
        desde = datetime.fromtimestamp(copias[-1].stat().st_mtime).date()
        dias_copia = (date.today() - desde).days

    return {
        "sesion_activa": bool(activa),
        "sesion_comprobada": bool(activa and activa.get("comprobada")),
        "sesion_titulo": activa["titulo"] if activa else "",
        "sesiones": len(sesiones),
        "gastado_hoy": presupuesto.get("hechas", 0),
        "tope": motor.tope_diario(),
        "prudente": bool(limite.get("prudente")),
        "bloqueos_hoy": presupuesto.get("bloqueos", 0),
        "rechazos_hoy": presupuesto.get("rechazos", 0),
        "historial_limite": limite.get("historial") or [],
        "cuentas": sorted(motor.leer_cuentas()),
        "ritmo": motor.leer_ritmo(),
        "capturas": len(fechas_todas),
        "capturas_incompletas": incompletas,
        "mayor_hueco": huecos,
        "max_dias_sin_bajar": motor.MAX_DIAS_SIN_BAJAR,
        "cadena_rota": rotas,
        "errores_registro": sum(1 for e in registro.leer()
                                if e["nivel"] == "ERROR"),
        "sin_copia": not copias,
        "dias_sin_copia": dias_copia,
    }


TAREA = "FocusMedia vigilar"


def _orden_de_la_tarea(retraso: int) -> str:
    """
    Qué ejecutará el programador.

    Si esto corre dentro de un .exe empaquetado, la tarea tiene que
    apuntar al .exe: al lado no hay ningún .py que ejecutar. El propio
    ejecutable atiende la línea de órdenes cuando le pasan argumentos.

    Y si no, a `pythonw` en vez de a `python`, para que la tarea no abra
    una consola negra cada mañana.
    """
    import sys as _s
    cola = f"vigilar --todas --retraso {retraso}"
    if getattr(_s, "frozen", False):
        return f'"{Path(_s.executable)}" {cola}'

    python = Path(_s.executable)
    sin_consola = python.with_name("pythonw.exe")
    if sin_consola.exists():
        python = sin_consola
    aqui = Path(__file__).resolve().parent
    return f'"{python}" "{aqui / "instagram_listas.py"}" {cola}'


def cmd_programar(args) -> None:
    """
    Crea, quita o consulta la tarea diaria de vigilancia.

    En Windows usa schtasks, que ya está en el sistema. En lo demás se
    imprime la línea de cron para pegarla: escribir en el crontab de otro
    sin preguntar es de las cosas que no se hacen.
    """
    import platform
    import subprocess

    orden = _orden_de_la_tarea(args.retraso)

    if platform.system() != "Windows":
        minuto = random.randint(0, 59)
        print("\nEn este sistema no hay schtasks. Añade esta línea con "
              "'crontab -e':\n")
        print(f"  {minuto} {args.hora.split(':')[0]} * * *  {orden}\n")
        print("  El minuto va al azar a propósito: una tarea que salta "
              "siempre en el")
        print("  mismo segundo exacto es de las cosas que distinguen un "
              "programa de")
        print("  una persona.")
        return

    def correr(*trozos):
        return subprocess.run(["schtasks", *trozos], capture_output=True,
                              text=True)

    if args.quitar:
        r = correr("/delete", "/tn", TAREA, "/f")
        print("\nTarea quitada." if r.returncode == 0
              else f"\nNo se pudo quitar: {r.stderr.strip()[:120]}")
        return

    if args.ver:
        r = correr("/query", "/tn", TAREA)
        print("\n" + (r.stdout.strip() if r.returncode == 0
                       else "No hay ninguna tarea programada."))
        return

    r = correr("/create", "/tn", TAREA, "/tr", orden, "/sc", "daily",
               "/st", args.hora, "/f")
    if r.returncode != 0:
        sys.exit(f"\nNo se pudo crear: {r.stderr.strip()[:200]}")
    print(f"\nTarea creada: todos los días a las {args.hora}.")
    print(f"  Ejecuta: {orden}")
    print(f"  Con hasta {motor.plural(args.retraso, 'minuto')} de retraso "
          "al azar, para no")
    print("  saltar siempre en el mismo segundo exacto.")
    print("  Se quita con: programar --quitar")


def cmd_pagina(args) -> None:
    """
    Mide cuánta gente sirve Instagram por página. Una petición por tamaño.

    La web de Instagram pide 50 y este programa también. Nadie ha
    comprobado nunca si el servidor daría más: si diera 200, la descarga
    de una cuenta de 1.000 personas pasaría de 20 peticiones a 5.
    """
    tamanos = [50]
    if args.hasta >= 100:
        tamanos.append(100)
    if args.hasta >= 200:
        tamanos.append(min(args.hasta, 500))

    # La sesión PRIMERO: anunciar «se van a probar 2 peticiones» y luego
    # fallar al abrir la sesión promete un gasto que no llega a ocurrir.
    s = motor.crear_sesion()

    if len(tamanos) > 1:
        # Escrito antes de gastar nada en medir: pedir más de 50 es la
        # parte que no se parece a un navegador.
        print("\nLa web de Instagram pide 50 por página. Pedir más puede")
        print("funcionar, pero no se parece a lo que hace un navegador.")
        print("Se van a probar " + str(tamanos) + " — "
              + motor.plural(len(tamanos), "petición", "peticiones") + ".")

    p = motor.perfil(s, motor.OBJETIVO)
    aviso = motor.avisar_si_privada(p)
    if aviso:
        print(f"\n  Aviso: {aviso}")

    medidas = motor.medir_pagina(s, p["id"], args.lista, tamanos)
    print(f"\nPOR PÁGINA en {args.lista} de @{motor.OBJETIVO}")
    for pedido, llegaron, cortado in medidas:
        marca = "  <- el servidor corta aquí" if cortado else ""
        print(f"  pedidos {pedido:>4}   llegaron {llegaron:>4}{marca}")

    mejor = max((ll for _, ll, _ in medidas), default=0)
    if not mejor:
        print("\n  No ha llegado nadie. Con la lista vacía esto no se puede "
              "medir.")
        return

    print(f"\n  Lo máximo que sirve: {motor.plural(mejor, 'persona')} por "
          "petición.")
    if mejor <= motor.POR_PAGINA:
        print("  Es lo que ya se pide, así que no hay nada que ganar por "
              "aquí.")
        return

    personas = p.get(args.lista) or 0
    if personas:
        antes = -(-personas // motor.POR_PAGINA)
        ahora = -(-personas // mejor)
        print(f"  Para tus {personas}: {antes} peticiones -> {ahora}.")
    print(f"\n  Se cambia con: ajustes --poner por_pagina={mejor}")
    print("  Antes de hacerlo: pedir más de 50 ahorra peticiones a cambio")
    print("  de que cada una se parezca menos a las de un navegador. Con el")
    print("  doble no suele compensar; con el cuádruple ya es otra cosa.")


def cmd_salud(_) -> None:
    """Todo lo que hay que saber para confiar en esto. 0 peticiones."""
    # Comprobar la integridad relee y rehace la huella de cada captura:
    # con medio año de historial son un par de segundos. Callado parecería
    # colgado.
    print("Revisando capturas, presupuesto y registro...")
    d = _recoger_salud()
    avisos = analitica.avisos_de_salud(d, motor.plural)

    print(f"\nSALUD DE @{motor.OBJETIVO}   ({motor.firma()})")
    if avisos:
        # Arriba lo que hay que mirar. Un informe que lo enseña todo por
        # igual no es un informe, es un volcado.
        print(f"\n  {motor.plural(len(avisos), 'cosa')} que mirar:")
        for gravedad, texto in avisos:
            marca = "!!" if gravedad == "alto" else " ·"
            print(f"   {marca} {texto}")
    else:
        print("\n  Nada que mirar. Todo en orden.")

    print("\n  SESIÓN")
    print(f"    {d['sesion_titulo'] or 'ninguna activa'}"
          + (f"   ({motor.plural(d['sesiones'], 'guardada')})"
             if d["sesiones"] else ""))

    print("\n  PETICIONES")
    print(f"    Hoy: {d['gastado_hoy']} de {d['tope']}"
          + ("   (modo prudente)" if d["prudente"] else ""))
    limpios = [x for x in d["historial_limite"] if not x.get("bloqueos")]
    if d["historial_limite"]:
        print(f"    Días medidos: {len(d['historial_limite'])}, "
              f"{len(limpios)} sin bloqueos")
        print(f"    Tope de partida {motor.TOPE_DIARIO} -> aprendido "
              f"{d['tope']}")

    if d["cuentas"]:
        print(f"\n  VIGILANCIA   ({motor.plural(len(d['cuentas']), 'cuenta')})")
        coste = sum(1 / min(int((d["ritmo"].get(c) or {}).get("cadencia") or 1),
                            motor.MAX_DIAS_SIN_BAJAR) for c in d["cuentas"])
        print(f"    Con el ritmo actual salen {coste:.1f} sondeos al día "
              f"(mirarlas todas serían {len(d['cuentas'])})")

    print("\n  DATOS")
    print(f"    Capturas: {d['capturas']}"
          + (f", {d['capturas_incompletas']} sin terminar"
             if d["capturas_incompletas"] else ""))
    print(f"    Mayor hueco sin capturar: "
          f"{motor.plural(d['mayor_hueco'], 'día')}")
    print(f"    Integridad: {'todo cuadra' if not d['cadena_rota'] else str(d['cadena_rota']) + ' rotas'}")
    print("    Copia de seguridad: "
          + ("ninguna" if d["sin_copia"]
             else f"hace {motor.plural(d['dias_sin_copia'], 'día')}"))


def cmd_verificar(_) -> None:
    """Comprueba que ninguna captura cambió desde que se guardó."""
    hubo_rotas = hubo_descolocadas = False
    print(f"\nCuenta: @{motor.OBJETIVO}")
    for tipo in ("seguidores", "seguidos"):
        r = motor.verificar_cadena(tipo)
        if not (r["bien"] or r["rotas"] or r["descolocadas"]
                or r["sin_sellar"]):
            continue
        print(f"\n{tipo.upper()}")
        print(f"  Intactas: {len(r['bien'])}")
        if r["sin_sellar"]:
            # No consta que estén mal: consta que son de antes de los
            # sellos. Decir «corrupta» de algo que solo es viejo sería el
            # mismo error que llamar incompleta a una captura sin meta.
            print(f"  Sin sellar (de antes): {len(r['sin_sellar'])}"
                  f" — desde la del {r['sin_sellar'][0]}")
        for fecha in r["descolocadas"]:
            hubo_descolocadas = True
            print(f"  DESCOLOCADA  {fecha}: su contenido está intacto, "
                  "pero lo de antes cambió")
        for fecha, motivo in r["rotas"]:
            hubo_rotas = True
            print(f"  ROTA  {fecha}: {motivo}")
        print(f"  Cabeza: {r['cabeza']}")

    if hubo_descolocadas:
        print("\nLo descolocado tiene dos causas y esto NO las distingue:")
        print("  · restauraste una copia que rellenó un hueco -> normal;")
        print("  · alguien reescribió una captura anterior y la reselló.")
        print("Si no has restaurado nada, compara la cabeza con la que "
              "guardaste fuera.")
    if hubo_rotas:
        print("\nUna captura cambió después de guardarse. Puede ser una "
              "edición,\nun disco con problemas o una restauración a "
              "medias. La copia de\nseguridad más reciente debería "
              "traerla entera.")
    print("\nGuarda la cabeza en otro sitio —otro equipo, un correo, un "
          "repositorio—\ny compárala de vez en cuando. Aquí dentro, quien "
          "pueda editar una\ncaptura puede editar también sus sellos; "
          "fuera, no.")


def cmd_cruzar(_) -> None:
    """Rellena las columnas de relación sobre lo que ya hay. 0 peticiones."""
    print(f"\n@{motor.OBJETIVO}")
    motor.cruzar_capturas()


def cmd_bajar(args) -> None:
    s = motor.crear_sesion()
    p = motor.perfil(s, motor.OBJETIVO)

    print(f"\n@{p['username']} — {p['seguidores']} seguidores, "
          f"{p['seguidos']} seguidos")

    cabe, explicacion = motor.comprobar_coste(p, args.lista)
    print(f"  {explicacion}")
    if not cabe:
        sys.exit(f"No cabe en el presupuesto de hoy ({motor.tope_diario()}).")

    problema = motor.avisar_si_privada(p)
    if problema:
        if p.get("la_sigo") is False:
            sys.exit(problema)
        print(f"  Aviso: {problema}")

    tipos = [args.lista] if args.lista != "ambas" else ["seguidores", "seguidos"]
    try:
        for tipo in tipos:
            motor.descargar(s, p, tipo)
        # Con las dos listas recién bajadas se puede contestar quién sigue a
        # la cuenta y a quién sigue ella. No cuesta ninguna petición.
        motor.cruzar_capturas()
    except KeyboardInterrupt:
        sys.exit("\nCortado por ti. Vuelve a descargar para continuar desde "
                 "donde lo dejaste.")
    print("\nHecho.")


def cmd_comparar(args) -> None:
    if not motor.CARPETA.exists():
        sys.exit(f"No existe '{motor.CARPETA.name}'. Descarga las listas "
                 "primero.")
    desde = getattr(args, "desde", None)
    hasta = getattr(args, "hasta", None)

    if args.totales or args.historico:
        if desde or hasta:
            # Decirlo. Aceptar unas fechas y no usarlas es peor que no
            # admitirlas: quien las escribe se cree la respuesta.
            print("\n  '--totales' enseña la serie entera; --desde y --hasta "
                  "no se aplican aquí.")
        motor.tendencia_totales()
        return

    seguidores = motor.comparar("seguidores", args.forzar, desde, hasta)
    seguidos = motor.comparar("seguidos", args.forzar, desde, hasta)
    motor.relaciones(seguidores, seguidos)

    if desde or hasta:
        # Lo de abajo mira las DOS ÚLTIMAS capturas, no el intervalo que se
        # ha pedido. Mezclarlo sería contestar a agosto con los cambios de
        # hoy. Y 'cruzar' además ESCRIBE, que no es algo que deba hacer una
        # consulta sobre el pasado.
        print("\n  Los cambios de relación y el cruce miran siempre las dos "
              "últimas capturas,")
        print("  así que se omiten al pedir un intervalo. Ejecuta 'comparar' "
              "sin fechas para verlos.")
        return

    motor.cambios_de_relacion()
    # Aprovecha que ya están las dos listas leídas: rellena en las capturas
    # quién sigue a la cuenta y a quién sigue ella. Cero peticiones, y así
    # quien tenga descargas de antes ve esas columnas sin volver a bajar.
    motor.cruzar_capturas()


def main() -> None:
    # Lo primero: dejar el registro listo y recoger lo que hoy se pierde.
    # Un error fuera de todo try se escribía en stderr y ahí se acababa.
    registro.arrancar(motor.CARPETA)
    registro.instalar_enganches()
    # Lo primero del registro: con qué versión, qué Python y qué sistema.
    # Es lo primero que hace falta saber cuando algo falla, y lo que nadie
    # recuerda de memoria.
    registro.anotar(motor.firma())
    for movido in motor.migrar_sesiones():
        registro.anotar(f"sesión movida a su carpeta  {movido}")
    for cambio in motor.aplicar_ajustes():
        registro.anotar(f"ajuste aplicado  {cambio}")

    ap = argparse.ArgumentParser(
        description=f"FocusMedia {motor.VERSION}: seguidores y seguidos de "
                    "Instagram.")
    ap.add_argument("--version", action="version", version=motor.firma())
    ap.add_argument("--cuenta", help="cuenta objetivo, solo para esta "
                                     "ejecución (por defecto, OBJETIVO)")
    sub = ap.add_subparsers(dest="comando", required=True)

    p_imp = sub.add_parser("importar",
                           help="lee la exportación oficial de Instagram "
                                "(0 peticiones, riesgo cero)")
    p_imp.add_argument("archivo", help="el .zip descargado, o la carpeta ya "
                                       "descomprimida")
    p_imp.add_argument("--guardar", action="store_true",
                       help="guardarlo; sin esto solo dice qué hay dentro")
    p_imp.set_defaults(func=cmd_importar)

    p_pod = sub.add_parser("podar",
                           help="quita capturas viejas dejando una por "
                                "semana; el historial no cambia")
    p_pod.add_argument("--dias", type=int, default=motor.DIAS_A_DIARIO,
                       help=f"cuántos días se guardan enteros "
                            f"(por defecto {motor.DIAS_A_DIARIO})")
    p_pod.add_argument("--hacerlo", action="store_true",
                       help="borrar de verdad; sin esto solo lo enseña")
    p_pod.set_defaults(func=cmd_podar)

    p_aj = sub.add_parser("ajustes",
                          help="ver y cambiar la configuración "
                               "(0 peticiones)")
    p_aj.add_argument("--poner", nargs="+", metavar="CLAVE=VALOR",
                      help="cambiar uno o varios ajustes")
    p_aj.add_argument("--restaurar", action="store_true",
                      help="volver a los valores de serie")
    p_aj.set_defaults(func=cmd_ajustes)

    sub.add_parser("ritmo",
                   help="cada cuánto se mira cada cuenta y por qué "
                        "(0 peticiones)").set_defaults(func=cmd_ritmo)

    p_lim = sub.add_parser("limite",
                           help="qué tope de peticiones está en uso y por "
                                "qué (0 peticiones)")
    p_lim.add_argument("--prudente", action="store_true",
                       help="el tope solo baja: no tantea cuánto aguanta")
    p_lim.add_argument("--normal", action="store_true",
                       help="volver a dejar que lo aprenda subiendo")
    p_lim.add_argument("--fijar", type=int, metavar="N",
                       help="ponerlo a mano en vez de dejar que lo aprenda")
    p_lim.set_defaults(func=cmd_limite)

    p_cop = sub.add_parser("copia",
                           help="guardar o restaurar los datos de una "
                                "cuenta (0 peticiones)")
    p_cop.add_argument("--en", metavar="ARCHIVO.zip",
                       help="dónde dejar la copia")
    p_cop.add_argument("--restaurar", metavar="ARCHIVO.zip",
                       help="traer una copia de vuelta")
    p_cop.add_argument("--reemplazar", action="store_true",
                       help="al restaurar, pisar lo que ya esté; sin esto "
                            "solo se traen los archivos que faltan")
    p_cop.set_defaults(func=cmd_copia)

    p_com = sub.add_parser("comun",
                           help="qué audiencia comparten dos cuentas que ya "
                                "tienes descargadas (0 peticiones)")
    p_com.add_argument("a", help="una cuenta")
    p_com.add_argument("b", help="la otra")
    p_com.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores",
                       help="qué lista cruzar (por defecto seguidores)")
    p_com.add_argument("--forzar", action="store_true",
                       help="cruzar aunque alguna captura esté incompleta")
    p_com.set_defaults(func=cmd_comun)

    p_gra = sub.add_parser("grafo",
                           help="exportar a GraphML quién aparece en el "
                                "círculo de qué cuentas (0 peticiones)")
    p_gra.add_argument("cuentas", nargs="*",
                       help="cuáles; sin nada, todas las que sigues")
    p_gra.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores", help="qué lista usar")
    p_gra.add_argument("--forzar", action="store_true",
                       help="incluir cuentas con la última captura "
                            "incompleta")
    p_gra.set_defaults(func=cmd_grafo)

    p_est = sub.add_parser("estudio",
                           help="cohortes, permanencia y composición de tu "
                                "audiencia (0 peticiones)")
    p_est.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores", help="cuál estudiar")
    p_est.add_argument("--tope-hueco", dest="tope_hueco", type=int,
                       default=7, metavar="N",
                       help="días sin captura a partir de los cuales avisar")
    p_est.add_argument("--incluir-sospechosas", dest="incluir_sospechosas",
                       action="store_true",
                       help="usar también las capturas dudosas")
    p_est.set_defaults(func=cmd_estudio)

    p_pro = sub.add_parser("programar",
                           help="dejar la vigilancia corriendo sola cada "
                                "día (0 peticiones)")
    p_pro.add_argument("--hora", default="09:00", metavar="HH:MM",
                       help="a qué hora (por defecto 09:00)")
    p_pro.add_argument("--retraso", type=int, default=45, metavar="MIN",
                       help="minutos de retraso al azar antes de empezar")
    p_pro.add_argument("--ver", action="store_true",
                       help="ver la tarea que hay")
    p_pro.add_argument("--quitar", action="store_true", help="quitarla")
    p_pro.set_defaults(func=cmd_programar)

    p_pag = sub.add_parser("pagina",
                           help="medir cuánta gente sirve Instagram por "
                                "página (1 petición por tamaño)")
    p_pag.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores", help="con qué lista medir")
    p_pag.add_argument("--hasta", type=int, default=100, metavar="N",
                       help="tamaño mayor a probar (50 no gasta nada nuevo; "
                            "por defecto 100)")
    p_pag.set_defaults(func=cmd_pagina)

    sub.add_parser("salud",
                   help="cómo va todo, de un vistazo (0 peticiones)"
                   ).set_defaults(func=cmd_salud)

    sub.add_parser("verificar",
                   help="comprobar que ninguna captura cambió desde que se "
                        "guardó (0 peticiones)"
                   ).set_defaults(func=cmd_verificar)

    sub.add_parser("informe",
                   help="un archivo HTML con todo dentro, para abrir o "
                        "mandar (0 peticiones)").set_defaults(func=cmd_informe)

    sub.add_parser("cruzar",
                   help="rellena quién sigue a la cuenta y a quién sigue "
                        "ella, sobre las capturas que ya hay "
                        "(0 peticiones)").set_defaults(func=cmd_cruzar)

    p_cta = sub.add_parser("cuentas",
                           help="ver, añadir o quitar cuentas seguidas")
    p_cta.add_argument("--anadir", nargs="+", metavar="CUENTA")
    p_cta.add_argument("--quitar", nargs="+", metavar="CUENTA")
    p_cta.set_defaults(func=cmd_cuentas)

    p_ses = sub.add_parser("sesion",
                           help="importa las cookies del navegador")
    p_ses.add_argument("--pegar", metavar="COOKIE",
                       help="usar esta sesión en vez de leerla del "
                            "navegador; vale el sessionid o la cabecera "
                            "Cookie entera")
    p_ses.add_argument("--etiqueta", metavar="NOMBRE",
                       help="con --pegar, un nombre para reconocerla")
    p_ses.add_argument("--buscar", action="store_true",
                       help="mirar TODOS los navegadores del equipo y "
                            "guardar las sesiones que encuentre "
                            "(0 peticiones)")
    p_ses.add_argument("--listar", action="store_true",
                       help="ver las sesiones guardadas")
    p_ses.add_argument("--usar", metavar="ID",
                       help="cambiar a una de las guardadas")
    p_ses.add_argument("--quitar", metavar="ID",
                       help="borrar una de las guardadas")
    p_ses.add_argument("--comprobar-estas", dest="comprobar_estas",
                       nargs="+", metavar="ID",
                       help="comprobar estas sesiones guardadas y aprender "
                            "de quién son (1 petición por cada una, hasta "
                            "3 si la primera vía no responde)")
    p_ses.add_argument("--comprobar", action="store_true",
                       help="solo comprobar la que ya está guardada")
    p_ses.set_defaults(func=cmd_sesion)

    sub.add_parser("contar", help="solo los totales (1 petición)"
                   ).set_defaults(func=cmd_contar)

    p_bajar = sub.add_parser("bajar", help="descarga las listas completas")
    p_bajar.add_argument("--lista", choices=["ambas", "seguidores", "seguidos"],
                         default="ambas")
    p_bajar.set_defaults(func=cmd_bajar)

    p_ins = sub.add_parser("inspeccionar",
                           help="1 petición: muestra qué campos manda Instagram")
    p_ins.add_argument("--lista", choices=["seguidores", "seguidos"],
                       default="seguidores")
    p_ins.set_defaults(func=cmd_inspeccionar)

    p_vig = sub.add_parser("vigilar",
                           help="comprueba con 1 petición y baja solo si hace falta")
    p_vig.add_argument("--umbral", type=int, default=motor.UMBRAL_CAMBIO,
                       help=f"cambio en los totales que dispara la descarga "
                            f"(por defecto {motor.UMBRAL_CAMBIO})")
    p_vig.add_argument("--max-dias", type=int, default=motor.MAX_DIAS_SIN_BAJAR,
                       dest="max_dias",
                       help=f"forzar descarga completa cada N días aunque los "
                            f"totales no cambien (por defecto "
                            f"{motor.MAX_DIAS_SIN_BAJAR})")
    p_vig.add_argument("--solo-mirar", action="store_true", dest="solo_mirar",
                       help="informar de si haría falta bajar, sin bajar")
    p_vig.add_argument("--retraso", type=int, default=0, metavar="MIN",
                       help="esperar un rato al azar antes de empezar, "
                            "hasta N minutos (para la tarea programada)")
    p_vig.add_argument("--todas-ya", dest="todas_ya", action="store_true",
                       help="con --todas, mirarlas TODAS aunque no les toque")
    p_vig.add_argument("--todas", action="store_true",
                       help="recorrer TODAS las cuentas seguidas, por turnos "
                            "y repartiendo el presupuesto (no en paralelo)")
    p_vig.set_defaults(func=cmd_vigilar)

    p_hist = sub.add_parser("historial",
                            help="trayectoria de cada persona a lo largo de "
                                 "todas las capturas")
    p_hist.add_argument("--lista", choices=["ambas", "seguidores", "seguidos"],
                        default="ambas")
    p_hist.add_argument("--min-entradas", type=int, default=2,
                        dest="min_entradas",
                        help="a partir de cuántas entradas se considera "
                             "'ida y vuelta' (mínimo y por defecto 2)")
    p_hist.add_argument("--incluir-sospechosas", action="store_true",
                        dest="incluir_sospechosas",
                        help="usar también las capturas cuyo tamaño se "
                             "desploma (solo si la bajada fue real)")
    p_hist.set_defaults(func=cmd_historial)

    sub.add_parser("presupuesto",
                   help="cuántas peticiones llevas hoy y en qué"
                   ).set_defaults(func=cmd_presupuesto)

    p_con = sub.add_parser("contratos",
                           help="rutas, parámetros y forma esperada "
                                "(0 peticiones)")
    p_con.add_argument("--crear", action="store_true",
                       help="escribir salida/rutas.json para poder editarlo")
    p_con.set_defaults(func=cmd_contratos)

    sub.add_parser("diagnostico",
                   help="prueba cada endpoint y dice cuál responde"
                   ).set_defaults(func=cmd_diagnostico)

    p_det = sub.add_parser("detalles",
                           help="perfil completo de la lista de vigilancia "
                                "(1 petición POR CUENTA)")
    p_det.add_argument("--crear", action="store_true",
                       help="generar la lista con candidatos de tus capturas")
    p_det.add_argument("--solo-listar", action="store_true",
                       dest="solo_listar",
                       help="ver a quién se consultaría, sin consultar")
    p_det.set_defaults(func=cmd_detalles)

    p_cmp = sub.add_parser("comparar", help="qué cambió entre dos capturas")
    p_cmp.add_argument("--totales", action="store_true",
                       help="solo la evolución del NÚMERO de seguidores "
                            "(para la trayectoria de cada persona, usa el "
                            "comando 'historial')")
    p_cmp.add_argument("--historico", action="store_true",
                       help=argparse.SUPPRESS)   # alias antiguo
    p_cmp.add_argument("--desde", metavar="AAAA-MM-DD",
                       help="comparar desde esa fecha en vez de la captura "
                            "anterior; si no hay captura ese día se usa la "
                            "más cercana hacia atrás")
    p_cmp.add_argument("--hasta", metavar="AAAA-MM-DD",
                       help="comparar hasta esa fecha en vez de la última")
    p_cmp.add_argument("--forzar", action="store_true",
                       help="comparar aunque haya capturas incompletas")
    p_cmp.set_defaults(func=cmd_comparar)

    args = ap.parse_args()
    registro.anotar(f"orden '{args.comando}'", cuenta=args.cuenta or "-")

    if getattr(args, "cuenta", None):
        limpio = motor.limpiar_usuario(args.cuenta)
        if not limpio or not motor.PATRON_USUARIO.match(limpio):
            sys.exit(f"'{args.cuenta}' no parece un nombre de usuario.")
        # En el motor, no aquí: era un `global OBJETIVO` cuando esto vivía
        # dentro, y al mudarse habría creado un OBJETIVO propio de este
        # archivo que no lee nadie. Es el precio de que la cuenta objetivo
        # sea una variable global, y la razón por la que el siguiente paso
        # del reparto es quitarla.
        motor.OBJETIVO = limpio

    try:
        args.func(args)
    except motor.RespuestaInesperada as e:
        sys.exit(f"\nRespuesta con otra forma: {e}\n"
                 "Esto es un cambio de Instagram, no un fallo tuyo. "
                 "Ejecuta 'diagnostico' para ver qué sigue funcionando.")
    except motor.PeticionRechazada as e:
        sys.exit(f"\nPetición rechazada: {e}\n"
                 "Esto no se arregla esperando. Si se repite, ejecuta "
                 "'diagnostico'.")
    except motor.SinPresupuesto as e:
        sys.exit(f"\nSin presupuesto: {e}")
    except motor.SesionInvalida as e:
        sys.exit(f"\nSesión no válida: {e}")
    except motor.NoEncontrado as e:
        sys.exit(f"\nNo encontrado: {e}\n"
                 f"Revisa que la cuenta ('{motor.OBJETIVO}') esté bien "
                 "escrita.")
    except KeyboardInterrupt:
        sys.exit("\nCortado.")
