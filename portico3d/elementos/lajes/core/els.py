# -*- coding: utf-8 -*-
"""
els.py
Estados limites de serviço da laje maciça: deformação excessiva e, quando
pedida, abertura de fissuras.

A flecha segue o roteiro do §1.6 da apostila, que é a simplificação da norma
para quem ainda não conhece a armadura:

    f(t=0)   = k . p_ser . a⁴ / (Ecs . Ieq)
    f(t=inf) = (1 + alfa_f) . f(t=0)

com o ``k`` tabelado por vinculação e o ``Ieq`` estimado em dois patamares --
a seção bruta enquanto o momento de serviço não passa o de fissuração, e
30 % dela depois que passa:

    m_a <= m_r  ->  Ieq = Ic
    m_a >  m_r  ->  Ieq = 0,30 Ic          com  m_r = 0,25 fctm b h²

É uma estimativa grosseira do lado seguro, e é ela que a apostila usa para
**escolher a espessura**: arbitra-se o mínimo do item 13.2.4.1, calcula-se a
flecha, e sobe-se 1 cm até caber no limite. O programa reproduz esse laço.

O fator ``1 + alfa_f = 2,32`` é o do item 17.3.2.1.2 com a hipótese que a
apostila fixa: laje sem armadura de compressão, carga aplicada em t0 = 1 mês
e flecha lida em t = infinito.
"""

from __future__ import annotations

from dataclasses import dataclass

from .materiais import Concreto
from .modelo import Config, Laje


@dataclass
class ResultadoELS:
    """Verificação da flecha de uma laje."""

    laje: str
    h: float                        # cm
    p_ser: float                    # kN/m²
    vao: float                      # m, o vão que governa
    k: float = 0.0
    Ic: float = 0.0                 # cm⁴/m
    Ieq: float = 0.0                # cm⁴/m
    m_r: float = 0.0                # kN·m/m, momento de fissuração
    m_a: float = 0.0                # kN·m/m, momento de serviço
    estadio: str = ""               # "I - não fissurada" / "II - fissurada"
    f_imediata: float = 0.0         # cm
    f_diferida: float = 0.0         # cm
    f_admissivel: float = 0.0       # cm
    divisor: int = 250
    Ecs: float = 0.0                # MPa

    @property
    def atende(self) -> bool:
        return self.f_diferida <= self.f_admissivel + 1e-9

    @property
    def aproveitamento(self) -> float:
        if self.f_admissivel <= 0.0:
            return 0.0
        return self.f_diferida / self.f_admissivel


def inercia_bruta(h: float) -> float:
    """Momento de inércia da faixa de 1 m, cm⁴/m: ``b h³ / 12``."""
    return 100.0 * h ** 3 / 12.0


def momento_fissuracao(concreto: Concreto, h: float) -> float:
    """``m_r = 0,25 fctm b h²`` da faixa de 1 m, em kN·m/m (§1.6).

    O 0,25 é o ``alfa . fct / 6`` do item 17.3.1 com ``alfa = 1,5`` da seção
    retangular: ``1,5 / 6 = 0,25``.
    """
    fctm_kNcm2 = concreto.fctm / 10.0
    return fctm_kNcm2 * 100.0 * h ** 2 / 4.0 / 100.0


def inercia_equivalente(concreto: Concreto, h: float, m_a: float
                        ) -> tuple[float, str]:
    """``Ieq`` estimado em dois patamares e o estádio correspondente."""
    Ic = inercia_bruta(h)
    m_r = momento_fissuracao(concreto, h)
    if m_a <= m_r:
        return Ic, "I - não fissurada"
    return 0.30 * Ic, "II - fissurada"


def verificar(laje: Laje, esforcos, concreto: Concreto,
              cfg: Config) -> ResultadoELS:
    """Flecha imediata e diferida da laje, contra o limite da Tabela 13.3."""
    balanco = esforcos.classificacao.balanco
    # a flecha da laje armada em cruz é lida com o vão menor, que é o vão da
    # tabela de k; na armada em uma direção, com o vão que ela vaza
    vao = esforcos.vao_referencia
    res = ResultadoELS(laje=laje.nome, h=laje.h, p_ser=esforcos.p_ser,
                       vao=vao, k=esforcos.k_flecha, Ecs=concreto.Ecs)
    res.Ic = inercia_bruta(laje.h)
    res.m_r = momento_fissuracao(concreto, laje.h)
    res.m_a = esforcos.m_ser_maximo
    res.Ieq, res.estadio = inercia_equivalente(concreto, laje.h, res.m_a)

    # f = k p a⁴ / (Ecs Ieq), com p em kN/m², a em m, Ecs em MPa e Ieq em
    # cm⁴/m. Passando tudo para kN e cm: p/10⁴ kN/cm², a.100 cm, Ecs/10.
    p = res.p_ser / 1e4                             # kN/cm²
    L = vao * 100.0                                 # cm
    Ecs = concreto.Ecs / 10.0                       # kN/cm²
    if Ecs * res.Ieq > 0.0:
        res.f_imediata = res.k * p * L ** 4 / (Ecs * res.Ieq)
    res.f_diferida = cfg.fator_fluencia * res.f_imediata

    res.divisor = cfg.divisor_flecha_balanco if balanco else cfg.divisor_flecha
    res.f_admissivel = L / res.divisor
    return res


# ---------------------------------------------------------------------------
# Pré-dimensionamento da espessura (§1.6)
# ---------------------------------------------------------------------------

def espessura_minima_normativa(laje: Laje) -> float:
    """Espessura mínima do item 13.2.4.1, cm, pelo destino da laje."""
    from .materiais import ESPESSURA_MINIMA
    return ESPESSURA_MINIMA[laje.destino]


@dataclass
class Predimensionamento:
    """Rastro do laço que escolheu a espessura."""

    laje: str
    h_inicial: float
    h_final: float
    tentativas: list[tuple[float, float, float, str]]   # h, f_inf, f_adm, veredito
    convergiu: bool = True
    mensagem: str = ""


def predimensionar(laje: Laje, concreto: Concreto, cfg: Config
                   ) -> Predimensionamento:
    """Escolhe a espessura da laje pelo roteiro do §1.6.

    Arbitra o mínimo do item 13.2.4.1, refaz a composição de cargas a cada
    centímetro -- o peso próprio muda, e é isso que faz o laço não ser
    trivial -- e para quando a flecha de longa duração couber no limite.

    A laje é devolvida com a espessura escolhida: a função **altera** o campo
    ``h`` da laje recebida, porque é a espessura dela que está sendo decidida.
    """
    from . import esforcos as esf_mod

    h0 = max(espessura_minima_normativa(laje), 5.0)
    laje.h = h0
    tentativas: list[tuple[float, float, float, str]] = []
    h = h0
    while h <= cfg.espessura_maxima + 1e-9:
        laje.h = h
        esf = esf_mod.calcular(laje, cfg)
        r = verificar(laje, esf, concreto, cfg)
        veredito = "atende" if r.atende else "flecha excessiva"
        tentativas.append((h, r.f_diferida, r.f_admissivel, veredito))
        if r.atende:
            return Predimensionamento(
                laje.nome, h0, h, tentativas, True,
                f"espessura de {h:g} cm: flecha de longa duração de "
                f"{r.f_diferida:.2f} cm contra o limite de "
                f"{r.f_admissivel:.2f} cm (L/{r.divisor})")
        h += 1.0
    laje.h = cfg.espessura_maxima
    return Predimensionamento(
        laje.nome, h0, cfg.espessura_maxima, tentativas, False,
        f"a flecha não couber no limite até {cfg.espessura_maxima:g} cm: "
        f"reveja os vãos, a vinculação ou o limite adotado")


# ---------------------------------------------------------------------------
# Fissuração (17.3.3.2)
# ---------------------------------------------------------------------------

@dataclass
class ResultadoFissuracao:
    """Abertura característica de fissuras de uma seção, mm."""

    rotulo: str
    phi: float                      # mm
    sigma_s: float = 0.0            # MPa, tensão no Estádio II
    rho_r: float = 0.0
    wk_1: float = 0.0               # mm, primeira expressão
    wk_2: float = 0.0               # mm, segunda expressão
    wk: float = 0.0                 # mm, a menor das duas
    wk_limite: float = 0.3          # mm
    dispensada: bool = False
    motivo: str = ""

    @property
    def atende(self) -> bool:
        return self.dispensada or self.wk <= self.wk_limite + 1e-9


def verificar_fissuracao(rotulo: str, m_ser: float, As: float, phi: float,
                         d: float, h: float, concreto: Concreto, aco,
                         wk_limite: float) -> ResultadoFissuracao:
    """Abertura de fissuras pelas duas expressões do item 17.3.3.2.

    A tensão na armadura sai do Estádio II com a hipótese usual da laje:
    braço de ``0,85 d``, que é o que resta quando a linha neutra está no
    terço superior. É aproximação, mas a laje de edifício corrente fica
    longe do limite -- e o item 17.3.3.3 dispensa a verificação quando a
    armadura mínima é respeitada e o cobrimento é o nominal.
    """
    res = ResultadoFissuracao(rotulo=rotulo, phi=phi, wk_limite=wk_limite)
    if As <= 0.0 or m_ser <= 0.0:
        res.dispensada = True
        res.motivo = "seção sem momento de serviço ou sem armadura"
        return res

    # tensão de serviço na armadura, MPa
    braco = 0.85 * d                                    # cm
    res.sigma_s = m_ser * 100.0 / (As * braco) * 10.0   # kN·cm / cm³ -> MPa

    # área de envolvimento: a faixa de 1 m com 7,5 phi de cada lado da barra
    acri = 100.0 * min(7.5 * phi / 10.0 * 2.0, h)       # cm²/m
    res.rho_r = As / acri if acri > 0 else 0.0

    eta1 = aco.eta_1
    Es = aco.Es
    fctm = concreto.fctm
    if res.rho_r > 0.0:
        res.wk_1 = (phi / (12.5 * eta1)) * (res.sigma_s / Es) * \
            (3.0 * res.sigma_s / fctm)
        res.wk_2 = (phi / (12.5 * eta1)) * (res.sigma_s / Es) * \
            (4.0 / res.rho_r + 45.0)
        res.wk = min(res.wk_1, res.wk_2)
    return res
