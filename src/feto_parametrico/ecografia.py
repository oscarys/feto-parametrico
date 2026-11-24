# -*- coding: utf-8 -*-
"""
ecografia.py — Simulador de ecografía modo B (rayos + convolución) sobre la
escena 3D de feto3d, con una sonda apoyada en el abdomen materno: convexa,
lineal o sectorial (phased array).

El núcleo es el simulador 2D anterior (fetal_us_sim/simulator.py); los cambios:
* la escena se muestrea en el plano de la sonda dentro del volumen 3D;
* el moteado se ancla a coordenadas locales 3D de cada pieza (se mueve con el feto);
* grosor de corte opcional (suma coherente de varios planos en elevación);
* `plano_estandar` coloca la sonda para los cortes de biometría y anatomía.

Tubería (en coordenadas del haz: línea u y profundidad d a lo largo de ella):
  escena.evaluar -> etiquetas, pieza, coordenadas locales
  tablas         -> impedancia Z, atenuación, amplitud de dispersión
  moteado        -> dispersores complejos anclados al tejido
  especular      -> d(ln Z)/dr ponderado por cos^p(haz, normal de la interfaz)
  transmisión    -> atenuación de ida y vuelta + pérdidas en interfaces
                    (hueso: sombra acústica; líquido: refuerzo posterior)
  PSF            -> gaussiana axial + lateral dependiente de la profundidad
  receptor       -> ruido, TGC, envolvente, compresión logarítmica
  conversión     -> imagen cartesiana (sector, trapecio o rectángulo) + etiquetas

Geometrías de la sonda (`Sonda.geometria`):
  convexa   líneas en abanico desde un arco de radio `radio_mm`; u = ángulo
  sectorial igual, con huella casi puntual (`radio_mm` pequeño) y abanico amplio
  lineal    líneas paralelas repartidas en `ancho_mm`; u = posición lateral

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d, map_coordinates

from .feto3d import Escena, _unit
from .tejidos import T, tablas_propiedades


GEOMETRIAS = ("convexa", "lineal", "sectorial")


@dataclass
class Sonda:
    f0_mhz: float = 3.5
    geometria: str = "convexa"          # "convexa", "lineal" o "sectorial"
    radio_mm: float = 50.0              # convexa / sectorial: radio del arco de la huella
    apertura_grados: float = 70.0       # convexa / sectorial: abanico
    ancho_mm: float = 40.0              # lineal: ancho de la imagen
    profundidad_mm: float = 170.0
    n_lineas: int = 256
    dr_mm: float = 0.1
    foco_mm: float = 80.0
    sigma_axial_mm: float = 0.25        # a 3.5 MHz; escala como 1/f0
    sigma_lat_foco_mm: float = 0.75
    crecimiento_lat: float = 0.022      # mm de sigma por mm fuera del foco
    tgc_max_db: float | None = None     # tope de la TGC automática (None: sin tope); con
                                        # frecuencias altas evita que el ruido amplificado
                                        # llene lo que está fuera del alcance de la sonda

    @property
    def es_lineal(self) -> bool:
        if self.geometria not in GEOMETRIAS:
            raise ValueError(f"geometría desconocida: {self.geometria}; opciones: {GEOMETRIAS}")
        return self.geometria == "lineal"

    @property
    def huella_mm(self) -> float:
        """Largo de la cara de la sonda que toca la piel."""
        if self.es_lineal:
            return self.ancho_mm
        return max(2 * self.radio_mm * math.sin(math.radians(self.apertura_grados / 2)), 15.0)


# Valores típicos de cada tipo de sonda; profundidad: (por omisión, mínima, máxima) en mm,
# frecuencia: (por omisión, mínima, máxima) en MHz.
TIPOS_SONDA = {
    "convexa": dict(sonda=dict(geometria="convexa", radio_mm=50.0, apertura_grados=70.0),
                    f0=(3.5, 2.0, 6.0), prof=(160, 80, 240)),
    "lineal": dict(sonda=dict(geometria="lineal", ancho_mm=40.0, tgc_max_db=50.0),
                   f0=(7.5, 5.0, 12.0), prof=(70, 30, 120)),
    "sectorial": dict(sonda=dict(geometria="sectorial", radio_mm=1.0, apertura_grados=90.0),
                      f0=(3.0, 2.0, 5.0), prof=(150, 60, 240)),
}


def sonda_tipo(geometria: str = "convexa", **kw) -> Sonda:
    """Sonda con los valores típicos de su tipo; `kw` sustituye cualquier campo."""
    t = TIPOS_SONDA[geometria]
    base = dict(t["sonda"], f0_mhz=t["f0"][0], profundidad_mm=float(t["prof"][0]),
                foco_mm=0.5 * t["prof"][0])
    base.update(kw)
    return Sonda(**base)


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
# Geometría del haz: coordenadas (u, d) de cada línea <-> plano de la imagen (X, Z)
# ---------------------------------------------------------------------------

def lineas(s: Sonda):
    """Coordenada u de cada línea (rad en convexa/sectorial, mm en lineal) y
    profundidades d (mm) de las muestras a lo largo de la línea, desde la piel."""
    if s.es_lineal:
        u = np.linspace(-s.ancho_mm / 2, s.ancho_mm / 2, s.n_lineas)
    else:
        u = np.deg2rad(np.linspace(-s.apertura_grados / 2, s.apertura_grados / 2, s.n_lineas))
    return u, np.arange(0.0, s.profundidad_mm, s.dr_mm)


def haz_a_plano(s: Sonda, U, D):
    """(u, d) -> (X lateral, Z hacia adentro) en mm, con la piel en Z = 0."""
    if s.es_lineal:
        return U + 0.0 * D, D + 0.0 * U
    R = s.radio_mm + D
    return R * np.sin(U), R * np.cos(U) - s.radio_mm


def plano_a_haz(s: Sonda, X, Z):
    """Inversa de `haz_a_plano`."""
    if s.es_lineal:
        return X, Z
    return np.arctan2(X, Z + s.radio_mm), np.hypot(X, Z + s.radio_mm) - s.radio_mm


def paso_lateral(s: Sonda, u, d):
    """Distancia (mm) entre líneas vecinas a cada profundidad."""
    du = u[1] - u[0]
    if s.es_lineal:
        return np.full_like(d, du)
    return np.maximum((s.radio_mm + d) * du, 1e-3)


def malla_haz(s: Sonda):
    u, d = lineas(s)
    U, D = np.meshgrid(u, d, indexing="ij")
    X, Z = haz_a_plano(s, U, D)
    return u, d, X, Z


def malla_cartesiana(s: Sonda, px):
    if s.es_lineal:
        half = s.ancho_mm / 2
    else:
        half = (s.radio_mm + s.profundidad_mm) * np.sin(np.deg2rad(s.apertura_grados / 2))
    xs = np.arange(-half, half, px)
    zs = np.arange(0.0, s.profundidad_mm, px)
    Xc, Zc = np.meshgrid(xs, zs)
    return xs, zs, Xc, Zc


def conversion(haz, s: Sonda, u, d, Xc, Zc, orden=1, relleno=0.0):
    """Remuestrea una imagen en coordenadas del haz (líneas x profundidad) al plano."""
    Uc, Dc = plano_a_haz(s, Xc, Zc)
    iu = (Uc - u[0]) / (u[1] - u[0])
    i_d = (Dc - d[0]) / (d[1] - d[0])
    dentro = (iu >= 0) & (iu <= len(u) - 1) & (i_d >= 0) & (i_d <= len(d) - 1)
    out = map_coordinates(haz, [iu, i_d], order=orden, mode="nearest")
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
    u, d, X, Z = malla_haz(sonda)
    du, dr, f0 = u[1] - u[0], sonda.dr_mm, sonda.f0_mhz
    lat = paso_lateral(sonda, u, d)             # mm entre líneas vecinas, por profundidad

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
    g_t = np.gradient(lnZ, du, axis=0) * du / lat[None, :]
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
    prof = d
    bordes = np.linspace(0, len(d), 33).astype(int)
    out = np.empty_like(rf)
    for i0, i1 in zip(bordes[:-1], bordes[1:]):
        im = (i0 + i1) // 2
        sig = (sonda.sigma_lat_foco_mm + sonda.crecimiento_lat * abs(d[im] - sonda.foco_mm)) * 3.5 / f0
        sl = min(sig / lat[im], float(len(u)))  # junto al vértice de la sectorial: todo un punto
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
        tgc_np = np.median(acum, axis=0)
    else:
        tgc_np = 2.0 * adq.tgc_alfa * f0 / 8.686 / 10.0 * prof
    if sonda.tgc_max_db is not None:
        tgc_np = np.minimum(tgc_np, sonda.tgc_max_db / 8.686)
    tgc = np.exp(tgc_np)[None, :]
    env = np.abs(rf) * tgc
    ref = np.percentile(env, 99.5)
    db = 20 * np.log10(env / ref + 1e-12) + adq.ganancia_db
    bmodo_haz = np.clip((db + adq.rango_dinamico_db) / adq.rango_dinamico_db, 0.0, 1.0)

    xs, zs, Xc, Zc = malla_cartesiana(sonda, adq.px_salida_mm)
    bmodo, dentro = conversion(bmodo_haz, sonda, u, d, Xc, Zc)
    res = dict(bmodo=bmodo.astype(np.float32), dentro=dentro, xs=xs, zs=zs,
               bmodo_haz=bmodo_haz.astype(np.float32), u=u, d=d,
               extent=(xs[0], xs[-1] + adq.px_salida_mm, zs[-1] + adq.px_salida_mm, zs[0]))
    if etiquetas == "rapidas":          # vecino más cercano desde la malla del haz
        lab, _ = conversion(etq.astype(float), sonda, u, d, Xc, Zc, orden=0, relleno=-1)
        res["etiquetas"] = np.where(dentro, lab, -1).astype(np.int16)
    elif etiquetas:
        lab, _, _ = _evaluar_plano(esc, pose, Xc, Zc)
        res["etiquetas"] = np.where(dentro, lab, -1).astype(np.int16)
    if etapas:
        conv = lambda p: conversion(p, sonda, u, d, Xc, Zc)[0]
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


PLANOS = ("transtalamico", "transcerebelar", "cuatro_camaras", "abdominal", "femur", "sagital",
          "perfil", "nariz_labios")
PLANOS_BIOMETRIA = PLANOS[:6]
PLANOS_CARA = ("perfil", "nariz_labios")


def plano_estandar(esc: Escena, nombre: str, **kw) -> Pose:
    f, Rg = esc.feto, esc.Rg
    if nombre == "transtalamico":
        c, R = f.marcos["talamos"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 2], **kw)
    elif nombre == "transcerebelar":
        # oblicuo: pasa por el CSP por delante y por el cerebelo por detrás
        c1, R = f.marcos["csp"]
        c2, _ = f.marcos["cerebelo"]
        n = np.cross(R[:, 1], c2 - c1)
        n = n if n @ R[:, 2] > 0 else -n
        pose = pose_hacia(esc, esc.a_mundo(0.5 * (c1 + c2)), Rg @ _unit(n), **kw)
    elif nombre == "perfil":
        c, R = f.marcos["perfil"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ R[:, 1], **kw)
        pose.info["hueso_nasal"] = tuple(esc.a_mundo(q) for q in f.marcos["hueso_nasal"])
    elif nombre == "nariz_labios":
        c, n = f.marcos["nariz_labios"]
        pose = pose_hacia(esc, esc.a_mundo(c), Rg @ n, **kw)
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


def sonda_para(pose: Pose, margen_mm: float = 65.0, geometria: str = "convexa", **kw) -> Sonda:
    """Sonda del tipo dado con la profundidad ajustada a la del objetivo (dentro del
    intervalo del tipo; una lineal no llega a objetivos profundos)."""
    objetivo = float(pose.info.get("profundidad_objetivo", 80.0))
    _, pmin, pmax = TIPOS_SONDA[geometria]["prof"]
    prof = float(np.clip(objetivo + margen_mm, max(pmin, 90.0 if geometria != "lineal" else pmin), pmax))
    kw.setdefault("profundidad_mm", prof)
    kw.setdefault("foco_mm", min(objetivo, prof))
    return sonda_tipo(geometria, **kw)


# ---------------------------------------------------------------------------
# Medidas sobre el mapa de etiquetas (máscaras de referencia)
# ---------------------------------------------------------------------------

def _perimetro_elipse(a, b):
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def medir_en_imagen(res, plano, px, pose: Pose | None = None):
    """Medidas sobre las etiquetas de la imagen simulada (mm): CC/DBP/DFO
    (transtalámico), DTC y CM (transcerebelar), CA, LF y HN (hueso nasal, perfil)."""
    from scipy.ndimage import binary_fill_holes, distance_transform_edt, label as etiquetar
    from skimage.measure import regionprops
    lab = res["etiquetas"]
    out = {}
    if plano == "transtalamico":
        cab = np.isin(lab, [T[k] for k in ("hueso", "cerebro", "lcr", "coroides", "talamo",
                                           "hoz", "cerebelo", "vermis")])
        comp, _ = etiquetar(cab)
        sem = comp[lab == T["talamo"]]
        if sem.size:
            m = binary_fill_holes(comp == np.bincount(sem[sem > 0]).argmax())
            rp = regionprops(m.astype(int))[0]
            A, B = rp.axis_major_length * px / 2, rp.axis_minor_length * px / 2
            out = {"CC": _perimetro_elipse(A, B), "DBP_ext": 2 * B, "DFO": 2 * A}
    elif plano == "transcerebelar":
        comp, _ = etiquetar(np.isin(lab, [T["cerebelo"], T["vermis"]]))
        if comp.max():
            k = np.bincount(comp[comp > 0]).argmax()
            yy, xx = np.nonzero(comp == k)
            q = np.column_stack([xx, yy]) * px
            centro = q.mean(0)
            v = np.linalg.svd(q - centro, full_matrices=False)[2]
            proy = (q - centro) @ v[0]
            out["DTC"] = proy.max() - proy.min() + px
            # cisterna magna: el LCR pegado al cerebelo, medido a lo ancho (perpendicular al DTC)
            lcr, n = etiquetar(lab == T["lcr"])
            if n:
                yy, xx = np.nonzero(lcr)
                q = np.column_stack([xx, yy]) * px
                dist = np.hypot(*(q - centro).T)
                j = lcr[yy[dist.argmin()], xx[dist.argmin()]]
                if dist.min() < 0.5 * out["DTC"]:
                    pr = (q[lcr[yy, xx] == j] - centro) @ v[1]
                    out["CM"] = pr.max() - pr.min() + px
    elif plano == "perfil" and pose is not None:
        comp, n = etiquetar(lab == T["hueso"])
        hn = pose.info.get("hueso_nasal")
        if n and hn is not None:
            cm = 0.5 * (hn[0] + hn[1]) - pose.origen
            col = int(round((cm @ pose.ex - res["xs"][0]) / px))
            fil = int(round((cm @ pose.ez - res["zs"][0]) / px))
            ventana = comp[max(fil - 3, 0):fil + 4, max(col - 3, 0):col + 4]
            ks = ventana[ventana > 0]
            if ks.size:
                yy, xx = np.nonzero(comp == np.bincount(ks).argmax())
                q = np.column_stack([xx, yy]) * px
                q = q - q.mean(0)
                v = np.linalg.svd(q, full_matrices=False)[2][0]
                proy = q @ v
                out["HN"] = proy.max() - proy.min() + px
    elif plano == "abdominal":
        cuerpo = (lab >= T["fetal"]) & (lab != T["amniotico"]) & (lab != T["cordon"])
        comp, _ = etiquetar(binary_fill_holes(cuerpo))
        sem = comp[lab == T["liquido"]]          # el estómago está en el abdomen
        if sem.size and (sem > 0).any():
            m = comp == np.bincount(sem[sem > 0]).argmax()
            # apertura con un disco de ~1/4 del radio: separa brazos o piernas que
            # tocan el abdomen (como al ajustar la elipse sólo a la piel del abdomen)
            r = 0.25 * math.sqrt(m.sum() / math.pi)
            nucleo = distance_transform_edt(m) > r
            m = m & (distance_transform_edt(~nucleo) <= r)
            comp, _ = etiquetar(m)
            sem = comp[lab == T["liquido"]]
            if (sem > 0).any():
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
