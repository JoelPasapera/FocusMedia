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

`crudo_perfil_*.html` guarda la respuesta del perfil para poder mirarla
sin gastar peticiones. **No lo compartas**: lleva tu sesión dentro. Por
eso tampoco entra en las copias de seguridad.

---

## Archivos

| | |
|---|---|
| `instagram_gui.py` | la ventana |
| `instagram_listas.py` | el motor; funciona solo, sin la ventana |
| `ordenes.py` | lo que se pide desde la línea de órdenes |
| `informe_html.py` | el informe de una sola pieza |
| `indice_eventos.py` | la trayectoria de cada persona, sin releerlo todo |
| `export_instagram.py` | lee la exportación oficial de Instagram |
| `copia.py` | copia de seguridad de una cuenta |
| `registro.py` | qué ha pasado, con rotación |
| `version.py` | qué versión es esto |
| `hacer_logo.py` | regenera `marca/` |
| `marca/` | el logo en todos los tamaños |
| `test_modulo.py` | las pruebas del motor |
| `test_gui.py` | las pruebas de la ventana |
| `PROJECT_CONTEXT.md` | por qué está hecho así, y todo lo aprendido |

Las carpetas `salida/` y `sesiones/` las crea el programa. Las dos están
en `.gitignore`: la primera son tus datos, la segunda son tus cuentas.

---

## Pruebas

```bash
python test_modulo.py
python test_gui.py
```

No necesitan internet ni una sesión: se prueban contra un Instagram falso.

---

## Uso

Es una herramienta para mirar tus propios datos con tu propia sesión. Usa
una cuenta secundaria, respeta los límites que la herramienta calcula, y
ten presente que los datos de otras personas que quedan en tus CSV son
suyos.
