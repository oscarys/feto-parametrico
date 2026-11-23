# -*- coding: utf-8 -*-
"""
i18n.py — Traducción mínima, sin dependencias, para las aplicaciones.

Esquema
-------
* El texto fuente está en español y **es la clave** (como el msgid de gettext):
  en el código se escribe ``tr("Edad gestacional")``.
* Cada idioma tiene un catálogo JSON en ``feto_parametrico/traducciones/<código>.json``
  que asocia el texto en español con su traducción. Si falta una entrada se muestra
  el texto en español, así que la aplicación nunca se rompe por una traducción.
* Los textos que viven en tablas (menús, nombres de planos, leyenda) se marcan con
  ``N_("...")``, que no traduce nada pero permite extraerlos; se traducen al mostrarse.
* Los textos con valores usan campos con nombre del formato de Python:
  ``tr("{eg:g} semanas", eg=22)`` → "22 weeks". La traducción conserva los campos.
* El idioma se elige, en este orden: ``fijar_idioma()`` (opción ``--idioma`` o menú de
  la aplicación), la variable de entorno ``FETO_IDIOMA``, la configuración regional del
  sistema (``LC_ALL``, ``LC_MESSAGES``, ``LANG``) y, si nada coincide, español.

Para agregar un idioma: copiar ``traducciones/en.json`` a ``<código>.json``, traducir
los valores y añadir el código a ``IDIOMAS``. ``scripts/cadenas_i18n.py`` lista los
textos nuevos o faltantes, y una prueba verifica que el inglés esté completo.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import json
import os
from importlib import resources

IDIOMAS = {"es": "Español", "en": "English"}
ORIGEN = "es"                     # idioma del texto fuente

_idioma: str | None = None
_catalogo: dict[str, str] = {}


def idioma_sistema() -> str:
    """Código de idioma según FETO_IDIOMA o la configuración regional."""
    for var in ("FETO_IDIOMA", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        cod = v.split("_")[0].split(".")[0].lower()
        if cod in IDIOMAS:
            return cod
    return ORIGEN


def cargar_catalogo(codigo: str) -> dict[str, str]:
    if codigo == ORIGEN:
        return {}
    archivo = resources.files("feto_parametrico") / "traducciones" / f"{codigo}.json"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    return {k: v for k, v in datos.items() if v and not k.startswith("_")}


def fijar_idioma(codigo: str | None = None) -> str:
    """Activa un idioma (None = el del sistema). Devuelve el código activo."""
    global _idioma, _catalogo
    codigo = (codigo or idioma_sistema()).lower()
    if codigo not in IDIOMAS:
        codigo = ORIGEN
    _catalogo = cargar_catalogo(codigo)
    _idioma = codigo
    return codigo


def idioma() -> str:
    if _idioma is None:
        fijar_idioma()
    return _idioma


def agregar_idioma(ap) -> None:
    """Agrega --idioma a un argparse.ArgumentParser (comandos de línea)."""
    ap.add_argument("--idioma", choices=sorted(IDIOMAS),
                    help="idioma del texto en figuras y videos / language of figure text (es, en)")


def N_(texto: str) -> str:
    """Marca un texto para traducción sin traducirlo todavía (para tablas que se
    definen al importar y se traducen al mostrarse con ``tr(variable)``)."""
    return texto


def tr(texto: str, **campos) -> str:
    """Traduce `texto` al idioma activo y rellena los campos con nombre."""
    if _idioma is None:
        fijar_idioma()
    t = _catalogo.get(texto, texto)
    return t.format(**campos) if campos else t
