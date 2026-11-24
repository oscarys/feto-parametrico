# -*- coding: utf-8 -*-
"""Pruebas del modelo: biometría, malla de superficie, anatomía 3D y escena."""

import math

import numpy as np
import pytest

from feto_parametrico import biometria, largo_pie, malla_fetal, medir
from feto_parametrico.feto3d import Escena, construir_feto, sdf_piel
from feto_parametrico.tejidos import T
from feto_parametrico.vista3d import _malla_prim_np


# Tabla de Hadlock et al. (Radiology 1984, doi:10.1148/radiology.152.2.6739822): valores medios en cm
@pytest.mark.parametrize("eg, dbp, cc", [(12, 1.7, 6.8), (20, 4.6, 17.7), (40, 9.4, 34.6)])
def test_biometria_hadlock(eg, dbp, cc):
    b = biometria(eg)
    assert b["DBP"] / 10 == pytest.approx(dbp, abs=0.1)
    assert b["CC"] / 10 == pytest.approx(cc, abs=0.15)


@pytest.mark.parametrize("eg", [16, 24, 32, 40])
def test_razon_femur_pie(eg):
    lf = biometria(eg)["LF"]
    assert lf / largo_pie(eg, lf) == pytest.approx(1.0, abs=1e-6)


def test_pie_a_termino_como_recien_nacido():
    # Pie del recién nacido a término: ~73-80 mm (doi:10.4314/gmj.v57i3.11)
    assert 70 <= largo_pie(40, biometria(40)["LF"]) <= 82


def test_pie_del_modelo_3d_mide_lo_esperado():
    for eg in (16, 30, 40):
        f = construir_feto(eg)
        pie = next(p for p in f.piezas if p.nombre == "pie_i")
        largo = np.linalg.norm(pie.p["b"] - pie.p["a"]) + pie.p["ra"] + pie.p["rb"]
        assert largo == pytest.approx(largo_pie(eg, f.bio["LF"]), rel=1e-6)


@pytest.mark.parametrize("eg", [14, 28])
def test_malla_superficie_hermetica_y_cc(eg):
    malla, info = malla_fetal(eg, 90, devolver_info=True)
    assert malla.is_watertight
    m = medir(malla, info)
    assert m["CC_malla"] == pytest.approx(info["CC"], rel=0.03)
    assert m["DBP_malla"] == pytest.approx(info["DBP"], rel=0.04)


def test_malla_fina_sin_triangulos_sueltos():
    """A resolución fina marching cubes dejaba triángulos sueltos junto a las orejas
    (malla no hermética y CC inflada); se conserva sólo la pieza conexa mayor."""
    malla, info = malla_fetal(40, 180, devolver_info=True)
    assert malla.is_watertight and len(malla.split(only_watertight=False)) == 1
    assert medir(malla, info)["CC_malla"] == pytest.approx(info["CC"], rel=0.02)


def _sdf_cuerpo(piezas, P):
    return sdf_piel(piezas, P)


@pytest.mark.parametrize("eg", [14, 22, 30, 39])
def test_organos_dentro_del_cuerpo(eg):
    """Ningún órgano (columna incluida) sobresale de la piel."""
    f = construir_feto(eg)
    peor = {}
    for o in f.organos:
        V, _ = _malla_prim_np(o)
        d = float(_sdf_cuerpo(f.piezas, V.astype(np.float32)).max())
        if d > 0.3:
            peor[o.nombre] = round(d, 2)
    assert not peor, f"órganos fuera de la piel (mm): {peor}"


def test_escena_etiquetas_basicas():
    esc = Escena(22)
    c_cor = esc.a_mundo(esc.feto.marcos["corazon"][0])
    etq, _, _ = esc.evaluar(np.array([c_cor, [0.0, 0.0, 0.0], [0.0, 0.0, 10 * esc.abd[2]]]))
    assert etq[0] in (T["miocardio"], T["sangre"])
    assert etq[2] == T["gel"]                     # fuera del abdomen


def test_moteado_anclado_es_determinista():
    from feto_parametrico.ecografia import moteado_anclado
    L = np.random.default_rng(0).normal(size=(500, 3)) * 10
    pieza = np.full(500, 7)
    a = moteado_anclado(L, pieza, 0.1)
    b = moteado_anclado(L, pieza, 0.1)
    assert np.array_equal(a, b)
    assert abs(np.mean(np.abs(a) ** 2) - 1.0) < 0.2     # Rayleigh con potencia media 1
    assert math.isfinite(float(np.abs(a).max()))
