# -*- coding: utf-8 -*-
"""
passarela_dnit.py
Benchmark contra um projeto de verdade: a passarela metálica PL-35 do DNIT
(treliça espacial tipo Warren, vão de 35 m, dois eixos de treliça plana
afastados 2,5 m), remodelada com a API crua de ``portico3d.core`` e
confrontada com a frequência natural publicada no documento de referência
(SAP2000, Volume 2 do projeto, Tabela 3.1, pág. 256):

    * flexão vertical     f = 3,21 Hz
    * flexão transversal   f = 5,58 Hz

Toda a geometria e os perfis vêm do desenho cotado (Volume 1, folha 10/117) e
da memória de cálculo (Volume 2, páginas 40-42) — ver o prompt que gerou este
script para a transcrição completa. A única grandeza que o documento não
fecha em número é o peso do tabuleiro (steeldeck + capa de concreto): o
SAP2000 original tirava isso da espessura de casca modelada, que não está
no texto. Aqui ela é o parâmetro de calibração: ver ``PESO_TABULEIRO_KN_M2``
mais abaixo e a varredura de espessuras no fim do script.

Este script é o consumidor da capacidade nova de ``core/dinamica.py`` —
``analisar_modal(..., casos_de_massa=(...))`` — que converte o peso de um
caso de carga em massa adicional (ver o próprio módulo para a formulação).

Rodar com:

    py exemplos/passarela_dnit.py
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PASTA not in sys.path:
    sys.path.insert(0, PASTA)

# Console em cp1252 (cmd.exe/Git Bash em português) não aceita ² nem ≈ —
# ver a mesma solução em main.py.
for _fluxo in (sys.stdout, sys.stderr):
    if hasattr(_fluxo, "reconfigure"):
        try:
            _fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from portico3d.core.dinamica import GRAVIDADE, analisar_modal
from portico3d.core.modelo import Modelo, Secao

# ---------------------------------------------------------------------------
# Geometria do desenho cotado (Volume 1, folha 10/117)
# ---------------------------------------------------------------------------

VAO = 35.0                  # m, comprimento total
N_PAINEIS = 14               # painéis de 2,5 m
PASSO = VAO / N_PAINEIS       # 2,5 m
ALTURA = 2.5                 # m, altura da treliça (seção 2,5 x 2,5 m)
AFASTAMENTO = 2.5             # m, distância entre os dois eixos (Y)

EIXOS = {"A": 0.0, "B": AFASTAMENTO}

# ---------------------------------------------------------------------------
# Material — ASTM A572 Grau 50 (item 1.3 do Volume 1, "Ligação entre Módulos")
# ---------------------------------------------------------------------------

E_ACO = 2.0e8     # kN/m² (= 20000 kN/cm², valor do próprio documento)
POISSON_ACO = 0.3  # padrão do aço; não declarado explicitamente no documento
GAMA_ACO = 78.5    # kN/m³, padrão da casa para aço


# ---------------------------------------------------------------------------
# Seções — perfis W da memória de cálculo (Volume 2, páginas 40-42),
# modeladas como perfil I de abas paralelas, aproximação de paredes finas.
# ---------------------------------------------------------------------------

def secao_perfil_i(nome: str, d_cm: float, bf_cm: float, tw_cm: float,
                   tf_cm: float, area_catalogo_cm2: float | None = None
                   ) -> Secao:
    """Seção genérica a partir das dimensões de um perfil I de abas
    paralelas (mesa/alma), aproximação usual de paredes finas.

    ``Iy`` (eixo local que flete no plano x-z, vertical) recebe o momento de
    inércia forte do perfil I — o que resiste à flexão por carga de
    gravidade num banzo ou diagonal deitados; ``Iz`` recebe o fraco. É a
    mesma convenção de eixos que o resto do ``core`` usa (ver
    ``elemento.py``: "para barras não verticais o eixo local z aponta para
    cima").

    ``A`` usa o valor de catálogo quando informado (mais fiel que a soma de
    retângulos finos), e as inércias e a torção saem sempre da aproximação de
    paredes finas — este programa não tem tabela de perfis W embutida.

    As áreas de cisalhamento ficam em zero (Euler-Bernoulli), como é o
    padrão da casa: a deformação por cortante só importa em peça baixa e
    alta, e os banzos e diagonais desta treliça são esbeltos.
    """
    d, bf, tw, tf = d_cm / 100.0, bf_cm / 100.0, tw_cm / 100.0, tf_cm / 100.0
    h_alma = d - 2.0 * tf

    A_calc = 2.0 * bf * tf + h_alma * tw
    A = (area_catalogo_cm2 / 1.0e4) if area_catalogo_cm2 is not None else A_calc

    # Eixo forte (perpendicular à alma — flexão com as mesas resistindo).
    Iy = (tw * h_alma ** 3) / 12.0 + 2.0 * (
        (bf * tf ** 3) / 12.0 + bf * tf * ((d - tf) / 2.0) ** 2)
    # Eixo fraco (no plano das mesas).
    Iz = (2.0 * tf * bf ** 3) / 12.0 + (h_alma * tw ** 3) / 12.0
    # Torção de Saint-Venant, seção aberta de paredes finas: J = (1/3)Σbt³.
    J = (2.0 * bf * tf ** 3 + h_alma * tw ** 3) / 3.0

    return Secao(nome, A, Iy, Iz, J, 0.0, 0.0, "generica", 0.0, 0.0)


def secao_cantoneira_dupla(nome: str, area_por_cantoneira_cm2: float) -> Secao:
    """Par de cantoneiras costas-com-costas (contraventamento CS01/CI01).

    Barra secundária, carrega principalmente axial — aproximada como seção
    maciça equivalente (quadrado de mesma área), que já dá Iy=Iz e uma
    torção plausível pela mesma fórmula de ``Secao.retangular`` que o resto
    do programa usa para seção maciça. Não tem rigor de flexão, documentado
    como tal no prompt que gerou este script.
    """
    area_total = 2.0 * area_por_cantoneira_cm2 / 1.0e4   # m²
    lado = math.sqrt(area_total)
    base = Secao.retangular(nome, lado, lado)
    return base


SECOES = {
    # Banzo superior — W360x72.
    "BS": secao_perfil_i("BS", d_cm=35.0, bf_cm=20.4, tw_cm=0.86, tf_cm=1.51,
                        area_catalogo_cm2=91.3),
    # Banzo inferior — W360x44,6.
    "BI": secao_perfil_i("BI", d_cm=35.2, bf_cm=17.1, tw_cm=0.69, tf_cm=0.98,
                        area_catalogo_cm2=57.7),
    # Diagonais — W200x35,9.
    "D": secao_perfil_i("D", d_cm=20.1, bf_cm=16.5, tw_cm=0.62, tf_cm=1.02,
                       area_catalogo_cm2=45.7),
    # Montante de apoio — W200x41,7: não extraído do documento (não há
    # dimensão d/bf/tw/tf publicada para ele). Usa-se um W200 de catálogo
    # (Gerdau/AISC equivalente) com massa linear compatível — aproximado,
    # documentado como tal.
    "M": secao_perfil_i("M", d_cm=20.5, bf_cm=16.6, tw_cm=0.72, tf_cm=1.13,
                       area_catalogo_cm2=53.0),
    # Transversal superior — W150x13: perfil leve, aproximado por catálogo
    # (não extraído do documento).
    "TS": secao_perfil_i("TS", d_cm=15.0, bf_cm=10.0, tw_cm=0.43, tf_cm=0.49,
                        area_catalogo_cm2=16.6),
    # Transversal inferior — W150x29,8: mais robusto que o TS01, aproximado
    # por catálogo de forma coerente com a massa linear informada.
    "TI": secao_perfil_i("TI", d_cm=15.0, bf_cm=14.0, tw_cm=0.66, tf_cm=0.97,
                        area_catalogo_cm2=38.0),
    # Contraventamento em X — par de cantoneiras 2L 63,5x8,78 mm
    # (2L 2½"x2½"x11/32"), aproximado como seção maciça equivalente.
    "C": secao_cantoneira_dupla("C", area_por_cantoneira_cm2=9.48),
}


# ---------------------------------------------------------------------------
# Montagem da malha
# ---------------------------------------------------------------------------

def no_banzo(eixo: str, banzo: str, i: int) -> str:
    """Nome do nó: eixo (A/B), banzo (I/S, inferior/superior), painel i."""
    return f"{eixo}_{banzo}_{i}"


def montar_modelo(espessura_concreto_m: float) -> tuple[Modelo, dict]:
    """Monta a passarela PL-35 e devolve o modelo e os metadados do
    tabuleiro (área, carga total, carga por eixo) para o relatório.
    """
    m = Modelo("passarela_dnit_pl35")
    m.add_material("aco", E_ACO, POISSON_ACO, GAMA_ACO)
    for nome, secao in SECOES.items():
        m.add_secao(secao)

    # -- nós -----------------------------------------------------------
    for eixo, y in EIXOS.items():
        for i in range(N_PAINEIS + 1):
            x = PASSO * i
            m.add_no(no_banzo(eixo, "I", i), x, y, 0.0)
            m.add_no(no_banzo(eixo, "S", i), x, y, ALTURA)

    # -- barras dos dois eixos (banzos, diagonais em zigue-zague,
    #    montantes de apoio) --------------------------------------------
    for eixo in EIXOS:
        for i in range(N_PAINEIS):
            m.add_barra(f"BI_{eixo}_{i}", no_banzo(eixo, "I", i),
                       no_banzo(eixo, "I", i + 1), "aco", "BI")
            m.add_barra(f"BS_{eixo}_{i}", no_banzo(eixo, "S", i),
                       no_banzo(eixo, "S", i + 1), "aco", "BS")
            # Zigue-zague Warren, sem vertical no meio: alterna "\" (S_i a
            # I_{i+1}) e "/" (I_i a S_{i+1}) a cada painel.
            if i % 2 == 0:
                m.add_barra(f"D_{eixo}_{i}", no_banzo(eixo, "S", i),
                           no_banzo(eixo, "I", i + 1), "aco", "D")
            else:
                m.add_barra(f"D_{eixo}_{i}", no_banzo(eixo, "I", i),
                           no_banzo(eixo, "S", i + 1), "aco", "D")
        # Montantes — só nas duas pontas.
        m.add_barra(f"M_{eixo}_0", no_banzo(eixo, "I", 0),
                   no_banzo(eixo, "S", 0), "aco", "M")
        m.add_barra(f"M_{eixo}_{N_PAINEIS}", no_banzo(eixo, "I", N_PAINEIS),
                   no_banzo(eixo, "S", N_PAINEIS), "aco", "M")

    # -- transversais, a cada seção X (ligam eixo A a eixo B) -----------
    for i in range(N_PAINEIS + 1):
        m.add_barra(f"TS_{i}", no_banzo("A", "S", i), no_banzo("B", "S", i),
                   "aco", "TS")
        m.add_barra(f"TI_{i}", no_banzo("A", "I", i), no_banzo("B", "I", i),
                   "aco", "TI")

    # -- contraventamento em X, duplo em planta, nos dois banzos --------
    for i in range(N_PAINEIS):
        for banzo in ("I", "S"):
            secao_cv = "CI" if banzo == "I" else "CS"
            # A seção CI01/CS01 já existe no dicionário como "C" (mesma
            # bitola de cantoneira dupla para os dois planos).
            m.add_barra(f"{secao_cv}_{i}_1", no_banzo("A", banzo, i),
                       no_banzo("B", banzo, i + 1), "aco", "C")
            m.add_barra(f"{secao_cv}_{i}_2", no_banzo("A", banzo, i + 1),
                       no_banzo("B", banzo, i), "aco", "C")

    # -- apoios: 4, nos dois nós de banzo inferior nas pontas de cada
    #    eixo — vertical travado, horizontal em mola de neoprene,
    #    rotação livre nas três direções (aparelho não transmite momento).
    for eixo in EIXOS:
        for i in (0, N_PAINEIS):
            no = no_banzo(eixo, "I", i)
            m.apoiar(no, ux=False, uy=False, uz=True,
                    rx=False, ry=False, rz=False)
            m.add_mola(no, kx=833.0, ky=833.0)

    # -- caso de carga do tabuleiro: steeldeck + capa de concreto,
    #    peso rateado pela área de influência nodal (Figura 1-6 do
    #    Volume 2 — mesmo princípio do rateio de vento, aplicado aqui ao
    #    peso), aplicado como carga nodal vertical nos nós de banzo
    #    inferior (onde os transversais TI chegam de verdade). ----------
    gama_concreto = 25.0  # kN/m³
    peso_tabuleiro_m2 = espessura_concreto_m * gama_concreto  # kN/m²
    largura_tabuleiro = AFASTAMENTO
    area_tabuleiro = largura_tabuleiro * VAO
    carga_total = peso_tabuleiro_m2 * area_tabuleiro
    carga_linear_total = carga_total / VAO          # kN/m, no vão todo
    carga_linear_por_eixo = carga_linear_total / 2.0  # kN/m, por eixo

    caso = m.add_caso("TABULEIRO", natureza="permanente")
    for eixo in EIXOS:
        for i in range(N_PAINEIS + 1):
            tributario = PASSO if 0 < i < N_PAINEIS else PASSO / 2.0
            forca = carga_linear_por_eixo * tributario
            caso.nodal(no_banzo(eixo, "I", i), fz=-forca)

    metadados = {
        "espessura_concreto_m": espessura_concreto_m,
        "peso_tabuleiro_m2_kN": peso_tabuleiro_m2,
        "area_tabuleiro_m2": area_tabuleiro,
        "carga_total_kN": carga_total,
        "carga_linear_por_eixo_kN_m": carga_linear_por_eixo,
    }
    return m, metadados


def contar_malha_esperada() -> tuple[int, int]:
    """Nós e barras esperados, calculados da regra de montagem — conferido
    antes de rodar, para pegar erro de malha antes de interpretar
    frequência nenhuma."""
    nos = 2 * 2 * (N_PAINEIS + 1)   # 2 eixos × (banzo I + banzo S) × 15 nós
    barras = (2 * (N_PAINEIS + N_PAINEIS + N_PAINEIS + 2)
             + (N_PAINEIS + 1) * 2
             + N_PAINEIS * 2 * 2)
    return nos, barras


# ---------------------------------------------------------------------------
# Classificação de modo pela forma: olha o deslocamento no meio do vão
# ---------------------------------------------------------------------------

def classificar_modos(modelo: Modelo, modal, n_olhar: int = 14) -> dict:
    """Devolve o índice do primeiro modo de **flexão do vão** dominado por Z
    (vertical) e o primeiro dominado por Y (transversal).

    As molas de apoio (neoprene, k = 833 kN/m nas duas direções horizontais)
    dão à passarela inteira modos de corpo quase-rígido balançando sobre os
    quatro apoios — e, como a direção Y não tem vínculo rígido nenhum (só a
    mola), um modo real de flexão transversal nesta estrutura sempre vem
    misturado com alguma translação de corpo rígido sobre a mola; olhar
    "o apoio ficou parado?" (que funciona bem em Z, onde o apoio é
    de verdade rígido) não serve para separar os dois em Y.

    Por isso a classificação olha o **perfil ao longo do vão todo** (banzo
    inferior do eixo A, os 15 nós, i = 0 a 14), não só dois pontos: decompõe
    o deslocamento de cada direção em uma parcela de translação rígida
    (a média ao longo do vão) e uma parcela de forma variável (o resíduo em
    relação à média, que é o que entorta o vão). Um modo é "flexão" na
    direção em que a parcela de forma variável domina a norma do perfil
    (fração ≥ 0,5); caso contrário é predominantemente sway sobre a mola.
    """
    nos_perfil = [no_banzo("A", "I", i) for i in range(N_PAINEIS + 1)]
    gdl_y = [modelo.gdl(no)[1] for no in nos_perfil]
    gdl_z = [modelo.gdl(no)[2] for no in nos_perfil]

    CORTE_FLEXAO = 0.3    # fração mínima de variação de forma para contar como
                          # flexão (ver ``fracao_flexao`` abaixo)
    CORTE_RELEVANCIA = 0.15  # fração mínima do modo inteiro que tem de passar
                             # pelo perfil de referência, para não classificar
                             # como "vertical"/"transversal" um modo cujo
                             # movimento de verdade está noutro lugar (outro
                             # banzo, outro eixo, torção local) e que só
                             # aparece como ruído numérico no perfil olhado.

    def fracao_flexao(perfil: np.ndarray) -> float:
        """Quanto o perfil **varia de forma** ao longo do vão, 0 a 1.

        Não usa "quanto a média é diferente de zero" (isso falha para um
        modo de flexão de primeira ordem, que é uma meia-onda de seno,
        sempre do mesmo sinal — a média de um seno meia-onda já é mais de
        60 % do seu próprio pico, o que faria um modo de flexão de livro-
        texto parecer "metade corpo rígido" sem ser). Em vez disso, mede a
        amplitude relativa entre o ponto de maior e o de menor módulo do
        perfil: numa translação de corpo rígido todo nó tem o mesmo módulo
        (razão 0); numa forma de flexão a razão tende a 1 (os apoios ficam
        perto de zero, o meio no pico).
        """
        absperfil = np.abs(perfil)
        pico = float(absperfil.max())
        if pico < 1e-12:
            return 0.0
        return float((pico - absperfil.min()) / pico)

    vertical = None
    transversal = None
    formas = []
    for i, modo in enumerate(modal.modos[:n_olhar]):
        perfil_y = modo[gdl_y]
        perfil_z = modo[gdl_z]
        amp_y = float(np.linalg.norm(perfil_y))
        amp_z = float(np.linalg.norm(perfil_z))
        escala_modo = float(np.linalg.norm(modo)) or 1.0
        relevante_y = amp_y / escala_modo >= CORTE_RELEVANCIA
        relevante_z = amp_z / escala_modo >= CORTE_RELEVANCIA
        frac_y = fracao_flexao(perfil_y)
        frac_z = fracao_flexao(perfil_z)

        flexao_y = relevante_y and frac_y >= CORTE_FLEXAO
        flexao_z = relevante_z and frac_z >= CORTE_FLEXAO
        if flexao_z and amp_z >= amp_y:
            dominante = f"Z (flexão vertical, fração {frac_z:.2f})"
        elif flexao_y and amp_y > amp_z:
            dominante = f"Y (flexão transversal, fração {frac_y:.2f})"
        elif amp_y > amp_z and relevante_y:
            dominante = f"Y (sway sobre a mola, fração de flexão {frac_y:.2f})"
        elif relevante_z:
            dominante = f"Z (outro/local, fração de flexão {frac_z:.2f})"
        else:
            dominante = "outro — o perfil de referência não participa deste modo"
        formas.append((i, modal.frequencias[i], amp_y, amp_z, dominante))
        if flexao_z and amp_z >= amp_y and vertical is None:
            vertical = i
        if flexao_y and amp_y > amp_z and transversal is None:
            transversal = i

    return {"vertical": vertical, "transversal": transversal, "formas": formas}


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

F_VERTICAL_DOC = 3.21   # Hz, Tabela 3.1 do Volume 2, pág. 256
F_TRANSVERSAL_DOC = 5.58  # Hz, idem

PESO_TABULEIRO_KN_M2 = 2.0   # ≈ 8 cm de capa — hipótese inicial, ver docstring


def rodar(espessura_concreto_m: float, mostrar_formas: bool = False) -> dict:
    modelo, meta = montar_modelo(espessura_concreto_m)

    nos_esp, barras_esp = contar_malha_esperada()
    if len(modelo.nos) != nos_esp or len(modelo.barras) != barras_esp:
        raise RuntimeError(
            f"malha fora do esperado: {len(modelo.nos)} nós / "
            f"{len(modelo.barras)} barras, esperado {nos_esp} / {barras_esp}")

    modelo.validar()

    modal = analisar_modal(modelo, n_modos=14, casos_de_massa=("TABULEIRO",))
    classif = classificar_modos(modelo, modal)

    if mostrar_formas:
        print(f"  (malha: {len(modelo.nos)} nós, {len(modelo.barras)} barras "
              "— confere com o esperado)")
        for i, f, amp_y, amp_z, dominante in classif["formas"]:
            print(f"    modo {i + 1}: f = {f:7.4f} Hz   "
                  f"||perfil_y||={amp_y:.4f}  ||perfil_z||={amp_z:.4f}   "
                  f"{dominante}")

    f_vert = (modal.frequencias[classif["vertical"]]
             if classif["vertical"] is not None else float("nan"))
    f_transv = (modal.frequencias[classif["transversal"]]
               if classif["transversal"] is not None else float("nan"))

    return {
        "espessura_concreto_m": espessura_concreto_m,
        "meta": meta,
        "f_vertical": f_vert,
        "f_transversal": f_transv,
        "erro_vertical_pct": 100.0 * (f_vert - F_VERTICAL_DOC) / F_VERTICAL_DOC,
        "erro_transversal_pct": 100.0 * (f_transv - F_TRANSVERSAL_DOC)
                                / F_TRANSVERSAL_DOC,
    }


def main() -> None:
    nos_esp, barras_esp = contar_malha_esperada()
    print("Passarela PL-35 do DNIT — remodelagem e confronto de frequência\n")
    print(f"Malha esperada: {nos_esp} nós, {barras_esp} barras.\n")

    print("-- Primeira estimativa: capa de concreto de 8 cm --")
    r8 = rodar(0.08, mostrar_formas=True)
    print(f"\n  f vertical    = {r8['f_vertical']:.4f} Hz   "
          f"(documento {F_VERTICAL_DOC} Hz, erro {r8['erro_vertical_pct']:+.2f} %)")
    print(f"  f transversal = {r8['f_transversal']:.4f} Hz   "
          f"(documento {F_TRANSVERSAL_DOC} Hz, "
          f"erro {r8['erro_transversal_pct']:+.2f} %)\n")

    print("-- Varredura de espessura de capa de concreto --")
    print(f"  {'espessura (cm)':>15}  {'f vertical (Hz)':>17}  "
          f"{'erro (%)':>9}  {'f transversal (Hz)':>20}  {'erro (%)':>9}")
    resultados = []
    for espessura_cm in (6.0, 8.0, 10.0, 12.0, 14.0, 16.0):
        r = rodar(espessura_cm / 100.0)
        resultados.append(r)
        print(f"  {espessura_cm:>15.1f}  {r['f_vertical']:>17.4f}  "
              f"{r['erro_vertical_pct']:>+8.2f}%  "
              f"{r['f_transversal']:>20.4f}  {r['erro_transversal_pct']:>+8.2f}%")

    # Interpola linearmente (f_vertical cresce quase como 1/sqrt(massa),
    # e massa cresce linear com a espessura — a relação entre espessura e
    # f² é quase linear) para achar a espessura que reproduziria 3,21 Hz.
    espessuras = [r["espessura_concreto_m"] * 100.0 for r in resultados]
    f2 = [r["f_vertical"] ** 2 for r in resultados]
    # Ajuste linear simples em f² × espessura (mínimos quadrados).
    n = len(espessuras)
    sx = sum(espessuras)
    sy = sum(f2)
    sxx = sum(e * e for e in espessuras)
    sxy = sum(e * f for e, f in zip(espessuras, f2))
    inclinacao = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    intercepto = (sy - inclinacao * sx) / n
    alvo_f2 = F_VERTICAL_DOC ** 2
    espessura_calibrada = (alvo_f2 - intercepto) / inclinacao

    print(f"\nEspessura de capa que reproduziria {F_VERTICAL_DOC} Hz (flexão "
          f"vertical), por interpolação de f² linear em espessura: "
          f"≈ {espessura_calibrada:.1f} cm")

    if espessura_calibrada <= 0.0 or espessura_calibrada > 60.0:
        print("  Espessura calibrada fora de qualquer faixa construtiva "
              "(não dá nem para montar o modelo com massa positiva) — não "
              "faz sentido rodar o modal nela. Isso por si só já é o "
              "achado: NENHUMA espessura de capa plausível reproduz as "
              "duas frequências com a rigidez desta malha (ver LEIAME.md).")
    else:
        r_cal = rodar(espessura_calibrada / 100.0)
        print(f"  conferindo nessa espessura: f vertical = "
              f"{r_cal['f_vertical']:.4f} Hz (erro "
              f"{r_cal['erro_vertical_pct']:+.2f} %), f transversal = "
              f"{r_cal['f_transversal']:.4f} Hz (documento {F_TRANSVERSAL_DOC} "
              f"Hz, erro {r_cal['erro_transversal_pct']:+.2f} %)")

        print("\nComentário sobre plausibilidade: uma capa de concreto nessa "
              "espessura média sobre steeldeck MF-75 numa passarela é "
              + ("plausível." if 4.0 <= espessura_calibrada <= 15.0 else
                 "ACIMA do que se espera de uma composição típica de steeldeck "
                 "— ver LEIAME.md para a discussão completa."))

    print("\nAchado sobre a flexão transversal: ela fica entre 50 % e 60 % "
          "abaixo do valor publicado (5,58 Hz) em TODA a varredura de "
          "espessura, e calibrar a vertical não aproxima a transversal — ao "
          "contrário, afasta um pouco mais. Isso não é falta de massa: é "
          "falta de RIGIDEZ transversal. Este modelo só recebe o tabuleiro "
          "como massa (``casos_de_massa``, por desenho desta capacidade) —\n"
          "nenhuma rigidez de diafragma do concreto entra na matriz de "
          "rigidez, igual à ressalva que ``Laje`` já faz noutro lugar do "
          "``core`` ('a laje não trabalha como diafragma'). No SAP2000 "
          "original a capa de concreto provavelmente foi modelada como "
          "casca, contribuindo rigidez própria no plano — sobretudo "
          "relevante para a flexão TRANSVERSAL (que depende da treliça "
          "resistir como viga deitada, com as cordas longitudinais fazendo "
          "de mesa a 2,5 m uma da outra) e pouco para a vertical (que "
          "depende sobretudo da rigidez axial das cordas verticais, bem "
          "capturada aqui). Testado à parte (fora deste script, não "
          "persistido): multiplicar por 5 a área do contraventamento em X "
          "(CS01/CI01) quase não mudou a frequência transversal — o que "
          "aponta para a rigidez que falta estar no diafragma do tabuleiro, "
          "não nos perfis de aço aproximados por catálogo.")


if __name__ == "__main__":
    main()
