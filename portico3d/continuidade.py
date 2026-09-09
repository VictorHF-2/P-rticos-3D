# -*- coding: utf-8 -*-
"""
continuidade.py
Reconhece vigas contínuas dentro do pórtico.

No modelo do pórtico não existe "viga de três vãos": existem três barras
alinhadas, uma atrás da outra. Quem lê o desenho vê uma viga contínua; o
programa precisa ser ensinado a ver o mesmo, e é isso que este módulo faz.

## A regra

Duas barras entram na mesma viga quando são **horizontais**, **colineares** e
se **encontram num nó**. A cadeia cresce enquanto isso valer, e para quando o
alinhamento muda de direção ou o nó seguinte não continua.

Dentro da cadeia, os nós se dividem em dois tipos, e a distinção é o que
define os vãos:

* **apoio** — o nó em que chega um pilar. É ali que a viga descarrega;
* **passagem** — o nó que existe só porque a malha foi dividida ali, por uma
  carga concentrada ou por um encontro com outra viga. Ele **não** é apoio, e
  tratá-lo como tal inventaria um vão que não existe.

Uma cadeia sem nenhum pilar não é viga contínua para este fim: é viga apoiada
em outras vigas, e o programa a declara em vez de fingir que tem apoio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .core.modelo import ErroDeModelo, Modelo

TOL_ANGULO = 1.0e-6      # tolerância de colinearidade, em seno do ângulo
TOL_VERTICAL = 1.0e-3


@dataclass
class VigaContinua:
    """Uma cadeia de barras colineares que forma uma viga contínua."""

    nome: str
    barras: list[str] = field(default_factory=list)
    nos: list[str] = field(default_factory=list)
    #: Índices, dentro de ``nos``, dos nós em que chega um pilar.
    apoios: list[int] = field(default_factory=list)
    #: Posição de cada nó ao longo da viga, em metros a partir do primeiro.
    posicoes: list[float] = field(default_factory=list)
    direcao: tuple[float, float, float] = (1.0, 0.0, 0.0)

    @property
    def comprimento(self) -> float:
        return self.posicoes[-1] if self.posicoes else 0.0

    @property
    def vaos(self) -> list[float]:
        """Os vãos entre apoios consecutivos, em metros."""
        return [self.posicoes[b] - self.posicoes[a]
                for a, b in zip(self.apoios, self.apoios[1:])]

    @property
    def balanco_inicial(self) -> float:
        return self.posicoes[self.apoios[0]] if self.apoios else 0.0

    @property
    def balanco_final(self) -> float:
        return (self.comprimento - self.posicoes[self.apoios[-1]]
                if self.apoios else 0.0)

    def __str__(self) -> str:
        vaos = " + ".join(f"{v:.2f}" for v in self.vaos) or "sem vão"
        extras = []
        if self.balanco_inicial > 1e-9:
            extras.append(f"balanço inicial {self.balanco_inicial:.2f} m")
        if self.balanco_final > 1e-9:
            extras.append(f"balanço final {self.balanco_final:.2f} m")
        return (f"{self.nome}: {len(self.barras)} barras, "
                f"{len(self.apoios)} apoios, vãos {vaos} m"
                + ("  (" + ", ".join(extras) + ")" if extras else ""))


def _eh_vertical(modelo: Modelo, barra) -> bool:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    return (abs(d[2]) > 1e-9
            and float(np.hypot(d[0], d[1])) < TOL_VERTICAL * abs(d[2]))


def _eh_horizontal(modelo: Modelo, barra) -> bool:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    comprimento = float(np.linalg.norm(d))
    return comprimento > 1e-9 and abs(d[2]) < TOL_ANGULO * comprimento


def nos_com_pilar(modelo: Modelo) -> set[str]:
    """Os nós em que chega alguma barra vertical."""
    apoiados = set()
    for barra in modelo.barras.values():
        if _eh_vertical(modelo, barra):
            apoiados.add(barra.no_i)
            apoiados.add(barra.no_j)
    return apoiados


def _direcao(modelo: Modelo, barra) -> np.ndarray:
    d = modelo.ponto(barra.no_j) - modelo.ponto(barra.no_i)
    return d / float(np.linalg.norm(d))


def vigas_continuas(modelo: Modelo) -> list[VigaContinua]:
    """Agrupa as barras horizontais em vigas contínuas."""
    horizontais = {nome: b for nome, b in modelo.barras.items()
                   if _eh_horizontal(modelo, b)}
    if not horizontais:
        return []

    # Quais barras horizontais chegam a cada nó.
    incidentes: dict[str, list[str]] = {}
    for nome, b in horizontais.items():
        incidentes.setdefault(b.no_i, []).append(nome)
        incidentes.setdefault(b.no_j, []).append(nome)

    def continua(atual: str, no: str) -> str | None:
        """A barra que segue reto a partir de ``no``, se houver só uma."""
        eixo = _direcao(modelo, horizontais[atual])
        candidatas = []
        for outra in incidentes.get(no, []):
            if outra == atual:
                continue
            eixo_outra = _direcao(modelo, horizontais[outra])
            if float(np.linalg.norm(np.cross(eixo, eixo_outra))) < TOL_ANGULO:
                candidatas.append(outra)
        # Duas barras seguindo reto do mesmo nó seriam sobreposição; nesse
        # caso a cadeia para, em vez de escolher uma por sorteio.
        return candidatas[0] if len(candidatas) == 1 else None

    pilares = nos_com_pilar(modelo)
    vistas: set[str] = set()
    vigas = []

    for nome in horizontais:
        if nome in vistas:
            continue

        # Anda para trás até o começo da cadeia, depois para a frente.
        cadeia = [nome]
        vistas.add(nome)
        atual, no = nome, horizontais[nome].no_i
        while (proxima := continua(atual, no)) is not None and proxima not in vistas:
            cadeia.insert(0, proxima)
            vistas.add(proxima)
            b = horizontais[proxima]
            no = b.no_j if b.no_i == no else b.no_i
            atual = proxima
        atual, no = nome, horizontais[nome].no_j
        while (proxima := continua(atual, no)) is not None and proxima not in vistas:
            cadeia.append(proxima)
            vistas.add(proxima)
            b = horizontais[proxima]
            no = b.no_j if b.no_i == no else b.no_i
            atual = proxima

        vigas.append(_montar(modelo, cadeia, pilares, len(vigas) + 1))

    vigas.sort(key=lambda v: (-len(v.barras), v.nome))
    return vigas


def _montar(modelo: Modelo, cadeia: list[str], pilares: set[str],
            indice: int) -> VigaContinua:
    """Ordena os nós da cadeia e mede as posições ao longo dela."""
    # Sequência de nós, seguindo as barras encadeadas.
    primeira = modelo.barras[cadeia[0]]
    if len(cadeia) == 1:
        nos = [primeira.no_i, primeira.no_j]
    else:
        segunda = modelo.barras[cadeia[1]]
        comum = {primeira.no_i, primeira.no_j} & {segunda.no_i, segunda.no_j}
        inicio = (primeira.no_j if primeira.no_i in comum else primeira.no_i)
        nos = [inicio]
        atual = inicio
        for nome in cadeia:
            b = modelo.barras[nome]
            atual = b.no_j if b.no_i == atual else b.no_i
            nos.append(atual)

    origem = modelo.ponto(nos[0])
    eixo = modelo.ponto(nos[-1]) - origem
    eixo = eixo / float(np.linalg.norm(eixo))
    posicoes = [float(np.dot(modelo.ponto(n) - origem, eixo)) for n in nos]

    # A cadeia pode ter sido montada de trás para a frente.
    if posicoes[-1] < 0.0:
        nos.reverse()
        cadeia = list(reversed(cadeia))
        origem = modelo.ponto(nos[0])
        eixo = -eixo
        posicoes = [float(np.dot(modelo.ponto(n) - origem, eixo)) for n in nos]

    apoios = [i for i, n in enumerate(nos) if n in pilares]
    return VigaContinua(nome=f"V{indice}", barras=cadeia, nos=nos,
                        apoios=apoios, posicoes=posicoes,
                        direcao=tuple(float(c) for c in eixo))


def viga_que_contem(vigas: list[VigaContinua], barra: str) -> VigaContinua:
    for viga in vigas:
        if barra in viga.barras:
            return viga
    raise ErroDeModelo(f"a barra '{barra}' não está em nenhuma viga contínua")
