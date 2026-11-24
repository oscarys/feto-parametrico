#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_ecografia.py — Figuras y videos que combinan el modelo 3D con la
ecografía simulada.

    feto-eco planos   --eg 22   # planos_estandar_22s.png (+ medidas)
    feto-eco cabeza   --eg 22   # transcerebelar, perfil y nariz-labios (DTC, CM, HN)
    feto-eco latido   --eg 22   # cine de 4 cámaras (latido) .mp4
    feto-eco combinado --eg 22  # 3D + ecografía con el feto moviéndose
    feto-eco lote --n 32        # imágenes + etiquetas + JSON para entrenamiento
    feto-eco planos --sonda lineal   # con sonda lineal (o sectorial)
    feto-eco sondas           # un plano con las tres sondas (16 semanas por omisión)

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import json
import os

import imageio.v2 as imageio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv

from ..ecografia import (GEOMETRIAS, PLANOS, PLANOS_BIOMETRIA, TIPOS_SONDA, Adquisicion,
                         medir_en_imagen, plano_estandar, simular, sonda_para)

PLANOS_CABEZA = ("transcerebelar", "perfil", "nariz_labios")
from ..feto3d import Escena, Materno, Postura
from ..movimiento import Movimiento, guion_demostracion
from ..tejidos import COLORES, TEJIDOS, T
from ..vista3d import abanico_3d, agregar_escena, malla_placenta, mallas_escena, sonda_3d
from ..i18n import N_, agregar_idioma, fijar_idioma, tr

NOMBRES = {"transtalamico": N_("Transtalámico (CC, DBP)"),
           "transcerebelar": N_("Transcerebelar (DTC, CM)"), "cuatro_camaras": N_("Cuatro cámaras"),
           "abdominal": N_("Abdominal (CA)"), "femur": N_("Fémur (LF)"), "sagital": N_("Sagital medio"),
           "perfil": N_("Perfil (hueso nasal)"), "nariz_labios": N_("Nariz y labios")}
# nombre mostrado de cada medida que devuelve medir_en_imagen
TIPOS = {"convexa": N_("Convexa"), "lineal": N_("Lineal"),
         "sectorial": N_("Sectorial (phased array)")}
MEDIDAS = {"CC": N_("CC"), "DBP_ext": N_("DBP"), "DFO": N_("DFO"), "CA": N_("CA"), "LF": N_("LF"),
           "DTC": N_("DTC"), "CM": N_("CM"), "HN": N_("HN")}


# ---------------------------------------------------------------------------
# Abanico 3D texturizado con la imagen
# ---------------------------------------------------------------------------

def vista_plano(esc, pose, sonda, res, mallas, tamano=(900, 800), archivo=None, plotter=None):
    p = plotter or pv.Plotter(off_screen=True, window_size=tamano, lighting="three lights")
    if plotter is None:
        p.set_background("#f7f4ef", top="#d9d4cc")
        p.enable_anti_aliasing("ssaa")
    agregar_escena(p, mallas, recorte=((0, 0, 0), (1, 0, 0)))
    p.add_mesh(abanico_3d(pose, sonda, res), scalars="eco", cmap="gray", clim=(0, 1),
               show_scalar_bar=False, name="abanico", lighting=False)
    p.add_mesh(sonda_3d(pose, sonda), color="#3b4252", name="sonda")
    # cámara: mirando el plano de frente, un poco oblicua
    c = pose.origen + 0.55 * sonda.profundidad_mm * pose.ez
    n = pose.ey if pose.ey @ np.array([1, 0, 0.3]) > 0 else -pose.ey
    pos = c + 620 * (0.80 * n + 0.35 * np.array([0, 0, 1.0]) + 0.25 * pose.ex)
    p.camera_position = [tuple(pos), tuple(c), (0, 1, 0)]
    if archivo:
        p.screenshot(archivo)
    return p


def superponer_etiquetas(ax, res):
    lab = res["etiquetas"]
    img = np.where(lab[..., None] >= 0, COLORES[np.clip(lab, 0, None)], 0.0)
    ax.imshow(img, extent=res["extent"])


# ---------------------------------------------------------------------------
# Modos
# ---------------------------------------------------------------------------

def figura_planos(eg=22.0, salida=None, semilla=0, geometria="convexa", planos=PLANOS_BIOMETRIA):
    """Escena con la sonda, ecografía y etiquetas de cada plano, con sus medidas.
    Con planos=PLANOS_CABEZA: transcerebelar, perfil y nariz-labios."""
    cabeza = tuple(planos) == PLANOS_CABEZA
    sufijo = "" if geometria == "convexa" else f"_{geometria}"
    salida = salida or f"planos_{'cabeza' if cabeza else 'estandar'}_{eg:g}s{sufijo}.png"
    esc = Escena(eg)
    mallas = mallas_escena(esc, 140 if cabeza else 110)
    fig, ax = plt.subplots(3, len(planos), figsize=(5.2 * len(planos), 14.5),
                           gridspec_kw={"height_ratios": [1.15, 1, 1]})
    medidas = {}
    for j, nom in enumerate(planos):
        pose = plano_estandar(esc, nom)
        sonda = sonda_para(pose, geometria=geometria)
        px = 0.15 if sonda.es_lineal else 0.3
        res = simular(esc, pose, sonda, Adquisicion(elevacion=(-1.0, 0.0, 1.0), px_salida_mm=px),
                      semilla=semilla)
        med = medir_en_imagen(res, nom, px, pose)
        medidas[nom] = med
        tmp = f"/tmp/_vista_{nom}.png"
        vista_plano(esc, pose, sonda, res, mallas, archivo=tmp).close()
        ax[0, j].imshow(imageio.imread(tmp)); ax[0, j].set_axis_off()
        ax[0, j].set_title(tr(NOMBRES[nom]), fontsize=15)
        ax[1, j].imshow(res["bmodo"], cmap="gray", extent=res["extent"], vmin=0, vmax=1)
        superponer_etiquetas(ax[2, j], res)
        txt = "   ".join(f"{tr(MEDIDAS.get(k, k))} {v:.1f} mm" for k, v in med.items())
        ax[1, j].set_xlabel(txt, fontsize=11)
        for a in ax[1:, j]:
            a.set_facecolor("black"); a.tick_params(labelsize=8)
    bio = esc.feto.bio
    if cabeza:
        titulo = tr("{eg:g} semanas — esperado: DTC {dtc:.1f}, CM {cm:.1f}, HN {hn:.1f} mm"
                    "   |   fila 2: ecografía simulada; fila 3: etiquetas (máscaras de referencia)",
                    eg=eg, dtc=bio["DTC"], cm=bio["CM"], hn=bio["HN"])
    else:
        titulo = tr("{eg:g} semanas — Hadlock: DBP {dbp:.1f}, CC {cc:.1f}, CA {ca:.1f}, LF {lf:.1f} mm"
                    "   |   fila 2: ecografía simulada; fila 3: etiquetas (máscaras de referencia)",
                    eg=eg, dbp=bio["DBP"], cc=bio["CC"], ca=bio["CA"], lf=bio["LF"])
    fig.suptitle(titulo, fontsize=14)
    plt.tight_layout()
    plt.savefig(salida, dpi=90)
    plt.close(fig)
    print(salida, json.dumps({k: {m: round(v, 1) for m, v in d.items()} for k, d in medidas.items()}))
    return medidas


def figura_sondas(eg=16.0, salida=None, plano="transtalamico", semilla=0):
    """El mismo plano con cada tipo de sonda, a la misma escala."""
    salida = salida or f"sondas_{eg:g}s.png"
    esc = Escena(eg)
    pose = plano_estandar(esc, plano)
    sondas = [sonda_para(pose, geometria=g) for g in GEOMETRIAS]
    fondo = max(s.profundidad_mm for s in sondas)
    anchos = [2 * (s.radio_mm + s.profundidad_mm) * np.sin(np.deg2rad(s.apertura_grados / 2))
              if not s.es_lineal else s.ancho_mm for s in sondas]
    fig, ax = plt.subplots(1, len(sondas), figsize=(16, 6.2), facecolor="black",
                           gridspec_kw={"width_ratios": anchos})
    for a, s in zip(ax, sondas):
        px = 0.15 if s.es_lineal else 0.3
        res = simular(esc, pose, s, Adquisicion(elevacion=(-1.0, 0.0, 1.0), px_salida_mm=px),
                      semilla=semilla, etiquetas=False)
        a.imshow(res["bmodo"], cmap="gray", extent=res["extent"], vmin=0, vmax=1)
        a.set_ylim(fondo, 0)
        a.set_facecolor("black")
        a.set_title(f"{tr(TIPOS[s.geometria])}\n{s.f0_mhz:.1f} MHz", color="white", fontsize=13)
        a.tick_params(colors="0.7", labelsize=8)
        for lado in a.spines.values():
            lado.set_color("0.4")
    fig.suptitle(tr("{eg:g} semanas, plano {plano}: el mismo corte con cada tipo de sonda (mm)",
                    eg=eg, plano=tr(NOMBRES[plano])), color="white", fontsize=14)
    plt.tight_layout()
    plt.savefig(salida, dpi=90, facecolor="black")
    plt.close(fig)
    print(salida)


def cine_latido(eg=22.0, salida=None, fps=20, duracion=2.0):
    """Corte de 4 cámaras con la sonda fija; el corazón late y el feto respira."""
    salida = salida or f"latido_4c_{eg:g}s.mp4"
    esc0 = Escena(eg)
    pose = plano_estandar(esc0, "cuatro_camaras")
    sonda = sonda_para(pose, margen_mm=25)
    mov = Movimiento(semilla=1, duracion=duracion, intensidad=0.15, tasa_patadas=0,
                     tasa_brazos=0, tasa_giros=0)
    cuadros = []
    for k in range(int(duracion * fps)):
        t = k / fps
        esc = Escena(eg, mov.en(t), mat=esc0.mat)
        res = simular(esc, pose, sonda, etiquetas=False)
        img = (255 * res["bmodo"]).astype(np.uint8)
        # recorte alrededor del corazón
        cm = esc.a_mundo(esc.feto.marcos["corazon"][0]) - pose.origen
        cx = int((cm @ pose.ex - res["xs"][0]) / 0.3); cz = int((cm @ pose.ez - res["zs"][0]) / 0.3)
        h = 150
        pad = np.pad(img, h)                      # recorte de tamaño fijo aunque toque el borde
        rec = pad[cz:cz + 2 * h, cx:cx + 2 * h]
        rec = np.kron(rec, np.ones((2, 2), np.uint8))
        cuadros.append(rec)
    imageio.mimwrite(salida, cuadros, fps=fps, macro_block_size=1)
    print(salida)


def video_combinado(eg=22.0, salida=None, fps=8, duracion=6.0, plano="sagital"):
    """Izquierda: escena 3D con el abanico; derecha: la ecografía. Sonda fija."""
    salida = salida or f"combinado_{plano}_{eg:g}s.mp4"
    esc0 = Escena(eg)
    pose = plano_estandar(esc0, plano)
    sonda = sonda_para(pose)
    sonda.n_lineas = 200
    mov = guion_demostracion(duracion)
    placenta = ("placenta", malla_placenta(esc0), TEJIDOS[T["placenta"]].color, 0.9)
    utero = ("utero", pv.ParametricEllipsoid(*esc0.cav, u_res=48, v_res=32, w_res=0),
             TEJIDOS[T["miometrio"]].color, 0.10)
    escritor = imageio.get_writer(salida, fps=fps, macro_block_size=1, quality=8)
    for k in range(int(duracion * fps)):
        t = k / fps
        esc = Escena(eg, mov.en(t), mat=esc0.mat)
        res = simular(esc, pose, sonda, etiquetas=False, semilla=0)
        M = mallas_escena(esc, 85, placenta=False, utero=False) + [placenta, utero]
        p = vista_plano(esc, pose, sonda, res, M, tamano=(800, 720))
        p.add_text(tr("{eg:g} sem   t = {t:4.2f} s", eg=eg, t=t), font_size=12, color="#222222")
        izq = p.screenshot(return_img=True); p.close()
        fig = plt.figure(figsize=(8, 7.2), dpi=100)
        a = fig.add_axes([0, 0, 1, 1]); a.set_facecolor("black")
        a.imshow(res["bmodo"], cmap="gray", extent=res["extent"], vmin=0, vmax=1)
        a.set_axis_off()
        fig.canvas.draw()
        der = np.asarray(fig.canvas.buffer_rgba())[..., :3]
        plt.close(fig)
        from PIL import Image
        izq = np.asarray(Image.fromarray(np.ascontiguousarray(izq[..., :3])).resize((800, 720)))
        der = np.asarray(Image.fromarray(np.ascontiguousarray(der)).resize((800, 720)))
        escritor.append_data(np.hstack([izq, der]))
    escritor.close()
    print(salida)


def lote(n=32, carpeta="lote_eco", semilla=0, eg_rango=(18, 34), geometria="convexa"):
    """Imágenes aleatorias (EG, postura, plano, ganancia) con etiquetas y medidas."""
    rng = np.random.default_rng(semilla)
    os.makedirs(carpeta, exist_ok=True)
    meta = []
    for i in range(n):
        eg = float(rng.uniform(*eg_rango))
        mat = Materno(grasa_mm=float(rng.uniform(6, 30)),
                      placenta=str(rng.choice(["anterior", "posterior", "fundica", "lateral"])),
                      dorso_grados=float(rng.uniform(90, 200)))
        mov = Movimiento(semilla=int(rng.integers(1 << 30)), duracion=5)
        esc = Escena(eg, mov.en(float(rng.uniform(0, 5))), mat=mat)
        nom = str(rng.choice(PLANOS))
        try:
            pose = plano_estandar(esc, nom, giro_en_plano=float(rng.uniform(-12, 12)))
        except ValueError:
            continue
        _, fmin, fmax = TIPOS_SONDA[geometria]["f0"]
        sonda = sonda_para(pose, geometria=geometria,
                           f0_mhz=float(rng.uniform(fmin + 0.5, fmax - 1.0)))
        adq = Adquisicion(ganancia_db=float(rng.uniform(-6, 6)),
                          rango_dinamico_db=float(rng.uniform(45, 65)))
        res = simular(esc, pose, sonda, adq, semilla=i)
        base = os.path.join(carpeta, f"{i:04d}_{nom}")
        imageio.imwrite(base + "_img.png", (255 * res["bmodo"]).astype(np.uint8))
        imageio.imwrite(base + "_etq.png", (res["etiquetas"] + 1).astype(np.uint8))
        meta.append({"archivo": os.path.basename(base), "plano": nom, "eg": eg,
                     "biometria_hadlock": {k: esc.feto.bio[k] for k in ("DBP", "CC", "CA", "LF")},
                     "medidas_en_imagen": medir_en_imagen(res, nom, adq.px_salida_mm, pose),
                     "sonda": sonda.geometria, "f0_mhz": sonda.f0_mhz, "profundidad_mm": sonda.profundidad_mm,
                     "px_mm": adq.px_salida_mm, "placenta": mat.placenta,
                     "etiquetas": {t.nombre: k + 1 for k, t in enumerate(TEJIDOS)}})
        print(base)
    with open(os.path.join(carpeta, "etiquetas.json"), "w") as f:
        json.dump(meta, f, indent=1, default=float)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("modo", choices=["planos", "cabeza", "sondas", "latido", "combinado", "lote"])
    ap.add_argument("--eg", type=float, default=None,
                    help=tr("semanas (por omisión 22; 16 en el modo sondas)"))
    ap.add_argument("--plano", default=None, choices=PLANOS,
                    help=tr("plano (por omisión sagital; transtalamico en el modo sondas)"))
    ap.add_argument("--n", type=int, default=32)
    ap.add_argument("--sonda", default="convexa", choices=GEOMETRIAS,
                    help=tr("tipo de sonda (modos planos y lote)"))
    ap.add_argument("-o", "--salida")
    agregar_idioma(ap)
    a = ap.parse_args(argv)
    fijar_idioma(a.idioma)
    if a.modo == "sondas":
        figura_sondas(a.eg or 16.0, a.salida, plano=a.plano or "transtalamico")
        return
    eg = a.eg or 22.0
    if a.modo == "planos":
        figura_planos(eg, a.salida, geometria=a.sonda)
    elif a.modo == "cabeza":
        figura_planos(eg, a.salida, geometria=a.sonda, planos=PLANOS_CABEZA)
    elif a.modo == "latido":
        cine_latido(eg, a.salida)
    elif a.modo == "combinado":
        video_combinado(eg, a.salida, plano=a.plano or "sagital")
    else:
        lote(a.n, a.salida or "lote_eco", geometria=a.sonda)


if __name__ == "__main__":
    main()
