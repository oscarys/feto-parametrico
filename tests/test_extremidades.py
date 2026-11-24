# -*- coding: utf-8 -*-
"""Pruebas de manos, pies, grandes vasos y los planos de corazón y miembros."""

import numpy as np
import pytest

from feto_parametrico.ecografia import plano_estandar, simular, sonda_para
from feto_parametrico.feto3d import Escena, Postura, construir_feto, sdf_piel
from feto_parametrico.tejidos import T


def _tramos_dentro(piezas, a, b, n=600):
    """Cuántos tramos separados de piel cruza el segmento a-b."""
    t = np.linspace(0, 1, n)[:, None]
    dentro = sdf_piel(piezas, (a + t * (b - a)).astype(np.float32)) < 0
    return int(np.sum(dentro[1:] & ~dentro[:-1]) + dentro[0])


def _dedos(f, nombre_mano):
    """Puntas de los dedos 2 a 5 de una mano."""
    return [next(p for p in f.piezas if p.nombre == f"dedo{k}_{nombre_mano}_1").p["a"]
            for k in range(2, 6)]


@pytest.mark.parametrize("eg", [18, 30])
def test_mano_abierta_tiene_cuatro_dedos_separados_y_pulgar(eg):
    f = construir_feto(eg, Postura(puno=(0.0, 0.0)))
    a, b = _dedos(f, "i")[0], _dedos(f, "i")[-1]
    d = (b - a) / np.linalg.norm(b - a)
    # una recta a la altura de la falange media, un poco más allá del índice y el meñique
    assert _tramos_dentro(f.piezas, a - 3 * d, b + 3 * d) == 4
    assert any(p.nombre.startswith("dedo1_i") for p in f.piezas)


@pytest.mark.parametrize("eg", [18, 30])
def test_pie_tiene_cinco_ortejos(eg):
    f = construir_feto(eg)
    bases = [next(p for p in f.piezas if p.nombre == f"ortejo{k}_i") for k in range(1, 6)]
    # recta por los ortejos, cerca de la punta (fuera de la planta)
    pts = [p.p["a"] + 0.75 * (p.p["b"] - p.p["a"]) for p in bases]
    d = (pts[-1] - pts[0]) / np.linalg.norm(pts[-1] - pts[0])
    assert _tramos_dentro(f.piezas, pts[0] - 4 * d, pts[-1] + 4 * d) == 5


def test_huesos_de_mano_y_pie():
    f = construir_feto(24)
    nombres = {o.nombre for o in f.organos if o.etiqueta == T["hueso"]}
    assert sum(n.startswith("metacarpiano") for n in nombres) == 10
    assert sum(n.startswith("metatarsiano") for n in nombres) == 10
    assert {"calcaneo_i", "calcaneo_d"} <= nombres
    assert sum(n.startswith("falange_dedo") for n in nombres) == 2 * (4 * 3 + 2)


@pytest.fixture(scope="module")
def escena():
    return Escena(24)


def _etiquetas(escena, plano):
    pose = plano_estandar(escena, plano)
    res = simular(escena, pose, sonda_para(pose, n_lineas=128, dr_mm=0.2), etiquetas="rapidas")
    return res["etiquetas"]


def test_tres_vasos_y_traquea(escena):
    lab = _etiquetas(escena, "tres_vasos")
    assert (lab == T["sangre"]).sum() > 50 and (lab == T["liquido"]).any()   # vasos, tráquea


def test_vejiga_con_arterias_umbilicales(escena):
    lab = _etiquetas(escena, "vejiga")
    assert (lab == T["liquido"]).sum() > 200 and (lab == T["sangre"]).any()


@pytest.mark.parametrize("plano", ["tsvi", "tsvd"])
def test_tractos_de_salida(escena, plano):
    lab = _etiquetas(escena, plano)
    assert (lab == T["miocardio"]).any() and (lab == T["sangre"]).sum() > 100


@pytest.mark.parametrize("plano", ["mano", "pie"])
def test_planos_de_mano_y_pie(escena, plano):
    lab = _etiquetas(escena, plano)
    assert (lab == T["hueso"]).sum() > 20
