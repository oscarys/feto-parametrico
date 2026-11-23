# -*- coding: utf-8 -*-
"""
vista_previa.py — Vista previa rápida de la superficie fetal sólo con matplotlib
(sin VTK): varias edades a la misma escala y una edad desde cuatro ángulos.

    feto-vista-previa 12 20 28 36 40 -o vista_previa.png

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from ..superficie import malla_fetal
from ..i18n import agregar_idioma, fijar_idioma, tr


def dibujar(ax, m, lim, elev=10, azim=-60):
    tri = m.vertices[m.faces]
    luz = np.array([0.4, -0.6, 0.7]); luz /= np.linalg.norm(luz)
    sh = np.clip(m.face_normals @ luz, 0, 1) * 0.75 + 0.25
    col = np.c_[0.93 * sh, 0.72 * sh, 0.62 * sh, np.ones_like(sh)]
    ax.add_collection3d(Poly3DCollection(tri, facecolors=col, linewidths=0))
    for f in (ax.set_xlim, ax.set_ylim, ax.set_zlim):
        f(-lim, lim)
    ax.set_box_aspect((1, 1, 1)); ax.view_init(elev, azim); ax.set_axis_off()


def serie(edades, salida="vista_previa.png", resolucion=120):
    mallas = [malla_fetal(e, resolucion) for e in edades]
    lim = 0.6 * max(np.abs(m.vertices).max() for m in mallas)
    fig = plt.figure(figsize=(3.2 * len(edades), 7))
    for i, (e, m) in enumerate(zip(edades, mallas)):
        for j, (el, az) in enumerate([(8, -90), (15, -30)]):
            ax = fig.add_subplot(2, len(edades), j * len(edades) + i + 1, projection="3d")
            dibujar(ax, m, lim, el, az)
            if j == 0:
                ax.set_title(tr("{eg:g} semanas", eg=e), fontsize=13)
    fig.suptitle(tr("Misma escala para todas las edades"), fontsize=11)
    plt.tight_layout(); plt.savefig(salida, dpi=110); plt.close(fig)
    return salida


def cuatro_vistas(eg, salida, resolucion=160):
    m = malla_fetal(eg, resolucion)
    lim = 0.62 * np.abs(m.vertices).max()
    fig = plt.figure(figsize=(12, 4.5))
    for i, (el, az) in enumerate([(5, -90), (10, 0), (20, -40), (10, 180)]):
        ax = fig.add_subplot(1, 4, i + 1, projection="3d"); dibujar(ax, m, lim, el, az)
    plt.tight_layout(); plt.savefig(salida, dpi=110); plt.close(fig)
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("eg", type=float, nargs="*", default=[12, 20, 28, 36, 40])
    ap.add_argument("-o", "--salida", default="vista_previa.png")
    ap.add_argument("--detalle", type=float, default=None,
                    help="además, cuatro vistas de esta edad (vista_<EG>s.png)")
    agregar_idioma(ap)
    a = ap.parse_args(argv)
    fijar_idioma(a.idioma)
    print(serie(a.eg, a.salida))
    if a.detalle:
        print(cuatro_vistas(a.detalle, f"vista_{a.detalle:g}s.png"))


if __name__ == "__main__":
    main()
