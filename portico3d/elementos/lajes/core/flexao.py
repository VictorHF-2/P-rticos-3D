# -*- coding: utf-8 -*-
"""
flexao.py
Dimensionamento à flexão simples da faixa de 1 m de laje, pelo diagrama
retangular equivalente do item 17.2.2 da NBR 6118.

A laje é sempre uma seção retangular de ``b = 100 cm``, armadura simples, e
por isso o problema fecha em forma explícita (apostila §1.8):

    x = (d / lambda) . [1 - raiz(1 - 2 md / (alfa_c fcd b d²))]
    As = alfa_c . lambda . fcd . b . x / fyd

O limite de ``x/d`` que vale aqui **não** é o do domínio 3/4 das vigas: como
os momentos vêm do regime rígido-plástico, o item 14.6.4.3 exige a
ductilidade reforçada de ``x/d <= 0,25`` até C50 (§1.7). É um limite bem mais
severo, e é comum ser ele -- e não a resistência -- que obriga a engrossar a
laje.

As armaduras mínimas seguem a tabela do §1.8, que não é uma taxa só: a
negativa de continuidade pede ``rho_mín`` cheio, a negativa de borda sem
continuidade e a positiva da laje armada em cruz pedem ``0,67 rho_mín``, e a
de distribuição pede ``0,5 rho_mín`` com um piso absoluto de 0,9 cm²/m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .materiais import Aco, Ambiente, Concreto, interpola_rho_min

#: Fatores da tabela de armadura mínima (§1.8).
FATOR_MINIMA = {
    "negativa": 1.00,               # armadura negativa de continuidade
    "negativa de borda": 0.67,      # borda sem continuidade
    "positiva em cruz": 0.67,       # positiva de laje armada em duas direções
    "positiva principal": 1.00,     # principal da laje armada em uma direção
    "distribuicao": 0.50,           # armadura de distribuição
}

#: Piso absoluto da armadura de distribuição, cm²/m (§1.8).
MINIMA_DISTRIBUICAO = 0.9

#: Fração mínima da armadura principal que a de distribuição deve ter (20.1).
FRACAO_DISTRIBUICAO = 0.20


@dataclass
class ResultadoFlexao:
    """Dimensionamento de uma seção de laje à flexão."""

    rotulo: str                     # "vão a", "bordo 2", ...
    md: float                       # kN·m/m, momento de cálculo
    h: float                        # cm
    d: float                        # cm, altura útil
    cobrimento: float               # cm
    x: float = 0.0                  # cm, linha neutra
    x_sobre_d: float = 0.0
    x_sobre_d_limite: float = 0.25
    As_calculada: float = 0.0       # cm²/m
    As_minima: float = 0.0          # cm²/m
    As: float = 0.0                 # cm²/m, a adotada = max das duas
    rho_min: float = 0.0            # %
    tipo_minima: str = ""
    md_minimo: float = 0.0          # kN·m/m, do 0,8 W0 fctk,sup
    governa: str = ""               # "cálculo" ou "mínima"
    erro: str = ""

    @property
    def taxa(self) -> float:
        """Taxa geométrica de armadura, % da seção bruta."""
        return self.As / (100.0 * self.h) * 100.0

    @property
    def ductil(self) -> bool:
        return not self.erro and self.x_sobre_d <= self.x_sobre_d_limite + 1e-9


def altura_util(h: float, cobrimento: float, face: str,
                direcao_inferior: bool = True) -> float:
    """Altura útil da faixa, cm.

    Na face inferior há duas armaduras cruzadas, e a do **menor vão** vai por
    baixo -- ela é a mais solicitada e ganha o braço maior. A apostila §3.3
    resolve isso admitindo ``da = h - c - 0,5`` para a direção ``a`` e
    ``db = h - c - 1,0`` para a direção ``b``, uma diferença de meio
    centímetro que é a bitola de laje típica.

    Na face superior as duas negativas também se cruzam, mas cada uma governa
    numa borda diferente; ali vale ``d = h - c - 0,5`` para as duas.
    """
    folga = 0.5 if (face == "superior" or direcao_inferior) else 1.0
    return h - cobrimento - folga


def momento_minimo(concreto: Concreto, h: float) -> float:
    """``Md,mín = 0,8 W0 fctk,sup`` da faixa de 1 m, em kN·m/m (17.3.5.2.1).

    ``W0`` é o módulo resistente da seção bruta relativo à fibra mais
    tracionada: ``b h² / 6``.
    """
    w0 = 100.0 * h ** 2 / 6.0                       # cm³/m
    return 0.8 * w0 * concreto.fctk_sup / 10.0 / 100.0      # kN·m/m


def armadura_minima(concreto: Concreto, h: float, tipo: str) -> float:
    """Armadura mínima da faixa de 1 m, cm²/m, pela tabela do §1.8."""
    rho = interpola_rho_min(concreto.fck)           # %
    fator = FATOR_MINIMA[tipo]
    minima = fator * rho / 100.0 * 100.0 * h        # cm²/m
    if tipo == "distribuicao":
        minima = max(minima, MINIMA_DISTRIBUICAO)
    return minima


def dimensionar_secao(md: float, h: float, d: float, cobrimento: float,
                      concreto: Concreto, aco: Aco, tipo_minima: str,
                      rotulo: str = "", limite_xd: float | None = None
                      ) -> ResultadoFlexao:
    """Armadura de flexão da faixa de 1 m, para o momento de cálculo dado.

    ``md`` em kN·m/m e sempre em módulo -- quem chama sabe de que face é a
    armadura. Devolve o resultado com a armadura adotada já confrontada com o
    mínimo do tipo pedido.
    """
    res = ResultadoFlexao(rotulo=rotulo, md=abs(md), h=h, d=d,
                          cobrimento=cobrimento, tipo_minima=tipo_minima,
                          rho_min=interpola_rho_min(concreto.fck),
                          x_sobre_d_limite=(
                              concreto.x_sobre_d_limite if limite_xd is None
                              else limite_xd))
    res.As_minima = armadura_minima(concreto, h, tipo_minima)
    res.md_minimo = momento_minimo(concreto, h)

    b = 100.0
    sigma = concreto.sigma_cd                       # kN/cm²
    lam = concreto.lambda_
    md_kNcm = res.md * 100.0                        # kN·cm/m

    if d <= 0.0:
        res.erro = (f"a altura útil ficou {d:.1f} cm: o cobrimento não cabe "
                    f"na espessura de {h:g} cm")
        res.As = res.As_minima
        res.governa = "mínima"
        return res

    if md_kNcm > 1e-9:
        radicando = 1.0 - 2.0 * md_kNcm / (sigma * b * d ** 2)
        if radicando < 0.0:
            res.erro = (f"a seção de {h:g} cm não resiste a "
                        f"{res.md:.2f} kN·m/m com armadura simples: seria "
                        f"preciso engrossar a laje")
            res.x = d
            res.x_sobre_d = 1.0
            res.As = res.As_minima
            res.governa = "mínima"
            return res
        res.x = d * (1.0 - math.sqrt(radicando)) / lam
        res.x_sobre_d = res.x / d
        res.As_calculada = sigma * lam * b * res.x / aco.fyd_kNcm2

    if res.x_sobre_d > res.x_sobre_d_limite + 1e-9:
        regime = ("em regime rígido-plástico" if limite_xd is None
                  else "por análise elástica (com a redistribuição "
                       "adotada)")
        res.erro = (f"x/d = {res.x_sobre_d:.3f} passa do limite de "
                    f"{res.x_sobre_d_limite:.2f} que o item 14.6.4.3 impõe "
                    f"a quem determina as solicitações {regime}: engrosse "
                    f"a laje")

    if res.As_calculada >= res.As_minima:
        res.As = res.As_calculada
        res.governa = "cálculo"
    else:
        res.As = res.As_minima
        res.governa = "mínima"
    return res


def armadura_distribuicao(As_principal: float, concreto: Concreto, h: float,
                          bw_cm: float = 100.0,
                          b_parede_cm: float = 0.0) -> tuple[float, str]:
    """Armadura de distribuição da laje armada em uma direção, cm²/m.

    São três pisos simultâneos (§1.8 e 20.1): um quinto da armadura
    principal, metade da mínima e 0,9 cm²/m. Quando a faixa carrega parede
    paralela ao vão entra um quarto critério, o (III) do §2.1:

        As,distr / s >= 0,8 . (1 - b/bw) . As,princ / s

    -- a faixa carregada precisa distribuir transversalmente a carga da
    parede, e quanto mais estreita for a difusão ``b`` diante de ``bw``, mais
    armadura transversal ela pede.
    """
    minima = armadura_minima(concreto, h, "distribuicao")
    candidatos = [
        (FRACAO_DISTRIBUICAO * As_principal, "1/5 da armadura principal"),
        (minima, "0,5 rho_mín com piso de 0,9 cm²/m"),
    ]
    if bw_cm > 0.0 and b_parede_cm > 0.0:
        fator = max(0.0, 1.0 - b_parede_cm / bw_cm)
        candidatos.append((0.8 * fator * As_principal,
                           f"critério (III) do §2.1: 0,8 (1 - b/bw) As,princ "
                           f"com b/bw = {b_parede_cm / bw_cm:.2f}"))
    valor, motivo = max(candidatos, key=lambda x: x[0])
    return valor, motivo


def armadura_contorno(concreto: Concreto, h: float,
                      a_menor: float) -> tuple[float, float]:
    """Armadura de contorno do apoio de borda de piso (§3.3).

    Onde a laje termina, o apoio não é a rótula perfeita que o cálculo supôs:
    a viga tem alguma rigidez à torção e aparece momento negativo. A apostila
    manda uma armadura de ``0,67 rho_mín``, nunca menor que Ø5 c/20 cm
    (1,0 cm²/m), estendida por um quinto do vão menor da laje.

    Devolve ``(As em cm²/m, comprimento de cada lado em cm)``.
    """
    As = max(armadura_minima(concreto, h, "negativa de borda"), 1.0)
    return As, 0.20 * a_menor * 100.0


def verificar_bitola_maxima(phi_mm: float, h: float) -> str:
    """Item 20.1: a barra de flexão da laje tem bitola de no máximo h/8."""
    limite = h / 8.0 * 10.0                         # mm
    if phi_mm > limite + 1e-9:
        return (f"a bitola Ø{phi_mm:g} mm passa do máximo de h/8 = "
                f"{limite:.1f} mm do item 20.1")
    return ""


def cobrimentos(ambiente: Ambiente, phi_mm: float = 0.0) -> tuple[float,
                                                                  float]:
    """Cobrimento das faces inferior e superior da laje, cm."""
    return ambiente.cobrimento_nominal, ambiente.cobrimento_superior(phi_mm)
