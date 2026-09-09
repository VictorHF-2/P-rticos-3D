# -*- coding: utf-8 -*-
"""
analise.py
Análise estrutural da viga contínua pelo método da rigidez direta, com
elementos de barra de Euler-Bernoulli (2 graus de liberdade por nó).

A matriz de rigidez não depende do carregamento; por isso o módulo resolve
uma única vez os casos-base (a ação permanente e a ação variável de cada
tramo, isoladamente) e obtém qualquer combinação por superposição. Isso torna
barato varrer todos os padrões de carregamento alternado da envoltória.

Convenções:
    x .......... coordenada global, m, a partir da extremidade esquerda;
    cargas ..... positivas para baixo;
    V .......... positivo quando a resultante à esquerda da seção é para cima;
    M .......... positivo quando traciona a fibra inferior (momento positivo);
    flecha ..... positiva para baixo, em metros.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .modelo import Viga

DX_MAX = 0.025         # m, comprimento máximo do elemento na discretização
TOL = 1e-9


# ---------------------------------------------------------------------------
# Malha
# ---------------------------------------------------------------------------

@dataclass
class Malha:
    """Discretização da viga em nós e elementos."""

    x_nos: np.ndarray                 # (nn,) coordenadas dos nós, m
    EI: np.ndarray                    # (ne,) rigidez à flexão de cada elemento
    tramo_elem: np.ndarray            # (ne,) índice do tramo de cada elemento
    x_grid: np.ndarray                # (2*ne,) grade de saída dos diagramas
    #: (ne,) índice do **trecho prismático** de cada elemento. O tramo diz de
    #: que vão o elemento faz parte; o trecho diz que seção ele tem, e é dele
    #: que sai o EI. Numa viga prismática os dois coincidem
    trecho_elem: np.ndarray | None = None

    @property
    def n_nos(self) -> int:
        return len(self.x_nos)

    @property
    def n_elem(self) -> int:
        return len(self.EI)

    @property
    def comprimentos(self) -> np.ndarray:
        return np.diff(self.x_nos)


def _pontos_notaveis(viga: Viga) -> list[float]:
    """Coordenadas em que a malha precisa obrigatoriamente ter um nó."""
    pts = list(viga.x_apoios)
    # cada mudança de seção é ponto notável: sem nó ali, um elemento ficaria
    # metade numa seção e metade na outra, e o EI dele sairia da seção do meio
    # do elemento -- uma seção que não existe em lugar nenhum da viga
    for t in viga.trechos:
        pts += [t.x_ini, t.x_fim]
    for i, ap in enumerate(viga.apoios):      # faces dos apoios
        if ap.tipo == "livre":
            continue
        pts += [viga.x_apoios[i] - ap.largura / 200.0,
                viga.x_apoios[i] + ap.largura / 200.0]
    for c in viga.todas_distribuidas():
        pts += [c.x_ini, c.x_fim]
    for p in viga.concentradas:
        pts.append(p.x)
    for m in viga.momentos:
        pts.append(m.x)
    L = viga.comprimento
    pts = [min(max(p, 0.0), L) for p in pts]
    pts = sorted(set(round(p, 6) for p in pts))
    return pts


def gerar_malha(viga: Viga, dx_max: float = DX_MAX,
                inercias: list[float] | None = None) -> Malha:
    """Monta a malha com nós nos pontos notáveis e refino uniforme.

    ``inercias`` permite substituir, **tramo a tramo**, a inércia da seção
    bruta pela inércia equivalente do Estádio II (usada na verificação de
    flecha). Ela continua por tramo porque é isso que o item 17.3.2.1.1 produz:
    uma rigidez equivalente para o vão, a partir do momento e da fissuração
    dele. Onde o tramo tem mais de um trecho, a inércia equivalente do tramo é
    **rateada** entre os trechos na proporção das inércias brutas -- assim o
    trecho mais alto continua mais rígido que o mais baixo dentro do mesmo vão,
    em vez de todos receberem a mesma inércia média.
    """
    pontos = _pontos_notaveis(viga)
    x_nos: list[float] = [pontos[0]]
    for a, b in zip(pontos, pontos[1:]):
        n = max(1, int(np.ceil((b - a) / dx_max - 1e-9)))
        for k in range(1, n + 1):
            x_nos.append(a + (b - a) * k / n)
    x = np.array(x_nos, dtype=float)

    ne = len(x) - 1
    xm = 0.5 * (x[:-1] + x[1:])
    tramo = np.array([viga.tramo_em(v) for v in xm], dtype=int)
    trecho = np.array([viga.trecho_em(v) for v in xm], dtype=int)
    Ecs = viga.concreto.Ecs                       # MPa
    trechos = viga.trechos
    I_trecho = [t.secao.inercia for t in trechos]
    if inercias is not None:
        # a inércia equivalente vem por tramo: rateia-se entre os trechos dele
        # na proporção das inércias brutas, preservando a média ponderada pelo
        # comprimento -- do contrário um tramo de dois trechos teria a mesma
        # rigidez nos dois, e a mudança de seção desapareceria do modelo
        for i in range(len(viga.tramos)):
            do_tramo = [t for t in trechos if t.tramo == i]
            L = sum(t.L for t in do_tramo) or 1.0
            media = sum(I_trecho[t.k] * t.L for t in do_tramo) / L
            fator = (list(inercias)[i] / media) if media > 0 else 1.0
            for t in do_tramo:
                I_trecho[t.k] *= fator
    # EI [kN.m²] = Ecs [MPa] * 1e3 [kN/m²] * I [cm^4] * 1e-8 [m^4]
    EI = np.array([Ecs * I_trecho[t] * 1e-5 for t in trecho])

    x_grid = np.empty(2 * ne)
    x_grid[0::2] = x[:-1]
    x_grid[1::2] = x[1:]
    return Malha(x_nos=x, EI=EI, tramo_elem=tramo, x_grid=x_grid,
                 trecho_elem=trecho)


# ---------------------------------------------------------------------------
# Rigidez
# ---------------------------------------------------------------------------

def _k_elemento(EI: float, L: float) -> np.ndarray:
    c = EI / L ** 3
    return c * np.array([
        [12.0,     6.0 * L,   -12.0,     6.0 * L],
        [6.0 * L,  4.0 * L * L, -6.0 * L, 2.0 * L * L],
        [-12.0,   -6.0 * L,    12.0,    -6.0 * L],
        [6.0 * L,  2.0 * L * L, -6.0 * L, 4.0 * L * L],
    ])


def montar_rigidez(viga: Viga, malha: Malha) -> sp.csr_matrix:
    """Matriz de rigidez global esparsa, com as molas rotacionais dos apoios."""
    n = 2 * malha.n_nos
    ne = malha.n_elem
    Ls = malha.comprimentos
    linhas = np.empty(16 * ne, dtype=int)
    colunas = np.empty(16 * ne, dtype=int)
    valores = np.empty(16 * ne)
    for e in range(ne):
        ke = _k_elemento(malha.EI[e], Ls[e])
        g = np.array([2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3])
        fatia = slice(16 * e, 16 * (e + 1))
        linhas[fatia] = np.repeat(g, 4)
        colunas[fatia] = np.tile(g, 4)
        valores[fatia] = ke.ravel()
    K = sp.coo_matrix((valores, (linhas, colunas)), shape=(n, n)).tocsr()
    molas = []
    for i, ap in enumerate(viga.apoios):
        if ap.tipo == "mola" and ap.k_mola > 0:
            no = _no_do_apoio(malha, viga.x_apoios[i])
            molas.append((2 * no + 1, ap.k_mola))
    if molas:
        idx = [m[0] for m in molas]
        val = [m[1] for m in molas]
        K = K + sp.coo_matrix((val, (idx, idx)), shape=(n, n)).tocsr()
    return K


def _no_do_apoio(malha: Malha, x: float) -> int:
    return int(np.argmin(np.abs(malha.x_nos - x)))


def graus_restritos(viga: Viga, malha: Malha) -> list[int]:
    """Índices dos graus de liberdade impedidos pelos apoios."""
    fixos: list[int] = []
    for i, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        no = _no_do_apoio(malha, viga.x_apoios[i])
        fixos.append(2 * no)                       # deslocamento vertical
        if ap.tipo == "engaste":
            fixos.append(2 * no + 1)               # rotação
    return sorted(set(fixos))


# ---------------------------------------------------------------------------
# Vetores de carga
# ---------------------------------------------------------------------------

def _carga_distribuida_no_elemento(viga: Viga, xa: float, xb: float,
                                   acao: str, tramo: int) -> tuple[float, float]:
    """Intensidade da carga distribuída (kN/m) nas extremidades do elemento.

    Considera apenas as cargas da ação e do tramo pedidos; como a malha tem
    nós em todos os pontos de descontinuidade, a carga é linear no elemento.
    """
    w = [0.0, 0.0]
    xm = 0.5 * (xa + xb)
    if viga.tramo_em(xm) != tramo:
        return 0.0, 0.0
    for c in viga.todas_distribuidas():
        if c.acao != acao:
            continue
        if c.x_fim <= xa + TOL or c.x_ini >= xb - TOL:
            continue
        w[0] += c.valor(min(max(xa, c.x_ini), c.x_fim))
        w[1] += c.valor(min(max(xb, c.x_ini), c.x_fim))
    return w[0], w[1]


def _q_elemento(w1: float, w2: float, L: float) -> np.ndarray:
    """Vetor de cargas nodais equivalentes de uma carga trapezoidal p/ baixo."""
    return np.array([
        -L * (7.0 * w1 + 3.0 * w2) / 20.0,
        -L * L * (3.0 * w1 + 2.0 * w2) / 60.0,
        -L * (3.0 * w1 + 7.0 * w2) / 20.0,
        L * L * (2.0 * w1 + 3.0 * w2) / 60.0,
    ])


@dataclass
class CasoBase:
    """Um caso de carga elementar: uma ação atuando em um único tramo."""

    acao: str                 # 'g' ou 'q'
    tramo: int
    F: np.ndarray             # vetor de forças nodais
    Q: np.ndarray             # (ne, 4) cargas equivalentes por elemento
    w: np.ndarray             # (ne, 2) carga distribuída nas pontas


def montar_casos_base(viga: Viga, malha: Malha) -> list[CasoBase]:
    """Um caso por (ação, tramo), para permitir alternância de carregamento."""
    n = 2 * malha.n_nos
    ne = malha.n_elem
    Ls = malha.comprimentos
    casos: list[CasoBase] = []

    for acao in ("g", "q"):
        for t in range(len(viga.tramos)):
            F = np.zeros(n)
            Q = np.zeros((ne, 4))
            W = np.zeros((ne, 2))
            for e in range(ne):
                if malha.tramo_elem[e] != t:
                    continue
                xa, xb = malha.x_nos[e], malha.x_nos[e + 1]
                w1, w2 = _carga_distribuida_no_elemento(viga, xa, xb, acao, t)
                if w1 == 0.0 and w2 == 0.0:
                    continue
                q = _q_elemento(w1, w2, Ls[e])
                Q[e] = q
                W[e] = (w1, w2)
                F[2 * e:2 * e + 4] += q
            # cargas concentradas e momentos aplicados (nós coincidentes)
            for p in viga.concentradas:
                if p.acao != acao or viga.tramo_em(p.x) != t:
                    continue
                no = int(np.argmin(np.abs(malha.x_nos - p.x)))
                F[2 * no] -= p.P
            for m in viga.momentos:
                if m.acao != acao or viga.tramo_em(m.x) != t:
                    continue
                no = int(np.argmin(np.abs(malha.x_nos - m.x)))
                F[2 * no + 1] += m.M
            casos.append(CasoBase(acao=acao, tramo=t, F=F, Q=Q, w=W))
    return casos


# ---------------------------------------------------------------------------
# Solução
# ---------------------------------------------------------------------------

@dataclass
class RespostaBase:
    """Resposta da estrutura a um caso de carga elementar."""

    acao: str
    tramo: int
    V: np.ndarray             # (2*ne,) kN
    M: np.ndarray             # (2*ne,) kN.m
    flecha: np.ndarray        # (2*ne,) m, positiva para baixo
    reacoes: np.ndarray       # (n_apoios,) kN, positivas para cima
    momentos_apoio: np.ndarray  # (n_apoios,) kN.m de reação (engastes/molas)


@dataclass
class Estrutura:
    """Viga discretizada, resolvida para todos os casos-base."""

    viga: Viga
    malha: Malha
    K: sp.csr_matrix
    livres: np.ndarray
    fixos: np.ndarray
    respostas: list[RespostaBase] = field(default_factory=list)

    def resposta(self, acao: str, tramo: int) -> RespostaBase:
        for r in self.respostas:
            if r.acao == acao and r.tramo == tramo:
                return r
        raise KeyError(f"Caso base ausente: {acao}/{tramo}")

    @property
    def x(self) -> np.ndarray:
        return self.malha.x_grid


def _esforcos_internos(malha: Malha, u: np.ndarray, caso: CasoBase
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Diagramas de V e M na grade de saída, a partir dos deslocamentos."""
    ne = malha.n_elem
    Ls = malha.comprimentos
    V = np.zeros(2 * ne)
    M = np.zeros(2 * ne)
    for e in range(ne):
        L = Ls[e]
        ue = u[2 * e:2 * e + 4]
        fe = _k_elemento(malha.EI[e], L) @ ue - caso.Q[e]
        w1, w2 = caso.w[e]
        # V(x) = fe0 - integral da carga; M(x) = -fe1 + fe0.x - momento da carga
        V[2 * e] = fe[0]
        M[2 * e] = -fe[1]
        carga = (w1 + w2) / 2.0 * L
        mom_carga = L * L * (2.0 * w1 + w2) / 6.0
        V[2 * e + 1] = fe[0] - carga
        M[2 * e + 1] = -fe[1] + fe[0] * L - mom_carga
    return V, M


def resolver(viga: Viga, dx_max: float = DX_MAX,
             inercias: list[float] | None = None) -> Estrutura:
    """Monta e resolve a estrutura para todos os casos-base."""
    malha = gerar_malha(viga, dx_max, inercias)
    K = montar_rigidez(viga, malha)
    n = K.shape[0]
    fixos = np.array(graus_restritos(viga, malha), dtype=int)
    livres = np.setdiff1d(np.arange(n), fixos)

    casos = montar_casos_base(viga, malha)
    Fm = np.column_stack([c.F for c in casos])

    Kff = K[livres][:, livres].tocsc()
    try:
        Uf = spla.splu(Kff).solve(Fm[livres])
    except RuntimeError as exc:
        raise ValueError(
            "A viga está hipostática: verifique os apoios informados.") from exc

    U = np.zeros((n, len(casos)))
    U[livres] = Uf

    nos_apoio = [_no_do_apoio(malha, x) for x in viga.x_apoios]
    respostas: list[RespostaBase] = []
    for j, caso in enumerate(casos):
        u = U[:, j]
        V, M = _esforcos_internos(malha, u, caso)
        flecha = np.empty(2 * malha.n_elem)
        flecha[0::2] = -u[0:-2:2]
        flecha[1::2] = -u[2::2]
        R = K @ u - caso.F
        reac = np.zeros(len(viga.apoios))
        mom = np.zeros(len(viga.apoios))
        for i, (no, ap) in enumerate(zip(nos_apoio, viga.apoios)):
            if ap.tipo == "livre":
                continue
            reac[i] = R[2 * no]
            if ap.tipo == "engaste":
                mom[i] = R[2 * no + 1]
            elif ap.tipo == "mola":
                mom[i] = ap.k_mola * u[2 * no + 1]
        respostas.append(RespostaBase(
            acao=caso.acao, tramo=caso.tramo, V=V, M=M, flecha=flecha,
            reacoes=reac, momentos_apoio=mom))

    return Estrutura(viga=viga, malha=malha, K=K, livres=livres, fixos=fixos,
                     respostas=respostas)


# ---------------------------------------------------------------------------
# Torção
# ---------------------------------------------------------------------------

def _rigidez_torcao(secao) -> float:
    """Módulo de rigidez à torção da seção retangular, kN.m² por rad/m."""
    a, b = max(secao.bw, secao.h), min(secao.bw, secao.h)
    beta = 1.0 / 3.0 - 0.21 * (b / a) * (1.0 - (b / a) ** 4 / 12.0)
    return beta * a * b ** 3            # J em cm^4


def resolver_torcao(viga: Viga, dx_max: float = DX_MAX
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Diagrama de momento torçor das ações permanente e variável.

    Devolve (x, T_g, T_q) em m e kN.m. Os apoios não livres são considerados
    impedidos de girar em torno do eixo da viga; a rigidez usada é a elástica
    da seção bruta, o que corresponde à torção de equilíbrio distribuída pela
    rigidez relativa dos tramos.
    """
    malha = gerar_malha(viga, dx_max)
    x = malha.x_nos
    nn = len(x)
    Ls = malha.comprimentos
    G = viga.concreto.Ecs / (2.0 * (1.0 + 0.2)) * 1e3      # kN/m² (nu = 0,2)

    K = np.zeros((nn, nn))
    for e in range(malha.n_elem):
        J = _rigidez_torcao(viga.tramos[malha.tramo_elem[e]].secao) * 1e-8
        k = G * J / Ls[e]
        K[e, e] += k
        K[e, e + 1] -= k
        K[e + 1, e] -= k
        K[e + 1, e + 1] += k

    F = {"g": np.zeros(nn), "q": np.zeros(nn)}
    m = {"g": np.zeros(malha.n_elem), "q": np.zeros(malha.n_elem)}
    for t in viga.torcores:
        acao = t.acao if t.acao in F else "g"
        if t.x_fim is None or abs(t.x_fim - t.x) < 1e-9:
            no = int(np.argmin(np.abs(x - t.x)))
            F[acao][no] += t.T
        else:
            for e in range(malha.n_elem):
                xa, xb = x[e], x[e + 1]
                if xb <= t.x + 1e-9 or xa >= t.x_fim - 1e-9:
                    continue
                m[acao][e] += t.T
                F[acao][e] += t.T * Ls[e] / 2.0
                F[acao][e + 1] += t.T * Ls[e] / 2.0

    fixos = [int(np.argmin(np.abs(x - viga.x_apoios[i])))
             for i, ap in enumerate(viga.apoios) if ap.tipo != "livre"]
    livres = np.setdiff1d(np.arange(nn), np.array(sorted(set(fixos))))

    diagramas = []
    for acao in ("g", "q"):
        theta = np.zeros(nn)
        if livres.size and np.any(F[acao]):
            theta[livres] = np.linalg.solve(K[np.ix_(livres, livres)],
                                            F[acao][livres])
        T = np.zeros(2 * malha.n_elem)
        for e in range(malha.n_elem):
            J = _rigidez_torcao(viga.tramos[malha.tramo_elem[e]].secao) * 1e-8
            k = G * J / Ls[e]
            Te = k * (theta[e] - theta[e + 1])
            T[2 * e] = Te
            T[2 * e + 1] = Te - m[acao][e] * Ls[e]
        diagramas.append(T)
    return malha.x_grid, diagramas[0], diagramas[1]


# ---------------------------------------------------------------------------
# Combinação de casos
# ---------------------------------------------------------------------------

@dataclass
class Solicitacao:
    """Diagramas de uma combinação já montada."""

    nome: str
    x: np.ndarray
    V: np.ndarray
    M: np.ndarray
    flecha: np.ndarray
    reacoes: np.ndarray
    momentos_apoio: np.ndarray


def combinar(estrutura: Estrutura, fatores_g: np.ndarray,
             fatores_q: np.ndarray, nome: str = "") -> Solicitacao:
    """Superpõe os casos-base com um fator por tramo para cada ação."""
    nt = len(estrutura.viga.tramos)
    fg = np.broadcast_to(np.asarray(fatores_g, dtype=float), (nt,))
    fq = np.broadcast_to(np.asarray(fatores_q, dtype=float), (nt,))

    V = np.zeros_like(estrutura.x)
    M = np.zeros_like(estrutura.x)
    d = np.zeros_like(estrutura.x)
    R = np.zeros(len(estrutura.viga.apoios))
    Ma = np.zeros(len(estrutura.viga.apoios))
    for r in estrutura.respostas:
        f = fg[r.tramo] if r.acao == "g" else fq[r.tramo]
        if f == 0.0:
            continue
        V += f * r.V
        M += f * r.M
        d += f * r.flecha
        R += f * r.reacoes
        Ma += f * r.momentos_apoio
    return Solicitacao(nome=nome, x=estrutura.x, V=V, M=M, flecha=d,
                       reacoes=R, momentos_apoio=Ma)
