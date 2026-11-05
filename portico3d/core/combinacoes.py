# -*- coding: utf-8 -*-
"""
combinacoes.py
Combinação de casos de carga por superposição.

Cada caso é resolvido uma única vez; a combinação é a soma ponderada dos
resultados. Isso só vale porque a análise é linear — e é justamente essa a
hipótese que a segunda ordem, na fase 3, vai derrubar: com P-Δ, cada
combinação precisa ser resolvida por si, porque o efeito de uma ação passa a
depender das outras que estão atuando junto. A separação entre ``resolver_casos``
e ``combinar`` existe para que essa troca, quando vier, fique contida aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from .carregamento import escalar
from .modelo import CasoDeCarga, ErroDeModelo, Modelo
from .montagem import resolver
from .resultados import Resultado

TIPOS = ("ELU", "ELS-QP", "ELS-F", "ELS-R")


@dataclass(frozen=True)
class Combinacao:
    """Soma ponderada de casos de carga.

    ``fatores`` mapeia o nome do caso ao seu coeficiente. ``tipo`` diz a qual
    verificação a combinação serve, e é o que separa, na envoltória, o que vai
    para o dimensionamento do que vai para a verificação em serviço.
    """

    nome: str
    fatores: dict[str, float] = field(default_factory=dict)
    tipo: str = "ELU"
    descricao: str = ""

    def __post_init__(self) -> None:
        if self.tipo not in TIPOS:
            raise ErroDeModelo(
                f"combinação '{self.nome}': tipo '{self.tipo}' inválido; "
                f"use um de {', '.join(TIPOS)}")


def resolver_casos(modelo: Modelo,
                   casos: list[str] | None = None) -> dict[str, Resultado]:
    """Resolve cada caso de carga uma vez só."""
    nomes = casos if casos is not None else list(modelo.casos)
    return {nome: resolver(modelo, nome) for nome in nomes}


def combinar(resultados: dict[str, Resultado],
             combinacao: Combinacao) -> Resultado:
    """Superpõe os resultados dos casos segundo os fatores da combinação."""
    if not combinacao.fatores:
        raise ErroDeModelo(f"combinação '{combinacao.nome}' está vazia")

    faltando = [c for c in combinacao.fatores if c not in resultados]
    if faltando:
        raise ErroDeModelo(
            f"combinação '{combinacao.nome}' cita casos não resolvidos: "
            f"{', '.join(faltando)}")

    referencia = resultados[next(iter(combinacao.fatores))]
    modelo = referencia.modelo

    deslocamentos = np.zeros_like(referencia.deslocamentos)
    reacoes = np.zeros_like(referencia.reacoes)
    esforcos = {nome: np.zeros(12) for nome in referencia.esforcos}
    # A intensidade entra linearmente em tudo que se calcula a partir dela,
    # então combinar carregamentos é concatenar segmentos já escalados.
    segmentos: dict[str, list] = {nome: [] for nome in referencia.segmentos}
    reacoes_mola: dict[str, np.ndarray] = {}
    pontuais: dict[str, list] = {}

    for caso, fator in combinacao.fatores.items():
        r = resultados[caso]
        if r.modelo is not modelo:
            raise ErroDeModelo(
                f"combinação '{combinacao.nome}': os casos '{caso}' e "
                "os demais vêm de modelos diferentes")
        deslocamentos += fator * r.deslocamentos
        reacoes += fator * r.reacoes
        for nome in esforcos:
            esforcos[nome] += fator * r.esforcos[nome]
            segmentos[nome].extend(escalar(r.segmentos[nome], fator))
        for nome, lista in r.pontuais.items():
            pontuais.setdefault(nome, []).extend(
                (s, fator * f) for s, f in lista)
        for no, valor in r.reacoes_mola.items():
            reacoes_mola[no] = reacoes_mola.get(no, 0.0) + fator * valor

    return Resultado(modelo=modelo, caso=combinacao.nome,
                     deslocamentos=deslocamentos, reacoes=reacoes,
                     esforcos=esforcos, preparadas=referencia.preparadas,
                     segmentos=segmentos,
                     gdl_restritos=referencia.gdl_restritos,
                     reacoes_mola=reacoes_mola, pontuais=pontuais)


def caso_efetivo(modelo: Modelo, combinacao: Combinacao) -> CasoDeCarga:
    """Monta um único caso de carga com as ações já ponderadas.

    É o caminho que a segunda ordem exige. Na análise linear dá no mesmo somar
    as cargas antes ou os resultados depois; com P-Δ não dá, porque o efeito de
    uma ação passa a depender das outras que atuam junto — e aí a combinação
    precisa existir como carregamento, não como soma de respostas.
    """
    faltando = [c for c in combinacao.fatores if c not in modelo.casos]
    if faltando:
        raise ErroDeModelo(
            f"combinação '{combinacao.nome}' cita casos inexistentes: "
            f"{', '.join(faltando)}")

    efetivo = CasoDeCarga(combinacao.nome)
    for nome, fator in combinacao.fatores.items():
        caso = modelo.casos[nome]
        for c in caso.nodais:
            efetivo.nodais.append(replace(
                c, fx=fator * c.fx, fy=fator * c.fy, fz=fator * c.fz,
                mx=fator * c.mx, my=fator * c.my, mz=fator * c.mz))
        for c in caso.distribuidas:
            efetivo.distribuidas.append(replace(
                c, qx=fator * c.qx, qy=fator * c.qy, qz=fator * c.qz,
                qx_fim=None if c.qx_fim is None else fator * c.qx_fim,
                qy_fim=None if c.qy_fim is None else fator * c.qy_fim,
                qz_fim=None if c.qz_fim is None else fator * c.qz_fim))
        for c in caso.recalques:
            efetivo.recalques.append(replace(
                c, ux=fator * c.ux, uy=fator * c.uy, uz=fator * c.uz,
                rx=fator * c.rx, ry=fator * c.ry, rz=fator * c.rz))
    return efetivo


def resolver_combinacoes(modelo: Modelo, combinacoes: list[Combinacao],
                         resultados: dict[str, Resultado] | None = None
                         ) -> dict[str, Resultado]:
    """Resolve os casos necessários e devolve o resultado de cada combinação."""
    if resultados is None:
        necessarios = sorted({c for comb in combinacoes for c in comb.fatores})
        resultados = resolver_casos(modelo, necessarios)
    return {comb.nome: combinar(resultados, comb) for comb in combinacoes}
