# -*- coding: utf-8 -*-
"""
edificio_3pav.py
Edifício de três pavimentos para conferir o Pórticos contra os programas de
Vigas, Pilares e Lajes rodados isoladamente (``verificar_contra_programas.py``).

O que ele tem, de propósito:

* vãos variados — em X 4,0 / 5,0 / 3,5 m; em Y 5,0 / 4,0 m;
* vigas de cinco seções — 15×40, 15×45, 20×50, 20×55 e 20×60;
* vigas em balanço — V1 e V2 avançam 1,5 m além da linha D, a V8 fecha as
  pontas, e a laje L7 (sacada) se apoia nelas;
* lajes em balanço — L8 e L9 avançam 1,2 m além da linha 3, engastadas nas
  lajes de dentro (L4 e L5), com a mesma espessura;
* pilares 20×40 (cantos), 20×50 (bordas) e 25×60 (centrais), e vento.

Eixos: colunas A (x = 0), B (4,0), C (9,0), D (12,5); linhas 1 (y = 0),
2 (5,0), 3 (9,0). Pavimentos nas cotas 3, 6 e 9 m, a mesma planta.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROGRAMA = Path(__file__).resolve().parent.parent
if str(PROGRAMA) not in sys.path:
    sys.path.insert(0, str(PROGRAMA))

from portico3d.lancamento import (Lancamento, LajeLancada, Pavimento,  # noqa
                                  PilarLancado, Planta, VentoLancado,
                                  VigaLancada)
from portico3d.lancamento.grelha import nova_grelha  # noqa: E402

XS = (0.0, 4.0, 9.0, 12.5)
YS = (0.0, 5.0, 9.0)
#: ponta das vigas em balanço V1 e V2, e da laje em balanço
X_BALANCO = 14.0
BALANCO_LAJE = 1.2
ESPESSURA = 0.12
G_REVESTIMENTO, Q_PISO, Q_SACADA = 1.5, 2.0, 2.5


def lancamento() -> Lancamento:
    planta = Planta("Tipo")
    # -- pilares: cantos 20×40, bordas 20×50, centrais 25×60. O lado maior
    # vai na direção em que o pilar recebe viga contínua dos dois lados
    secoes = {
        (0, 0): (0.20, 0.40, 0.0), (3, 0): (0.20, 0.40, 0.0),
        (0, 2): (0.20, 0.40, 0.0), (3, 2): (0.20, 0.40, 0.0),
        (1, 0): (0.20, 0.50, 90.0), (2, 0): (0.20, 0.50, 90.0),
        (1, 2): (0.20, 0.50, 90.0), (2, 2): (0.20, 0.50, 90.0),
        (0, 1): (0.20, 0.50, 0.0), (3, 1): (0.20, 0.50, 0.0),
        (1, 1): (0.25, 0.60, 90.0), (2, 1): (0.25, 0.60, 90.0),
    }
    k = 1
    for j, y in enumerate(YS):
        for i, x in enumerate(XS):
            b, h, ang = secoes[(i, j)]
            planta.pilares.append(PilarLancado(f"P{k}", x, y, b, h, ang))
            k += 1

    # -- vigas: cinco seções, duas em balanço
    planta.vigas += [
        VigaLancada("V1", [(0.0, 0.0), (X_BALANCO, 0.0)], 0.20, 0.50),
        VigaLancada("V2", [(0.0, 5.0), (X_BALANCO, 5.0)], 0.20, 0.60),
        VigaLancada("V3", [(0.0, 9.0), (12.5, 9.0)], 0.20, 0.55),
        VigaLancada("V4", [(0.0, 0.0), (0.0, 9.0)], 0.15, 0.45),
        VigaLancada("V5", [(4.0, 0.0), (4.0, 9.0)], 0.20, 0.50),
        VigaLancada("V6", [(9.0, 0.0), (9.0, 9.0)], 0.20, 0.50),
        VigaLancada("V7", [(12.5, 0.0), (12.5, 9.0)], 0.15, 0.45),
        VigaLancada("V8", [(X_BALANCO, 0.0), (X_BALANCO, 5.0)], 0.15, 0.40),
    ]

    # -- lajes: seis internas, a sacada sobre as vigas em balanço e duas em
    # balanço puro na linha 3
    def laje(nome, x, y, q=Q_PISO, **extra):
        return LajeLancada(nome, x, y, ESPESSURA, G_REVESTIMENTO, q, **extra)

    planta.lajes += [
        laje("L1", 2.0, 2.5), laje("L2", 6.5, 2.5), laje("L3", 10.75, 2.5),
        laje("L4", 2.0, 7.0), laje("L5", 6.5, 7.0), laje("L6", 10.75, 7.0),
        laje("L7", 13.25, 2.5, Q_SACADA),
        laje("L8", 2.0, 9.6, Q_SACADA, balanco=BALANCO_LAJE, sentido="+y"),
        laje("L9", 6.5, 9.6, Q_SACADA, balanco=BALANCO_LAJE, sentido="+y"),
    ]

    lanc = Lancamento("edificio 3 pavimentos", fck=30.0,
                      plantas={"Tipo": planta},
                      pavimentos=[Pavimento("1PAV", 3.0, "Tipo"),
                                  Pavimento("2PAV", 6.0, "Tipo"),
                                  Pavimento("COB", 9.0, "Tipo")],
                      vento=VentoLancado(v0=30.0))
    lanc.grelha = nova_grelha(4, 1.0, 3, 1.0)
    lanc.grelha.espacos_colunas = [XS[1] - XS[0], XS[2] - XS[1],
                                   XS[3] - XS[2]]
    lanc.grelha.espacos_linhas = [YS[1] - YS[0], YS[2] - YS[1]]
    return lanc


if __name__ == "__main__":
    from portico3d.lancamento import gerar
    from portico3d.lancamento.arquivo import gravar

    lanc = lancamento()
    g = gerar(lanc)
    print(g.resumo())
    destino = Path(__file__).with_name("edificio-3pav.json")
    gravar(lanc, destino)
    print(f"gravado em {destino}")
