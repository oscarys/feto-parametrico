#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
escaner.py — Simulador de exploración obstétrica: una sonda virtual sobre el
abdomen materno produce la ecografía en vivo, junto a la escena 3D.

    feto-escaner                 # 22 semanas
    feto-escaner --eg 28 --udp   # escuchando una sonda física por UDP (puerto 5005)

Controles
---------
Mapa del abdomen: arrastrar = mover la sonda; rueda = girarla.
Teclado (con la ventana activa; Mayús = pasos finos):
    flechas         deslizar la sonda (izq/der: lateral de la imagen; arriba/abajo: elevación)
    Q / E           girar alrededor del haz
    W / S           balanceo (rock), en el plano de la imagen
    A / D           abanico (fan), fuera del plano
    N               sonda perpendicular a la piel
    Espacio         congelar / descongelar (al congelar: imagen de alta calidad y medidas)
    M               feto en movimiento sí/no
    B               biplano sí/no (sonda matricial)
    V               adquirir un volumen (sonda matricial)

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np
from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                             QPushButton, QSizePolicy, QSlider, QSpinBox, QSplitter,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)
from pyvistaqt import QtInteractor

from ..ecografia import (PLANOS, TIPOS_SONDA, Adquisicion, medir_en_imagen, plano_estandar,
                         simular, sonda_tipo)
from ..volumen import arriba_cabeza, caja_alrededor, pose_biplano, simular_volumen
from ..feto3d import Escena, Materno, Postura
from ..fuentes_sonda import PUERTO, FuenteUDP
from ..i18n import N_, tr
from ..movimiento import Movimiento
from ..sonda_control import EstadoSonda, Tolerancia, errores_planos, orientacion_normal, punto_piel
from ..tejidos import COLORES, TEJIDOS, T
from .comun import agregar_argumento, idioma_inicial, menu_idioma
from ..vista3d import (a_pv_lista, abanico_3d, agregar_escena, malla_placenta, mallas_escena,
                     mallas_escena_np, sonda_3d)

NOMBRES = {"transtalamico": N_("Transtalámico"), "transcerebelar": N_("Transcerebelar"),
           "cuatro_camaras": N_("Cuatro cámaras"), "abdominal": N_("Abdominal (CA)"),
           "femur": N_("Fémur"), "sagital": N_("Sagital medio"), "perfil": N_("Perfil"),
           "nariz_labios": N_("Nariz y labios"), "tsvi": N_("Tracto de salida del VI"),
           "tsvd": N_("Tracto de salida del VD"), "tres_vasos": N_("Tres vasos y tráquea"),
           "vejiga": N_("Vejiga y arterias umbilicales"), "mano": N_("Mano"),
           "pie": N_("Pie (planta)")}
# medida -> (nombre mostrado, clave en Feto.bio, fuente del valor esperado)
MEDIDAS = {"CC": (N_("CC"), "CC", "Hadlock"), "DBP_ext": (N_("DBP"), "DBP", "Hadlock"),
           "CA": (N_("CA"), "CA", "Hadlock"), "LF": (N_("LF"), "LF", "Hadlock"),
           "DTC": (N_("DTC"), "DTC", N_("esperado")), "CM": (N_("CM"), "CM", N_("esperado")),
           "HN": (N_("HN"), "HN", N_("esperado"))}
TIPOS = {"convexa": N_("Convexa"), "lineal": N_("Lineal"),
         "sectorial": N_("Sectorial (phased array)"), "matricial": N_("Matricial (volumen)")}
CALIDAD = {"rápida": dict(n_lineas=128, dr_mm=0.2, px=0.5),
           "alta": dict(n_lineas=256, dr_mm=0.1, px=0.3)}


# ---------------------------------------------------------------------------
# Trabajo en segundo plano: escena + simulación (+ mallas si el feto se movió)
# ---------------------------------------------------------------------------

class _Senales(QObject):
    listo = pyqtSignal(object)


class _SenalesVolumen(QObject):
    avance = pyqtSignal(int, int)
    listo = pyqtSignal(object)


class _TrabajoVolumen(QRunnable):
    """Barrido completo de la sonda matricial (unos 15 s)."""
    def __init__(self, esc, pose, sonda, adq):
        super().__init__()
        self.args = (esc, pose, sonda, adq)
        self.senales = _SenalesVolumen()

    def run(self):
        esc, pose, sonda, adq = self.args
        try:
            v = simular_volumen(esc, pose, sonda, adq, n_planos=97, voxel_mm=0.6,
                                caja=caja_alrededor(pose, sonda),
                                progreso=lambda k, n: self.senales.avance.emit(k, n))
            self.senales.listo.emit({"volumen": v, "arriba": arriba_cabeza(esc, v)})
        except Exception as e:                 # noqa: BLE001
            self.senales.listo.emit({"error": repr(e)})


class _Trabajo(QRunnable):
    def __init__(self, pedido: dict):
        super().__init__()
        self.pedido = pedido
        self.senales = _Senales()

    def run(self):
        p = self.pedido
        out = {"pedido": p}
        try:
            esc = p["escena"]
            if esc is None:
                esc = Escena(p["eg"], p["postura"], mat=p["materno"])
            out["escena"] = esc
            pose = p["estado"].pose(esc)
            out["pose"] = pose
            if pose is not None:
                c = CALIDAD[p["calidad"]]
                fino = 0.5 if p["geometria"] == "lineal" else 1.0   # campo pequeño, más detalle
                sonda = sonda_tipo(p["geometria"], f0_mhz=p["f0"], profundidad_mm=p["prof"],
                                   n_lineas=c["n_lineas"], dr_mm=c["dr_mm"] * fino,
                                   foco_mm=0.55 * p["prof"])
                adq = Adquisicion(ganancia_db=p["ganancia"], rango_dinamico_db=p["rd"],
                                  px_salida_mm=c["px"] * fino,
                                  elevacion=(0.0,))
                res = simular(esc, pose, sonda, adq,
                              etiquetas=True if p["calidad"] == "alta" else "rapidas")
                out.update(res=res, sonda=sonda, adq=adq,
                           errores=errores_planos(esc, pose))
                if p.get("biplano"):
                    pose2 = pose_biplano(pose)
                    out.update(pose2=pose2, res2=simular(
                        esc, pose2, sonda, adq, normalizacion=res["normalizacion"],
                        etiquetas=True if p["calidad"] == "alta" else "rapidas"))
                if p.get("medir"):
                    mejor = min(out["errores"].items(), key=lambda kv: kv[1][0] + kv[1][1])[0]
                    out["medidas"] = (mejor, medir_en_imagen(res, mejor, adq.px_salida_mm,
                                                             plano_estandar(esc, mejor)))
            if p.get("mallas"):
                # sólo NumPy aquí: VTK no es seguro entre hilos
                out["mallas"] = mallas_escena_np(esc, 80, placenta=False, utero=False)
        except Exception as e:                 # noqa: BLE001 — se muestra en la barra de estado
            out["error"] = repr(e)
        self.senales.listo.emit(out)


# ---------------------------------------------------------------------------
# Mapa del abdomen (vista superior) para mover la sonda con el ratón
# ---------------------------------------------------------------------------

class MapaAbdomen(QWidget):
    movido = pyqtSignal(float, float)       # x, y en mm
    girado = pyqtSignal(float)              # grados

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.esc = None
        self.silueta = None
        self.estado = None
        self.setMouseTracking(False)

    def fijar_escena(self, esc, silueta_xy):
        self.esc, self.silueta = esc, silueta_xy
        self.update()

    def _escala(self):
        c, a = self.esc.c_abd, self.esc.abd
        w, h = self.width() - 20, self.height() - 20
        s = min(w / (2 * a[0]), h / (2 * a[1]))
        return s, c

    def a_pantalla(self, x, y):
        s, c = self._escala()
        # izquierda materna a la derecha de la pantalla (vista desde los pies? no: desde arriba,
        # con la cabeza materna arriba y el lado izquierdo materno a la derecha, como al explorar)
        return QPointF(self.width() / 2 + (x - c[0]) * s, self.height() / 2 - (y - c[1]) * s)

    def a_mundo(self, pt):
        s, c = self._escala()
        return c[0] + (pt.x() - self.width() / 2) / s, c[1] - (pt.y() - self.height() / 2) / s

    def paintEvent(self, ev):
        if self.esc is None:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.fillRect(self.rect(), QColor("#20242c"))
        s, c = self._escala()
        a = self.esc.abd
        centro = self.a_pantalla(c[0], c[1])
        qp.setPen(QPen(QColor("#c9a28f"), 2))
        qp.setBrush(QBrush(QColor("#3a2f2c")))
        qp.drawEllipse(centro, a[0] * s, a[1] * s)
        # útero
        cav = self.esc.cav
        qp.setPen(QPen(QColor("#a0606a"), 1, Qt.PenStyle.DashLine))
        qp.setBrush(Qt.BrushStyle.NoBrush)
        qp.drawEllipse(self.a_pantalla(0, 0), cav[0] * s, cav[1] * s)
        # silueta del feto
        if self.silueta is not None:
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QBrush(QColor(238, 190, 165, 70)))
            for x, y in self.silueta:
                qp.drawEllipse(self.a_pantalla(x, y), 1.6, 1.6)
        # rótulos
        qp.setPen(QColor("#8a8f98"))
        qp.setFont(QFont("Sans", 8))
        qp.drawText(QRectF(0, 2, self.width(), 14), Qt.AlignmentFlag.AlignHCenter, tr("craneal"))
        qp.drawText(QRectF(0, self.height() - 16, self.width(), 14), Qt.AlignmentFlag.AlignHCenter, tr("caudal"))
        qp.drawText(QRectF(4, self.height() / 2 - 7, 60, 14), Qt.AlignmentFlag.AlignLeft, tr("der."))
        qp.drawText(QRectF(self.width() - 64, self.height() / 2 - 7, 60, 14),
                    Qt.AlignmentFlag.AlignRight, tr("izq."))
        # sonda: rectángulo orientado según ex proyectado
        if self.estado is not None:
            e = self.estado
            p = self.a_pantalla(e.x, e.y)
            ex = e.R[:2, 0]
            n = np.linalg.norm(ex)
            ex = ex / n if n > 1e-6 else np.array([1.0, 0.0])
            ey = np.array([-ex[1], ex[0]])
            L, W = 30 * s, 8 * s
            pts = [(+L, +W), (-L, +W), (-L, -W), (+L, -W)]
            poly = QPolygonF([QPointF(p.x() + (u * ex[0] + v * ey[0]), p.y() - (u * ex[1] + v * ey[1]))
                              for u, v in pts])
            qp.setPen(QPen(QColor("#e8eef7"), 2))
            qp.setBrush(QBrush(QColor(80, 110, 160, 180)))
            qp.drawPolygon(poly)
            # marca de orientación (lado +ex, que aparece a la derecha de la imagen)
            qp.setBrush(QBrush(QColor("#7cd992")))
            qp.drawEllipse(QPointF(p.x() + L * ex[0], p.y() - L * ex[1]), 4, 4)

    def _raton(self, ev):
        if self.esc is not None:
            x, y = self.a_mundo(ev.position())
            self.movido.emit(x, y)

    def mousePressEvent(self, ev):
        self._raton(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._raton(ev)

    def wheelEvent(self, ev):
        self.girado.emit(5.0 if ev.angleDelta().y() > 0 else -5.0)


# ---------------------------------------------------------------------------
# Imagen de ecografía
# ---------------------------------------------------------------------------

class PanelEco(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: black; color: #c8c8c8;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(420, 320)
        self._pix = None
        self.setText(tr("Coloque la sonda sobre el abdomen"))

    @staticmethod
    def _rgb(res, etiquetas):
        b = (255 * np.clip(res["bmodo"], 0, 1)).astype(np.uint8)
        rgb = np.repeat(b[..., None], 3, axis=2)
        if etiquetas and "etiquetas" in res:
            lab = res["etiquetas"]
            col = (255 * COLORES[np.clip(lab, 0, None)]).astype(np.uint8)
            m = (lab >= T["fetal"])[..., None]
            rgb = np.where(m, (0.55 * rgb + 0.45 * col).astype(np.uint8), rgb)
        return rgb

    def mostrar(self, res, etiquetas=False, textos=(), res2=None):
        rgb = self._rgb(res, etiquetas)
        if res2 is not None:                   # biplano: los dos planos lado a lado
            rgb2 = self._rgb(res2, etiquetas)
            h = max(rgb.shape[0], rgb2.shape[0])
            pad = lambda a: np.pad(a, ((0, h - a.shape[0]), (0, 0), (0, 0)))  # noqa: E731
            sep = np.full((h, max(4, rgb.shape[1] // 60), 3), 60, np.uint8)
            rgb = np.hstack([pad(rgb), sep, pad(rgb2)])
        h, w0, _ = rgb.shape
        # imagen angosta (sonda lineal): bandas negras a los lados para textos y escala
        izq = max(0, (int(0.8 * h) - w0) // 2)
        if izq:
            rgb = np.pad(rgb, ((0, 0), (izq, izq), (0, 0)))
        rgb = np.ascontiguousarray(rgb)
        h, w, _ = rgb.shape
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        # escala de profundidad cada 2 cm, junto al borde derecho de la imagen
        qp = QPainter(img)
        qp.setPen(QColor("#9fd3ff"))
        px = res["zs"][1] - res["zs"][0]
        borde = izq + w0
        for d in range(0, int(res["zs"][-1]) + 1, 10 if izq else 20):
            y = int(d / px)
            qp.drawLine(borde - 10, y, borde - 2, y)
            if d and d % (20 if izq else 40) == 0:
                qp.setFont(QFont("Sans", max(8, w // 70)))
                x = borde + 6 if izq else w - int(w * 0.09)
                qp.drawText(x, y + 4, f"{d // 10} cm")
        fs = max(10, w // 55)
        qp.setFont(QFont("Sans", fs))
        for i, t in enumerate(textos):
            qp.drawText(8, int((1.6 + 1.5 * i) * fs), t)
        qp.end()
        self._pix = QPixmap.fromImage(img)
        self._reescalar()

    def _reescalar(self):
        if self._pix is not None:
            self.setPixmap(self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        self._reescalar()
        super().resizeEvent(ev)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class Escaner(QMainWindow):
    def __init__(self, eg=22.0, udp=False, puerto=PUERTO):
        super().__init__()
        self.setWindowTitle(tr("Simulador de exploración obstétrica"))
        self.resize(1600, 950)
        self.eg = eg
        self.materno = Materno()
        self.estado = EstadoSonda()
        self.congelado = False
        self.movimiento = None
        self.t0 = time.time()
        self.pool = QThreadPool.globalInstance()
        self.ocupado, self.pendiente, self.pendiente_mallas = False, False, False
        self.pendiente_alta = False
        self.escena_fija = None          # escena reutilizada mientras el feto no se mueve
        self.tol = Tolerancia()
        self.ultimo = None

        # --- centro: 3D | eco
        self.vista = QtInteractor(self)
        self.vista.set_background("#f2efe9", top="#d4cfc6")
        self.vista.add_axes()
        self.eco = PanelEco()
        div = QSplitter(Qt.Orientation.Horizontal)
        div.addWidget(self.vista.interactor); div.addWidget(self.eco)
        div.setSizes([750, 850])
        self.setCentralWidget(div)

        self._panel()
        menu_idioma(self, self._reconstruir)
        self.statusBar().showMessage(tr("Listo"))

        # fuente física
        self.udp = FuenteUDP(puerto, self) if FuenteUDP else None
        if self.udp:
            self.udp.muestra.connect(self._muestra_udp)
            self.udp.error.connect(lambda m: self.statusBar().showMessage(m, 6000))
        if udp:
            self.ch_udp.setChecked(True)

        self.temporizador = QTimer(self, interval=120)
        self.temporizador.timeout.connect(self._tic_movimiento)

        self._nueva_escena()

    # ............................................................ panel
    def _panel(self):
        panel = QWidget(); lay = QVBoxLayout(panel)

        self.mapa = MapaAbdomen()
        self.mapa.movido.connect(self._mapa_movido)
        self.mapa.girado.connect(lambda g: self._accion(giro=g))
        caja = QGroupBox(tr("Abdomen (arrastre para mover, rueda para girar)"))
        v = QVBoxLayout(caja); v.addWidget(self.mapa)
        lay.addWidget(caja, stretch=2)

        caja = QGroupBox(tr("Paciente")); f = QFormLayout(caja)
        self.sp_eg = QDoubleSpinBox(); self.sp_eg.setRange(14, 40); self.sp_eg.setSingleStep(1)
        self.sp_eg.setValue(self.eg); self.sp_eg.setSuffix(tr(" sem"))
        self.sp_eg.editingFinished.connect(self._eg_cambio)
        self.cb_plac = QComboBox()
        for sitio in (N_("anterior"), N_("posterior"), N_("fundica"), N_("lateral")):
            self.cb_plac.addItem(tr(sitio), sitio)        # texto traducido, dato interno
        self.cb_plac.currentTextChanged.connect(self._materno_cambio)
        self.sp_grasa = QSpinBox(); self.sp_grasa.setRange(4, 50); self.sp_grasa.setValue(12)
        self.sp_grasa.setSuffix(tr(" mm")); self.sp_grasa.editingFinished.connect(self._materno_cambio)
        self.sp_dorso = QSpinBox(); self.sp_dorso.setRange(0, 345); self.sp_dorso.setSingleStep(15)
        self.sp_dorso.setValue(135); self.sp_dorso.setSuffix("°"); self.sp_dorso.setWrapping(True)
        self.sp_dorso.setToolTip(tr("0° dorso anterior, 90° a la izquierda materna, 180° posterior "
                                    "(cara hacia la sonda)"))
        self.sp_dorso.editingFinished.connect(self._materno_cambio)
        self.ch_mov = QCheckBox(tr("Feto en movimiento (M)"))
        self.ch_mov.toggled.connect(self._mov_toggled)
        f.addRow(tr("Edad gestacional"), self.sp_eg); f.addRow(tr("Placenta"), self.cb_plac)
        f.addRow(tr("Grasa abdominal"), self.sp_grasa); f.addRow(tr("Dorso fetal"), self.sp_dorso)
        f.addRow(self.ch_mov)
        lay.addWidget(caja)

        caja = QGroupBox(tr("Equipo")); f = QFormLayout(caja)
        self.cb_tipo = QComboBox()
        for g in TIPOS_SONDA:
            self.cb_tipo.addItem(tr(TIPOS[g]), g)
        self.cb_tipo.currentIndexChanged.connect(self._cambiar_tipo)
        f.addRow(tr("Tipo de sonda"), self.cb_tipo)
        self.sp_f0 = QDoubleSpinBox(); self.sp_f0.setRange(2.0, 6.0); self.sp_f0.setSingleStep(0.5)
        self.sp_f0.setValue(3.5); self.sp_f0.setSuffix(tr(" MHz"))
        self.sp_prof = QSpinBox(); self.sp_prof.setRange(80, 240); self.sp_prof.setSingleStep(10)
        self.sp_prof.setValue(160); self.sp_prof.setSuffix(tr(" mm"))
        self.desl_gan = QSlider(Qt.Orientation.Horizontal); self.desl_gan.setRange(-15, 15)
        self.desl_rd = QSlider(Qt.Orientation.Horizontal); self.desl_rd.setRange(35, 75)
        self.desl_rd.setValue(55)
        self.ch_etq = QCheckBox(tr("Superponer etiquetas"))
        for w in (self.sp_f0, self.sp_prof):
            w.valueChanged.connect(lambda _: self._pedir())
        for w in (self.desl_gan, self.desl_rd):
            w.valueChanged.connect(lambda _: self._pedir())
        self.ch_etq.toggled.connect(self._redibujar_eco)
        fila_m = QHBoxLayout()
        self.ch_biplano = QCheckBox(tr("Biplano (B)"))
        self.ch_biplano.toggled.connect(lambda _: self._pedir())
        self.btn_vol = QPushButton(tr("Adquirir volumen (V)"))
        self.btn_vol.clicked.connect(self._adquirir_volumen)
        fila_m.addWidget(self.ch_biplano); fila_m.addWidget(self.btn_vol)
        self.fila_matricial = QWidget(); self.fila_matricial.setLayout(fila_m)
        self.fila_matricial.setVisible(False)
        f.addRow(self.fila_matricial)
        f.addRow(tr("Frecuencia"), self.sp_f0); f.addRow(tr("Profundidad"), self.sp_prof)
        f.addRow(tr("Ganancia"), self.desl_gan); f.addRow(tr("Rango dinámico"), self.desl_rd)
        f.addRow(self.ch_etq)
        lay.addWidget(caja)

        caja = QGroupBox(tr("Sonda")); v = QVBoxLayout(caja)
        fila = QHBoxLayout()
        b = QPushButton(tr("Perpendicular (N)")); b.clicked.connect(self._perpendicular); fila.addWidget(b)
        self.btn_cong = QPushButton(tr("Congelar (Espacio)")); self.btn_cong.clicked.connect(self._congelar)
        fila.addWidget(self.btn_cong); v.addLayout(fila)
        fila = QHBoxLayout()
        self.cb_plano = QComboBox(); self.cb_plano.addItems([tr(NOMBRES[p]) for p in PLANOS])
        b = QPushButton(tr("Ir al plano")); b.clicked.connect(self._ir_plano)
        fila.addWidget(self.cb_plano); fila.addWidget(b); v.addLayout(fila)
        fila = QHBoxLayout()
        self.ch_udp = QCheckBox(tr("Sonda física UDP :{puerto}", puerto=PUERTO))
        self.ch_udp.toggled.connect(self._udp_toggled)
        b = QPushButton(tr("Calibrar IMU")); b.clicked.connect(self._calibrar)
        fila.addWidget(self.ch_udp); fila.addWidget(b); v.addLayout(fila)
        self.lbl_udp = QLabel("—"); self.lbl_udp.setStyleSheet("color: gray;")
        v.addWidget(self.lbl_udp)
        lay.addWidget(caja)

        caja = QGroupBox(tr("Planos estándar: ángulo / distancia"))
        v = QVBoxLayout(caja)
        self.tabla = QTableWidget(len(PLANOS), 3)
        self.tabla.setHorizontalHeaderLabels([tr("Plano"), tr("Ángulo"), tr("Distancia")])
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.verticalHeader().setDefaultSectionSize(22)
        self.tabla.setMinimumHeight(150)
        for i, p in enumerate(PLANOS):
            self.tabla.setItem(i, 0, QTableWidgetItem(tr(NOMBRES[p])))
        v.addWidget(self.tabla)
        self.lbl_medidas = QLabel(""); self.lbl_medidas.setWordWrap(True)
        v.addWidget(self.lbl_medidas)
        lay.addWidget(caja)

        from PyQt6.QtWidgets import QScrollArea
        desplaz = QScrollArea(); desplaz.setWidget(panel); desplaz.setWidgetResizable(True)
        desplaz.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dock = QDockWidget(tr("Controles"), self); dock.setWidget(desplaz)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        dock.setMinimumWidth(360)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        for w in panel.findChildren(QWidget):          # el teclado lo maneja la ventana
            if not isinstance(w, (QDoubleSpinBox, QSpinBox, QComboBox)):
                w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # ............................................................ escena
    def _nueva_escena(self):
        self.escena_fija = Escena(self.eg, mat=self.materno)
        esc = self.escena_fija
        if self.movimiento is None:
            self.movimiento = Movimiento(semilla=0, duracion=3600, tasa_patadas=0.08,
                                         tasa_brazos=0.05, tasa_giros=0.04, intensidad=0.7)
        # estáticos 3D
        v = self.vista
        v.clear_actors()
        abd = pv_elipsoide(esc.abd, esc.c_abd).clip(normal=(0, 0, 1),
                                                     origin=(0, 0, esc.ut[2] - 10), invert=False)
        v.add_mesh(abd, color=TEJIDOS[T["piel"]].color, opacity=0.12, name="abdomen",
                   smooth_shading=True)
        estaticos = [("utero", pv_elipsoide(esc.cav, np.zeros(3)), TEJIDOS[T["miometrio"]].color, 0.10),
                     ("placenta", malla_placenta(esc), TEJIDOS[T["placenta"]].color, 0.85)]
        agregar_escena(v, estaticos)
        self._mallas_feto(mallas_escena(esc, 90, placenta=False, utero=False))
        # mapa
        piel = [m for m in self._ultimas_mallas if m[0] == "piel"][0][1]
        pts = np.asarray(piel.points)[::25]
        self.mapa.fijar_escena(esc, pts[:, :2])
        # sonda: arriba del abdomen del feto, perpendicular
        if self.estado.x == 0 and self.estado.y == 0:
            self.estado.x, self.estado.y = 0.0, 0.0
        self.estado.colocar_normal(esc)
        self.mapa.estado = self.estado
        v.camera_position = [(650, 380, 650), (0, 0, 0), (0, 1, 0)]
        self._pedir()

    def _mallas_feto(self, mallas):
        v = self.vista
        for n in getattr(self, "_nombres_feto", []):
            v.remove_actor(n, render=False)
        agregar_escena(v, mallas, render=False)     # se dibuja una sola vez en _aplicar
        self._nombres_feto = [m[0] for m in mallas]
        self._ultimas_mallas = mallas

    def _eg_cambio(self):
        if abs(self.sp_eg.value() - self.eg) > 1e-6:
            self.eg = self.sp_eg.value()
            self._nueva_escena()

    def _materno_cambio(self, *_):
        self.materno = Materno(grasa_mm=self.sp_grasa.value(), placenta=self.cb_plac.currentData(),
                               dorso_grados=float(self.sp_dorso.value()))
        self._nueva_escena()

    # ........................................................... pedidos
    def _escena_actual(self):
        if self.ch_mov.isChecked():
            return None                          # se construye en el hilo con la postura actual
        return self.escena_fija

    def _pedir(self, mallas=False, calidad=None, medir=False):
        if self.congelado and calidad is None:
            return
        if self.ocupado and calidad == "alta":
            self.pendiente_alta = True          # se lanza al terminar el cuadro en curso
            return
        if self.ocupado:
            self.pendiente = True
            self.pendiente_mallas |= mallas
            return
        t = time.time() - self.t0
        pedido = dict(eg=self.eg, materno=self.materno, escena=self._escena_actual(),
                      postura=self.movimiento.en(t) if self.ch_mov.isChecked() else Postura(),
                      estado=EstadoSonda(self.estado.x, self.estado.y, self.estado.R.copy()),
                      calidad=calidad or "rápida", geometria=self.cb_tipo.currentData(),
                      biplano=self._es_matricial() and self.ch_biplano.isChecked(),
                      f0=self.sp_f0.value(),
                      prof=self.sp_prof.value(), ganancia=self.desl_gan.value(),
                      rd=self.desl_rd.value(), mallas=mallas, medir=medir, t=t)
        self.ocupado = True
        trabajo = _Trabajo(pedido)
        trabajo.senales.listo.connect(self._listo)
        self.pool.start(trabajo)

    def _listo(self, out):
        self.ocupado = False
        if "error" in out:
            self.statusBar().showMessage(tr("Error: {msg}", msg=out["error"]), 8000)
        elif not (self.congelado and out["pedido"]["calidad"] != "alta"):
            self._aplicar(out)
            if out["pedido"]["calidad"] == "alta":
                self.statusBar().showMessage(tr("Imagen congelada"), 3000)
        if self.pendiente_alta and self.congelado:
            self.pendiente_alta = False
            self._pedir(calidad="alta", medir=True)
            return
        if self.pendiente and not self.congelado:
            m = self.pendiente_mallas
            self.pendiente = self.pendiente_mallas = False
            self._pedir(mallas=m)

    def _aplicar(self, out):
        if out.get("mallas"):
            self._mallas_feto(a_pv_lista(out["mallas"]))
        pose = out.get("pose")
        v = self.vista
        if pose is None:
            self.eco.setText(tr("La sonda está fuera del abdomen"))
            v.remove_actor("abanico", render=False); v.remove_actor("sonda", render=False)
            v.render()
            return
        res = out["res"]
        self.ultimo = out
        v.add_mesh(abanico_3d(pose, out["sonda"], res, sub=1 if out["pedido"]["calidad"] == "rápida" else 2),
                   scalars="eco", cmap="gray", clim=(0, 1), show_scalar_bar=False,
                   name="abanico", lighting=False, render=False)
        v.add_mesh(sonda_3d(pose, out["sonda"]), color="#3b4252", name="sonda", render=False)
        if "res2" in out:
            v.add_mesh(abanico_3d(out["pose2"], out["sonda"], out["res2"], sub=2),
                       scalars="eco", cmap="gray", clim=(0, 1), show_scalar_bar=False,
                       name="abanico2", lighting=False, render=False)
        else:
            v.remove_actor("abanico2", render=False)
        v.render()
        self._tabla_errores(out["errores"])
        if "medidas" in out:
            nom, med = out["medidas"]
            bio = out["escena"].feto.bio
            txt = ", ".join(f"{tr(MEDIDAS[k][0])} {v_:.1f} mm ({tr(MEDIDAS[k][2])} {bio[MEDIDAS[k][1]]:.1f})"
                            for k, v_ in med.items() if k in MEDIDAS)
            self.lbl_medidas.setText(f"<b>{tr(NOMBRES[nom])}</b>: {txt or tr('sin medidas para este plano')}")
        self._redibujar_eco()
        self.mapa.update()

    def _redibujar_eco(self, *_):
        if self.ultimo is None or "res" not in self.ultimo:
            return
        o = self.ultimo
        textos = [tr("{eg:g} sem   {f0:.1f} MHz", eg=self.eg, f0=o["sonda"].f0_mhz)]
        if self.congelado:
            textos.append(tr("CONGELADA"))
        self.eco.mostrar(o["res"], self.ch_etq.isChecked(), textos, o.get("res2"))

    def _tabla_errores(self, err):
        for i, p in enumerate(PLANOS):
            if p not in err:
                continue
            ang, dist = err[p]
            bien = ang <= self.tol.angulo_grados and dist <= self.tol.distancia_mm
            cerca = ang <= 2.5 * self.tol.angulo_grados and dist <= 3 * self.tol.distancia_mm
            col = QColor("#2e7d32") if bien else QColor("#b26a00") if cerca else QColor("#555555")
            for j, t in ((1, f"{ang:5.1f}°"), (2, f"{dist:5.1f} mm")):
                it = QTableWidgetItem(tr(t)); it.setForeground(QBrush(col))
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(i, j, it)
            self.tabla.item(i, 0).setForeground(QBrush(col))

    # ......................................................... acciones
    def _accion(self, giro=0.0, balanceo=0.0, abanico=0.0, lateral=0.0, elevacion=0.0):
        if self.congelado:
            return
        if giro or balanceo or abanico:
            self.estado.rotar(giro, balanceo, abanico)
        if lateral or elevacion:
            self.estado.deslizar(lateral, elevacion)
        self.mapa.update()
        self._pedir()

    def _mapa_movido(self, x, y):
        if self.congelado:
            return
        esc = self.escena_fija
        p_ant, n_ant = punto_piel(esc, self.estado.x, self.estado.y)
        p_new, n_new = punto_piel(esc, x, y)
        if p_new is None:
            return
        # al deslizar sobre la piel, la sonda acompaña el cambio de la normal
        if n_ant is not None:
            eje = np.cross(n_ant, n_new)
            s = np.linalg.norm(eje)
            if s > 1e-6:
                from ..feto3d import _rot
                self.estado.R = _rot(eje, math.asin(min(1.0, s))) @ self.estado.R
        self.estado.x, self.estado.y = x, y
        self.mapa.update()
        self._pedir()

    def _perpendicular(self):
        _, n = punto_piel(self.escena_fija, self.estado.x, self.estado.y)
        if n is None:
            return
        ex = self.estado.R[:, 0]
        self.estado.colocar_normal(self.escena_fija)
        # conservar la dirección lateral de la imagen en lo posible
        R = self.estado.R
        ang = math.degrees(math.atan2(ex @ R[:, 1], ex @ R[:, 0]))
        self.estado.colocar_normal(self.escena_fija, ang)
        self.mapa.update(); self._pedir()

    def _ir_plano(self):
        nom = PLANOS[self.cb_plano.currentIndex()]
        try:
            pose = plano_estandar(self.escena_fija, nom)
        except ValueError as e:
            self.statusBar().showMessage(str(e), 5000); return
        self.estado.desde_pose(pose)
        prof = pose.info["profundidad_objetivo"] + 60
        self.sp_prof.blockSignals(True)            # setValue se ajusta al intervalo de la sonda
        self.sp_prof.setValue(int(10 * round(prof / 10)))
        self.sp_prof.blockSignals(False)
        self.mapa.update(); self._pedir()

    def _es_matricial(self):
        return self.cb_tipo.currentData() == "matricial"

    def _cambiar_tipo(self, *_):
        """Frecuencia y profundidad típicas del tipo de sonda elegido."""
        self.fila_matricial.setVisible(self._es_matricial())
        t = TIPOS_SONDA[self.cb_tipo.currentData()]
        for sp, (val, lo, hi) in ((self.sp_f0, t["f0"]), (self.sp_prof, t["prof"])):
            sp.blockSignals(True)
            sp.setRange(lo, hi)
            sp.setValue(val)
            sp.blockSignals(False)
        self._pedir()

    # ......................................................... volumen
    def _adquirir_volumen(self):
        if not self._es_matricial() or self.ultimo is None or "res" not in self.ultimo:
            return
        if getattr(self, "_vol_en_curso", False):
            return
        o = self.ultimo
        self._vol_en_curso = True
        self.btn_vol.setEnabled(False)
        t = _TrabajoVolumen(o["escena"], o["pose"], o["sonda"], o["adq"])
        t.senales.avance.connect(lambda k, n: self.statusBar().showMessage(
            tr("Adquiriendo volumen… {k}/{n} planos", k=k, n=n)))
        t.senales.listo.connect(self._volumen_listo)
        self.pool.start(t)

    def _volumen_listo(self, out):
        self._vol_en_curso = False
        self.btn_vol.setEnabled(True)
        if "error" in out:
            self.statusBar().showMessage(tr("Error: {msg}", msg=out["error"]), 8000)
            return
        from .ventana_volumen import VentanaVolumen
        self.statusBar().showMessage(tr("Volumen listo"), 3000)
        w = VentanaVolumen(out["volumen"], out["arriba"], tr("{eg:g} sem", eg=self.eg))
        self.ventanas_volumen = [x for x in getattr(self, "ventanas_volumen", []) if x.isVisible()]
        self.ventanas_volumen.append(w)
        w.show()

    def _congelar(self):
        self.congelado = not self.congelado
        self.btn_cong.setText(tr("Descongelar (Espacio)") if self.congelado else tr("Congelar (Espacio)"))
        if self.congelado:
            self.statusBar().showMessage(tr("Calculando imagen de alta calidad y medidas…"))
            self._pedir(calidad="alta", medir=True)
        else:
            self.lbl_medidas.setText("")
            self.pendiente_alta = False
            self._pedir()

    def _mov_toggled(self, on):
        if on:
            self.temporizador.start()
        else:
            self.temporizador.stop()
            self._pedir(mallas=True)

    def _tic_movimiento(self):
        if not self.congelado:
            self._pedir(mallas=True)

    # ...................................................... sonda física
    def _udp_toggled(self, on):
        if self.udp is None:
            self.statusBar().showMessage(tr("QtNetwork no disponible"), 5000); return
        if on:
            if self.udp.iniciar():
                self.lbl_udp.setText(tr("Escuchando en el puerto {puerto}…", puerto=self.udp.puerto))
        else:
            self.udp.detener(); self.lbl_udp.setText("—")

    def _calibrar(self):
        if getattr(self, "_q_ultimo", None) is not None:
            self.estado.calibrar_imu(self._q_ultimo)
            self.statusBar().showMessage(tr("IMU calibrada: su orientación actual = la de la sonda virtual"), 4000)

    def _muestra_udp(self, d):
        ev = d.get("evento")
        if ev == "congelar" and not self.congelado or ev == "descongelar" and self.congelado:
            self._congelar(); return
        if ev == "calibrar" and "q" in d:
            self._q_ultimo = d["q"]; self._calibrar()
        if self.congelado:
            return
        esc = self.escena_fija
        if "u" in d and "v" in d:
            x = esc.c_abd[0] + float(d["u"]) * 0.8 * esc.abd[0]
            y = esc.c_abd[1] + float(d["v"]) * 0.8 * esc.abd[1]
        else:
            x, y = float(d.get("x", self.estado.x)), float(d.get("y", self.estado.y))
        self.estado.x, self.estado.y = x, y
        if "q" in d:
            self._q_ultimo = d["q"]
            self.estado.desde_imu(d["q"])
        elif any(k in d for k in ("giro", "balanceo", "abanico")):
            _, n = punto_piel(esc, x, y)
            if n is not None:
                self.estado.R = orientacion_normal(n, float(d.get("giro", 0.0)))
                self.estado.rotar(0.0, float(d.get("balanceo", 0.0)), float(d.get("abanico", 0.0)))
        self.lbl_udp.setText(tr("muestras: {n}   x {x:6.1f}  y {y:6.1f} mm", n=self.udp.n, x=x, y=y))
        self.mapa.update()
        self._pedir()

    # ........................................................... teclado
    def _reconstruir(self):
        """Ventana nueva (otro idioma) con el mismo estado de la exploración."""
        udp = self.ch_udp.isChecked()
        if udp:
            self.ch_udp.setChecked(False)          # libera el puerto para la ventana nueva
        w = Escaner(self.eg, udp)
        w.estado.x, w.estado.y, w.estado.R = self.estado.x, self.estado.y, self.estado.R.copy()
        w.cb_tipo.setCurrentIndex(self.cb_tipo.currentIndex())
        w.sp_f0.setValue(self.sp_f0.value())
        w.sp_prof.setValue(self.sp_prof.value())
        w.show()
        w._pedir()
        return w

    def keyPressEvent(self, ev):
        k = ev.key()
        fino = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        paso, ang = (1.0, 1.0) if fino else (4.0, 4.0)
        acciones = {
            Qt.Key.Key_Left: dict(lateral=-paso), Qt.Key.Key_Right: dict(lateral=paso),
            Qt.Key.Key_Up: dict(elevacion=paso), Qt.Key.Key_Down: dict(elevacion=-paso),
            Qt.Key.Key_Q: dict(giro=-ang), Qt.Key.Key_E: dict(giro=ang),
            Qt.Key.Key_W: dict(balanceo=ang), Qt.Key.Key_S: dict(balanceo=-ang),
            Qt.Key.Key_A: dict(abanico=-ang), Qt.Key.Key_D: dict(abanico=ang),
        }
        if k in acciones:
            self._accion(**acciones[k])
        elif k == Qt.Key.Key_Space:
            self._congelar()
        elif k == Qt.Key.Key_N:
            self._perpendicular()
        elif k == Qt.Key.Key_M:
            self.ch_mov.toggle()
        elif k == Qt.Key.Key_B and self._es_matricial():
            self.ch_biplano.toggle()
        elif k == Qt.Key.Key_V:
            self._adquirir_volumen()
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        self.temporizador.stop()
        if self.udp:
            self.udp.detener()
        self.pool.waitForDone(5000)
        self.vista.close()
        super().closeEvent(ev)


def pv_elipsoide(semiejes, centro):
    import pyvista as pv
    m = pv.ParametricEllipsoid(*semiejes, u_res=64, v_res=40, w_res=0)
    return m.translate(np.asarray(centro, float), inplace=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Simulador de exploración obstétrica / obstetric scanning simulator")
    ap.add_argument("--eg", type=float, default=22.0)
    ap.add_argument("--udp", action="store_true", help="escuchar una sonda física por UDP")
    agregar_argumento(ap)
    a = ap.parse_args(argv)
    # Depuración: `kill -USR1 <pid>` imprime la pila de todos los hilos en la terminal
    import faulthandler, signal
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    app = QApplication(sys.argv[:1])
    idioma_inicial(a.idioma)
    w = Escaner(a.eg, a.udp)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
