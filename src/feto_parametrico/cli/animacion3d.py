#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
animacion3d.py — Video 3D del feto con órganos moviéndose dentro del útero.

    python animacion3d.py --eg 22 --duracion 6 --fps 12 -o movimiento_22s.mp4

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse

import numpy as np
import pyvista as pv

from ..feto3d import Escena
from ..movimiento import Movimiento, guion_demostracion
from ..vista3d import agregar_escena, malla_placenta, mallas_escena
from ..tejidos import TEJIDOS, T
from ..i18n import agregar_idioma, fijar_idioma, tr


def escena_estatica(esc):
    cav = pv.ParametricEllipsoid(*esc.cav, u_res=48, v_res=32, w_res=0)
    return [("utero", cav, TEJIDOS[T["miometrio"]].color, 0.10),
            ("placenta", malla_placenta(esc), TEJIDOS[T["placenta"]].color, 0.9)]


def animar(eg=22.0, duracion=6.0, fps=12, salida="movimiento_22s.mp4", semilla=None,
           resolucion_piel=90, tamano=(1280, 960), tiempos=None):
    mov = guion_demostracion(duracion) if semilla is None else Movimiento(semilla, duracion)
    esc0 = Escena(eg)
    estatica = escena_estatica(esc0)
    p = pv.Plotter(off_screen=True, window_size=tamano, lighting="three lights")
    p.set_background("#f7f4ef", top="#d9d4cc")
    p.enable_anti_aliasing("fxaa")
    lat = esc0.Rg[:, 1]                    # eje lateral del feto (en el mundo)
    agregar_escena(p, estatica, recorte=((0, 0, 0), -lat))
    p.camera_position = [tuple(-520 * lat + np.array([0, 0, 60])), (0, 0, 0),
                         tuple(-esc0.Rg[:, 2])]
    p.camera.zoom(1.25)
    (p.open_gif if salida.endswith(".gif") else p.open_movie)(
        salida, **({"fps": fps} if salida.endswith(".gif") else {"framerate": fps, "quality": 8}))
    nombres_previos = []
    tiempos = tiempos if tiempos is not None else [k / fps for k in range(int(duracion * fps))]
    for t in tiempos:
        esc = Escena(eg, mov.en(t), mat=esc0.mat)
        M = mallas_escena(esc, resolucion_piel, placenta=False, utero=False)
        for n in nombres_previos:
            p.remove_actor(n, render=False)
        agregar_escena(p, M)
        nombres_previos = [m[0] for m in M]
        p.add_text(tr("{eg:g} semanas   t = {t:4.2f} s", eg=eg, t=t), position="upper_left",
                   font_size=13, color="#222222", name="texto")
        p.write_frame()
    p.close()
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eg", type=float, default=22.0)
    ap.add_argument("--duracion", type=float, default=6.0)
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--semilla", type=int, default=None,
                    help="movimiento aleatorio; sin ella se usa el guion de demostración")
    ap.add_argument("-o", "--salida", default="movimiento_22s.mp4")
    agregar_idioma(ap)
    a = ap.parse_args(argv)
    fijar_idioma(a.idioma)
    print(animar(a.eg, a.duracion, a.fps, a.salida, a.semilla))


if __name__ == "__main__":
    main()
