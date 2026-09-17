<div align="center">

<img src="marca/focusmedia_256.png" alt="FocusMedia" width="128">

# FocusMedia

**Quién entra, quién sale y quién deja de seguirte.**
Seguidores y seguidos de Instagram a lo largo del tiempo.

<!-- Insignias sin promesas: solo lo que se puede comprobar abriendo el
     repositorio. Nada de «build passing» sin integración continua, ni
     número de versión, que se quedaría viejo y además lo prohíbe f38. -->
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-0078D4?logo=windows&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black)
![Sin frameworks](https://img.shields.io/badge/sin%20frameworks-4FB3D9)
![Datos locales](https://img.shields.io/badge/datos-en%20tu%20disco-63C68A)
![Analisis sin peticiones](https://img.shields.io/badge/an%C3%A1lisis-0%20peticiones-63C68A)

[Empezar](#instalación) ·
[Analizar](#analizar-nada-de-esto-gasta-peticiones) ·
[No perder la cuenta](#no-perder-la-cuenta) ·
[Cuando algo falla](#cuando-algo-falla)

</div>

---

Funciona con ventana o desde la línea de órdenes. Los datos quedan en CSV
en tu disco, no en ningún servicio.


## En qué se diferencia

**Cada petición cuenta y se dice lo que cuesta.** Instagram limita a quien
pregunta demasiado. Cada acción lleva su coste escrito al lado, hay un
presupuesto diario que se aprende solo, un tope por hora para no ir a
ráfagas, y un cortafuegos que para al primer bloqueo en vez de insistir.

**El análisis no gasta nada.** Comparar, el historial, los informes y las
tablas trabajan sobre lo que ya está descargado. Funcionan aunque
Instagram deje de responder.

**No se afirma lo que no se sabe.** Una captura sin metadatos no es una
captura completa; un cero del buscador no es «cero seguidores», es «no se
sabe»; una columna vacía se marca como vacía y no como un dato. Las cosas
que se calculan —quién es mutuo, por ejemplo— se dicen calculadas.

**Se puede reparar sin tocar código.** Cuando Instagram cambia una ruta o
el nombre de un campo, se arregla editando un JSON.

---

## Instalación

```bash
pip install customtkinter requests browser_cookie3 pillow
```

```bash
python instagram_gui.py          # la ventana
python instagram_listas.py -h    # la línea de órdenes
```

En Windows, **doble clic en `FocusMedia.pyw`** abre solo la ventana, sin la
consola negra detrás. Y con `python construir.py` se empaqueta en un
`.exe` que funciona sin tener Python instalado. Si algo falla al arrancar —una biblioteca que
falta— lo dice en un cuadro, porque sin consola no se vería nada.

### La primera vez

1. Escribe arriba la cuenta que quieres seguir.
2. Pulsa **Importar sesión** (o **Sesiones**, más abajo).
3. Pulsa **Contar** para comprobar que funciona. Gasta 1 petición.

El botón **Guía y ayuda** explica el resto sin gastar nada.

Si vienes de una versión anterior, copia tu carpeta `salida/` aquí: ahí
están las capturas, el presupuesto y las cuentas seguidas. Cada cuenta
pasa a tener su subcarpeta (`usuario - id`) la primera vez que se abre, y
los archivos sueltos se recogen solos.

---

## La sesión

> Una cookie de sesión equivale a estar dentro de esa cuenta. No las
> compartas. Se guardan en `sesiones/`, que está entera en `.gitignore`.

El botón **Sesiones** —o pulsar donde pone «Sesión activa como @…»— abre
todo lo relacionado:

| | Qué hace | Coste |
|---|---|---|
| **Buscar en los navegadores** | Mira los once navegadores que conoce y guarda todas las sesiones abiertas que encuentre, con el navegador de donde salió. No cambia la que estés usando. | 0 |
| **Añadir una a mano** | Para cuando un navegador que sí tienes no suelta su sesión. | 0 |
| **Comprobar las marcadas** | Descubre de qué cuenta es cada sesión: hasta entonces solo se sabe su número. | 1 por cada una, hasta 3 si la primera vía no responde |
| **Conectar** | Cambia a esa cuenta y la deja lista para trabajar. | igual |

Chrome y Edge en Windows cifran sus cookies y casi nunca se dejan leer. Si
pasa, la búsqueda **lo dice** y no lo confunde con «no lo tienes»: copia
el valor de `sessionid` del navegador (F12 → Aplicación → Cookies →
instagram.com) y pégalo en «Añadir una a mano».

Se pueden guardar varias y cambiar entre ellas, pero **se usa una a la
vez**. Cambiar de sesión no da presupuesto nuevo: el límite es de la
sesión y de la IP, y la IP no cambia por cambiar de cuenta.

```bash
instagram_listas.py sesion --buscar
instagram_listas.py sesion --listar
instagram_listas.py sesion --usar 9982027586
```

---

## Descargar

| | Coste |
|---|---|
| **Contar** — solo los totales | 1 petición |
| **Listas completas** | ~50 peticiones para 2.500 personas |

La descarga se puede parar en cualquier momento y sigue donde lo dejó.

Las columnas «sigue a la cuenta» y «la cuenta le sigue» se **calculan**
cruzando las dos listas; no las manda Instagram. Se rellenan al bajar y al
comparar; para capturas antiguas, `instagram_listas.py cruzar`.

---

### Sin sesión

La página de una cuenta **pública** lleva dentro un bloque con sus datos, y
se lee sin iniciar sesión: seguidores y seguidos exactos, publicaciones,
nombre, biografía, foto, si es privada o verificada, y el **id numérico**.

«Contar» funciona así aunque no hayas importado ninguna sesión. Si la hay,
se usa la sesión; la diferencia es que ya no depende de ella para esto. `vigilar` lo intenta así primero, y solo tira de la sesión si Instagram
responde con el muro de inicio de sesión.

Como vigilar consiste precisamente en mirar los totales, una ronda sobre
cuentas públicas puede costar **cero peticiones de sesión** — y ese era el
gasto recurrente del proyecto.

> **No es gratis, y conviene tenerlo claro.** La cuota de Instagram es de
> la sesión **y de la IP**, y la IP es la misma. Lo que se ahorra es el
> presupuesto de la sesión, no el riesgo. Por eso lleva su propio contador
> y su propio freno por horas, visibles en `salud` y en `ajustes`.
>
> Se apaga poniendo `tope_hora_anonimo` a 0.

La página trae un bloque con todo esto, sin cookies:

| | |
|---|---|
| seguidores, seguidos | exactos, no redondeados |
| id numérico | el que usa el proyecto como clave |
| nombre, biografía, enlace | tal cual los puso la cuenta |
| foto de perfil | se guarda, y si cambió se archiva la anterior |
| privada, verificada | sin heurísticas |
| pronombres, Threads | si los tiene |
| conmemorativa, desactivada | por qué una cuenta deja de aparecer | Las metas `og:` redondean
—970 por 969—, así que solo se usan como respaldo y en ese caso los
totales se marcan como no fiables.

No hay listas ni relaciones por esta vía: eso nunca ha estado disponible
sin autenticar.

## Analizar — nada de esto gasta peticiones

### Qué cambió

Quién entró y quién salió, y de qué **tipo** fue cada movimiento respecto
a la cuenta: quién dejó de seguirla, a quién dejó ella de seguir, quién se
fue del todo. Necesita dos días con las dos listas completas.

### Comparar fechas

Entre dos días cualesquiera, no solo entre las dos últimas capturas.

```bash
instagram_listas.py comparar --desde 2026-08-01 --hasta 2026-09-01
instagram_listas.py comparar --hasta 2026-09-01    # qué cambió ese día
```

Si eliges un día sin captura se usa la más cercana hacia atrás, y se dice
cuál.

### Comparar cuentas

Si sigues varias, cruza dos de ellas: quién está en las dos y quién solo
en una.

```bash
instagram_listas.py comun marca_a marca_b
instagram_listas.py comun marca_a marca_b --lista seguidos
```

### Historial

La trayectoria de cada persona: cuándo entró, cuándo salió, cuántas veces.
Con muchas capturas no las relee todas — guarda un índice y solo lee lo
nuevo.

### Estudio

Lo que el disco ya puede responder y nadie más:

```bash
instagram_listas.py estudio
instagram_listas.py estudio --lista seguidos
```

| | |
|---|---|
| **Cohortes** | de los que entraron cada mes, cuántos siguen |
| **Permanencia** | cuánto dura quien se va, sin contar el tiempo que estuvo fuera |
| **Los que vuelven** | quién se fue y regresó |
| **Composición** | qué proporción son privadas, verificadas o sin foto |
| **Publicar y crecer** | si los días que publicas ganas más gente |
| **Huecos** | días sin captura, que es sobre lo que se mide todo lo demás |

Instagram enseña cuántos seguidores tienes. No cuántos de los de agosto
siguen contigo en diciembre; eso solo lo sabe tu historial.

> **No hay likes ni comentarios.** Este proyecto nunca los ha descargado,
> así que «quién interactuó en una publicación» no es una pregunta de
> coste cero: sacarlos costaría cientos de peticiones por cuenta contra
> endpoints más vigilados que el de listas.

### Grafo de varias cuentas

Quién aparece en el círculo de cuáles de tus objetivo, y quién está en
varias a la vez.

```bash
instagram_listas.py grafo                      # todas las que sigues
instagram_listas.py grafo marca_a marca_b marca_c
```

Deja un `.graphml` que abren Gephi, yEd o Cytoscape. Cada nodo lleva
`clase` (objetivo o persona) y `en_cuantas`, que es lo que conviene usar
para el tamaño.

> **Qué grafo es este.** Es bipartito: hay aristas entre tus cuentas y las
> personas, y **ninguna entre personas**. Saber quién sigue a quién dentro
> de ese grupo serían las listas de cada una de esas miles de personas:
> decenas de miles de peticiones. Sirve para solapamiento de audiencias y
> para ver quién hace de puente; no para detectar comunidades entre tus
> seguidores, aunque Gephi calcule ese número igual — lo calcularía sobre
> aristas que no existen.

### Relaciones

Quién es mutuo y quién no. Tres estados, y cada uno con su explicación al
lado — en la tabla y en el informe:

Cada fila es una persona, y la relación dice qué pasa entre ella y la
cuenta que estás mirando:

| | |
|---|---|
| `mutuo` | se siguen los dos |
| `solo_sigue_a_la_cuenta` | sigue a @X, pero @X no le sigue |
| `solo_la_cuenta_le_sigue` | @X le sigue, pero no sigue a @X |

En la tabla y en el informe sale el nombre real de la cuenta en lugar de
`@X`, y las mismas frases aparecen en la consola: un solo vocabulario
para los tres estados.

### Informe HTML

Un archivo que se abre con doble clic y lleva todo dentro: tablas con
buscador, la evolución y los cambios. Se puede mandar tal cual y no
necesita internet.

### Podar

Cuando el índice está al día, los CSV viejos sobran:

```bash
instagram_listas.py podar             # dice cuáles, sin borrar nada
instagram_listas.py podar --hacerlo   # los borra; el historial no cambia
```

---

## Vigilar sin estar delante

`vigilar` mira si los totales se movieron y **solo descarga si hace
falta**. Con varias cuentas, cada una tiene su ritmo, aprendido de cuánto
se mueve: las activas se miran a diario y las dormidas cada varios días.

```bash
instagram_listas.py ritmo                        # cuándo toca cada una
instagram_listas.py vigilar --todas --todas-ya   # forzar la ronda entera
```

Si lo dejas programado, lo que encuentre se acumula en
`salida/novedades.txt` y te lo cuenta la ventana la próxima vez que la
abras. En Windows además sale un globo en el momento.

---

## Que no se pueda cuestionar el historial

Cada captura se sella con un SHA-256 de **lo que Instagram dijo**, y cada
sello se encadena con el de la captura anterior. Cambiar la de agosto
invalida septiembre, octubre y todo lo que venga después.

```bash
instagram_listas.py verificar
```

Se sella lo observado, no el archivo: las columnas que calcula el propio
programa quedan fuera, así que rellenarlas no dispara ninguna alarma.
Reordenar las filas tampoco. Cambiar quién estaba, sí.

> **Qué demuestra y qué no.** Detecta que una captura se editó, se
> corrompió o desapareció. **No** demuestra nada frente a quien pueda
> escribir en la carpeta y sepa cómo funciona: puede reescribir la
> captura, su sello y todos los eslabones siguientes.
>
> Para eso hace falta que **la cabeza esté guardada donde esa persona no
> llegue** — otro equipo, un correo, un repositorio. `verificar` la
> imprime precisamente para que la puedas anclar fuera; se recalcula
> siempre desde los archivos, así que cualquier cambio la mueve.

Las capturas de antes de esta versión salen como **sin sellar**, que no es
lo mismo que rotas: no consta que estén mal, consta que no se sellaron.

Y hay un tercer estado, **descolocada**: el contenido está intacto pero lo
de antes cambió. Pasa al restaurar una copia que rellena un hueco, y
también si alguien reescribió una captura anterior. La cadena no distingue
las dos — quien lo mira sabe si restauró algo, y si no, ahí es donde sirve
la cabeza guardada fuera.

## Cómo va todo

```bash
instagram_listas.py salud
```

Junta en una vista lo que antes exigía cinco comandos: la sesión, el
presupuesto y el tope aprendido, las cuentas vigiladas y su ritmo, las
capturas incompletas, los huecos del calendario, la integridad de la
cadena, los errores del registro y cuándo fue la última copia.

Arriba, lo que hay que mirar. Un informe que lo enseña todo por igual no
es un informe, es un volcado.

## Dejarlo corriendo solo

```bash
instagram_listas.py programar                    # cada día a las 09:00
instagram_listas.py programar --hora 22:30
instagram_listas.py programar --ver
instagram_listas.py programar --quitar
```

En Windows crea la tarea con `schtasks`, que ya está en el sistema, y la
apunta a `pythonw` para que no abra consola. Si estás usando el `.exe`,
apunta al `.exe`: el mismo ejecutable abre la ventana cuando se pulsa dos
veces y atiende la línea de órdenes cuando se le pasan argumentos. En otros sistemas imprime la
línea de cron para pegarla: escribir en el crontab de otro sin preguntar
es de las cosas que no se hacen.

La tarea lleva un **retraso al azar** de hasta 45 minutos. Saltar siempre
en el mismo segundo exacto es de las cosas que distinguen un programa de
una persona.

### La foto de perfil, también

Cada cuenta guarda su foto actual en `foto_<cuenta>.jpg`, y **cuando
cambia, la anterior se archiva con la fecha en la que dejó de estar
puesta**. Una foto de perfil cambiada no se puede volver a descargar:
Instagram deja de servirla.

Se compara el contenido, no la URL — el CDN cambia el enlace
constantemente sirviendo la misma imagen, y comparar enlaces daría un
«cambió de foto» cada semana. Ocupan unos pocos KB y no cuestan ninguna
petición: la descarga ya se había hecho.

Que una cuenta cambie de imagen es una señal, no decoración: puede haber
cambiado de manos.

## No perder los datos

> Una lista de seguidores de hace tres semanas **no se puede volver a
> descargar**: ya no existe en ningún sitio. Haz copia.

```bash
instagram_listas.py --cuenta X copia                    # deja un zip
instagram_listas.py copia --restaurar copia.zip         # la trae de vuelta
```

También con el botón **Copia de seguridad**. La copia no lleva sesiones
dentro, así que se puede mover sin cuidado. Llévala a otro disco: en la
misma carpeta no sirve de nada si el disco es el que falla.

Al restaurar **no se pisa nada** de lo que ya haya, salvo con
`--reemplazar`: lo del disco puede ser más nuevo que la copia.

---

### Cuánto sirve Instagram por página

La descarga cuesta una petición por cada 50 personas, porque 50 es lo que
pide la web de Instagram. Nadie ha comprobado si el servidor daría más:

```bash
instagram_listas.py pagina              # prueba 50 y 100
instagram_listas.py pagina --hasta 200
```

Una petición por tamaño, y **para en cuanto encuentra el tope**.

> Pedir más de 50 ahorra peticiones a cambio de que cada una se parezca
> menos a las de un navegador. Con el doble no suele compensar; con el
> cuádruple ya es otra cosa. El programa mide y lo explica; decidir es
> tuyo, y de serie sigue pidiendo 50.

## No perder la cuenta

El tope diario no es un número fijo: sube solo tras cada día limpio y
apurado, y cae en cuanto hay un bloqueo. Cuando encuentra el borde, deja
de empujarlo.

```bash
instagram_listas.py limite               # cuál está en uso y por qué
instagram_listas.py limite --fijar 300   # ponerlo a mano
instagram_listas.py limite --prudente    # que solo baje, sin tantear
```

Hay además un tope por hora: las mismas peticiones repartidas por el día o
gastadas en diez minutos son dos cosas muy distintas para quien las
recibe.

Un **HTTP 401/403** —«no te reconozco la sesión»— para el día entero al
segundo aviso. Eso no se arregla esperando: insistir es lo que escala.
Cuando pase, abre Instagram en el navegador y mira si hay algo que
confirmar.

### Lo que esto no hace

No rota direcciones IP ni reparte peticiones entre varias cuentas para
esquivar el límite. Una sesión que ya funciona vista desde una IP nueva es
la señal más clara de cuenta robada, y el resultado más probable no es ir
más rápido sino perder la sesión que funciona.

---

## Ajustes

Todo lo configurable está en `salida/ajustes.json`, y se ve y se cambia
desde el botón **Ajustes**. Cada valor tiene un margen; lo que quede fuera
se recorta al límite y se avisa.

```bash
instagram_listas.py ajustes                      # verlos
instagram_listas.py ajustes --poner pausa_min=2  # cambiarlos
instagram_listas.py ajustes --restaurar          # dejarlos como venían
```

---

## Cuando algo falla

### Registro

El botón **Registro**, junto a la consola, enseña qué pasó, con los
errores en rojo y un buscador. El archivo es `salida/registro.log`. No
lleva cookies dentro, pero **sí los nombres de las cuentas que miras**:
tenlo en cuenta si lo compartes.

### Si Instagram cambia algo

```bash
instagram_listas.py diagnostico        # qué vía responde y cuál cambió
instagram_listas.py contratos          # rutas y nombres en uso
instagram_listas.py contratos --crear  # deja salida/rutas.json editable
```

Las rutas, los nombres de parámetros y los de campos se reparan ahí, **sin
tocar código**. Cuando algo falla se guarda un `fallo_*.json` con el
detalle completo; ese sí se puede compartir, no lleva tu sesión.

### Para pedir ayuda

```bash
instagram_listas.py --version
```

Dice versión, Python y sistema, que es lo primero que hace falta saber.

---

## Otras cosas

Si pides tu propia información a Instagram (Accounts Center, formato JSON,
sección «Followers and following»), esto la lee sin gastar nada:

```bash
instagram_listas.py importar export.zip
instagram_listas.py --cuenta TU importar export.zip --guardar
```

Solo vale para **tu** cuenta y no trae ids, así que se guarda aparte y no
como captura: mezclarlo estropearía el historial.

Al importarlo, comprueba **si el `timestamp` del export es de verdad la
fecha en que cada persona empezó a seguirte**, contrastándolo con tus
propias capturas: un sello posterior a la primera vez que ya veías a esa
persona es imposible, y muchos sellos en el mismo día significan que es la
fecha en que se generó el export. Con menos de diez personas cotejables no
opina.

`crudo_perfil_*.html` guarda la respuesta del perfil para poder mirarla
sin gastar peticiones. Los tokens que trae dentro se quitan al guardarlo
—una página de Instagram lleva un `csrf_token` aunque la pidas sin
sesión—, pero sigue fuera de las copias de seguridad por prudencia.

Todo lo que el programa escribe pensando en que lo compartas —`fallo_*.json`,
`registro.log`, `crudo_*`, la salida de las pruebas— pasa por el mismo
limpiador. El `ds_user_id` **no** se oculta: es el número de la cuenta, no
abre nada, y es lo que dice de quién era el error.

---

## Archivos

| | |
|---|---|
| `FocusMedia.pyw` | doble clic en Windows: la ventana sin consola |
| `construir.py` | empaqueta todo en un `.exe` |
| `instagram_gui.py` | la ventana |
| `instagram_listas.py` | el motor; funciona solo, sin la ventana |
| `ordenes.py` | lo que se pide desde la línea de órdenes |
| `informe_html.py` | el informe de una sola pieza |
| `indice_eventos.py` | la trayectoria de cada persona, sin releerlo todo |
| `export_instagram.py` | lee la exportación oficial de Instagram |
| `analitica.py` | cohortes, permanencia y composición |
| `copia.py` | copia de seguridad de una cuenta |
| `registro.py` | qué ha pasado, con rotación |
| `version.py` | qué versión es esto |
| `hacer_logo.py` | regenera `marca/` |
| `marca/` | el logo en todos los tamaños |
| `test_modulo.py` | lanza las pruebas del motor |
| `pruebas/` | las pruebas del motor, por temas |
| `pruebas/consola.py` | guarda la salida y espera, para el doble clic |
| `repartir.py` | script de un solo uso que las repartió |
| `test_gui.py` | las pruebas de la ventana |
| `pruebas/` | una página real de Instagram, como caso de prueba |
| `PROJECT_CONTEXT.md` | por qué está hecho así, y todo lo aprendido |

Las carpetas `salida/` y `sesiones/` las crea el programa. Las dos están
en `.gitignore`: la primera son tus datos, la segunda son tus cuentas.

---

## Pruebas

En Windows puedes darles doble clic: al terminar **esperan** a que pulses
Intro, y dejan todo lo que salió en `salida_pruebas_motor.txt` o
`salida_pruebas_ventana.txt`, al lado del programa. Ese archivo es el que
se puede mandar a alguien para que lo mire.

```bash
python test_modulo.py              # las 147 del motor
python test_modulo.py sesion       # solo un tema, mientras tocas esa parte
python test_modulo.py --temas      # qué temas hay
python test_gui.py                 # las de la ventana
```

No necesitan internet ni una sesión: se prueban contra un Instagram
falso. Las de la ventana necesitan poder abrir una ventana; donde no
se pueda, lo dicen y se saltan.

Las del motor viven en `pruebas/`, repartidas por temas:

| | |
|---|---|
| `sesion` | cookies, verificación, cortafuegos |
| `presupuesto` | topes, frenos, contadores |
| `capturas` | formato, metadatos, fusión, reanudación |
| `analisis` | comparar, historial, relaciones, estudio |
| `vigilancia` | varias cuentas, ritmo, programación |
| `pagina_publica` | lo que se saca sin iniciar sesión |
| `salidas` | informe, registro, copias, exportación |
| `proyecto` | nombres sueltos, README, versión, código muerto |

Casi cada prueba encierra **un fallo que pasó de verdad**, y lo explica en
un comentario. Esa es la razón de que existan: no persiguen cubrir cada
línea —eso produce bulto y confianza falsa— sino que lo ya roto no se
vuelva a romper.

---

## Uso

Es una herramienta para mirar tus propios datos con tu propia sesión. Usa
una cuenta secundaria, respeta los límites que la herramienta calcula, y
ten presente que los datos de otras personas que quedan en tus CSV son
suyos.
