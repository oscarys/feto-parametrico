#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visor.py — Visor interactivo (PyQt6 + pyvistaqt) del modelo fetal
paramétrico. Un deslizador recorre la edad gestacional de 12 a 40 semanas.

    feto-visor            # o: feto-visor 24

Dependencias: PyQt6, pyvista, pyvistaqt, numpy, scikit-image, trimesh

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import sys

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget,
                             QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QMainWindow, QPushButton, QSlider, QSpinBox,
                             QStatusBar, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QHeaderView)
from pyvistaqt import QtInteractor

from ..superficie import EG_MAX, EG_MIN
from ..i18n import N_, tr
from .comun import agregar_argumento, idioma_inicial, menu_idioma
from ..feto_pv import (a_pyvista, agregar_feto, agregar_organos, camara_lateral, generar,
                     organos_cuerpo)

PASOS_POR_SEMANA = 2          # resolución del deslizador: media semana


# ---------------------------------------------------------------------------
# Generación en segundo plano
# ---------------------------------------------------------------------------

class _Senales(QObject):
    listo = pyqtSignal(object, object)     # (clave, datos)
    error = pyqtSignal(object, str)


class _TrabajoOrganos(QRunnable):
    """Mallas de los órganos (no dependen de la resolución de la piel)."""
    def __init__(self, eg):
        super().__init__()
        self.eg = eg
        self.senales = _Senales()

    def run(self):
        try:
            self.senales.listo.emit(("organos", self.eg), organos_cuerpo(self.eg))
        except Exception as e:             # noqa: BLE001
            self.senales.error.emit(("organos", self.eg), str(e))


class _Trabajo(QRunnable):
    def __init__(self, eg, resolucion):
        super().__init__()
        self.clave = (eg, resolucion)
        self.senales = _Senales()

    def run(self):
        try:
            # sin VTK en este hilo: la malla PyVista se crea en el hilo de la interfaz
            self.senales.listo.emit(self.clave, generar(*self.clave, vtk=False))
        except Exception as e:             # noqa: BLE001 — se informa en la GUI
            self.senales.error.emit(self.clave, str(e))


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class VisorFeto(QMainWindow):
    def __init__(self, eg_inicial: float = 20.0):
        super().__init__()
        self.setWindowTitle(tr("Modelo fetal paramétrico"))
        self.resize(1400, 900)

        self.cache: dict[tuple, dict] = {}
        self.cache_org: dict[float, list] = {}   # órganos por EG
        # redibujado diferido: muchos cambios seguidos -> una sola reconstrucción
        self.t_redibujo = QTimer(self, singleShot=True, interval=40)
        self.t_redibujo.timeout.connect(self._redibujar)
        self.t_render = QTimer(self, singleShot=True, interval=15)
        self.t_render.timeout.connect(lambda: self.vista.render())
        self.pendiente: tuple | None = None   # última petición del usuario
        self.en_curso: set[tuple] = set()
        self.actual: dict | None = None
        self.radio_fijo = None                # escala de la cámara fija (40 sem)
        self.reproduciendo = False
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(2)

        # --- vista 3D
        self.vista = QtInteractor(self)
        self.vista.set_background("#f7f4ef", top="#d9d4cc")
        self.vista.enable_anti_aliasing("fxaa")
        self.vista.add_axes()
        self.setCentralWidget(self.vista.interactor)

        # --- panel de controles
        self._construir_panel()
        self._construir_menu()
        self.setStatusBar(QStatusBar())

        # deslizador con rebote: genera al soltar o tras 250 ms quieto
        self.temporizador = QTimer(self, singleShot=True, interval=250)
        self.temporizador.timeout.connect(self._solicitar)

        self.desl_eg.setValue(int(round(eg_inicial * PASOS_POR_SEMANA)))
        self._solicitar()
        # malla de 40 semanas a baja resolución para fijar la escala de la cámara
        self._lanzar(EG_MAX, 70)

    # ..................................................................... UI
    def _construir_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)

        # Edad gestacional
        caja = QGroupBox(tr("Edad gestacional"))
        f = QVBoxLayout(caja)
        self.lbl_eg = QLabel()
        self.lbl_eg.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.desl_eg = QSlider(Qt.Orientation.Horizontal)
        self.desl_eg.setRange(int(EG_MIN * PASOS_POR_SEMANA), int(EG_MAX * PASOS_POR_SEMANA))
        self.desl_eg.setTickInterval(4 * PASOS_POR_SEMANA)
        self.desl_eg.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.desl_eg.valueChanged.connect(self._eg_cambio)
        self.desl_eg.sliderReleased.connect(self._solicitar)
        fila = QHBoxLayout()
        self.btn_play = QPushButton(tr("▶ Reproducir 12→40"))
        self.btn_play.clicked.connect(self._alternar_reproduccion)
        fila.addWidget(self.btn_play)
        f.addWidget(self.lbl_eg); f.addWidget(self.desl_eg); f.addLayout(fila)
        lay.addWidget(caja)

        # Visualización
        caja = QGroupBox(tr("Visualización"))
        f = QFormLayout(caja)
        self.sp_res = QSpinBox(); self.sp_res.setRange(60, 280); self.sp_res.setSingleStep(20)
        self.sp_res.setValue(130); self.sp_res.setSuffix(tr(" vóxeles"))
        self.sp_res.setToolTip(tr("Vóxeles en el eje más largo. Más = más fino y más lento."))
        self.sp_res.editingFinished.connect(self._solicitar)
        self.cb_color = QComboBox(); self.cb_color.addItems([tr("Piel"), tr("Curvatura media")])
        self.cb_color.currentIndexChanged.connect(self._programar)
        self.desl_op = QSlider(Qt.Orientation.Horizontal); self.desl_op.setRange(10, 100)
        self.desl_op.setValue(100); self.desl_op.valueChanged.connect(self._opacidad)
        self.ch_bio = QCheckBox(tr("Biometría (CC, DBP, LF)"))
        self.ch_bio.toggled.connect(self._biometria_toggled)
        self.ch_org = QCheckBox(tr("Órganos internos"))
        self.ch_org.setToolTip(tr("Cráneo, encéfalo, ventrículos, corazón, pulmones, hígado, "
                               "estómago, riñones, vejiga, columna, costillas y huesos largos "
                               "(los mismos del simulador de ecografía)."))
        self.ch_org.toggled.connect(self._organos_toggled)
        self.ch_leyenda = QCheckBox(tr("Leyenda de colores"))
        self.ch_rotulos = QCheckBox(tr("Nombres de los órganos"))
        for c in (self.ch_leyenda, self.ch_rotulos):
            c.setEnabled(False)
            c.toggled.connect(self._programar)
        self.ch_leyenda.setChecked(True)
        self.ch_aristas = QCheckBox(tr("Aristas de la malla"))
        self.ch_aristas.toggled.connect(self._programar)
        self.ch_escala = QCheckBox(tr("Escala real (cámara fija)"))
        self.ch_escala.setChecked(True)
        self.ch_escala.setToolTip(tr("La cámara no se reencuadra al cambiar la edad: "
                                  "se aprecia el crecimiento."))
        self.ch_escala.toggled.connect(lambda _: self._encuadrar())
        self.ch_reglas = QCheckBox(tr("Reglas (mm)"))
        self.ch_reglas.toggled.connect(self._programar)
        f.addRow(tr("Resolución"), self.sp_res)
        f.addRow(tr("Color"), self.cb_color)
        f.addRow(tr("Opacidad"), self.desl_op)
        f.addRow(self.ch_org)
        sub = QWidget(); hl = QHBoxLayout(sub); hl.setContentsMargins(18, 0, 0, 0)
        hl.addWidget(self.ch_leyenda); hl.addWidget(self.ch_rotulos)
        f.addRow(sub)
        f.addRow(self.ch_bio); f.addRow(self.ch_aristas)
        f.addRow(self.ch_escala); f.addRow(self.ch_reglas)
        lay.addWidget(caja)

        # Leyenda de órganos (widget de Qt: legible y fuera de la vista 3D)
        self.caja_leyenda = QGroupBox(tr("Leyenda"))
        self.lbl_leyenda = QLabel()
        self.lbl_leyenda.setTextFormat(Qt.TextFormat.RichText)
        QVBoxLayout(self.caja_leyenda).addWidget(self.lbl_leyenda)
        self.caja_leyenda.setVisible(False)
        lay.addWidget(self.caja_leyenda)

        # Tabla de biometría
        caja = QGroupBox(tr("Biometría (Hadlock) y medidas de la malla"))
        v = QVBoxLayout(caja)
        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels([tr("Medida"), tr("Valor")])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        v.addWidget(self.tabla)
        lay.addWidget(caja, stretch=1)

        # Botones
        fila = QHBoxLayout()
        for texto, fn in [(N_("Exportar malla…"), self._exportar),
                          (N_("Captura…"), self._captura),
                          (N_("Reencuadrar"), self._reencuadrar)]:
            b = QPushButton(tr(texto)); b.clicked.connect(fn); fila.addWidget(b)
        lay.addLayout(fila)

        dock = QDockWidget(tr("Controles"), self)
        dock.setWidget(panel)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _construir_menu(self):
        m = self.menuBar().addMenu(tr("&Archivo"))
        for texto, atajo, fn in [(N_("Exportar malla…"), "Ctrl+E", self._exportar),
                                 (N_("Captura de pantalla…"), "Ctrl+S", self._captura),
                                 (N_("Salir"), "Ctrl+Q", self.close)]:
            a = QAction(tr(texto), self); a.setShortcut(QKeySequence(atajo))
            a.triggered.connect(fn); m.addAction(a)
        m = self.menuBar().addMenu(tr("&Vista"))
        for texto, az, el in [(N_("Lateral"), -90, 5), (N_("Frontal"), 0, 5),
                              (N_("Oblicua"), -40, 20), (N_("Posterior"), 180, 5)]:
            a = QAction(tr(texto), self)
            a.triggered.connect(lambda _, az=az, el=el: self._vista(az, el))
            m.addAction(a)
        menu_idioma(self, self._reconstruir)

    def _reconstruir(self):
        """Ventana nueva (otro idioma) con la misma edad y opciones principales."""
        w = VisorFeto(self._eg())
        w.ch_org.setChecked(self.ch_org.isChecked())
        w.ch_bio.setChecked(self.ch_bio.isChecked())
        w.show()
        return w

    # ............................................................ generación
    def _eg(self) -> float:
        return self.desl_eg.value() / PASOS_POR_SEMANA

    def _eg_cambio(self, _):
        self.lbl_eg.setText(tr("{eg:g} semanas", eg=self._eg()))
        if self.reproduciendo:
            return
        clave = (self._eg(), self.sp_res.value())
        if clave in self.cache:          # respuesta inmediata si ya existe
            self._mostrar(self.cache[clave])
        else:
            self.temporizador.start()

    def _solicitar(self):
        clave = (self._eg(), self.sp_res.value())
        self.pendiente = clave
        if clave in self.cache:
            self._mostrar(self.cache[clave])
            if self.reproduciendo:          # ya estaba en caché: avanzar sin esperar
                QTimer.singleShot(60, self._siguiente_cuadro)
        else:
            self._lanzar(*clave)

    def _lanzar(self, eg, res):
        clave = (eg, res)
        if clave in self.en_curso or clave in self.cache:
            return
        self.en_curso.add(clave)
        if clave == self.pendiente:
            self.statusBar().showMessage(tr("Generando {eg:g} semanas ({res} vóxeles)…", eg=eg, res=res))
        t = _Trabajo(eg, res)
        t.senales.listo.connect(self._recibido)
        t.senales.error.connect(self._fallo)
        self.pool.start(t)

    def _recibido(self, clave, datos):
        self.en_curso.discard(clave)
        if clave[0] == "organos":
            self.cache_org[clave[1]] = datos
            if self.actual is not None and self.actual["eg"] == clave[1]:
                self._programar()
            return
        if "pv" not in datos:
            datos["pv"] = a_pyvista(datos["trimesh"])     # VTK sólo en este hilo
        self.cache[clave] = datos
        if clave[0] == EG_MAX and self.radio_fijo is None:
            b = np.array(datos["pv"].bounds).reshape(3, 2)
            self.radio_fijo = 0.5 * (b[:, 1] - b[:, 0]).max()
            if self.actual is not None:
                self._encuadrar()
        if clave == self.pendiente:
            self._mostrar(datos)
            self.statusBar().showMessage(
                tr("{eg:g} semanas: {n} triángulos", eg=clave[0], n=datos["med"]["caras"]), 4000)
            if self.reproduciendo:
                QTimer.singleShot(40, self._siguiente_cuadro)

    def _fallo(self, clave, msg):
        self.en_curso.discard(clave)
        if clave[0] == "organos":
            self.statusBar().showMessage(tr("Error en los órganos ({eg:g} sem): {msg}", eg=clave[1], msg=msg))
            return
        self.statusBar().showMessage(tr("Error con {eg:g} semanas: {msg}", eg=clave[0], msg=msg))
        self.reproduciendo = False
        self.btn_play.setText(tr("▶ Reproducir 12→40"))

    # .............................................................. dibujo
    def _mostrar(self, datos):
        primera = self.actual is None
        self.actual = datos
        self._redibujar()
        self._llenar_tabla()
        if primera or not self.ch_escala.isChecked():
            self._encuadrar()

    def _llenar_leyenda(self, organos):
        from ..feto_pv import LEYENDA
        filas = []
        for n, _, color, _ in organos["mallas"]:
            hexa = "#%02x%02x%02x" % tuple(int(255 * c) for c in color)
            filas.append(f'<td><span style="color:{hexa}; font-size:15px;">&#9632;</span></td>'
                         f"<td>{tr(LEYENDA.get(n, n))}</td>")
        # dos columnas para no alargar el panel
        mitad = (len(filas) + 1) // 2
        html = "<table cellspacing='2'>"
        for a, b in zip(filas[:mitad], filas[mitad:] + [""]):
            html += f"<tr>{a}<td width='10'></td>{b}</tr>"
        self.lbl_leyenda.setText(html + "</table>")

    def _organos_toggled(self, activo):
        self.ch_leyenda.setEnabled(activo); self.ch_rotulos.setEnabled(activo)
        if activo and self.desl_op.value() > 40:
            self.desl_op.setValue(25)     # piel translúcida para ver el interior
        elif not activo and self.desl_op.value() == 25:
            self.desl_op.setValue(100)
        self._programar()

    def _pedir_organos(self, eg):
        if eg in self.cache_org or ("organos", eg) in self.en_curso:
            return
        self.en_curso.add(("organos", eg))
        t = _TrabajoOrganos(eg)
        t.senales.listo.connect(self._recibido)
        t.senales.error.connect(self._fallo)
        self.pool.start(t)

    def _biometria_toggled(self, activo):
        if activo and self.desl_op.value() == 100:
            self.desl_op.setValue(45)     # translúcido para ver el fémur
        self._programar()

    def _programar(self, *_):
        """Agrupa varios cambios seguidos en un solo redibujado."""
        self.t_redibujo.start()

    def _opacidad(self, valor):
        """Cambia la opacidad de la piel sin reconstruir la escena."""
        actor = self.vista.actors.get("feto")
        if actor is None:
            self._programar()
            return
        actor.prop.opacity = valor / 100
        self.t_render.start()

    def _redibujar(self, *_):
        if self.actual is None:
            return
        self.t_redibujo.stop()
        v = self.vista
        for nombre in list(v.actors):
            if nombre.startswith("feto") or nombre.startswith("regla"):
                v.remove_actor(nombre, render=False)
        v.remove_bounds_axes()
        if v.scalar_bars:
            v.remove_scalar_bar(render=False)
        self.caja_leyenda.setVisible(self.ch_org.isChecked() and self.ch_leyenda.isChecked())
        agregar_feto(v, self.actual,
                     opacidad=self.desl_op.value() / 100,
                     biometria=self.ch_bio.isChecked(),
                     aristas=self.ch_aristas.isChecked(),
                     escalar="curvatura" if self.cb_color.currentIndex() == 1 else None,
                     render=False)
        if self.ch_org.isChecked():
            eg = self.actual["eg"]
            if eg in self.cache_org:
                agregar_organos(v, self.actual, self.cache_org[eg],
                                rotulos=self.ch_rotulos.isChecked())
                self._llenar_leyenda(self.cache_org[eg])
            else:
                self._pedir_organos(eg)
                self.statusBar().showMessage(tr("Construyendo órganos ({eg:g} semanas)…", eg=eg), 3000)
        if self.ch_reglas.isChecked():
            v.show_bounds(grid=False, location="outer", ticks="outside",
                          xtitle="x (mm)", ytitle="y (mm)", ztitle="z (mm)",
                          font_size=10, color="#444444", render=False)
        v.add_text(tr("{eg:g} sem", eg=self.actual["eg"]), position="upper_left",
                   font_size=14, color="#222222", name="feto_titulo", render=False)
        v.render()

    def _llenar_tabla(self):
        i, m = self.actual["info"], self.actual["med"]
        filas = [(N_("DBP (Hadlock)"), f"{i['DBP']:.1f} mm"),
                 (N_("DBP en la malla (cráneo)"), f"{m['DBP_malla']:.1f} mm"),
                 (N_("CC (Hadlock)"), f"{i['CC']:.1f} mm"),
                 (N_("CC en la malla (cráneo)"), f"{m['CC_malla']:.1f} mm"),
                 (N_("CA (Hadlock)"), f"{i['CA']:.1f} mm"),
                 (N_("LF (Hadlock)"), f"{i['LF']:.1f} mm"),
                 (N_("Diámetro fronto-occipital"), f"{i['OFD']:.1f} mm"),
                 (N_("LCC aproximada"), f"{m['LCC_aprox']:.0f} mm"),
                 (N_("Volumen de la malla"), f"{m['volumen_cm3']:.1f} cm³"),
                 (N_("PFE (Hadlock 1985)"), f"{i['PFE_g']:.0f} g"),
                 (N_("Triángulos"), f"{m['caras']:,}"),
                 (N_("Hermética"), tr("sí") if m["hermetica"] else tr("no"))]
        self.tabla.setRowCount(len(filas))
        for r, (a, b) in enumerate(filas):
            self.tabla.setItem(r, 0, QTableWidgetItem(tr(a)))
            it = QTableWidgetItem(tr(b))
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tabla.setItem(r, 1, it)

    # .............................................................. cámara
    def _encuadrar(self):
        if self.actual is None:
            return
        if self.ch_escala.isChecked() and self.radio_fijo is not None:
            az = getattr(self, "_azimut", -70.0); el = getattr(self, "_elev", 12.0)
            camara_lateral(self.vista, self.radio_fijo, azimut=az, elevacion=el,
                           distancia=4.4)
        else:
            self.vista.reset_camera()
        self.vista.render()

    def _reencuadrar(self):
        self.vista.reset_camera(); self.vista.render()

    def _vista(self, az, el):
        self._azimut, self._elev = az, el
        if self.ch_escala.isChecked():
            self._encuadrar()
        else:
            r = 0.5 * max(np.ptp(np.array(self.actual["pv"].bounds).reshape(3, 2), axis=1))
            camara_lateral(self.vista, r, azimut=az, elevacion=el, distancia=3.0)
            self.vista.render()

    # ......................................................... reproducción
    def _alternar_reproduccion(self):
        self.reproduciendo = not self.reproduciendo
        self.btn_play.setText(tr("■ Detener") if self.reproduciendo else tr("▶ Reproducir 12→40"))
        if self.reproduciendo:
            if self._eg() >= EG_MAX:
                self.desl_eg.setValue(int(EG_MIN * PASOS_POR_SEMANA))
            self._solicitar()

    def _siguiente_cuadro(self):
        if not self.reproduciendo:
            return
        if self.desl_eg.value() >= self.desl_eg.maximum():
            self._alternar_reproduccion()
            return
        self.desl_eg.setValue(self.desl_eg.value() + 1)
        self._solicitar()

    # ............................................................ archivos
    def _exportar(self):
        if self.actual is None:
            return
        nombre, _ = QFileDialog.getSaveFileName(
            self, tr("Exportar malla"), f"feto_{self.actual['eg']:g}s.stl",
            tr("STL (*.stl);;Wavefront OBJ (*.obj);;PLY (*.ply);;VTK PolyData (*.vtp)"))
        if not nombre:
            return
        if nombre.lower().endswith(".vtp"):
            self.actual["pv"].save(nombre)
        else:
            self.actual["trimesh"].export(nombre)
        self.statusBar().showMessage(tr("Guardado: {archivo}", archivo=nombre), 5000)

    def _captura(self):
        nombre, _ = QFileDialog.getSaveFileName(self, tr("Guardar captura"),
                                                f"feto_{self._eg():g}s.png", tr("PNG (*.png)"))
        if nombre:
            self.vista.screenshot(nombre, scale=2)
            self.statusBar().showMessage(tr("Guardado: {archivo}", archivo=nombre), 5000)

    def closeEvent(self, ev):
        self.reproduciendo = False
        self.pool.waitForDone(5000)
        self.vista.close()
        super().closeEvent(ev)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Visor del modelo fetal paramétrico / parametric fetus viewer")
    ap.add_argument("eg", type=float, nargs="?", default=20.0,
                    help="edad gestacional en semanas / gestational age in weeks")
    agregar_argumento(ap)
    a = ap.parse_args(argv)
    # Depuración: `kill -USR1 <pid>` imprime la pila de todos los hilos en la terminal
    import faulthandler, signal
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    app = QApplication(sys.argv[:1])
    idioma_inicial(a.idioma)
    w = VisorFeto(a.eg)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
