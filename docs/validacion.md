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
| 12 | 17.3 → 17.2 | 68.0 → 67.2 | 52 | 12 | (fuera de rango) | sí |
| 20 | 46.3 → 45.8 | 176.8 → 174.8 | 154 | 297 | 336 | sí |
| 28 | 70.6 → 69.8 | 266.1 → 263.1 | 242 | 1208 | 1230 | sí |
| 36 | 88.3 → 87.4 | 327.9 → 324.2 | 314 | 2763 | 2828 | sí |
| 38 | 91.5 → 90.5 | 338.2 → 334.4 | 330 | 3224 | 3280 | sí |
| 40 | 94.2 → 93.1 | 346.1 → 342.3 | 344 | 3701 | 3725 | sí |

Con una densidad de ~1.04 g/cm³, el volumen queda a pocos por ciento del PFE desde
las 28 semanas y ~10 % por debajo a las 20 semanas.

## Ecografía simulada (22 semanas)

`feto-eco planos --eg 22`. Medidas sobre el mapa de etiquetas de la imagen simulada:

| Medida | Hadlock | En la imagen |
|---|---|---|
| CC | 201.3 mm | 201.3 mm |
| DBP (externo-externo) | 52.9 mm | 52.9 mm |
| CA | 172.9 mm | 172.6 mm |
| LF | 38.4 mm | 40.4 mm (+5 %) |

La LF medida sale sistemáticamente ~5 % larga; la causa no está identificada todavía.

## Pie

La razón LF/pie es 1.0 hasta las 24 semanas y baja linealmente a 0.85 a las 40
(prueba `test_razon_femur_pie`), de acuerdo con:

* Ultraschall in der Medizin 2000, doi:[10.1055/s-2000-12986](https://doi.org/10.1055/s-2000-12986):
  razón media ~1 hasta las 24 semanas y 0.85 al término.
* Joshi et al., *Nepalese Journal of Radiology* (razón LF/pie de 0.9–1.0 en la mayoría de los casos).

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
