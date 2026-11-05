# -*- coding: utf-8 -*-
"""
woodarmer.py
Momentos de cálculo para armaduras ortogonais a partir do trio de esforços
``(Mx, My, Mxy)`` de uma análise elástica de placa -- o procedimento de Wood
(1968) e Armer (1968), na forma que Parsekian (1996, cap. 2) usa.

A armadura em duas direções ortogonais só resiste a ``Mx`` e ``My``. O momento
volvente ``Mxy`` -- que a análise por linhas de ruptura e as tabelas não
mostram, e que na laje apoiada se concentra nos cantos --, é levado em conta
somando-o, em módulo, a cada direção: são os **momentos equivalentes**

    ``M*x = Mx + K |Mxy|``      ``M*y = My + |Mxy| / K``

com ``K = 1`` no caso comum (o que dá o mínimo de aço total, e coincide com
o critério de Wood e de Leonhardt-Mönnig). A face inferior usa o sinal de
vão (``Mx`` positivo traciona embaixo); a superior usa o sinal trocado. Um
momento equivalente negativo vira zero -- aquela direção não precisa de
armadura naquela face -- e o outro se recalcula pela condição de que a
resultante em 45° continue resistida::

    M*x < 0  ->  M*x = 0 ;  M*y = My + Mxy² / |Mx|

Todos os resultados saem como **módulos** (kN·m/m ≥ 0): quem chama sabe de
que face é cada um.

``Mxyc`` é a parcela do momento volvente que o próprio concreto resiste
(Parsekian, 3.6-3.7): só ``|Mxy| - Mxyc`` entra na soma. É critério da NB-1
(a NBR 6118:2026 não o prescreve) e fica desligado por padrão.
"""

from __future__ import annotations

import math


def volvente_efetivo(mxy: float, mxyc: float = 0.0) -> float:
    """``|Mxy|`` que a armadura precisa resistir, depois de descontar a
    parcela ``mxyc`` do concreto."""
    return max(abs(mxy) - max(mxyc, 0.0), 0.0)


def _face(m1: float, m2: float, t: float, k: float) -> tuple[float, float]:
    """Wood-Armer de uma face, com os momentos já no sinal "positivo =
    precisa de armadura": ``(M*1, M*2)`` em módulo."""
    e1 = m1 + k * t
    e2 = m2 + t / k
    if e1 >= 0.0 and e2 >= 0.0:
        return e1, e2
    if e1 < 0.0 and e2 < 0.0:
        return 0.0, 0.0
    if e1 < 0.0:
        # a direção 1 não pede armadura; a 2 absorve o que sobra do volvente
        return 0.0, max(m2 + t * t / abs(m1), 0.0) if m1 != 0.0 else 0.0
    return max(m1 + t * t / abs(m2), 0.0) if m2 != 0.0 else 0.0, 0.0


def wood_armer(mx: float, my: float, mxy: float, k: float = 1.0,
               mxyc: float = 0.0) -> tuple[float, float, float, float]:
    """``(Mx_inf, My_inf, Mx_sup, My_sup)``: momentos de cálculo das
    armaduras das direções x e y, na face inferior e na superior.

    ``mx``, ``my`` e ``mxy`` saem da análise de placa, com ``mx`` e ``my``
    **positivos quando tracionam a face inferior**; ``k`` é a relação entre
    as parcelas do volvente que vão a cada direção (1 = mínimo de aço);
    ``mxyc`` é o volvente que o concreto resiste.
    """
    if k <= 0.0:
        raise ValueError("K precisa ser positivo.")
    t = volvente_efetivo(mxy, mxyc)
    inf = _face(mx, my, t, k)
    sup = _face(-mx, -my, t, k)
    return inf[0], inf[1], sup[0], sup[1]


def mxyc_nb1(h_cm: float, d_cm: float, fck: float, cortante: float = 0.0,
             c_distribuida: float = 1.0) -> float:
    """Momento volvente que o concreto resiste, kN·m/m, pelo critério de
    Parsekian (3.6-3.7) com a ``τwu1`` da NB-1 / NBR 7197.

    ``τwu1 = (0,06 + 0,08 C) α k √fck`` em MPa, com ``α = 1,06`` (ρ1 =
    0,12 %), ``k = 1,6 - d`` (d em m, k ≥ 1) e ``C`` a parcela do cortante
    que vem de carga distribuída (1 para laje só com carga distribuída); no
    máximo 4,5 MPa. Com a interação circular entre cortante e torção
    (``(τwd/τwu1)² + (τtd/τwu1)² ≤ 1``) e a seção de laje (``Wt = h²/3`` por
    metro), ::

        Mxyc = (h² / 3) sqrt(τwu1² - τwd²),    τwd = V / d

    ``cortante`` é o ``V`` de cálculo do ponto, kN/m. Aqui o resultado já é
    de cálculo -- a conversão para valor característico que o texto de
    Parsekian faz (divisão por 1,4) não se aplica quando se compara com o
    ``Mxy`` de cálculo.
    """
    d_m, h_m = d_cm / 100.0, h_cm / 100.0
    k = max(1.6 - d_m, 1.0)
    tau_wu1 = min((0.06 + 0.08 * c_distribuida) * 1.06 * k
                  * math.sqrt(max(fck, 0.0)), 4.5)             # MPa
    tau_wd = abs(cortante) / d_m / 1000.0 if d_m > 0.0 else 0.0   # MPa
    radicando = tau_wu1 ** 2 - tau_wd ** 2
    if radicando <= 0.0:
        return 0.0
    # MPa x m² -> MN·m/m -> kN·m/m
    return h_m ** 2 / 3.0 * math.sqrt(radicando) * 1000.0
