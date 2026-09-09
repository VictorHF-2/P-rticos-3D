# -*- coding: utf-8 -*-
"""
reacoes.py
Reações de apoio das lajes maciças retangulares -- a carga que cada laje
entrega a cada viga do contorno.

A norma (14.7.6.1) e a apostila (§3.4) mandam repartir a carga pelas
**charneiras plásticas**, aproximadas por retas saindo dos vértices com
ângulos que dependem do par de bordos que se encontram ali:

    45° entre dois apoios do mesmo tipo;
    60° a partir do bordo engastado, quando o outro é apoiado;
    90° a partir do bordo, quando o vizinho é livre.

Esses três ângulos são um único critério escrito de três formas. Ao longo de
uma reta que sai do vértice a um ângulo ``theta`` do bordo *i*, a razão entre
as distâncias aos dois bordos é ``tg(theta)`` -- constante. Então a charneira
é o lugar onde ``d_i / w_i = d_j / w_j``, com um **peso** por tipo de bordo:

    apoiado ..... w = 1
    engastado ... w = raiz(3)     (tg 60° = raiz 3)
    livre ....... w = 0

45° sai de dois pesos iguais, 60° da razão raiz(3):1 e 90° do peso nulo, que
tira o bordo livre da disputa e deixa a divisória perpendicular ao bordo
carregado. Com isso a repartição é uma partição por distância ponderada, e
sai **exata** por integração em uma variável, para qualquer relação entre os
lados e qualquer combinação de vínculos -- inclusive as que a tabela de Hahn
não alcança (b/a > 2, bordo livre).

A tabela de Hahn é a tabulação desse mesmo critério, e o programa calcula as
duas: usa a tabela onde ela vale, como pede a apostila, e a construção
geométrica no resto -- guardando as duas para a memória de cálculo mostrar
que concordam.

Geometria adotada, coerente com a numeração dos bordos: o eixo ``x`` corre ao
longo dos bordos 2 e 4 (comprimento ``b``) e o eixo ``y`` ao longo dos bordos
1 e 3 (comprimento ``a``). Logo o bordo 1 está em ``x = 0``, o bordo 3 em
``x = b``, o bordo 2 em ``y = 0`` e o bordo 4 em ``y = a``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import tabelas as tb
from .modelo import Config, Laje

#: Peso de cada tipo de bordo na partição por distância ponderada.
PESO = {tb.LIVRE: 0.0, tb.APOIADO: 1.0, tb.ENGASTADO: math.sqrt(3.0)}

#: Comprimento do bordo: os bordos 1 e 3 medem ``a``; os 2 e 4 medem ``b``.
COMPRIMENTO_DO_BORDO = {1: "a", 2: "b", 3: "a", 4: "b"}


@dataclass
class ReacaoBordo:
    """Carga que a laje entrega a um bordo."""

    bordo: int
    vinculo: str
    comprimento: float              # m, extensão do bordo
    fracao: float                   # parcela da carga total da laje
    area: float = 0.0               # m², área do quadrilátero de influência
    v_k: float = 0.0                # kN/m, característica (g + q)
    v_g: float = 0.0                # kN/m, permanente
    v_q: float = 0.0                # kN/m, variável
    v_d: float = 0.0                # kN/m, de cálculo
    fracao_hahn: float | None = None
    fonte: str = ""                 # "Hahn" ou "charneiras"


@dataclass
class ReacoesLaje:
    """Reações dos quatro bordos de uma laje."""

    laje: str
    carga_total: float              # kN, carga característica da laje
    carga_total_d: float            # kN, de cálculo
    bordos: list[ReacaoBordo] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def do_bordo(self, n: int) -> ReacaoBordo | None:
        for r in self.bordos:
            if r.bordo == n:
                return r
        return None


# ---------------------------------------------------------------------------
# Partição geométrica exata
# ---------------------------------------------------------------------------

def _comprimento_no_perfil(w_perto: float, w_longe: float, a: float,
                           limite: float) -> float:
    """Trecho da coluna que cabe ao bordo de peso ``w_perto``.

    Numa coluna de abscissa fixa, os bordos 1 e 3 têm distância constante e
    entram só pelo ``limite`` (a menor das razões deles). O bordo perto ganha
    o trecho em que ele bate tanto o bordo oposto quanto esse limite.
    """
    if w_perto <= 0.0:
        return 0.0
    contra_oposto = a * w_perto / (w_perto + w_longe) if w_longe > 0.0 else a
    if math.isinf(limite):
        return min(contra_oposto, a)
    return max(0.0, min(w_perto * limite, contra_oposto, a))


def fracoes_charneiras(a: float, b: float,
                       vinculos: tuple[int, int, int, int],
                       n: int = 20_000) -> tuple[float, float, float, float]:
    """Parcela da carga que cabe a cada bordo, pela partição ponderada.

    Integração em ``x`` de perfis lineares por trechos: a quadratura do ponto
    médio com passo fino erra apenas nos poucos pontos de quebra, e o erro na
    área é da ordem de ``(b/n)²`` -- desprezível diante de qualquer decisão
    de projeto.
    """
    w1, w2, w3, w4 = (PESO[v] for v in vinculos)
    if w1 + w2 + w3 + w4 <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)

    area_total = a * b
    A = [0.0, 0.0, 0.0, 0.0]
    dx = b / n
    for k in range(n):
        x = (k + 0.5) * dx
        r1 = x / w1 if w1 > 0.0 else math.inf
        r3 = (b - x) / w3 if w3 > 0.0 else math.inf
        limite = min(r1, r3)
        y2 = _comprimento_no_perfil(w2, w4, a, limite)
        y4 = _comprimento_no_perfil(w4, w2, a, limite)
        meio = max(0.0, a - y2 - y4)
        A[1] += y2 * dx
        A[3] += y4 * dx
        if meio > 0.0:
            if r1 < r3:
                A[0] += meio * dx
            elif r3 < r1:
                A[2] += meio * dx
            else:
                A[0] += meio * dx / 2.0
                A[2] += meio * dx / 2.0
    return tuple(x / area_total for x in A)          # type: ignore


def fracoes_hahn(caso: int, b_sobre_a: float,
                 vinculos: tuple[int, int, int, int]
                 ) -> tuple[float, float, float, float]:
    """Parcela de cada bordo pela tabela de Hahn (§3.4).

    A tabela dá uma entrada por direção quando os dois bordos daquela direção
    têm o mesmo vínculo (``va``, ``vb``) e duas quando não têm (``vae`` para o
    engastado e ``var`` para o apoiado).
    """
    linha = tb.hahn(caso, b_sobre_a)
    saida = []
    for k in (1, 2, 3, 4):
        direcao = "a" if k in (1, 3) else "b"
        prefixo = "v" + direcao
        if prefixo in linha:
            saida.append(linha[prefixo])
        else:
            engastado = vinculos[k - 1] == tb.ENGASTADO
            saida.append(linha[prefixo + ("e" if engastado else "r")])
    return tuple(saida)                              # type: ignore


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def calcular(laje: Laje, esforcos, cfg: Config) -> ReacoesLaje:
    """Reações da laje nos quatro bordos, em kN/m.

    A carga repartida é a **total** da laje: as parcelas permanente e variável
    saem na mesma proporção, porque a partição é geométrica e não depende do
    valor da carga. Isso deixa a viga receber ``g`` e ``q`` separados, que é
    do que ela precisa para montar as combinações dela.
    """
    a, b = laje.a_ef, laje.b_ef
    g = laje.g_total                       # com as paredes espalhadas
    q = laje.variavel
    area = a * b
    res = ReacoesLaje(laje=laje.nome, carga_total=(g + q) * area,
                      carga_total_d=(cfg.gamma_g * g + cfg.gamma_q * q) * area)

    vinculos = laje.vinculos
    geo = fracoes_charneiras(a, b, vinculos)
    caso = tb.caso_de(vinculos)
    ba = b / a
    usa_hahn = caso is not None and 1.0 <= ba <= 2.0
    tabela = fracoes_hahn(caso, ba, vinculos) if caso is not None else None

    if caso is not None and not usa_hahn:
        res.avisos.append(
            f"{laje.nome}: b/a = {ba:.2f} sai da tabela de Hahn (1,00 a "
            f"2,00); as reações vieram da construção das charneiras a "
            f"45°/60°/90° (14.7.6.1), que é o critério que a tabela tabula.")
    if caso is None:
        res.avisos.append(
            f"{laje.nome}: a laje tem bordo livre, situação sem entrada na "
            f"tabela de Hahn; as reações vieram das charneiras a 45°/60°/90° "
            f"(14.7.6.1), com o bordo livre não recebendo carga.")

    for k in (1, 2, 3, 4):
        bordo = laje.bordos[k - 1]
        comprimento = a if COMPRIMENTO_DO_BORDO[k] == "a" else b
        if bordo.vinculo == "livre":
            fracao, fonte = 0.0, "bordo livre"
        elif usa_hahn and tabela is not None:
            fracao, fonte = tabela[k - 1], "Hahn"
        else:
            fracao, fonte = geo[k - 1], "charneiras"
        r = ReacaoBordo(bordo=k, vinculo=bordo.vinculo,
                        comprimento=comprimento, fracao=fracao,
                        area=fracao * area, fonte=fonte,
                        fracao_hahn=tabela[k - 1] if tabela else None)
        if comprimento > 0.0:
            r.v_g = fracao * g * area / comprimento
            r.v_q = fracao * q * area / comprimento
            r.v_k = r.v_g + r.v_q
            r.v_d = (cfg.gamma_g * r.v_g + cfg.gamma_q * r.v_q)
        res.bordos.append(r)

    # a carga entregue tem de ser a carga recebida
    entregue = sum(r.fracao for r in res.bordos)
    if abs(entregue - 1.0) > 0.02 and any(
            bb.vinculo != "livre" for bb in laje.bordos):
        res.avisos.append(
            f"{laje.nome}: as reações somam {entregue * 100:.1f} % da carga "
            f"da laje -- confira a vinculação dos bordos.")
    return res


def conferir_contra_hahn(tolerancia: float = 0.006) -> list[str]:
    """Confere a construção geométrica contra a tabela de Hahn.

    Roda os nove casos em três relações e reprova se alguma parcela se
    afastar da tabela mais que a tolerância. É a conferência que valida ao
    mesmo tempo a transcrição da tabela e a construção das charneiras: são
    dois caminhos independentes para o mesmo número.
    """
    erros: list[str] = []
    codigos = {1: "1111", 2: "2222", 3: "2112", 4: "2121", 5: "1212",
               6: "2111", 7: "1112", 8: "2212", 9: "2122"}
    for caso, codigo in codigos.items():
        vinculos = tuple(int(c) for c in codigo)
        for ba in (1.0, 1.2, 1.5, 1.8, 2.0):
            geo = fracoes_charneiras(1.0, ba, vinculos)   # type: ignore
            tab = fracoes_hahn(caso, ba, vinculos)        # type: ignore
            for k in range(4):
                if abs(geo[k] - tab[k]) > tolerancia:
                    erros.append(
                        f"caso {caso} ({codigo}), b/a = {ba:.2f}, bordo "
                        f"{k + 1}: charneiras dão {geo[k]:.4f} e Hahn "
                        f"{tab[k]:.4f}")
    return erros
