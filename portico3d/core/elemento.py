# -*- coding: utf-8 -*-
"""
elemento.py
Elemento de pórtico espacial de dois nós e doze graus de liberdade.

Formulação de Euler-Bernoulli (sem deformação por cortante), com rigidez
axial, torção de Saint-Venant e flexão nos dois planos principais. É a mesma
formulação do capítulo de análise matricial de McGuire, Gallagher e Ziemian,
que está por trás do MASTAN2.

Ordem dos graus de liberdade locais:

    0 u1   1 v1   2 w1   3 θx1   4 θy1   5 θz1
    6 u2   7 v2   8 w2   9 θx2  10 θy2  11 θz2

Eixos locais: x da barra vai do nó inicial ao final; y e z são os eixos
principais da seção. Para barras não verticais o eixo local z aponta para
cima (fica no plano vertical que contém a barra), de modo que a carga de
gravidade flete a barra em torno do eixo local y. Para barras verticais o
eixo local y aponta na direção do X global e o z na direção do Y global.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .modelo import Barra, ErroDeModelo, Material, Modelo, Secao

# Uma barra é tratada como vertical quando o seno do ângulo entre o seu eixo
# e o eixo Z global cai abaixo disso — aí o vetor de referência padrão troca.
TOL_VERTICAL = 1.0e-3


def vetor_referencia_padrao(ex: np.ndarray) -> np.ndarray:
    """Vetor auxiliar que, com o eixo da barra, define o plano local x–z."""
    if math.hypot(ex[0], ex[1]) < TOL_VERTICAL:
        return np.array([0.0, 1.0, 0.0])
    return np.array([0.0, 0.0, 1.0])


def matriz_rotacao(pi: np.ndarray, pj: np.ndarray, rotacao: float = 0.0,
                   vetor_ref: tuple[float, float, float] | None = None
                   ) -> np.ndarray:
    """Matriz 3×3 cujas linhas são os eixos locais escritos no sistema global."""
    d = pj - pi
    L = float(np.linalg.norm(d))
    if L <= 0.0:
        raise ErroDeModelo("barra de comprimento nulo")
    ex = d / L

    vr = (np.array(vetor_ref, float) if vetor_ref is not None
          else vetor_referencia_padrao(ex))
    ey = np.cross(vr, ex)
    n = float(np.linalg.norm(ey))
    if n < 1.0e-8:
        raise ErroDeModelo(
            "vetor de referência paralelo ao eixo da barra: "
            "não define o plano dos eixos locais")
    ey /= n
    ez = np.cross(ex, ey)

    R = np.vstack([ex, ey, ez])
    if rotacao:
        a = math.radians(rotacao)
        c, s = math.cos(a), math.sin(a)
        R = np.array([[1.0, 0.0, 0.0],
                      [0.0, c, s],
                      [0.0, -s, c]]) @ R
    return R


def matriz_transformacao(R: np.ndarray) -> np.ndarray:
    """Espalha a rotação 3×3 nos quatro blocos dos doze graus de liberdade."""
    T = np.zeros((12, 12))
    for k in range(4):
        T[3 * k:3 * k + 3, 3 * k:3 * k + 3] = R
    return T


def fatores_cortante(L: float, material: Material,
                     secao: Secao) -> tuple[float, float]:
    """Os dois Φ de Timoshenko, um por plano de flexão.

        Φ = 12·E·I / (G·As·L²)

    ``Φ`` é a razão entre a flexibilidade ao cisalhamento e a de flexão: vale
    zero quando a área de cisalhamento não foi declarada, e aí toda a
    formulação recai em Euler-Bernoulli. Cresce com o quadrado da relação
    altura/vão, e é por isso que só pesa em peça baixa e alta.

    O primeiro valor é o do plano x–y, que combina ``Iz`` com ``Asy``; o
    segundo é o do plano x–z, que combina ``Iy`` com ``Asz``. Trocar os dois é
    o erro fácil aqui: a inércia e a área de cisalhamento de um mesmo plano
    levam índices diferentes.
    """
    phi_y = (12.0 * material.E * secao.Iz / (material.G * secao.Asy * L ** 2)
             if secao.Asy > 0.0 else 0.0)
    phi_z = (12.0 * material.E * secao.Iy / (material.G * secao.Asz * L ** 2)
             if secao.Asz > 0.0 else 0.0)
    return phi_y, phi_z


def rigidez_local(L: float, material: Material, secao: Secao) -> np.ndarray:
    """Matriz de rigidez 12×12 nos eixos locais.

    Com área de cisalhamento declarada na seção, a flexão é a de Timoshenko;
    sem ela, a de Euler-Bernoulli. As duas são a mesma expressão: os termos de
    flexão ganham o divisor ``(1+Φ)`` e os da diagonal de rotação passam de 4
    e 2 para ``(4+Φ)`` e ``(2−Φ)``, o que devolve exatamente a formulação
    clássica quando ``Φ`` é nulo.
    """
    E, G = material.E, material.G
    A, Iy, Iz, J = secao.A, secao.Iy, secao.Iz, secao.J
    phi_y, phi_z = fatores_cortante(L, material, secao)

    k = np.zeros((12, 12))

    # Axial
    ea = E * A / L
    k[0, 0] = k[6, 6] = ea
    k[0, 6] = k[6, 0] = -ea

    # Torção
    gj = G * J / L
    k[3, 3] = k[9, 9] = gj
    k[3, 9] = k[9, 3] = -gj

    # Flexão no plano x–y (deslocamento v, rotação θz, inércia Iz)
    a = 12.0 * E * Iz / (L ** 3 * (1.0 + phi_y))
    b = 6.0 * E * Iz / (L ** 2 * (1.0 + phi_y))
    c = (4.0 + phi_y) * E * Iz / (L * (1.0 + phi_y))
    d = (2.0 - phi_y) * E * Iz / (L * (1.0 + phi_y))
    k[1, 1] = k[7, 7] = a
    k[1, 7] = k[7, 1] = -a
    k[1, 5] = k[5, 1] = k[1, 11] = k[11, 1] = b
    k[5, 7] = k[7, 5] = k[7, 11] = k[11, 7] = -b
    k[5, 5] = k[11, 11] = c
    k[5, 11] = k[11, 5] = d

    # Flexão no plano x–z (deslocamento w, rotação θy, inércia Iy).
    # Os sinais trocam em relação ao plano x–y porque θy = -dw/dx.
    a = 12.0 * E * Iy / (L ** 3 * (1.0 + phi_z))
    b = 6.0 * E * Iy / (L ** 2 * (1.0 + phi_z))
    c = (4.0 + phi_z) * E * Iy / (L * (1.0 + phi_z))
    d = (2.0 - phi_z) * E * Iy / (L * (1.0 + phi_z))
    k[2, 2] = k[8, 8] = a
    k[2, 8] = k[8, 2] = -a
    k[2, 4] = k[4, 2] = k[2, 10] = k[10, 2] = -b
    k[4, 8] = k[8, 4] = k[8, 10] = k[10, 8] = b
    k[4, 4] = k[10, 10] = c
    k[4, 10] = k[10, 4] = d

    return k


def rigidez_geometrica(L: float, N: float, secao: Secao) -> np.ndarray:
    """Matriz de rigidez geométrica 12×12 nos eixos locais.

    ``N`` é o esforço normal da barra, **positivo à tração**. A matriz é a
    consistente, deduzida das mesmas cúbicas de Hermite da rigidez elástica —
    o que dá o efeito de segunda ordem dentro da barra, e não apenas o P-Δ dos
    nós, mas exige malha para convergir: uma barra por pilar erra a carga
    crítica de Euler em cerca de 0,8 %, e duas já reduzem isso a menos de 0,1 %.

    Somada à rigidez elástica, ela enrijece a barra tracionada e amolece a
    comprimida, que é o efeito que se quer representar.

    **A recuperação do esforço tem de somar esta matriz, não só a elástica.**
    Um confronto com o PyNiteFEA no caso da viga-coluna em balanço (P a 50 %
    da crítica) achou o deslocamento do topo batendo a 13 algarismos com uma
    barra só — ``Ke + Kg`` e a iteração estavam certas —, mas o **momento
    recuperado na extremidade** errando a solução fechada em 6,6 %. A causa
    não era a malha: ``segunda_ordem._esforcos_das_barras`` recuperava o
    esforço só com ``Ke·D``, sem somar esta ``Kg`` que tinha corrigido o
    deslocamento. Somada — ``(Ke + Kg)·D`` —, o erro já cai para 0,13 % sem
    mexer em malha nenhuma; ver ``rigidez_geometrica_refinada`` (abaixo, neste
    módulo) para o resíduo que sobra, esse sim de malha, e que a condensação estática
    de sub-elementos resolve por dentro do cálculo, sem o usuário precisar
    desenhar mais barra nenhuma. Ver ``validacao.p_delta_confrontado_com_pynite``.
    """
    kg = np.zeros((12, 12))
    if N == 0.0:
        return kg

    c = N / L
    ip_a = (secao.Iy + secao.Iz) / secao.A

    # Torção: raio de giração polar.
    kg[3, 3] = kg[9, 9] = c * ip_a
    kg[3, 9] = kg[9, 3] = -c * ip_a

    # Flexão no plano x–y (v, θz).
    kg[1, 1] = kg[7, 7] = c * 6.0 / 5.0
    kg[1, 7] = kg[7, 1] = -c * 6.0 / 5.0
    kg[1, 5] = kg[5, 1] = kg[1, 11] = kg[11, 1] = c * L / 10.0
    kg[5, 7] = kg[7, 5] = kg[7, 11] = kg[11, 7] = -c * L / 10.0
    kg[5, 5] = kg[11, 11] = c * 2.0 * L ** 2 / 15.0
    kg[5, 11] = kg[11, 5] = -c * L ** 2 / 30.0

    # Flexão no plano x–z (w, θy), com a mesma troca de sinal da rigidez
    # elástica, porque θy = -dw/dx.
    kg[2, 2] = kg[8, 8] = c * 6.0 / 5.0
    kg[2, 8] = kg[8, 2] = -c * 6.0 / 5.0
    kg[2, 4] = kg[4, 2] = kg[2, 10] = kg[10, 2] = -c * L / 10.0
    kg[4, 8] = kg[8, 4] = kg[8, 10] = kg[10, 8] = c * L / 10.0
    kg[4, 4] = kg[10, 10] = c * 2.0 * L ** 2 / 15.0
    kg[4, 10] = kg[10, 4] = -c * L ** 2 / 30.0

    return kg


#: Sub-elementos por barra na rigidez geométrica refinada. Convergência
#: medida no caso de referência (viga-coluna em balanço, P a 50 % da
#: crítica, contra a solução fechada), já com a recuperação somando
#: ``Kg`` — ver o docstring de ``rigidez_geometrica`` sobre essa correção,
#: que é a que mais pesa: 1 sub-elemento (ou seja, sem refinar) erra o
#: momento em 0,16 %; 2 em 0,011 %; **4 em 0,0007 %**; 8 em 0,00005 %.
#: Quatro já é indistinguível de exato para qualquer projeto, sem inflar o
#: custo de cada iteração do P-Δ.
SUBDIVISOES_PADRAO = 4


def _bloco_de_flexao(l: float, EI: float, G_As: float, N: float,
                     sinal: float) -> tuple[np.ndarray, np.ndarray]:
    """As 4×4 elástica e geométrica de **um** sub-elemento, num só plano.

    A ordem dos graus é ``(v_i, θ_i, v_j, θ_j)`` do plano. ``sinal`` é ``+1``
    para o plano x–y e ``-1`` para o x–z — a mesma troca de sinal do
    acoplamento v–θ que ``rigidez_local`` e ``rigidez_geometrica`` já fazem
    entre os dois planos, aqui como fator em vez de escrita duas vezes.
    """
    phi = 12.0 * EI / (G_As * l ** 2) if G_As > 0.0 else 0.0
    a = 12.0 * EI / (l ** 3 * (1.0 + phi))
    b = sinal * 6.0 * EI / (l ** 2 * (1.0 + phi))
    c = (4.0 + phi) * EI / (l * (1.0 + phi))
    d = (2.0 - phi) * EI / (l * (1.0 + phi))
    ke = np.array([[a, b, -a, b],
                  [b, c, -b, d],
                  [-a, -b, a, -b],
                  [b, d, -b, c]])

    if N == 0.0:
        return ke, np.zeros((4, 4))
    cg = N / l
    bg = sinal * cg * l / 10.0
    kg = np.array([[cg * 6.0 / 5.0, bg, -cg * 6.0 / 5.0, bg],
                  [bg, cg * 2.0 * l ** 2 / 15.0, -bg, -cg * l ** 2 / 30.0],
                  [-cg * 6.0 / 5.0, -bg, cg * 6.0 / 5.0, -bg],
                  [bg, -cg * l ** 2 / 30.0, -bg, cg * 2.0 * l ** 2 / 15.0]])
    return ke, kg


def _condensar_cadeia(L: float, EI: float, G_As: float, N: float,
                      sinal: float, n_sub: int, com_kg: bool) -> np.ndarray:
    """A 4×4 de um plano de flexão, condensada de uma cadeia de ``n_sub``
    sub-elementos aos dois nós de ponta — estática, exata dado o ``n_sub``.

    Com ``n_sub == 1`` não há nó interno e a "condensação" é a própria matriz
    do sub-elemento único, que é a barra inteira: por construção, esta função
    com ``n_sub=1`` e ``com_kg=True`` reproduz bit a bit o bloco do plano na
    ``rigidez_local``/``rigidez_geometrica`` de hoje.
    """
    l = L / n_sub
    ngl = 2 * (n_sub + 1)
    K = np.zeros((ngl, ngl))
    for e in range(n_sub):
        ke, kg = _bloco_de_flexao(l, EI, G_As, N, sinal)
        bloco = ke + kg if com_kg else ke
        i0 = 2 * e
        K[i0:i0 + 4, i0:i0 + 4] += bloco

    externos = [0, 1, ngl - 2, ngl - 1]
    internos = [i for i in range(ngl) if i not in externos]
    if not internos:
        return K
    Kee = K[np.ix_(externos, externos)]
    Kei = K[np.ix_(externos, internos)]
    Kie = K[np.ix_(internos, externos)]
    Kii = K[np.ix_(internos, internos)]
    return Kee - Kei @ np.linalg.solve(Kii, Kie)


def rigidez_geometrica_refinada(L: float, N: float, material: Material,
                                secao: Secao,
                                n_sub: int = SUBDIVISOES_PADRAO) -> np.ndarray:
    """A rigidez geométrica 12×12, com os dois planos de flexão refinados.

    ``rigidez_geometrica`` já dá o deslocamento dos nós exato — é o que
    convergiu a 13 algarismos contra o PyNiteFEA mesmo com uma barra só,
    contanto que a recuperação do esforço some esta matriz e não só a
    elástica (ver o docstring dela). O que sobra depois dessa correção é
    menor, mas ainda é real: a curvatura *dentro* da barra (o P-δ) não cabe
    na cúbica de um elemento só, e no caso de referência isso ainda deixava
    o momento recuperado 0,13–0,16 % longe do fechado. Esta função resolve
    esse resíduo. Ela não muda a malha que o usuário vê: subdivide a barra
    **só para montar esta matriz**, condensando os nós internos de volta aos
    dois de sempre pela mesma álgebra exata de subestruturação (Guyan) que
    se usaria se a barra tivesse sido desenhada em pedaços — só que sem os
    pedaços aparecerem em lugar nenhum fora daqui. As duas correções juntas
    deixam o caso de referência a -0,0007 % do fechado, com uma barra só.

    A técnica: ``Kg_efetiva = condensar(Ke_sub + Kg_sub) - condensar(Ke_sub)``.
    Subtrair a condensação de ``Ke`` sozinho (sem geometria) em vez de somar o
    ``Ke`` de sempre é o que torna o resultado exato mesmo que a condensação
    de ``Ke`` isolado não reproduza precisamente o ``Ke`` de um elemento só —
    a diferença cancela qualquer resíduo, e só sobra o que a geometria muda.

    Torção e axial não entram na subdivisão: o docstring de
    ``rigidez_geometrica`` já nota que elas não têm o efeito de curvatura
    interna que a flexão tem — uma cadeia em série de barras idênticas dá,
    condensada, a mesma rigidez que uma peça só, tração ou torção. Os dois
    graus continuam vindo direto da matriz de hoje.
    """
    kg = rigidez_geometrica(L, N, secao)
    if N == 0.0 or n_sub <= 1:
        return kg

    G_Asy = material.G * secao.Asy if secao.Asy > 0.0 else 0.0
    G_Asz = material.G * secao.Asz if secao.Asz > 0.0 else 0.0

    for indices, EI, G_As, sinal in (
            ((1, 5, 7, 11), material.E * secao.Iz, G_Asy, 1.0),
            ((2, 4, 8, 10), material.E * secao.Iy, G_Asz, -1.0)):
        com = _condensar_cadeia(L, EI, G_As, N, sinal, n_sub, com_kg=True)
        sem = _condensar_cadeia(L, EI, G_As, N, sinal, n_sub, com_kg=False)
        efetiva = com - sem
        idx = np.array(indices)
        kg[np.ix_(idx, idx)] = efetiva

    return kg


def matriz_trecho_rigido(offset_i: float, offset_j: float) -> np.ndarray:
    """Leva os deslocamentos dos nós aos das extremidades do vão flexível.

    O trecho rígido é um braço: girar o nó desloca a ponta do vão flexível.
    Para um braço de comprimento ``c`` ao longo do eixo local x, a ponta anda
    ``+c·θz`` em y e ``−c·θy`` em z, e a rotação passa inteira.

    O braço do nó inicial aponta para dentro da barra, ``+offset_i``; o do nó
    final aponta para trás, ``−offset_j``. Sem trechos rígidos a matriz é a
    identidade, e nada no resto do programa precisa saber que ela existe.
    """
    H = np.eye(12)
    for base, c in ((0, offset_i), (6, -offset_j)):
        if c == 0.0:
            continue
        H[base + 1, base + 5] = c
        H[base + 2, base + 4] = -c
    return H


def condensar(k: np.ndarray, liberados: list[int],
              nome: str) -> tuple[np.ndarray, np.ndarray]:
    """Elimina por condensação estática os graus de liberdade soltos.

    Devolve ``(k*, C)``: a rigidez condensada, já de volta ao tamanho 12×12
    com linhas e colunas nulas nas posições liberadas, e a matriz ``C`` que
    corrige o vetor de engastamento perfeito,

        k* = k_cc - k_cr·k_rr⁻¹·k_rc        f* = f_c - k_cr·k_rr⁻¹·f_r

    A rótula não é um artifício de montagem: é a condição de esforço nulo
    naquela extremidade, e a condensação é exatamente o que impõe isso sem
    acrescentar grau de liberdade ao sistema global.
    """
    if not liberados:
        return k, np.eye(12)

    retidos = [i for i in range(12) if i not in liberados]
    krr = k[np.ix_(liberados, liberados)]

    autovalores = np.linalg.eigvalsh(krr)
    if np.min(np.abs(autovalores)) < 1e-12 * np.max(np.abs(autovalores)):
        raise ErroDeModelo(
            f"barra '{nome}': as liberações escolhidas soltam a barra por "
            "inteiro — liberar o mesmo esforço axial ou de torção nas duas "
            "extremidades cria um mecanismo dentro do próprio elemento")

    krc = k[np.ix_(liberados, retidos)]
    kcr = k[np.ix_(retidos, liberados)]
    ponte = kcr @ np.linalg.solve(krr, krc)

    k_condensada = np.zeros((12, 12))
    k_condensada[np.ix_(retidos, retidos)] = k[np.ix_(retidos, retidos)] - ponte

    correcao = np.eye(12)
    correcao[np.ix_(retidos, liberados)] = -kcr @ np.linalg.inv(krr)
    correcao[liberados, :] = 0.0

    return k_condensada, correcao


@dataclass
class BarraPreparada:
    """Tudo o que a barra precisa ter calculado uma única vez por análise.

    Há dois comprimentos: ``L``, de nó a nó, e ``Lf``, o do vão flexível que
    sobra depois de descontados os trechos rígidos. Toda a mecânica do
    elemento — rigidez, engastamento perfeito, diagramas — acontece em ``Lf``.

    Há também duas transformações. ``T`` gira os eixos do global para o local,
    e ``TH`` faz isso e ainda atravessa os braços rígidos, indo do
    deslocamento dos nós ao das extremidades do vão flexível. É ``TH`` que
    entra em tudo que liga o elemento à estrutura; ``T`` sozinha só serve para
    girar direções de carga, que os braços não afetam.

    ``k_local`` já vem condensada pelas liberações, e ``correcao`` é a matriz
    que leva o vetor de engastamento perfeito da barra biengastada ao da barra
    com as rótulas que ela tem.
    """

    barra: Barra
    material: Material
    secao: Secao
    L: float
    R: np.ndarray
    T: np.ndarray
    k_local: np.ndarray
    k_global: np.ndarray
    gdl: list[int]
    correcao: np.ndarray
    liberados: list[int]
    Lf: float = 0.0
    H: np.ndarray = None
    TH: np.ndarray = None
    phi_y: float = 0.0
    phi_z: float = 0.0

    @property
    def tem_trecho_rigido(self) -> bool:
        return self.barra.offset_i != 0.0 or self.barra.offset_j != 0.0

    def engastamento(self, segmentos) -> np.ndarray:
        """Engastamento perfeito da barra, já corrigido pelas liberações.

        Existe como método, e não como chamada solta em cada lugar que
        precisa, porque são três os pontos que a usam — montagem do vetor de
        cargas, recuperação de esforços e segunda ordem — e todos os três têm
        de passar o mesmo comprimento flexível e os mesmos Φ. Esquecer num só
        deles daria uma incoerência silenciosa entre carga e rigidez.
        """
        from .carregamento import forcas_engastamento
        return self.correcao @ forcas_engastamento(
            self.Lf, segmentos, self.phi_y, self.phi_z)


def preparar(modelo: Modelo, barra: Barra) -> BarraPreparada:
    pi = modelo.ponto(barra.no_i)
    pj = modelo.ponto(barra.no_j)
    material = modelo.materiais[barra.material]
    secao = modelo.secoes[barra.secao]

    L = float(np.linalg.norm(pj - pi))
    Lf = L - barra.offset_i - barra.offset_j
    if Lf <= 0.0:
        raise ErroDeModelo(
            f"barra '{barra.nome}': os trechos rígidos consomem todo o vão")

    R = matriz_rotacao(pi, pj, barra.rotacao, barra.vetor_ref)
    T = matriz_transformacao(R)
    H = matriz_trecho_rigido(barra.offset_i, barra.offset_j)
    TH = H @ T

    liberados = barra.graus_liberados
    k_local, correcao = condensar(rigidez_local(Lf, material, secao),
                                  liberados, barra.nome)
    k_global = TH.T @ k_local @ TH
    gdl = modelo.gdl(barra.no_i) + modelo.gdl(barra.no_j)
    phi_y, phi_z = fatores_cortante(Lf, material, secao)

    return BarraPreparada(barra, material, secao, L, R, T, k_local, k_global,
                          gdl, correcao, liberados, Lf, H, TH, phi_y, phi_z)
