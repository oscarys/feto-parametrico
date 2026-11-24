# Validación

**Español** · [English](validacion.en.md)

Todo lo de esta página se puede reproducir con los comandos indicados; las pruebas
automáticas (`pytest`) comprueban una parte en cada cambio.

## Superficie

`feto-malla 12 20 28 36 40 --informe -r 180`. CC y DBP se miden en un corte axial de la
cabeza, descontando el cuero cabelludo (borde externo del cráneo, como en Hadlock).
LCC = longitud cráneo-caudal aproximada; PFE = peso fetal estimado (Hadlock 1985).

| EG | DBP Hadlock → malla (mm) | CC Hadlock → malla (mm) | LCC (mm) | Volumen (cm³) | PFE (g) | Hermética |
|---|---|---|---|---|---|---|
| 12 | 17.3 → 17.2 | 68.0 → 67.1 | 52 | 12 | (fuera de rango) | sí |
| 20 | 46.3 → 45.8 | 176.8 → 174.8 | 154 | 294 | 336 | sí |
| 28 | 70.6 → 69.8 | 266.1 → 263.0 | 242 | 1191 | 1230 | sí |
| 36 | 88.3 → 87.4 | 327.9 → 324.2 | 314 | 2711 | 2828 | sí |
| 38 | 91.5 → 90.5 | 338.2 → 334.4 | 330 | 3160 | 3280 | sí |
| 40 | 94.2 → 93.1 | 346.1 → 342.2 | 344 | 3624 | 3725 | sí |

Con una densidad de ~1.04 g/cm³, el volumen queda a pocos por ciento del PFE desde
las 28 semanas y ~10 % por debajo a las 20 semanas.

## Ecografía simulada (22 semanas)

`feto-eco planos --eg 22` y `feto-eco cabeza --eg 22`. Medidas sobre el mapa de etiquetas
de la imagen simulada:

| Medida | Esperado | En la imagen |
|---|---|---|
| CC | 201.3 mm | 201.3 mm |
| DBP (externo-externo) | 52.9 mm | 52.9 mm |
| CA | 172.9 mm | 172.9 mm |
| LF | 38.4 mm | 40.4 mm (+5 %) |
| DTC (transcerebelar) | 23.6 mm | 23.8 mm |
| Cisterna magna | 5.1 mm | 5.3 mm |
| Hueso nasal (perfil) | 7.3 mm | 7.3 mm |

CC, DBP, CA y LF se comparan con Hadlock; DTC, cisterna magna y hueso nasal con los
nomogramas de [`cabeza.py`](modelo.md#cara-y-fosa-posterior). La CA se mide tras una
apertura morfológica que separa los brazos cuando tocan el abdomen.

La LF medida sale sistemáticamente ~5 % larga; la causa no está identificada todavía.

## Pie

La razón LF/pie es 1 en toda la gestación: el pie mide lo mismo que la LF de Hadlock
(pruebas `test_razon_femur_pie` y `test_pie_a_termino_como_recien_nacido`). A las 40
semanas da 77 mm.

* Joshi et al., *Nepalese Journal of Radiology*: la razón LF/pie es bastante constante
  durante la gestación.
* Ravisankar et al. 2025, doi:[10.7759/cureus.84515](https://doi.org/10.7759/cureus.84515):
  razón de 0.9 a 1 en todos los casos (17–25 semanas).
* Pie del recién nacido a término: 77.9 ± 4.2 mm (Kuponiyi y Ogunlesi 2023, doi:[10.4314/gmj.v57i3.11](https://doi.org/10.4314/gmj.v57i3.11)),
  coherente con 77 mm.
* Merz et al., *Ultraschall in der Medizin* 2000,
  doi:[10.1055/s-2000-12986](https://doi.org/10.1055/s-2000-12986), reportan una razón de
  ~1 hasta las 24 semanas que baja a 0.85 a las 41. Con la LF de Hadlock eso daría un pie
  de ~91 mm al término, más largo que el del recién nacido, por lo que no se usa.

## Anatomía

`test_organos_dentro_del_cuerpo` comprueba a 14, 22, 30 y 39 semanas que ningún
órgano (columna incluida) sobresale de la piel más de 0.3 mm.

## Hilos y VTK

`test_rutas_de_hilos_de_trabajo_no_cargan_vtk` comprueba que todo lo que calculan los
hilos de trabajo de `feto-visor` y `feto-escaner` (mallas, órganos, simulación) ni
siquiera importa VTK: VTK no es seguro entre hilos y crear objetos VTK fuera del hilo
de la interfaz llegó a bloquear la ventana.

## Traducciones

`test_i18n.py` comprueba que cada catálogo de traducción cubra todos los textos de la
interfaz que hay en el código, que no tenga claves sobrantes y que conserve cada
`{campo}` del texto fuente en español.
