# -*- coding: utf-8 -*-
"""
geometria.py
Converte o detalhamento calculado em geometria de desenho -- polilinhas,
círculos e textos -- usada tanto pelo croqui em matplotlib quanto pela
exportação em DXF.

Todas as coordenadas são dadas em centímetros: ``x`` ao longo da viga, com a
origem no eixo do primeiro apoio, e ``y`` medido a partir da face inferior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..core.detalhamento import TIPOS_TRANSVERSAIS, Posicao
from ..core import alinhamento as al
from ..core import ganchos as gk
from ..core.dimensionar import ResultadoViga
from ..core.modelo import Secao, Viga


@dataclass
class Polilinha:
    """Sequência de pontos com um papel no desenho."""

    pontos: list[tuple[float, float]]
    camada: str = "ARMADURA"
    fechada: bool = False


@dataclass
class Circulo:
    centro: tuple[float, float]
    raio: float
    camada: str = "BARRA"


@dataclass
class Texto:
    texto: str
    posicao: tuple[float, float]
    altura: float = 6.0
    camada: str = "TEXTO"
    ancora: str = "left"
    rotacao: float = 0.0
    #: (x, y) do ponto da barra a que este rótulo se refere. Quem desenha traça
    #: a linha de chamada até a posição final do texto -- que o croqui pode
    #: deslocar, depois de medir a largura real da fonte.
    chamada: tuple[float, float] | None = None


@dataclass
class Elevacao:
    """Geometria da elevação da viga."""

    contorno: list[Polilinha] = field(default_factory=list)
    apoios: list[Polilinha] = field(default_factory=list)
    barras: list[Polilinha] = field(default_factory=list)
    estribos: list[Polilinha] = field(default_factory=list)
    textos: list[Texto] = field(default_factory=list)
    cotas: list[tuple] = field(default_factory=list)
    #: linhas verticais que marcam o limite de cada faixa de estribos
    zonas: list[Polilinha] = field(default_factory=list)
    #: (x_ini, x_fim, y, rótulo) da cota de cada faixa de estribos
    cotas_estribo: list[tuple[float, float, float, str]] = field(
        default_factory=list)
    #: (x em cm, rótulo) de cada eixo de apoio -- a linha de chamada que amarra
    #: a elevação à vista explodida
    eixos: list[tuple[float, str]] = field(default_factory=list)
    x_min: float = 0.0
    x_max: float = 0.0
    h_max: float = 0.0
    #: menor ordenada ocupada pela elevação (rótulos e cotas), cm
    y_min: float = 0.0


@dataclass
class BarraExplodida:
    """Uma posição de armadura desenhada isolada, com as cotas dos trechos."""

    posicao: Posicao
    pontos: list[tuple[float, float]]      # normalizados, origem no canto
    largura: float
    altura: float
    fechada: bool
    camada: str
    rotulo: str
    #: (p0, p1, comprimento) de cada trecho reto, para cotar no desenho
    segmentos: list[tuple[tuple[float, float], tuple[float, float], float]]
    #: (p0, p1, l0t, rótulo) de cada traspasse: p0..p1 é a sobreposição
    emendas: list[tuple[tuple[float, float], tuple[float, float], float, str]]
    #: abscissa real, cm, em que a barra começa na viga -- é ela que alinha a
    #: vista explodida com a elevação
    x_real: float = 0.0
    #: cota de locação: (x do eixo de referência, rótulo, distância em cm)
    referencia: tuple[float, str, float] | None = None
    #: cotas de raio das dobras: (centro do arco, ponto sobre o arco, raio cm).
    #: Só a armadura longitudinal recebe: no estribo a dobra é a de sempre e
    #: cotar as quatro entulharia o desenho sem informar nada
    raios: list[tuple[tuple[float, float], tuple[float, float], float]] = \
        field(default_factory=list)


@dataclass
class SecaoTransversal:
    """Geometria de uma seção transversal cotada."""

    x: float                              # cm, posição na viga
    nome: str
    contorno: Polilinha
    estribo: Polilinha
    barras: list[Circulo] = field(default_factory=list)
    textos: list[Texto] = field(default_factory=list)
    largura: float = 0.0
    altura: float = 0.0


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _y_barra(secao: Secao, cob: float, phi_estribo: float, phi: float,
             camada: int, face: str, d_agregado: float = 1.9) -> float:
    """Ordenada do eixo de uma barra, cm a partir da face inferior."""
    phi_cm = phi / 10.0
    av = max(2.0, phi_cm, 0.5 * d_agregado)
    y0 = cob + phi_estribo / 10.0 + phi_cm / 2.0
    y = y0 + (camada - 1) * (phi_cm + av)
    return y if face == "inferior" else secao.h - y


#: segmentos com que um quarto de círculo é aproximado no desenho. Oito dão
#: erro de flecha abaixo de 0,2 % do raio, invisível em qualquer escala de
#: prancha, e saem como polilinha simples em matplotlib e em DXF
SEGMENTOS_ARCO = 8


def arco_dobra(x: float, y: float, raio: float, sx: float, sy: float,
               segmentos: int = SEGMENTOS_ARCO
               ) -> list[tuple[float, float]]:
    """Eixo da barra ao longo de uma dobra de 90°, do trecho reto para a perna.

    ``(x, y)`` é o vértice teórico -- onde as duas retas se cruzariam se a
    barra dobrasse em canto vivo. ``sx`` é o sentido em que segue o trecho reto
    a partir do vértice (+1 para a direita) e ``sy`` o sentido da perna (+1
    para cima). Devolve os pontos do ponto de tangência na reta até o ponto de
    tangência na perna.

    Armadura não dobra em ângulo vivo: o pino da Tabela 9.1 tem diâmetro de
    5 Ø a 8 Ø, o que numa Ø20 dá 9 cm de raio no eixo. Desenhar isso como canto
    reto esconde justamente a parte da dobra que consome altura de seção.
    """
    cx, cy = x + sx * raio, y + sy * raio
    return [(cx - sx * raio * math.sin(t), cy - sy * raio * math.cos(t))
            for t in ((k / segmentos) * (math.pi / 2.0)
                      for k in range(segmentos + 1))]


def centros_das_dobras(x0: float, x1: float, y: float, dobra_ini: float,
                       dobra_fim: float, sinal: float, raio: float,
                       phi_mm: float, tipo: str
                       ) -> list[tuple[tuple[float, float],
                                       tuple[float, float]]]:
    """Centro de cada dobra e um ponto sobre o arco, para a cota de raio.

    O ponto escolhido é o do meio do arco: é onde a seta da cota encosta sem
    tocar nenhum dos dois trechos retos.
    """
    if not phi_mm or gk.normalizar(tipo) == gk.SEM_GANCHO:
        return []
    saida = []
    for x_vertice, sx, dobra in ((x0, 1.0, dobra_ini), (x1, -1.0, dobra_fim)):
        if dobra <= 1e-9 or dobra < gk.altura(raio, phi_mm, tipo) - 1e-6:
            continue
        centro = (x_vertice + sx * raio, y + sinal * raio)
        ponta = gk.ponta_para_altura(raio, phi_mm, tipo, dobra)
        arco = gk.pontos(raio, phi_mm, tipo, sx, sinal, ponta=ponta)
        meio = arco[len(arco) // 2]
        saida.append((centro, (x_vertice + meio[0], y + meio[1])))
    return saida


def barra_com_dobras(x0: float, x1: float, y: float, dobra_ini: float,
                     dobra_fim: float, sinal: float, raio: float,
                     phi_mm: float = 0.0, tipo: str = gk.PADRAO
                     ) -> list[tuple[float, float]]:
    """Polilinha do eixo de uma barra longitudinal, com os ganchos do tipo.

    A forma do gancho vem de :mod:`vigas.core.ganchos`, a mesma fonte de onde o
    cálculo tira a altura -- é isso que impede o desenho de mostrar um gancho
    diferente do que foi dimensionado.

    Quando a perna adotada não chega à altura que o tipo pede, a dobra sai em
    canto vivo: é o caso que a conferência do 9.4.2.3 já reprovou, e o desenho
    o mostra como está em vez de esconder.
    """
    def gancho(x_vertice: float, sx: float,
               dobra: float) -> list[tuple[float, float]]:
        # a ponta reta é a que a perna adotada exige -- a mesma regra do
        # cálculo. Sem isso o desenho traçava a ponta mínima do tipo e o
        # gancho saía mais baixo do que a perna dimensionada
        ponta = gk.ponta_para_altura(raio, phi_mm, tipo, dobra)
        return [(x_vertice + dx, y + dy)
                for dx, dy in gk.pontos(raio, phi_mm, tipo, sx, sinal,
                                        ponta=ponta)]

    altura_tipo = gk.altura(raio, phi_mm, tipo) if phi_mm else 0.0
    pontos: list[tuple[float, float]] = []
    if dobra_ini > 1e-9:
        if phi_mm and dobra_ini >= altura_tipo - 1e-6:
            pontos += gancho(x0, 1.0, dobra_ini)[::-1]
        else:
            pontos += [(x0, y + sinal * dobra_ini), (x0, y)]
    else:
        pontos.append((x0, y))
    if dobra_fim > 1e-9:
        if phi_mm and dobra_fim >= altura_tipo - 1e-6:
            pontos += gancho(x1, -1.0, dobra_fim)
        else:
            pontos += [(x1, y), (x1, y + sinal * dobra_fim)]
    else:
        pontos.append((x1, y))
    return pontos


#: pernas de um grampo -- espelha ``vigas.core.grampos.PERNAS`` sem criar
#: dependência do desenho no cálculo
gr_PERNAS = 2


def grampo_em_u(perna: float, vao: float, raio: float,
                espelhado: bool = False) -> list[tuple[float, float]]:
    """Polilinha de um grampo: duas pernas de ``perna`` fechadas por ``vao``.

    A dobra que fecha o U é semicircular, no pino do estribo, e fica na
    **extremidade da viga**: a abertura aponta para dentro do vão. O grampo
    abraça as pernas das barras por fora, como um estribo horizontal, e é nele
    que o cobrimento é medido -- por isso ele é o elemento mais externo da
    ponta, e as barras recuam uma bitola de grampo para dar lugar a ele.

    Em coordenadas locais a dobra fica em ``x = 0`` e a abertura em
    ``x = perna``. No apoio da direita a peça é o espelho da do esquerdo, e
    ``espelhado`` faz a troca; desenhar as duas iguais punha a dobra virada
    para o meio do vão em uma delas.
    """
    r = max(min(raio, vao / 2.0), 0.0)
    if r <= 1e-9:
        pontos = [(perna, 0.0), (0.0, 0.0), (0.0, vao), (perna, vao)]
    else:
        pontos = [(perna, 0.0)]
        # dobra no canto (0, 0) subindo, e no canto (0, vao) voltando
        pontos += arco_dobra(0.0, 0.0, r, 1.0, 1.0)
        pontos += arco_dobra(0.0, vao, r, 1.0, -1.0)[::-1]
        pontos.append((perna, vao))
    if espelhado:
        pontos = [(perna - x, y) for x, y in pontos]
    return pontos


def retangulo_arredondado(largura: float, altura: float, raio: float,
                          gancho: float = 0.0
                          ) -> list[tuple[float, float]]:
    """Estribo fechado com os quatro cantos dobrados no pino da Tabela 9.2.

    Percorrido no sentido anti-horário a partir do canto inferior esquerdo. Em
    cada vértice o arco é gerado no sentido reta -> perna e invertido quando o
    percurso chega por ela, o que mantém a polilinha contínua.
    """
    r = max(min(raio, largura / 2.0, altura / 2.0), 0.0)
    if r <= 1e-9:
        base = [(0.0, 0.0), (largura, 0.0), (largura, altura), (0.0, altura),
                (0.0, 0.0)]
        return base + [(gancho, 0.0)] if gancho > 0.0 else base
    #    vértice              sx    sy   inverter?
    CANTOS = (((0.0, 0.0), 1.0, 1.0, True),
              ((largura, 0.0), -1.0, 1.0, False),
              ((largura, altura), -1.0, -1.0, True),
              ((0.0, altura), 1.0, -1.0, False))
    pontos: list[tuple[float, float]] = []
    for (x, y), sx, sy, inverter in CANTOS:
        arco = arco_dobra(x, y, r, sx, sy)
        pontos += arco[::-1] if inverter else arco
    pontos.append(pontos[0])
    if gancho > 0.0:
        # ponta do gancho do estribo, ao longo da base a partir do canto
        pontos.append((max(gancho, r), 0.0))
    return pontos


#: tipos de posição que são estribo, e por isso se desenham fechados
#: os tipos de armadura transversal vêm do detalhamento: duas listas
#: iguais em dois módulos divergem na primeira peça nova
TIPOS_ESTRIBO = TIPOS_TRANSVERSAIS


def camada_barra(face: str, tipo: str = "") -> str:
    """Camada de desenho de uma posição, pela face que ocupa.

    A costura da emenda e da ancoragem é estribo suplementar: vai para a
    camada dos estribos, não para a da armadura de pele, embora ocupe a alma.
    """
    if tipo in TIPOS_ESTRIBO:
        return "ESTRIBO"
    if face == "superior":
        return "ARMADURA_SUP"
    if face == "inferior":
        return "ARMADURA_INF"
    return "PELE"


def _contorno_secao(secao: Secao) -> list[tuple[float, float]]:
    """Polígono da seção transversal, com origem no canto inferior esquerdo."""
    b, h, bf, hf = secao.bw, secao.h, secao.bf, secao.hf
    if secao.tipo == "retangular":
        return [(0, 0), (b, 0), (b, h), (0, h)]
    e = (bf - b) / 2.0
    if secao.tipo == "T":
        return [(0, 0), (b, 0), (b, h - hf), (b + e, h - hf), (b + e, h),
                (-e, h), (-e, h - hf), (0, h - hf)]
    return [(-e, 0), (b + e, 0), (b + e, hf), (b, hf), (b, h), (0, h),
            (0, hf), (-e, hf)]


# ---------------------------------------------------------------------------
# Elevação
# ---------------------------------------------------------------------------

def _parte_reta_do_gancho(res: ResultadoViga, x0: float, x1: float,
                          cob: float, base: float) -> tuple[float, float]:
    """Faixa de altura da **parte reta** do gancho que o grampo atravessa, cm.

    O grampo abraça a ponta reta do gancho -- não a dobra, onde a barra está
    curva e não haveria como encostar. A faixa vai do fim do arco (``y da barra
    + raio no eixo``) até a ponta (``y da barra + perna``). Devolve ``(0, 0)``
    quando não há gancho ali.
    """
    viga = res.viga
    cfg = viga.config
    perto_do_inicio = abs(x0 - viga.x_inicio_fisico * 100.0) < 80.0
    alvo = None
    for p in res.posicoes:
        if p.tipo not in ("longitudinal", "porta") or p.face != "inferior":
            continue
        dobra = p.dobra_ini if perto_do_inicio else p.dobra_fim
        if dobra <= 1e-9:
            continue
        extremo = (p.x_ini if perto_do_inicio else p.x_fim) * 100.0
        if abs(extremo - (x0 if perto_do_inicio else x1)) > 80.0:
            continue
        if alvo is None or dobra > (alvo.dobra_ini if perto_do_inicio
                                    else alvo.dobra_fim):
            alvo = p
    if alvo is None:
        return 0.0, 0.0
    secao = al.secao_da(viga, alvo)
    y = base + _y_barra(secao, cob, cfg.phi_estribo, alvo.phi, alvo.camada,
                        "inferior", cfg.d_agregado)
    dobra = alvo.dobra_ini if perto_do_inicio else alvo.dobra_fim
    raio = viga.aco.raio_dobramento_eixo(alvo.phi)
    return y + min(raio, dobra), y + dobra


#: largura estimada de um caractere da cota de estribos, cm de desenho. A cota
#: tem tamanho de fonte fixo e o desenho está em centímetros; este número é
#: calibrado pelo rastreio de sobreposição, que mede o texto renderizado
LARGURA_CARACTERE_COTA = 12.0

#: passo entre níveis de cota de estribo, cm
PASSO_COTA_ESTRIBO = 20.0


def _escalonar_cotas(cotas: list[tuple[float, float, float, str]],
                     h_max: float
                     ) -> list[tuple[float, float, float, str]]:
    """Põe cada cota no primeiro nível em que o texto dela não encosta noutro.

    O texto da cota é mais largo que o trecho que ela mede sempre que o trecho é
    curto: dois terços de traspasse de 40 cm, 40 cm um do outro, têm rótulos de
    quase 3 m de desenho. Alinhá-los todos no mesmo nível os fazia colidir --
    mesma solução dos rótulos das barras e das cotas da vista explodida, que já
    escolhem o primeiro nível livre.
    """
    postos: list[tuple[float, float, float]] = []
    saida: list[tuple[float, float, float, str]] = []
    for xa, xb, y, texto in sorted(cotas, key=lambda c: (c[2], c[0])):
        meia = LARGURA_CARACTERE_COTA * len(texto) / 2.0
        centro = (xa + xb) / 2.0
        caixa = (min(xa, centro - meia), max(xb, centro + meia))
        nivel = 0
        while any(abs(yq - (y + PASSO_COTA_ESTRIBO * nivel)) < 1e-6
                  and caixa[0] < bq and aq < caixa[1]
                  for aq, bq, yq in postos):
            nivel += 1
        y_final = y + PASSO_COTA_ESTRIBO * nivel
        postos.append((caixa[0], caixa[1], y_final))
        saida.append((xa, xb, y_final, texto))
    del h_max
    return saida


def _posicao_da_faixa(res: ResultadoViga, zona) -> str:
    """``"N7 "`` da posição que desenha aquela faixa de estribos, ou ``""``.

    A ligação existe porque a posição é o ferro e a faixa é a locação dele: uma
    posição pode cobrir várias faixas, com passos diferentes. Procura-se a
    posição de estribo cuja lista de faixas contenha aquele trecho com aquele
    espaçamento.
    """
    for p in res.posicoes:
        if p.tipo != "estribo":
            continue
        for a, b, esp, _q in (p.faixas or [(p.x_ini, p.x_fim, p.s, p.n)]):
            if (a - 1e-6 <= zona.x_ini and zona.x_fim <= b + 1e-6
                    and abs(esp - zona.s) < 1e-9):
                return f"N{p.numero} "
    return ""


def montar_elevacao(res: ResultadoViga, mostrar_estribos: bool = True,
                    folga_rotulo: float = 1.0) -> Elevacao:
    """Geometria da elevação com todas as posições de armadura.

    ``folga_rotulo`` multiplica a largura estimada dos rótulos ao empilhá-los.
    O DXF usa 1,0, porque lá o texto tem altura real em centímetros; o croqui
    em matplotlib desenha com fonte de tamanho fixo, que ocupa mais espaço de
    desenho, e por isso pede uma folga maior.
    """
    viga: Viga = res.viga
    cob = viga.ambiente.cobrimento_nominal
    cfg = viga.config
    el = Elevacao()
    xs = [x * 100.0 for x in viga.x_apoios]
    el.x_min = viga.x_inicio_fisico * 100.0
    el.x_max = viga.x_fim_fisico * 100.0
    # cada tramo tem a sua base: o desenho encostava todos em y = 0, o que
    # equivale a supor alinhamento pelo fundo mesmo quando o projeto declara
    # outro -- e aí o degrau da junta, que é a razão dos ganchos, não aparecia
    bases = al.bases_verticais(viga)
    trechos = viga.trechos
    el.h_max = max(b + t.secao.h for b, t in zip(bases, trechos))

    # o degrau de uma junta cai na **face** do pilar oposta ao trecho de seção
    # maior, e não no eixo: é esse trecho que se apoia na largura toda do pilar
    # da divisa. Cortar no eixo deixava meio pilar sem a viga que ele sustenta.
    # Na junta interna não há pilar, e a face é a própria abscissa da mudança
    juntas = al.juntas(viga)
    lim_ini = [t.x_ini * 100.0 for t in trechos]
    lim_fim = [t.x_fim * 100.0 for t in trechos]
    lim_ini[0] = el.x_min
    lim_fim[-1] = el.x_max
    for j in juntas:
        lim_fim[j.trecho_esq] = j.x_face * 100.0
        lim_ini[j.trecho_dir] = j.x_face * 100.0

    # contorno da viga, trecho a trecho
    for t in trechos:
        a, b = lim_ini[t.k], lim_fim[t.k]
        y0, h = bases[t.k], t.secao.h
        el.contorno.append(Polilinha(
            [(a, y0), (b, y0), (b, y0 + h), (a, y0 + h)],
            camada="CONCRETO", fechada=True))

    # pilares de apoio
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        larg = ap.largura
        x0 = xs[k] - larg / 2.0
        # o pilar tem de encostar na viga que ele sustenta: desenhá-lo sempre
        # até y = 0 deixava um vão aberto sob o tramo que o alinhamento
        # levantou, como se a viga estivesse no ar
        # os vizinhos do pilar são os **trechos** que morrem nele, não os
        # tramos: com mudança de seção interna, o trecho que chega ao pilar
        # pode não ser o que começa o tramo
        vizinhos = []
        for i in (k - 1, k):
            if not 0 <= i < len(viga.tramos):
                continue
            do_tramo = viga.trechos_do_tramo(i)
            vizinhos.append((do_tramo[-1] if i == k - 1 else do_tramo[0]).k)
        topo = min(bases[i] for i in vizinhos)
        el.apoios.append(Polilinha(
            [(x0, -30.0), (x0 + larg, -30.0), (x0 + larg, topo), (x0, topo)],
            camada="APOIO", fechada=True))
        el.textos.append(Texto(f"P{k + 1}", (xs[k], -20.0), altura=7.0,
                               camada="TEXTO", ancora="center"))
        # a seção da viga ao lado do nome do pilar: quem lê a elevação vê o
        # degrau, mas não as dimensões que o produziram
        secoes = []
        for i in vizinhos:
            d = trechos[i].secao.descricao()
            if d not in secoes:
                secoes.append(d)
        el.textos.append(Texto(" / ".join(secoes),
                               (x0 + larg + 4.0, -20.0), altura=7.0,
                               camada="TEXTO", ancora="left"))
        el.eixos.append((xs[k], f"P{k + 1}"))

    # armaduras longitudinais, com os rótulos escalonados fora da viga
    longitudinais = [p for p in res.posicoes
                     if p.tipo in ("longitudinal", "porta")]
    niveis = {"inferior": 0, "superior": 0}
    ocupacao_rotulos: dict[str, dict[int, list[tuple[float, float]]]] = {
        "inferior": {}, "superior": {}}
    def rotular(rotulo: str, face: str, x0: float, x1: float,
                y: float) -> None:
        """Põe o rótulo no primeiro nível livre e liga-o à barra.

        Alternar posições fixas não bastava em viga com muitas barras, e uma
        segunda regra para os grampos fazia os rótulos deles colidirem entre
        si. Uma fila só, por face, resolve as duas famílias.
        """
        indice = niveis[face]
        niveis[face] += 1
        fracao = (0.5, 0.3, 0.7, 0.4, 0.6, 0.2, 0.8)[indice % 7]
        xm = x0 + (x1 - x0) * fracao
        meia = (LARGURA_CARACTERE * ALTURA_ROTULO_ELEVACAO
                * folga_rotulo * len(rotulo) / 2.0)
        ocupado = ocupacao_rotulos[face]
        nivel = 0
        while any(xm - meia < fim and ini < xm + meia
                  for ini, fim in ocupado.get(nivel, ())):
            nivel += 1
        ocupado.setdefault(nivel, []).append((xm - meia, xm + meia))
        passo = ALTURA_ROTULO_ELEVACAO * 2.4
        if face == "inferior":
            # abaixo do retângulo do pilar, que desce até -30
            y_rot = -42.0 - passo * nivel
        else:
            y_rot = el.h_max + 30.0 + passo * nivel
        sentido = 1.0 if face == "inferior" else -1.0
        el.textos.append(Texto(rotulo, (xm, y_rot + sentido * -3.5),
                               altura=ALTURA_ROTULO_ELEVACAO,
                               ancora="center", chamada=(xm, y)))

    for p in sorted(longitudinais, key=lambda p: (p.face, p.x_ini)):
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        y = bases[i_trecho] + _y_barra(secao, cob, cfg.phi_estribo, p.phi,
                                      p.camada, p.face, cfg.d_agregado)
        x0, x1 = p.x_ini * 100.0, p.x_fim * 100.0
        sinal = 1.0 if p.face == "inferior" else -1.0
        pontos = barra_com_dobras(
            x0, x1, y, p.dobra_ini, p.dobra_fim, sinal,
            viga.aco.raio_dobramento_eixo(p.phi), p.phi,
            p.tipo_gancho or gk.normalizar(cfg.tipo_gancho))
        el.barras.append(Polilinha(pontos, camada=camada_barra(p.face)))

        # o rótulo é colocado no primeiro nível em que não encosta em nenhum
        # outro: alternar posições fixas não bastava em viga com muitas barras
        rotular(f"N{p.numero}  {p.texto_quantidade}Ø{p.phi:g}  "
                f"C={p.comprimento:.0f}", p.face, x0, x1, y)

    # grampos de ancoragem e de costura: em elevação o U está no plano
    # horizontal e as duas pernas se projetam sobre a mesma linha, na altura
    # das barras que ele abraça. Sai na camada do estribo, com um traço
    # vertical marcando a dobra que fecha o U, para não se confundir com a
    # barra longitudinal que corre ali
    for p in res.posicoes:
        if p.tipo != "grampo":
            continue
        i_trecho = al.trecho_da(viga, p)
        secao = trechos[i_trecho].secao
        x0, x1 = p.x_ini * 100.0, p.x_fim * 100.0
        y_barra = bases[i_trecho] + _y_barra(
            secao, cob, cfg.phi_estribo, p.phi, 1, "inferior", cfg.d_agregado)
        # o grampo **atravessa a parte reta do gancho**: é nela que ele se
        # apoia para assumir a parcela de Rsd que o trecho reto do apoio não
        # desenvolveu, e por isso as n peças se distribuem ao longo dela
        alturas = [y_barra]
        if p.papel == "ancoragem":
            y_ini, y_fim = _parte_reta_do_gancho(res, x0, x1, cob,
                                                 bases[i_trecho])
            if y_fim > y_ini + 1e-6:
                # igualmente distribuídos na parte reta; um só vai ao meio dela
                alturas = [y_ini + (k + 1) / (p.n + 1) * (y_fim - y_ini)
                           for k in range(p.n)]
        # a dobra fica na ponta **externa**, na extremidade da viga: é a
        # abertura do U que aponta para dentro do vão
        externo = x0 if abs(x0 - el.x_min) < abs(x1 - el.x_max) else x1
        for y in alturas:
            el.estribos.append(Polilinha([(x0, y), (x1, y)], camada="ESTRIBO"))
            el.estribos.append(Polilinha(
                [(externo, y - 2.0), (externo, y + 2.0)], camada="ESTRIBO"))
        rotular(f"N{p.numero}  {p.texto_quantidade}Ø{p.phi:g}  "
                f"C={p.comprimento:.0f}", "inferior", x0, x1, alturas[0])

    # estribos
    if mostrar_estribos:
        for z in res.zonas_estribo:
            n = max(2, z.n_estribos)
            x0, x1 = z.x_ini * 100.0, z.x_fim * 100.0
            passo = (x1 - x0) / max(n - 1, 1)
            for k in range(n):
                x = x0 + k * passo
                # a divisa entre duas faixas é o mesmo x para as duas, e cada
                # uma punha o seu estribo ali: dois traços sobrepostos, e um
                # estribo a mais na conta de quem lê o desenho
                if any(abs(x - q.pontos[0][0]) < 1e-6 for q in el.estribos):
                    continue
                # cada estribo é desenhado na seção **do seu próprio x**: uma
                # faixa de espaçamento pode atravessar uma mudança de seção, e
                # com a altura de um lado só metade dela sairia fora do
                # concreto. `bases` é indexado por trecho, e usar o índice do
                # tramo aqui lia a base errada assim que os dois deixaram de
                # coincidir
                i_tr = al.trecho_em(viga, x / 100.0)
                secao = trechos[i_tr].secao
                el.estribos.append(Polilinha(
                    [(x, bases[i_tr] + cob),
                     (x, bases[i_tr] + secao.h - cob)], camada="ESTRIBO"))
            # o limite da faixa precisa ser inequívoco: linha de chamada
            # atravessando a viga nas duas pontas mais a cota do trecho
            for x_limite in (x0, x1):
                el.zonas.append(Polilinha(
                    [(x_limite, -18.0), (x_limite, el.h_max + 18.0)],
                    camada="ZONA"))
            # a cota da faixa é a locação, e é aqui que ela pertence: diz
            # quantos, de qual posição, com que passo. Sem o número, quem lê a
            # elevação não sabe qual ferro do catálogo montar
            # sem a bitola: ela está no catálogo, ao lado do número da
            # posição, e repeti-la aqui alargava o rótulo além da faixa que ele
            # mede. Uma faixa de 1,50 m com rótulo de 1,80 m era empurrada para
            # outro nível, e uma distribuição só saía cotada em três alturas
            el.cotas_estribo.append(
                (x0, x1, el.h_max + 14.0,
                 f"{n} {_posicao_da_faixa(res, z)}c/{z.s:g}"))

    # a costura da emenda e a armadura de suspensão são estribos extra, e
    # precisam ser **localizáveis**: antes apareciam no catálogo e na lista de
    # aço sem lugar nenhum no desenho. Saem como cota, e não como traço: eles
    # ficam intercalados entre os estribos que já existem naquele trecho, e na
    # escala da prancha traços a mais ali só adensam a hachura -- foi o que
    # deixou o desenho confuso quando eu os tracei
    if mostrar_estribos:
        for p in res.posicoes:
            if p.tipo not in ("costura", "suspensao", "ligacao"):
                continue
            for xa, xb, esp, quantos in (
                    p.faixas or [(p.x_ini, p.x_fim, p.s, p.n)]):
                el.cotas_estribo.append(
                    (xa * 100.0, xb * 100.0, el.h_max + 14.0,
                     f"{max(1, quantos)} N{p.numero} c/{esp:g}"))

    # duas faixas vizinhas com a mesma posição e o mesmo passo são uma cota:
    # a divisa entre elas é a divisa dos tramos, que não interessa a quem monta
    unidas: list[tuple[float, float, float, str]] = []
    for xa, xb, y, texto in el.cotas_estribo:
        resto = texto.split(" ", 1)[1] if " " in texto else texto
        juntou = False
        for i, (ax, bx, ay, atexto) in enumerate(unidas):
            aresto = atexto.split(" ", 1)[1] if " " in atexto else atexto
            # junta o que se encosta **ou se sobrepõe** dizendo a mesma coisa:
            # duas emendas próximas davam dois terços no mesmo lugar, e as duas
            # cotas caíam uma sobre a outra
            if (aresto == resto and abs(ay - y) < 1e-6
                    and xa <= bx + 1e-6 and ax <= xb + 1e-6):
                quantos = (int(atexto.split(" ", 1)[0])
                           + int(texto.split(" ", 1)[0]))
                unidas[i] = (min(ax, xa), max(bx, xb), ay,
                             f"{quantos} {resto}")
                juntou = True
                break
        if not juntou:
            unidas.append((xa, xb, y, texto))
    el.cotas_estribo = _escalonar_cotas(unidas, el.h_max)

    # cotas dos vãos, abaixo do rótulo mais baixo da face inferior
    niveis_inf = max(ocupacao_rotulos["inferior"], default=-1) + 1
    y_cotas = -42.0 - ALTURA_ROTULO_ELEVACAO * 3.2 * niveis_inf - 45.0
    for i, t in enumerate(viga.tramos):
        el.cotas.append((xs[i], xs[i + 1], y_cotas, f"{t.L:.2f}"))
    el.y_min = y_cotas - 20.0
    return el


# ---------------------------------------------------------------------------
# Seções transversais
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Vista explodida das armaduras
# ---------------------------------------------------------------------------

#: Folga horizontal entre duas barras que dividem a mesma linha, cm.
FOLGA_EXPLODIDA = 70.0

#: Espaço reservado abaixo de cada barra para o rótulo e a cota, cm.
ALTURA_ROTULO = 72.0

#: Largura mínima reservada por barra, para o rótulo não invadir a vizinha, cm.
LARGURA_MINIMA_ROTULO = 180.0

#: Altura do texto dos rótulos da elevação, cm.
ALTURA_ROTULO_ELEVACAO = 5.0

#: Largura média de um caractere, como fração da altura do texto.
LARGURA_CARACTERE = 0.62

def ordem_na_vista(barra: "BarraExplodida") -> tuple[int, int]:
    """Chave que ordena a vista explodida de cima para baixo.

    A pilha reproduz a posição das barras na seção: primeiro as superiores,
    depois a armadura de pele, depois as inferiores e, por último, os
    estribos, que envolvem tudo. Dentro de cada face, a camada mais próxima
    daquela face fica do lado de fora -- a camada 1 da armadura inferior é a
    de baixo de todas, e a camada 1 da superior é a de cima de todas.
    """
    camada = getattr(barra.posicao, "camada", 1)
    if barra.camada == "ARMADURA_SUP":
        return (0, camada)
    if barra.camada == "PELE":
        return (1, 0)
    if barra.camada == "ARMADURA_INF":
        return (2, -camada)
    return (3, 0)


def direcao_cota(barra: "BarraExplodida", a: tuple[float, float],
                 b: tuple[float, float]) -> tuple[float, float]:
    """Versor que aponta para **fora** da barra, onde a cota deve ficar.

    Num contorno fechado -- o estribo -- a normal do segmento aponta para
    dentro em metade dos lados; sem corrigir isso, as cotas caem dentro do
    estribo e se sobrepõem. Em barra aberta a cota do trecho horizontal vai
    por cima e a do gancho vai para o lado de fora.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    norma = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / norma, dx / norma
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    if barra.fechada:
        cx = sum(px for px, _ in barra.pontos) / len(barra.pontos)
        cy = sum(py for _, py in barra.pontos) / len(barra.pontos)
        if (mx - cx) * nx + (my - cy) * ny < 0.0:
            nx, ny = -nx, -ny
    elif abs(dx) >= abs(dy):            # trecho reto: cota por cima
        if ny < 0.0:
            nx, ny = -nx, -ny
    else:                                # gancho: cota para fora
        cx = (min(px for px, _ in barra.pontos)
              + max(px for px, _ in barra.pontos)) / 2.0
        if (mx - cx) * nx < 0.0:
            nx, ny = -nx, -ny
    return nx, ny


def _normalizar(pontos: list[tuple[float, float]]
                ) -> tuple[list[tuple[float, float]], float, float]:
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    x0, y0 = min(xs), min(ys)
    return ([(x - x0, y - y0) for x, y in pontos],
            max(xs) - x0, max(ys) - y0)


def _rotulo_posicao(p: Posicao, aco=None) -> str:
    """Rótulo da posição: quantidade, bitola, espaçamento e comprimento.

    O raio da dobra **não** entra aqui: ele é uma dimensão da peça e sai como
    cota de raio sobre o próprio arco, onde quem lê o desenho o procura. Como
    texto no identificador ele competia com o comprimento e não apontava para
    nada.
    """
    partes = [f"{p.texto_quantidade} N{p.numero}", f"Ø{p.phi:g}"]
    # o espaçamento não entra no identificador da peça transversal: a vista
    # explodida é catálogo de ferro -- quantidade, bitola e comprimento --, e a
    # distribuição está cotada na elevação, faixa por faixa, com o número da
    # posição. Repetir aqui obrigava a listar trecho por trecho e a leitura
    # ficava estranha justamente por isso
    if p.s and p.tipo not in TIPOS_ESTRIBO:
        partes.append(f"c/{p.s:g}")
    if p.pecas:
        partes.append("C=" + "+".join(f"{c:.0f}" for c in p.pecas)
                      + f" ({p.n_pecas} peças)")
    elif p.n_pecas > 1:
        partes.append(f"C={p.comprimento_peca:.0f} ({p.n_pecas} peças)")
    else:
        partes.append(f"C={p.comprimento:.0f}")
    return " ".join(partes)


def _forma_barra(p: Posicao, secao: Secao, cob: float,
                 gancho_estribo: bool = True, aco=None,
                 tipo: str = gk.PADRAO
                 ) -> tuple[list[tuple[float, float]], bool]:
    """Pontos da barra desdobrada e se o contorno é fechado.

    As dobras saem arredondadas no raio do pino: o da Tabela 9.1 para a
    armadura longitudinal e o da Tabela 9.2 para o estribo, que é mais
    apertado. Sem ``aco`` a forma cai no canto vivo antigo -- só para quem
    chama sem ter o material à mão.
    """
    raio_est = (aco.diametro_dobramento_estribo(p.phi) / 2.0 + p.phi / 20.0
                if aco is not None else 0.0)
    if p.tipo == "grampo":
        # o grampo é um U em planta: duas pernas ao longo da viga fechadas por
        # uma dobra na largura. Desenhá-lo como estribo fechado da seção -- que
        # é o que o tipo "estribo" faz -- dava uma peça do tamanho errado e da
        # forma errada
        perna = p.perna or (p.comprimento / gr_PERNAS)
        vao = max(p.comprimento - gr_PERNAS * perna, 2.0)
        return grampo_em_u(perna, vao, raio_est, p.espelhado), False
    if p.tipo in TIPOS_ESTRIBO:
        b = secao.bw - 2.0 * cob
        h = secao.h - 2.0 * cob
        gancho = 0.0 if not gancho_estribo else max(5.0 * p.phi / 10.0, 5.0)
        return retangulo_arredondado(b, h, raio_est, gancho), True

    comp = (p.x_fim - p.x_ini) * 100.0
    sinal = 1.0 if p.face == "inferior" else -1.0
    raio = aco.raio_dobramento_eixo(p.phi) if aco is not None else 0.0
    return barra_com_dobras(0.0, comp, 0.0, p.dobra_ini, p.dobra_fim, sinal,
                            raio, p.phi if aco is not None else 0.0,
                            tipo), False


def montar_explodida(res: ResultadoViga) -> list[BarraExplodida]:
    """Uma :class:`BarraExplodida` por posição de armadura do detalhamento."""
    viga = res.viga
    cob = viga.ambiente.cobrimento_nominal
    eixos = [(x * 100.0, f"P{k + 1}")
             for k, (x, ap) in enumerate(zip(viga.x_apoios, viga.apoios))
             if ap.tipo != "livre"]
    barras: list[BarraExplodida] = []

    for p in res.posicoes:
        secao = al.secao_da(viga, p)
        tipo_gancho = p.tipo_gancho or gk.normalizar(
            viga.config.tipo_gancho)
        pontos, fechada = _forma_barra(p, secao, cob,
                                       viga.config.gancho_estribo, viga.aco,
                                       tipo_gancho)
        # o desenho leva o arco; a **cota** leva o esqueleto de canto vivo, que
        # é a dimensão externa da peça. É o que a prática de detalhamento pede
        # ("omitem-se os detalhes de curvatura, cotam-se as dimensões
        # externas") e o que evita cotar cada corda do arco como um trecho de
        # 1 cm. Os dois têm a mesma envoltória, porque o arco é tangente às
        # duas retas, e por isso normalizam para o mesmo referencial
        esqueleto, _ = _forma_barra(p, secao, cob,
                                    viga.config.gancho_estribo, None,
                                    tipo_gancho)
        # o raio só é cotado na armadura longitudinal
        raios: list[tuple[tuple[float, float], tuple[float, float],
                          float]] = []
        if p.tipo not in TIPOS_ESTRIBO:
            r_dobra = viga.aco.raio_dobramento_eixo(p.phi)
            comp = (p.x_fim - p.x_ini) * 100.0
            sinal = 1.0 if p.face == "inferior" else -1.0
            raios = [(c, m, r_dobra) for c, m in centros_das_dobras(
                0.0, comp, 0.0, p.dobra_ini, p.dobra_fim, sinal, r_dobra,
                p.phi, tipo_gancho)]
        x_desloc = min(x for x, _ in pontos)
        y_desloc = min(y for _, y in pontos)
        raios = [((cx - x_desloc, cy - y_desloc),
                  (mx - x_desloc, my - y_desloc), r)
                 for (cx, cy), (mx, my), r in raios]
        pontos, largura, altura = _normalizar(pontos)
        esqueleto, _l, _a = _normalizar(esqueleto)
        if p.tipo in TIPOS_ESTRIBO:
            # o estribo é desenhado uma vez, centrado no trecho que ocupa
            x_real = (p.x_ini + p.x_fim) / 2.0 * 100.0 - largura / 2.0
        else:
            x_real = p.x_ini * 100.0
        segmentos = [(a, b, math.dist(a, b))
                     for a, b in zip(esqueleto, esqueleto[1:])
                     if math.dist(a, b) > 1e-6]
        # medida repetida se cota uma vez: os lados do estribo (b, h, b, h) e
        # as duas pernas iguais do grampo. A regra morava nos dois
        # renderizadores, e o grampo escapava dela por não ser contorno fechado
        if fechada or p.tipo in TIPOS_ESTRIBO:
            vistas: set[int] = set()
            unicos = []
            for a, bb, comp in segmentos:
                chave = int(round(comp))
                if chave in vistas:
                    continue
                vistas.add(chave)
                unicos.append((a, bb, comp))
            segmentos = unicos

        # traspasses: o trecho de sobreposição fica sobre o maior trecho reto
        emendas: list[tuple[tuple[float, float], tuple[float, float],
                            float, str]] = []
        if segmentos and (p.emendas_x or p.emendas_vizinhas):
            maior = max(segmentos, key=lambda s: s[2])
            (xa, ya), (xb, _yb) = maior[0], maior[1]
            x_esq, x_dir = min(xa, xb), max(xa, xb)
            # a origem das distâncias é a extremidade esquerda da barra
            deslocamento = x_esq - min(px for px, _ in pontos)

            def _trecho(inicio: float, comprimento: float):
                a = min(max(inicio - deslocamento, x_esq), x_dir)
                return (a, ya), (min(a + comprimento, x_dir), ya)

            # o rótulo é só o comprimento, em cm: a sobreposição desenhada já
            # diz que ali há emenda, e "c/" em detalhamento significa "cada"
            for inicio in p.emendas_x:      # emenda de peça comercial
                a, b = _trecho(inicio, p.traspasse)
                emendas.append((a, b, p.traspasse, f"{p.traspasse:.0f}"))
            for inicio, l0t, _vizinha in p.emendas_vizinhas:
                a, b = _trecho(inicio, l0t)
                emendas.append((a, b, l0t, f"{l0t:.0f}"))

        camada = camada_barra(p.face, p.tipo)
        barras.append(BarraExplodida(
            posicao=p, pontos=pontos, largura=largura, altura=altura,
            fechada=fechada, camada=camada, raios=raios,
            rotulo=_rotulo_posicao(p, viga.aco),
            segmentos=segmentos, emendas=emendas, x_real=x_real,
            referencia=None if p.tipo == "estribo"
            else _referencia(x_real, eixos)))
    return barras


def _referencia(x_real: float, eixos: list[tuple[float, str]]
                ) -> tuple[float, str, float] | None:
    """Eixo de apoio mais próximo à esquerda, para a cota de locação."""
    if not eixos:
        return None
    anteriores = [(x, nome) for x, nome in eixos if x <= x_real + 1e-6]
    x_ref, nome = anteriores[-1] if anteriores else eixos[0]
    return (x_ref, nome, x_real - x_ref)


def dispor_explodidas(barras: list[BarraExplodida],
                      folga: float = FOLGA_EXPLODIDA
                      ) -> tuple[list[tuple[BarraExplodida, float, float]],
                                 float]:
    """Empilha as barras em linhas, cada uma sob a sua posição real na viga.

    A abscissa é a da própria barra (``x_real``), não uma sequência da
    esquerda para a direita: quem lê o desenho encontra a barra exatamente
    abaixo do trecho de viga em que ela vai. Duas barras dividem a mesma linha
    apenas quando não se sobrepõem em x, com ``folga`` entre elas; caso
    contrário, a de baixo desce uma linha.

    A ordem vertical das linhas segue :func:`ordem_na_vista`: superiores em
    cima, pele no meio, inferiores embaixo e estribos por último.

    Devolve [(barra, x_absoluto, y_base)] com ``y`` decrescente a partir de
    zero, e a altura total ocupada.
    """
    ordenadas = sorted(barras,
                       key=lambda b: (ordem_na_vista(b), b.x_real, -b.largura))

    # cada linha pertence a um grupo -- face e camada -- e só recebe barras
    # daquele grupo: o desenho fica com as azuis juntas, as vermelhas juntas e
    # os estribos no fim, e nenhuma camada se mistura com a vizinha
    ocupacao: list[list[tuple[float, float]]] = []
    grupo_da_linha: list[tuple[int, int]] = []
    linha_da_barra: list[int] = []
    for barra in ordenadas:
        grupo = ordem_na_vista(barra)
        a = barra.x_real
        b = a + max(barra.largura, LARGURA_MINIMA_ROTULO)
        destino = None
        for i, intervalos in enumerate(ocupacao):
            if grupo_da_linha[i] != grupo:
                continue
            if all(b + folga <= x0 or a >= x1 + folga
                   for x0, x1 in intervalos):
                destino = i
                break
        if destino is None:
            ocupacao.append([])
            grupo_da_linha.append(grupo)
            destino = len(ocupacao) - 1
        ocupacao[destino].append((a, b))
        linha_da_barra.append(destino)

    alturas = [0.0] * len(ocupacao)
    for barra, linha in zip(ordenadas, linha_da_barra):
        alturas[linha] = max(alturas[linha], barra.altura)

    topo_da_linha: list[float] = []
    y = 0.0
    for altura in alturas:
        topo_da_linha.append(y)
        y -= altura + ALTURA_ROTULO

    postas = [(barra, barra.x_real, topo_da_linha[linha] - barra.altura)
              for barra, linha in zip(ordenadas, linha_da_barra)]
    return postas, abs(y)


def barras_em(res: ResultadoViga, x_m: float) -> list[Posicao]:
    """Posições longitudinais presentes na abscissa ``x_m`` (m)."""
    return [p for p in res.posicoes
            if p.tipo in ("longitudinal", "porta")
            and p.x_ini - 1e-9 <= x_m <= p.x_fim + 1e-9]


def montar_secao(res: ResultadoViga, x_m: float, nome: str = ""
                 ) -> SecaoTransversal:
    """Geometria da seção transversal na abscissa ``x_m`` (m)."""
    viga = res.viga
    cfg = viga.config
    cob = viga.ambiente.cobrimento_nominal
    # a seção troca na face do pilar, não no eixo: entre uma e outra o
    # concreto já é o do trecho dominante
    i_secao = al.trecho_em(viga, x_m)
    secao = viga.trechos[i_secao].secao
    # uma barra pode atravessar a junta e aparecer numa seção que não é a dela:
    # o nível e a largura que valem são os do **trecho** em que ela foi
    # dimensionada, deslocados até o datum desta seção
    bases_v = al.bases_verticais(viga)
    bases_l = al.bases_laterais(viga)
    contorno = Polilinha(_contorno_secao(secao), camada="CONCRETO",
                         fechada=True)
    b, h = secao.bw, secao.h
    est = Polilinha([(cob, cob), (b - cob, cob), (b - cob, h - cob),
                     (cob, h - cob)], camada="ESTRIBO", fechada=True)

    barras: list[Circulo] = []
    textos: list[Texto] = []
    # os rótulos têm altura em pontos e a seção, em centímetros: numa seção
    # alta um passo fixo de 7 cm deixa as linhas de texto se tocando
    passo_rotulo = max(7.0, 0.06 * h)
    niveis_rotulo = {"inferior": 1, "superior": 1}
    # última altura usada pelo rótulo lateral de cada face: com bitola grossa o
    # passo entre camadas (phi + av) fica menor que a linha de texto, e dois
    # rótulos de camada interna se encostam
    ultimo_lateral: dict[str, float] = {}
    #: camadas internas de cada face, para rotular depois do laço
    internas: dict[str, list[tuple]] = {}
    por_face: dict[tuple[str, int], list[Posicao]] = {}
    # a geometria separa também por trecho; o rótulo continua um por camada,
    # senão dois rótulos iguais brigariam pelo mesmo lugar fora da face
    por_geometria: dict[tuple[str, int, int], list[Posicao]] = {}
    for p in barras_em(res, x_m):
        por_face.setdefault((p.face, p.camada), []).append(p)
        i_barra = al.trecho_da(viga, p)
        por_geometria.setdefault((p.face, p.camada, i_barra), []).append(p)

    for (face, camada, i_barra), grupo in sorted(por_geometria.items()):
        # uma face pode reunir bitolas diferentes -- a armadura calculada e o
        # porta-estribo que completa os cantos, por exemplo. Cada barra é
        # desenhada com o seu próprio diâmetro; a maior governa o afastamento
        # do estribo e o eixo da camada, onde todas se apoiam
        phis = sorted((p.phi for p in grupo for _ in range(p.n)), reverse=True)
        n_total = len(phis)
        phi_max = phis[0]
        secao_barra = viga.trechos[i_barra].secao
        dy = bases_v[i_barra] - bases_v[i_secao]
        dx = bases_l[i_barra] - bases_l[i_secao]
        y = dy + _y_barra(secao_barra, cob, cfg.phi_estribo, phi_max, camada,
                          face, cfg.d_agregado)
        x0 = dx + cob + cfg.phi_estribo / 10.0 + phi_max / 20.0
        x1 = dx + secao_barra.bw - (cob + cfg.phi_estribo / 10.0
                                    + phi_max / 20.0)
        if n_total == 1:
            posx = [(x0 + x1) / 2.0]
        else:
            passo = (x1 - x0) / (n_total - 1)
            posx = [x0 + k * passo for k in range(n_total)]
        # as maiores nas extremidades, como se detalha: o canto do estribo
        # recebe a barra portante e a menor sobra para o meio da camada
        centro = (x0 + x1) / 2.0
        ordem = sorted(range(n_total),
                       key=lambda k: (-abs(posx[k] - centro), posx[k]))
        for k, phi_barra in zip(ordem, phis):
            barras.append(Circulo((posx[k], y), phi_barra / 20.0,
                                  camada=camada_barra(face)))
        # o rótulo é um só por camada, emitido pelo grupo "dono": o desta
        # seção quando ele existe, senão o primeiro. Um rótulo por grupo faria
        # dois textos iguais brigarem pelo mesmo lugar fora da face
        trechos_da_camada = sorted({t[2] for t in por_geometria
                                    if t[0] == face and t[1] == camada})
        dono = (i_secao if i_secao in trechos_da_camada
                else trechos_da_camada[0])
        if i_barra != dono:
            continue
        rotulo = " + ".join(
            f"{p.texto_quantidade}Ø{p.phi:g} (N{p.numero})"
            + ("" if al.trecho_da(viga, p) == i_secao
               else f" do tramo {p.tramo + 1}")
            for p in por_face[(face, camada)])
        if max(camada, 1) == 1:
            # a camada externa é rotulada fora da face, como sempre
            y_rot = -3.0 if face == "inferior" else h + 1.0
            textos.append(Texto(rotulo, ((x0 + x1) / 2.0, y_rot),
                                altura=4.5, ancora="center"))
        else:
            # as camadas internas são rotuladas ao lado das suas barras, com a
            # camada escrita: empilhadas fora da face e sem essa indicação,
            # ninguém sabia qual fileira era qual. A emissão fica para depois
            # do laço, porque com muitas camadas os rótulos não caberiam
            internas.setdefault(face, []).append(
                (camada, y, rotulo, sum(p.n for p in grupo), phi_max))
        niveis_rotulo[face] = max(niveis_rotulo[face], 1)

    # rótulos das camadas internas. Até duas camadas, cada uma ganha o seu
    # rótulo ao lado das barras. Acima disso a pilha de rótulos não caberia na
    # altura, e sai um rótulo só, consolidado -- caso que só aparece em seção
    # que o dimensionamento já reprovou por não caber
    for face, itens in internas.items():
        itens.sort(key=lambda t: t[0])
        sentido = 1.0 if face == "inferior" else -1.0
        if len(itens) <= 2:
            for camada, y, rotulo, _n, _phi in itens:
                y_lat = y
                anterior = ultimo_lateral.get(face)
                if anterior is not None:
                    minimo = anterior + sentido * passo_rotulo
                    y_lat = max(y, minimo) if sentido > 0 else min(y, minimo)
                ultimo_lateral[face] = y_lat
                textos.append(Texto(f"{rotulo} na {camada}ª camada",
                                    (b + 6.0, y_lat), altura=4.5,
                                    ancora="left"))
            continue
        total = sum(t[3] for t in itens)
        phis = {t[4] for t in itens}
        bitola = (f"Ø{phis.pop():g}" if len(phis) == 1 else "barras")
        y_medio = sum(t[1] for t in itens) / len(itens)
        textos.append(Texto(
            f"{total}{bitola} nas camadas {itens[0][0]}ª a {itens[-1][0]}ª",
            (b + 6.0, y_medio), altura=4.5, ancora="left"))

    # armadura de pele. Num apoio as posições dos dois tramos se sobrepõem;
    # rotular a mesma armadura duas vezes só enche a seção de texto
    rotulos_pele: list[str] = []
    for p in res.posicoes:
        if p.tipo != "pele" or not (p.x_ini <= x_m <= p.x_fim):
            continue
        n_face = max(p.n // 2, 1)
        # a posição pode ocupar só uma faixa da alma: a armadura de pele é
        # separada por situação de aderência (9.3.1), e cada trecho tem a sua
        y0, y1 = p.faixa_altura
        if not any(p.faixa_altura):
            y0, y1 = cob + 10.0, h - cob - 10.0
        for k in range(n_face):
            y = y0 + (y1 - y0) * (k / max(n_face - 1, 1))
            for xb in (cob + 1.0, b - cob - 1.0):
                barras.append(Circulo((xb, y), p.phi / 20.0, camada="PELE"))
        # com o N: é por ele que se acha a posição na lista de aço, e a pele
        # do tramo vizinho tem outro N com outro número de barras
        rotulo_pele = (f"pele {p.texto_quantidade} N{p.numero}Ø{p.phi:g}"
                       + (f" c/{p.s:g}" if p.s else ""))
        if rotulo_pele in rotulos_pele:
            continue
        textos.append(Texto(
            rotulo_pele,
            (b + 4.0, h / 2.0 - passo_rotulo * len(rotulos_pele)),
            altura=4.5, ancora="left"))
        rotulos_pele.append(rotulo_pele)

    # abaixo do último degrau de rótulos da face inferior
    y_descricao = -3.0 - passo_rotulo * niveis_rotulo["inferior"] - 4.0
    textos.append(Texto(f"{secao.descricao()}", (b / 2.0, y_descricao),
                        altura=5.5, ancora="center"))
    return SecaoTransversal(x=x_m * 100.0, nome=nome or f"Seção x={x_m:.2f} m",
                            contorno=contorno, estribo=est, barras=barras,
                            textos=textos, largura=secao.bf or secao.bw,
                            altura=h)
