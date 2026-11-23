# Capturas de pantalla de feto-visor y feto-escaner para la documentación.
# Uso: xvfb-run -a -s "-screen 0 1600x950x24" python scripts/capturas_apps.py visor|escaner [es|en]
# Con "en" la interfaz está en inglés y los archivos terminan en _en.png.
# Licencia: GPL-3.0-or-later
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv[:1])
modo = sys.argv[1]
lengua = sys.argv[2] if len(sys.argv) > 2 else "es"
sufijo = "" if lengua == "es" else f"_{lengua}"
from feto_parametrico.i18n import fijar_idioma
fijar_idioma(lengua)


def foto(nombre):
    app.primaryScreen().grabWindow(0).save(nombre)
    print("guardada", nombre, flush=True)


if modo == "visor":
    from feto_parametrico.apps.visor import VisorFeto
    w = VisorFeto(34)
    w.show()

    def organos():
        w.ch_escala.setChecked(False)
        w.ch_org.setChecked(True)

    def nombres():
        w.ch_rotulos.setChecked(True)
        w._vista(-40, 15)

    pasos = [(8000, organos), (12000, nombres), (14000, lambda: foto(f"salidas/captura_visor{sufijo}.png")),
             (14500, app.quit)]
else:
    from feto_parametrico.apps.escaner import Escaner
    w = Escaner(22)
    w.show()

    def cuatro_camaras():
        w.cb_plano.setCurrentIndex(1)
        w._ir_plano()
        w.ch_etq.setChecked(False)

    def etiquetas():
        w.ch_etq.setChecked(True)

    pasos = [(10000, cuatro_camaras), (14000, lambda: foto(f"salidas/captura_escaner{sufijo}.png")),
             (14500, etiquetas), (17000, lambda: foto(f"salidas/captura_escaner_etiquetas{sufijo}.png")),
             (17500, app.quit)]

for t, f in pasos:
    QTimer.singleShot(t, f)
app.exec()
