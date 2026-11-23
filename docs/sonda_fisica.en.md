# Physical probe

[Español](sonda_fisica.md) · **English**

`feto-escaner` can receive the position and orientation of a physical probe (for
example, a prop probe on a phantom abdomen) over the network. Input is decoupled from the
interface (`sonda_control.EstadoSonda`), so any hardware that produces the same fields
will work.

## Protocol

One UDP datagram per sample, to port 5005, containing a UTF-8 JSON object. All fields are
optional; whichever arrive are applied. Field names are Spanish.

| Field | Meaning |
|---|---|
| `u`, `v` | normalized position on the physical abdomen, −1…1 (`u`: maternal left +, `v`: cranial +) |
| `x`, `y` | or the position in mm in the virtual world |
| `q` | absolute IMU orientation as a quaternion `[w, x, y, z]` |
| `giro`, `balanceo`, `abanico` | or angles in degrees relative to the skin normal: rotation about the beam, rock, fan |
| `evento` | `"congelar"` (freeze), `"descongelar"` (unfreeze) or `"calibrar"` (calibrate) |

Example:

```json
{"u": -0.2, "v": 0.35, "q": [0.98, 0.0, 0.17, 0.1]}
```

## Calibration

On calibration (*Calibrate IMU* button or the `"calibrar"` event), the current IMU
orientation is taken to correspond to the current orientation of the virtual probe. For
example: hold both perpendicular to the skin with the marker toward the mother's right
and calibrate. From then on, IMU rotations are applied to the virtual probe.

## Testing without hardware

```bash
feto-escaner --udp            # listens on port 5005
feto-sonda-emulador           # in another terminal: sweeps the abdomen over UDP
feto-sonda-emulador --modo angulos --hz 20
```

## Hardware ideas

* Orientation: an ESP32 with a 9-axis IMU (BNO055 or BNO085), which outputs the quaternion directly.
* Position: a camera above the phantom tracking an ArUco marker on the probe, a resistive
  panel, or a magnetic tracker.
