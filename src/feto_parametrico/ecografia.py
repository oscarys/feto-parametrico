# -*- coding: utf-8 -*-
"""
ecografia.py — Simulador de ecografía modo B (rayos + convolución) sobre la
escena 3D de feto3d, con una sonda convexa apoyada en el abdomen materno.

El núcleo es el simulador 2D anterior (fetal_us_sim/simulator.py); los cambios:
* la escena se muestrea en el plano de la sonda dentro del volumen 3D;
* el moteado se ancla a coordenadas locales 3D de cada pieza (se mueve con el feto);
* grosor de corte opcional (suma coherente de varios planos en elevación);
* `plano_estandar` coloca la sonda para los cortes de biometría y anatomía.

Tubería (en coordenadas polares del haz, un rayo por línea):
  escena.evaluar -> etiquetas, pieza, coordenadas locales
  tablas         -> impedancia Z, atenuación, amplitud de dispersión
  moteado        -> dispersores complejos anclados al tejido
  especular      -> d(ln Z)/dr ponderado por cos^p(haz, normal de la interfaz)
  transmisión    -> atenuación de ida y vuelta + pérdidas en interfaces
                    (hueso: sombra acústica; líquido: refuerzo posterior)
  PSF            -> gaussiana axial + lateral dependiente de la profundidad
  receptor       -> ruido, TGC, envolvente, compresión logarítmica
  conversión     -> imagen sectorial cartesiana + mapa de etiquetas

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d, map_coordinates

from .feto3d import Escena, _unit
from .tejidos import T, tablas_propiedades


@dataclass
class Sonda:
    f0_mhz: float = 3.5
    radio_mm: float = 50.0
    apertura_grados: float = 70.0
    profundidad_mm: float = 170.0
    n_lineas: int = 256
    dr_mm: float = 0.1
    foco_mm: float = 80.0
    sigma_axial_mm: float = 0.25        # a 3.5 MHz; escala como 1/f0
    sigma_lat_foco_mm: float = 0.75
    crecimiento_lat: float = 0.022      # mm de sigma por mm fuera del foco


@dataclass
class Adquisicion:
    ganancia_db: float = 0.0
    rango_dinamico_db: float = 55.0
    ruido_db: float = -62.0
    tgc_auto: bool = True               # compensa la atenuación real (mediana entre líneas)
    tgc_alfa: float = 0.5               # dB/cm/MHz supuesta por la TGC
    ganancia_especular: float = 25.0
    potencia_especular: float = 4.0
    celda_moteado_mm: float = 0.1
    px_salida_mm: float = 0.3
    elevacion: tuple = (0.0,)           # desplazamientos (mm) en elevación; p.ej. (-1, 0, 1)
    sigma_elevacion_mm: float = 1.0


@dataclass
class Pose:
    """Sonda en el mundo: origen en la piel, ex lateral de la imagen, ez hacia adentro."""
    origen: np.ndarray
    ex: np.ndarray
    ez: np.ndarray
    info: dict = field(default_factory=dict)

    @property
    def ey(self):
        return np.cross(self.ez, self.ex)

    def a_mundo(self, X, Z, elev=0.0):
        return (self.origen + X[..., None] * self.ex + Z[..., None] * self.ez
                + elev * self.ey)


# ---------------------------------------------------------------------------
# Moteado anclado al tejido (hash de coordenadas locales 3D)
# ---------------------------------------------------------------------------
_M1, _M2, _M3 = (np.uint64(0xBF58476D1CE4E5B9), np.uint64(0x94D049BB133111EB),
                 np.uint64(0x9E3779B97F4A7C15))


def _splitmix(x):
    x = x + _M3
    x = (x ^ (x >> np.uint64(30))) * _M1
    x = (x ^ (x >> np.uint64(27))) * _M2
    return x ^ (x >> np.uint64(31))


def moteado_anclado(L, pieza, celda, semilla=0):
    i = [np.floor(L[..., k] / celda).astype(np.int64).view(np.uint64) for k in range(3)]
    with np.errstate(over="ignore"):
        h = _splitmix(_splitmix(_splitmix(_splitmix(i[0]) ^ i[1]) ^ i[2])
                      ^ (pieza.astype(np.uint64) + np.uint64(semilla * 7919)))
        h2 = _splitmix(h)
    u1 = ((h >> np.uint64(11)).astype(np.float64) + 0.5) * 2.0 ** -53
    u2 = (h2 >> np.uint64(11)).astype(np.float64) * 2.0 ** -53
    return np.sqrt(-np.log(u1)) * np.exp(2j * np.pi * u2)


# ---------------------------------------------------------------------------
# Geometría del sector
# ---------------------------------------------------------------------------

def malla_polar(s: Sonda):
    th = np.deg2rad(np.linspace(-s.apertura_grados / 2, s.apertura_grados / 2, s.n_lineas))
    r = s.radio_mm + np.arange(0.0, s.profundidad_mm, s.dr_mm)
    TH, R = np.meshgrid(th, r, indexing="ij")
    return th, r, R * np.sin(TH), R * np.cos(TH) - s.radio_mm


def malla_cartesiana(s: Sonda, px):
    half = (s.radio_mm + s.profundidad_mm) * np.sin(np.deg2rad(s.apertura_grados / 2))
    xs = np.arange(-half, half, px)
    zs = np.arange(0.0, s.profundidad_mm, px)
    Xc, Zc = np.meshgrid(xs, zs)
    return xs, zs, Xc, Zc


def conversion(polar, s: Sonda, th, r, Xc, Zc, orden=1, relleno=0.0):
    Rc = np.hypot(Xc, Zc + s.radio_mm)
    Tc = np.arctan2(Xc, Zc + s.radio_mm)
    it = (Tc - th[0]) / (th[1] - th[0])
    ir = (Rc - r[0]) / (r[1] - r[0])
    dentro = (it >= 0) & (it <= len(th) - 1) & (ir >= 0) & (ir <= len(r) - 1)
    out = map_coordinates(polar, [it, ir], order=orden, mode="nearest")
    return np.where(dentro, out, relleno), dentro


def _evaluar_plano(esc, pose, X, Z, elev=0.0):
    P = pose.a_mundo(X, Z, elev).reshape(-1, 3)
    etq, pieza, loc = esc.evaluar(P)
    sh = X.shape
    return etq.reshape(sh), pieza.reshape(sh), loc.reshape(sh + (3,))


# ---------------------------------------------------------------------------
# Simulación
# ---------------------------------------------------------------------------

def simular(esc: Escena, pose: Pose, sonda: Sonda = Sonda(), adq: Adquisicion = Adquisicion(),
            semilla: int = 0, etapas: bool = False, etiquetas: bool = True):
    th, r, X, Z = malla_polar(sonda)
    dth, dr, f0 = th[1] - th[0], sonda.dr_mm, sonda.f0_mhz

    etq, pieza, loc = _evaluar_plano(esc, pose, X, Z)
    Zlut, alut, slut = tablas_propiedades(esc.osificacion)
    Zmap, amap = Zlut[etq], alut[etq]

    # dispersión difusa; con grosor de corte, suma coherente en elevación
    pesos = np.exp(-0.5 * (np.asarray(adq.elevacion) / adq.sigma_elevacion_mm) ** 2)
    pesos = pesos / np.sqrt(np.sum(pesos ** 2))
    disp = np.zeros(X.shape, complex)
    for w, e in zip(pesos, adq.elevacion):
        if e == 0.0:
            et_e, pz_e, lc_e = etq, pieza, loc
        else:
            et_e, pz_e, lc_e = _evaluar_plano(esc, pose, X, Z, e)
        disp += w * slut[et_e] * moteado_anclado(lc_e, pz_e, adq.celda_moteado_mm, semilla)

    # reflexión especular con dependencia angular
    lnZ = gaussian_filter(np.log(Zmap), sigma=(0.7, 0.15 / dr))
    g_r = np.gradient(lnZ, dr, axis=1)
    g_t = np.gradient(lnZ, dth, axis=0) / r[None, :]
    cosang = np.abs(g_r) / (np.hypot(g_r, g_t) + 1e-9)
    espec = adq.ganancia_especular * 0.5 * g_r * dr * cosang ** adq.potencia_especular

    # transmisión: atenuación de ida y vuelta + pérdidas por interfaz
    a_np = amap * f0 / 8.686 / 10.0
    dlnz = np.diff(np.log(Zmap), axis=1, prepend=np.log(Zmap[:, :1]))
    perdida = 2.0 * a_np * dr - np.log(np.clip(1.0 - (0.5 * dlnz) ** 2, 1e-6, 1.0))
    acum = np.cumsum(perdida, axis=1) - perdida
    acum = gaussian_filter1d(acum, 1.5, axis=0)
    Tr = np.exp(-acum)
    eco = (disp + espec) * Tr

    # PSF
    s_ax = sonda.sigma_axial_mm * 3.5 / f0 / dr
    rf = gaussian_filter1d(eco.real, s_ax, axis=1) + 1j * gaussian_filter1d(eco.imag, s_ax, axis=1)
    prof = r - sonda.radio_mm
    bordes = np.linspace(0, len(r), 33).astype(int)
    out = np.empty_like(rf)
    for i0, i1 in zip(bordes[:-1], bordes[1:]):
        dm = prof[(i0 + i1) // 2]
        sig = (sonda.sigma_lat_foco_mm + sonda.crecimiento_lat * abs(dm - sonda.foco_mm)) * 3.5 / f0
        sl = sig / (r[(i0 + i1) // 2] * dth)
        b = rf[:, i0:i1]
        out[:, i0:i1] = gaussian_filter1d(b.real, sl, axis=0) + 1j * gaussian_filter1d(b.imag, sl, axis=0)
    rf = out

    # receptor
    rng = np.random.default_rng(semilla + 1)
    ref0 = np.percentile(np.abs(rf), 99.0)
    rf = rf + ref0 * 10 ** (adq.ruido_db / 20) * (rng.standard_normal(rf.shape)
                                                 + 1j * rng.standard_normal(rf.shape)) / np.sqrt(2)
    if adq.tgc_auto:
        # perfil de pérdida típico a cada profundidad (la mediana ignora sombras aisladas);
        # en el líquido amniótico no crece, así que no amplifica el ruido
        tgc = np.exp(np.median(acum, axis=0))[None, :]
    else:
        tgc = np.exp(2.0 * adq.tgc_alfa * f0 / 8.686 / 10.0 * prof)[None, :]
    env = np.abs(rf) * tgc
    ref = np.percentile(env, 99.5)
    db = 20 * np.log10(env / ref + 1e-12) + adq.ganancia_db
    bmodo_polar = np.clip((db + adq.rango_dinamico_db) / adq.rango_dinamico_db, 0.0, 1.0)

    xs, zs, Xc, Zc = malla_cartesiana(sonda, adq.px_salida_mm)
    bmodo, dentro = conversion(bmodo_polar, sonda, th, r, Xc, Zc)
    res = dict(bmodo=bmodo.astype(np.float32), dentro=dentro, xs=xs, zs=zs,
               bmodo_polar=bmodo_polar.astype(np.float32), th=th, r=r,
               extent=(xs[0], xs[-1] + adq.px_salida_mm, zs[-1] + adq.px_salida_mm, zs[0]))
    if etiquetas == "rapidas":          # vecino más cercano desde la malla polar
        lab, _ = conversion(etq.astype(float), sonda, th, r, Xc, Zc, orden=0, relleno=-1)
        res["etiquetas"] = np.where(dentro, lab, -1).astype(np.int16)
    elif etiquetas:
        lab, _, _ = _evaluar_plano(esc, pose, Xc, Zc)
        res["etiquetas"] = np.where(dentro, lab, -1).astype(np.int16)
    if etapas:
        conv = lambda p: conversion(p, sonda, th, r, Xc, Zc)[0]
        res["etapa_Z"] = conv(Zmap)
        res["etapa_T_db"] = conv(20 * np.log10(Tr + 1e-6))
        res["etapa_disp_db"] = conv(20 * np.log10(np.abs(gaussian_filter1d(np.abs(disp), 1.0, axis=1)) + 1e-3))
        res["etapa_espec"] = conv(np.abs(espec))
    return res


# ---------------------------------------------------------------------------
# Colocación de la sonda
# ---------------------------------------------------------------------------

def _piel_a_lo_largo(esc: Escena, c, d):
    """Distancia s>0 tal que c - s d está en la piel materna (bisección)."""
    lo, hi = 0.0, 1500.0
    if esc.sdf_abdomen((c - hi * d)[None])[0] <= 0:
        raise ValueError("el rayo no sale del abdomen")
    for _ in range(60):
        m = 0.5 * (lo + hi)
        if esc.sdf_abdomen((c - m * d)[None])[0] < 0:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def pose_hacia(esc: Escena, centro, normal, giro_en_plano=0.0):
    """Sonda que ve el plano (centro, normal) desde la piel anterior materna.

    El haz central queda en el plano, apuntando lo más posible hacia atrás
    (de la piel anterior hacia la columna materna). `giro_en_plano` inclina el
    haz dentro del plano (grados).
    """
    n = _unit(normal)
    atras = np.array([0.0, 0.0, -1.0])
    d = atras - (atras @ n) * n
    if np.linalg.norm(d) < 0.25:                     # plano casi coronal materno
        d = np.array([0.0, -1.0, 0.0]) - (np.array([0.0, -1.0, 0.0]) @ n) * n
    d = _unit(d)
    if giro_en_plano:
        a = math.radians(giro_en_plano)
        d = _unit(math.cos(a) * d + math.sin(a) * np.cross(n, d))
    s = _piel_a_lo_largo(esc, np.asarray(centro, float), d)
    ex = _unit(np.cross(n, d))
    return Pose(np.asarray(centro) - s * d, ex, d,
                {"profundidad_objetivo": s, "centro": np.asarray(centro, float), "normal": n})


PLANOS = ("transtalamico", "cuatro_camaras", "abdominal", "femur", "sagital")


def plano_estandar(esc: Escena, nombre: str, **kw) -> Pose:
    f, Rg = esc.feto, esc.Rg
    if nombre == "transtalamico":
        c, R = f.marcos["talamos"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 2], **kw)
    elif nombre == "cuatro_camaras":
        c, R = f.marcos["corazon"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 2], **kw)
    elif nombre == "abdominal":
        c, R = f.marcos["abdomen"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 2], **kw)
    elif nombre == "femur":
        # el fémur más cercano a la pared anterior materna
        fem = max(f.marcos["femures"], key=lambda ab: esc.a_mundo(0.5 * (ab[0] + ab[1]))[2])
        a, b = esc.a_mundo(fem[0]), esc.a_mundo(fem[1])
        eje = _unit(b - a)
        n = _unit(np.cross(eje, [0.0, 0.0, 1.0]))
        pose = pose_hacia(esc, 0.5 * (a + b), n, **kw)
        pose.info["femur"] = (a, b)
    elif nombre == "sagital":
        c, R = f.marcos["columna"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 1], **kw)
    else:
        raise ValueError(f"plano desconocido: {nombre}; opciones: {PLANOS}")
    pose.info["plano"] = nombre
    return pose


def sonda_para(pose: Pose, margen_mm: float = 65.0, **kw) -> Sonda:
    """Sonda con la profundidad ajustada a la del objetivo."""
    prof = pose.info.get("profundidad_objetivo", 100.0) + margen_mm
    return Sonda(profundidad_mm=float(np.clip(prof, 90.0, 240.0)),
                 foco_mm=float(pose.info.get("profundidad_objetivo", 80.0)), **kw)


# ---------------------------------------------------------------------------
# Medidas sobre el mapa de etiquetas (máscaras de referencia)
# ---------------------------------------------------------------------------

def _perimetro_elipse(a, b):
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def medir_en_imagen(res, plano, px, pose: Pose | None = None):
    """CC/DBP, CA o LF medidos sobre las etiquetas de la imagen simulada (mm)."""
    from scipy.ndimage import binary_fill_holes, label as etiquetar
    from skimage.measure import regionprops
    lab = res["etiquetas"]
    out = {}
    if plano == "transtalamico":
        cab = np.isin(lab, [T[k] for k in ("hueso", "cerebro", "lcr", "coroides", "talamo",
                                           "hoz", "cerebelo")])
        comp, _ = etiquetar(cab)
        sem = comp[lab == T["talamo"]]
        if sem.size:
            m = binary_fill_holes(comp == np.bincount(sem[sem > 0]).argmax())
            rp = regionprops(m.astype(int))[0]
            A, B = rp.axis_major_length * px / 2, rp.axis_minor_length * px / 2
            out = {"CC": _perimetro_elipse(A, B), "DBP_ext": 2 * B, "DFO": 2 * A}
    elif plano == "abdominal":
        cuerpo = (lab >= T["fetal"]) & (lab != T["amniotico"]) & (lab != T["cordon"])
        comp, _ = etiquetar(binary_fill_holes(cuerpo))
        sem = comp[lab == T["liquido"]]          # el estómago está en el abdomen
        if sem.size and (sem > 0).any():
            m = comp == np.bincount(sem[sem > 0]).argmax()
            rp = regionprops(m.astype(int))[0]
            A, B = rp.axis_major_length * px / 2, rp.axis_minor_length * px / 2
            out = {"CA": _perimetro_elipse(A, B)}
    elif plano == "femur" and pose is not None and "femur" in pose.info:
        comp, n = etiquetar(lab == T["hueso"])
        a, b = pose.info["femur"]
        cm = 0.5 * (a + b) - pose.origen
        col = int(round((cm @ pose.ex - res["xs"][0]) / px))
        fil = int(round((cm @ pose.ez - res["zs"][0]) / px))
        k = comp[fil, col] if (0 <= fil < lab.shape[0] and 0 <= col < lab.shape[1]) else 0
        if k:
            # longitud = extensión de la diáfisis a lo largo de su eje principal
            yy, xx = np.nonzero(comp == k)
            q = np.column_stack([xx, yy]) * px
            q = q - q.mean(0)
            v = np.linalg.svd(q, full_matrices=False)[2][0]
            proy = q @ v
            out = {"LF": proy.max() - proy.min() + px}
    return out
