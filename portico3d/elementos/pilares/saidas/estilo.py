# -*- coding: utf-8 -*-
"""Paleta e ajustes de estilo compartilhados pelos gráficos e desenhos."""

from __future__ import annotations

import matplotlib as mpl
from matplotlib.ticker import FuncFormatter
from ..core import formato

AZUL = "#1f4e79"
AZUL_MEDIO = "#2e75b6"
AZUL_CLARO = "#9dc3e6"
LARANJA = "#c55a11"
LARANJA_CLARO = "#f4b183"
VERDE = "#2e7d4f"
VERDE_CLARO = "#a9d18e"
CINZA = "#595959"
CINZA_MEDIO = "#8c8c8c"
CINZA_CLARO = "#d9d9d9"
VERMELHO = "#a5232f"
VERMELHO_ESCURO = "#5c0f17"
AMARELO = "#bf9000"
CONCRETO = "#e8e4dc"
ROXO = "#6b3fa0"

#: Cores das situações de cálculo, na ordem em que aparecem.
CORES_SITUACOES = (VERMELHO, LARANJA, ROXO, VERDE, AZUL_MEDIO, AMARELO)
#: Marcadores por posição no lance: extremo, meio.
MARCADOR = {"extremo": "o", "meio": "s"}

#: Segoe UI vem em todo Windows; Aptos e Calibri só com o Office. A lista é
#: do matplotlib, que procura na ordem e não troca a fonte sem avisar.
FONTE = ["Segoe UI", "Calibri", "Arial", "DejaVu Sans"]


def aplicar_estilo() -> None:
    """Configura o matplotlib para o padrão visual dos relatórios."""
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": FONTE,
        "font.size": 9.5,
        "axes.titlesize": 10.5,
        "axes.titleweight": "bold",
        "axes.titlecolor": "#1a1d21",
        "axes.titlepad": 8,
        "axes.labelsize": 9.5,
        "axes.labelcolor": "#33383f",
        "axes.edgecolor": "#8c939d",
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#e3e6ea",
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.color": "#5b6470",
        "ytick.color": "#5b6470",
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "legend.fontsize": 8.5,
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.edgecolor": "#d7dbe1",
        "legend.fancybox": True,
        "legend.borderpad": 0.6,
        "lines.solid_capstyle": "round",
        "figure.facecolor": "white",
        "figure.titlesize": 12,
        "figure.titleweight": "bold",
        "savefig.facecolor": "white",
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.08,
    })


def num(valor: float, casas: int = 2) -> str:
    """Número com vírgula decimal e ponto de milhar, como nas tabelas."""
    return formato.num(valor, casas)


def virgula(ax) -> None:
    """Rótulos dos eixos com vírgula decimal."""
    def fmt(v, _pos):
        if abs(v - round(v)) < 1e-9:
            return num(round(v), 0).replace("-", "−")
        casas = 1 if abs(v * 10 - round(v * 10)) < 1e-9 else 2
        return num(v, casas).replace("-", "−")
    ax.xaxis.set_major_formatter(FuncFormatter(fmt))
    ax.yaxis.set_major_formatter(FuncFormatter(fmt))
