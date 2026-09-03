# -*- coding: utf-8 -*-
"""
nbr6118.py
O que vem da norma: coeficientes, fatores de combinação, geração das
combinações de ações e o desaprumo.

Referências desta edição — ABNT NBR 6118:2026:

* 11.3.3.4.1 e Figura 11.1  imperfeições geométricas globais (desaprumo)
* 11.7.1 e Tabela 11.1       coeficiente γf = γf1·γf3
* 11.7.1 e Tabela 11.2       fatores ψ0, ψ1 e ψ2 (o γf2)
* 11.8.2.4 e Tabela 11.3     combinações últimas
* 11.8.3.2 e Tabela 11.4     combinações de serviço

A numeração é a da edição 2026, que renumerou tabelas em relação à de 2014
mantendo o conteúdo dos itens.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .combinacoes import Combinacao
from .modelo import CasoDeCarga, ErroDeModelo, Modelo

# ---------------------------------------------------------------------------
# Tabela 11.2 — fatores ψ0, ψ1 e ψ2
# ---------------------------------------------------------------------------

PSI: dict[str, tuple[float, float, float]] = {
    "residencial": (0.5, 0.4, 0.3),
    "comercial": (0.7, 0.6, 0.4),
    "biblioteca": (0.8, 0.7, 0.6),
    "vento": (0.6, 0.3, 0.0),
    "temperatura": (0.6, 0.5, 0.3),
}

DESCRICAO_PSI = {
    "residencial": "locais sem predominância de pesos de equipamentos fixos "
                   "nem de elevadas concentrações de pessoas — ocupação "
                   "residencial, hospedagem, acesso restrito",
    "comercial": "locais com predominância de pesos de equipamentos fixos ou "
                 "de elevada concentração de pessoas — comercial, escritórios, "
                 "lojas, estações, edifícios públicos",
    "biblioteca": "biblioteca, arquivos, oficinas e garagens",
    "vento": "pressão dinâmica do vento nas estruturas em geral",
    "temperatura": "variações uniformes de temperatura em relação à média "
                   "anual local",
}

# ---------------------------------------------------------------------------
# Tabela 11.1 — coeficientes γf para combinações normais
# ---------------------------------------------------------------------------

GAMA_PERMANENTE_DESFAVORAVEL = 1.4
GAMA_PERMANENTE_FAVORAVEL = 1.0
GAMA_VARIAVEL = 1.4
GAMA_TEMPERATURA = 1.2

# 11.3.3.4.1 — limites do desaprumo
THETA1_MIN = 1.0 / 300.0
THETA1_MAX = 1.0 / 200.0


@dataclass(frozen=True)
class Acao:
    """A natureza normativa de um caso de carga.

    ``grupo`` marca ações mutuamente excludentes: as quatro incidências de
    vento pertencem ao mesmo grupo, e nunca entram juntas numa combinação.
    Ação sem grupo forma um grupo só dela.
    """

    caso: str
    natureza: str = "permanente"
    categoria: str = ""
    grupo: str = ""
    psi: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.natureza not in ("permanente", "variavel"):
            raise ErroDeModelo(
                f"ação '{self.caso}': natureza '{self.natureza}' inválida; "
                "use 'permanente' ou 'variavel'")
        if self.natureza == "variavel" and self.psi is None:
            if self.categoria not in PSI:
                raise ErroDeModelo(
                    f"ação variável '{self.caso}': categoria "
                    f"'{self.categoria}' não está na Tabela 11.2; use uma de "
                    f"{', '.join(PSI)} ou informe psi explicitamente")

    @property
    def fatores_psi(self) -> tuple[float, float, float]:
        return self.psi if self.psi is not None else PSI[self.categoria]

    @property
    def gama_desfavoravel(self) -> float:
        if self.natureza == "permanente":
            return GAMA_PERMANENTE_DESFAVORAVEL
        return (GAMA_TEMPERATURA if self.categoria == "temperatura"
                else GAMA_VARIAVEL)

    @property
    def chave_grupo(self) -> str:
        return self.grupo if self.grupo else f"\0{self.caso}"


def acoes_do_modelo(modelo: Modelo) -> list[Acao]:
    """Lê a classificação que veio junto com os casos de carga do modelo."""
    return [Acao(caso.nome, caso.natureza, caso.categoria, caso.grupo)
            for caso in modelo.casos.values()]


def validar_acoes(modelo: Modelo, acoes: list[Acao]) -> None:
    for a in acoes:
        if a.caso not in modelo.casos:
            raise ErroDeModelo(
                f"ação '{a.caso}' não corresponde a nenhum caso de carga")
    vistos = [a.caso for a in acoes]
    repetidos = {c for c in vistos if vistos.count(c) > 1}
    if repetidos:
        raise ErroDeModelo(
            f"casos classificados mais de uma vez: {', '.join(sorted(repetidos))}")


def _agrupar(variaveis: list[Acao]) -> dict[str, list[Acao]]:
    grupos: dict[str, list[Acao]] = {}
    for a in variaveis:
        grupos.setdefault(a.chave_grupo, []).append(a)
    return grupos


def _escolhas_secundarias(grupos: dict[str, list[Acao]], excluir: str,
                          permitir_ausencia: bool = True):
    """Uma ação de cada grupo que não seja o da principal.

    Com ``permitir_ausencia``, cada grupo ganha também a opção de não
    participar. Isso importa no ELU, onde a ação variável que alivia não deve
    ser incluída: sem essa variante a envoltória perderia a combinação crítica
    dos casos em que o vento descarrega o pilar. Já as fórmulas do ELS são
    somatórios explícitos sobre as demais ações variáveis, e por isso o padrão
    lá é o contrário.
    """
    outros = [g for g in grupos if g != excluir]
    opcoes = [([None] if permitir_ausencia else []) + grupos[g]
              for g in outros]
    if not opcoes:
        return [()]
    return itertools.product(*opcoes)


def _rotular(prefixo: str, indice: int) -> str:
    return f"{prefixo} {indice:02d}"


def combinacoes_elu(acoes: list[Acao], incluir_permanente_favoravel: bool = False,
                    limite: int = 400) -> list[Combinacao]:
    """Combinações últimas normais — Tabela 11.3.

        Fd = γg·Fgk + γq·(Fq1k + Σ ψ0j·Fqjk)

    Cada ação variável assume a vez de principal. Por padrão só entra a
    variante com o permanente desfavorável: a nota ᵃ da Tabela 11.3 dispensa,
    "no caso de estruturas usuais de edifícios", as combinações com γg = 1,0.
    Para os demais casos — em que o alívio do permanente é o que governa —
    basta ligar ``incluir_permanente_favoravel``.
    """
    permanentes = [a for a in acoes if a.natureza == "permanente"]
    variaveis = [a for a in acoes if a.natureza == "variavel"]
    grupos = _agrupar(variaveis)

    variantes = [("g desfavorável", GAMA_PERMANENTE_DESFAVORAVEL)]
    if incluir_permanente_favoravel:
        variantes.append(("g favorável", GAMA_PERMANENTE_FAVORAVEL))

    combinacoes: list[Combinacao] = []
    for rotulo_g, gama_g in variantes:
        if not variaveis:
            combinacoes.append(Combinacao(
                _rotular("ELU", len(combinacoes) + 1),
                {a.caso: gama_g for a in permanentes}, "ELU",
                f"só ações permanentes, {rotulo_g}"))
            continue

        for principal in variaveis:
            for escolha in _escolhas_secundarias(grupos, principal.chave_grupo):
                fatores = {a.caso: gama_g for a in permanentes}
                fatores[principal.caso] = principal.gama_desfavoravel
                partes = [f"{principal.caso} principal"]
                for secundaria in escolha:
                    if secundaria is None:
                        continue
                    psi0 = secundaria.fatores_psi[0]
                    fatores[secundaria.caso] = secundaria.gama_desfavoravel * psi0
                    partes.append(f"{secundaria.caso} com ψ0={psi0:.2f}")
                combinacoes.append(Combinacao(
                    _rotular("ELU", len(combinacoes) + 1), fatores, "ELU",
                    f"{', '.join(partes)}, {rotulo_g}"))

        if len(combinacoes) > limite:
            raise ErroDeModelo(
                f"a geração passou de {limite} combinações; reveja os grupos "
                "de ações excludentes ou aumente o limite conscientemente")

    return combinacoes


def combinacoes_els(acoes: list[Acao], tipos: tuple[str, ...] =
                    ("ELS-QP", "ELS-F", "ELS-R"),
                    incluir_variavel_ausente: bool = False) -> list[Combinacao]:
    """Combinações de serviço — Tabela 11.4.

        quase permanente  Fd,ser = ΣFgk + Σ ψ2j·Fqjk
        frequente         Fd,ser = ΣFgk + ψ1·Fq1k + Σ ψ2j·Fqjk
        rara              Fd,ser = ΣFgk + Fq1k + Σ ψ1j·Fqjk

    Atenção ao último: na combinação rara as ações secundárias entram com
    **ψ1**, e não com ψ0. É o que diz a Tabela 11.4, e é onde a implementação
    distraída erra.

    Por padrão as demais ações variáveis entram todas, uma por grupo
    excludente, como manda o somatório das fórmulas. ``incluir_variavel_ausente``
    acrescenta também as variantes em que cada grupo fica de fora, para quando
    a ação variável aliviar a verificação em serviço.
    """
    permanentes = [a for a in acoes if a.natureza == "permanente"]
    variaveis = [a for a in acoes if a.natureza == "variavel"]
    grupos = _agrupar(variaveis)

    combinacoes: list[Combinacao] = []
    contagem = {"ELS-QP": 0, "ELS-F": 0, "ELS-R": 0}

    def rotulo(tipo: str) -> str:
        contagem[tipo] += 1
        return _rotular(tipo, contagem[tipo])

    if "ELS-QP" in tipos:
        for escolha in _escolhas_secundarias(grupos, "",
                                             incluir_variavel_ausente):
            fatores = {a.caso: 1.0 for a in permanentes}
            partes = []
            for acao in escolha:
                if acao is None:
                    continue
                psi2 = acao.fatores_psi[2]
                if psi2 == 0.0:
                    continue
                fatores[acao.caso] = psi2
                partes.append(f"{acao.caso} com ψ2={psi2:.2f}")
            if fatores in [c.fatores for c in combinacoes]:
                continue
            combinacoes.append(Combinacao(
                rotulo("ELS-QP"), fatores, "ELS-QP",
                ", ".join(partes) or "só ações permanentes"))

    for tipo, indice_principal in (("ELS-F", 1), ("ELS-R", None)):
        if tipo not in tipos:
            continue
        for principal in variaveis:
            for escolha in _escolhas_secundarias(grupos, principal.chave_grupo,
                                                 incluir_variavel_ausente):
                fatores = {a.caso: 1.0 for a in permanentes}
                if indice_principal is None:
                    fatores[principal.caso] = 1.0
                    partes = [f"{principal.caso} com valor característico"]
                    psi_secundario = 1
                else:
                    psi1 = principal.fatores_psi[1]
                    fatores[principal.caso] = psi1
                    partes = [f"{principal.caso} com ψ1={psi1:.2f}"]
                    psi_secundario = 2
                for secundaria in escolha:
                    if secundaria is None:
                        continue
                    psi = secundaria.fatores_psi[psi_secundario]
                    if psi == 0.0:
                        continue
                    fatores[secundaria.caso] = psi
                    partes.append(
                        f"{secundaria.caso} com ψ{psi_secundario}={psi:.2f}")
                # Ação secundária de ψ nulo desaparece da soma, e duas
                # escolhas diferentes podem cair na mesma combinação.
                if any(c.tipo == tipo and c.fatores == fatores
                       for c in combinacoes):
                    continue
                combinacoes.append(Combinacao(
                    rotulo(tipo), fatores, tipo, ", ".join(partes)))

    return combinacoes


# ---------------------------------------------------------------------------
# 11.3.3.4.1 — desaprumo
# ---------------------------------------------------------------------------

@dataclass
class Desaprumo:
    """O que foi calculado, para poder ir para a memória de cálculo."""

    H: float
    n: int
    theta1: float
    theta1_sem_limite: float
    theta_a: float
    limitado: str
    forca_total: float
    nos: dict[str, float] = field(default_factory=dict)

    def __str__(self) -> str:
        return (f"desaprumo: H={self.H:.3f} m, n={self.n}, "
                f"θ1={self.theta1:.6f} ({self.limitado}), "
                f"θa={self.theta_a:.6f}, força total={self.forca_total:.4f}")


def _altura_e_prumadas(modelo: Modelo) -> tuple[float, int, float]:
    zs = [no.z for no in modelo.nos.values()]
    base = min(zs)
    H = max(zs) - base

    prumadas = set()
    for barra in modelo.barras.values():
        pi, pj = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
        d = pj - pi
        if abs(d[2]) > 1e-9 and math.hypot(d[0], d[1]) < 1e-6 * abs(d[2]):
            prumadas.add((round(pi[0], 6), round(pi[1], 6)))
    return H, len(prumadas), base


def cargas_verticais_por_no(modelo: Modelo, caso: CasoDeCarga) -> dict[str, float]:
    """Carga vertical descendente que chega a cada nó, no caso dado.

    A carga distribuída de uma barra é rateada entre os dois nós pela posição
    da sua resultante, e não meio a meio: com carga parcial ou trapezoidal as
    duas coisas deixam de coincidir. É a carga **aplicada** naquele nível, não
    a acumulada — a acumulação é o que a análise faz depois.
    """
    from .carregamento import resultante
    from .montagem import cargas_locais, preparar_barras

    por_no = {nome: 0.0 for nome in modelo.nos}

    for carga in caso.nodais:
        por_no[carga.no] += -carga.fz

    preparadas = preparar_barras(modelo)
    for nome, segmentos in cargas_locais(caso, preparadas).items():
        if not segmentos:
            continue
        p = preparadas[nome]
        F, posicao = resultante(segmentos)

        # Quanto cada componente local da resultante pesa na vertical global,
        # e onde ela age. ``p.R[c, 2]`` é a componente Z do eixo local ``c``.
        vertical_por_componente = -p.R[:, 2] * F
        vertical = float(np.sum(vertical_por_componente))
        if vertical == 0.0:
            continue
        centro = float(np.sum(vertical_por_componente * posicao) / vertical)

        fracao = min(max(centro / p.L, 0.0), 1.0)
        por_no[p.barra.no_i] += vertical * (1.0 - fracao)
        por_no[p.barra.no_j] += vertical * fracao

    return por_no


def desaprumo(modelo: Modelo, caso_vertical: str, destino: CasoDeCarga,
              direcao: tuple[float, float], H: float | None = None,
              n: int | None = None, aplicar_minimo: bool = True,
              theta_a_igual_theta1: bool = False) -> Desaprumo:
    """Acrescenta ao caso ``destino`` as forças nocionais de desaprumo.

        θ1 = 1/(100·√H)      com 1/300 ≤ θ1 ≤ 1/200
        θa = θ1·√[(1 + 1/n)/2]

    ``H`` é a altura total da edificação em metros e ``n`` o número de pilares
    que contribuem para o desaprumo global. Ambos são deduzidos do modelo
    quando não informados.

    A força nocional em cada nó vale θa vezes a carga vertical que chega
    naquele nó no caso ``caso_vertical``, e aponta na ``direcao`` dada, um
    versor horizontal. Nós com o deslocamento horizontal impedido ficam de
    fora: a força ali iria direto para a reação, sem solicitar nada.

    ``theta_a_igual_theta1`` atende ao caso dos edifícios com predominância de
    lajes lisas ou cogumelo, para os quais a norma manda tomar θa = θ1.
    """
    if caso_vertical not in modelo.casos:
        raise ErroDeModelo(f"caso de carga '{caso_vertical}' não existe")

    H_auto, n_auto, base = _altura_e_prumadas(modelo)
    H = H_auto if H is None else H
    n = n_auto if n is None else n

    if H <= 0.0:
        raise ErroDeModelo(
            "altura total nula: o desaprumo precisa de uma estrutura com "
            "elementos verticais")
    if n < 1:
        raise ErroDeModelo(
            "nenhum pilar identificado para o desaprumo; informe n")

    d = (float(direcao[0]), float(direcao[1]))
    norma = math.hypot(*d)
    if norma < 1e-12:
        raise ErroDeModelo("a direção do desaprumo não pode ser nula")
    d = (d[0] / norma, d[1] / norma)

    theta1_bruto = 1.0 / (100.0 * math.sqrt(H))
    if aplicar_minimo and theta1_bruto < THETA1_MIN:
        theta1, limitado = THETA1_MIN, "limitado pelo mínimo 1/300"
    elif theta1_bruto > THETA1_MAX:
        theta1, limitado = THETA1_MAX, "limitado pelo máximo 1/200"
    else:
        theta1, limitado = theta1_bruto, "dentro dos limites"

    theta_a = (theta1 if theta_a_igual_theta1
               else theta1 * math.sqrt((1.0 + 1.0 / n) / 2.0))

    verticais = cargas_verticais_por_no(modelo, modelo.casos[caso_vertical])
    aplicadas: dict[str, float] = {}
    total = 0.0
    for no, carga in verticais.items():
        if carga == 0.0:
            continue
        apoio = modelo.apoios.get(no)
        if apoio is not None and apoio.ux and apoio.uy:
            continue
        forca = theta_a * carga
        destino.nodal(no, fx=forca * d[0], fy=forca * d[1])
        aplicadas[no] = forca
        total += forca

    return Desaprumo(H, n, theta1, theta1_bruto, theta_a, limitado,
                     total, aplicadas)


def momento_na_base(modelo: Modelo, caso: CasoDeCarga) -> float:
    """Momento de tombamento das cargas horizontais de um caso, na base."""
    _, _, base = _altura_e_prumadas(modelo)
    mx = my = 0.0
    for carga in caso.nodais:
        braco = modelo.ponto(carga.no)[2] - base
        mx += carga.fx * braco
        my += carga.fy * braco
    return math.hypot(mx, my)


def confronto_vento_desaprumo(momento_vento: float,
                              momento_desaprumo: float) -> str:
    """A regra dos 30 % do item 11.3.3.4.1.

    a) 30 % do vento maior que o desaprumo — considera-se só o vento;
    b) vento menor que 30 % do desaprumo — só o desaprumo, respeitando θ1mín;
    c) nos demais casos — combinam-se os dois, sem θ1mín.

    A comparação é feita com os momentos totais na base, com o desaprumo
    calculado com θa e sem o θ1mín.
    """
    if 0.30 * momento_vento > momento_desaprumo:
        return "vento"
    if momento_vento < 0.30 * momento_desaprumo:
        return "desaprumo"
    return "ambos"
