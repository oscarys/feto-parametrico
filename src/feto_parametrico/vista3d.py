# -*- coding: utf-8 -*-
"""
vista3d.py — Mallas PyVista de una Escena (feto con órganos, útero, placenta,
cordón) para visualizar en 3D.

Los órganos son primitivas analíticas, así que sus mallas se construyen
directamente (elipsoides y cápsulas). Sólo la piel fetal, que es una unión
suave de muchas piezas, se extrae con marching cubes.

Las funciones *_np sólo usan NumPy y devuelven (V, F): son las que deben usar
los hilos de trabajo, porque VTK no es seguro entre hilos (ver mallas_np.py).

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import numpy as np
from skimage.measure import marching_cubes

from .feto3d import Escena, _caja, sdf_piel
from .superficie import componente_mayor
from .tejidos import TEJIDOS, T
from . import mallas_np as mnp


class _PyVistaPerezoso:
    """Importa PyVista (y VTK) sólo al crear el primer objeto VTK. Así las rutas
    de NumPy que usan los hilos de trabajo ni siquiera cargan VTK."""

    def __getattr__(self, nombre):
        import pyvista
        return getattr(pyvista, nombre)


pv = _PyVistaPerezoso()

# opacidad por tejido en la vista 3D (0 = no se dibuja)
OPACIDAD = {"hueso": 1.0, "cerebro": 0.12, "lcr": 1.0, "coroides": 1.0, "talamo": 1.0,
            "cerebelo": 0.9, "hoz": 0.0, "vitreo": 1.0, "miocardio": 0.45, "sangre": 1.0,
            "pulmon": 0.40, "higado": 0.75, "liquido": 1.0, "rinon": 1.0,
            "intestino": 0.6, "cordon": 1.0, "cristalino": 1.0,
            "vermis": 0.9}


# ---------------------------------------------------------------------------
# Geometría con NumPy (segura en hilos de trabajo) -> (V, F)
# ---------------------------------------------------------------------------

def _malla_prim_np(pr):
    if pr.tipo in ("elip", "cascara"):
        se = pr.p["semiejes"]
        V, F = mnp.elipsoide(se, pr.R, pr.centro, fino=max(se) > 4)
        if "corte" in pr.p:                   # sólo las caras del lado que se conserva
            n, d = pr.p["corte"][:2]
            dentro = pr.local(V) @ np.asarray(n) <= d
            F = F[dentro[F].all(axis=1)]
        return V, F
    return mnp.capsula(pr.p["a"], pr.p["b"], 0.5 * (pr.p["ra"] + pr.p["rb"]))


def mallas_organos_np(prims) -> list:
    """Órganos agrupados por tejido: [(nombre, (V, F), color, opacidad)]."""
    out = []
    grupos: dict[int, list] = {}
    for pr in prims:
        grupos.setdefault(pr.etiqueta, []).append(pr)
    for etq, ps in grupos.items():
        nombre = TEJIDOS[etq].nombre
        op = OPACIDAD.get(nombre, 0.8)
        if op == 0:
            continue
        if nombre == "hueso":                 # la calota se dibuja aparte, translúcida
            cal = [p for p in ps if p.nombre == "calota"]
            if cal:
                out.append(("calota", _malla_prim_np(cal[0]), TEJIDOS[etq].color, 0.28))
            ps = [p for p in ps if p.nombre != "calota"]
        if ps:
            out.append((nombre, mnp.unir([_malla_prim_np(p) for p in ps]), TEJIDOS[etq].color, op))
    return out


def malla_piel_np(esc: Escena, resolucion: int = 120):
    """Superficie de la piel fetal (mundo) como (V, F)."""
    import trimesh
    piezas = esc.feto.piezas
    lo, hi = _caja(piezas)
    h = (hi - lo).max() / resolucion
    ejes = [np.arange(lo[i], hi[i] + h, h, dtype=np.float32) for i in range(3)]
    X, Yg, Z = np.meshgrid(*ejes, indexing="ij")
    P = np.column_stack([X.ravel(), Yg.ravel(), Z.ravel()])
    d = sdf_piel(piezas, P)
    v, f, _, _ = marching_cubes(d.reshape(X.shape), 0.0, spacing=(h, h, h))
    m = componente_mayor(trimesh.Trimesh(esc.a_mundo(v + lo), f, process=True))
    trimesh.smoothing.filter_taubin(m, iterations=10)
    return np.asarray(m.vertices), np.asarray(m.faces)


def malla_placenta_np(esc: Escena, h: float = 2.0):
    import trimesh
    c = esc.cav
    ejes = [np.arange(-c[i] - 2, c[i] + 2, h, dtype=np.float32) for i in range(3)]
    X, Yg, Z = np.meshgrid(*ejes, indexing="ij")
    P = np.column_stack([X.ravel(), Yg.ravel(), Z.ravel()])
    etq, _, _ = esc.evaluar_materno(P)
    vol = (etq == T["placenta"]).reshape(X.shape).astype(np.float32)
    if vol.sum() == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    v, f, _, _ = marching_cubes(vol, 0.5, spacing=(h, h, h))
    m = trimesh.Trimesh(v + np.array([e[0] for e in ejes]), f, process=True)
    trimesh.smoothing.filter_taubin(m, iterations=30)
    return np.asarray(m.vertices), np.asarray(m.faces)


def mallas_escena_np(esc: Escena, resolucion_piel: int = 120, placenta=True, utero=True):
    """Como mallas_escena, pero con (V, F) de NumPy: usable desde hilos de trabajo."""
    out = mallas_organos_np([pr.transformada(esc.Rg, esc.tg) for pr in esc.feto.organos])
    out.append(("piel", malla_piel_np(esc, resolucion_piel), TEJIDOS[T["fetal"]].color, 0.20))
    cam = esc.camino_cordon
    t = np.linspace(0, 1, len(cam)); tt = np.linspace(0, 1, 150)
    suave = np.column_stack([np.interp(tt, t, cam[:, k]) for k in range(3)])
    out.append(("cordon", mnp.tubo_camino(suave, esc.radio_cordon), TEJIDOS[T["cordon"]].color, 1.0))
    if placenta:
        out.append(("placenta", malla_placenta_np(esc), TEJIDOS[T["placenta"]].color, 0.9))
    if utero:
        out.append(("utero", mnp.elipsoide(esc.cav), TEJIDOS[T["miometrio"]].color, 0.10))
    return out


# ---------------------------------------------------------------------------
# Versiones PyVista (sólo en el hilo principal / scripts sin hilos)
# ---------------------------------------------------------------------------

def a_pv_lista(mallas_np):
    """[(nombre, (V, F), color, op)] -> [(nombre, PolyData, color, op)]."""
    return [(n, mnp.a_pv(m), c, o) for n, m, c, o in mallas_np]


def _malla_prim(pr) -> pv.PolyData:
    return mnp.a_pv(_malla_prim_np(pr))


def mallas_organos(prims) -> list:
    return a_pv_lista(mallas_organos_np(prims))


def malla_piel(esc: Escena, resolucion: int = 120) -> pv.PolyData:
    return mnp.a_pv(malla_piel_np(esc, resolucion))


def malla_placenta(esc: Escena, h: float = 2.0) -> pv.PolyData:
    return mnp.a_pv(malla_placenta_np(esc, h))


def mallas_escena(esc: Escena, resolucion_piel: int = 120, placenta=True, utero=True):
    """Lista de (nombre, malla, color, opacidad) en coordenadas del mundo."""
    return a_pv_lista(mallas_escena_np(esc, resolucion_piel, placenta, utero))


def agregar_escena(p: pv.Plotter, mallas, recorte=None, render=True):
    """Añade las mallas a un plotter. `recorte`: (origen, normal) para cortar el útero."""
    for nombre, m, color, op in mallas:
        if m.n_points == 0:
            continue
        if recorte is not None and nombre in ("utero", "placenta"):
            m = m.clip(normal=recorte[1], origin=recorte[0], invert=True)
        p.add_mesh(m, color=color, opacity=op, smooth_shading=True, specular=0.3,
                   name=nombre, show_scalar_bar=False, render=False)
    if render:
        p.render()


# ---------------------------------------------------------------------------
# Sonda y abanico de la imagen en 3D
# ---------------------------------------------------------------------------

def abanico_3d(pose, sonda, res, sub=2):
    """StructuredGrid con la forma de la imagen (sector, trapecio o rectángulo) en el
    mundo y la imagen como escalar."""
    from .ecografia import haz_a_plano
    u, d = res["u"][::sub], res["d"][::sub * 5]
    U, D = np.meshgrid(u, d, indexing="ij")
    X, Z = haz_a_plano(sonda, U, D)
    P = pose.a_mundo(X, Z)
    g = pv.StructuredGrid(P[..., 0], P[..., 1], P[..., 2])
    g["eco"] = res["bmodo_haz"][::sub, ::sub * 5].ravel(order="F")
    return g


def sonda_3d(pose, sonda=None, largo=None):
    """Caja que representa la sonda; su largo sigue la huella del transductor."""
    if largo is None:
        largo = 55.0 if sonda is None else sonda.huella_mm + 10.0
    c = pose.origen - 18 * pose.ez
    return pv.Cube(center=(0, 0, 0), x_length=largo, y_length=14, z_length=36).transform(
        np.block([[np.column_stack([pose.ex, pose.ey, pose.ez]), c[:, None]],
                  [np.zeros((1, 3)), np.ones((1, 1))]]), inplace=False)
