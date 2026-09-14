FocusMedia
==========

Sigue los seguidores y seguidos de una cuenta de Instagram a lo largo del
tiempo, y dice qué cambia: quién entra, quién sale y de qué tipo fue cada
movimiento.

Todo lo que cuesta peticiones lleva su coste escrito al lado. Casi todo el
análisis cuesta cero: se hace sobre lo que ya está descargado.


EMPEZAR
-------

    pip install customtkinter requests browser_cookie3 pillow

    python instagram_gui.py          la ventana
    python instagram_listas.py -h    la línea de órdenes

La primera vez, tres pasos:

    1. Escribe arriba la cuenta que quieres seguir.
    2. Pulsa «Importar sesión» (o «Sesiones», ver abajo).
    3. Pulsa «Contar» para comprobar que funciona. Gasta 1 petición.

El botón «Guía y ayuda» explica el resto sin gastar nada.

Si vienes de una versión anterior, copia tu carpeta salida/ aquí: ahí
están las capturas, el presupuesto y las cuentas seguidas. Cada cuenta
pasa a tener su subcarpeta («usuario - id») la primera vez que se abre;
los archivos sueltos se recogen solos y no se pierde ninguno.


LA SESIÓN
---------

Una cookie de sesión equivale a estar dentro de esa cuenta. No las
compartas. Se guardan en sesiones/, que está entera en .gitignore.

El botón «Sesiones», o pulsar donde pone «Sesión activa como @…», abre
todo lo relacionado:

  Buscar en los navegadores del equipo
      Mira los once navegadores que conoce y guarda todas las sesiones
      abiertas que encuentre, cada una con el navegador de donde salió.
      No gasta peticiones y NO cambia la que estés usando.
      También: instagram_listas.py sesion --buscar

  Añadir una a mano
      Para cuando un navegador que SÍ tienes no suelta su sesión. Chrome y
      Edge en Windows cifran sus cookies y casi nunca se dejan leer; si
      pasa eso, la búsqueda te lo dice y no lo confunde con «no lo
      tienes». Copia el valor de «sessionid» del navegador (F12 →
      Aplicación → Cookies → instagram.com) y pégalo ahí.

  Comprobar las marcadas
      Es lo que descubre de QUÉ CUENTA es cada sesión: hasta entonces solo
      se sabe su número. 1 petición por cada una, hasta 3 si la primera
      vía no responde.

  Conectar
      Cambia a esa cuenta y la deja lista para trabajar.

Se pueden guardar varias y cambiar entre ellas, pero se usa UNA a la vez.
Cambiar de sesión NO da presupuesto nuevo: el límite es de la sesión y de
la IP, y la IP no cambia por cambiar de cuenta.

    instagram_listas.py sesion --listar
    instagram_listas.py sesion --usar 9982027586


DESCARGAR
---------

    Contar            1 petición. Solo los totales.
    Listas completas  ~50 peticiones para 2.500 personas. Se puede parar
                      en cualquier momento y sigue donde lo dejó.

Las columnas «sigue a la cuenta» y «la cuenta le sigue» se CALCULAN
cruzando las dos listas; no las manda Instagram. Se rellenan al bajar y al
comparar. Para capturas antiguas: instagram_listas.py cruzar


ANALIZAR — nada de esto gasta peticiones
----------------------------------------

  Qué cambió
      Quién entró y quién salió, y de qué TIPO fue cada movimiento
      respecto a la cuenta: quién dejó de seguirla, a quién dejó ella de
      seguir, quién se fue del todo. Necesita dos días con las dos listas
      completas.

  Comparar fechas
      Entre dos días cualesquiera, no solo entre las dos últimas capturas.

        comparar --desde 2026-08-01 --hasta 2026-09-01
        comparar --hasta 2026-09-01      qué cambió ESE día

      Si eliges un día sin captura se usa la más cercana hacia atrás, y se
      dice cuál.

  Comparar cuentas
      Si sigues varias, cruza dos de ellas: quién está en las dos y quién
      solo en una.

        comun marca_a marca_b
        comun marca_a marca_b --lista seguidos

  Historial
      La trayectoria de cada persona: cuándo entró, cuándo salió, cuántas
      veces. Con muchas capturas no las relee todas — guarda un índice y
      solo lee lo nuevo.

  Informe HTML
      Un archivo que se abre con doble clic y lleva todo dentro: tablas
      con buscador, la evolución y los cambios. Se puede mandar tal cual y
      no necesita internet.

Cuando el índice está al día, los CSV viejos sobran:

    instagram_listas.py podar             dice cuáles, sin borrar nada
    instagram_listas.py podar --hacerlo   los borra; el historial no cambia


VIGILAR SIN ESTAR DELANTE
-------------------------

'vigilar' mira si los totales se movieron y solo descarga si hace falta.
Con varias cuentas, cada una tiene su ritmo, aprendido de cuánto se mueve:
las activas se miran a diario y las dormidas cada varios días.

    instagram_listas.py ritmo                        cuándo toca cada una
    instagram_listas.py vigilar --todas --todas-ya   forzar la ronda entera

Si lo dejas programado, lo que encuentre se acumula en
salida/novedades.txt y te lo cuenta la ventana la próxima vez que la
abras. En Windows además sale un globo en el momento.


NO PERDER LOS DATOS
-------------------

Una lista de seguidores de hace tres semanas NO se puede volver a
descargar: ya no existe en ningún sitio. Haz copia.

    botón «Copia de seguridad»                       deja un zip
    instagram_listas.py --cuenta X copia             lo mismo
    instagram_listas.py copia --restaurar copia.zip  la trae de vuelta

La copia no lleva sesiones dentro, así que se puede mover sin cuidado.
Llévala a otro disco: en la misma carpeta no sirve de nada si el disco es
el que falla. Al restaurar NO se pisa nada de lo que ya haya, salvo con
--reemplazar.


NO PERDER LA CUENTA
-------------------

El tope diario no es un número fijo: sube solo tras cada día limpio y
apurado, y cae en cuanto hay un bloqueo. Cuando encuentra el borde, deja
de empujarlo.

    instagram_listas.py limite               cuál está en uso y por qué
    instagram_listas.py limite --fijar 300   ponerlo a mano
    instagram_listas.py limite --prudente    que solo baje, sin tantear

Hay además un tope por hora: las mismas peticiones repartidas por el día o
gastadas en diez minutos son dos cosas muy distintas para quien las
recibe.

Un HTTP 401/403 —«no te reconozco la sesión»— para el día entero al
segundo aviso. Eso no se arregla esperando: insistir es lo que escala.
Cuando pase, abre Instagram en el navegador y mira si hay algo que
confirmar.


AJUSTES
-------

Todo lo configurable está en salida/ajustes.json, y se ve y se cambia
desde el botón «Ajustes». Cada valor tiene un margen; lo que quede fuera
se recorta al límite y se avisa.

    instagram_listas.py ajustes                      verlos
    instagram_listas.py ajustes --poner pausa_min=2  cambiarlos
    instagram_listas.py ajustes --restaurar          dejarlos como venían


CUANDO ALGO FALLA
-----------------

  Registro
      El botón «Registro», junto a la consola, enseña qué pasó, con los
      errores en rojo y un buscador. El archivo es salida/registro.log. No
      lleva cookies dentro, pero sí los nombres de las cuentas que miras:
      tenlo en cuenta si lo compartes.

  Si Instagram cambia algo
      diagnostico          qué vía responde y cuál cambió de forma
      contratos            rutas y nombres en uso (0 peticiones)
      contratos --crear    deja salida/rutas.json editable

      Las rutas, los nombres de parámetros y los de campos se reparan ahí,
      SIN TOCAR CÓDIGO. Cuando algo falla se guarda un fallo_*.json con el
      detalle completo; ese sí se puede compartir, no lleva tu sesión.

      El análisis de lo ya descargado no necesita red: comparar, historial
      y las tablas funcionan aunque Instagram deje de responder.

  Para pedir ayuda
      Pega esto, que dice versión, Python y sistema:

        instagram_listas.py --version


OTRAS COSAS
-----------

Si pides tu propia información a Instagram (Accounts Center, formato JSON,
sección «Followers and following»), esto la lee sin gastar nada:

    instagram_listas.py importar export.zip              dice qué hay
    instagram_listas.py --cuenta TU importar export.zip --guardar

Solo vale para TU cuenta y no trae ids, así que se guarda aparte y NO como
captura: mezclarlo estropearía el historial.

crudo_perfil_*.html guarda la respuesta del perfil para poder mirarla sin
gastar peticiones. NO lo compartas: lleva tu sesión dentro. Por eso
tampoco entra en las copias de seguridad.


ARCHIVOS
--------

    instagram_gui.py     la ventana
    instagram_listas.py  el motor; funciona solo, sin la ventana
    ordenes.py           lo que se pide desde la línea de órdenes
    informe_html.py      el informe de una sola pieza
    indice_eventos.py    la trayectoria de cada persona, sin releerlo todo
    export_instagram.py  lee la exportación oficial de Instagram
    copia.py             copia de seguridad de una cuenta
    registro.py          qué ha pasado, con rotación
    version.py           qué versión es esto
    hacer_logo.py        regenera marca/
    marca/               el logo en todos los tamaños
    test_modulo.py       las pruebas del motor
    test_gui.py          las pruebas de la ventana
    PROJECT_CONTEXT.md   por qué está hecho así, y todo lo aprendido

Las carpetas salida/ y sesiones/ las crea el programa. Las dos están en
.gitignore: la primera son tus datos, la segunda son tus cuentas.


COMPROBAR QUE TODO SIGUE BIEN
-----------------------------

    python test_modulo.py
    python test_gui.py

No necesitan internet ni una sesión: se prueban contra un Instagram falso.
