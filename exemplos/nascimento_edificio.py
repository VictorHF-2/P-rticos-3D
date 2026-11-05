# -*- coding: utf-8 -*-
"""
nascimento_edificio.py
Benchmark contra a literatura acadêmica: Nascimento, "Análise Modal de uma
Edificação de Multipavimentos Considerando a Interação com a Alvenaria de
Vedação" (TCC, UFSM, 2025) -- edifício real de 12 pavimentos.

Escopo desta rodada: **só os modelos SEM alvenaria participante** --
simulações 1, 2 e 5 do documento (pórtico espacial; pórtico plano com massa
pelo método 1; pórtico plano com massa pelo método 2, charneiras plásticas).
A diagonal de Mainstone (alvenaria) fica fora -- não é modelada aqui.

Geometria (planta de formas, Figura 12 do documento): grelha regular de
pilares, 5 colunas em X (0, 6, 12, 18, 24 m) x 3 colunas em Y (0, 6, 12 m),
15 pilares por pavimento (P1 a P15, varrendo X dentro de cada linha de Y:
P1-P5 em Y=0, P6-P10 em Y=6, P11-P15 em Y=12). 12 pavimentos, pé-direito
3,0 m, térreo em Z=0.

    * Pilares da linha Y=6 m (P6-P10, "central" em Y): seção 50x50 cm.
    * Pilares das linhas Y=0 e Y=12 m (P1-P5, P11-P15, "extremidade"):
      seção 40x40 cm.
    * Vigas (nas duas direções): seção 20x60 cm.
    * Lajes: espessura 13 cm -- só carga (peso próprio + revestimento),
      não são elemento de rigidez (Laje, em core/modelo.py, nunca é).

Materiais -- dois concretos, com a redução de rigidez à flexão simplificada
que o documento usa para a análise dinâmica (NBR 6118:2023, 15.7.3): pilares
a 80% de EI, vigas a 40% de EI. Implementada reduzindo o **E** do material
(a seção mantém a inércia geométrica real) -- é equivalente e mais simples
de montar: EI_reduzido = fator x E_bruto x I_bruto = (fator x E_bruto) x I_bruto.

    * C40_pilar: E = 0,8 x 35 GPa = 28 GPa      (pavimentos 1 e 2)
    * C40_viga:  E = 0,4 x 35 GPa = 14 GPa      (pavimentos 1 e 2)
    * C25_pilar: E = 0,8 x 28 GPa = 22,4 GPa    (pavimentos 3 a 12)
    * C25_viga:  E = 0,4 x 28 GPa = 11,2 GPa    (pavimentos 3 a 12)

"Pavimentos 1 e 2" = os pilares entre o térreo e o 2º piso (1º e 2º lance
vertical) e as vigas dos pisos 1 e 2; os demais (3º ao 12º piso) usam
C25_*. Todos com ni = 0,2 e peso específico = 2500 kgf/m³ x 9,80665 =
24 516,625 N/m³ = 24,516625 kN/m³ (valor exato do documento, não o padrão
de 25 kN/m³ da casa).

Massa (``casos_de_massa``, a capacidade nova de core/dinamica.py): um caso
"MASSA" com (1) parede de vedação sobre TODAS as vigas -- 310 kgf/m² x
2,40 m de altura (Tabela 2 do documento) = 744 kgf/m = 7,296 kN/m -- e
(2) revestimento sobre as lajes -- 100 kgf/m² em todo pavimento, exceto a
cobertura (12º), que recebe 40 kgf/m² de telhado. Nenhuma carga acidental
entra na massa -- o documento usa só permanente.

**Decisão de modelagem tomada sozinha**: o peso próprio da laje (espessura x
peso específico do concreto) entra via o próprio mecanismo de ``Laje`` do
``core`` (``carga_permanente`` soma espessura x peso específico ao
``permanente`` declarado) -- não é uma magnitude à parte que o roteiro lista,
mas a frase "além do peso próprio" do prompt, mais o fato de o documento dar
a espessura da laje como dado de geometria, tornam essa leitura a mais
natural: a espessura não serve só para a área de influência (ela não entra
nessa conta, que é puramente geométrica -- lx, ly dos cantos), serve para
que ``Laje.carga_permanente`` compute o peso próprio automaticamente, somado
ao revestimento, e tudo reparta junto pela mesma área de influência.

Rodar com:

    py exemplos/nascimento_edificio.py
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

from portico3d.core import lajes as mod_lajes
from portico3d.core.dinamica import analisar_modal
from portico3d.core.modelo import Modelo, Secao

# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

XS = (0.0, 6.0, 12.0, 18.0, 24.0)   # 5 linhas de pilares em X
YS = (0.0, 6.0, 12.0)                # 3 linhas de pilares em Y
NX, NY = len(XS), len(YS)             # 5, 3
N_PAV = 12                            # pavimentos (térreo é iz = 0)
PE_DIREITO = 3.0                      # m

IY_CENTRAL = 1                        # linha Y = 6 m -- pilares 50x50

# ---------------------------------------------------------------------------
# Materiais -- EI reduzido simplificado (15.7.3), via E
# ---------------------------------------------------------------------------

GPA = 1.0e6                           # 1 GPa = 1e6 kN/m² (1 Pa = 1e-3 kN/m²)
E_C40 = 35.0 * GPA
E_C25 = 28.0 * GPA
POISSON_CONCRETO = 0.2
GAMA_CONCRETO = 2500.0 * 9.80665 / 1000.0   # kN/m³ = 24,516625

MATERIAIS = {
    "C40_pilar": (0.8 * E_C40, "pavimentos 1-2, pilar, 0,8 EI"),
    "C40_viga": (0.4 * E_C40, "pavimentos 1-2, viga, 0,4 EI"),
    "C25_pilar": (0.8 * E_C25, "pavimentos 3-12, pilar, 0,8 EI"),
    "C25_viga": (0.4 * E_C25, "pavimentos 3-12, viga, 0,4 EI"),
}

# ---------------------------------------------------------------------------
# Seções
# ---------------------------------------------------------------------------

SEC_PILAR_CENTRAL = Secao.retangular("P50x50", 0.5, 0.5)   # linha Y = 6 m
SEC_PILAR_EXTREMO = Secao.retangular("P40x40", 0.4, 0.4)   # linhas Y=0, Y=12
SEC_VIGA = Secao.retangular("V20x60", 0.2, 0.6)

# ---------------------------------------------------------------------------
# Cargas de massa (permanente -- parede, revestimento/telhado; sem acidental)
# ---------------------------------------------------------------------------

PESO_PAREDE_KN_M = 310.0 * 2.40 * 9.80665 / 1000.0          # kN/m, ~7,296
REVESTIMENTO_KN_M2 = 100.0 * 9.80665 / 1000.0                # kN/m², ~0,980665
TELHADO_COBERTURA_KN_M2 = 40.0 * 9.80665 / 1000.0            # kN/m², ~0,392266
ESPESSURA_LAJE = 0.13                                        # m

PAV_COBERTURA = N_PAV   # 12º piso


def material_pilar(lance: int) -> str:
    """``lance`` 1..12 -- o lance vertical entre o piso (lance-1) e (lance)."""
    return "C40_pilar" if lance <= 2 else "C25_pilar"


def material_viga(piso: int) -> str:
    """``piso`` 1..12 -- o piso em que a viga está (térreo, piso 0, não tem viga)."""
    return "C40_viga" if piso <= 2 else "C25_viga"


def revestimento_do_piso(piso: int) -> float:
    return (TELHADO_COBERTURA_KN_M2 if piso == PAV_COBERTURA
            else REVESTIMENTO_KN_M2)


def no(ix: int, iy: int, iz: int) -> str:
    return f"N{ix}_{iy}_{iz}"


def nome_pilar(ix: int, iy: int) -> str:
    """P1..P15, varrendo X dentro de cada linha de Y -- só para legibilidade
    dos nomes de barra, sem efeito no cálculo."""
    return f"P{iy * NX + ix + 1}"


# ---------------------------------------------------------------------------
# Pórtico espacial -- Simulação 1
# ---------------------------------------------------------------------------

def montar_predio_3d() -> tuple[Modelo, dict]:
    m = Modelo("nascimento_predio_3d")
    for nome_mat, (E, _descr) in MATERIAIS.items():
        m.add_material(nome_mat, E, POISSON_CONCRETO, GAMA_CONCRETO)
    m.add_secao(SEC_PILAR_CENTRAL)
    m.add_secao(SEC_PILAR_EXTREMO)
    m.add_secao(SEC_VIGA)

    # -- nós: 5 x 3 x 13 (térreo + 12 pavimentos) ---------------------------
    for ix, x in enumerate(XS):
        for iy, y in enumerate(YS):
            for iz in range(N_PAV + 1):
                m.add_no(no(ix, iy, iz), x, y, PE_DIREITO * iz)

    # -- pilares: 15 colunas x 12 lances -------------------------------------
    for ix in range(NX):
        for iy in range(NY):
            secao = (SEC_PILAR_CENTRAL.nome if iy == IY_CENTRAL
                     else SEC_PILAR_EXTREMO.nome)
            for lance in range(1, N_PAV + 1):
                m.add_barra(f"{nome_pilar(ix, iy)}_L{lance}",
                           no(ix, iy, lance - 1), no(ix, iy, lance),
                           material_pilar(lance), secao)

    # -- vigas X (ao longo de X, em cada linha de Y, em cada piso) -----------
    for iy in range(NY):
        for piso in range(1, N_PAV + 1):
            mat = material_viga(piso)
            for ix in range(NX - 1):
                m.add_barra(f"VX_{ix}-{ix+1}_Y{iy}_P{piso}",
                           no(ix, iy, piso), no(ix + 1, iy, piso),
                           mat, SEC_VIGA.nome)

    # -- vigas Y (ao longo de Y, em cada linha de X, em cada piso) -----------
    for ix in range(NX):
        for piso in range(1, N_PAV + 1):
            mat = material_viga(piso)
            for iy in range(NY - 1):
                m.add_barra(f"VY_{iy}-{iy+1}_X{ix}_P{piso}",
                           no(ix, iy, piso), no(ix, iy + 1, piso),
                           mat, SEC_VIGA.nome)

    # -- apoios: engastados no térreo -----------------------------------------
    for ix in range(NX):
        for iy in range(NY):
            m.apoiar(no(ix, iy, 0))

    # -- lajes: 4 vãos em X x 2 vãos em Y, por pavimento ---------------------
    for piso in range(1, N_PAV + 1):
        mat_laje = material_viga(piso)   # só para o peso específico
        permanente = revestimento_do_piso(piso)
        for ix in range(NX - 1):
            for iy in range(NY - 1):
                m.add_laje(f"L_{ix}{iy}_P{piso}",
                          no(ix, iy, piso), no(ix + 1, iy + 1, piso),
                          espessura=ESPESSURA_LAJE, material=mat_laje,
                          permanente=permanente)

    # -- caso de massa: parede em todas as vigas + lajes (peso próprio +
    #    revestimento/telhado), nada de acidental -----------------------------
    massa = m.add_caso("MASSA", natureza="permanente")
    for nome_barra, barra in m.barras.items():
        if nome_barra.startswith("VX_") or nome_barra.startswith("VY_"):
            massa.distribuida(nome_barra, qz=-PESO_PAREDE_KN_M,
                              sistema="global")
    mod_lajes.aplicar_lajes(m, massa)

    metadados = {
        "n_nos_esperado": NX * NY * (N_PAV + 1),
        "n_pilares_esperado": NX * NY * N_PAV,
        "n_vigas_x_esperado": (NX - 1) * NY * N_PAV,
        "n_vigas_y_esperado": NX * (NY - 1) * N_PAV,
    }
    return m, metadados


# ---------------------------------------------------------------------------
# Pórtico plano -- a linha de pilares P3-P8-P13 (X = 12 m), confinado ao
# plano Y-Z com ux, ry, rz restringidos em TODOS os nós -- Simulações 2 e 5
# ---------------------------------------------------------------------------

IX_PLANO = 2   # X = 12 m -- a linha "central" em X (P3, P8, P13)


def montar_portico_plano() -> Modelo:
    m = Modelo("nascimento_portico_plano")
    for nome_mat, (E, _descr) in MATERIAIS.items():
        m.add_material(nome_mat, E, POISSON_CONCRETO, GAMA_CONCRETO)
    m.add_secao(SEC_PILAR_CENTRAL)
    m.add_secao(SEC_PILAR_EXTREMO)
    m.add_secao(SEC_VIGA)

    ix = IX_PLANO
    x = XS[ix]

    for iy, y in enumerate(YS):
        for iz in range(N_PAV + 1):
            m.add_no(no(ix, iy, iz), x, y, PE_DIREITO * iz)

    for iy in range(NY):
        secao = (SEC_PILAR_CENTRAL.nome if iy == IY_CENTRAL
                 else SEC_PILAR_EXTREMO.nome)
        for lance in range(1, N_PAV + 1):
            m.add_barra(f"{nome_pilar(ix, iy)}_L{lance}",
                       no(ix, iy, lance - 1), no(ix, iy, lance),
                       material_pilar(lance), secao)

    for piso in range(1, N_PAV + 1):
        mat = material_viga(piso)
        for iy in range(NY - 1):
            m.add_barra(f"VY_{iy}-{iy+1}_P{piso}",
                       no(ix, iy, piso), no(ix, iy + 1, piso),
                       mat, SEC_VIGA.nome)

    # -- confinamento ao plano: ux, ry, rz restringidos em TODOS os nós.
    #    O solver é sempre 3D; uma barra isolada neste plano (variando só Y
    #    e Z) não tem rigidez nenhuma fora dele -- ux (translação global X,
    #    perpendicular ao plano), ry e rz (rotações fora do plano) ficam sem
    #    barra nenhuma que os resista, e o sistema fica singular (mecanismo)
    #    nessas direções. É o mesmo que o elemento de pórtico bidimensional
    #    do ANSYS (BEAM3, só 3 GDL/nó: ux-no-plano, uy-no-plano, rz-no-plano)
    #    faz por definição, replicado aqui restringindo as direções de fora
    #    do plano em vez de usar um elemento 2D nativo.
    for iy in range(NY):
        for iz in range(N_PAV + 1):
            n = no(ix, iy, iz)
            if iz == 0:
                m.apoiar(n)   # térreo: engaste total (inclui ux, ry, rz)
            else:
                m.apoiar(n, ux=True, uy=False, uz=False,
                        rx=False, ry=True, rz=True)

    # -- massa: parede nas vigas do próprio pórtico + tributário de laje -----
    # As lajes adjacentes a este pórtico (vãos de 6x6 m, quadrados) são
    # repassadas às vigas Y do próprio pórtico por um cálculo de área de
    # influência feito à mão (ver ``carga_tributaria_laje_quadrada`` abaixo)
    # -- o mecanismo ``Laje``/``aplicar_lajes`` do core precisa das 4 vigas
    # de contorno do painel (inclusive as de X, que não existem neste
    # modelo reduzido, por desenho: ele é só o plano Y-Z de X = 12 m), então
    # não dá para chamá-lo direto aqui. A conta reproduz a MESMA fórmula de
    # ``lajes.distribuir`` (quinhão = q·lx·(2·Le−lx)/4) para os dois painéis
    # adjacentes (a leste e a oeste da linha de pilares, ambos 6x6 m,
    # quadrados), somados na mesma viga Y -- ver a nota no relatório sobre
    # método 1 x método 2 coincidirem, exatamente por os painéis serem
    # quadrados.
    massa = m.add_caso("MASSA", natureza="permanente")
    for piso in range(1, N_PAV + 1):
        permanente = revestimento_do_piso(piso)
        carga_area = ESPESSURA_LAJE * GAMA_CONCRETO + permanente
        for iy in range(NY - 1):
            barra = f"VY_{iy}-{iy+1}_P{piso}"
            massa.distribuida(barra, qz=-PESO_PAREDE_KN_M, sistema="global")
            carga_tributaria_laje_quadrada(massa, barra, carga_area,
                                           vao=YS[iy + 1] - YS[iy],
                                           n_paineis_adjacentes=2)

    return m


def carga_tributaria_laje_quadrada(caso, barra: str, carga_area: float,
                                   vao: float,
                                   n_paineis_adjacentes: int) -> None:
    """Carga triangular (0 nas pontas, pico no meio do vão) que um painel de
    laje QUADRADO de lado ``vao`` repassa a uma viga de contorno, pela mesma
    fórmula de ``lajes.distribuir`` -- aqui aplicada à mão porque a viga não
    tem as 4 vigas de contorno reais do painel neste modelo reduzido (só o
    plano Y-Z existe). Para painel quadrado ``menor == Le == vao``, o
    quinhão cai exatamente no triângulo: ``carga_area * vao² / 4``, pico
    ``carga_area * vao / 2`` no meio do vão -- e ``n_paineis_adjacentes``
    soma a contribuição de quantos painéis compartilham esta viga (2 para
    uma viga interna, com painel dos dois lados).
    """
    pico_um_painel = carga_area * vao / 2.0   # kN/m, no meio do vão
    pico = n_paineis_adjacentes * pico_um_painel
    # Triângulo inteiro: rampa de subida (0 -> meio) E rampa de descida
    # (meio -> fim) -- faltava a segunda metade, que deixava zero de carga
    # do meio do vão em diante e aplicava só metade da força total do
    # painel (achado ao conferir o resultado contra ``lajes.distribuir``,
    # que sempre fecha as duas rampas, mesmo quando o patamar do meio
    # desaparece para painel quadrado).
    caso.distribuida(barra, qz=0.0, qz_fim=-pico, inicio=0.0, fim=0.5,
                     sistema="global")
    caso.distribuida(barra, qz=-pico, qz_fim=0.0, inicio=0.5, fim=1.0,
                     sistema="global")
    caso.distribuida(barra, qz=-pico, qz_fim=0.0, inicio=0.5, fim=1.0,
                     sistema="global")


# ---------------------------------------------------------------------------
# Execução e confronto
# ---------------------------------------------------------------------------

ALVO_ESPACIAL = (0.3529, 1.0815, 1.8920)           # Simulação 1
ALVO_PLANO_METODO_1 = (0.3434, 1.0591, 1.8609)      # Simulação 2
ALVO_PLANO_METODO_2 = (0.3435, 1.0594, 1.8620)      # Simulação 5


def imprimir_comparacao(titulo: str, calculados, alvos) -> None:
    print(f"\n{titulo}")
    print(f"  {'modo':>5}  {'calculado (Hz)':>16}  {'publicado (Hz)':>16}  "
          f"{'erro (%)':>9}")
    for k, (f_calc, alvo) in enumerate(zip(calculados, alvos), start=1):
        erro = 100.0 * (f_calc - alvo) / alvo
        print(f"  {k:>5}  {f_calc:>16.4f}  {alvo:>16.4f}  {erro:>+8.2f}%")


def rodar_espacial() -> list[float]:
    modelo, meta = montar_predio_3d()

    n_nos_esp = meta["n_nos_esperado"]
    n_barras_esp = (meta["n_pilares_esperado"] + meta["n_vigas_x_esperado"]
                    + meta["n_vigas_y_esperado"])
    if len(modelo.nos) != n_nos_esp or len(modelo.barras) != n_barras_esp:
        raise RuntimeError(
            f"malha fora do esperado: {len(modelo.nos)} nós / "
            f"{len(modelo.barras)} barras, esperado {n_nos_esp} / "
            f"{n_barras_esp}")
    modelo.validar()
    print(f"Pórtico espacial: malha OK -- {len(modelo.nos)} nós, "
          f"{len(modelo.barras)} barras, {len(modelo.lajes)} lajes "
          f"(esperado {n_nos_esp} / {n_barras_esp} / "
          f"{(NX - 1) * (NY - 1) * N_PAV})")

    modal = analisar_modal(modelo, n_modos=3, casos_de_massa=("MASSA",))
    imprimir_comparacao("Simulação 1 -- pórtico espacial (sem alvenaria)",
                       modal.frequencias, ALVO_ESPACIAL)
    return modal.frequencias


def rodar_plano() -> list[float]:
    modelo = montar_portico_plano()

    n_nos_esp = NY * (N_PAV + 1)
    n_pilares_esp = NY * N_PAV
    n_vigas_esp = (NY - 1) * N_PAV
    n_barras_esp = n_pilares_esp + n_vigas_esp
    if len(modelo.nos) != n_nos_esp or len(modelo.barras) != n_barras_esp:
        raise RuntimeError(
            f"malha fora do esperado: {len(modelo.nos)} nós / "
            f"{len(modelo.barras)} barras, esperado {n_nos_esp} / "
            f"{n_barras_esp}")
    modelo.validar()
    print(f"\nPórtico plano (P3-P8-P13): malha OK -- {len(modelo.nos)} nós, "
          f"{len(modelo.barras)} barras (esperado {n_nos_esp} / "
          f"{n_barras_esp})")

    modal = analisar_modal(modelo, n_modos=3, casos_de_massa=("MASSA",))

    # Método 1 (carga nas vigas do próprio pórtico + tributário simples) e
    # método 2 (charneiras/área de influência) coincidem neste programa --
    # ver docstring de ``montar_portico_plano``: os painéis são quadrados, e
    # a fórmula de área de influência cai no mesmo triângulo que o rateio
    # "tributário simples" daria. Um modelo só, confrontado com os dois
    # alvos do documento (que também quase coincidem entre si, <0,1%).
    imprimir_comparacao(
        "Simulação 2 -- pórtico plano, massa método 1 (mesmo modelo -- ver "
        "nota sobre método 1 = método 2 nesta geometria)",
        modal.frequencias, ALVO_PLANO_METODO_1)
    imprimir_comparacao(
        "Simulação 5 -- pórtico plano, massa método 2 (charneiras -- mesmo "
        "modelo que a Simulação 2, ver nota)",
        modal.frequencias, ALVO_PLANO_METODO_2)
    return modal.frequencias


def main() -> None:
    print("Nascimento (TCC UFSM, 2025) -- edifício de 12 pavimentos, SEM "
          "alvenaria participante\n")
    print(f"E(C40_pilar) = {MATERIAIS['C40_pilar'][0]:.4e} kN/m²   "
          f"E(C40_viga) = {MATERIAIS['C40_viga'][0]:.4e} kN/m²")
    print(f"E(C25_pilar) = {MATERIAIS['C25_pilar'][0]:.4e} kN/m²   "
          f"E(C25_viga) = {MATERIAIS['C25_viga'][0]:.4e} kN/m²")
    print(f"peso específico (concreto) = {GAMA_CONCRETO:.6f} kN/m³")
    print(f"parede = {PESO_PAREDE_KN_M:.4f} kN/m   "
          f"revestimento = {REVESTIMENTO_KN_M2:.6f} kN/m²   "
          f"telhado (cobertura) = {TELHADO_COBERTURA_KN_M2:.6f} kN/m²")

    rodar_espacial()
    rodar_plano()


if __name__ == "__main__":
    main()
