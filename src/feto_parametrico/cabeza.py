# -*- coding: utf-8 -*-
"""
cabeza.py — Cara y fosa posterior del feto, compartidas por la superficie
(`superficie.py`, visor y STL) y la escena 3D (`feto3d.py`, ecografía).

Todo se describe en el marco de la cabeza: x hacia la cara (frontal), y lateral,
z hacia el vértice. Las posiciones van normalizadas por los semiejes del cráneo
(a fronto-occipital, b transverso, c vertical) y los tamaños en mm, de modo que la
cara crece con la cabeza y las estructuras con nomograma propio (cerebelo, hueso
nasal) siguen su medida.

Medidas de referencia (mm, EG en semanas):
* DTC (diámetro transverso del cerebelo): EG = 0.557·DTC + 8.84
  (Adelabu et al. 2024, doi:10.4103/jmu.jmu_116_22).
* Hueso nasal: de 5.7 mm a las 18 semanas a 7.6 mm a las 23
  (doi:10.1515/jpm-2014-0296); grosor prenasal ≈ 0.61 × hueso nasal
  (https://pubmed.ncbi.nlm.nih.gov/21584886/).
* Cisterna magna: profundidad normal de 2 a 10 mm.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math

import numpy as np


def dtc(eg: float) -> float:
    """Diámetro transverso del cerebelo (mm)."""
    return (eg - 8.84) / 0.557


def hueso_nasal(eg: float) -> float:
    """Longitud del hueso nasal (mm)."""
    return 0.38 * eg - 1.1


def cisterna_magna(eg: float) -> float:
    """Profundidad antero-posterior de la cisterna magna (mm)."""
    return 2.5 + 0.12 * eg


# Base del cráneo: plano que separa la bóveda (encéfalo, calota) de la cara y el
# cuello. Pasa por encima de las órbitas por delante y por debajo de la fosa
# posterior por detrás: z = Z0 + PENDIENTE·x (coordenadas normalizadas).
BASE_Z0, BASE_PENDIENTE = -0.41, 0.387


def _giro_xz(u):
    """Rotación (marco de la cabeza) cuyo eje x local apunta a lo largo de u = (x, z)."""
    ex = np.array([u[0], 0.0, u[1]])
    ez = np.array([-u[1], 0.0, u[0]])
    return np.column_stack([ex, [0.0, 1.0, 0.0], ez])


def corte_base(a: float, c: float):
    """(n, d) en el marco local de la cabeza (mm): se conserva n·q <= d."""
    # z/c >= Z0 + m x/a  <=>  m/a·x - z/c <= -Z0
    n = np.array([BASE_PENDIENTE / a, 0.0, -1.0 / c])
    s = np.linalg.norm(n)
    return n / s, -BASE_Z0 / s


def _corte_por_recta(a, c, p, q):
    """Plano (normal en el plano x-z) por los puntos normalizados p y q; se conserva el
    lado opuesto al de la normal, que apunta hacia adelante y abajo. (n, d) en mm."""
    p = np.array([p[0] * a, 0.0, p[1] * c]); q = np.array([q[0] * a, 0.0, q[1] * c])
    t = q - p
    n = np.array([t[2], 0.0, -t[0]])
    n = n / np.linalg.norm(n)
    if n[0] < 0:
        n = -n
    return n, float(n @ p)


def corte_cara(a: float, c: float):
    """La piel del cráneo no cubre la cara: se recorta por delante y abajo de la
    recta glabela-mentón para que párpados, nariz y labios formen el perfil.
    (n, d, k): el tercer valor suaviza el borde del recorte (mm)."""
    n, d = _corte_por_recta(a, c, (0.97, -0.12), (0.50, -1.0))
    k = 0.12 * a
    return n, d + 0.25 * k, k        # el máximo suave hunde hasta k/4: se compensa


def geometria(a: float, b: float, c: float, eg: float) -> dict:
    """Piezas de la cara y órganos de la cabeza en el marco de la cabeza.

    Devuelve {"piel": [...], "restas": [...], "organos": [...]}, con elementos
    dict(nombre, tipo, ...): tipo "elip" (centro normalizado, semiejes en mm),
    "cono" (a, b normalizados; ra, rb en mm) o "cascara" (como elip, más grosor y
    un corte opcional (n, d) en mm). Los órganos llevan el nombre del tejido.
    """
    dbp = 2 * b
    E = lambda x, y, z: np.array([x, y, z], float)       # noqa: E731
    piel, restas, org = [], [], []

    def elip(lista, nombre, centro, semi, k=0.0, tejido=None, **extra):
        lista.append(dict(nombre=nombre, tipo="elip", centro=E(*centro), semiejes=tuple(semi),
                          k=k, tejido=tejido, **extra))

    def cono(lista, nombre, p, q, ra, rb, k=0.0, tejido=None):
        lista.append(dict(nombre=nombre, tipo="cono", a=E(*p), b=E(*q), ra=ra, rb=rb,
                          k=k, tejido=tejido))

    # ---------------------------------------------------------------- piel
    elip(piel, "cara", (0.50, 0, -0.48), (0.44 * a, 0.66 * b, 0.50 * c), 0.25 * b)
    for lado in (+1, -1):
        elip(piel, f"mejilla{lado:+d}", (0.66, 0.36 * lado, -0.50),
             (0.24 * a, 0.24 * b, 0.24 * c), 0.12 * b)
        elip(piel, f"parpado{lado:+d}", (0.84, 0.30 * lado, -0.24),
             (0.07 * a, 0.14 * b, 0.10 * c), 0.03 * b)
        elip(piel, f"ala_nasal{lado:+d}", (0.94, 0.11 * lado, -0.42),
             (0.05 * a, 0.06 * b, 0.045 * c), 0.04 * b)
    cono(piel, "dorso_nasal", (0.90, 0, -0.18), (0.98, 0, -0.36), 0.05 * b, 0.065 * b, 0.06 * b)
    elip(piel, "punta_nasal", (0.98, 0, -0.39), (0.055 * a, 0.10 * b, 0.06 * c), 0.05 * b)
    elip(piel, "labio_superior", (0.93, 0, -0.53), (0.07 * a, 0.20 * b, 0.065 * c), 0.05 * b)
    elip(piel, "labio_inferior", (0.91, 0, -0.64), (0.065 * a, 0.17 * b, 0.06 * c), 0.05 * b)
    elip(piel, "menton", (0.80, 0, -0.86), (0.14 * a, 0.20 * b, 0.13 * c), 0.10 * b)

    # ------------------------------------------------- restas (boca, narinas)
    hendidura = 0.25 + 0.01 * dbp
    elip(restas, "boca", (0.97, 0, -0.585), (0.10 * a, 0.15 * b, hendidura), 0.3)
    for lado in (+1, -1):
        elip(restas, f"fisura_palpebral{lado:+d}", (0.905, 0.30 * lado, -0.25),
             (0.03 * a, 0.12 * b, 0.6 * hendidura), 0.3)
        r = 0.5 + 0.012 * dbp
        elip(restas, f"narina{lado:+d}", (0.985, 0.055 * lado, -0.435), (r, 0.8 * r, 0.7 * r), 0.2)

    # ---------------------------------------------------------- ojos
    r_ojo = 0.11 * a
    for lado, sfx in ((+1, "i"), (-1, "d")):
        y = 0.30 * lado
        # órbita ósea: cáscara abierta por delante
        org.append(dict(nombre=f"orbita_{sfx}", tipo="cascara", centro=E(0.74, y, -0.24),
                        semiejes=(r_ojo + 0.9,) * 3, grosor=0.5 + 0.01 * dbp,
                        corte=(np.array([1.0, 0.0, 0.0]), 0.35 * r_ojo), k=0.0, tejido="hueso"))
        elip(org, f"ojo_{sfx}", (0.74, y, -0.24), (r_ojo, 0.11 * b, 0.11 * c), tejido="vitreo")
        elip(org, f"cristalino_{sfx}", (0.74 + 0.72 * r_ojo / a, y, -0.24),
             (0.12 * r_ojo, 0.30 * r_ojo, 0.30 * r_ojo), tejido="cristalino")

    # ---------------------------------------------------------- huesos de la cara
    g = 0.45 + 0.01 * dbp                                  # radio de los huesos finos
    nbl = hueso_nasal(eg)
    p0 = np.array([0.90 * a, 0.0, -0.18 * c])             # nasion (mm, marco de la cabeza)
    p1 = np.array([0.98 * a, 0.0, -0.36 * c])
    eje = (p1 - p0) / np.linalg.norm(p1 - p0)
    atras = np.array([-eje[2], 0.0, eje[0]])               # perpendicular, hacia adentro
    atras = -atras if atras[0] > 0 else atras
    prenasal = 0.61 * nbl                                  # piel delante del hueso
    base = p0 + (prenasal - 0.05 * b) * atras
    ra, rb = 0.8 * g, 0.6 * g                            # los casquetes cuentan en el largo
    n0, n1 = base + ra * eje, base + (nbl - rb) * eje
    cono(org, "hueso_nasal", n0 / (a, b, c), n1 / (a, b, c), ra, rb, tejido="hueso")

    def arco(nombre, cx, cz, rx, ry, t0, t1, n=9):
        ts = np.radians(np.linspace(t0, t1, n))
        P = [(cx + rx * math.cos(t) / a, ry * math.sin(t) / b, cz) for t in ts]
        for i in range(n - 1):
            cono(org, f"{nombre}{i}", P[i], P[i + 1], g, g, tejido="hueso")
        return P

    arco("maxilar", 0.52, -0.52, 0.36 * a, 0.34 * b, -75, 75)
    elip(org, "paladar", (0.62, 0, -0.47), (0.26 * a, 0.28 * b, 0.6 + 0.008 * dbp), tejido="hueso")
    P = arco("mandibula", 0.42, -0.76, 0.40 * a, 0.42 * b, -90, 90)
    for extremo, lado in ((P[0], -1), (P[-1], +1)):
        cono(org, f"rama_mandibular{lado:+d}", extremo, (0.10, 0.55 * lado, -0.50), g, g,
             tejido="hueso")

    # ---------------------------------------------------------- fosa posterior
    # El plano transcerebelar pasa por el CSP y por el centro del cerebelo; el
    # cerebelo se coloca de modo que, a lo largo de ese plano, entre el vermis y la
    # pared interna del occipital quede exactamente la cisterna magna.
    t = dtc(eg)
    cm = cisterna_magna(eg)
    zc = -0.40 * c                                         # altura del cerebelo (mm)
    g_cal = 0.6 + 0.03 * dbp
    ai, ci = a - g_cal, c - g_cal
    vx = 0.20 * t                                          # semieje AP del vermis
    csp = np.array([0.30 * a, 0.01 * c])                   # (x, z) del CSP, como en feto3d
    x_cb = -0.5 * a
    for _ in range(30):
        cb = np.array([x_cb, zc])
        u = (cb - csp) / np.linalg.norm(cb - csp)          # hacia atrás y abajo
        # cb + s u sobre la elipse interna (x/ai)^2 + (z/ci)^2 = 1
        A = (u[0] / ai) ** 2 + (u[1] / ci) ** 2
        B = 2 * (cb[0] * u[0] / ai ** 2 + cb[1] * u[1] / ci ** 2)
        C = (cb[0] / ai) ** 2 + (cb[1] / ci) ** 2 - 1
        s = (-B + math.sqrt(B * B - 4 * A * C)) / (2 * A)  # distancia hasta la pared
        x_cb += 0.8 * (s - (vx + cm)) * u[0]
    # la cisterna empieza en el vermis y se mete 1.5 mm en el hueso (la calota se pinta
    # encima), así llega siempre a la pared interna
    semi = 0.5 * cm + 0.75
    m = cb + (vx + semi) * u
    elip(org, "cisterna_magna", (m[0] / a, 0, m[1] / c), (semi, 0.25 * t, 0.20 * t),
         tejido="lcr", R_local=_giro_xz(u))
    for lado in (+1, -1):
        elip(org, f"hemisferio_cerebeloso{lado:+d}", ((x_cb + 0.02 * t) / a, 0.25 * t * lado / b,
                                                     zc / c),
             (0.22 * t, 0.25 * t, 0.25 * t), tejido="cerebelo")
    elip(org, "cerebelo", (x_cb / a, 0, zc / c), (vx, 0.12 * t, 0.24 * t), tejido="vermis")
    return {"piel": piel, "restas": restas, "organos": org,
            "medidas": {"DTC": t, "CM": cm, "HN": nbl}}
