# -*- coding: utf-8 -*-
"""
envoltoria.py
Envoltória de esforços ao longo das barras, com os valores concomitantes.

O ponto que justifica o módulo inteiro: **os esforços concomitantes**. Guardar
só o maior N, o maior My e o maior Mz de uma barra é inútil para o
dimensionamento de pilar, porque os três máximos costumam vir de combinações
diferentes, e a flexão composta oblíqua é verificada com um trio simultâneo.
Aqui, cada extremo carrega os seis esforços da combinação que o produziu, e o
nome dessa combinação.

Fica registrado o que a envoltória é: uma **seleção**. Ela guarda as
combinações que governam algum componente em alguma estação. Para o rigor
completo da flexão composta oblíqua, o caminho seguro é verificar todas as
combinações — e é por isso que o nome da combinação vai junto, para que o
orquestrador possa voltar a ela quando quiser.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .modelo import ErroDeModelo, Modelo
from .resultados import COMPONENTES, Resultado


@dataclass(frozen=True)
class Extremo:
    """Um valor extremo, com quem o acompanhava quando aconteceu."""

    barra: str
    componente: str
    tipo: str
    valor: float
    x: float
    combinacao: str
    esforcos: dict[str, float]

    def __str__(self) -> str:
        acompanham = "  ".join(f"{k}={v:+.4f}" for k, v in self.esforcos.items())
        return (f"{self.barra} {self.componente} {self.tipo} = {self.valor:+.4f} "
                f"em x={self.x:.3f} por '{self.combinacao}'  [{acompanham}]")


@dataclass
class EnvoltoriaBarra:
    barra: str
    x: np.ndarray
    combinacoes: list[str]
    maximos: np.ndarray          # (6, n)
    minimos: np.ndarray          # (6, n)
    indice_max: np.ndarray       # (6, n) — combinação que produziu o máximo
    indice_min: np.ndarray       # (6, n)
    concomitantes_max: np.ndarray   # (6, n, 6)
    concomitantes_min: np.ndarray   # (6, n, 6)

    def _extremo(self, componente: str, tipo: str, estacao: int) -> Extremo:
        c = COMPONENTES.index(componente)
        if tipo == "max":
            valor = self.maximos[c, estacao]
            indice = self.indice_max[c, estacao]
            acompanham = self.concomitantes_max[c, estacao]
        else:
            valor = self.minimos[c, estacao]
            indice = self.indice_min[c, estacao]
            acompanham = self.concomitantes_min[c, estacao]
        return Extremo(self.barra, componente, tipo, float(valor),
                       float(self.x[estacao]), self.combinacoes[int(indice)],
                       {k: float(v) for k, v in zip(COMPONENTES, acompanham)})

    def extremo(self, componente: str, tipo: str = "max") -> Extremo:
        """O maior (ou menor) valor do componente ao longo de toda a barra."""
        if componente not in COMPONENTES:
            raise ErroDeModelo(f"componente '{componente}' não existe")
        c = COMPONENTES.index(componente)
        linha = self.maximos[c] if tipo == "max" else self.minimos[c]
        estacao = int(np.argmax(linha) if tipo == "max" else np.argmin(linha))
        return self._extremo(componente, tipo, estacao)

    def extremos(self) -> list[Extremo]:
        """Os doze extremos da barra: máximo e mínimo de cada componente."""
        return [self.extremo(c, t) for c in COMPONENTES for t in ("max", "min")]

    def casos_de_dimensionamento(self, estacoes: list[int] | None = None
                                 ) -> list[dict]:
        """Os conjuntos de esforços simultâneos que governam a barra.

        Um registro por combinação que governa algum componente na estação,
        com os seis esforços daquela combinação naquele ponto. É este o
        formato que vai alimentar os programas de elemento na fase 4.
        """
        if estacoes is None:
            estacoes = [0, len(self.x) - 1]

        vistos: set[tuple[int, str]] = set()
        saida = []
        for estacao in estacoes:
            for componente in COMPONENTES:
                for tipo in ("max", "min"):
                    e = self._extremo(componente, tipo, estacao)
                    chave = (estacao, e.combinacao)
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    saida.append({"barra": self.barra, "x": e.x,
                                  "combinacao": e.combinacao, **e.esforcos})
        return saida


class Acumulador:
    """Percorre as combinações uma a uma, guardando só os extremos.

    Somar tudo em memória e depois reduzir seria mais simples de escrever, mas
    um edifício com milhares de barras e dezenas de combinações não cabe nessa
    conta. O acumulador mantém, por barra, apenas os arrays de extremos e de
    concomitantes — o custo não cresce com o número de combinações.
    """

    def __init__(self, modelo: Modelo, n_estacoes: int = 11) -> None:
        if n_estacoes < 2:
            raise ErroDeModelo("a envoltória precisa de ao menos duas estações")
        self.modelo = modelo
        self.n = n_estacoes
        self.combinacoes: list[str] = []
        forma = (6, n_estacoes)
        self._max = {b: np.full(forma, -np.inf) for b in modelo.barras}
        self._min = {b: np.full(forma, np.inf) for b in modelo.barras}
        self._imax = {b: np.zeros(forma, int) for b in modelo.barras}
        self._imin = {b: np.zeros(forma, int) for b in modelo.barras}
        self._cmax = {b: np.zeros((*forma, 6)) for b in modelo.barras}
        self._cmin = {b: np.zeros((*forma, 6)) for b in modelo.barras}
        self._x: dict[str, np.ndarray] = {}

    def acrescentar(self, resultado: Resultado) -> None:
        indice = len(self.combinacoes)
        self.combinacoes.append(resultado.caso)

        for barra in self.modelo.barras:
            d = resultado.diagrama(barra, self.n)
            self._x[barra] = d.x
            E = np.vstack([getattr(d, c) for c in COMPONENTES])
            acompanham = np.broadcast_to(E.T[None, :, :], (6, self.n, 6))

            maior = E > self._max[barra]
            self._max[barra][maior] = E[maior]
            self._imax[barra][maior] = indice
            self._cmax[barra][maior] = acompanham[maior]

            menor = E < self._min[barra]
            self._min[barra][menor] = E[menor]
            self._imin[barra][menor] = indice
            self._cmin[barra][menor] = acompanham[menor]

    def concluir(self) -> dict[str, EnvoltoriaBarra]:
        if not self.combinacoes:
            raise ErroDeModelo("nenhuma combinação foi acrescentada")
        return {b: EnvoltoriaBarra(b, self._x[b], list(self.combinacoes),
                                   self._max[b], self._min[b], self._imax[b],
                                   self._imin[b], self._cmax[b], self._cmin[b])
                for b in self.modelo.barras}


def envoltoria(modelo: Modelo, resultados: dict[str, Resultado],
               n_estacoes: int = 11) -> dict[str, EnvoltoriaBarra]:
    """Envoltória de todas as barras sobre os resultados dados."""
    acumulador = Acumulador(modelo, n_estacoes)
    for resultado in resultados.values():
        acumulador.acrescentar(resultado)
    return acumulador.concluir()
