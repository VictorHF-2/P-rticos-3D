# -*- coding: utf-8 -*-
"""
torcao.py
Dimensionamento à torção pelo modelo de treliça espacial generalizada da
NBR 6118 (item 17.5), com a seção vazada equivalente, a verificação conjunta
da biela com a força cortante (17.7.2.2) e as armaduras transversal e
longitudinal de torção.

Unidades: forças em kN, momentos torçores em kN.m, comprimentos em cm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .materiais import Aco, Concreto
from .modelo import Secao
from . import avisos as av

FYWD_MAX = 43.5            # kN/cm², limite de 435 MPa (17.5.1.6)


@dataclass
class SecaoVazada:
    """Geometria da seção vazada equivalente (17.5.1.4.1)."""

    A: float                  # cm², área da seção cheia
    u: float                  # cm, perímetro da seção cheia
    he: float                 # cm, espessura da parede equivalente
    c1: float                 # cm, distância do eixo da barra de canto à face
    c2: float                 # cm, distância do eixo da parede à face
    Ae: float                 # cm², área limitada pela linha média da parede
    ue: float                 # cm, perímetro de Ae
    valida: bool
    aviso: str = ""


def secao_vazada(secao: Secao, c1: float) -> SecaoVazada:
    """Parâmetros da seção vazada equivalente de uma seção retangular."""
    A = secao.bw * secao.h
    u = 2.0 * (secao.bw + secao.h)
    he = A / u
    aviso = ""
    valida = True
    if he >= 2.0 * c1:
        c2 = he / 2.0
    elif he <= secao.bw - 2.0 * c1:
        c2 = c1
    else:
        c2 = c1
        valida = False
        aviso = ("Seção estreita para torção: a espessura equivalente não "
                 "se enquadra nos limites do item 17.5.1.4.1.")
    Ae = (secao.bw - 2.0 * c2) * (secao.h - 2.0 * c2)
    ue = 2.0 * ((secao.bw - 2.0 * c2) + (secao.h - 2.0 * c2))
    return SecaoVazada(A=A, u=u, he=he, c1=c1, c2=c2, Ae=Ae, ue=ue,
                       valida=valida, aviso=aviso)


def armadura_minima_transversal(secao: Secao, concreto: Concreto, aco: Aco,
                                c1: float) -> float:
    """Armadura transversal mínima de torção, cm²/m (17.5.1.2).

    São os dois ramos da parede da seção vazada equivalente. É o que o item
    exige mesmo quando a torção de compatibilidade é desprezada.
    """
    del c1
    fctm = concreto.fctm / 10.0                      # kN/cm²
    fywk = min(aco.fyk, 500.0) / 10.0                # kN/cm²
    # `Asw/(bw.s) >= 0,2 fctm/fywk` -- a taxa é sobre a largura da seção e vale
    # para o estribo inteiro, e não sobre a espessura da parede equivalente
    return 20.0 * fctm / fywk * secao.bw


@dataclass
class ResultadoTorcao:
    """Verificação e armaduras de torção de uma seção."""

    x: float
    Tsd: float                # kN.m
    Vsd: float                # kN
    theta: float              # graus
    geometria: SecaoVazada
    TRd2: float               # kN.m
    VRd2: float               # kN
    interacao: float          # Tsd/TRd2 + Vsd/VRd2
    a90: float                # cm²/m, armadura transversal de torção (1 ramo)
    a90_min: float            # cm²/m
    Asl: float                # cm², armadura longitudinal de torção
    Asl_min: float            # cm²
    asw_cortante: float       # cm²/m, armadura de cortante somada
    a_transversal: float      # cm²/m, total dos dois ramos + cortante
    biela_ok: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        return "OK" if self.biela_ok else "ESMAGAMENTO DA BIELA"


def verificar(secao: Secao, concreto: Concreto, aco: Aco, Tsd: float,
              Vsd: float, VRd2_cortante: float, asw_cortante: float,
              asw_min_cortante: float, c1: float, theta: float = 45.0,
              x: float = 0.0, aco_estribo: Aco | None = None
              ) -> ResultadoTorcao:
    """Dimensiona a seção à torção combinada com a força cortante.

    ``Tsd`` em kN.m, ``Vsd`` em kN. ``VRd2_cortante`` e ``asw_cortante`` vêm
    do dimensionamento ao cisalhamento da mesma seção.

    São **dois aços**: ``aco_estribo`` para o estribo de torção (A90) e ``aco``
    para as barras longitudinais (Asl). Em obra são categorias diferentes -- o
    estribo Ø5 é CA-60 e a barra longitudinal CA-50 --, e a armadura mínima do
    item 17.5.1.2 é inversamente proporcional ao fywk de cada uma. Sem
    ``aco_estribo`` os dois caem no mesmo aço, como antes.
    """
    aco_t = aco_estribo or aco
    Tsd = abs(Tsd)
    Vsd = abs(Vsd)
    g = secao_vazada(secao, c1)
    # o teto de 435 MPa em fywd é do item 17.5.1.6; o de 500 MPa em fywk é da
    # taxa mínima do 17.5.1.2, e **só dela** -- o item 17.4.1.1.1, da armadura
    # mínima de cortante, não tem teto nenhum
    fywd_t = min(aco_t.fyd_kNcm2, FYWD_MAX)         # estribo
    fywd_l = min(aco.fyd_kNcm2, FYWD_MAX)           # barra longitudinal
    fctm = concreto.fctm / 10.0                     # kN/cm²
    fywk_t = min(aco_t.fyk, 500.0) / 10.0           # kN/cm²
    fywk_l = min(aco.fyk, 500.0) / 10.0             # kN/cm²
    th = math.radians(theta)

    TRd2 = 0.5 * concreto.sigma_biela * g.Ae * g.he * math.sin(2.0 * th) / 100.0
    interacao = (Tsd / TRd2 if TRd2 else float("inf")) + \
                (Vsd / VRd2_cortante if VRd2_cortante else 0.0)
    biela_ok = interacao <= 1.0 + 1e-9

    # armadura transversal de torção (um ramo), cm²/m
    a90 = Tsd * 5000.0 * math.tan(th) / g.Ae / fywd_t if g.Ae > 0 else 0.0
    # a taxa mínima do 17.5.1.2 é `Asw/(bw.s) >= 0,2 fctm/fywk` na
    # transversal e `As/(ue.he) >= 0,2 fctm/fywk` na longitudinal: a
    # transversal é sobre a LARGURA DA SEÇÃO, não sobre a espessura da parede
    # equivalente. Em seção vazada bw é a soma das almas mais externas -- o
    # programa só modela seção cheia, e aí bw é o próprio bw
    # `a90` é a área dos ramos de UMA parede equivalente -- num retângulo
    # cheio, um ramo -- e `a_transv` abaixo o dobra para o estribo inteiro. A
    # taxa do item é do estribo inteiro (`Asw/(bw.s)`), logo o piso por ramo é
    # a metade dela
    a90_min = 10.0 * fctm / fywk_t * secao.bw

    # armadura longitudinal de torção, cm²
    Asl = (Tsd * 50.0 * g.ue / g.Ae / math.tan(th) / fywd_l
           if g.Ae > 0 else 0.0)
    Asl_min = 0.2 * fctm / fywk_l * g.ue * g.he

    # O item 17.7.2.3 diz como combinar: "a armadura transversal pode ser
    # calculada pela **soma das armaduras calculadas separadamente** para VSd
    # e TSd". A armadura calculada para VSd é a que se poria se só houvesse
    # cortante -- e essa nunca é menor que o mínimo do 17.4.1.1.1; a calculada
    # para TSd, idem com o mínimo do 17.5.1.2. Cada uma é uma armadura
    # completa, e é a soma delas que vai no estribo.
    #
    # Não é `max` das duas somas: com o cortante governado pelo seu mínimo, o
    # `max` compara o mínimo com a torção em vez de somá-los, e o estribo sai
    # curto na razão em que o mínimo de cortante pesa.
    parte_cortante = max(asw_cortante, asw_min_cortante)
    # onde não há torção não se soma armadura de torção -- inclusive para não
    # contar duas vezes um mínimo que é a mesma expressão nos dois itens
    parte_torcao = max(2.0 * a90, 2.0 * a90_min) if Tsd > 1e-9 else 0.0
    a_transv = parte_cortante + parte_torcao

    avisos: list[str] = []
    if g.aviso:
        avisos.append(av.erro(g.aviso))
    if not biela_ok:
        avisos.append(av.erro(
            f"Tsd/TRd2 + Vsd/VRd2 = {interacao:.3f} > 1,0: a biela esmaga sob "
            f"torção e cortante combinados (17.7.2.2)."))
    return ResultadoTorcao(
        x=x, Tsd=Tsd, Vsd=Vsd, theta=theta, geometria=g, TRd2=TRd2,
        VRd2=VRd2_cortante, interacao=interacao, a90=a90, a90_min=a90_min,
        Asl=max(Asl, Asl_min), Asl_min=Asl_min, asw_cortante=asw_cortante,
        a_transversal=a_transv, biela_ok=biela_ok, avisos=avisos)


def torcao_de_compatibilidade(secao: Secao, concreto: Concreto) -> float:
    """Torçor de fissuração, kN.m (referência para torção de compatibilidade).

    Quando a torção decorre apenas da compatibilidade de deformações, o item
    17.5.1.2 permite desprezá-la desde que a peça tenha a armadura mínima e
    a capacidade de adaptação plástica; este valor serve de referência para
    essa decisão.
    """
    A = secao.bw * secao.h
    u = 2.0 * (secao.bw + secao.h)
    he = A / u
    Ae = (secao.bw - he) * (secao.h - he)
    return 2.0 * concreto.fctd_kNcm2 * Ae * he / 100.0
