# -*- coding: utf-8 -*-
"""
avisos.py
Classificação dos avisos emitidos pelo dimensionamento em dois níveis:

``erro``
    Alguma verificação não foi atendida ou o dado de entrada é inconsistente.
    O pilar, como está, não serve: a seção não resiste à flexão composta, a
    taxa de armadura estoura os 8 %, as barras não cabem na face, a esbeltez
    passa dos 200. Exige ação do projetista.

``construtivo``
    Decisão de detalhamento que o programa tomou e está declarando: entraram
    estribos suplementares, prevaleceu a armadura mínima, o espaçamento dos
    estribos foi reduzido pelo diâmetro da barra longitudinal. Não há nada
    errado.

O aviso é uma subclasse de ``str`` para que todo o código que já o tratava
como texto (f-strings, ``join``, ``dict.fromkeys``, gravação em planilha)
continue funcionando sem alteração; o nível viaja como atributo.
"""

from __future__ import annotations

from typing import Iterable

ERRO = "erro"
CONSTRUTIVO = "construtivo"


class Aviso(str):
    """Texto de aviso com o nível de severidade anexado."""

    nivel: str

    def __new__(cls, texto: str, nivel: str = ERRO) -> "Aviso":
        obj = super().__new__(cls, texto)
        obj.nivel = nivel
        return obj


def erro(texto: str) -> Aviso:
    """Aviso de verificação não atendida ou dado inconsistente."""
    return Aviso(texto, ERRO)


def construtivo(texto: str) -> Aviso:
    """Aviso informativo sobre uma decisão de detalhamento."""
    return Aviso(texto, CONSTRUTIVO)


def nivel_de(texto: str) -> str:
    """Nível de um aviso; texto solto sem nível é tratado como erro.

    O padrão é ``erro`` de propósito: um aviso novo que ninguém classificou
    aparece em vermelho e é notado, em vez de se esconder entre as
    observações construtivas.
    """
    return getattr(texto, "nivel", ERRO)


def prefixar(texto: str, prefixo: str) -> Aviso:
    """Acrescenta um prefixo ao aviso preservando o nível."""
    return Aviso(f"{prefixo}{texto}", nivel_de(texto))


def separar(lista: Iterable[str]) -> tuple[list[Aviso], list[Aviso]]:
    """Devolve (erros, construtivos), sem repetições e na ordem de entrada."""
    vistos: dict[str, str] = dict.fromkeys(lista)     # type: ignore[arg-type]
    erros = [a for a in vistos if nivel_de(a) == ERRO]
    outros = [a for a in vistos if nivel_de(a) != ERRO]
    return erros, outros
