# -*- coding: utf-8 -*-
"""Pruebas de la cara y la fosa posterior: nomogramas, geometría y medidas en la imagen."""

import numpy as np
import pytest

from feto_parametrico.cabeza import cisterna_magna, dtc, hueso_nasal
from feto_parametrico.ecografia import (Adquisicion, medir_en_imagen, plano_estandar, simular,
                                        sonda_para)
from feto_parametrico.feto3d import Escena, construir_feto, sdf_piel
from feto_parametrico.tejidos import T


def test_nomogramas():
    # DTC ~ 1 mm por semana a mitad de la gestación; hueso nasal 5.7 mm a las 18 semanas
    assert dtc(22) == pytest.approx(23.6, abs=0.2)
    assert hueso_nasal(18) == pytest.approx(5.7, abs=0.2)
    assert hueso_nasal(23) == pytest.approx(7.6, abs=0.2)
    assert 2 <= cisterna_magna(16) < cisterna_magna(36) <= 10


@pytest.mark.parametrize("eg", [16, 24, 34])
def test_cerebelo_mide_el_dtc(eg):
    f = construir_feto(eg)
    hem = [o for o in f.organos if o.nombre.startswith("hemisferio_cerebeloso")]
    lat = f.marcos["cabeza"][1][:, 1]                    # eje lateral de la cabeza
    extremos = [float((o.centro - f.marcos["cabeza"][0]) @ lat) for o in hem]
    ancho = max(extremos) - min(extremos) + 2 * hem[0].p["semiejes"][1]
    assert ancho == pytest.approx(dtc(eg), rel=0.01)


def test_cara_sobresale_y_boca_abierta():
    f = construir_feto(22)
    p, R = f.marcos["cabeza"]
    a, b, c = f.bio["semiejes_cabeza"]
    H = lambda x, z: (p + x * a * R[:, 0] + z * c * R[:, 2])[None].astype(np.float32)  # noqa: E731
    # la punta de la nariz y los labios están dentro de la piel...
    assert sdf_piel(f.piezas, H(1.00, -0.39))[0] < 0
    assert sdf_piel(f.piezas, H(0.97, -0.53))[0] < 0
    # ...y la comisura de la boca (entre los labios) queda fuera: hay hendidura
    assert sdf_piel(f.piezas, H(0.99, -0.585))[0] > 0


@pytest.fixture(scope="module")
def escena():
    return Escena(22)


def _medir(escena, plano):
    pose = plano_estandar(escena, plano)
    res = simular(escena, pose, sonda_para(pose, n_lineas=192, dr_mm=0.15),
                  Adquisicion(px_salida_mm=0.2))
    return medir_en_imagen(res, plano, 0.2, pose), res


def test_transcerebelar_dtc_y_cisterna(escena):
    med, res = _medir(escena, "transcerebelar")
    assert med["DTC"] == pytest.approx(escena.feto.bio["DTC"], rel=0.05)
    assert med["CM"] == pytest.approx(escena.feto.bio["CM"], abs=1.0)
    assert (res["etiquetas"] == T["vermis"]).any()


def test_perfil_hueso_nasal(escena):
    med, _ = _medir(escena, "perfil")
    assert med["HN"] == pytest.approx(escena.feto.bio["HN"], rel=0.10)


def test_nariz_labios_corta_la_cara(escena):
    _, res = _medir(escena, "nariz_labios")
    lab = res["etiquetas"]
    assert (lab == T["fetal"]).any() and (lab == T["amniotico"]).any()
