# -*- coding: utf-8 -*-
"""
cache_motores.py
As chamadas aos motores de Pilares e de Vigas, sem repetição e em paralelo.

**Sem repetição.** O mesmo lance e a mesma viga eram dimensionados várias
vezes numa sessão: no "Dimensionar", de novo na armadura 3D de cada
pavimento, no projeto completo, na compatibilização. O motor é função pura da
entrada — a mesma ``Pilar`` (ou a mesma ``Viga`` com a mesma envoltória do
pórtico) dá sempre o mesmo resultado —, e por isso o resultado é guardado
pela **impressão da entrada** (o ``para_dict`` do motor, que é o ``asdict``
dela inteira, mais a envoltória externa no caso da viga). Entrada diferente,
chave diferente: um modelo alterado nunca reaproveita resultado velho, e não
há invalidação a esquecer.

O resultado guardado é o mesmo objeto devolvido antes: quem o recebe só lê.
É o que o código do Pórticos faz — as verificações, as transições e os nós
anotam nos objetos deles, não no resultado do motor.

**Em paralelo.** Os lances de pilar são independentes entre si, e o motor de
Pilares é a parte lenta do programa (alguns segundos por combinação de
lance). Os que não estão no cache vão para um pool de processos, um por
núcleo, menos um. Dentro de cada processo a busca paralela do próprio motor
fica desligada (``PILARES_SEM_PARALELO``), para não abrir pool dentro de pool.
O resultado é o mesmo da execução em série, na mesma ordem.

``PORTICOS_SEM_PARALELO=1`` desliga o paralelismo daqui (depuração, ou uma
máquina em que processos filhos não sejam bem-vindos); ``limpar()`` esvazia o
cache.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor

import numpy as np

#: Variável de ambiente que desliga o paralelismo do Pórticos.
SEM_PARALELO = "PORTICOS_SEM_PARALELO"
#: Quantos resultados de cada motor ficam guardados (os mais antigos saem).
LIMITE = 5000
#: Erros que o motor de Pilares pode levantar para uma entrada ruim — os
#: mesmos que ``verificar_pilares`` transforma em ``erro`` da verificação.
ERROS_DE_ENTRADA = (ValueError, ZeroDivisionError)

_PILARES: OrderedDict = OrderedDict()
_VIGAS: OrderedDict = OrderedDict()
_EXECUTOR: ProcessPoolExecutor | None = None
_EXECUTOR_FALHOU = False
#: Contagem das chamadas, para medir o que o cache poupou.
contagem = {"pilares_calculados": 0, "pilares_do_cache": 0,
            "vigas_calculadas": 0, "vigas_do_cache": 0}


def limpar() -> None:
    _PILARES.clear()
    _VIGAS.clear()
    for k in contagem:
        contagem[k] = 0


def _padrao(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, (set, frozenset, tuple)):
        return list(obj)
    return str(obj)


def impressao(*partes) -> str:
    """SHA-256 do conteúdo, de forma estável (chaves ordenadas)."""
    texto = json.dumps(partes, sort_keys=True, default=_padrao,
                       ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _guardar(cache: OrderedDict, chave: str, valor) -> None:
    cache[chave] = valor
    cache.move_to_end(chave)
    while len(cache) > LIMITE:
        cache.popitem(last=False)


# ---------------------------------------------------------------------------
# Pilares
# ---------------------------------------------------------------------------

def _inicio_trabalhador() -> None:
    # o processo filho não abre o pool da busca do motor de Pilares
    os.environ["PILARES_SEM_PARALELO"] = "1"


def _dimensionar_pilar(pilar):
    """No processo filho: o motor, e o erro de entrada como valor."""
    from .elementos.pilares.core.dimensionar import dimensionar
    try:
        return dimensionar(pilar), ""
    except ERROS_DE_ENTRADA as erro:
        return None, str(erro)


def _executor() -> ProcessPoolExecutor | None:
    global _EXECUTOR, _EXECUTOR_FALHOU
    if os.environ.get(SEM_PARALELO) or _EXECUTOR_FALHOU:
        return None
    if _EXECUTOR is None:
        n = max(1, min(8, (os.cpu_count() or 2) - 1))
        if n < 2:
            return None
        try:
            _EXECUTOR = ProcessPoolExecutor(max_workers=n,
                                            initializer=_inicio_trabalhador)
        except Exception:                                  # noqa: BLE001
            _EXECUTOR_FALHOU = True
            return None
    return _EXECUTOR


def dimensionar_pilares(pilares: list) -> list[tuple[object, str]]:
    """``[(resultado, erro)]`` de cada ``Pilar``, na ordem dada.

    Os que já estão no cache voltam dele; os outros são calculados — em
    paralelo quando há mais de um e o pool está disponível. ``erro`` é o
    texto do erro de entrada do motor (e ``resultado`` é None).
    """
    global _EXECUTOR_FALHOU
    chaves = [impressao(p.para_dict()) for p in pilares]
    saida: list = [None] * len(pilares)
    faltam: dict[str, list[int]] = {}
    for i, chave in enumerate(chaves):
        if chave in _PILARES:
            saida[i] = _PILARES[chave]
            _PILARES.move_to_end(chave)
            contagem["pilares_do_cache"] += 1
        else:
            faltam.setdefault(chave, []).append(i)

    pendentes = [(chave, pilares[idx[0]]) for chave, idx in faltam.items()]
    calculados: dict[str, tuple] = {}
    ex = _executor() if len(pendentes) > 1 else None
    if ex is not None:
        try:
            futuros = {chave: ex.submit(_dimensionar_pilar, p)
                       for chave, p in pendentes}
            for chave, futuro in futuros.items():
                calculados[chave] = futuro.result()
        except Exception:                                  # noqa: BLE001
            # pool quebrado (processo morto, ambiente sem spawn): em série
            _EXECUTOR_FALHOU = True
            calculados = {}
    for chave, p in pendentes:
        if chave not in calculados:
            calculados[chave] = _dimensionar_pilar(p)

    for chave, idx in faltam.items():
        valor = calculados[chave]
        contagem["pilares_calculados"] += 1
        _guardar(_PILARES, chave, valor)
        for i in idx:
            saida[i] = valor
    return saida


# ---------------------------------------------------------------------------
# Vigas
# ---------------------------------------------------------------------------

def dimensionar_viga(deles, externa, calcular):
    """O resultado do motor de Vigas para a ``Viga`` ``deles`` com a
    envoltória externa ``externa`` (None = a da viga contínua), calculado por
    ``calcular(deles, externa)`` só se ainda não estiver no cache.

    A chave leva a viga inteira e a impressão da envoltória externa
    (``externa.chave``, posta por ``envoltoria_externa``); envoltória sem
    impressão não é guardada — o cache não adivinha o que ela faz.
    """
    marca = getattr(externa, "chave", None) if externa is not None else ""
    if marca is None:
        return calcular(deles, externa)
    chave = impressao(deles.para_dict(), marca)
    if chave in _VIGAS:
        _VIGAS.move_to_end(chave)
        contagem["vigas_do_cache"] += 1
        return _VIGAS[chave]
    resultado = calcular(deles, externa)
    contagem["vigas_calculadas"] += 1
    _guardar(_VIGAS, chave, resultado)
    return resultado
