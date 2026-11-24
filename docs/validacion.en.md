# Validation

[Español](validacion.md) · **English**

Everything on this page can be reproduced with the commands given; the automated tests
(`pytest`) check part of it on every change.

## Surface

`feto-malla 12 20 28 36 40 --informe -r 180`. HC and BPD are measured on an axial section
of the head, subtracting the scalp (outer edge of the skull, as in Hadlock). CRL = approximate
crown-rump length; EFW = estimated fetal weight (Hadlock 1985).

| GA (weeks) | BPD Hadlock → mesh (mm) | HC Hadlock → mesh (mm) | CRL (mm) | Volume (cm³) | EFW (g) | Watertight |
|---|---|---|---|---|---|---|
| 12 | 17.3 → 17.2 | 68.0 → 67.2 | 52 | 12 | (out of range) | yes |
| 20 | 46.3 → 45.8 | 176.8 → 174.8 | 154 | 297 | 336 | yes |
| 28 | 70.6 → 69.8 | 266.1 → 263.1 | 242 | 1208 | 1230 | yes |
| 36 | 88.3 → 87.4 | 327.9 → 324.2 | 314 | 2763 | 2828 | yes |
| 38 | 91.5 → 90.5 | 338.2 → 334.4 | 330 | 3224 | 3280 | yes |
| 40 | 94.2 → 93.1 | 346.1 → 342.3 | 344 | 3701 | 3725 | yes |

With a density of ~1.04 g/cm³, the volume is within a few percent of the EFW from 28
weeks on, and ~10 % low at 20 weeks.

## Simulated ultrasound (22 weeks)

`feto-eco planos --eg 22`. Measurements on the label map of the simulated image:

| Measurement | Hadlock | On the image |
|---|---|---|
| HC | 201.3 mm | 201.3 mm |
| BPD (outer–outer) | 52.9 mm | 52.9 mm |
| AC | 172.9 mm | 172.6 mm |
| FL | 38.4 mm | 40.4 mm (+5 %) |

FL measured on the image is consistently ~5 % long; the cause has not been identified yet.

## Foot

The FL/foot ratio is 1 throughout gestation: the foot is as long as Hadlock's FL
(tests `test_razon_femur_pie` and `test_pie_a_termino_como_recien_nacido`). At 40 weeks
this gives 77 mm.

* Joshi et al., *Nepalese Journal of Radiology*: the FL/foot ratio is fairly constant
  throughout gestation.
* Ravisankar et al. 2025, doi:[10.7759/cureus.84515](https://doi.org/10.7759/cureus.84515):
  ratio between 0.9 and 1 in all cases (17–25 weeks).
* Term newborn foot length: 77.9 ± 4.2 mm (Kuponiyi and Ogunlesi 2023, doi:[10.4314/gmj.v57i3.11](https://doi.org/10.4314/gmj.v57i3.11)),
  consistent with 77 mm.
* Merz et al., *Ultraschall in der Medizin* 2000,
  doi:[10.1055/s-2000-12986](https://doi.org/10.1055/s-2000-12986), report a ratio of ~1
  up to 24 weeks falling to 0.85 at 41. With Hadlock's FL that would give a ~91 mm foot at
  term, longer than a newborn's, so it is not used.

## Anatomy

`test_organos_dentro_del_cuerpo` checks at 14, 22, 30 and 39 weeks that no organ (spine
included) protrudes from the skin by more than 0.3 mm.

## Threads and VTK

`test_rutas_de_hilos_de_trabajo_no_cargan_vtk` checks that nothing computed by the worker
threads of `feto-visor` and `feto-escaner` (meshes, organs, simulation) even imports
VTK: VTK is not thread-safe, and creating VTK objects outside the GUI thread used to
freeze the window.

## Translations

`test_i18n.py` checks that every translation catalog covers all the interface texts in
the code, has no stale keys, and keeps every `{field}` of the Spanish source text.
