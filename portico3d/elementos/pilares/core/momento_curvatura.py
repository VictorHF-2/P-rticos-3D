# -*- coding: utf-8 -*-
"""
momento_curvatura.py
Relação momento-curvatura de **deformabilidade** (itens 15.3 e 15.3.1 da NBR
6118:2026, Figura 15.1) e a rigidez secante ``(EI)sec`` que sai dela.

A norma separa duas curvas:

* a de **deformabilidade**, com pico do concreto ``1,10 fcd`` ("já incluído
  o efeito de carga mantida", Rüsch) e aço a ``fyd``, para a normal
  ``NRd/gamma_f3`` -- é a que dá as curvaturas;
* a de **cálculo**, com ``0,85 eta_c fcd`` (o diagrama do ELU), que só define
  o momento resistente ``MRd`` correspondente a ``NRd``.

A reta ``AB`` -- da origem ao ponto da curva de deformabilidade em que
``M = MRd/gamma_f3`` -- é a rigidez secante ``(EI)sec``, que "pode ser
utilizada em processos aproximados para flexão composta normal ou oblíqua".
É a base do pilar-padrão acoplado a diagramas M, N, 1/r (15.8.3.3.4) e do
método geral (15.8.3.2).

O motor é o mesmo do ELU (:mod:`pilares.core.seccional`): só o concreto muda,
para o de pico ``1,10 fcd`` (:class:`ConcretoDeformabilidade`), e o estado de
deformação é o de curvatura livre (:func:`seccional.resolver_estado`), não o
amarrado aos domínios.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import seccional as sc
from .materiais import Concreto

#: Coeficiente gamma_f3 da formulação de segurança do item 15.3.1.
GAMMA_F3 = 1.1

#: Pico do concreto na curva de deformabilidade, sobre ``fcd`` (item 15.3).
PICO_DEFORMABILIDADE = 1.10


class ConcretoDeformabilidade(Concreto):
    """O mesmo concreto, com o pico do parábola-retângulo em ``1,10 fcd``.

    Os demais parâmetros do diagrama (``eps_c2``, ``eps_cu``, ``n``) são os
    da Seção 8, como o item 15.3 manda ("diagramas tensão-deformação dos
    materiais definidos na Seção 8"). ``fator_fluencia`` (1 + phi_ef) estica
    ``eps_c2`` e ``eps_cu`` -- a fluência pela curva, opção ``diagrama`` de
    ``Config.fluencia_metodo``; 1,0 sem ela.
    """

    fator_fluencia = 1.0

    @property
    def fator_pico(self) -> float:
        return PICO_DEFORMABILIDADE

    @property
    def eps_c2_mil(self) -> float:
        return Concreto.eps_c2_mil.fget(self) * self.fator_fluencia

    @property
    def eps_cu_mil(self) -> float:
        return Concreto.eps_cu_mil.fget(self) * self.fator_fluencia


def concreto_deformabilidade(c: Concreto, fator_fluencia: float = 1.0
                             ) -> ConcretoDeformabilidade:
    cd = ConcretoDeformabilidade(fck=c.fck, gamma_c=c.gamma_c,
                                 agregado=c.agregado,
                                 peso_especifico=c.peso_especifico)
    cd.fator_fluencia = fator_fluencia
    return cd


def secao_deformabilidade(secao: sc.SecaoDiscreta,
                          fator_fluencia: float = 1.0) -> sc.SecaoDiscreta:
    """A mesma seção (contorno e barras) com o concreto de deformabilidade.

    Guardada na própria seção, uma por ``fator_fluencia``: o pilar-padrão e o
    método geral pedem a curva várias vezes para a mesma armadura.
    """
    cache = getattr(secao, "_deformabilidade", None)
    if not isinstance(cache, dict):
        cache = secao._deformabilidade = {}
    pronta = cache.get(fator_fluencia)
    if pronta is None:
        pronta = sc.SecaoDiscreta(
            secao.contornos, secao.barras,
            concreto_deformabilidade(secao.concreto, fator_fluencia),
            secao.aco, secao.n_fatias)
        cache[fator_fluencia] = pronta
    return pronta


def theta_da_direcao(direcao: str, sentido: float = 1.0) -> float:
    """Direção da linha neutra da flexão composta normal em ``direcao`` --
    a mesma convenção de :func:`seccional.momento_resistente_uniaxial`."""
    if isinstance(direcao, str):
        theta = 0.0 if direcao == "x" else math.pi / 2.0
    else:
        theta = float(direcao)       # direção principal, em radianos
    return theta + (math.pi if sentido < 0 else 0.0)


def dentro_dos_limites(secao: sc.SecaoDiscreta, theta: float,
                       est: sc.Estado) -> bool:
    """O plano está dentro dos limites de deformação dos domínios (17.2.2)?

    A curva de deformabilidade termina onde a seção "rompe" com o diagrama
    dela: encurtamento ``eps_cu`` na borda, alongamento de 10 ‰ na barra mais
    tracionada, ou ``eps_c2`` no ponto a ``(eps_cu - eps_c2)/eps_cu . h`` da
    borda comprimida (polo C).
    """
    c = secao.concreto
    u_min, u_max = secao.extremos(theta)
    h = u_max - u_min
    p = est.plano
    if p.eps(u_max) > c.eps_cu_mil + 1e-9:
        return False
    ub = secao.u_barras(theta)
    if ub and p.eps(min(ub)) < -sc.EPS_S_MAXIMA - 1e-9:
        return False
    u_c = u_max - h * (c.eps_cu_mil - c.eps_c2_mil) / c.eps_cu_mil
    return p.eps(u_c) <= c.eps_c2_mil + 1e-9


def momento_na_curvatura(secao: sc.SecaoDiscreta, theta: float, k: float,
                         N: float, direcao: str
                         ) -> tuple[float, sc.Estado | None]:
    """Momento para a curvatura ``k`` (‰/cm) e a normal ``N`` (kN), e o
    estado; ``(nan, None)`` se não há equilíbrio.

    É a componente na direção da flexão **com sinal, no sentido de**
    ``theta`` (positiva quando a face comprimida é a de ``theta``). Com
    armadura assimétrica a deformação uniforme já dá momento -- o centro de
    resistência não é o CG --, e a curva não parte de zero: no sentido fraco
    ela parte de um valor negativo. Tomar o módulo, como até a R05, achava
    ``M >= MRd/gamma_f3`` com curvatura quase nula e um ``(EI)sec`` infinito.
    """
    est = sc.resolver_estado(secao, theta, k, N)
    if est is None:
        return float("nan"), None
    # projeção no sentido de theta: theta = 0 / pi na direção x, pi/2 / 3pi/2
    # na direção y
    return est.Mx * math.cos(theta) + est.My * math.sin(theta), est


@dataclass
class RigidezSecante:
    """``(EI)sec`` de uma direção e um sentido, e de onde ela saiu."""

    EI: float                 # kN·cm²
    MRd: float                # kN·cm, curva de cálculo (0,85 eta_c fcd)
    M_B: float                # kN·cm, MRd/gamma_f3 -- o ponto B da Figura 15.1
    curvatura_B: float        # 1/cm
    N_deformabilidade: float  # kN, Nd/gamma_f3


def _curvatura_limite(sd: sc.SecaoDiscreta, theta: float, N: float,
                      direcao: str) -> float:
    """Maior curvatura (‰/cm) dentro dos limites do ELU de deformabilidade,
    para a normal ``N``."""
    u_min, u_max = sd.extremos(theta)
    h = u_max - u_min
    c = sd.concreto
    lo, hi = 0.0, 2.0 * (c.eps_cu_mil + sc.EPS_S_MAXIMA) / h
    for _ in range(80):
        m = (lo + hi) / 2.0
        _, est = momento_na_curvatura(sd, theta, m, N, direcao)
        if est is not None and dentro_dos_limites(sd, theta, est):
            lo = m
        else:
            hi = m
        if hi - lo < 1e-9 * hi:
            break
    return lo


def rigidez_secante(secao: sc.SecaoDiscreta, Nd: float, direcao: str,
                    sentido: float = 1.0, gamma_f3: float = GAMMA_F3,
                    fator_fluencia: float = 1.0) -> RigidezSecante | None:
    """``(EI)sec`` da Figura 15.1 para a normal ``Nd`` (kN, compressão
    positiva) e flexão composta normal em ``direcao``.

    ``MRd`` sai do diagrama de cálculo (a seção do ELU, ``secao``); a
    curvatura do ponto B, da curva de deformabilidade com ``Nd/gamma_f3`` no
    momento ``MRd/gamma_f3``. Devolve ``None`` se a curva de deformabilidade
    não alcança ``MRd/gamma_f3`` dentro dos limites de deformação -- caso em
    que a reta AB não está definida.
    """
    cache = getattr(secao, "_rigidez", None)
    if cache is None:
        cache = secao._rigidez = {}
    chave = (Nd, direcao, 1.0 if sentido >= 0 else -1.0, gamma_f3,
             fator_fluencia)
    if chave in cache:
        return cache[chave]

    MRd = sc.momento_resistente_uniaxial(secao, Nd, direcao, sentido)
    sd = secao_deformabilidade(secao, fator_fluencia)
    N = Nd / gamma_f3
    alvo = MRd / gamma_f3
    theta = theta_da_direcao(direcao, sentido)
    resultado = None
    if MRd > 0.0:
        k_lim = _curvatura_limite(sd, theta, N, direcao)
        M_lim, _ = momento_na_curvatura(sd, theta, k_lim, N, direcao)
        if k_lim > 0.0 and math.isfinite(M_lim) and M_lim >= alvo:
            # primeira travessia de M(k) = alvo: varredura grossa e bisseção
            n = 40
            k_ant, M_ant = 0.0, 0.0
            k_b = None
            for i in range(1, n + 1):
                k = k_lim * i / n
                M, _ = momento_na_curvatura(sd, theta, k, N, direcao)
                if math.isfinite(M) and M >= alvo:
                    lo, hi = k_ant, k
                    for _ in range(80):
                        m = (lo + hi) / 2.0
                        Mm, _ = momento_na_curvatura(sd, theta, m, N, direcao)
                        if math.isfinite(Mm) and Mm >= alvo:
                            hi = m
                        else:
                            lo = m
                        if hi - lo < 1e-12 * hi:
                            break
                    k_b = (lo + hi) / 2.0
                    break
                k_ant, M_ant = k, M
            if k_b and k_b > 0.0:
                curv = k_b / 1000.0
                resultado = RigidezSecante(EI=alvo / curv, MRd=MRd, M_B=alvo,
                                           curvatura_B=curv,
                                           N_deformabilidade=N)
    cache[chave] = resultado
    return resultado
