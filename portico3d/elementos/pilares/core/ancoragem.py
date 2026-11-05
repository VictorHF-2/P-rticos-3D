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
from .materiais import (ALFA_0T_PILAR, comprimento_espera,
                        comprimento_traspasse_tracao, f_bd, lb_basico,
                        lb_necessario)
from .modelo import Pilar
from .formato import num


@dataclass
class Ancoragem:
    """Comprimentos de ancoragem e de espera do lance."""

    phi: float = 0.0             # mm
    fbd: float = 0.0             # kN/cm²
    lb: float = 0.0              # cm, comprimento básico
    lb_nec: float = 0.0          # cm, com a relação As,calc/As,ef
    #: Comprimento de espera **adotado**, cm: o l0c da barra comprimida ou,
    #: com ``tracionada``, o l0t da tracionada. É o que entra no quantitativo
    #: e nos desenhos.
    l0c: float = 0.0
    l0c_min: float = 0.0         # cm, o piso do comprimento adotado
    boa_aderencia: bool = True
    As_calc: float = 0.0
    As_efet: float = 0.0
    #: Alguma barra fica tracionada em alguma solicitação de cálculo -- e a
    #: emenda de todas passa a ser a de barra tracionada (9.5.2.2.1).
    tracionada: bool = False
    alfa_0t: float = 0.0
    l0c_compressao: float = 0.0  # cm, o que valeria com todas comprimidas
    motivo: str = ""             # onde a tração apareceu
    avisos: list[str] = field(default_factory=list)

    @property
    def simbolo(self) -> str:
        return "l0t" if self.tracionada else "l0c"

    @property
    def item(self) -> str:
        return "9.5.2.2.1" if self.tracionada else "9.5.2.3"

    @property
    def regra(self) -> str:
        if self.tracionada:
            return (f"l0t = α0t lb,nec >= max(0,3 α0t lb; 15 ø; 20 cm), "
                    f"α0t = {num(self.alfa_0t, 1)}")
        return "l0c = lb As,calc/As,ef >= max(0,6 lb; 15 ø; 20 cm)"


def analisar(pilar: Pilar, phi: float, As_calc: float,
             As_efet: float, tracionada: bool = False,
             motivo: str = "") -> Ancoragem:
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
    l0c_comp = comprimento_espera(lb, As_calc, As_efet, phi)
    l0c, l0c_min = l0c_comp, max(0.6 * lb, 15.0 * phi / 10.0, 20.0)
    alfa = 0.0

    if tracionada:
        # Critério de projeto: basta uma barra tracionada em uma solicitação
        # para **todas** as barras do pilar levarem a emenda de tração -- um
        # comprimento só por lance, para a obra não emendar a barra errada
        # com o comprimento menor.
        alfa = ALFA_0T_PILAR
        l0c, l0c_min = comprimento_traspasse_tracao(lb, lb_nec, phi, alfa)
        avisos.append(av.construtivo(
            f"Emenda por traspasse de barras **tracionadas** (item "
            f"9.5.2.2.1): {motivo or 'há barra tracionada no ELU'}. Por "
            f"critério de projeto, o comprimento vale para **todas** as "
            f"barras do pilar: l0t = α0t lb,nec = {num(alfa, 1)} × "
            f"{num(lb_nec, 0)} = {num(l0c, 0)} cm (piso {num(l0c_min, 0)} cm), "
            f"com α0t da Tabela 9.4 para mais de 50 % das barras emendadas "
            f"na mesma seção. Com todas comprimidas seria l0c = "
            f"{num(l0c_comp, 0)} cm."))
    else:
        avisos.append(av.construtivo(
            f"Comprimento de espera l0c = {num(l0c, 0)} cm, medido a partir da face "
            f"superior do lance (item 9.5.2.3). O piso é o maior entre 0,6 lb, "
            f"15 ø e 20 cm: {num(l0c_min, 0)} cm. Nenhuma barra fica "
            f"tracionada nas solicitações de cálculo."))
    if phi > 32.0 + 1e-9:
        avisos.append(av.erro(
            f"Barra ø{num(phi)} mm: o item 9.5.2 não admite emenda por "
            f"traspasse acima de ø32 mm. Use luva ou solda, e confira o "
            f"comprimento de espera com o fabricante da emenda."))
    if l0c > pilar.lance.altura / 2.0:
        avisos.append(av.construtivo(
            f"O comprimento de espera ({num(l0c, 0)} cm) passa da metade do lance "
            f"({num(pilar.lance.altura, 0)} cm). Verifique o escalonamento das "
            f"emendas: o item 17.3.5.3.2 conta a sobreposição dentro dos 8 % "
            f"de taxa máxima."))

    return Ancoragem(phi=phi, fbd=f_bd(pilar.concreto, phi, boa), lb=lb,
                     lb_nec=lb_nec, l0c=l0c, l0c_min=l0c_min,
                     boa_aderencia=boa, As_calc=As_calc, As_efet=As_efet,
                     tracionada=tracionada, alfa_0t=alfa,
                     l0c_compressao=l0c_comp, motivo=motivo, avisos=avisos)
