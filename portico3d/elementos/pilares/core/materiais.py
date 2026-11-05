# -*- coding: utf-8 -*-
"""
materiais.py
Propriedades de concreto e aço segundo a ABNT NBR 6118 e tabelas auxiliares
(bitolas comerciais, cobrimentos, classes de agressividade ambiental).

Unidades adotadas neste módulo:
    resistências e módulos ..... MPa (as propriedades em kN/cm² são explícitas)
    comprimentos ............... cm
    deformações ................ por mil (o sufixo ``_mil`` marca as que são)
Funções puras, sem dependência de interface gráfica.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from .formato import num

# ---------------------------------------------------------------------------
# Tabelas auxiliares
# ---------------------------------------------------------------------------

#: Bitolas comerciais de barras (NBR 7480:2024), diâmetro nominal em mm.
BITOLAS_BARRAS = (5.0, 6.3, 8.0, 10.0, 12.5, 16.0, 20.0, 25.0, 32.0, 40.0)

#: Bitolas admissíveis na armadura longitudinal de pilar. O item 18.4.2.1 fixa
#: o piso de 10 mm; abaixo disso a barra não é opção, e não faz sentido
#: oferecê-la na interface.
BITOLAS_LONGITUDINAIS_PILAR = (10.0, 12.5, 16.0, 20.0, 25.0, 32.0, 40.0)

#: Bitolas usuais para estribos, em mm.
BITOLAS_ESTRIBOS = (5.0, 6.3, 8.0, 10.0, 12.5)

#: Massa linear nominal das barras, kg/m (NBR 7480:2024, Tabela 4).
MASSA_LINEAR = {
    5.0: 0.154, 6.3: 0.245, 8.0: 0.395, 10.0: 0.617, 12.5: 0.963,
    16.0: 1.578, 20.0: 2.466, 25.0: 3.853, 32.0: 6.313, 40.0: 9.865,
}

#: Cobrimento nominal para pilares, cm, por classe de agressividade
#: (Tabela 7.2, coluna "pilar / viga" do concreto armado).
COBRIMENTO_NOMINAL = {"I": 2.5, "II": 3.0, "III": 4.0, "IV": 5.0}

#: Descrição das classes de agressividade ambiental (Tabela 6.1).
DESCRICAO_CAA = {
    "I": "Fraca - rural / submersa",
    "II": "Moderada - urbana",
    "III": "Forte - marinha / industrial",
    "IV": "Muito forte - respingos de maré / quimicamente agressiva",
}

#: Classe mínima de concreto armado por classe de agressividade, MPa
#: (Tabela 7.1 -- correspondência entre agressividade e qualidade do
#: concreto). É um piso por durabilidade, distinto do piso estrutural
#: absoluto de C20 do item 7.4.2: em CAA III ou IV, C20/C25 continuam
#: estruturalmente calculáveis, mas a norma não os admite ali.
FCK_MINIMO_CAA = {"I": 20.0, "II": 25.0, "III": 30.0, "IV": 40.0}

#: Classe máxima de concreto que a NBR 6118 cobre (item 8.2.1: C20 a C90).
FCK_MAXIMO = 90.0

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

#: Coeficientes de ponderação das resistências no ELU (Tabela 12.1),
#: por tipo de combinação: ``(gamma_c, gamma_s)``.
COEFICIENTES_PONDERACAO = {
    "normais": (1.4, 1.15),
    "especiais": (1.2, 1.15),
    "excepcionais": (1.2, 1.0),
}

DESCRICAO_COMBINACAO = {
    "normais": "Normais",
    "especiais": "Especiais ou de construção",
    "excepcionais": "Excepcionais",
}

#: Umidades médias ambientes tabeladas para a fluência (Tabela 8.1), %.
UMIDADES_FLUENCIA = (40.0, 55.0, 75.0, 90.0)

#: Espessuras fictícias 2Ac/u tabeladas para a fluência (Tabela 8.1), cm.
ESPESSURAS_FLUENCIA = (20.0, 60.0)

#: Idades de carregamento tabeladas para a fluência (Tabela 8.1), dias.
IDADES_FLUENCIA = (5.0, 30.0, 60.0)

#: Coeficiente de fluência phi(t_inf, t0) da Tabela 8.1 da NBR 6118:2026
#: (Tabela 8.2 na edição de 2014). Indexado por ``[classe][t0][umidade]``,
#: e cada entrada é o par ``(2Ac/u = 20 cm, 2Ac/u = 60 cm)``.
#:
#: A norma admite obter os valores intermediários por **interpolação
#: linear**, e é o que :func:`coeficiente_fluencia` faz nas três entradas.
FLUENCIA = {
    "C20-C45": {
        5.0:  {40.0: (4.6, 3.8), 55.0: (3.9, 3.3),
               75.0: (2.8, 2.4), 90.0: (2.0, 1.9)},
        30.0: {40.0: (3.4, 3.0), 55.0: (2.9, 2.6),
               75.0: (2.2, 2.0), 90.0: (1.6, 1.5)},
        60.0: {40.0: (2.9, 2.7), 55.0: (2.5, 2.3),
               75.0: (1.9, 1.8), 90.0: (1.4, 1.4)},
    },
    "C50-C90": {
        5.0:  {40.0: (2.7, 2.4), 55.0: (2.4, 2.1),
               75.0: (1.9, 1.8), 90.0: (1.6, 1.5)},
        30.0: {40.0: (2.0, 1.8), 55.0: (1.7, 1.6),
               75.0: (1.4, 1.3), 90.0: (1.1, 1.1)},
        60.0: {40.0: (1.7, 1.6), 55.0: (1.5, 1.4),
               75.0: (1.2, 1.2), 90.0: (1.0, 1.0)},
    },
}

#: Coeficiente alfa_E do agregado graúdo (item 8.2.8).
ALFA_E_AGREGADO = {"basalto": 1.2, "diabasio": 1.2, "granito": 1.0,
                   "gnaisse": 1.0, "calcario": 0.9, "arenito": 0.7}

#: Espaçamento livre mínimo entre barras longitudinais de pilar, cm
#: (item 18.4.2.2): 2 cm, a bitola da barra e 1,2 vezes o agregado.
ESPACAMENTO_LIVRE_MINIMO = 2.0

#: Espaçamento máximo entre eixos de barras longitudinais, cm (18.4.2.2):
#: duas vezes a menor dimensão, sem exceder 40 cm.
ESPACAMENTO_EIXOS_MAXIMO = 40.0

#: Taxa geométrica máxima de armadura (17.3.5.3.2), critério de projeto:
#: 4 % na seção corrente e 8 % na região de emenda, onde as barras do lance e
#: as de espera se sobrepõem. Com todas as barras emendadas no mesmo nível,
#: a taxa da emenda é o dobro da corrente.
RHO_MAXIMO_CORRENTE = 0.04
RHO_MAXIMO_EMENDA = 0.08
#: O limite que a busca de arranjo e as verificações usam como teto da seção
#: corrente.
RHO_MAXIMO = RHO_MAXIMO_CORRENTE

#: Piso da taxa geométrica mínima de armadura (17.3.5.3.1).
RHO_MINIMO_PISO = 0.004

#: Dimensão mínima da seção transversal de pilar, cm (13.2.3).
DIMENSAO_MINIMA = 19.0

#: Dimensão abaixo da qual nem o coeficiente adicional salva (13.2.3).
DIMENSAO_MINIMA_ABSOLUTA = 14.0

#: Área mínima da seção transversal de pilar, cm² (13.2.3).
AREA_MINIMA = 360.0

#: Esbeltez acima da qual a norma não admite o pilar (15.8.1).
ESBELTEZ_MAXIMA = 200.0

#: Esbeltez acima da qual o método exato passa a ser obrigatório (15.8.1).
ESBELTEZ_METODO_EXATO = 140.0

#: Esbeltez acima da qual a fluência é obrigatória (15.8.4).
ESBELTEZ_FLUENCIA = 90.0


def area_barra(phi_mm: float) -> float:
    """Área da seção transversal de uma barra, em cm²."""
    return math.pi * (phi_mm / 10.0) ** 2 / 4.0


def massa_linear(phi_mm: float) -> float:
    """Massa linear da barra, kg/m; interpola o que não está na tabela."""
    if phi_mm in MASSA_LINEAR:
        return MASSA_LINEAR[phi_mm]
    return area_barra(phi_mm) * 7.85 / 10.0


def bitola_comercial(phi_mm: float,
                     opcoes: tuple[float, ...] = BITOLAS_BARRAS) -> float:
    """Menor bitola comercial maior ou igual a ``phi_mm``."""
    for b in opcoes:
        if b >= phi_mm - 1e-9:
            return b
    return opcoes[-1]


def diametro_equivalente(n: int, phi_mm: float) -> float:
    """Diâmetro de um feixe de ``n`` barras de bitola ``phi_mm`` (18.4.2.2).

    O feixe se comporta como uma barra única de área equivalente, e é esse
    diâmetro -- ``phi . sqrt(n)`` -- que entra no espaçamento livre e no
    comprimento de ancoragem.
    """
    return phi_mm * math.sqrt(max(n, 1))


# ---------------------------------------------------------------------------
# Concreto
# ---------------------------------------------------------------------------

@dataclass
class Concreto:
    """Concreto estrutural definido pela classe de resistência.

    ``fck`` em MPa. As classes acima de C50 usam o diagrama parábola-retângulo
    com os parâmetros do item 8.2.10.1, o que altera ``eps_c2``, ``eps_cu``,
    ``n``, ``alfa_c`` e ``lambda_bloco``; acima de C40 entra ``eta_c`` -- e é aí que o comportamento do pilar muda
    de fato, porque a compressão é o esforço que governa.
    """

    fck: float = 25.0
    gamma_c: float = 1.4
    agregado: str = "granito"
    peso_especifico: float = 25.0        # kN/m³

    def __post_init__(self) -> None:
        if self.fck <= 0:
            raise ValueError("fck precisa ser positivo.")

    # -- resistências -------------------------------------------------------
    @property
    def fcd(self) -> float:
        """Resistência de cálculo à compressão, MPa."""
        return self.fck / self.gamma_c

    @property
    def fcd_kNcm2(self) -> float:
        """Resistência de cálculo à compressão, kN/cm²."""
        return self.fcd / 10.0

    @property
    def fctm(self) -> float:
        """Resistência média à tração, MPa (item 8.2.5)."""
        if self.fck <= 50.0:
            return 0.3 * self.fck ** (2.0 / 3.0)
        return 2.12 * math.log(1.0 + 0.11 * self.fck)

    @property
    def fctk_inf(self) -> float:
        return 0.7 * self.fctm

    @property
    def fctd(self) -> float:
        """Resistência de cálculo à tração inferior, MPa."""
        return self.fctk_inf / self.gamma_c

    # -- módulos ------------------------------------------------------------
    @property
    def alfa_E(self) -> float:
        return ALFA_E_AGREGADO.get(self.agregado, 1.0)

    @property
    def Eci(self) -> float:
        """Módulo de elasticidade inicial, MPa (item 8.2.8)."""
        if self.fck <= 50.0:
            return self.alfa_E * 5600.0 * math.sqrt(self.fck)
        return 21500.0 * self.alfa_E * (self.fck / 10.0 + 1.25) ** (1.0 / 3.0)

    @property
    def Ecs(self) -> float:
        """Módulo de elasticidade secante, MPa (item 8.2.8)."""
        alfa_i = min(0.8 + 0.2 * self.fck / 80.0, 1.0)
        return alfa_i * self.Eci

    # -- diagrama parábola-retângulo ---------------------------------------
    @property
    def eps_c2_mil(self) -> float:
        """Deformação no início do patamar plástico, por mil (8.2.10.1)."""
        if self.fck <= 50.0:
            return 2.0
        return 2.0 + 0.085 * (self.fck - 50.0) ** 0.53

    @property
    def eps_cu_mil(self) -> float:
        """Deformação última na compressão, por mil (8.2.10.1)."""
        if self.fck <= 50.0:
            return 3.5
        return 2.6 + 35.0 * ((90.0 - self.fck) / 100.0) ** 4

    @property
    def expoente_n(self) -> float:
        """Expoente ``n`` da parábola do diagrama tensão-deformação."""
        if self.fck <= 50.0:
            return 2.0
        return 1.4 + 23.4 * ((90.0 - self.fck) / 100.0) ** 4

    @property
    def eta_c(self) -> float:
        """Fator que considera a fragilidade do concreto (8.2.10.1, Figura
        8.2): 1,0 até 40 MPa; ``(40/fck)^(1/3)`` acima. Novo na edição de
        2026 -- entra nos dois diagramas do ELU, o parábola-retângulo e o
        retângulo equivalente do 17.2.2-e.
        """
        if self.fck <= 40.0:
            return 1.0
        return (40.0 / self.fck) ** (1.0 / 3.0)

    @property
    def alfa_c(self) -> float:
        """``alfa_c`` do retângulo equivalente (item 17.2.2-e): 0,85 até 50
        MPa; ``0,85·[1 - (fck - 50)/200]`` acima. Só o bloco retangular o
        usa; o parábola-retângulo tem pico fixo em ``0,85·eta_c·fcd``.
        """
        if self.fck <= 50.0:
            return 0.85
        return 0.85 * (1.0 - (self.fck - 50.0) / 200.0)

    @property
    def fator_pico(self) -> float:
        """Pico do parábola-retângulo sobre ``fcd``: ``0,85·eta_c`` (Figura
        8.2 e item 17.2.2-e da edição de 2026). Até a R05 era ``alfa_c`` --
        o redutor do bloco retangular, emprestado ao diagrama curvo, e sem
        ``eta_c``.
        """
        return 0.85 * self.eta_c

    @property
    def fator_bloco(self) -> float:
        """Tensão do retângulo equivalente sobre ``fcd``: ``alfa_c·eta_c``
        (item 17.2.2-e), para largura que não diminui rumo à borda
        comprimida -- a única forma em que o roteiro fechado (retangular) o
        usa. A largura decrescente pediria ``0,9·alfa_c·eta_c``.
        """
        return self.alfa_c * self.eta_c

    @property
    def lambda_bloco(self) -> float:
        """Relação entre a altura do bloco retangular e ``x`` (17.2.2)."""
        if self.fck <= 50.0:
            return 0.8
        return 0.8 - (self.fck - 50.0) / 400.0

    def sigma_c(self, eps_mil: float) -> float:
        """Tensão do diagrama parábola-retângulo, kN/cm², para ``eps`` em ‰.

        Compressão positiva, pico ``0,85·eta_c·fcd`` (Figura 8.2). Serve o
        motor seccional por integração; o bloco retangular usa
        ``fator_bloco`` e ``lambda_bloco``.
        """
        if eps_mil <= 0.0:
            return 0.0
        fcd = self.fator_pico * self.fcd_kNcm2
        if eps_mil >= self.eps_c2_mil:
            return fcd
        r = 1.0 - eps_mil / self.eps_c2_mil
        return fcd * (1.0 - r ** self.expoente_n)

    def descricao(self) -> str:
        return f"C{num(self.fck)}"


# ---------------------------------------------------------------------------
# Aço
# ---------------------------------------------------------------------------

#: Categorias de aço para armadura passiva cobertas pela NBR 7480 (item 8.3).
CATEGORIAS_ACO = ("CA-25", "CA-50", "CA-60")


@dataclass
class Aco:
    """Aço para armadura passiva, com diagrama elastoplástico perfeito."""

    categoria: str = "CA-50"
    gamma_s: float = 1.15
    Es: float = 210000.0                 # MPa (item 8.3.5)

    def __post_init__(self) -> None:
        if self.categoria not in CATEGORIAS_ACO:
            raise ValueError(
                f"Categoria de aço inválida: {self.categoria!r}. A NBR 7480 "
                f"só cobre {', '.join(CATEGORIAS_ACO)}.")

    @property
    def fyk(self) -> float:
        """Resistência característica ao escoamento, MPa.

        O número da categoria está em kgf/mm² por herança histórica: CA-50 é
        aço de 500 MPa, não de 50. O fator 10 é essa conversão.
        """
        return 10.0 * float(self.categoria.split("-")[1])

    @property
    def fyd(self) -> float:
        return self.fyk / self.gamma_s

    @property
    def fyd_kNcm2(self) -> float:
        return self.fyd / 10.0

    @property
    def Es_kNcm2(self) -> float:
        return self.Es / 10.0

    @property
    def eps_yd_mil(self) -> float:
        """Deformação de escoamento de cálculo, por mil."""
        return self.fyd / self.Es * 1000.0

    def sigma_s(self, eps_mil: float) -> float:
        """Tensão no aço, kN/cm², para a deformação em ‰ (tração positiva)."""
        s = math.copysign(1.0, eps_mil)
        return s * min(abs(eps_mil) * self.Es_kNcm2 / 1000.0, self.fyd_kNcm2)

    def pino_dobramento(self, phi_mm: float) -> float | None:
        """Diâmetro do pino de dobramento, em cm (Tabela 9.1)."""
        faixa = "menor" if phi_mm < 20.0 else "maior"
        mult = PINO_DOBRAMENTO.get(self.categoria, {}).get(faixa)
        return None if mult is None else mult * phi_mm / 10.0

    def pino_dobramento_estribo(self, phi_mm: float) -> float:
        """Diâmetro do pino de dobramento do estribo, em cm (Tabela 9.2)."""
        tab = PINO_DOBRAMENTO_ESTRIBO.get(self.categoria,
                                          PINO_DOBRAMENTO_ESTRIBO["CA-50"])
        i = 0 if phi_mm <= 10.0 else (1 if phi_mm < 20.0 else 2)
        return tab[i] * phi_mm / 10.0

    def descricao(self) -> str:
        return self.categoria


# ---------------------------------------------------------------------------
# Ambiente
# ---------------------------------------------------------------------------

@dataclass
class Ambiente:
    """Classe de agressividade e cobrimento adotado."""

    caa: str = "II"
    cobrimento: float = 0.0              # cm; 0 = calcular pelo item 7.4.7
    dmax_agregado: float = 1.9           # cm
    controle_rigoroso: bool = False       # item 7.4.7.4: Delta c = 5 mm

    def __post_init__(self) -> None:
        if self.caa not in COBRIMENTO_NOMINAL:
            raise ValueError(f"Classe de agressividade inválida: {self.caa!r}")

    @property
    def cobrimento_tabelado(self) -> float:
        """Cobrimento nominal da Tabela 7.2, cm, já com a redução do 7.4.7.4.

        A Tabela 7.2 é dada para ``Delta c = 10 mm``. O item 7.4.7.4 admite
        ``Delta c = 5 mm`` -- e portanto reduzir o cobrimento nominal em 5 mm
        -- apenas em estruturas projetadas segundo a ABNT NBR 9062, com
        controle adequado de qualidade e limites rígidos de tolerância, e
        exige que a exigência de controle rigoroso conste dos desenhos.
        """
        c = COBRIMENTO_NOMINAL[self.caa]
        return c - 0.5 if self.controle_rigoroso else c

    #: Nome antigo, mantido porque a memória e a auditoria o citam.
    @property
    def cobrimento_nominal(self) -> float:
        return self.cobrimento_tabelado

    def cobrimento_minimo(self, phi_barra: float = 0.0,
                          phi_estribo: float = 0.0) -> float:
        """Cobrimento nominal mínimo, cm, fechando o item 7.4.7 inteiro.

        A Tabela 7.2 é o piso da agressividade, mas não é o único. O item
        7.4.7.5 acrescenta que o cobrimento nominal "de uma determinada
        barra" tem de ser maior ou igual ao diâmetro dela, e o 7.4.7.6 que o
        agregado graúdo não pode exceder em 20 % o cobrimento nominal --
        isto é, ``c >= dmax/1,2``.

        Sobre a leitura do 7.4.7.5: o cobrimento é medido na face externa do
        **estribo**, de modo que a barra longitudinal já tem, sobre si,
        ``c + phi_t``. Ainda assim o programa exige ``c >= phi_l``, que é a
        leitura conservadora e a que a bibliografia da disciplina aplica.
        Exigir só ``c >= phi_t`` deixaria passar uma Ø32 sob 2,5 cm de
        cobrimento, e o item não foi escrito para isso.
        """
        return max(self.cobrimento_tabelado, phi_barra / 10.0,
                   phi_estribo / 10.0, self.dmax_agregado / 1.2)

    def cobrimento_para(self, phi_barra: float = 0.0,
                        phi_estribo: float = 0.0) -> float:
        """Cobrimento a adotar, cm: o do usuário, ou o mínimo do item 7.4.7."""
        if self.cobrimento > 0:
            return self.cobrimento
        return self.cobrimento_minimo(phi_barra, phi_estribo)

    @property
    def cobrimento_adotado(self) -> float:
        """Cobrimento sem conhecer a bitola -- só a Tabela 7.2 e o agregado.

        Serve para a pré-visualização e para os relatórios que rodam antes de
        o arranjo existir. O valor que de fato entra no dimensionamento sai de
        :meth:`cobrimento_para`, que já conhece as bitolas.
        """
        return self.cobrimento_para()

    def governante(self, phi_barra: float = 0.0,
                   phi_estribo: float = 0.0) -> str:
        """Qual exigência do item 7.4.7 governou o cobrimento."""
        if self.cobrimento > 0:
            return "valor imposto pelo projetista"
        candidatos = [
            (self.cobrimento_tabelado, f"Tabela 7.2, CAA {self.caa}"),
            (phi_barra / 10.0, f"item 7.4.7.5: ø{num(phi_barra)} mm da barra"),
            (phi_estribo / 10.0,
             f"item 7.4.7.5: ø{num(phi_estribo)} mm do estribo"),
            (self.dmax_agregado / 1.2,
             f"item 7.4.7.6: dmáx/1,2 = {num(self.dmax_agregado / 1.2, 2)} cm"),
        ]
        return max(candidatos, key=lambda t: t[0])[1]

    def descricao(self) -> str:
        return f"CAA {self.caa} - {DESCRICAO_CAA[self.caa]}"


# ---------------------------------------------------------------------------
# Aderência e ancoragem
# ---------------------------------------------------------------------------

def eta_1(nervurada: bool = True, entalhada: bool = False) -> float:
    """Coeficiente de conformação superficial da barra (item 9.3.2.1)."""
    if nervurada:
        return 2.25
    return 1.4 if entalhada else 1.0


def f_bd(concreto: Concreto, phi_mm: float, boa_aderencia: bool = True,
         nervurada: bool = True) -> float:
    """Resistência de aderência de cálculo, kN/cm² (item 9.3.2.1).

    ``fbd = eta1 . eta2 . eta3 . fctd``, com ``eta2 = 1,0`` em boa situação de
    aderência e 0,7 em má, e ``eta3 = 1,0`` para bitolas até 32 mm.

    Em pilar a barra é vertical: inclinação maior que 45° com a horizontal,
    a alínea a) do item 9.3.1 -- boa aderência, qualquer que seja a altura de
    concretagem (a condição dos 60 cm é das barras horizontais). O
    parâmetro fica exposto para quem quiser declarar má aderência à parte.
    """
    eta2 = 1.0 if boa_aderencia else 0.7
    eta3 = 1.0 if phi_mm <= 32.0 else (132.0 - phi_mm) / 100.0
    return eta_1(nervurada) * eta2 * eta3 * concreto.fctd / 10.0


def lb_basico(concreto: Concreto, aco: Aco, phi_mm: float,
              boa_aderencia: bool = True) -> float:
    """Comprimento de ancoragem básico, cm (item 9.4.2.4).

    ``lb = phi/4 . fyd/fbd >= 25 phi``.
    """
    phi_cm = phi_mm / 10.0
    lb = phi_cm / 4.0 * aco.fyd_kNcm2 / f_bd(concreto, phi_mm, boa_aderencia)
    return max(lb, 25.0 * phi_cm)


def lb_necessario(lb: float, As_calc: float, As_efet: float, phi_mm: float,
                  alfa: float = 1.0) -> float:
    """Comprimento de ancoragem necessário, cm (item 9.4.2.5).

    ``lb,nec = alfa . lb . As,calc/As,ef >= lb,min``, com
    ``lb,min = max(0,3 lb; 10 phi; 10 cm)``.
    """
    phi_cm = phi_mm / 10.0
    lb_min = max(0.3 * lb, 10.0 * phi_cm, 10.0)
    if As_efet <= 0.0:
        return max(alfa * lb, lb_min)
    return max(alfa * lb * As_calc / As_efet, lb_min)


def comprimento_espera(lb: float, As_calc: float, As_efet: float,
                       phi_mm: float) -> float:
    """Comprimento de espera do pilar, cm (item 9.5.2.3).

    ``l0c = lb . As,calc/As,ef >= l0c,min``, com
    ``l0c,min = max(0,6 lb; 15 phi; 20 cm)``.

    É a mesma forma do ``lb,nec``, com pisos maiores: a emenda por traspasse
    de barra comprimida precisa de mais que a ancoragem simples, e é por isso
    que a função existe separada em vez de reaproveitar :func:`lb_necessario`.
    """
    phi_cm = phi_mm / 10.0
    minimo = max(0.6 * lb, 15.0 * phi_cm, 20.0)
    if As_efet <= 0.0:
        return max(lb, minimo)
    return max(lb * As_calc / As_efet, minimo)


#: Coeficiente alfa_0t da emenda de barras tracionadas (item 9.5.2.2.1,
#: Tabela 9.4) com mais de 50 % das barras emendadas na mesma seção -- o
#: caso do pilar, em que todas as barras param no mesmo nível.
ALFA_0T_PILAR = 2.0


def comprimento_traspasse_tracao(lb: float, lb_nec: float, phi_mm: float,
                                 alfa_0t: float = ALFA_0T_PILAR
                                 ) -> tuple[float, float]:
    """Traspasse de barras tracionadas, cm (item 9.5.2.2.1).

    ``l0t = alfa_0t . lb,nec >= l0t,min``, com
    ``l0t,min = max(0,3 alfa_0t lb; 15 phi; 20 cm)``. Devolve
    ``(l0t, l0t,min)``."""
    minimo = max(0.3 * alfa_0t * lb, 15.0 * phi_mm / 10.0, 20.0)
    return max(alfa_0t * lb_nec, minimo), minimo


# ---------------------------------------------------------------------------
# Coeficiente adicional gamma_n do item 13.2.3
# ---------------------------------------------------------------------------

def gamma_n(menor_dimensao: float) -> float:
    """Coeficiente adicional das seções entre 19 e 14 cm (Tabela 13.1).

    ``gamma_n = 1,95 - 0,05 b``, com ``b`` em cm. Abaixo de 14 cm a norma não
    admite a seção em hipótese alguma, e quem barra isso é a validação do
    modelo -- aqui a função apenas devolve o valor que a tabela extrapola,
    para que a mensagem de erro possa dizer quanto seria.
    """
    if menor_dimensao >= DIMENSAO_MINIMA:
        return 1.0
    return 1.95 - 0.05 * menor_dimensao


def gamma_n1(esbeltez: float) -> float:
    """Coeficiente adicional dos pilares com lambda > 140 (item 15.8.1).

    ``gamma_n1 = 1 + (lambda - 140)/140`` (escrito ``1 + 0,01 (lambda -
    140)/1,4``). Majora os **efeitos locais de 2ª ordem** -- a parcela
    ``Nd e2`` --, não o momento de 1ª ordem (texto da edição de 2026).
    """
    if esbeltez <= ESBELTEZ_METODO_EXATO:
        return 1.0
    return 1.0 + 0.01 * (esbeltez - ESBELTEZ_METODO_EXATO) / 1.4


def rho_minimo(nu: float, concreto: Concreto, aco: Aco) -> float:
    """Taxa geométrica mínima de armadura (item 17.3.5.3.1).

    ``rho,min = 0,15 . nu . fcd/fyd >= 0,4 %``, com ``nu = Nd/(Ac fcd)``.
    Devolve a taxa como fração (0,004 = 0,4 %).
    """
    return max(0.15 * nu * concreto.fcd / aco.fyd, RHO_MINIMO_PISO)


# ---------------------------------------------------------------------------
# Coeficientes de ponderação das resistências (Tabela 12.1)
# ---------------------------------------------------------------------------

def coeficientes_ponderacao(combinacao: str = "normais",
                            execucao_desfavoravel: bool = False,
                            ca25_sem_controle: bool = False
                            ) -> tuple[float, float]:
    """``(gamma_c, gamma_s)`` do ELU pela Tabela 12.1.

    Os dois multiplicadores de 1,1 são as ressalvas da própria tabela, e não
    invenção: ``gamma_c`` é multiplicado por 1,1 quando estão previstas
    condições desfavoráveis de execução -- más condições de transporte,
    adensamento manual, concretagem deficiente por concentração de armadura --
    e ``gamma_s`` por 1,1 quando se emprega CA-25 sem o controle de qualidade
    da ABNT NBR 7480, o que a norma só admite em obras de pequena importância.
    """
    if combinacao not in COEFICIENTES_PONDERACAO:
        raise ValueError(f"Combinação desconhecida: {combinacao!r}")
    gc, gs = COEFICIENTES_PONDERACAO[combinacao]
    if execucao_desfavoravel:
        gc *= 1.1
    if ca25_sem_controle:
        gs *= 1.1
    return gc, gs


# ---------------------------------------------------------------------------
# Coeficiente de fluência (Tabela 8.1)
# ---------------------------------------------------------------------------

def _interpolar(x: float, xs, ys) -> float:
    """Interpolação linear em ``xs`` crescente, truncada nas pontas.

    Truncar, e não extrapolar, é deliberado: fora da faixa tabelada a norma
    não diz nada, e prolongar a reta produziria número com aparência de
    tabelado sem nenhum respaldo.
    """
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for a, b, ya, yb in zip(xs, xs[1:], ys, ys[1:]):
        if a <= x <= b:
            return ya + (yb - ya) * (x - a) / (b - a)
    return ys[-1]


def espessura_ficticia(area: float, perimetro_exposto: float) -> float:
    """Espessura fictícia ``2 Ac/u``, cm (item 8.2.11).

    ``u`` é o perímetro da seção **em contato com a atmosfera**. Num pilar de
    edifício isso é o contorno externo inteiro; o vazio de uma seção circular
    vazada não conta, porque ele é fechado nas duas pontas pelas lajes.
    """
    return 2.0 * area / perimetro_exposto if perimetro_exposto > 0 else 0.0


def coeficiente_fluencia(fck: float, umidade: float, espessura: float,
                         idade_carregamento: float) -> float:
    """Coeficiente de fluência ``phi(t_inf, t0)`` pela Tabela 8.1.

    ``umidade`` é a umidade média ambiente em %, ``espessura`` a espessura
    fictícia ``2Ac/u`` em cm e ``idade_carregamento`` o ``t0`` em dias. As
    três entradas são interpoladas linearmente, como o item 8.2.11 admite;
    fora da faixa tabelada o valor é truncado no extremo.

    A tabela separa as classes até C45 das de C50 em diante, e a diferença
    entre as duas é grande -- de 3,4 para 2,0 em ambiente de 40 % com
    carregamento aos 30 dias. Não é refinamento: o concreto de alta
    resistência flui bem menos.
    """
    faixa = "C20-C45" if fck <= 45.0 else "C50-C90"
    por_idade = FLUENCIA[faixa]
    valores_por_idade = []
    for t0 in IDADES_FLUENCIA:
        linha = por_idade[t0]
        # primeiro interpola na espessura, depois na umidade
        por_umidade = [_interpolar(espessura, ESPESSURAS_FLUENCIA,
                                   linha[u]) for u in UMIDADES_FLUENCIA]
        valores_por_idade.append(
            _interpolar(umidade, UMIDADES_FLUENCIA, por_umidade))
    return _interpolar(idade_carregamento, IDADES_FLUENCIA,
                       valores_por_idade)
