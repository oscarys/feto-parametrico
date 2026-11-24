# -*- coding: utf-8 -*-
"""
feto3d.py — Feto 3D articulado con órganos, dentro de un útero con placenta,
cordón umbilical y pared abdominal materna. Cada punto del espacio recibe una
etiqueta de tejido (ver tejidos.py), una pieza a la que pertenece y sus
coordenadas locales en esa pieza (para anclar el moteado al tejido).

Sistemas de coordenadas (mm)
----------------------------
* Cuerpo fetal: x anterior (vientre), y izquierda del feto, z cefálico.
* Mundo (materno): x izquierda de la madre, y craneal, z anterior (hacia la
  piel del abdomen). El centro de la cavidad uterina está en el origen.

Uso básico
----------
    from .feto3d import Escena, Postura
    esc = Escena(22)                       # 22 semanas, postura de reposo
    etiq, pieza, local = esc.evaluar(P)    # P: (N, 3) en coordenadas del mundo

Licencia: GPL-3.0-or-later
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .superficie import (EG_MAX, EG_MIN, Proporciones, _marco, _unit, biometria, largo_pie,
                              sdf_cono_redondeado, sdf_elipsoide,
                              recortar, resta_suave, semieje_mayor_elipse, semiejes_por_perimetro,
                         union_suave)
from . import cabeza
from .tejidos import T, osificacion

GRANDE = 1e5      # "infinito" finito para la unión suave con piezas descartadas


# ---------------------------------------------------------------------------
# Postura
# ---------------------------------------------------------------------------

@dataclass
class Postura:
    """Ángulos en grados. Los pares son (izquierda, derecha)."""
    flex_cabeza: float = 30.0       # flexión del cuello (mentón al pecho)
    giro_cabeza: float = 0.0        # rotación de la cabeza (+ hacia la izquierda)
    incl_cabeza: float = 0.0        # inclinación lateral
    curv_tronco: float = 55.0       # curvatura total de la columna
    cadera: tuple = (115.0, 115.0)  # flexión de cadera (0 = extendida)
    abd_muslo: tuple = (0.30, 0.30)
    rodilla: tuple = (125.0, 125.0) # flexión de rodilla (0 = extendida)
    hombro: tuple = (30.0, 30.0)    # brazo: ángulo desde "abajo" hacia anterior
    abd_brazo: tuple = (0.05, 0.05)
    codo: tuple = (70.0, 70.0)      # flexión de codo (manos frente al pecho, cara libre)
    resp: float = 0.0               # movimiento respiratorio, -1..1
    fase_card: float = 0.0          # fase del ciclo cardiaco, 0..1
    giro_global: float = 0.0        # giro del feto sobre su eje longitudinal
    cabeceo_global: float = 0.0     # inclinación del eje longitudinal
    desplaz: tuple = (0.0, 0.0, 0.0)  # traslación en el mundo (mm)


def _rot(eje, ang_rad):
    """Matriz de rotación (Rodrigues) alrededor de `eje`."""
    k = _unit(eje)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(ang_rad) * K + (1 - math.cos(ang_rad)) * K @ K


# ---------------------------------------------------------------------------
# Primitivas con marco local
# ---------------------------------------------------------------------------

class Prim:
    """Primitiva geométrica con marco local (centro, R: columnas = ejes)."""

    def __init__(self, nombre, tipo, etiqueta=None, k=0.0, resta=False, **p):
        """`resta`: la pieza se sustrae (suavemente) de la superficie corporal.
        p["corte"] = (n, d) en el marco local: sólo se conserva n·q <= d."""
        self.nombre, self.tipo, self.etiqueta, self.k = nombre, tipo, etiqueta, k
        self.resta = resta
        self.p = p
        if tipo == "cono":
            a, b = np.asarray(p["a"], float), np.asarray(p["b"], float)
            eje = b - a
            perp = np.cross(eje, [0.0, 0.0, 1.0])
            if np.linalg.norm(perp) < 1e-6 * np.linalg.norm(eje):
                perp = np.cross(eje, [1.0, 0.0, 0.0])
            self.centro, self.R = a, _marco(perp, eje)
            r = max(p["ra"], p["rb"])
            self.lo, self.hi = np.minimum(a, b) - r, np.maximum(a, b) + r
        else:
            self.centro = np.asarray(p["centro"], float)
            self.R = np.asarray(p.get("R", np.eye(3)), np.float32)
            r = max(p["semiejes"])
            self.lo, self.hi = self.centro - r, self.centro + r

    def sdf(self, P):
        p = self.p
        if self.tipo == "elip":
            d = sdf_elipsoide(P, self.centro, p["semiejes"], self.R)
        elif self.tipo == "cono":
            return sdf_cono_redondeado(P, p["a"], p["b"], p["ra"], p["rb"])
        elif self.tipo == "cascara":           # elipsoide hueco de grosor dado
            ext = sdf_elipsoide(P, self.centro, p["semiejes"], self.R)
            inn = sdf_elipsoide(P, self.centro,
                                tuple(s - p["grosor"] for s in p["semiejes"]), self.R)
            d = np.maximum(ext, -inn)
        else:
            raise ValueError(self.tipo)
        if "corte" in p:
            d = recortar(d, self.local(P), p["corte"])
        return d

    def local(self, P):
        return (P - self.centro) @ self.R

    def en_caja(self, P, margen=0.0):
        return np.all((P >= self.lo - margen) & (P <= self.hi + margen), axis=1)

    def transformada(self, Rg, tg):
        """Copia de la primitiva llevada al mundo: x_mundo = Rg x + tg."""
        p = dict(self.p)
        if self.tipo == "cono":
            p["a"] = Rg @ np.asarray(p["a"]) + tg
            p["b"] = Rg @ np.asarray(p["b"]) + tg
        else:
            p["centro"] = Rg @ self.centro + tg
            p["R"] = (Rg @ self.R).astype(np.float32)
        return Prim(self.nombre, self.tipo, self.etiqueta, self.k, self.resta, **p)


# ---------------------------------------------------------------------------
# Feto articulado
# ---------------------------------------------------------------------------

@dataclass
class Feto:
    eg: float
    piezas: list          # superficie corporal (unión suave) -> tejido "fetal"
    organos: list         # se pintan en orden sobre el interior del cuerpo
    marcos: dict          # marcos anatómicos útiles (planos estándar)
    bio: dict


def construir_feto(eg: float, post: Postura | None = None,
                   prop: Proporciones | None = None) -> Feto:
    post = post or Postura()
    prop = prop or Proporciones()
    bio = biometria(eg)
    dbp, cc, ca, lf = bio["DBP"], bio["CC"], bio["CA"], bio["LF"]

    # ---------------- cabeza y tronco (mismas reglas que feto_parametrico)
    b_cab = dbp / 2
    a_cab = semieje_mayor_elipse(cc, b_cab)
    c_cab = prop.altura_cabeza * a_cab
    b_abd, a_abd = semiejes_por_perimetro(ca, prop.razon_ap_abdomen)
    L = prop.largo_tronco * (a_abd + b_abd)
    th = math.radians(post.curv_tronco)
    Rc = L / th
    C = np.array([Rc, 0.0, 0.0])
    Y = np.array([0.0, 1.0, 0.0])

    def columna(s):
        phi = -th / 2 + s * th
        p = C + Rc * np.array([-math.cos(phi), 0.0, math.sin(phi)])
        t = np.array([math.sin(phi), 0.0, math.cos(phi)])
        n = np.array([math.cos(phi), 0.0, -math.sin(phi)])
        return p, t, n

    def marco_tronco(s):
        p, t, n = columna(s)
        return p, np.column_stack([n, Y, t]).astype(np.float32)

    grosor = 1.0 + prop.engrosamiento_tardio * (eg - EG_MIN) / (EG_MAX - EG_MIN)
    fr = 1.0 + 0.03 * post.resp            # expansión torácica respiratoria
    piezas, organos = [], []

    for nombre, s, fx, fz in [("pelvis", 0.17, 0.85, 0.30),
                              ("abdomen", 0.45, 1.00, 0.34),
                              ("torax", 0.75, 0.95 * fr, 0.32)]:
        p, R = marco_tronco(s)
        piezas.append(Prim(nombre, "elip", k=0.25 * b_abd, centro=p,
                           semiejes=(a_abd * fx, b_abd * fx, L * fz), R=R))

    p_cue, t_cue, n_cue = columna(1.0)
    fl = math.radians(post.flex_cabeza)
    u0 = _unit(math.cos(fl) * t_cue + math.sin(fl) * n_cue)
    f0 = _unit(math.cos(fl) * n_cue - math.sin(fl) * t_cue)
    p_cab = p_cue + (prop.largo_cuello * dbp + 0.75 * c_cab) * u0 - 0.10 * a_cab * f0
    Rh = _rot(u0, math.radians(post.giro_cabeza)) @ np.column_stack([f0, np.cross(u0, f0), u0])
    Rh = _rot(Rh[:, 0], math.radians(post.incl_cabeza)) @ Rh
    f, yh, u = Rh[:, 0], Rh[:, 1], Rh[:, 2]
    Rh = Rh.astype(np.float32)

    piel = 1.2 + 0.02 * dbp      # cuero cabelludo: la CC se mide en el borde externo del cráneo

    def H(x, y, z):                      # punto en coordenadas de la cabeza
        return p_cab + x * a_cab * f + y * b_cab * yh + z * c_cab * u

    piezas += [
        Prim("cuello", "cono", k=0.15 * b_cab, a=p_cue - 0.1 * L * t_cue,
             b=p_cab - 0.5 * c_cab * u0, ra=0.55 * b_abd, rb=0.42 * b_cab),
        Prim("craneo", "elip", k=0.2 * b_cab, centro=p_cab,
             semiejes=(a_cab + piel, b_cab + piel, c_cab + piel), R=Rh,
             corte=cabeza.corte_cara(a_cab, c_cab)),
    ]
    geo_cab = cabeza.geometria(a_cab, b_cab, c_cab, eg)

    def desde_cabeza(e, resta=False):
        """Elemento de cabeza.geometria -> Prim en el cuerpo."""
        etq = T[e["tejido"]] if e["tejido"] else None
        if e["tipo"] == "cono":
            return Prim(e["nombre"], "cono", etq, k=e["k"], resta=resta, a=H(*e["a"]),
                        b=H(*e["b"]), ra=e["ra"], rb=e["rb"])
        extra = {k: e[k] for k in ("grosor", "corte") if k in e}
        R = (Rh @ e["R_local"]).astype(np.float32) if "R_local" in e else Rh
        return Prim(e["nombre"], e["tipo"], etq, k=e["k"], resta=resta, centro=H(*e["centro"]),
                    semiejes=e["semiejes"], R=R, **extra)

    piezas += [desde_cabeza(e) for e in geo_cab["piel"]]
    for lado in (+1, -1):
        piezas.append(Prim(f"oreja{lado:+d}", "elip", k=0.05 * b_cab,
                           centro=H(-0.08, 0.97 * lado, -0.1),
                           semiejes=(0.20 * a_cab, 0.06 * b_cab, 0.28 * c_cab), R=Rh))

    # ---------------- órganos de la cabeza (orden = prioridad de pintado)
    g_hueso = 0.6 + 0.03 * dbp                  # grosor de la calota
    sem_cal = (a_cab, b_cab, c_cab)             # borde externo del cráneo = CC, DBP
    sem_enc = tuple(s - g_hueso for s in sem_cal)
    at = 3.5 + 0.02 * dbp                       # semiancho del atrio ventricular (~constante)

    def EH(nombre, etq, x, y, z, sx, sy, sz, absoluto=False):
        s = (sx, sy, sz) if absoluto else (sx * a_cab, sy * b_cab, sz * c_cab)
        return Prim(nombre, "elip", etq, centro=H(x, y, z), semiejes=s, R=Rh)

    # bóveda: calota y encéfalo terminan en la base del cráneo (por debajo, la cara)
    n_base, d_base = cabeza.corte_base(a_cab, c_cab)
    base = dict(corte=(n_base, d_base))
    organos += [
        Prim("encefalo", "elip", T["cerebro"], centro=p_cab, semiejes=sem_enc, R=Rh, **base),
        Prim("hoz", "elip", T["hoz"], centro=H(0.0, 0, 0.30),
             semiejes=(0.78 * sem_enc[0], 0.35 + 0.004 * dbp, 0.55 * sem_enc[2]), R=Rh),
    ]
    organos += [desde_cabeza(e) for e in geo_cab["organos"]
                if not e["nombre"].startswith(("ojo_", "orbita_", "cristalino_"))]
    # la calota se pinta después de la fosa posterior: la cisterna magna llega al hueso
    organos.append(Prim("calota", "cascara", T["hueso"], centro=p_cab, semiejes=sem_cal,
                        grosor=g_hueso, R=Rh, **base))
    for lado, sfx in ((+1, "i"), (-1, "d")):
        organos += [
            EH(f"ventriculo_{sfx}", T["lcr"], -0.16, 0.33 * lado, 0.06,
               0.42 * a_cab, 0.65 * at, 0.16 * c_cab, absoluto=True),
            EH(f"coroides_{sfx}", T["coroides"], -0.40, 0.33 * lado, 0.04,
               0.15 * a_cab, 0.75 * at, 0.10 * c_cab, absoluto=True),
        ]
    # órbitas, ojos y cristalinos (en este orden: el ojo se pinta sobre la órbita)
    organos += [desde_cabeza(e) for e in geo_cab["organos"]
                if e["nombre"].startswith(("orbita_", "ojo_", "cristalino_"))]
    organos += [EH("talamo_i", T["talamo"], -0.04, 0.13, -0.02, 0.18, 0.11, 0.14),
                EH("talamo_d", T["talamo"], -0.04, -0.13, -0.02, 0.18, 0.11, 0.14),
                EH("csp", T["lcr"], 0.30, 0, 0.01, 0.08, 0.04, 0.07)]

    # ---------------- órganos del tronco
    def ET(nombre, etq, s, x, y, sx, sy, sz, desliz=0.0, rotz=0.0, escala=1.0):
        """Elipsoide en el marco del tronco a la altura s; x en unidades de
        a_abd (anterior +), y en unidades de b_abd (izquierda +), sz en L."""
        p, R = marco_tronco(s)
        R = (_rot(R[:, 2], math.radians(rotz)) @ R).astype(np.float32) if rotz else R
        c = p + x * a_abd * R[:, 0] + y * b_abd * Y + desliz * R[:, 2]
        return Prim(nombre, "elip", etq, centro=c, R=R,
                    semiejes=(sx * a_abd * escala, sy * b_abd * escala, sz * L * escala))

    diafragma = -1.5 * post.resp      # el hígado desciende al inspirar
    organos += [
        ET("pulmon_i", T["pulmon"], 0.74, -0.08, 0.48, 0.62, 0.40, 0.17, escala=fr),
        ET("pulmon_d", T["pulmon"], 0.74, -0.08, -0.48, 0.62, 0.40, 0.17, escala=fr),
        ET("intestino", T["intestino"], 0.31, 0.15, 0.0, 0.50, 0.60, 0.09),
        ET("higado", T["higado"], 0.53, 0.05, -0.22, 0.70, 0.62, 0.11, desliz=diafragma),
        ET("estomago", T["liquido"], 0.47, 0.20, 0.42, 0.24, 0.20, 0.07, desliz=diafragma),
        ET("rinon_i", T["rinon"], 0.40, -0.48, 0.38, 0.17, 0.15, 0.075),
        ET("rinon_d", T["rinon"], 0.40, -0.48, -0.38, 0.17, 0.15, 0.075),
        ET("vejiga", T["liquido"], 0.17, 0.25, 0.0, 0.22, 0.20, 0.06),
    ]

    # Corazón: 4 cámaras, eje rotado ~40° hacia la izquierda
    fase = post.fase_card % 1.0
    sist = math.sin(math.pi * fase / 0.4) if fase < 0.4 else 0.0     # sístole ventricular
    sv, sa = 1 - 0.20 * sist, 1 + 0.12 * sist - 0.15 * max(0.0, math.sin(math.pi * (fase - 0.8) / 0.2)) * (fase > 0.8)
    p_cor, Rt = marco_tronco(0.72)
    Rcor = (_rot(Rt[:, 2], math.radians(40)) @ Rt).astype(np.float32)
    c_cor = p_cor + 0.12 * a_abd * Rt[:, 0] + 0.10 * b_abd * Y
    r_c = 0.40 * 0.95 * min(a_abd, b_abd)
    xc, yc, zc = Rcor[:, 0], Rcor[:, 1], Rcor[:, 2]

    def EC(nombre, etq, x, y, z, sx, sy, sz, esc):
        return Prim(nombre, "elip", etq, centro=c_cor + r_c * (x * xc + y * yc + z * zc),
                    semiejes=(sx * r_c * esc, sy * r_c * esc, sz * r_c * esc), R=Rcor)

    organos += [
        EC("corazon", T["miocardio"], 0, 0, 0, 1.0, 1.1, 0.9, 1 - 0.04 * sist),
        EC("vi", T["sangre"], 0.30, 0.34, -0.05, 0.38, 0.27, 0.45, sv),
        EC("vd", T["sangre"], 0.32, -0.30, -0.05, 0.36, 0.27, 0.45, sv),
        EC("ai", T["sangre"], -0.40, 0.30, 0.05, 0.30, 0.27, 0.35, sa),
        EC("ad", T["sangre"], -0.38, -0.32, 0.05, 0.30, 0.27, 0.35, sa),
    ]
    # Aorta descendente (anterior a la columna)
    p1, _, n1 = columna(0.30); p2, _, n2 = columna(0.80)
    organos.append(Prim("aorta", "cono", T["sangre"], a=p1 - 0.50 * a_abd * n1,
                        b=p2 - 0.50 * a_abd * n2, ra=0.07 * a_abd, rb=0.08 * a_abd))
    # Inserción del cordón y vena umbilical intraabdominal
    p_ins, _, n_ins = columna(0.30)
    ins_cordon = p_ins + 0.88 * a_abd * n_ins
    h_c = organos[[o.nombre for o in organos].index("higado")].centro
    organos.append(Prim("vena_umbilical", "cono", T["sangre"], a=ins_cordon - 0.05 * a_abd * n_ins,
                        b=h_c + 0.25 * a_abd * Rt[:, 0], ra=0.06 * a_abd, rb=0.05 * a_abd))

    # Columna: cuerpos vertebrales y arcos posteriores. La profundidad se toma
    # de la piel real de la espalda (la superficie es una unión suave de
    # pelvis, abdomen y tórax, que no sigue exactamente el arco de la columna).
    tronco = list(piezas)

    def piel_posterior(P, N):
        """Distancia desde cada P hasta la piel siguiendo -N (bisección vectorizada)."""
        lo, hi = np.zeros(len(P)), np.full(len(P), 3.0 * a_abd)
        for _ in range(30):
            m = 0.5 * (lo + hi)
            Q = (P - m[:, None] * N).astype(np.float32)
            d = np.full(len(Q), GRANDE, np.float32)
            for pz in tronco:
                d = union_suave(d, pz.sdf(Q), pz.k)
            dentro = d < 0
            lo, hi = np.where(dentro, m, lo), np.where(dentro, hi, m)
        return 0.5 * (lo + hi)

    nv = 26
    esp = L / nv
    sa = (0.05 * a_abd, 0.04 * b_abd, 0.25 * esp)        # arco posterior
    sv = (0.10 * a_abd, 0.11 * b_abd, 0.30 * esp)        # cuerpo vertebral
    margen = 1.0 + 0.05 * a_abd                         # piel y músculo sobre los arcos
    s_vert = np.linspace(0.07, 0.95, nv)
    marcos_v = [marco_tronco(s) for s in s_vert]
    T_posts = piel_posterior(np.array([m[0] for m in marcos_v]),
                             np.array([m[1][:, 0] for m in marcos_v]))
    for i, ((p, R), T_post) in enumerate(zip(marcos_v, T_posts)):
        n = R[:, 0]
        prof_arco = min(0.86 * a_abd, T_post - margen - sa[0])
        prof_cuerpo = prof_arco - 0.16 * a_abd
        organos.append(Prim(f"vertebra{i}", "elip", T["hueso"], R=R,
                            centro=p - prof_cuerpo * n, semiejes=sv))
        for lado in (+1, -1):
            organos.append(Prim(f"arco{i}{lado:+d}", "elip", T["hueso"], R=R,
                                centro=p - prof_arco * n + lado * 0.09 * b_abd * Y,
                                semiejes=sa))

    # Costillas: arcos desde la columna hasta la pared anterolateral
    r_cost = max(0.45, 0.022 * b_abd)
    for j, s in enumerate(np.linspace(0.62, 0.90, 7)):
        p, t, n = columna(s)
        k = math.sqrt(max(0.05, 1 - ((s - 0.75) / 0.32) ** 2))
        A, B = 0.86 * 0.95 * fr * a_abd * k, 0.86 * 0.95 * fr * b_abd * k
        for lado in (+1, -1):
            angs = np.linspace(math.pi * 0.92, 0.30, 6)
            pts = [p + A * math.cos(g) * n + lado * B * math.sin(g) * Y
                   - 0.05 * L * t * (1 - g / math.pi) for g in angs]
            for q in range(len(pts) - 1):
                organos.append(Prim(f"costilla{j}{lado:+d}{q}", "cono", T["hueso"],
                                    a=pts[q], b=pts[q + 1], ra=r_cost, rb=r_cost))

    # ---------------- extremidades
    tib, hum, cub = prop.tibia * lf, prop.humero * lf, prop.cubito * lf
    r_mus = prop.radio_muslo * lf * grosor
    r_bra = prop.radio_brazo * lf * grosor
    p_pel, t_pel, n_pel = columna(0.17)
    p_tor, t_tor, n_tor = columna(0.82)
    abajo = -t_pel
    femures, humeros = [], []

    def hueso_largo(nombre, a, b, r, recorte):
        d = _unit(b - a); l = np.linalg.norm(b - a)
        return Prim(nombre, "cono", T["hueso"], a=a + recorte * l * d,
                    b=b - recorte * l * d, ra=r, rb=r)

    for i, lado in enumerate((+1, -1)):
        sfx = "i" if lado > 0 else "d"
        beta = math.radians(post.cadera[i]); gamma = math.radians(post.rodilla[i])
        cadera = p_pel + 0.70 * b_abd * 0.85 * lado * Y - 0.15 * L * t_pel
        d_mus = _unit(math.cos(beta) * abajo + math.sin(beta) * n_pel + post.abd_muslo[i] * lado * Y)
        rodilla = cadera + 1.08 * lf * d_mus      # 0.04 LF de cartílago en cada extremo
        d_tib = _unit(math.cos(beta - gamma) * abajo + math.sin(beta - gamma) * n_pel
                      - 0.15 * lado * Y)
        tobillo = rodilla + tib * d_tib
        d_pie = _unit(0.75 * n_pel - 0.35 * abajo - 0.35 * lado * Y)
        lp = prop.pie * largo_pie(eg, lf)
        piezas += [
            Prim(f"muslo_{sfx}", "cono", k=0.35 * r_mus, a=cadera, b=rodilla, ra=r_mus, rb=0.62 * r_mus),
            Prim(f"pierna_{sfx}", "cono", k=0.2 * r_mus, a=rodilla, b=tobillo, ra=0.62 * r_mus, rb=0.36 * r_mus),
            # largo total (casquetes incluidos) = lp, de talón a punta
            Prim(f"pie_{sfx}", "cono", k=0.15 * r_mus, a=tobillo + (0.36 * r_mus - 0.20 * lp) * d_pie,
                 b=tobillo + (0.80 * lp - 0.30 * r_mus) * d_pie, ra=0.36 * r_mus, rb=0.30 * r_mus),
        ]
        # el fémur va de cadera a rodilla: su longitud osificada es ~LF
        rf_ = 0.05 * lf      # la diáfisis osificada mide exactamente LF (incluye los casquetes)
        organos.append(Prim(f"femur_{sfx}", "cono", T["hueso"],
                            a=cadera + (0.04 * lf + rf_) * d_mus,
                            b=cadera + (1.04 * lf - rf_) * d_mus, ra=rf_, rb=rf_))
        femures.append((cadera, rodilla))
        perp = _unit(np.cross(d_tib, n_pel))
        organos += [hueso_largo(f"tibia_{sfx}", rodilla, tobillo, 0.045 * lf, 0.05),
                    hueso_largo(f"perone_{sfx}", rodilla + 0.25 * r_mus * perp,
                                tobillo + 0.20 * r_mus * perp, 0.025 * lf, 0.08)]

        # Brazo
        alfa = math.radians(post.hombro[i]); psi = math.radians(post.codo[i])
        hombro = p_tor + 0.95 * b_abd * lado * Y + 0.05 * L * t_tor
        d_hum = _unit(-math.cos(alfa) * t_tor + math.sin(alfa) * n_tor + post.abd_brazo[i] * lado * Y)
        codo = hombro + hum * d_hum
        e = _unit(t_tor - (t_tor @ d_hum) * d_hum)
        d_cub = _unit(math.cos(psi) * d_hum + math.sin(psi) * e - 0.55 * lado * Y)
        muneca = codo + cub * d_cub
        lm = prop.mano * lf
        piezas += [
            Prim(f"brazo_{sfx}", "cono", k=0.35 * r_bra, a=hombro, b=codo, ra=r_bra, rb=0.68 * r_bra),
            Prim(f"antebrazo_{sfx}", "cono", k=0.2 * r_bra, a=codo, b=muneca, ra=0.68 * r_bra, rb=0.50 * r_bra),
            Prim(f"mano_{sfx}", "elip", k=0.12 * r_bra, centro=muneca + 0.45 * lm * d_cub,
                 semiejes=(0.22 * lm, 0.38 * lm, 0.50 * lm), R=_marco(n_tor, d_cub)),
        ]
        perp = _unit(np.cross(d_cub, d_hum)) if abs(d_cub @ d_hum) < 0.99 else Y
        organos += [hueso_largo(f"humero_{sfx}", hombro, codo, 0.045 * lf, 0.04),
                    hueso_largo(f"cubito_{sfx}", codo + 0.22 * r_bra * perp,
                                muneca + 0.18 * r_bra * perp, 0.028 * lf, 0.06),
                    hueso_largo(f"radio_{sfx}", codo - 0.22 * r_bra * perp,
                                muneca - 0.18 * r_bra * perp, 0.028 * lf, 0.08)]
        humeros.append((hombro, codo))

    # al final: boca y narinas se restan de toda la superficie
    piezas += [desde_cabeza(e, resta=True) for e in geo_cab["restas"]]

    por_nombre = {o.nombre: o for o in organos}
    # plano coronal tangente a la cara, por la punta de la nariz y el mentón, 2 mm por
    # dentro de la piel: corta labios y narinas rodeados de líquido
    pz = {e["nombre"]: e for e in geo_cab["piel"]}
    frente = lambda e: H(*e["centro"]) + e["semiejes"][0] * f    # noqa: E731
    punta, menton = frente(pz["punta_nasal"]), frente(pz["menton"])
    n_nl = _unit(np.cross(yh, menton - punta))
    n_nl = n_nl if n_nl @ f > 0 else -n_nl
    plano_nariz_labios = (0.5 * (punta + menton) - (2.0 + 0.02 * dbp) * n_nl, n_nl)
    hn = por_nombre["hueso_nasal"]
    marcos = {
        "cabeza": (p_cab, Rh),
        "talamos": (H(0.0, 0, 0.0), Rh),
        "cerebelo": (por_nombre["cerebelo"].centro, Rh),
        "csp": (por_nombre["csp"].centro, Rh),
        "hueso_nasal": (np.asarray(hn.p["a"]), np.asarray(hn.p["b"])),
        "perfil": (H(0.80, 0, -0.45), Rh),                 # centro de la cara, línea media
        "nariz_labios": plano_nariz_labios,
        "corazon": (c_cor, Rt),            # plano axial del tórax a la altura del corazón
        "abdomen": marco_tronco(0.47),     # plano de la circunferencia abdominal
        "columna": marco_tronco(0.55),
        "femures": femures,
        "humeros": humeros,
        "insercion_cordon": (ins_cordon, n_ins),
    }
    bio = dict(bio, **geo_cab["medidas"], OFD=2 * a_cab, a_abd=a_abd, b_abd=b_abd, L_tronco=L,
               semiejes_cabeza=(a_cab, b_cab, c_cab))
    return Feto(eg, piezas, organos, marcos, bio)


# ---------------------------------------------------------------------------
# Escena: feto + útero + placenta + cordón + pared materna
# ---------------------------------------------------------------------------

@dataclass
class Materno:
    grasa_mm: float = 12.0          # tejido adiposo subcutáneo
    musculo_mm: float = 10.0
    tejido_mm: float = 6.0          # tejido entre músculo y útero (anterior)
    miometrio_mm: float = 8.0
    placenta: str = "anterior"      # anterior | posterior | fundica | lateral
    holgura: float = 1.05           # cavidad / caja del feto
    presentacion: str = "cefalica"  # cefalica | podalica
    dorso_grados: float = 135.0     # 0 = dorso anterior, 90 = dorso a la izquierda, 180 = posterior


class Escena:
    def __init__(self, eg: float, post: Postura | None = None,
                 prop: Proporciones | None = None, mat: Materno | None = None,
                 semilla: int = 0):
        self.eg, self.post = eg, post or Postura()
        self.prop, self.mat = prop or Proporciones(), mat or Materno()
        self.osificacion = osificacion(eg)
        rng = np.random.default_rng(semilla)

        # Orientación del feto: cuerpo -> mundo
        a = math.radians(self.mat.dorso_grados)
        dorso = np.array([math.sin(a), 0.0, math.cos(a)])
        ez = np.array([0, -1.0, 0]) if self.mat.presentacion == "cefalica" else np.array([0, 1.0, 0])
        ex = -dorso
        R0 = np.column_stack([ex, np.cross(ez, ex), ez])

        # La cavidad uterina se dimensiona con la postura de reposo (no cambia al moverse)
        reposo = construir_feto(eg, Postura(), self.prop)
        lo, hi = _caja(reposo.piezas)
        self.centro_cuerpo = 0.5 * (lo + hi)
        ext_mundo = np.abs(R0) @ (hi - lo)
        liquido = 6.0 + 0.35 * (eg - 12)
        self.cav = 0.5 * ext_mundo * self.mat.holgura + liquido
        m = self.mat
        self.ut = self.cav + m.miometrio_mm
        pared = 2.0 + m.grasa_mm + m.musculo_mm + m.tejido_mm
        self.abd = self.ut + np.array([70.0, 90.0, 90.0])
        self.c_abd = np.array([0.0, -20.0, self.ut[2] + pared - self.abd[2]])

        # Postura actual
        self.feto = construir_feto(eg, self.post, self.prop)
        Rg = _rot(R0[:, 2], math.radians(self.post.giro_global)) @ R0
        Rg = _rot(Rg[:, 1], math.radians(self.post.cabeceo_global)) @ Rg
        self.Rg = Rg
        self.tg = -Rg @ self.centro_cuerpo + np.asarray(self.post.desplaz, float)

        # Placenta
        dirs = {"anterior": [0, 0.25, 1], "posterior": [0, 0.25, -1],
                "fundica": [0, 1, 0.2], "lateral": [1, 0.2, 0.3]}
        self.dir_pl = _unit(dirs[m.placenta])
        self.grosor_pl = max(10.0, 1.0 * eg)          # ~ EG mm
        self.cap_pl = math.radians(42)
        q = self.dir_pl / np.linalg.norm(self.dir_pl / self.cav)   # punto de la pared
        self.ins_placenta = q * (1 - self.grosor_pl / np.linalg.norm(q))
        self.cordon = self._cordon(rng)

    # ................................................................ cordón
    def _cordon(self, rng):
        p0b, nb = self.feto.marcos["insercion_cordon"]
        p0 = self.a_mundo(p0b)
        n0 = self.Rg @ nb
        p3 = self.ins_placenta
        D = np.linalg.norm(p3 - p0)
        lat = _unit(np.cross(p3 - p0, [0.3, 1, 0.1]))
        p1 = p0 + 0.45 * D * n0
        p2 = p3 - 0.35 * D * self.dir_pl + 0.25 * D * lat * rng.uniform(-1, 1)
        s = np.linspace(0, 1, 28)[:, None]
        cam = ((1 - s) ** 3) * p0 + 3 * ((1 - s) ** 2) * s * p1 + 3 * (1 - s) * s ** 2 * p2 + s ** 3 * p3
        r = 3.0 + 0.12 * (self.eg - 12)            # radio del cordón (mm)
        prims = [Prim(f"cordon{i}", "cono", T["cordon"], a=cam[i], b=cam[i + 1], ra=r, rb=r)
                 for i in range(len(cam) - 1)]
        # 2 arterias + 1 vena en hélice
        tang = np.gradient(cam, axis=0)
        e1 = _unit(np.cross(tang[0], [0.1, 0.2, 1.0]))
        vasos = []
        for k, (rv, ang0) in enumerate([(0.34, 0.0), (0.22, 2.1), (0.22, 4.2)]):
            pts = []
            for i in range(len(cam)):
                t = _unit(tang[i])
                e1 = _unit(e1 - (e1 @ t) * t); e2 = np.cross(t, e1)
                ang = ang0 + 8 * math.pi * s[i, 0]
                pts.append(cam[i] + 0.42 * r * (math.cos(ang) * e1 + math.sin(ang) * e2))
            vasos += [Prim(f"vaso{k}_{i}", "cono", T["sangre"], a=pts[i], b=pts[i + 1],
                           ra=rv * r, rb=rv * r) for i in range(len(pts) - 1)]
        self.camino_cordon, self.radio_cordon = cam, r
        return prims + vasos

    # ............................................................ utilidades
    def a_mundo(self, Pb):
        return np.asarray(Pb) @ self.Rg.T + self.tg

    def a_cuerpo(self, Pw):
        return (np.asarray(Pw) - self.tg) @ self.Rg

    def sdf_abdomen(self, P):
        return sdf_elipsoide(P, self.c_abd, self.abd)

    # .............................................................. evaluar
    def evaluar_materno(self, P):
        """Sólo tejidos maternos, útero, líquido y placenta (sin feto ni cordón)."""
        P = np.asarray(P, dtype=np.float32)
        N = len(P)
        etq = np.full(N, T["gel"], np.int16)
        pieza = np.zeros(N, np.int32)              # 0: tejidos maternos (estáticos)
        loc = P.copy()
        m = self.mat

        prof = -self.sdf_abdomen(P)
        dentro = prof > 0
        etq[dentro] = T["piel"]
        for lim, tj in [(2.0, "grasa"), (2.0 + m.grasa_mm, "musculo"),
                        (2.0 + m.grasa_mm + m.musculo_mm, "materno")]:
            etq[dentro & (prof >= lim)] = T[tj]
        etq[sdf_elipsoide(P, np.zeros(3), self.ut) < 0] = T["miometrio"]
        cav = sdf_elipsoide(P, np.zeros(3), self.cav) < 0
        etq[cav] = T["amniotico"]
        # placenta: lente adosada a la pared dentro del cap angular
        q = P / self.cav
        nq = np.linalg.norm(q, axis=1) + 1e-9
        cosang = (q @ (self.dir_pl / self.cav) / np.linalg.norm(self.dir_pl / self.cav)) / nq
        ang = np.arccos(np.clip(cosang, -1, 1))
        gros = self.grosor_pl * np.clip(1 - (ang / self.cap_pl) ** 2, 0, 1)
        rmed = np.linalg.norm(P, axis=1) / nq          # radio de la pared en esa dirección
        plac = cav & (ang < self.cap_pl) & (rmed * (1 - nq) < gros)
        etq[plac] = T["placenta"]
        return etq, pieza, loc

    def evaluar(self, P):
        """P (N,3) mundo -> etiqueta (N,), pieza (N,), coordenadas locales (N,3)."""
        P = np.asarray(P, dtype=np.float32)
        etq, pieza, loc = self.evaluar_materno(P)
        cav = etq == T["amniotico"]

        # cordón (en el mundo)
        cand = np.flatnonzero(cav)
        self._pintar(P, cand, self.cordon, etq, pieza, loc, base_id=1)

        # feto: superficie por unión suave y luego órganos
        Pb = self.a_cuerpo(P).astype(np.float32)
        lo, hi = _caja(self.feto.piezas)
        idx = np.flatnonzero(np.all((Pb > lo) & (Pb < hi), axis=1))
        if len(idx):
            Q = Pb[idx]
            d = np.full(len(Q), GRANDE, np.float32)
            dmin = np.full(len(Q), GRANDE, np.float32)
            cerca = np.zeros(len(Q), np.int32)
            for j, pz in enumerate(self.feto.piezas):
                sel = np.flatnonzero(pz.en_caja(Q, pz.k))
                if not len(sel):
                    continue
                if pz.resta:
                    d[sel] = resta_suave(d[sel], pz.sdf(Q[sel]), pz.k)
                    continue
                di = np.full(len(Q), GRANDE, np.float32)
                di[sel] = pz.sdf(Q[sel])
                mejor = di < dmin
                dmin[mejor] = di[mejor]; cerca[mejor] = j
                d = union_suave(d, di, pz.k)
            fet = d < 0
            ii = idx[fet]
            etq[ii] = T["fetal"]
            base = 1000
            pieza[ii] = base + cerca[fet]
            for j in np.unique(cerca[fet]):
                sel = ii[cerca[fet] == j]
                loc[sel] = self.feto.piezas[j].local(Pb[sel])
            # órganos: sólo dentro del cuerpo
            self._pintar(Pb, ii, self.feto.organos, etq, pieza, loc, base_id=2000)
        return etq, pieza, loc

    @staticmethod
    def _pintar(P, cand, prims, etq, pieza, loc, base_id):
        if not len(cand):
            return
        Pc = P[cand]
        for j, pr in enumerate(prims):
            sel = np.flatnonzero(pr.en_caja(Pc))
            if not len(sel):
                continue
            inside = pr.sdf(Pc[sel]) < 0
            if not inside.any():
                continue
            k = cand[sel[inside]]
            etq[k] = pr.etiqueta
            pieza[k] = base_id + j
            loc[k] = pr.local(P[k])

    # ........................................................ ayudas varias
    def con_postura(self, post: Postura) -> "Escena":
        """Misma madre/útero, otra postura del feto (el cordón se recalcula)."""
        return Escena(self.eg, post, self.prop, self.mat)


def sdf_piel(piezas, P):
    """Distancia con signo a la piel fetal: unión suave de las piezas menos las restas."""
    d = np.full(len(P), GRANDE, np.float32)
    for pz in piezas:
        sel = np.flatnonzero(pz.en_caja(P, pz.k))
        if pz.resta:
            d[sel] = resta_suave(d[sel], pz.sdf(P[sel]), pz.k)
            continue
        di = np.full(len(P), GRANDE, np.float32)
        di[sel] = pz.sdf(P[sel])
        d = union_suave(d, di, pz.k)
    return d


def _caja(prims):
    lo = np.min([p.lo for p in prims], axis=0)
    hi = np.max([p.hi for p in prims], axis=0)
    return lo - 2, hi + 2
