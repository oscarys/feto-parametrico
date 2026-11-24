#!/usr/bin/env bash
# Regenera las imágenes y animaciones de docs/img con los comandos instalados, en
# español (nombre.png) y en inglés (nombre_en.png), salvo las que no llevan texto.
# Requiere: pip install -e ".[todo]" y xvfb-run (sólo para las capturas de las apps).
# Tarda unos 30 minutos.
# Uso: scripts/medios_docs.sh [es|en|todos]   (por omisión: todos)
# Licencia: GPL-3.0-or-later
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p salidas
export PYVISTA_OFF_SCREEN=true
LENGUAS=${1:-todos}
[ "$LENGUAS" = todos ] && LENGUAS="es en"

for L in $LENGUAS; do
  S=""; [ "$L" = es ] || S="_$L"
  (
    cd salidas
    feto-vista-previa 12 20 28 36 40 -o "vista_previa$S.png" --idioma "$L"
    feto-render serie 12 20 28 36 40 -r 140 -o "serie_crecimiento$S.png" --idioma "$L"
    feto-render biometria 24 -o "biometria_24s$S.png" --idioma "$L"
    feto-render organos 22 -o "organos_utero_22s$S.png" --idioma "$L"
    feto-eco planos --eg 22 -o "planos_estandar_22s$S.png" --idioma "$L"
    feto-eco sondas -o "sondas_16s$S.png" --idioma "$L"
    feto-eco cabeza --eg 22 -o "planos_cabeza_22s$S.png" --idioma "$L"
    feto-render cara 16 24 32 -o "cara$S.png" --idioma "$L"
    feto-animacion --duracion 6 --fps 12 -o "movimiento_22s$S.mp4" --idioma "$L"
    feto-eco combinado --eg 22 -o "combinado_sagital_22s$S.mp4" --idioma "$L"
    python ../scripts/a_gif.py "combinado_sagital_22s$S.mp4" "combinado$S.gif" 960
    python ../scripts/a_gif.py "movimiento_22s$S.mp4" "movimiento$S.gif" 560
    if [ "$L" = es ]; then            # sin texto: una sola versión
      feto-render organos 22 --sin-utero -o organos_22s.png
      feto-eco latido --eg 22
      python ../scripts/a_gif.py latido_4c_22s.mp4 latido.gif 360
    fi
  )
  xvfb-run -a -s "-screen 0 1500x900x24" python scripts/capturas_apps.py visor "$L"
  xvfb-run -a -s "-screen 0 1600x950x24" python scripts/capturas_apps.py escaner "$L"
done

python - <<'PY'
from pathlib import Path
from PIL import Image
anchos = {"planos_estandar_22s": 1800, "sondas_16s": 1440, "planos_cabeza_22s": 1300, "cara": 1400, "organos_utero_22s": 1200, "organos_22s": 1100,
          "serie_crecimiento": 1600, "biometria_24s": 1100, "vista_previa": 1400,
          "captura_visor": 1500, "captura_escaner": 1600, "captura_escaner_etiquetas": 1600}
for base, ancho in anchos.items():
    for origen in Path("salidas").glob(base + "*.png"):
        im = Image.open(origen).convert("RGB")
        if im.width > ancho:
            im = im.resize((ancho, round(im.height * ancho / im.width)), Image.LANCZOS)
        # FASTOCTREE conserva los colores pequeños y saturados (anillo de la CC, leyendas)
        im.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(
            Path("docs/img") / origen.name, optimize=True)
PY
cp salidas/*.gif docs/img/
echo "Listo: docs/img actualizado"
