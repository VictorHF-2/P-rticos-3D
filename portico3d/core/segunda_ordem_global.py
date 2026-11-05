# -*- coding: utf-8 -*-
"""
segunda_ordem_global.py
Os esforços com que pilares e vigas são dimensionados, já com a 2ª ordem
global — NBR 6118:2026, 15.4.2, 15.5.3, 15.7.1 a 15.7.3.

O item 15.7.1 manda: em estrutura de nós móveis, "no dimensionamento devem
ser obrigatoriamente considerados os efeitos globais e locais de 2ª ordem".
Os locais são do motor de Pilares (curvatura aproximada, 15.8.3.3.2). Os
globais são daqui, e até esta revisão **não chegavam ao dimensionamento**: a
envoltória era de 1ª ordem pura, e o γz era só relatado.

Combinação a combinação, pelo γz dela:

* **γz ≤ 1,10** — nós fixos (15.4.2): a 1ª ordem basta.
* **1,10 < γz ≤ 1,30**, com ao menos quatro andares — majoração das ações
  horizontais da combinação por 0,95·γz (15.7.2), por superposição dos casos
  já resolvidos.
* **γz > 1,30**, ou menos de quatro andares (onde o γz não vale, 15.5.3) com
  γz > 1,10 — análise P-Δ da combinação, com a rigidez secante do 15.7.3.
* Combinação **sem ação horizontal**: γz não é definido; vale a 1ª ordem —
  mas o desaprumo entra nas combinações da NBR como ação horizontal, de modo
  que isso só acontece num modelo sem desaprumo nem vento.

O γz é calculado com a **rigidez secante** do 15.7.3 (0,8 nos pilares, 0,4
nas vigas, 0,3 nas lajes em grelha), que é a rigidez com que a norma pede a
análise dos esforços globais de 2ª ordem. Com a rigidez cheia ele sai menor
que o de projeto, e era o que a janela relatava antes.

Os esforços de 1ª ordem que a majoração multiplica são os do modelo com a
rigidez cheia — a distribuição de esforços em serviço; a P-Δ, quando
necessária, é feita no modelo com a rigidez secante, e são os esforços dela
que vão ao dimensionamento.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .combinacoes import Combinacao, caso_efetivo, combinar, resolver_casos
from .estabilidade import (ANDARES_MINIMOS_GAMA_Z, GAMA_Z_LIMITE_MAJORACAO,
                           GAMA_Z_NOS_FIXOS, RIGIDEZ_LAJE, contar_andares,
                           gama_z, majorar_horizontais, rigidez_secante)
from .modelo import ErroDeModelo, Modelo
from .montagem import resolver
from .resultados import Resultado

PRIMEIRA_ORDEM = "1ª ordem"
MAJORACAO = "0,95·γz"
P_DELTA = "P-Δ"


@dataclass
class TratamentoDaCombinacao:
    """O que foi feito com uma combinação, e por quê."""

    combinacao: str
    gama_z: float | None
    tratamento: str
    motivo: str

    def __str__(self) -> str:
        g = "  γz   —  " if self.gama_z is None else f"γz {self.gama_z:.3f}"
        return f"  {self.combinacao:<14} {g}  {self.tratamento:<9} {self.motivo}"


def modelo_secante(modelo: Modelo) -> Modelo:
    """O modelo com a rigidez do 15.7.3, inclusive a da laje em grelha."""
    m = rigidez_secante(modelo).modelo
    m.calculo = replace(m.calculo, fator_rigidez_laje=RIGIDEZ_LAJE)
    return m


def resultados_para_dimensionamento(
        modelo: Modelo, combinacoes: list[Combinacao],
        resultados_dos_casos: dict[str, Resultado] | None = None
        ) -> tuple[dict[str, Resultado], list[TratamentoDaCombinacao]]:
    """Os resultados das combinações ELU, com a 2ª ordem global já dentro.

    Devolve o resultado de cada combinação (com o nome dela, qualquer que
    seja o tratamento) e o relatório do que foi feito em cada uma.
    """
    from .segunda_ordem import resolver_p_delta

    necessarios = sorted({c for comb in combinacoes for c in comb.fatores})
    if resultados_dos_casos is None:
        resultados_dos_casos = {}
    faltando = [c for c in necessarios if c not in resultados_dos_casos]
    casos = dict(resultados_dos_casos)
    casos.update(resolver_casos(modelo, faltando))

    andares = contar_andares(modelo)
    secante = modelo_secante(modelo)
    saida: dict[str, Resultado] = {}
    relatorio: list[TratamentoDaCombinacao] = []

    for comb in combinacoes:
        caso = caso_efetivo(secante, comb)
        caso = replace(caso, nome=f"{comb.nome} (γz)")
        secante.casos[caso.nome] = caso
        try:
            g = gama_z(secante, caso, resolver(secante, caso.nome))
        except ErroDeModelo:
            g = None
        finally:
            secante.casos.pop(caso.nome, None)

        if g is None:
            saida[comb.nome] = combinar(casos, comb)
            relatorio.append(TratamentoDaCombinacao(
                comb.nome, None, PRIMEIRA_ORDEM,
                "sem ação horizontal: γz não se define"))
            continue
        if g.valor <= GAMA_Z_NOS_FIXOS:
            saida[comb.nome] = combinar(casos, comb)
            relatorio.append(TratamentoDaCombinacao(
                comb.nome, g.valor, PRIMEIRA_ORDEM,
                f"nós fixos (γz ≤ {GAMA_Z_NOS_FIXOS:.2f}, 15.4.2)"))
            continue
        if (g.valor <= GAMA_Z_LIMITE_MAJORACAO
                and andares >= ANDARES_MINIMOS_GAMA_Z):
            majorada = majorar_horizontais(modelo, comb, g)
            r = combinar(casos, majorada)
            r.caso = comb.nome
            saida[comb.nome] = r
            relatorio.append(TratamentoDaCombinacao(
                comb.nome, g.valor, MAJORACAO,
                f"horizontais × {g.fator_majoracao:.4f} (15.7.2)"))
            continue

        motivo = (f"γz > {GAMA_Z_LIMITE_MAJORACAO:.2f}: a majoração não vale "
                  "(15.7.2)" if g.valor > GAMA_Z_LIMITE_MAJORACAO else
                  f"{andares} andares: o γz não vale abaixo de "
                  f"{ANDARES_MINIMOS_GAMA_Z} (15.5.3)")
        try:
            r = resolver_p_delta(secante, caso_efetivo(secante, comb))
        except ErroDeModelo as erro:
            raise ErroDeModelo(
                f"combinação {comb.nome}: γz = {g.valor:.3f} pede análise de "
                f"2ª ordem, e ela não tem solução — {erro}") from None
        r.caso = comb.nome
        r.modelo = modelo
        saida[comb.nome] = r
        relatorio.append(TratamentoDaCombinacao(
            comb.nome, g.valor, P_DELTA,
            f"{motivo}; P-Δ com rigidez secante (15.7.3), "
            f"{r.iteracoes} iterações"))
    return saida, relatorio


def resumo(relatorio: list[TratamentoDaCombinacao]) -> str:
    if not relatorio:
        return ""
    gamas = [t.gama_z for t in relatorio if t.gama_z is not None]
    contagem = {}
    for t in relatorio:
        contagem[t.tratamento] = contagem.get(t.tratamento, 0) + 1
    linhas = ["2ª ordem global no dimensionamento (NBR 6118, 15.7) — γz com a "
              "rigidez secante do 15.7.3:"]
    if gamas:
        linhas.append(f"  γz máximo {max(gamas):.3f}; "
                      + ", ".join(f"{n} combinações por {t}"
                                  for t, n in contagem.items()))
    linhas += [str(t) for t in relatorio]
    return "\n".join(linhas)
