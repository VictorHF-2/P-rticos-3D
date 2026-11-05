# -*- coding: utf-8 -*-
"""
fibras.py
Amostragem da seção em fibras discretas, para a vista 3D de transparência
(pilares/ui/vista3d.py): dado o estado de equilíbrio de uma situação, diz
que ponto da seção está comprimido -- e portanto resiste, e com que tensão
-- e qual a tensão em cada barra. Só números: quem desenha é a interface.

A ideia -- mostrar a seção como um conjunto de fibras, cada uma com sua
própria tensão, em vez de só o par (N, M) resultante -- vem da biblioteca
``fkit`` (Robert Wang, github.com/wcfrobert/fkit), que faz isso para flexão
**uniaxial** segundo o ACI 318. Nada do código foi aproveitado -- o ``fkit``
nem resolve o problema biaxial que este módulo amostra --, só o conceito: a
fibra como unidade visual de "isto está comprometido" ou "isto está livre".

O motor já integra o concreto em forma fechada, pelo Teorema de Green
(:mod:`pilares.core.green`) -- não há fibra nenhuma no cálculo em si, e é
assim que fica mais exato (ver a nota de precisão em ``green.py``). As
fibras daqui são só uma amostragem **a posteriori**, para desenho: o
programa resolve a seção sem elas, e as recria depois para mostrar onde a
tensão calculada está.

Amostragem por grade + teste dentro/fora (:func:`geometria.dentro`), não
triangulação nem booleana: cobre contorno côncavo (L, T, U) e furo
(circular/retangular vazada) do mesmo jeito, ao custo de um grão finito em
vez de uma malha exata -- grão pequeno o bastante (:data:`RESOLUCAO`) para a
transição comprimido/tracionado parecer contínua na tela.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geometria as geo
from . import seccional as sc
from .dimensionar import ResultadoPilar

#: Fibras por lado da caixa envolvente da seção -- grade
#: ``RESOLUCAO x RESOLUCAO``, filtrada pelo contorno real. Maior dá uma
#: transição mais lisa entre comprimido e tracionado; cada fibra a mais é
#: um teste de ponto-no-polígono (barato) e um cubo a mais na vista (não
#: tão barato), e o valor abaixo já deixa a transição visualmente contínua
#: numa seção de pilar comum.
RESOLUCAO = 26

#: Posição relativa de cada cota ao longo do lance -- 0 na base, 1 no topo.
#: ``res.verificacoes_z`` tem estas chaves -- no pilar em balanço nas duas
#: direções, só Topo e Base (ver ``dimensionar.py``) --, e é o que a vista
#: "Completo" (``vista3d.py``) usa
#: para empilhar as três situações na altura real do lance, em vez de
#: desenhar uma de cada vez.
FRACAO_Z = {"Base": 0.0, "Meio": 0.5, "Topo": 1.0}


@dataclass
class Fibra:
    """Uma fibra comprimida -- só estas aparecem na vista 3D."""

    x: float                     # cm, no sistema de eixos da seção
    y: float                     # cm
    tensao: float                 # kN/cm², sempre > 0 (só fibra comprimida)


@dataclass
class FibraBarra:
    """Tensão numa barra -- todas aparecem, inclusive as tracionadas."""

    x: float
    y: float
    area: float                  # cm²
    phi: float                   # mm
    rotulo: str
    eps: float                   # ‰, compressão positiva
    tensao: float                 # kN/cm², compressão positiva


@dataclass
class EstadoFibras:
    """Tudo que a vista 3D precisa para colorir uma situação.

    ``estado`` vem ``None`` quando a direção do momento solicitante está
    fora do alcance da envoltória resistente (item 5.5 de CADAMURO JÚNIOR,
    1997) -- a mesma reprovação sem equilíbrio que
    :func:`pilares.saidas.graficos.figura_momento_curvatura` já trata; aqui
    ``fibras`` e ``barras`` saem vazias e quem desenha mostra o aviso.
    """

    situacao: str                 # "Topo" / "Meio" / "Base"
    estado: "sc.Estado | None"
    fibras: list[Fibra] = field(default_factory=list)
    barras: list[FibraBarra] = field(default_factory=list)
    fcd_ac: float = 0.0            # kN/cm², teto de tensão do concreto (clim)
    fyd: float = 0.0               # kN/cm², teto de tensão do aço (clim)
    altura: float = 0.0            # cm, altura do lance (extrusão em z)


def _dentro_do_material(contornos: list, x: float, y: float) -> bool:
    """``True`` quando ``(x, y)`` está no contorno externo e fora de todo
    furo -- o segundo em diante em :meth:`SecaoPilar.contornos`."""
    if not geo.dentro(contornos[0], x, y):
        return False
    return not any(geo.dentro(furo, x, y) for furo in contornos[1:])


def amostrar_centros(contornos: list,
                     resolucao: int = RESOLUCAO) -> list[tuple[float, float]]:
    """Centros de fibra dentro do material, numa grade regular que cobre a
    caixa envolvente de todos os contornos."""
    xs = [p[0] for c in contornos for p in c]
    ys = [p[1] for c in contornos for p in c]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    passo_x = (x1 - x0) / resolucao
    passo_y = (y1 - y0) / resolucao
    if passo_x <= 0.0 or passo_y <= 0.0:
        return []
    centros = []
    for i in range(resolucao):
        x = x0 + (i + 0.5) * passo_x
        for j in range(resolucao):
            y = y0 + (j + 0.5) * passo_y
            if _dentro_do_material(contornos, x, y):
                centros.append((x, y))
    return centros


def estado_da_situacao(res: ResultadoPilar,
                       nome_situacao: str) -> "sc.Estado | None":
    """O estado de equilíbrio no ELU, na direção do momento daquela situação.

    É o mesmo estado que a envoltória de momentos resistentes já usa para
    dizer se a situação passa (``razao_envoltoria`` em
    :class:`pilares.core.dimensionar.VerificacaoSituacao`) -- aqui, em vez
    do número da razão, o campo de deformação inteiro por trás dele.
    """
    v = res.verificacoes_z.get(nome_situacao)
    if v is None or res.secao_discreta is None:
        return None
    s = v.situacao
    alfa = math.atan2(s.My, s.Mx) if (s.Mx or s.My) else 0.0
    estados = sc.estados_na_direcao(res.secao_discreta, res.pilar.Nd, alfa)
    return estados[-1] if estados else None


def montar(res: ResultadoPilar, nome_situacao: str,
          resolucao: int = RESOLUCAO) -> EstadoFibras:
    """Amostra a seção inteira -- fibras de concreto e barras -- para a
    situação pedida ("Topo", "Meio" ou "Base", as chaves de
    ``res.verificacoes_z``).
    """
    pilar = res.pilar
    fcd_ac = pilar.concreto.fator_pico * pilar.concreto.fcd_kNcm2
    fyd = pilar.aco.fyd_kNcm2
    altura = pilar.lance.altura
    estado = estado_da_situacao(res, nome_situacao)
    secao = res.secao_discreta
    if estado is None or secao is None:
        return EstadoFibras(nome_situacao, None, fcd_ac=fcd_ac, fyd=fyd,
                            altura=altura)

    plano = estado.plano
    theta = estado.theta
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    contornos = pilar.secao.contornos()

    fibras: list[Fibra] = []
    centros = amostrar_centros(contornos, resolucao)
    if centros:
        pontos = np.asarray(centros, dtype=float)
        u = pontos[:, 0] * cos_t + pontos[:, 1] * sin_t
        eps = plano.eps_ref + plano.k * (u - plano.u_ref)
        comprimidas = eps > 0.0
        if np.any(comprimidas):
            sigma = sc.tensao_concreto(pilar.concreto, eps[comprimidas])
            for (x, y), s_i in zip(pontos[comprimidas], sigma):
                fibras.append(Fibra(float(x), float(y), float(s_i)))

    barras: list[FibraBarra] = []
    for b in secao.barras:
        u = b.x * cos_t + b.y * sin_t
        eps_b = plano.eps(u)
        sigma_b = sc.tensao_aco(pilar.aco, eps_b)
        barras.append(FibraBarra(b.x, b.y, b.area, b.phi, b.rotulo,
                                 eps_b, sigma_b))

    return EstadoFibras(nome_situacao, estado, fibras, barras, fcd_ac, fyd,
                        altura)


def montar_completo(res: ResultadoPilar,
                    resolucao: int = RESOLUCAO) -> dict[str, EstadoFibras]:
    """Amostra as três cotas de uma vez, para a vista "Completo" -- a
    mesma amostragem de :func:`montar`, repetida em Base, Meio e Topo."""
    return {nome: montar(res, nome, resolucao) for nome in FRACAO_Z
            if nome in res.verificacoes_z}
