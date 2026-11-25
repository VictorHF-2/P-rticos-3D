# -*- coding: utf-8 -*-
"""
acoes.py
Combinações de ações a partir dos esforços **característicos** de cada ação
(NBR 6118:2026, 11.7 e 11.8; NBR 8681:2025).

A entrada passa a poder ser a lista de ações do lance -- peso próprio e
demais permanentes, sobrecargas, vento, temperatura -- cada uma com os seus
esforços característicos no topo e na base. O programa monta:

* as **combinações últimas** da Tabela 11.3 (normais, especiais ou de
  construção, conforme os critérios), com os coeficientes da Tabela 11.1 e
  os fatores de combinação ``psi0`` da Tabela 11.2:
  ``Fd = gamma_g Fgk + gamma_q (Fq1k + sum psi0j Fqjk) + gamma_eq psi0e Feqk``,
  cada ação variável direta como principal por vez, mais a combinação só
  com as permanentes;
* para cada combinação última, a **frequente** de mesmo arranjo
  (``Fgk + psi1 Fq1k + sum psi2j Fqjk``, Tabela 11.4) -- o ELS-W, quando
  ligado -- e a **quase permanente** (``Fgk + sum psi2j Fqjk``), de onde
  saem ``N_Sg/Nd`` e ``M_Sg/Md`` da fluência (15.8.4);
* a combinação de **incêndio** da NBR 15200 (8.1): a excepcional da Tabela
  11.1 (``gamma_g = 1,2``, ``gamma_q = 1,0``) com ``0,7 psi2`` nas variáveis,
  sem os esforços da dilatação térmica restringida.

Ações variáveis do mesmo **grupo excludente** não atuam juntas: as direções
do vento (categoria ``V``) formam um grupo automaticamente -- e cada uma entra
também com o sinal trocado, porque o vento muda de sentido --, e qualquer outra
ação pode ser posta num grupo com o sufixo ``#nome`` na categoria (posições
alternativas de uma carga móvel, por exemplo). Em cada combinação entra no
máximo um membro de cada grupo.

A temperatura (categoria ``T``) é ação indireta: entra sempre como
secundária, ``gamma_eq psi0e``, nunca como principal (Tabela 11.3).

As permanentes entram sempre desfavoráveis (``gamma_g`` = 1,4 nas normais);
as combinações com ``gamma_g`` = 1,0 -- permanente favorável -- só com o
critério ligado: a nota a) da Tabela 11.3 as dispensa em edifícios usuais.
Variável favorável não entra (``gamma_q`` = 0): a combinação só com as
permanentes cobre esse caso.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, fields

from .formato import num
from .modelo import CATEGORIAS_ACOES, Acao, Combinacao, Esforcos, Pilar

CATEGORIAS = CATEGORIAS_ACOES

#: Tabela 11.1 -- (gamma_g desfavorável, gamma_g favorável, gamma_q,
#: gamma_eq da temperatura) por tipo de combinação última.
GAMMA_F: dict[str, tuple[float, float, float, float]] = {
    "normais": (1.4, 1.0, 1.4, 1.2),
    "especiais": (1.3, 1.0, 1.2, 1.0),
    "excepcionais": (1.2, 1.0, 1.0, 0.0),
}

#: NBR 15200, 8.1: psi2 pode ser multiplicado por 0,7 (NBR 8681).
FATOR_PSI2_INCENDIO = 0.7

#: Teto de combinações geradas -- acima disso a entrada provavelmente tem
#: grupos demais e o cálculo ficaria lento sem ganho.
MAXIMO_COMBINACOES = 120

_CAMPOS = tuple(f.name for f in fields(Esforcos))


@dataclass
class CombinacaoGerada:
    """Uma combinação última gerada, com as de serviço do mesmo arranjo."""

    nome: str
    descricao: str                       # a fórmula, com os coeficientes
    esforcos: Esforcos                   # de cálculo
    frequente: Esforcos                  # sem ponderação
    quase_permanente: Esforcos
    Nsg_sobre_Nd: float = 0.0
    Msg_sobre_Md: float = 0.0


def _soma(termos: list[tuple[float, Acao]]) -> Esforcos:
    """``sum f_i E_i`` campo a campo; cortante em módulo (sem sinal)."""
    saida = {}
    for c in _CAMPOS:
        v = sum(f * getattr(a.esforcos, c) for f, a in termos)
        saida[c] = abs(v) if c.startswith("Vd") else v
    return Esforcos(**saida)


def _termo(f: float, a: Acao) -> str:
    return a.nome if abs(f - 1.0) < 1e-12 else f"{num(f, 2)}·{a.nome}"


def _maior_momento(e: Esforcos) -> float:
    return max(abs(e.Mx_topo), abs(e.Mx_base), abs(e.My_topo),
               abs(e.My_base))


def _arranjos(variaveis: list[Acao], principal: Acao | None
              ) -> list[list[Acao]]:
    """As secundárias que acompanham ``principal``: todas as independentes
    e um membro de cada grupo excludente (fora o grupo da principal)."""
    indep = [a for a in variaveis if not a.grupo and a is not principal]
    grupos: dict[str, list[Acao]] = {}
    for a in variaveis:
        if a.grupo and (principal is None or a.grupo != principal.grupo):
            grupos.setdefault(a.grupo, []).append(a)
    if not grupos:
        return [indep]
    return [indep + list(escolha)
            for escolha in itertools.product(*grupos.values())]


def _vento_nos_dois_sentidos(acoes: list[Acao]) -> list[Acao]:
    """Cada ação de vento (``V``) entra também com o sinal trocado -- o vento
    muda de sentido --, no mesmo grupo excludente. Quem já informou os dois
    sentidos só ganha combinações repetidas."""
    from dataclasses import replace
    saida = []
    for a in acoes:
        saida.append(a)
        if a.codigo == "V":
            oposto = Esforcos(**{c: -getattr(a.esforcos, c) for c in _CAMPOS})
            saida.append(replace(a, nome=f"−{a.nome}", esforcos=oposto))
    return saida


def gerar(acoes: list[Acao], tipo: str = "normais",
          permanente_favoravel: bool = False) -> list[CombinacaoGerada]:
    """As combinações últimas do tipo pedido (Tabela 11.3), com a frequente e
    a quase permanente de cada uma."""
    for a in acoes:
        a.validar()
    acoes = _vento_nos_dois_sentidos(acoes)
    gd, gfav, gq, geq = GAMMA_F.get(tipo, GAMMA_F["normais"])
    perm = [a for a in acoes if a.permanente]
    var = [a for a in acoes if not a.permanente]
    diretas = [a for a in var if not a.temperatura]
    saida: list[CombinacaoGerada] = []
    gammas_g = [gd] + ([gfav] if permanente_favoravel and gfav != gd else [])

    for gg in gammas_g:
        casos: list[tuple[Acao | None, list[Acao]]] = [(None, [])]
        for p in diretas:
            for sec in _arranjos(var, p):
                casos.append((p, sec))
        if not diretas and var:
            casos += [(None, s) for s in _arranjos(var, None)]
        for principal, sec in casos:
            termos = [(gg, a) for a in perm]
            freq = [(1.0, a) for a in perm]
            qp = [(1.0, a) for a in perm]
            texto = []
            if perm:
                texto.append(f"{num(gg, 2)}·(" + " + ".join(a.nome for a in perm)
                             + ")")
            if principal is not None:
                p0, p1, p2 = principal.psi
                termos.append((gq, principal))
                freq.append((p1, principal))
                qp.append((p2, principal))
            parte_q = ([principal.nome] if principal is not None else [])
            parte_t = []
            for a in sec:
                p0, p1, p2 = a.psi
                g = geq if a.temperatura else gq
                if g == 0.0 or p0 == 0.0:
                    continue
                termos.append((g * p0, a))
                freq.append((p2, a))
                qp.append((p2, a))
                (parte_t if a.temperatura else parte_q).append(_termo(p0, a))
            if parte_q:
                texto.append(f"{num(gq, 2)}·(" + " + ".join(parte_q) + ")")
            if parte_t:
                texto.append(f"{num(geq, 2)}·(" + " + ".join(parte_t) + ")")
            ed = _soma(termos)
            ef = _soma(freq)
            eq = _soma(qp)
            n_sg = eq.Nd / ed.Nd if abs(ed.Nd) > 1e-9 else 0.0
            m_d = _maior_momento(ed)
            m_sg = (_maior_momento(eq) / m_d) if m_d > 1e-9 else 0.0
            saida.append(CombinacaoGerada(
                nome=f"ELU {len(saida) + 1}",
                descricao=" + ".join(texto) if texto else "(vazia)",
                esforcos=ed, frequente=ef, quase_permanente=eq,
                Nsg_sobre_Nd=min(max(n_sg, 0.0), 1.0),
                Msg_sobre_Md=min(max(m_sg, 0.0), 1.0)))
    if len(saida) > MAXIMO_COMBINACOES:
        raise ValueError(
            f"As ações informadas geram {len(saida)} combinações últimas, "
            f"acima do teto de {MAXIMO_COMBINACOES}. Reduza os grupos "
            f"excludentes ou junte ações de mesma natureza.")
    return saida


def incendio(acoes: list[Acao]) -> tuple[Esforcos, str]:
    """Combinação excepcional de incêndio (NBR 15200, 8.1; Tabela 11.1 da
    NBR 6118, excepcionais): ``1,2 Fgk + sum 0,7 psi2 Fqk``, sem o vento
    (``psi2 = 0``) e sem a dilatação térmica restringida."""
    gd, _, gq, _ = GAMMA_F["excepcionais"]
    termos, texto = [], []
    for a in acoes:
        if a.permanente:
            termos.append((gd, a))
            texto.append(_termo(gd, a))
            continue
        f = gq * FATOR_PSI2_INCENDIO * a.psi[2]
        if f > 0.0:
            termos.append((f, a))
            texto.append(_termo(f, a))
    return _soma(termos), " + ".join(texto)


def aplicar(pilar: Pilar) -> Pilar:
    """O lance com as combinações geradas das ações no lugar dos esforços
    de entrada (``esforcos`` = a primeira, ``combinacoes`` = as demais), já
    de cálculo: ``gamma_f`` da entrada vai a 1,0. Sem ações, o próprio
    lance."""
    if not pilar.acoes:
        return pilar
    from dataclasses import replace
    cfg = pilar.config
    geradas = gerar(pilar.acoes, cfg.combinacao,
                    cfg.acoes_permanente_favoravel)
    servico = cfg.acoes_servico

    def comb(g: CombinacaoGerada) -> Combinacao:
        return Combinacao(
            nome=g.nome, esforcos=g.esforcos, descricao=g.descricao,
            esforcos_servico=g.frequente if servico else None,
            Nsg_sobre_Nd=g.Nsg_sobre_Nd, Msg_sobre_Md=g.Msg_sobre_Md)

    primeira, *demais = [comb(g) for g in geradas]
    novo = replace(pilar, esforcos=primeira.esforcos,
                   nome_combinacao=primeira.nome,
                   combinacoes=demais,
                   config=replace(cfg, gamma_f=1.0))
    return novo.com_combinacao(primeira, manter_demais=True)
