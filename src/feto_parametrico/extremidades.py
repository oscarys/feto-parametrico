# -*- coding: utf-8 -*-
"""
extremidades.py — Manos con cinco dedos y pies con cinco ortejos, con sus huesos,
compartidos por la superficie (`superficie.py`) y la escena 3D (`feto3d.py`).

Cada función recibe el punto de partida (muñeca o tobillo), un marco (e1 distal,
e2 a lo ancho, e3 dorsal) y el largo de la mano o del pie, y devuelve elementos en
coordenadas absolutas:

    dict(nombre, tipo="elip", centro, semiejes, R, k)   o
    dict(nombre, tipo="cono", a, b, ra, rb, k)

Proporciones aproximadas de la mano y el pie fetales; los dedos se flexionan hacia
la palma según `puno` (0 abierta, 1 puño). Osifican las falanges, los metacarpianos
y metatarsianos y, en el pie, el calcáneo; los huesos del carpo no (nacen cartilaginosos).

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math

import numpy as np


def _u(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _girar(v, eje, grados):
    """Rodrigues: v girado alrededor de eje."""
    k = _u(eje)
    a = math.radians(grados)
    return v * math.cos(a) + np.cross(k, v) * math.sin(a) + k * (k @ v) * (1 - math.cos(a))


def marco_ortonormal(e1, e3_aprox):
    """(e1, e2, e3) ortonormal con e1 exacto y e3 lo más cerca posible de e3_aprox."""
    e1 = _u(e1)
    e3 = _u(np.asarray(e3_aprox, float) - (np.asarray(e3_aprox, float) @ e1) * e1)
    return e1, np.cross(e3, e1), e3


def _cadena(nombre, base, direccion, palmar, largos, radios, flexiones, k, huesos, piel,
            r_hueso=0.38):
    """Dedo: segmentos (falanges) que se doblan hacia `palmar` en cada articulación."""
    p = np.asarray(base, float)
    d = _u(direccion)
    for j, (l, (ra, rb), fl) in enumerate(zip(largos, radios, flexiones)):
        if fl:
            eje = np.cross(d, palmar)
            if np.linalg.norm(eje) > 1e-9:
                d = _u(_girar(d, eje, fl))
        q = p + l * d
        piel.append(dict(nombre=f"{nombre}_{j}", tipo="cono", a=p, b=q - rb * d, ra=ra, rb=rb, k=k))
        # falange: un poco más corta que el segmento, centrada
        huesos.append(dict(nombre=f"falange_{nombre}_{j}", tipo="cono",
                           a=p + 0.15 * l * d, b=q - 0.20 * l * d,
                           ra=r_hueso * ra, rb=r_hueso * rb, k=0.0))
        p = q
    return p


def mano(nombre, muneca, e1, e2, e3, L, puno=0.15):
    """Mano: palma, cuatro dedos y pulgar. e2 apunta hacia el lado del pulgar."""
    muneca = np.asarray(muneca, float)
    piel, huesos = [], []
    R = np.column_stack([e3, e2, e1]).astype(np.float32)
    piel.append(dict(nombre=f"palma_{nombre}", tipo="elip", centro=muneca + 0.27 * L * e1,
                     semiejes=(0.10 * L, 0.24 * L, 0.29 * L), R=R, k=0.10 * L))
    palmar = -e3
    # índice, medio, anular, meñique
    lados = (0.15, 0.05, -0.05, -0.15)
    largos = (0.40, 0.44, 0.41, 0.33)
    abiertos = (9.0, 3.0, -4.0, -11.0)                 # dedos algo separados: se pueden contar
    radios = (0.044, 0.046, 0.043, 0.038)
    for i, (w, lg, ab, r) in enumerate(zip(lados, largos, abiertos, radios)):
        base = muneca + 0.52 * L * e1 + w * L * e2 - 0.01 * L * e3
        d0 = math.cos(math.radians(ab)) * e1 + math.sin(math.radians(ab)) * e2   # + = pulgar
        seg = (0.45 * lg * L, 0.30 * lg * L, 0.25 * lg * L)
        rr = (r * L, 0.88 * r * L, 0.76 * r * L)
        _cadena(f"dedo{i + 2}_{nombre}", base, d0, palmar, seg,
                ((rr[0], rr[1]), (rr[1], rr[2]), (rr[2], 0.9 * rr[2])),
                (70 * puno, 90 * puno, 60 * puno), 0.12 * r * L, huesos, piel)
        huesos.append(dict(nombre=f"metacarpiano{i + 2}_{nombre}", tipo="cono",
                           a=muneca + 0.08 * L * e1 + 0.7 * w * L * e2,
                           b=base - 0.08 * L * e1 - 0.15 * w * L * e2, ra=0.018 * L,
                           rb=0.020 * L, k=0.0))
    # pulgar: sale del borde radial de la palma, hacia afuera y hacia la palma
    base = muneca + 0.16 * L * e1 + 0.17 * L * e2 - 0.03 * L * e3
    d0 = _u(math.cos(math.radians(40)) * e1 + math.sin(math.radians(40)) * e2 - 0.30 * e3)
    r = 0.062 * L
    _cadena(f"dedo1_{nombre}", base, d0, palmar, (0.19 * L, 0.15 * L),
            ((r, 0.9 * r), (0.9 * r, 0.8 * r)), (25 * puno, 40 * puno), 0.25 * r, huesos, piel)
    huesos.append(dict(nombre=f"metacarpiano1_{nombre}", tipo="cono",
                       a=muneca + 0.04 * L * e1 + 0.10 * L * e2, b=base - 0.01 * L * d0,
                       ra=0.020 * L, rb=0.020 * L, k=0.0))
    return {"piel": piel, "huesos": huesos, "palma": muneca + 0.40 * L * e1}


def pie(nombre, talon, e1, e2, e3, lp, r_tobillo):
    """Pie: talón y planta, cinco ortejos, calcáneo, metatarsianos y falanges.
    El largo del talón a la punta del primer ortejo es exactamente lp. e2 apunta hacia
    el lado medial (el del primer ortejo)."""
    talon = np.asarray(talon, float)
    piel, huesos = [], []
    R = np.column_stack([e3, e2, e1]).astype(np.float32)
    rt = min(r_tobillo, 0.12 * lp)
    piel.append(dict(nombre=f"talon_{nombre}", tipo="cono", a=talon + rt * e1,
                     b=talon + 0.30 * lp * e1, ra=rt, rb=0.12 * lp, k=0.08 * lp))
    piel.append(dict(nombre=f"planta_{nombre}", tipo="elip", centro=talon + 0.52 * lp * e1,
                     semiejes=(0.10 * lp, 0.20 * lp, 0.32 * lp), R=R, k=0.08 * lp))
    # primer a quinto ortejo (medial -> lateral)
    lados = (0.12, 0.04, -0.02, -0.075, -0.125)
    largos = (0.20, 0.15, 0.13, 0.11, 0.09)
    radios = (0.050, 0.028, 0.026, 0.025, 0.024)
    fondo = (0.80, 0.81, 0.79, 0.77, 0.74)
    abiertos = (0.0, -3.0, -7.0, -11.0, -15.0)         # en abanico hacia lateral
    punta = None
    for i, (w, lg, r, f, ab) in enumerate(zip(lados, largos, radios, fondo, abiertos)):
        base = talon + f * lp * e1 + w * lp * e2
        if i == 0:
            lg = 1.0 - f                               # la punta del primero marca el largo
        d = math.cos(math.radians(ab)) * e1 + math.sin(math.radians(ab)) * e2   # + = medial
        q = base + lg * lp * d
        piel.append(dict(nombre=f"ortejo{i + 1}_{nombre}", tipo="cono", a=base,
                         b=q - r * lp * d, ra=r * lp, rb=r * lp, k=0.12 * r * lp))
        huesos.append(dict(nombre=f"falange_ortejo{i + 1}_{nombre}", tipo="cono",
                           a=base + 0.15 * lg * lp * d, b=q - 0.25 * lg * lp * d,
                           ra=0.35 * r * lp, rb=0.30 * r * lp, k=0.0))
        huesos.append(dict(nombre=f"metatarsiano{i + 1}_{nombre}", tipo="cono",
                           a=talon + 0.40 * lp * e1 + 0.5 * w * lp * e2,
                           b=base - 0.08 * lp * e1 - 0.15 * w * lp * e2, ra=0.022 * lp,
                           rb=0.022 * lp, k=0.0))
        if i == 0:
            punta = q
    huesos.append(dict(nombre=f"calcaneo_{nombre}", tipo="elip", centro=talon + 0.13 * lp * e1,
                       semiejes=(0.05 * lp, 0.05 * lp, 0.09 * lp), R=R, k=0.0))
    return {"piel": piel, "huesos": huesos, "talon": talon, "punta": punta,
            "planta": talon + 0.52 * lp * e1}
