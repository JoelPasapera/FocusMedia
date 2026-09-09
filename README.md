<div align="center">

  <img src="marca/focusmedia_512.png" alt="FocusMedia" width="120">

  <h1>FocusMedia</h1>

  <p><strong>Seguimiento local de seguidores y seguidos de Instagram</strong></p>

  <p>
    Una herramienta de escritorio en Python para capturar listas de relaciones,
    detectar cambios entre capturas y construir un historial sobre los datos
    que ya tienes guardados.
  </p>

  <p>
    <a href="#-características">Características</a> ·
    <a href="#-arquitectura">Arquitectura</a> ·
    <a href="#-instalación">Instalación</a> ·
    <a href="#-uso">Uso</a> ·
    <a href="#-pruebas">Pruebas</a> ·
    <a href="#-consideraciones">Consideraciones</a>
  </p>

  <br>

  <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/GUI-CustomTkinter-1f6f8b?style=for-the-badge" alt="CustomTkinter">
  <img src="https://img.shields.io/badge/Data-CSV-4B9CD3?style=for-the-badge" alt="CSV">
  <img src="https://img.shields.io/badge/Status-Personal%20Project-555555?style=for-the-badge" alt="Personal project">

</div>

<br>

---

## ✦ ¿Qué es FocusMedia?

**FocusMedia** es un proyecto personal desarrollado en Python para observar la evolución de las relaciones de una cuenta de Instagram a partir de **capturas locales**.

La idea es sencilla:

> **capturar → conservar → comparar → entender la evolución**

La aplicación permite consultar el tamaño actual de las listas, descargar las listas completas de **seguidores** y **seguidos**, guardar capturas fechadas y, posteriormente, trabajar sobre esos datos incluso sin conexión.

No se plantea como un simple descargador. El diseño del proyecto gira alrededor de una preocupación más concreta: **hacer un seguimiento reproducible y resistente a fallos de una relación que cambia con el tiempo**.

---

## ◇ Características

<table>
<tr>
<td width="50%" valign="top">

### 🖥️ Interfaz de escritorio

Interfaz gráfica construida con **CustomTkinter**, con:

- consola de actividad en tiempo real;
- barra de progreso;
- estado de sesión;
- indicador visible del consumo de peticiones;
- selector de cuenta y listas;
- acciones organizadas por etapas;
- visor de CSV integrado;
- guía contextual según el estado actual.

</td>
<td width="50%" valign="top">

### ⚙️ Motor independiente

La lógica principal vive en `instagram_listas.py` y puede ejecutarse sin interfaz.

Esto permite utilizar el proyecto tanto:

- desde la GUI;
- desde la línea de comandos;
- como tarea automatizada, especialmente para la vigilancia periódica.

</td>
</tr>

<tr>
<td width="50%" valign="top">

### 📸 Capturas históricas

Las listas se almacenan como capturas fechadas.

Con varias capturas es posible determinar:

- quién apareció;
- quién desapareció;
- evolución de seguidores;
- evolución de seguidos;
- trayectoria histórica de una persona.

</td>
<td width="50%" valign="top">

### 🛡️ Diseño orientado a fallos

El motor incorpora mecanismos para:

- recordar vías que ya funcionaron;
- evitar repetir solicitudes innecesarias;
- detectar respuestas inesperadas;
- diferenciar errores de bloqueo;
- poner endpoints bloqueados en espera;
- cancelar descargas largas;
- conservar el progreso;
- rechazar análisis de capturas incompletas cuando podrían generar falsos cambios.

</td>
</tr>
</table>

---

## ◈ Flujo general

```text
                    ┌─────────────────────┐
                    │   Sesión del        │
                    │     navegador       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Crear / reutilizar│
                    │      sesión         │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      Consultar      │
                    │   perfiles/listas   │
                    └──────────┬──────────┘
                               │
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
       ┌──────────────────┐        ┌──────────────────┐
       │   Captura CSV    │        │ Diagnóstico /    │
       │  fechada + meta  │        │ contratos        │
       └────────┬─────────┘        └──────────────────┘
                │
                ▼
       ┌──────────────────────┐
       │ Comparación histórica│
       │   + historial        │
       └──────────┬───────────┘
                  │
                  ▼
       ┌──────────────────────┐
       │ Lectura local de     │
       │ tablas / evolución   │
       └──────────────────────┘
```

La GUI no contiene toda la lógica: funciona como una capa de interacción sobre el motor. Esto permite conservar la CLI y utilizar las operaciones largas sin necesidad de mantener abierta una ventana.

---

# 🧩 Arquitectura

## `instagram_listas.py` — motor

Es el núcleo del proyecto.

Se encarga de la:

- creación y reutilización de sesiones;
- lectura de cookies del navegador;
- comunicación con Instagram;
- control del presupuesto de peticiones;
- descargas paginadas;
- persistencia de capturas;
- comparación;
- historial;
- vigilancia;
- diagnóstico;
- contratos de respuesta;
- tratamiento de errores.

El motor puede funcionar de forma independiente de la interfaz.

### Estrategia de vías alternativas

Para determinadas operaciones, el proyecto mantiene varias vías posibles para obtener la misma información.

Conceptualmente:

```text
               ┌─ API interna
               │
Perfil ────────┼─ Página del perfil
               │
               └─ Buscador
```

Cuando una vía deja de funcionar o devuelve una respuesta incompatible, el motor puede probar otra y **recordar cuál funcionó** para evitar gastar peticiones inútiles en la siguiente ejecución.

---

## `instagram_gui.py` — interfaz

La GUI está diseñada alrededor del comportamiento del motor.

Las operaciones que pueden tardar minutos u horas se ejecutan en un **hilo separado**, mientras la interfaz recibe los mensajes mediante una cola.

```text
                Worker thread
                     │
                     │ print()
                     ▼
               ┌───────────┐
               │   Queue   │
               └─────┬─────┘
                     │
                     ▼
              GUI / consola
                     │
                     ▼
                after(...)
```

La GUI no modifica directamente los widgets desde el hilo de trabajo. Esto evita bloquear la ventana durante descargas largas y mantiene el estado de la aplicación actualizado.

La cancelación utiliza un punto de interrupción cooperativo que permite detener una descarga y conservar el progreso.

---

## `test_modulo.py` — regresión del motor

El proyecto incluye un banco de pruebas que **simula la API** para comprobar el comportamiento sin depender de una red real.

El archivo documenta **86 pruebas del motor**, incluyendo regresiones relacionadas con:

- bloqueos;
- sesiones;
- presupuesto;
- paginación;
- capturas incompletas;
- comparación;
- historial;
- cambio de nombre de usuarios;
- rutas y contratos;
- recuperación ante respuestas inesperadas.

---

## `test_gui.py` — pruebas de interfaz

La interfaz dispone de pruebas específicas para la lógica de la GUI y el arranque de la ventana.

El archivo documenta **34 pruebas de la ventana**, con casos para:

- cola de salida;
- progreso;
- ejecución en segundo plano;
- cancelación;
- ajustes;
- validación de cuentas;
- estados de sesión;
- panel de disco;
- guía contextual;
- indicador de gasto;
- visor de tablas;
- evolución gráfica;
- cierre limpio.

Las pruebas visuales necesitan un `DISPLAY`; el propio proyecto contempla `xvfb-run` para entornos sin pantalla.

---

# 📦 Instalación

## 1. Clona el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd FocusMedia
```

## 2. Instala las dependencias

```bash
pip install customtkinter requests browser_cookie3 pillow
```

---

# ▶️ Uso

## Interfaz gráfica

```bash
python instagram_gui.py
```

Flujo inicial recomendado:

```text
1. Escribe la cuenta
2. Importa la sesión del navegador
3. Pulsa "Contar"
4. Ejecuta "Listas completas"
5. Repite la captura otro día
6. Usa "Qué cambió" o "Historial"
```

La propia aplicación incluye una sección de **"Guía y ayuda"** para explicar qué hace cada acción y en qué orden conviene utilizarla.

---

## Línea de comandos

El motor también puede utilizarse directamente:

```bash
python instagram_listas.py -h
```

Esto es especialmente útil para automatizaciones y tareas programadas donde no conviene abrir una interfaz gráfica.

Entre las operaciones contempladas por el proyecto se encuentran:

| Operación | Propósito |
|---|---|
| `diagnostico` | Comprobar qué vías siguen respondiendo |
| `contratos` | Ver las rutas, parámetros y nombres que espera el motor |
| `contratos --crear` | Generar una configuración editable de contratos |
| `comparar` | Detectar cambios entre capturas |
| `historial` | Reconstruir la trayectoria de las personas a lo largo del tiempo |
| `vigilar` | Comprobar primero si hubo cambios y descargar solo cuando corresponde |
| `vigilar todas` | Revisar varias cuentas siguiendo el presupuesto disponible |

Consulta la ayuda integrada para ver la sintaxis exacta de cada comando:

```bash
python instagram_listas.py -h
```

---

# 📊 Qué puede analizar FocusMedia

Una vez que existen capturas válidas, buena parte del análisis deja de depender de Instagram.

### Comparación

Compara las dos últimas capturas para obtener, entre otras cosas:

```text
+----------------------+
|      QUÉ CAMBIÓ      |
+----------------------+
| Nuevos               |
| Salieron             |
| Diferencia de tamaño |
+----------------------+
```

### Historial

Con varias capturas, el proyecto puede reconstruir una trayectoria temporal:

```text
Fecha 1 ──┐
Fecha 2 ──┼──► presencia / ausencia
Fecha 3 ──┤
Fecha 4 ──┘
```

El historial utiliza identificadores cuando están disponibles para evitar interpretar un **cambio de nombre** como una baja seguida de un alta.

### Evolución de totales

La interfaz puede representar la evolución de seguidores y seguidos a partir de los metadatos de las capturas.

---

# 🗂️ Estructura del proyecto

```text
FocusMedia/
│
├── marca/
│   ├── focusmedia.ico
│   ├── focusmedia.png
│   ├── focusmedia_16.png
│   ├── focusmedia_32.png
│   ├── focusmedia_48.png
│   ├── focusmedia_64.png
│   ├── focusmedia_128.png
│   ├── focusmedia_256.png
│   └── focusmedia_512.png
│
├── .gitignore
├── hacer_logo.py
├── instagram_gui.py
├── instagram_listas.py
├── LEEME.txt
├── PROJECT_CONTEXT.md
├── test_gui.py
└── test_modulo.py
```

### Recursos generados localmente

El proyecto utiliza archivos locales para conservar estado y resultados. Entre ellos se contemplan:

```text
sesion_instagram.json
config_gui.json
salida/
__pycache__/
```

Estos elementos están incluidos en `.gitignore` y **no deberían publicarse en el repositorio**.

---

# 🔬 Diseño y decisiones técnicas

FocusMedia está construido alrededor de varias decisiones deliberadas.

### 1. El presupuesto de peticiones es un recurso de primera clase

La aplicación no oculta el gasto: lo muestra en la interfaz y lo utiliza antes de iniciar operaciones costosas.

Esto permite estimar el coste de una descarga antes de comenzar y aplazarla cuando no cabe en el presupuesto disponible.

### 2. Los bloqueos se gestionan por endpoint

Un `429` no implica necesariamente que todo el sistema esté inutilizable.

El motor mantiene un enfriamiento por endpoint para no castigar las rutas que todavía responden correctamente.

### 3. La sesión se reutiliza

La verificación repetida de una sesión consume peticiones. Por ello, el motor reutiliza la sesión durante un periodo de caché y puede recordar cuál fue la vía de comprobación que funcionó.

### 4. Las capturas incompletas no se tratan como datos válidos

Una captura truncada puede hacer parecer que decenas o cientos de personas desaparecieron cuando, en realidad, simplemente no llegaron a descargarse.

Por eso el proyecto conserva metadatos sobre la completitud y evita incluir automáticamente esas capturas en comparaciones e historiales.

### 5. El análisis local permanece disponible

Comparar, reconstruir historiales y visualizar CSV son operaciones que trabajan sobre los datos almacenados.

Una vez que las capturas están en disco, estas tareas pueden realizarse incluso cuando Instagram no responde.

### 6. Los contratos están desacoplados

Las rutas, nombres de parámetros y nombres de campos que espera Instagram se concentran en una capa de contratos.

La intención es que un cambio de estructura pueda repararse modificando el contrato, sin tener que reescribir toda la lógica del motor.

---

# ⚠️ Limitaciones y consideraciones

## Instagram puede cambiar en cualquier momento

El proyecto trabaja con **endpoints y respuestas internas de Instagram**, no con una API pública estable diseñada específicamente para esta herramienta.

Por tanto:

- una actualización de Instagram puede romper una ruta;
- los nombres de campos pueden cambiar;
- una respuesta puede seguir siendo `200` y, aun así, tener una forma incompatible;
- una cuenta o sesión puede responder de manera distinta según el contexto.

El proyecto incorpora diagnóstico y contratos precisamente para hacer visibles estos cambios y reducir el coste de mantenimiento.

---

## 🔐 La sesión del navegador es información sensible

FocusMedia no solicita la contraseña de Instagram. La aplicación reutiliza la sesión existente del navegador mediante cookies.

Eso significa que debes tratar los archivos de sesión como **credenciales sensibles**.

Nunca publiques en GitHub:

```text
sesion_instagram.json
```

El proyecto ya lo excluye mediante `.gitignore`, pero conviene revisar siempre qué archivos se están subiendo antes de hacer un `git push`.

---

## 🍪 Navegadores y cookies

El proyecto contempla varios navegadores, pero en Windows la lectura de cookies puede presentar dificultades en algunos navegadores con cifrado.

La propia interfaz muestra un aviso específico para este escenario y contempla Firefox como alternativa cuando la lectura de cookies falla.

---

## 👤 "Salió" no significa necesariamente "dejó de seguirte"

Una desaparición entre capturas solamente indica que la persona ya no aparece en la fuente consultada.

Desde fuera, una salida puede deberse a diferentes causas, por ejemplo:

- unfollow;
- cuenta eliminada;
- cuenta suspendida;
- bloqueo;
- cambio en la información disponible.

FocusMedia **no pretende afirmar la causa exacta** cuando los datos no permiten distinguirla.

---

# 🧪 Verificación del proyecto

Para comprobar el motor:

```bash
python test_modulo.py
```

Para comprobar la interfaz:

```bash
python test_gui.py
```

En un entorno Linux sin pantalla:

```bash
xvfb-run -a python test_gui.py
```

---

# 🖼️ Marca

El logotipo también forma parte del proyecto.

`hacer_logo.py` genera distintos tamaños para que la marca conserve legibilidad desde el icono de 16 px hasta recursos de mayor resolución.

```bash
python hacer_logo.py
```

La idea visual del logo es una **lupa que contiene una pequeña red**, con un único nodo en ámbar representando el elemento que cambió.

---

# 🎯 Objetivo del proyecto

FocusMedia nace de una idea concreta:

> **No basta con obtener una lista. Lo interesante es poder guardar una fotografía de esa lista y entender cómo cambia con el tiempo.**

Por eso el proyecto pone tanto énfasis en:

- capturas reproducibles;
- presupuesto y coste;
- tolerancia a fallos;
- análisis histórico;
- persistencia local;
- separación entre motor e interfaz;
- diagnóstico de cambios;
- pruebas de regresión.

---

# 👨‍💻 Autoría

Proyecto personal desarrollado en Python.

Este repositorio documenta el diseño, implementación, decisiones técnicas y evolución de **FocusMedia** como trabajo propio.

---

# 📄 Documentación interna

Dentro del proyecto se incluyen dos documentos especialmente útiles:

- `LEEME.txt` — guía rápida de instalación, uso y comprobación.
- `PROJECT_CONTEXT.md` — contexto técnico, decisiones de diseño y conocimiento acumulado durante el desarrollo.

Para una lectura rápida, comienza por `LEEME.txt`. Para entender **por qué** determinadas partes del sistema están diseñadas de esta manera, consulta `PROJECT_CONTEXT.md`.

---

<div align="center">

### FocusMedia

**Observar una red es fácil. Entender cómo cambia es el proyecto.**

</div>
