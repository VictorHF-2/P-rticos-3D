# -*- coding: utf-8 -*-
"""
programa_lajes.py
Momentos de laje e charneiras plásticas, chamando o programa de Lajes.

O solver não refaz o que outro programa já resolve: os momentos saem do motor
do programa de Lajes, que calcula em regime rígido-plástico e conhece as
tabelas. Daqui sai só o que o modelo do pórtico sabe — a geometria dos painéis,
quais bordos são contínuos, e o desenho.

O motor é a **cópia** que está em ``portico3d/elementos/lajes``, e não o
programa de Lajes onde ele mora. A diferença importa: assim o resultado deste
programa não muda sozinho quando aquele evoluir. A procedência da cópia está
em ``elementos/__init__.py``.

## Os vínculos de bordo saem do próprio modelo

Bordo que separa **dois painéis** é engastado, porque a laje é contínua ali;
bordo que só tem um painel de um lado é apoiado. É a regra que se usa à mão, e
ela é derivável do modelo sem perguntar nada. A coluna ``bordos`` da tabela
permite corrigir o caso em que a leitura automática não serve — laje em
balanço, bordo livre, apoio que na verdade engasta.

## As charneiras são desenhadas aqui, mas conferidas contra lá

A geometria das charneiras é traçada por este módulo: retas saindo dos vértices
com a inclinação que a razão dos pesos de bordo determina. Ela **não** usa
função interna do outro programa, para não quebrar quando ele mudar por dentro
— em vez disso, o autoteste integra as áreas das regiões desenhadas e compara
com as frações de carga que o programa de Lajes publica. Se o desenho e o
cálculo divergirem, a conferência acusa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .lajes import _cantos
from .modelo import ErroDeModelo, Laje, Modelo

#: Peso de cada vínculo na partição por distância ponderada. São os mesmos do
#: programa de Lajes, e o autoteste confere que continuam sendo.
PESO = {"livre": 0.0, "apoiado": 1.0, "engastado": math.sqrt(3.0)}

VINCULOS = ("apoiado", "engastado", "livre")


def carregar_programa_lajes():
    """Devolve o motor de Lajes copiado, e de qual revisão ele veio."""
    from ..elementos import PROCEDENCIA
    from ..elementos.lajes.core import esforcos, modelo as modelo_lajes

    return esforcos, modelo_lajes, PROCEDENCIA["lajes"]["revisao"]


def motor_de_reacoes():
    """O módulo de reações da cópia, que traz as frações das charneiras."""
    from ..elementos.lajes.core import reacoes, tabelas
    return reacoes, tabelas


# ---------------------------------------------------------------------------
# Vínculos de bordo
# ---------------------------------------------------------------------------

def _aresta(canto_a, canto_b) -> frozenset:
    return frozenset((canto_a, canto_b))


def vinculos_automaticos(modelo: Modelo) -> dict[str, list[str]]:
    """Bordo compartilhado por dois painéis é engastado; os demais, apoiados.

    A ordem dos bordos é a do programa de Lajes: 1 e 3 medem o vão ``a``, 2 e
    4 medem o ``b``. Aqui eles saem na ordem em que os cantos foram percorridos
    e são reordenados depois, quando os vãos forem conhecidos.
    """
    contagem: dict[frozenset, int] = {}
    arestas: dict[str, list[frozenset]] = {}

    for laje in modelo.lajes.values():
        try:
            cantos, _, _ = _cantos(modelo, laje)
        except ErroDeModelo:
            continue
        lados = [_aresta(cantos[k], cantos[(k + 1) % 4]) for k in range(4)]
        arestas[laje.nome] = lados
        for lado in lados:
            contagem[lado] = contagem.get(lado, 0) + 1

    return {nome: ["engastado" if contagem.get(lado, 0) > 1 else "apoiado"
                   for lado in lados]
            for nome, lados in arestas.items()}


# ---------------------------------------------------------------------------
# Charneiras plásticas
# ---------------------------------------------------------------------------

def _extensao(w_perto: float, w_longe: float, a: float,
              limite: float) -> float:
    """Até onde vai a região do bordo próximo, num corte a distância dada."""
    if w_perto <= 0.0:
        return 0.0
    contra = a * w_perto / (w_perto + w_longe) if w_longe > 0.0 else a
    if math.isinf(limite):
        return min(contra, a)
    return max(0.0, min(w_perto * limite, contra, a))


def charneiras(a: float, b: float, vinculos: tuple[str, str, str, str],
               n: int = 60) -> dict[str, np.ndarray]:
    """As linhas de ruptura do painel, em coordenadas locais (x ao longo de b).

    Devolve as duas fronteiras longitudinais — entre o bordo 2 e o miolo, e
    entre o miolo e o bordo 4 — e a divisa transversal entre os bordos 1 e 3.
    São as retas a partir dos vértices cuja inclinação sai da razão dos pesos:
    bordo engastado atrai mais área que apoiado, na razão de √3 para 1.
    """
    w1, w2, w3, w4 = (PESO[v] for v in vinculos)
    xs = np.linspace(0.0, b, n)
    baixo, cima = [], []
    for x in xs:
        r1 = x / w1 if w1 > 0.0 else math.inf
        r3 = (b - x) / w3 if w3 > 0.0 else math.inf
        limite = min(r1, r3)
        y2 = _extensao(w2, w4, a, limite)
        y4 = _extensao(w4, w2, a, limite)
        baixo.append(y2)
        cima.append(a - y4)

    divisa = (b * w1 / (w1 + w3)) if (w1 + w3) > 0.0 else b / 2.0
    y_divisa = min(_extensao(w2, w4, a, min(divisa / w1 if w1 else math.inf,
                                            (b - divisa) / w3 if w3
                                            else math.inf)), a)
    y_topo = a - _extensao(w4, w2, a, min(divisa / w1 if w1 else math.inf,
                                          (b - divisa) / w3 if w3
                                          else math.inf))

    return {
        "borda2": np.column_stack([xs, np.array(baixo)]),
        "borda4": np.column_stack([xs, np.array(cima)]),
        "divisa": np.array([[divisa, y_divisa], [divisa, y_topo]]),
    }


def fracoes_das_regioes(a: float, b: float,
                        vinculos: tuple[str, str, str, str],
                        n: int = 20_000) -> tuple[float, float, float, float]:
    """Fração da área que cabe a cada bordo, integrando as regiões desenhadas.

    Serve de aferição: o programa de Lajes publica essas mesmas frações por
    outro caminho, e o autoteste exige que os dois números coincidam.
    """
    w1, w2, w3, w4 = (PESO[v] for v in vinculos)
    if w1 + w2 + w3 + w4 <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)

    areas = [0.0, 0.0, 0.0, 0.0]
    dx = b / n
    for k in range(n):
        x = (k + 0.5) * dx
        r1 = x / w1 if w1 > 0.0 else math.inf
        r3 = (b - x) / w3 if w3 > 0.0 else math.inf
        limite = min(r1, r3)
        y2 = _extensao(w2, w4, a, limite)
        y4 = _extensao(w4, w2, a, limite)
        meio = max(0.0, a - y2 - y4)
        areas[1] += y2 * dx
        areas[3] += y4 * dx
        if meio > 0.0:
            if r1 < r3:
                areas[0] += meio * dx
            elif r3 < r1:
                areas[2] += meio * dx
            else:
                areas[0] += meio * dx / 2.0
                areas[2] += meio * dx / 2.0
    total = a * b
    return tuple(x / total for x in areas)           # type: ignore


# ---------------------------------------------------------------------------
# Momentos
# ---------------------------------------------------------------------------

@dataclass
class MomentosDaLaje:
    """O que o programa de Lajes devolveu, no vocabulário do pórtico."""

    laje: str
    revisao: str
    a: float                        # menor vão
    b: float                        # maior vão
    direcao_a: str                  # "X" ou "Y", a direção do menor vão
    vinculos: tuple[str, str, str, str]
    ma: float = 0.0                 # kN·m/m, momento positivo na direção a
    mb: float = 0.0                 # kN·m/m, na direção b
    m_negativos: dict[int, float] = field(default_factory=dict)
    carga: float = 0.0              # kN/m² de cálculo
    avisos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        negativos = "  ".join(f"bordo {k}: {v:.2f}"
                              for k, v in sorted(self.m_negativos.items()))
        return (f"{self.laje}: {self.a:.2f} × {self.b:.2f} m  "
                f"p_d = {self.carga:.2f} kN/m²\n"
                f"    m{self.direcao_a.lower()} = {self.ma:.2f}   "
                f"m{'y' if self.direcao_a == 'X' else 'x'} = {self.mb:.2f} "
                f"kN·m/m" + (f"\n    negativos: {negativos}" if negativos
                             else ""))


def calcular_momentos(modelo: Modelo, laje: Laje,
                      vinculos: list[str] | None = None) -> MomentosDaLaje:
    """Momentos do painel, pelo programa de Lajes."""
    esforcos, modelo_lajes, revisao = carregar_programa_lajes()

    cantos, lx, ly = _cantos(modelo, laje)
    automaticos = vinculos or vinculos_automaticos(modelo).get(
        laje.nome, ["apoiado"] * 4)

    # O programa de Lajes exige ``a`` como o menor vão, e ordena os bordos de
    # modo que 1 e 3 meçam ``a``. Os cantos foram percorridos começando pelo
    # lado paralelo a X, então o bordo 1 mede lx.
    if lx <= ly:
        a, b, direcao_a = lx, ly, "X"
        ordem = automaticos
    else:
        a, b, direcao_a = ly, lx, "Y"
        ordem = [automaticos[1], automaticos[2], automaticos[3],
                 automaticos[0]]

    bordos = [modelo_lajes.Bordo(vinculo=v) for v in ordem]
    laje_deles = modelo_lajes.Laje(
        nome=laje.nome, a=a, b=b, h=max(laje.espessura, 0.01) * 100.0,
        bordos=bordos, permanente_extra=laje.permanente,
        variavel=laje.acidental)
    resultado = esforcos.calcular(laje_deles, modelo_lajes.Config())

    return MomentosDaLaje(
        laje=laje.nome, revisao=revisao, a=a, b=b, direcao_a=direcao_a,
        vinculos=tuple(ordem), ma=resultado.ma, mb=resultado.mb,
        m_negativos=dict(resultado.m_neg), carga=resultado.p_d,
        avisos=list(resultado.avisos))
