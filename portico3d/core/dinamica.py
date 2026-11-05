# -*- coding: utf-8 -*-
"""
dinamica.py
Análise modal: frequências naturais e modos de vibração livre, sem
amortecimento, sem histórico no tempo e sem espectro de resposta sísmica.

A mecânica é a mesma de ``segunda_ordem.flambagem``: um problema de
autovalor montado por barra e espalhado pelos mesmos graus de liberdade da
rigidez elástica. A diferença está em que matriz entra no lugar de ``Kg`` —
aqui é a matriz de massa consistente — e em como o problema é bem posto: a
flambagem troca o sinal de ``Kg`` porque ela não é positiva definida sozinha;
aqui ``M`` já nasce positiva definida (é energia cinética, nunca negativa), e
o problema ``Ke·φ = ω²·M·φ`` vai direto ao ``scipy.linalg.eigh(Ke, M)`` sem
nenhuma troca de sinal.

Escopo desta rodada — três simplificações assumidas de propósito, e não por
descuido:

* **Massa sem Timoshenko.** A matriz consistente é a de Euler-Bernoulli pura
  (McGuire/Logan, cap. 16.6); ela não usa ``phi_y``/``phi_z``, mesmo quando a
  seção declara área de cisalhamento e a rigidez elástica já os usa. É a
  simplificação padrão de quem faz massa consistente sem Timoshenko — difere
  da rigidez elástica, que aqui já tem a correção.
* **Massa própria, mais massa adicional por caso de carga quando pedida.**
  Por padrão a massa que entra no problema é só a das barras —
  ``peso_especifico/g`` vezes o volume de cada uma —, pela matriz consistente
  de cada barra. Quando ``analisar_modal`` recebe ``casos_de_massa``, a massa
  de cada caso ali listado entra também — ver ``massa_adicional_global``: é
  peso (de casos de carga já existentes no modelo, como o peso de um
  tabuleiro) convertido em massa por ``F/g``, não uma entidade de dados nova.
  Isso ainda não é a massa sísmica da NBR 15421 (que pede uma fração do
  acidental, não o permanente inteiro) — essa regra composta fica para quando
  houver espectro de resposta —, mas a peça que faltava (peso virar massa)
  já está pronta e é reaproveitável para ela.
* **Sem trecho rígido pesado.** A massa de cada barra é calculada sobre o vão
  flexível ``Lf``, do mesmo jeito que a rigidez elástica e a geométrica já
  fazem — a massa que fisicamente estaria no trecho rígido (que é desenho, não
  peça) não entra à parte. Em trecho rígido típico (frações pequenas do vão)
  o efeito é desprezível; em trecho rígido dominante seria preciso somar a
  massa do braço, o que esta rodada não faz.
* **Rótulas não mudam a massa.** Uma liberação de grau de liberdade
  (``Barra.liberacoes_i``/``liberacoes_j``) solta a rigidez naquela
  extremidade, mas a inércia continua acoplada nos doze graus locais da
  matriz consistente — rótula é uma condição de esforço nulo, não de massa
  nula.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.linalg import eigh

from .modelo import ErroDeModelo, Material, Modelo, Secao
from .montagem import (Montador, base_de_calculo, cargas_locais, esparsa,
                       matriz_global, preparar_barras, usa_grelha,
                       vetor_cargas)

#: Aceleração da gravidade padrão, m/s². Não há constante de gravidade
#: declarada em nenhum outro lugar do ``core``: ``cargas.peso_proprio`` usa
#: ``peso_especifico`` direto como força por volume (kN/m³), sem precisar de
#: ``g`` — ali o peso específico já é a grandeza que entra na carga. Aqui, ao
#: contrário, a massa é o que entra no autovalor, e densidade de massa
#: (kN·s²/m⁴) é ``peso_especifico/g``.
GRAVIDADE = 9.80665


def massa_local(L: float, material: Material, secao: Secao) -> np.ndarray:
    """Matriz de massa consistente 12×12 nos eixos locais de uma barra.

    Decomposta pela mesma família de graus de liberdade que
    ``elemento.rigidez_local`` usa — axial, torção, flexão x–y (Iz), flexão
    x–z (Iy) —, inclusive a mesma troca de sinal entre os dois planos de
    flexão nos termos de acoplamento translação–rotação (``θy = -dw/dx``).
    """
    rho = material.peso_especifico / GRAVIDADE
    A = secao.A
    m = np.zeros((12, 12))

    # Axial: ρAL/6 · [[2,1],[1,2]].
    ma = rho * A * L / 6.0
    m[0, 0] = m[6, 6] = 2.0 * ma
    m[0, 6] = m[6, 0] = ma

    # Torção: a mesma forma, com a inércia de massa polar por comprimento —
    # ρ·(Iy+Iz), o momento polar de área vezes densidade, e não ``J`` (que é
    # a constante de torção de Saint-Venant, grandeza de rigidez, não de
    # massa).
    mt = rho * (secao.Iy + secao.Iz) * L / 6.0
    m[3, 3] = m[9, 9] = 2.0 * mt
    m[3, 9] = m[9, 3] = mt

    coef = rho * A * L / 420.0
    L2 = L * L

    # Flexão x–y (v, θz), índices 1, 5, 7, 11 — plano de referência, sem
    # troca de sinal, igual à ``rigidez_local``.
    idx_xy = (1, 5, 7, 11)
    m[np.ix_(idx_xy, idx_xy)] = coef * np.array([
        [156.0, 22.0 * L, 54.0, -13.0 * L],
        [22.0 * L, 4.0 * L2, 13.0 * L, -3.0 * L2],
        [54.0, 13.0 * L, 156.0, -22.0 * L],
        [-13.0 * L, -3.0 * L2, -22.0 * L, 4.0 * L2],
    ])

    # Flexão x–z (w, θy), índices 2, 4, 8, 10 — os termos de acoplamento
    # translação-rotação (os que multiplicam L, não L²) trocam de sinal em
    # relação ao plano x–y; os de translação-translação e rotação-rotação
    # (156, 54, 4L², -3L²) não trocam. É a mesma troca que
    # ``rigidez_local``/``rigidez_geometrica`` já fazem entre os dois planos.
    idx_xz = (2, 4, 8, 10)
    m[np.ix_(idx_xz, idx_xz)] = coef * np.array([
        [156.0, -22.0 * L, 54.0, 13.0 * L],
        [-22.0 * L, 4.0 * L2, -13.0 * L, -3.0 * L2],
        [54.0, -13.0 * L, 156.0, 22.0 * L],
        [13.0 * L, -3.0 * L2, 22.0 * L, 4.0 * L2],
    ])

    return m


def matriz_massa_global(modelo: Modelo,
                        preparadas: dict) -> np.ndarray:
    """Monta a matriz de massa global, barra a barra.

    Mesma transformação e mesmo espalhamento que
    ``segunda_ordem.matriz_geometrica_global`` usa para a rigidez
    geométrica: ``p.TH.T @ m_local @ p.TH``, espalhada pelos graus de
    liberdade de ``p.gdl``. Ao contrário da rigidez geométrica, toda barra
    com massa declarada entra — não há um ``if`` de "esforço nulo não
    contribui", porque a massa de uma barra não depende de carga nenhuma.
    """
    montador = Montador(modelo.n_gdl, esparsa(modelo))
    for p in preparadas.values():
        m_local = massa_local(p.Lf, p.material, p.secao)
        montador.somar(p.gdl, p.TH.T @ m_local @ p.TH)
    return montador.matriz()


def massa_adicional_global(modelo: Modelo, preparadas: dict,
                           casos: tuple[str, ...]) -> np.ndarray:
    """Massa extra (kN·s²/m) vinda de casos de carga tratados como peso.

    Para cada nó, toma a componente Fz do vetor de cargas equivalente do
    caso (``montagem.vetor_cargas``) — é a componente na direção da
    gravidade — e divide por ``GRAVIDADE`` para achar a massa que aquele
    peso representa. A massa não tem direção: o mesmo valor escalar entra
    nos três graus de translação (ux, uy, uz) do nó, não só em uz — é
    assim que massa concentrada entra num autovalor de vibração livre em
    qualquer direção. Os graus de rotação não ganham inércia nenhuma
    (hipótese comum para massa não-estrutural sem inércia rotacional
    conhecida; documentado, não escondido).

    Segue a convenção de ``cargas.peso_proprio``: peso é carga em **-Z**
    global, então a componente Fz do vetor de cargas equivalente sai
    negativa para peso para baixo, e a massa (sempre não negativa num
    caso bem-formado) é ``-Fz/GRAVIDADE``.
    """
    montador = Montador(modelo.n_gdl, esparsa(modelo))
    for nome_caso in casos:
        if nome_caso not in modelo.casos:
            raise ErroDeModelo(
                f"caso de carga '{nome_caso}' não existe: não há como "
                "tirar massa adicional dele")
        caso = modelo.casos[nome_caso]
        segmentos = cargas_locais(caso, preparadas)
        P = vetor_cargas(modelo, caso, preparadas, segmentos)
        for no in modelo.nos:
            gdl = modelo.gdl(no)
            massa_no = -P[gdl[2]] / GRAVIDADE
            montador.somar_diagonal(gdl[:3], [massa_no] * 3)
    return montador.matriz()


@dataclass
class Modal:
    """Frequências, períodos e modos de vibração livre."""

    frequencias: list[float]           # Hz
    periodos: list[float]              # s
    modos: list[np.ndarray] = field(default_factory=list)
    modelo: Modelo | None = None

    @property
    def frequencia_fundamental(self) -> float:
        return self.frequencias[0]

    @property
    def periodo_fundamental(self) -> float:
        return self.periodos[0]

    def modo(self, indice: int = 0) -> dict[str, np.ndarray]:
        """O modo de vibração, nó a nó, normalizado pelo maior deslocamento."""
        if self.modelo is None:
            raise ErroDeModelo("modo de vibração sem modelo associado")
        vetor = self.modos[indice]
        pico = float(np.max(np.abs(vetor))) or 1.0
        return {no: vetor[self.modelo.gdl(no)] / pico
                for no in self.modelo.nos}

    def __str__(self) -> str:
        linhas = [f"  modo {i + 1}: f = {f:8.4f} Hz   T = {t:7.4f} s"
                  for i, (f, t) in enumerate(zip(self.frequencias,
                                                 self.periodos))]
        return "análise modal — massa própria da estrutura:\n" + "\n".join(linhas)


def analisar_modal(modelo: Modelo, n_modos: int = 6,
                   casos_de_massa: tuple[str, ...] = ()) -> Modal:
    """Frequências e modos naturais, resolvendo ``Ke·φ = ω²·M·φ``.

    Não depende de caso de carga para a rigidez: é vibração livre. A massa
    considerada é sempre a própria da estrutura (ver escopo no topo do
    módulo) e, quando ``casos_de_massa`` não é vazio, soma também a massa
    adicional desses casos de carga — ver ``massa_adicional_global``. Com
    ``casos_de_massa`` vazio (o padrão) o resultado é bit a bit igual ao de
    antes desta capacidade existir.

    Resolvido direto nos graus de liberdade livres com
    ``scipy.linalg.eigh(Ke, M)`` — sem a troca de sinal que
    ``segunda_ordem.flambagem`` precisa, porque aqui ``M`` já é positiva
    definida (toda barra com peso específico maior que zero contribui com
    massa real, nunca negativa, e a massa adicional, bem-formada, soma na
    mesma direção).
    """
    modelo.validar()
    if usa_grelha(modelo):
        from .grelha import modal_com_grelha
        return modal_com_grelha(modelo, n_modos, casos_de_massa)

    preparadas = preparar_barras(modelo)
    Ke = matriz_global(modelo, preparadas)
    M = matriz_massa_global(modelo, preparadas)
    if casos_de_massa:
        M = M + massa_adicional_global(modelo, preparadas, casos_de_massa)
    base = base_de_calculo(modelo)

    if base.m == 0:
        raise ErroDeModelo(
            "estrutura sem grau de liberdade livre: não há o que vibrar")

    sem_massa = [nome for nome, barra in modelo.barras.items()
                 if modelo.materiais[barra.material].peso_especifico == 0.0]
    if len(sem_massa) == len(modelo.barras) and not casos_de_massa:
        raise ErroDeModelo(
            "nenhuma barra tem peso específico declarado: sem massa não há "
            "frequência nenhuma a calcular")

    Kff = base.reduzir(Ke)
    Mff = base.reduzir(M)

    if sp.issparse(Kff):
        # Lanczos com deslocamento em zero aceita massa singular: o grau sem
        # massa vira autovalor infinito, que ele não procura. A condensação
        # só é preciso no caminho denso, em que ``eigh`` exige M definida.
        recuperar = None
        n = min(n_modos, Kff.shape[0] - 1)
        try:
            omega2, vetores = _modos_esparsos(Kff, Mff, n)
        except Exception:                       # ARPACK não convergiu
            # Sistema pequeno e quase todo sem massa é onde o Lanczos
            # desanda; aí vale o caminho denso, com a condensação.
            Kff, Mff, recuperar = _condensar_sem_massa(Kff, Mff)
            if sp.issparse(Kff):
                Kff, Mff = Kff.toarray(), Mff.toarray()
            n = min(n_modos, Kff.shape[0])
            omega2, vetores = eigh(Kff, Mff)
    else:
        Kff, Mff, recuperar = _condensar_sem_massa(Kff, Mff)
        n = min(n_modos, Kff.shape[0])
        omega2, vetores = eigh(Kff, Mff)
    # ``eigh`` devolve em ordem crescente — é a ordem de interesse aqui
    # (frequências baixas primeiro), ao contrário da flambagem, que precisa
    # inverter a ordem do seu autovalor ``μ``.
    omega2 = np.clip(omega2[:n], 0.0, None)
    omega = np.sqrt(omega2)
    frequencias = (omega / (2.0 * math.pi)).tolist()
    periodos = [1.0 / f if f > 0.0 else math.inf for f in frequencias]

    modos = []
    for i in range(n):
        vetor = vetores[:, i] if recuperar is None else recuperar(vetores[:, i])
        modos.append(base.expandir(vetor))

    return Modal(frequencias, periodos, modos, modelo)


def _condensar_sem_massa(K, M):
    """Condensação estática dos graus sem massa nenhuma.

    Grau sem massa não tem inércia: no modo de vibração ele só acompanha os
    outros, ``φ₀ = −K₀₀⁻¹·K₀ₘ·φₘ``, e a rigidez que sobra para os graus com
    massa é ``Kₘₘ − Kₘ₀·K₀₀⁻¹·K₀ₘ``. É exata, não aproximação. Aparece na laje
    em grelha: as barras da laje não pesam (o peso dela é carga, e vira massa
    só por ``casos_de_massa``), e os nós internos ficariam com a matriz de
    massa singular. Sem grau sem massa, devolve tudo como veio.
    """
    diagonal = M.diagonal() if sp.issparse(M) else np.diag(M)
    maior = float(np.max(np.abs(diagonal))) if diagonal.size else 0.0
    sem = np.abs(diagonal) <= 1.0e-14 * maior
    if maior == 0.0 or not sem.any():
        return K, M, lambda v: v

    zero, com = np.flatnonzero(sem), np.flatnonzero(~sem)
    if sp.issparse(K):
        from scipy.sparse.linalg import splu
        K = K.tocsr()
        K00 = K[zero][:, zero].tocsc()
        K0m = K[zero][:, com].toarray()
        Kmm = K[com][:, com].toarray()
        Mmm = M.tocsr()[com][:, com].toarray()
        try:
            X = splu(K00).solve(K0m)
        except RuntimeError:
            raise ErroDeModelo(
                "modal: os graus sem massa formam mecanismo entre si")                 from None
    else:
        K00 = K[np.ix_(zero, zero)]
        K0m = K[np.ix_(zero, com)]
        Kmm = K[np.ix_(com, com)]
        Mmm = M[np.ix_(com, com)]
        try:
            X = np.linalg.solve(K00, K0m)
        except np.linalg.LinAlgError:
            raise ErroDeModelo(
                "modal: os graus sem massa formam mecanismo entre si")                 from None
    Kc = Kmm - K0m.T @ X
    Kc = (Kc + Kc.T) / 2.0
    n = len(diagonal)

    def recuperar(v):
        cheio = np.zeros(n)
        cheio[com] = v
        cheio[zero] = -X @ v
        return cheio

    return Kc, Mmm, recuperar


def _modos_esparsos(K, M, n: int):
    """Os ``n`` menores autovalores de ``K·φ = ω²·M·φ``, por Lanczos com
    deslocamento em zero — só os modos pedidos, e não o espectro inteiro."""
    from scipy.sparse.linalg import eigsh

    k = max(1, min(n, K.shape[0] - 1))
    omega2, vetores = eigsh(K.tocsc(), k=k, M=M.tocsc(), sigma=0.0,
                            which="LM")
    ordem = np.argsort(omega2)
    return omega2[ordem], vetores[:, ordem]
