# -*- coding: utf-8 -*-
"""
alveolar.py
Verificação (e escolha automática da protensão) da laje alveolar protendida
biapoiada, pré-tracionada, com ou sem capa estrutural.

O roteiro é o dos manuais de referência (Gramalho, 2013, cap. 5; Ferro,
2020, cap. 2 -- o segundo segue Petrucelli, 2009), com as expressões
normativas da ABNT NBR 6118:2026 e da NBR 14861 conforme transcritas por
eles:

    1. seção simples (painel) e seção composta (painel + capa);
    2. protensão: força inicial, perdas (simplificado ou calculado pela
       NBR 6118: ancoragem, relaxação, encurtamento elástico, e fluência,
       retração e relaxação progressivas), comprimentos de transferência
       ``lbpt`` e de regularização ``lp`` (9.4.5, 9.6.2.3);
    3. ato da protensão -- tensões na seção simples fora de ``lp``;
    4. serviço -- tensões por estágio (painel só até a capa curar; o
       acréscimo de perda e as cargas finais na seção composta) nas
       combinações do nível de protensão (13.4.2, Tabela 13.4);
    5. flechas: contraflecha no ato e flecha total com fluência;
    6. ELU de flexão por compatibilidade de deformações, com o
       pré-alongamento e o diagrama bilinear do aço de protensão, ao longo
       do vão (a tensão da cordoalha cresce de zero na ponta até ``fpyd``
       em ``lbpd``);
    7. cortante (NBR 14861/6118 17.4.1.1.2): VRd1 = Vc + Vp e VRd2.

Unidades: forças em kN, momentos em kN·m, comprimentos em m (a seção entra em
cm e é convertida), tensões em MPa -- compressão **positiva**.

**O que é hipótese e não norma**, declarado para não parecer o contrário:

* a NBR 14861 e a NBR 9062 não foram lidas diretamente; os limites que vêm
  delas são os que os dois manuais transcrevem (tensões do ato, 1,3 do
  concreto pré-moldado, ``VRd1``, ``lpt2 = 85 Ø``);
* a seção composta usa o concreto da capa convertido ao do painel pela
  razão dos módulos (``homogeneizar_capa``); a capa só recebe a tensão das
  ações aplicadas depois de curada;
* o acréscimo de perda diferida atua na seção composta, com a
  excentricidade medida a partir do CG **composto**;
* a região de regularização (``x < max(lbpt, lp)``) fica sem verificação de
  tensão normal -- nela vale a verificação do cortante e da ancoragem;
* VRd1 só tem a expressão da laje **fissurada** (a de zonas não
  fissuradas, por cisalhamento-tração, não foi implementada -- é a favor da
  segurança nas regiões de apoio);
* as perdas por fluência e retração usam uma única espessura fictícia, com
  o perímetro em contato com o ar ``2(b + h)`` do painel (conservador); o
  material de referência faz fase a fase;
* não se verifica içamento, transporte, nem a ação de continuidade
  (ligação com viga, negativa na capa).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from .alveolar_modelo import (ACOS_PROTENSAO, AGREGADOS, CIMENTOS,
                              CORDOALHAS, PSI_1000, LajeAlveolar,
                              SecaoAlveolar, secao_parametrica)

#: Aço de protensão: alongamento último de cálculo (‰) e de referência do
#: diagrama (cordoalhas de 7 fios, NBR 6118 8.4.5).
EPS_UK = 35.0
#: Estações por meio vão (passo L/40 -- inclui os múltiplos de L/10 do manual).
N_ESTACOES = 21


# ---------------------------------------------------------------------------
# Concreto
# ---------------------------------------------------------------------------

def fctm(fck: float) -> float:
    if fck <= 50.0:
        return 0.3 * fck ** (2.0 / 3.0)
    return 2.12 * math.log(1.0 + 0.11 * fck)


def eci(fck: float, alfa_e: float) -> float:
    if fck <= 50.0:
        return alfa_e * 5600.0 * math.sqrt(fck)
    return 21500.0 * alfa_e * (fck / 10.0 + 1.25) ** (1.0 / 3.0)


def ecs(fck: float, alfa_e: float) -> float:
    alfa_i = min(1.0, 0.8 + 0.2 * fck / 80.0)
    return alfa_i * eci(fck, alfa_e)


@dataclass
class Conc:
    fck: float
    fcd: float
    fctm: float
    fctk_inf: float
    fctk_sup: float
    fctd: float
    eci: float
    ecs: float


def concreto(fck: float, gamma: float, alfa_e: float, *,
             fctd_com_fctm: bool = False) -> Conc:
    fm = fctm(fck)
    inf = 0.7 * fm
    return Conc(fck=fck, fcd=fck / gamma, fctm=fm, fctk_inf=inf,
                fctk_sup=1.3 * fm,
                fctd=(fm if fctd_com_fctm else inf) / gamma,
                eci=eci(fck, alfa_e), ecs=ecs(fck, alfa_e))


# ---------------------------------------------------------------------------
# Aço de protensão
# ---------------------------------------------------------------------------

@dataclass
class AcoP:
    fptk: float
    fpyk: float
    fptd: float
    fpyd: float
    Ep: float
    eps_yd: float        # ‰

    def sigma(self, eps_permil: float) -> float:
        """Tensão (MPa) para o alongamento total (‰), diagrama bilinear."""
        if eps_permil <= 0.0:
            return 0.0
        if eps_permil <= self.eps_yd:
            return self.Ep * eps_permil / 1000.0
        return self.fpyd + (self.fptd - self.fpyd) * \
            (eps_permil - self.eps_yd) / (EPS_UK - self.eps_yd)


def aco_protensao(l: LajeAlveolar) -> AcoP:
    fptk = l.fptk
    fpyk = 0.9 * fptk
    fpyd = fpyk / l.gamma_s
    return AcoP(fptk=fptk, fpyk=fpyk, fptd=fptk / l.gamma_s, fpyd=fpyd,
                Ep=l.Ep, eps_yd=fpyd / l.Ep * 1000.0)


# ---------------------------------------------------------------------------
# Seção composta
# ---------------------------------------------------------------------------

@dataclass
class Prop:
    """Propriedades de uma seção, em m / m² / m⁴."""
    A: float
    yi: float
    I: float
    h: float             # altura total, m

    def sigma(self, N: float, M: float, y: float) -> float:
        """Tensão (kN/m²) na cota ``y`` (m, da face inferior).

        ``N`` > 0 comprime; ``M`` > 0 é momento positivo (traciona embaixo).
        """
        return N / self.A + M * (y - self.yi) / self.I


def propriedades(l: LajeAlveolar) -> tuple[Prop, Prop, float]:
    """(simples, composta homogeneizada ao concreto do painel, n_e)."""
    s = l.sec
    A = s.Ac / 1e4
    I = s.I / 1e8
    yi = s.yi / 100.0
    h = s.h / 100.0
    simples = Prop(A, yi, I, h)
    hc = l.capa / 100.0
    if hc <= 0.0:
        return simples, simples, 1.0
    bc = (l.largura_capa if l.largura_capa is not None else s.b) / 100.0
    n_e = 1.0
    if l.homogeneizar_capa:
        gam = l.gamma_c
        n_e = ecs(l.fck_capa, AGREGADOS[l.agregado]) / \
            ecs(l.fck, AGREGADOS[l.agregado])
    Ac = n_e * bc * hc
    yc = h + hc / 2.0
    A2 = A + Ac
    yi2 = (A * yi + Ac * yc) / A2
    I2 = I + A * (yi2 - yi) ** 2 + n_e * bc * hc ** 3 / 12.0 \
        + Ac * (yc - yi2) ** 2
    return simples, Prop(A2, yi2, I2, h + hc), n_e


# ---------------------------------------------------------------------------
# Perdas de protensão
# ---------------------------------------------------------------------------

def _psi1000(sigma_rel: float) -> float:
    """ψ1000 (fração, não %) por interpolação linear (NBR 6118)."""
    r = sigma_rel
    if r <= PSI_1000[0][0]:
        return 0.0
    for (r0, p0), (r1, p1) in zip(PSI_1000, PSI_1000[1:]):
        if r <= r1:
            return (p0 + (p1 - p0) * (r - r0) / (r1 - r0)) / 100.0
    return PSI_1000[-1][1] / 100.0


def _beta_f(t: float, h_m: float) -> float:
    h = min(max(h_m, 0.05), 1.6)
    t = max(t, 3.0)
    A = 42 * h ** 3 - 350 * h ** 2 + 588 * h + 113
    B = 768 * h ** 3 - 3060 * h ** 2 + 3234 * h - 23
    C = -200 * h ** 3 + 13 * h ** 2 + 1090 * h + 183
    D = 7579 * h ** 3 - 31916 * h ** 2 + 35343 * h + 1931
    return (t * t + A * t + B) / (t * t + C * t + D)


def _beta_s(t: float, h_m: float) -> float:
    h = min(max(h_m, 0.05), 1.6)
    t = max(t, 3.0)
    A = 40.0
    B = 116 * h ** 3 - 282 * h ** 2 + 220 * h - 4.8
    C = 2.5 * h ** 3 - 8.8 * h + 40.7
    D = -75 * h ** 3 + 585 * h ** 2 + 496 * h - 6.8
    E = -169 * h ** 4 + 88 * h ** 3 + 584 * h ** 2 - 39 * h + 0.8
    u = t / 100.0
    return (u ** 3 + A * u ** 2 + B * u) / (u ** 3 + C * u ** 2 + D * u + E)


def fluencia_retracao(l: LajeAlveolar, c: Conc, simples: Prop) -> dict:
    """φ(∞, t0) e εcs(∞, t0) pelo Anexo A da NBR 6118:2026."""
    U = l.umidade
    s_cim, alfa = CIMENTOS[l.cimento]
    gam = 1.0 + math.exp(-7.8 + 0.1 * U)
    u_ar = 2.0 * (l.sec.b + l.sec.h) / 100.0          # m
    hfic = 2.0 * simples.A / u_ar                     # m
    h_pond = gam * hfic                               # m
    h_cm = h_pond * 100.0
    # consistência
    fator_slump = 0.75 if l.slump < 5.0 else (1.25 if l.slump > 9.0 else 1.0)
    phi1c = (4.45 - 0.035 * U) * fator_slump
    phi2c = (42.0 + h_cm) / (20.0 + h_cm)
    phi_f_inf = phi1c * phi2c if l.fck <= 50.0 else 0.45 * phi1c * phi2c
    razao = min(1.0, l.fckj / l.fck)
    phi_a = (0.8 if l.fck <= 50.0 else 1.4) * (1.0 - razao)
    t0 = alfa * (l.temperatura + 10.0) / 30.0 * l.idade_protensao
    phi = phi_a + phi_f_inf * (1.0 - _beta_f(t0, h_pond)) + 0.4
    eps1s = (-8.09 + U / 15.0 - U ** 2 / 2284.0 - U ** 3 / 133765.0
             + U ** 4 / 7608150.0) * 1e-4 * fator_slump
    eps2s = (33.0 + 2.0 * h_cm) / (20.8 + 3.0 * h_cm)
    eps_cs = abs(eps1s * eps2s) * (1.0 - _beta_s(t0, h_pond))
    return dict(hfic=hfic * 100.0, h_pond=h_cm, phi=phi, phi_a=phi_a,
                phi_f=phi_f_inf * (1.0 - _beta_f(t0, h_pond)), phi_d=0.4,
                eps_cs=eps_cs, t0_fic=t0, u_ar=u_ar * 100.0)


def calcular_perdas(l: LajeAlveolar, c: Conc, cj: Conc, aco: AcoP,
                    simples: Prop, composta: Prop, cargas: dict) -> dict:
    """Perdas iniciais e progressivas. Devolve forças em kN e tensões MPa."""
    n = l.n_cordoalhas
    Ap = l.Ap / 1e4                                   # m²
    Pi = l.sigma_pi * Ap * 1000.0                     # kN
    e_s = simples.yi - l.d_linha / 100.0
    res = dict(sigma_pi=l.sigma_pi, Pi=Pi, modo=l.perdas_modo)
    if l.perdas_modo != "nbr":
        p_im = l.perda_imediata / 100.0
        p_tot = l.perda_total / 100.0
        res.update(perda_imediata=p_im, perda_total=p_tot,
                   P0=Pi * (1 - p_im), Pinf=Pi * (1 - p_tot),
                   sigma_p0=l.sigma_pi * (1 - p_im),
                   sigma_pinf=l.sigma_pi * (1 - p_tot), componentes=None)
        return res
    # --- iniciais -----------------------------------------------------
    d_anc = l.escorregamento / (l.pista * 1000.0) * l.Ep
    sigma_pr = l.sigma_pi - d_anc
    psi_ini = _psi1000(l.sigma_pi / aco.fptk) * \
        ((l.t_liberacao / 24.0) / 41.67) ** 0.15
    d_rel_i = psi_ini * sigma_pr
    N1 = (l.sigma_pi - d_anc - d_rel_i) * Ap * 1000.0
    Mg0 = cargas["g0"] * l.vao ** 2 / 8.0
    sig_c = (N1 / simples.A + N1 * e_s ** 2 / simples.I
             - Mg0 * e_s / simples.I) / 1000.0        # MPa
    alfa_p = l.Ep / cj.eci
    d_el = alfa_p * sig_c
    sigma_p0 = l.sigma_pi - d_anc - d_rel_i - d_el
    perda_im = (d_anc + d_rel_i + d_el) / l.sigma_pi
    # --- progressivas -------------------------------------------------
    fr = fluencia_retracao(l, c, simples)
    phi, eps_cs = fr["phi"], fr["eps_cs"]
    psi_inf = 2.5 * _psi1000(l.sigma_pi / aco.fptk)
    chi_aco = -math.log(1.0 - psi_inf)
    d_rel_inf = psi_inf * sigma_pr
    # tensão no CG dos cabos pelas ações permanentes (painel e capa na
    # seção simples; revestimento na composta)
    N0 = sigma_p0 * Ap * 1000.0
    Mperm_s = (cargas["g0"] + cargas["g1c"]) * l.vao ** 2 / 8.0
    Mg2 = cargas["g2"] * l.vao ** 2 / 8.0
    e_c = composta.yi - l.d_linha / 100.0
    sig_c_perm = (N0 / simples.A + N0 * e_s ** 2 / simples.I
                  - Mperm_s * e_s / simples.I
                  - Mg2 * e_c / composta.I) / 1000.0
    alfa_p28 = l.Ep / c.eci
    rho_p = (Ap) / simples.A
    eta_p = 1.0 + e_s ** 2 * simples.A / simples.I
    chi_c = 1.0 + 0.5 * phi
    chi_p = 1.0 + chi_aco
    d_fluencia = alfa_p28 * sig_c_perm * phi
    d_retracao = eps_cs * l.Ep
    prog = (d_retracao + d_fluencia + sigma_p0 * chi_aco) \
        / (chi_p + chi_c * alfa_p28 * eta_p * rho_p)
    isolada = d_retracao + d_fluencia + d_rel_inf
    d_prog_ref = max(prog, isolada)
    sigma_pinf = sigma_p0 - d_prog_ref
    perda_tot = 1.0 - sigma_pinf / l.sigma_pi
    res.update(
        perda_imediata=perda_im, perda_total=perda_tot,
        P0=sigma_p0 * Ap * 1000.0, Pinf=sigma_pinf * Ap * 1000.0,
        sigma_p0=sigma_p0, sigma_pinf=sigma_pinf,
        componentes=dict(ancoragem=d_anc, relaxacao_ini=d_rel_i,
                         elastica=d_el, alfa_p=alfa_p, sigma_c_cg=sig_c,
                         fluencia=d_fluencia, retracao=d_retracao,
                         relaxacao_final=d_rel_inf, progressiva=prog,
                         isolada=isolada, adotada=d_prog_ref,
                         psi_final=psi_inf, chi_aco=chi_aco,
                         sigma_c_perm=sig_c_perm, **{
                             "phi": phi, "eps_cs": eps_cs,
                             "hfic": fr["hfic"], "h_pond": fr["h_pond"],
                             "u_ar": fr["u_ar"]}))
    return res


# ---------------------------------------------------------------------------
# Comprimentos de transferência
# ---------------------------------------------------------------------------

def comprimentos(l: LajeAlveolar, cj: Conc, aco: AcoP, sigma_pi: float,
                 sigma_pinf: float) -> dict:
    """lbp, lbpt, lp, lbpd, lpt2 (m) -- NBR 6118:2026 9.4.5 e 9.6.2.3."""
    phi = l.phi / 1000.0
    eta1 = 1.2           # cordoalhas de 3 e 7 fios (9.3.2.1)
    fbpd = eta1 * 1.0 * 1.0 * cj.fctd        # MPa; boa aderência, ≤ Ø32
    lbp = 7.0 / 36.0 * phi * aco.fpyd / fbpd
    lbpt = 0.5 * lbp * sigma_pi / aco.fpyd
    if not l.liberacao_gradual:
        lbpt *= 1.25
    h = l.sec.h / 100.0
    lp = math.sqrt(h * h + (0.6 * lbpt) ** 2)
    lbpd = lbpt + lbp * max(aco.fpyd - sigma_pinf, 0.0) / aco.fpyd
    return dict(fbpd=fbpd, lbp=lbp, lbpt=lbpt, lp=lp, lbpd=lbpd,
                lpt2=85.0 * phi)


def _rampa(x: float, comp: float) -> float:
    if comp <= 0.0:
        return 1.0 if x > 0.0 else 0.0
    return min(1.0, max(0.0, x / comp))


def fator_forca(l: LajeAlveolar, x: float, lbpt: float) -> float:
    """Fração da força de protensão efetiva na estação ``x`` (da ponta)."""
    n = l.n_cordoalhas
    ne = min(max(l.encapar, 0), n - 1) if n > 1 else 0
    if n <= 0:
        return 0.0
    return ((n - ne) * _rampa(x, lbpt)
            + ne * _rampa(x - l.encapar_comp, lbpt)) / n


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoAlveolar:
    laje: LajeAlveolar
    conc: Conc | None = None
    conc_j: Conc | None = None
    conc_capa: Conc | None = None
    aco: AcoP | None = None
    simples: Prop | None = None
    composta: Prop | None = None
    n_e: float = 1.0
    secao: dict = field(default_factory=dict)
    cargas: dict = field(default_factory=dict)
    perdas: dict = field(default_factory=dict)
    comp: dict = field(default_factory=dict)
    x: np.ndarray | None = None
    ato: dict = field(default_factory=dict)
    servico: dict = field(default_factory=dict)
    flexao: dict = field(default_factory=dict)
    cortante: dict = field(default_factory=dict)
    flechas: dict = field(default_factory=dict)
    verificacoes: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    quantitativo: dict = field(default_factory=dict)
    escolha: list = field(default_factory=list)    # alternativas (automática)

    @property
    def atende(self) -> bool:
        return not any(c == "erro" for c, _ in self.avisos)


# ---------------------------------------------------------------------------
# Cargas
# ---------------------------------------------------------------------------

def cargas_lineares(l: LajeAlveolar) -> dict:
    s = l.sec
    A = s.Ac / 1e4
    b = s.b / 100.0
    gam = l.peso_especifico
    hc = l.capa / 100.0
    bc = (l.largura_capa if l.largura_capa is not None else s.b) / 100.0
    g0 = A * gam * (1.0 + l.acrescimo_chave / 100.0)
    g1c = bc * hc * gam
    return dict(g0=g0, g1c=g1c, g2=l.g2 * b, q=l.q * b, b=b,
                peso_painel=A * gam * l.vao)


def _M(w: float, L: float, x: float) -> float:
    return w * x * (L - x) / 2.0


def _V(w: float, L: float, x: float) -> float:
    return w * (L / 2.0 - x)


# ---------------------------------------------------------------------------
# Flexão no ELU
# ---------------------------------------------------------------------------

def _bloco_comprimido(l: LajeAlveolar, cc: Conc, cp: Conc, x: float,
                      bc: float, b: float, hc: float) -> float:
    """Força de compressão, kN, de um bloco 0,85·fcd·λx (λ = 0,8)."""
    y = 0.8 * x
    f_capa = cp.fcd * bc * min(y, hc)
    f_laje = cc.fcd * b * max(y - hc, 0.0)
    return 0.85 * (f_capa + f_laje) * 1000.0


def resistencia_flexao(l: LajeAlveolar, cc: Conc, cp: Conc, aco: AcoP,
                       sigma_pinf: float, h: float, hc: float, bc: float,
                       b: float, Ap_m2: float, d: float,
                       limites: list | None = None) -> dict:
    """MRd e posição da linha neutra por compatibilidade de deformações.

    ``limites`` é uma lista de ``(fração da armadura, tensão máxima MPa)``:
    cada conjunto de cordoalhas só desenvolve a tensão que a ancoragem
    permite naquela seção (9.4.5). ``None`` = todas ancoradas.
    """
    limites = limites or [(1.0, math.inf)]
    eps_po = sigma_pinf / l.Ep * 1000.0               # ‰
    Hc = h + hc if hc > 0 else h
    lim_d2 = 3.5 / (3.5 + 10.0)

    def estado(x: float):
        if x / d <= lim_d2:
            eps_s = 10.0
        else:
            eps_s = 3.5 * (d - x) / x
        sig_p = aco.sigma(eps_s + eps_po)
        sig = sum(fr * min(sig_p, cap) for fr, cap in limites)
        return sig, eps_s

    def f(x: float) -> float:
        sig, _ = estado(x)
        return _bloco_comprimido(l, cc, cp, x, bc, b, hc) - \
            Ap_m2 * sig * 1000.0

    lo, hi = 1e-6, min(Hc, 3.0 * d)
    if f(hi) < 0.0:
        x = hi
    else:
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if f(mid) > 0.0:
                hi = mid
            else:
                lo = mid
        x = 0.5 * (lo + hi)
    sig, eps_s = estado(x)
    Rp = Ap_m2 * sig * 1000.0
    z = d - 0.4 * x
    dom = 2 if x / d <= lim_d2 else (3 if x / d <= 0.628 else 4)
    return dict(x=x, kx=x / d, sigma_p=sig, eps_s=eps_s, Rp=Rp, z=z,
                MRd=Rp * z, dominio=dom, eps_po=eps_po)


def ap_necessario_manual(md: float, cc: Conc, cp: Conc, aco: AcoP,
                         sigma_pinf: float, l: LajeAlveolar, bc: float,
                         d: float) -> dict:
    """Roteiro do manual (5.6.1): Ax² + Bx + C = 0 com a tensão da
    cordoalha tirada da deformação, retornando Ap necessário (m²)."""
    fcd = cp.fcd * 1000.0 if l.capa > 0 else cc.fcd * 1000.0
    A = 0.272 * fcd * bc
    B = -0.68 * fcd * bc * d
    C = md
    disc = B * B - 4 * A * C
    if disc < 0.0 or md <= 0.0:
        return dict(x=0.0, kx=0.0, sigma_p=0.0, z=d, Rp=0.0, ap=0.0,
                    dominio=2)
    x = (-B - math.sqrt(disc)) / (2 * A)
    kx = x / d
    lim = 3.5 / 13.5
    eps_s = 10.0 if kx <= lim else 3.5 * (d - x) / x
    eps_po = sigma_pinf / l.Ep * 1000.0
    sig = aco.sigma(eps_s + eps_po)
    z = d - 0.4 * x
    Rp = md / z
    return dict(x=x, kx=kx, sigma_p=sig, z=z, Rp=Rp,
                ap=Rp / (sig * 1000.0), dominio=2 if kx <= lim else 3,
                eps_s=eps_s)


# ---------------------------------------------------------------------------
# Verificação completa
# ---------------------------------------------------------------------------

def _cap_cordoalha(x: float, comp: dict, sigma_pinf: float, fpyd: float,
                   deslocamento: float = 0.0) -> float:
    """Tensão máxima da cordoalha (MPa) a ``x`` da ponta (NBR 9.4.5)."""
    xe = x - deslocamento
    if xe <= 0.0:
        return 0.0
    if xe <= comp["lbpt"]:
        return sigma_pinf * xe / comp["lbpt"]
    if xe >= comp["lbpd"]:
        return math.inf
    return sigma_pinf + (fpyd - sigma_pinf) * (xe - comp["lbpt"]) / \
        max(comp["lbpd"] - comp["lbpt"], 1e-9)


def verificar_alveolar(l: LajeAlveolar) -> ResultadoAlveolar:
    """Verifica a laje com a protensão dada em ``l``."""
    res = ResultadoAlveolar(laje=l)
    s = l.sec
    L = l.vao
    alfa_e = AGREGADOS[l.agregado]
    gc = l.gamma_c_prefab if l.usar_gamma_prefab else l.gamma_c
    cc = concreto(l.fck, gc, alfa_e, fctd_com_fctm=l.fctd_com_fctm)
    cj = concreto(l.fckj, gc, alfa_e)
    cp = concreto(l.fck_capa, gc, alfa_e)
    aco = aco_protensao(l)
    simples, composta, n_e = propriedades(l)
    res.conc, res.conc_j, res.conc_capa = cc, cj, cp
    res.aco, res.simples, res.composta, res.n_e = aco, simples, composta, n_e
    cg = cargas_lineares(l)
    res.cargas = cg
    h = simples.h
    hc = l.capa / 100.0
    bc = (l.largura_capa if l.largura_capa is not None else s.b) / 100.0
    b = s.b / 100.0
    e_s = simples.yi - l.d_linha / 100.0
    e_c = composta.yi - l.d_linha / 100.0
    res.secao = dict(
        simples=dict(A=simples.A, yi=simples.yi, ys=h - simples.yi,
                     I=simples.I, Wi=simples.I / simples.yi,
                     Ws=simples.I / (h - simples.yi)),
        composta=dict(A=composta.A, yi=composta.yi,
                      ys=composta.h - composta.yi, I=composta.I,
                      Wi=composta.I / composta.yi,
                      Ws=composta.I / max(composta.h - composta.yi, 1e-9),
                      W_int=composta.I / (h - composta.yi)
                      if abs(h - composta.yi) > 1e-9 else float("inf")),
        e_s=e_s, e_c=e_c, d=composta.h - l.d_linha / 100.0,
        d_simples=h - l.d_linha / 100.0, n_e=n_e, bc=bc, b=b, hc=hc,
        sum_bw=s.sum_bw / 100.0)

    # -- perdas e comprimentos ---------------------------------------
    perdas = calcular_perdas(l, cc, cj, aco, simples, composta, cg)
    res.perdas = perdas
    comp = comprimentos(l, cj, aco, perdas["sigma_p0"], perdas["sigma_pinf"])
    res.comp = comp
    P0, Pinf = perdas["P0"], perdas["Pinf"]
    dP = P0 - Pinf

    # -- estações ----------------------------------------------------
    xs = np.linspace(0.0, L / 2.0, N_ESTACOES)
    res.x = xs
    lim_t_ato = -cj.fctm / 1.2
    lim_c_ato = 0.85 * cj.fck / gc
    lim_c_serv = 0.85 * cc.fck / gc
    lim_c_capa = 0.85 * cp.fck / gc
    ft_f = l.alfa_f * cc.fctk_inf
    ft_f_capa = l.alfa_f * cp.fctk_inf
    y_int, y_top = h, composta.h

    # ato -----------------------------------------------------------
    ato = dict(x=[], sig_i=[], sig_s=[], verificada=[], N=[], M=[])
    for x in xs:
        f = fator_forca(l, x, comp["lbpt"])
        N = P0 * f
        M = -N * e_s + _M(cg["g0"], L, x)
        ato["x"].append(float(x))
        ato["N"].append(N)
        ato["M"].append(M)
        ato["sig_i"].append(simples.sigma(N, M, 0.0) / 1000.0)
        ato["sig_s"].append(simples.sigma(N, M, h) / 1000.0)
        ato["verificada"].append(x >= max(comp["lbpt"], comp["lp"]) - 1e-9)
    ato["lim_trac"], ato["lim_comp"] = lim_t_ato, lim_c_ato
    res.ato = ato

    # serviço -------------------------------------------------------
    nivel = l.nivel_protensao
    plano = {1: [("QP", "F"), ("FREQ", "F")],
             2: [("QP", "D"), ("FREQ", "F")],
             3: [("FREQ", "D"), ("RARA", "F")]}[nivel if nivel in (1, 2, 3)
                                                    else 2]
    psi = {"QP": l.psi2, "FREQ": l.psi1, "RARA": 1.0}
    nomes = {"QP": "quase permanente", "FREQ": "frequente", "RARA": "rara"}
    res.servico = dict(plano=plano, nomes=nomes, comb={})
    for comb in ("QP", "FREQ", "RARA"):
        d = dict(x=[], sig_i=[], sig_s=[], sig_capa=[], psi=psi[comb])
        for x in xs:
            f = fator_forca(l, x, comp["lbpt"])
            N1 = P0 * f
            M1 = -N1 * e_s + _M(cg["g0"] + cg["g1c"], L, x)
            dN = dP * f
            e_perda = e_s if l.excentr_perda_simples else e_c
            M2 = dN * e_perda + _M(cg["g2"] + psi[comb] * cg["q"], L, x)
            d["x"].append(float(x))
            si = simples.sigma(N1, M1, 0.0) + composta.sigma(-dN, M2, 0.0)
            ss = simples.sigma(N1, M1, h) + composta.sigma(-dN, M2, y_int)
            sc = composta.sigma(-dN, M2, y_top) * n_e if hc > 0 else ss
            d["sig_i"].append(si / 1000.0)
            d["sig_s"].append(ss / 1000.0)
            d["sig_capa"].append(sc / 1000.0)
        res.servico["comb"][comb] = d
    res.servico["lim"] = dict(F=-ft_f, F_capa=-ft_f_capa, D=0.0,
                              comp=lim_c_serv, comp_capa=lim_c_capa)

    # flechas ---------------------------------------------------------
    Ej = cj.ecs * 1000.0                      # kN/m²
    E28 = cc.ecs * 1000.0
    E_inf = E28 / (1.0 + l.phi_flecha)
    Is, Ic = simples.I, composta.I
    d_p0 = P0 * e_s * L ** 2 / (8 * Ej * Is)
    d_g0 = 5 * cg["g0"] * L ** 4 / (384 * Ej * Is)
    d_ini = d_g0 - d_p0
    d_pinf = Pinf * e_s * L ** 2 / (8 * E_inf * Is)
    d_per = 5 * (cg["g0"] + cg["g1c"]) * L ** 4 / (384 * E_inf * Is)
    d_g2 = 5 * cg["g2"] * L ** 4 / (384 * E_inf * Ic)
    if l.q_flecha_inteira:
        d_q = 5 * cg["q"] * L ** 4 / (384 * E28 * Ic)
    else:
        d_q = 5 * l.psi2 * cg["q"] * L ** 4 / (384 * E_inf * Ic)
    d_tot = d_per + d_g2 + d_q - d_pinf
    lim_contra = L / l.lim_contra_den
    lim_ini = L / l.lim_flecha_ini_den
    lim_tot = L / l.lim_flecha_den
    res.flechas = dict(
        protensao_ini=-d_p0, peso_ini=d_g0, inicial=d_ini,
        protensao_inf=-d_pinf, permanente_painel=d_per, g2=d_g2, q=d_q,
        total=d_tot, lim_contra=lim_contra, lim_ini=lim_ini, lim_total=lim_tot,
        E_ini=Ej / 1000.0, E_inf=E_inf / 1000.0, E28=E28 / 1000.0,
        atende_ini=(-d_ini <= lim_contra if d_ini < 0 else d_ini <= lim_ini),
        atende_total=d_tot <= lim_tot)

    # flexão (ELU) -----------------------------------------------------
    d_util = res.secao["d"]
    d_simp = res.secao["d_simples"]
    Ap_m2 = l.Ap / 1e4
    sig_pinf = perdas["sigma_pinf"]
    xs_f = xs
    Mg_k = cg["g0"] + cg["g1c"] + cg["g2"]
    fx = dict(x=[], Md=[], MRd=[], Ap_nec=[], kx=[], dominio=[],
              sigma_p=[], z=[], ok=[], Rp=[], xn=[])
    for x in xs_f:
        md = l.gamma_g * _M(Mg_k, L, x) + l.gamma_q * _M(cg["q"], L, x)
        # as cordoalhas isoladas (encapadas) só ancoram a partir da ponta do
        # encapamento
        n_enc = min(max(l.encapar, 0), l.n_cordoalhas - 1)
        lim = [((l.n_cordoalhas - n_enc) / l.n_cordoalhas,
                _cap_cordoalha(x, comp, sig_pinf, aco.fpyd))]
        if n_enc > 0:
            lim.append((n_enc / l.n_cordoalhas,
                        _cap_cordoalha(x, comp, sig_pinf, aco.fpyd,
                                       l.encapar_comp)))
        r = resistencia_flexao(l, cc, cp, aco, sig_pinf, h, hc, bc, b,
                               Ap_m2, d_util, limites=lim)
        nec = ap_necessario_manual(md, cc, cp, aco, sig_pinf, l, bc, d_util)
        fx["x"].append(float(x))
        fx["Md"].append(md)
        fx["MRd"].append(r["MRd"])
        fx["Ap_nec"].append(nec["ap"] * 1e4)
        fx["kx"].append(r["kx"])
        fx["xn"].append(r["x"])
        fx["dominio"].append(r["dominio"])
        fx["sigma_p"].append(r["sigma_p"])
        fx["z"].append(r["z"])
        fx["Rp"].append(r["Rp"])
        fx["ok"].append(r["MRd"] >= md - 1e-6)
    # momento de fissuração (informativo, p/ ruptura frágil)
    Wi2 = composta.I / composta.yi
    Mcr = Wi2 * (l.alfa_f * cc.fctk_inf * 1000.0
                 + Pinf / simples.A + Pinf * e_s / (simples.I / simples.yi))
    fx["Mcr"] = Mcr
    res.flexao = fx

    # cortante -------------------------------------------------------
    cz = dict(x=[], VSd=[], VRd1=[], Vc=[], Vp=[], alfa=[], VRd2=[], ok=[])
    sum_bw = s.sum_bw / 100.0
    nu = max(0.5, 0.7 - l.fck / 200.0)
    d_v = d_util
    k = max(1.6 - d_v, 1.0)
    rho1 = Ap_m2 / (sum_bw * d_v)
    Fd = l.gamma_g * (cg["g0"] + cg["g1c"] + cg["g2"]) + l.gamma_q * cg["q"]
    x_ini = 0.5 * composta.h
    xs_v = np.unique(np.concatenate([[x_ini], xs[xs > x_ini]]))
    for x in xs_v:
        al = min(1.0, x / comp["lpt2"])
        ne = min(max(l.encapar, 0), l.n_cordoalhas - 1)
        frac = (l.n_cordoalhas - ne) / l.n_cordoalhas if x < l.encapar_comp \
            else 1.0
        sig_cp = Pinf * frac * al / simples.A / 1000.0           # MPa
        Vc = 0.25 * cc.fctd * k * (1.2 + 40.0 * rho1) * sum_bw * d_v * 1000.0
        Vp = 0.15 * sig_cp * sum_bw * d_v * 1000.0
        Vrd1 = Vc + Vp
        Vrd2 = 0.5 * nu * cc.fcd * 0.9 * d_v * sum_bw * 1000.0
        Vsd = _V(Fd, L, x)
        cz["x"].append(float(x))
        cz["VSd"].append(Vsd)
        cz["VRd1"].append(Vrd1)
        cz["Vc"].append(Vc)
        cz["Vp"].append(Vp)
        cz["alfa"].append(al)
        cz["VRd2"].append(Vrd2)
        cz["ok"].append(Vsd <= Vrd1 + 1e-9 and Vsd <= Vrd2 + 1e-9)
    # seção simples (içamento/montagem, só painel + capa fresca)
    d_s = d_simp
    k_s = max(1.6 - d_s, 1.0)
    rho_s = Ap_m2 / (sum_bw * d_s)
    Fd_s = l.gamma_g * (cg["g0"] + cg["g1c"])
    x_s = 0.5 * h
    al_s = min(1.0, x_s / comp["lpt2"])
    sig_cp_s = P0 * al_s / simples.A / 1000.0
    Vc_s = 0.25 * cj.fctd * k_s * (1.2 + 40.0 * rho_s) * sum_bw * d_s * 1000.0
    Vp_s = 0.15 * sig_cp_s * sum_bw * d_s * 1000.0
    nu_s = max(0.5, 0.7 - l.fckj / 200.0)
    cz["simples"] = dict(
        x=x_s, VSd=_V(Fd_s, L, x_s), Vc=Vc_s, Vp=Vp_s, VRd1=Vc_s + Vp_s,
        VRd2=0.5 * nu_s * cj.fcd * 0.9 * d_s * sum_bw * 1000.0, k=k_s,
        rho1=rho_s, d=d_s)
    cz["k"], cz["rho1"], cz["nu"], cz["Fd"] = k, rho1, nu, Fd
    res.cortante = cz

    # -- quantitativo -------------------------------------------------
    massa_aco = l.Ap * 1e-4 * L * 7850.0
    vol_painel = simples.A * L
    res.quantitativo = dict(
        volume_painel=vol_painel, volume_capa=bc * hc * L,
        massa_aco=massa_aco, peso_painel=cg["peso_painel"],
        massa_painel=cg["peso_painel"] / 9.80665 * 1000.0 / 1000.0,
        custo=vol_painel * l.custo_concreto + massa_aco * l.custo_aco,
        area_painel=b * L)
    _montar_verificacoes(res)
    return res


# ---------------------------------------------------------------------------
# Verificações e avisos
# ---------------------------------------------------------------------------

def _montar_verificacoes(res: ResultadoAlveolar) -> None:
    l = res.laje
    lin: list = []
    av: list = []

    def add(item, local, sol, rest, ok, ref):
        lin.append([item, local, sol, rest, "OK" if ok else "NÃO OK", ref])

    # ato
    ato = res.ato
    v = [i for i, vv in enumerate(ato["verificada"]) if vv]
    if v:
        si = [ato["sig_i"][i] for i in v]
        ss = [ato["sig_s"][i] for i in v]
        tmin = min(min(si), min(ss))
        cmax = max(max(si), max(ss))
        ok_t, ok_c = tmin >= ato["lim_trac"] - 1e-9, cmax <= ato["lim_comp"] + 1e-9
        ix = int(np.argmin([min(ato["sig_i"][i], ato["sig_s"][i])
                            for i in v]))
        add("Tensão no ato — tração", f"x ≥ {res.comp['lp']:.2f} m",
            f"{tmin:.2f} MPa", f"≥ {ato['lim_trac']:.2f} MPa", ok_t,
            "NBR 14861")
        add("Tensão no ato — compressão", f"x ≥ {res.comp['lp']:.2f} m",
            f"{cmax:.2f} MPa", f"≤ {ato['lim_comp']:.2f} MPa", ok_c,
            "NBR 14861")
        if not ok_t:
            av.append(("erro", "Ato da protensão: tração de "
                       f"{tmin:.2f} MPa passa do limite de "
                       f"{ato['lim_trac']:.2f} MPa -- reduza a força, "
                       "encape cordoalhas nas pontas ou suba o fckj."))
        if not ok_c:
            av.append(("erro", "Ato da protensão: compressão de "
                       f"{cmax:.2f} MPa passa do limite de "
                       f"{ato['lim_comp']:.2f} MPa -- reduza a força ou "
                       "suba o fckj."))
    # serviço
    sv = res.servico
    for comb, tipo in sv["plano"]:
        d = sv["comb"][comb]
        si, ss, sc = d["sig_i"], d["sig_s"], d["sig_capa"]
        verif = [i for i, x in enumerate(d["x"])
                 if x >= max(res.comp["lbpt"], res.comp["lp"]) - 1e-9]
        if not verif:
            verif = list(range(len(d["x"])))
        lim_t = sv["lim"]["D"] if tipo == "D" else sv["lim"]["F"]
        lim_tc = sv["lim"]["D"] if tipo == "D" else sv["lim"]["F_capa"]
        tmin = min(min(si[i] for i in verif), min(ss[i] for i in verif))
        tmin_c = min(sc[i] for i in verif) if res.laje.capa > 0 else tmin
        cmax = max(max(si[i] for i in verif), max(ss[i] for i in verif))
        cmax_c = max(sc[i] for i in verif) if res.laje.capa > 0 else cmax
        ok_t = tmin >= lim_t - 1e-9 and tmin_c >= lim_tc - 1e-9
        ok_c = cmax <= sv["lim"]["comp"] + 1e-9 and \
            cmax_c <= sv["lim"]["comp_capa"] + 1e-9
        nm = sv["nomes"][comb]
        rotulo = "ELS-D" if tipo == "D" else "ELS-F"
        pior_t = min(tmin, tmin_c)
        lim_mostr = lim_t if pior_t == tmin else lim_tc
        add(f"{rotulo} ({nm}) — tração", "ao longo do vão",
            f"{pior_t:.2f} MPa", f"≥ {lim_mostr:.2f} MPa", ok_t,
            "13.4.2 / Tab. 13.4")
        add(f"{rotulo} ({nm}) — compressão", "ao longo do vão",
            f"{max(cmax, cmax_c):.2f} MPa",
            f"≤ {sv['lim']['comp']:.2f} MPa", ok_c, "13.4.2")
        if not ok_t:
            av.append(("erro", f"{rotulo} ({nm}): a fibra mais tracionada "
                       f"chega a {pior_t:.2f} MPa e o limite é "
                       f"{lim_mostr:.2f} MPa -- aumente a protensão ou a "
                       "altura."))
        if not ok_c:
            av.append(("erro", f"{rotulo} ({nm}): compressão de "
                       f"{max(cmax, cmax_c):.2f} MPa passa de "
                       f"{sv['lim']['comp']:.2f} MPa."))
    # flechas
    f = res.flechas
    add("Contraflecha / flecha no ato", "meio do vão",
        f"{f['inicial'] * 100:+.2f} cm (− = contraflecha)",
        (f"≥ −{f['lim_contra'] * 100:.2f} cm (L/{l.lim_contra_den:g})"
         if f["inicial"] < 0 else
         f"≤ {f['lim_ini'] * 100:.2f} cm (L/{l.lim_flecha_ini_den:g})"),
        f["atende_ini"], "NBR 6118 Tab. 13.3 / NBR 9062")
    add("Flecha total (fluência)", "meio do vão",
        f"{f['total'] * 100:+.2f} cm", f"≤ {f['lim_total'] * 100:.2f} cm "
        f"(L/{l.lim_flecha_den:g})", f["atende_total"],
        "NBR 6118 17.3.2 / Tab. 13.3")
    if not f["atende_ini"]:
        av.append(("erro", f"Contraflecha de {abs(f['inicial']) * 100:.2f} cm "
                   f"no ato passa do limite de {f['lim_contra'] * 100:.2f} cm."
                   if f["inicial"] < 0 else
                   f"Flecha de {f['inicial'] * 100:.2f} cm no ato passa do "
                   f"limite de {f['lim_ini'] * 100:.2f} cm."))
    if not f["atende_total"]:
        av.append(("erro", f"Flecha total de {f['total'] * 100:.2f} cm passa "
                   f"de {f['lim_total'] * 100:.2f} cm -- aumente a altura."))
    # flexão
    fx = res.flexao
    ratios = [m / d if d > 1e-9 else 9.9 for m, d in zip(fx["MRd"], fx["Md"])]
    i_pior = int(np.argmin(ratios)) if ratios else 0
    ok_f = all(fx["ok"])
    add("Flexão no ELU", f"x = {fx['x'][i_pior]:.2f} m",
        f"Md = {fx['Md'][i_pior]:.2f} kN·m",
        f"MRd = {fx['MRd'][i_pior]:.2f} kN·m", ok_f, "17.2 / 9.4.5")
    if not ok_f:
        av.append(("erro", "Flexão no ELU: MRd menor que Md em "
                   f"x = {fx['x'][i_pior]:.2f} m "
                   f"({fx['MRd'][i_pior]:.1f} contra {fx['Md'][i_pior]:.1f}"
                   " kN·m) -- aumente as cordoalhas ou a altura."))
    imeio = len(fx["x"]) - 1
    if fx["MRd"][imeio] < fx["Mcr"] - 1e-9:
        av.append(("aviso", f"MRd = {fx['MRd'][imeio]:.1f} kN·m no meio do "
                   f"vão é menor que o momento de fissuração "
                   f"({fx['Mcr']:.1f} kN·m): ruptura frágil sem aviso."))
    if fx["dominio"][imeio] == 4:
        av.append(("erro", "Domínio 4: ruptura sem aviso -- reduza a "
                   "armadura ou aumente a seção."))
    # cortante
    cz = res.cortante
    razoes = [r / s_ if s_ > 1e-9 else 9.9
              for r, s_ in zip(cz["VRd1"], cz["VSd"])]
    ic = int(np.argmin(razoes))
    ok_v = all(cz["ok"])
    add("Cortante VRd1", f"x = {cz['x'][ic]:.2f} m",
        f"VSd = {cz['VSd'][ic]:.2f} kN", f"VRd1 = {cz['VRd1'][ic]:.2f} kN",
        cz["VSd"][ic] <= cz["VRd1"][ic] + 1e-9, "17.4.1.1.2 / NBR 14861")
    add("Cortante VRd2 (diagonal comprimida)", f"x = {cz['x'][0]:.2f} m",
        f"VSd = {cz['VSd'][0]:.2f} kN", f"VRd2 = {cz['VRd2'][0]:.2f} kN",
        cz["VSd"][0] <= cz["VRd2"][0] + 1e-9, "17.4.2.2")
    sm = cz["simples"]
    add("Cortante na seção simples", f"x = {sm['x']:.2f} m",
        f"VSd = {sm['VSd']:.2f} kN", f"VRd1 = {sm['VRd1']:.2f} kN",
        sm["VSd"] <= sm["VRd1"] + 1e-9 and sm["VSd"] <= sm["VRd2"] + 1e-9,
        "NBR 14861")
    if not ok_v:
        av.append(("erro", "Cortante: VSd passa de VRd1 ou de VRd2 -- "
                   "preencha os alvéolos, aumente a altura ou a protensão "
                   "(a verificação com alvéolo preenchido não está "
                   "implementada)."))
    if sm["VSd"] > sm["VRd1"] + 1e-9 or sm["VSd"] > sm["VRd2"] + 1e-9:
        av.append(("erro", "Cortante na seção simples (painel + capa fresca) "
                   "passa do limite."))
    # avisos de escopo
    pr = res.perdas
    if l.sigma_pi > min(0.77 * res.aco.fptk, 0.85 * res.aco.fpyk) + 1e-6:
        av.append(("erro", f"σpi = {l.sigma_pi:.0f} MPa passa do limite de "
                   f"{min(0.77 * res.aco.fptk, 0.85 * res.aco.fpyk):.0f} MPa "
                   "(9.6.1.2.1, pré-tração com relaxação baixa)."))
    if l.perdas_modo != "nbr":
        av.append(("obs", f"perdas informadas ({pr['perda_imediata'] * 100:.1f}"
                   f" % imediata, {pr['perda_total'] * 100:.1f} % total); use "
                   "o modo 'calculadas' para estimá-las pela NBR 6118."))
    else:
        av.append(("obs", "perdas calculadas com uma única espessura fictícia"
                   f" (perímetro no ar {res.perdas['componentes']['u_ar']:.0f}"
                   " cm); o material de referência calcula por fases e chega "
                   "a valores diferentes."))
    if l.nivel_protensao == 1:
        av.append(("obs", "nível 1: o ELS-W (wk ≤ 0,2 mm) não é calculado; "
                   "verifica-se o ELS-F, mais rígido."))
    if l.capa <= 0.0:
        av.append(("obs", "sem capa: seção simples nas duas fases."))
    hs = 0.8 * res.flexao["xn"][imeio]
    if hs > l.capa / 100.0 + res.laje.sec.tf_sup / 100.0 > 0 and \
            res.laje.sec.tf_sup > 0:
        av.append(("aviso", "o bloco comprimido passa da mesa superior "
                   "(alvéolo): a resistência está sobrestimada."))
    av.append(("obs", "não verificados: içamento e transporte, ligação com "
               "a viga (continuidade) e VRd1 em região não fissurada."))
    res.verificacoes = lin
    res.avisos.extend(av)


# ---------------------------------------------------------------------------
# Escolha automática
# ---------------------------------------------------------------------------

def _clonar(l: LajeAlveolar, **kw) -> LajeAlveolar:
    import dataclasses
    return dataclasses.replace(l, **kw)


def linhas_protensao(res: ResultadoAlveolar, n) -> list:
    """Linhas (item, valor, observação) da tabela de protensão e perdas;
    ``n(valor, casas)`` formata o número (tela e relatório têm o seu)."""
    l, p, c = res.laje, res.perdas, res.comp
    linhas = [
        ["Cordoalhas", f"{l.n_cordoalhas} Ø{l.phi:g} {l.aco}",
         f"Ap = {n(l.Ap, 2)} cm²"],
        ["σpi (macaco)", f"{n(l.sigma_pi, 0)} MPa",
         f"Pi = {n(p['Pi'], 1)} kN"],
        ["Perda imediata", f"{n(p['perda_imediata'] * 100, 2)} %",
         f"P0 = {n(p['P0'], 1)} kN"],
        ["Perda total", f"{n(p['perda_total'] * 100, 2)} %",
         f"P∞ = {n(p['Pinf'], 1)} kN (σp∞ = {n(p['sigma_pinf'], 0)} MPa)"],
    ]
    cp = p.get("componentes")
    if cp:
        linhas += [
            ["  ancoragem", f"{n(cp['ancoragem'], 2)} MPa", ""],
            ["  relaxação inicial", f"{n(cp['relaxacao_ini'], 2)} MPa", ""],
            ["  encurtamento elástico", f"{n(cp['elastica'], 2)} MPa",
             f"σc no CG = {n(cp['sigma_c_cg'], 2)} MPa; "
             f"αp = {n(cp['alfa_p'], 2)}"],
            ["  fluência", f"{n(cp['fluencia'], 2)} MPa",
             f"φ = {n(cp['phi'], 2)}; hfic = {n(cp['hfic'], 1)} cm"],
            ["  retração", f"{n(cp['retracao'], 2)} MPa",
             f"εcs = {n(cp['eps_cs'] * 1e4, 3)} · 10⁻⁴"],
            ["  relaxação final", f"{n(cp['relaxacao_final'], 2)} MPa",
             f"ψ∞ = {n(cp['psi_final'] * 100, 2)} %"],
            ["  progressiva (interação)", f"{n(cp['progressiva'], 2)} MPa",
             "NBR 6118, 9.6.3.4.2"],
            ["  isolada (soma)", f"{n(cp['isolada'], 2)} MPa",
             "adota-se a maior"]]
    linhas += [
        ["fbpd", f"{n(c['fbpd'], 2)} MPa", "η1 = 1,2 (cordoalha)"],
        ["lbp", f"{n(c['lbp'], 3)} m", "9.4.5.1"],
        ["lbpt (transferência)", f"{n(c['lbpt'], 3)} m", "9.4.5.2"],
        ["lp (regularização)", f"{n(c['lp'], 3)} m",
         "√(h² + (0,6 lbpt)²)"],
        ["lbpd (ancoragem)", f"{n(c['lbpd'], 3)} m", "9.4.5.3"],
        ["lpt2 (cortante)", f"{n(c['lpt2'], 3)} m", "85 Ø"]]
    return linhas


def resolver(l: LajeAlveolar, gamma_g: float | None = None,
             gamma_q: float | None = None) -> ResultadoAlveolar:
    """Caminho único da tela e do relatório: aplica os coeficientes gerais e
    verifica, ou escolhe a protensão, conforme ``l.automatica``."""
    import dataclasses
    kw = {}
    if gamma_g is not None:
        kw["gamma_g"] = gamma_g
    if gamma_q is not None:
        kw["gamma_q"] = gamma_q
    if kw:
        l = dataclasses.replace(l, **kw)
    return escolher_protensao(l) if l.automatica else verificar_alveolar(l)


def escolher_protensao(l: LajeAlveolar, *, phis=(9.5, 12.7, 15.2),
                       acos=None, n_max: int = 24, tracos=None,
                       manter: int = 6) -> ResultadoAlveolar:
    """Enumera cordoalhas (Ø, aço, quantidade) e fica com a de menor custo
    que atende todas as verificações; ``res.escolha`` lista as melhores.

    A seção (altura) e a capa são os do projeto -- o programa não varia a
    seção do fabricante.
    """
    acos = acos or list(ACOS_PROTENSAO)
    candidatas = []
    melhor_falha = None
    for aco_n, phi in itertools.product(acos, phis):
        fptk = ACOS_PROTENSAO[aco_n]
        limite = min(0.77 * fptk, 0.85 * 0.9 * fptk)
        sig_use = min(l.sigma_pi * fptk / l.fptk, limite)
        for n in range(2, n_max + 1):
            c = _clonar(l, aco=aco_n, phi=phi, n_cordoalhas=n,
                        sigma_pi=sig_use, area_cordoalha=None)
            r = verificar_alveolar(c)
            if r.atende:
                candidatas.append(r)
                break               # mais cordoalhas do mesmo tipo só custa
            if melhor_falha is None:
                melhor_falha = r
    if not candidatas:
        r = melhor_falha or verificar_alveolar(l)
        r.avisos.append(("erro", "nenhuma combinação de cordoalhas com até "
                         f"{n_max} unidades atende -- aumente a altura da "
                         "laje ou o fckj."))
        return r
    candidatas.sort(key=lambda r: r.quantitativo["custo"])
    melhor = candidatas[0]
    melhor.escolha = [dict(aco=r.laje.aco, phi=r.laje.phi,
                           n=r.laje.n_cordoalhas,
                           Ap=r.laje.Ap, custo=r.quantitativo["custo"],
                           massa=r.quantitativo["massa_aco"])
                      for r in candidatas[:manter]]
    return melhor
