#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cadenas_i18n.py — Extrae los textos traducibles del código (llamadas tr("...") y
N_("...") con un literal) y los compara con los catálogos de traducciones.

    python scripts/cadenas_i18n.py                 # informe: faltantes y sobrantes por idioma
    python scripts/cadenas_i18n.py --actualizar    # agrega las claves faltantes (vacías) a cada catálogo

Las claves vacías se muestran en español hasta que alguien las traduzca. Las
sobrantes (textos que ya no existen en el código) sólo se informan.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PAQUETE = RAIZ / "src" / "feto_parametrico"
TRADUCCIONES = PAQUETE / "traducciones"


def textos_del_codigo(paquete: Path = PAQUETE) -> dict[str, list[str]]:
    """{texto: [archivo:línea, ...]} para cada tr("...") / N_("...") literal."""
    out: dict[str, list[str]] = {}
    for f in sorted(paquete.rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in ("tr", "N_") and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                out.setdefault(n.args[0].value, []).append(f"{f.relative_to(RAIZ)}:{n.lineno}")
    return out


def catalogos() -> dict[str, Path]:
    return {p.stem: p for p in sorted(TRADUCCIONES.glob("*.json"))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--actualizar", action="store_true")
    a = ap.parse_args(argv)
    textos = textos_del_codigo()
    print(f"{len(textos)} textos traducibles en el código")
    incompleto = False
    for cod, ruta in catalogos().items():
        cat = json.loads(ruta.read_text(encoding="utf-8"))
        claves = {k for k in cat if not k.startswith("_")}
        faltan = sorted(set(textos) - claves)
        vacias = sorted(k for k in claves & set(textos) if not cat[k])
        sobran = sorted(claves - set(textos))
        print(f"\n[{cod}] faltan {len(faltan)}, sin traducir {len(vacias)}, sobran {len(sobran)}")
        for k in faltan:
            print(f"  + {k!r}   ({textos[k][0]})")
        for k in vacias:
            print(f"  ? {k!r}")
        for k in sobran:
            print(f"  - {k!r}")
        incompleto |= bool(faltan or vacias)
        if a.actualizar and faltan:
            for k in faltan:
                cat[k] = ""
            orden = {k: cat[k] for k in cat if k.startswith("_")}
            orden.update({k: cat[k] for k in sorted(k for k in cat if not k.startswith("_"))})
            ruta.write_text(json.dumps(orden, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  -> {len(faltan)} claves agregadas a {ruta.name}")
    return 1 if incompleto else 0


if __name__ == "__main__":
    sys.exit(main())
