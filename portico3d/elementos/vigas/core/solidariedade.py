# -*- coding: utf-8 -*-
"""
solidariedade.py
Solidariedade da viga com os pilares (NBR 6118:2026, 14.6.6.1).

O item admite o modelo clássico de viga contínua simplesmente apoiada nos
pilares, com três correções:

a) momentos positivos não menores que os do engastamento perfeito nos apoios
   internos;
b) com a viga solidária ao pilar intermediário e a largura do apoio maior que
   ¼ da altura do pilar, momento negativo não menor, em valor absoluto, que o
   de engastamento perfeito nesse apoio;
c) nos apoios extremos, sem o cálculo exato, o momento de engastamento
   perfeito multiplicado por ``(r_inf + r_sup)/(r_vig + r_inf + r_sup)`` na
   viga, ``r_sup/(...)`` no lance de cima do pilar e ``r_inf/(...)`` no de
   baixo, com ``r = I/ℓ`` avaliado como na Figura 14.8: o pilar com a metade
   do lance (``ℓ/2``) e a viga com o vão.

"Alternativamente, o modelo de viga contínua pode ser melhorado, considerando-
se a solidariedade dos pilares com a viga, mediante a introdução da rigidez à
flexão dos pilares extremos e intermediários." É o modelo ``rigidez``: cada
pilar entra como mola rotacional

    k = 4 Ecs (I_sup/(ℓ_sup/2) + I_inf/(ℓ_inf/2))

-- a mesma rigidez relativa da Figura 14.8, na mesma escala da viga de
extremidade engastada (``4 Ecs I_vig/ℓ_vig``). Com ela, num vão de ponta
oposta engastada, a mola recebe exatamente o momento da alínea c); na viga
contínua, a distribuição sai do equilíbrio do modelo inteiro.

Unidades: cm e cm⁴ nas seções, m nos vãos, kN·m/rad na mola.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from . import avisos as av
from .modelo import Viga


@dataclass
class PilarNoApoio:
    """Rigidezes relativas de um pilar de apoio (Figura 14.8)."""

    apoio: int                # nº do apoio (1, 2, ...)
    largura: float            # cm, ao longo do eixo da viga
    transversal: float        # cm, perpendicular à viga
    l_sup: float              # cm, lance de cima (0 = não há)
    l_inf: float              # cm, lance de baixo
    I_pilar: float            # cm⁴, flexão no plano da viga
    r_sup: float              # cm³, I/(ℓ_sup/2)
    r_inf: float              # cm³
    r_vig: float              # cm³, I_vig/ℓ_vig do vão adjacente (extremos)
    k: float                  # kN·m/rad, 4 Ecs (r_sup + r_inf)

    @property
    def coef_viga(self) -> float:
        soma = self.r_vig + self.r_inf + self.r_sup
        return (self.r_inf + self.r_sup) / soma if soma > 0 else 0.0

    @property
    def coef_sup(self) -> float:
        soma = self.r_vig + self.r_inf + self.r_sup
        return self.r_sup / soma if soma > 0 else 0.0

    @property
    def coef_inf(self) -> float:
        soma = self.r_vig + self.r_inf + self.r_sup
        return self.r_inf / soma if soma > 0 else 0.0


@dataclass
class CorrecaoExtremo:
    """Alínea c): momento no apoio extremo pela solidariedade."""

    apoio: int
    M_eng: float              # kN·m, engastamento perfeito (negativo)
    coef: float
    M_viga: float             # kN·m, coef·M_eng
    M_sup: float              # kN·m, no lance de cima do pilar
    M_inf: float              # kN·m, no lance de baixo


@dataclass
class CorrecaoInterno:
    """Alínea b): apoio interno largo diante do pilar."""

    apoio: int
    largura: float            # cm
    l_pilar: float            # cm, o lance que decide (o menor informado)
    aplica: bool              # largura > ℓ/4
    M_eng: float              # kN·m, engastamento perfeito nesse apoio
    M_modelo: float           # kN·m, o do modelo clássico


@dataclass
class ResultadoSolidariedade:
    """O que o 14.6.6.1 fez nesta viga."""

    modelo: str
    pilares: list[PilarNoApoio] = field(default_factory=list)
    #: a) tramos em que o engastamento nos apoios internos governou o positivo
    positivos: list[tuple[int, float, float]] = field(default_factory=list)
    internos: list[CorrecaoInterno] = field(default_factory=list)
    extremos: list[CorrecaoExtremo] = field(default_factory=list)
    #: apoios extremos em pilar sem altura informada (c não aplicada)
    sem_altura: list[int] = field(default_factory=list)
    #: modelo "rigidez": momento no nó de cada pilar, kN·m (mín, máx)
    momentos_no_no: dict = field(default_factory=dict)
    #: mínimos de momento negativo por apoio (índice 0..n-1) para o momento
    #: de projeto: (M, observação)
    minimos: dict = field(default_factory=dict)


def inercia_pilar(ap) -> float:
    """Inércia do pilar na flexão do plano da viga, cm⁴."""
    bt = ap.largura_pilar_transversal or ap.largura
    return bt * ap.largura ** 3 / 12.0


def pilar_no_apoio(viga: Viga, k: int) -> PilarNoApoio | None:
    """Rigidezes do pilar do apoio ``k`` (0..n-1); None se não há pilar
    informado."""
    ap = viga.apoios[k]
    if not ap.pilar_informado or ap.largura <= 0:
        return None
    I = inercia_pilar(ap)
    r_sup = I / (ap.altura_pilar_acima / 2.0) if ap.altura_pilar_acima > 0 \
        else 0.0
    r_inf = I / (ap.altura_pilar_abaixo / 2.0) if ap.altura_pilar_abaixo > 0 \
        else 0.0
    # a viga do vão adjacente (a de maior rigidez quando o apoio é interno:
    # só a alínea c, de extremo, usa este número)
    vizinhos = [i for i in (k - 1, k) if 0 <= i < len(viga.tramos)]
    r_vig = max((viga.secao_em(_meio(viga, i)).inercia
                 / (viga.tramos[i].L * 100.0) for i in vizinhos), default=0.0)
    kk = 4.0 * viga.concreto.Ecs * (r_sup + r_inf) * 1e-3
    return PilarNoApoio(apoio=k + 1, largura=ap.largura,
                        transversal=ap.largura_pilar_transversal or ap.largura,
                        l_sup=ap.altura_pilar_acima,
                        l_inf=ap.altura_pilar_abaixo, I_pilar=I, r_sup=r_sup,
                        r_inf=r_inf, r_vig=r_vig, k=kk)


def _meio(viga: Viga, i: int) -> float:
    xs = viga.x_apoios
    return 0.5 * (xs[i] + xs[i + 1])


def k_rotacional(viga: Viga, k: int) -> float:
    """Rigidez rotacional do apoio ``k`` no modelo, kN·m/rad.

    A mola declarada pelo usuário vale como foi dada. No modelo ``rigidez``
    do 14.6.6.1, o apoio simples em pilar com lance informado vira mola com a
    rigidez dos pilares. Engaste já é rotação impedida; apoio em outra viga e
    balanço não têm pilar.
    """
    ap = viga.apoios[k]
    if ap.tipo == "mola":
        return max(ap.k_mola, 0.0)
    if (ap.tipo == "simples" and viga.config.modelo_pilares == "rigidez"
            and ap.pilar_informado):
        p = pilar_no_apoio(viga, k)
        return p.k if p else 0.0
    return 0.0


def _engastada(viga: Viga, apoios: list[int]) -> Viga:
    """Cópia da viga com os apoios ``apoios`` engastados."""
    v = copy.deepcopy(viga)
    for k in apoios:
        v.apoios[k].tipo = "engaste"
    return v


def _envoltoria(viga: Viga):
    from . import combinacoes as cb
    from .analise import resolver
    est = resolver(viga)
    env, _ = cb.calcular(est, cb.gerar_combinacoes(viga), tipos=("ELU",))
    return env


def _no_grid(env, x: np.ndarray, nome: str) -> np.ndarray:
    arr = getattr(env, nome)
    xe = env.x if hasattr(env, "x") else x
    if len(arr) == len(x):
        return np.asarray(arr)
    return np.interp(x, xe, arr)


def aplicar(viga: Viga, env, x: np.ndarray, avisos: list[str]
            ) -> ResultadoSolidariedade:
    """Aplica o 14.6.6.1 sobre a envoltória ELU do modelo de cálculo.

    No modelo ``rigidez`` a solidariedade já está na análise (as molas de
    ``k_rotacional``): aqui só se registram os pilares e os momentos nos nós.
    No ``classico``, a envoltória é corrigida em ``env`` (alíneas a e b) e os
    mínimos de momento negativo vão para o momento de projeto (b e c).
    """
    cfg = viga.config
    res = ResultadoSolidariedade(modelo=cfg.modelo_pilares)
    n = len(viga.apoios)
    for k in range(n):
        p = pilar_no_apoio(viga, k)
        if p is not None:
            res.pilares.append(p)

    if cfg.modelo_pilares == "rigidez":
        for p in res.pilares:
            k = p.apoio - 1
            if viga.apoios[k].tipo != "simples":
                continue
            res.momentos_no_no[k] = (float(env.momentos_apoio_min[k]),
                                     float(env.momentos_apoio_max[k]))
        sem = [k + 1 for k, ap in enumerate(viga.apoios)
               if ap.tipo == "simples" and ap.pilar
               and not ap.pilar_informado]
        if sem and res.pilares:
            avisos.append(av.construtivo(
                f"Rigidez dos pilares no modelo (14.6.6.1): o(s) apoio(s) "
                f"{', '.join(map(str, sem))} não têm o lance do pilar "
                f"informado e ficaram como rótula."))
        return res

    # -- modelo clássico: a viga contínua apoiada nos pilares -----------------
    internos = [k for k in range(1, n - 1)
                if viga.apoios[k].pilar and viga.apoios[k].tipo == "simples"]
    if internos:
        env_a = _envoltoria(_engastada(viga, internos))
        Mmax_a = _no_grid(env_a, x, "M_max")
        Mmin_a = _no_grid(env_a, x, "M_min")
        # a) positivo nunca menor que o de engastamento nos apoios internos
        for i in range(len(viga.tramos)):
            a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
            m = (x >= a - 1e-9) & (x <= b + 1e-9)
            if not m.any():
                continue
            antes = float(np.max(env.M_max[m]))
            depois = float(np.max(np.maximum(env.M_max[m], Mmax_a[m])))
            if depois > antes + 1e-6:
                res.positivos.append((i, antes, depois))
        env.M_max = np.maximum(env.M_max, Mmax_a)
        # b) apoio interno largo, solidário ao pilar
        for k in internos:
            ap = viga.apoios[k]
            lances = [h for h in (ap.altura_pilar_acima,
                                  ap.altura_pilar_abaixo) if h > 1e-9]
            if not lances:
                continue
            l_pil = min(lances)
            xk = viga.x_apoios[k]
            meia = ap.largura / 200.0
            janela = (x >= xk - meia - 1e-9) & (x <= xk + meia + 1e-9)
            M_eng = float(np.min(Mmin_a[janela])) if janela.any() else 0.0
            M_mod = float(np.min(env.M_min[janela])) if janela.any() else 0.0
            aplica = ap.largura > l_pil / 4.0 + 1e-9
            res.internos.append(CorrecaoInterno(
                apoio=k + 1, largura=ap.largura, l_pilar=l_pil,
                aplica=aplica, M_eng=M_eng, M_modelo=M_mod))
            if not aplica or M_eng >= M_mod - 1e-6:
                continue
            # o trecho negativo contínuo em torno do apoio no modelo engastado
            neg = Mmin_a < 0.0
            i0 = int(np.argmin(np.abs(x - xk)))
            ini, fim = i0, i0
            while ini > 0 and neg[ini - 1]:
                ini -= 1
            while fim < len(x) - 1 and neg[fim + 1]:
                fim += 1
            env.M_min[ini:fim + 1] = np.minimum(env.M_min[ini:fim + 1],
                                                Mmin_a[ini:fim + 1])
            res.minimos[k] = (M_eng, (
                f"engastamento perfeito no apoio (14.6.6.1 b): largura "
                f"{ap.largura:g} cm > ℓ/4 = {l_pil / 4.0:g} cm"))

    # c) apoios extremos em pilar
    extremos = [k for k in (0, n - 1)
                if viga.apoios[k].pilar and viga.apoios[k].tipo == "simples"]
    if extremos:
        env_c = None
        for k in extremos:
            p = pilar_no_apoio(viga, k)
            if p is None:
                res.sem_altura.append(k + 1)
                continue
            if env_c is None:
                todos = [j for j in range(n) if viga.apoios[j].pilar
                         and viga.apoios[j].tipo == "simples"]
                env_c = _envoltoria(_engastada(viga, todos))
            Mmin_c = _no_grid(env_c, x, "M_min")
            xk = viga.x_apoios[k]
            meia = viga.apoios[k].largura / 200.0
            janela = (x >= xk - meia - 1e-9) & (x <= xk + meia + 1e-9)
            M_eng = float(np.min(Mmin_c[janela])) if janela.any() else 0.0
            if M_eng >= -1e-9:
                continue
            c = CorrecaoExtremo(apoio=k + 1, M_eng=M_eng, coef=p.coef_viga,
                                M_viga=p.coef_viga * M_eng,
                                M_sup=p.coef_sup * M_eng,
                                M_inf=p.coef_inf * M_eng)
            res.extremos.append(c)
            res.minimos[k] = (c.M_viga, (
                f"solidariedade com o pilar (14.6.6.1 c): "
                f"{c.coef:.3f} × M_eng = {c.coef:.3f} × {M_eng:.2f}"))
        if res.sem_altura:
            avisos.append(av.construtivo(
                f"Solidariedade viga–pilar (14.6.6.1 c): o(s) apoio(s) "
                f"extremo(s) {', '.join(map(str, res.sem_altura))} são "
                f"pilares sem o lance informado, e ficaram como rótula, sem o "
                f"momento de solidariedade. Informe as alturas do pilar acima "
                f"e abaixo da viga, ou use o engastamento mínimo dos "
                f"critérios."))
    if res.positivos:
        avisos.append(av.construtivo(
            "Momento positivo de engastamento perfeito nos apoios internos "
            "(14.6.6.1 a) governou o(s) tramo(s) "
            + ", ".join(str(i + 1) for i, _, _ in res.positivos) + "."))
    return res
