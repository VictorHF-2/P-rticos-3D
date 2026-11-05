# -*- coding: utf-8 -*-
"""
busca.py
Varredura **exata** dos arranjos candidatos nos métodos cuja 2ª ordem depende
da armadura (pilar-padrão com M, N, 1/r e método geral).

A lista de candidatos vem ordenada por custo (``arranjo.custo``), e o primeiro
que passa é o mais barato -- mas cada teste é uma análise de 2ª ordem inteira.
Em vez de testar um a um (lento) ou por bisseção (rápido, mas a aprovação não
cresce de forma estrita com o custo e a bisseção pode perder o ótimo), a busca
faz duas coisas:

1. **Rejeição rigorosa sem a análise.** A relação momento-curvatura da seção é
   côncava: a rigidez secante nunca passa da rigidez **inicial** da curva de
   deformabilidade (tangente na origem, concreto a 1,10 fcd e aço, seção
   inteira, em torno do CG geométrico). Com essa rigidez máxima a amplificação
   ``1/(1 - Nd le²/(10 EI))`` dá um piso do momento verdadeiro: o candidato que
   reprova com o piso -- ou cuja barra mais rígida possível já é instável --
   reprova com certeza. É uma conta de milissegundos.
2. **Avaliação em paralelo** dos sobreviventes, em lotes na ordem de custo, um
   por núcleo, depois de alguns testados no próprio processo; fica o primeiro
   aprovado **na ordem** -- o resultado é o mesmo da varredura linear.

O piso e a lista são consumidos sob demanda: nada é calculado além do lote em
que o aprovado aparece.

No método geral o pilar-padrão é só uma estimativa da barra discretizada; o
piso leva uma margem (``MARGEM_GERAL``) para continuar sendo piso.
"""

from __future__ import annotations

import itertools
import math
import os
from concurrent.futures import ProcessPoolExecutor

from . import seccional as sc

#: Fração do e2 do piso usada na rejeição (1 = o piso inteiro).
MARGEM_DIAGRAMA = 1.0
MARGEM_GERAL = 0.7
#: Variável de ambiente que desliga o paralelismo (testes, depuração).
SEM_PARALELO = "PILARES_SEM_PARALELO"
#: Candidatos testados no próprio processo antes de abrir o pool.
SEQUENCIAIS = 3

_EXECUTOR: ProcessPoolExecutor | None = None
_EXECUTOR_FALHOU = False


def rigidez_inicial(secao: sc.SecaoDiscreta, direcao: str,
                    fator_fluencia: float = 1.0) -> float:
    """Teto da rigidez secante, kN·cm²: tangente na origem da curva de
    deformabilidade (pico 1,10 fcd, ``n``), seção de concreto inteira mais o
    aço, em torno do CG geométrico (eixo que dá a maior inércia entre os
    paralelos ao do CG transformado -- continua teto)."""
    c = secao.concreto
    n = c.expoente_n
    eps_c2 = c.eps_c2_mil * fator_fluencia / 1000.0
    Ec0 = 1.10 * c.fcd_kNcm2 * n / eps_c2
    Es = secao.aco.Es_kNcm2
    prop = secao.propriedades
    I = prop.Ix if direcao == "x" else prop.Iy
    aco = sum(b.area * (b.x if direcao == "x" else b.y) ** 2
              for b in secao.barras)
    return Ec0 * I + (Es - Ec0) * aco


def amplificacao(Nd: float, le: float, EI: float) -> float:
    """``1/(1 - Nd le²/(10 EI))``; ``inf`` se a carga crítica foi atingida."""
    x = Nd * le * le / (10.0 * EI) if EI > 0 else float("inf")
    return 1.0 / (1.0 - x) if x < 1.0 else float("inf")


def _executor() -> ProcessPoolExecutor | None:
    global _EXECUTOR, _EXECUTOR_FALHOU
    if os.environ.get(SEM_PARALELO) or _EXECUTOR_FALHOU:
        return None
    if _EXECUTOR is None:
        try:
            n = max(1, min(8, (os.cpu_count() or 2) - 1))
            _EXECUTOR = ProcessPoolExecutor(max_workers=n,
                                            initializer=_inicio_trabalhador)
        except Exception:                                  # noqa: BLE001
            _EXECUTOR_FALHOU = True
            return None
    return _EXECUTOR


def _inicio_trabalhador() -> None:
    # um trabalhador não abre pool próprio
    os.environ[SEM_PARALELO] = "1"


def _avaliar(args):
    from .dimensionar import FATIAS_BUSCA, _testar_arranjo
    pilar, a, situacoes, nu, As_nec, minimo, esb = args
    passou, _, avisos = _testar_arranjo(pilar, a, situacoes, nu, As_nec,
                                        FATIAS_BUSCA, minimo, esb)
    return passou, avisos


def primeiro_aprovado(candidatos, pilar, situacoes, nu, As_nec, minimo, esb):
    """O primeiro candidato aprovado na ordem de ``candidatos`` (iterável,
    consumido sob demanda); ``(None, avisos)`` se nenhum.

    Os ``SEQUENCIAIS`` primeiros são testados aqui mesmo -- na maioria dos
    pilares o ótimo está entre eles e abrir o pool não compensaria; os demais
    vão em lotes paralelos, um por núcleo, mantendo a ordem."""
    it = iter(candidatos)
    ultimo: list[str] = []
    args = lambda a: (pilar, a, situacoes, nu, As_nec, minimo, esb)  # noqa: E731
    for _ in range(SEQUENCIAIS):
        a = next(it, None)
        if a is None:
            return None, ultimo
        passou, ultimo = _avaliar(args(a))
        if passou:
            return a, []
    ex = _executor()
    if ex is not None:
        lote = ex._max_workers
        pendentes: list = []
        try:
            while True:
                grupo = list(itertools.islice(it, lote))
                if not grupo:
                    return None, ultimo
                pendentes = grupo
                resultados = list(ex.map(_avaliar, [args(a) for a in grupo]))
                pendentes = []
                for a, (passou, avisos) in zip(grupo, resultados):
                    ultimo = avisos
                    if passou:
                        return a, []
        except Exception:                                  # noqa: BLE001
            global _EXECUTOR_FALHOU
            _EXECUTOR_FALHOU = True      # cai para a avaliação sequencial
            it = itertools.chain(pendentes, it)
    for a in it:
        passou, ultimo = _avaliar(args(a))
        if passou:
            return a, []
    return None, ultimo
