# -*- coding: utf-8 -*-
"""
seccional.py
Motor seccional geral: equilíbrio de uma seção de concreto armado de contorno
poligonal qualquer, com as barras nas posições em que de fato estão, sob
flexão composta oblíqua no estado-limite último.

É o módulo que responde à pergunta que o roteiro dos casos fechados não sabe
responder: *dada esta armadura, qual é o momento resistente nesta direção?*
Ele integra o diagrama parábola-retângulo do item 8.2.10.1 sobre a área
comprimida e soma a contribuição de cada barra com a deformação que ela tem --
não com a de uma camada média.

Convenções deste módulo, e só dele:

    ``eps`` .... positiva na **compressão**, em ‰. É a convenção do diagrama
                 do concreto, e adotá-la aqui evita trocar de sinal a cada
                 linha; a conversão para o aço fica dentro de :func:`_sigma_s`.
    ``u`` ...... coordenada ao longo da normal à linha neutra, cm, crescente
                 no sentido da compressão. ``u = x cos(theta) + y sin(theta)``.
    ``Mx`` ..... ``integral de sigma . x dA``, de modo que ``ex = Mx/N``.
                 Mesma convenção do resto do programa.

Método de integração: fatiamento em faixas paralelas à linha neutra. Cada
faixa é obtida recortando o contorno por dois semiplanos, o que dá a área e o
centroide **exatos** da faixa; a tensão dentro dela é avaliada no centroide.
O erro é o da variação de ``sigma`` dentro da faixa, e cai com o quadrado da
espessura -- com 160 faixas ele é da ordem de 10^-5 da resultante.

Este **não** é o método do Teorema de Gauss-Green com integração analítica
por trapézios de CADAMURO JÚNIOR (1997, "Dimensionamento de pilares esbeltos
de concreto armado com seção qualquer solicitados por flexão composta
oblíqua", TCC EESC-USP, sistema FLEXOR), que resolve a mesma integral de
superfície em forma **fechada** e sem erro de discretização algum. O
fatiamento aqui adotado converge para o mesmo resultado -- e a conferência
correspondente no autoteste testa exatamente essa convergência --, só que
numericamente. A referência importa mais na busca de direção, adiante: o
item 5.5 daquele trabalho é dedicado a um problema que o fatiamento por si só
não resolve -- **quantos** estados de equilíbrio produzem momento resistente
numa direção pedida (zero, um ou dois, conforme a seção e a força normal) --,
e é o algoritmo de lá que :func:`estados_na_direcao` segue.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from . import geometria as geo
from . import green
from .materiais import Aco, Concreto

#: Número de faixas em que a seção é fatiada na integração.
FATIAS = 160

#: Deformação máxima de tração no aço no ELU, ‰ (item 17.2.2).
EPS_S_MAXIMA = 10.0

#: Tolerância relativa das buscas por bisseção.
TOL = 1e-9


#: Recorte de polígono por semiplano -- mora em geometria.py por ser função
#: puramente geométrica, sem nada de seccional; reexportado aqui porque o
#: resto deste módulo o chama sem prefixo desde antes de ele se mudar.
recortar = geo.recortar_semiplano


# ---------------------------------------------------------------------------
# Barras e seção discretizada
# ---------------------------------------------------------------------------

@dataclass
class Barra:
    """Uma barra longitudinal na posição em que está, coordenadas do CG."""

    x: float
    y: float
    area: float                  # cm²
    phi: float = 0.0             # mm, só para o desenho e o quantitativo
    rotulo: str = ""


@dataclass
class Faixa:
    """Uma faixa da integração: área e centroide exatos."""

    area: float
    x: float
    y: float
    u: float


class SecaoDiscreta:
    """Seção pronta para o equilíbrio: contornos, barras e materiais.

    As faixas dependem só da direção da linha neutra, e não da profundidade;
    por isso ficam em cache por ângulo. Uma varredura de 30 ângulos com 60
    profundidades cada custa 30 fatiamentos, e não 1800.
    """

    def __init__(self, contornos: list[geo.Poligono], barras: list[Barra],
                 concreto: Concreto, aco: Aco, fatias: int = FATIAS) -> None:
        self.contornos = contornos
        self.barras = barras
        self.concreto = concreto
        self.aco = aco
        self.n_fatias = fatias
        self._cache: dict[int, list[Faixa]] = {}
        self._arrays: dict[int, tuple] = {}
        #: Varredura grossa de ângulos de linha neutra por normal, para
        #: :func:`estados_na_direcao`: ela **não** depende da direção de
        #: momento procurada, só de ``N_alvo``. Ver a nota lá.
        self._amostras: dict[tuple, list[tuple[float, "Estado"]]] = {}
        #: Resultado de :func:`estados_na_direcao` por ``(N_alvo, alfa)``. Na
        #: varredura da altura com as duas direções amplificando juntas, a
        #: **direção** do momento é constante e só o módulo muda -- todos os
        #: pontos caem no mesmo ``alfa`` e a busca roda uma vez só.
        self._direcoes: dict[tuple, list["Estado"]] = {}
        #: ``MRd,xx`` / ``MRd,yy`` por ``(N_alvo, direção, sentido)``.
        self._uniaxial: dict[tuple, float] = {}
        #: Diagrama momento-curvatura por ``(N_alvo, alfa, pontos)``. É a
        #: conta mais cara do motor -- uma varredura de direção por curvatura
        #: -- e a figura que o consome é redesenhada a cada troca de aba e a
        #: cada exportação da memória; sem este cache, cada uma delas paga a
        #: conta inteira de novo.
        self._diagramas: dict[tuple, list["PontoMN"]] = {}
        self.propriedades = geo.propriedades(contornos)

    # -- geometria ----------------------------------------------------------
    @property
    def area_concreto(self) -> float:
        return self.propriedades.area

    @property
    def area_aco(self) -> float:
        return sum(b.area for b in self.barras)

    @property
    def taxa(self) -> float:
        """Taxa geométrica de armadura, fração da área bruta."""
        a = self.area_concreto
        return self.area_aco / a if a > 0 else 0.0

    def faixas(self, theta: float) -> list[Faixa]:
        """Faixas paralelas à linha neutra de direção ``theta``."""
        chave = int(round(theta * 1e9))
        if chave in self._cache:
            return self._cache[chave]
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        us = [x * cos_t + y * sin_t
              for pol in self.contornos for x, y in pol]
        u0, u1 = min(us), max(us)
        n = self.n_fatias
        passo = (u1 - u0) / n if n > 0 else 0.0
        saida: list[Faixa] = []
        for i in range(n):
            a = u0 + i * passo
            b = a + passo
            area = 0.0
            sx = sy = 0.0
            for pol in self.contornos:
                p = recortar(pol, cos_t, sin_t, a, True)
                p = recortar(p, cos_t, sin_t, b, False)
                if len(p) < 3:
                    continue
                ai = geo.area_poligono(p)
                if abs(ai) < 1e-12:
                    continue
                ci = geo.centroide_poligono(p)
                area += ai
                sx += ai * ci[0]
                sy += ai * ci[1]
            if abs(area) < 1e-12:
                continue
            x, y = sx / area, sy / area
            saida.append(Faixa(area=area, x=x, y=y,
                               u=x * cos_t + y * sin_t))
        self._cache[chave] = saida
        return saida

    def arrays(self, theta: float):
        """Faixas e barras como vetores ``numpy``, prontos para o equilíbrio.

        O equilíbrio é avaliado dezenas de vezes por bisseção e centenas por
        varredura de arranjo; em laço Python o custo aparece na interface. Os
        vetores dependem só da direção da linha neutra, e ficam em cache junto
        com as faixas.
        """
        chave = int(round(theta * 1e9))
        pronto = self._arrays.get(chave)
        if pronto is not None:
            return pronto
        f = self.faixas(theta)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        vazio = np.zeros(0)
        fa = np.array([x.area for x in f]) if f else vazio
        fx = np.array([x.x for x in f]) if f else vazio
        fy = np.array([x.y for x in f]) if f else vazio
        fu = np.array([x.u for x in f]) if f else vazio
        if self.barras:
            ba = np.array([b.area for b in self.barras])
            bx = np.array([b.x for b in self.barras])
            by = np.array([b.y for b in self.barras])
            bu = bx * cos_t + by * sin_t
        else:
            ba = bx = by = bu = vazio
        pronto = (fa, fx, fy, fu, ba, bx, by, bu)
        self._arrays[chave] = pronto
        return pronto

    def extremos(self, theta: float) -> tuple[float, float]:
        """Coordenadas ``u`` mínima e máxima do contorno de concreto."""
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        us = [x * cos_t + y * sin_t
              for pol in self.contornos for x, y in pol]
        return min(us), max(us)

    def u_barras(self, theta: float) -> list[float]:
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        return [b.x * cos_t + b.y * sin_t for b in self.barras]


# ---------------------------------------------------------------------------
# Diagrama de deformações do ELU
# ---------------------------------------------------------------------------

@dataclass
class Plano:
    """Plano de deformações no ELU, escrito em função de ``u``.

    ``eps(u) = eps_ref + k (u - u_ref)``, com ``eps`` em ‰ e ``k`` em ‰/cm.
    """

    eps_ref: float
    k: float
    u_ref: float
    dominio: str = ""
    x: float = 0.0               # profundidade da linha neutra, cm

    def eps(self, u: float) -> float:
        return self.eps_ref + self.k * (u - self.u_ref)


def plano_uls(secao: SecaoDiscreta, theta: float, x: float) -> Plano:
    """Plano de deformações do ELU para a linha neutra na profundidade ``x``.

    ``x`` é medido a partir da **fibra mais comprimida**, no sentido de ``u``
    decrescente. Os domínios saem dos três polos do item 17.2.2:

    ``x <= x_23``
        domínio 2, polo A: a barra mais tracionada está em 10 ‰.
    ``x_23 < x <= h``
        domínios 3, 4 e 4a, polo B: a fibra mais comprimida está em
        ``eps_cu``.
    ``x > h``
        domínio 5, polo C: a fibra a ``(1 - eps_c2/eps_cu) h`` da borda
        comprimida está em ``eps_c2``; é a reta que passa pelo ponto por onde
        todas as retas de compressão uniforme têm de passar.

    Com ``x <= 0`` a seção está toda tracionada -- domínio 1 --, e o plano é
    o de tração uniforme a 10 ‰, que é o limite que interessa.
    """
    c = secao.concreto
    u_min, u_max = secao.extremos(theta)
    h = u_max - u_min
    eps_cu = c.eps_cu_mil
    eps_c2 = c.eps_c2_mil

    ub = secao.u_barras(theta)
    u_traz = min(ub) if ub else u_min          # barra mais tracionada
    d = u_max - u_traz                          # altura útil na direção theta

    if x <= 1e-9:
        return Plano(eps_ref=-EPS_S_MAXIMA, k=0.0, u_ref=u_max,
                     dominio="1", x=max(x, 0.0))

    x_23 = d * eps_cu / (eps_cu + EPS_S_MAXIMA) if d > 0 else 0.0
    if x <= x_23:
        # polo A: 10 ‰ de tração na barra mais afastada
        k = EPS_S_MAXIMA / (d - x) if d > x else 0.0
        return Plano(eps_ref=k * x, k=k, u_ref=u_max, dominio="2", x=x)
    if x <= h:
        k = eps_cu / x
        dominio = "3/4" if x <= d else "4a"
        return Plano(eps_ref=eps_cu, k=k, u_ref=u_max, dominio=dominio, x=x)
    # polo C
    xc = h * (eps_cu - eps_c2) / eps_cu
    denom = x - xc
    k = eps_c2 / denom if abs(denom) > 1e-12 else 0.0
    return Plano(eps_ref=k * x, k=k, u_ref=u_max, dominio="5", x=x)


def _sigma_s(aco: Aco, eps_mil: float) -> float:
    """Tensão no aço, kN/cm², para ``eps`` **positiva na compressão**."""
    s = 1.0 if eps_mil >= 0 else -1.0
    return s * min(abs(eps_mil) * aco.Es_kNcm2 / 1000.0, aco.fyd_kNcm2)


# ---------------------------------------------------------------------------
# Equilíbrio
# ---------------------------------------------------------------------------

@dataclass
class Estado:
    """Resultante de um plano de deformações sobre a seção."""

    N: float                     # kN, positivo em compressão
    Mx: float                    # kN·cm, integral de sigma.x dA
    My: float                    # kN·cm
    plano: Plano
    theta: float
    eps_max: float = 0.0         # ‰, maior compressão
    eps_min: float = 0.0         # ‰, maior tração

    @property
    def M(self) -> float:
        return math.hypot(self.Mx, self.My)

    @property
    def alfa(self) -> float:
        """Direção do momento resultante, rad."""
        return math.atan2(self.My, self.Mx)


def _sigma_c_vetorial(c: Concreto, eps) -> "np.ndarray":
    """Diagrama parábola-retângulo do item 8.2.10.1, vetorizado.

    Compressão positiva; tração devolve zero, porque o concreto tracionado
    não entra no ELU de flexão composta.
    """
    fcd = c.alfa_c * c.fcd_kNcm2
    # ``maximum``/``minimum`` em vez de ``clip``: metade do custo de
    # despacho, e esta função roda dezenas de milhares de vezes por
    # lance (ver a nota em green._r).
    e = np.maximum(eps, 0.0)
    r = np.minimum(np.maximum(1.0 - e / c.eps_c2_mil, 0.0), 1.0)
    return np.where(e >= c.eps_c2_mil, fcd, fcd * (1.0 - r ** c.expoente_n))


def _sigma_s_vetorial(aco: Aco, eps) -> "np.ndarray":
    """Aço elastoplástico perfeito, vetorizado; compressão positiva."""
    return np.sign(eps) * np.minimum(np.abs(eps) * aco.Es_kNcm2 / 1000.0,
                                     aco.fyd_kNcm2)


def resultantes(secao: SecaoDiscreta, theta: float, x: float) -> Estado:
    """Resultantes ``(N, Mx, My)`` do plano de ELU com linha neutra em ``x``.

    Monta o plano do item 17.2.2 (:func:`plano_uls`) e equilibra a seção
    sobre ele (:func:`resultantes_de_plano`). Para um plano que **não**
    obedece à regra dos domínios -- uma curvatura de serviço qualquer, por
    exemplo --, use :func:`resultantes_de_plano` diretamente com um
    :class:`Plano` de :func:`plano_geral`.
    """
    return resultantes_de_plano(secao, theta, plano_uls(secao, theta, x))


def resultantes_de_plano(secao: SecaoDiscreta, theta: float,
                         plano: Plano) -> Estado:
    """Resultantes ``(N, Mx, My)`` de um plano de deformações qualquer.

    O concreto é integrado pelo Teorema de Green (:mod:`pilares.core.green`):
    a integral de superfície das tensões vira uma integral de linha ao longo
    do contorno, resolvida por quadratura de Gauss lado a lado -- sem fatiar
    a seção, e sem o erro de discretização que o fatiamento carregava. Cada
    barra entra com a sua própria deformação, **descontada** a área de
    concreto que ela ocupa: sem esse desconto a seção ganharia, em cada
    barra, uma área de concreto que não existe -- num pilar com 3 % de
    armadura são 3 % de compressão a mais, sempre contra a segurança.

    Perto da deformação uniforme (``|k|`` muito pequeno) a substituição que a
    integração de Green faz degenera, e o módulo cai de volta ao fatiamento
    em faixas -- convergente e correto, só que mais lento; esse regime não é
    alcançado pela bisseção de :func:`resolver_x` nem de
    :func:`resolver_estado` em uso normal.

    Esta função não sabe se ``plano`` respeita o ELU: serve tanto para
    :func:`plano_uls` (o limite de ruptura) quanto para uma curvatura de
    serviço qualquer, de :func:`plano_geral` -- é o mesmo equilíbrio de
    forças dos dois lados, muda só de onde o plano de deformações veio.
    """
    c, aco = secao.concreto, secao.aco
    fa, fx, fy, fu, ba, bx, by, bu = secao.arrays(theta)

    if abs(plano.k) >= green.K_MINIMO:
        N, Mx, My = green.resultantes_concreto(
            secao.contornos, c, theta, plano.eps_ref, plano.k, plano.u_ref)
        eps_max, eps_min = _extremos_eps(secao, theta, plano)
    else:
        N = Mx = My = 0.0
        eps_max, eps_min = -1e9, 1e9
        if fa.size:
            e = plano.eps_ref + plano.k * (fu - plano.u_ref)
            eps_max = max(eps_max, float(e.max()))
            eps_min = min(eps_min, float(e.min()))
            forca = _sigma_c_vetorial(c, e) * fa
            N += float(forca.sum())
            Mx += float((forca * fx).sum())
            My += float((forca * fy).sum())

    if ba.size:
        e = plano.eps_ref + plano.k * (bu - plano.u_ref)
        eps_max = max(eps_max, float(e.max()))
        eps_min = min(eps_min, float(e.min()))
        forca = (_sigma_s_vetorial(aco, e) - _sigma_c_vetorial(c, e)) * ba
        N += float(forca.sum())
        Mx += float((forca * bx).sum())
        My += float((forca * by).sum())

    return Estado(N=N, Mx=Mx, My=My, plano=plano, theta=theta,
                  eps_max=eps_max, eps_min=eps_min)


def _extremos_eps(secao: SecaoDiscreta, theta: float,
                  plano: Plano) -> tuple[float, float]:
    """Maior e menor deformação da seção de concreto, para o relatório.

    A integração de Green não passa pelos pontos do contorno para somar
    forças -- só a quadratura de cada lado --, então os extremos de
    deformação, que servem só de informação auxiliar, são lidos direto dos
    vértices em vez de saírem de graça da soma.
    """
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    us = [x * cos_t + y * sin_t for pol in secao.contornos for x, y in pol]
    if not us:
        return -1e9, 1e9
    e1 = plano.eps(min(us))
    e2 = plano.eps(max(us))
    return max(e1, e2), min(e1, e2)


def _limite_x(secao: SecaoDiscreta, theta: float) -> float:
    """Profundidade de linha neutra que satura a compressão da seção."""
    u_min, u_max = secao.extremos(theta)
    return 20.0 * (u_max - u_min) + 1.0


def resolver_x(secao: SecaoDiscreta, theta: float, N_alvo: float
               ) -> Estado | None:
    """Profundidade da linha neutra que equilibra ``N_alvo``, por bisseção.

    ``N(x)`` é monótona crescente: aprofundar a linha neutra só acrescenta
    área comprimida e alivia tração. É essa monotonia que autoriza a bisseção
    e dispensa chute inicial.
    """
    x_max = _limite_x(secao, theta)
    lo, hi = 0.0, x_max
    e_lo = resultantes(secao, theta, lo)
    e_hi = resultantes(secao, theta, hi)
    if N_alvo < e_lo.N - 1e-6 or N_alvo > e_hi.N + 1e-6:
        return None
    for _ in range(200):
        meio = (lo + hi) / 2.0
        est = resultantes(secao, theta, meio)
        if abs(est.N - N_alvo) <= max(1e-8, abs(N_alvo) * 1e-10):
            return est
        if est.N < N_alvo:
            lo = meio
        else:
            hi = meio
        if hi - lo < 1e-10 * max(1.0, x_max):
            break
    return resultantes(secao, theta, (lo + hi) / 2.0)


#: Faixa de varredura de ``eps_topo``, ‰, para :func:`resolver_estado`. Bem
#: além do ELU (que não passa de ``EPS_S_MAXIMA`` de tração nem de
#: ``eps_cu`` de compressão) de propósito: o diagrama momento-curvatura do
#: item 5.6 de CADAMURO JÚNIOR (1997) varre estados de serviço, que ficam
#: dentro dessa faixa, mas o teto largo evita que a busca falhe por excesso
#: de cautela perto dos extremos.
EPS_TOPO_LIMITE = 100.0


def plano_geral(secao: SecaoDiscreta, theta: float, eps_topo: float,
                k: float) -> Plano:
    """Plano de deformações **qualquer**, sem obedecer à regra dos domínios.

    ``eps_topo`` é a deformação na fibra mais comprimida da direção ``theta``
    e ``k`` a curvatura (‰/cm) -- os dois livres, ao contrário de
    :func:`plano_uls`, em que ``k`` sai amarrado ao domínio do item 17.2.2
    pela profundidade ``x`` da linha neutra. É o plano de três parâmetros
    (curvatura, direção, deformação de referência) do capítulo 5 de
    CADAMURO JÚNIOR (1997) -- ``theta`` faz o papel do ``alfa`` de lá, ``k``
    do ``theta`` (curvatura) de lá, e ``eps_topo`` fixa a terceira variável
    ancorada na fibra extrema em vez de no CG, o que dispensa calcular ``d``
    para nada: a única diferença é onde a régua começa a marcar zero.

    Serve ao diagrama momento-curvatura de serviço e, adiante, ao método
    exato de segunda ordem (item 15.8.3.2): o estado de uma seção sob um
    momento total qualquer, não necessariamente no ELU.
    """
    u_min, u_max = secao.extremos(theta)
    return Plano(eps_ref=eps_topo, k=k, u_ref=u_max, dominio="",
                x=(eps_topo / k if abs(k) > 1e-12 else 0.0))


def resolver_estado(secao: SecaoDiscreta, theta: float, k: float,
                    N_alvo: float) -> Estado | None:
    """``eps_topo`` que equilibra ``N_alvo`` para uma curvatura ``k`` livre.

    Generaliza :func:`resolver_x` para uma curvatura que não precisa ser a do
    ELU: ``N`` cresce monotonicamente com ``eps_topo`` para ``k`` fixo -- vale
    a mesma razão física de lá, deslocar todo o perfil de deformação para
    mais compressão só aumenta a força normal --, e a bisseção dispensa chute
    inicial do mesmo jeito. É o item 5.4 de CADAMURO JÚNIOR (1997)
    ("PROCURA_e_CG"), com a referência na fibra extrema em vez do CG.
    """
    lo, hi = -EPS_TOPO_LIMITE, EPS_TOPO_LIMITE
    e_lo = resultantes_de_plano(secao, theta, plano_geral(secao, theta, lo, k))
    e_hi = resultantes_de_plano(secao, theta, plano_geral(secao, theta, hi, k))
    if N_alvo < e_lo.N - 1e-6 or N_alvo > e_hi.N + 1e-6:
        return None
    for _ in range(200):
        meio = (lo + hi) / 2.0
        est = resultantes_de_plano(secao, theta,
                                   plano_geral(secao, theta, meio, k))
        if abs(est.N - N_alvo) <= max(1e-8, abs(N_alvo) * 1e-10):
            return est
        if est.N < N_alvo:
            lo = meio
        else:
            hi = meio
        if hi - lo < 1e-10 * EPS_TOPO_LIMITE:
            break
    return resultantes_de_plano(
        secao, theta, plano_geral(secao, theta, (lo + hi) / 2.0, k))


def _dif_angular(a: float, b: float) -> float:
    """Diferença ``a - b`` levada ao intervalo (-pi, pi]."""
    d = (a - b) % (2.0 * math.pi)
    return d - 2.0 * math.pi if d > math.pi else d


ResolverEstado = Callable[[SecaoDiscreta, float, float], "Estado | None"]


def estados_na_direcao(secao: SecaoDiscreta, N_alvo: float, alfa: float,
                       passos: int = 72,
                       resolver: ResolverEstado | None = None,
                       chave_resolver: tuple | None = None
                       ) -> list[Estado]:
    """Todos os estados de equilíbrio cujo momento resultante aponta ``alfa``.

    ``resolver`` decide **qual** estado de deformação, para cada direção
    ``theta`` de linha neutra, equilibra ``N_alvo`` -- por padrão
    :func:`resolver_x`, que amarra a curvatura à regra dos domínios do ELU
    (item 17.2.2). Passar :func:`resolver_estado` com uma curvatura ``k``
    fixada resolve o mesmo problema de direção para uma curvatura de
    **serviço** qualquer -- é o que :func:`diagrama_m_n_theta` usa para varrer
    o item 5.6 de CADAMURO JÚNIOR (1997) sem duplicar a busca de direção.

    ``chave_resolver`` é o que aquele resolvedor **representa**, em valores
    comparáveis (``("curvatura", k)``, por exemplo). Serve só ao cache: com
    ela as amostras e o resultado ficam guardados na seção; sem ela o cache
    fica desligado, e a busca é refeita a cada chamada.

    Procura o ângulo ``theta`` da linha neutra cujo momento resultante aponta
    para ``alfa``, para a normal ``N_alvo``. Numa seção qualquer -- e mesmo
    numa retangular com armadura assimétrica -- a linha neutra **não** é
    perpendicular ao plano de flexão, e é justamente essa obliquidade que a
    expressão de interação do item 17.2.5 aproxima com um expoente. Aqui ela
    é resolvida por equilíbrio.

    O resultado **não é sempre um único ponto**, e tratar como se fosse é o
    defeito que CADAMURO JÚNIOR (1997, itens 5.5 e 6.2.4) aponta em boa parte
    dos algoritmos "gerais" da literatura:

    * numa seção assimétrica sob curvatura baixa -- ``N_alvo`` perto da
      compressão quase uniforme --, a direção do momento resistente não
      cobre os 360° por mais que a linha neutra gire por completo; se
      ``alfa`` cair fora dessa faixa, **não existe** linha neutra que
      resolva o problema, e a lista correta é vazia -- não o ponto mais
      próximo que a varredura encontrou;
    * em compensação, pode haver **duas** direções de linha neutra que
      produzem momento resistente na direção pedida (a fig. 6.1b do mesmo
      trabalho): a seção só resiste quando o módulo do momento solicitante
      cai entre as duas, e não basta compará-lo com uma delas.

    A varredura grosseira de ``passos`` ângulos localiza **todas** as trocas
    de sinal do desvio angular ao longo da volta completa; cada uma é
    refinada por bisseção. Devolve os estados achados, em ordem crescente de
    ``|M|`` -- vazia quando nenhum existe.
    """
    achar = resolver if resolver is not None else resolver_x
    # O resolvedor entra na chave do cache **por valor**, nunca por
    # identidade: ``resolver`` é uma closure recriada a cada chamada (é assim
    # que :func:`diagrama_m_n_theta` fixa a curvatura), e identificá-la por
    # ``id`` seria um erro -- o CPython reaproveita o ``id`` de objetos já
    # liberados, e a chave passaria a casar com uma curvatura diferente.
    # Quem passa um resolvedor próprio diz, em ``chave_resolver``, o que ele
    # representa; sem essa declaração o cache fica desligado, porque não há
    # como saber se dois resolvedores são o mesmo problema.
    marca = chave_resolver if resolver is not None else None
    cacheavel = resolver is None or chave_resolver is not None
    chave_dir = (N_alvo, alfa, passos, marca)
    if cacheavel:
        pronto = secao._direcoes.get(chave_dir)
        if pronto is not None:
            return pronto

    def desvio(theta: float) -> tuple[float, Estado] | None:
        est = achar(secao, theta % (2.0 * math.pi), N_alvo)
        if est is None or est.M < 1e-9:
            return None
        return _dif_angular(est.alfa, alfa), est

    # A varredura grossa custa ``passos`` resoluções de equilíbrio e **não
    # depende de** ``alfa``: para uma normal fixa, os estados equilibrados em
    # cada direção de linha neutra são os mesmos qualquer que seja a direção
    # de momento procurada. Só o desvio angular -- aritmética -- e a bisseção
    # de refino é que dependem dela. Guardar as amostras por normal é o que
    # torna a varredura contínua da altura viável: 21 pontos com o mesmo Nd
    # pagam uma varredura grossa, não 21.
    chave = (N_alvo, passos, marca)
    base = secao._amostras.get(chave) if cacheavel else None
    if base is None:
        base = []
        for i in range(passos):
            th = 2.0 * math.pi * i / passos
            est = achar(secao, th % (2.0 * math.pi), N_alvo)
            if est is not None and est.M >= 1e-9:
                base.append((th, est))
        if cacheavel:
            secao._amostras[chave] = base

    amostras = [(th, _dif_angular(est.alfa, alfa), est) for th, est in base]
    if len(amostras) < 2:
        if cacheavel:
            secao._direcoes[chave_dir] = []
        return []

    n = len(amostras)
    achados: list[Estado] = []
    for i in range(n):
        th0, d0, e0 = amostras[i]
        th1, d1, _ = amostras[(i + 1) % n]
        if d0 == 0.0:
            achados.append(e0)
            continue
        if d0 * d1 >= 0.0 or abs(d0) > math.pi / 2.0 or abs(d1) > math.pi / 2.0:
            continue                    # sem troca de sinal, ou salto do wrap
        a, b = th0, (th1 if th1 > th0 else th1 + 2.0 * math.pi)
        da = d0
        raiz: Estado | None = None
        for _ in range(80):
            m = (a + b) / 2.0
            r = desvio(m)
            if r is None:
                break
            dm, est = r
            raiz = est
            if dm == 0.0 or b - a < 1e-10:
                break
            if da * dm < 0.0:
                b = m
            else:
                a, da = m, dm
        if raiz is not None:
            achados.append(raiz)

    # A mesma raiz pode ter sido encontrada por dois brackets vizinhos quando
    # ela cai perto de uma amostra; descartam-se as repetidas.
    unicos: list[Estado] = []
    for e in achados:
        if not any(abs(_dif_angular(e.theta, u.theta)) < 1e-4 for u in unicos):
            unicos.append(e)
    unicos.sort(key=lambda e: e.M)
    if cacheavel:
        secao._direcoes[chave_dir] = unicos
    return unicos


def momento_resistente_uniaxial(secao: SecaoDiscreta, N_alvo: float,
                                direcao: str, sentido: float = 1.0
                                ) -> float:
    """``MRd,xx`` ou ``MRd,yy``: momento resistente em flexão composta normal.

    É o que a expressão de interação do item 17.2.5 chama de ``MRd,xx`` e
    ``MRd,yy`` -- momento resistente **em torno de um eixo só**, com a mesma
    normal. A linha neutra é imposta paralela ao outro eixo, que é o que
    "flexão composta normal" quer dizer.
    """
    chave = (N_alvo, direcao, 1.0 if sentido >= 0 else -1.0)
    guardado = secao._uniaxial.get(chave)
    if guardado is not None:
        return guardado
    theta = 0.0 if direcao == "x" else math.pi / 2.0
    if sentido < 0:
        theta += math.pi
    est = resolver_x(secao, theta, N_alvo)
    valor = 0.0 if est is None else abs(est.Mx if direcao == "x" else est.My)
    secao._uniaxial[chave] = valor
    return valor


def normal_resistente_maxima(secao: SecaoDiscreta) -> float:
    """``N_Rd`` de compressão centrada, kN.

    Sai do plano de deformação uniforme em ``eps_c2`` -- o polo C levado ao
    limite --, que é onde o concreto atinge ``alfa_c fcd`` e o aço a tensão
    correspondente a ``eps_c2``. Serve de teto do diagrama de interação e da
    verificação de esmagamento.
    """
    c, aco = secao.concreto, secao.aco
    e = c.eps_c2_mil
    N = c.sigma_c(e) * secao.area_concreto
    for b in secao.barras:
        N += (_sigma_s(aco, e) - c.sigma_c(e)) * b.area
    return N


def normal_resistente_minima(secao: SecaoDiscreta) -> float:
    """``N_Rd`` de tração centrada, kN (negativa)."""
    return -sum(b.area for b in secao.barras) * secao.aco.fyd_kNcm2


# ---------------------------------------------------------------------------
# Diagrama momento-curvatura (item 5.6 de CADAMURO JÚNIOR, 1997)
# ---------------------------------------------------------------------------

@dataclass
class PontoMN:
    """Um ponto do diagrama momento-curvatura, para uma normal fixa."""

    k: float                     # ‰/cm, curvatura
    M: float                     # kN·cm, módulo do momento resistente
    Mx: float
    My: float
    dominio: str
    rompeu: bool = False         # este ponto já ultrapassa o ELU?


def diagrama_m_n_theta(secao: SecaoDiscreta, N_alvo: float, alfa: float,
                       pontos: int = 40) -> list[PontoMN]:
    """Diagrama momento-curvatura para ``N_alvo`` na direção ``alfa``.

    O item 5.6 de CADAMURO JÚNIOR (1997) chama isso de diagrama M-N-θ:
    fixados a normal e a direção do momento resistente, varre-se a curvatura
    e observa-se como o momento cresce -- convexo, contínuo e passando pela
    origem numa seção duplamente simétrica (fig. 5.8 daquele trabalho); numa
    seção assimétrica, o formato pode ser bem menos regular, e não é seguido
    aqui além do ramo que contém a origem (a curva pode ter um segundo ramo
    desconexo, do lado negativo de ``k`` -- ver o item 5.6 para o caso geral).

    Cada ponto reaproveita :func:`estados_na_direcao` -- que já resolve
    "existe linha neutra que dá esse momento nessa direção?", e quantas --
    com :func:`resolver_estado` no lugar de :func:`resolver_x`: a curvatura
    fica fixa no valor da varredura em vez de amarrada à regra dos domínios.

    A varredura vai de curvatura quase nula até o ELU, que é obtido por
    equilíbrio independente (:func:`estados_na_direcao` com o resolvedor
    padrão) -- não estimado por tentativa --, e o **último ponto do
    diagrama tem de coincidir com ele**: é a conferência cruzada que valida
    esta função contra a rotina de ELU já testada extensivamente à parte.
    """
    chave = (N_alvo, alfa, pontos)
    pronto = secao._diagramas.get(chave)
    if pronto is not None:
        return pronto

    ultimo = estados_na_direcao(secao, N_alvo, alfa)
    if not ultimo:
        return []
    estado_elu = ultimo[-1]
    k_elu = estado_elu.plano.k
    if abs(k_elu) < green.K_MINIMO:
        return []

    def _com_curvatura(k: float) -> ResolverEstado:
        def resolver(s: SecaoDiscreta, th: float, n: float) -> Estado | None:
            return resolver_estado(s, th, k, n)
        return resolver

    saida: list[PontoMN] = []
    for i in range(1, pontos + 1):
        k = k_elu * i / pontos
        estados = estados_na_direcao(secao, N_alvo, alfa,
                                     resolver=_com_curvatura(k),
                                     chave_resolver=("curvatura", k))
        if not estados:
            continue
        e = estados[-1]
        saida.append(PontoMN(k=k, M=e.M, Mx=e.Mx, My=e.My,
                             dominio=e.plano.dominio,
                             rompeu=(i == pontos)))
    secao._diagramas[chave] = saida
    # As varreduras grossas de cada curvatura serviram a um ponto só do
    # diagrama e não se repetem (cada ``k`` é único): ficam de fora do cache
    # para a seção não carregar alguns milhares de estados sem uso. O que
    # vale guardar é o diagrama pronto, acima.
    secao._amostras = {c: v for c, v in secao._amostras.items()
                       if c[-1] is None}
    secao._direcoes = {c: v for c, v in secao._direcoes.items()
                       if c[-1] is None}
    return saida


def envoltoria_momentos(secao: SecaoDiscreta, N_alvo: float,
                        pontos: int = 72) -> list[tuple[float, float]]:
    """Envoltória ``(MRd,x, MRd,y)`` para a normal dada, em kN·cm.

    É a curva que o item 3.3.3.4 da apostila manda comparar com a composição
    dos momentos solicitantes. Ao contrário da elipse generalizada do item
    17.2.5, esta sai do equilíbrio -- e é por isso que ela pode ser
    reentrante numa seção L, coisa que nenhum expoente reproduz.

    O traçado varre a **direção da linha neutra**, não a do momento: para
    cada ``theta`` basta uma bisseção em ``x`` para equilibrar ``N``, e o par
    ``(Mx, My)`` que sai já é um ponto da fronteira. Procurar ponto a ponto a
    linha neutra que aponta o momento numa direção pedida daria a mesma curva
    com uma busca aninhada a mais em cada ponto -- e cem vezes o tempo.
    """
    saida: list[tuple[float, float]] = []
    for i in range(pontos):
        theta = 2.0 * math.pi * i / pontos
        est = resolver_x(secao, theta, N_alvo)
        if est is not None:
            saida.append((est.Mx, est.My))
    return saida


def diagrama_interacao(secao: SecaoDiscreta, direcao: str = "x",
                       pontos: int = 40) -> list[tuple[float, float]]:
    """Diagrama ``N`` x ``M`` em flexão composta normal, kN e kN·cm.

    Varre a profundidade da linha neutra em vez da normal: a varredura em
    ``x`` cobre todos os domínios com passo regular e não deixa buraco no
    joelho da curva, onde ``N`` varia depressa e ``M`` quase não varia.
    """
    theta = 0.0 if direcao == "x" else math.pi / 2.0
    u_min, u_max = secao.extremos(theta)
    h = u_max - u_min
    saida: list[tuple[float, float]] = []
    x_max = 3.0 * h
    for i in range(pontos + 1):
        x = x_max * (i / pontos) ** 2
        est = resultantes(secao, theta, x)
        M = est.Mx if direcao == "x" else est.My
        saida.append((est.N, M))
    return saida


# ---------------------------------------------------------------------------
# Montagem a partir do modelo
# ---------------------------------------------------------------------------

def montar(secao_pilar, barras: list[Barra], concreto: Concreto, aco: Aco,
           fatias: int = FATIAS) -> SecaoDiscreta:
    """Cria a seção discreta a partir de uma :class:`SecaoPilar` e das barras."""
    return SecaoDiscreta(secao_pilar.contornos(), barras, concreto, aco,
                         fatias)
