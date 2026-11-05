# -*- coding: utf-8 -*-
"""
grelha.py
Os eixos do projeto e o que se faz com eles na planta — sem tela nenhuma, para
que o editor, a linha de comando e as conferências façam a mesma coisa.

* ``nova_grelha``: colunas (letras) e linhas (números) em espaçamento
  uniforme;
* ``lancar_na_grelha``: pilares nos encontros e vigas entre os pilares de
  cada eixo;
* ``mudar_espaco``: troca **um** espaçamento; os eixos depois dele andam, e o
  que está lançado anda junto;
* ``dividir_por_direcao``: a polilinha de viga quebrada em trechos retos, uma
  viga por direção.
"""

from __future__ import annotations

import math
from dataclasses import replace

from .modelo import Grelha, Lancamento, PilarLancado, Planta, VigaLancada

#: Abaixo disso dois pontos são o mesmo, m.
TOL = 1e-6
#: Duas direções que diferem menos que isso, em graus, são a mesma: a viga
#: segue reta.
TOL_ANGULO = 0.5


def nova_grelha(n_colunas: int, espaco_colunas: float, n_linhas: int,
                espaco_linhas: float, x0: float = 0.0,
                y0: float = 0.0) -> Grelha:
    """Grelha de ``n_colunas`` × ``n_linhas`` eixos, espaçamentos uniformes."""
    if n_colunas < 1 or n_linhas < 1:
        raise ValueError("a grelha precisa de pelo menos uma coluna e uma "
                         "linha")
    if espaco_colunas <= 0.0 or espaco_linhas <= 0.0:
        raise ValueError("o espaçamento da grelha tem de ser positivo")
    return Grelha(x0=x0, y0=y0,
                  espacos_colunas=[float(espaco_colunas)] * (n_colunas - 1),
                  espacos_linhas=[float(espaco_linhas)] * (n_linhas - 1))


# ---------------------------------------------------------------------------
# Viga quebrada por direção
# ---------------------------------------------------------------------------

def _direcao(a, b) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def dividir_por_direcao(pontos) -> list[list[tuple[float, float]]]:
    """Os trechos retos da polilinha: um a cada mudança de direção.

    ``(0;0) (4,5;0) (6;2)`` dá dois trechos — ``(0;0)-(4,5;0)`` e
    ``(4,5;0)-(6;2)`` —, e cada um vira uma viga. Pontos repetidos somem, e
    pontos no meio de um trecho reto também (o trecho continua um só).
    """
    limpos: list[tuple[float, float]] = []
    for p in pontos:
        p = (float(p[0]), float(p[1]))
        if not limpos or math.dist(limpos[-1], p) > TOL:
            limpos.append(p)
    if len(limpos) < 2:
        return []
    trechos = [[limpos[0], limpos[1]]]
    for p in limpos[2:]:
        atual = trechos[-1]
        diferenca = abs((_direcao(atual[-1], p) - _direcao(atual[0], atual[-1])
                         + 180.0) % 360.0 - 180.0)
        if diferenca <= TOL_ANGULO:
            atual[-1] = p                     # segue reto: estica o trecho
        else:
            trechos.append([atual[-1], p])
    return trechos


# ---------------------------------------------------------------------------
# Lançar na grelha
# ---------------------------------------------------------------------------

def _proximo_nome(prefixo: str, itens) -> str:
    usados = {i.nome for i in itens}
    k = 1
    while f"{prefixo}{k}" in usados:
        k += 1
    return f"{prefixo}{k}"


def _tem_pilar(planta: Planta, x: float, y: float, tol: float) -> bool:
    return any(math.dist(p.centro, (x, y)) <= tol for p in planta.pilares)


def _coberto_por_viga(planta: Planta, a, b) -> bool:
    """Se já existe viga sobre o segmento ``a``–``b`` inteiro."""
    for v in planta.vigas:
        for c, d in zip(v.pontos, v.pontos[1:]):
            dx, dy = d[0] - c[0], d[1] - c[1]
            L2 = dx * dx + dy * dy
            if L2 <= TOL:
                continue
            ok = True
            for p in (a, b):
                t = ((p[0] - c[0]) * dx + (p[1] - c[1]) * dy) / L2
                proj = (c[0] + t * dx, c[1] + t * dy)
                if not (-TOL <= t <= 1 + TOL) or math.dist(proj, p) > 1e-3:
                    ok = False
            if ok:
                return True
    return False


def lancar_na_grelha(planta: Planta, grelha: Grelha, pilares: bool = True,
                     vigas: bool = True,
                     pilar_padrao: PilarLancado | None = None,
                     viga_padrao: VigaLancada | None = None
                     ) -> tuple[list[PilarLancado], list[VigaLancada]]:
    """Pilares nos encontros e vigas entre os pilares de cada eixo.

    Com ``pilares``, cada encontro ganha um pilar, menos onde já há um. Com
    ``vigas``, cada eixo ganha **uma viga reta** do primeiro ao último pilar
    que está sobre ele — o gerador a quebra nos pilares do meio, como faz
    com qualquer viga. Eixo com menos de dois pilares não leva viga, e eixo
    que já tem viga em cima não ganha outra.

    Devolve o que foi acrescentado.
    """
    pilar_padrao = pilar_padrao or PilarLancado("P", 0.0, 0.0)
    viga_padrao = viga_padrao or VigaLancada("V", [])
    novos_p: list[PilarLancado] = []
    novas_v: list[VigaLancada] = []
    tol = 1e-3

    if pilares:
        for _, x, y in grelha.encontros():
            if _tem_pilar(planta, x, y, tol):
                continue
            # o pilar entra pelo centro: o encontro é o eixo dele
            p = replace(pilar_padrao, nome=_proximo_nome("P", planta.pilares),
                        x=x, y=y, insercao="centro")
            planta.pilares.append(p)
            novos_p.append(p)

    if vigas:
        eixos = ([[(x, y) for x in grelha.xs] for y in grelha.ys]       # linhas
                 + [[(x, y) for y in grelha.ys] for x in grelha.xs])    # colunas
        for eixo in eixos:
            com_pilar = [q for q in eixo if _tem_pilar(planta, *q, tol)]
            if len(com_pilar) < 2:
                continue
            a, b = com_pilar[0], com_pilar[-1]
            if _coberto_por_viga(planta, a, b):
                continue
            v = replace(viga_padrao, nome=_proximo_nome("V", planta.vigas),
                        pontos=[a, b])
            planta.vigas.append(v)
            novas_v.append(v)
    return novos_p, novas_v


# ---------------------------------------------------------------------------
# Mudar um espaçamento
# ---------------------------------------------------------------------------

def _mapa(antigos: list[float], novos: list[float]):
    """A coordenada antiga levada para a nova, eixo a eixo.

    Sobre um eixo, o ponto vai para o eixo novo; entre dois eixos, fica na
    mesma proporção do vão (a laje no meio do vão continua no meio); além do
    último, anda o que o último andou.
    """
    def f(v: float) -> float:
        if v <= antigos[0] + TOL:
            return v + (novos[0] - antigos[0])
        for k in range(len(antigos) - 1):
            a, b = antigos[k], antigos[k + 1]
            if v <= b + TOL:
                if abs(v - b) <= TOL:
                    return novos[k + 1]
                return novos[k] + (v - a) * (novos[k + 1] - novos[k]) / (b - a)
        return v + (novos[-1] - antigos[-1])
    return f


def mudar_espaco(lanc: Lancamento, eixo: str, indice: int,
                 valor: float) -> None:
    """Troca o espaçamento ``indice`` das colunas (``eixo="coluna"``) ou das
    linhas (``eixo="linha"``) para ``valor``, m.

    Só aquele espaço muda: os outros ficam como estão, e os eixos depois dele
    se deslocam. O que está lançado em todas as plantas anda com os eixos —
    pilar sobre a coluna D continua sobre a coluna D.
    """
    g = lanc.grelha
    if g is None:
        raise ValueError("não há grelha")
    if valor <= 0.0:
        raise ValueError("o espaçamento tem de ser positivo")
    espacos = g.espacos_colunas if eixo == "coluna" else g.espacos_linhas
    if not 0 <= indice < len(espacos):
        raise IndexError(f"a grelha não tem o espaço {indice + 1} de "
                         f"{'colunas' if eixo == 'coluna' else 'linhas'}")
    antigos = g.xs if eixo == "coluna" else g.ys
    espacos[indice] = float(valor)
    f = _mapa(antigos, g.xs if eixo == "coluna" else g.ys)

    def mover(p):
        return ((round(f(p[0]), 6), p[1]) if eixo == "coluna"
                else (p[0], round(f(p[1]), 6)))

    for planta in lanc.plantas.values():
        # o pilar anda pelo centro, e não pelo ponto de inserção: inserido
        # pelo canto mas centrado no eixo, ele continua centrado no eixo
        for p in planta.pilares:
            cx, cy = p.centro
            nx, ny = mover((cx, cy))
            p.x, p.y = round(p.x + nx - cx, 6), round(p.y + ny - cy, 6)
        for laje in planta.lajes:
            laje.x, laje.y = mover((laje.x, laje.y))
        for o in planta.vigas + planta.paredes:
            o.pontos = [mover(q) for q in o.pontos]
