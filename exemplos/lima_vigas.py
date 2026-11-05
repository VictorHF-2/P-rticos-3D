# -*- coding: utf-8 -*-
"""
lima_vigas.py
Benchmark contra a literatura acadêmica: Lima, R. "Análise Dinâmica de Vigas
e Pórticos" (TCC, Universidade de Brasília, 2019). O documento valida, para
duas vigas de aço clássicas (biapoiada e engastada-livre), as três primeiras
frequências naturais de flexão contra um modelo em ANSYS, e por sua vez
contra a fórmula fechada de Euler-Bernoulli — com erro do próprio autor de
0 % / 3 % / 7 % (biapoiada) e 0 % / 2 % / 6 % (engastada-livre) entre ANSYS
e fórmula fechada.

Dados (texto do TCC, mais o vão retrocalculado pela frequência publicada
contra a fórmula fechada — bateu em 4,0 m exato nos dois casos):

    * vão L = 4,0 m
    * seção retangular 0,1 x 0,3 m (b x h)
    * aço: E = 2x10^11 Pa = 2x10^8 kN/m², ni = 0,3, massa específica
      7850 kg/m³ -> peso específico = 7850 x 9,80665 = 76 982 N/m³
      = 76,982 kN/m³ (o valor do documento, não o padrão de 78,5 kN/m³
      da casa)

Vibração livre pura, sem carga nenhuma (``casos_de_massa`` vazio): só a massa
própria das barras entra no problema de autovalor, exatamente como em
``validacao.modal_viga_em_balanco``.

Alvos publicados (ANSYS, Tabela do TCC, Hz):

    * Caso 1, biapoiada:       42,512 / 123,08 / 192,16
    * Caso 2, engastada-livre: 15,221 / 77,754 / 159,645

Rodar com:

    py exemplos/lima_vigas.py
"""

from __future__ import annotations

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

from portico3d.core.dinamica import analisar_modal
from portico3d.core.modelo import Modelo, Secao

# ---------------------------------------------------------------------------
# Dados comuns aos dois casos
# ---------------------------------------------------------------------------

L = 4.0                     # m, vão (retrocalculado, consistente nos 2 casos)
B, H = 0.1, 0.3              # m, seção retangular (b x h)
E_ACO = 2.0e8                # kN/m², = 2x10^11 Pa
POISSON_ACO = 0.3
GAMA_ACO = 76.982             # kN/m³ = 7850 kg/m³ x 9,80665 m/s² (do documento)

N_ELEMENTOS = 16              # malha refinada o bastante para o 3º modo convergir
                              # (mesma lição de validacao.modal_viga_em_balanco)
N_MODOS_PEDIDOS = 12           # pede mais que 3: a seção não é quadrada (Iy != Iz),
                              # então modos de flexão no eixo fraco (Y) se
                              # intercalam com os do eixo forte (Z, o que o
                              # documento mede) na lista ordenada por frequência

SECAO = Secao.retangular("R10x30", B, H)
# Iy = b*h^3/12 governa a flexão no plano x-z (vertical, a que o documento
# mede); Iz = h*b^3/12 governa o eixo fraco (horizontal) -- ver docstring de
# elemento.py: "para barras não verticais o eixo local z aponta para cima".


def montar_modelo(engastada: bool) -> Modelo:
    nome = "lima_engastada" if engastada else "lima_biapoiada"
    m = Modelo(nome)
    m.add_material("aco", E_ACO, POISSON_ACO, GAMA_ACO)
    m.add_secao(SECAO)

    for i in range(N_ELEMENTOS + 1):
        m.add_no(f"N{i}", L * i / N_ELEMENTOS, 0.0, 0.0)
    for i in range(N_ELEMENTOS):
        m.add_barra(f"B{i}", f"N{i}", f"N{i + 1}", "aco", "R10x30")

    if engastada:
        # Caso 2: engaste total na base (N0), ponta livre -- igual ao
        # padrão de validacao.modal_viga_em_balanco.
        m.apoiar("N0")
    else:
        # Caso 1: biapoiada -- pino em N0 (trava as 3 translações), rolete
        # no outro extremo (trava uy/uz, libera ux); flexão livre nos dois
        # (ry, rz), mas **rx (torção) travado nos dois** -- um apoio de
        # viga de verdade impede o giro em torno do próprio eixo (apoio de
        # garfo), e sem essa trava o modelo 3D completo tem um mecanismo de
        # corpo rígido (girar livre em torno de x, frequência zero) que não
        # existe no problema uniaxial que a fórmula fechada do documento
        # resolve.
        m.apoiar("N0", ux=True, uy=True, uz=True, rx=True, ry=False, rz=False)
        m.apoiar(f"N{N_ELEMENTOS}", ux=False, uy=True, uz=True,
                rx=True, ry=False, rz=False)

    return m


def classificar_modos_verticais(modelo: Modelo, modal, n_esperados: int = 3
                                ) -> list[int]:
    """Índices (ordem crescente de frequência) dos modos de flexão
    **vertical** (plano x-z, eixo forte Iy) -- a direção que a fórmula
    fechada do documento mede.

    A seção não é quadrada (Iy > Iz aqui: 0,3 m de altura é o eixo forte),
    então os modos de flexão no eixo fraco (Y, horizontal) entram
    intercalados na lista ordenada, com frequência mais baixa que o modo de
    mesma ordem no eixo forte -- por isso pedir só os 3 primeiros ``modal``
    não bastaria. A classificação olha o perfil ao longo de toda a viga,
    nas duas direções de flexão (uy e uz), e decide qual direção domina --
    mesmo método de ``exemplos/passarela_dnit.py:classificar_modos``,
    simplificado (aqui não há mola nem sway de corpo rígido para confundir).
    """
    nos = [f"N{i}" for i in range(N_ELEMENTOS + 1)]
    gdl_uy = [modelo.gdl(no)[1] for no in nos]
    gdl_uz = [modelo.gdl(no)[2] for no in nos]

    verticais = []
    for i, modo in enumerate(modal.modos):
        perfil_uy = modo[gdl_uy]
        perfil_uz = modo[gdl_uz]
        amp_uy = float(np.linalg.norm(perfil_uy))
        amp_uz = float(np.linalg.norm(perfil_uz))
        escala = float(np.linalg.norm(modo)) or 1.0
        if (amp_uy + amp_uz) / escala < 0.2:
            continue  # modo axial/torcional: nem uy nem uz participam
        if amp_uz > amp_uy:
            verticais.append(i)
        if len(verticais) >= n_esperados:
            break
    return verticais


def rodar_caso(nome: str, engastada: bool, alvos_hz: list[float]) -> None:
    modelo = montar_modelo(engastada)

    n_esperado = N_ELEMENTOS + 1
    if len(modelo.nos) != n_esperado or len(modelo.barras) != N_ELEMENTOS:
        raise RuntimeError(
            f"malha fora do esperado: {len(modelo.nos)} nós / "
            f"{len(modelo.barras)} barras, esperado {n_esperado} / "
            f"{N_ELEMENTOS}")
    modelo.validar()

    modal = analisar_modal(modelo, n_modos=N_MODOS_PEDIDOS)
    indices = classificar_modos_verticais(modelo, modal, len(alvos_hz))

    print(f"\n{nome}")
    print(f"  (malha: {len(modelo.nos)} nós, {len(modelo.barras)} barras, "
          f"{N_MODOS_PEDIDOS} modos pedidos, {len(indices)} verticais achados)")
    if len(indices) < len(alvos_hz):
        print(f"  AVISO: só achou {len(indices)} modo(s) vertical(is) de "
              f"{len(alvos_hz)} esperados -- aumentar N_MODOS_PEDIDOS")

    print(f"  {'modo':>5}  {'calculado (Hz)':>15}  {'publicado (Hz)':>15}  "
          f"{'erro (%)':>9}")
    for k, (idx, alvo) in enumerate(zip(indices, alvos_hz), start=1):
        f_calc = modal.frequencias[idx]
        erro = 100.0 * (f_calc - alvo) / alvo
        print(f"  {k:>5}  {f_calc:>15.4f}  {alvo:>15.4f}  {erro:>+8.2f}%")


def main() -> None:
    print("Lima (TCC UnB, 2019) -- vigas biapoiada e engastada-livre, "
          "flexão vertical\n")
    print(f"L = {L} m, seção {B} x {H} m, E = {E_ACO:.3e} kN/m², "
          f"peso específico = {GAMA_ACO} kN/m³\n")

    rodar_caso("Caso 1 -- viga biapoiada (ANSYS, Tabela do TCC)", False,
              [42.512, 123.08, 192.16])
    rodar_caso("Caso 2 -- viga engastada-livre (ANSYS, Tabela do TCC)", True,
              [15.221, 77.754, 159.645])


if __name__ == "__main__":
    main()
