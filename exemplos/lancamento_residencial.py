# -*- coding: utf-8 -*-
"""
lancamento_residencial.py
Um prédio pequeno lançado por planta, do jeito dos programas de edifício.

* planta-tipo com 9 pilares 20×40 numa grade irregular (vãos de 4,0 e 5,0 m
  em X, 5,0 e 3,5 m em Y), usada em dois pavimentos; os das linhas de
  extremidade em X giram 90°, com os 40 cm na direção da viga que termina
  neles;
* uma viga secundária (V7) que nasce na V1 e morre na V2 — apoiada nas duas
  — e divide os painéis da direita; a laje de cima fica com o lado de baixo
  coberto por duas vigas;
* paredes de alvenaria sobre as vigas do contorno;
* cobertura com planta própria: laje treliçada e sem paredes;
* vento da NBR 6123 (V0 = 35 m/s).

Rodar com:

    py exemplos/lancamento_residencial.py
"""

from __future__ import annotations

import os
import sys

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        try:
            _fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from portico3d.lancamento import (Lancamento, LajeLancada, ParedeLancada,
                                  Pavimento, PilarLancado, Planta,
                                  VentoLancado, VigaLancada, gerar)

XS = (0.0, 4.0, 9.0)
YS = (0.0, 5.0, 8.5)


def _estrutura(planta: Planta, laje_trelicada: bool = False) -> Planta:
    k = 0
    for j, y in enumerate(YS):
        for i, x in enumerate(XS):
            k += 1
            # os pilares das extremidades em X ficam com os 40 cm na direção
            # da viga que termina neles — é onde a armadura dela ancora
            planta.pilares.append(PilarLancado(
                f"P{k}", x, y, 0.20, 0.40,
                angulo=90.0 if x in (XS[0], XS[-1]) else 0.0))
    for j, y in enumerate(YS):
        planta.vigas.append(VigaLancada(f"V{j + 1}", [(0.0, y), (9.0, y)],
                                        0.20, 0.45))
    for i, x in enumerate(XS):
        planta.vigas.append(VigaLancada(f"V{4 + i}", [(x, 0.0), (x, 8.5)],
                                        0.20, 0.45))
    planta.vigas.append(VigaLancada("V7", [(6.5, 0.0), (6.5, 5.0)],
                                    0.20, 0.40))
    paineis = [("L1", 2.0, 2.5), ("L2", 5.2, 2.5), ("L3", 7.7, 2.5),
               ("L4", 2.0, 6.7), ("L5", 6.5, 6.7)]
    for nome, x, y in paineis:
        if laje_trelicada:
            planta.lajes.append(LajeLancada(
                nome, x, y, tipo="trelicada", direcao="x",
                altura_enchimento=0.12, capa=0.05, permanente=1.0,
                acidental=0.5))
        else:
            planta.lajes.append(LajeLancada(nome, x, y, espessura=0.10,
                                            tipo_carga="residencial"))
    return planta


def lancamento() -> Lancamento:
    lanc = Lancamento("residencial", fck=30.0,
                      vento=VentoLancado(v0=35.0, categoria="III"))
    lanc.cargas_de_laje["residencial"] = (1.5, 1.5)
    tipo = _estrutura(Planta("Tipo"))
    contorno = [(0.0, 0.0), (9.0, 0.0), (9.0, 8.5), (0.0, 8.5), (0.0, 0.0)]
    tipo.paredes.append(ParedeLancada("Pa1", contorno, 0.15, 13.0))
    lanc.plantas["Tipo"] = tipo
    lanc.plantas["Cobertura"] = _estrutura(Planta("Cobertura"),
                                           laje_trelicada=True)
    lanc.pavimentos = [Pavimento("1PAV", 3.0, "Tipo"),
                       Pavimento("2PAV", 6.0, "Tipo"),
                       Pavimento("COB", 9.0, "Cobertura")]
    return lanc


def main() -> None:
    from portico3d.lancamento.arquivo import gravar

    lanc = lancamento()
    caminho = gravar(lanc, os.path.join(os.path.dirname(__file__),
                                        "lancamento-residencial.json"))
    print(f"Lançamento gravado em {caminho} — abra pela janela (Abrir).")
    print(gerar(lanc).resumo())


if __name__ == "__main__":
    main()
