# -*- coding: utf-8 -*-
"""
ventana_volumen.py — Ventana del volumen de la sonda matricial: render de superficie
3D y los tres cortes ortogonales (MPR) con un punto de cruce que se mueve con
deslizadores o con un clic sobre cualquier corte.

Se abre desde feto-escaner con la sonda matricial (botón «Adquirir volumen», tecla V).

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                             QLabel, QMainWindow, QPushButton, QSizePolicy, QSlider,
                             QVBoxLayout, QWidget)
from pyvistaqt import QtInteractor

from ..i18n import tr
from ..tejidos import COLORES, T
from ..volumen import Volumen, agregar_render, camara_desde_sonda, inicio_render


class Corte(QLabel):
    """Un corte del volumen con su punto de cruce; un clic mueve el cruce."""
    clic = pyqtSignal(float, float)          # coordenadas (h, v) en mm del corte

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self.titulo = titulo
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: black;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(260, 220)
        self._pix = None
        self._geom = None                      # (ejes h, ejes v, rect de la imagen)

    def mostrar(self, img, h, v, cruz, etq=None):
        g = (255 * np.clip(img, 0, 1)).astype(np.uint8)
        rgb = np.repeat(g[..., None], 3, axis=2)
        if etq is not None:
            col = (255 * COLORES[np.clip(etq, 0, None)]).astype(np.uint8)
            m = (etq >= T["fetal"])[..., None]
            rgb = np.where(m, (0.55 * rgb + 0.45 * col).astype(np.uint8), rgb)
        rgb = np.ascontiguousarray(rgb)
        alto, ancho, _ = rgb.shape
        qimg = QImage(rgb.data, ancho, alto, 3 * ancho, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        esc = pix.width() / ancho
        qp = QPainter(pix)
        qp.setPen(QPen(QColor("#ffcc00"), 1))
        cx = (cruz[0] - h[0]) / (h[1] - h[0]) * ancho * esc
        cy = (cruz[1] - v[0]) / (v[1] - v[0]) * alto * esc
        qp.drawLine(int(cx), 0, int(cx), pix.height())
        qp.drawLine(0, int(cy), pix.width(), int(cy))
        qp.setPen(QColor("#9fd3ff"))
        qp.setFont(QFont("Sans", 10))
        qp.drawText(6, 16, self.titulo)
        qp.end()
        self.setPixmap(pix)
        x0 = (self.width() - pix.width()) / 2
        y0 = (self.height() - pix.height()) / 2
        self._geom = (h, v, (x0, y0, pix.width(), pix.height()))

    def mousePressEvent(self, ev):
        if self._geom is None:
            return
        (h0, h1), (v0, v1), (x0, y0, w, hh) = self._geom
        fx = (ev.position().x() - x0) / max(w, 1)
        fy = (ev.position().y() - y0) / max(hh, 1)
        if 0 <= fx <= 1 and 0 <= fy <= 1:
            self.clic.emit(h0 + fx * (h1 - h0), v0 + fy * (v1 - v0))


class VentanaVolumen(QMainWindow):
    def __init__(self, v: Volumen, arriba=None, titulo="", parent=None):
        super().__init__(parent)
        self.v = v
        self.arriba = arriba
        self.setWindowTitle(tr("Volumen (sonda matricial)") + (f" — {titulo}" if titulo else ""))
        self.resize(1500, 900)
        obj = float(v.info.get("info_pose", {}).get("profundidad_objetivo", v.z[len(v.z) // 2]))
        self.cruz = np.array([0.0, 0.0, float(np.clip(obj, v.z[0], v.z[-1]))])

        central = QWidget(); self.setCentralWidget(central)
        rej = QGridLayout(central)
        self.render3d = QtInteractor(central)
        self.render3d.set_background("black")
        self.cortes = {k: Corte(t) for k, t in (("A", tr("A: plano de la imagen")),
                                               ("B", tr("B: plano de elevación")),
                                               ("C", tr("C: corte coronal (profundidad fija)")))}
        rej.addWidget(self.cortes["A"], 0, 0)
        rej.addWidget(self.cortes["B"], 0, 1)
        rej.addWidget(self.cortes["C"], 1, 0)
        rej.addWidget(self.render3d.interactor, 1, 1)
        rej.setColumnStretch(0, 1); rej.setColumnStretch(1, 1)
        rej.setRowStretch(0, 1); rej.setRowStretch(1, 1)
        self.cortes["A"].clic.connect(lambda h, vv: self._mover(x=h, z=vv))
        self.cortes["B"].clic.connect(lambda h, vv: self._mover(y=h, z=vv))
        self.cortes["C"].clic.connect(lambda h, vv: self._mover(x=h, y=vv))

        # panel lateral
        panel = QWidget(); lay = QVBoxLayout(panel)
        caja = QGroupBox(tr("Punto de cruce")); f = QFormLayout(caja)
        self.desl = {}
        for eje, nombre, val in (("x", tr("Lateral"), v.x), ("y", tr("Elevación"), v.y),
                                 ("z", tr("Profundidad"), v.z)):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, len(val) - 1)
            s.valueChanged.connect(self._deslizado)
            self.desl[eje] = s
            f.addRow(nombre, s)
        self.ch_etq = QCheckBox(tr("Superponer etiquetas"))
        self.ch_etq.toggled.connect(self._dibujar_cortes)
        f.addRow(self.ch_etq)
        lay.addWidget(caja)

        caja = QGroupBox(tr("Render de superficie")); f = QFormLayout(caja)
        self.desl_umbral = QSlider(Qt.Orientation.Horizontal)
        self.desl_umbral.setRange(20, 80); self.desl_umbral.setValue(50)
        self.desl_inicio = QSlider(Qt.Orientation.Horizontal)
        self.desl_inicio.setRange(0, len(v.z) - 1)
        self.desl_inicio.setValue(int(np.searchsorted(v.z, inicio_render(v))))
        self.t_render = QTimer(self, singleShot=True, interval=250)
        self.t_render.timeout.connect(self._render)
        for s in (self.desl_umbral, self.desl_inicio):
            s.valueChanged.connect(lambda _: self.t_render.start())
        f.addRow(tr("Umbral"), self.desl_umbral)
        f.addRow(tr("Inicio de la caja"), self.desl_inicio)
        b = QPushButton(tr("Vista desde la sonda"))
        b.clicked.connect(lambda: (camara_desde_sonda(self.render3d, self.v, self._z_inicio(),
                                                      self.arriba), self.render3d.render()))
        f.addRow(b)
        lay.addWidget(caja)
        info = QLabel(tr("{n} planos en {ap:g}° de elevación; vóxel de {vx:.1f} mm",
                         n=v.info.get("n_planos", 0), ap=v.info.get("apertura_elev", 0),
                         vx=v.voxel))
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch(1)
        lay2 = QHBoxLayout()
        lay2.addWidget(panel)
        cont = QWidget(); cont.setLayout(lay2); cont.setMaximumWidth(300)
        rej.addWidget(cont, 0, 2, 2, 1)

        self._fijar_deslizadores()
        self._render(primera=True)

    # ................................................................ cortes
    def _fijar_deslizadores(self):
        iz, iy, ix = self.v.indice(*self.cruz)
        for eje, i in (("x", ix), ("y", iy), ("z", iz)):
            self.desl[eje].blockSignals(True)
            self.desl[eje].setValue(i)
            self.desl[eje].blockSignals(False)
        self._dibujar_cortes()

    def _deslizado(self, *_):
        v = self.v
        self.cruz = np.array([v.x[self.desl["x"].value()], v.y[self.desl["y"].value()],
                              v.z[self.desl["z"].value()]], float)
        self._dibujar_cortes()

    def _mover(self, x=None, y=None, z=None):
        for k, val in enumerate((x, y, z)):
            if val is not None:
                self.cruz[k] = val
        self._fijar_deslizadores()

    def _dibujar_cortes(self, *_):
        v = self.v
        iz, iy, ix = v.indice(*self.cruz)
        c = v.cortes(iz, iy, ix)
        etq = self.ch_etq.isChecked()
        x, y, z = (v.x[0], v.x[-1]), (v.y[0], v.y[-1]), (v.z[0], v.z[-1])
        cx, cy, cz = self.cruz
        self.cortes["A"].mostrar(c["A"], x, z, (cx, cz), c["A_etq"] if etq else None)
        self.cortes["B"].mostrar(c["B"], y, z, (cy, cz), c["B_etq"] if etq else None)
        self.cortes["C"].mostrar(c["C"], x, y, (cx, cy), c["C_etq"] if etq else None)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(0, self._dibujar_cortes)

    # ................................................................ render
    def _z_inicio(self):
        return float(self.v.z[self.desl_inicio.value()])

    def _render(self, primera=False):
        p = self.render3d
        agregar_render(p, self.v, self._z_inicio(), umbral=self.desl_umbral.value() / 100)
        if primera:
            camara_desde_sonda(p, self.v, self._z_inicio(), self.arriba)
        p.render()

    def closeEvent(self, ev):
        self.render3d.close()
        super().closeEvent(ev)
