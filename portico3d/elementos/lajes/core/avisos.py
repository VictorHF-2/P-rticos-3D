# -*- coding: utf-8 -*-
"""
avisos.py
Classificação dos avisos do dimensionamento em duas famílias, porque elas não
têm o mesmo peso:

**erro de verificação** -- alguma verificação da norma não fechou. A laje,
como está, não pode ser executada: x/d passou do limite, a flecha estourou, o
cortante não cabe, não há bitola comercial que sirva. Precisa de decisão do
projetista.

**observação construtiva** -- o cálculo fechou, e o programa está contando o
que fez ou lembrando de algo do detalhamento: adotou o maior dos dois
momentos numa borda, majorou o balanço por gamma_n, escolheu espaçamento fora
da faixa recomendada, tratou a parede pela envoltória elástica.

A separação existe para a aba de avisos e o capítulo de pendências da memória
não misturarem "sua laje não passa" com "veja como eu resolvi isto".
"""

from __future__ import annotations

from dataclasses import dataclass

ERRO, CONSTRUTIVO = "erro", "construtivo"

#: Trechos que marcam um aviso como erro de verificação. A classificação é
#: por conteúdo, e não por quem emitiu, para que qualquer módulo possa
#: acrescentar aviso sem saber desta lista.
MARCAS_DE_ERRO = (
    "passa do limite",
    "passa do máximo",
    "não resiste",
    "não cobre",
    "não há bitola",
    "engrosse",
    "flecha excessiva",
    "não couber",
    "não cabe",
    "não ancora",
    "não pode",
    "sem barras",
    "não existe",
    "vinculação insuficiente",
    "abaixo do mínimo",
    "precisa ser mais espessa",
    "não fechou",
    "confira a vinculação",
    "não se sustenta",
    "sem a continuidade",
    "em vez de engastado",
    "acima do limite",
    "estourou",
    "precisa de apoio",
    "não pôde ser calculada",
    "não vale na nervurada",
)


@dataclass
class Aviso:
    """Um aviso classificado."""

    texto: str
    classe: str = CONSTRUTIVO
    laje: str = ""
    item: str = ""                  # item da norma, quando identificado

    @property
    def erro(self) -> bool:
        return self.classe == ERRO


def classificar(texto: str, laje: str = "") -> Aviso:
    """Classifica um aviso pelo conteúdo dele."""
    minusculo = texto.lower()
    classe = ERRO if any(m in minusculo for m in MARCAS_DE_ERRO) \
        else CONSTRUTIVO
    return Aviso(texto=texto, classe=classe, laje=laje)


def classificar_todos(textos: list[str], laje: str = "") -> list[Aviso]:
    return [classificar(t, laje) for t in textos]


def separar(avisos: list[Aviso]) -> tuple[list[Aviso], list[Aviso]]:
    """Devolve ``(erros, observações construtivas)``."""
    return ([a for a in avisos if a.erro],
            [a for a in avisos if not a.erro])


def resumo(avisos: list[Aviso]) -> str:
    """Uma linha dizendo quantos avisos de cada família saíram."""
    erros, obs = separar(avisos)
    if not erros and not obs:
        return "Nenhuma pendência: todas as verificações fecharam."
    partes = []
    if erros:
        partes.append(f"{len(erros)} erro(s) de verificação")
    if obs:
        partes.append(f"{len(obs)} observação(ões) construtiva(s)")
    return " e ".join(partes) + "."
