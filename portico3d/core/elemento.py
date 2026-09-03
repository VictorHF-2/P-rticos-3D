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
