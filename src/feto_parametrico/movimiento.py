# -*- coding: utf-8 -*-
"""
movimiento.py — Movimientos fetales en función del tiempo.

`Movimiento.en(t)` devuelve una `Postura` (feto3d) para el instante t (s):

* movimientos generales: deriva lenta y suave de todas las articulaciones
  (suma de senoides con frecuencias y fases aleatorias);
* patadas: extensión rápida de una pierna (rodilla y cadera) y regreso;
* sobresaltos de brazos;
* giros de cabeza;
* respiración fetal en episodios (~0.8–1 Hz);
* latido cardiaco (~140 lpm por omisión);
* pequeño balanceo global del feto en el líquido.

Las amplitudes son ilustrativas, no medidas de cinemática fetal.

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .feto3d import Postura


def _campana(t, t0, dur):
    """Pulso suave (sin²) de duración `dur` que empieza en t0; 0 fuera de él."""
    x = (t - t0) / dur
    return math.sin(math.pi * x) ** 2 if 0.0 <= x <= 1.0 else 0.0


@dataclass
class Evento:
    tipo: str          # "patada" | "brazo" | "giro_cabeza"
    t0: float
    dur: float
    lado: int = 0      # 0 izquierda, 1 derecha
    amp: float = 1.0


@dataclass
class Movimiento:
    semilla: int = 0
    duracion: float = 10.0              # s, para generar eventos aleatorios
    fc_lpm: float = 140.0               # frecuencia cardiaca
    fr_hz: float = 0.9                  # frecuencia respiratoria en los episodios
    tasa_patadas: float = 0.25          # eventos por segundo
    tasa_brazos: float = 0.15
    tasa_giros: float = 0.08
    intensidad: float = 1.0             # escala de los movimientos generales
    eventos: list = field(default_factory=list)
    base: Postura = field(default_factory=Postura)

    def __post_init__(self):
        rng = np.random.default_rng(self.semilla)
        self._rng = rng
        # deriva lenta: para cada grado de libertad, 3 senoides
        self._deriva = {}
        amps = {"flex_cabeza": 6, "giro_cabeza": 12, "incl_cabeza": 4, "curv_tronco": 5,
                "cadera0": 8, "cadera1": 8, "rodilla0": 10, "rodilla1": 10,
                "hombro0": 10, "hombro1": 10, "codo0": 12, "codo1": 12,
                "giro_global": 6, "cabeceo_global": 3}
        for k, a in amps.items():
            f = rng.uniform(0.04, 0.35, 3)
            ph = rng.uniform(0, 2 * np.pi, 3)
            w = rng.dirichlet(np.ones(3))
            self._deriva[k] = (a, f, ph, w)
        self._fase_card0 = rng.uniform()
        # episodios de respiración: activos ~50 % del tiempo
        self._resp_on = rng.uniform(0, 2 * np.pi)
        if not self.eventos:
            self.eventos = self._eventos_aleatorios()

    def _eventos_aleatorios(self):
        rng, ev = self._rng, []
        for tipo, tasa, dur in [("patada", self.tasa_patadas, (0.6, 1.0)),
                                ("brazo", self.tasa_brazos, (0.5, 0.9)),
                                ("giro_cabeza", self.tasa_giros, (1.5, 2.5))]:
            t = rng.exponential(1 / tasa) if tasa > 0 else self.duracion + 1
            while t < self.duracion:
                ev.append(Evento(tipo, t, rng.uniform(*dur), int(rng.integers(2)),
                                 rng.uniform(0.6, 1.0) * rng.choice([-1, 1]) if tipo == "giro_cabeza"
                                 else rng.uniform(0.6, 1.0)))
                t += rng.exponential(1 / tasa)
        return ev

    def _d(self, k, t):
        a, f, ph, w = self._deriva[k]
        return self.intensidad * a * float(np.sum(w * np.sin(2 * np.pi * f * t + ph)))

    def en(self, t: float) -> Postura:
        b = self.base
        cad = [b.cadera[i] + self._d(f"cadera{i}", t) for i in range(2)]
        rod = [b.rodilla[i] + self._d(f"rodilla{i}", t) for i in range(2)]
        hom = [b.hombro[i] + self._d(f"hombro{i}", t) for i in range(2)]
        cod = [b.codo[i] + self._d(f"codo{i}", t) for i in range(2)]
        giro_cab = b.giro_cabeza + self._d("giro_cabeza", t)
        for e in self.eventos:
            g = _campana(t, e.t0, e.dur)
            if g == 0:
                continue
            if e.tipo == "patada":
                rod[e.lado] -= 85 * e.amp * g
                cad[e.lado] -= 45 * e.amp * g
            elif e.tipo == "brazo":
                hom[e.lado] += 50 * e.amp * g
                cod[e.lado] -= 60 * e.amp * g
            elif e.tipo == "giro_cabeza":
                giro_cab += 35 * e.amp * g
        # respiración: senoide modulada por episodios lentos
        env = max(0.0, math.sin(0.25 * t + self._resp_on))
        resp = env * math.sin(2 * math.pi * self.fr_hz * t)
        fase = (self._fase_card0 + self.fc_lpm / 60.0 * t) % 1.0
        return replace(
            b, flex_cabeza=b.flex_cabeza + self._d("flex_cabeza", t),
            giro_cabeza=giro_cab, incl_cabeza=b.incl_cabeza + self._d("incl_cabeza", t),
            curv_tronco=b.curv_tronco + self._d("curv_tronco", t),
            cadera=tuple(cad), rodilla=tuple(rod), hombro=tuple(hom), codo=tuple(cod),
            resp=resp, fase_card=fase,
            giro_global=b.giro_global + self._d("giro_global", t),
            cabeceo_global=b.cabeceo_global + self._d("cabeceo_global", t),
            desplaz=tuple(np.asarray(b.desplaz) + 1.5 * np.array(
                [math.sin(0.3 * t), math.sin(0.23 * t + 1), math.sin(0.17 * t + 2)]) * self.intensidad))


def guion_demostracion(duracion=6.0, semilla=3) -> Movimiento:
    """Movimiento con eventos fijos y visibles: patada, brazo y giro de cabeza."""
    ev = [Evento("patada", 0.8, 0.9, 0, 1.0), Evento("brazo", 2.2, 0.8, 1, 0.9),
          Evento("giro_cabeza", 3.0, 2.2, 0, 1.0), Evento("patada", 4.3, 0.8, 1, 0.9)]
    return Movimiento(semilla=semilla, duracion=duracion, eventos=ev, intensidad=0.8)
