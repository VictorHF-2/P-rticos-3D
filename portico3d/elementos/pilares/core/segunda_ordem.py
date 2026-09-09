# -*- coding: utf-8 -*-
"""
segunda_ordem.py
Efeitos locais de segunda ordem pelos métodos aproximados do pilar-padrão
(itens 15.8.3.3.2 e 15.8.3.3.3 da NBR 6118), a fluência do item 15.8.4 e o
arranjo das **situações de cálculo** que saem daí.

O que este módulo entrega ao dimensionamento é uma lista de situações -- pares
``(ex, ey)`` acompanhados da seção do lance em que atuam --, e não um único
momento. A razão está no item 3.3.3.4 da apostila de referência: obtida a
distribuição de momentos totais em cada direção, "deve ser verificada, para
cada seção ao longo do eixo, se a composição desses momentos solicitantes fica
dentro da envoltória de momentos resistentes", e essa verificação "pode ser
realizada em apenas três seções: nas extremidades A e B e num ponto
intermediário". Reduzir tudo a um par só antes de conhecer a armadura seria
escolher o pior sem poder saber qual é o pior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .esbeltez import Esbeltez
from .modelo import PONTOS_VARREDURA_MINIMO, Pilar


# ---------------------------------------------------------------------------
# Métodos aproximados
# ---------------------------------------------------------------------------

@dataclass
class SegundaOrdem:
    """Segunda ordem local numa direção, pelos dois métodos aproximados."""

    direcao: str
    aplicavel: bool                  # a esbeltez pede segunda ordem?
    nu: float = 0.0                  # força normal adimensional
    curvatura: float = 0.0           # 1/r, cm^-1
    e2_curvatura: float = 0.0        # cm
    e2_rigidez: float = 0.0          # cm
    e2: float = 0.0                  # cm, o adotado
    metodo: str = "-"                # qual governou
    e_cc: float = 0.0                # cm, excentricidade de fluência
    kappa: float = 0.0               # rigidez adimensional do 15.8.3.3.3
    avisos: list[str] = field(default_factory=list)


def forca_normal_adimensional(Nd: float, area: float, fcd_kNcm2: float
                              ) -> float:
    """``nu = Nd / (Ac fcd)``, adimensional."""
    denom = area * fcd_kNcm2
    return Nd / denom if denom > 0 else 0.0


def curvatura_aproximada(h: float, nu: float) -> float:
    """Curvatura da seção crítica, cm⁻¹ (item 15.8.3.3.2).

    ``1/r = 0,005 / [h (nu + 0,5)] <= 0,005 / h``. O teto existe para que a
    curvatura não cresça sem limite quando a normal é pequena: com ``nu``
    tendendo a zero a primeira expressão dobraria o valor, e a peça já teria
    deixado de ser pilar bem antes disso.
    """
    if h <= 0:
        return 0.0
    return min(0.005 / (h * (nu + 0.5)), 0.005 / h)


def e2_por_curvatura(le: float, curvatura: float) -> float:
    """Excentricidade de segunda ordem pelo método da curvatura, cm.

    Vem de ``M_tot = alfa_b M1d,A + Nd le²/10 . 1/r``: a parcela de segunda
    ordem é ``le²/10 . 1/r``, que é a flecha de uma barra de deformada
    senoidal com essa curvatura no meio.
    """
    return le * le / 10.0 * curvatura


def e2_por_rigidez(le: float, h: float, e1: float) -> tuple[float, float]:
    """Excentricidade de segunda ordem pela rigidez aproximada, cm.

    O item 15.8.3.3.3 dá ``M_tot = alfa_b M1d,A / (1 - lambda²/(120 kappa/nu))``
    com ``kappa = 32 (1 + 5 M_tot/(h Nd)) nu``, e a própria norma apresenta a
    forma direta

        ``A M_tot² + B M_tot + C = 0``,
        ``A = 5h``, ``B = h² Nd - Nd le²/320 - 5h alfa_b M1d,A``,
        ``C = -Nd h² alfa_b M1d,A``.

    Dividindo tudo por ``5 h Nd²`` e escrevendo em excentricidades
    (``e = M/Nd``, ``e1 = alfa_b M1d,A/Nd``) sobra uma quadrática que **não
    depende de Nd**:

        ``e² + (h/5 - le²/(1600 h) - e1) e - h e1/5 = 0``.

    É a forma que a planilha de referência usa, e é a implementada aqui: a
    normal sai da conta e o resultado deixa de depender de quantos algarismos
    ela tem. Devolve ``(e_total, kappa)``.
    """
    if h <= 0:
        return 0.0, 0.0
    b = h / 5.0 - le * le / (1600.0 * h) - e1
    c = -h * e1 / 5.0
    delta = b * b - 4.0 * c
    if delta < 0.0:
        return float("inf"), 0.0
    e_total = (-b + math.sqrt(delta)) / 2.0
    kappa = 32.0 * (1.0 + 5.0 * e_total / h)
    return e_total, kappa


def excentricidade_fluencia(pilar: Pilar, direcao: str, e1: float,
                            Ic: float) -> tuple[float, list[str]]:
    """Excentricidade adicional de fluência, cm (item 15.8.4).

    ``e_cc = (M_Sg/N_Sg + e_a) [exp(phi N_Sg/(N_e - N_Sg)) - 1]``, com
    ``N_e = 10 E_ci I_c / le²``. A excentricidade acidental ``e_a`` entra
    zerada: neste programa a imperfeição geométrica local está coberta pelo
    momento mínimo do item 11.3.3.4.3, que é comparado com o de primeira
    ordem em vez de somado a ele, e somá-la aqui seria contá-la duas vezes.
    """
    avisos: list[str] = []
    cfg = pilar.config
    le = pilar.le(direcao)
    Nsg = abs(pilar.Nd) * cfg.Nsg_sobre_Nd
    Ne = 10.0 * (pilar.concreto.Eci / 10.0) * Ic / (le * le)   # kN
    if Ne <= Nsg:
        avisos.append(av.erro(
            f"Fluência em {direcao}: a carga de flambagem N_e = {Ne:.0f} kN "
            f"não supera a normal quase permanente N_Sg = {Nsg:.0f} kN. A "
            f"expressão do item 15.8.4 diverge, o que é a própria peça "
            f"dizendo que instabiliza sob carga de longa duração."))
        return 0.0, avisos
    fator = math.exp(pilar.phi_fluencia * Nsg / (Ne - Nsg)) - 1.0
    return abs(e1) * fator, avisos


def analisar(pilar: Pilar, esb: Esbeltez) -> SegundaOrdem:
    """Segunda ordem local na direção de ``esb``."""
    avisos: list[str] = []
    prop = pilar.secao.propriedades()
    Nd = pilar.Nd
    nu = forca_normal_adimensional(abs(Nd), prop.area,
                                   pilar.concreto.fcd_kNcm2)

    if not esb.considerar_2a_ordem or Nd <= 0.0:
        motivo = ("a normal é de tração" if Nd <= 0.0
                  else f"lambda = {esb.lam:.1f} <= lambda_1 = {esb.lam_1:.1f}")
        return SegundaOrdem(direcao=esb.direcao, aplicavel=False, nu=nu,
                            metodo=f"dispensada ({motivo})", avisos=avisos)

    h = esb.h
    # e1 que entra na segunda ordem já é o de projeto: alfa_b vezes o de
    # primeira ordem, com o piso do momento mínimo (item 15.8.3.3.2).
    e1 = esb.alfa_b * max(abs(esb.e1), esb.e1_min)

    curv = curvatura_aproximada(h, nu)
    e2_curv = e2_por_curvatura(esb.le, curv)
    e_total_rig, kappa = e2_por_rigidez(esb.le, h, e1)
    e2_rig = max(e_total_rig - e1, 0.0)

    cfg = pilar.config
    if cfg.metodo_2a_ordem == "curvatura":
        e2, metodo = e2_curv, "pilar-padrão com curvatura aproximada"
    elif cfg.metodo_2a_ordem == "rigidez":
        e2, metodo = e2_rig, "pilar-padrão com rigidez aproximada"
    else:
        if e2_curv <= e2_rig:
            e2, metodo = e2_curv, "curvatura aproximada (menor dos dois)"
        else:
            e2, metodo = e2_rig, "rigidez aproximada (menor dos dois)"

    if (cfg.metodo_2a_ordem in ("rigidez", "menor")
            and pilar.secao.tipo != "retangular"):
        avisos.append(av.erro(
            f"O método da rigidez aproximada (15.8.3.3.3) só vale para seção "
            f"retangular constante, e a seção é {pilar.secao.tipo}. Adote o "
            f"método da curvatura aproximada nos critérios de cálculo."))
    if not math.isfinite(e2_rig):
        avisos.append(av.erro(
            f"A quadrática da rigidez aproximada em {esb.direcao} não tem "
            f"raiz real: a peça não encontra equilíbrio de segunda ordem com "
            f"essa esbeltez e essa excentricidade de primeira ordem."))

    e_cc = 0.0
    if cfg.considerar_fluencia:
        Ic = prop.Ix if esb.direcao == "x" else prop.Iy
        e_cc, av_flu = excentricidade_fluencia(pilar, esb.direcao, e1, Ic)
        avisos += av_flu
    elif esb.fluencia_obrigatoria:
        avisos.append(av.erro(
            f"Esbeltez em {esb.direcao} = {esb.lam:.0f} > 90 e a fluência "
            f"está desligada nos critérios; o item 15.8.4 a torna "
            f"obrigatória nessa faixa."))

    return SegundaOrdem(direcao=esb.direcao, aplicavel=True, nu=nu,
                        curvatura=curv, e2_curvatura=e2_curv,
                        e2_rigidez=e2_rig, e2=e2 + e_cc, metodo=metodo,
                        e_cc=e_cc, kappa=kappa, avisos=avisos)


# ---------------------------------------------------------------------------
# Situações de cálculo
# ---------------------------------------------------------------------------

@dataclass
class Situacao:
    """Um par de excentricidades a verificar numa seção do lance."""

    nome: str
    posicao: str                 # "extremo" ou "meio"
    ex: float                    # cm
    ey: float                    # cm
    Mx: float                    # kN·cm, já com o piso do momento mínimo
    My: float
    descricao: str = ""

    @property
    def modulo(self) -> float:
        """Módulo da excentricidade resultante, cm."""
        return math.hypot(self.ex, self.ey)


def momento_com_piso(Nd: float, e: float, M_min: float) -> float:
    """Momento de cálculo, com o piso do momento mínimo (11.3.3.4.3)."""
    return max(abs(Nd) * abs(e), M_min) * (1.0 if e >= 0 else -1.0)


def situacoes(pilar: Pilar, esb: dict[str, Esbeltez],
              so: dict[str, SegundaOrdem]) -> list[Situacao]:
    """Monta as situações de cálculo a verificar.

    O momento mínimo (item 11.3.3.4.3) entra aqui de duas formas possíveis,
    conforme ``pilar.config.momento_minimo_metodo``:

    ``planilha``
        piso ``max(|M|, M1d,min)`` imposto diretamente em cada situação,
        numa direção de cada vez -- o critério mais simples, e o que este
        programa usava antes de ler o item 3.1 da apostila de referência com
        atenção.

    ``envoltoria`` (padrão)
        as situações aqui carregam só o momento **real**, sem piso nenhum: o
        item 3.1 verifica o momento mínimo à parte, com duas análises
        isoladas à flexão composta normal (ver
        ``dimensionar._verificar_momento_minimo``), e não como piso do
        momento real. Combinar os dois inflaria situações que a norma não
        pede para inflar -- basta que a seção resista, isoladamente, ao
        mínimo de cada direção.

    Em ambos os casos, no **meio** entram ``alfa_b e1`` e a segunda ordem.
    Aqui o programa diverge da planilha de referência, e a divergência é
    deliberada: a planilha põe ``e2`` só na direção cujo mínimo está sendo
    imposto, de modo que os dois efeitos de segunda ordem nunca se somam. O
    item 3.3.3.4 da apostila pede o contrário -- num ponto intermediário
    "admite-se atuar concomitantemente os momentos Md,tot nas duas
    direções". O critério ``combinar_2a_ordem_biaxial`` liga o comportamento
    normativo (padrão) e, desligado, reproduz a planilha.
    """
    Nd = pilar.Nd
    ex1 = esb["x"].e1
    ey1 = esb["y"].e1
    abx, aby = esb["x"].alfa_b, esb["y"].alfa_b
    e2x, e2y = so["x"].e2, so["y"].e2
    combinar = pilar.config.combinar_2a_ordem_biaxial
    sx = 1.0 if (ex1 or 1.0) >= 0 else -1.0
    sy = 1.0 if (ey1 or 1.0) >= 0 else -1.0

    if pilar.config.momento_minimo_metodo == "planilha":
        exmin = esb["x"].e1_min
        eymin = esb["y"].e1_min
        Mx_min = esb["x"].M1d_min
        My_min = esb["y"].M1d_min

        def s(nome, posicao, ex, ey, descricao) -> Situacao:
            return Situacao(nome=nome, posicao=posicao, ex=ex, ey=ey,
                            Mx=momento_com_piso(Nd, ex, Mx_min),
                            My=momento_com_piso(Nd, ey, My_min),
                            descricao=descricao)

        lista = [
            s("Situação 1", "extremo",
              math.copysign(max(abs(ex1), exmin), ex1 or 1.0), ey1,
              "extremo do pilar, mínimo imposto em x"),
            s("Situação 2", "extremo",
              ex1, math.copysign(max(abs(ey1), eymin), ey1 or 1.0),
              "extremo do pilar, mínimo imposto em y"),
        ]

        ex_meio = math.copysign(abx * max(abs(ex1), exmin), ex1 or 1.0)
        ey_meio = math.copysign(aby * max(abs(ey1), eymin), ey1 or 1.0)
        ex_livre = abx * ex1
        ey_livre = aby * ey1

        if combinar:
            lista.append(s("Situação 3", "meio",
                           ex_meio + sx * e2x, ey_livre + sy * e2y,
                           "meio do pilar, mínimo imposto em x, 2ª ordem "
                           "nas duas direções"))
            lista.append(s("Situação 4", "meio",
                           ex_livre + sx * e2x, ey_meio + sy * e2y,
                           "meio do pilar, mínimo imposto em y, 2ª ordem "
                           "nas duas direções"))
        else:
            lista.append(s("Situação 3", "meio", ex_meio + sx * e2x,
                           ey_livre,
                           "meio do pilar, mínimo e 2ª ordem em x (critério "
                           "da planilha)"))
            lista.append(s("Situação 4", "meio", ex_livre,
                           ey_meio + sy * e2y,
                           "meio do pilar, mínimo e 2ª ordem em y (critério "
                           "da planilha)"))
        return lista

    # "envoltoria": sem piso -- o momento mínimo é verificado à parte.
    def s(nome, posicao, ex, ey, descricao) -> Situacao:
        return Situacao(nome=nome, posicao=posicao, ex=ex, ey=ey,
                        Mx=momento_com_piso(Nd, ex, 0.0),
                        My=momento_com_piso(Nd, ey, 0.0), descricao=descricao)

    lista = [s("Extremo", "extremo", ex1, ey1,
               "extremo do pilar, momento real de 1ª ordem")]
    ex_meio = abx * ex1
    ey_meio = aby * ey1
    if combinar:
        lista.append(s("Meio", "meio", ex_meio + sx * e2x,
                       ey_meio + sy * e2y,
                       "meio do pilar, 2ª ordem nas duas direções"))
    else:
        lista.append(s("Meio (x)", "meio", ex_meio + sx * e2x, ey_meio,
                       "meio do pilar, 2ª ordem em x (critério da "
                       "planilha)"))
        lista.append(s("Meio (y)", "meio", ex_meio, ey_meio + sy * e2y,
                       "meio do pilar, 2ª ordem em y (critério da "
                       "planilha)"))
    return lista


def situacoes_altura(pilar: Pilar, esb: dict[str, Esbeltez],
                     so: dict[str, SegundaOrdem],
                     n_pontos: int | None = None) -> list[Situacao]:
    """Situações de cálculo por varredura contínua da altura do lance.

    Alternativa ao critério dos três pontos do item 15.8.3.3.5, usada quando
    ``pilar.config.verificacao_altura == "continua"`` -- é o que o PCalc faz
    para achar o seu "F.S. mínimo": em vez de amostrar extremos e meio, varre
    ``z`` de 0 (base) a ``altura`` (topo) e, em cada ponto, combina o que
    atua em cada direção **separadamente**, conforme a esbeltez pedir 2ª
    ordem naquela direção ou não:

    * direção **sem** 2ª ordem: o momento real de primeira ordem,
      interpolado linearmente entre o de base e o de topo -- o diagrama real,
      sem artifício nenhum;
    * direção **com** 2ª ordem: ``alfa_b M1d,A`` -- a mesma constante
      equivalente do critério dos três pontos, e não o diagrama real -- somada
      à segunda ordem senoidal do método da curvatura aproximada (15.8.3.3.2),
      ``Nd e2(z)`` com ``e2(z) = e2_max sin(pi z / le)``. O alfa_b **não**
      soma -- ele é o artifício da norma para condensar um diagrama que pode
      ter curvatura reversa numa constante conservadora, e continua sendo
      necessário aqui: descartá-lo e interpolar o M1 real faria a peça
      "sentir menos" momento perto da ponta de momento nulo do que a norma
      manda supor. É só o pico de 2ª ordem que a varredura contínua liberta de
      ficar preso ao meio físico do lance -- coincide com o do critério dos
      três pontos sempre que as duas direções pedem 2ª ordem ao mesmo tempo
      (``e2_max`` cai exatamente sobre ``z = le/2`` nas duas), e diverge só
      quando uma direção precisa e a outra não, que é o caso em que os três
      pontos deixam de enxergar o pior ponto real.

    Em pilar biapoiado (``le = altura``) o seno de cada direção com 2ª ordem
    vale zero nos dois extremos e máximo no meio físico; em balanço
    (``le = 2 altura``), o lance físico é a metade inferior dessa senoide --
    zero no engaste, máximo na ponta livre.

    Todos os pontos entram com ``posicao="meio"``: os extremos exatos
    (momento real, sem 2ª ordem) já são verificados à parte, em
    ``dimensionar._situacao_extremo_real``.
    """
    Nd = pilar.Nd
    f = pilar.fator_esforcos
    altura = pilar.lance.altura
    # Menos de três pontos não é varredura: com dois, a grade cai nos dois
    # extremos e **pula o pico de segunda ordem**, que é o que a varredura
    # existe para achar -- o F.S. sairia várias vezes maior que o real. A
    # validação do Config já acusa o valor; aqui ele é travado, para o número
    # inseguro não ser calculado nem exibido ao lado do aviso.
    n = max(int(n_pontos or pilar.config.pontos_varredura_altura),
            PONTOS_VARREDURA_MINIMO)
    # A base vem pelo conversor de convenção do modelo, não crua.
    Mx_topo, Mx_base = f * pilar.esforcos.Mx_topo, f * pilar.momento_base("x")
    My_topo, My_base = f * pilar.esforcos.My_topo, f * pilar.momento_base("y")
    ex1, ey1 = esb["x"].e1, esb["y"].e1
    abx, aby = esb["x"].alfa_b, esb["y"].alfa_b
    sx = 1.0 if (ex1 or 1.0) >= 0 else -1.0
    sy = 1.0 if (ey1 or 1.0) >= 0 else -1.0
    e2x_max = so["x"].e2 if esb["x"].considerar_2a_ordem else 0.0
    e2y_max = so["y"].e2 if esb["y"].considerar_2a_ordem else 0.0
    le_x, le_y = esb["x"].le, esb["y"].le

    lista: list[Situacao] = []
    for i in range(n):
        z = altura * i / (n - 1)
        t = z / altura if altura > 0 else 0.0
        if esb["x"].considerar_2a_ordem:
            Mx = (abx * Nd * ex1
                  + (Nd * sx * e2x_max * math.sin(math.pi * z / le_x)
                     if le_x > 0 else 0.0))
        else:
            Mx = Mx_base + (Mx_topo - Mx_base) * t
        if esb["y"].considerar_2a_ordem:
            My = (aby * Nd * ey1
                  + (Nd * sy * e2y_max * math.sin(math.pi * z / le_y)
                     if le_y > 0 else 0.0))
        else:
            My = My_base + (My_topo - My_base) * t
        ex = Mx / Nd if abs(Nd) > 1e-9 else 0.0
        ey = My / Nd if abs(Nd) > 1e-9 else 0.0
        lista.append(Situacao(
            nome=f"z = {z:.0f} cm", posicao="meio", ex=ex, ey=ey,
            Mx=Mx, My=My,
            descricao=f"varredura contínua, ponto {i + 1}/{n} da altura"))
    return lista


def governante(lista: list[Situacao]) -> Situacao:
    """Situação de maior excentricidade resultante.

    É o critério da planilha de referência -- ``max sqrt(ex² + ey²)`` -- e
    serve para **escolher a armadura de partida**, não para encerrar a
    verificação: como as duas direções têm alturas diferentes, o maior módulo
    não é necessariamente o caso mais desfavorável. Por isso o programa
    verifica a armadura escolhida contra **todas** as situações, e é essa
    verificação que dá o veredito.
    """
    return max(lista, key=lambda s: s.modulo)
