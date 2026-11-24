# -*- coding: utf-8 -*-
"""Pruebas del simulador de ecografía, de la sonda y de la separación NumPy/VTK."""

import subprocess
import sys
import textwrap

import numpy as np
import pytest

from feto_parametrico.ecografia import (GEOMETRIAS, PLANOS, Adquisicion, Sonda, haz_a_plano,
                                        medir_en_imagen, plano_a_haz, plano_estandar, simular,
                                        sonda_para, sonda_tipo)
from feto_parametrico.feto3d import Escena
from feto_parametrico.movimiento import Movimiento
from feto_parametrico.sonda_control import EstadoSonda, errores_planos
from feto_parametrico.tejidos import T


@pytest.fixture(scope="module")
def escena():
    return Escena(22)


def test_planos_estandar_tienen_pose(escena):
    for nom in PLANOS:
        pose = plano_estandar(escena, nom)
        assert pose.info["profundidad_objetivo"] > 0
        assert abs(float(pose.ex @ pose.ez)) < 1e-6


def test_cc_medida_en_imagen_transtalamica(escena):
    pose = plano_estandar(escena, "transtalamico")
    res = simular(escena, pose, sonda_para(pose, n_lineas=128, dr_mm=0.2))
    b = res["bmodo"][res["dentro"]]
    assert 0.0 <= b.min() and b.max() <= 1.0
    med = medir_en_imagen(res, "transtalamico", 0.3, pose)
    assert med["CC"] == pytest.approx(escena.feto.bio["CC"], rel=0.03)


def test_liquido_amniotico_oscuro(escena):
    pose = plano_estandar(escena, "sagital")
    res = simular(escena, pose, sonda_para(pose, n_lineas=128, dr_mm=0.2))
    liq = res["bmodo"][res["etiquetas"] == T["amniotico"]]
    fet = res["bmodo"][res["etiquetas"] == T["fetal"]]
    assert np.median(liq) < 0.25 < np.median(fet)


@pytest.mark.parametrize("geometria", GEOMETRIAS)
def test_geometria_ida_y_vuelta(geometria):
    s = sonda_tipo(geometria)
    rng = np.random.default_rng(0)
    U = rng.uniform(-0.6, 0.6, 50) * (s.ancho_mm if s.es_lineal else 1.0)
    D = rng.uniform(0, s.profundidad_mm, 50)
    U2, D2 = plano_a_haz(s, *haz_a_plano(s, U, D))
    assert np.allclose(U, U2) and np.allclose(D, D2)


def test_sonda_lineal_imagen_rectangular():
    esc = Escena(16)
    pose = plano_estandar(esc, "transtalamico")
    s = sonda_para(pose, geometria="lineal", n_lineas=128, dr_mm=0.1)
    assert s.f0_mhz > 5 and s.profundidad_mm <= 120
    res = simular(esc, pose, s, Adquisicion(px_salida_mm=0.2), etiquetas="rapidas")
    assert res["dentro"].mean() > 0.97                     # sin esquinas vacías
    assert res["xs"][-1] - res["xs"][0] == pytest.approx(s.ancho_mm, abs=0.5)
    # el cráneo del feto de 16 semanas queda al alcance de la lineal
    assert (res["etiquetas"] == T["hueso"]).any()


def test_tgc_limitada_no_satura_con_ruido(escena):
    # objetivo profundo con sonda lineal: lo superficial no queda negro bajo ruido amplificado
    pose = plano_estandar(escena, "femur")
    res = simular(escena, pose, sonda_para(pose, geometria="lineal", n_lineas=96, dr_mm=0.2),
                  etiquetas=False)
    b = res["bmodo"]
    assert np.median(b[: b.shape[0] // 4]) > np.median(b[-b.shape[0] // 4:])


def test_etiquetas_rapidas_coinciden_en_su_mayoria(escena):
    pose = plano_estandar(escena, "abdominal")
    s = sonda_para(pose, n_lineas=128, dr_mm=0.2)
    exactas = simular(escena, pose, s)["etiquetas"]
    rapidas = simular(escena, pose, s, etiquetas="rapidas")["etiquetas"]
    m = exactas >= 0
    assert np.mean(exactas[m] == rapidas[m]) > 0.95


def test_sonda_en_plano_estandar_da_error_cero(escena):
    est = EstadoSonda()
    est.desde_pose(plano_estandar(escena, "cuatro_camaras"))
    err = errores_planos(escena, est.pose(escena))
    ang, dist = err["cuatro_camaras"]
    assert ang < 1.0 and dist < 1.0


def test_movimiento_produce_posturas_distintas():
    mov = Movimiento(semilla=0)
    a, b = mov.en(0.0), mov.en(1.3)
    assert a.cadera != b.cadera and 0.0 <= b.fase_card < 1.0


def test_rutas_de_hilos_de_trabajo_no_cargan_vtk():
    """Los hilos de trabajo de los visores sólo deben usar NumPy (VTK no es
    seguro entre hilos). Estas rutas no deben ni siquiera importar VTK."""
    codigo = textwrap.dedent("""
        import sys
        from feto_parametrico.feto3d import Escena
        from feto_parametrico.vista3d import mallas_escena_np
        from feto_parametrico.feto_pv import generar, organos_cuerpo
        from feto_parametrico.ecografia import plano_estandar, simular, sonda_para
        esc = Escena(20)
        mallas_escena_np(esc, 50, placenta=False, utero=True)
        generar(20, 50, vtk=False)
        organos_cuerpo(20)
        p = plano_estandar(esc, "femur")
        simular(esc, p, sonda_para(p, n_lineas=64, dr_mm=0.3), etiquetas="rapidas")
        cargados = [m for m in sys.modules if m.startswith(("vtk", "pyvista"))]
        print("VTK:", cargados)
        sys.exit(1 if cargados else 0)
    """)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.vtk
def test_conversion_a_pyvista():
    pv = pytest.importorskip("pyvista")
    from feto_parametrico.vista3d import mallas_escena
    mallas = mallas_escena(Escena(20), 50, placenta=False)
    assert all(isinstance(m, pv.PolyData) and m.n_points > 0 for _, m, _, _ in mallas)
