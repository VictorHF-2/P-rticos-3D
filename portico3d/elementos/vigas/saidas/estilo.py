# -*- coding: utf-8 -*-
"""Paleta e ajustes de estilo compartilhados pelos gráficos e desenhos."""

from __future__ import annotations

import matplotlib as mpl

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
AMARELO = "#bf9000"
CONCRETO = "#e8e4dc"

FONTE = ["Aptos", "Segoe UI", "Calibri", "DejaVu Sans"]


def aplicar_estilo() -> None:
    """Configura o matplotlib para o padrão visual dos relatórios."""
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": FONTE,
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 9,
        "axes.edgecolor": CINZA,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": CINZA_CLARO,
        "grid.linewidth": 0.5,
        "grid.linestyle": "-",
        "xtick.color": CINZA,
        "ytick.color": CINZA,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.dpi": 150,
    })
