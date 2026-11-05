# -*- coding: utf-8 -*-
"""
servico.py
Estado-limite de serviço do pilar: abertura de fissuras (ELS-W).

Base normativa (NBR 6118:2026; a NBR 7187:2021 remete à 6118 para o ELS de
armadura passiva e não acrescenta limites próprios):

* 13.4.2, Tabela 13.4 -- concreto armado: ELS-W na combinação **frequente**,
  ``wk <= 0,4 mm`` (CAA I), ``0,3 mm`` (II e III), ``0,2 mm`` (IV). ELS-F e
  ELS-D são exigências da protensão e não se aplicam aqui.
* 17.3.3.2 -- ``wk`` de cada barra tracionada é o menor de

      ``wk1 = phi/(12,5 eta1) . sigma_s/Es . 3 sigma_s/fctm``
      ``wk2 = phi/(12,5 eta1) . sigma_s/Es . (4/rho_r + 45)``

  (phi em mm, tensões em MPa, wk em mm), com ``sigma_s`` no **estádio II**
  (materiais lineares, concreto tracionado desprezado, ``alpha_e = 15``) e
  ``rho_r = As/Acr``, Acr a área de envolvimento -- um quadrado de lado
  15 phi centrado na barra (Figura 17.4), limitado pela face do concreto e
  repartido com as barras vizinhas (cada ponto conta para a barra mais
  próxima; a norma não detalha o recorte, e esta é a leitura da figura).
* 17.3.3.3, Tabela 17.2 -- controle sem cálculo de wk (bitola e espaçamento
  máximos em função de sigma_s), equivalente a ~0,3 mm: entra como
  informação ao lado do cálculo, que é o que decide.

Os esforços de serviço são os da combinação frequente, informados pelo
projetista (de 1ª ordem; quem quiser a 2ª ordem de serviço a inclui nos
valores). São verificadas as duas cotas extremas do lance, topo e base, onde
o momento de 1ª ordem -- linear ao longo do lance -- é máximo.

A 6118 não dispensa a verificação em pilar nem em seção comprimida; quando,
no estádio II, nenhuma barra fica tracionada, não há fissura de flexão e a
verificação fica atendida por consequência do cálculo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .fibras import _dentro_do_material, amostrar_centros
from .formato import num

#: Tabela 13.4, concreto armado, combinação frequente: wk limite, mm.
WK_LIMITE = {"I": 0.4, "II": 0.3, "III": 0.3, "IV": 0.2}

#: Tabela 8.2 (NBR 6118:2026): coeficiente de aderência eta1 por categoria.
ETA1 = {"CA-25": 1.00, "CA-50": 2.25, "CA-60": 1.00}

#: Tabela 17.2, concreto sem armadura ativa: (sigma_s MPa, phi máx mm,
#: s máx cm). Sem interpolação: vale a primeira linha com sigma >= sigma_s.
TABELA_17_2 = ((160.0, 32.0, 30.0), (200.0, 25.0, 25.0), (240.0, 20.0, 20.0),
               (280.0, 16.0, 15.0), (320.0, 12.5, 10.0), (360.0, 10.0, 5.0),
               (400.0, 8.0, None))

#: Lado da área de envolvimento, em bitolas (7,5 phi para cada lado).
LADO_ACR = 15.0
#: Resolução da grade da seção no estádio II.
RESOLUCAO = 90


@dataclass
class BarraServico:
    x: float
    y: float
    phi: float                   # mm
    sigma: float                 # MPa, positiva em TRAÇÃO
    Acr: float = 0.0             # cm²
    rho_r: float = 0.0
    wk1: float = 0.0             # mm
    wk2: float = 0.0
    wk: float = 0.0


@dataclass
class CotaServico:
    nome: str
    N: float                     # kN, compressão positiva
    Mx: float                    # kN·cm
    My: float
    convergiu: bool = True
    sigma_c_max: float = 0.0     # MPa, compressão máxima no concreto
    barras: list[BarraServico] = field(default_factory=list)

    @property
    def tracionadas(self) -> list[BarraServico]:
        return [b for b in self.barras if b.sigma > 1e-6]

    @property
    def critica(self) -> BarraServico | None:
        return max(self.tracionadas, key=lambda b: b.wk, default=None)

    @property
    def wk_max(self) -> float:
        c = self.critica
        return c.wk if c is not None else 0.0

    @property
    def sigma_s_max(self) -> float:
        return max((b.sigma for b in self.tracionadas), default=0.0)


@dataclass
class VerificacaoServico:
    """ELS-W do lance."""

    aplicavel: bool = False
    motivo: str = ""             # por que não se aplica
    wk_limite: float = 0.0       # mm
    origem_limite: str = ""
    alfa_e: float = 15.0
    eta1: float = 2.25
    fctm: float = 0.0            # MPa
    cotas: list[CotaServico] = field(default_factory=list)
    #: Tabela 17.2 para a maior tensão de tração: (phi máx, s máx) ou None
    tabela_17_2: tuple | None = None
    espacamento_barras: float = 0.0   # cm, maior entre eixos do arranjo
    avisos: list[str] = field(default_factory=list)

    @property
    def wk_max(self) -> float:
        return max((c.wk_max for c in self.cotas), default=0.0)

    @property
    def governante(self) -> CotaServico | None:
        return max(self.cotas, key=lambda c: c.wk_max, default=None)

    @property
    def ok(self) -> bool:
        return (not self.aplicavel
                or (all(c.convergiu for c in self.cotas)
                    and self.wk_max <= self.wk_limite + 1e-9))


# ---------------------------------------------------------------------------
# Estádio II
# ---------------------------------------------------------------------------

def _resolver_3x3(A, b):
    import numpy as np
    try:
        return list(np.linalg.solve(np.asarray(A, float), np.asarray(b, float)))
    except np.linalg.LinAlgError:
        return None


def estadio_2(celulas, barras, Ec: float, Es: float, N: float, Mx: float,
              My: float):
    """Plano ``eps = e0 + kx x + ky y`` (compressão positiva) que equilibra
    ``(N, Mx, My)`` com concreto linear só na compressão e aço linear.

    ``celulas``: [(x, y, área)] cm; ``barras``: [(x, y, As)] cm, cm²;
    ``Ec``, ``Es`` em kN/cm². Iteração no conjunto de células comprimidas:
    com ele fixo o problema é linear (3x3); repete-se até o conjunto parar
    de mudar. Devolve ``(e0, kx, ky, convergiu)``."""
    ativas = [True] * len(celulas)
    p = None
    for _ in range(60):
        K = [[0.0] * 3 for _ in range(3)]

        def somar(x, y, rig):
            v = (1.0, x, y)
            for i in range(3):
                for j in range(3):
                    K[i][j] += rig * v[i] * v[j]
        for (x, y, a), at in zip(celulas, ativas):
            if at:
                somar(x, y, Ec * a)
        for x, y, As in barras:
            somar(x, y, Es * As)
        p = _resolver_3x3(K, [N, Mx, My])
        if p is None:
            return 0.0, 0.0, 0.0, False
        e0, kx, ky = p
        novas = [e0 + kx * x + ky * y > 0.0 for x, y, _ in celulas]
        if novas == ativas:
            return e0, kx, ky, True
        ativas = novas
    return (p[0], p[1], p[2], False) if p else (0.0, 0.0, 0.0, False)


# ---------------------------------------------------------------------------
# Área de envolvimento
# ---------------------------------------------------------------------------

def area_envolvimento(contornos, barras, i: int) -> float:
    """Acr da barra ``i``, cm²: o quadrado de lado 15 phi centrado nela,
    dentro do concreto, contando só os pontos mais próximos dela que de
    qualquer outra barra (repartição com as vizinhas)."""
    bx, by, phi = barras[i]
    meio = LADO_ACR * phi / 10.0 / 2.0
    passo = max(min(phi / 10.0 / 2.0, 1.0), 0.2)
    n = max(int(2.0 * meio / passo), 4)
    passo = 2.0 * meio / n
    area = 0.0
    for a in range(n):
        x = bx - meio + (a + 0.5) * passo
        for b in range(n):
            y = by - meio + (b + 0.5) * passo
            if not _dentro_do_material(contornos, x, y):
                continue
            d_i = (x - bx) ** 2 + (y - by) ** 2
            if any((x - cx) ** 2 + (y - cy) ** 2 < d_i - 1e-12
                   for j, (cx, cy, _f) in enumerate(barras) if j != i):
                continue
            area += passo * passo
    return area


def tabela_17_2(sigma: float):
    """(phi máx, s máx) da Tabela 17.2 para a tensão de tração dada, sem
    interpolar (a primeira linha que a cobre). ``None`` acima de 400 MPa."""
    for s, phi, esp in TABELA_17_2:
        if sigma <= s + 1e-9:
            return phi, esp
    return None


# ---------------------------------------------------------------------------
# Verificação
# ---------------------------------------------------------------------------

def tem_esforcos(e) -> bool:
    return any(abs(v) > 1e-9 for v in (e.Nd, e.Mx_topo, e.Mx_base,
                                       e.My_topo, e.My_base))


def verificar(pilar, arr) -> VerificacaoServico:
    """ELS-W (abertura de fissuras) nas cotas de topo e base do lance."""
    from dataclasses import replace
    cfg = pilar.config
    v = VerificacaoServico(alfa_e=cfg.alfa_e_servico)
    serv = pilar.esforcos_servico
    if arr is None or not arr.barras:
        v.motivo = "sem arranjo de barras"
        return v
    if not tem_esforcos(serv):
        v.motivo = ("esforços de serviço (combinação frequente) não "
                    "informados")
        return v
    v.aplicavel = True
    caa = pilar.ambiente.caa
    if cfg.wk_limite > 0.0:
        v.wk_limite = cfg.wk_limite
        v.origem_limite = "imposto pelo projetista (13.4.3)"
    else:
        v.wk_limite = WK_LIMITE.get(caa, 0.3)
        v.origem_limite = f"Tabela 13.4, CAA {caa}, combinação frequente"
    v.eta1 = ETA1.get(pilar.aco.categoria, 2.25)
    c = pilar.concreto
    v.fctm = c.fctm
    Es = pilar.aco.Es_kNcm2                       # kN/cm²
    Ec = Es / cfg.alfa_e_servico
    Es_mpa = Es * 10.0

    contornos = pilar.secao.contornos()
    xs = [q[0] for cc in contornos for q in cc]
    ys = [q[1] for cc in contornos for q in cc]
    dx = (max(xs) - min(xs)) / RESOLUCAO
    dy = (max(ys) - min(ys)) / RESOLUCAO
    celulas = [(x, y, dx * dy)
               for x, y in amostrar_centros(contornos, RESOLUCAO)]
    barras_m = [(b.x, b.y, b.area) for b in arr.barras]
    barras_g = [(b.x, b.y, b.phi) for b in arr.barras]
    v.espacamento_barras = arr.espacamento_eixos

    # a mesma convenção de sinal da base que o ELU usa
    p_serv = replace(pilar, esforcos=serv)
    for nome, Mx, My in (("Topo", serv.Mx_topo, serv.My_topo),
                         ("Base", p_serv.momento_base("x"),
                          p_serv.momento_base("y"))):
        cota = CotaServico(nome=nome, N=serv.Nd, Mx=Mx, My=My)
        e0, kx, ky, ok = estadio_2(celulas, barras_m, Ec, Es, serv.Nd, Mx, My)
        cota.convergiu = ok
        cota.sigma_c_max = max(
            (Ec * (e0 + kx * x + ky * y) * 10.0 for x, y, _ in celulas),
            default=0.0)
        for i, b in enumerate(arr.barras):
            eps = e0 + kx * b.x + ky * b.y
            sigma = -Es * eps * 10.0                 # MPa, + tração
            bs = BarraServico(b.x, b.y, b.phi, sigma)
            if sigma > 1e-6:
                bs.Acr = area_envolvimento(contornos, barras_g, i)
                bs.rho_r = b.area / bs.Acr if bs.Acr > 0 else 0.0
                base = b.phi / (12.5 * v.eta1) * sigma / Es_mpa
                bs.wk1 = base * 3.0 * sigma / v.fctm
                bs.wk2 = (base * (4.0 / bs.rho_r + 45.0)
                          if bs.rho_r > 0 else bs.wk1)
                bs.wk = min(bs.wk1, bs.wk2)
            cota.barras.append(bs)
        v.cotas.append(cota)

    sigma_max = max((ct.sigma_s_max for ct in v.cotas), default=0.0)
    if sigma_max > 0:
        v.tabela_17_2 = tabela_17_2(sigma_max)

    gov = v.governante
    if any(not ct.convergiu for ct in v.cotas):
        v.avisos.append(av.erro(
            "ELS-W: o estádio II não convergiu numa das cotas de serviço -- "
            "confira os esforços da combinação frequente."))
    elif gov is None or gov.critica is None:
        v.avisos.append(av.construtivo(
            "ELS-W (17.3.3.2): nas duas cotas a seção fica inteiramente "
            "comprimida em serviço, no estádio II -- sem barra tracionada "
            "não há fissura de flexão, e a abertura de fissuras fica "
            "atendida por consequência do cálculo (a 6118 não traz dispensa "
            "explícita para pilar)."))
    elif v.wk_max > v.wk_limite + 1e-9:
        b = gov.critica
        v.avisos.append(av.erro(
            f"ELS-W (17.3.3.2): abertura de fissura wk = {num(b.wk, 3)} mm "
            f"na cota {gov.nome}, barra ø{num(b.phi)} em ({num(b.x, 1)}; "
            f"{num(b.y, 1)}) cm com σs = {num(b.sigma, 0)} MPa no estádio II, "
            f"acima do limite de {num(v.wk_limite, 2)} mm ({v.origem_limite}). "
            f"Aumente a armadura, reduza a bitola ou o espaçamento."))
    else:
        b = gov.critica
        v.avisos.append(av.construtivo(
            f"ELS-W (17.3.3.2): wk máximo = {num(b.wk, 3)} mm na cota "
            f"{gov.nome} (σs = {num(b.sigma, 0)} MPa no estádio II, "
            f"αe = {num(v.alfa_e)}), dentro do limite de "
            f"{num(v.wk_limite, 2)} mm ({v.origem_limite})."))
    return v


# ---------------------------------------------------------------------------
# NBR 7187: dimensões mínimas de pilar de ponte
# ---------------------------------------------------------------------------

def avisos_ponte(pilar) -> list[str]:
    """Item 9.1.5 e 9.1.6 da NBR 7187:2021, com a obra marcada como ponte:
    pilar maciço com menor dimensão >= 40 cm e >= altura livre/25; seção
    celular com paredes >= 20 cm; pilar-parede com espessura >= 30 cm e >=
    altura livre/25."""
    saida = []
    secao = pilar.secao
    L = pilar.lance.altura
    if secao.tipo in ("retangular vazada", "circular vazada"):
        parede = secao.menor_dimensao
        if parede < 20.0 - 1e-9:
            saida.append(av.erro(
                f"NBR 7187, item 9.1.5: pilar de ponte de seção celular com "
                f"paredes de {num(parede)} cm, abaixo dos 20 cm (25 cm com "
                f"forma deslizante)."))
        return saida
    menor = secao.menor_dimensao
    if secao.eh_pilar_parede:
        if menor < max(30.0, L / 25.0) - 1e-9:
            saida.append(av.erro(
                f"NBR 7187, item 9.1.6: pilar-parede de ponte com espessura "
                f"de {num(menor)} cm, abaixo do maior entre 30 cm e a altura "
                f"livre/25 ({num(L / 25.0, 1)} cm)."))
        return saida
    if menor < max(40.0, L / 25.0) - 1e-9:
        saida.append(av.erro(
            f"NBR 7187, item 9.1.5: pilar de ponte com menor dimensão de "
            f"{num(menor)} cm, abaixo do maior entre 40 cm e a altura "
            f"livre/25 ({num(L / 25.0, 1)} cm). Em passarela o mínimo é "
            f"30 cm."))
    return saida
