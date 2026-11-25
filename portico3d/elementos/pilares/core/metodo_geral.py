# -*- coding: utf-8 -*-
"""
metodo_geral.py
Método geral de 2ª ordem do item 15.8.3.2 da NBR 6118:2026: "análise não
linear de 2ª ordem efetuada com discretização adequada da barra,
consideração da relação momento-curvatura real em cada seção e consideração
da não linearidade geométrica de maneira não aproximada". Obrigatório para
lambda > 140.

Como é feito aqui
-----------------

* **Formulação de segurança do 15.3.1.** Os efeitos de 2ª ordem são
  calculados com as cargas majoradas de ``gamma_f/gamma_f3`` e o resultado é
  majorado de ``gamma_f3 = 1,1``. Com ``M = N (e1 + a)`` isso se reduz a
  calcular a flecha ``a`` sob ``Nd/gamma_f3`` e somá-la à excentricidade de
  1ª ordem com o ``Nd`` inteiro. ``gamma_n`` (esforços finais, nota da Tabela
  13.1) sai da mesma forma.
* **Relação momento-curvatura** (Figura 15.1): concreto com pico ``1,10
  fcd`` e aço a ``fyd`` (:mod:`momento_curvatura`). Duas opções, as duas da
  norma: ``"curva"`` -- o estado real de cada seção sob ``(N, Mx, My)`` --
  ou ``"secante"`` -- a reta AB, rigidez ``(EI)sec`` constante, que "a favor
  da segurança" a Figura 15.1 admite para as deformações.
* **Barra discretizada** em ``n`` seções (11 por padrão). Pilar vinculado nas
  duas pontas: barra biarticulada de comprimento ``le`` em cada direção, com
  os momentos de extremidade da entrada; em balanço: engastada na base e
  livre no topo, com o comprimento do lance.
* **Não linearidade geométrica**: ``M(z) = N (e1(z) + braço(z))`` -- o
  braço é ``-a(z)`` na biarticulada e ``a(L) - a(z)`` em balanço; a curvatura
  de cada seção sai do estado da seção, e a flecha da dupla integração
  (trapézios) com as condições de contorno; repete-se até a flecha máxima
  parar (variação relativa < 1e-4). Flecha maior que o comprimento, ou uma
  seção que não equilibra o momento dentro dos limites de deformação, é
  perda de estabilidade ou esgotamento -- a resposta é "não passa".
* **Oblíqua acoplada** (padrão): cada seção é resolvida para os dois
  momentos juntos e devolve as duas curvaturas. Desacoplada, cada direção é
  analisada em flexão composta normal, como no P4 do PCalc.

``gamma_n1`` (15.8.1) majora a parcela de 2ª ordem, ``N . braço``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import green
from . import momento_curvatura as mc
from . import seccional as sc
from .formato import num

#: Seções da barra no método geral (o PCalc usa 11).
SECOES_PADRAO = 11
TOLERANCIA = 1e-4
ITERACOES_MAXIMAS = 100


# ---------------------------------------------------------------------------
# Estado de uma seção para esforços dados
# ---------------------------------------------------------------------------

def _resultantes(secao: sc.SecaoDiscreta, e0: float, kx: float, ky: float
                 ) -> sc.Estado:
    """``(N, Mx, My)`` do plano ``eps = e0 + kx x + ky y`` (‰, ‰/cm;
    compressão positiva)."""
    k = math.hypot(kx, ky)
    theta = math.atan2(ky, kx) if k > 0.0 else 0.0
    plano = sc.Plano(eps_ref=e0, k=k, u_ref=0.0)
    # o passo do Newton pode testar deformações absurdas antes de ser
    # reduzido; o resultado não finito é rejeitado pela busca linear
    with np.errstate(all="ignore"):
        return sc.resultantes_de_plano(secao, theta, plano)


def _dentro(secao: sc.SecaoDiscreta, e0: float, kx: float, ky: float) -> bool:
    k = math.hypot(kx, ky)
    if k < green.K_MINIMO:
        c = secao.concreto
        return -sc.EPS_S_MAXIMA - 1e-9 <= e0 <= c.eps_c2_mil + 1e-9
    theta = math.atan2(ky, kx)
    est = sc.Estado(N=0.0, Mx=0.0, My=0.0,
                    plano=sc.Plano(eps_ref=e0, k=k, u_ref=0.0), theta=theta)
    return mc.dentro_dos_limites(secao, theta, est)


@dataclass
class EstadoSecao:
    e0: float
    kx: float                 # ‰/cm
    ky: float
    ok: bool = True


def estado_por_esforcos(secao: sc.SecaoDiscreta, N: float, Mx: float,
                        My: float, chute: EstadoSecao | None = None,
                        acoplado: bool = True) -> EstadoSecao:
    """Plano de deformações que equilibra ``(N, Mx, My)`` (kN, kN·cm).

    Newton em ``(e0, kx, ky)`` com jacobiana por diferenças finitas e passo
    amortecido (o resíduo tem de cair); parte do estado da iteração anterior
    da mesma seção, que é quase sempre vizinho. Desacoplado (``acoplado =
    False``), só a curvatura da direção do momento é livre -- flexão
    composta normal. ``ok = False`` se não há equilíbrio dentro dos limites
    de deformação (o momento passa do que a seção resiste).
    """
    escala_N = max(abs(N), 1.0)
    escala_M = max(abs(Mx), abs(My), 1.0)
    if abs(Mx) < 1e-9 and abs(My) < 1e-9:
        # sem momento: só a deformação uniforme é incógnita (as curvaturas
        # ficam em zero, e o equilíbrio é o da compressão centrada)
        livres = [0]
    else:
        livres = [0, 1, 2] if acoplado else ([0, 1] if abs(Mx) >= abs(My)
                                             else [0, 2])
    p = [0.0, 0.0, 0.0]
    if chute is not None and chute.ok:
        p = [chute.e0, chute.kx, chute.ky]
    else:
        # deformação uniforme que equilibra N, por bisseção (N cresce com e0)
        # -- um chute elástico pode cair além do patamar do concreto e do
        # escoamento do aço, onde dN/de0 ~ 0 e o Newton não sai do lugar.
        # Depende só da seção e de N: guardada na seção, porque as 11 seções
        # da barra, em todas as análises da mesma armadura (situações e os
        # dois mínimos), pedem a mesma -- eram 60 avaliações fatiadas a cada
        # vez, ~10 % do método geral.
        cache = getattr(secao, "_e0_uniforme", None)
        if not isinstance(cache, dict):
            cache = secao._e0_uniforme = {}
        e0 = cache.get(N)
        if e0 is None:
            lo, hi = -sc.EPS_S_MAXIMA, secao.concreto.eps_c2_mil
            for _ in range(60):
                m = (lo + hi) / 2.0
                if _resultantes(secao, m, 0.0, 0.0).N < N:
                    lo = m
                else:
                    hi = m
            e0 = cache[N] = (lo + hi) / 2.0
        p[0] = e0
        # curvaturas: elásticas, com o módulo inicial do diagrama -- só a
        # ordem de grandeza importa. Ix é a inércia da flexão na direção x
        # (a que o Mx = ∫ sigma x dA mobiliza), Iy a da direção y
        prop = secao.propriedades
        c = secao.concreto
        E = 2.0 * c.fator_pico * c.fcd_kNcm2 / (c.eps_c2_mil / 1000.0)
        if 1 in livres and prop.Ix > 0:
            p[1] = 1000.0 * Mx / (E * prop.Ix)
        if 2 in livres and prop.Iy > 0:
            p[2] = 1000.0 * My / (E * prop.Iy)
    alvo = (N, Mx, My)

    def residuo(q):
        est = _resultantes(secao, *q)
        r = (est.N - alvo[0], est.Mx - alvo[1], est.My - alvo[2])
        if not all(math.isfinite(v) for v in r):
            return r, float("inf")
        return r, math.sqrt((r[0] / escala_N) ** 2
                            + ((r[1] / escala_M) ** 2 if 1 in livres else 0)
                            + ((r[2] / escala_M) ** 2 if 2 in livres else 0))

    r, nr = residuo(p)
    for _ in range(60):
        if nr < 1e-9:
            break
        # jacobiana nas variáveis livres
        J = []
        passos = []
        for i in livres:
            # passo das diferenças finitas: relativo, com piso -- na curvatura
            # bem acima do K_MINIMO da integração de Green, onde ela degenera
            h = 1e-6 * max(abs(p[i]), 1e-3) if i == 0 else \
                max(1e-6 * abs(p[i]), 1e-7)
            q = list(p)
            q[i] += h
            rq, _ = residuo(q)
            J.append([(rq[j] - r[j]) / h for j in livres])
            passos.append(h)
        # J[i][j] = d r_j / d p_i ; resolve J^T dp = -r
        m = len(livres)
        A_ = [[J[i][j] for i in range(m)] for j in range(m)]
        b_ = [-r[j] for j in livres]
        dp = _resolver(A_, b_)
        if dp is None:
            break
        fator = 1.0
        melhorou = False
        for _ in range(30):
            q = list(p)
            for idx, i in enumerate(livres):
                q[i] += fator * dp[idx]
            rq, nq = residuo(q)
            if nq < nr:
                p, r, nr = q, rq, nq
                melhorou = True
                break
            fator /= 2.0
        if not melhorou:
            break
    ok = nr < 1e-6 and _dentro(secao, *p)
    return EstadoSecao(e0=p[0], kx=p[1], ky=p[2], ok=ok)


def _resolver(A, b):
    """Eliminação de Gauss com pivotamento parcial (2x2 ou 3x3)."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda i: abs(M[i][c]))
        if abs(M[piv][c]) < 1e-300:
            return None
        M[c], M[piv] = M[piv], M[c]
        for i in range(c + 1, n):
            f = M[i][c] / M[c][c]
            for j in range(c, n + 1):
                M[i][j] -= f * M[c][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


# ---------------------------------------------------------------------------
# A barra
# ---------------------------------------------------------------------------

@dataclass
class ResultadoGeral:
    convergiu: bool
    motivo: str = ""
    z: list[float] = field(default_factory=list)        # 0..1, base -> topo
    Mx: list[float] = field(default_factory=list)       # kN·cm, finais
    My: list[float] = field(default_factory=list)
    ax: list[float] = field(default_factory=list)       # cm, flecha
    ay: list[float] = field(default_factory=list)
    iteracoes: int = 0
    ecc: tuple[float, float] = (0.0, 0.0)               # cm, fluência (15.8.4)


def _integrar(curv: list[float], L: float, engastado_na_base: bool
              ) -> list[float]:
    """Deslocamento lateral por dupla integração de ``a'' = curv``
    (trapézios), cm. ``curv`` > 0 quando a face +x (+y) está comprimida: a
    barra fica côncava para esse lado.

    Engastada na base: ``a(0) = a'(0) = 0``. Biarticulada: ``a(0) = a(L) =
    0``.
    """
    n = len(curv)
    dz = L / (n - 1)
    s = [0.0] * n
    a = [0.0] * n
    for i in range(1, n):
        s[i] = s[i - 1] + (curv[i] + curv[i - 1]) / 2.0 * dz
        a[i] = a[i - 1] + (s[i] + s[i - 1]) / 2.0 * dz
    if not engastado_na_base:
        for i in range(n):
            a[i] -= a[n - 1] * i / (n - 1)
    return a


def _braco(a: list[float], engastado_na_base: bool) -> list[float]:
    """Braço de 2ª ordem da normal em cada seção, cm.

    A normal age na linha das excentricidades de 1ª ordem; a seção está em
    ``a(z)``. Biarticulada: a linha é fixa nas duas pontas e o braço é
    ``-a(z)``. Em balanço a carga do topo acompanha o topo: o braço é
    ``a(L) - a(z)`` -- máximo na base.
    """
    if engastado_na_base:
        return [a[-1] - v for v in a]
    return [-v for v in a]


def analisar(secao: sc.SecaoDiscreta, N: float,
             e1x: tuple[float, float], e1y: tuple[float, float],
             L: tuple[float, float], balanco: tuple[bool, bool],
             gamma_n1: tuple[float, float] = (1.0, 1.0),
             n: int = SECOES_PADRAO, rigidez: str = "curva",
             acoplado: bool = True, gamma_f3: float = mc.GAMMA_F3,
             fator_final: float = 1.0,
             segunda_ordem: tuple[bool, bool] = (True, True),
             fator_fluencia: float = 1.0,
             ecc: tuple[float, float] = (0.0, 0.0)) -> ResultadoGeral:
    """Método geral num lance.

    ``N`` é a normal de cálculo **sem** ``gamma_n`` (kN, compressão
    positiva); ``fator_final`` (o ``gamma_n``) multiplica os momentos finais.
    ``e1x``/``e1y`` são as excentricidades de 1ª ordem ``(base, topo)`` de
    cada direção (cm, convenção interna: o mesmo sinal nas duas pontas é
    curvatura simples); ``L`` o comprimento da barra em cada direção e
    ``balanco`` se ela é engastada na base e livre no topo;
    ``segunda_ordem`` liga a não linearidade geométrica em cada direção (a
    dispensa do 15.8.2 continua valendo, e a normal de tração não tem 2ª
    ordem). Fluência (15.8.4): ``fator_fluencia`` (``1 + phi_ef``) estica a
    curva de deformabilidade, ou ``ecc`` (cm, com sinal, por direção) soma a
    excentricidade de fluência à linha de 1ª ordem com a forma da deformada
    -- ``sen(pi z/L)`` na biarticulada, ``cos(pi z/2L)`` no braço do balanço
    --, "como se fosse um efeito imediato".
    """
    sd = mc.secao_deformabilidade(secao, fator_fluencia)
    Nr = N / gamma_f3
    z = [i / (n - 1) for i in range(n)]
    e1 = {"x": [e1x[0] + (e1x[1] - e1x[0]) * t for t in z],
          "y": [e1y[0] + (e1y[1] - e1y[0]) * t for t in z]}
    Ld = {"x": L[0], "y": L[1]}
    bal = {"x": balanco[0], "y": balanco[1]}
    for k, d in enumerate(("x", "y")):
        if ecc[k]:
            forma = ([math.cos(math.pi * t / 2.0) for t in z] if bal[d]
                     else [math.sin(math.pi * t) for t in z])
            e1[d] = [v + ecc[k] * f for v, f in zip(e1[d], forma)]
    g1 = {"x": gamma_n1[0], "y": gamma_n1[1]}
    segunda_ordem = {"x": segunda_ordem[0], "y": segunda_ordem[1]}
    a = {"x": [0.0] * n, "y": [0.0] * n}
    estados: list[EstadoSecao | None] = [None] * n
    ei: dict[tuple[str, float], float] = {}

    def EI(direcao: str, M: float) -> float | None:
        s = 1.0 if M >= 0 else -1.0
        if (direcao, s) not in ei:
            r = mc.rigidez_secante(secao, N, direcao, s, gamma_f3,
                                   fator_fluencia)
            ei[(direcao, s)] = r.EI if r is not None else None
        return ei[(direcao, s)]

    res = ResultadoGeral(convergiu=False, z=z, ecc=tuple(ecc))
    for it in range(1, ITERACOES_MAXIMAS + 1):
        bx = _braco(a["x"], bal["x"])
        by = _braco(a["y"], bal["y"])
        Mx = [Nr * (e1["x"][i] + bx[i]) for i in range(n)]
        My = [Nr * (e1["y"][i] + by[i]) for i in range(n)]
        cx = [0.0] * n
        cy = [0.0] * n
        for i in range(n):
            if rigidez == "secante":
                for d, M, c in (("x", Mx[i], cx), ("y", My[i], cy)):
                    if abs(M) < 1e-12:
                        continue
                    E = EI(d, M)
                    if not E:
                        res.motivo = (f"a reta AB não está definida em {d} "
                                      f"(a curva de deformabilidade não "
                                      f"alcança MRd/γf3)")
                        return res
                    c[i] = M / E
            else:
                if acoplado:
                    est = estado_por_esforcos(sd, Nr, Mx[i], My[i],
                                              estados[i], True)
                    if not est.ok:
                        res.motivo = (f"a seção a {num(z[i], 2)}·L não equilibra "
                                      f"(Mx, My) = ({num(Mx[i] / 100, 1)}; "
                                      f"{num(My[i] / 100, 1)}) kN·m sob "
                                      f"N/γf3 -- esgotamento")
                        return res
                    estados[i] = est
                    cx[i], cy[i] = est.kx / 1000.0, est.ky / 1000.0
                else:
                    for d, M, c in (("x", Mx[i], cx), ("y", My[i], cy)):
                        if abs(M) < 1e-12:
                            continue
                        est = estado_por_esforcos(
                            sd, Nr, M if d == "x" else 0.0,
                            M if d == "y" else 0.0, None, False)
                        if not est.ok:
                            res.motivo = (f"a seção a {num(z[i], 2)}·L não "
                                          f"equilibra M{d} = {num(M / 100, 1)} "
                                          f"kN·m -- esgotamento")
                            return res
                        c[i] = (est.kx if d == "x" else est.ky) / 1000.0
        novo = {"x": _integrar(cx, Ld["x"], bal["x"]),
                "y": _integrar(cy, Ld["y"], bal["y"])}
        for d in ("x", "y"):
            if not segunda_ordem[d]:
                novo[d] = [0.0] * n
        m_novo = max(max(abs(v) for v in novo["x"]),
                     max(abs(v) for v in novo["y"]))
        dif = max(max(abs(p - q) for p, q in zip(novo["x"], a["x"])),
                  max(abs(p - q) for p, q in zip(novo["y"], a["y"])))
        a = novo
        res.iteracoes = it
        if m_novo > max(Ld["x"], Ld["y"]):
            res.motivo = "a flecha passou do comprimento da barra -- instabilidade"
            return res
        if m_novo == 0.0 or dif <= TOLERANCIA * m_novo:
            res.convergiu = True
            break
    if not res.convergiu:
        res.motivo = (f"não convergiu em {ITERACOES_MAXIMAS} iterações -- "
                      f"perda de estabilidade")
        return res
    f = fator_final
    res.ax, res.ay = a["x"], a["y"]
    bx = _braco(a["x"], bal["x"])
    by = _braco(a["y"], bal["y"])
    res.Mx = [f * N * (e1["x"][i] + g1["x"] * bx[i]) for i in range(n)]
    res.My = [f * N * (e1["y"][i] + g1["y"] * by[i]) for i in range(n)]
    return res
