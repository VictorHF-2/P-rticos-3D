# -*- coding: utf-8 -*-
"""Cálculo e detalhamento de pilares de concreto armado (ABNT NBR 6118)."""

#: Revisão do programa. Acompanha o nome da pasta ("Pilares R02") e é o que
#: aparece na janela "Sobre", no rodapé da memória de cálculo e no
#: ``--versao``: uma memória entregue sem dizer qual revisão a produziu não
#: pode ser reproduzida depois.
__version__ = "R05"

#: Identificação do build: commit e data gravados por ``construir.py`` em
#: ``pilares/_build.py`` (fora do controle de versão) no momento de empacotar.
#: Rodando do código-fonte, sem esse arquivo, é "desenvolvimento" -- uma
#: memória com essa marca não saiu de um executável liberado.
try:
    from ._build import BUILD
except ImportError:                                        # pragma: no cover
    BUILD = "desenvolvimento"

#: O que as saídas exibem: revisão e build, ex. ``R05 (a1b2c3d, 03/11/2026)``.
VERSAO_COMPLETA = f"{__version__} ({BUILD})"

#: Edição da norma implementada. Vale para a numeração dos itens citados nas
#: saídas -- em especial 15.8.2 (alfa_b) e 15.8.3.3.5, que mudaram de 2014
#: para 2026.
EDICAO_NORMA = "ABNT NBR 6118:2026"
