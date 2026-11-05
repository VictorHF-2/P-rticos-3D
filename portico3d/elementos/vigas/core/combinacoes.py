# -*- coding: utf-8 -*-
"""
combinacoes.py
Padrões de carregamento, combinações últimas e de serviço e as envoltórias
de esforços delas resultantes (NBR 6118, 11.8 e NBR 8681).

A ação permanente recebe o mesmo coeficiente em toda a estrutura, como exige
o item 11.7.1 da NBR 6118 (ações de mesma origem não se fracionam); o que
varia de tramo para tramo é apenas a ação variável, pela alternância de
carregamento do item 14.6.7.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from .analise import Estrutura, Solicitacao, combinar
from .modelo import Viga


# ---------------------------------------------------------------------------
# Padrões de carregamento
# ---------------------------------------------------------------------------

def padroes_carregamento(n_tramos: int, alternancia: bool = True,
                         limite_exaustivo: int = 8) -> list[np.ndarray]:
    """Padrões de atuação da ação variável (1 = tramo carregado).

    Até ``limite_exaustivo`` tramos a varredura é exaustiva (2^n padrões);
    acima disso usam-se os padrões clássicos: todos carregados, ímpares,
    pares e cada par de tramos adjacentes.
    """
    if not alternancia:
        return [np.ones(n_tramos)]
    if n_tramos == 1:
        return [np.ones(1)]
    if n_tramos <= limite_exaustivo:
        padroes = [np.array(p, dtype=float)
                   for p in itertools.product((0.0, 1.0), repeat=n_tramos)]
        return [p for p in padroes if p.any()]

    padroes = [np.ones(n_tramos)]
    impares = np.array([1.0 if i % 2 == 0 else 0.0 for i in range(n_tramos)])
    padroes += [impares, 1.0 - impares]
    for i in range(n_tramos - 1):
        p = np.zeros(n_tramos)
        p[i] = p[i + 1] = 1.0
        padroes.append(p)
    for i in range(n_tramos):
        p = np.zeros(n_tramos)
        p[i] = 1.0
        padroes.append(p)
    unicos: list[np.ndarray] = []
    for p in padroes:
        if not any(np.array_equal(p, u) for u in unicos):
            unicos.append(p)
    return unicos


# ---------------------------------------------------------------------------
# Combinações
# ---------------------------------------------------------------------------

@dataclass
class Combinacao:
    """Uma combinação de ações, descrita pelos fatores de cada caso-base."""

    nome: str
    tipo: str                 # 'ELU', 'ELS-rara', 'ELS-frequente', 'ELS-qp'
    fg: np.ndarray            # fator da ação permanente por tramo
    fq: np.ndarray            # fator da ação variável por tramo


def gerar_combinacoes(viga: Viga) -> list[Combinacao]:
    """Combinações últimas normais e de serviço, com alternância."""
    cfg = viga.config
    nt = len(viga.tramos)
    padroes = padroes_carregamento(nt, cfg.alternancia)
    combs: list[Combinacao] = []

    # ELU -- combinações últimas normais (Tabela 11.3)
    combs.append(Combinacao("ELU: 1,4G", "ELU",
                            np.full(nt, cfg.gamma_g), np.zeros(nt)))
    for i, p in enumerate(padroes, start=1):
        rotulo = _rotulo_padrao(p)
        combs.append(Combinacao(
            f"ELU {i}: {cfg.gamma_g:g}G + {cfg.gamma_q:g}Q{rotulo}", "ELU",
            np.full(nt, cfg.gamma_g), cfg.gamma_q * p))
        if cfg.gamma_g_fav != cfg.gamma_g:
            combs.append(Combinacao(
                f"ELU {i}a: {cfg.gamma_g_fav:g}G + {cfg.gamma_q:g}Q{rotulo}",
                "ELU", np.full(nt, cfg.gamma_g_fav), cfg.gamma_q * p))

    # ELS -- rara, frequente e quase permanente (11.8.3.2)
    for tipo, psi, sigla in (("ELS-rara", 1.0, "G + Q"),
                             ("ELS-frequente", cfg.psi1, "G + psi1.Q"),
                             ("ELS-qp", cfg.psi2, "G + psi2.Q")):
        for i, p in enumerate(padroes, start=1):
            combs.append(Combinacao(f"{tipo} {i}: {sigla}{_rotulo_padrao(p)}",
                                    tipo, np.ones(nt), psi * p))
    return combs


def _rotulo_padrao(p: np.ndarray) -> str:
    if p.all():
        return " (todos os tramos)"
    carregados = [str(i + 1) for i, v in enumerate(p) if v]
    return " (tramos " + ", ".join(carregados) + ")"


# ---------------------------------------------------------------------------
# Envoltórias
# ---------------------------------------------------------------------------

@dataclass
class Envoltoria:
    """Valores extremos dos esforços ao longo da viga."""

    x: np.ndarray
    M_max: np.ndarray
    M_min: np.ndarray
    V_max: np.ndarray
    V_min: np.ndarray
    reacoes_max: np.ndarray
    reacoes_min: np.ndarray
    momentos_apoio_max: np.ndarray
    momentos_apoio_min: np.ndarray
    combinacoes: list[str] = field(default_factory=list)

    @property
    def V_abs(self) -> np.ndarray:
        return np.maximum(np.abs(self.V_max), np.abs(self.V_min))

    def em(self, x: float) -> tuple[float, float, float, float]:
        """(M_max, M_min, V_max, V_min) interpolados na abscissa ``x``."""
        return (float(np.interp(x, self.x, self.M_max)),
                float(np.interp(x, self.x, self.M_min)),
                float(np.interp(x, self.x, self.V_max)),
                float(np.interp(x, self.x, self.V_min)))

    def extremo_no_intervalo(self, xa: float, xb: float,
                             grandeza: str = "M_max") -> tuple[float, float]:
        """Valor extremo de uma grandeza em [xa, xb] e a abscissa onde ocorre."""
        arr = getattr(self, grandeza)
        mask = (self.x >= xa - 1e-9) & (self.x <= xb + 1e-9)
        if not mask.any():
            v, x0 = float(np.interp(xa, self.x, arr)), xa
            return v, x0
        sub, xs = arr[mask], self.x[mask]
        i = int(np.argmax(sub)) if grandeza.endswith("max") else int(np.argmin(sub))
        return float(sub[i]), float(xs[i])


def redistribuir(sol: Solicitacao, viga: Viga, delta: float) -> Solicitacao:
    """Redistribui os momentos negativos dos apoios internos (14.6.4.3).

    O momento de cada apoio interno passa a ``delta`` vezes o valor elástico e
    o diagrama de cada tramo é reconstruído a partir do momento isostático,
    o que devolve ao vão o momento retirado do apoio -- inclusive no cortante,
    que ganha a parcela constante ``(dM2 - dM1)/L``.
    """
    if delta >= 1.0:
        return sol
    xs = viga.x_apoios
    M = sol.M.copy()
    V = sol.V.copy()
    dM = np.zeros(len(viga.apoios))
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre" or k == 0 or k == len(viga.apoios) - 1:
            continue
        Mk = float(np.interp(xs[k], sol.x, sol.M))
        if Mk < 0.0:
            dM[k] = Mk * (delta - 1.0)     # variação (positiva) do momento
    if not dM.any():
        return sol
    # cortante que cada tramo ganha; a reação de um apoio é o que sobra entre o
    # cortante à direita dele e o cortante à esquerda. Sem atualizá-las, a
    # tabela de reações e o arredondamento do diagrama sobre o apoio (14.6.3,
    # que usa a reação) liam os valores de antes da redistribuição
    # a grade tem **dois** pontos na abscissa de cada apoio interno (o cortante
    # à esquerda e à direita dele). O momento é contínuo: recebe o ajuste uma
    # vez, por interpolação. O cortante é de cada lado: o ponto da esquerda é
    # do tramo da esquerda, o da direita é do da direita. Somar por máscara de
    # abscissa dava o ajuste duas vezes ao momento do eixo e anulava o do
    # cortante nesses pontos
    M += np.interp(sol.x, xs, dM)
    dV = np.zeros(len(viga.tramos))
    esquerda_de = {}                       # índice do ponto à esquerda do apoio
    direita_de = {}                        # índice do ponto à direita do apoio
    for k, xk in enumerate(xs):
        ids = np.flatnonzero(np.isclose(sol.x, xk, atol=1e-9))
        if ids.size:
            esquerda_de[k], direita_de[k] = int(ids[0]), int(ids[-1])
    for i in range(len(viga.tramos)):
        L = xs[i + 1] - xs[i]
        dV[i] = (dM[i + 1] - dM[i]) / L
        if i in direita_de and (i + 1) in esquerda_de:
            V[direita_de[i]:esquerda_de[i + 1] + 1] += dV[i]
    reacoes = np.array(sol.reacoes, dtype=float)
    for k in range(len(viga.apoios)):
        direita = dV[k] if k < len(viga.tramos) else 0.0
        esquerda = dV[k - 1] if k > 0 else 0.0
        reacoes[k] += direita - esquerda
    momentos_apoio = np.array(sol.momentos_apoio, dtype=float)
    momentos_apoio += dM
    return Solicitacao(nome=sol.nome + " [redistribuído]", x=sol.x, V=V, M=M,
                       flecha=sol.flecha, reacoes=reacoes,
                       momentos_apoio=momentos_apoio)


def calcular(estrutura: Estrutura, combs: list[Combinacao] | None = None,
             tipos: tuple[str, ...] = ("ELU",)) -> tuple[Envoltoria,
                                                         list[Solicitacao]]:
    """Envoltória dos tipos de combinação pedidos e as solicitações usadas."""
    viga = estrutura.viga
    if combs is None:
        combs = gerar_combinacoes(viga)
    selecionadas = [c for c in combs if c.tipo in tipos]
    if not selecionadas:
        raise ValueError(f"Nenhuma combinação do tipo {tipos}.")

    sols = [combinar(estrutura, c.fg, c.fq, c.nome) for c in selecionadas]
    delta = viga.config.redistribuicao
    if delta < 1.0 and "ELU" in tipos:
        sols = [redistribuir(s, viga, delta) for s in sols]
    M = np.array([s.M for s in sols])
    V = np.array([s.V for s in sols])
    R = np.array([s.reacoes for s in sols])
    Ma = np.array([s.momentos_apoio for s in sols])

    env = Envoltoria(
        x=estrutura.x,
        M_max=M.max(axis=0), M_min=M.min(axis=0),
        V_max=V.max(axis=0), V_min=V.min(axis=0),
        reacoes_max=R.max(axis=0), reacoes_min=R.min(axis=0),
        momentos_apoio_max=Ma.max(axis=0), momentos_apoio_min=Ma.min(axis=0),
        combinacoes=[c.nome for c in selecionadas])
    return env, sols


def envoltoria_servico(estrutura: Estrutura, tipo: str,
                       combs: list[Combinacao] | None = None
                       ) -> tuple[np.ndarray, np.ndarray, list[Solicitacao]]:
    """Flechas elásticas extremas de uma família de combinações de serviço.

    Devolve (flecha_max, flecha_min, solicitações) na grade da estrutura.
    Os valores são elásticos, com a inércia bruta; a correção pela fissuração
    e pela fluência é feita em :mod:`vigas.core.els`.
    """
    if combs is None:
        combs = gerar_combinacoes(estrutura.viga)
    sols = [combinar(estrutura, c.fg, c.fq, c.nome)
            for c in combs if c.tipo == tipo]
    if not sols:
        raise ValueError(f"Nenhuma combinação do tipo {tipo!r}.")
    F = np.array([s.flecha for s in sols])
    return F.max(axis=0), F.min(axis=0), sols


# ---------------------------------------------------------------------------
# Momentos de projeto por região
# ---------------------------------------------------------------------------

@dataclass
class MomentoProjeto:
    """Momento de cálculo adotado em uma região (vão ou apoio)."""

    regiao: str               # 'vao' ou 'apoio'
    indice: int               # nº do tramo (vão) ou do apoio
    x: float                  # abscissa de projeto, m
    M: float                  # kN.m (positivo traciona a face inferior)
    M_bruto: float            # antes da redução à face e da redistribuição
    observacao: str = ""
    #: trecho prismático deste momento, ou -1 no momento de apoio. Um vão com
    #: mudança de seção interna gera **um momento por trecho**: dimensionar o
    #: vão inteiro com a seção do ponto de momento máximo aplicaria a seção de
    #: 70 cm ao pedaço que tem 50
    trecho: int = -1


def momento_arredondado(viga: Viga, sols: list[Solicitacao],
                        k: int) -> tuple[float, float, float]:
    """Momento negativo do apoio ``k`` com o diagrama arredondado (14.6.3).

    O item 14.6.3 e a Figura 14.6 permitem arredondar o pico do diagrama de
    momentos sobre o apoio: ``ΔM = R·t/8``, com ``R`` a reação do apoio e ``t``
    a largura dele (a parábola que substitui o pico). Aplica-se **combinação por
    combinação** -- a reação que reduz o pico é a da mesma combinação que o
    produziu, e não a maior de todas -- e o momento de projeto é o mais
    negativo entre os arredondados. Reação negativa (apoio que levanta) não
    reduz nada.

    Devolve ``(M de projeto, ΔM aplicado, reação da combinação que governa)``.
    Não é a "redução à face": a face daria ``R·t/4``, o dobro, e a norma não a
    prevê (o 14.6.2.1 trata de trechos rígidos).
    """
    xs = viga.x_apoios
    t = viga.apoios[k].largura / 100.0                       # m
    meia = t / 2.0
    melhor = None
    for s in sols:
        mask = (s.x >= xs[k] - meia - 1e-9) & (s.x <= xs[k] + meia + 1e-9)
        pico = float(s.M[mask].min()) if mask.any() else float(
            np.interp(xs[k], s.x, s.M))
        if pico >= 0.0:
            continue
        R = max(float(s.reacoes[k]), 0.0)
        # o arredondamento não vira momento positivo: se ΔM passa do pico, o
        # apoio fica sem momento negativo e sem armadura de topo
        M = min(pico + R * t / 8.0, 0.0)
        if melhor is None or M < melhor[0]:
            melhor = (M, M - pico, R)
    # nenhuma combinação com momento negativo: nada a dimensionar
    return melhor if melhor is not None else (0.0, 0.0, 0.0)


def momentos_de_projeto(viga: Viga, env: Envoltoria,
                        sols: list[Solicitacao] | None = None
                        ) -> list[MomentoProjeto]:
    """Momentos de dimensionamento em cada vão e em cada apoio.

    Nos apoios internos aplica-se, quando pedido e quando se conhecem as
    solicitações de cada combinação (``sols``), o arredondamento do diagrama do
    item 14.6.3 (:func:`momento_arredondado`) e, antes dele, a redistribuição do
    item 14.6.4.3, que já vem embutida nas solicitações.
    """
    cfg = viga.config
    xs = viga.x_apoios
    momentos: list[MomentoProjeto] = []

    # -- vãos ---------------------------------------------------------------
    # um momento por **trecho prismático** do vão. No tramo prismático há um
    # trecho e nada muda; com mudança de seção interna, cada pedaço é
    # dimensionado com a sua seção e com o máximo do momento **dentro dele**
    for i in range(len(viga.tramos)):
        for t in viga.trechos_do_tramo(i):
            M, x0 = env.extremo_no_intervalo(t.x_ini, t.x_fim, "M_max")
            momentos.append(MomentoProjeto("vao", i, x0, M, M, trecho=t.k))

    # -- apoios -------------------------------------------------------------
    extremos = (0, len(viga.apoios) - 1)
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        meia = ap.largura / 200.0
        xa = max(xs[k] - meia, 0.0)
        xb = min(xs[k] + meia, viga.comprimento)
        M_eixo, _ = env.extremo_no_intervalo(xa, xb, "M_min")
        M = M_eixo
        obs = []
        # só nos apoios internos: num apoio de extremidade o diagrama não
        # continua do outro lado, e não há pico a arredondar
        if (cfg.arredondar_momento_apoio and ap.largura > 0
                and sols and 0 < k < len(viga.apoios) - 1):
            M_arr, dM, R = momento_arredondado(viga, sols, k)
            if dM > 1e-9:
                M = max(M_arr, M_eixo)
                obs.append(f"diagrama arredondado sobre o apoio (14.6.3): "
                           f"ΔM = R·t/8 = {R:.1f}·{ap.largura / 100.0:.2f}/8 "
                           f"= {dM:.2f} kN·m")
        if cfg.redistribuicao < 1.0 and 0 < k < len(viga.apoios) - 1:
            obs.append(f"envoltória já redistribuída (delta = "
                       f"{cfg.redistribuicao:g})")
        if k in extremos and cfg.engastamento_minimo_extremidade > 0.0:
            vizinho = 0 if k == 0 else len(viga.tramos) - 1
            M_vao = next((m.M for m in momentos
                          if m.regiao == "vao" and m.indice == vizinho), 0.0)
            M_eng = -cfg.engastamento_minimo_extremidade * abs(M_vao)
            if M_eng < M:
                M = M_eng
                obs.append(f"engastamento parcial mínimo adotado "
                           f"({cfg.engastamento_minimo_extremidade:.0%} do "
                           f"momento do vão) -- critério de projeto")
        if M >= -1e-6:
            continue          # apoio sem momento negativo: sem armadura de topo
        momentos.append(MomentoProjeto("apoio", k, xs[k], M, M_eixo,
                                       "; ".join(obs)))
    return momentos
