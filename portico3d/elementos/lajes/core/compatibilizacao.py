# -*- coding: utf-8 -*-
"""
compatibilizacao.py
Compatibilização dos momentos negativos nas bordas comuns entre lajes
vizinhas, item 14.7.6.2 da NBR 6118 e §3.3 da apostila.

O cálculo por tabelas trata cada laje como isolada e engastada nas bordas de
continuidade. Duas lajes vizinhas, com vãos e cargas diferentes, chegam à
mesma borda com momentos negativos diferentes -- e a borda é uma só. Sobre
ela vai **uma** armadura, e a norma dá dois caminhos para decidir qual:

``"maior"``
    adotar o maior dos dois momentos. É a simplificação que o item permite de
    forma explícita, e é segura nos dois lados: a laje que tinha o momento
    menor passa a ter mais engastamento do que supôs, e mais engastamento
    alivia o vão dela -- o momento positivo que ela calculou continua
    cobrindo.

``"iterativa"``
    alterar os graus de engastamento ``i`` até os dois lados se igualarem. É
    o procedimento que o item recomenda, e o que a norma chama de "valores
    equilibrados nas bordas". Aqui ele é caro em nada: o momento de cada laje
    é uma função fechada dos ``i``, e o laço converge em poucas passagens.

    Este caminho **muda os momentos de vão**: quem cede momento negativo
    recebe momento positivo em troca. O programa recalcula a laje inteira a
    cada passagem, e não só a borda, justamente por isso.

Em qualquer dos dois, a armadura da borda comum é dimensionada para o momento
adotado e para a **menor** das duas alturas úteis (§3.3), e se estende para
cada lado do eixo do apoio por um quarto do maior dos vãos menores das duas
lajes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .esforcos import BORDOS_DA_DIRECAO, Esforcos
from .modelo import (GRAU_ENGASTAMENTO_MAXIMO, GRAU_ENGASTAMENTO_MINIMO,
                     Config, Continuidade, Pavimento)


@dataclass
class BordaComum:
    """Uma borda de continuidade, vista dos dois lados."""

    laje_a: str
    bordo_a: int
    laje_b: str
    bordo_b: int
    m_a: float = 0.0                # kN·m/m, momento negativo do lado A
    m_b: float = 0.0                # kN·m/m, do lado B
    m_adotado: float = 0.0          # kN·m/m
    m_a_inicial: float = 0.0        # antes da compatibilização
    m_b_inicial: float = 0.0
    i_a: float = 0.0                # grau de engastamento final
    i_b: float = 0.0
    h_a: float = 0.0                # cm
    h_b: float = 0.0
    d_adotado: float = 0.0          # cm, a menor das duas alturas úteis
    comprimento: float = 0.0        # m, extensão do apoio
    extensao: float = 0.0           # cm, para cada lado do eixo
    criterio: str = ""
    desequilibrio: float = 0.0      # kN·m/m, |m_a - m_b| ao fim

    @property
    def rotulo(self) -> str:
        return (f"{self.laje_a} (bordo {self.bordo_a}) / "
                f"{self.laje_b} (bordo {self.bordo_b})")


@dataclass
class Compatibilizacao:
    """Resultado da compatibilização do pavimento."""

    criterio: str
    bordas: list[BordaComum] = field(default_factory=list)
    iteracoes: int = 0
    convergiu: bool = True
    avisos: list[str] = field(default_factory=list)

    def borda_de(self, laje: str, bordo: int) -> BordaComum | None:
        for b in self.bordas:
            if (b.laje_a, b.bordo_a) == (laje, bordo) or \
               (b.laje_b, b.bordo_b) == (laje, bordo):
                return b
        return None

    def momento_do_bordo(self, laje: str, bordo: int) -> float | None:
        """Momento negativo adotado naquele bordo, se ele é de continuidade."""
        b = self.borda_de(laje, bordo)
        return None if b is None else b.m_adotado


def _direcao_do_bordo(bordo: int) -> str:
    return "b" if bordo in BORDOS_DA_DIRECAO["b"] else "a"


def _momento_negativo(esf: Esforcos, bordo: int) -> float:
    return esf.m_neg.get(bordo, 0.0)


def _extensao(pav: Pavimento, c: Continuidade) -> float:
    """Um quarto do maior dos vãos menores das duas lajes, em cm (§3.3) --
    ou até a extremidade livre, se um dos lados for um balanço.

    A borda comum de um balanço com a laje vizinha é a única armadura do
    balanço: se ela parasse em um quarto do vão (a regra normal, pensada
    para uma laje que continua nos dois lados), o resto do balanço, entre
    ali e a ponta livre, ficaria sem nenhuma negativa. Por isso o lado que
    é balanço força a extensão até a extremidade, menos o cobrimento da
    própria borda livre -- não importa que o momento nominal já tenha
    decaído antes disso.
    """
    la, lb = pav.laje(c.laje_a), pav.laje(c.laje_b)
    menores = [x.a_ef for x in (la, lb) if x is not None]
    extensao = 0.25 * max(menores) * 100.0 if menores else 0.0
    cobrimento = pav.ambiente.cobrimento_nominal
    for laje, bordo in ((la, c.bordo_a), (lb, c.bordo_b)):
        if laje is None or laje.destino != "balanco":
            continue
        direcao = _direcao_do_bordo(bordo)
        vao_livre = (laje.a if direcao == "a" else laje.b) * 100.0
        extensao = max(extensao, vao_livre - cobrimento)
    return extensao


def _comprimento_da_borda(pav: Pavimento, c: Continuidade) -> float:
    """Extensão da borda comum, m -- o comprimento do bordo."""
    la = pav.laje(c.laje_a)
    if la is None:
        return 0.0
    return la.a_ef if c.bordo_a in (1, 3) else la.b_ef


def _altura_util_negativa(pav: Pavimento, nome: str) -> float:
    """Altura útil da armadura negativa da laje, cm."""
    from .flexao import altura_util
    laje = pav.laje(nome)
    if laje is None:
        return 0.0
    c_sup = pav.ambiente.cobrimento_superior(pav.config.bitola_minima_negativa)
    return altura_util(laje.h, c_sup, "superior")


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def compatibilizar(pav: Pavimento, esforcos: dict[str, Esforcos],
                   cfg: Config) -> tuple[Compatibilizacao,
                                         dict[str, Esforcos]]:
    """Compatibiliza as bordas comuns e devolve os esforços atualizados.

    Devolve ``(compatibilizacao, esforcos)``. No critério ``"iterativa"`` o
    dicionário de esforços vem recalculado com os graus de engastamento
    ajustados; nos outros, ele volta como entrou.
    """
    from . import esforcos as esf_mod

    criterio = cfg.compatibilizacao
    comp = Compatibilizacao(criterio=criterio)

    if not pav.continuidades or criterio == "nenhuma":
        if pav.continuidades and criterio == "nenhuma":
            comp.avisos.append(
                "A compatibilização dos momentos negativos está desligada: "
                "cada laje ficou com o momento que calculou isolada, e a "
                "borda comum vai receber duas armaduras diferentes. Só é "
                "aceitável se a diferença for desprezível (14.7.6.2).")
        return comp, esforcos

    # -- laço iterativo sobre os graus de engastamento ----------------------
    if criterio == "iterativa":
        graus_originais = {laje.nome: [b.grau for b in laje.bordos]
                           for laje in pav.lajes}
        for passagem in range(cfg.iteracoes_compatibilizacao):
            comp.iteracoes = passagem + 1
            maior_desvio = 0.0
            for c in pav.continuidades:
                la, lb = pav.laje(c.laje_a), pav.laje(c.laje_b)
                if la is None or lb is None:
                    continue
                ma = _momento_negativo(esforcos[la.nome], c.bordo_a)
                mb = _momento_negativo(esforcos[lb.nome], c.bordo_b)
                maior_desvio = max(maior_desvio, abs(ma - mb))
                alvo = (ma + mb) / 2.0
                # i = m' / m do vão daquela direção; quando o vão não tem
                # momento (balanço), o grau não é a alavanca e fica como está
                for laje, bordo, m_atual in ((la, c.bordo_a, ma),
                                             (lb, c.bordo_b, mb)):
                    base = esforcos[laje.nome].momento_da_direcao(
                        _direcao_do_bordo(bordo))
                    if base <= 1e-9:
                        continue
                    novo = min(max(alvo / base, GRAU_ENGASTAMENTO_MINIMO),
                               GRAU_ENGASTAMENTO_MAXIMO)
                    laje.bordos[bordo - 1].grau = novo
            for laje in pav.lajes:
                esforcos[laje.nome] = esf_mod.calcular(laje, cfg)
            if maior_desvio <= cfg.tolerancia_compatibilizacao:
                break
        else:
            comp.convergiu = False
            comp.avisos.append(
                f"A compatibilização iterativa não fechou em "
                f"{cfg.iteracoes_compatibilizacao} passagens: os graus de "
                f"engastamento bateram nos limites de "
                f"{GRAU_ENGASTAMENTO_MINIMO:g} a "
                f"{GRAU_ENGASTAMENTO_MAXIMO:g} (§3.2) antes de equilibrar as "
                f"bordas. A armadura de continuidade saiu pelo maior dos dois "
                f"momentos, que é o caminho seguro.")
        for laje in pav.lajes:
            for k, grau in enumerate(graus_originais[laje.nome]):
                if abs(laje.bordos[k].grau - grau) > 1e-6 and \
                        laje.bordos[k].vinculo == "engastado":
                    comp.avisos.append(
                        f"{laje.nome}, bordo {k + 1}: grau de engastamento "
                        f"ajustado de {grau:.2f} para "
                        f"{laje.bordos[k].grau:.2f} pela compatibilização.")

    # -- montagem das bordas ------------------------------------------------
    for c in pav.continuidades:
        la, lb = pav.laje(c.laje_a), pav.laje(c.laje_b)
        if la is None or lb is None:
            continue
        ma = _momento_negativo(esforcos[la.nome], c.bordo_a)
        mb = _momento_negativo(esforcos[lb.nome], c.bordo_b)
        borda = BordaComum(
            laje_a=la.nome, bordo_a=c.bordo_a, laje_b=lb.nome,
            bordo_b=c.bordo_b, m_a=ma, m_b=mb, m_a_inicial=ma,
            m_b_inicial=mb, i_a=la.bordos[c.bordo_a - 1].i,
            i_b=lb.bordos[c.bordo_b - 1].i, h_a=la.h, h_b=lb.h,
            comprimento=_comprimento_da_borda(pav, c),
            extensao=_extensao(pav, c), criterio=criterio,
            desequilibrio=abs(ma - mb))
        borda.d_adotado = min(_altura_util_negativa(pav, la.nome),
                              _altura_util_negativa(pav, lb.nome))
        borda.m_adotado = max(ma, mb)
        comp.bordas.append(borda)

        if borda.desequilibrio > 1e-6 and criterio == "maior":
            menor, maior = min(ma, mb), max(ma, mb)
            if maior > 1e-9:
                comp.avisos.append(
                    f"{borda.rotulo}: os dois lados chegaram com "
                    f"{ma:.2f} e {mb:.2f} kN·m/m; adotado o maior "
                    f"({maior:.2f}), uma diferença de "
                    f"{(1 - menor / maior) * 100:.0f} % (14.7.6.2).")
    return comp, esforcos
