# -*- coding: utf-8 -*-
"""
arranjo.py
Distribuição das barras longitudinais na seção e as verificações do item 18.4.2
da NBR 6118: bitola mínima e máxima, taxa geométrica, número mínimo de barras,
espaçamentos livre e entre eixos.

O que sai daqui é a lista de barras nas coordenadas em que elas realmente
ficam, pronta para o motor seccional -- e não uma área equivalente. É essa
diferença que permite verificar a seção com as barras intermediárias das faces
contando na força normal, como elas contam na peça.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from . import geometria as geo
from .materiais import (ESPACAMENTO_EIXOS_MAXIMO, ESPACAMENTO_LIVRE_MINIMO,
                        RHO_MAXIMO, RHO_MAXIMO_CORRENTE, RHO_MAXIMO_EMENDA,
                        area_barra, massa_linear, rho_minimo)
from .modelo import Pilar, SecaoPilar
from .seccional import Barra
from .formato import num

#: Número mínimo de barras em seção circular (item 18.4.2.2).
BARRAS_MINIMAS_CIRCULAR = 6


@dataclass
class Arranjo:
    """Um arranjo concreto de barras longitudinais na seção."""

    barras: list[Barra] = field(default_factory=list)
    phi: float = 0.0             # mm
    nx: int = 0                  # barras por face perpendicular a y
    ny: int = 0                  # barras por face perpendicular a x
    recuo: float = 0.0           # cm, do contorno ao eixo da barra
    cobrimento: float = 0.0      # cm, o adotado para este arranjo
    phi_estribo: float = 0.0     # mm, o suposto ao medir o recuo
    d_linha_x: float = 0.0       # cm, da face ao eixo da camada, direção x
    d_linha_y: float = 0.0
    espacamento_livre: float = 0.0    # cm, o menor da seção
    espacamento_eixos: float = 0.0    # cm, o maior da seção
    #: Índices das barras que caem em vértice do contorno, nas seções L, T e
    #: U. É o que o item 18.2.4 chama de barra de canto, e é a partir delas
    #: que se mede o alcance de 20 phi_t da proteção do estribo.
    indices_vertices: list[int] = field(default_factory=list)
    #: Distância ao longo do contorno entre barras vizinhas, cm, na mesma
    #: ordem das barras. Vazia na seção retangular e na circular, onde o
    #: espaçamento é uniforme por construção.
    passos_contorno: list[float] = field(default_factory=list)
    #: Barras da camada interna (seção vazada), as últimas da lista.
    n_internas: int = 0
    phi_interna: float = 0.0
    cabe: bool = True
    avisos: list[str] = field(default_factory=list)

    @property
    def n_barras(self) -> int:
        return len(self.barras)

    @property
    def As(self) -> float:
        return sum(b.area for b in self.barras)

    def massa(self, comprimento_cm: float) -> float:
        """Massa de aço longitudinal do lance, kg."""
        return sum(massa_linear(b.phi) for b in self.barras) \
            * comprimento_cm / 100.0

    @property
    def simetrico(self) -> bool:
        """As barras são invariantes a ``x -> -x`` e a ``y -> -y`` (com a
        mesma bitola)? É a "armadura simétrica" que os itens 15.8.3.3.2 e
        15.8.3.3.3 exigem dos métodos aproximados."""
        return barras_simetricas(self.barras)

    def por_bitola(self) -> dict[float, int]:
        """Quantidade de barras por bitola, da maior para a menor."""
        cont: dict[float, int] = {}
        for b in self.barras:
            cont[b.phi] = cont.get(b.phi, 0) + 1
        return dict(sorted(cont.items(), key=lambda kv: -kv[0]))

    def descricao_bitolas(self) -> str:
        """``12 ø20`` ou, com bitolas misturadas, ``3 ø20 + 2 ø12.5``."""
        return " + ".join(f"{n} ø{num(f)}" for f, n in self.por_bitola().items())

    @property
    def phi_min(self) -> float:
        return min((b.phi for b in self.barras), default=self.phi)

    def barras_por_camada(self, direcao: str) -> int:
        """Barras na camada extrema da direção pedida.

        É o que o modelo de duas camadas chama de ``As1``/``As2``: as barras
        que ficam na face mais afastada do centro na direção da flexão. Numa
        seção retangular com ``nx`` por face horizontal e ``ny`` por face
        vertical, a flexão em x tem ``ny`` barras por camada.
        """
        return self.ny if direcao == "x" else self.nx

    def descricao(self) -> str:
        return f"{self.descricao_bitolas()} mm ({num(self.As, 2)} cm²)"


# ---------------------------------------------------------------------------
# Recuo do contorno até o eixo da barra
# ---------------------------------------------------------------------------

def barras_simetricas(barras, tol: float = 1e-6) -> bool:
    """Conjunto de barras simétrico em relação aos dois eixos (posição e
    bitola)."""
    conj = {(round(b.x / tol), round(b.y / tol), round(b.phi * 1000))
            for b in barras}
    return all((-x, y, f) in conj and (x, -y, f) in conj for x, y, f in conj)


def montar_lista(secao: SecaoPilar, lista, cobrimento: float,
                 phi_estribo: float) -> Arranjo:
    """Arranjo a partir de uma lista explícita ``(x, y, ø)`` (cm, mm; x e y
    a partir do CG da seção bruta).

    Confere se cada barra fica dentro do concreto com o recuo do item 7.4.7
    (cobrimento + estribo + ø/2), e mede os espaçamentos do item 18.4.2.2
    entre vizinhas.
    """
    barras = [Barra(float(x), float(y), area_barra(float(f)), float(f))
              for x, y, f in lista]
    # Ordem ao longo do perímetro, para a regra do 18.2.4 e o vão do 18.4.2.2
    # caminharem de barra em barra. Pela posição projetada no contorno
    # externo -- o ângulo em torno do CG, que se usava antes, zigue-zagueava
    # numa L, onde o CG cai na reentrância, fora do concreto.
    externo = secao.contornos()[0]
    barras.sort(key=lambda b: _abscissa_no_contorno(b.x, b.y, externo))
    phi = max((b.phi for b in barras), default=0.0)
    arr = Arranjo(barras=barras, phi=phi, cobrimento=cobrimento,
                  phi_estribo=phi_estribo)
    if not barras:
        arr.cabe = False
        return arr
    contornos = secao.contornos()
    externo, furos = contornos[0], contornos[1:]
    recuo_max = 0.0
    fora = []
    for b in barras:
        r = recuo_da_barra(cobrimento, phi_estribo, b.phi)
        recuo_max = max(recuo_max, r)
        dentro = geo.ponto_no_poligono(b.x, b.y, externo) and not any(
            geo.ponto_no_poligono(b.x, b.y, f) for f in furos)
        dist = min(geo.distancia_ao_contorno(b.x, b.y, c) for c in contornos)
        if not dentro or dist < r - 1e-6:
            fora.append((b, dist, r))
    for b, dist, r in fora:
        arr.avisos.append(av.erro(
            f"Barra ø{num(b.phi)} em ({num(b.x, 1)}; {num(b.y, 1)}) cm a {num(dist, 2)} cm do "
            f"contorno, abaixo do recuo de {num(r, 2)} cm (cobrimento + estribo + "
            f"ø/2, item 7.4.7) -- ou fora do concreto."))
    arr.cabe = not fora
    arr.recuo = recuo_max
    if furos and secao.tipo in SECOES_VAZADAS:
        # junto ao furo = mais perto dele que do contorno externo
        arr.n_internas = sum(
            1 for b in barras
            if min(geo.distancia_ao_contorno(b.x, b.y, f) for f in furos)
            < geo.distancia_ao_contorno(b.x, b.y, externo))
    # d' em cada direção: da face mais próxima à barra mais externa
    u_min_x = min(x for pol in contornos[:1] for x, _ in pol)
    u_max_x = max(x for pol in contornos[:1] for x, _ in pol)
    u_min_y = min(y for pol in contornos[:1] for _, y in pol)
    u_max_y = max(y for pol in contornos[:1] for _, y in pol)
    arr.d_linha_x = min(u_max_x - max(b.x for b in barras),
                        min(b.x for b in barras) - u_min_x)
    arr.d_linha_y = min(u_max_y - max(b.y for b in barras),
                        min(b.y for b in barras) - u_min_y)
    # espaçamento livre: o mínimo entre quaisquer duas barras
    livre = float("inf")
    for i, a in enumerate(barras):
        for j in range(i + 1, len(barras)):
            c = barras[j]
            d = math.hypot(a.x - c.x, a.y - c.y)
            livre = min(livre, d - (a.phi + c.phi) / 20.0)
    arr.espacamento_livre = livre if math.isfinite(livre) else 0.0
    n = len(barras)
    if n >= 3:
        arr.passos_contorno = [math.hypot(barras[(i + 1) % n].x - barras[i].x,
                                          barras[(i + 1) % n].y - barras[i].y)
                               for i in range(n)]
        arr.indices_vertices = _vertices_convexos(barras)
        # entre eixos: o maior vão entre barras consecutivas no contorno --
        # o vizinho mais próximo, que se usava antes, achava os 12 cm do lado
        # curto de uma 20x60 com quatro barras e perdia os 51 cm do lado longo
        arr.espacamento_eixos = max(arr.passos_contorno)
    elif n == 2:
        arr.espacamento_eixos = math.hypot(barras[1].x - barras[0].x,
                                           barras[1].y - barras[0].y)
    return arr


def _abscissa_no_contorno(x: float, y: float, contorno) -> float:
    """Posição, ao longo do perímetro, do ponto do contorno mais próximo de
    ``(x, y)``, cm a partir do primeiro vértice."""
    melhor, abscissa, acumulado = float("inf"), 0.0, 0.0
    n = len(contorno)
    for i in range(n):
        x0, y0 = contorno[i]
        x1, y1 = contorno[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        comp2 = dx * dx + dy * dy
        t = 0.0 if comp2 <= 0 else max(0.0, min(1.0, ((x - x0) * dx
                                                    + (y - y0) * dy) / comp2))
        px, py = x0 + t * dx, y0 + t * dy
        dist = math.hypot(x - px, y - py)
        comp = math.sqrt(comp2)
        if dist < melhor - 1e-9:
            melhor, abscissa = dist, acumulado + t * comp
        acumulado += comp
    return abscissa


def _vertices_convexos(barras) -> list[int]:
    """Índices das barras que são vértices do contorno convexo (as de canto,
    que o estribo abraça); colineares ficam de fora."""
    pts = sorted(range(len(barras)), key=lambda i: (barras[i].x, barras[i].y))

    def cruz(o, a, b):
        return ((barras[a].x - barras[o].x) * (barras[b].y - barras[o].y)
                - (barras[a].y - barras[o].y) * (barras[b].x - barras[o].x))

    baixo, cima = [], []
    for i in pts:
        while len(baixo) >= 2 and cruz(baixo[-2], baixo[-1], i) <= 1e-9:
            baixo.pop()
        baixo.append(i)
    for i in reversed(pts):
        while len(cima) >= 2 and cruz(cima[-2], cima[-1], i) <= 1e-9:
            cima.pop()
        cima.append(i)
    return sorted(set(baixo[:-1] + cima[:-1]))


def recuo_da_barra(cobrimento: float, phi_estribo: float,
                   phi: float) -> float:
    """Distância da face ao **eixo** da barra longitudinal, cm.

    ``c + phi_t + phi/2``. É o ``d'`` do roteiro de flexo-compressão, e a
    ordem importa: o estribo é a peça mais externa da armadura, e o cobrimento
    é medido nele.
    """
    return cobrimento + phi_estribo / 10.0 + phi / 20.0


# ---------------------------------------------------------------------------
# Montagem por tipo de seção
# ---------------------------------------------------------------------------

SECOES_VAZADAS = ("circular vazada", "retangular vazada")


def montar(secao: SecaoPilar, cobrimento: float, phi_estribo: float,
           phi: float, nx: int = 0, ny: int = 0, n: int = 0,
           n_internas: int = 0, phi_interna: float = 0.0) -> Arranjo:
    """Monta o arranjo de barras da seção.

    ``nx`` e ``ny`` valem na seção retangular -- barras por face horizontal e
    por face vertical, cantos incluídos. Nas demais vale ``n``, o total da
    camada externa. ``n_internas`` acrescenta, nas seções vazadas, uma
    camada junto ao furo (bitola ``phi_interna``, 0 = a mesma).
    """
    recuo = recuo_da_barra(cobrimento, phi_estribo, phi)
    a = area_barra(phi)
    if secao.tipo == "retangular":
        arr = _montar_retangular(secao, recuo, phi, a, nx, ny)
    elif secao.tipo in ("circular", "circular vazada"):
        arr = _montar_circular(secao, recuo, phi, a, n)
    else:
        arr = _montar_contorno(secao, recuo, phi, a, n)
    arr.cobrimento = cobrimento
    arr.phi_estribo = phi_estribo
    if n_internas > 0 and secao.tipo in SECOES_VAZADAS and arr.cabe:
        _camada_interna(arr, secao, cobrimento, phi_estribo,
                        phi_interna or phi, int(n_internas), recuo)
    return arr


def linha_do_furo(secao: SecaoPilar, recuo: float):
    """Linha a ``recuo`` do furo, para dentro da parede: ``("circulo",
    diâmetro)`` ou ``("poligono", vértices anti-horários)``, centrada no CG
    (as duas seções vazadas são duplamente simétricas)."""
    if secao.tipo == "circular vazada":
        return "circulo", secao.Di + 2.0 * recuo
    wx = secao.hx - 2.0 * secao.e1 + 2.0 * recuo
    wy = secao.hy - 2.0 * secao.e2 + 2.0 * recuo
    return "poligono", geo.retangulo(wx, wy, 0.0, 0.0)


#: Mínimo de barras na camada interna: uma por canto do furo retangular, seis
#: no furo circular (o mesmo do item 18.4.2.2 para o contorno circular).
BARRAS_MINIMAS_INTERNAS = {"retangular vazada": 4, "circular vazada": 6}


def _camada_interna(arr: Arranjo, secao: SecaoPilar, cobrimento: float,
                    phi_estribo: float, phi_i: float, n_i: int,
                    recuo_ext: float) -> None:
    """Acrescenta a camada junto ao furo ao arranjo já montado."""
    n_i = max(n_i, BARRAS_MINIMAS_INTERNAS[secao.tipo])
    recuo_i = recuo_da_barra(cobrimento, phi_estribo, phi_i)
    tipo, linha = linha_do_furo(secao, recuo_i)
    if tipo == "circulo":
        pontos = geo.distribuir_na_circunferencia(linha, n_i, math.pi / 2.0)
        passo = linha * math.sin(math.pi / n_i)
        passos = [passo] * n_i
    else:
        pontos = geo.distribuir_no_contorno(linha, n_i)
        passos = [math.hypot(pontos[(k + 1) % n_i][0] - pontos[k][0],
                             pontos[(k + 1) % n_i][1] - pontos[k][1])
                  for k in range(n_i)]
    # parede: as duas camadas e o espaço livre entre elas
    parede = secao.menor_dimensao
    livre_radial = parede - recuo_ext - recuo_i - (arr.phi + phi_i) / 20.0
    if livre_radial <= 0.0:
        arr.cabe = False
        arr.avisos.append(av.erro(
            f"A parede de {num(parede)} cm não comporta as duas camadas de "
            f"armadura: com o recuo de {num(recuo_ext, 2)} cm de fora e "
            f"{num(recuo_i, 2)} cm do furo, as barras se sobrepõem."))
        return
    a_i = area_barra(phi_i)
    arr.barras += [Barra(x, y, a_i, phi_i) for x, y in pontos]
    arr.n_internas = n_i
    arr.phi_interna = phi_i
    arr.espacamento_eixos = max(arr.espacamento_eixos, max(passos))
    arr.espacamento_livre = min(arr.espacamento_livre,
                                min(passos) - phi_i / 10.0, livre_radial)


def _montar_retangular(secao: SecaoPilar, recuo: float, phi: float,
                       area: float, nx: int, ny: int) -> Arranjo:
    nx = max(int(nx), 2)
    ny = max(int(ny), 2)
    lx, ly = geo.encolher_retangulo(secao.hx, secao.hy, recuo)
    if lx <= 0 or ly <= 0:
        return Arranjo(phi=phi, nx=nx, ny=ny, recuo=recuo, cabe=False,
                       avisos=[av.erro(
                           f"O recuo de {num(recuo, 2)} cm consome a seção "
                           f"{secao.descricao()}: não sobra linha de armadura. "
                           f"Reduza o cobrimento, o estribo ou a bitola.")])
    pontos = geo.distribuir_no_perimetro(lx, ly, nx, ny)
    barras = [Barra(x, y, area, phi) for x, y in pontos]
    arr = Arranjo(barras=barras, phi=phi, nx=nx, ny=ny, recuo=recuo,
                  d_linha_x=recuo, d_linha_y=recuo)
    passo_x = lx / (nx - 1) if nx > 1 else lx
    passo_y = ly / (ny - 1) if ny > 1 else ly
    arr.espacamento_eixos = max(passo_x, passo_y)
    arr.espacamento_livre = min(passo_x, passo_y) - phi / 10.0
    return arr


def _montar_circular(secao: SecaoPilar, recuo: float, phi: float,
                     area: float, n: int) -> Arranjo:
    n = max(int(n), BARRAS_MINIMAS_CIRCULAR)
    d = secao.diametro - 2.0 * recuo
    if d <= 0:
        return Arranjo(phi=phi, recuo=recuo, cabe=False, avisos=[av.erro(
            f"O recuo de {num(recuo, 2)} cm consome a seção circular de "
            f"ø{num(secao.diametro)} cm.")])
    pontos = geo.distribuir_na_circunferencia(d, n, math.pi / 2.0)
    barras = [Barra(x, y, area, phi) for x, y in pontos]
    arr = Arranjo(barras=barras, phi=phi, recuo=recuo, d_linha_x=recuo,
                  d_linha_y=recuo)
    # Numa distribuição circular a "camada" da flexão é uma só barra por
    # ponta; nx e ny servem apenas de contagem para o relatório.
    arr.nx = arr.ny = n
    corda = d * math.sin(math.pi / n)
    arr.espacamento_eixos = corda
    arr.espacamento_livre = corda - phi / 10.0
    return arr


def _montar_contorno(secao: SecaoPilar, recuo: float, phi: float,
                     area: float, n: int) -> Arranjo:
    contorno = secao.contornos()[0]
    linha = geo.deslocar_para_dentro(contorno, recuo)
    if geo.area_poligono(linha) <= 0:
        return Arranjo(phi=phi, recuo=recuo, cabe=False, avisos=[av.erro(
            f"O recuo de {num(recuo, 2)} cm consome a seção "
            f"{secao.descricao()}.")])
    n = max(int(n), len(linha))
    pontos = geo.distribuir_no_contorno(linha, n)
    barras = [Barra(x, y, area, phi) for x, y in pontos]
    arr = Arranjo(barras=barras, phi=phi, recuo=recuo, d_linha_x=recuo,
                  d_linha_y=recuo)

    # Quais barras caem em vértice **convexo**: são as barras de canto do
    # item 18.2.4. A do vértice reentrante de uma L não conta -- ali o
    # estribo externo não abraça a barra, que flamba para a abertura do
    # "V"; é o mesmo critério do fecho convexo do modo lista de barras.
    orient = 1.0 if geo.area_poligono(linha) > 0 else -1.0
    m_l = len(linha)
    vertices = set()
    for i, (x, y) in enumerate(linha):
        xa, ya = linha[i - 1]
        xb, yb = linha[(i + 1) % m_l]
        cruz = (x - xa) * (yb - y) - (y - ya) * (xb - x)
        if cruz * orient > 1e-9:
            vertices.add((round(x, 6), round(y, 6)))
    arr.indices_vertices = [i for i, (x, y) in enumerate(pontos)
                            if (round(x, 6), round(y, 6)) in vertices]

    m = len(pontos)
    passos = []
    for i in range(m):
        x0, y0 = pontos[i]
        x1, y1 = pontos[(i + 1) % m]
        passos.append(math.hypot(x1 - x0, y1 - y0))
    arr.passos_contorno = passos

    xs = sorted({round(b.x, 6) for b in barras})
    ys = sorted({round(b.y, 6) for b in barras})
    arr.nx = sum(1 for b in barras if abs(b.y - ys[-1]) < 1e-6)
    arr.ny = sum(1 for b in barras if abs(b.x - xs[-1]) < 1e-6)
    arr.espacamento_eixos = max(passos) if passos else 0.0
    arr.espacamento_livre = (min(passos) if passos else 0.0) - phi / 10.0
    return arr


# ---------------------------------------------------------------------------
# Verificações do item 18.4.2
# ---------------------------------------------------------------------------

def bitola_maxima(secao: SecaoPilar) -> float:
    """Bitola máxima da armadura longitudinal, mm (item 18.4.2.1).

    ``phi <= 1/8`` da menor dimensão transversal. Numa seção L, T ou U a
    "menor dimensão transversal" é a espessura da parede, não a caixa: é ali
    que a barra tem de caber com cobrimento dos dois lados.
    """
    return secao.menor_dimensao * 10.0 / 8.0


def espacamento_livre_minimo(phi: float, dmax_agregado: float) -> float:
    """Espaçamento livre mínimo entre barras, cm (item 18.4.2.2).

    O maior entre 20 mm, a bitola da barra e 1,2 vez a dimensão máxima do
    agregado graúdo.
    """
    return max(ESPACAMENTO_LIVRE_MINIMO, phi / 10.0, 1.2 * dmax_agregado)


def espacamento_eixos_maximo(secao: SecaoPilar) -> float:
    """Espaçamento máximo entre eixos de barras, cm (item 18.4.2.2).

    Duas vezes a menor dimensão **do trecho**, limitado a 40 cm -- numa L,
    T, U ou vazada, a espessura da parede, não a caixa envolvente.
    """
    return min(2.0 * secao.menor_dimensao, ESPACAMENTO_EIXOS_MAXIMO)


def verificar(arr: Arranjo, pilar: Pilar, nu: float,
              As_necessaria: float) -> list[str]:
    """Confere o arranjo contra o item 18.4.2 e a taxa do item 17.3.5.3."""
    saida: list[str] = list(arr.avisos)
    secao = pilar.secao
    Ac = secao.area
    rho = arr.As / Ac if Ac > 0 else 0.0
    rho_min = rho_minimo(nu, pilar.concreto, pilar.aco)

    if arr.phi_min < 10.0 - 1e-9:
        saida.append(av.erro(
            f"Bitola longitudinal ø{num(arr.phi_min)} mm abaixo dos 10 mm que o "
            f"item 18.4.2.1 exige em pilar."))
    phi_max = bitola_maxima(secao)
    if arr.phi > phi_max + 1e-9:
        saida.append(av.erro(
            f"Bitola longitudinal ø{num(arr.phi)} mm acima de 1/8 da menor "
            f"dimensão transversal ({num(phi_max, 1)} mm), contra o item "
            f"18.4.2.1."))

    if rho < rho_min - 1e-9:
        saida.append(av.erro(
            f"Taxa de armadura ρ = {num(rho * 100, 3)} % abaixo da mínima de "
            f"{num(rho_min * 100, 3)} % do item 17.3.5.3.1 "
            f"(0,15 ν fcd/fyd >= 0,4 %, com ν = {num(nu, 3)})."))
    if rho > RHO_MAXIMO_CORRENTE + 1e-9:
        saida.append(av.erro(
            f"Taxa de armadura ρ = {num(rho * 100, 2)} % acima dos "
            f"{num(RHO_MAXIMO_CORRENTE * 100)} % da seção corrente (item "
            f"17.3.5.3.2). Aumente a seção ou a classe do concreto."))
    if 2.0 * rho > RHO_MAXIMO_EMENDA + 1e-9:
        saida.append(av.erro(
            f"Na região de emenda por traspasse, com todas as barras emendadas "
            f"no mesmo nível, a taxa dobra para {num(rho * 200, 2)} %, acima "
            f"dos {num(RHO_MAXIMO_EMENDA * 100)} % do item 17.3.5.3.2."))

    if arr.As < As_necessaria - 1e-6:
        saida.append(av.erro(
            f"Armadura efetiva de {num(arr.As, 2)} cm² abaixo da necessária, "
            f"{num(As_necessaria, 2)} cm²."))

    s_min = espacamento_livre_minimo(arr.phi, pilar.ambiente.dmax_agregado)
    if arr.espacamento_livre < s_min - 1e-6:
        saida.append(av.erro(
            f"Espaçamento livre entre barras de "
            f"{num(arr.espacamento_livre, 1)} cm, abaixo do mínimo de "
            f"{num(s_min, 1)} cm do item 18.4.2.2 (o maior entre 2 cm, a bitola "
            f"ø{num(arr.phi)} mm e 1,2 vez o agregado de "
            f"{num(pilar.ambiente.dmax_agregado)} cm)."))
    s_max = espacamento_eixos_maximo(secao)
    if arr.espacamento_eixos > s_max + 1e-6:
        saida.append(av.erro(
            f"Espaçamento entre eixos de barras de "
            f"{num(arr.espacamento_eixos, 1)} cm, acima do máximo de "
            f"{num(s_max, 1)} cm do item 18.4.2.2 (duas vezes a menor dimensão, "
            f"no máximo 40 cm). Acrescente barras nas faces."))

    c_min = pilar.ambiente.cobrimento_minimo(arr.phi, arr.phi_estribo)
    if arr.cobrimento < c_min - 1e-9:
        saida.append(av.erro(
            f"Cobrimento de {num(arr.cobrimento)} cm abaixo do mínimo de "
            f"{num(c_min, 2)} cm exigido pelo item 7.4.7: governa "
            f"{pilar.ambiente.governante(arr.phi, arr.phi_estribo)}."))

    if secao.tipo in ("circular", "circular vazada"):
        if arr.n_barras < BARRAS_MINIMAS_CIRCULAR:
            saida.append(av.erro(
                f"Seção circular com {arr.n_barras} barras; o item 18.4.2.2 "
                f"exige no mínimo {BARRAS_MINIMAS_CIRCULAR} distribuídas ao "
                f"longo do perímetro."))
    else:
        vertices = len(secao.contornos()[0])
        if arr.n_barras < vertices:
            saida.append(av.erro(
                f"A seção tem {vertices} vértices e só {arr.n_barras} barras; "
                f"o item 18.4.2.2 exige pelo menos uma barra em cada vértice "
                f"de seção poligonal."))
    return saida


# ---------------------------------------------------------------------------
# Busca do arranjo mais econômico
# ---------------------------------------------------------------------------

#: Peso do número de barras no custo de um arranjo. Ver :func:`custo`.
PESO_POR_BARRA = 0.02


def custo(phi: float, n: int, secao: SecaoPilar, nx: int = 0,
          ny: int = 0) -> tuple[float, float]:
    """Custo comparativo de um arranjo, e o desempate.

    Ordenar só pela área de aço leva a detalhes que ninguém executa: numa
    seção apertada, 28 ø10 tem menos área que 8 ø20 e ganharia -- com 28
    barras a amarrar, quatro grampos suplementares por nível e o espaçamento
    livre no limite. O aço é o que se paga por quilo, mas a barra é o que se
    paga por corte, dobra, posicionamento e amarração.

    O custo é ``As (1 + 0,02 n)``: 2 % de acréscimo por barra. É o suficiente
    para que 8 ø20 (25,1 cm², 8 barras) ganhe de 28 ø10 (22,0 cm², 28 barras)
    e para que 12 ø16 ganhe de 18 ø12,5 -- sem chegar a favorecer o extremo
    oposto, 4 ø40 em tudo.

    O desempate premia o arranjo de espaçamento mais **uniforme** nas duas
    direções, ``|hx/(nx-1) - hy/(ny-1)|``: entre 8 barras dispostas 3x3 e as
    mesmas 8 dispostas 2x4 numa seção quadrada, a primeira distribui melhor a
    armadura e é a que se desenha.
    """
    area = n * area_barra(phi)
    principal = area * (1.0 + PESO_POR_BARRA * n)
    if nx > 1 and ny > 1:
        desempate = abs(secao.hx / (nx - 1) - secao.hy / (ny - 1))
    else:
        desempate = 0.0
    return principal, desempate


def candidatos(secao: SecaoPilar, bitolas: tuple[float, ...],
               max_por_face: int = 12) -> list[tuple[float, int, int, int]]:
    """Arranjos candidatos ``(phi, nx, ny, n)``, do mais barato ao mais caro.

    A ordem é a de :func:`custo`, de modo que o primeiro candidato que passa
    em todas as verificações é o escolhido -- não é preciso avaliar o resto.
    """
    saida: list[tuple[float, int, int, int]] = []
    phi_max = bitola_maxima(secao)
    for phi in bitolas:
        if phi > phi_max + 1e-9 or phi < 10.0 - 1e-9:
            continue
        if secao.tipo == "retangular":
            for nx in range(2, max_por_face + 1):
                for ny in range(2, max_por_face + 1):
                    n = 2 * nx + 2 * ny - 4
                    saida.append((phi, nx, ny, n))
        elif secao.tipo in ("circular", "circular vazada"):
            for n in range(BARRAS_MINIMAS_CIRCULAR, 4 * max_por_face + 1):
                saida.append((phi, 0, 0, n))
        else:
            vertices = len(secao.contornos()[0])
            for n in range(vertices, 6 * max_por_face + 1):
                saida.append((phi, 0, 0, n))
    saida.sort(key=lambda t: custo(t[0], t[3], secao, t[1], t[2]))
    return saida
