# -*- coding: utf-8 -*-
"""
python -m feto_parametrico — Lista las aplicaciones y comandos disponibles, con la
forma de ejecutarlos con y sin instalar el paquete.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse

from .i18n import N_, agregar_idioma, fijar_idioma, tr

COMANDOS = [
    ("feto-visor", "apps.visor", N_("visor 3D con deslizador de edad gestacional, órganos y biometría")),
    ("feto-escaner", "apps.escaner", N_("simulador de exploración: sonda sobre el abdomen y ecografía en vivo")),
    ("feto-malla", "superficie", N_("malla de superficie (STL/OBJ/PLY)")),
    ("feto-eco", "cli.demo_ecografia", N_("planos estándar, cines, video 3D+eco y lotes para entrenamiento")),
    ("feto-render", "cli.render_pyvista", N_("figuras con PyVista: serie, biometría, órganos, giros")),
    ("feto-animacion", "cli.animacion3d", N_("video 3D del feto moviéndose en el útero")),
    ("feto-vista-previa", "cli.vista_previa", N_("vista previa rápida sólo con matplotlib")),
    ("feto-sonda-emulador", "fuentes_sonda", N_("emulador de sonda física por UDP")),
]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m feto_parametrico", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    agregar_idioma(ap)
    fijar_idioma(ap.parse_args(argv).idioma)
    print(tr("Comandos (instalados con pip install -e .):"))
    for cmd, _, desc in COMANDOS:
        print(f"  {cmd:21s} {tr(desc)}")
    print()
    print(tr("Sin instalar, desde la carpeta del repositorio:"))
    for cmd, mod, _ in COMANDOS:
        print(f"  PYTHONPATH=src python -m feto_parametrico.{mod}")
    print()
    print(tr("Cada comando acepta --help e --idioma es|en."))


if __name__ == "__main__":
    main()
