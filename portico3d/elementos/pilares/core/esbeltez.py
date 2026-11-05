# -*- coding: utf-8 -*-
"""
esbeltez.py
Índice de esbeltez, esbeltez limite e o coeficiente ``alfa_b`` do item 15.8.2
da NBR 6118, em cada uma das duas direções principais.

É este módulo que decide **se** a segunda ordem local precisa ser considerada;
quem a calcula é :mod:`pilares.core.segunda_ordem`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import avisos as av
from .materiais import (ESBELTEZ_FLUENCIA, ESBELTEZ_MAXIMA,
                        ESBELTEZ_METODO_EXATO, gamma_n1)
from .modelo import Pilar
from .formato import num

#: Limites do item 15.8.2 para a esbeltez limite.
LAMBDA_1_MINIMO = 35.0
LAMBDA_1_MAXIMO = 90.0


@dataclass
class Esbeltez:
    """Resultado da análise de esbeltez numa direção."""

    direcao: str                 # "x" ou "y"
    h: float                     # cm, altura da seção nessa direção
    i: float                     # cm, raio de giração
    le: float                    # cm, comprimento equivalente
    lam: float                   # índice de esbeltez
    lam_1: float                 # esbeltez limite
    alfa_b: float
    vinculo: int
    e1: float                    # cm, excentricidade de 1ª ordem (M1d,A/Nd)
    e1_min: float                # cm, excentricidade mínima do item 11.3.3.4.3
    M1d_A: float                 # kN·cm
    M1d_B: float                 # kN·cm
    M1d_min: float               # kN·cm
    gamma_n1: float = 1.0
    #: sentido físico de M1d,A (+1/-1); ``e1`` e ``M1d_A`` são em módulo
    sinal_A: float = 1.0
    #: 2ª ordem imposta pelo critério de projeto (``Config.sempre_2a_ordem``)
    imposta: bool = False
    avisos: list[str] = field(default_factory=list)

    @property
    def considerar_2a_ordem(self) -> bool:
        """A segunda ordem local entra nesta direção: obrigatória pelo item
        15.8.2 (lambda > lambda_1) ou imposta pelo critério de projeto."""
        return self.lam > self.lam_1 or self.imposta

    @property
    def fluencia_obrigatoria(self) -> bool:
        return self.lam > ESBELTEZ_FLUENCIA

    @property
    def metodo_exato_obrigatorio(self) -> bool:
        return self.lam > ESBELTEZ_METODO_EXATO

    @property
    def veredito(self) -> str:
        if self.lam <= self.lam_1 and self.imposta:
            return "Considerar 2ª ordem (imposta pelo projetista)"
        return ("Considerar 2ª ordem" if self.considerar_2a_ordem
                else "2ª ordem é desprezível")


def excentricidade_minima(h: float) -> float:
    """Excentricidade mínima de primeira ordem, cm (item 11.3.3.4.3).

    ``e1,min = 1,5 + 0,03 h``, com ``h`` em cm na direção considerada. Não é
    excentricidade acidental nem imperfeição geométrica: é o piso do momento
    de primeira ordem, e por isso entra comparado com ``e1``, e não somado.
    """
    return 1.5 + 0.03 * h


def alfa_b(vinculo: int, M1d_A: float, M1d_B: float, M1d_min: float,
           M1d_C: float = 0.0, regra_minimo: bool = True
           ) -> tuple[float, str, list[str]]:
    """Coeficiente ``alfa_b`` do item 15.8.2, com a justificativa e os avisos.

    Os três casos da norma:

    ``biapoiado sem cargas transversais``
        ``alfa_b = 0,60 + 0,40 MB/MA >= 0,40``. O sinal de ``MB`` já vem
        resolvido pelo modelo: positivo quando traciona a mesma face que
        ``MA``, negativo em caso contrário -- ou seja, curvatura reversa dá
        ``alfa_b`` menor, o que é o efeito físico esperado.

    ``biapoiado com cargas transversais``
        ``alfa_b = 1,0``, porque o diagrama de primeira ordem já tem o máximo
        no meio do vão, onde a segunda ordem também é máxima.

    ``em balanço``
        ``alfa_b = 1,0``, sem depender de ``MC``. **Mudou na edição de
        2026**: a NBR 6118:2014 dava ``alfa_b = 0,80 + 0,20 MC/MA >= 0,85``
        para este caso, e o item 15.8.2-c) de 2026 passou a fixar 1,0. Como
        1,0 é o teto do intervalo antigo, a redação nova é mais conservadora
        -- amplia mais a segunda ordem --, e o programa segue a 2026. ``MC``
        continua sendo lido da entrada porque ainda documenta o diagrama do
        lance, mas não entra mais no ``alfa_b``.

    E a regra que atravessa os três, item 15.8.2-d): se o momento de primeira
    ordem for menor que o mínimo do item 11.3.3.4.3, ``alfa_b = 1,0``.
    ``regra_minimo`` a desliga -- o PCalc não a aplica, e desligá-la é o que
    reproduz o resultado dele, ao custo de sair da alínea d).
    """
    avisos: list[str] = []
    if regra_minimo and abs(M1d_A) < abs(M1d_min) - 1e-9:
        return 1.0, "momento de 1ª ordem abaixo do mínimo (15.8.2-d)", avisos
    if vinculo == 2:
        return 1.0, "biapoiado com cargas transversais", avisos
    if vinculo == 3:
        return 1.0, "em balanço (item 15.8.2-c da NBR 6118:2026)", avisos
    if abs(M1d_A) < 1e-9:
        return 1.0, "momento de 1ª ordem nulo", avisos
    valor = max(0.60 + 0.40 * M1d_B / M1d_A, 0.40)
    return min(valor, 1.0), "biapoiado sem cargas transversais", avisos


def esbeltez_limite(e1: float, h: float, ab: float) -> tuple[float, list[str]]:
    """Esbeltez limite ``lambda_1`` do item 15.8.2, já truncada em [35, 90].

    A expressão é ``(25 + 12,5 e1/h)/alfa_b``, e a norma acrescenta que
    ``35 <= lambda_1 <= 90``. O truncamento no teto merece nota: acima de 90
    o pilar precisaria de fluência obrigatória de qualquer modo (item
    15.8.4), e deixar ``lambda_1`` crescer livremente dispensaria a segunda
    ordem justamente onde ela mais importa.
    """
    avisos: list[str] = []
    bruto = (25.0 + 12.5 * e1 / h) / ab if h > 0 else LAMBDA_1_MINIMO
    valor = min(max(bruto, LAMBDA_1_MINIMO), LAMBDA_1_MAXIMO)
    if bruto > LAMBDA_1_MAXIMO:
        avisos.append(av.construtivo(
            f"Esbeltez limite calculada em {num(bruto, 1)}, acima do teto de "
            f"{num(LAMBDA_1_MAXIMO)} do item 15.8.2; adotado o teto. A "
            f"excentricidade relativa e1/h = {num(e1 / h, 2)} é o que a empurra "
            f"para cima."))
    return valor, avisos


def pilar_pouco_comprimido(pilar: Pilar) -> bool:
    """Elemento pouco comprimido do item 15.8.1: ``Nd < 0,10 fcd Ac`` -- o
    único caso em que a norma admite lambda > 200 (tração inclusa)."""
    Ac = pilar.secao.propriedades().area
    return pilar.Nd < 0.10 * pilar.concreto.fcd_kNcm2 * Ac


def analisar(pilar: Pilar, direcao: str) -> Esbeltez:
    """Análise de esbeltez do pilar numa direção."""
    avisos: list[str] = []
    prop = pilar.secao.propriedades()
    h = pilar.secao.altura(direcao)
    i = prop.ix if direcao == "x" else prop.iy
    le = pilar.le(direcao)
    lam = le / i if i > 0 else float("inf")

    Nd = pilar.Nd
    M1d_A = pilar.M1d_A(direcao)
    M1d_B = pilar.M1d_B(direcao)
    e1 = M1d_A / Nd if abs(Nd) > 1e-9 else 0.0
    e1_min = excentricidade_minima(h)
    M1d_min = abs(Nd) * e1_min

    ab, motivo, av_ab = alfa_b(pilar.lance.vinculo(direcao), M1d_A, M1d_B,
                               M1d_min,
                               pilar.fator_esforcos
                               * pilar.esforcos.meio(direcao),
                               pilar.config.alfa_b_unitario_sob_minimo)
    avisos += av_ab
    lam_1, av_l1 = esbeltez_limite(abs(e1), h, ab)
    avisos += av_l1

    if not prop.simetrica:
        avisos.append(av.construtivo(
            f"A seção {pilar.secao.tipo} tem produto de inércia não nulo "
            f"(Ixy = {num(prop.Ixy, 0)} cm⁴): os eixos x e y não são principais. "
            f"A esbeltez em {direcao} foi calculada com o raio de giração "
            f"desses eixos, que é o que casa com a direção dos momentos de "
            f"entrada, mas a flambagem real se dá segundo os eixos "
            f"principais. Confira se o comprimento equivalente informado "
            f"corresponde a essa direção."))

    metodo = pilar.config.metodo_2a_ordem
    pouco_comprimido = pilar_pouco_comprimido(pilar)
    if lam > ESBELTEZ_MAXIMA and pouco_comprimido:
        avisos.append(av.construtivo(
            f"Esbeltez em {direcao} = {num(lam, 0)}, acima de "
            f"{num(ESBELTEZ_MAXIMA)}: o item 15.8.1 só a admite em elemento pouco "
            f"comprimido, com Nd < 0,10 fcd Ac -- é o caso. O método geral "
            f"continua obrigatório (λ > 140)."))
    if lam > ESBELTEZ_MAXIMA and not pouco_comprimido:
        avisos.append(av.erro(
            f"Esbeltez em {direcao} = {num(lam, 0)}, acima do limite de "
            f"{num(ESBELTEZ_MAXIMA)} do item 15.8.1. A norma só admite o pilar "
            f"se ele for pouco comprimido (Nd < 0,10 fcd Ac), e não é; "
            f"aumente a seção ou reduza o comprimento de flambagem."))
    elif lam > ESBELTEZ_METODO_EXATO and metodo != "geral":
        avisos.append(av.erro(
            f"Esbeltez em {direcao} = {num(lam, 0)}, acima de "
            f"{num(ESBELTEZ_METODO_EXATO)}: o item 15.8.3.2 torna o **método "
            f"geral** obrigatório, com análise não linear de 2ª ordem e "
            f"relação momento-curvatura real. Os métodos do pilar-padrão não "
            f"são permitidos nessa faixa: escolha o método geral nos "
            f"critérios de cálculo. O resultado abaixo é indicativo."))
    elif lam > ESBELTEZ_FLUENCIA and metodo in ("curvatura", "rigidez",
                                                "menor"):
        avisos.append(av.erro(
            f"Esbeltez em {direcao} = {num(lam, 0)}, acima de "
            f"{num(ESBELTEZ_FLUENCIA)}: os métodos do pilar-padrão com "
            f"curvatura e com rigidez aproximadas ficam restritos a "
            f"λ <= 90 (itens 15.8.3.3.2 e 15.8.3.3.3) -- use o "
            f"pilar-padrão acoplado a diagramas M, N, 1/r ou o método "
            f"geral; e o item 15.8.4 torna a **fluência** obrigatória."))

    imposta = pilar.config.sempre_2a_ordem
    if imposta and lam <= lam_1 and Nd > 0.0:
        avisos.append(av.construtivo(
            f"Esbeltez em {direcao} = {num(lam, 1)} <= λ₁ = {num(lam_1, 1)}: o "
            f"item 15.8.2 dispensaria a 2ª ordem, mas o critério de projeto "
            f"manda considerá-la sempre (a favor da segurança)."))

    g1 = gamma_n1(lam) if pilar.config.aplicar_gamma_n1 else 1.0
    if g1 > 1.0:
        avisos.append(av.construtivo(
            f"Esbeltez em {direcao} = {num(lam, 0)} > 140: os efeitos locais de "
            f"2ª ordem foram majorados por γn1 = {num(g1, 3)} (item "
            f"15.8.1)."))

    return Esbeltez(direcao=direcao, h=h, i=i, le=le, lam=lam, lam_1=lam_1,
                    alfa_b=ab, vinculo=pilar.lance.vinculo(direcao), e1=e1,
                    e1_min=e1_min, M1d_A=M1d_A, M1d_B=M1d_B, M1d_min=M1d_min,
                    gamma_n1=g1, sinal_A=pilar.sinal_A(direcao),
                    imposta=imposta, avisos=avisos)


def lambda_retangular(le: float, h: float) -> float:
    """``lambda = 3,46 le/h``, a particularização da seção retangular.

    Existe para conferência e para a memória de cálculo: é a forma em que a
    esbeltez aparece na bibliografia e na planilha de referência. O programa
    calcula ``lambda = le/i`` porque essa vale para qualquer seção, e as duas
    coincidem no retângulo -- ``i = h/sqrt(12)`` e ``sqrt(12) = 3,4641``.
    """
    return math.sqrt(12.0) * le / h if h > 0 else float("inf")
