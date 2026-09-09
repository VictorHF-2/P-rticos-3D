# -*- coding: utf-8 -*-
"""
materiais.py
Propriedades de concreto e aço segundo a ABNT NBR 6118 e tabelas auxiliares
(bitolas comerciais, cobrimentos, classes de agressividade ambiental).

Unidades adotadas neste módulo:
    resistências e módulos ..... MPa (as propriedades em kN/cm² são explícitas)
    comprimentos ............... cm
Funções puras, sem dependência de interface gráfica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Tabelas auxiliares
# ---------------------------------------------------------------------------

#: Bitolas comerciais de barras (NBR 7480:2024), diâmetro nominal em mm.
BITOLAS_BARRAS = (5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0, 25.0, 32.0, 40.0)

#: Bitolas usuais para estribos, em mm.
BITOLAS_ESTRIBOS = (5.0, 6.3, 8.0, 10.0, 12.5)

#: Massa linear nominal das barras, kg/m (NBR 7480:2024, Tabela 4).
MASSA_LINEAR = {
    5.0: 0.154, 6.3: 0.245, 8.0: 0.395, 10.0: 0.617, 12.5: 0.963,
    16.0: 1.578, 20.0: 2.466, 25.0: 3.853, 32.0: 6.313, 40.0: 9.865,
}

#: Taxa mínima de armadura de flexão, % da seção de concreto, em função do fck
#: (NBR 6118, Tabela 17.3, seção retangular com gamma_c = 1,4).
RHO_MIN_FLEXAO = {
    20: 0.150, 25: 0.150, 30: 0.150, 35: 0.164, 40: 0.179, 45: 0.194,
    50: 0.208, 55: 0.211, 60: 0.219, 65: 0.226, 70: 0.233, 75: 0.239,
    80: 0.245, 85: 0.251, 90: 0.256,
}

#: Cobrimento nominal para vigas, cm, por classe de agressividade (Tabela 7.2).
COBRIMENTO_NOMINAL = {"I": 2.5, "II": 3.0, "III": 4.0, "IV": 5.0}

#: Abertura característica limite de fissuras, mm (Tabela 13.4, concreto armado).
WK_LIMITE = {"I": 0.4, "II": 0.3, "III": 0.3, "IV": 0.2}

#: Descrição das classes de agressividade ambiental (Tabela 6.1).
DESCRICAO_CAA = {
    "I": "Fraca - rural / submersa",
    "II": "Moderada - urbana",
    "III": "Forte - marinha / industrial",
    "IV": "Muito forte - respingos de maré / quimicamente agressiva",
}

#: Diâmetro do pino de dobramento D dos ganchos da armadura longitudinal,
#: em múltiplos da bitola (Tabela 9.1). None = combinação não prevista.
PINO_DOBRAMENTO = {
    "CA-25": {"menor": 4.0, "maior": 5.0},
    "CA-50": {"menor": 5.0, "maior": 8.0},
    "CA-60": {"menor": 6.0, "maior": None},
}

#: Diâmetro do pino de dobramento dos **estribos**, em múltiplos da bitola
#: (Tabela 9.2). As faixas são phi <= 10, 10 < phi < 20 e phi >= 20 mm.
PINO_DOBRAMENTO_ESTRIBO = {
    "CA-25": (3.0, 4.0, 5.0),
    "CA-50": (3.0, 5.0, 8.0),
    "CA-60": (3.0, 3.0, 3.0),
}

#: Delta f_sd,fad,mín para 2x10^6 ciclos, MPa, de barra reta ou dobrada com
#: pino D >= 25 phi (Tabela 23.2, armadura passiva CA-50).
DELTA_FSD_FAD = {
    10.0: 190.0, 12.5: 190.0, 16.0: 190.0, 20.0: 185.0, 22.0: 180.0,
    25.0: 175.0, 32.0: 165.0, 40.0: 150.0,
}

#: Delta f_sd,fad em ambiente marinho / CAA IV, MPa (Tabela 23.2).
DELTA_FSD_FAD_MARINHO = 110.0

#: Coeficiente alfa_E do agregado graúdo (item 8.2.8).
ALFA_E_AGREGADO = {"basalto": 1.2, "diabasio": 1.2, "granito": 1.0,
                   "gnaisse": 1.0, "calcario": 0.9, "arenito": 0.7}


def delta_fsd_fad(phi_mm: float, categoria: str = "CA-50",
                  d_sobre_phi: float | None = None,
                  marinho: bool = False) -> float:
    """Limite de variação de tensão por fadiga, MPa (Tabela 23.2).

    ``d_sobre_phi`` é a relação entre o pino de dobramento e a bitola: abaixo
    de 25 a resistência cai pelo fator ``xi = 0,35 + 0,026 D/phi`` da nota (d)
    da tabela -- é o caso dos estribos e das barras dobradas. Em ambiente
    marinho (CAA IV) o limite é 110 MPa para qualquer bitola.
    """
    if marinho:
        return DELTA_FSD_FAD_MARINHO
    chaves = sorted(DELTA_FSD_FAD)
    if phi_mm <= chaves[0]:
        base = DELTA_FSD_FAD[chaves[0]]
    elif phi_mm >= chaves[-1]:
        base = DELTA_FSD_FAD[chaves[-1]]
    else:
        base = DELTA_FSD_FAD[chaves[-1]]
        for a, b in zip(chaves, chaves[1:]):
            if a <= phi_mm <= b:
                ya, yb = DELTA_FSD_FAD[a], DELTA_FSD_FAD[b]
                base = ya + (yb - ya) * (phi_mm - a) / (b - a)
                break
    if categoria == "CA-60":
        base *= 0.9        # sem tabela própria: penaliza o aço mais duro
    if d_sobre_phi is not None and d_sobre_phi < 25.0:
        xi = min(0.35 + 0.026 * d_sobre_phi, 1.0)
        base *= xi
    return base


def area_barra(phi_mm: float) -> float:
    """Área da seção transversal de uma barra, em cm²."""
    return math.pi * (phi_mm / 10.0) ** 2 / 4.0


def massa_linear(phi_mm: float) -> float:
    """Massa linear nominal da barra, em kg/m."""
    if phi_mm in MASSA_LINEAR:
        return MASSA_LINEAR[phi_mm]
    return 0.785 * area_barra(phi_mm) * 10.0  # 7850 kg/m³


def interpola_rho_min(fck: float) -> float:
    """Taxa mínima de armadura de flexão (%), interpolando a Tabela 17.3."""
    chaves = sorted(RHO_MIN_FLEXAO)
    if fck <= chaves[0]:
        return RHO_MIN_FLEXAO[chaves[0]]
    if fck >= chaves[-1]:
        return RHO_MIN_FLEXAO[chaves[-1]]
    for a, b in zip(chaves, chaves[1:]):
        if a <= fck <= b:
            ya, yb = RHO_MIN_FLEXAO[a], RHO_MIN_FLEXAO[b]
            return ya + (yb - ya) * (fck - a) / (b - a)
    return RHO_MIN_FLEXAO[chaves[-1]]


# ---------------------------------------------------------------------------
# Concreto
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Concreto:
    """Concreto estrutural dos grupos I e II de resistência (NBR 6118, 8.2)."""

    fck: float = 25.0                 # MPa
    gamma_c: float = 1.4
    agregado: str = "granito"
    peso_especifico: float = 25.0     # kN/m³

    # -- resistências -------------------------------------------------------
    @property
    def fcd(self) -> float:
        """Resistência de cálculo à compressão, MPa."""
        return self.fck / self.gamma_c

    @property
    def fctm(self) -> float:
        """Resistência média à tração, MPa (8.2.5).

        Acima de C50 a expressão da norma é ``2,12 ln[1 + 0,1 (fck + 8)]`` --
        e não a forma ``2,12 ln(1 + 0,11 fck)``, que circula em bibliografia
        e estava aqui.
        """
        if self.fck <= 50.0:
            return 0.3 * self.fck ** (2.0 / 3.0)
        return 2.12 * math.log(1.0 + 0.1 * (self.fck + 8.0))

    @property
    def fctk_inf(self) -> float:
        return 0.7 * self.fctm

    @property
    def fctk_sup(self) -> float:
        return 1.3 * self.fctm

    @property
    def fctd(self) -> float:
        """fctk,inf / gamma_c, em MPa."""
        return self.fctk_inf / self.gamma_c

    # -- rigidez ------------------------------------------------------------
    @property
    def alfa_E(self) -> float:
        return ALFA_E_AGREGADO.get(self.agregado.lower(), 1.0)

    @property
    def Eci(self) -> float:
        """Módulo de elasticidade inicial, MPa (8.2.8)."""
        if self.fck <= 50.0:
            return self.alfa_E * 5600.0 * math.sqrt(self.fck)
        return 21.5e3 * self.alfa_E * (self.fck / 10.0 + 1.25) ** (1.0 / 3.0)

    @property
    def alfa_i(self) -> float:
        return min(0.8 + 0.2 * self.fck / 80.0, 1.0)

    @property
    def Ecs(self) -> float:
        """Módulo de elasticidade secante, MPa (8.2.8)."""
        return self.alfa_i * self.Eci

    # -- diagrama retangular simplificado (17.2.2) --------------------------
    @property
    def lambda_(self) -> float:
        """Relação y/x do diagrama retangular equivalente."""
        if self.fck <= 50.0:
            return 0.8
        return 0.8 - (self.fck - 50.0) / 400.0

    @property
    def alfa_c(self) -> float:
        """Coeficiente de redução da tensão do bloco retangular."""
        if self.fck <= 50.0:
            return 0.85
        return 0.85 * (1.0 - (self.fck - 50.0) / 200.0)

    @property
    def eta_c(self) -> float:
        """Fator de fragilidade dos concretos de alta resistência (17.2.2)."""
        if self.fck <= 40.0:
            return 1.0
        return (40.0 / self.fck) ** (1.0 / 3.0)

    @property
    def sigma_cd(self) -> float:
        """Tensão do bloco retangular, kN/cm²: alfa_c . eta_c . fcd."""
        return self.alfa_c * self.eta_c * self.fcd / 10.0

    # -- deformações --------------------------------------------------------
    @property
    def eps_cu(self) -> float:
        """Deformação última do concreto (8.2.10.1)."""
        if self.fck <= 50.0:
            return 3.5e-3
        return (2.6 + 35.0 * ((90.0 - self.fck) / 100.0) ** 4) / 1000.0

    @property
    def eps_c2(self) -> float:
        """Deformação no início do patamar plástico (8.2.10.1)."""
        if self.fck <= 50.0:
            return 2.0e-3
        return (2.0 + 0.085 * (self.fck - 50.0) ** 0.53) / 1000.0

    # -- cisalhamento -------------------------------------------------------
    @property
    def alfa_v2(self) -> float:
        """Coeficiente de efetividade da biela (17.4.2.2)."""
        return 1.0 - self.fck / 250.0

    @property
    def sigma_biela(self) -> float:
        """alfa_v2 . fcd, em kN/cm²."""
        return self.alfa_v2 * self.fcd / 10.0

    @property
    def fctd_kNcm2(self) -> float:
        """fctd em kN/cm² (usado em Vc e nas ancoragens)."""
        return self.fctd / 10.0

    @property
    def classe(self) -> str:
        return f"C{self.fck:g}"

    def resumo(self) -> dict:
        """Propriedades derivadas, para a memória de cálculo."""
        return {
            "fck (MPa)": self.fck,
            "gamma_c": self.gamma_c,
            "fcd (MPa)": self.fcd,
            "fctm (MPa)": self.fctm,
            "fctk,inf (MPa)": self.fctk_inf,
            "fctd (MPa)": self.fctd,
            "Eci (MPa)": self.Eci,
            "Ecs (MPa)": self.Ecs,
            "lambda": self.lambda_,
            "alfa_c": self.alfa_c,
            "eta_c": self.eta_c,
            "alfa_c.eta_c.fcd (kN/cm2)": self.sigma_cd,
            "eps_cu": self.eps_cu,
            "alfa_v2": self.alfa_v2,
        }


# ---------------------------------------------------------------------------
# Aço
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Aco:
    """Aço para concreto armado (NBR 7480:2024)."""

    categoria: str = "CA-50"
    gamma_s: float = 1.15
    Es: float = 210_000.0             # MPa

    @property
    def fyk(self) -> float:
        """Resistência característica de escoamento, MPa."""
        return {"CA-25": 250.0, "CA-50": 500.0, "CA-60": 600.0}[self.categoria]

    @property
    def fyd(self) -> float:
        return self.fyk / self.gamma_s

    @property
    def fyd_kNcm2(self) -> float:
        return self.fyd / 10.0

    @property
    def eps_yd(self) -> float:
        return self.fyd / self.Es

    @property
    def eta_1(self) -> float:
        """Coeficiente de conformação superficial (9.3.2.1).

        2,25 para barras nervuradas (CA-50), 1,4 para entalhadas (CA-60)
        e 1,0 para barras lisas (CA-25).
        """
        return {"CA-25": 1.0, "CA-50": 2.25, "CA-60": 1.4}[self.categoria]

    def diametro_dobramento(self, phi_mm: float) -> float:
        """Diâmetro do pino de dobramento do gancho, cm (Tabela 9.1)."""
        faixa = "menor" if phi_mm < 20.0 else "maior"
        d = PINO_DOBRAMENTO[self.categoria][faixa]
        if d is None:                     # CA-60 não é previsto a partir de 20
            d = PINO_DOBRAMENTO[self.categoria]["menor"]
        return d * phi_mm / 10.0

    def raio_dobramento_eixo(self, phi_mm: float) -> float:
        """Raio de dobramento medido no **eixo** da barra, cm.

        A Tabela 9.1 dá o diâmetro do pino, logo o raio interno; o eixo da
        barra corre meio diâmetro adiante dele. É este o raio com que a dobra
        se desenha, porque o desenho traça o eixo da barra.
        """
        return self.raio_dobramento(phi_mm) + phi_mm / 20.0

    def ponta_reta_gancho(self, phi_mm: float) -> float:
        """Ponta reta mínima do gancho a 90°, cm (9.4.2.3-c: 8 Ø)."""
        return 8.0 * phi_mm / 10.0

    def altura_gancho_90(self, phi_mm: float) -> float:
        """Altura mínima do gancho a 90°, cm, do eixo da barra até a ponta.

        É o raio de dobramento no eixo mais a ponta reta de 8 Ø. O programa
        usava só os 8 Ø, tratando-os como se fossem a perna toda -- mas o item
        9.4.2.3-c fala da **ponta reta**, que começa depois da dobra. Medida na
        face externa (``+ Ø/2``), esta expressão reproduz exatamente a tabela de
        alturas de gancho de Araújo: 7,2 cm para Ø6,3, 11,5 para Ø10, 18,4 para
        Ø16 e 26,0 para Ø20.
        """
        return self.raio_dobramento_eixo(phi_mm) + self.ponta_reta_gancho(
            phi_mm)

    def diametro_dobramento_estribo(self, phi_mm: float) -> float:
        """Diâmetro do pino de dobramento do estribo, cm (Tabela 9.2)."""
        menor, medio, maior = PINO_DOBRAMENTO_ESTRIBO[self.categoria]
        if phi_mm <= 10.0:
            fator = menor
        elif phi_mm < 20.0:
            fator = medio
        else:
            fator = maior
        return fator * phi_mm / 10.0

    def raio_dobramento(self, phi_mm: float) -> float:
        """Raio de curvatura do gancho, cm -- metade do pino (Tabela 9.1)."""
        return self.diametro_dobramento(phi_mm) / 2.0

    def sigma_s(self, eps: float) -> float:
        """Tensão no aço, MPa, pelo diagrama elastoplástico perfeito."""
        if abs(eps) >= self.eps_yd:
            return math.copysign(self.fyd, eps)
        return self.Es * eps

    def resumo(self) -> dict:
        return {
            "categoria": self.categoria,
            "fyk (MPa)": self.fyk,
            "gamma_s": self.gamma_s,
            "fyd (MPa)": self.fyd,
            "Es (MPa)": self.Es,
            "eps_yd": self.eps_yd,
            "eta_1": self.eta_1,
        }


# ---------------------------------------------------------------------------
# Ambiente
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ambiente:
    """Classe de agressividade ambiental e o cobrimento dela decorrente."""

    caa: str = "II"
    cobrimento: float | None = None   # cm; None usa o nominal da Tabela 7.2
    controle_rigoroso: bool = False   # 7.4.7.6: permite reduzir 5 mm

    @property
    def cobrimento_nominal(self) -> float:
        if self.cobrimento is not None:
            return self.cobrimento
        c = COBRIMENTO_NOMINAL[self.caa]
        return c - 0.5 if self.controle_rigoroso else c

    @property
    def wk_limite(self) -> float:
        return WK_LIMITE[self.caa]

    @property
    def descricao(self) -> str:
        return DESCRICAO_CAA[self.caa]
