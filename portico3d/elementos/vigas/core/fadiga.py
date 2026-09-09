# -*- coding: utf-8 -*-
"""
fadiga.py
Estado-limite último de fadiga (NBR 6118, item 23.5).

A verificação é feita com uma única intensidade de solicitação, a da
**combinação frequente** (23.5.2), em regime elástico, com as tensões de flexão
no Estádio II (23.5.3). Os coeficientes do item são ``gamma_f = 1,0``,
``gamma_c = 1,4`` e ``gamma_s = 1,0``, e admite-se ``alpha_e = 10``.

Três verificações:

``concreto comprimido`` (23.5.4.1)
    ``eta_c,grad · gamma_f · sigma_c,máx <= f_cd,fad = 0,45 f_cd``, com
    ``eta_c,grad = 1 / (1,5 - 0,5 |sigma_c1|/|sigma_c2|)``.

``concreto tracionado`` (23.5.4.2)
    ``gamma_f · sigma_ct,máx <= f_ctd,fad = 0,3 f_ctd``. Só faz sentido onde a
    seção não fissurou; onde já fissurou, a tração do concreto é desprezada e a
    verificação passa para a armadura.

``armadura`` (23.5.5)
    ``gamma_f · Delta_sigma_s <= Delta_f_sd,fad`` da Tabela 23.2. A variação de
    tensão é entre a combinação frequente e a permanente: é a parcela variável
    que oscila.

O cortante entra com a contribuição do concreto reduzida (23.5.3): ``Vc`` cai à
metade no Modelo I e, no Modelo II, corrige-se a biela por
``tg theta_cor = raiz(tg theta) <= 1``.

Unidades: momentos em kN.m, forças em kN, comprimentos em cm, tensões em MPa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .els import estadio_ii, momento_fissuracao
from .materiais import Aco, Concreto, delta_fsd_fad
from .modelo import Secao

#: coeficientes do item 23.5.3
GAMMA_F = 1.0
GAMMA_C = 1.4
GAMMA_S = 1.0

#: alpha_e admitido pelo item 23.5.3
ALPHA_E = 10.0

#: distância da face dentro da qual se medem sigma_c1 e sigma_c2 (Figura 23.1)
FAIXA_GRADIENTE = 30.0          # cm


def theta_corrigido(theta_graus: float) -> float:
    """Inclinação da biela corrigida para fadiga, graus (23.5.3).

        tg theta_cor = raiz(tg theta) <= 1
    """
    tg = math.sqrt(math.tan(math.radians(theta_graus)))
    return math.degrees(math.atan(min(tg, 1.0)))


def eta_c_grad(sigma_c1: float, sigma_c2: float) -> float:
    """Fator de gradiente das tensões de compressão (23.5.4.1)."""
    if abs(sigma_c2) < 1e-9:
        return 1.0
    razao = min(abs(sigma_c1) / abs(sigma_c2), 1.0)
    return 1.0 / (1.5 - 0.5 * razao)


@dataclass
class ResultadoFadiga:
    """Verificação de fadiga de uma seção (23.5)."""

    regiao: str
    M_frequente: float        # kN.m
    M_permanente: float       # kN.m
    fissurada: bool
    x_II: float               # cm
    sigma_s_max: float        # MPa
    sigma_s_min: float        # MPa
    delta_sigma_s: float      # MPa
    delta_fsd_fad: float      # MPa
    sigma_c_max: float        # MPa
    sigma_c1: float           # MPa
    eta_grad: float
    fcd_fad: float            # MPa
    sigma_ct_max: float       # MPa
    fctd_fad: float           # MPa
    phi: float                # mm
    ok_armadura: bool
    ok_concreto_comprimido: bool
    ok_concreto_tracionado: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.ok_armadura and self.ok_concreto_comprimido
                and self.ok_concreto_tracionado)

    @property
    def veredito(self) -> str:
        return "OK" if self.ok else "NÃO OK"


def verificar_secao(secao: Secao, concreto: Concreto, aco: Aco,
                    M_frequente: float, M_permanente: float, As: float,
                    d: float, phi_mm: float, regiao: str = "",
                    As_linha: float = 0.0, d_linha: float = 0.0,
                    face: str = "inferior",
                    marinho: bool = False) -> ResultadoFadiga:
    """Verifica a fadiga de uma seção sob flexão (23.5.4 e 23.5.5)."""
    e2 = estadio_ii(secao, ALPHA_E, As, d, As_linha, d_linha, face)
    Mr = momento_fissuracao(secao, concreto, face, estado="formacao")
    fissurada = abs(M_frequente) > Mr

    # -- armadura (23.5.5) --------------------------------------------------
    def sigma_s(M: float) -> float:
        if e2.I <= 0.0:
            return 0.0
        return ALPHA_E * abs(M) * 100.0 * (d - e2.x) / e2.I * 10.0   # MPa

    s_max = sigma_s(M_frequente)
    s_min = sigma_s(M_permanente)
    delta = abs(s_max - s_min)
    limite_aco = delta_fsd_fad(phi_mm, aco.categoria, marinho=marinho)

    # -- concreto comprimido (23.5.4.1) -------------------------------------
    if e2.I > 0.0 and e2.x > 0.0:
        # no Estádio II homogeneizado, sigma_c = M.x / I_II
        sc2 = abs(M_frequente) * 100.0 * e2.x / e2.I * 10.0
        # sigma_c1 é a tensão a 30 cm da face comprimida, no mesmo diagrama
        y1 = max(e2.x - FAIXA_GRADIENTE, 0.0)
        sc1 = sc2 * y1 / e2.x if e2.x > 0 else 0.0
    else:
        sc2 = sc1 = 0.0
    eta = eta_c_grad(sc1, sc2)
    fcd_fad = 0.45 * concreto.fck / GAMMA_C

    # -- concreto tracionado (23.5.4.2) -------------------------------------
    # só onde a seção não fissurou: no Estádio II a tração é desprezada
    if fissurada:
        sct = 0.0
    else:
        yt = secao.y_cg if face == "inferior" else secao.h - secao.y_cg
        sct = abs(M_frequente) * 100.0 * yt / secao.inercia * 10.0
    fctd_fad = 0.3 * concreto.fctd

    ok_aco = GAMMA_F * delta <= limite_aco + 1e-9
    ok_comp = eta * GAMMA_F * sc2 <= fcd_fad + 1e-9
    ok_trac = GAMMA_F * sct <= fctd_fad + 1e-9

    avisos: list[str] = []
    if not ok_aco:
        avisos.append(av.erro(
            f"Fadiga da armadura: variação de tensão de {delta:.0f} MPa "
            f"supera Δfsd,fad = {limite_aco:.0f} MPa da Tabela 23.2 para "
            f"Ø{phi_mm:g} (23.5.5). Aumente a armadura ou reduza a bitola."))
    if not ok_comp:
        avisos.append(av.erro(
            f"Fadiga do concreto comprimido: ηc,grad·σc,máx = "
            f"{eta * sc2:.1f} MPa supera fcd,fad = 0,45·fcd = "
            f"{fcd_fad:.1f} MPa (23.5.4.1)."))
    if not ok_trac:
        avisos.append(av.erro(
            f"Fadiga do concreto tracionado: σct,máx = {sct:.2f} MPa supera "
            f"fctd,fad = 0,3·fctd = {fctd_fad:.2f} MPa (23.5.4.2)."))
    return ResultadoFadiga(
        regiao=regiao, M_frequente=M_frequente, M_permanente=M_permanente,
        fissurada=fissurada, x_II=e2.x, sigma_s_max=s_max, sigma_s_min=s_min,
        delta_sigma_s=delta, delta_fsd_fad=limite_aco, sigma_c_max=sc2,
        sigma_c1=sc1, eta_grad=eta, fcd_fad=fcd_fad, sigma_ct_max=sct,
        fctd_fad=fctd_fad, phi=phi_mm, ok_armadura=ok_aco,
        ok_concreto_comprimido=ok_comp, ok_concreto_tracionado=ok_trac,
        avisos=avisos)


@dataclass
class ResultadoFadigaEstribo:
    """Verificação de fadiga do estribo (23.5.3 e 23.5.5)."""

    x: float                  # m
    V_frequente: float        # kN
    V_permanente: float       # kN
    Vc_reduzido: float        # kN
    theta: float              # graus, já corrigido no Modelo II
    asw: float                # cm²/m efetiva
    delta_sigma_s: float      # MPa
    delta_fsd_fad: float      # MPa
    ok: bool
    avisos: list[str] = field(default_factory=list)

    @property
    def veredito(self) -> str:
        return "OK" if self.ok else "NÃO OK"


def verificar_estribo(V_frequente: float, V_permanente: float, Vc: float,
                      asw_cm2_m: float, d: float, phi_estribo: float,
                      aco: Aco, modelo: int = 1, theta: float = 45.0,
                      alpha: float = 90.0, x: float = 0.0,
                      marinho: bool = False) -> ResultadoFadigaEstribo:
    """Fadiga da armadura transversal, com a redução do item 23.5.3.

    No Modelo I a parcela do concreto cai à metade; no Modelo II a biela é
    corrigida e não há redução de ``Vc``. A variação de tensão no estribo vem
    da diferença entre a combinação frequente e a permanente.
    """
    th = theta if modelo == 2 else 45.0
    if modelo == 1:
        vc = 0.5 * Vc
    else:
        th = theta_corrigido(theta)
        vc = Vc
    th_r, al_r = math.radians(th), math.radians(alpha)
    braco = 0.9 * d * (1.0 / math.tan(th_r) + 1.0 / math.tan(al_r)) \
        * math.sin(al_r)

    def sigma_sw(V: float) -> float:
        vsw = max(abs(V) - vc, 0.0)
        if asw_cm2_m <= 0.0 or braco <= 0.0:
            return 0.0
        return vsw / (asw_cm2_m / 100.0 * braco) * 10.0        # MPa

    delta = abs(sigma_sw(V_frequente) - sigma_sw(V_permanente))
    # o estribo é barra dobrada: o pino da Tabela 9.2 reduz o limite (nota d
    # da Tabela 23.2)
    d_sobre_phi = (aco.diametro_dobramento_estribo(phi_estribo)
                   / (phi_estribo / 10.0))
    limite = delta_fsd_fad(phi_estribo, aco.categoria,
                           d_sobre_phi=d_sobre_phi, marinho=marinho)
    ok = GAMMA_F * delta <= limite + 1e-9
    avisos: list[str] = []
    if not ok:
        extra = ""
        if delta > aco.fyd:
            # não é erro de conta: o item 23.5.3 manda usar metade de Vc, e
            # com isso o estribo recebe mais carga do que no ELU. Passar de
            # fyd é sinal de que a seção não serve para carga cíclica
            extra = (f" O valor passa de fyd = {aco.fyd:.0f} MPa porque o "
                     f"item 23.5.3 manda reduzir Vc à metade no Modelo I: "
                     f"a armadura transversal desta viga está muito longe do "
                     f"necessário para carga cíclica.")
        avisos.append(av.erro(
            f"Fadiga do estribo em x = {x:.2f} m: variação de "
            f"{delta:.0f} MPa supera Δfsd,fad = {limite:.0f} MPa (Tabela 23.2, "
            f"barra dobrada com pino de {d_sobre_phi:.0f}Ø). Reduza o "
            f"espaçamento ou aumente a bitola do estribo.{extra}"))
    return ResultadoFadigaEstribo(
        x=x, V_frequente=V_frequente, V_permanente=V_permanente,
        Vc_reduzido=vc, theta=th, asw=asw_cm2_m, delta_sigma_s=delta,
        delta_fsd_fad=limite, ok=ok, avisos=avisos)
