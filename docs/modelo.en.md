# The model

[Español](modelo.md) · **English**

Two levels of detail share the same body geometry:

* **Surface** (`superficie.py`): the fetal skin as a watertight triangle mesh, for
  export (STL/OBJ/PLY) or viewing in `feto-visor`.
* **3D scene** (`feto3d.py`): the articulated fetus with internal organs, inside a uterus
  with placenta, umbilical cord and maternal abdominal wall. Every point in space gets a
  tissue label; this is the input to the ultrasound simulator.

In the resting pose both build exactly the same body parts (a test checks this
indirectly: the organs stay inside the skin).

Code identifiers are in Spanish; see the glossary in the [English README](../README.en.md#glossary-of-spanish-names).

## Biometry

Gestational age (GA, `eg` in the code, in weeks) sets four measurements through the
regressions of Hadlock et al. ([1984](https://doi.org/10.1148/radiology.152.2.6739822)), valid roughly from 12 to 40 weeks:

| Measurement | Regression (cm) |
|---|---|
| BPD | −3.08 + 0.41·GA − 0.000061·GA³ |
| HC | −11.48 + 1.56·GA − 0.0002548·GA³ |
| AC | −13.3 + 1.61·GA − 0.00998·GA² |
| FL | −3.91 + 0.427·GA − 0.0034·GA² |

The estimated fetal weight (EFW) comes from Hadlock et al. ([1985](https://doi.org/10.1016/0002-9378(85)90298-4)) using HC, AC and FL,
and is used to check the mesh volume.

## Geometry

| Part | How it is built |
|---|---|
| Skull | ellipsoid with transverse semi-axis BPD/2 and an occipitofrontal diameter chosen so that its perimeter (Ramanujan) equals HC: the **outer edge of the skull** matches Hadlock |
| Scalp | the head skin lies `1.2 + 0.02·BPD` mm outside the skull |
| Face | profile with nose, lips, chin, cheeks and eyelids (see [Face and posterior fossa](#face-and-posterior-fossa)); the head can flex, turn and tilt |
| Trunk | pelvis, abdomen and thorax along an arched spine; the abdominal cross-section has perimeter AC |
| Limbs | rounded cones; femur with 0.04·FL of cartilage at each end (the ossified shaft measures FL); tibia, humerus and ulna proportional to FL |
| Hands and feet | palm with four slightly spread three-phalanx fingers and a two-phalanx thumb, closed with `Postura.puno` (0 open, 1 fist); foot with heel, sole and five fanned toes (`extremidades.py`, shared with the 3D scene) |
| Foot | heel to toe = FL (FL/foot ratio = 1 throughout gestation) |
| Surface | smooth union of signed distance functions (SDF) → marching cubes → largest connected component → Taubin smoothing. Next to the skin the grid is twice as fine (`refinar=2`): the exact SDF is computed only within two voxels of the skin and interpolated elsewhere, so fingers and toes appear without paying for a full fine grid |

![Fetuses from 12 to 40 weeks at true scale](img/serie_crecimiento_en.png)

![Biometry on the model: HC plane, BPD and femurs](img/biometria_24s_en.png)

Proportions not covered by Hadlock (trunk length, limb thickness, flexion angles, etc.)
are heuristic and gathered in `Proporciones` so they can be edited.

## Organs (feto3d)

Head: calvarium (thickness from BPD), brain, falx, lateral ventricles with choroid
plexuses, thalami, cavum septi pellucidi, cerebellum (hemispheres and vermis), cisterna
magna, eyes with lens, orbits, nasal bone, maxilla, palate and mandible. Trunk:
four-chamber heart (axis at 40°), lungs, liver, stomach, umbilical vein, bowel, kidneys
and bladder. Great vessels: ascending aorta, arch and descending aorta; pulmonary trunk
and ductus arteriosus, reaching almost the same axial plane (the "V" of the
three-vessel view); superior vena cava and trachea. Umbilical arteries from the cord
insertion, on both sides of the bladder. Skeleton: spine (vertebral bodies and arches,
placed from the actual skin of the back so they stay inside the body at every age),
ribs, long bones (femur, tibia, fibula, humerus, ulna, radius), metacarpals,
metatarsals, phalanges and calcaneus.

![Organs at 22 weeks](img/organos_22s.png)

Maternal scene: skin, fat (configurable thickness) and muscle of the abdominal wall,
myometrium, amniotic fluid, placenta (a lens against the wall: anterior, posterior,
fundal or lateral) and an umbilical cord with two arteries and one vein in a helix.
Presentation (cephalic/breech) and the position of the fetal back are parameters
(`Materno`).

The acoustic properties of each tissue (impedance, attenuation, scattering) are in
`tejidos.py`; bone properties change with ossification according to GA.

## Face and posterior fossa

The face and the posterior fossa live in `cabeza.py` (head), shared by the surface
and the 3D scene. Positions are given in the head frame, normalized by the skull
semi-axes, so the face grows with the head:

| Structure | How it is built |
|---|---|
| Profile | the skull skin is trimmed in front of the glabella–chin line; forehead, nasal bridge and tip, nasal alae, lips, chin, cheeks and eyelids are smoothly joined onto a base face |
| Mouth, nostrils, closed eyes | slits **subtracted** from the surface (smooth SDF subtraction) |
| Facial bones | nasal bone (length by GA, with prenasal skin 0.61 × its length), maxillary and mandibular arches, mandibular rami, hard palate, orbits open in front |
| Eyes | vitreous and lens (anechoic with a bright rim) |
| Vault | calvarium and brain stop at the skull base; the face lies below it |
| Posterior fossa | cerebellar hemispheres (hypoechoic) and vermis (echogenic) with the nomogram TCD; the cerebellum is placed so that, in the transcerebellar plane, the cisterna magna fills the gap between the vermis and the occipital bone |

Reference measurements: TCD from `GA = 0.557·TCD + 8.84`
([Adelabu et al. 2024](https://doi.org/10.4103/jmu.jmu_116_22)); nasal bone from 5.7 mm at
18 weeks to 7.6 mm at 23 ([doi:10.1515/jpm-2014-0296](https://doi.org/10.1515/jpm-2014-0296)),
prenasal thickness 0.61 × nasal bone ([PubMed 21584886](https://pubmed.ncbi.nlm.nih.gov/21584886/));
cisterna magna 2.5 + 0.12·GA mm, within the normal 2–10 mm range.

The width of the face is not a fixed fraction of the skull: it is set by the binocular
(`BOD = 2.590 + 1.420·GA`) and interocular (`IOD = 2.304 + 0.510·GA`) distances of 595
fetuses from 15 to 40 weeks (*Fetal ocular distance in normal pregnancies*), which agree
with the MRI values of [Velasco-Annis et al. 2015](https://doi.org/10.1002/pd.4558)
(BOD 30.8 mm at 20 weeks). They give the spacing and size of the eyes, and eyelids,
cheeks, nose, lips, mouth, maxilla and mandible scale with them. Since BOD grows more
slowly than BPD, the face is relatively wider at mid-gestation than at term. The mandible
(temporomandibular joint to symphysis) follows Otto and Platt 1991:
`ML = −2.41 + 0.297·GA − 0.0027·GA²` cm. Eyes and eyelids are placed under the actual
skin (face or skull, whichever is further forward), with the eyelid half a millimetre
proud.

![The face in three-quarter view at 16, 24 and 32 weeks](img/cara_en.png)

## Movement

`Postura` (pose) controls the neck (flexion, turn, tilt), trunk curvature, hips, knees,
shoulders, elbows, breathing, cardiac phase and the global pose. `Movimiento.en(t)`
combines slow drift of every joint, kicks, arm startles, head turns, breathing episodes
(~0.9 Hz) and a heartbeat (140 bpm). The amplitudes are illustrative, not measured fetal
kinematics.

![Kick, arm startle and head turn](img/movimiento_en.gif)

## Limitations

* Primitive-based anatomy (ellipsoids and capsules): schematic face, hands and feet,
  simplified organ shapes; no heart valves.
* Outside 12–40 weeks the regressions are extrapolated (the program warns).
* The heuristic proportions are a reasonable starting point, not an anatomical reference.

Preview without VTK (matplotlib only), `feto-vista-previa`:

![Matplotlib preview](img/vista_previa_en.png)
