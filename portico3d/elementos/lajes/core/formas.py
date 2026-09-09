# -*- coding: utf-8 -*-
"""
formas.py
Área de forma de cada laje, separada em **forma inferior** e **forma de
fechamento**.

Forma não é área de laje. O que se paga é a superfície de madeira que
efetivamente precisa existir para o concreto não vazar e não cair -- e essa
superfície não coincide com o retângulo da laje em nenhuma das duas
direções:

``forma inferior``
    o fundo da laje, **descontada a faixa que se apoia sobre a viga**. A
    viga é desenhada centrada na linha do bordo -- ``t/2`` embutido sob a
    laje e ``t/2`` para fora (a mesma convenção da aba de vinculação e do
    desenho esquemático) --, então a faixa de ``t/2`` ao longo de cada bordo
    com apoio fica sobre o fundo da viga, que já tem forma própria. Contar
    essa faixa nas duas peças é medir a mesma chapa duas vezes.

    O desconto é feito **recuando cada bordo apoiado**, e não somando faixas:
    no canto onde dois bordos apoiados se encontram, as duas faixas se
    sobrepõem num quadrado de ``t/2 x t/2``, e somar as duas descontaria
    aquele canto duas vezes. Recuar as arestas e medir o retângulo interno
    resolve isso sem caso particular.

``forma de fechamento``
    a face lateral, de altura ``h``, **só nos bordos livres**. É o critério
    do vazamento: onde o bordo apoia numa viga, a lateral da viga já sobe
    até o topo da laje e fecha a concretagem; onde o bordo é comum com
    outra laje, não há nada a fechar, o concreto é contínuo. Sobra o bordo
    **livre** -- a ponta de um balanço, a borda de uma sacada --, que é
    exatamente onde o concreto escorreria se não houvesse uma tábua ali.

Um bordo apoiado com ``t = 0`` (parede, apoio sem largura declarada) não
desconta nada do fundo e também não pede fechamento: ele apoia, então não
vaza, mas não há faixa de viga sob a laje para descontar.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .modelo import Laje


@dataclass
class FormasLaje:
    """Área de forma de uma laje, em m²."""

    laje: str
    inferior: float = 0.0           # m², fundo já sem a faixa sobre viga
    fechamento: float = 0.0         # m², lateral dos bordos livres
    area_bruta: float = 0.0         # m², retângulo cheio, para comparação
    bordos_livres: list[int] = field(default_factory=list)
    descontos: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.inferior + self.fechamento


def calcular(laje: Laje) -> FormasLaje:
    """Forma inferior e de fechamento de uma laje, em m².

    Ver o docstring do módulo para o critério dos dois valores.
    """
    x0, y0, x1, y1 = laje.retangulo
    recuo = {"esquerda": 0.0, "direita": 0.0, "baixo": 0.0, "cima": 0.0}
    res = FormasLaje(laje=laje.nome,
                     area_bruta=(x1 - x0) * (y1 - y0))

    for bordo in (1, 2, 3, 4):
        b = laje.bordos[bordo - 1]
        face = laje.face_do_bordo(bordo)
        bx0, by0, bx1, by1 = laje.segmento_do_bordo(bordo)
        comprimento = math.hypot(bx1 - bx0, by1 - by0)      # m

        if b.vinculo == "livre":
            res.bordos_livres.append(bordo)
            res.fechamento += comprimento * laje.h / 100.0
            continue
        if b.t <= 0.0:
            continue
        recuo[face] = b.t / 2.0 / 100.0                     # m
        res.descontos.append(
            f"bordo {bordo} ({face}): {b.t / 2.0:.0f} cm sobre a viga de "
            f"t = {b.t:g} cm")

    largura = max((x1 - x0) - recuo["esquerda"] - recuo["direita"], 0.0)
    altura = max((y1 - y0) - recuo["baixo"] - recuo["cima"], 0.0)
    res.inferior = largura * altura
    return res


def total(formas: list[FormasLaje]) -> dict:
    """Soma as formas do pavimento, em m²."""
    return {
        "forma_inferior": sum(f.inferior for f in formas),
        "forma_fechamento": sum(f.fechamento for f in formas),
        "forma_total": sum(f.total for f in formas),
    }
