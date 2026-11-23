"""
feto_parametrico — Feto humano paramétrico por edad gestacional, con órganos y
movimiento, dentro de un útero, y simulación de ecografía obstétrica modo B.

Módulos principales
-------------------
superficie     malla de superficie a partir de la biometría de Hadlock
feto3d         feto articulado con órganos + útero, placenta, cordón y pared materna
movimiento     posturas en función del tiempo (patadas, giros, respiración, latido)
ecografia      simulador modo B por rayos y convolución; planos estándar
sonda_control  estado de la sonda virtual; retroalimentación de planos
fuentes_sonda  entrada de una sonda física por UDP y emulador
tejidos        propiedades acústicas por tejido

Licencia: GPL-3.0-or-later
"""

__version__ = "0.1.0"

from .superficie import Proporciones, biometria, largo_pie, malla_fetal, medir  # noqa: F401
