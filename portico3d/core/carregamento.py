# -*- coding: utf-8 -*-
"""
carregamento.py
Carga distribuída ao longo da barra: trechos parciais e variação trapezoidal.

A carga de uma barra é uma lista de **segmentos**. Cada segmento cobre um
trecho ``[a, b]`` medido a partir do nó inicial e tem intensidade que varia
linearmente entre as duas pontas. A carga uniforme de barra inteira é o caso
particular ``a=0``, ``b=L``, ``qa=qb`` — e é por isso que a generalização não
custou uma segunda formulação: as fórmulas fechadas do caso uniforme saem
destas por substituição, e as conferências antigas continuam valendo.

As forças de engastamento perfeito saem da integral das funções de forma,

    f = -∫ N(x)ᵀ q(x) dx

com quadratura de Gauss de quatro pontos. O integrando é no máximo do quarto
grau — cúbica de Hermite vezes carga linear —, e quatro pontos integram até o
sétimo grau, de modo que a quadratura é exata, não aproximada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .modelo import CasoDeCarga, ErroDeModelo

_XI, _W = np.polynomial.legendre.leggauss(4)


@dataclass(frozen=True)
class Segmento:
    """Trecho carregado, em abscissas absolutas a partir do nó inicial."""

    a: float
    b: float
    qa: np.ndarray
    qb: np.ndarray

    @property
    def vazio(self) -> bool:
        return self.b <= self.a or (not self.qa.any() and not self.qb.any())


def escalar(segmentos: list[Segmento], fator: float) -> list[Segmento]:
    """Multiplica as intensidades, preservando a geometria dos trechos.

    É o que permite combinar casos de carga: a intensidade entra linearmente
    em tudo que se calcula a partir dela, então combinar é concatenar listas
    de segmentos já escalados.
    """
    return [Segmento(s.a, s.b, fator * s.qa, fator * s.qb) for s in segmentos]


def _intensidade(s: Segmento, x: float) -> np.ndarray:
    if s.b <= s.a:
        return s.qa
    return s.qa + (s.qb - s.qa) * (x - s.a) / (s.b - s.a)


def _hermite(xi: float, L: float, phi: float) -> tuple[float, float, float,
                                                       float]:
    """As quatro funções de forma da flexão, com deformação por cortante.

    Com ``phi`` nulo elas são as cúbicas de Hermite de sempre. O ``phi`` entra
    como uma correção linear em ξ que reparte parte do deslocamento para o
    cisalhamento — e é o mesmo ``phi`` da matriz de rigidez, de propósito: se a
    rigidez fosse de Timoshenko e o vetor de carga de Euler-Bernoulli, os dois
    descreveriam barras diferentes, e o engastamento perfeito deixaria de
    fechar com a rigidez que o recebe.
    """
    d = 1.0 + phi
    h1 = (2.0 * xi ** 3 - 3.0 * xi ** 2 - phi * xi + 1.0 + phi) / d
    h2 = L * (xi ** 3 - (2.0 + phi / 2.0) * xi ** 2
              + (1.0 + phi / 2.0) * xi) / d
    h3 = (-2.0 * xi ** 3 + 3.0 * xi ** 2 + phi * xi) / d
    h4 = L * (xi ** 3 - (1.0 - phi / 2.0) * xi ** 2 - (phi / 2.0) * xi) / d
    return h1, h2, h3, h4


def _matriz_forma(x: float, L: float, phi_y: float = 0.0,
                  phi_z: float = 0.0) -> np.ndarray:
    """N(x), de forma que o deslocamento (u, v, w) valha N(x)·d.

    A linha de w troca o sinal dos termos de rotação porque θy = -dw/dx, que é
    a mesma troca de sinal que aparece na matriz de rigidez.
    """
    xi = x / L
    N = np.zeros((3, 12))

    N[0, 0] = 1.0 - xi
    N[0, 6] = xi

    h1, h2, h3, h4 = _hermite(xi, L, phi_y)
    N[1, 1], N[1, 5], N[1, 7], N[1, 11] = h1, h2, h3, h4

    g1, g2, g3, g4 = _hermite(xi, L, phi_z)
    N[2, 2], N[2, 4], N[2, 8], N[2, 10] = g1, -g2, g3, -g4

    return N


def forcas_engastamento(L: float, segmentos: list[Segmento],
                        phi_y: float = 0.0, phi_z: float = 0.0) -> np.ndarray:
    """Esforços de extremidade da barra biengastada sob os segmentos dados.

    O vetor devolvido são as forças que os nós aplicam sobre a barra,
    positivas no sentido dos eixos locais. ``L`` é o comprimento do vão
    **flexível**, e não a distância entre os nós, quando houver trecho rígido.
    """
    f = np.zeros(12)
    for s in segmentos:
        if s.vazio:
            continue
        meio, semi = (s.b + s.a) / 2.0, (s.b - s.a) / 2.0
        for xi, w in zip(_XI, _W):
            x = meio + semi * xi
            f -= (w * semi * _matriz_forma(x, L, phi_y, phi_z).T
                  @ _intensidade(s, x))
    return f


def acumulado(segmentos: list[Segmento], x: float) -> tuple[np.ndarray, np.ndarray]:
    """Resultante e momento da carga do trecho ``[0, x]``, tomados em ``x``.

    Devolve ``(F, M)`` com ``F = ∫₀ˣ q ds`` e ``M = ∫₀ˣ q(s)·(x - s) ds``,
    ambos vetores de três componentes nos eixos locais. São exatamente as duas
    integrais de que os diagramas precisam, e aqui saem em forma fechada.
    """
    F = np.zeros(3)
    M = np.zeros(3)
    for s in segmentos:
        if s.vazio or x <= s.a:
            continue
        u = min(x, s.b)
        comprimento = u - s.a
        inclinacao = ((s.qb - s.qa) / (s.b - s.a) if s.b > s.a
                      else np.zeros(3))
        braco = x - s.a
        F += comprimento * (s.qa + _intensidade(s, u)) / 2.0
        M += (s.qa * (braco * comprimento - comprimento ** 2 / 2.0)
              + inclinacao * (braco * comprimento ** 2 / 2.0
                              - comprimento ** 3 / 3.0))
    return F, M


def resultante(segmentos: list[Segmento]) -> tuple[np.ndarray, np.ndarray]:
    """Resultante total e o seu ponto de aplicação, por componente.

    O ponto de aplicação sai por componente porque as três direções podem ter
    distribuições diferentes. Onde a resultante é nula, devolve o meio da
    barra, que é neutro para o que se faz com ela.
    """
    F = np.zeros(3)
    momento = np.zeros(3)
    for s in segmentos:
        if s.vazio:
            continue
        comprimento = s.b - s.a
        parcela = comprimento * (s.qa + s.qb) / 2.0
        # Centroide do trapézio, medido a partir de a.
        soma = s.qa + s.qb
        centro = np.where(
            np.abs(soma) > 0.0,
            comprimento * (s.qa + 2.0 * s.qb) / (3.0 * np.where(
                np.abs(soma) > 0.0, soma, 1.0)),
            comprimento / 2.0)
        F += parcela
        momento += parcela * (s.a + centro)
    posicao = np.where(np.abs(F) > 0.0, momento / np.where(
        np.abs(F) > 0.0, F, 1.0), 0.0)
    return F, posicao


def segmentos_da_barra(caso: CasoDeCarga, nome: str, L: float,
                       R: np.ndarray) -> list[Segmento]:
    """Converte as cargas distribuídas de um caso nos segmentos de uma barra."""
    segmentos = []
    for carga in caso.distribuidas:
        if carga.barra != nome:
            continue
        if not 0.0 <= carga.inicio < carga.fim <= 1.0:
            raise ErroDeModelo(
                f"carga na barra '{nome}': trecho [{carga.inicio}, "
                f"{carga.fim}] fora do intervalo 0 a 1")
        qa, qb = carga.vetor_inicio, carga.vetor_fim
        if carga.sistema == "global":
            qa, qb = R @ qa, R @ qb
        segmentos.append(Segmento(carga.inicio * L, carga.fim * L, qa, qb))
    return segmentos
