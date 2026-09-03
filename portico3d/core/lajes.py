# -*- coding: utf-8 -*-
"""
lajes.py
Painéis de laje: peso próprio, revestimento e acidental, repartidos às vigas.

A laje entra como **carga**, não como elemento. O painel é retangular, dado
por dois cantos de uma diagonal, e a sua carga vai para as quatro vigas de
contorno pelas áreas de influência delimitadas por retas a 45° saindo dos
cantos — o processo das áreas, que é como se faz à mão e como a maioria dos
programas de edifício faz.

Isso reparte o painel em dois triângulos, sobre os lados menores, e dois
trapézios, sobre os maiores. Daí a viga do lado menor recebe carga triangular
e a do maior, trapezoidal — que é exatamente o tipo de carga que o solver
passou a aceitar na fase 2, e é por isso que esta peça coube sem tocar no
núcleo.

**Uma laje nesta lista não é diafragma.** Ela não enrijece o pavimento no
próprio plano: cada prumada resiste ao vento pela sua própria rigidez, sem a
compatibilização horizontal que a laje real impõe. Para pórtico de contraventamento
regular a diferença é pequena; para planta muito assimétrica, não é.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .modelo import CasoDeCarga, ErroDeModelo, Laje, Modelo

TOLERANCIA = 1.0e-6


@dataclass
class Aresta:
    """Um lado do painel e a viga que o percorre."""

    barra: str
    comprimento: float
    total: float = 0.0


@dataclass
class RepasseDeLaje:
    """O que a laje entregou, para poder ir para a memória de cálculo."""

    laje: str
    lx: float
    ly: float
    area: float
    carga: float
    arestas: list[Aresta] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(a.total for a in self.arestas)

    def __str__(self) -> str:
        linhas = [f"laje {self.laje}: {self.lx:.3f} × {self.ly:.3f} m, "
                  f"{self.area:.3f} m², q = {self.carga:.4f} kN/m²  "
                  f"→ {self.total:.4f} kN"]
        for a in self.arestas:
            linhas.append(f"    {a.barra:<12} L = {a.comprimento:.3f} m   "
                          f"{a.total:.4f} kN")
        return "\n".join(linhas)


def _cantos(modelo: Modelo, laje: Laje) -> tuple[list[str], float, float]:
    """Os quatro cantos do painel, em volta, mais os lados em X e Y."""
    for no in (laje.no_a, laje.no_c):
        if no not in modelo.nos:
            raise ErroDeModelo(
                f"laje '{laje.nome}': o nó '{no}' não existe")

    a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
    if abs(a[2] - c[2]) > TOLERANCIA:
        raise ErroDeModelo(
            f"laje '{laje.nome}': os cantos estão em cotas diferentes "
            f"({a[2]:.3f} e {c[2]:.3f} m); o painel tem de ser horizontal")

    lx, ly = abs(c[0] - a[0]), abs(c[1] - a[1])
    if lx <= TOLERANCIA or ly <= TOLERANCIA:
        raise ErroDeModelo(
            f"laje '{laje.nome}': os cantos '{laje.no_a}' e '{laje.no_c}' não "
            "formam retângulo — eles têm de ser diagonalmente opostos")

    x0, x1 = min(a[0], c[0]), max(a[0], c[0])
    y0, y1 = min(a[1], c[1]), max(a[1], c[1])
    z = a[2]

    procurados = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    cantos = []
    for x, y in procurados:
        achado = None
        for nome, no in modelo.nos.items():
            if (abs(no.x - x) < TOLERANCIA and abs(no.y - y) < TOLERANCIA
                    and abs(no.z - z) < TOLERANCIA):
                achado = nome
                break
        if achado is None:
            raise ErroDeModelo(
                f"laje '{laje.nome}': falta o nó do canto ({x:.3f}, {y:.3f}, "
                f"{z:.3f})")
        cantos.append(achado)

    return cantos, lx, ly


def _barra_entre(modelo: Modelo, no_i: str, no_j: str, laje: str) -> str:
    for nome, barra in modelo.barras.items():
        if {barra.no_i, barra.no_j} == {no_i, no_j}:
            return nome
    raise ErroDeModelo(
        f"laje '{laje}': não há viga entre '{no_i}' e '{no_j}'. O painel "
        "precisa das quatro vigas de contorno; se o lado for vencido por mais "
        "de uma viga, divida a laje em painéis menores")


def arestas_da_laje(modelo: Modelo, laje: Laje) -> tuple[list[Aresta], float,
                                                         float]:
    cantos, lx, ly = _cantos(modelo, laje)
    arestas = []
    for k in range(4):
        nome = _barra_entre(modelo, cantos[k], cantos[(k + 1) % 4], laje.nome)
        arestas.append(Aresta(nome, modelo.comprimento(nome)))
    return arestas, lx, ly


def carga_permanente(modelo: Modelo, laje: Laje) -> float:
    """Peso próprio da espessura mais o revestimento, em kN/m²."""
    peso = 0.0
    if laje.espessura > 0.0:
        if laje.material not in modelo.materiais:
            raise ErroDeModelo(
                f"laje '{laje.nome}': material '{laje.material}' não existe, e "
                "sem ele não há como pesar a espessura")
        peso = laje.espessura * modelo.materiais[laje.material].peso_especifico
    return peso + laje.permanente


def distribuir(modelo: Modelo, laje: Laje, caso: CasoDeCarga,
               carga: float) -> RepasseDeLaje:
    """Reparte ``carga`` (kN/m²) do painel para as quatro vigas de contorno.

    O quinhão de cada aresta é ``q·lx·(2·Le − lx)/4``, com ``lx`` o **menor**
    lado do painel e ``Le`` o comprimento da aresta. A fórmula é a mesma para
    o lado curto e para o longo — no curto, ``Le = lx`` e ela cai em
    ``q·lx²/4``, que é a área do triângulo. A soma das quatro dá ``q·lx·ly``
    exatamente, e há conferência para isso.

    A carga é emitida em segmentos: rampa, patamar e rampa. Onde o painel é
    quadrado o patamar tem comprimento nulo e some, restando o triângulo.
    """
    arestas, lx, ly = arestas_da_laje(modelo, laje)
    menor = min(lx, ly)
    repasse = RepasseDeLaje(laje.nome, min(lx, ly), max(lx, ly), lx * ly,
                            carga, arestas)
    if carga == 0.0:
        return repasse

    for aresta in arestas:
        Le = aresta.comprimento
        aresta.total = carga * menor * (2.0 * Le - menor) / 4.0

        # O perfil é desenhado sobre o vão flexível, que é menor que a aresta
        # quando a viga tem trecho rígido. A intensidade é calculada a partir
        # do total, e não da geometria do painel, justamente para que a carga
        # que cairia sobre o trecho rígido não desapareça do modelo.
        p = modelo.barras[aresta.barra]
        vao = Le - p.offset_i - p.offset_j
        rampa = min(menor / 2.0, vao / 2.0)
        pico = aresta.total / (vao - rampa)

        a = rampa / vao
        b = 1.0 - a
        caso.distribuida(aresta.barra, qz=0.0, qz_fim=-pico, inicio=0.0,
                         fim=a, sistema="global")
        if b - a > TOLERANCIA:
            caso.distribuida(aresta.barra, qz=-pico, inicio=a, fim=b,
                             sistema="global")
        caso.distribuida(aresta.barra, qz=-pico, qz_fim=0.0, inicio=b,
                         fim=1.0, sistema="global")

    return repasse


def aplicar_lajes(modelo: Modelo, permanente: CasoDeCarga,
                  acidental: CasoDeCarga | None = None
                  ) -> list[RepasseDeLaje]:
    """Distribui todas as lajes do modelo para os casos indicados."""
    repasses = []
    for laje in modelo.lajes.values():
        repasses.append(distribuir(modelo, laje, permanente,
                                   carga_permanente(modelo, laje)))
        if acidental is not None and laje.acidental != 0.0:
            distribuir(modelo, laje, acidental, laje.acidental)
    return repasses


def area_total(modelo: Modelo) -> float:
    total = 0.0
    for laje in modelo.lajes.values():
        _, lx, ly = _cantos(modelo, laje)
        total += lx * ly
    return total
