#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_pyvista.py — Renders fuera de pantalla con PyVista/VTK.

    feto-render serie 12 20 28 36 40          # serie_crecimiento.png
    feto-render biometria 24                  # biometria_24s.png
    feto-render giro 28 -o giro_28s.mp4       # vuelta de 360° (mp4 o gif)
    feto-render crecimiento -o crecimiento.mp4 --paso 0.5
    feto-render organos 22                    # organos_utero_22s.png
    feto-render organos 22 --sin-utero        # organos_22s.png

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse

import numpy as np
import pyvista as pv

from ..feto_pv import (COLOR_CC, COLOR_DBP, COLOR_LF, agregar_feto, camara_lateral,
                     generar, texto_biometria)
from ..i18n import agregar_idioma, fijar_idioma, tr

FONDO = ("#f7f4ef", "#d9d4cc")     # degradado claro, adecuado para impresión


def _plotter(tamano=(1600, 900)):
    p = pv.Plotter(off_screen=True, window_size=tamano, lighting="three lights")
    p.set_background(FONDO[0], top=FONDO[1])
    p.enable_anti_aliasing("ssaa")
    return p


def _abrir_video(p, salida, fps):
    if salida.lower().endswith(".gif"):
        p.open_gif(salida, fps=fps)
    else:
        p.open_movie(salida, framerate=fps, quality=8)


def serie(edades, salida, resolucion):
    """Fetos a escala real, uno junto a otro, sobre una regla en mm."""
    datos = [generar(e, resolucion) for e in edades]
    p = _plotter((420 * len(edades), 900))
    x = 0.0
    xs = []
    for i, d in enumerate(datos):
        m = d["pv"]
        ancho = m.bounds[1] - m.bounds[0]
        m.translate((x + ancho / 2 - m.center[0], 0, -m.bounds[4]), inplace=True)
        xs.append(m.center[0])
        agregar_feto(p, d, nombre=f"feto{i}")
        p.add_point_labels([(m.center[0], 0, m.bounds[5] + 12)], [tr("{eg:g} sem", eg=d["eg"])],
                           font_size=22, text_color="#333333", shape=None,
                           show_points=False, always_visible=True)
        x += ancho + 0.25 * max(dd["pv"].bounds[1] - dd["pv"].bounds[0] for dd in datos)
    total = x
    p.add_ruler((0, 0, -15), (total, 0, -15), title="mm", number_labels=6,
                font_size_factor=0.7, label_size_factor=0.7, tick_length=4)
    p.view_xz()
    p.camera.elevation = 8
    p.camera.zoom(1.9)
    p.screenshot(salida)
    print(salida)


def biometria(eg, salida, resolucion):
    """Feto semitransparente con el plano de la CC, el DBP y los fémures."""
    d = generar(eg, resolucion)
    p = _plotter((1400, 1000))
    agregar_feto(p, d, opacidad=0.45, biometria=True)
    p.add_text(texto_biometria(d), position="upper_left", font_size=13, color="#222222")
    p.add_legend([[tr("contorno cefálico (CC)"), COLOR_CC],
                  [tr("diámetro biparietal (DBP)"), COLOR_DBP],
                  [tr("longitud femoral (LF)"), COLOR_LF]],
                 bcolor="white", border=True, size=(0.36, 0.15), loc="lower left")
    p.camera_position = "yz"
    p.camera.azimuth = -50
    p.camera.elevation = 18
    p.reset_camera(); p.camera.zoom(1.1)
    p.screenshot(salida)
    print(salida)


def giro(eg, salida, resolucion, cuadros=120, fps=30):
    """Vuelta completa alrededor del eje vertical."""
    d = generar(eg, resolucion)
    p = _plotter((640, 640) if salida.lower().endswith(".gif") else (960, 960))
    agregar_feto(p, d)
    p.add_text(tr("{eg:g} semanas", eg=eg), position="upper_left", font_size=14, color="#222222")
    radio = 0.5 * np.linalg.norm(d["pv"].bounds[1::2]) + 0.5 * np.linalg.norm(d["pv"].bounds[0::2])
    _abrir_video(p, salida, fps)
    for k in range(cuadros):
        camara_lateral(p, radio, azimut=-90 + 360 * k / cuadros, elevacion=12, distancia=2.6)
        p.write_frame()
    p.close()
    print(salida)


def crecimiento(salida, resolucion, paso=0.5, fps=12, eg0=12.0, eg1=40.0):
    """Animación del crecimiento con la cámara fija (escala real constante)."""
    edades = np.arange(eg0, eg1 + 1e-9, paso)
    grande = generar(eg1, 80)["pv"]
    radio = 0.5 * max(grande.bounds[1] - grande.bounds[0],
                      grande.bounds[3] - grande.bounds[2],
                      grande.bounds[5] - grande.bounds[4])
    p = _plotter((1088, 1088))
    _abrir_video(p, salida, fps)
    for eg in edades:
        d = generar(float(eg), resolucion)
        # apoyar el feto en el mismo "piso" en todas las edades
        d["pv"].translate((0, 0, -radio - d["pv"].bounds[4] + 0.0), inplace=True)
        agregar_feto(p, d)
        p.add_text(texto_biometria(d), position="upper_left", font_size=13,
                   color="#222222", name="texto")
        camara_lateral(p, radio, centro=(0, 0, 0), azimut=-70,
                       elevacion=10, distancia=4.6)
        p.write_frame()
    for _ in range(fps):          # pausa al final
        p.write_frame()
    p.close()
    print(salida)


def organos(eg, salida, resolucion, con_utero=True):
    """Feto con órganos; con el útero (cortado), la placenta y el cordón, o solo."""
    from ..feto3d import Escena
    from ..vista3d import agregar_escena, mallas_escena
    esc = Escena(eg)
    M = mallas_escena(esc, resolucion)
    p = _plotter((1600, 1100))
    if con_utero:
        agregar_escena(p, M, recorte=((0, 0, 0), (1, 0, 0)))
        p.camera_position = [(520, 60, 120), (0, 0, 0), (0, 1, 0)]
        p.camera.zoom(1.15)
        p.add_text(tr("{eg:g} semanas: órganos, útero (corte), placenta {sitio} y cordón",
                      eg=eg, sitio=tr(esc.mat.placenta)),
                   font_size=12, color="#333333")
    else:
        agregar_escena(p, [m for m in M if m[0] not in ("utero", "placenta", "cordon")])
        p.view_vector(-esc.Rg[:, 1], viewup=esc.Rg[:, 2])
        p.reset_camera(); p.camera.zoom(1.35)
    p.screenshot(salida)
    print(salida)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="modo", required=True)
    a = sub.add_parser("serie"); a.add_argument("eg", type=float, nargs="+")
    a = sub.add_parser("biometria"); a.add_argument("eg", type=float)
    a = sub.add_parser("giro"); a.add_argument("eg", type=float)
    a.add_argument("--cuadros", type=int, default=120)
    a = sub.add_parser("organos"); a.add_argument("eg", type=float)
    a.add_argument("--sin-utero", action="store_true")
    a = sub.add_parser("crecimiento")
    a.add_argument("--paso", type=float, default=0.5)
    a.add_argument("--fps", type=int, default=12)
    for s in sub.choices.values():
        s.add_argument("-o", "--salida")
        s.add_argument("-r", "--resolucion", type=int, default=160)
        agregar_idioma(s)
    args = ap.parse_args(argv)
    fijar_idioma(args.idioma)

    if args.modo == "serie":
        serie(args.eg, args.salida or "serie_crecimiento.png", args.resolucion)
    elif args.modo == "biometria":
        biometria(args.eg, args.salida or f"biometria_{args.eg:g}s.png", args.resolucion)
    elif args.modo == "giro":
        giro(args.eg, args.salida or f"giro_{args.eg:g}s.mp4", args.resolucion, args.cuadros)
    elif args.modo == "organos":
        nombre = f"organos_{args.eg:g}s.png" if args.sin_utero else f"organos_utero_{args.eg:g}s.png"
        organos(args.eg, args.salida or nombre, min(args.resolucion, 130), not args.sin_utero)
    else:
        crecimiento(args.salida or "crecimiento.mp4", args.resolucion, args.paso, args.fps)


if __name__ == "__main__":
    main()
