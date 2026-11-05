# -*- coding: utf-8 -*-
"""
flexocompressao.py
Dimensionamento da seção retangular à flexão composta **normal** pelo roteiro
dos casos fechados -- FC1 a FC4 na flexo-compressão, FT1 a FT4 na flexo-tração
-- que é o método da planilha de referência e da bibliografia da disciplina.

O modelo é o de **duas camadas**: toda a armadura de um lado concentrada em
``As1``, na profundidade ``d``, e a do outro em ``As2``, na profundidade
``d'``. As barras intermediárias das faces laterais não entram. É uma
simplificação a favor da segurança no momento -- elas ficam perto da linha
neutra e pouco ajudam --, mas **não** na força normal, que elas de fato
ajudam a resistir. Por isso o resultado daqui é a armadura de partida, e quem
dá o veredito final é o motor seccional de :mod:`pilares.core.seccional`, com
as barras onde elas realmente estão.

Convenções deste módulo:

    ``Nd`` positiva em compressão; ``Md`` sempre tomado em módulo, com
    ``As1`` colocada do lado **afastado** da resultante -- o lado tracionado
    quando a excentricidade é grande.
    ``sigma`` positiva em compressão, tanto no concreto quanto no aço.
    ``y`` medido a partir da fibra mais comprimida.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .materiais import Aco, Concreto
from .formato import num

#: Deformação máxima de tração no aço, ‰ (item 17.2.2).
EPS_S_MAXIMA = 10.0

#: Casos previstos pelo roteiro.
CASOS = ("FC1", "FC2", "FC3", "FC4", "FT1", "FT2", "FT3", "FT4")

DESCRICAO_CASO = {
    "FC1": "flexo-compressão, grande excentricidade, armadura simples",
    "FC2": "flexo-compressão, grande excentricidade, armadura dupla",
    "FC3": "flexo-compressão, pequena excentricidade",
    "FC4": "compressão composta (seção inteiramente comprimida)",
    "FT1": "flexo-tração, grande excentricidade, armadura simples",
    "FT2": "flexo-tração, grande excentricidade, armadura dupla",
    "FT3": "flexo-tração, pequena excentricidade",
    "FT4": "tração composta (seção inteiramente tracionada)",
}


# ---------------------------------------------------------------------------
# Dados da seção retangular em uma direção
# ---------------------------------------------------------------------------

@dataclass
class Retangular:
    """Seção retangular vista de uma direção de flexão.

    ``h`` é a altura na direção em que a excentricidade atua e ``b`` a largura
    perpendicular a ela. Na direção x, ``h = hx`` e ``b = hy``.
    """

    b: float
    h: float
    d_linha: float               # d', cm
    concreto: Concreto
    aco: Aco

    @property
    def d(self) -> float:
        return self.h - self.d_linha

    @property
    def alfa_c(self) -> float:
        """Tensão do retângulo equivalente sobre ``fcd``: ``alfa_c·eta_c``
        (17.2.2-e, edição de 2026). O nome ficou ``alfa_c`` porque é o lugar
        dele nas fórmulas do roteiro; a largura da seção retangular não
        diminui rumo à borda, então não cabe o fator 0,9."""
        return self.concreto.fator_bloco

    @property
    def lam(self) -> float:
        return self.concreto.lambda_bloco

    @property
    def fcd(self) -> float:
        """kN/cm²."""
        return self.concreto.fcd_kNcm2

    @property
    def fyd(self) -> float:
        """kN/cm²."""
        return self.aco.fyd_kNcm2

    @property
    def eps_cu(self) -> float:
        return self.concreto.eps_cu_mil

    @property
    def eps_c2(self) -> float:
        return self.concreto.eps_c2_mil

    @property
    def eps_yd(self) -> float:
        return self.aco.eps_yd_mil

    @property
    def y_c(self) -> float:
        """Profundidade do polo C, cm: ``h (εcu - εc2)/εcu``."""
        return self.h * (self.eps_cu - self.eps_c2) / self.eps_cu

    @property
    def x_23(self) -> float:
        """Fronteira dos domínios 2 e 3, cm."""
        return self.d * self.eps_cu / (self.eps_cu + EPS_S_MAXIMA)

    @property
    def x_lim(self) -> float:
        """Fronteira dos domínios 3 e 4, cm: aço no escoamento."""
        return self.d * self.eps_cu / (self.eps_cu + self.eps_yd)

    @property
    def Rcc_pleno(self) -> float:
        """Resultante do concreto com a seção inteiramente comprimida, kN."""
        return self.alfa_c * self.fcd * self.b * self.h

    @property
    def Md_lim(self) -> float:
        """Momento que a seção resiste com armadura simples, kN·cm.

        É o momento em torno de ``As1`` com a linha neutra em ``x_lim``: acima
        dele o concreto sozinho não equilibra e entra armadura comprimida.
        """
        y = self.lam * self.x_lim
        return self.alfa_c * self.fcd * self.b * y * (self.d - y / 2.0)

    # -- deformações e tensões ---------------------------------------------
    def dominio(self, x: float) -> str:
        if x <= 0.0:
            return "1"
        if x <= self.x_23:
            return "2"
        if x <= self.x_lim:
            return "3"
        if x <= self.d:
            return "4"
        if x <= self.h:
            return "4a"
        return "5"

    def eps(self, x: float, y: float) -> float:
        """Deformação em ``y``, ‰, positiva na compressão.

        Os três polos do item 17.2.2 numa expressão só por faixa de ``x``:
        polo A enquanto a linha neutra é rasa, polo B no miolo e polo C quando
        a seção fica toda comprimida.
        """
        if x <= 0.0:
            return -EPS_S_MAXIMA
        if x <= self.x_23:                       # polo A
            denom = self.d - x
            return EPS_S_MAXIMA * (x - y) / denom if denom > 1e-12 else 0.0
        if x <= self.h:                          # polo B
            return self.eps_cu * (x - y) / x
        denom = x - self.y_c                     # polo C
        return self.eps_c2 * (x - y) / denom if abs(denom) > 1e-12 else 0.0

    def sigma_s(self, eps_mil: float) -> float:
        """Tensão no aço, kN/cm², positiva na compressão."""
        s = 1.0 if eps_mil >= 0 else -1.0
        return s * min(abs(eps_mil) * self.aco.Es_kNcm2 / 1000.0, self.fyd)

    def sigma1(self, x: float) -> float:
        """Tensão em ``As1`` (profundidade ``d``), kN/cm²."""
        return self.sigma_s(self.eps(x, self.d))

    def sigma2(self, x: float) -> float:
        """Tensão em ``As2`` (profundidade ``d'``), kN/cm²."""
        return self.sigma_s(self.eps(x, self.d_linha))

    def Rcc(self, x: float) -> float:
        """Resultante de compressão do concreto, kN, com o bloco retangular.

        O bloco de altura ``lambda x`` é truncado na altura da seção: passado
        ``x = h/lambda`` não há mais concreto para comprimir, e deixar a
        expressão correr geraria compressão fora da peça.
        """
        y = min(self.lam * max(x, 0.0), self.h)
        return self.alfa_c * self.fcd * self.b * y

    def braco_Rcc(self, x: float) -> float:
        """Distância do CG da seção ao CG do bloco comprimido, cm."""
        y = min(self.lam * max(x, 0.0), self.h)
        return self.h / 2.0 - y / 2.0


# ---------------------------------------------------------------------------
# Classificação em casos
# ---------------------------------------------------------------------------

@dataclass
class Classificacao:
    """Caso do roteiro, com as grandezas que o determinaram."""

    caso: str
    caso_simetrico: str
    e0: float                    # cm
    e1: float                    # cm, de Nd até As1
    e2: float                    # cm, de Nd até As2
    e2_0: float = 0.0            # cm
    e2_GP: float = 0.0
    e2_PC: float = 0.0
    e2_23: float = 0.0
    e2_34: float = 0.0
    excentricidade: str = ""     # "Grande" / "Pequena" / "Composta"
    precisa_armadura: bool = True
    armadura: str = ""           # "Simples" / "Dupla"
    avisos: list[str] = field(default_factory=list)


def classificar(sec: Retangular, Nd: float, Md: float) -> Classificacao:
    """Identifica o caso do roteiro para ``(Nd, Md)``.

    A lógica é a da planilha de referência, item a item:

    1. ``e0 = Md/Nd`` e as distâncias ``e1`` e ``e2`` de ``Nd`` a cada camada;
    2. a excentricidade é **grande** quando ``e0 >= (d-d')/2`` -- a resultante
       cai fora do miolo entre as camadas -- ou quando ``e2 <= e2,GP``, o
       limite de grande excentricidade com a linha neutra em ``x_lim``;
    3. sendo grande, ``Nd e1 <= Md,lim`` decide entre armadura simples e dupla;
    4. sendo pequena, ``e2 <= e2,PC`` separa a pequena excentricidade da
       compressão composta, em que a seção inteira está comprimida.

    O caso **simétrico** segue caminho próprio a partir de ``e2,23`` e
    ``e2,34``: como as duas camadas têm a mesma área, a fronteira entre os
    casos não é a mesma.
    """
    avisos: list[str] = []
    compressao = Nd >= 0.0
    Nabs = abs(Nd)
    e0 = abs(Md) / Nabs if Nabs > 1e-9 else float("inf")
    meio = (sec.d - sec.d_linha) / 2.0
    e1 = meio + e0 if compressao else meio - e0
    e2 = meio - e0 if compressao else meio + e0

    prefixo = "FC" if compressao else "FT"
    grande = e0 >= meio - 1e-9

    # e2,0: abaixo dele a seção dispensa armadura calculada (só a mínima).
    e2_0 = (Nabs / (2.0 * sec.alfa_c * sec.fcd * sec.b) - sec.d_linha
            if compressao else 0.0)
    precisa = True if not compressao else (e2 < e2_0)

    # e2,GP: fronteira da grande excentricidade, linha neutra em x_lim.
    y_lim = sec.lam * sec.x_lim
    e2_GP = (sec.alfa_c * sec.fcd * sec.b * y_lim
             * (y_lim / 2.0 - sec.d_linha) / Nabs) if Nabs > 1e-9 else 0.0
    if compressao and not grande:
        grande = e2 <= e2_GP + 1e-9

    # e2,PC: fronteira entre pequena excentricidade e compressão composta.
    e2_PC = (sec.Rcc_pleno * (sec.h / 2.0 - sec.d_linha) / Nabs
             if Nabs > 1e-9 else 0.0)

    if grande:
        simples = Nabs * abs(e1) <= sec.Md_lim + 1e-9
        armadura = "Simples" if simples else "Dupla"
        caso = f"{prefixo}1" if simples else f"{prefixo}2"
        excentricidade = "Grande"
    else:
        armadura = ""
        if compressao:
            pequena = e2 <= e2_PC + 1e-9
            caso = "FC3" if pequena else "FC4"
            excentricidade = "Pequena" if pequena else "Composta"
        else:
            # Com a resultante entre as camadas a seção já está toda
            # tracionada; o roteiro separa a tração centrada (FT4, as duas
            # camadas iguais) da excêntrica (FT3). Antes o teste ``e0 <
            # meio`` repetia o do ramo e o FT4 nunca era escolhido.
            caso = "FT4" if e0 <= 1e-6 * max(meio, 1.0) else "FT3"
            excentricidade = "Pequena"

    # -- caso simétrico -----------------------------------------------------
    # e2,23 é a fronteira entre os casos simétricos 2 e 3, e sai da linha
    # neutra em x = d: ali a deformação de As1 passa por zero, e a camada que
    # até então tracionava começa a comprimir. Não confundir com x_23, que é
    # a fronteira dos domínios 2 e 3 e nada tem a ver.
    y_d = sec.lam * sec.d
    e2_23 = (sec.alfa_c * sec.fcd * sec.b * y_d
             * (y_d / 2.0 - sec.d_linha) / Nabs) if Nabs > 1e-9 else 0.0
    e2_34 = _e2_34(sec, Nabs)
    if not compressao:
        caso_sim = caso
    elif e0 >= meio - 1e-9:
        caso_sim = "FC1"
    elif e2 <= e2_23 + 1e-9:
        caso_sim = "FC2"
    elif e2 <= e2_34 + 1e-9:
        caso_sim = "FC3"
    else:
        caso_sim = "FC4"

    if not compressao:
        avisos.append(av.construtivo(
            "Normal de tração: a seção é dimensionada à flexo-tração, e as "
            "verificações de esbeltez e segunda ordem local não se aplicam."))

    return Classificacao(caso=caso, caso_simetrico=caso_sim, e0=e0, e1=e1,
                         e2=e2, e2_0=e2_0, e2_GP=e2_GP, e2_PC=e2_PC,
                         e2_23=e2_23, e2_34=e2_34,
                         excentricidade=excentricidade,
                         precisa_armadura=precisa, armadura=armadura,
                         avisos=avisos)


def _e2_34(sec: Retangular, Nabs: float) -> float:
    """Fronteira ``e2,34`` do caso simétrico, cm.

    Sai da reta de deformação que passa pelo polo C com a linha neutra em
    ``x = h/lambda`` -- o instante em que o bloco retangular acaba de cobrir a
    seção inteira. As tensões nas duas camadas nessa reta, ``sigma1*`` e
    ``sigma2*``, dão a assimetria de esforço que a expressão pondera.
    """
    if Nabs <= 1e-9:
        return 0.0
    x = sec.h / sec.lam
    e1s = sec.eps(x, sec.d)
    e2s = sec.eps(x, sec.d_linha)
    s1 = sec.sigma_s(e1s)
    s2 = sec.sigma_s(e2s)
    soma = s1 + s2
    if abs(soma) < 1e-12:
        return 0.0
    return 0.5 * (sec.d - sec.d_linha) * (
        1.0 + (sec.Rcc_pleno / Nabs - 1.0) * (s2 - s1) / soma)


# ---------------------------------------------------------------------------
# Dimensionamento
# ---------------------------------------------------------------------------

@dataclass
class Dimensionamento:
    """Resultado do dimensionamento da seção numa direção."""

    direcao: str
    Nd: float
    Md: float
    classificacao: Classificacao
    As1: float = 0.0             # cm²
    As2: float = 0.0             # cm²
    x: float = 0.0               # cm, linha neutra
    dominio: str = ""
    sigma1: float = 0.0          # kN/cm²
    sigma2: float = 0.0
    simetrica: bool = True
    convergiu: bool = True
    avisos: list[str] = field(default_factory=list)

    @property
    def As_total(self) -> float:
        return self.As1 + self.As2

    @property
    def caso(self) -> str:
        c = self.classificacao
        return c.caso_simetrico if self.simetrica else c.caso


def _residuo_simetrica(sec: Retangular, Nd: float, Md: float, x: float
                       ) -> tuple[float, float]:
    """Resíduo do equilíbrio simétrico para a linha neutra ``x`` e o ``As``
    que dele sai: ``(F, As)``.

    Com armadura simétrica sobram duas incógnitas -- ``As`` e ``x`` -- e duas
    equações, a de força normal e a de momento:

        ``N = Rcc + As (sigma1 + sigma2)``
        ``M = Rcc . z + As (sigma2 - sigma1) (d - d')/2``

    Cada uma isola um ``As``: ``As_N = (N - Rcc)/soma`` e ``As_M = (M - Rcc
    z)/denom``. O equilíbrio é onde as duas concordam -- mas a **diferença**
    ``As_N - As_M`` tem polos onde ``soma`` ou ``denom`` se anulam, e
    ``soma = sigma1 + sigma2`` vale **zero em todo o domínio 3** (uma camada
    tracionada e a outra comprimida, as duas escoando): ali ``As_N`` não
    existe, e a solução -- ``Rcc = N`` --, a que a seção de pilar mais cai,
    ficava de fora. O resíduo é, então, a forma **multiplicada em cruz**,

        ``F = (N - Rcc) denom - (M - Rcc z) soma``

    que é contínua e se anula exatamente no equilíbrio, sem dividir por nada
    -- é o que a função ``f(xi)`` do roteiro de ARAÚJO (2018, eq. 2.5.11) faz.
    O ``As`` sai da equação de maior denominador.
    """
    s1 = sec.sigma1(x)
    s2 = sec.sigma2(x)
    Rcc = sec.Rcc(x)
    soma = s1 + s2
    denom = (s2 - s1) * (sec.d - sec.d_linha) / 2.0
    num_N = Nd - Rcc
    num_M = abs(Md) - Rcc * sec.braco_Rcc(x)
    F = num_N * denom - num_M * soma
    if abs(denom) >= abs(soma):
        As = num_M / denom if abs(denom) > 1e-9 else float("nan")
    else:
        As = num_N / soma
    return F, As


def dimensionar_simetrica(sec: Retangular, Nd: float, Md: float,
                          direcao: str = "x") -> Dimensionamento:
    """Armadura simétrica ``As1 = As2`` que equilibra ``(Nd, Md)``.

    É a hipótese que os métodos aproximados do pilar-padrão pressupõem (itens
    15.8.3.3.2 e 15.8.3.3.3, "armadura simétrica e constante ao longo do
    eixo"), e a que se usa em pilar por razão construtiva: a direção do
    momento muda com a combinação, e armar assimetricamente exigiria garantir
    na obra qual face é qual.
    """
    cl = classificar(sec, Nd, Md)
    avisos = list(cl.avisos)

    # Varredura da linha neutra: começa acima de zero para não cair na
    # singularidade do domínio 1 e vai até bem além da seção, cobrindo o
    # domínio 5 inteiro.
    x_max = 6.0 * sec.h
    n = 400
    anterior = None
    raizes: list[float] = []
    for i in range(1, n + 1):
        x = x_max * i / n
        r, _ = _residuo_simetrica(sec, Nd, Md, x)
        if not math.isfinite(r):
            anterior = None
            continue
        if anterior is not None and anterior[1] * r < 0.0:
            raizes.append(_bissecao(sec, Nd, Md, anterior[0], x))
        anterior = (x, r)

    melhor: tuple[float, float] | None = None       # (As, x)
    for x in raizes:
        _, As = _residuo_simetrica(sec, Nd, Md, x)
        if not math.isfinite(As) or As < -1e-6:
            continue
        As = max(As, 0.0)
        if melhor is None or As < melhor[0]:
            melhor = (As, x)

    if melhor is None:
        avisos.append(av.construtivo(
            f"O roteiro de armadura de partida não achou equilíbrio "
            f"simétrico em {direcao} para Nd = {num(Nd, 0)} kN e "
            f"Md = {num(abs(Md), 0)} kN·cm com o modelo de duas camadas (As1 "
            f"em d, As2 em d'). É uma limitação conhecida do roteiro, não "
            f"um veredito sobre a seção: ele ignora de propósito a "
            f"contribuição das barras das faces laterais para a força "
            f"normal -- elas só entram no cálculo do momento, a favor da "
            f"segurança --, e numa situação de excentricidade pequena, "
            f"como esta, é justamente essa parcela que falta para fechar "
            f"a conta. Quem decide é o motor seccional, com as barras "
            f"reais nas posições reais."))
        return Dimensionamento(direcao=direcao, Nd=Nd, Md=Md, classificacao=cl,
                               convergiu=False, avisos=avisos)

    As, x = melhor
    return Dimensionamento(direcao=direcao, Nd=Nd, Md=Md, classificacao=cl,
                           As1=As, As2=As, x=x, dominio=sec.dominio(x),
                           sigma1=sec.sigma1(x), sigma2=sec.sigma2(x),
                           simetrica=True, avisos=avisos)


def _bissecao(sec: Retangular, Nd: float, Md: float, a: float, b: float
              ) -> float:
    fa = _residuo_simetrica(sec, Nd, Md, a)[0]
    for _ in range(100):
        m = (a + b) / 2.0
        fm = _residuo_simetrica(sec, Nd, Md, m)[0]
        if fm == 0.0 or b - a < 1e-12:
            return m
        if fa * fm < 0.0:
            b = m
        else:
            a, fa = m, fm
    return (a + b) / 2.0


def dimensionar_assimetrica(sec: Retangular, Nd: float, Md: float,
                            direcao: str = "x") -> Dimensionamento:
    """Armadura assimétrica pelas expressões fechadas de cada caso.

    Reproduz as fórmulas do roteiro FC1-FC4 / FT1-FT4. Cada caso resolve o
    par ``(As1, As2)`` diretamente, sem iteração -- é essa a vantagem do
    roteiro sobre a busca numérica, e é o que permite conferir a conta à mão.
    """
    cl = classificar(sec, Nd, Md)
    avisos = list(cl.avisos)
    caso = cl.caso
    Nabs = abs(Nd)
    dd = sec.d - sec.d_linha
    k = sec.alfa_c * sec.fcd * sec.b

    As1 = As2 = 0.0
    x = 0.0

    if caso in ("FC1", "FT1"):
        # Armadura simples: x sai da equação de momento em torno de As1.
        x = _raiz_momento_As1(sec, Nabs * abs(cl.e1))
        if x is None or x > sec.x_lim + 1e-6:
            avisos.append(av.erro(
                f"Caso {caso} em {direcao}: a linha neutra de armadura "
                f"simples caiu fora do domínio admitido; o roteiro deveria "
                f"ter classificado como armadura dupla."))
            x = sec.x_lim
        y = sec.lam * x
        Rcc = k * y
        As1 = ((Rcc - Nd) if caso == "FC1" else (Rcc + Nabs)) / sec.fyd
        As2 = 0.0
    elif caso in ("FC2", "FT2"):
        x = sec.x_lim
        s2 = sec.sigma2(x)
        As2 = ((Nabs * abs(cl.e1) - sec.Md_lim) / (s2 * dd)
               if abs(s2 * dd) > 1e-9 else 0.0)
        y = sec.lam * x
        As1 = ((-Nd if caso == "FC2" else Nabs) + As2 * s2 + k * y) / sec.fyd
    elif caso == "FC3":
        x = _raiz_momento_As2(sec, Nabs * abs(cl.e2))
        if x is None:
            x = sec.h
        s2 = sec.sigma2(x)
        As1 = 0.0
        As2 = (Nd - k * min(sec.lam * x, sec.h)) / s2 if abs(s2) > 1e-9 else 0.0
    elif caso == "FC4":
        s2 = sec.sigma_s(sec.eps_c2)
        Rcc = sec.Rcc_pleno
        As1 = ((Nabs * abs(cl.e2) - Rcc * (sec.h / 2.0 - sec.d_linha))
               / (s2 * dd)) if abs(s2 * dd) > 1e-9 else 0.0
        As2 = ((Nabs * abs(cl.e1) - Rcc * (sec.d - sec.h / 2.0))
               / (s2 * dd)) if abs(s2 * dd) > 1e-9 else 0.0
        x = sec.h / sec.lam
    elif caso == "FT3":
        As1 = Nabs * abs(cl.e2) / (sec.fyd * dd)
        As2 = Nabs * abs(cl.e1) / (sec.fyd * dd)
    else:                                            # FT4
        As1 = Nabs * abs(cl.e2) / (sec.fyd * dd)
        As2 = Nabs * abs(cl.e1) / (sec.fyd * dd)
        avisos.append(av.construtivo(
            "Caso FT4: seção inteiramente tracionada; as duas camadas "
            "trabalham no escoamento e o concreto não colabora."))

    As1 = max(As1, 0.0)
    As2 = max(As2, 0.0)
    return Dimensionamento(direcao=direcao, Nd=Nd, Md=Md, classificacao=cl,
                           As1=As1, As2=As2, x=x, dominio=sec.dominio(x),
                           sigma1=sec.sigma1(x), sigma2=sec.sigma2(x),
                           simetrica=False, avisos=avisos)


def _raiz_momento_As1(sec: Retangular, M_As1: float) -> float | None:
    """``x`` que equilibra o momento ``M_As1`` tomado em torno de ``As1``.

    ``alfa_c fcd b lambda x (d - lambda x/2) = M``, uma quadrática em ``x``
    cuja menor raiz positiva é a que interessa: a maior corresponde ao ramo
    em que o bloco já passou do centro e o braço volta a diminuir.
    """
    k = sec.alfa_c * sec.fcd * sec.b
    a = -k * sec.lam * sec.lam / 2.0
    b = k * sec.lam * sec.d
    c = -M_As1
    return _menor_raiz(a, b, c)


def _raiz_momento_As2(sec: Retangular, M_As2: float) -> float | None:
    """``x`` que equilibra o momento ``M_As2`` em torno de ``As2``."""
    k = sec.alfa_c * sec.fcd * sec.b
    a = k * sec.lam * sec.lam / 2.0
    b = -k * sec.lam * sec.d_linha
    c = -M_As2
    return _menor_raiz(a, b, c, positiva_maior=True)


def _menor_raiz(a: float, b: float, c: float,
                positiva_maior: bool = False) -> float | None:
    if abs(a) < 1e-12:
        return -c / b if abs(b) > 1e-12 else None
    delta = b * b - 4.0 * a * c
    if delta < 0.0:
        return None
    r = math.sqrt(delta)
    r1 = (-b + r) / (2.0 * a)
    r2 = (-b - r) / (2.0 * a)
    validas = sorted(v for v in (r1, r2) if v > 0.0)
    if not validas:
        return None
    return validas[-1] if positiva_maior else validas[0]


# ---------------------------------------------------------------------------
# Verificação: momento resistente das duas camadas
# ---------------------------------------------------------------------------

def momento_resistente(sec: Retangular, Nd: float, As1: float, As2: float
                       ) -> tuple[float, float, str]:
    """``MRd`` do modelo de duas camadas para a normal dada.

    Procura a linha neutra que equilibra ``Nd`` e devolve
    ``(MRd, x, domínio)``, com ``MRd`` em kN·cm e tomado em torno do CG da
    seção. É a conta que a aba ``Verif`` da planilha faz iterando; aqui ela
    sai por bisseção, que sempre converge porque ``N(x)`` é monótona.
    """
    def N(x: float) -> float:
        return sec.Rcc(x) + As1 * sec.sigma1(x) + As2 * sec.sigma2(x)

    lo, hi = 1e-6, 20.0 * sec.h
    if N(hi) < Nd or N(lo) > Nd:
        return 0.0, 0.0, sec.dominio(0.0)
    for _ in range(200):
        m = (lo + hi) / 2.0
        if N(m) < Nd:
            lo = m
        else:
            hi = m
        if hi - lo < 1e-12:
            break
    x = (lo + hi) / 2.0
    braco = (sec.d - sec.d_linha) / 2.0
    M = (sec.Rcc(x) * sec.braco_Rcc(x)
         + As2 * sec.sigma2(x) * braco - As1 * sec.sigma1(x) * braco)
    return M, x, sec.dominio(x)
