# -*- coding: utf-8 -*-
"""
cisalhamento.py
Força cortante em lajes, itens 19.4.1 e 19.4.2 da NBR 6118.

A apostila §1.7 dispensa a verificação: "em lajes de estruturas de edifícios
correntes, as cargas atuantes são relativamente baixas e não é necessária a
verificação das tensões devidas às forças cortantes e nem o dimensionamento
de armadura transversal". Isso é verdade na laje de dormitório de 8 cm -- e
deixa de ser na laje espessa de vão curto, na laje de garagem e na laje que
recebe parede pesada. O programa verifica sempre e diz em quanto ficou.

**Sem armadura transversal (19.4.1)**

    VSd <= VRd1 = [tau_Rd . k . (1,2 + 40 rho_1) + 0,15 sigma_cp] . bw . d

    tau_Rd = 0,25 fctd,  com fctd = fctk,inf / gamma_c e o fck limitado a
             60 MPa no cálculo de tau_Rd;
    rho_1  = As1 / (bw d), não maior que 0,02;
    k      = |1,6 - d| >= 1, com d em metros -- e igual a 1 quando 50 % da
             armadura inferior não chega ao apoio.

Na laje o ``k`` é sempre o ``1,6 - d``, e não por escolha: o item 20.1 proíbe
escalonar a armadura positiva da laje maciça, de modo que ela chega inteira
ao apoio. É o mesmo item que garante o ``As1`` da expressão, que pede
armadura ancorada ``d + lb,nec`` além da seção.

O ``VSd`` é lido **a uma distância d da face do apoio**, como o item manda.
Na faixa que vaza em uma direção a redução é exata: desconta-se a carga do
trecho ``t/2 + d``. Na laje armada em cruz o cortante de bordo é a própria
reação de apoio, e ela fica sem reduzir -- a favor da segurança, porque a
área de influência daquele trecho não é um retângulo.

**Com armadura transversal (19.4.2)**

Valem os critérios de viga (17.4.2), com um teto na tensão do estribo que é
próprio da laje: 250 MPa até 15 cm de espessura e 435 MPa acima de 35 cm,
interpolando linearmente entre as duas -- estribo de laje fina não consegue
mobilizar o escoamento.
"""

from __future__ import annotations

from dataclasses import dataclass

from .materiais import Aco, Concreto

#: Teto da tensão do estribo em laje (19.4.2), MPa, por espessura em cm.
FYWD_LAJE = ((15.0, 250.0), (35.0, 435.0))

#: Valor de a_l a considerar na distribuição da armadura da laje (19.4.1,
#: último parágrafo): 1,5 d.
FATOR_DECALAGEM = 1.5


def fywd_laje(h: float) -> float:
    """Tensão máxima do estribo de laje, MPa (19.4.2)."""
    (h1, f1), (h2, f2) = FYWD_LAJE
    if h <= h1:
        return f1
    if h >= h2:
        return f2
    return f1 + (f2 - f1) * (h - h1) / (h2 - h1)


def tau_rd(concreto: Concreto) -> float:
    """``tau_Rd = 0,25 fctd``, em kN/cm² (19.4.1).

    O item limita o ``tau_Rd`` ao correspondente a fck = 60 MPa; acima disso
    a resistência à tração continua a crescer na fórmula, mas não pode ser
    aproveitada aqui.
    """
    fck = min(concreto.fck, 60.0)
    limitado = Concreto(fck=fck, gamma_c=concreto.gamma_c,
                        agregado=concreto.agregado)
    return 0.25 * limitado.fctd / 10.0


@dataclass
class ResultadoCortante:
    """Verificação da força cortante em um bordo da laje."""

    rotulo: str
    h: float                        # cm
    d: float                        # cm
    v_sd_apoio: float = 0.0         # kN/m, na face do apoio
    v_sd: float = 0.0               # kN/m, a d da face
    As1: float = 0.0                # cm²/m
    rho_1: float = 0.0
    k: float = 1.0
    tau_rd: float = 0.0             # kN/cm²
    v_rd1: float = 0.0              # kN/m
    reduzido: bool = False
    # -- armadura transversal, quando necessária ---------------------------
    precisa_armadura: bool = False
    v_rd2: float = 0.0              # kN/m, ruína da biela
    fywd: float = 0.0               # MPa
    asw_por_m2: float = 0.0         # cm²/m por metro de laje
    erro: str = ""

    @property
    def atende(self) -> bool:
        return not self.erro and self.v_sd <= self.v_rd1 + 1e-9

    @property
    def aproveitamento(self) -> float:
        return self.v_sd / self.v_rd1 if self.v_rd1 > 0.0 else 0.0


def verificar(rotulo: str, v_sd_apoio: float, h: float, d: float, As1: float,
              concreto: Concreto, aco: Aco, p_d: float = 0.0,
              t_apoio: float = 0.0, reduzir: bool = False,
              sigma_cp: float = 0.0) -> ResultadoCortante:
    """Verifica o cortante de um bordo da laje pelo item 19.4.

    ``v_sd_apoio`` é a reação de cálculo do bordo, em kN/m; ``p_d`` a carga de
    cálculo e ``t_apoio`` a largura do apoio, ambas usadas só quando
    ``reduzir`` pede a leitura a ``d`` da face -- o que só é exato na faixa
    que vaza em uma direção.
    """
    res = ResultadoCortante(rotulo=rotulo, h=h, d=d, v_sd_apoio=v_sd_apoio,
                            As1=As1)
    if d <= 0.0:
        res.erro = f"altura útil de {d:.1f} cm"
        return res

    res.v_sd = v_sd_apoio
    if reduzir and p_d > 0.0:
        recuo = (t_apoio / 2.0 + d) / 100.0          # m
        res.v_sd = max(0.0, v_sd_apoio - p_d * recuo)
        res.reduzido = True

    res.rho_1 = min(As1 / (100.0 * d), 0.02)
    res.k = max(1.0, 1.6 - d / 100.0)
    res.tau_rd = tau_rd(concreto)
    # VRd1 em kN/m: [tau_Rd k (1,2 + 40 rho1) + 0,15 sigma_cp] . bw . d
    res.v_rd1 = (res.tau_rd * res.k * (1.2 + 40.0 * res.rho_1)
                 + 0.15 * sigma_cp / 10.0) * 100.0 * d

    if res.v_sd > res.v_rd1 + 1e-9:
        res.precisa_armadura = True
        res.fywd = fywd_laje(h)
        # biela (17.4.2.2, Modelo I): VRd2 = 0,27 alfa_v2 fcd bw d
        res.v_rd2 = 0.27 * concreto.alfa_v2 * concreto.fcd / 10.0 * 100.0 * d
        if res.v_sd > res.v_rd2:
            res.erro = (f"VSd = {res.v_sd:.1f} kN/m passa da ruína da biela "
                        f"VRd2 = {res.v_rd2:.1f} kN/m (17.4.2.2): a laje "
                        f"precisa ser mais espessa")
            return res
        # Vc do Modelo I: 0,6 fctd bw d
        vc = 0.6 * concreto.fctd / 10.0 * 100.0 * d
        vsw = max(0.0, res.v_sd - vc)
        # Asw/s por metro de largura, com estribo vertical: Vsw = 0,9 d fywd A
        res.asw_por_m2 = vsw / (0.9 * d * res.fywd / 10.0) * 100.0
    return res
