#!/usr/bin/env python3
"""
Genera el logo de FocusMedia en todos los tamaños que hacen falta.

Idea: una lupa cuya lente enseña una pequeña red de nodos, con UNO en ámbar
— el que cambió. El guiño detectivesco por fuera, y por dentro lo que la
herramienta hace de verdad: mirar una red y ver quién se movió.

A 16 y 32 píxeles la red desaparece: a ese tamaño solo se distingue el aro,
el mango y un punto. Dibujar los cinco nodos ahí sería una mancha.

    python hacer_logo.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SALIDA = Path(__file__).parent / "marca"

ACENTO = (70, 168, 214, 255)      # cian del tema
CLARO = (220, 227, 237, 255)      # nodos normales
AMBAR = (227, 179, 65, 255)       # el nodo que cambió
LENTE = (21, 27, 36, 255)         # relleno de la lente

ESCALA = 8                        # se dibuja grande y se reduce: antialias


def _lupa(d: ImageDraw.ImageDraw, s: int, detalle: str) -> None:
    """Aro, mango y, según el tamaño, más o menos red dentro."""
    cx, cy = s * 0.43, s * 0.40
    r = s * 0.29
    grosor = max(2, int(s * 0.075))

    # Mango: desde el borde del aro hacia abajo a la derecha, en diagonal.
    ang = math.radians(45)
    x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
    x2, y2 = s * 0.86, s * 0.83
    d.line([(x1, y1), (x2, y2)], fill=ACENTO, width=int(grosor * 1.15))
    # Punta redondeada: la línea sola deja un corte feo en diagonal.
    pr = grosor * 0.57
    d.ellipse([x2 - pr, y2 - pr, x2 + pr, y2 + pr], fill=ACENTO)

    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=LENTE)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACENTO, width=grosor)

    if detalle == "minimo":
        # A 32 píxeles o menos solo se distingue el aro y un punto. Dibujar
        # la red ahí sería una mancha.
        pr = r * 0.32
        d.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=AMBAR)
        return

    if detalle == "medio":
        # Entre 48 y 96: tres nodos. Seis se emborronaban.
        nodos = [(-0.38, 0.22), (0.34, -0.34), (0.06, 0.06)]
        indice_cambiado = 1
        enlaces = [(2, 0), (2, 1)]
    else:
        # Red completa. Posiciones a mano: repartidas pero no simétricas,
        # para que parezca una red y no un adorno geométrico.
        nodos = [(-0.42, -0.34), (0.34, -0.46), (0.46, 0.20),
                 (-0.10, 0.48), (-0.52, 0.16), (0.02, -0.02)]
        indice_cambiado = 1
        enlaces = [(5, 0), (5, 1), (5, 2), (5, 3), (5, 4), (0, 1), (3, 4)]

    puntos = [(cx + dx * r, cy + dy * r) for dx, dy in nodos]

    grueso = max(1, int(s * (0.018 if detalle == "medio" else 0.012)))
    for a, b in enlaces:
        d.line([puntos[a], puntos[b]], fill=(70, 168, 214, 140),
               width=grueso)

    for i, (px, py) in enumerate(puntos):
        # Un solo nodo en ámbar: el que cambió. Es la idea entera.
        cambiado = i == indice_cambiado
        grande = 0.26 if detalle == "medio" else 0.20
        pequeno = 0.19 if detalle == "medio" else 0.14
        pr = r * (grande if cambiado else pequeno)
        d.ellipse([px - pr, py - pr, px + pr, py + pr],
                  fill=AMBAR if cambiado else CLARO)


def hacer(tam: int) -> Image.Image:
    s = tam * ESCALA
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    detalle = "completo" if tam >= 128 else "medio" if tam >= 48 else "minimo"
    _lupa(ImageDraw.Draw(img), s, detalle)
    return img.resize((tam, tam), Image.LANCZOS)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    tamanos = [512, 256, 128, 64, 48, 32, 16]
    imagenes = {t: hacer(t) for t in tamanos}

    for t, img in imagenes.items():
        img.save(SALIDA / f"focusmedia_{t}.png")

    # .ico multi-tamaño: Windows elige el que necesita en cada sitio.
    imagenes[256].save(SALIDA / "focusmedia.ico",
                       sizes=[(t, t) for t in (256, 128, 64, 48, 32, 16)])

    # El que carga la interfaz.
    imagenes[64].save(SALIDA / "focusmedia.png")

    print(f"Generado en {SALIDA}:")
    for f in sorted(SALIDA.iterdir()):
        print(f"  {f.name:24} {f.stat().st_size:>7} bytes")


if __name__ == "__main__":
    main()
