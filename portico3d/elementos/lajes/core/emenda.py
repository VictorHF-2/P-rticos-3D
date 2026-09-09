# -*- coding: utf-8 -*-
"""
emenda.py
Emenda por traspasse das barras mais longas que o comprimento comercial,
item 9.5.2 da NBR 6118.

A barra de aço não vem em qualquer comprimento -- o mercado vende em varas de
uma medida comercial (12 m é a mais comum em CA-50), e uma armadura de
continuidade que atravessa várias lajes em linha, ou uma faixa principal de
um vão comprido, pode passar disso sem que nada no cálculo da laje em si
avise. Este módulo fecha essa lacuna: não decide *onde* escalonar a emenda
(isso é decisão de detalhamento de obra, de quem desenha a prancha), mas diz
**quando** ela é necessária e **quanto** de traspasse ela exige.

    l0t = alfa_0t . lb,nec

``alfa_0t`` vem da Tabela 9.4, em função do percentual de barras emendadas na
mesma seção -- quanto mais barras emendadas juntas, maior o traspasse exigido,
porque a aderência de cada uma compete com a das vizinhas. Sem um plano de
escalonamento definido, o programa assume o melhor caso construtivo (até 20 %
das barras emendadas na mesma seção, alfa_0t = 1,2) e diz isso no aviso: é
responsabilidade de quem desenha a prancha manter esse escalonamento, ou
recalcular com um alfa_0t maior se não puder.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .ancoragem import lb
from .materiais import Aco, Concreto

#: alfa_0t da Tabela 9.4 para barras tracionadas, por percentual de barras
#: emendadas na mesma seção. Interpolado nos pontos tabelados, e não abaixo
#: de 20 % nem acima de 100 %.
ALFA_0T = ((20.0, 1.2), (25.0, 1.4), (33.0, 1.6), (50.0, 1.8), (100.0, 2.0))

#: Comprimento comercial usual da barra de aço, cm (12 m em CA-50).
COMPRIMENTO_COMERCIAL_PADRAO = 1200.0


def alfa_0t(percentual: float) -> float:
    """``alfa_0t`` da Tabela 9.4 para o percentual de barras emendadas."""
    for limite, alfa in ALFA_0T:
        if percentual <= limite:
            return alfa
    return ALFA_0T[-1][1]


@dataclass
class ResultadoTraspasse:
    """Emenda por traspasse de uma posição cuja barra passa do comercial."""

    rotulo: str
    phi: float                      # mm
    comprimento_barra: float        # cm, por barra
    comprimento_comercial: float    # cm
    alfa_0t: float
    precisa_emenda: bool = False
    numero_emendas: int = 0         # por barra
    l0t: float = 0.0                # cm


def verificar(rotulo: str, phi_mm: float, comprimento_barra: float,
              comprimento_comercial: float, concreto: Concreto, aco: Aco,
              percentual_emendado: float = 20.0) -> ResultadoTraspasse:
    """Confere se a barra passa do comprimento comercial e, se passar,
    o traspasse necessário em cada emenda (9.5.2.3)."""
    res = ResultadoTraspasse(
        rotulo=rotulo, phi=phi_mm, comprimento_barra=comprimento_barra,
        comprimento_comercial=comprimento_comercial,
        alfa_0t=alfa_0t(percentual_emendado))
    if comprimento_barra <= comprimento_comercial + 1e-6:
        return res
    res.precisa_emenda = True
    res.numero_emendas = math.ceil(
        comprimento_barra / comprimento_comercial) - 1
    lb_nec = lb(concreto, aco, phi_mm)
    res.l0t = max(res.alfa_0t * lb_nec, 15.0 * phi_mm / 10.0, 20.0)
    return res
