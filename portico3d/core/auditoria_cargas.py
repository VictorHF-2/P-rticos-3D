# -*- coding: utf-8 -*-
"""
auditoria_cargas.py
O que um caso de carga aplica ao modelo, em texto e em número — para o
usuário **conferir** quais cargas estão sendo consideradas.

Nada aqui desenha: a vista de cargas (``ui/vista3d``) e o relatório leem
daqui, de modo que o que está na tela e o que está no texto saem da mesma
conta. A conferência mais útil é a **resultante**: a soma das forças do caso no
sistema global. Num caso de peso próprio ela tem de bater com o peso da
estrutura; numa ação de vento, com a força horizontal total. Quem audita lê
essa linha antes de olhar seta por seta.

Convenções, as mesmas do resto do programa: forças em kN, cargas distribuídas
em kN/m **por metro de barra**, momentos em kN·m, recalques em m e rad; sistema
global com Z para cima, de modo que gravidade é Fz negativo.
"""

from __future__ import annotations

import numpy as np

from .modelo import CargaDistribuida, CasoDeCarga, Modelo
from .montagem import preparar_barras

GRAUS = ("Fx", "Fy", "Fz", "Mx", "My", "Mz")


def intensidades_globais(c: CargaDistribuida, preparadas) -> tuple[np.ndarray,
                                                                    np.ndarray]:
    """Intensidade nas duas pontas do trecho, no sistema global, kN/m.

    Carga em eixo local é girada pela mesma matriz que a montagem usa
    (``R.T @ q``); carga global já está pronta.
    """
    qa, qb = c.vetor_inicio, c.vetor_fim
    if c.sistema == "local":
        R = preparadas[c.barra].R
        qa, qb = R.T @ qa, R.T @ qb
    return np.asarray(qa, float), np.asarray(qb, float)


def comprimento_do_trecho(modelo: Modelo, c: CargaDistribuida) -> float:
    """Comprimento carregado, em metros: a fração da barra entre os nós."""
    return (c.fim - c.inicio) * modelo.comprimento(c.barra)


def total_da_distribuida(modelo: Modelo, c: CargaDistribuida,
                         preparadas) -> np.ndarray:
    """Força total que a carga distribuída aplica, kN, no sistema global.

    A intensidade varia linearmente no trecho, e o total é a média das duas
    pontas vezes o comprimento — exato para uniforme e para trapézio.
    """
    qa, qb = intensidades_globais(c, preparadas)
    return 0.5 * (qa + qb) * comprimento_do_trecho(modelo, c)


def resultante(modelo: Modelo, caso: CasoDeCarga,
               preparadas=None) -> dict[str, np.ndarray]:
    """Soma das forças do caso (``Fx, Fy, Fz``), separada por origem."""
    preparadas = preparadas if preparadas is not None else preparar_barras(
        modelo)
    nodais = np.zeros(3)
    for c in caso.nodais:
        nodais += c.vetor[:3]
    distribuidas = np.zeros(3)
    for c in caso.distribuidas:
        distribuidas += total_da_distribuida(modelo, c, preparadas)
    return {"nodais": nodais, "distribuidas": distribuidas,
            "total": nodais + distribuidas}


def _componentes(vetor, nomes, unidade: str, limite: float = 1e-12) -> str:
    partes = [f"{n} = {v:+.2f}" for n, v in zip(nomes, vetor)
              if abs(v) > limite]
    return (", ".join(partes) + f" {unidade}") if partes else "nula"


def texto_da_nodal(c) -> str:
    return (f"Nó {c.no}: forças {_componentes(c.vetor[:3], GRAUS[:3], 'kN')}"
            f"; momentos {_componentes(c.vetor[3:], GRAUS[3:], 'kN·m')}")


def texto_da_distribuida(modelo: Modelo, c: CargaDistribuida,
                         preparadas) -> str:
    qa, qb = c.vetor_inicio, c.vetor_fim
    forma = ("uniforme" if c.uniforme else "trapezoidal")
    qs = _componentes(qa, ("qx", "qy", "qz"), "kN/m")
    if not c.uniforme:
        qs += " → " + _componentes(qb, ("qx", "qy", "qz"), "kN/m")
    total = total_da_distribuida(modelo, c, preparadas)
    return (f"Barra {c.barra}: {forma}, {qs} (eixos {c.sistema}), de "
            f"{100 * c.inicio:.0f} % a {100 * c.fim:.0f} % do vão — "
            f"{comprimento_do_trecho(modelo, c):.2f} m, total global "
            f"{_componentes(total, GRAUS[:3], 'kN')}")


def texto_do_recalque(c) -> str:
    graus = ("ux", "uy", "uz", "rx", "ry", "rz")
    partes = [f"{g} = {v * 1000.0:+.2f} mm" if g[0] == "u"
              else f"{g} = {v:+.5f} rad"
              for g, v in zip(graus, c.vetor) if abs(v) > 1e-15]
    return f"Nó {c.no}: recalque {', '.join(partes) or 'nulo'}"


def texto_da_barra(modelo: Modelo, caso: CasoDeCarga, barra: str,
                   preparadas) -> str:
    """Todas as cargas do caso que caem nesta barra."""
    cargas = [c for c in caso.distribuidas if c.barra == barra]
    if not cargas:
        return f"Barra {barra}: nenhuma carga distribuída no caso '{caso.nome}'"
    total = sum((total_da_distribuida(modelo, c, preparadas) for c in cargas),
                np.zeros(3))
    linhas = [f"Barra {barra} · caso '{caso.nome}': {len(cargas)} carga(s), "
              f"total {_componentes(total, GRAUS[:3], 'kN')}"]
    linhas += ["  " + texto_da_distribuida(modelo, c, preparadas)
               for c in cargas[:6]]
    if len(cargas) > 6:
        linhas.append(f"  ... e mais {len(cargas) - 6}")
    return "\n".join(linhas)


def texto_do_no(caso: CasoDeCarga, no: str) -> str:
    nodais = [c for c in caso.nodais if c.no == no]
    recalques = [c for c in caso.recalques if c.no == no]
    if not nodais and not recalques:
        return f"Nó {no}: nenhuma carga nodal nem recalque no caso '{caso.nome}'"
    return "\n".join([texto_da_nodal(c) for c in nodais]
                     + [texto_do_recalque(c) for c in recalques])


def resumo_do_caso(modelo: Modelo, caso: CasoDeCarga,
                   limite: int = 40) -> str:
    """O caso por inteiro, para o relatório: totais e uma linha por carga."""
    preparadas = preparar_barras(modelo)
    soma = resultante(modelo, caso, preparadas)
    linhas = [
        f"Cargas do caso '{caso.nome}' ({caso.natureza}"
        + (f", {caso.categoria}" if caso.categoria else "") + "): "
        f"{len(caso.nodais)} nodais, {len(caso.distribuidas)} distribuídas, "
        f"{len(caso.recalques)} recalques.",
        "Resultante (sistema global): "
        + _componentes(soma["total"], GRAUS[:3], "kN")
        + f"  [nodais: {_componentes(soma['nodais'], GRAUS[:3], 'kN')}; "
        f"distribuídas: {_componentes(soma['distribuidas'], GRAUS[:3], 'kN')}]"]
    itens = ([texto_da_nodal(c) for c in caso.nodais]
             + [texto_da_distribuida(modelo, c, preparadas)
                for c in caso.distribuidas]
             + [texto_do_recalque(c) for c in caso.recalques])
    linhas += ["  " + t for t in itens[:limite]]
    if len(itens) > limite:
        linhas.append(f"  ... e mais {len(itens) - limite} cargas "
                      "(clique nelas na vista para ler cada uma)")
    return "\n".join(linhas)
