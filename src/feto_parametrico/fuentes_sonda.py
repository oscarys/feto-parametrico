# -*- coding: utf-8 -*-
"""
fuentes_sonda.py — Entrada de una sonda física (o emulada) por UDP.

Protocolo: un datagrama UDP por muestra con un objeto JSON (UTF-8). Todos
los campos son opcionales; se aplican los que lleguen.

    {"u": -0.2, "v": 0.35,              posición normalizada en el abdomen físico,
                                         -1..1 (u: izquierda materna +, v: craneal +)
     "x": 12.5, "y": -40.0,             o bien posición en mm del mundo virtual
     "q": [w, x, y, z],                 orientación absoluta de la IMU (cuaternión)
     "giro": 30, "balanceo": -5,        o bien ángulos (grados) respecto a la
     "abanico": 10,                       normal de la piel
     "evento": "congelar" | "calibrar" | "descongelar"}

Un ESP32 con una IMU de 9 ejes (BNO055 o BNO085) da "q" directamente; la
posición puede salir de una cámara sobre el maniquí (marcador ArUco en la
sonda), de un panel resistivo o de un rastreador magnético.

Emulador para probar sin hardware:

    feto-sonda-emulador --destino 127.0.0.1 --puerto 5005

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import time

PUERTO = 5005

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtNetwork import QHostAddress, QUdpSocket

    class FuenteUDP(QObject):
        """Escucha datagramas JSON y emite cada muestra como diccionario."""
        muestra = pyqtSignal(dict)
        error = pyqtSignal(str)

        def __init__(self, puerto: int = PUERTO, parent=None):
            super().__init__(parent)
            self.puerto = puerto
            self.sock = QUdpSocket(self)
            self.sock.readyRead.connect(self._leer)
            self.n = 0

        def iniciar(self) -> bool:
            ok = self.sock.bind(QHostAddress.SpecialAddress.AnyIPv4, self.puerto)
            if not ok:
                self.error.emit(f"No se pudo abrir el puerto UDP {self.puerto}")
            return ok

        def detener(self):
            self.sock.close()

        def _leer(self):
            ultimo = None
            while self.sock.hasPendingDatagrams():
                dg = self.sock.receiveDatagram()
                try:
                    d = json.loads(bytes(dg.data()).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(d, dict):
                    if "evento" in d:              # los eventos no se descartan
                        self.muestra.emit(d)
                    else:
                        ultimo = d                 # de la posición sólo importa la última
            if ultimo is not None:
                self.n += 1
                self.muestra.emit(ultimo)
except ImportError:          # el emulador funciona sin Qt
    FuenteUDP = None


def _cuaternion_eje_angulo(eje, ang):
    s = math.sin(ang / 2)
    n = math.sqrt(sum(e * e for e in eje))
    return [math.cos(ang / 2)] + [s * e / n for e in eje]


def _producto(q1, q2):
    w1, x1, y1, z1 = q1; w2, x2, y2, z2 = q2
    return [w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2]


def emular(destino="127.0.0.1", puerto=PUERTO, hz=30.0, modo="imu"):
    """Recorre el abdomen en una trayectoria de Lissajous, girando la sonda."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t0 = time.time()
    print(f"Enviando a {destino}:{puerto} ({modo}). Ctrl+C para terminar.")
    try:
        while True:
            t = time.time() - t0
            msg = {"u": 0.45 * math.sin(0.21 * t), "v": 0.55 * math.sin(0.13 * t + 0.6)}
            giro = math.radians(60 * math.sin(0.09 * t))
            bal = math.radians(10 * math.sin(0.4 * t))
            if modo == "imu":
                # IMU apuntando hacia abajo (eje z del sensor = haz), girando y balanceándose
                q = _producto(_cuaternion_eje_angulo((0, 0, 1), giro),
                              _cuaternion_eje_angulo((0, 1, 0), bal))
                msg["q"] = q
            else:
                msg.update(giro=math.degrees(giro), balanceo=math.degrees(bal))
            if int(t) % 20 == 0 and (t % 1) < 1 / hz:
                msg["evento"] = "calibrar" if t < 1 else None
                if msg["evento"] is None:
                    del msg["evento"]
            s.sendto(json.dumps(msg).encode(), (destino, puerto))
            time.sleep(1 / hz)
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Emulador de sonda física por UDP")
    ap.add_argument("--destino", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=PUERTO)
    ap.add_argument("--hz", type=float, default=30.0)
    ap.add_argument("--modo", choices=["imu", "angulos"], default="imu")
    a = ap.parse_args(argv)
    emular(a.destino, a.puerto, a.hz, a.modo)


if __name__ == "__main__":
    main()
