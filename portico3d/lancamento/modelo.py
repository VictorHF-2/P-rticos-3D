# -*- coding: utf-8 -*-
"""
modelo.py
O lançamento estrutural: o edifício como o engenheiro o desenha — pavimentos,
e em cada pavimento a planta de fôrma com pilares, vigas, lajes e paredes.

É a entrada dos programas de edifício, e é diferente do ``core.Modelo``, que
é o modelo de **cálculo** (nós e barras). Do lançamento sai o modelo de
cálculo pelo ``gerador``; quem lança não digita nó nenhum.

Convenções:

* unidades em metros e kN, como no resto do programa;
* a planta é em X e Y; a cota do pavimento é a do **eixo das vigas** dele,
  que é onde o modelo de barras põe os nós;
* **o pilar lançado na planta de um pavimento é o lance que chega nele**, do
  pavimento de baixo (ou da fundação) até este. Um pilar que existe só num
  pavimento é um pilarete; um que não tem pilar embaixo nasce na viga do
  pavimento de baixo (pilar de transição);
* uma **planta** pode servir a vários pavimentos — o pavimento-tipo: lança-se
  uma vez, e cada pavimento que a usa a repete na sua cota.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.modelo import OpcoesDeCalculo

#: Pontos de inserção do pilar: o centro, ou um dos cantos da seção (os
#: pontos cardeais, no sistema local do pilar antes do giro).
INSERCOES = ("centro", "SO", "SE", "NE", "NO")


@dataclass
class PilarLancado:
    """Um pilar na planta: posição, seção e como ela se orienta.

    ``b`` mede na direção X local e ``h`` na Y local; ``angulo`` gira a
    seção em planta, em graus, anti-horário. ``insercao`` diz que ponto da
    seção está em ``(x, y)``: o centro, ou um canto — é como se encosta a
    face do pilar na face da parede.
    """

    nome: str
    x: float
    y: float
    b: float = 0.20
    h: float = 0.40
    angulo: float = 0.0
    insercao: str = "centro"

    @property
    def centro(self) -> tuple[float, float]:
        if self.insercao == "centro":
            return self.x, self.y
        sx = {"SO": 1, "NO": 1, "SE": -1, "NE": -1}[self.insercao]
        sy = {"SO": 1, "SE": 1, "NO": -1, "NE": -1}[self.insercao]
        dx, dy = sx * self.b / 2.0, sy * self.h / 2.0
        a = math.radians(self.angulo)
        c, s = math.cos(a), math.sin(a)
        return self.x + c * dx - s * dy, self.y + s * dx + c * dy

    def dimensao_na_direcao(self, dx: float, dy: float) -> float:
        """A dimensão da seção medida na direção ``(dx, dy)`` de planta: é o
        que a viga que chega nessa direção atravessa."""
        n = math.hypot(dx, dy) or 1.0
        a = math.radians(self.angulo)
        ex, ey = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
        cx = abs(dx * ex[0] + dy * ex[1]) / n
        cy = abs(dx * ey[0] + dy * ey[1]) / n
        return cx * self.b + cy * self.h


@dataclass
class VigaLancada:
    """Uma viga como polilinha de planta, de ponta a ponta.

    O gerador a quebra onde ela cruza outra viga ou passa por um pilar, e
    decide sozinho os apoios. ``pontos`` são os vértices, ``b`` × ``h`` a
    seção.
    """

    nome: str
    pontos: list[tuple[float, float]]
    b: float = 0.15
    h: float = 0.40


@dataclass
class LajeLancada:
    """Uma laje: um ponto dentro do contorno de vigas que a fecha — ou, em
    balanço, um ponto na sacada, com ``balanco`` e ``sentido``.

    O gerador acha o retângulo de vigas em volta do ponto. Os campos de laje
    são os do ``core.Laje`` (espessura, cargas, tipo e os da treliçada).
    """

    nome: str
    x: float
    y: float
    espessura: float = 0.10
    permanente: float = 0.0
    acidental: float = 0.0
    tipo_carga: str = ""
    tipo: str = "macica"
    direcao: str = "x"
    trelica: str = "TR 12646"
    enchimento: str = "EPS"
    altura_enchimento: float = 0.0
    capa: float = 0.0
    largura_bloco: float = 0.40
    base_vigota: float = 0.12
    #: Laje em balanço: o comprimento, m, do eixo da viga de apoio até a
    #: borda livre, e para onde ela avança (``+x``, ``-x``, ``+y``, ``-y``).
    #: O ponto ``(x, y)`` fica na sacada; a viga de apoio é a primeira atrás
    #: dele, contra o sentido. Zero é a laje comum, fechada por vigas.
    balanco: float = 0.0
    sentido: str = ""


@dataclass
class ParedeLancada:
    """Uma parede sobre viga: polilinha, espessura e peso específico.

    A altura padrão (``altura = 0``) é a distância até o pavimento de cima
    menos a altura da viga que a recebe — a parede vai do topo de uma viga
    ao fundo da de cima.
    """

    nome: str
    pontos: list[tuple[float, float]]
    espessura: float = 0.15
    peso_especifico: float = 13.0       # kN/m³, alvenaria de bloco cerâmico
    altura: float = 0.0


@dataclass
class Planta:
    """A planta de fôrma — a de um pavimento, ou a de um pavimento-tipo."""

    nome: str
    pilares: list[PilarLancado] = field(default_factory=list)
    vigas: list[VigaLancada] = field(default_factory=list)
    lajes: list[LajeLancada] = field(default_factory=list)
    paredes: list[ParedeLancada] = field(default_factory=list)


@dataclass
class Pavimento:
    nome: str
    cota: float
    planta: str


@dataclass
class VentoLancado:
    """Vento da NBR 6123, nas quatro direções dos eixos (``v0 = 0`` desliga)."""

    v0: float = 0.0
    categoria: str = "II"
    grupo_s3: str = "2"
    s1: float = 1.0


def nome_de_coluna(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, como as colunas de uma planilha."""
    nome = ""
    indice += 1
    while indice > 0:
        indice, resto = divmod(indice - 1, 26)
        nome = chr(ord("A") + resto) + nome
    return nome


@dataclass
class Grelha:
    """Os eixos do projeto: colunas verticais com letras, linhas horizontais
    com números.

    A coluna A passa em ``x0`` e as seguintes vêm à direita, nos espaços de
    ``espacos_colunas``; a linha 1 passa em ``y0`` e as seguintes vêm para
    cima, nos espaços de ``espacos_linhas``. Cada espaço é guardado por si:
    mudar um não mexe nos outros, só desloca os eixos que vêm depois dele. O
    encontro "2-E" é a linha 2 com a coluna E.
    """

    x0: float = 0.0
    y0: float = 0.0
    espacos_colunas: list[float] = field(default_factory=list)
    espacos_linhas: list[float] = field(default_factory=list)

    @property
    def xs(self) -> list[float]:
        xs = [self.x0]
        for e in self.espacos_colunas:
            xs.append(xs[-1] + e)
        return xs

    @property
    def ys(self) -> list[float]:
        ys = [self.y0]
        for e in self.espacos_linhas:
            ys.append(ys[-1] + e)
        return ys

    @property
    def colunas(self) -> list[tuple[str, float]]:
        return [(nome_de_coluna(k), x) for k, x in enumerate(self.xs)]

    @property
    def linhas(self) -> list[tuple[str, float]]:
        return [(str(k + 1), y) for k, y in enumerate(self.ys)]

    def encontros(self) -> list[tuple[str, float, float]]:
        """Todos os encontros, como ("2-E", x, y)."""
        return [(f"{ln}-{cn}", x, y) for ln, y in self.linhas
                for cn, x in self.colunas]

    def encontro(self, nome: str) -> tuple[float, float]:
        for n, x, y in self.encontros():
            if n == nome.strip().upper():
                return x, y
        raise KeyError(f"a grelha não tem o encontro {nome}")


@dataclass
class Lancamento:
    nome: str = "edificio"
    fck: float = 30.0
    agregado: str = "granito e gnaisse"
    peso_especifico: float = 25.0
    cota_base: float = 0.0
    #: Trechos rígidos viga–pilar pelo 14.6.2.1 (Figura 14.1): do eixo do
    #: pilar até 0,3·h da viga antes da face.
    trecho_rigido: bool = True
    categoria_acidental: str = "residencial"
    plantas: dict[str, Planta] = field(default_factory=dict)
    pavimentos: list[Pavimento] = field(default_factory=list)
    cargas_de_laje: dict[str, tuple[float, float]] = field(
        default_factory=dict)
    vento: VentoLancado = field(default_factory=VentoLancado)
    calculo: OpcoesDeCalculo = field(default_factory=OpcoesDeCalculo)
    #: Os eixos do projeto, comuns a todas as plantas (``None`` = sem grelha).
    grelha: Grelha | None = None

    def planta(self, nome: str) -> Planta:
        if nome not in self.plantas:
            self.plantas[nome] = Planta(nome)
        return self.plantas[nome]
