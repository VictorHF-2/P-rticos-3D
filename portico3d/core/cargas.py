# -*- coding: utf-8 -*-
"""
cargas.py
Geradores de carga: o que o programa consegue deduzir do próprio modelo.

O peso próprio sai da geometria e do peso específico do material. O desaprumo
sai da altura da estrutura e das cargas verticais por pavimento, segundo as
imperfeições geométricas globais da NBR 6118.
"""

from __future__ import annotations

from .modelo import CasoDeCarga, ErroDeModelo, Modelo


def peso_proprio(modelo: Modelo, caso: CasoDeCarga,
                 fator: float = 1.0) -> list[str]:
    """Acrescenta ao caso o peso próprio das barras, em -Z global.

    A carga de cada barra é ``γ · A``, por metro de barra. Devolve a lista das
    barras em que a carga entrou — barra de material sem peso específico fica
    de fora, e aparece na lista de omissões de quem chamou.
    """
    aplicadas = []
    for nome, barra in modelo.barras.items():
        material = modelo.materiais.get(barra.material)
        secao = modelo.secoes.get(barra.secao)
        if material is None or secao is None:
            raise ErroDeModelo(
                f"barra '{nome}' cita material ou seção inexistente")
        if material.peso_especifico == 0.0:
            continue
        caso.distribuida(nome, qz=-fator * material.peso_especifico * secao.A,
                         sistema="global")
        aplicadas.append(nome)
    return aplicadas


def alternancia(modelo: Modelo, base: str, grupos: list[list[str]],
                padroes: tuple[str, ...] = ("todas", "alternadas",
                                            "adjacentes")) -> list[str]:
    """Desdobra um caso acidental nos seus padrões de carregamento.

    ``grupos`` lista os conjuntos de barras e nós de cada tramo, na ordem em
    que eles se sucedem — é dessa ordem que saem os padrões:

    * ``todas``       todos os tramos carregados;
    * ``alternadas``  tramos ímpares e tramos pares, que dão os máximos de vão;
    * ``adjacentes``  cada par de tramos consecutivos, que dá o máximo sobre o
      apoio entre eles.

    Os casos gerados herdam a classificação do caso base e **nascem todos no
    mesmo grupo excludente**: são padrões alternativos da mesma ação acidental,
    e combiná-los entre si contaria a mesma carga duas vezes. O caso base é
    removido do modelo, para não sobrar somado aos seus próprios padrões.
    """
    if base not in modelo.casos:
        raise ErroDeModelo(f"caso de carga '{base}' não existe")
    if len(grupos) < 2:
        raise ErroDeModelo(
            "a alternância precisa de ao menos dois tramos para alternar")

    caso_base = modelo.casos[base]
    chave = caso_base.grupo or f"alternancia:{base}"

    selecoes: list[tuple[str, set[str]]] = []
    if "todas" in padroes:
        selecoes.append(("todas", {n for g in grupos for n in g}))
    if "alternadas" in padroes:
        for rotulo, resto in (("ímpares", 0), ("pares", 1)):
            marcados = {n for i, g in enumerate(grupos) if i % 2 == resto
                        for n in g}
            if marcados:
                selecoes.append((rotulo, marcados))
    if "adjacentes" in padroes:
        for i in range(len(grupos) - 1):
            selecoes.append((f"tramos {i + 1}-{i + 2}",
                             set(grupos[i]) | set(grupos[i + 1])))

    criados = []
    for rotulo, marcados in selecoes:
        nome = f"{base} ({rotulo})"
        novo = modelo.add_caso(nome, caso_base.natureza, caso_base.categoria,
                               chave)
        novo.nodais.extend(c for c in caso_base.nodais if c.no in marcados)
        novo.distribuidas.extend(c for c in caso_base.distribuidas
                                 if c.barra in marcados)
        novo.recalques.extend(caso_base.recalques)
        criados.append(nome)

    del modelo.casos[base]
    return criados


def barras_sem_peso(modelo: Modelo) -> list[str]:
    """Barras cujo material não tem peso específico declarado."""
    return [nome for nome, barra in modelo.barras.items()
            if modelo.materiais[barra.material].peso_especifico == 0.0]
