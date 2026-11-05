# -*- coding: utf-8 -*-
"""
dissertacao_vigas.py
Benchmark contra a dissertação "Aplicação de métodos no domínio da
frequência" (identificação modal por PP e FDD). Dos seis casos dela, dois
têm estrutura descrita o bastante para ser modelada aqui:

* **Viga modelada computacionalmente** (item 4.3): aço, biapoiada, 6 m,
  E = 210 GPa, ρ = 7850 kg/m³, A = 2,81·10⁻³ m², I = 1,845·10⁻⁸ m⁴. A
  referência é a fórmula fechada da biapoiada, ``fᵢ = (i²π/2)·√(EI/ρAL⁴)``
  — que o autor confirma com um MEF próprio de 200 elementos (Tabela 16:
  0,58 / 2,31 / 5,21 Hz, arredondados a duas casas).
* **Viga biapoiada da COPPE/UFRJ** (item 4.4): aço, 1,46 m, seção 76,2 × 8,0
  mm, E = 200 GPa, ρ = 7850 kg/m³. Referência analítica na Tabela 24
  (8,59 / 34,34 / 77,27 / 137,37 / 214,64 Hz) e duas campanhas de ensaio —
  vibração aleatória (Tabela 25) e impacto (Tabela 27) — identificadas pelo
  PP e pelo FDD, que deram o mesmo número nos dois métodos.

Os outros casos ficam de fora por não terem estrutura: os "Casos Controle"
I e II são sinais sintéticos, e as pontes PI-57 e PK075+317 só trazem as
frequências de referência, sem geometria, seção nem material.

O modelo aqui é de barras de Euler-Bernoulli com massa consistente, em 3D:
a viga também tem modos laterais, de torção e axiais, que a referência não
lista. Os modos são separados pela forma — fica o que é dominado pelo
deslocamento vertical (uz).

Rodar com:

    py exemplos/dissertacao_vigas.py
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        try:
            _fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from portico3d.core.dinamica import GRAVIDADE, analisar_modal
from portico3d.core.modelo import Modelo, Secao


def viga_biapoiada(nome: str, L: float, E: float, rho: float, secao: Secao,
                   n_elementos: int = 40) -> Modelo:
    """Viga em X, apoio de 2º gênero em x = 0 e de 1º gênero em x = L. A
    torção é travada nos apoios (senão o eixo giraria livre)."""
    m = Modelo(nome)
    m.add_material("aco", E, 0.3, rho * GRAVIDADE / 1000.0)
    m.add_secao(secao)
    for k in range(n_elementos + 1):
        m.add_no(f"N{k}", L * k / n_elementos, 0.0, 0.0)
    for k in range(n_elementos):
        m.add_barra(f"B{k}", f"N{k}", f"N{k + 1}", "aco", secao.nome)
    m.apoiar("N0", True, True, True, True, False, False)
    m.apoiar(f"N{n_elementos}", False, True, True, True, False, False)
    return m


def modos_verticais(m: Modelo, n_modos: int, n_procurar: int = 30):
    """As frequências dos modos dominados por uz, em ordem."""
    modal = analisar_modal(m, n_modos=n_procurar)
    saida = []
    for f, modo in zip(modal.frequencias, modal.modos):
        uz = np.array([modo[m.gdl(no)[2]] for no in m.nos])
        uy = np.array([modo[m.gdl(no)[1]] for no in m.nos])
        ux = np.array([modo[m.gdl(no)[0]] for no in m.nos])
        if uz @ uz > 10.0 * max(uy @ uy, ux @ ux, 1e-300):
            saida.append(f)
        if len(saida) == n_modos:
            break
    return saida


def analitica(i: int, L: float, E: float, I: float, rho: float,
              A: float) -> float:
    return i ** 2 * math.pi / 2.0 * math.sqrt(E * I / (rho * A * L ** 4))


def caso_viga_numerica() -> list[dict]:
    L, E, rho, A, I = 6.0, 210.0e6, 7850.0, 2.81e-3, 1.845e-8
    # Iz e J grandes: só a flexão vertical interessa aqui, e a referência é
    # uma viga plana (dois nós, três graus de liberdade cada, no MEF dela).
    secao = Secao("I_dissertacao", A, I, 1.0e-4, 1.0e-4)
    f = modos_verticais(viga_biapoiada("viga_6m", L, E, rho, secao), 3)
    publicadas = (0.58, 2.31, 5.21)
    return [{"modo": i + 1, "programa": f[i],
             "analitica": analitica(i + 1, L, E * 1e3, I, rho, A),
             "publicada": publicadas[i]} for i in range(3)]


def caso_viga_coppe() -> list[dict]:
    L, E, rho = 1.46, 200.0e6, 7850.0
    # A e I como a dissertação os publica (arredondados): 6,1·10⁻⁴ m² e
    # 3,25·10⁻⁹ m⁴. A inércia lateral é a do retângulo 76,2 × 8,0 mm.
    real = Secao.retangular("76x8", 0.0762, 0.0080)
    secao = Secao("76x8", 6.1e-4, 3.25e-9, real.Iz, real.J)
    f = modos_verticais(viga_biapoiada("coppe", L, E, rho, secao), 5)
    analiticas_pub = (8.59, 34.34, 77.27, 137.37, 214.64)
    aleatorio = (9.24, 33.25, 73.80, 136.04, 196.65)
    impacto = (8.32, 33.28, 73.28, 135.32, None)
    return [{"modo": i + 1, "programa": f[i],
             "analitica": analitica(i + 1, L, E * 1e3, secao.Iy, rho,
                                    secao.A),
             "publicada": analiticas_pub[i], "aleatorio": aleatorio[i],
             "impacto": impacto[i]} for i in range(5)]


def _pct(a, b):
    return "    —  " if b is None else f"{100.0 * (a - b) / b:+7.2f} %"


def main() -> None:
    print("Viga modelada computacionalmente — 6 m, 40 elementos")
    print("  modo   programa    analítica   publicada   prog×analít   "
          "prog×publicada")
    for r in caso_viga_numerica():
        print(f"  {r['modo']:4d}  {r['programa']:9.4f}  {r['analitica']:10.4f}"
              f"  {r['publicada']:10.2f}   {_pct(r['programa'], r['analitica'])}"
              f"   {_pct(r['programa'], r['publicada'])}")

    print("\nViga biapoiada da COPPE — 1,46 m, 76,2 × 8,0 mm, 40 elementos")
    print("  modo   programa    analítica   ensaio aleat.   ensaio impacto"
          "   prog×analít   prog×aleat.   prog×impacto")
    for r in caso_viga_coppe():
        imp = "      —     " if r["impacto"] is None else \
            f"{r['impacto']:10.2f}  "
        print(f"  {r['modo']:4d}  {r['programa']:9.3f}  {r['analitica']:10.3f}"
              f"  {r['aleatorio']:12.2f}   {imp}"
              f"   {_pct(r['programa'], r['analitica'])}"
              f"   {_pct(r['programa'], r['aleatorio'])}"
              f"   {_pct(r['programa'], r['impacto'])}")


if __name__ == "__main__":
    main()
