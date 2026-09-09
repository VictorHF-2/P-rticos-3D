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
                        RHO_MAXIMO, area_barra, massa_linear, rho_minimo)
from .modelo import Pilar, SecaoPilar
from .seccional import Barra

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

    def barras_por_camada(self, direcao: str) -> int:
        """Barras na camada extrema da direção pedida.

        É o que o modelo de duas camadas chama de ``As1``/``As2``: as barras
        que ficam na face mais afastada do centro na direção da flexão. Numa
        seção retangular com ``nx`` por face horizontal e ``ny`` por face
        vertical, a flexão em x tem ``ny`` barras por camada.
        """
        return self.ny if direcao == "x" else self.nx

    def descricao(self) -> str:
        return f"{self.n_barras} ø{self.phi:g} mm ({self.As:.2f} cm²)"


# ---------------------------------------------------------------------------
# Recuo do contorno até o eixo da barra
# ---------------------------------------------------------------------------

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

def montar(secao: SecaoPilar, cobrimento: float, phi_estribo: float,
           phi: float, nx: int = 0, ny: int = 0, n: int = 0) -> Arranjo:
    """Monta o arranjo de barras da seção.

    ``nx`` e ``ny`` valem na seção retangular -- barras por face horizontal e
    por face vertical, cantos incluídos. Nas demais vale ``n``, o total.
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
    return arr


def _montar_retangular(secao: SecaoPilar, recuo: float, phi: float,
                       area: float, nx: int, ny: int) -> Arranjo:
    nx = max(int(nx), 2)
    ny = max(int(ny), 2)
    lx, ly = geo.encolher_retangulo(secao.hx, secao.hy, recuo)
    if lx <= 0 or ly <= 0:
        return Arranjo(phi=phi, nx=nx, ny=ny, recuo=recuo, cabe=False,
                       avisos=[av.erro(
                           f"O recuo de {recuo:.2f} cm consome a seção "
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
            f"O recuo de {recuo:.2f} cm consome a seção circular de "
            f"ø{secao.diametro:g} cm.")])
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
            f"O recuo de {recuo:.2f} cm consome a seção "
            f"{secao.descricao()}.")])
    n = max(int(n), len(linha))
    pontos = geo.distribuir_no_contorno(linha, n)
    barras = [Barra(x, y, area, phi) for x, y in pontos]
    arr = Arranjo(barras=barras, phi=phi, recuo=recuo, d_linha_x=recuo,
                  d_linha_y=recuo)

    # Quais barras caem em vértice: são as barras de canto do item 18.2.4.
    vertices = {(round(x, 6), round(y, 6)) for x, y in linha}
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

    Duas vezes a menor dimensão do trecho, limitado a 40 cm.
    """
    return min(2.0 * min(secao.hx, secao.hy), ESPACAMENTO_EIXOS_MAXIMO)


def verificar(arr: Arranjo, pilar: Pilar, nu: float,
              As_necessaria: float) -> list[str]:
    """Confere o arranjo contra o item 18.4.2 e a taxa do item 17.3.5.3."""
    saida: list[str] = list(arr.avisos)
    secao = pilar.secao
    Ac = secao.area
    rho = arr.As / Ac if Ac > 0 else 0.0
    rho_min = rho_minimo(nu, pilar.concreto, pilar.aco)

    if arr.phi < 10.0 - 1e-9:
        saida.append(av.erro(
            f"Bitola longitudinal ø{arr.phi:g} mm abaixo dos 10 mm que o item "
            f"18.4.2.1 exige em pilar."))
    phi_max = bitola_maxima(secao)
    if arr.phi > phi_max + 1e-9:
        saida.append(av.erro(
            f"Bitola longitudinal ø{arr.phi:g} mm acima de 1/8 da menor "
            f"dimensão transversal ({phi_max:.1f} mm), contra o item "
            f"18.4.2.1."))

    if rho < rho_min - 1e-9:
        saida.append(av.erro(
            f"Taxa de armadura rho = {rho * 100:.3f} % abaixo da mínima de "
            f"{rho_min * 100:.3f} % do item 17.3.5.3.1 "
            f"(0,15 nu fcd/fyd >= 0,4 %, com nu = {nu:.3f})."))
    if rho > RHO_MAXIMO + 1e-9:
        saida.append(av.erro(
            f"Taxa de armadura rho = {rho * 100:.2f} % acima dos "
            f"{RHO_MAXIMO * 100:g} % do item 17.3.5.3.2. O limite vale para a "
            f"seção real e **inclui a sobreposição na região de emenda**, de "
            f"modo que na prática o lance deve ficar bem abaixo dele."))
    elif rho > RHO_MAXIMO / 2.0:
        saida.append(av.construtivo(
            f"Taxa de armadura rho = {rho * 100:.2f} %: na emenda por "
            f"traspasse ela dobra para {rho * 200:.2f} %, e o item 17.3.5.3.2 "
            f"conta a emenda dentro dos {RHO_MAXIMO * 100:g} %. Verifique o "
            f"escalonamento das emendas ou aumente a seção."))

    if arr.As < As_necessaria - 1e-6:
        saida.append(av.erro(
            f"Armadura efetiva de {arr.As:.2f} cm² abaixo da necessária, "
            f"{As_necessaria:.2f} cm²."))

    s_min = espacamento_livre_minimo(arr.phi, pilar.ambiente.dmax_agregado)
    if arr.espacamento_livre < s_min - 1e-6:
        saida.append(av.erro(
            f"Espaçamento livre entre barras de "
            f"{arr.espacamento_livre:.1f} cm, abaixo do mínimo de "
            f"{s_min:.1f} cm do item 18.4.2.2 (o maior entre 2 cm, a bitola "
            f"ø{arr.phi:g} mm e 1,2 vez o agregado de "
            f"{pilar.ambiente.dmax_agregado:g} cm)."))
    s_max = espacamento_eixos_maximo(secao)
    if arr.espacamento_eixos > s_max + 1e-6:
        saida.append(av.erro(
            f"Espaçamento entre eixos de barras de "
            f"{arr.espacamento_eixos:.1f} cm, acima do máximo de "
            f"{s_max:.1f} cm do item 18.4.2.2 (duas vezes a menor dimensão, "
            f"no máximo 40 cm). Acrescente barras nas faces."))

    c_min = pilar.ambiente.cobrimento_minimo(arr.phi, arr.phi_estribo)
    if arr.cobrimento < c_min - 1e-9:
        saida.append(av.erro(
            f"Cobrimento de {arr.cobrimento:g} cm abaixo do mínimo de "
            f"{c_min:.2f} cm exigido pelo item 7.4.7: governa "
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
