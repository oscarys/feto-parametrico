#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
superficie.py — Modelo de superficie triangulada de un feto humano,
parametrizado por la edad gestacional (semanas de amenorrea).

Idea general
------------
1. La biometría (DBP, CC, CA, LF) se obtiene de las regresiones de
   Hadlock et al. (Radiology 1984;152:497-501, doi:10.1148/radiology.152.2.6739822),
   válidas aprox. 12-40 semanas:
       DBP = -3.08  + 0.41 EG - 0.000061  EG^3     [cm]
       CC  = -11.48 + 1.56 EG - 0.0002548 EG^3     [cm]
       CA  = -13.3  + 1.61 EG - 0.00998   EG^2     [cm]
       LF  = -3.91  + 0.427 EG - 0.0034   EG^2     [cm]
2. El resto de las dimensiones (longitud del tronco, huesos largos que no
   son el fémur, grosor de las extremidades, ángulos de flexión) se deriva
   de esas cuatro con proporciones heurísticas, documentadas en
   `Proporciones`. No son datos clínicos: son un punto de partida editable.
3. El cuerpo se describe como una función de distancia con signo (SDF):
   elipsoides y conos redondeados unidos con una unión suave.
4. La isosuperficie SDF = 0 se extrae con marching cubes, se suaviza
   (Taubin, que no encoge la malla) y se exporta en STL/OBJ/PLY.

Unidades: milímetros.  Ejes: x anterior, y izquierda del feto, z superior.

Uso
---
    feto-malla 20                    # feto_20s.stl
    feto-malla 32 -o feto32.obj -r 220
    feto-malla 12 20 28 36 --informe

    from .superficie import malla_fetal, biometria
    malla = malla_fetal(24)       # objeto trimesh.Trimesh
    malla.export("feto24.ply")

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field

import numpy as np
import trimesh
from skimage.measure import marching_cubes

from . import cabeza

EG_MIN, EG_MAX = 12.0, 40.0   # intervalo de validez de las regresiones


# ---------------------------------------------------------------------------
# Biometría
# ---------------------------------------------------------------------------

def biometria(eg: float) -> dict:
    """Biometría fetal esperada (mediana, Hadlock 1984) en mm."""
    if not (EG_MIN <= eg <= EG_MAX):
        print(f"Aviso: EG = {eg} sem está fuera de {EG_MIN:.0f}-{EG_MAX:.0f} sem; "
              "las regresiones se extrapolan.", file=sys.stderr)
    dbp = -3.08 + 0.41 * eg - 0.000061 * eg**3
    cc = -11.48 + 1.56 * eg - 0.0002548 * eg**3
    ca = -13.3 + 1.61 * eg - 0.00998 * eg**2
    lf = -3.91 + 0.427 * eg - 0.0034 * eg**2
    # Peso fetal estimado, Hadlock et al. AJOG 1985, doi:10.1016/0002-9378(85)90298-4 (CC, CA, LF en cm)
    pfe = 10 ** (1.326 - 0.00326 * ca * lf + 0.0107 * cc + 0.0438 * ca + 0.158 * lf)
    return {"EG_sem": eg, "DBP": 10 * dbp, "CC": 10 * cc,
            "CA": 10 * ca, "LF": 10 * lf, "PFE_g": pfe}


def largo_pie(eg: float, lf: float) -> float:
    """Longitud del pie (talón a punta, mm) = LF: razón LF/pie constante de 1.

    La razón se mantiene cerca de 1 durante toda la gestación (Joshi et al.;
    Ravisankar et al. 2025, doi:10.7759/cureus.84515). Merz et al. (Ultraschall
    Med 2000, doi:10.1055/s-2000-12986) la reportan bajando a 0.85 al término,
    pero con la LF de Hadlock eso daría ~91 mm a las 40 semanas, más que el pie
    del recién nacido a término (~78 mm, doi:10.4314/gmj.v57i3.11). `eg` se
    conserva en la firma por si se quiere una razón dependiente de la edad."""
    return lf


def semieje_mayor_elipse(perimetro: float, b: float) -> float:
    """Semieje a de la elipse cuyo perímetro (Ramanujan II) es `perimetro`
    y cuyo otro semieje es b. Bisección sencilla."""
    def per(a):
        h = ((a - b) / (a + b)) ** 2
        return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
    lo, hi = 0.2 * b, 5.0 * b
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if per(mid) < perimetro else (lo, mid)
    return 0.5 * (lo + hi)


def semiejes_por_perimetro(perimetro: float, razon: float) -> tuple[float, float]:
    """Semiejes (a, b) de una elipse con b = razon*a y perímetro dado."""
    def per(a):
        bb = razon * a
        h = ((a - bb) / (a + bb)) ** 2
        return math.pi * (a + bb) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
    lo, hi = 1e-3, perimetro
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if per(mid) < perimetro else (lo, mid)
    a = 0.5 * (lo + hi)
    return a, razon * a


# ---------------------------------------------------------------------------
# Proporciones heurísticas (editables)
# ---------------------------------------------------------------------------

@dataclass
class Proporciones:
    # Cabeza
    altura_cabeza: float = 0.88      # semieje vertical / semieje fronto-occipital
    flexion_cabeza_grados: float = 30.0
    largo_cuello: float = 0.12       # × DBP
    # Tronco
    largo_tronco: float = 1.95       # (cuello a nalgas) × diámetro abdominal medio
    curvatura_tronco_grados: float = 55.0
    razon_ap_abdomen: float = 0.92   # diámetro AP / transverso del abdomen
    # Huesos largos relativos al fémur (aprox. curvas de Jeanty)
    tibia: float = 0.88
    humero: float = 0.93
    cubito: float = 0.84
    pie: float = 1.0                 # factor sobre largo_pie() (talón a punta)
    mano: float = 0.62
    # Grosor de las extremidades: radio proximal / LF
    radio_muslo: float = 0.33
    radio_brazo: float = 0.22
    engrosamiento_tardio: float = 0.50   # aumento relativo del grosor de 12 a 40 sem
    # Posición fetal
    flexion_cadera_grados: float = 115.0
    flexion_rodilla_grados: float = 125.0
    abduccion_muslo: float = 0.30


# ---------------------------------------------------------------------------
# Primitivas SDF (vectorizadas, puntos P de forma (N, 3))
# ---------------------------------------------------------------------------

def _local(P, centro, R):
    """Coordenadas de P en el sistema local (columnas de R = ejes locales)."""
    return (P - centro) @ R


def sdf_elipsoide(P, centro, semiejes, R=np.eye(3)):
    q = _local(P, centro, R)
    r = np.asarray(semiejes, dtype=np.float32)
    k0 = np.linalg.norm(q / r, axis=1)
    k1 = np.linalg.norm(q / (r * r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sdf_cono_redondeado(P, a, b, ra, rb):
    """Segmento a→b con radios ra y rb en los extremos (Quilez)."""
    a = np.asarray(a, np.float32); b = np.asarray(b, np.float32)
    ba = b - a
    l2 = float(ba @ ba)
    rr = ra - rb
    a2 = l2 - rr * rr
    il2 = 1.0 / l2
    pa = P - a
    y = pa @ ba
    z = y - l2
    xv = pa * l2 - np.outer(y, ba)
    x2 = np.einsum("ij,ij->i", xv, xv)
    y2 = y * y * l2
    z2 = z * z * l2
    k = math.copysign(1.0, rr) * rr * rr * x2
    d = np.empty_like(y)
    m1 = np.sign(z) * a2 * z2 > k
    m2 = (~m1) & (np.sign(y) * a2 * y2 < k)
    m3 = ~(m1 | m2)
    d[m1] = np.sqrt(x2[m1] + z2[m1]) * il2 - rb
    d[m2] = np.sqrt(x2[m2] + y2[m2]) * il2 - ra
    d[m3] = (np.sqrt(x2[m3] * a2 * il2) + y[m3] * rr) * il2 - ra
    return d


def union_suave(d1, d2, k):
    """Unión suave polinomial; k en mm (ancho de la transición)."""
    h = np.clip(0.5 + 0.5 * (d2 - d1) / k, 0.0, 1.0)
    return d2 * (1 - h) + d1 * h - k * h * (1 - h)


def resta_suave(d, dc, k):
    """Sustracción suave: quita de `d` el sólido `dc`; k en mm."""
    k = max(k, 1e-3)
    h = np.clip(0.5 - 0.5 * (d + dc) / k, 0.0, 1.0)
    return d * (1 - h) - dc * h + k * h * (1 - h)


def recortar(d, Q, corte):
    """Conserva sólo n·Q <= dd; corte = (n, dd) o (n, dd, k) con borde suave de k mm."""
    n, dd = corte[0], corte[1]
    pl = Q @ np.asarray(n, np.float32) - dd
    if len(corte) > 2 and corte[2] > 0:
        return -union_suave(-d, -pl, corte[2])          # máximo suave
    return np.maximum(d, pl)


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def _marco(eje_x, eje_z):
    """Matriz de rotación con columnas (x, y, z) ortonormales."""
    z = _unit(eje_z)
    x = _unit(np.asarray(eje_x) - (np.asarray(eje_x) @ z) * z)
    y = np.cross(z, x)
    return np.column_stack([x, y, z]).astype(np.float32)


# ---------------------------------------------------------------------------
# Esqueleto geométrico del feto
# ---------------------------------------------------------------------------

@dataclass
class Pieza:
    nombre: str
    tipo: str                      # "elipsoide" | "cono"
    params: dict
    k: float                       # unión suave con el resto del cuerpo
    extension: tuple = field(default=None)   # (min, max) aproximados
    resta: bool = False            # se sustrae de la superficie (boca, narinas)
    corte: tuple = None            # (n, d) en el mundo: sólo se conserva n·P <= d


def construir_piezas(eg: float, prop: Proporciones | None = None):
    prop = prop or Proporciones()
    bio = biometria(eg)
    dbp, cc, ca, lf = bio["DBP"], bio["CC"], bio["CA"], bio["LF"]

    # --- cabeza: elipse con semieje transverso DBP/2 y perímetro CC
    b_cab = dbp / 2
    a_cab = semieje_mayor_elipse(cc, b_cab)          # fronto-occipital
    c_cab = prop.altura_cabeza * a_cab

    # --- tronco: sección abdominal con perímetro CA
    # b_abd: semieje transverso (mayor); a_abd: semieje antero-posterior
    b_abd, a_abd = semiejes_por_perimetro(ca, prop.razon_ap_abdomen)
    L = prop.largo_tronco * (a_abd + b_abd)           # cuello→nalgas

    # Columna en arco (cóncavo hacia delante), en el plano x-z
    th = math.radians(prop.curvatura_tronco_grados)
    Rc = L / th
    C = np.array([Rc, 0.0, 0.0])

    def columna(s):            # s ∈ [0,1]: 0 = nalgas, 1 = cuello
        phi = -th / 2 + s * th
        p = C + Rc * np.array([-math.cos(phi), 0.0, math.sin(phi)])
        t = np.array([math.sin(phi), 0.0, math.cos(phi)])     # hacia arriba
        n = np.array([math.cos(phi), 0.0, -math.sin(phi)])    # anterior
        return p, t, n

    grosor = 1.0 + prop.engrosamiento_tardio * (eg - EG_MIN) / (EG_MAX - EG_MIN)
    piezas: list[Pieza] = []

    # Tórax, abdomen, pelvis
    for nombre, s, fx, fz in [("pelvis", 0.17, 0.85, 0.30),
                              ("abdomen", 0.45, 1.00, 0.34),
                              ("torax", 0.75, 0.95, 0.32)]:
        p, t, n = columna(s)
        piezas.append(Pieza(nombre, "elipsoide",
                            dict(centro=p, semiejes=(a_abd * fx, b_abd * fx, L * fz),
                                 R=_marco(n, t)), k=0.25 * b_abd))

    # Cuello y cabeza
    p_cue, t_cue, n_cue = columna(1.0)
    fl = math.radians(prop.flexion_cabeza_grados)
    u = _unit(math.cos(fl) * t_cue + math.sin(fl) * n_cue)      # eje vertical cabeza
    f = _unit(math.cos(fl) * n_cue - math.sin(fl) * t_cue)      # eje anterior cabeza
    largo_cuello = prop.largo_cuello * dbp
    p_cab = p_cue + (largo_cuello + 0.75 * c_cab) * u - 0.10 * a_cab * f
    piezas.append(Pieza("cuello", "cono",
                        dict(a=p_cue - 0.1 * L * t_cue, b=p_cab - 0.5 * c_cab * u,
                             ra=0.55 * b_abd, rb=0.42 * b_cab), k=0.15 * b_cab))
    # La CC y el DBP de Hadlock se miden en el borde externo del cráneo;
    # el cuero cabelludo agrega `piel` mm por fuera (igual que feto3d).
    piel = 1.2 + 0.02 * dbp
    Rh = _marco(f, u)
    n_c, d_c, k_c = cabeza.corte_cara(a_cab, c_cab)
    n_w = Rh @ n_c
    piezas.append(Pieza("craneo", "elipsoide",
                        dict(centro=p_cab, semiejes=(a_cab + piel, b_cab + piel, c_cab + piel),
                             R=Rh), k=0.2 * b_cab, corte=(n_w, d_c + float(n_w @ p_cab), k_c)))
    # cara (compartida con feto3d)
    geo_cab = cabeza.geometria(a_cab, b_cab, c_cab, eg)

    def H(x, y, z):
        return p_cab + Rh @ np.array([x * a_cab, y * b_cab, z * c_cab], np.float32)

    def desde_cabeza(e, resta=False):
        if e["tipo"] == "cono":
            return Pieza(e["nombre"], "cono", dict(a=H(*e["a"]), b=H(*e["b"]), ra=e["ra"],
                                                     rb=e["rb"]), k=e["k"], resta=resta)
        return Pieza(e["nombre"], "elipsoide", dict(centro=H(*e["centro"]),
                                                    semiejes=e["semiejes"], R=Rh),
                     k=e["k"], resta=resta)

    piezas += [desde_cabeza(e) for e in geo_cab["piel"]]
    for lado in (+1, -1):
        y = np.array([0.0, lado, 0.0])
        piezas.append(Pieza(f"oreja_{'izq' if lado > 0 else 'der'}", "elipsoide",
                            dict(centro=p_cab + 0.97 * b_cab * y - 0.08 * a_cab * f - 0.1 * c_cab * u,
                                 semiejes=(0.20 * a_cab, 0.06 * b_cab, 0.28 * c_cab),
                                 R=_marco(f, u)), k=0.05 * b_cab))

    # Extremidades
    tib, hum, cub = prop.tibia * lf, prop.humero * lf, prop.cubito * lf
    lpie_eg = largo_pie(eg, lf)
    r_mus = prop.radio_muslo * lf * grosor
    r_bra = prop.radio_brazo * lf * grosor
    p_pel, t_pel, n_pel = columna(0.17)
    p_tor, t_tor, n_tor = columna(0.82)
    abajo = -t_pel
    beta = math.radians(prop.flexion_cadera_grados)
    gamma = math.radians(prop.flexion_rodilla_grados)

    femures = []
    for lado in (+1, -1):
        y = np.array([0.0, lado, 0.0])
        suf = "izq" if lado > 0 else "der"
        # Pierna: cadera → rodilla → tobillo → pie
        cadera = p_pel + 0.70 * b_abd * 0.85 * y - 0.15 * L * t_pel
        d_mus = _unit(math.cos(beta) * abajo + math.sin(beta) * n_pel + prop.abduccion_muslo * y)
        rodilla = cadera + 1.08 * lf * d_mus      # 0.04 LF de cartílago en cada extremo
        femures.append((cadera + 0.04 * lf * d_mus, cadera + 1.04 * lf * d_mus))  # diáfisis = LF
        # la tibia regresa: girar d_mus en el plano sagital por la flexión de rodilla
        d_tib = _unit(math.cos(beta - gamma) * abajo + math.sin(beta - gamma) * n_pel
                      - 0.15 * y)
        tobillo = rodilla + tib * d_tib
        d_pie = _unit(0.75 * n_pel - 0.35 * abajo - 0.35 * y)
        lpie = prop.pie * lpie_eg
        piezas += [
            Pieza(f"muslo_{suf}", "cono", dict(a=cadera, b=rodilla, ra=r_mus, rb=0.62 * r_mus),
                  k=0.35 * r_mus),
            Pieza(f"pierna_{suf}", "cono", dict(a=rodilla, b=tobillo, ra=0.62 * r_mus,
                                                 rb=0.36 * r_mus), k=0.2 * r_mus),
            # el largo total, casquetes incluidos, es lpie (talón a punta)
            Pieza(f"pie_{suf}", "cono", dict(
                a=tobillo + (0.36 * r_mus - 0.20 * lpie) * d_pie,
                b=tobillo + (0.80 * lpie - 0.30 * r_mus) * d_pie,
                ra=0.36 * r_mus, rb=0.30 * r_mus), k=0.15 * r_mus),
        ]
        # Brazo: hombro → codo → muñeca → mano (cruzado frente al tórax)
        hombro = p_tor + 0.95 * b_abd * y + 0.05 * L * t_tor
        alfa, psi = math.radians(30.0), math.radians(70.0)    # hombro y codo (como feto3d.Postura)
        d_hum = _unit(-math.cos(alfa) * t_tor + math.sin(alfa) * n_tor + 0.05 * y)
        codo = hombro + hum * d_hum
        e_cod = _unit(t_tor - (t_tor @ d_hum) * d_hum)
        d_cub = _unit(math.cos(psi) * d_hum + math.sin(psi) * e_cod - 0.55 * y)
        muneca = codo + cub * d_cub
        largo_mano = prop.mano * lf
        piezas += [
            Pieza(f"brazo_{suf}", "cono", dict(a=hombro, b=codo, ra=r_bra, rb=0.68 * r_bra),
                  k=0.35 * r_bra),
            Pieza(f"antebrazo_{suf}", "cono", dict(a=codo, b=muneca, ra=0.68 * r_bra,
                                                    rb=0.50 * r_bra), k=0.2 * r_bra),
            Pieza(f"mano_{suf}", "elipsoide",
                  dict(centro=muneca + 0.45 * largo_mano * d_cub,
                       semiejes=(0.22 * largo_mano, 0.38 * largo_mano, 0.50 * largo_mano),
                       R=_marco(n_tor, d_cub)), k=0.12 * r_bra),
        ]

    piezas += [desde_cabeza(e, resta=True) for e in geo_cab["restas"]]
    extra = dict(bio, OFD=2 * a_cab, L_tronco=L, crown_dir=u, p_cabeza=p_cab, piel_cabeza=piel,
                 c_cabeza=c_cab, nalgas=columna(0.0)[0] - 0.30 * L * t_pel,
                 femures=femures)
    return piezas, extra


def _caja(piezas):
    pts = []
    for p in piezas:
        if p.tipo == "elipsoide":
            r = max(p.params["semiejes"])
            c = p.params["centro"]
            pts += [c - r, c + r]
        else:
            r = max(p.params["ra"], p.params["rb"])
            for q in (p.params["a"], p.params["b"]):
                pts += [q - r, q + r]
    pts = np.array(pts)
    return pts.min(0), pts.max(0)


def evaluar_sdf(P, piezas):
    d = None
    for p in piezas:
        if p.tipo == "elipsoide":
            di = sdf_elipsoide(P, **p.params)
        else:
            di = sdf_cono_redondeado(P, **p.params)
        if p.corte is not None:
            di = recortar(di, P, p.corte)
        if p.resta:
            d = resta_suave(d, di, p.k)
        else:
            d = di if d is None else union_suave(d, di, p.k)
    return d


# ---------------------------------------------------------------------------
# Malla
# ---------------------------------------------------------------------------

def componente_mayor(malla: trimesh.Trimesh) -> trimesh.Trimesh:
    """Se queda con la pieza conexa más grande. Marching cubes a resolución
    fina puede dejar triángulos sueltos (p. ej. junto a las orejas) que rompen
    la hermeticidad y contaminan los cortes de medición."""
    piezas = malla.split(only_watertight=False)
    if len(piezas) <= 1:
        return malla
    return max(piezas, key=lambda p: len(p.faces))


def malla_fetal(eg: float, resolucion: int = 180, prop: Proporciones | None = None,
                suavizado: int = 10, devolver_info: bool = False):
    """Malla triangulada (trimesh.Trimesh, mm) del feto a `eg` semanas.

    resolucion: número de vóxeles a lo largo del eje más largo de la caja.
    """
    piezas, info = construir_piezas(eg, prop)
    lo, hi = _caja(piezas)
    margen = 0.05 * (hi - lo).max()
    lo, hi = lo - margen, hi + margen
    h = (hi - lo).max() / resolucion
    ejes = [np.arange(lo[i], hi[i] + h, h, dtype=np.float32) for i in range(3)]
    X, Y, Z = np.meshgrid(*ejes, indexing="ij")
    P = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    D = evaluar_sdf(P, piezas).reshape(X.shape)

    verts, caras, _, _ = marching_cubes(D, level=0.0, spacing=(h, h, h))
    verts += lo
    malla = componente_mayor(trimesh.Trimesh(verts, caras, process=True))
    if suavizado:
        trimesh.smoothing.filter_taubin(malla, iterations=suavizado)
    malla.fix_normals()
    # Origen en el centroide, para que los visores lo encuadren bien
    desplaz = -malla.centroid
    malla.apply_translation(desplaz)
    for k in ("p_cabeza", "nalgas"):
        info[k] = info[k] + desplaz
    info["femures"] = [(a + desplaz, b + desplaz) for a, b in info["femures"]]
    info["desplazamiento"] = desplaz        # cuerpo (feto3d) -> malla centrada
    info["voxel_mm"] = h
    return (malla, info) if devolver_info else malla


# ---------------------------------------------------------------------------
# Verificación: medir la malla y comparar con la biometría de entrada
# ---------------------------------------------------------------------------

def medir(malla: trimesh.Trimesh, info: dict) -> dict:
    """Mide CC y DBP en un corte axial de la cabeza, LCC aproximada y volumen."""
    u = info["crown_dir"]
    centro = info["p_cabeza"] + 0.15 * info["c_cabeza"] * u   # por arriba de la cara
    corte = malla.section(plane_origin=centro, plane_normal=u)
    cc = dbp = float("nan")
    lazo = extremos = None
    if corte is not None:
        # el contorno cuyo centroide queda más cerca del centro de la cabeza
        lazos = [np.asarray(l) for l in corte.discrete]
        lazo = min(lazos, key=lambda l: np.linalg.norm(l.mean(0) - centro))
        cc = float(np.linalg.norm(np.diff(lazo, axis=0), axis=1).sum())
        # DBP: anchura en la dirección lateral (eje y) dentro del contorno
        dbp = float(lazo[:, 1].max() - lazo[:, 1].min())
        extremos = (lazo[lazo[:, 1].argmin()], lazo[lazo[:, 1].argmax()])
    piel = info.get("piel_cabeza", 0.0)
    corona = info["p_cabeza"] + (info["c_cabeza"] + piel) * u
    lcc = float(np.linalg.norm(corona - info["nalgas"]))
    # CC y DBP se comparan con Hadlock en el borde externo del cráneo:
    # se descuenta el cuero cabelludo (curva paralela: perímetro - 2·pi·piel)
    return {"CC_malla": cc - 2 * math.pi * piel, "DBP_malla": dbp - 2 * piel,
            "CC_piel": cc, "DBP_piel": dbp, "LCC_aprox": lcc,
            "volumen_cm3": malla.volume / 1000.0, "caras": len(malla.faces),
            "hermetica": bool(malla.is_watertight),
            "contorno_cc": lazo, "extremos_dbp": extremos,
            "plano_cc": (centro, u), "corona": corona}


def informe(eg: float, resolucion: int = 180) -> str:
    malla, info = malla_fetal(eg, resolucion, devolver_info=True)
    m = medir(malla, info)
    ext = malla.extents
    return (f"EG {eg:4.1f} sem | DBP {info['DBP']:5.1f} → {m['DBP_malla']:5.1f} mm | "
            f"CC {info['CC']:6.1f} → {m['CC_malla']:6.1f} mm | CA {info['CA']:6.1f} | "
            f"LF {info['LF']:5.1f} | LCC≈{m['LCC_aprox']:6.1f} mm | "
            f"caja {ext[0]:.0f}×{ext[1]:.0f}×{ext[2]:.0f} mm | "
            f"vol {m['volumen_cm3']:7.1f} cm³ (PFE Hadlock {info['PFE_g']:6.0f} g) | {m['caras']} caras | "
            f"hermética={m['hermetica']}")


# ---------------------------------------------------------------------------
# Línea de comandos
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Malla paramétrica de un feto humano "
                                             "según la edad gestacional.")
    ap.add_argument("eg", type=float, nargs="+", help="edad gestacional en semanas (12-40)")
    ap.add_argument("-o", "--salida", help="archivo de salida (.stl, .obj, .ply); "
                    "solo con una EG. Por omisión feto_<EG>s.stl")
    ap.add_argument("-r", "--resolucion", type=int, default=180,
                    help="vóxeles en el eje más largo (def. 180)")
    ap.add_argument("--informe", action="store_true",
                    help="imprimir biometría de entrada y medidas de la malla")
    args = ap.parse_args(argv)

    if args.salida and len(args.eg) > 1:
        ap.error("--salida solo admite una edad gestacional")
    for eg in args.eg:
        malla, info = malla_fetal(eg, args.resolucion, devolver_info=True)
        nombre = args.salida or f"feto_{eg:g}s.stl"
        malla.export(nombre)
        print(f"{nombre}: {len(malla.faces)} triángulos")
        if args.informe:
            m = medir(malla, info)
            print(f"  DBP {info['DBP']:.1f} mm (malla {m['DBP_malla']:.1f}), "
                  f"CC {info['CC']:.1f} mm (malla {m['CC_malla']:.1f}), "
                  f"CA {info['CA']:.1f} mm, LF {info['LF']:.1f} mm, "
                  f"LCC≈{m['LCC_aprox']:.1f} mm, volumen {m['volumen_cm3']:.1f} cm³, "
                  f"hermética={m['hermetica']}")


if __name__ == "__main__":
    main()
