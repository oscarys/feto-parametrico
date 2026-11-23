# -*- coding: utf-8 -*-
"""
comun.py — Idioma de las aplicaciones: opción --idioma, elección guardada y menú
"Idioma / Language" que reconstruye la ventana en el idioma elegido.

Orden de prioridad: --idioma > elección guardada en el menú > FETO_IDIOMA >
configuración regional del sistema > español.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction, QActionGroup

from ..i18n import IDIOMAS, fijar_idioma, idioma

_ventanas = []          # referencias vivas a las ventanas reconstruidas


def _ajustes():
    return QSettings("feto-parametrico", "aplicaciones")


def agregar_argumento(ap):
    ap.add_argument("--idioma", choices=sorted(IDIOMAS),
                    help="idioma de la interfaz / interface language (es, en)")


def idioma_inicial(desde_linea_de_comandos: str | None) -> str:
    guardado = _ajustes().value("idioma", None)
    return fijar_idioma(desde_linea_de_comandos or guardado or None)


def menu_idioma(ventana, reconstruir):
    """Agrega el menú de idioma. `reconstruir()` debe crear y mostrar una ventana
    nueva equivalente (con el idioma ya activo) y devolverla."""
    m = ventana.menuBar().addMenu("Idioma / Language")
    grupo = QActionGroup(m)
    for cod, nombre in IDIOMAS.items():
        a = QAction(nombre, m, checkable=True)
        a.setChecked(cod == idioma())
        a.triggered.connect(lambda _, c=cod: _cambiar(ventana, reconstruir, c))
        grupo.addAction(a)
        m.addAction(a)
    return m


def _cambiar(ventana, reconstruir, codigo):
    if codigo == idioma():
        return
    _ajustes().setValue("idioma", codigo)
    fijar_idioma(codigo)
    nueva = reconstruir()
    nueva.setGeometry(ventana.geometry())
    _ventanas.append(nueva)
    ventana.close()
    if ventana in _ventanas:
        _ventanas.remove(ventana)
