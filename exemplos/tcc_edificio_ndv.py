# -*- coding: utf-8 -*-
"""
tcc_edificio_ndv.py
Benchmark contra o TCC "Simulação de edifício esbelto com neutralizador de
vibrações": um protótipo de prédio de quatro pavimentos em escala e um
neutralizador dinâmico de vibrações (NDV) em pêndulo invertido no topo, com
as frequências calculadas em três ferramentas — um modelo de edifício de
cisalhamento no Octave, e sólidos de elementos finitos no SolidWorks e no
ANSYS.

O protótipo (Tabelas 1 a 3 do TCC):

* quatro chapas de aço de 220 × 150 × 11,5 mm (3,000 kg cada), uma por
  pavimento, sobre quatro barras chatas de 19 × 2,75 mm (0,103 kg cada) nos
  cantos, com 250 mm livres entre chapas e a base engastada; altura total
  1046 mm = 4 × (250 + 11,5);
* aço de baixo carbono, E = 200 GPa. O pilar trabalha na direção fraca:
  I = 19 · 2,75³ / 12 = 3,29·10⁻¹¹ m⁴, k = 12EI/ℓ³ = 5 057,8 N/m.

O NDV (Tabela 2): um cubo de aço de 56 mm (1,3821 kg) sobre uma haste de aço
inox de 71 × 26 × 0,9 mm (13,29 g), engastada no centro da chapa do topo.

Alvos publicados (Hz):

* sistema primário — Octave 4,4672 / 12,8629 / 19,7071 / 24,1744;
  SolidWorks 4,320 / 12,494 / 19,288 / 23,800;
  ANSYS 4,377 / 12,649 / 19,494 / 24,031;
* NDV isolado — teórico 25,3823 rad/s; SolidWorks 25,826; ANSYS 26,134;
* sistema global (prédio + NDV) — SolidWorks 3,4514 / 5,0938 / 12,499 /
  19,225 / 23,761; ANSYS 3,4670 / 5,1214 / 12,640 / 19,413 / 23,987.

Como o protótipo entra aqui, só com barras e as opções que o programa já tem:

* **Pilar**: barra entre os planos médios das chapas, com **trecho rígido**
  de 5,75 mm (meia chapa) em cada ponta que entra numa chapa — os 250 mm
  livres são o vão flexível. A massa do pilar sai do material e cai no vão
  flexível.
* **Chapa**, de dois jeitos:
  * *rígida* — vigas de borda muito rígidas e diafragma rígido: é a hipótese
    do modelo de cisalhamento do Octave (pavimento indeformável, pilar
    biengastado);
  * *grelha* — a chapa de 11,5 mm como **laje em grelha**, com as vigas de
    borda quase sem rigidez: a chapa flete, o pilar não fica perfeitamente
    engastado, e é isso que os sólidos do SolidWorks e do ANSYS capturam.
  Nos dois, a massa da chapa entra como carga de laje (o peso dos 3,000 kg)
  convertida em massa por ``casos_de_massa``; na grelha ela se espalha pela
  chapa, com a inércia de rotação certa.
* **NDV**: a haste é uma barra vertical engastada no centro da chapa do topo
  (trecho rígido de meia chapa na base), com a direção fraca na mesma
  direção dos pilares. O cubo é uma barra rígida sem peso de 56 mm, com
  metade da massa em cada um de dois nós a ``±a/√6`` do centro — o par que
  tem a massa **e** a inércia de rotação do cubo (``m·a²/6``). Nada disso
  muda a geometria do programa: é barra, trecho rígido e massa de caso de
  carga.

**A haste é lâmina, não viga.** Com 26 mm de largura para 0,9 mm de
espessura e 71 mm de comprimento, ela flete entre o comportamento de viga
(módulo E) e o de placa em flexão cilíndrica (E/(1−ν²), 9,9 % mais rígida):
a curvatura anticlástica que a viga deixa livre é contida pela largura. Os
sólidos do SolidWorks e do ANSYS capturam isso, a barra daqui não. O script
roda as duas leituras — elas são os limites, e os dois CAD caem entre eles.

**A chapa rígida é a leitura certa deste protótipo.** Na grelha o pilar se
liga à chapa num nó só; no sólido, a barra chata de 19 mm fica colada ao
longo da chapa e é bem mais travada. Na direção fraca a diferença é de
0,5 %, mas na forte o modo em Y desce para 22,8 Hz e entra no meio dos quatro
primeiros, o que o SolidWorks não mostra. Com a chapa rígida, os quatro
primeiros modos são os quatro da direção fraca, como no TCC.

A gravidade não entra na rigidez do NDV (análise modal sem pré-tensão, como
a análise de frequência padrão do SolidWorks e do ANSYS).

Rodar com:

    py exemplos/tcc_edificio_ndv.py
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import replace

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
from portico3d.core.lajes import aplicar_lajes
from portico3d.core.modelo import Modelo, Secao

# -- protótipo -----------------------------------------------------------
LX, LY, E_CHAPA = 0.220, 0.150, 0.0115         # m
LIVRE = 0.250                                  # m, pilar entre chapas
B_PILAR, T_PILAR = 0.019, 0.00275               # m
N_PAV = 4
E_ACO = 200.0e6                                # kN/m²
M_CHAPA, M_PILAR = 3.000, 0.103                 # kg

# -- NDV -----------------------------------------------------------------
L_HASTE, B_HASTE, T_HASTE = 0.071, 0.026, 0.0009
E_INOX, RHO_INOX = 193.0e6, 8000.0             # kN/m², kg/m³ (13,29 g)
A_CUBO, M_CUBO = 0.056, 1.3821

ALVOS = {
    "primario": {"Octave": (4.4672, 12.8629, 19.7071, 24.1744),
                 "SolidWorks": (4.320, 12.494, 19.288, 23.800),
                 "ANSYS": (4.377, 12.649, 19.494, 24.031)},
    "ndv": {"teórico": 25.3823 / (2 * math.pi),
            "SolidWorks": 25.826 / (2 * math.pi),
            "ANSYS": 26.134 / (2 * math.pi)},
    "global": {"SolidWorks": (3.4514, 5.0938, 12.499, 19.225, 23.761),
               "ANSYS": (3.4670, 5.1214, 12.640, 19.413, 23.987)},
}


def _peso_especifico(massa_kg: float, volume_m3: float) -> float:
    """kN/m³ que dá exatamente a massa publicada."""
    return massa_kg / volume_m3 * GRAVIDADE / 1000.0


def montar(chapa: str = "grelha", ndv: bool = False,
           malha: float = 0.0275, lamina: bool = False) -> Modelo:
    """``chapa``: ``"rigida"`` ou ``"grelha"``."""
    m = Modelo(f"tcc_{chapa}" + ("_ndv" if ndv else ""))
    m.add_material("pilar", E_ACO, 0.3,
                   _peso_especifico(M_PILAR, LIVRE * B_PILAR * T_PILAR))
    m.add_material("chapa", E_ACO, 0.3,
                   _peso_especifico(M_CHAPA, LX * LY * E_CHAPA))
    m.add_material("sem_peso", E_ACO, 0.3, 0.0)
    # Direção fraca em X: na barra vertical o eixo local y é o X global, e
    # ``b`` é medido em y — b = 2,75 mm, h = 19 mm, Iz = h·b³/12.
    m.add_secao(Secao.retangular("pilar", T_PILAR, B_PILAR))
    if chapa == "rigida":
        m.add_secao(Secao("borda", 1.0e-2, 1.0e-4, 1.0e-4, 1.0e-4))
    else:
        m.add_secao(Secao("borda", 1.0e-6, 1.0e-13, 1.0e-13, 1.0e-13))

    meia = E_CHAPA / 2.0
    cotas = [k * (LIVRE + E_CHAPA) + LIVRE + meia for k in range(N_PAV)]
    cantos = [(0, 0.0, 0.0), (1, LX, 0.0), (2, LX, LY), (3, 0.0, LY)]
    for c, x, y in cantos:
        m.add_no(f"B{c}", x, y, 0.0)
        m.apoiar(f"B{c}")
        for k, z in enumerate(cotas, start=1):
            m.add_no(f"N{c}.{k}", x, y, z)
    for c, _, _ in cantos:
        anterior = f"B{c}"
        for k in range(1, N_PAV + 1):
            m.add_barra(f"P{c}.{k}", anterior, f"N{c}.{k}", "pilar", "pilar",
                        offset_i=0.0 if k == 1 else meia, offset_j=meia)
            anterior = f"N{c}.{k}"
    for k in range(1, N_PAV + 1):
        for c in range(4):
            m.add_barra(f"V{c}.{k}", f"N{c}.{k}", f"N{(c + 1) % 4}.{k}",
                        "sem_peso", "borda")
        m.add_laje(f"L{k}", f"N0.{k}", f"N2.{k}", espessura=E_CHAPA,
                   material="chapa")
    aplicar_lajes(m, m.add_caso("CHAPAS"))
    casos_de_massa = ["CHAPAS"]

    if chapa == "rigida":
        m.calculo = replace(m.calculo, diafragma=True)
        # nó no centro da chapa do topo, preso aos cantos por barras rígidas
        m.add_no("C", LX / 2, LY / 2, cotas[-1])
        for c in range(4):
            m.add_barra(f"R{c}", "C", f"N{c}.{N_PAV}", "sem_peso", "borda")
        centro = "C"
    else:
        m.calculo = replace(m.calculo, grelha=True, malha_grelha=malha)
        centro = None

    if ndv:
        centro = _acrescentar_ndv(m, cotas[-1], centro, lamina=lamina)
    m.validar()
    m.__dict__["casos_de_massa"] = tuple(casos_de_massa + (["NDV"] if ndv
                                                           else []))
    return m


def _acrescentar_ndv(m: Modelo, cota: float, centro: str | None,
                     meia: float = E_CHAPA / 2.0,
                     lamina: bool = False) -> str:
    """Haste + cubo sobre o centro da chapa do topo.

    Na grelha o nó do centro não existe no modelo do usuário — é do modelo de
    cálculo. Ele é criado aqui como nó comum: a grelha o reconhece pela
    posição e liga a ele as faixas da laje.
    """
    E = E_INOX / (1.0 - 0.3 ** 2) if lamina else E_INOX
    m.add_material("inox", E, 0.3, RHO_INOX * GRAVIDADE / 1000.0)
    m.add_secao(Secao.retangular("haste", T_HASTE, B_HASTE))
    m.add_secao(Secao("cubo", 1.0e-3, 1.0e-6, 1.0e-6, 1.0e-6))
    if centro is None:
        m.add_no("C", LX / 2, LY / 2, cota)
        centro = "C"
    topo_haste = cota + meia + L_HASTE
    d = A_CUBO / math.sqrt(6.0)
    meio_cubo = topo_haste + A_CUBO / 2.0
    m.add_no("H", LX / 2, LY / 2, topo_haste)
    m.add_no("Q1", LX / 2, LY / 2, meio_cubo - d)
    m.add_no("Q2", LX / 2, LY / 2, meio_cubo + d)
    m.add_barra("HASTE", centro, "H", "inox", "haste", offset_i=meia)
    m.add_barra("CUBO1", "H", "Q1", "sem_peso", "cubo")
    m.add_barra("CUBO2", "Q1", "Q2", "sem_peso", "cubo")
    caso = m.add_caso("NDV")
    peso = M_CUBO * GRAVIDADE / 1000.0
    caso.nodal("Q1", fz=-peso / 2.0)
    caso.nodal("Q2", fz=-peso / 2.0)
    return centro


def ndv_isolado(lamina: bool = False) -> float:
    """O NDV engastado numa base fixa — o que o TCC chama de 'modelo CAD do
    NDV'. Devolve a primeira frequência na direção fraca, Hz."""
    m = Modelo("ndv")
    m.add_material("sem_peso", E_ACO, 0.3, 0.0)
    m.add_no("C", LX / 2, LY / 2, 0.0)
    m.apoiar("C")
    _acrescentar_ndv(m, 0.0, "C", meia=0.0, lamina=lamina)
    modal = analisar_modal(m, n_modos=4, casos_de_massa=("NDV",))
    return _frequencias_em_x(m, modal, ["Q1"], 1)[0]


def _frequencias_em_x(m: Modelo, modal, nos: list[str], n: int) -> list:
    """As ``n`` primeiras frequências cujo modo é dominado por ux dos nós
    dados (a direção fraca dos pilares e da haste)."""
    saida = []
    for f, modo in zip(modal.frequencias, modal.modos):
        ux = np.array([modo[m.gdl(no)[0]] for no in nos])
        uy = np.array([modo[m.gdl(no)[1]] for no in nos])
        rz = np.array([modo[m.gdl(no)[5]] for no in nos])
        giro = rz * max(LX, LY) / 2.0
        if ux @ ux > 4.0 * max(uy @ uy, giro @ giro, 1e-300):
            saida.append(f)
        if len(saida) == n:
            break
    return saida


def rodar(chapa: str, ndv: bool, n: int, imprimir: bool = False,
          lamina: bool = False):
    m = montar(chapa, ndv, lamina=lamina)
    modal = analisar_modal(m, n_modos=12,
                           casos_de_massa=m.__dict__["casos_de_massa"])
    nos = [f"N0.{k}" for k in range(1, N_PAV + 1)] + (["Q1"] if ndv else [])
    if imprimir:
        for i, f in enumerate(modal.frequencias):
            modo = modal.modos[i]
            amp = {d: max(abs(modo[m.gdl(no)[k]]) for no in nos)
                   for d, k in (("ux", 0), ("uy", 1), ("rz", 5))}
            print(f"     modo {i + 1:2d}: {f:8.3f} Hz   máx ux {amp['ux']:.3f}"
                  f"  uy {amp['uy']:.3f}  rz·a {amp['rz'] * 0.11:.3f}")
    return _frequencias_em_x(m, modal, nos, n)


def _tabela(titulo: str, obtidas: list, alvos: dict) -> None:
    print(titulo)
    cab = "  modo  programa " + "".join(f"{k:>12s} {'Δ':>8s}" for k in alvos)
    print(cab)
    for i, f in enumerate(obtidas):
        linha = f"  {i + 1:4d}  {f:8.3f} "
        for valores in alvos.values():
            ref = valores[i]
            linha += f"{ref:12.3f} {100 * (f - ref) / ref:+7.2f}%"
        print(linha)


def main() -> None:
    print("TCC — prédio de 4 pavimentos em escala, com NDV em pêndulo invertido")
    for chapa, rotulo in (("rigida", "chapa rígida (hipótese do Octave)"),
                          ("grelha", "chapa em grelha (chapa de 11,5 mm "
                                     "flexível)")):
        _tabela(f"\nSistema primário — {rotulo}",
                rodar(chapa, False, 4), ALVOS["primario"])

    print("\nNDV isolado, engastado na base")
    for lamina, rotulo in ((False, "haste como viga (E)"),
                           (True, "haste como lâmina (E/(1−ν²))")):
        f = ndv_isolado(lamina)
        print(f"  {rotulo}: {f:7.4f} Hz ({2 * math.pi * f:7.3f} rad/s)")
        for nome, ref in ALVOS["ndv"].items():
            print(f"      × {nome:10s} {ref:7.4f} Hz: "
                  f"{100 * (f - ref) / ref:+6.2f} %")

    for chapa, lamina, rotulo in (
            ("rigida", False, "chapa rígida, haste como viga"),
            ("rigida", True, "chapa rígida, haste como lâmina"),
            ("grelha", True, "chapa em grelha, haste como lâmina")):
        _tabela(f"\nSistema global (prédio + NDV) — {rotulo}",
                rodar(chapa, True, 5, lamina=lamina), ALVOS["global"])


if __name__ == "__main__":
    main()
