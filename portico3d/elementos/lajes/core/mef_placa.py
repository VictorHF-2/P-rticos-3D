# -*- coding: utf-8 -*-
"""
mef_placa.py
Placa de Reissner-Mindlin em malha retangular, pelo elemento MITC4
(Bathe-Dvorkin), para o pavimento de lajes maciças.

É a ferramenta de análise elástica da R10: dá os momentos Mx, My e Mxy
**campo a campo**, que o método das linhas de ruptura e as tabelas não dão --
e é do trio (Mx, My, Mxy) que sai o dimensionamento de Wood-Armer
(``woodarmer.py``), com o momento volvente e a armadura de canto.

Convenções
==========
* ``x`` e ``y`` são os eixos globais da planta, em metros; ``w`` (deslocamento
  transversal) é positivo **no sentido da carga**, para baixo.
* Os graus de liberdade de cada nó são ``(w, psix, psiy)``, com
  ``psix = dw/dx`` e ``psiy = dw/dy`` no limite de placa fina -- a rotação da
  normal medida de modo que a deformação de cisalhamento é
  ``gxz = dw/dx - psix`` e ``gyz = dw/dy - psiy``.
* Momentos por metro, em kN·m/m, **positivos quando tracionam a face
  inferior** (momento de vão); ``Mx = -D (dpsix/dx + nu dpsiy/dy)``,
  ``Mxy = -D (1 - nu)/2 (dpsix/dy + dpsiy/dx)``.
* Unidades: kN e m (``E`` em kN/m², ``h`` em m).

A malha é uma **grade de linhas** x e y globais; cada célula pertence a um
painel (uma laje) ou fica vazia. Isso dispensa gerador de malha: as lajes de
um pavimento são retângulos alinhados, e as bordas comuns caem sobre linhas
da grade. Nós de painéis vizinhos que dividem uma linha de continuidade são
**fundidos** (rotação contínua); nos demais ficam duplicados (rótula).

Apoios (viga rígida): ``w = 0`` e rotação **tangente** ao bordo nula -- o
apoio simples "duro", que reproduz o limite de placa fina de Kirchhoff, com
o momento volvente concentrado no canto. O engaste rígido (parede, viga de
torção impedida) anula também a rotação normal.

Validação: série de Navier (placa apoiada, quadrada e retangular, com
carga uniforme), tabelas de Timoshenko (placa engastada) e diferenças
finitas de Kirchhoff -- ver ``main.py``, conferências da R10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

try:                                    # opcional: sem SciPy resolve denso
    import scipy.sparse as _sp
    import scipy.sparse.linalg as _spl
except Exception:                       # noqa: BLE001
    _sp = None
    _spl = None

#: Fator de correção do cisalhamento de Reissner-Mindlin.
K_CISALHAMENTO = 5.0 / 6.0

#: Pontos de Gauss 2 x 2.
_G = 1.0 / math.sqrt(3.0)
PONTOS_GAUSS = ((-_G, -_G), (_G, -_G), (_G, _G), (-_G, _G))

#: Cantos do elemento em coordenadas naturais, na ordem dos nós.
_CANTOS = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


# ---------------------------------------------------------------------------
# Elemento
# ---------------------------------------------------------------------------

def _N(xi: float, eta: float) -> np.ndarray:
    return np.array([0.25 * (1.0 + sx * xi) * (1.0 + sy * eta)
                     for sx, sy in _CANTOS])


def _dN(xi: float, eta: float) -> tuple[np.ndarray, np.ndarray]:
    dxi = np.array([0.25 * sx * (1.0 + sy * eta) for sx, sy in _CANTOS])
    deta = np.array([0.25 * sy * (1.0 + sx * xi) for sx, sy in _CANTOS])
    return dxi, deta


def matriz_B_flexao(xi: float, eta: float, dx: float, dy: float
                    ) -> np.ndarray:
    """``B`` (3 x 12) das curvaturas ``(dpsix/dx, dpsiy/dy, dpsix/dy +
    dpsiy/dx)`` no ponto natural dado."""
    dxi, deta = _dN(xi, eta)
    gx, gy = 2.0 / dx * dxi, 2.0 / dy * deta
    B = np.zeros((3, 12))
    for i in range(4):
        B[0, 3 * i + 1] = gx[i]
        B[1, 3 * i + 2] = gy[i]
        B[2, 3 * i + 1] = gy[i]
        B[2, 3 * i + 2] = gx[i]
    return B


def _b_xi(xi: float, eta: float, dx: float) -> np.ndarray:
    """Deformação covariante ``g_xi = dw/dxi - (dx/2) psix`` (1 x 12)."""
    dxi, _ = _dN(xi, eta)
    N = _N(xi, eta)
    b = np.zeros(12)
    for i in range(4):
        b[3 * i] = dxi[i]
        b[3 * i + 1] = -0.5 * dx * N[i]
    return b


def _b_eta(xi: float, eta: float, dy: float) -> np.ndarray:
    _, deta = _dN(xi, eta)
    N = _N(xi, eta)
    b = np.zeros(12)
    for i in range(4):
        b[3 * i] = deta[i]
        b[3 * i + 2] = -0.5 * dy * N[i]
    return b


def matriz_B_cisalhamento(xi: float, eta: float, dx: float, dy: float
                          ) -> np.ndarray:
    """``B`` (2 x 12) do cisalhamento ``(gxz, gyz)`` com a interpolação
    assumida do MITC4: ``g_xi`` amarrada em ``(0, +-1)`` e ``g_eta`` em
    ``(+-1, 0)`` -- o que elimina o travamento por cisalhamento."""
    a = _b_xi(0.0, 1.0, dx)
    c = _b_xi(0.0, -1.0, dx)
    d = _b_eta(1.0, 0.0, dy)
    b = _b_eta(-1.0, 0.0, dy)
    gxi = 0.5 * (1.0 + eta) * a + 0.5 * (1.0 - eta) * c
    geta = 0.5 * (1.0 + xi) * d + 0.5 * (1.0 - xi) * b
    return np.vstack([2.0 / dx * gxi, 2.0 / dy * geta])


def rigidezes(E: float, nu: float, h: float) -> tuple[np.ndarray, float]:
    """``(Db, ks)``: matriz de flexão (3 x 3, kN·m) e rigidez ao
    cisalhamento ``k G h`` (kN/m)."""
    D = E * h ** 3 / (12.0 * (1.0 - nu ** 2))
    Db = D * np.array([[1.0, nu, 0.0], [nu, 1.0, 0.0],
                       [0.0, 0.0, 0.5 * (1.0 - nu)]])
    ks = K_CISALHAMENTO * E / (2.0 * (1.0 + nu)) * h
    return Db, ks


def rigidez_elemento(dx: float, dy: float, E: float, nu: float, h: float
                     ) -> np.ndarray:
    """Matriz de rigidez 12 x 12 do elemento retangular ``dx`` por ``dy``."""
    Db, ks = rigidezes(E, nu, h)
    jac = dx * dy / 4.0
    K = np.zeros((12, 12))
    for xi, eta in PONTOS_GAUSS:
        Bb = matriz_B_flexao(xi, eta, dx, dy)
        Bs = matriz_B_cisalhamento(xi, eta, dx, dy)
        K += jac * (Bb.T @ Db @ Bb + ks * (Bs.T @ Bs))
    return K


def momentos_no_ponto(u_e: np.ndarray, xi: float, eta: float, dx: float,
                      dy: float, E: float, nu: float, h: float
                      ) -> np.ndarray:
    """``(Mx, My, Mxy)`` em kN·m/m, positivos de vão, no ponto natural."""
    Db, _ = rigidezes(E, nu, h)
    kappa = matriz_B_flexao(xi, eta, dx, dy) @ u_e
    return -(Db @ kappa)


def cortantes_no_ponto(u_e: np.ndarray, xi: float, eta: float, dx: float,
                       dy: float, E: float, nu: float, h: float
                       ) -> np.ndarray:
    """``(Qx, Qy)`` em kN/m (interpolação do MITC4)."""
    _, ks = rigidezes(E, nu, h)
    return ks * (matriz_B_cisalhamento(xi, eta, dx, dy) @ u_e)


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@dataclass
class Painel:
    """Uma laje da malha: espessura, material, carga e retângulo.

    ``bordos`` guarda, para cada lado (``"esq"``, ``"dir"``, ``"baixo"``,
    ``"cima"``), ``(tipo, vizinha)``: tipo ``"livre"``, ``"apoiado"`` ou
    ``"engastado"``; ``vizinha`` é o nome do painel que continua a laje do
    outro lado (engaste por continuidade) ou vazio (engaste rígido).
    """

    nome: str
    x0: float
    y0: float
    x1: float
    y1: float
    h: float                           # m
    E: float                           # kN/m²
    nu: float = 0.2
    p: float = 0.0                     # kN/m², positivo para baixo
    bordos: dict = field(default_factory=dict)
    #: cargas lineares: ``(eixo, coordenada, inicio, fim, valor kN/m)``.
    #: ``eixo = "x"`` é uma linha de ``x`` constante (corre em y).
    lineares: list = field(default_factory=list)
    #: (R11) cargas em área pequena: ``(x0, x1, y0, y1, P kN)`` -- a força
    #: total P uniforme no retângulo
    concentradas: list = field(default_factory=list)


@dataclass
class Resultado:
    """O que o solver devolve, já com os momentos por elemento."""

    x: np.ndarray                      # linhas da grade
    y: np.ndarray
    painel_da_celula: np.ndarray       # (ny-1, nx-1): índice do painel, -1
    paineis: list
    no_de: dict                        # (i, j, painel) -> índice do nó
    u: np.ndarray                      # (3 * n_nos,)
    w_max: dict = field(default_factory=dict)       # painel -> w máximo
    #: por célula ativa: ``(j, i) -> dict(M=(4,3) nos pontos de Gauss,
    #: Mc=(3,) no centro, Q=(2,) no centro, fe=(12,) força interna do
    #: elemento, xc, yc, painel)``
    celulas: dict = field(default_factory=dict)
    reacoes: dict = field(default_factory=dict)     # painel -> kN
    carga_total: dict = field(default_factory=dict)  # painel -> kN
    n_nos: int = 0
    n_elementos: int = 0
    fixos: np.ndarray | None = None
    #: reação em cada grau de liberdade (K u - f): nos graus presos, é a
    #: força (ou o momento) que o apoio faz sobre a malha, com o sinal de
    #: "carga positiva para baixo"
    reac: np.ndarray | None = None


def _grade(paineis: list[Painel], tamanho: float, extras_x=(), extras_y=()):
    """Linhas x e y da grade: todas as bordas dos painéis, as cargas
    lineares e as subdivisões que respeitam o ``tamanho`` do elemento."""
    def linhas(vals, ini_fim):
        base = sorted({round(v, 9) for v in vals})
        saida = [base[0]]
        for a, b in zip(base, base[1:]):
            # só subdivide intervalo que algum painel cobre
            coberto = any(lo - 1e-9 <= a and b <= hi + 1e-9
                          for lo, hi in ini_fim)
            n = max(int(math.ceil((b - a) / tamanho - 1e-9)), 1) \
                if coberto else 1
            for k in range(1, n + 1):
                saida.append(a + (b - a) * k / n)
        return np.array(saida)

    xs = [p.x0 for p in paineis] + [p.x1 for p in paineis] + list(extras_x)
    ys = [p.y0 for p in paineis] + [p.y1 for p in paineis] + list(extras_y)
    gx = linhas(xs, [(p.x0, p.x1) for p in paineis])
    gy = linhas(ys, [(p.y0, p.y1) for p in paineis])
    return gx, gy


class _Uniao:
    def __init__(self) -> None:
        self.pai: dict = {}

    def achar(self, a):
        self.pai.setdefault(a, a)
        while self.pai[a] != a:
            self.pai[a] = self.pai[self.pai[a]]
            a = self.pai[a]
        return a

    def unir(self, a, b) -> None:
        ra, rb = self.achar(a), self.achar(b)
        if ra != rb:
            self.pai[rb] = ra


def resolver(paineis: list[Painel], tamanho: float = 0.25) -> Resultado:
    """Monta a grade, o sistema, impõe os apoios, resolve e calcula os
    momentos em todos os elementos."""
    if not paineis:
        raise ValueError("Nenhum painel para analisar.")
    extras_x, extras_y = [], []
    for p in paineis:
        for eixo, coord, ini, fim, _v in p.lineares:
            (extras_x if eixo == "x" else extras_y).extend([coord, ini, fim])
    gx, gy = _grade(paineis, tamanho, extras_x, extras_y)
    nx, ny = len(gx) - 1, len(gy) - 1

    # -- células -> painel ------------------------------------------------
    celula = -np.ones((ny, nx), dtype=int)
    for j in range(ny):
        yc = 0.5 * (gy[j] + gy[j + 1])
        for i in range(nx):
            xc = 0.5 * (gx[i] + gx[i + 1])
            for k, p in enumerate(paineis):
                if p.x0 < xc < p.x1 and p.y0 < yc < p.y1:
                    celula[j, i] = k
                    break
    nomes = {p.nome: k for k, p in enumerate(paineis)}

    # -- nós; fusão onde há continuidade ---------------------------------
    uf = _Uniao()
    chaves = set()
    for j in range(ny):
        for i in range(nx):
            k = celula[j, i]
            if k < 0:
                continue
            for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                chave = (i + di, j + dj, k)
                chaves.add(chave)
                uf.achar(chave)

    def continuo(k: int, lado: str, vizinho: int) -> bool:
        tipo, viz = paineis[k].bordos.get(lado, ("livre", ""))
        return tipo == "engastado" and viz != "" and \
            nomes.get(viz, -2) == vizinho

    # aresta entre duas células de painéis diferentes
    arestas = []        # (k, lado, (i1,j1), (i2,j2), vizinho)
    for j in range(ny):
        for i in range(nx):
            k = celula[j, i]
            if k < 0:
                continue
            for lado, (di, dj) in (("esq", (-1, 0)), ("dir", (1, 0)),
                                   ("baixo", (0, -1)), ("cima", (0, 1))):
                ii, jj = i + di, j + dj
                viz = celula[jj, ii] if 0 <= ii < nx and 0 <= jj < ny \
                    else -1
                if viz == k:
                    continue
                if lado == "esq":
                    a, b = (i, j), (i, j + 1)
                elif lado == "dir":
                    a, b = (i + 1, j), (i + 1, j + 1)
                elif lado == "baixo":
                    a, b = (i, j), (i + 1, j)
                else:
                    a, b = (i, j + 1), (i + 1, j + 1)
                arestas.append((k, lado, a, b, viz))
                # basta um dos lados declarar a continuidade: na
                # continuidade parcial (R11) o lado de contato < 2/3 fica
                # apoiado no cálculo por tabelas, mas a placa é a mesma
                # por cima da viga -- sem fundir, o lado engastado viraria
                # apoio (engaste com vizinha não é engaste rígido)
                if viz >= 0 and (continuo(k, lado, viz) or
                                 continuo(viz, {"esq": "dir", "dir": "esq",
                                                "baixo": "cima",
                                                "cima": "baixo"}[lado], k)):
                    uf.unir((a[0], a[1], k), (a[0], a[1], viz))
                    uf.unir((b[0], b[1], k), (b[0], b[1], viz))

    no_de: dict = {}
    indices: dict = {}
    for chave in sorted(chaves):
        raiz = uf.achar(chave)
        if raiz not in indices:
            indices[raiz] = len(indices)
        no_de[chave] = indices[raiz]
    n_nos = len(indices)
    ndof = 3 * n_nos

    # -- apoios -------------------------------------------------------------
    preso = np.zeros(ndof, dtype=bool)
    for k, lado, a, b, viz in arestas:
        tipo, vizinha = paineis[k].bordos.get(lado, ("livre", ""))
        if tipo == "livre":
            continue
        rigido = tipo == "engastado" and vizinha == ""
        horizontal = lado in ("baixo", "cima")
        for (ii, jj) in (a, b):
            n = no_de[(ii, jj, k)]
            preso[3 * n] = True                          # w = 0
            preso[3 * n + (1 if horizontal else 2)] = True   # tangente
            if rigido:
                preso[3 * n + (2 if horizontal else 1)] = True   # normal

    # -- montagem ------------------------------------------------------------
    linhas, colunas, valores = [], [], []
    f = np.zeros(ndof)
    carga_total: dict = {p.nome: 0.0 for p in paineis}
    cache: dict = {}
    n_el = 0
    for j in range(ny):
        for i in range(nx):
            k = celula[j, i]
            if k < 0:
                continue
            p = paineis[k]
            dx, dy = gx[i + 1] - gx[i], gy[j + 1] - gy[j]
            chave_k = (round(dx, 9), round(dy, 9), k)
            Ke = cache.get(chave_k)
            if Ke is None:
                Ke = rigidez_elemento(dx, dy, p.E, p.nu, p.h)
                cache[chave_k] = Ke
            nos = [no_de[(i + di, j + dj, k)]
                   for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))]
            gl = np.array([3 * n + c for n in nos for c in range(3)])
            linhas.append(np.repeat(gl, 12))
            colunas.append(np.tile(gl, 12))
            valores.append(Ke.ravel())
            n_el += 1
            if p.p:
                fe = p.p * dx * dy / 4.0
                for n in nos:
                    f[3 * n] += fe
                carga_total[p.nome] += p.p * dx * dy
    # cargas lineares: nós ao longo da linha, cargas consistentes
    for k, p in enumerate(paineis):
        for eixo, coord, ini, fim, valor in p.lineares:
            if eixo == "x":
                i0 = int(np.argmin(np.abs(gx - coord)))
                for j in range(ny):
                    ya, yb = gy[j], gy[j + 1]
                    lo, hi = max(ya, ini), min(yb, fim)
                    if hi - lo <= 1e-9:
                        continue
                    # a linha pertence à célula do lado onde há painel k
                    for i in (i0 - 1, i0):
                        if 0 <= i < nx and celula[j, i] == k:
                            na = no_de[(i0, j, k)]
                            nb = no_de[(i0, j + 1, k)]
                            frac_a = ((hi - lo) / (yb - ya))
                            f[3 * na] += valor * (hi - lo) * 0.5
                            f[3 * nb] += valor * (hi - lo) * 0.5
                            carga_total[p.nome] += valor * (hi - lo)
                            break
            else:
                j0 = int(np.argmin(np.abs(gy - coord)))
                for i in range(nx):
                    xa, xb = gx[i], gx[i + 1]
                    lo, hi = max(xa, ini), min(xb, fim)
                    if hi - lo <= 1e-9:
                        continue
                    for j in (j0 - 1, j0):
                        if 0 <= j < ny and celula[j, i] == k:
                            na = no_de[(i, j0, k)]
                            nb = no_de[(i + 1, j0, k)]
                            f[3 * na] += valor * (hi - lo) * 0.5
                            f[3 * nb] += valor * (hi - lo) * 0.5
                            carga_total[p.nome] += valor * (hi - lo)
                            break
    # cargas em área pequena (R11): a parte de cada célula vai aos nós pelas
    # funções de forma bilineares no centroide da interseção
    for k, p in enumerate(paineis):
        for (cx0, cx1, cy0, cy1, P) in getattr(p, "concentradas", []):
            area = max((cx1 - cx0) * (cy1 - cy0), 1e-12)
            for j in range(ny):
                ylo, yhi = max(gy[j], cy0), min(gy[j + 1], cy1)
                if yhi - ylo <= 1e-12:
                    continue
                for i in range(nx):
                    if celula[j, i] != k:
                        continue
                    xlo, xhi = max(gx[i], cx0), min(gx[i + 1], cx1)
                    if xhi - xlo <= 1e-12:
                        continue
                    parte = P * (xhi - xlo) * (yhi - ylo) / area
                    s = ((xlo + xhi) / 2 - gx[i]) / (gx[i + 1] - gx[i])
                    t = ((ylo + yhi) / 2 - gy[j]) / (gy[j + 1] - gy[j])
                    for (di, dj), N in (((0, 0), (1 - s) * (1 - t)),
                                        ((1, 0), s * (1 - t)),
                                        ((1, 1), s * t),
                                        ((0, 1), (1 - s) * t)):
                        f[3 * no_de[(i + di, j + dj, k)]] += parte * N
                    carga_total[p.nome] += parte

    livres = np.where(~preso)[0]
    r = np.concatenate(linhas)
    c = np.concatenate(colunas)
    v = np.concatenate(valores)
    u = np.zeros(ndof)
    if _sp is not None:
        K = _sp.coo_matrix((v, (r, c)), shape=(ndof, ndof)).tocsr()
        Kff = K[livres][:, livres].tocsc()
        u[livres] = _spl.spsolve(Kff, f[livres])
        reac = K @ u - f
    else:                                                  # pragma: no cover
        K = np.zeros((ndof, ndof))
        np.add.at(K, (r, c), v)
        u[livres] = np.linalg.solve(K[np.ix_(livres, livres)], f[livres])
        reac = K @ u - f

    # -- pós-processamento ------------------------------------------------------
    res = Resultado(x=gx, y=gy, painel_da_celula=celula, paineis=paineis,
                    no_de=no_de, u=u, n_nos=n_nos, n_elementos=n_el,
                    fixos=preso, carga_total=carga_total, reac=reac)
    for p in paineis:
        res.reacoes[p.nome] = 0.0
    # reação de w de cada nó preso, atribuída ao menor painel que o usa; o nó
    # fundido aparece em duas chaves e entra uma vez só
    contado = set()
    for chave in sorted(no_de, key=lambda t: (t[2], t[0], t[1])):
        n = no_de[chave]
        if n in contado or not preso[3 * n]:
            continue
        contado.add(n)
        res.reacoes[paineis[chave[2]].nome] += -reac[3 * n]
    # as matrizes B só dependem do tamanho do elemento: calculadas uma vez
    cache_b: dict = {}
    for j in range(ny):
        for i in range(nx):
            k = celula[j, i]
            if k < 0:
                continue
            p = paineis[k]
            dx, dy = gx[i + 1] - gx[i], gy[j + 1] - gy[j]
            nos = [no_de[(i + di, j + dj, k)]
                   for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))]
            u_e = np.array([u[3 * n + c_] for n in nos for c_ in range(3)])
            chave_b = (round(dx, 9), round(dy, 9))
            mats = cache_b.get(chave_b)
            if mats is None:
                mats = (
                    np.array([matriz_B_flexao(xi, eta, dx, dy)
                              for xi, eta in PONTOS_GAUSS]),
                    matriz_B_flexao(0.0, 0.0, dx, dy),
                    matriz_B_cisalhamento(0.0, 0.0, dx, dy))
                cache_b[chave_b] = mats
            Bg, Bc, Bs = mats
            Db, ks = rigidezes(p.E, p.nu, p.h)
            M = -np.einsum("ab,gbc,c->ga", Db, Bg, u_e)
            Mc = -(Db @ (Bc @ u_e))
            Q = ks * (Bs @ u_e)
            fe = cache[(round(dx, 9), round(dy, 9), k)] @ u_e
            res.celulas[(j, i)] = dict(
                M=M, Mc=Mc, Q=Q, fe=fe, xc=0.5 * (gx[i] + gx[i + 1]),
                yc=0.5 * (gy[j] + gy[j + 1]), painel=k, dx=dx, dy=dy,
                w=float(np.mean([u[3 * n] for n in nos])))
            res.w_max[p.nome] = max(res.w_max.get(p.nome, 0.0),
                                    res.celulas[(j, i)]["w"])
    return res


# ---------------------------------------------------------------------------
# Momentos nos nós
# ---------------------------------------------------------------------------

#: Matriz que leva os 4 valores dos pontos de Gauss aos 4 nós (extrapolação
#: bilinear pelas funções de forma avaliadas em ``xi_no / g``).
_EXTRAPOLA = np.array([_N(sx / _G, sy / _G) for sx, sy in _CANTOS])


def momentos_nodais(res: Resultado) -> dict:
    """Momentos ``(Mx, My, Mxy)`` em cada nó **de cada painel**, por
    extrapolação dos pontos de Gauss e média dos elementos que concorrem no
    nó (dentro do mesmo painel).

    Devolve ``{(i, j, painel): ndarray(3)}``. Painéis diferentes não
    se misturam: a espessura e a vinculação podem mudar de um lado para
    o outro da viga, e o momento normal ao apoio só é igual dos dois lados
    onde há continuidade de fato.
    """
    soma: dict = {}
    cont: dict = {}
    for (j, i), c in res.celulas.items():
        k = c["painel"]
        vals = _EXTRAPOLA @ c["M"]                 # (4, 3): nó 1..4
        for n, (di, dj) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
            chave = (i + di, j + dj, k)
            soma[chave] = soma.get(chave, 0.0) + vals[n]
            cont[chave] = cont.get(chave, 0) + 1
    return {ch: soma[ch] / cont[ch] for ch in soma}
