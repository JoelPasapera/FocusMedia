#!/usr/bin/env python3
"""
informe_html.py  ·  un archivo HTML con todo lo que hay dentro

Convierte lo que ya está en disco en un solo archivo que se abre con doble
clic, se manda por correo y se guarda. Sin servidor, sin internet y sin
nada instalado: los datos van dentro, el CSS va dentro, el JavaScript va
dentro y la foto va dentro en base64.

Que sea autocontenido no es un capricho. Un informe que pida algo a un CDN
deja de funcionar sin conexión, y además avisa a un tercero cada vez que
lo abres. Aquí no sale ni una petición.

Por qué está en su propio archivo
---------------------------------
Generar HTML no tiene nada que ver con hablar con Instagram. `generar()` es
una función PURA —diccionario a texto—, así que se comprueba entera
sin tocar el disco ni la red. El módulo recoge los datos; este les da
forma.
"""

from __future__ import annotations

import html
import json

# Los mismos colores que la ventana: el informe es el mismo producto, no un
# anexo de otro sitio.
TEMA = {
    "canvas": "#0B0F14", "panel": "#121821", "raised": "#1A2330",
    "line": "#223041", "texto": "#DDE4EE", "dim": "#6F7D91",
    "acento": "#4FB3D9", "acento2": "#8C7BD8",
    "bien": "#63C68A", "aviso": "#E0A93F", "error": "#EB6A63",
}


def _json_para_html(dato) -> str:
    """
    JSON seguro de meter dentro de un <script>.

    Un nombre de perfil puede llevar '<' dentro (hay gente que se llama
    'Ana <3'), y la cadena '</script>' dentro del JSON cerraría la etiqueta
    antes de tiempo y volcaría el resto de los datos en la página como si
    fueran HTML. Escapando '<' no puede pasar.
    """
    return json.dumps(dato, ensure_ascii=False).replace("<", "\\u003c")


def _svg_evolucion(series: dict, ancho: int = 720, alto: int = 150) -> str:
    """
    La evolución de las dos listas, en SVG y sin JavaScript.

    Mismo criterio que la gráfica de la ventana: el eje X va por FECHA y no
    por posición —doce días y un día no pueden medir igual—, cada serie
    tiene su escala vertical, y los tramos son rectos. Una curva
    suavizada pasaría por valores que nunca se midieron.
    """
    from datetime import date

    def dia(f):
        try:
            return date.fromisoformat(f).toordinal()
        except (ValueError, TypeError):
            return None

    dibujables = {t: v for t, v in series.items() if len(v) >= 2}
    if not dibujables:
        return ('<p class="vacio">Con dos capturas de una misma lista se '
                "dibuja la evolución.</p>")

    dias = [d for v in series.values() for d in (dia(f) for f, _ in v)
            if d is not None]
    t0, t1 = (min(dias), max(dias)) if dias else (0, 0)
    izq, der = 90, ancho - 60
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" role="img" '
              'aria-label="Evolución de seguidores y seguidos">']

    for i, (tipo, color) in enumerate((("seguidores", TEMA["acento"]),
                                       ("seguidos", TEMA["acento2"]))):
        fila = alto / 2
        centro = fila * i + fila / 2
        partes.append(f'<text x="0" y="{centro + 4:.0f}" class="s-nombre">'
                      f"{tipo}</text>")
        datos = series.get(tipo, [])
        if len(datos) < 2:
            partes.append(f'<text x="{izq}" y="{centro + 4:.0f}" '
                          'class="s-nota">falta otra captura</text>')
            continue

        valores = [n for _, n in datos]
        bajo, alto_v = min(valores), max(valores)
        arriba, abajo = centro - fila * 0.30, centro + fila * 0.30
        puntos = []
        for j, (fecha, n) in enumerate(datos):
            d = dia(fecha)
            if d is None or t1 <= t0:
                x = izq + (der - izq) * j / max(len(datos) - 1, 1)
            else:
                x = izq + (der - izq) * (d - t0) / (t1 - t0)
            y = ((arriba + abajo) / 2 if alto_v == bajo
                 else abajo - (n - bajo) / (alto_v - bajo) * (abajo - arriba))
            puntos.append((x, y))

        traza = " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos)
        partes.append(f'<polyline points="{traza}" fill="none" '
                      f'stroke="{color}" stroke-width="2" '
                      'stroke-linejoin="round" stroke-linecap="round"/>')
        x, y = puntos[-1]
        partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" '
                      f'fill="{color}" stroke="{TEMA["panel"]}" '
                      'stroke-width="2"/>')
        cambio = datos[-1][1] - datos[-2][1]
        partes.append(f'<text x="{ancho}" y="{centro + 4:.0f}" '
                      f'class="s-delta">{cambio:+d}</text>')

    partes.append("</svg>")
    return "".join(partes)


# Lo que rompe una relación establecida va primero, pase lo que pase con
# las cantidades: un solo "dejó de seguir a la cuenta" importa más que
# cuarenta altas corrientes, y ordenar por cantidad lo enterraba.
ORDEN_CAMBIOS = ("dejó de seguir a la cuenta", "la cuenta dejó de seguirle",
                 "era mutuo y desapareció", "nuevo mutuo")


def _seccion_cambios(cambios: list, entre: list | None = None) -> str:
    """Los cambios de relación, si los hay. Todo respecto a la cuenta."""
    if not cambios:
        return ""
    por_tipo = {}
    for c in cambios:
        por_tipo.setdefault(c.get("cambio", ""), []).append(c)

    def peso(nombre):
        return (ORDEN_CAMBIOS.index(nombre) if nombre in ORDEN_CAMBIOS
                else len(ORDEN_CAMBIOS))

    bloques = []
    for cambio, gente in sorted(por_tipo.items(),
                                key=lambda kv: (peso(kv[0]), -len(kv[1]))):
        nombres = ", ".join(html.escape(str(g.get("username", "")))
                            for g in gente[:40])
        if len(gente) > 40:
            nombres += f" … y {len(gente) - 40} más"
        bloques.append(
            f'<div class="cambio"><h3>{html.escape(cambio)}'
            f'<span class="cuantos">{len(gente)}</span></h3>'
            f"<p>{nombres}</p></div>")
    cuando = ""
    if entre and len(entre) == 2:
        cuando = (' <span class="cuando">entre el '
                  + html.escape(str(entre[0])) + " y el "
                  + html.escape(str(entre[1])) + "</span>")
    return ('<section><h2>Qué cambió en la relación con la cuenta'
            + cuando + "</h2>" + "".join(bloques) + "</section>")


ESTILO = """
:root {{
  --canvas: {canvas}; --panel: {panel}; --raised: {raised};
  --line: {line}; --texto: {texto}; --dim: {dim};
  --acento: {acento}; --aviso: {aviso};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 32px 28px 64px; background: var(--canvas);
  color: var(--texto); font: 14px/1.5 "Segoe UI", Inter, system-ui, sans-serif;
}}
h1, h2, h3 {{ font-weight: 600; margin: 0; }}
h1 {{ font-size: 22px; }}
h2 {{ font-size: 15px; color: var(--dim); margin-bottom: 14px;
     font-weight: 500; }}
section {{ max-width: 1180px; margin: 0 auto 34px; }}

/* Identidad: la foto sujeta las dos líneas, como en la ventana */
.cabecera {{ display: flex; align-items: center; gap: 16px;
             max-width: 1180px; margin: 0 auto 30px; }}
.cabecera img {{ width: 62px; height: 62px; border-radius: 50%;
                 border: 1px solid var(--line); }}
.cabecera .sub {{ color: var(--dim); font-size: 13px; margin-top: 3px; }}

/* Las cifras son el producto: monoespaciadas y grandes */
.medidas {{ display: flex; gap: 1px; background: var(--line);
            border: 1px solid var(--line); border-radius: 8px;
            overflow: hidden; }}
.medida {{ flex: 1; background: var(--panel); padding: 16px 20px; }}
.medida .cifra {{ font: 30px/1 "Cascadia Mono", Consolas, monospace; }}
.medida .que {{ color: var(--dim); font-size: 12px; margin-top: 6px; }}

.grafica {{ background: var(--panel); border: 1px solid var(--line);
            border-radius: 8px; padding: 16px 20px; margin-top: 18px; }}
.grafica svg {{ width: 100%; height: auto; }}
.s-nombre {{ fill: {dim}; font-size: 12px; }}
.s-nota {{ fill: {dim}; font-size: 12px; }}
.s-delta {{ fill: {texto}; font-size: 12px; text-anchor: end;
            font-family: "Cascadia Mono", Consolas, monospace; }}
.vacio {{ color: var(--dim); margin: 0; }}
.cuando {{ font-weight: 400; }}

.avisos {{ border-left: 3px solid var(--aviso); padding: 4px 0 4px 14px;
           color: var(--aviso); max-width: 1180px; margin: 0 auto 26px; }}
.avisos p {{ margin: 3px 0; }}

.cambio {{ border-left: 3px solid var(--line); padding: 2px 0 2px 14px;
           margin-bottom: 16px; }}
.cambio h3 {{ font-size: 14px; display: flex; gap: 10px;
              align-items: baseline; }}
.cambio .cuantos {{ font: 12px "Cascadia Mono", Consolas, monospace;
                    color: var(--dim); }}
.cambio p {{ color: var(--dim); margin: 4px 0 0; font-size: 13px; }}

/* Controles */
.barra {{ display: flex; gap: 10px; align-items: center;
          margin-bottom: 12px; flex-wrap: wrap; }}
button, input {{ font: inherit; color: var(--texto); background: var(--raised);
                 border: 1px solid var(--line); border-radius: 6px;
                 padding: 7px 12px; }}
button {{ cursor: pointer; }}
button[aria-pressed="true"] {{ background: #2A3B4E; }}
input {{ min-width: 260px; }}
button:focus-visible, input:focus-visible, th:focus-visible {{
  outline: 2px solid var(--acento); outline-offset: 2px;
}}
.cuenta-filas {{ color: var(--dim); font: 12px "Cascadia Mono", monospace;
                 margin-left: auto; }}

/* Sin 'overflow: hidden': una cabecera 'sticky' dentro de un contenedor que
   recorta no se pega a nada, así que la fila de títulos se perdía al bajar
   por una tabla de 2.000 filas. El redondeo se hace en las esquinas. */
table {{ width: 100%; border-collapse: separate; border-spacing: 0;
         background: var(--panel); border: 1px solid var(--line);
         border-radius: 8px; }}
thead th:first-child {{ border-top-left-radius: 7px; }}
thead th:last-child {{ border-top-right-radius: 7px; }}
th, td {{ text-align: left; padding: 8px 12px; font-size: 13px;
          white-space: nowrap; }}
th {{ background: var(--raised); cursor: pointer; user-select: none;
      position: sticky; top: 0; }}
th .flecha {{ color: var(--dim); font-size: 10px; }}
tbody tr:nth-child(even) {{ background: #151C26; }}
td {{ font-family: "Cascadia Mono", Consolas, monospace; }}
td.txt {{ font-family: inherit; }}
.pie {{ max-width: 1180px; margin: 40px auto 0; color: var(--dim);
        font-size: 12px; border-top: 1px solid var(--line);
        padding-top: 14px; }}
"""


GUION = """
// Sin frameworks y sin dependencias: son ~80 líneas y así el archivo se
// abre igual dentro de diez años.
const DATOS = __DATOS__;

let lista = Object.keys(DATOS.listas)[0];
let orden = { columna: null, invertido: false };

const $ = (sel) => document.querySelector(sel);

function normalizar(v) {
  return String(v == null ? "" : v).toLowerCase();
}

function filtrar(filas, texto) {
  const t = texto.trim().toLowerCase();
  if (!t) return filas;
  return filas.filter((f) =>
    Object.values(f).some((v) => normalizar(v).includes(t)));
}

function ordenar(filas, columna, invertido) {
  if (!columna) return filas;
  // Los números se ordenan como números: si no, 100 va antes que 20.
  const copia = filas.slice();
  copia.sort((a, b) => {
    const x = a[columna], y = b[columna];
    // Number() y no parseFloat(): parseFloat("12abc") da 12, y entonces un
    // nombre de usuario que empieza por cifras se ordenaba como número. El
    // visor de la ventana usa float(), que es igual de estricto: la misma
    // columna tiene que ordenarse igual en los dos sitios.
    const nx = Number(String(x).trim()), ny = Number(String(y).trim());
    const numericos = String(x).trim() !== "" && String(y).trim() !== "" &&
      !isNaN(nx) && !isNaN(ny);
    const cmp = numericos ? nx - ny
      : normalizar(x).localeCompare(normalizar(y), "es");
    return invertido ? -cmp : cmp;
  });
  return copia;
}

function pintar() {
  const datos = DATOS.listas[lista];
  const visibles = ordenar(filtrar(datos.filas, $("#buscar").value),
                           orden.columna, orden.invertido);

  const vacias = datos.vacias || [];
  const cab = datos.columnas.map((c) => {
    const marca = orden.columna === c
      ? (orden.invertido ? " \\u25b2" : " \\u25bc") : "";
    // Una columna en blanco parece una avería; dicho así, es un dato que no
    // llegó. Mismo criterio que el visor de la ventana.
    const nombre = (DATOS.etiquetas[c] || c) +
      (vacias.includes(c) ? " (sin datos)" : "");
    return `<th tabindex="0" data-col="${c}">${nombre}` +
           `<span class="flecha">${marca}</span></th>`;
  }).join("");

  // Una sola escritura en el DOM: con 2.500 filas, hacerlo fila a fila se
  // nota y no aporta nada.
  const cuerpo = visibles.map((f) =>
    "<tr>" + datos.columnas.map((c) => {
      const v = f[c] == null ? "" : String(f[c]);
      const texto = (c === "nombre" || c === "biografia");
      const clase = texto ? ' class="txt"' : "";
      return `<td${clase}>${v.replace(/[<>&]/g, (x) =>
        ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[x])}</td>`;
    }).join("") + "</tr>").join("");

  $("#tabla").innerHTML = `<thead><tr>${cab}</tr></thead>` +
                          `<tbody>${cuerpo}</tbody>`;
  $("#cuenta-filas").textContent = visibles.length === datos.filas.length
    ? `${datos.filas.length} filas`
    : `${visibles.length} de ${datos.filas.length} filas`;

  document.querySelectorAll("th").forEach((th) => {
    const activar = () => {
      const c = th.dataset.col;
      orden = { columna: c,
                invertido: orden.columna === c ? !orden.invertido : false };
      pintar();
    };
    th.onclick = activar;
    th.onkeydown = (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        activar();
      }
    };
  });
}

function cambiarLista(nueva) {
  lista = nueva;
  orden = { columna: null, invertido: false };
  document.querySelectorAll("[data-lista]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.lista === nueva)));
  pintar();
}

document.querySelectorAll("[data-lista]").forEach((b) => {
  b.onclick = () => cambiarLista(b.dataset.lista);
});
$("#buscar").oninput = pintar;
cambiarLista(lista);
"""


def generar(datos: dict) -> str:
    """
    El informe entero, en una cadena. Función pura: dict -> HTML.

    No lee nada del disco ni sale a la red, así que se puede comprobar con
    un diccionario a mano.
    """
    cuenta = html.escape(str(datos.get("cuenta", "")))
    listas = datos.get("listas") or {}

    # Se escapa UNA vez, al final. Escapar al construir y otra vez al unir
    # dejaba «Ana &amp;amp; Co» en pantalla.
    sub = []
    if datos.get("nombre"):
        sub.append(str(datos["nombre"]))
    if datos.get("publicaciones"):
        sub.append(f"{datos['publicaciones']} publicaciones")
    subtitulo = html.escape(", ".join(sub))

    foto = datos.get("foto") or ""
    bloque_foto = (f'<img src="{foto}" alt="Foto de perfil de @{cuenta}">'
                   if foto else "")

    medidas = []
    for tipo in ("seguidores", "seguidos"):
        d = listas.get(tipo) or {}
        cifra = f"{d.get('total', 0):,}".replace(",", " ") if d else "—"
        cuando = html.escape(str(d.get("fecha", "sin capturas")))
        medidas.append(f'<div class="medida"><div class="cifra">{cifra}</div>'
                       f'<div class="que">{tipo} · {cuando}</div></div>')

    avisos = "".join(f"<p>{html.escape(str(a))}</p>"
                     for a in (datos.get("avisos") or []))
    bloque_avisos = f'<div class="avisos">{avisos}</div>' if avisos else ""

    botones = "".join(
        f'<button data-lista="{t}" aria-pressed="false">{t}</button>'
        for t in listas)

    carga = {
        "listas": {t: {"columnas": d.get("columnas", []),
                       "filas": d.get("filas", []),
                       "vacias": d.get("vacias", [])}
                   for t, d in listas.items()},
        "etiquetas": datos.get("etiquetas") or {},
    }

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FocusMedia · @{cuenta}</title>
<style>{ESTILO.format(**TEMA)}</style>
</head>
<body>

<header class="cabecera">
  {bloque_foto}
  <div>
    <h1>@{cuenta}</h1>
    <div class="sub">{subtitulo}</div>
  </div>
</header>

{bloque_avisos}

<section>
  <div class="medidas">{''.join(medidas)}</div>
  <div class="grafica">
    <h2>Evolución</h2>
    {_svg_evolucion(datos.get("evolucion") or {})}
  </div>
</section>

{_seccion_cambios(datos.get("cambios") or [], datos.get("comparado"))}

<section>
  <h2>Listas</h2>
  <div class="barra">
    {botones}
    <input id="buscar" type="search" placeholder="buscar en toda la tabla"
           aria-label="Buscar en la tabla">
    <span class="cuenta-filas" id="cuenta-filas"></span>
  </div>
  <table id="tabla"></table>
</section>

<p class="pie">
  Generado por FocusMedia {html.escape(str(datos.get('version', '')))} el
  {html.escape(str(datos.get('generado', '')))}.
  Todo va dentro de este archivo: se abre sin internet y no le pide nada a
  nadie.
</p>

<script>{GUION.replace('__DATOS__', _json_para_html(carga))}</script>
</body>
</html>
"""
