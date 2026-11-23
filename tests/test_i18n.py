# -*- coding: utf-8 -*-
"""Pruebas del esquema de traducción de las aplicaciones."""

import importlib.util
import json
import string
from pathlib import Path

import pytest

from feto_parametrico import i18n

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cadenas_i18n", RAIZ / "scripts" / "cadenas_i18n.py")
cadenas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cadenas)


def _campos(texto):
    return sorted(f for _, f, _, _ in string.Formatter().parse(texto) if f)


@pytest.fixture(autouse=True)
def _restaurar_idioma():
    yield
    i18n.fijar_idioma("es")


@pytest.mark.parametrize("codigo", [c for c in i18n.IDIOMAS if c != i18n.ORIGEN])
def test_catalogo_completo_y_sin_sobrantes(codigo):
    textos = cadenas.textos_del_codigo()
    cat = json.loads((cadenas.TRADUCCIONES / f"{codigo}.json").read_text(encoding="utf-8"))
    claves = {k for k in cat if not k.startswith("_")}
    assert not set(textos) - claves, f"faltan en {codigo}.json (scripts/cadenas_i18n.py --actualizar)"
    assert not [k for k in claves if not cat[k]], f"claves sin traducir en {codigo}.json"
    assert not claves - set(textos), f"claves que ya no están en el código en {codigo}.json"


@pytest.mark.parametrize("codigo", [c for c in i18n.IDIOMAS if c != i18n.ORIGEN])
def test_traducciones_conservan_los_campos(codigo):
    cat = i18n.cargar_catalogo(codigo)
    malos = {k: v for k, v in cat.items() if _campos(k) != _campos(v)}
    assert not malos, f"campos distintos: {malos}"


def test_tr_traduce_formatea_y_recurre_al_espanol():
    i18n.fijar_idioma("en")
    assert i18n.tr("Edad gestacional") == "Gestational age"
    assert i18n.tr("{eg:g} semanas", eg=22.5) == "22.5 weeks"
    assert i18n.tr("texto que no existe") == "texto que no existe"
    i18n.fijar_idioma("es")
    assert i18n.tr("{eg:g} semanas", eg=22) == "22 semanas"


def test_idioma_desde_el_entorno(monkeypatch):
    for v in ("FETO_IDIOMA", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.idioma_sistema() == "en"
    monkeypatch.setenv("FETO_IDIOMA", "es")
    assert i18n.idioma_sistema() == "es"
    monkeypatch.setenv("FETO_IDIOMA", "xx")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert i18n.idioma_sistema() == "es"
    assert i18n.fijar_idioma("xx") == "es"


def test_n_no_traduce():
    i18n.fijar_idioma("en")
    assert i18n.N_("Edad gestacional") == "Edad gestacional"
