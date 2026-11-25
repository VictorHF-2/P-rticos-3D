# -*- coding: utf-8 -*-
"""
detalhamento.py
Escolha das barras, arranjo em camadas, escalonamento (corte) da armadura
longitudinal e distribuição dos estribos, conforme os itens 18.3 e 9.4 da
NBR 6118.

Unidades: comprimentos das barras e espaçamentos em cm; posições ao longo da
viga em metros; armaduras em cm² (longitudinal) e cm²/m (transversal).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .materiais import (BITOLAS_BARRAS, BITOLAS_ESTRIBOS, area_barra, massa_linear)
from .modelo import Secao
from .avisos import construtivo, erro

#: Bitola dos porta-estribos, mm (uma barra por canto de estribo).
PHI_PORTA_ESTRIBO = 6.3

#: Barras necessárias em cada face para apoiar os cantos do estribo.
CANTOS_POR_FACE = 2

#: Espaçamentos comerciais de estribos, cm.
ESPACAMENTOS = (5.0, 6.0, 7.0, 7.5, 8.0, 9.0, 10.0, 11.0, 12.0, 12.5, 13.0,
                14.0, 15.0, 16.0, 17.0, 17.5, 18.0, 19.0, 20.0, 22.0, 22.5,
                25.0, 27.5, 30.0)


# ---------------------------------------------------------------------------
# Arranjo das barras longitudinais
# ---------------------------------------------------------------------------

@dataclass
class Arranjo:
    """Distribuição de ``n`` barras de bitola ``phi`` em camadas."""

    phi: float                # mm
    n: int
    camadas: list[int]        # nº de barras em cada camada, da face para dentro
    As_ef: float              # cm²
    y_cg: float               # cm, do centro de gravidade à face tracionada
    d: float                  # cm, altura útil resultante
    ah: float                 # cm, espaçamento livre horizontal
    av: float                 # cm, espaçamento livre vertical
    n_por_camada: int
    cabe: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def descricao(self) -> str:
        if len(self.camadas) == 1:
            return f"{self.n} phi {self.phi:g}"
        camadas = " + ".join(f"{c}" for c in self.camadas)
        return f"{self.n} phi {self.phi:g} ({camadas})"

    @property
    def excesso(self) -> float:
        return self.As_ef


def espacamentos_minimos(phi_mm: float, d_agregado: float
                         ) -> tuple[float, float]:
    """Espaçamentos livres mínimos horizontal e vertical, cm (18.3.2.2)."""
    phi_cm = phi_mm / 10.0
    ah = max(2.0, phi_cm, 1.2 * d_agregado)
    av = max(2.0, phi_cm, 0.5 * d_agregado)
    return ah, av


def camadas_por_altura(secao: Secao, phi_mm: float, cobrimento: float,
                       phi_estribo: float, d_agregado: float) -> int:
    """Número máximo de camadas que cabem na altura da seção (18.3.2.2).

    A primeira camada nasce a ``y0`` da face tracionada e a última não pode
    passar de ``h - y0``, senão as barras invadiriam o cobrimento da face
    oposta. Sem esse limite, uma armadura que não cabe na seção sai como uma
    pilha de dezenas de camadas e a altura útil resultante fica negativa.
    """
    _, av = espacamentos_minimos(phi_mm, d_agregado)
    phi_cm = phi_mm / 10.0
    y0 = cobrimento + phi_estribo / 10.0 + phi_cm / 2.0
    livre = secao.h - 2.0 * y0
    if livre < 0.0:
        return 0
    return 1 + int(math.floor(livre / (phi_cm + av) + 1e-9))


def barras_por_camada(secao: Secao, phi_mm: float, cobrimento: float,
                      phi_estribo: float, d_agregado: float) -> int:
    """Número máximo de barras que cabem numa camada."""
    ah, _ = espacamentos_minimos(phi_mm, d_agregado)
    phi_cm = phi_mm / 10.0
    livre = secao.bw - 2.0 * cobrimento - 2.0 * phi_estribo / 10.0
    if livre < phi_cm:
        return 0
    return max(1, int(math.floor((livre + ah) / (phi_cm + ah) + 1e-9)))


def montar_arranjo(secao: Secao, As_req: float, phi_mm: float,
                   cobrimento: float, phi_estribo: float, d_agregado: float,
                   n_min: int = 2, n_ramos: int = 2) -> Arranjo:
    """Distribui as barras necessárias de uma bitola em camadas.

    A primeira camada aproveita toda a largura disponível; da segunda em
    diante o número de barras é limitado ao número de ramos do estribo,
    porque cada barra dessas camadas precisa se apoiar em um ramo para ficar
    amarrada -- não há canto de estribo para segurá-la.
    """
    A1 = area_barra(phi_mm)
    n = max(n_min, int(math.ceil(As_req / A1 - 1e-9)))
    npc = barras_por_camada(secao, phi_mm, cobrimento, phi_estribo, d_agregado)
    ncam = camadas_por_altura(secao, phi_mm, cobrimento, phi_estribo,
                              d_agregado)
    ah, _av = espacamentos_minimos(phi_mm, d_agregado)
    avisos: list[str] = []
    cabe = npc >= 1
    if not cabe:
        return Arranjo(phi=phi_mm, n=n, camadas=[n], As_ef=n * A1, y_cg=0.0,
                       d=0.0, ah=0.0, av=0.0, n_por_camada=0, cabe=False,
                       avisos=[erro(f"A bitola {phi_mm:g} mm não cabe na "
                                    f"largura bw = {secao.bw:g} cm, "
                                    f"respeitado o espaçamento livre mínimo "
                                    f"de {ah:.1f} cm (18.3.2.2).")])
    npc_interna = max(1, min(npc, n_ramos))
    camadas: list[int] = []
    restante = n
    while restante > 0:
        limite = npc if not camadas else npc_interna
        camadas.append(min(limite, restante))
        restante -= camadas[-1]
    if len(camadas) > 1 and npc_interna < npc:
        avisos.append(construtivo(
            f"Camadas acima da primeira limitadas a {npc_interna} barra(s), "
            f"igual ao número de ramos do estribo, para que cada barra fique "
            f"amarrada em um ramo (18.3.2.2)."))

    ah, av = espacamentos_minimos(phi_mm, d_agregado)
    phi_cm = phi_mm / 10.0
    y0 = cobrimento + phi_estribo / 10.0 + phi_cm / 2.0
    passo = phi_cm + av
    soma = sum(nc * (y0 + k * passo) for k, nc in enumerate(camadas))
    y_cg = soma / n
    d = secao.h - y_cg
    if len(camadas) > ncam:
        # a armadura não cabe na seção: avisa e trunca a altura útil num valor
        # utilizável, para o erro aparecer em vez de virar d negativo
        cabe = False
        avisos.append(erro(
            f"{n} barras Ø{phi_mm:g} exigem {len(camadas)} camadas e só cabem "
            f"{ncam} na altura h = {secao.h:g} cm, com {npc} barra(s) por "
            f"camada em bw = {secao.bw:g} cm (espaçamentos livres mínimos "
            f"ah = {ah:.1f} cm e av = {av:.1f} cm, item 18.3.2.2). Aumente a "
            f"seção, use bitola maior ou armadura em feixe."))
        d = max(d, 0.2 * secao.h)
    elif len(camadas) > 2:
        avisos.append(construtivo(
            f"{len(camadas)} camadas de armadura na face: cabem na seção, mas "
            f"reveja a bitola ou a largura da viga para facilitar a "
            f"concretagem."))
    return Arranjo(phi=phi_mm, n=n, camadas=camadas, As_ef=n * A1, y_cg=y_cg,
                   d=d, ah=ah, av=av, n_por_camada=npc, cabe=cabe,
                   avisos=avisos)


#: fração de h que a distância do CG da armadura à camada mais afastada não
#: pode exceder, para as forças poderem ser tomadas concentradas no CG
#: (17.2.4.1)
FRACAO_RESULTANTE = 0.10


def resultante_concentrada(arranjo: Arranjo, h_cm: float) -> tuple[bool, float]:
    """O item 17.2.4.1 permite concentrar as forças no CG da armadura?

    "As forças nas armaduras podem ser consideradas concentradas no centro de
    gravidade correspondente, se a distância deste centro de gravidade ao
    centro da armadura mais afastada, medida normalmente à linha neutra, for
    menor que 10 % de h."

    A armadura mais afastada da linha neutra é a camada **mais próxima da face
    tracionada**, e a distância sai da geometria que o arranjo já guarda: as
    camadas estão a ``phi + av`` uma da outra, e ``y_cg`` é a distância do CG à
    face. Num arranjo de camada única a distância é zero e o item é trivial.

    Devolve ``(atende, distância em cm)``. A condição morde em viga baixa com
    muitas camadas, e é ali que o ``d`` calculado pelo CG deixa de representar
    o conjunto -- exatamente o que o item protege.
    """
    if arranjo.n <= 0 or len(arranjo.camadas) <= 1:
        return True, 0.0
    passo = arranjo.phi / 10.0 + arranjo.av
    # y da primeira camada (a mais próxima da face) que dá o y_cg guardado
    desloc = (sum(nb * k * passo for k, nb in enumerate(arranjo.camadas))
              / max(arranjo.n, 1))
    distancia = abs(desloc)
    return distancia < FRACAO_RESULTANTE * h_cm + 1e-9, distancia


def escolher_barras(secao: Secao, As_req: float, cobrimento: float,
                    phi_estribo: float, d_agregado: float,
                    phi_min: float = 8.0, phi_max: float = 25.0,
                    phi_fixo: float = 0.0, n_min: int = 2,
                    n_ramos: int = 2) -> Arranjo:
    """Escolhe a bitola e o número de barras para atender ``As_req``.

    Prefere o arranjo de uma só camada com a menor sobra de área; entre
    empates, a menor bitola. Bitolas que não cabem na largura são descartadas.
    """
    if phi_fixo:
        return montar_arranjo(secao, As_req, phi_fixo, cobrimento,
                              phi_estribo, d_agregado, n_min, n_ramos)
    candidatos: list[Arranjo] = []
    for phi in BITOLAS_BARRAS:
        if phi < phi_min or phi > phi_max:
            continue
        arr = montar_arranjo(secao, As_req, phi, cobrimento, phi_estribo,
                             d_agregado, n_min, n_ramos)
        if arr.cabe and arr.n <= 12:
            candidatos.append(arr)
    if not candidatos:
        # nenhuma bitola atende com um número razoável de barras: devolve o
        # arranjo menos ruim (menos camadas, maior bitola) já marcado como
        # inviável. Cair na menor bitola aqui produzia dezenas de camadas de
        # Ø8, o que esconde o problema em vez de mostrá-lo.
        todos = [montar_arranjo(secao, As_req, phi, cobrimento, phi_estribo,
                                d_agregado, n_min, n_ramos)
                 for phi in BITOLAS_BARRAS if phi_min <= phi <= phi_max]
        todos = todos or [montar_arranjo(secao, As_req, phi_min, cobrimento,
                                         phi_estribo, d_agregado, n_min,
                                         n_ramos)]
        melhor = min(todos, key=lambda a: (len(a.camadas), -a.phi))
        if melhor.cabe:
            melhor.cabe = False
            melhor.avisos.append(erro(
                f"As = {As_req:.2f} cm² exige {melhor.n} barras "
                f"Ø{melhor.phi:g} nesta face: mais que as 12 barras admitidas "
                f"por face. Aumente a seção ou o fck."))
        return melhor
    def chave(a: Arranjo) -> tuple:
        return (len(a.camadas), a.As_ef / max(As_req, 1e-6), a.phi)
    return min(candidatos, key=chave)


# ---------------------------------------------------------------------------
# Estribos
# ---------------------------------------------------------------------------

@dataclass
class ZonaEstribo:
    """Trecho da viga com um mesmo estribo e espaçamento."""

    x_ini: float              # m
    x_fim: float              # m
    phi: float                # mm
    s: float                  # cm
    n_ramos: int
    asw_req: float            # cm²/m
    asw_ef: float             # cm²/m
    n_estribos: int
    tramo: int = 0
    #: trecho prismático da faixa. O estribo é uma **peça**, e o comprimento
    #: dela sai da seção: uma faixa que atravessasse uma mudança de seção
    #: especificaria um estribo de 206 cm numa seção de 60 cm de altura
    trecho: int = 0
    #: faixa adensada para costurar uma emenda (9.5.2.4.1), embutida na
    #: distribuição. O espaçamento dela vem da emenda, e não do cortante
    costura: bool = False
    #: faixa adensada pela armadura de suspensão (18.3.6), somada ao
    #: cisalhamento no cruzamento com outra viga
    suspensao: bool = False
    #: faixa adensada pela armadura transversal ao longo de uma ancoragem
    #: (9.4.2.6), onde os estribos existentes não davam 25 % da força da barra
    ancoragem: bool = False

    @property
    def comprimento(self) -> float:
        return self.x_fim - self.x_ini

    @property
    def descricao(self) -> str:
        return f"phi {self.phi:g} c/{self.s:g}"


def asw_efetiva(phi_mm: float, s_cm: float, n_ramos: int) -> float:
    """Armadura transversal efetiva, cm²/m."""
    return n_ramos * area_barra(phi_mm) / s_cm * 100.0


def espacamento_para(asw_req: float, phi_mm: float, n_ramos: int,
                     s_max: float) -> float:
    """Maior espaçamento comercial que atende à armadura pedida, cm."""
    if asw_req <= 0.0:
        return min(s_max, ESPACAMENTOS[-1])
    s_calc = n_ramos * area_barra(phi_mm) / asw_req * 100.0
    limite = min(s_calc, s_max)
    validos = [s for s in ESPACAMENTOS if s <= limite + 1e-9]
    return validos[-1] if validos else ESPACAMENTOS[0]


def detalhar_estribos(x: np.ndarray, asw_req: np.ndarray, s_max: np.ndarray,
                      phi_mm: float, n_ramos: int, x_ini: float, x_fim: float,
                      tramo: int = 0, comprimento_minimo: float = 0.5,
                      n_zonas_max: int = 3,
                      trecho: int = 0) -> list[ZonaEstribo]:
    """Escalona os estribos de um tramo em até ``n_zonas_max`` trechos.

    A viga é dividida em trechos simétricos de apoio e um trecho central; em
    cada um adota-se o espaçamento exigido pelo ponto mais solicitado, o que
    mantém o desenho executável sem deixar nenhuma seção descoberta.
    """
    mask = (x >= x_ini - 1e-9) & (x <= x_fim + 1e-9)
    if not mask.any():
        return []
    xs, aswx, smaxx = x[mask], asw_req[mask], s_max[mask]
    L = x_fim - x_ini
    n_zonas = max(1, min(n_zonas_max, int(L / comprimento_minimo)))

    if n_zonas == 1:
        cortes = [x_ini, x_fim]
    elif n_zonas == 2:
        cortes = [x_ini, x_ini + L / 2.0, x_fim]
    else:
        # trechos de apoio com 1/4 do vão e trecho central com a metade
        cortes = [x_ini, x_ini + L / 4.0, x_fim - L / 4.0, x_fim]

    zonas: list[ZonaEstribo] = []
    for a, b in zip(cortes, cortes[1:]):
        m = (xs >= a - 1e-9) & (xs <= b + 1e-9)
        if not m.any():
            continue
        req = float(np.max(aswx[m]))
        smx = float(np.min(smaxx[m]))
        s = espacamento_para(req, phi_mm, n_ramos, smx)
        n_est = max(2, int(math.ceil((b - a) * 100.0 / s)) + 1)
        zonas.append(ZonaEstribo(
            x_ini=a, x_fim=b, phi=phi_mm, s=s, n_ramos=n_ramos, asw_req=req,
            asw_ef=asw_efetiva(phi_mm, s, n_ramos), n_estribos=n_est,
            tramo=tramo, trecho=trecho))

    # funde trechos vizinhos com o mesmo espaçamento
    fundidas: list[ZonaEstribo] = []
    for z in zonas:
        if fundidas and abs(fundidas[-1].s - z.s) < 1e-9 and \
                fundidas[-1].phi == z.phi:
            ant = fundidas[-1]
            ant.x_fim = z.x_fim
            ant.asw_req = max(ant.asw_req, z.asw_req)
            ant.n_estribos = max(2, int(math.ceil(
                (ant.x_fim - ant.x_ini) * 100.0 / ant.s)) + 1)
        else:
            fundidas.append(z)
    return fundidas


#: quanto dois espaçamentos podem diferir e ainda serem "a mesma distribuição".
#: 15 % é menos de um passo da grade comercial na faixa usual (c/13 a c/16), e
#: uma faixa a mais no desenho por 1 cm de espaçamento não se paga
TOLERANCIA_FUSAO_FAIXA = 1.15


def fundir_faixas_proximas(zonas: list[ZonaEstribo],
                           secao_do_trecho=None) -> list[ZonaEstribo]:
    """Junta faixas vizinhas que são a mesma peça com o mesmo espaçamento.

    Duas razões produzem faixas que não deveriam existir:

    * o escalonamento divide o tramo em três e adota, em cada pedaço, o
      espaçamento do ponto mais solicitado dele. Onde o cortante é quase
      constante isso dá ``c/16`` e ``c/15`` lado a lado -- duas faixas, duas
      cotas, e para quem monta a mesma coisa;
    * as faixas nascem **por trecho**, e a divisa entre dois trechos de seção
      igual não é divisa de nada: numa viga prismática o fim do vão 2 e o
      começo do vão 3 saíam como duas faixas de ``c/16``, uma "faixa adicional"
      no meio da viga sem razão nenhuma.

    Junta-se o que é a **mesma peça** -- mesma bitola, mesmos ramos, mesma
    seção -- e vizinho, adotando o espaçamento **mais apertado**, que é o lado
    seguro. ``secao_do_trecho`` mapeia o índice do trecho na seção dele; sem
    ele a comparação cai no índice, e aí a divisa de trechos volta a valer.
    """
    def mesma_secao(a: ZonaEstribo, b: ZonaEstribo) -> bool:
        if a.trecho == b.trecho:
            return True
        if secao_do_trecho is None:
            return False
        return secao_do_trecho(a.trecho) == secao_do_trecho(b.trecho)

    saida: list[ZonaEstribo] = []
    for z in zonas:
        if saida:
            a = saida[-1]
            mesma_peca = (abs(a.phi - z.phi) < 1e-9
                          and a.n_ramos == z.n_ramos and mesma_secao(a, z))
            encosta = abs(z.x_ini - a.x_fim) < 1e-6
            maior, menor = max(a.s, z.s), min(a.s, z.s)
            if (mesma_peca and encosta
                    and maior <= menor * TOLERANCIA_FUSAO_FAIXA + 1e-9):
                a.x_fim = z.x_fim
                a.s = menor
                a.asw_req = max(a.asw_req, z.asw_req)
                a.asw_ef = asw_efetiva(a.phi, a.s, a.n_ramos)
                a.n_estribos = max(
                    2, math.ceil((a.x_fim - a.x_ini) * 100.0 / a.s) + 1)
                continue
        saida.append(z)
    return saida


def uniformizar(zonas: list[ZonaEstribo]) -> list[ZonaEstribo]:
    """Uma única distribuição por tramo, a mais conservadora (18.3.3.2).

    Escalonar o estribo economiza aço e custa conferência na obra. Quando o
    projeto prefere uma distribuição só por tramo, adota-se a **mais
    conservadora** -- o menor espaçamento, com a maior bitola entre as faixas
    daquele tramo --, estendida de ponta a ponta. Nunca o contrário: o trecho
    mais exigido continua atendido.
    """
    if not zonas:
        return zonas
    saida: list[ZonaEstribo] = []
    # o agrupamento é por **trecho**, não por tramo: uma distribuição só não
    # pode atravessar mudança de seção, porque o estribo é outra peça de cada
    # lado do degrau. Num tramo prismático trecho e tramo coincidem e nada muda.
    # A fusão que roda depois volta a juntar trechos de seção igual, e é ela que
    # faz "um por trecho" virar "um por tramo" onde a seção não muda
    for trecho in sorted({z.trecho for z in zonas}):
        faixas = [z for z in zonas if z.trecho == trecho]
        tramo = faixas[0].tramo
        phi = max(z.phi for z in faixas)
        # entre as faixas da bitola que governa, a de menor espaçamento
        s = min(z.s for z in faixas if z.phi == phi)
        n_ramos = max(z.n_ramos for z in faixas)
        x_ini = min(z.x_ini for z in faixas)
        x_fim = max(z.x_fim for z in faixas)
        saida.append(ZonaEstribo(
            x_ini=x_ini, x_fim=x_fim, phi=phi, s=s, n_ramos=n_ramos,
            asw_req=max(z.asw_req for z in faixas),
            asw_ef=asw_efetiva(phi, s, n_ramos),
            n_estribos=max(2, int(math.ceil((x_fim - x_ini) * 100.0 / s)) + 1),
            tramo=tramo, trecho=trecho))
    return saida


#: tipos de posição que são armadura transversal -- peças fechadas ou em U,
#: contadas por unidade e não por comprimento de face. `saidas.geometria` tem a
#: sua própria lista para escolher a camada de desenho; esta é a do
#: detalhamento, e as duas coincidem por construção
TIPOS_TRANSVERSAIS = ("estribo", "costura", "suspensao", "grampo")


def agrupar_transversais(posicoes: list[Posicao]) -> list[Posicao]:
    """Junta numa posição só os estribos que são a **mesma peça**.

    Duas faixas de estribo com a mesma bitola, o mesmo espaçamento e o mesmo
    comprimento desenvolvido são o mesmo ferro, e numa prancha levam **um**
    número de posição, com a quantidade somada e os trechos listados. O
    programa emitia uma posição por faixa: uma viga de quatro tramos com Ø5
    c/13 em três deles saía com três tipos de estribo onde existe um.

    O que **não** se junta: peça de comprimento diferente (seção diferente),
    espaçamento diferente (é outra distribuição) ou papel diferente -- o
    grampo de ancoragem e a costura da emenda não se confundem com o estribo
    do vão, mesmo quando calham de ter a mesma geometria, porque quem monta
    precisa saber onde cada um vai e por quê.

    A ordem das posições é preservada: a primeira ocorrência fica no lugar dela
    e as seguintes desaparecem, somadas a ela.
    """
    saida: list[Posicao] = []
    indice: dict[tuple, Posicao] = {}
    for p in posicoes:
        if p.tipo not in TIPOS_TRANSVERSAIS:
            saida.append(p)
            continue
        # a chave é a **peça**, e o espaçamento não entra nela: um estribo
        # Ø5 de 136 cm é o mesmo ferro se vai c/16 num trecho e c/10 noutro.
        # Com o espaçamento na chave, o mesmo ferro saía como três posições --
        # e é exatamente o que a prancha não faz: a posição identifica o ferro,
        # a distribuição é locação e vai na elevação
        chave = (p.tipo, round(p.phi, 3), round(p.comprimento, 1),
                 p.n_ramos_efetivo, p.papel, p.espelhado)
        igual = indice.get(chave)
        if igual is None:
            indice[chave] = p
            p.faixas = [(p.x_ini, p.x_fim, p.s, p.n)]
            saida.append(p)
            continue
        igual.n += p.n
        igual.faixas.append((p.x_ini, p.x_fim, p.s, p.n))
        igual.x_ini = min(igual.x_ini, p.x_ini)
        igual.x_fim = max(igual.x_fim, p.x_fim)
    for p in saida:
        if not p.faixas:
            continue
        p.faixas = _unir_contiguas(p.faixas)
        # o espaçamento da posição só faz sentido quando é um só; misturado,
        # ele fica zero e quem quiser saber lê as faixas ou a elevação
        esp = {round(s, 2) for _a, _b, s, _n in p.faixas}
        p.s = p.faixas[0][2] if len(esp) == 1 else 0.0
    return saida


def _unir_contiguas(faixas: list[tuple[float, float, float, int]]
                   ) -> list[tuple[float, float, float, int]]:
    """Junta trechos que se encostam **com o mesmo espaçamento**.

    Dois tramos vizinhos com a mesma distribuição davam dois trechos, e quem lê
    a prancha não tem por que saber onde o programa colocou a divisa dos
    tramos: o estribo corre de 7,30 a 12,70 e é isso que interessa. Trechos que
    se encostam com espaçamentos **diferentes** continuam separados -- ali a
    divisa é real, e é onde o montador troca o passo.
    """
    saida: list[tuple[float, float, float, int]] = []
    for a, b, s, n in sorted(faixas):
        if (saida and a - saida[-1][1] < 1e-6
                and abs(s - saida[-1][2]) < 1e-9):
            saida[-1] = (saida[-1][0], max(saida[-1][1], b), s,
                         saida[-1][3] + n)
        else:
            saida.append((a, b, s, n))
    return saida


def renumerar(posicoes: list[Posicao]) -> None:
    """Renumera as posições de 1 a N, na ordem da lista.

    Depois de agrupar sobram buracos na numeração, e buraco em lista de aço é
    dúvida na obra ("onde está a N16?"). Renumerar aqui é seguro porque nada
    guarda posição por número: a bitola imposta é por região e por tramo, o
    gancho escolhido é por nome de região.
    """
    for i, p in enumerate(posicoes, start=1):
        p.numero = i


def escolher_estribo(asw_max: float, s_max: float, bw: float, n_ramos: int,
                     phi_preferido: float = 5.0) -> float:
    """Escolhe a bitola do estribo que atende à armadura máxima do tramo."""
    phi_lim = bw          # bw em cm equivale a bw/10 em mm (18.3.3.2)
    for phi in BITOLAS_ESTRIBOS:
        if phi < phi_preferido or phi > phi_lim:
            continue
        s = n_ramos * area_barra(phi) / max(asw_max, 1e-6) * 100.0
        if s >= 5.0:
            return phi
    return min(max(BITOLAS_ESTRIBOS[0], phi_preferido), phi_lim)


# ---------------------------------------------------------------------------
# Posições (itens de armadura para desenho e quantitativo)
# ---------------------------------------------------------------------------

@dataclass
class Posicao:
    """Um item de armadura do detalhamento (uma 'posição' da ferragem)."""

    numero: int
    tipo: str                 # 'longitudinal', 'estribo', 'pele', 'porta'
    n: int
    phi: float                # mm
    face: str                 # 'inferior', 'superior', 'alma'
    x_ini: float              # m
    x_fim: float              # m
    comprimento: float        # cm, comprimento total de uma barra
    dobra_ini: float = 0.0    # cm, perna vertical na extremidade esquerda
    dobra_fim: float = 0.0    # cm
    camada: int = 1
    s: float = 0.0            # cm, espaçamento (estribos e pele)
    descricao: str = ""
    tramo: int = 0
    n_pecas: int = 1          # peças comerciais emendadas por traspasse
    comprimento_peca: float = 0.0   # cm, comprimento de cada peça
    traspasse: float = 0.0    # cm, l0t consumido em cada emenda
    #: início de cada traspasse, cm medidos da extremidade esquerda da barra
    emendas_x: list[float] = field(default_factory=list)
    #: comprimento de cada peça, cm (as peças não precisam ser iguais)
    pecas: list[float] = field(default_factory=list)
    #: armadura de compressão: emenda pelo l0c do item 9.5.2.3, não pelo l0t
    comprimida: bool = False
    #: faixa de altura que a posição ocupa na alma, cm da face inferior
    #: (só a armadura de pele usa; (0, 0) = distribuir na alma toda)
    faixa_altura: tuple[float, float] = (0.0, 0.0)
    #: número de faces em que a posição se repete, quando a armadura é uma só
    #: distribuída simetricamente -- é o caso da pele, que é **um** N com
    #: ``n_por_face`` barras em cada uma das duas faces. Zero significa "não se
    #: aplica", e a quantidade sai como o número simples
    n_faces: int = 0
    #: para que serve este grampo: "ancoragem" quando ele assume parcela de
    #: Rsd atravessando as pernas dos ganchos, "costura" quando é a armadura
    #: transversal do item 9.4.2.6 ao longo da ancoragem. São desenhados em
    #: alturas diferentes porque abraçam coisas diferentes
    papel: str = ""
    #: o U abre para a face do apoio: no apoio da direita ele é o espelho do
    #: da esquerda, e desenhar os dois iguais punha a dobra do lado errado
    espelhado: bool = False
    #: armadura longitudinal de torção que esta barra leva, cm² (17.5.1.6):
    #: a barra lateral de torção e o porta-estribo de uma face sem momento que
    #: recebeu a parcela da face. É por ela que a ancoragem da barra nos apoios
    #: de extremidade é verificada
    As_torcao: float = 0.0
    #: raio de dobramento no eixo da barra, cm, quando não é o da Tabela 9.1:
    #: a negativa que desce no engaste dobra num nó de pórtico, e o 18.2.2
    #: pede ali um pino maior que o do gancho. Zero = o da Tabela 9.1
    raio_dobra: float = 0.0
    #: ramos do estribo, para o agrupamento não juntar um estribo de 2 ramos
    #: com um de 4 que calhe de ter o mesmo comprimento desenvolvido
    n_ramos_efetivo: int = 0
    #: onde esta posição vai: ``[(x_ini, x_fim, espaçamento, quantidade)]``,
    #: em m, cm e peças. Só a armadura transversal usa. Uma posição é **um
    #: ferro**, e o mesmo ferro pode ir em vários trechos, com espaçamentos e
    #: quantidades diferentes. A quantidade por faixa é dado, não conta a
    #: refazer: numa costura de emenda ela é o número de estribos **extra**, e
    #: recalculá-la a partir do trecho e do passo desenharia também os que já
    #: existem. Vazio significa "o trecho é ``x_ini`` a ``x_fim``, com
    #: :attr:`s` e :attr:`n`"
    faixas: list[tuple[float, float, float, int]] = field(
        default_factory=list)
    #: a barra existe **só para fechar o canto do estribo** -- porta-estribo
    #: ou armadura de uma região sem momento de tração naquela face. Não
    #: carrega força calculada, então a bitola dela pode ser elevada para
    #: atender ao item 18.3.3.2 quando o estribo engrossa; uma barra de flexão
    #: dimensionada, não
    so_canto: bool = False
    #: trecho prismático em que esta posição está, ou -1 para "deduza".
    #: Existe porque numa barra que morre numa junta o meio da barra não
    #: decide: a armadura negativa de um apoio pertence ao nível de um dos
    #: dois lados, e é o cálculo que sabe qual. Onde o cálculo sabe, ele
    #: grava; onde não há ambiguidade, :func:`alinhamento.trecho_da` deduz
    trecho: int = -1
    #: perna do grampo, cm: o lb1 medido da face do apoio à ponta. O
    #: ``comprimento`` do grampo é ``2 . perna + vão entre as pernas``, e sem
    #: guardar a perna o desenho não sabe separar uma coisa da outra
    perna: float = 0.0
    #: tipo de gancho desta barra (9.4.2.3), como resolvido pelo critério
    #: geral e pela escolha da região. Viaja na posição de propósito: o
    #: desenho lê daqui em vez de re-derivar, e assim não há como desenhar um
    #: gancho de 90° numa barra dimensionada com gancho semicircular
    tipo_gancho: str = ""
    #: x, m, onde a barra ancora contra uma junta de tramos desalinhados:
    #: ali ela não pode ser prolongada, porque adiante não existe concreto
    #: naquela face. ``None`` = livre para alongar
    trava_ini: float | None = None
    trava_fim: float | None = None
    #: x, m, onde a barra ancora contra uma junta de tramos desalinhados:
    #: ali ela não pode ser prolongada, porque adiante não existe concreto
    #: naquela face. ``None`` = livre para alongar
    trava_ini: float | None = None
    trava_fim: float | None = None
    #: traspasses com a posição seguinte da mesma face:
    #: (início em cm desde a extremidade esquerda, l0t em cm, nº da vizinha)
    emendas_vizinhas: list[tuple[float, float, int]] = field(
        default_factory=list)

    @property
    def comprimento_total(self) -> float:
        """Comprimento total de aço da posição, m (já com as emendas)."""
        if self.pecas:
            return self.n * sum(self.pecas) / 100.0
        if self.n_pecas > 1:
            return self.n * self.n_pecas * self.comprimento_peca / 100.0
        return self.n * self.comprimento / 100.0

    @property
    def emendada(self) -> bool:
        return self.n_pecas > 1

    @property
    def massa(self) -> float:
        """Massa da posição, kg."""
        return self.comprimento_total * massa_linear(self.phi)

    def raio_da_dobra(self, aco) -> float:
        """Raio de dobramento no eixo, cm: o próprio ou o da Tabela 9.1."""
        return self.raio_dobra or aco.raio_dobramento_eixo(self.phi)

    @property
    def texto_quantidade(self) -> str:
        """Quantidade como se escreve na prancha.

        Numa armadura distribuída em faces -- a pele -- o que interessa a quem
        monta é **quantas barras por face**, e é assim que a prancha escreve:
        ``4 x 2`` são 4 por face nas duas faces, 8 barras. O total continua em
        :attr:`n`, e é dele que sai a massa; este texto é só a leitura.

        Fonte única: todo rótulo, tabela e legenda passa por aqui. Escrever o
        ``n`` cru num lugar e o par no outro faria a prancha dizer 8 onde a
        lista de aço diz 4 x 2.
        """
        if self.n_faces > 1 and self.n % self.n_faces == 0:
            return f"{self.n // self.n_faces} x {self.n_faces}"
        return str(self.n)

    @property
    def rotulo(self) -> str:
        base = f"N{self.numero} - {self.texto_quantidade} phi {self.phi:g}"
        if self.s:
            base += f" c/{self.s:g}"
        return f"{base} C={self.comprimento:.0f}"


# ---------------------------------------------------------------------------
# Escalonamento da armadura longitudinal
# ---------------------------------------------------------------------------

@dataclass
class CorteBarra:
    """Ponto de corte de uma barra do escalonamento."""

    ordem: int                # 1 = barra que vai até o apoio/extremo
    x_ini: float              # m, início da barra
    x_fim: float              # m, fim da barra
    As_acumulada: float       # cm² garantidos por esta barra e as anteriores
    lb_nec: float             # cm de ancoragem somado em cada ponta


def escalonar(x: np.ndarray, As_req: np.ndarray, arranjo: Arranjo,
              al_cm: float, lb_nec_cm: float, x_ini: float, x_fim: float,
              x_min_barra: float, x_max_barra: float,
              manter_ate_apoio: int = 2) -> list[CorteBarra]:
    """Determina onde cada barra do arranjo pode ser interrompida.

    O diagrama de área de aço necessária é decalado de ``al`` para os dois
    lados (17.4.2.2) e cada barra é prolongada de ``lb,nec`` além da seção em
    que deixa de ser necessária -- o que já cobre o mínimo de 10 Ø além do
    ponto de tensão nula do item 18.3.2.3.1, porque ``lb,nec >= lb,min >=
    10 Ø``.

    As barras são interrompidas **aos pares**, uma de cada lado do eixo: a
    armadura de uma face é simétrica, e cortar uma barra sozinha desmancha a
    simetria da seção. Cada par recebe o comprimento da sua barra **mais
    interna** -- a que é exigida no trecho maior --, o que é o lado seguro.

    A barra que só existe pela armadura mínima (o cálculo não a exige em
    seção nenhuma) vai até onde a face ainda tem As_req > 0, decalado de aℓ,
    mais ℓb,nec; as ``manter_ate_apoio`` primeiras correm a região inteira.
    """
    mask = (x >= x_ini - 1e-9) & (x <= x_fim + 1e-9)
    xs, As = x[mask], As_req[mask]
    if xs.size == 0:
        return []
    al_m = al_cm / 100.0
    lb_m = lb_nec_cm / 100.0

    # decalagem: em cada seção vale a maior exigência entre x - al e x + al
    As_dec = np.maximum(np.interp(xs - al_m, xs, As, left=As[0], right=As[-1]),
                        np.interp(xs + al_m, xs, As, left=As[0], right=As[-1]))

    A1 = area_barra(arranjo.phi)
    cortes: list[CorteBarra] = []
    n = arranjo.n
    for k in range(n, 0, -1):
        # índice da barra mais interna do par a que esta pertence: os pares se
        # formam de fora para dentro, (n, n-1), (n-2, n-3), ...
        k_par = k if (n - k) % 2 == 1 else max(k - 1, 1)
        # a k-ésima barra é necessária onde As_dec > (k-1) * A1
        limite = (k_par - 1) * A1
        necessarias = As_dec > limite + 1e-9
        if not necessarias.any() and k > manter_ate_apoio:
            # barra que só existe pela armadura mínima (17.3.5.2.1): não é
            # exigida pelo cálculo em seção nenhuma, mas também não precisa
            # ir além de onde a face tem momento -- vai até onde As_req
            # daquela face (já decalado de aℓ) é maior que zero, mais ℓb,nec,
            # como as calculadas. Sem momento algum na face, a região toda.
            necessarias = As_dec > 1e-9
        if k <= manter_ate_apoio or not necessarias.any():
            a, b = x_min_barra, x_max_barra
        else:
            idx = np.where(necessarias)[0]
            a = float(xs[idx[0]]) - lb_m
            b = float(xs[idx[-1]]) + lb_m
            a = max(a, x_min_barra)
            b = min(b, x_max_barra)
        cortes.append(CorteBarra(ordem=k, x_ini=a, x_fim=b,
                                 As_acumulada=k * A1, lb_nec=lb_nec_cm))
    cortes.reverse()
    return cortes


def agrupar_cortes(cortes: list[CorteBarra], tolerancia: float = 0.25
                   ) -> list[tuple[int, float, float]]:
    """Agrupa barras com comprimentos próximos em (n_barras, x_ini, x_fim)."""
    grupos: list[list[CorteBarra]] = []
    for c in sorted(cortes, key=lambda c: (c.x_ini, c.x_fim)):
        if grupos and abs(grupos[-1][-1].x_ini - c.x_ini) <= tolerancia and \
                abs(grupos[-1][-1].x_fim - c.x_fim) <= tolerancia:
            grupos[-1].append(c)
        else:
            grupos.append([c])
    saida = []
    for g in grupos:
        saida.append((len(g), min(c.x_ini for c in g),
                      max(c.x_fim for c in g)))
    return saida
