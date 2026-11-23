# -*- coding: utf-8 -*-
"""
sonda_control.py — Estado de la sonda virtual y su conversión a una Pose
(ecografia.py), independiente de la interfaz y de la fuente de entrada.

El estado es (x, y, R):
* (x, y): punto del abdomen materno visto desde arriba (mm, mundo: x izquierda
  de la madre, y craneal). La sonda se apoya en la piel bajo ese punto.
* R: orientación de la sonda (columnas ex, ey, ez = lateral de la imagen,
  elevación, haz hacia adentro), en el mundo.

Fuentes posibles (ver fuentes_sonda.py): teclado y ratón, o una sonda física
que envíe posición y cuaternión (IMU) por UDP.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .ecografia import PLANOS, Pose, plano_estandar
from .feto3d import Escena, _rot, _unit


def punto_piel(esc: Escena, x: float, y: float):
    """Punto de la piel materna en la vertical de (x, y) y la normal exterior."""
    z_hi = esc.c_abd[2] + esc.abd[2] + 20.0
    z_lo = esc.c_abd[2]
    if esc.sdf_abdomen(np.array([[x, y, z_lo]], np.float32))[0] >= 0:
        return None, None                          # fuera de la silueta del abdomen
    for _ in range(50):
        zm = 0.5 * (z_lo + z_hi)
        if esc.sdf_abdomen(np.array([[x, y, zm]], np.float32))[0] < 0:
            z_lo = zm
        else:
            z_hi = zm
    p = np.array([x, y, 0.5 * (z_lo + z_hi)])
    h = 0.5
    g = np.array([(esc.sdf_abdomen((p + h * e)[None].astype(np.float32))[0]
                   - esc.sdf_abdomen((p - h * e)[None].astype(np.float32))[0]) for e in np.eye(3)])
    return p, _unit(g)


def orientacion_normal(normal, giro_grados=0.0):
    """Sonda perpendicular a la piel; giro 0 = plano transversal materno
    (ex hacia la izquierda de la madre)."""
    ez = -_unit(normal)
    ex = _unit(np.array([1.0, 0.0, 0.0]) - (np.array([1.0, 0.0, 0.0]) @ ez) * ez)
    R = np.column_stack([ex, np.cross(ez, ex), ez])
    return _rot(ez, math.radians(giro_grados)) @ R


def cuaternion_a_matriz(q):
    w, x, y, z = _unit(np.asarray(q, float))
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


@dataclass
class EstadoSonda:
    x: float = 0.0
    y: float = 0.0
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    # calibración de una sonda física: orientación de referencia
    R_ref_imu: np.ndarray | None = None
    R_ref_mundo: np.ndarray | None = None

    # ................................................................ pose
    def pose(self, esc: Escena) -> Pose | None:
        p, n = punto_piel(esc, self.x, self.y)
        if p is None:
            return None
        R = self.R
        if R[:, 2] @ n > -0.2:          # la sonda no puede apuntar hacia afuera
            R = orientacion_normal(n)
        return Pose(p, R[:, 0].copy(), R[:, 2].copy(), {"normal_piel": n})

    # ........................................................... movimientos
    def colocar_normal(self, esc: Escena, giro=0.0):
        _, n = punto_piel(esc, self.x, self.y)
        if n is not None:
            self.R = orientacion_normal(n, giro)

    def mover(self, dx, dy):
        self.x += dx; self.y += dy

    def deslizar(self, d_lateral, d_elevacion):
        """Desplazamiento en el marco de la sonda (proyectado en el plano x-y)."""
        for d, eje in ((d_lateral, self.R[:, 0]), (d_elevacion, self.R[:, 1])):
            v = np.array([eje[0], eje[1]])
            if np.linalg.norm(v) > 1e-6:
                v = v / np.linalg.norm(v) * d
                self.x += v[0]; self.y += v[1]

    def rotar(self, giro=0.0, balanceo=0.0, abanico=0.0):
        """Grados. giro: alrededor del haz; balanceo (rock): en el plano de la
        imagen; abanico (fan): fuera del plano."""
        R = self.R
        for eje, ang in ((R[:, 2], giro), (R[:, 1], balanceo), (R[:, 0], abanico)):
            if ang:
                R = _rot(eje, math.radians(ang)) @ R
        U, _, Vt = np.linalg.svd(R)          # reortonormalizar
        self.R = U @ Vt

    def desde_pose(self, pose: Pose):
        self.x, self.y = float(pose.origen[0]), float(pose.origen[1])
        self.R = np.column_stack([pose.ex, pose.ey, pose.ez])

    # .................................................. sonda física (IMU)
    def calibrar_imu(self, q_imu):
        """La orientación actual de la IMU pasa a corresponder a la actual de la sonda virtual."""
        self.R_ref_imu = cuaternion_a_matriz(q_imu)
        self.R_ref_mundo = self.R.copy()

    def desde_imu(self, q_imu):
        Rq = cuaternion_a_matriz(q_imu)
        if self.R_ref_imu is None:
            self.calibrar_imu(q_imu)
        # rotación relativa desde la calibración, aplicada en el mundo
        self.R = Rq @ self.R_ref_imu.T @ self.R_ref_mundo


# ---------------------------------------------------------------------------
# Retroalimentación: qué tan cerca está la imagen de cada plano estándar
# ---------------------------------------------------------------------------

@dataclass
class Tolerancia:
    angulo_grados: float = 10.0
    distancia_mm: float = 4.0


def errores_planos(esc: Escena, pose: Pose, planos=PLANOS):
    """{plano: (ángulo entre planos en grados, distancia del objetivo al plano en mm)}."""
    out = {}
    n = _unit(pose.ey)
    for nom in planos:
        try:
            ref = plano_estandar(esc, nom)
        except ValueError:
            continue
        n_ref = _unit(ref.info["normal"])
        ang = math.degrees(math.acos(min(1.0, abs(float(n @ n_ref)))))
        dist = abs(float((ref.info["centro"] - pose.origen) @ n))
        out[nom] = (ang, dist)
    return out
