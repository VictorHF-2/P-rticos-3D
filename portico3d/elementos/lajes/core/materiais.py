# -*- coding: utf-8 -*-
"""
materiais.py
Propriedades de concreto e aço segundo a ABNT NBR 6118 e tabelas auxiliares
das lajes maciças: bitolas, cobrimentos, espessuras mínimas, pesos específicos
e cargas variáveis usuais.

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

#: Bitolas comerciais usadas em laje, diâmetro nominal em mm. A NBR 7480:2024
#: mantém a Ø4,2 e a Ø5,0 na série de fios; a apostila recomenda Ø4,2 como
#: mínimo da armadura positiva e Ø5,0 como mínimo da negativa.
BITOLAS = (4.2, 5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0)

#: Massa linear nominal, kg/m (NBR 7480:2024, Tabela 4; fios pela área).
MASSA_LINEAR = {
    4.2: 0.109, 5.0: 0.154, 6.3: 0.245, 8.0: 0.395, 10.0: 0.617,
    12.5: 0.963, 16.0: 1.578, 20.0: 2.466,
}

#: Espaçamentos possíveis entre barras, cm. A armadura de laje é locada com o
#: espaçamento em centímetros inteiros -- é assim que ela é marcada na obra, e
#: é assim que a apostila detalha (Ø5 c/14, Ø6,3 c/15).
ESPACAMENTOS = tuple(float(s) for s in range(7, 34))

#: Bitolas que a NBR 7480:2024 classifica como **fio**, e não como barra: a
#: fabricação em CA-50 começa na Ø6,3. Ø4,2 e Ø5,0 existem e são de uso
#: corrente em laje -- em CA-60 ou em tela soldada --, mas quem especifica
#: CA-50 nessas bitolas costuma não achar no mercado.
FIOS = (4.2, 5.0)

#: Taxa mínima de armadura de flexão, % da seção de concreto, em função do fck
#: (NBR 6118, Tabela 17.3, seção retangular com gamma_c = 1,4).
RHO_MIN_FLEXAO = {
    20: 0.150, 25: 0.150, 30: 0.150, 35: 0.164, 40: 0.179, 45: 0.194,
    50: 0.208, 55: 0.211, 60: 0.219, 65: 0.226, 70: 0.233, 75: 0.239,
    80: 0.245, 85: 0.251, 90: 0.256,
}

#: Cobrimento nominal para lajes, cm, por classe de agressividade
#: (NBR 6118, Tabela 7.2, coluna "laje").
COBRIMENTO_NOMINAL = {"I": 2.0, "II": 2.5, "III": 3.5, "IV": 4.5}

#: Cobrimento admitido na **face superior** de laje que recebe contrapiso,
#: revestimento seco ou piso de elevado desempenho (7.4.7.5): 15 mm, nunca
#: menor que a bitola da barra.
COBRIMENTO_FACE_REVESTIDA = 1.5

#: Abertura característica limite de fissuras, mm (Tabela 13.4, concreto
#: armado). A laje maciça de edifício corrente raramente é governada por ela,
#: mas o limite entra na memória.
WK_LIMITE = {"I": 0.4, "II": 0.3, "III": 0.3, "IV": 0.2}

#: Descrição das classes de agressividade ambiental (Tabela 6.1).
DESCRICAO_CAA = {
    "I": "Fraca - rural / submersa",
    "II": "Moderada - urbana",
    "III": "Forte - marinha / industrial",
    "IV": "Muito forte - respingos de maré / quimicamente agressiva",
}

#: Coeficiente alfa_E do agregado graúdo (item 8.2.8).
ALFA_E_AGREGADO = {"basalto": 1.2, "diabasio": 1.2, "granito": 1.0,
                   "gnaisse": 1.0, "calcario": 0.9, "arenito": 0.7}

#: Espessura mínima de laje maciça, cm (item 13.2.4.1).
ESPESSURA_MINIMA = {
    "cobertura": 7.0,
    "piso": 8.0,
    "balanco": 10.0,
    "veiculo <= 30 kN": 10.0,
    "veiculo > 30 kN": 12.0,
}

#: Pesos específicos usuais, kN/m³ (NBR 6120).
PESO_ESPECIFICO = {
    "concreto armado": 25.0,
    "concreto simples": 24.0,
    "enchimento": 14.0,
    "alvenaria de tijolo furado": 13.0,
    "alvenaria de tijolo macico": 18.0,
}

#: Cargas permanentes superficiais usuais, kN/m² (NBR 6120 / apostila §1.5).
REVESTIMENTOS = {
    "reboco (1 cm)": 0.20,
    "tacos ou tabuões de madeira": 0.70,
    "material cerâmico": 0.85,
    "forro falso": 0.50,
}

#: Cargas variáveis usuais em edifício residencial, kN/m² (§1.5).
CARGAS_VARIAVEIS = {
    "sala, dormitório, cozinha, banheiro": 1.5,
    "despensa, lavanderia, área de serviço": 2.0,
    "corredor e escada - residencial": 2.5,
    "corredor e escada - não residencial": 3.0,
}


def area_barra(phi_mm: float) -> float:
    """Área da seção transversal de uma barra, em cm²."""
    return math.pi * (phi_mm / 10.0) ** 2 / 4.0


def massa_linear(phi_mm: float) -> float:
    """Massa linear nominal da barra, em kg/m."""
    if phi_mm in MASSA_LINEAR:
        return MASSA_LINEAR[phi_mm]
    return 7.85 * area_barra(phi_mm) / 10.0     # 7850 kg/m³


def area_por_metro(phi_mm: float, espacamento_cm: float) -> float:
    """Área de armadura por metro de largura, cm²/m."""
    return area_barra(phi_mm) * 100.0 / espacamento_cm


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


def gamma_n(h_cm: float) -> float:
    """Coeficiente adicional das lajes em balanço (item 13.2.4.1).

    ``gamma_n = 1,95 - 0,05 h`` para h <= 19 cm, e 1,00 acima disso. Majora os
    esforços solicitantes finais de cálculo -- a laje fina em balanço perde
    pouco de altura útil por um erro de posicionamento da armadura negativa,
    e é esse risco que o coeficiente cobre.
    """
    if h_cm > 19.0:
        return 1.0
    return 1.95 - 0.05 * h_cm


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

        Acima de C50 a expressão da norma é ``2,12 ln[1 + 0,1 (fck + 8)]``.
        A apostila escreve ``2,12 ln(1 + 0,11 fck)``, forma que circula na
        bibliografia; aqui vale o texto da norma.
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

    @property
    def fctd_kNcm2(self) -> float:
        return self.fctd / 10.0

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
    def sigma_cd(self) -> float:
        """Tensão do bloco retangular, kN/cm²: alfa_c . fcd.

        A laje maciça de edifício fica sempre no grupo I ou no início do
        grupo II e não recebe o eta_c das vigas de alta resistência, porque a
        apostila -- e a planilha do usuário -- calculam com alfa_c . fcd.
        """
        return self.alfa_c * self.fcd / 10.0

    # -- deformações --------------------------------------------------------
    @property
    def eps_cu(self) -> float:
        """Deformação última do concreto (8.2.10.1)."""
        if self.fck <= 50.0:
            return 3.5e-3
        return (2.6 + 35.0 * ((90.0 - self.fck) / 100.0) ** 4) / 1000.0

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
    def x_sobre_d_limite(self) -> float:
        """Limite de x/d do regime rígido-plástico (item 14.6.4.3).

        A apostila §1.7 repete o limite da norma para quem determina as
        solicitações por análise plástica: 0,25 até C50 e 0,15 acima. É bem
        mais severo que o limite de ductilidade da flexão em regime elástico,
        e é ele que vale aqui porque os momentos das lajes saem das linhas de
        ruptura.
        """
        return 0.25 if self.fck <= 50.0 else 0.15

    def x_sobre_d_limite_redistribuido(self, delta: float = 1.0) -> float:
        """Limite de x/d de quem determina os momentos por **análise
        elástica** com redistribuição ``delta`` (14.6.4.3): ``x/d <=
        (delta - 0,44)/1,25`` até C50 e ``(delta - 0,56)/1,25`` acima, e no
        máximo 0,45 e 0,35 -- o valor de quem não redistribui (``delta =
        1``). É o que vale com os momentos do ``mef`` da R10; com
        ``delta = 0,75`` recai nos 0,25 do regime rígido-plástico."""
        if delta >= 1.0:
            return 0.45 if self.fck <= 50.0 else 0.35
        if self.fck <= 50.0:
            return (delta - 0.44) / 1.25
        return (delta - 0.56) / 1.25

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
            "fctk,sup (MPa)": self.fctk_sup,
            "fctd (MPa)": self.fctd,
            "alfa_E": self.alfa_E,
            "Eci (MPa)": self.Eci,
            "alfa_i": self.alfa_i,
            "Ecs (MPa)": self.Ecs,
            "lambda": self.lambda_,
            "alfa_c": self.alfa_c,
            "alfa_c.fcd (kN/cm2)": self.sigma_cd,
            "eps_cu": self.eps_cu,
            "x/d limite (14.6.4.3)": self.x_sobre_d_limite,
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
    """Classe de agressividade ambiental e o cobrimento dela decorrente.

    A laje tem **dois** cobrimentos, e eles não são iguais: o inferior é o
    nominal da Tabela 7.2, e o superior pode cair a 15 mm quando a face recebe
    contrapiso ou revestimento de elevado desempenho (7.4.7.5). É isso que faz
    ``d`` da armadura negativa ser maior que ``d`` da positiva na mesma laje.
    """

    caa: str = "II"
    cobrimento: float | None = None        # cm; None usa a Tabela 7.2
    face_superior_revestida: bool = True   # 7.4.7.5
    controle_rigoroso: bool = False        # 7.4.7.6: permite reduzir 5 mm

    @property
    def cobrimento_nominal(self) -> float:
        """Cobrimento da face inferior (armadura positiva), cm."""
        if self.cobrimento is not None:
            return self.cobrimento
        c = COBRIMENTO_NOMINAL[self.caa]
        return c - 0.5 if self.controle_rigoroso else c

    def cobrimento_superior(self, phi_mm: float = 0.0) -> float:
        """Cobrimento da face superior (armadura negativa), cm.

        Nunca menor que a bitola da barra, como manda a ressalva do item
        7.4.7.5, nem maior que o cobrimento da face inferior.
        """
        if not self.face_superior_revestida:
            return self.cobrimento_nominal
        return max(COBRIMENTO_FACE_REVESTIDA, phi_mm / 10.0)

    @property
    def wk_limite(self) -> float:
        return WK_LIMITE[self.caa]

    @property
    def descricao(self) -> str:
        return DESCRICAO_CAA[self.caa]
