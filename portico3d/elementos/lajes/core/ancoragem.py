# -*- coding: utf-8 -*-
"""
ancoragem.py
Aderência e comprimento de ancoragem das barras da laje, itens 9.3.2.1 e
9.4.2.5 da NBR 6118.

O detalhamento da laje é regra construtiva, não a escolha caso a caso de uma
viga -- mas as duas faces têm regras diferentes:

    negativa .... **sempre** com gancho a 90° nas duas pontas, com a ponta
                  igual à espessura da laje menos os dois cobrimentos (o que
                  cabe entre as duas faces sem aflorar em nenhuma). O gancho
                  não é escolhido para fechar ``lb,nec``: é a regra, e o
                  cálculo só confere se ela fecha;
    positiva .... **reta por regra**, de um extremo ao outro, sem escalonar
                  -- e com gancho a 90° só na extremidade em que o trecho
                  reto dentro do apoio não fecha ``lb,nec``. Aí dobrar a
                  ponta é o remédio da própria norma (o alfa cai de 1,0 para
                  0,7, 9.4.2.5), e é melhor que entregar uma barra reta que
                  se sabe mal ancorada.

A diferença entre as duas é o que o gancho significa em cada face: na
negativa ele é geometria fixa de projeto; na positiva é correção pontual de
um aperto de apoio, e por isso aparece **onde** o aperto está, não nas duas
pontas por igual.
"""

from __future__ import annotations

from dataclasses import dataclass

from .materiais import Aco, Concreto

#: Fator alfa do item 9.4.2.5: 1,0 na barra reta tracionada e 0,7 quando ela
#: termina em gancho com cobrimento no plano normal ao gancho maior que 3 Ø.
ALFA_RETA = 1.0
ALFA_GANCHO = 0.7

#: Ponta reta mínima do gancho a 90°, em bitolas (9.4.2.3). Abaixo disso a
#: dobra não é um gancho: é uma barra torta que não ancora nada.
PONTA_MINIMA_GANCHO = 8.0


def eta_2(phi_mm: float) -> float:
    """Coeficiente de bitola do item 9.3.2.1: 1,0 até Ø32."""
    return 1.0 if phi_mm <= 32.0 else (132.0 - phi_mm) / 100.0


def fbd(concreto: Concreto, aco: Aco, phi_mm: float,
        boa_aderencia: bool = True) -> float:
    """Resistência de aderência de cálculo, kN/cm² (9.3.2.1).

    ``fbd = eta_1 . eta_2 . eta_3 . fctd``, com eta_3 = 1,0 na laje, porque a
    bitola é sempre menor que 32 mm. A situação de aderência é boa: a barra
    da laje é horizontal e fica na região comprimida da concretagem.
    """
    eta1 = aco.eta_1
    eta3 = 1.0
    ancora = 1.0 if boa_aderencia else 0.7
    return ancora * eta1 * eta_2(phi_mm) * eta3 * concreto.fctd_kNcm2


def lb(concreto: Concreto, aco: Aco, phi_mm: float) -> float:
    """Comprimento de ancoragem básico, cm (9.4.2.4): ``phi/4 . fyd/fbd``,
    nunca menos que ``25 phi`` (R13: o piso faltava; governa a partir de
    ~C45 em CA-50)."""
    phi = phi_mm / 10.0
    return max(phi / 4.0 * aco.fyd_kNcm2 / fbd(concreto, aco, phi_mm),
               25.0 * phi)


#: Diâmetro do pino de dobramento, em bitolas (Tabela 9.1):
#: ``categoria -> (Ø < 20 mm, Ø >= 20 mm)``.
PINO_DOBRAMENTO = {"CA-25": (4.0, 5.0), "CA-50": (5.0, 8.0),
                   "CA-60": (6.0, 6.0)}

#: Prolongamento mínimo da positiva além do eixo teórico do apoio (20.1), cm.
PROLONGAMENTO_EIXO = 4.0


def raio_dobramento(aco: Aco, phi_mm: float) -> float:
    """Raio interno de curvatura do gancho, cm: metade do pino da Tabela
    9.1."""
    menor, maior = PINO_DOBRAMENTO.get(aco.categoria, (5.0, 8.0))
    return (menor if phi_mm < 20.0 else maior) * phi_mm / 10.0 / 2.0


def minimo_apoio_extremo(aco: Aco, phi_mm: float) -> float:
    """Os dois mínimos de 18.3.2.4.1 além de lb,nec, cm: ``r + 5,5 Ø`` e
    60 mm."""
    return max(raio_dobramento(aco, phi_mm) + 5.5 * phi_mm / 10.0, 6.0)


def lb_minimo(concreto: Concreto, aco: Aco, phi_mm: float,
              com_gancho: bool = False) -> float:
    """``lb,mín = max(0,3 alfa lb ; 10 phi ; 100 mm)`` em cm (9.4.2.5)."""
    alfa = ALFA_GANCHO if com_gancho else ALFA_RETA
    return max(0.3 * alfa * lb(concreto, aco, phi_mm), 10.0 * phi_mm / 10.0,
               10.0)


@dataclass
class ResultadoAncoragem:
    """Ancoragem de uma barra no apoio."""

    rotulo: str
    phi: float
    lb: float = 0.0                 # cm
    lb_nec: float = 0.0             # cm
    lb_min: float = 0.0             # cm
    disponivel: float = 0.0         # cm, reta dentro do apoio
    com_gancho: bool = False
    ponta_gancho: float = 0.0       # cm
    razao_As: float = 1.0
    atende: bool = True
    observacao: str = ""
    #: (R13) o que se ancora no apoio: "extremo" (18.3.2.4-b, força
    #: (aℓ/d)·VSd), "intermediario" (18.3.2.4-c, 10 Ø) ou "vao" (força do
    #: vão inteiro, o critério de antes da R13)
    criterio: str = "vao"
    forca: float = 0.0              # kN/m, a força ancorada no apoio extremo
    #: (R13) quanto a barra passa do eixo teórico do apoio (20.1: >= 4 cm)
    alem_do_eixo: float = 0.0
    atende_eixo: bool = True


def verificar_positiva(rotulo: str, phi_mm: float, As_calc: float,
                       As_ef: float, disponivel: float,
                       ponta_disponivel: float, concreto: Concreto,
                       aco: Aco, minimo: float = 0.0,
                       fixo: float | None = None) -> ResultadoAncoragem:
    """Ancoragem da positiva no apoio: reta quando fecha, gancho quando não.

    Em dois tempos, nesta ordem, porque a ordem **é** a regra:

    1. **reta.** ``disponivel`` é o quanto a barra reta avança dentro do
       apoio respeitando o cobrimento. Se isso cobre ``lb,nec`` com
       ``alfa = 1,0``, acabou: a barra sai reta, sem gancho, que é como a
       positiva da laje deve sair.
    2. **gancho a 90°, só nesta ponta.** Se a reta não fecha (apoio
       estreito, bitola grossa, concreto fraco), dobrar a ponta é o remédio
       da própria norma: o ``alfa`` cai a 0,7 (9.4.2.5) e a ponta do gancho
       soma ao trecho reto. A outra extremidade da barra continua reta se lá
       a reta fechar -- o gancho aparece onde está o aperto, e não nas duas
       pontas por simetria.

    ``ponta_disponivel`` é o quanto de gancho cabe entre as duas faces da
    laje (``h - 2c``). Abaixo de ``8 Ø`` (9.4.2.3) não existe gancho a 90°
    executável: nesse caso o programa **não** desenha um gancho de mentira
    -- avisa que a laje é fina demais para socorrer aquela bitola, e a barra
    fica reta e reprovada, para a decisão voltar para o projetista.

    ``minimo`` (cm) soma os mínimos de 18.3.2.4.1 no apoio extremo
    (``r + 5,5 Ø`` e 60 mm); ``fixo`` (cm) substitui o cálculo pelo
    comprimento que a norma aceita no apoio intermediário (10 Ø, 18.3.2.4-c).
    """
    res = ResultadoAncoragem(rotulo=rotulo, phi=phi_mm, disponivel=disponivel)
    res.razao_As = min(1.0, As_calc / As_ef) if As_ef > 0.0 else 1.0
    res.lb = lb(concreto, aco, phi_mm)

    # -- 1. reta, que é a regra ---------------------------------------------
    lb_min_reta = lb_minimo(concreto, aco, phi_mm)
    lb_nec_reta = max(ALFA_RETA * res.lb * res.razao_As, lb_min_reta,
                      minimo)
    if fixo is not None:
        lb_min_reta = lb_nec_reta = fixo
    if disponivel >= lb_nec_reta - 1e-9:
        res.lb_min, res.lb_nec = lb_min_reta, lb_nec_reta
        res.atende = True
        res.observacao = (f"trecho reto de {disponivel:.1f} cm dentro do "
                          f"apoio cobre lb,nec = {res.lb_nec:.1f} cm, sem "
                          f"gancho")
        return res

    # -- 2. não fechou reta: dobra a ponta a 90° nesta extremidade ----------
    res.lb_min = lb_minimo(concreto, aco, phi_mm, com_gancho=True)
    res.lb_nec = max(ALFA_GANCHO * res.lb * res.razao_As, res.lb_min,
                     minimo)
    if fixo is not None:
        res.lb_min = res.lb_nec = fixo
    ponta_minima = PONTA_MINIMA_GANCHO * phi_mm / 10.0
    if ponta_disponivel < ponta_minima - 1e-9:
        res.atende = False
        res.observacao = (
            f"o trecho reto de {disponivel:.1f} cm não cobre lb,nec = "
            f"{lb_nec_reta:.1f} cm da barra reta, e o gancho a 90° exigiria "
            f"ponta de 8 Ø = {ponta_minima:.1f} cm, mais do que os "
            f"{ponta_disponivel:.1f} cm que cabem entre as duas faces "
            f"(h - 2c): engrosse a laje, alargue o apoio ou reduza a bitola")
        return res

    res.com_gancho = True
    res.ponta_gancho = ponta_disponivel
    res.atende = disponivel + ponta_disponivel >= res.lb_nec - 1e-9
    if res.atende:
        res.observacao = (
            f"o trecho reto de {disponivel:.1f} cm não cobria lb,nec = "
            f"{lb_nec_reta:.1f} cm da barra reta, então esta ponta leva "
            f"gancho a 90° de {ponta_disponivel:.1f} cm (h - 2c): com "
            f"alfa = 0,7, reto + gancho cobrem lb,nec = {res.lb_nec:.1f} cm")
    else:
        res.observacao = (
            f"nem o trecho reto de {disponivel:.1f} cm somado ao gancho a "
            f"90° de {ponta_disponivel:.1f} cm (h - 2c) fecha lb,nec = "
            f"{res.lb_nec:.1f} cm: alargue o apoio, reduza a bitola ou "
            f"aumente o fck")
    return res


def verificar_com_gancho_fixo(rotulo: str, phi_mm: float, As_calc: float,
                              As_ef: float, disponivel: float,
                              ponta_gancho: float, concreto: Concreto,
                              aco: Aco) -> ResultadoAncoragem:
    """Confere a ancoragem da negativa, que sempre termina em gancho a 90°.

    ``ponta_gancho`` é a espessura da laje menos os dois cobrimentos -- o
    tanto que cabe de gancho sem aflorar em nenhuma das duas faces --, e não
    é escolhida para fechar ``lb,nec``: ela é a regra construtiva fixa. O
    que este cálculo decide é só se ela, somada ao trecho reto disponível,
    fecha a ancoragem exigida (9.4.2.5, alfa = 0,7 do gancho), e avisa
    quando não fecha -- sem mudar a ponta do gancho para compensar.
    """
    res = ResultadoAncoragem(rotulo=rotulo, phi=phi_mm, disponivel=disponivel,
                             com_gancho=True, ponta_gancho=ponta_gancho)
    res.razao_As = min(1.0, As_calc / As_ef) if As_ef > 0.0 else 1.0
    res.lb = lb(concreto, aco, phi_mm)
    res.lb_min = lb_minimo(concreto, aco, phi_mm, com_gancho=True)
    res.lb_nec = max(ALFA_GANCHO * res.lb * res.razao_As, res.lb_min)
    res.atende = disponivel + ponta_gancho >= res.lb_nec - 1e-9
    if res.atende:
        res.observacao = (
            f"trecho reto de {disponivel:.1f} cm + gancho de "
            f"{ponta_gancho:.1f} cm (h - 2c) cobrem lb,nec = "
            f"{res.lb_nec:.1f} cm")
    else:
        res.observacao = (
            f"nem o trecho reto de {disponivel:.1f} cm somado ao gancho de "
            f"{ponta_gancho:.1f} cm (h - 2c) fecha lb,nec = "
            f"{res.lb_nec:.1f} cm -- laje fina demais ou apoio estreito "
            f"demais para esta bitola")
    return res
