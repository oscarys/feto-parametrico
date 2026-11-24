# -*- coding: utf-8 -*-
"""
feto_pv.py — Utilidades PyVista compartidas por el visor (apps/visor.py) y
los renders (cli/render_pyvista.py).

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import numpy as np

from .i18n import N_
from .superficie import malla_fetal, medir


class _PyVistaPerezoso:
    """Importa PyVista (y VTK) sólo al crear el primer objeto VTK. Así las rutas
    de NumPy que usan los hilos de trabajo ni siquiera cargan VTK."""

    def __getattr__(self, nombre):
        import pyvista
        return getattr(pyvista, nombre)


pv = _PyVistaPerezoso()

COLOR_PIEL = (0.93, 0.74, 0.64)
COLOR_CC = "#d1495b"        # contorno cefálico
COLOR_DBP = "#00798c"       # diámetro biparietal
COLOR_LF = "#edae49"        # fémur


def a_pyvista(malla) -> pv.PolyData:
    """trimesh.Trimesh → pyvista.PolyData (con normales por vértice)."""
    caras = np.column_stack([np.full(len(malla.faces), 3), malla.faces]).ravel()
    pd = pv.PolyData(np.asarray(malla.vertices, dtype=np.float32), caras)
    return pd.compute_normals(cell_normals=False, auto_orient_normals=True)


def curvatura_suavizada(malla: pv.PolyData, pasadas: int = 8) -> np.ndarray:
    """Curvatura media sin el moteado del muestreo en vóxeles: se calcula sobre
    una copia suavizada (Taubin) y luego se promedia con los vecinos."""
    from scipy.sparse import coo_matrix, diags
    lisa = malla.smooth_taubin(n_iter=60, pass_band=0.05)
    k = lisa.curvature("mean")
    caras = malla.faces.reshape(-1, 4)[:, 1:]
    i = np.concatenate([caras[:, 0], caras[:, 1], caras[:, 2]])
    j = np.concatenate([caras[:, 1], caras[:, 2], caras[:, 0]])
    n = malla.n_points
    A = coo_matrix((np.ones(2 * len(i)), (np.r_[i, j], np.r_[j, i])), shape=(n, n)).tocsr()
    A = A + diags(np.ones(n))
    W = diags(1.0 / np.asarray(A.sum(1)).ravel()) @ A
    for _ in range(pasadas):
        k = W @ k
    return k


def generar(eg: float, resolucion: int = 140, vtk: bool = True) -> dict:
    """Malla + biometría + medidas en un solo diccionario.

    Con vtk=False no se crea ningún objeto VTK (para hilos de trabajo); el
    hilo de la interfaz debe agregar después datos["pv"] = a_pyvista(datos["trimesh"])."""
    malla, info = malla_fetal(eg, resolucion, devolver_info=True)
    med = medir(malla, info)
    datos = {"eg": eg, "trimesh": malla, "info": info, "med": med}
    if vtk:
        datos["pv"] = a_pyvista(malla)
    return datos


def actores_biometria(datos: dict) -> dict[str, pv.PolyData]:
    """Geometría auxiliar: contorno de la CC, segmento del DBP y fémures."""
    med, info = datos["med"], datos["info"]
    escala = info["DBP"]
    out = {}
    if med["contorno_cc"] is not None:
        lazo = np.asarray(med["contorno_cc"])
        out["cc"] = pv.Spline(lazo, len(lazo)).tube(radius=0.012 * escala)
        a, b = med["extremos_dbp"]
        out["dbp"] = pv.Line(a, b).tube(radius=0.012 * escala)
        c, n = med["plano_cc"]
        out["plano"] = pv.Disc(center=c, normal=n, inner=0, outer=0.62 * info["OFD"], c_res=64)
    tubos = [pv.Line(a, b).tube(radius=0.035 * info["LF"]) for a, b in info["femures"]]
    out["lf"] = tubos[0].merge(tubos[1])
    return out


def agregar_feto(p: pv.Plotter, datos: dict, *, color=COLOR_PIEL, opacidad=1.0,
                 biometria=False, aristas=False, escalar=None, cmap="coolwarm",
                 nombre="feto", render=True):
    """Añade el feto (y opcionalmente la biometría) a un plotter."""
    malla = datos["pv"]
    kw = dict(smooth_shading=True, specular=0.25, specular_power=20,
              diffuse=0.85, ambient=0.15, opacity=opacidad, name=nombre,
              show_edges=aristas, edge_color="#6b4a3c", line_width=0.3, render=False)
    if escalar == "curvatura":
        if "_curv" not in datos:                      # se calcula una sola vez por malla
            curv = curvatura_suavizada(malla)
            m2 = malla.copy(); m2["curvatura media (1/mm)"] = curv
            datos["_curv"] = (m2, float(np.percentile(np.abs(curv), 97)))
        malla, lim = datos["_curv"]
        p.add_mesh(malla, scalars="curvatura media (1/mm)", cmap=cmap,
                   clim=(-lim, lim), **kw)
    else:
        p.add_mesh(malla, color=color, **kw)
    if biometria:
        if "_bio" not in datos:
            datos["_bio"] = actores_biometria(datos)
        b = datos["_bio"]
        if "plano" in b:
            p.add_mesh(b["plano"], color=COLOR_CC, opacity=0.12, name=nombre + "_plano", render=False)
            p.add_mesh(b["cc"], color=COLOR_CC, name=nombre + "_cc", render=False)
            p.add_mesh(b["dbp"], color=COLOR_DBP, name=nombre + "_dbp", render=False)
        p.add_mesh(b["lf"], color=COLOR_LF, name=nombre + "_lf", render=False)
    if render:
        p.render()


# Nombres para la leyenda (por tejido) y para los rótulos (por órgano)
LEYENDA = {"calota": N_("Calota"), "hueso": N_("Huesos"), "cerebro": N_("Encéfalo"),
           "lcr": N_("LCR (ventrículos, CSP, cisterna)"), "coroides": N_("Plexos coroideos"),
           "talamo": N_("Tálamos"), "cerebelo": N_("Cerebelo"), "vermis": N_("Vermis"), "vitreo": N_("Ojos"), "cristalino": N_("Cristalino"),
           "miocardio": N_("Corazón (miocardio)"), "sangre": N_("Sangre (cámaras, vasos)"),
           "pulmon": N_("Pulmones"), "higado": N_("Hígado"), "liquido": N_("Estómago y vejiga"),
           "rinon": N_("Riñones"), "intestino": N_("Intestino")}

# órgano -> (nombre mostrado, punto de anclaje en coordenadas locales relativas a los semiejes)
ROTULOS = {"calota": (N_("Calota"), (0.0, 0.0, 1.0)), "encefalo": (N_("Encéfalo"), (0.45, 0.0, 0.55)),
           "ventriculo_i": (N_("Ventrículo lateral"), None), "talamo_i": (N_("Tálamo"), None),
           "cerebelo": (N_("Cerebelo"), None), "csp": (N_("CSP"), None), "coroides_i": (N_("Plexo coroideo"), None),
           "ojo_i": (N_("Ojo"), None), "corazon": (N_("Corazón"), None), "pulmon_i": (N_("Pulmón"), None),
           "higado": (N_("Hígado"), None), "estomago": (N_("Estómago"), None), "rinon_i": (N_("Riñón"), None),
           "vejiga": (N_("Vejiga"), None), "intestino": (N_("Intestino"), None), "aorta": (N_("Aorta"), None),
           "vena_umbilical": (N_("Vena umbilical"), None), "vertebra13": (N_("Columna"), None),
           "costilla3+12": (N_("Costilla"), None), "femur_i": (N_("Fémur"), None), "tibia_i": (N_("Tibia"), None),
           "humero_i": (N_("Húmero"), None), "cubito_i": (N_("Cúbito"), None),
           "cisterna_magna": (N_("Cisterna magna"), None), "hueso_nasal": (N_("Hueso nasal"), None),
           "mandibula4": (N_("Mandíbula"), None), "cristalino_i": (N_("Cristalino"), None)}


def organos_cuerpo(eg: float) -> dict:
    """Órganos (feto3d, postura de reposo) en coordenadas del cuerpo fetal:
    {"mallas": [(tejido, malla, color, opacidad)], "rotulos": [(nombre, punto)]}.
    Para dibujarlos sobre la malla de `generar`, trasladar por
    datos["info"]["desplazamiento"]."""
    from .feto3d import construir_feto
    from .vista3d import mallas_organos_np
    org = construir_feto(eg).organos
    rotulos = []
    for pr in org:
        if pr.nombre not in ROTULOS:
            continue
        nombre, ancla = ROTULOS[pr.nombre]
        if pr.tipo == "cono":
            pt = 0.5 * (np.asarray(pr.p["a"]) + np.asarray(pr.p["b"]))
        else:
            loc = np.asarray(ancla or (0, 0, 0)) * np.asarray(pr.p["semiejes"])
            pt = pr.centro + pr.R @ loc
        rotulos.append((nombre, pt))
    # (V, F) de NumPy: se puede llamar desde un hilo de trabajo
    return {"mallas": mallas_organos_np(org), "rotulos": rotulos}


def agregar_organos(p: pv.Plotter, datos: dict, organos: dict, nombre="feto_org",
                    opacidad=1.0, rotulos=False):
    d = datos["info"]["desplazamiento"]
    clave = id(organos)
    if datos.get("_org_clave") != clave:       # mallas trasladadas, una vez por malla/edad
        from .mallas_np import a_pv, trasladar
        datos["_org"] = [(n, a_pv(trasladar(m, d)), c, op) for n, m, c, op in organos["mallas"]]
        datos["_org_clave"] = clave
    for n, m, color, op in datos["_org"]:
        p.add_mesh(m, color=color, opacity=op * opacidad,
                   smooth_shading=True, specular=0.3, name=f"{nombre}_{n}",
                   show_scalar_bar=False, render=False)
    if rotulos:
        pts = np.array([pt + d for _, pt in organos["rotulos"]])
        from .i18n import tr
        p.add_point_labels(pts, [tr(n) for n, _ in organos["rotulos"]], name=f"{nombre}_rotulos",
                           font_size=11, point_size=6, point_color="#222222",
                           text_color="#111111", shape="rounded_rect", shape_color="white",
                           shape_opacity=0.75, margin=2, always_visible=True, render=False)



def texto_biometria(datos: dict) -> str:
    i, m = datos["info"], datos["med"]
    from .i18n import tr
    return tr("{eg:g} semanas\nDBP {dbp:.1f} mm   CC {cc:.1f} mm\nCA {ca:.1f} mm   LF {lf:.1f} mm\n"
              "LCC ≈ {lcc:.0f} mm   PFE {pfe:.0f} g", eg=datos["eg"], dbp=i["DBP"], cc=i["CC"],
              ca=i["CA"], lf=i["LF"], lcc=m["LCC_aprox"], pfe=i["PFE_g"])


def camara_lateral(p: pv.Plotter, radio: float, centro=(0, 0, 0), azimut=-90.0,
                   elevacion=12.0, distancia=3.2):
    """Cámara fija (no depende del tamaño del feto): útil para comparar edades."""
    az, el = np.radians(azimut), np.radians(elevacion)
    d = distancia * radio
    pos = np.array(centro) + d * np.array([np.cos(el) * np.cos(az),
                                          np.cos(el) * np.sin(az), np.sin(el)])
    p.camera_position = [tuple(pos), tuple(centro), (0, 0, 1)]
