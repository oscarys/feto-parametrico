# -*- coding: utf-8 -*-
"""
mallas_np.py — Mallas triangulares sólo con NumPy (vértices V (n,3), caras F (m,3)).

VTK no es seguro entre hilos: crear o filtrar objetos VTK en un hilo de trabajo
mientras el hilo de la interfaz dibuja puede bloquear la aplicación. Por eso los
hilos de trabajo de los visores construyen la geometría aquí, con NumPy, y sólo el
hilo de la interfaz la convierte a PyVista con `a_pv` (unos milisegundos).

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=8)
def _esfera(n_u=28, n_v=18):
    """Esfera unitaria UV: (V, F)."""
    u = np.linspace(0, 2 * np.pi, n_u, endpoint=False)
    v = np.linspace(0, np.pi, n_v + 1)[1:-1]
    U, Vv = np.meshgrid(u, v)
    V = np.column_stack([(np.sin(Vv) * np.cos(U)).ravel(), (np.sin(Vv) * np.sin(U)).ravel(),
                         np.cos(Vv).ravel()])
    V = np.vstack([V, [0, 0, 1], [0, 0, -1]])
    norte, sur = len(V) - 2, len(V) - 1
    F = []
    for i in range(n_v - 2):
        for j in range(n_u):
            a, b = i * n_u + j, i * n_u + (j + 1) % n_u
            c, d = a + n_u, b + n_u
            F += [(a, c, b), (b, c, d)]
    ult = (n_v - 2) * n_u
    for j in range(n_u):
        F.append((norte, j, (j + 1) % n_u))
        F.append((sur, ult + (j + 1) % n_u, ult + j))
    return V, np.asarray(F, np.int64)


def elipsoide(semiejes, R=np.eye(3), centro=(0, 0, 0), fino=True):
    V, F = _esfera(28, 18) if fino else _esfera(14, 9)
    return (V * np.asarray(semiejes)) @ np.asarray(R, float).T + np.asarray(centro, float), F


@lru_cache(maxsize=4)
def _tubo(n_lados=14):
    """Cilindro unitario abierto de z=0 a z=1 (radio 1)."""
    t = np.linspace(0, 2 * np.pi, n_lados, endpoint=False)
    anillo = np.column_stack([np.cos(t), np.sin(t)])
    V = np.vstack([np.column_stack([anillo, np.zeros(n_lados)]),
                   np.column_stack([anillo, np.ones(n_lados)])])
    F = []
    for j in range(n_lados):
        a, b = j, (j + 1) % n_lados
        F += [(a, b, a + n_lados), (b, b + n_lados, a + n_lados)]
    return V, np.asarray(F, np.int64)


def _marco_eje(eje):
    z = eje / np.linalg.norm(eje)
    aux = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(aux, z); x /= np.linalg.norm(x)
    return np.column_stack([x, np.cross(z, x), z])


def capsula(a, b, r):
    """Cilindro de a a b con radio r, cerrado por dos esferas."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = np.linalg.norm(b - a)
    if L < 1e-9:
        return elipsoide((r, r, r), centro=a, fino=False)
    Vt, Ft = _tubo()
    R = _marco_eje(b - a)
    Vt = (Vt * np.array([r, r, L])) @ R.T + a
    partes = [(Vt, Ft), elipsoide((r, r, r), centro=a, fino=False),
              elipsoide((r, r, r), centro=b, fino=False)]
    return unir(partes)


def tubo_camino(puntos, r, n_lados=16):
    """Tubo a lo largo de una polilínea (para el cordón)."""
    P = np.asarray(puntos, float)
    t = np.gradient(P, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    e1 = np.cross(t[0], [0.1, 0.2, 1.0]); e1 /= np.linalg.norm(e1)
    ang = np.linspace(0, 2 * np.pi, n_lados, endpoint=False)
    V = []
    for i in range(len(P)):
        e1 = e1 - (e1 @ t[i]) * t[i]; e1 /= np.linalg.norm(e1)
        e2 = np.cross(t[i], e1)
        V.append(P[i] + r * (np.cos(ang)[:, None] * e1 + np.sin(ang)[:, None] * e2))
    V = np.vstack(V)
    F = []
    for i in range(len(P) - 1):
        for j in range(n_lados):
            a, b = i * n_lados + j, i * n_lados + (j + 1) % n_lados
            F += [(a, b, a + n_lados), (b, b + n_lados, a + n_lados)]
    return V, np.asarray(F, np.int64)


def unir(partes):
    Vs, Fs, base = [], [], 0
    for V, F in partes:
        Vs.append(V); Fs.append(F + base); base += len(V)
    if not Vs:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    return np.vstack(Vs), np.vstack(Fs)


def trasladar(malla, d):
    V, F = malla
    return V + np.asarray(d, float), F


def a_pv(malla):
    """(V, F) -> pyvista.PolyData. Llamar SÓLO desde el hilo de la interfaz."""
    import pyvista as pv
    V, F = malla
    if len(F) == 0:
        return pv.PolyData()
    caras = np.column_stack([np.full(len(F), 3), F]).ravel()
    return pv.PolyData(np.asarray(V, np.float32), caras)
