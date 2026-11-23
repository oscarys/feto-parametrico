# Licencia: GPL-3.0-or-later
"""Convierte un MP4 en GIF compacto sin ruido de color: los píxeles casi grises
(moteado de la ecografía, comprimido en YUV 4:2:0) se vuelven grises exactos y
todos los cuadros comparten una paleta global."""
import sys

import imageio.v3 as iio
import numpy as np
from PIL import Image


def limpiar(fr, umbral=28):
    f = fr.astype(np.int16)
    croma = np.max(f, axis=2) - np.min(f, axis=2)
    gris = (0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2]).astype(np.int16)
    out = np.where((croma < umbral)[..., None], gris[..., None], f)
    return np.clip(out, 0, 255).astype(np.uint8)


def convertir(entrada, salida, ancho, cada=1, fps=None):
    cuadros = iio.imread(entrada, index=None)[::cada]
    meta = iio.immeta(entrada)
    fps = fps or meta.get("fps", 12) / cada
    ims = []
    for fr in cuadros:
        im = Image.fromarray(limpiar(fr))
        im = im.resize((ancho, round(im.height * ancho / im.width)), Image.LANCZOS)
        ims.append(im)
    # paleta global a partir de un mosaico de cuadros
    muestra = ims[:: max(1, len(ims) // 8)]
    mosaico = Image.new("RGB", (ims[0].width, ims[0].height * len(muestra)))
    for i, im in enumerate(muestra):
        mosaico.paste(im, (0, i * im.height))
    paleta = mosaico.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [im.quantize(palette=paleta, dither=Image.Dither.NONE) for im in ims]
    q[0].save(salida, save_all=True, append_images=q[1:], duration=int(1000 / fps),
              loop=0, optimize=True)


if __name__ == "__main__":
    convertir(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 1)
