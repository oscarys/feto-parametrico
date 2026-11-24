# -*- coding: utf-8 -*-
"""
volumen.py — Sonda matricial: volumen 3D, cortes ortogonales (MPR) y biplano.

Una sonda matricial (2D array) barre, además del abanico de la imagen, un abanico en
elevación. Aquí el volumen se arma con planos 2D de `ecografia.simular`, inclinados
alrededor del eje lateral de la sonda (el vértice del abanico de elevación está en la
cara de la sonda), y se remuestrea a una rejilla cartesiana en el marco de la sonda:

    x  lateral (pose.ex)     y  elevación (pose.ey)     z  profundidad (pose.ez)

`Volumen.vol` es (nz, ny, nx), con valores 0..1 como la imagen modo B; `Volumen.etq`
las etiquetas de tejido (máscaras de referencia), -1 fuera del barrido.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

from .ecografia import Adquisicion, Pose, Sonda, simular
from .feto3d import Escena
from .tejidos import T


# ---------------------------------------------------------------------------
# Poses derivadas
# ---------------------------------------------------------------------------

def pose_elevacion(pose: Pose, grados: float) -> Pose:
    """El plano de la imagen inclinado `grados` en elevación (giro alrededor de ex)."""
    a = math.radians(grados)
    ez = math.cos(a) * pose.ez + math.sin(a) * pose.ey
    return Pose(pose.origen, pose.ex, ez, dict(pose.info))


def pose_biplano(pose: Pose) -> Pose:
    """Segundo plano del biplano: comparte el haz central y es perpendicular al primero
    (su eje lateral es la elevación del primero)."""
    return Pose(pose.origen, pose.ey, pose.ez, dict(pose.info))


# ---------------------------------------------------------------------------
# Volumen
# ---------------------------------------------------------------------------

@dataclass
class Volumen:
    vol: np.ndarray                 # (nz, ny, nx) float32, 0..1
    etq: np.ndarray                 # (nz, ny, nx) int16, -1 fuera del barrido
    x: np.ndarray                   # coordenadas de la rejilla (mm, marco de la sonda)
    y: np.ndarray
    z: np.ndarray
    pose: Pose
    info: dict = field(default_factory=dict)

    @property
    def voxel(self) -> float:
        return float(self.x[1] - self.x[0])

    def a_mundo(self, x, y, z):
        p = self.pose
        return (p.origen + np.multiply.outer(x, p.ex) + np.multiply.outer(y, p.ey)
                + np.multiply.outer(z, p.ez))

    def indice(self, x, y, z):
        """Índices (iz, iy, ix) más cercanos a un punto en mm."""
        return tuple(int(np.clip(round((v - e[0]) / self.voxel), 0, len(e) - 1))
                     for v, e in ((z, self.z), (y, self.y), (x, self.x)))

    def cortes(self, iz, iy, ix):
        """Tres cortes ortogonales por el voxel (iz, iy, ix):
        A: plano de la imagen (z, x); B: plano de elevación (z, y); C: coronal (y, x)."""
        return {"A": self.vol[:, iy, :], "B": self.vol[:, :, ix], "C": self.vol[iz, :, :],
                "A_etq": self.etq[:, iy, :], "B_etq": self.etq[:, :, ix],
                "C_etq": self.etq[iz, :, :]}


def simular_volumen(esc: Escena, pose: Pose, sonda: Sonda, adq: Adquisicion | None = None,
                    n_planos: int = 97, voxel_mm: float = 0.6, caja=None, hilos: int = 4,
                    progreso=None, semilla: int = 0) -> Volumen:
    """Barrido en elevación de la sonda matricial y remuestreo a una rejilla cartesiana.
    Con un número impar de planos, el central es el plano de la imagen 2D.

    caja: ((xmin, xmax), (ymin, ymax), (zmin, zmax)) en mm del marco de la sonda; por
    omisión todo el campo hasta la profundidad de la sonda. progreso(hechos, total)
    se llama tras cada plano.
    """
    adq = adq or Adquisicion()
    apertura = sonda.apertura_elev_grados or 60.0
    angulos = np.linspace(-apertura / 2, apertura / 2, n_planos)
    adq_p = replace(adq, px_salida_mm=voxel_mm, elevacion=(0.0,))
    if caja is not None:                             # no simular más hondo que la caja
        sonda = replace(sonda, profundidad_mm=float(min(sonda.profundidad_mm, caja[2][1] + 2)))

    # el plano central fija la escala de grises de todos (si no, cada plano se
    # normaliza por su cuenta y el volumen sale con bandas)
    norm = simular(esc, pose, sonda, adq_p, semilla=semilla, etiquetas=False)["normalizacion"]
    hechos = [0]

    def plano(k):
        r = simular(esc, pose_elevacion(pose, float(angulos[k])), sonda, adq_p,
                    semilla=semilla, etiquetas="rapidas", normalizacion=norm,
                    semilla_ruido=1000 * semilla + k + 1)          # ruido distinto en cada plano
        hechos[0] += 1
        if progreso:
            progreso(hechos[0], n_planos)
        return r

    with ThreadPoolExecutor(max_workers=max(1, hilos)) as ex:
        planos = list(ex.map(plano, range(n_planos)))
    xs, zs = planos[0]["xs"], planos[0]["zs"]
    B = np.stack([r["bmodo"] for r in planos])                     # (nφ, nz', nx)
    E = np.stack([r["etiquetas"] for r in planos]).astype(np.float32)

    if caja is None:
        zmax = float(zs[-1])
        ymax = zmax * math.sin(math.radians(apertura / 2))
        caja = ((xs[0], xs[-1]), (-ymax, ymax), (0.0, zmax))
    (x0, x1), (y0, y1), (z0, z1) = caja
    # rejillas alineadas con el origen: x = 0 e y = 0 (el plano central) caen en un vóxel
    eje = lambda a, b: (np.arange(math.ceil(a / voxel_mm), math.floor(b / voxel_mm) + 1)  # noqa: E731
                        * voxel_mm).astype(np.float32)
    x, y, z = eje(x0, x1), eje(y0, y1), eje(z0, z1)
    Z, Y = np.meshgrid(z, y, indexing="ij")
    phi = np.degrees(np.arctan2(Y, Z))                             # (nz, ny)
    prof = np.hypot(Y, Z)
    i_phi = (phi - angulos[0]) / (angulos[1] - angulos[0])
    i_z = (prof - zs[0]) / (zs[1] - zs[0])
    i_x = (x - xs[0]) / (xs[1] - xs[0])
    dentro2 = (i_phi >= 0) & (i_phi <= n_planos - 1) & (i_z >= 0) & (i_z <= len(zs) - 1)
    nz, ny, nx = len(z), len(y), len(x)
    coords = [np.broadcast_to(i_phi[..., None], (nz, ny, nx)),
              np.broadcast_to(i_z[..., None], (nz, ny, nx)),
              np.broadcast_to(i_x[None, None, :], (nz, ny, nx))]
    vol = map_coordinates(B, coords, order=1, mode="nearest").astype(np.float32)
    etq = map_coordinates(E, coords, order=0, mode="nearest").astype(np.int16)
    fuera = ~dentro2[..., None] | (i_x < 0)[None, None, :] | (i_x > len(xs) - 1)[None, None, :]
    vol[fuera] = 0.0
    etq[fuera] = -1
    return Volumen(vol, etq, x, y, z, pose,
                   dict(angulos=angulos, apertura_elev=apertura, n_planos=n_planos,
                        sonda=sonda, info_pose=pose.info))


def caja_alrededor(pose: Pose, sonda: Sonda, medio_ancho: float = 60.0, delante: float = 45.0,
                   detras: float = 35.0):
    """Caja de adquisición centrada en el objetivo de la pose (mm, marco de la sonda)."""
    d = float(pose.info.get("profundidad_objetivo", 0.6 * sonda.profundidad_mm))
    z0 = max(0.0, d - delante)
    z1 = min(sonda.profundidad_mm, d + detras)
    return ((-medio_ancho, medio_ancho), (-medio_ancho, medio_ancho), (z0, z1))


def inicio_render(v: Volumen, margen_mm: float = 2.0) -> float:
    """Profundidad donde empieza la caja de render: el líquido amniótico frente al
    objetivo (como al colocar a mano la caja de render en un equipo real)."""
    iy, ix = len(v.y) // 2, len(v.x) // 2
    col = v.etq[:, max(iy - 3, 0):iy + 4, max(ix - 3, 0):ix + 4]
    liquido = (col == T["amniotico"]).mean(axis=(1, 2)) > 0.5
    objetivo = float(v.info["info_pose"].get("profundidad_objetivo", v.z[len(v.z) // 2]))
    k_obj = int(np.clip(np.searchsorted(v.z, objetivo), 0, len(v.z) - 1))
    hay = np.flatnonzero(liquido[:k_obj])
    if not len(hay):
        return float(v.z[0])
    # el comienzo del tramo de líquido que llega hasta el feto
    k = hay[-1]
    while k > 0 and liquido[k - 1]:
        k -= 1
    return float(v.z[k] + margen_mm)


def volumen_para_render(v: Volumen, z_inicio: float | None = None, suavizado: float = 1.6):
    """Volumen suavizado (como el filtro de los equipos) y recortado por delante."""
    z_inicio = inicio_render(v) if z_inicio is None else z_inicio
    r = gaussian_filter(v.vol, suavizado)
    r[v.z < z_inicio] = 0.0
    r[v.etq < 0] = 0.0
    return r


def imagen_pv(v: Volumen, datos: np.ndarray):
    """pyvista.ImageData en el marco de la sonda (sólo en el hilo de la interfaz)."""
    import pyvista as pv
    img = pv.ImageData(dimensions=(len(v.x), len(v.y), len(v.z)),
                       spacing=(v.voxel,) * 3, origin=(float(v.x[0]), float(v.y[0]), float(v.z[0])))
    img.point_data["eco"] = np.ascontiguousarray(datos.transpose(2, 1, 0)).ravel(order="F")
    return img


def agregar_render(p, v: Volumen, z_inicio: float | None = None, umbral: float = 0.35,
                   nombre: str = "volumen"):
    """Render de superficie al estilo obstétrico: lo oscuro (líquido) transparente, el
    tejido opaco, en tono sepia."""
    datos = volumen_para_render(v, z_inicio)
    img = imagen_pv(v, datos)
    op = np.clip((np.linspace(0, 1, 64) - umbral) / 0.06, 0, 1)
    actor = p.add_volume(img, scalars="eco", cmap="copper", clim=(0.0, 1.0),
                         opacity=op, shade=True, name=nombre, show_scalar_bar=False,
                         ambient=0.30, diffuse=0.85, specular=0.30)
    return actor


def arriba_cabeza(esc: Escena, v: Volumen):
    """Dirección del vértice de la cabeza fetal en el marco de la sonda (para que el
    render muestre la cara derecha)."""
    u = esc.Rg @ esc.feto.marcos["cabeza"][1][:, 2]
    p = v.pose
    return np.array([u @ p.ex, u @ p.ey, u @ p.ez])


def camara_desde_sonda(p, v: Volumen, z_inicio: float | None = None, arriba=None):
    """Mira el volumen desde la sonda (el eje z del volumen va hacia adentro)."""
    z_inicio = inicio_render(v) if z_inicio is None else z_inicio
    zc = float(v.info.get("info_pose", {}).get("profundidad_objetivo", 0.5 * (z_inicio + v.z[-1])))
    foco = np.array([0.0, 0.0, zc])
    arriba = np.array([-1.0, 0.0, 0.0]) if arriba is None else np.asarray(arriba, float)
    arriba = arriba - arriba[2] * np.array([0.0, 0.0, 1.0])       # en el plano de la pantalla
    if np.linalg.norm(arriba) < 1e-6:
        arriba = np.array([-1.0, 0.0, 0.0])
    pos = foco - np.array([0.0, 0.0, 1.25 * (v.x[-1] - v.x[0])])
    p.camera_position = [tuple(pos), tuple(foco), tuple(arriba / np.linalg.norm(arriba))]
