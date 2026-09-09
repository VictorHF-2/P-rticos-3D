# -*- coding: utf-8 -*-
"""
cisalhamento.py
Dimensionamento à força cortante pelos Modelos de Cálculo I e II da
NBR 6118 (item 17.4.2), com as armaduras mínima e máxima e os limites de
espaçamento do item 18.3.3.2.

Modelo I .... biela a 45°, parcela complementar Vc constante e igual a Vc0.
Modelo II ... biela entre 30° e 45°, com Vc reduzido linearmente entre Vc0
              (quando Vsd = Vc0) e zero (quando Vsd = VRd2).

Unidades: forças em kN, comprimentos em cm, armaduras em cm²/m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .materiais import Aco, Concreto
from .modelo import Secao
from . import avisos as av

FYWD_MAX = 43.5            # kN/cm², limite de 435 MPa para estribos (17.4.2.2)


@dataclass
class ResultadoCortante:
    """Verificação e armadura transversal de uma seção."""

    x: float                  # m, posição na viga
    Vsd: float                # kN, valor de cálculo considerado
    d: float                  # cm
    modelo: int
    theta: float              # graus
    alpha: float              # graus
    VRd2: float               # kN
    Vc0: float                # kN
    Vc: float                 # kN
    Vsw: float                # kN
    asw: float                # cm²/m, armadura calculada
    asw_min: float            # cm²/m
    asw_adotado: float        # cm²/m
    s_max: float              # cm
    st_max: float             # cm, espaçamento transversal entre ramos
    biela_ok: bool
    razao_biela: float        # Vsd / VRd2
    avisos: list[str] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        return "OK" if self.biela_ok else "ESMAGAMENTO DA BIELA"


def _fywd(aco: Aco) -> float:
    return min(aco.fyd_kNcm2, FYWD_MAX)


def VRd2(secao: Secao, concreto: Concreto, modelo: int, theta: float,
         alpha: float, d: float) -> float:
    """Resistência da biela comprimida, kN (17.4.2.2 / 17.4.2.3)."""
    sig = concreto.sigma_biela
    if modelo == 1:
        return 0.27 * sig * secao.bw * d
    th, al = math.radians(theta), math.radians(alpha)
    return (0.54 * sig * secao.bw * d * math.sin(th) ** 2
            * (1.0 / math.tan(th) + 1.0 / math.tan(al)))


def Vc0(secao: Secao, concreto: Concreto, d: float) -> float:
    """Parcela resistida por mecanismos complementares na flexão simples."""
    return 0.6 * concreto.fctd_kNcm2 * secao.bw * d


def exige_modelo_de_laje(secao: Secao, d: float) -> bool:
    """Verdadeiro quando o elemento cai na exceção do item 17.4.1.1.2 (a).

    Elementos lineares com ``bw > 5d`` saem do modelo de viga: a armadura
    transversal mínima do 17.4.1.1.1 não se aplica e a verificação tem de
    seguir o item 19.4, de lajes.
    """
    return d > 0.0 and secao.bw > 5.0 * d


def asw_minima(secao: Secao, concreto: Concreto, aco: Aco,
               alpha: float = 90.0) -> float:
    """Armadura transversal mínima, cm²/m (17.4.1.1.1).

    ``rho_sw,mín = 0,2 . fct,m / fywk``, com ``fywk`` a resistência
    característica do aço **da armadura transversal**, sem teto: o item
    17.4.1.1.1 não impõe nenhum. O teto de 435 MPa que a norma impõe é sobre
    ``fywd`` no **dimensionamento** (17.4.2.2), coisa diferente, e está em
    ``FYWD_MAX``.

    O programa aplicava aqui um teto de 500 MPa, sem base na norma. Com estribo
    de CA-60 -- o caso corrente, porque Ø5,0 e Ø4,2 só se produzem nessa
    categoria -- ele produzia 20 % mais armadura mínima que o exigido, e a
    armadura mínima governa a maior parte das vigas.
    """
    fctm = concreto.fctm / 10.0                    # kN/cm²
    fywk = aco.fyk / 10.0                          # kN/cm²
    return 0.2 * fctm / fywk * secao.bw * math.sin(math.radians(alpha)) * 100.0


def espacamento_maximo(Vsd: float, vrd2: float, d: float) -> tuple[float, float]:
    """Espaçamentos longitudinal e transversal máximos, cm (18.3.3.2).

    Os dois limites têm **gatilhos diferentes**: o longitudinal muda em
    0,67·VRd2 e o transversal entre ramos, em 0,20·VRd2.
    """
    s = min(0.6 * d, 30.0) if abs(Vsd) <= 0.67 * vrd2 else min(0.3 * d, 20.0)
    st = min(d, 80.0) if abs(Vsd) <= 0.20 * vrd2 else min(0.6 * d, 35.0)
    return s, st


def ramos_minimos(secao: Secao, cobrimento: float, phi_estribo: float,
                  st_max: float) -> int:
    """Nº mínimo de ramos do estribo para respeitar ``st,max`` (18.3.3.2).

    O limite é o espaçamento entre **ramos sucessivos**: com dois ramos, a
    distância entre eles é a largura útil da seção, e numa viga larga com
    cortante alto isso estoura o limite. Cada ramo extra divide o vão livre em
    mais um trecho.
    """
    livre = secao.bw - 2.0 * cobrimento - phi_estribo / 10.0
    if livre <= 0.0 or st_max <= 0.0:
        return 2
    return max(2, int(math.ceil(livre / st_max + 1e-9)) + 1)


def verificar(secao: Secao, concreto: Concreto, aco: Aco, Vsd: float,
              d: float, modelo: int = 1, theta: float = 45.0,
              alpha: float = 90.0, x: float = 0.0) -> ResultadoCortante:
    """Verifica a biela e calcula a armadura transversal de uma seção."""
    Vsd = abs(Vsd)
    fywd = _fywd(aco)
    vrd2 = VRd2(secao, concreto, modelo, theta, alpha, d)
    vc0 = Vc0(secao, concreto, d)
    th_ef = 45.0 if modelo == 1 else theta

    if modelo == 1 or Vsd <= vc0:
        vc = vc0
    elif Vsd > vrd2:
        vc = 0.0
    else:
        vc = (vrd2 - Vsd) / (vrd2 - vc0) * vc0

    vsw = max(Vsd - vc, 0.0)
    th, al = math.radians(th_ef), math.radians(alpha)
    braco = 0.9 * d * (1.0 / math.tan(th) + 1.0 / math.tan(al)) * math.sin(al)
    asw = vsw / braco / fywd * 100.0               # cm²/m
    asw_min = asw_minima(secao, concreto, aco, alpha)
    s_max, st_max = espacamento_maximo(Vsd, vrd2, d)

    avisos: list[str] = []
    biela_ok = Vsd <= vrd2 + 1e-9
    if not biela_ok:
        avisos.append(av.erro(
            f"Vsd = {Vsd:.1f} kN supera VRd2 = {vrd2:.1f} kN: a biela "
            f"comprimida esmaga (17.4.2.2). Aumente bw, h ou o fck."))
    return ResultadoCortante(
        x=x, Vsd=Vsd, d=d, modelo=modelo, theta=th_ef, alpha=alpha,
        VRd2=vrd2, Vc0=vc0, Vc=vc, Vsw=vsw, asw=asw, asw_min=asw_min,
        asw_adotado=max(asw, asw_min), s_max=s_max, st_max=st_max,
        biela_ok=biela_ok, razao_biela=Vsd / vrd2 if vrd2 else float("inf"),
        avisos=avisos)


def V_minimo_projeto(secao: Secao, concreto: Concreto, aco: Aco,
                     d: float, modelo: int = 1, theta: float = 45.0,
                     alpha: float = 90.0) -> float:
    """Cortante **de cálculo** que a armadura mínima já atende, kN.

    É o Vsd para o qual a armadura calculada iguala a mínima do item
    17.4.1.1.1: abaixo dele o estribo é o mínimo, e o diagrama de cortantes
    não pede mais nada. No Modelo II a parcela do concreto depende do próprio
    Vsd, e a igualdade tem de ser invertida.
    """
    fywd = _fywd(aco)
    asw_min = asw_minima(secao, concreto, aco, alpha)
    th_ef = 45.0 if modelo == 1 else theta
    th, al = math.radians(th_ef), math.radians(alpha)
    vrd2 = VRd2(secao, concreto, modelo, theta, alpha, d)
    vc0 = Vc0(secao, concreto, d)
    vsw = (asw_min / 100.0 * 0.9 * d
           * (1.0 / math.tan(th) + 1.0 / math.tan(al)) * math.sin(al) * fywd)
    if modelo == 1:
        return vsw + vc0
    # no Modelo II, Vc também depende de Vsd: Vsd = Vsw + Vc(Vsd)
    vc_estrela = vrd2 * vc0 / (vrd2 - vc0)
    coef = 1.0 + vc0 / (vrd2 - vc0)
    return (vsw + vc_estrela) / coef


def V_minimo_caracteristico(secao: Secao, concreto: Concreto, aco: Aco,
                            d: float, modelo: int = 1, theta: float = 45.0,
                            alpha: float = 90.0,
                            gamma_f: float = 1.4) -> float:
    """Cortante característico que a armadura mínima já atende, kN.

    Reproduz o 'Vk min' da planilha de referência: é o Vsd de
    :func:`V_minimo_projeto` dividido pelo coeficiente de ponderação.
    """
    return V_minimo_projeto(secao, concreto, aco, d, modelo, theta,
                            alpha) / gamma_f


def cortante_de_projeto(V_envoltoria, x, viga, d_cm: float):
    """Aplica a redução do item 17.4.1.2.1 (a) junto aos apoios.

    No trecho entre o apoio e a seção a d/2 da face, a força cortante de
    projeto é tomada constante e igual à da seção a d/2 da face -- o que só
    vale para a carga distribuída. Cargas concentradas próximas do apoio não
    são reduzidas aqui, a favor da segurança.
    """
    import numpy as np

    V = np.asarray(V_envoltoria, dtype=float).copy()
    xs = viga.x_apoios
    meia_d = d_cm / 200.0                       # d/2 em metros
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        meia_largura = ap.largura / 200.0
        x0 = xs[k]
        if k > 0:                                # trecho à esquerda do apoio
            xr = x0 - meia_largura - meia_d
            if xr > xs[k - 1]:
                alvo = float(np.interp(xr, x, V))
                mask = (x > xr) & (x <= x0)
                V[mask] = np.sign(alvo) * np.minimum(np.abs(V[mask]),
                                                     abs(alvo))
        if k < len(viga.apoios) - 1:             # trecho à direita
            xr = x0 + meia_largura + meia_d
            if xr < xs[k + 1]:
                alvo = float(np.interp(xr, x, V))
                mask = (x >= x0) & (x < xr)
                V[mask] = np.sign(alvo) * np.minimum(np.abs(V[mask]),
                                                     abs(alvo))
    return V
