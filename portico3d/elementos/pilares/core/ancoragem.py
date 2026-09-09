# -*- coding: utf-8 -*-
"""
ancoragem.py
Comprimento de ancoragem básico, comprimento de espera e emenda por traspasse
das barras longitudinais do pilar.

Base normativa: itens 9.3.2.1 (aderência), 9.4.2.4 e 9.4.2.5 (ancoragem) e
9.5.2.3 (emenda por traspasse de barras comprimidas e comprimento de espera).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import avisos as av
from .materiais import (comprimento_espera, f_bd, lb_basico, lb_necessario)
from .modelo import Pilar


@dataclass
class Ancoragem:
    """Comprimentos de ancoragem e de espera do lance."""

    phi: float = 0.0             # mm
    fbd: float = 0.0             # kN/cm²
    lb: float = 0.0              # cm, comprimento básico
    lb_nec: float = 0.0          # cm, com a relação As,calc/As,ef
    l0c: float = 0.0             # cm, comprimento de espera
    l0c_min: float = 0.0         # cm
    boa_aderencia: bool = True
    As_calc: float = 0.0
    As_efet: float = 0.0
    avisos: list[str] = field(default_factory=list)


def analisar(pilar: Pilar, phi: float, As_calc: float,
             As_efet: float) -> Ancoragem:
    """Ancoragem e comprimento de espera para a bitola e a armadura dadas.

    A situação de aderência é tomada como **boa**: em pilar a barra é
    vertical e a concretagem também, o que satisfaz o item 9.3.1 enquanto o
    lançamento respeitar as alturas usuais de camada. Onde isso não vale --
    arranque saindo de bloco concretado em uma etapa alta, por exemplo -- o
    critério do modelo permite declarar má aderência, e ``fbd`` cai a 70 %.
    """
    avisos: list[str] = []
    boa = True
    lb = lb_basico(pilar.concreto, pilar.aco, phi, boa)
    lb_nec = lb_necessario(lb, As_calc, As_efet, phi)
    l0c = comprimento_espera(lb, As_calc, As_efet, phi)
    l0c_min = max(0.6 * lb, 15.0 * phi / 10.0, 20.0)

    avisos.append(av.construtivo(
        f"Comprimento de espera l0c = {l0c:.0f} cm, medido a partir da face "
        f"superior do lance (item 9.5.2.3). O piso é o maior entre 0,6 lb, "
        f"15 ø e 20 cm: {l0c_min:.0f} cm."))
    if l0c > pilar.lance.altura / 2.0:
        avisos.append(av.construtivo(
            f"O comprimento de espera ({l0c:.0f} cm) passa da metade do lance "
            f"({pilar.lance.altura:.0f} cm). Verifique o escalonamento das "
            f"emendas: o item 17.3.5.3.2 conta a sobreposição dentro dos 8 % "
            f"de taxa máxima."))

    return Ancoragem(phi=phi, fbd=f_bd(pilar.concreto, phi, boa), lb=lb,
                     lb_nec=lb_nec, l0c=l0c, l0c_min=l0c_min,
                     boa_aderencia=boa, As_calc=As_calc, As_efet=As_efet,
                     avisos=avisos)
