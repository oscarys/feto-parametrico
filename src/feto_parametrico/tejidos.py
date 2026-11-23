# -*- coding: utf-8 -*-
"""
tejidos.py — Tabla de propiedades acústicas por tejido (etiqueta).

Viene del simulador 2D anterior (fetal_us_sim/phantom.py) con tejidos nuevos
para el modelo 3D (cerebelo, vítreo, riñón, intestino, cordón).

Z: impedancia acústica (MRayl); alfa: atenuación (dB/cm/MHz);
dispersion: amplitud relativa del moteado (speckle) difuso.
Los valores son aproximados, para un simulador didáctico.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Tejido:
    nombre: str
    Z: float
    alfa: float
    dispersion: float
    color: tuple


TEJIDOS = [
    Tejido("gel",        1.48, 0.002, 0.00,  (0.05, 0.05, 0.08)),
    Tejido("piel",       1.70, 1.00,  1.20,  (0.95, 0.80, 0.70)),
    Tejido("grasa",      1.38, 0.60,  0.45,  (0.98, 0.90, 0.45)),
    Tejido("musculo",    1.70, 1.10,  0.75,  (0.80, 0.35, 0.30)),
    Tejido("materno",    1.63, 0.70,  0.60,  (0.65, 0.45, 0.40)),
    Tejido("miometrio",  1.65, 0.90,  0.90,  (0.85, 0.50, 0.55)),
    Tejido("placenta",   1.60, 0.60,  1.10,  (0.60, 0.25, 0.55)),
    Tejido("amniotico",  1.52, 0.005, 0.003, (0.15, 0.25, 0.45)),
    Tejido("fetal",      1.60, 0.60,  0.60,  (0.93, 0.74, 0.64)),
    Tejido("cerebro",    1.58, 0.50,  0.25,  (0.75, 0.75, 0.85)),
    Tejido("lcr",        1.52, 0.005, 0.005, (0.20, 0.55, 0.85)),
    Tejido("coroides",   1.62, 0.60,  1.60,  (0.95, 0.55, 0.85)),
    Tejido("hueso",      4.00, 10.0,  1.00,  (0.97, 0.97, 0.92)),  # según osificación
    Tejido("sangre",     1.61, 0.15,  0.012, (0.80, 0.10, 0.15)),
    Tejido("miocardio",  1.67, 0.80,  0.80,  (0.95, 0.40, 0.40)),
    Tejido("pulmon",     1.62, 0.70,  1.00,  (0.55, 0.80, 0.70)),
    Tejido("higado",     1.65, 0.70,  0.65,  (0.55, 0.30, 0.22)),
    Tejido("liquido",    1.52, 0.005, 0.005, (0.25, 0.65, 0.85)),  # estómago, vejiga
    Tejido("talamo",     1.59, 0.50,  0.38,  (0.55, 0.55, 0.80)),
    Tejido("hoz",        1.72, 0.80,  1.50,  (1.00, 0.90, 0.30)),
    Tejido("cerebelo",   1.59, 0.50,  0.45,  (0.60, 0.50, 0.80)),
    Tejido("vitreo",     1.52, 0.005, 0.003, (0.30, 0.70, 0.95)),
    Tejido("rinon",      1.62, 0.70,  0.50,  (0.70, 0.30, 0.30)),
    Tejido("intestino",  1.62, 0.70,  0.95,  (0.85, 0.70, 0.45)),
    Tejido("cordon",     1.58, 0.40,  0.35,  (0.85, 0.85, 0.75)),
]
T = {t.nombre: i for i, t in enumerate(TEJIDOS)}
COLORES = np.array([t.color for t in TEJIDOS])


def osificacion(eg: float) -> float:
    """0..1, mineralización ósea aproximada (controla impedancia y sombra del hueso)."""
    return float(np.clip((eg - 11.0) / 22.0, 0.12, 1.0))


def tablas_propiedades(osif: float):
    """(Z, alfa, dispersión) por etiqueta, con el hueso según la osificación."""
    Z = np.array([t.Z for t in TEJIDOS])
    a = np.array([t.alfa for t in TEJIDOS])
    s = np.array([t.dispersion for t in TEJIDOS])
    b = T["hueso"]
    Z[b] = 1.65 + osif * 3.5
    a[b] = 1.5 + osif * 9.0
    s[b] = 0.6 + osif * 1.2
    return Z, a, s
