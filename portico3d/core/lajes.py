# -*- coding: utf-8 -*-
"""
lajes.py
Painéis de laje: peso próprio, revestimento e acidental, repartidos às vigas.

A laje entra como **carga**, não como elemento. O painel é retangular, dado
por dois cantos de uma diagonal, e a sua carga vai para as quatro vigas de
contorno pelas áreas de influência delimitadas por retas a 45° saindo dos
cantos — o processo das áreas, que é como se faz à mão e como a maioria dos
programas de edifício faz.

Isso reparte o painel em dois triângulos, sobre os lados menores, e dois
trapézios, sobre os maiores. Daí a viga do lado menor recebe carga triangular
e a do maior, trapezoidal — que é exatamente o tipo de carga que o solver
passou a aceitar na fase 2, e é por isso que esta peça coube sem tocar no
núcleo.

**Por padrão, a laje não é diafragma nem grelha.** Ela não enrijece o
pavimento no próprio plano nem tem rigidez à flexão: é só carga. As duas
coisas existem como opção de cálculo (``Modelo.calculo``): o diafragma
rígido em ``core.diafragma`` e a laje em grelha em ``core.grelha`` — esta
usa a marca ``origem`` das cargas daqui para tirá-las das vigas.
"""

from __future__ import annotations

import math

import numpy as np
from dataclasses import dataclass, field

from .modelo import CasoDeCarga, ErroDeModelo, Laje, Modelo

TOLERANCIA = 1.0e-6


@dataclass
class Aresta:
    """Um lado do painel e as barras de viga que o percorrem.

    O lado pode ser coberto por **várias** barras colineares — a viga partida
    onde outra viga chega de fora, ou onde um pilar aparece no meio do lado.
    ``trechos`` traz cada uma com o intervalo ``(s0, s1)`` que ela cobre, em
    metros a partir de ``inicio``, o canto em que o lado começa. ``barra`` é a
    primeira — e é tudo que o lado tem no caso de uma barra só.
    """

    barra: str
    comprimento: float
    total: float = 0.0
    trechos: list[tuple[str, float, float]] = field(default_factory=list)
    inicio: str = ""

    @property
    def barras(self) -> list[str]:
        return [t[0] for t in self.trechos] if self.trechos else [self.barra]


@dataclass
class RepasseDeLaje:
    """O que a laje entregou, para poder ir para a memória de cálculo."""

    laje: str
    lx: float
    ly: float
    area: float
    carga: float
    arestas: list[Aresta] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(a.total for a in self.arestas)

    def __str__(self) -> str:
        linhas = [f"laje {self.laje}: {self.lx:.3f} × {self.ly:.3f} m, "
                  f"{self.area:.3f} m², q = {self.carga:.4f} kN/m²  "
                  f"→ {self.total:.4f} kN"]
        for a in self.arestas:
            linhas.append(f"    {'+'.join(a.barras):<12} L = "
                          f"{a.comprimento:.3f} m   {a.total:.4f} kN")
        return "\n".join(linhas)


def retangulo(modelo: Modelo, laje: Laje
              ) -> tuple[float, float, float, float, float]:
    """``(x0, y0, x1, y1, z)`` do painel em planta, nos eixos das vigas.

    Vale para os dois tipos de laje. Na comum, ``no_a`` e ``no_c`` são a
    diagonal; na em balanço, são as pontas do lado apoiado, e o retângulo
    avança ``balanco`` no ``sentido`` dela — até a borda livre, onde não há
    nó nenhum.
    """
    for no in (laje.no_a, laje.no_c):
        if no not in modelo.nos:
            raise ErroDeModelo(
                f"laje '{laje.nome}': o nó '{no}' não existe")
    a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
    x0, x1 = min(a[0], c[0]), max(a[0], c[0])
    y0, y1 = min(a[1], c[1]), max(a[1], c[1])
    if laje.em_balanco:
        b = laje.balanco
        if laje.sentido == "+x":
            x1 = x0 + b
        elif laje.sentido == "-x":
            x0 = x1 - b
        elif laje.sentido == "+y":
            y1 = y0 + b
        else:
            y0 = y1 - b
    return float(x0), float(y0), float(x1), float(y1), float(a[2])


def contorno(modelo: Modelo, laje: Laje) -> np.ndarray:
    """Os quatro cantos do painel, ``(4, 3)``, em volta a partir de (x0, y0)
    — também os da borda livre da laje em balanço, que não são nós."""
    x0, y0, x1, y1, z = retangulo(modelo, laje)
    return np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]])


def _cantos(modelo: Modelo, laje: Laje) -> tuple[list[str], float, float]:
    """Os quatro cantos do painel, em volta, mais os lados em X e Y.

    Os cantos são **nós**: a laje em balanço não os tem (a borda livre não
    tem viga nem nó), e por isso é recusada aqui — quem precisa só da
    geometria usa :func:`retangulo` ou :func:`contorno`."""
    for no in (laje.no_a, laje.no_c):
        if no not in modelo.nos:
            raise ErroDeModelo(
                f"laje '{laje.nome}': o nó '{no}' não existe")
    if laje.em_balanco:
        raise ErroDeModelo(
            f"laje '{laje.nome}': em balanço — só o lado apoiado tem nós")

    a, c = modelo.ponto(laje.no_a), modelo.ponto(laje.no_c)
    if abs(a[2] - c[2]) > TOLERANCIA:
        raise ErroDeModelo(
            f"laje '{laje.nome}': os cantos estão em cotas diferentes "
            f"({a[2]:.3f} e {c[2]:.3f} m); o painel tem de ser horizontal")

    lx, ly = abs(c[0] - a[0]), abs(c[1] - a[1])
    if lx <= TOLERANCIA or ly <= TOLERANCIA:
        raise ErroDeModelo(
            f"laje '{laje.nome}': os cantos '{laje.no_a}' e '{laje.no_c}' não "
            "formam retângulo — eles têm de ser diagonalmente opostos")

    x0, x1 = min(a[0], c[0]), max(a[0], c[0])
    y0, y1 = min(a[1], c[1]), max(a[1], c[1])
    z = a[2]

    procurados = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    cantos = []
    for x, y in procurados:
        achado = None
        for nome, no in modelo.nos.items():
            if (abs(no.x - x) < TOLERANCIA and abs(no.y - y) < TOLERANCIA
                    and abs(no.z - z) < TOLERANCIA):
                achado = nome
                break
        if achado is None:
            raise ErroDeModelo(
                f"laje '{laje.nome}': falta o nó do canto ({x:.3f}, {y:.3f}, "
                f"{z:.3f})")
        cantos.append(achado)

    return cantos, lx, ly


def _barras_do_lado(modelo: Modelo, no_i: str, no_j: str,
                    laje: str) -> list[tuple[str, float, float]]:
    """As barras colineares que vão de ``no_i`` a ``no_j``, em ordem, com o
    trecho ``(s0, s1)`` do lado que cada uma cobre.

    Anda de nó em nó: de onde está, pega a barra que avança sobre a reta do
    lado sem sair dela. Uma barra só de canto a canto é o caso comum, e cai
    aqui igual.
    """
    a, b = modelo.ponto(no_i), modelo.ponto(no_j)
    L = float(np.linalg.norm(b - a))
    u = (b - a) / L
    incidentes: dict[str, list[str]] = {}
    for nome, barra in modelo.barras.items():
        incidentes.setdefault(barra.no_i, []).append(nome)
        incidentes.setdefault(barra.no_j, []).append(nome)

    trechos, atual, s = [], no_i, 0.0
    while atual != no_j:
        proximo = None
        for nome in incidentes.get(atual, []):
            barra = modelo.barras[nome]
            outro = barra.no_j if barra.no_i == atual else barra.no_i
            p = modelo.ponto(outro) - a
            s_outro = float(np.dot(p, u))
            fora = float(np.linalg.norm(p - s_outro * u))
            if fora < TOLERANCIA and s + TOLERANCIA < s_outro \
                    < L + TOLERANCIA:
                proximo = (nome, outro, s_outro)
                break
        if proximo is None:
            raise ErroDeModelo(
                f"laje '{laje}': não há viga entre '{no_i}' e '{no_j}' — o "
                "lado do painel tem de ser coberto de canto a canto por "
                "vigas na mesma reta")
        nome, atual, s_novo = proximo
        trechos.append((nome, s, s_novo))
        s = s_novo
    return trechos


def arestas_da_laje(modelo: Modelo, laje: Laje) -> tuple[list[Aresta], float,
                                                         float]:
    """As arestas apoiadas do painel, e os lados dele em X e Y.

    Na laje comum são quatro, na ordem embaixo (y0), à direita (x1), em
    cima (y1) e à esquerda (x0). Na laje em balanço é **uma** — o lado
    apoiado, sobre a viga —: os outros três são borda livre.
    """
    if laje.em_balanco:
        x0, y0, x1, y1, _ = retangulo(modelo, laje)
        trechos = _barras_do_lado(modelo, laje.no_a, laje.no_c, laje.nome)
        comprimento = float(np.linalg.norm(modelo.ponto(laje.no_c)
                                           - modelo.ponto(laje.no_a)))
        return ([Aresta(trechos[0][0], comprimento, trechos=trechos,
                        inicio=laje.no_a)], x1 - x0, y1 - y0)
    cantos, lx, ly = _cantos(modelo, laje)
    arestas = []
    for k in range(4):
        i, j = cantos[k], cantos[(k + 1) % 4]
        trechos = _barras_do_lado(modelo, i, j, laje.nome)
        comprimento = float(np.linalg.norm(modelo.ponto(j) - modelo.ponto(i)))
        arestas.append(Aresta(trechos[0][0], comprimento, trechos=trechos,
                              inicio=i))
    return arestas, lx, ly


def _horizontal(modelo: Modelo, barra) -> bool:
    a, b = modelo.ponto(barra.no_i), modelo.ponto(barra.no_j)
    return abs(float(a[2] - b[2])) < TOLERANCIA


def nivel_do_pavimento(modelo: Modelo, cota: float) -> float | None:
    """O topo do pavimento na cota dada, m: o topo da viga mais alta dela.

    O modelo de cálculo põe o **eixo** de toda viga na cota, e vigas de
    alturas diferentes ficariam com o topo em níveis diferentes — a de 60 cm
    5 cm acima da de 50. Na obra os topos e a laje ficam nivelados; o desenho
    segue a obra: toda viga e toda laje do pavimento com o topo aqui (ver
    :func:`desnivel_da_viga`). É geometria de desenho e de posição de
    armadura — o cálculo continua com os eixos na cota. ``None`` quando a
    cota não tem viga com altura declarada.
    """
    topo = None
    for barra in modelo.barras.values():
        if not _horizontal(modelo, barra):
            continue
        if abs(float(modelo.ponto(barra.no_i)[2]) - cota) > TOLERANCIA:
            continue
        secao = modelo.secoes.get(barra.secao)
        if secao is None or secao.h <= 0.0:
            continue
        t = cota + float(secao.h) / 2.0
        topo = t if topo is None else max(topo, t)
    return topo


def desnivel_da_viga(modelo: Modelo, nome: str) -> float:
    """Quanto a viga sobe no desenho, m (≥ 0), para o topo dela ficar no
    nível do pavimento (:func:`nivel_do_pavimento`) — o da viga mais alta da
    cota. Zero nas barras que não são viga horizontal e na viga mais alta."""
    barra = modelo.barras[nome]
    if not _horizontal(modelo, barra):
        return 0.0
    secao = modelo.secoes.get(barra.secao)
    if secao is None or secao.h <= 0.0:
        return 0.0
    z = float(modelo.ponto(barra.no_i)[2])
    topo = nivel_do_pavimento(modelo, z)
    return 0.0 if topo is None else topo - (z + float(secao.h) / 2.0)


def deslocamento_do_centro(modelo: Modelo, laje: Laje) -> float:
    """Quanto o plano médio da laje sobe acima do plano dos nós, em metros.

    O plano dos nós passa pelo **eixo** das vigas; a laje é desenhada com o
    **topo no nível do pavimento** — o topo da viga mais alta da cota, onde
    ficam também os topos das outras vigas (:func:`nivel_do_pavimento`). O
    plano médio fica então ``e/2`` abaixo desse nível. É geometria de desenho
    e de posição da armadura — nenhum cálculo depende disso. Sem viga com
    altura declarada na cota, não há onde alinhar e o deslocamento é zero.

    Antes a laje seguia a viga mais alta **do próprio contorno**: duas lajes
    vizinhas de contornos diferentes ficavam em níveis diferentes, e a
    negativa entre elas saía por cima de uma; a mesa da viga T, por baixo.
    """
    try:
        _, _, _, _, z = retangulo(modelo, laje)
    except ErroDeModelo:
        return 0.0
    topo = nivel_do_pavimento(modelo, z)
    if topo is None:
        return 0.0
    return topo - z - max(laje.altura, 0.01) / 2.0


# ---------------------------------------------------------------------------
# Laje treliçada: a geometria da nervura, por metro quadrado
# ---------------------------------------------------------------------------

#: Apoio do bloco de enchimento sobre a base da vigota, de cada lado, m — o
#: padrão do programa de Lajes (``LajeTrelicada.apoio_enchimento``).
APOIO_ENCHIMENTO = 0.015

#: Peso específico do enchimento, kN/m³ — os do programa de Lajes
#: (``trelicada_modelo.ENCHIMENTOS``).
ENCHIMENTOS = {"EPS": 0.18, "Cerâmico": 6.0}


def nervura(laje: Laje) -> tuple[float, float]:
    """``(bw, intereixo)`` da treliçada, m."""
    bw = laje.base_vigota - 2.0 * APOIO_ENCHIMENTO
    return bw, bw + laje.largura_bloco


def concreto_por_area(laje: Laje) -> float:
    """Volume de concreto por metro quadrado de laje, m³/m²: a espessura da
    maciça, ou a capa mais a nervura repartida pelo intereixo."""
    if not laje.trelicada:
        return max(laje.espessura, 0.0)
    bw, inter = nervura(laje)
    return laje.capa + bw * laje.altura_enchimento / inter


def carga_permanente(modelo: Modelo, laje: Laje) -> float:
    """Peso próprio mais o revestimento, em kN/m².

    Na treliçada o peso próprio é o da capa e da nervura mais o do
    enchimento, por intereixo — a mesma expressão do programa de Lajes
    (``trelicada.peso_proprio``), passada de "por nervura" a "por m²".
    """
    peso = 0.0
    if laje.altura > 0.0:
        if laje.material not in modelo.materiais:
            raise ErroDeModelo(
                f"laje '{laje.nome}': material '{laje.material}' não existe, e "
                "sem ele não há como pesar a espessura")
        gc = modelo.materiais[laje.material].peso_especifico
        peso = concreto_por_area(laje) * gc
        if laje.trelicada:
            _, inter = nervura(laje)
            ge = ENCHIMENTOS.get(laje.enchimento, ENCHIMENTOS["EPS"])
            peso += laje.largura_bloco * laje.altura_enchimento * ge / inter
    return peso + laje.permanente


def distribuir(modelo: Modelo, laje: Laje, caso: CasoDeCarga,
               carga: float) -> RepasseDeLaje:
    """Reparte ``carga`` (kN/m²) do painel para as quatro vigas de contorno.

    O quinhão de cada aresta é ``q·lx·(2·Le − lx)/4``, com ``lx`` o **menor**
    lado do painel e ``Le`` o comprimento da aresta. A fórmula é a mesma para
    o lado curto e para o longo — no curto, ``Le = lx`` e ela cai em
    ``q·lx²/4``, que é a área do triângulo. A soma das quatro dá ``q·lx·ly``
    exatamente, e há conferência para isso.

    A carga é emitida em segmentos: rampa, patamar e rampa. Onde o painel é
    quadrado o patamar tem comprimento nulo e some, restando o triângulo.
    """
    arestas, lx, ly = arestas_da_laje(modelo, laje)
    menor = min(lx, ly)
    repasse = RepasseDeLaje(laje.nome, min(lx, ly), max(lx, ly), lx * ly,
                            carga, arestas)
    if carga == 0.0:
        return repasse
    # A marca de origem é o que deixa a grelha (``core.grelha``) tirar esta
    # carga das vigas e devolvê-la à laje.
    origem = f"laje:{laje.nome}"

    if laje.trelicada:
        return _distribuir_unidirecional(modelo, laje, caso, carga, repasse,
                                         lx, ly, origem)
    if laje.em_balanco:
        return _distribuir_balanco(modelo, laje, caso, carga, repasse, origem)

    for aresta in arestas:
        Le = aresta.comprimento
        aresta.total = carga * menor * (2.0 * Le - menor) / 4.0
        if len(aresta.trechos) > 1:
            _distribuir_no_lado(modelo, caso, aresta, menor, origem)
            continue

        # O perfil é desenhado sobre o vão flexível, que é menor que a aresta
        # quando a viga tem trecho rígido. A intensidade é calculada a partir
        # do total, e não da geometria do painel, justamente para que a carga
        # que cairia sobre o trecho rígido não desapareça do modelo.
        p = modelo.barras[aresta.barra]
        vao = Le - p.offset_i - p.offset_j
        rampa = min(menor / 2.0, vao / 2.0)
        pico = aresta.total / (vao - rampa)

        a = rampa / vao
        b = 1.0 - a
        caso.distribuida(aresta.barra, qz=0.0, qz_fim=-pico, inicio=0.0,
                         fim=a, sistema="global", origem=origem)
        if b - a > TOLERANCIA:
            caso.distribuida(aresta.barra, qz=-pico, inicio=a, fim=b,
                             sistema="global", origem=origem)
        caso.distribuida(aresta.barra, qz=-pico, qz_fim=0.0, inicio=b,
                         fim=1.0, sistema="global", origem=origem)

    return repasse


def _distribuir_unidirecional(modelo: Modelo, laje: Laje, caso: CasoDeCarga,
                              carga: float, repasse: RepasseDeLaje,
                              lx: float, ly: float,
                              origem: str) -> RepasseDeLaje:
    """Laje armada numa direção só (treliçada): metade da carga para cada
    uma das duas vigas **perpendiculares às nervuras**, uniforme ao longo
    delas; as vigas paralelas às nervuras não recebem nada.

    As arestas vêm na ordem de ``arestas_da_laje``: embaixo (y0), à direita
    (x1), em cima (y1) e à esquerda (x0). Nervuras em X apoiam nas de x0 e
    x1; nervuras em Y, nas de y0 e y1.
    """
    if laje.direcao == "x":
        apoios, vao = (1, 3), lx
    else:
        apoios, vao = (0, 2), ly
    for k in apoios:
        aresta = repasse.arestas[k]
        aresta.total = carga * vao / 2.0 * aresta.comprimento
        for barra, s0, s1 in aresta.trechos:
            p = modelo.barras[barra]
            flexivel = modelo.comprimento(barra) - p.offset_i - p.offset_j
            # pelo total, para a carga sobre o trecho rígido não sumir
            caso.distribuida(barra, qz=-carga * vao / 2.0 * (s1 - s0)
                             / flexivel, sistema="global", origem=origem)
    return repasse


def _distribuir_balanco(modelo: Modelo, laje: Laje, caso: CasoDeCarga,
                        carga: float, repasse: RepasseDeLaje,
                        origem: str) -> RepasseDeLaje:
    """Laje em balanço: a carga inteira vai para a viga do lado apoiado,
    uniforme, ``q·balanço`` por metro.

    O momento do engaste (``q·balanço²/2`` por metro) **não** entra na viga
    como torção: ele é equilibrado pela laje interna do outro lado da viga,
    na compatibilização do programa de Lajes — que é como se projeta a
    sacada contínua com a laje de dentro, e é por isso que a laje em balanço
    sem vizinha é recusada no dimensionamento (``montar_pavimento``). O
    solver não tem torque distribuído; o engaste na torção da viga fica fora.
    """
    aresta = repasse.arestas[0]
    linear = carga * laje.balanco
    aresta.total = linear * aresta.comprimento
    for barra, s0, s1 in aresta.trechos:
        p = modelo.barras[barra]
        flexivel = modelo.comprimento(barra) - p.offset_i - p.offset_j
        # pelo total, para a carga sobre o trecho rígido não sumir
        caso.distribuida(barra, qz=-linear * (s1 - s0) / flexivel,
                         sistema="global", origem=origem)
    return repasse


def _distribuir_no_lado(modelo: Modelo, caso: CasoDeCarga, aresta: Aresta,
                        menor: float, origem: str) -> None:
    """O quinhão de um lado coberto por várias barras.

    O perfil do lado é o mesmo da barra única — rampa, patamar e rampa, com
    ``r = min(lx/2, Le/2)`` e pico ``total/(Le − r)`` —, só que recortado
    nos trechos de cada barra. Em cada uma, o pedaço do perfil que cai sobre
    ela é posto sobre o vão flexível, esticado na proporção ``L/Lf`` e
    escalado pelo inverso, de modo que o total dela seja exatamente a área do
    perfil no trecho dela: a carga que cairia sobre o trecho rígido não some.
    """
    Le = aresta.comprimento
    r = min(menor / 2.0, Le / 2.0)
    pico = aresta.total / (Le - r)
    origem_lado = modelo.ponto(aresta.inicio)

    def q(s: float) -> float:
        if r > 0.0 and s < r:
            return pico * s / r
        if r > 0.0 and s > Le - r:
            return pico * (Le - s) / r
        return pico

    for barra, s0, s1 in aresta.trechos:
        b = modelo.barras[barra]
        Lb = s1 - s0
        Lf = Lb - b.offset_i - b.offset_j
        escala = Lb / Lf
        # a barra pode percorrer o lado no sentido contrário ao dele
        s_no_i = float(np.linalg.norm(modelo.ponto(b.no_i) - origem_lado))
        invertida = abs(s_no_i - s1) < abs(s_no_i - s0)
        quebras = sorted({s0, s1} | {x for x in (r, Le - r) if s0 < x < s1})
        for sa, sb in zip(quebras, quebras[1:]):
            qa, qb = q(sa), q(sb)
            if invertida:
                xa, xb, qa, qb = s1 - sb, s1 - sa, qb, qa
            else:
                xa, xb = sa - s0, sb - s0
            if xb - xa <= TOLERANCIA or (qa == 0.0 and qb == 0.0):
                continue
            caso.distribuida(barra, qz=-qa * escala, qz_fim=-qb * escala,
                             inicio=xa / Lb, fim=xb / Lb, sistema="global",
                             origem=origem)


def aplicar_lajes(modelo: Modelo, permanente: CasoDeCarga,
                  acidental: CasoDeCarga | None = None
                  ) -> list[RepasseDeLaje]:
    """Distribui todas as lajes do modelo para os casos indicados."""
    repasses = []
    for laje in modelo.lajes.values():
        repasses.append(distribuir(modelo, laje, permanente,
                                   carga_permanente(modelo, laje)))
        if acidental is not None and laje.acidental != 0.0:
            distribuir(modelo, laje, acidental, laje.acidental)
    return repasses


def area_total(modelo: Modelo) -> float:
    total = 0.0
    for laje in modelo.lajes.values():
        x0, y0, x1, y1, _ = retangulo(modelo, laje)
        total += (x1 - x0) * (y1 - y0)
    return total
