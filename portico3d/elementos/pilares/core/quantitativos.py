# -*- coding: utf-8 -*-
"""
quantitativos.py
Quantitativo de um lance de pilar e a consolidação de um projeto inteiro:
volume de concreto, área de formas e massa de aço por bitola.

Unidades de **saída** deste módulo são as do quadro de quantidades, e não as
do resto do programa: ``m³`` para concreto, ``m²`` para formas e ``kg`` para
aço. As entradas continuam em cm, como em todo o resto.

Critério das formas
-------------------
Só entram as faces que **contêm o concreto fresco**, isto é, as faces
**laterais** -- todo o perímetro vertical, o externo e também o dos vazios,
que num pilar vazado precisam de forma interna. As faces horizontais ficam
fora: a de baixo apoia no que já foi concretado (lance anterior, bloco ou
sapata) e a de cima é justamente por onde se lança o concreto.

Não se descontam as áreas de cruzamento com vigas e lajes. É o critério
usual de medição, e é o lado seguro para compra e para o orçamento -- a forma
naquele trecho existe de todo modo, ainda que recortada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geometria as geo
from .materiais import massa_linear
from .modelo import SecaoPilar


def perimetro_moldante(secao: SecaoPilar) -> float:
    """Perímetro que precisa de forma, cm.

    Soma o contorno externo com os contornos dos vazios: a face interna de um
    pilar vazado também segura concreto. Na seção circular o perímetro sai da
    expressão exata ``pi D``, e não do polígono com que o programa a
    discretiza -- discretizar é decisão de integração, não de medição.
    """
    if secao.tipo == "circular":
        return math.pi * secao.hx
    if secao.tipo == "circular vazada":
        return math.pi * (secao.hx + secao.Di)
    return sum(geo.perimetro_poligono(c) for c in secao.contornos())


@dataclass
class Quantitativo:
    """Quantitativo de um lance, nas unidades do quadro de quantidades."""

    nome: str = ""
    secao: str = ""
    concreto: str = ""               # a classe, "C30"
    altura: float = 0.0              # cm, o lance
    volume_concreto: float = 0.0     # m³
    area_formas: float = 0.0         # m²
    perimetro: float = 0.0           # cm, o que gerou a área de formas
    #: kg de aço por bitola, em mm. Longitudinal e transversal somam na mesma
    #: bitola quando coincidem -- é como se compra.
    aco: dict[float, float] = field(default_factory=dict)
    #: cm, comprimento de corte da barra longitudinal (lance + espera).
    comprimento_barra: float = 0.0

    @property
    def massa_aco(self) -> float:
        """Massa total de aço do lance, kg."""
        return sum(self.aco.values())

    @property
    def taxa_aco(self) -> float:
        """Consumo de aço por metro cúbico de concreto, kg/m³.

        É o número que diz se o pilar está caro: acima de uns 150 kg/m³ em
        pilar de edifício corrente, vale reabrir a seção antes de detalhar.
        """
        return (self.massa_aco / self.volume_concreto
                if self.volume_concreto > 1e-9 else 0.0)


def calcular(res) -> Quantitativo:
    """Quantitativo de um :class:`~pilares.core.dimensionar.ResultadoPilar`.

    O comprimento de corte da barra longitudinal é o lance **mais o
    comprimento de espera** ``l0c``: a barra que sai deste lance para o
    próximo é comprada nesse comprimento, e medi-la só até o topo do lance
    subestimaria o aço de todo pavimento.
    """
    p = res.pilar
    secao = p.secao
    altura = p.lance.altura
    perim = perimetro_moldante(secao)
    q = Quantitativo(
        nome=p.nome,
        secao=secao.descricao(),
        concreto=p.concreto.descricao(),
        altura=altura,
        volume_concreto=secao.area * altura / 1e6,
        area_formas=perim * altura / 1e4,
        perimetro=perim)

    anc, arr, est = res.ancoragem, res.arranjo, res.estribos
    if arr is not None:
        comprimento = altura + (anc.l0c if anc is not None else 0.0)
        q.comprimento_barra = comprimento
        for b in arr.barras:            # bitola por bitola (lista livre)
            q.aco[b.phi] = (q.aco.get(b.phi, 0.0)
                            + massa_linear(b.phi) * comprimento / 100.0)
    if est is not None:
        q.aco[est.phi] = q.aco.get(est.phi, 0.0) + est.massa
    return q


@dataclass
class QuantitativoProjeto:
    """Quantitativo consolidado de vários lances."""

    itens: list[Quantitativo] = field(default_factory=list)

    @property
    def volume_concreto(self) -> float:
        return sum(q.volume_concreto for q in self.itens)

    @property
    def area_formas(self) -> float:
        return sum(q.area_formas for q in self.itens)

    @property
    def massa_aco(self) -> float:
        return sum(q.massa_aco for q in self.itens)

    @property
    def aco_por_bitola(self) -> dict[float, float]:
        """kg por bitola, somando todos os lances -- a lista de compra."""
        saida: dict[float, float] = {}
        for q in self.itens:
            for phi, massa in q.aco.items():
                saida[phi] = saida.get(phi, 0.0) + massa
        return dict(sorted(saida.items()))

    @property
    def concreto_por_classe(self) -> dict[str, float]:
        """m³ por classe de concreto: classes diferentes não se somam na
        compra, e misturar C30 com C40 num total só esconde o traço."""
        saida: dict[str, float] = {}
        for q in self.itens:
            saida[q.concreto] = saida.get(q.concreto, 0.0) + q.volume_concreto
        return dict(sorted(saida.items()))

    @property
    def taxa_aco(self) -> float:
        """kg de aço por m³ de concreto, do conjunto."""
        v = self.volume_concreto
        return self.massa_aco / v if v > 1e-9 else 0.0


def consolidar(resultados) -> QuantitativoProjeto:
    """Quantitativo de uma lista de resultados de pilar."""
    return QuantitativoProjeto(itens=[calcular(r) for r in resultados])


def massa_de_bitola(phi: float, comprimento_cm: float) -> float:
    """Massa de uma barra, kg -- reexportado para quem monta tabela de corte."""
    return massa_linear(phi) * comprimento_cm / 100.0
