# -*- coding: utf-8 -*-
"""Pruebas de la sonda matricial: geometría del barrido, volumen, cortes y biplano."""

import numpy as np
import pytest

from feto_parametrico.ecografia import plano_estandar, simular, sonda_para
from feto_parametrico.feto3d import Escena, Materno, Postura
from feto_parametrico.tejidos import T
from feto_parametrico.volumen import (caja_alrededor, inicio_render, pose_biplano,
                                      pose_elevacion, simular_volumen)


@pytest.fixture(scope="module")
def escena():
    # dorso posterior y cabeza extendida: la cara mira a la sonda
    return Escena(26, Postura(flex_cabeza=-5), mat=Materno(dorso_grados=180))


@pytest.fixture(scope="module")
def volumen(escena):
    pose = plano_estandar(escena, "perfil")
    s = sonda_para(pose, geometria="matricial", n_lineas=64, dr_mm=0.3)
    return simular_volumen(escena, pose, s, n_planos=25, voxel_mm=1.2,
                           caja=caja_alrededor(pose, s, medio_ancho=40))


def test_poses_derivadas_son_ortonormales(escena):
    pose = plano_estandar(escena, "perfil")
    for p in (pose_elevacion(pose, 20.0), pose_biplano(pose)):
        R = np.column_stack([p.ex, p.ey, p.ez])
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-6)
        assert np.allclose(p.origen, pose.origen)
    assert abs(float(pose_biplano(pose).ex @ pose.ex)) < 1e-6      # planos perpendiculares
    assert np.allclose(pose_biplano(pose).ez, pose.ez)              # mismo haz central


def test_volumen_contiene_el_plano_central(escena, volumen):
    v = volumen
    assert v.vol.shape == (len(v.z), len(v.y), len(v.x))
    assert 0.0 <= v.vol.min() and v.vol.max() <= 1.0
    # el corte A (elevación 0) tiene las mismas etiquetas que la imagen 2D del mismo plano
    pose = v.pose
    res = simular(escena, pose, v.info["sonda"], etiquetas="rapidas")
    iy = int(np.argmin(np.abs(v.y)))
    a = v.etq[:, iy, :]
    xs, zs = res["xs"], res["zs"]
    ix = np.clip(np.round((v.x - xs[0]) / (xs[1] - xs[0])).astype(int), 0, len(xs) - 1)
    iz = np.clip(np.round((v.z - zs[0]) / (zs[1] - zs[0])).astype(int), 0, len(zs) - 1)
    b = res["etiquetas"][np.ix_(iz, ix)]
    m = (a >= 0) & (b >= 0)
    assert np.mean(a[m] == b[m]) > 0.9


def test_cortes_y_caja_de_render(volumen):
    v = volumen
    iz, iy, ix = v.indice(0.0, 0.0, float(v.z[len(v.z) // 2]))
    c = v.cortes(iz, iy, ix)
    assert c["A"].shape == (len(v.z), len(v.x))
    assert c["B"].shape == (len(v.z), len(v.y))
    assert c["C"].shape == (len(v.y), len(v.x))
    # la caja de render empieza en el líquido que hay delante de la cara
    z0 = inicio_render(v)
    k = int(np.searchsorted(v.z, z0))
    col = v.etq[k, len(v.y) // 2, len(v.x) // 2]
    assert col == T["amniotico"]


def test_biplano_comparte_escala(escena):
    pose = plano_estandar(escena, "perfil")
    s = sonda_para(pose, geometria="matricial", n_lineas=64, dr_mm=0.3)
    r1 = simular(escena, pose, s, etiquetas=False)
    r2 = simular(escena, pose_biplano(pose), s, etiquetas=False,
                 normalizacion=r1["normalizacion"])
    assert r2["normalizacion"]["ref"] == pytest.approx(r1["normalizacion"]["ref"])
