# -*- coding: utf-8 -*-
"""
portico3d
Solver matricial de pórticos espaciais.

Uso típico:

    from portico3d import Modelo, Secao, resolver

    m = Modelo("exemplo")
    m.add_material("aco", 210e6, 0.3)
    m.add_secao(Secao.retangular("S", 0.20, 0.50))
    m.add_no("A", 0.0, 0.0, 0.0)
    m.add_no("B", 6.0, 0.0, 0.0)
    m.add_barra("V1", "A", "B", "aco", "S")
    m.apoiar("A")
    caso = m.add_caso("G")
    caso.distribuida("V1", qz=-20.0)

    r = resolver(m, "G")
    print(r.resumo())
"""

from .core.modelo import (Apoio, Barra, CargaDistribuida, CargaNodal,
                          CasoDeCarga, ErroDeModelo, Material, Modelo, No,
                          Secao)
from .core.montagem import resolver
from .core.resultados import Diagrama, Resultado

__all__ = ["Apoio", "Barra", "CargaDistribuida", "CargaNodal", "CasoDeCarga",
           "Diagrama", "ErroDeModelo", "Material", "Modelo", "No", "Resultado",
           "Secao", "resolver"]

#: A revisão, como nos demais programas da pasta: é ela que nomeia o
#: pacote de distribuição.
__version__ = "R03"
