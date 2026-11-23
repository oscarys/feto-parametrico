# Sonda física

**Español** · [English](sonda_fisica.en.md)

`feto-escaner` puede recibir la posición y orientación de una sonda física (por
ejemplo, una sonda de utilería sobre un abdomen de maniquí) por la red. La entrada está
desacoplada de la interfaz (`sonda_control.EstadoSonda`), así que cualquier hardware que
produzca los mismos campos sirve.

## Protocolo

Un datagrama UDP por muestra, al puerto 5005, con un objeto JSON en UTF-8. Todos los
campos son opcionales; se aplican los que lleguen.

| Campo | Significado |
|---|---|
| `u`, `v` | posición normalizada en el abdomen físico, −1…1 (`u`: izquierda materna +, `v`: craneal +) |
| `x`, `y` | o bien la posición en mm del mundo virtual |
| `q` | orientación absoluta de la IMU como cuaternión `[w, x, y, z]` |
| `giro`, `balanceo`, `abanico` | o bien ángulos en grados respecto a la normal de la piel |
| `evento` | `"congelar"`, `"descongelar"` o `"calibrar"` |

Ejemplo:

```json
{"u": -0.2, "v": 0.35, "q": [0.98, 0.0, 0.17, 0.1]}
```

## Calibración

Al calibrar (botón *Calibrar IMU* o evento `"calibrar"`), la orientación actual de la
IMU pasa a corresponder a la orientación actual de la sonda virtual. Por ejemplo:
poner ambas perpendiculares a la piel con la marca hacia la derecha materna y calibrar.
Desde ahí, las rotaciones de la IMU se aplican a la sonda virtual.

## Probar sin hardware

```bash
feto-escaner --udp            # escucha en el puerto 5005
feto-sonda-emulador           # en otra terminal: recorre el abdomen enviando UDP
feto-sonda-emulador --modo angulos --hz 20
```

## Ideas para el hardware

* Orientación: ESP32 con una IMU de 9 ejes (BNO055 o BNO085), que entrega el cuaternión directamente.
* Posición: una cámara sobre el maniquí que siga un marcador ArUco en la sonda, un
  panel resistivo o un rastreador magnético.
