# -*- coding: utf-8 -*-
"""
geometria.py
Geometria da seção transversal do pilar: contorno poligonal, propriedades da
seção bruta e as posições em que as barras podem ser alojadas.

Convenção de eixos, válida em todo o programa:

    x ..... horizontal, para a direita;
    y ..... vertical, para cima;
    origem no **centro de gravidade da seção bruta**.

E a convenção de nomes dos momentos, que é a da prática brasileira e a da
planilha de referência -- não a do produto vetorial:

    ``Mx`` é o momento que desloca a resultante normal **na direção x**,
    e portanto flexiona a seção segundo a altura ``hx``. Em notação vetorial
    seria um momento em torno do eixo y; chamá-lo de ``Mx`` é o que casa com
    ``ex = Mx/N`` e com as abas ``Dim,xx`` da planilha.

Todas as dimensões em centímetros. Funções puras, sem dependência de
interface gráfica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Número de lados do polígono que substitui o círculo na integração.
LADOS_CIRCULO = 72

Ponto = tuple[float, float]
Poligono = list[Ponto]


# ---------------------------------------------------------------------------
# Propriedades de um polígono
# ---------------------------------------------------------------------------

def area_poligono(pol: Poligono) -> float:
    """Área do polígono pela fórmula do shoelace, com sinal.

    Positiva quando os vértices estão no sentido anti-horário. O sinal é o que
    permite descrever um furo -- basta percorrê-lo no sentido inverso -- e é
    por isso que a função não devolve o módulo.
    """
    soma = 0.0
    n = len(pol)
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        soma += x0 * y1 - x1 * y0
    return soma / 2.0


def centroide_poligono(pol: Poligono) -> Ponto:
    """Centro de gravidade do polígono."""
    a = area_poligono(pol)
    if abs(a) < 1e-12:
        n = max(len(pol), 1)
        return (sum(p[0] for p in pol) / n, sum(p[1] for p in pol) / n)
    cx = cy = 0.0
    n = len(pol)
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        f = x0 * y1 - x1 * y0
        cx += (x0 + x1) * f
        cy += (y0 + y1) * f
    return (cx / (6.0 * a), cy / (6.0 * a))


def inercias_poligono(pol: Poligono) -> tuple[float, float, float]:
    """Momentos de inércia ``(Ixx, Iyy, Ixy)`` em relação à origem, cm⁴.

    ``Ixx`` é o momento de inércia para flexão **na direção y** (integral de
    y² dA) e ``Iyy`` o da flexão na direção x. Note que isso é o oposto da
    convenção de nomes dos momentos descrita no cabeçalho: aqui manda a
    integral, ali manda a direção da excentricidade. As funções de alto nível
    :func:`propriedades` devolvem os dois já casados com a direção.
    """
    ixx = iyy = ixy = 0.0
    n = len(pol)
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        f = x0 * y1 - x1 * y0
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * f
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * f
        ixy += (x0 * y1 + 2.0 * x0 * y0 + 2.0 * x1 * y1 + x1 * y0) * f
    return ixx / 12.0, iyy / 12.0, ixy / 24.0


def transladar(pol: Poligono, dx: float, dy: float) -> Poligono:
    return [(x + dx, y + dy) for x, y in pol]


def limites(pol: Poligono) -> tuple[float, float, float, float]:
    """Caixa envolvente ``(x_min, x_max, y_min, y_max)``."""
    xs = [p[0] for p in pol]
    ys = [p[1] for p in pol]
    return min(xs), max(xs), min(ys), max(ys)


def dentro(pol: Poligono, x: float, y: float) -> bool:
    """Teste do ponto no polígono pelo número de cruzamentos."""
    dentro_ = False
    n = len(pol)
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xi:
                dentro_ = not dentro_
    return dentro_


def retangulo(largura: float, altura: float, cx: float = 0.0,
              cy: float = 0.0, horario: bool = False) -> Poligono:
    """Retângulo centrado em ``(cx, cy)``, no sentido anti-horário.

    ``horario=True`` devolve o mesmo retângulo no sentido inverso -- é o que
    o furo de uma seção vazada precisa, para que sua área entre negativa na
    soma (mesma convenção de :func:`circulo`).
    """
    a, b = largura / 2.0, altura / 2.0
    pontos = [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy + b),
              (cx - a, cy + b)]
    return list(reversed(pontos)) if horario else pontos


def circulo(diametro: float, cx: float = 0.0, cy: float = 0.0,
            lados: int = LADOS_CIRCULO, horario: bool = False) -> Poligono:
    """Polígono regular inscrito num círculo, com a área corrigida.

    O polígono de ``n`` lados inscrito tem área ``sin(theta) cos(theta)/theta``
    vezes a do círculo, com ``theta = pi/n``; o raio é ampliado pelo inverso da
    raiz desse fator para que a área saia exata. Sem isso, um pilar circular
    perderia 0,1 % de concreto na integração -- pouco, mas é erro sistemático
    e sempre contra a segurança no lado da compressão.
    """
    r = diametro / 2.0
    theta = math.pi / lados
    if lados > 2:
        r *= math.sqrt(theta / (math.sin(theta) * math.cos(theta)))
    passo = 2.0 * math.pi / lados
    pontos = [(cx + r * math.cos(i * passo), cy + r * math.sin(i * passo))
              for i in range(lados)]
    return list(reversed(pontos)) if horario else pontos


# ---------------------------------------------------------------------------
# Propriedades da seção bruta
# ---------------------------------------------------------------------------

@dataclass
class Propriedades:
    """Propriedades da seção bruta, já casadas com a direção da flexão."""

    area: float                  # cm²
    cx: float                    # cm, centroide em relação ao contorno dado
    cy: float
    Ix: float                    # cm⁴, inércia para a flexão na direção x
    Iy: float                    # cm⁴, inércia para a flexão na direção y
    Ixy: float                   # cm⁴, produto de inércia
    hx: float                    # cm, extensão da seção na direção x
    hy: float                    # cm, extensão da seção na direção y

    @property
    def ix(self) -> float:
        """Raio de giração para a flexão na direção x, cm."""
        return math.sqrt(self.Ix / self.area) if self.area > 0 else 0.0

    @property
    def iy(self) -> float:
        return math.sqrt(self.Iy / self.area) if self.area > 0 else 0.0

    @property
    def simetrica(self) -> bool:
        """Verdadeiro quando os eixos x e y são principais de inércia."""
        ref = max(abs(self.Ix), abs(self.Iy), 1.0)
        return abs(self.Ixy) / ref < 1e-6

    def inercia_na_direcao(self, phi: float) -> float:
        """Inércia para a flexão na direção ``(cos phi, sin phi)``, cm⁴:
        ``∫ (x cos phi + y sin phi)² dA`` -- a mesma convenção de ``Ix``
        (flexão na direção x) e ``Iy``."""
        c, s = math.cos(phi), math.sin(phi)
        return self.Ix * c * c + self.Iy * s * s + 2.0 * self.Ixy * s * c

    def principais(self) -> tuple[float, float, float]:
        """``(I1, I2, phi1)``: inércias principais (I1 >= I2), cm⁴, e a
        direção de flexão da maior, rad, medida a partir de x. A menor é a
        direção ``phi1 + pi/2``. ``tan 2 phi = 2 Ixy / (Ix - Iy)``."""
        phi1 = 0.5 * math.atan2(2.0 * self.Ixy, self.Ix - self.Iy)
        media = (self.Ix + self.Iy) / 2.0
        raio = math.hypot((self.Ix - self.Iy) / 2.0, self.Ixy)
        return media + raio, media - raio, phi1


def propriedades(contornos: list[Poligono], hx: float | None = None,
                 hy: float | None = None) -> Propriedades:
    """Propriedades da seção bruta descrita por um ou mais contornos.

    O primeiro contorno é o externo; os seguintes, percorridos no sentido
    inverso, são furos. A saída já vem referida ao centro de gravidade.

    ``hx`` e ``hy`` permitem impor as dimensões **nominais** da seção em vez
    de medi-las na caixa envolvente. Existem por causa do círculo: o polígono
    que o substitui é circunscrito por construção -- o raio foi ampliado para
    acertar a área --, e a caixa envolvente dele daria 40,03 cm num pilar de
    40 cm. Essa diferença entraria em ``lambda = 3,46 le/h`` e na
    excentricidade mínima, onde não tem o que fazer.
    """
    area = sum(area_poligono(p) for p in contornos)
    if abs(area) < 1e-9:
        raise ValueError("A seção tem área nula.")
    sx = sy = 0.0
    for p in contornos:
        a = area_poligono(p)
        c = centroide_poligono(p)
        sx += a * c[0]
        sy += a * c[1]
    cx, cy = sx / area, sy / area

    ixx = iyy = ixy = 0.0
    for p in contornos:
        pxx, pyy, pxy = inercias_poligono(transladar(p, -cx, -cy))
        ixx += pxx
        iyy += pyy
        ixy += pxy

    x_min, x_max, y_min, y_max = limites(contornos[0])
    # Ix é a inércia da flexão na direção x, isto é, a integral de x² dA.
    return Propriedades(area=area, cx=cx, cy=cy, Ix=iyy, Iy=ixx, Ixy=ixy,
                        hx=x_max - x_min if hx is None else hx,
                        hy=y_max - y_min if hy is None else hy)


# ---------------------------------------------------------------------------
# Perímetro útil para distribuir barras
# ---------------------------------------------------------------------------

def encolher_retangulo(hx: float, hy: float, recuo: float
                       ) -> tuple[float, float]:
    """Dimensões do retângulo das barras, recuadas de ``recuo`` em cada face."""
    return max(hx - 2.0 * recuo, 0.0), max(hy - 2.0 * recuo, 0.0)


def distribuir_no_perimetro(hx: float, hy: float, nx: int, ny: int
                            ) -> list[Ponto]:
    """Barras no perímetro de um retângulo ``hx`` por ``hy``.

    ``nx`` é o número de barras em **cada** face horizontal (as de cima e as
    de baixo, cantos incluídos) e ``ny`` o número em cada face vertical, também
    com os cantos. O total é ``2 nx + 2 ny - 4``: os quatro cantos pertencem às
    duas faces e são contados uma vez só.
    """
    nx = max(int(nx), 2)
    ny = max(int(ny), 2)
    ax, ay = hx / 2.0, hy / 2.0
    pontos: list[Ponto] = []
    passo_x = hx / (nx - 1) if nx > 1 else 0.0
    passo_y = hy / (ny - 1) if ny > 1 else 0.0
    for i in range(nx):                      # face inferior e superior
        x = -ax + i * passo_x
        pontos.append((x, -ay))
        pontos.append((x, ay))
    for j in range(1, ny - 1):               # laterais, sem repetir os cantos
        y = -ay + j * passo_y
        pontos.append((-ax, y))
        pontos.append((ax, y))
    return pontos


def distribuir_na_circunferencia(diametro: float, n: int,
                                 fase: float = 0.0) -> list[Ponto]:
    """``n`` barras igualmente espaçadas numa circunferência de ``diametro``.

    O item 18.4.2.2 exige no mínimo seis barras em seção circular; quem
    verifica isso é o módulo de arranjo, porque aqui ainda não se sabe se a
    circunferência é a do pilar ou a de um furo.
    """
    n = max(int(n), 1)
    r = diametro / 2.0
    passo = 2.0 * math.pi / n
    return [(r * math.cos(fase + i * passo), r * math.sin(fase + i * passo))
            for i in range(n)]


def perimetro_poligono(pol: Poligono) -> float:
    total = 0.0
    n = len(pol)
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def distribuir_no_contorno(pol: Poligono, n: int) -> list[Ponto]:
    """``n`` barras espaçadas ao longo do contorno poligonal fechado.

    Usada nas seções L, T e U, em que não há "faces" no sentido do retângulo:
    as barras seguem o perímetro da linha de armadura, sempre havendo uma em
    cada vértice, como exige o item 18.4.2.2. As barras que sobram depois dos
    vértices são repartidas entre os lados na proporção do comprimento de cada
    um, de modo que o espaçamento saia parecido em todo o contorno.

    A saída vem em **ordem de percurso**: barra após barra ao longo do
    contorno. Não é detalhe de arrumação -- é o que permite medir o
    espaçamento entre barras vizinhas simplesmente percorrendo a lista, e o
    espaçamento entre eixos é limitado pelo item 18.4.2.2.
    """
    n = max(int(n), len(pol))
    m = len(pol)
    lados = []
    total = 0.0
    for i in range(m):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % m]
        c = math.hypot(x1 - x0, y1 - y0)
        lados.append(((x0, y0), (x1, y1), c))
        total += c
    if total <= 0.0:
        return [tuple(p) for p in pol]

    restantes = n - m
    inteiras = [0] * m
    if restantes > 0:
        quotas = [restantes * c / total for *_, c in lados]
        inteiras = [int(q) for q in quotas]
        sobra = restantes - sum(inteiras)
        ordem = sorted(range(m), key=lambda i: quotas[i] - inteiras[i],
                       reverse=True)
        for i in ordem[:sobra]:
            inteiras[i] += 1

    pontos: list[Ponto] = []
    for (p0, p1, _), k in zip(lados, inteiras):
        pontos.append((p0[0], p0[1]))               # o vértice
        for j in range(1, k + 1):
            t = j / (k + 1)
            pontos.append((p0[0] + t * (p1[0] - p0[0]),
                           p0[1] + t * (p1[1] - p0[1])))
    return pontos


def deslocar_para_dentro(pol: Poligono, recuo: float) -> Poligono:
    """Polígono paralelo a ``pol``, recuado ``recuo`` para dentro.

    Cada aresta é deslocada pela sua normal interior e as arestas vizinhas são
    reintersectadas. Serve para achar a linha de armadura das seções L, T e U:
    o recuo é cobrimento mais estribo mais meia bitola, e o resultado é o
    contorno em que as barras podem morar, com o vértice reentrante do L caindo
    no lugar certo -- que é o que um simples encolhimento em escala não daria.

    Pressupõe contorno simples percorrido no sentido anti-horário. Arestas
    quase paralelas são resolvidas pelo ponto médio dos dois deslocamentos, em
    vez de pela interseção, que ali é numericamente instável.
    """
    n = len(pol)
    if n < 3 or recuo == 0.0:
        return list(pol)
    if area_poligono(pol) < 0:
        pol = list(reversed(pol))
    retas: list[tuple[float, float, float]] = []      # a x + b y = c
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        c = math.hypot(dx, dy)
        if c < 1e-12:
            retas.append((0.0, 0.0, 0.0))
            continue
        nx, ny = -dy / c, dx / c                      # normal interior (CCW)
        retas.append((nx, ny, nx * x0 + ny * y0 + recuo))

    saida: Poligono = []
    for i in range(n):
        a1, b1, c1 = retas[i - 1]
        a2, b2, c2 = retas[i]
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-9:
            px, py = pol[i]
            saida.append((px + (a1 + a2) / 2.0 * recuo,
                          py + (b1 + b2) / 2.0 * recuo))
        else:
            saida.append(((c1 * b2 - c2 * b1) / det,
                          (a1 * c2 - a2 * c1) / det))
    return saida


def recortar_semiplano(pol: Poligono, cos_t: float, sin_t: float,
                       limite: float, manter_acima: bool) -> Poligono:
    """Recorta o polígono pelo semiplano ``u >= limite`` (ou ``u <= limite``),
    com ``u = x cos(t) + y sin(t)``.

    Algoritmo de Sutherland-Hodgman. O contorno de entrada pode ser côncavo:
    nesse caso a saída ganha arestas espúrias apoiadas sobre a própria reta de
    corte, mas elas têm contribuição nula na área e nos momentos estáticos, que
    é o que se extrai de um contorno recortado (seja por faixas, seja pela
    integração de Green). Para contornos convexos a saída é o polígono
    recortado, sem ressalva.
    """
    if not pol:
        return []
    saida: Poligono = []
    n = len(pol)
    sinal = 1.0 if manter_acima else -1.0
    for i in range(n):
        x0, y0 = pol[i]
        x1, y1 = pol[(i + 1) % n]
        d0 = sinal * (x0 * cos_t + y0 * sin_t - limite)
        d1 = sinal * (x1 * cos_t + y1 * sin_t - limite)
        if d0 >= 0.0:
            saida.append((x0, y0))
        if (d0 > 0.0 > d1) or (d0 < 0.0 < d1):
            t = d0 / (d0 - d1)
            saida.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
    return saida


def ponto_no_poligono(x: float, y: float, poligono: Poligono) -> bool:
    """Ponto dentro do polígono (regra par-ímpar)."""
    dentro = False
    n = len(poligono)
    for i in range(n):
        x0, y0 = poligono[i]
        x1, y1 = poligono[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xc:
                dentro = not dentro
    return dentro


def distancia_ao_contorno(x: float, y: float, poligono: Poligono) -> float:
    """Menor distância do ponto aos lados do polígono, cm."""
    melhor = float("inf")
    n = len(poligono)
    for i in range(n):
        x0, y0 = poligono[i]
        x1, y1 = poligono[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / L2))
        melhor = min(melhor, math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)))
    return melhor
