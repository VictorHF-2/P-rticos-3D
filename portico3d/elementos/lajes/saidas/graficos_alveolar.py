# -*- coding: utf-8 -*-
"""
graficos_alveolar.py
Figuras da laje alveolar: seção transversal com as cordoalhas, tensões ao
longo do vão (ato e serviço), esforços contra resistências e a elevação do
painel com os comprimentos de transferência.

Cores: como na laje treliçada -- armadura em azul (aqui só há a ativa, na
face inferior); os limites de tensão em vermelho tracejado.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

from ..core.alveolar import ResultadoAlveolar
from . import estilo

estilo.aplicar_estilo()

COR_ATIVA = estilo.AZUL_MEDIO
COR_LIM = estilo.VERMELHO


def figura_secao(res: ResultadoAlveolar) -> Figure:
    """Painel (alvéolos e cordoalhas) e capa, com as cotas principais."""
    l = res.laje
    s = l.sec
    b, h, hc = s.b, s.h, l.capa
    bc = l.largura_capa if l.largura_capa is not None else b
    fig = Figure(figsize=(8.4, 4.0))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((0, 0), b, h, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.9))
    if hc > 0:
        x0 = (b - bc) / 2.0
        ax.add_patch(Rectangle((x0, h), bc, hc, fc="#d9d3c5",
                               ec=estilo.CINZA, lw=0.9))
    n = s.n_alveolos
    if n > 0 and s.tf_inf > 0 and s.tf_sup > 0:
        a = (b - s.sum_bw) / n
        hv = h - s.tf_inf - s.tf_sup
        web = s.sum_bw / (n + 1)
        r = min(a, hv) * 0.18
        for k in range(n):
            x = web + k * (a + web)
            ax.add_patch(FancyBboxPatch(
                (x + r, s.tf_inf + r), a - 2 * r, hv - 2 * r,
                boxstyle=f"round,pad={r:.3f},rounding_size={r:.3f}",
                fc="white", ec=estilo.CINZA, lw=0.8))
    else:
        ax.text(b / 2.0, h / 2.0, "alvéolos não detalhados\n(propriedades "
                "informadas)", ha="center", va="center", fontsize=9,
                color=estilo.CINZA)
    # cordoalhas, espalhadas na largura
    nc = l.n_cordoalhas
    if nc > 0:
        marg = min(6.0, b * 0.06)
        xs = [b / 2.0] if nc == 1 else list(np.linspace(marg, b - marg, nc))
        for x in xs:
            ax.add_patch(Circle((x, l.d_linha), l.phi / 20.0 + 0.25,
                                fc=COR_ATIVA, ec="k", lw=0.5, zorder=5))
    # cotas
    y0 = -3.0
    ax.annotate("", (0, y0), (b, y0), arrowprops=dict(arrowstyle="<->",
                                                      lw=0.8))
    ax.text(b / 2.0, y0 - 2.2, f"{b:g} cm", ha="center", fontsize=9)
    xr = b + 4.0
    ax.annotate("", (xr, 0), (xr, h), arrowprops=dict(arrowstyle="<->",
                                                      lw=0.8))
    ax.text(xr + 1.4, h / 2.0, f"h = {h:g}", rotation=90, va="center",
            fontsize=9)
    if hc > 0:
        ax.annotate("", (xr + 8, h), (xr + 8, h + hc),
                    arrowprops=dict(arrowstyle="<->", lw=0.8))
        ax.text(xr + 9.4, h + hc / 2.0, f"capa {hc:g}", rotation=90,
                va="center", fontsize=9)
    ax.text(b / 2.0, -9.5, f"{nc} Ø{l.phi:g} {l.aco} (azul), CG a "
            f"{l.d_linha:g} cm da face inferior", fontsize=8.5,
            color=COR_ATIVA, ha="center", fontweight="bold")
    ax.set_xlim(-6, b + 22)
    ax.set_ylim(-13, h + hc + 6)
    ax.axis("off")
    ax.set_title(f"Seção transversal — {s.origem}", fontsize=10)
    fig.tight_layout()
    return fig


def _limites(ax, valor, rot, cor=COR_LIM):
    ax.axhline(valor, color=cor, lw=1.0, ls="--")
    ax.text(0.995, valor, rot, transform=ax.get_yaxis_transform(),
            ha="right", va="bottom", fontsize=7.5, color=cor)


def figura_tensoes(res: ResultadoAlveolar) -> Figure:
    """Tensões nas fibras ao longo do meio vão: ato e combinações."""
    fig = Figure(figsize=(8.6, 6.8))
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212, sharex=ax1)
    a = res.ato
    x = np.array(a["x"])
    ver = np.array(a["verificada"])
    ax1.plot(x, a["sig_i"], color=estilo.AZUL, lw=1.4,
             label="fibra inferior")
    ax1.plot(x, a["sig_s"], color=estilo.LARANJA, lw=1.4,
             label="fibra superior")
    if (~ver).any():
        ax1.axvspan(0.0, x[ver][0] if ver.any() else x[-1],
                    color=estilo.CINZA_CLARO, alpha=0.6, lw=0)
        ax1.text(x[0] + 0.02, 0.0, "regularização", fontsize=7.5,
                 color=estilo.CINZA, va="bottom")
    _limites(ax1, a["lim_trac"], f"tração máx. {a['lim_trac']:.2f}")
    _limites(ax1, a["lim_comp"], f"compressão máx. {a['lim_comp']:.2f}")
    ax1.axhline(0.0, color=estilo.CINZA, lw=0.7)
    ax1.set_ylim(a["lim_trac"] * 1.5, a["lim_comp"] * 1.45)
    ax1.set_ylabel("MPa (compressão +)")
    ax1.set_title("Ato da protensão — seção simples")
    ax1.legend(loc="upper left")

    sv = res.servico
    cores = {"QP": estilo.VERDE, "FREQ": estilo.AZUL, "RARA": estilo.LARANJA}
    for comb, tipo in sv["plano"]:
        d = sv["comb"][comb]
        ax2.plot(d["x"], d["sig_i"], color=cores[comb], lw=1.4,
                 label=f"{sv['nomes'][comb]}, inferior")
        ax2.plot(d["x"], d["sig_s"], color=cores[comb], lw=1.0, ls=":",
                 label=f"{sv['nomes'][comb]}, topo do painel")
    lim = sv["lim"]
    tipos = {t for _, t in sv["plano"]}
    if "F" in tipos:
        _limites(ax2, lim["F"], f"ELS-F {lim['F']:.2f}")
    if "D" in tipos:
        _limites(ax2, 0.0, "ELS-D 0")
    _limites(ax2, lim["comp"], f"compressão máx. {lim['comp']:.1f}")
    ax2.axhline(0.0, color=estilo.CINZA, lw=0.7)
    ax2.set_ylim(min(lim["F"], 0.0) * 1.8, lim["comp"] * 1.45)
    ax2.set_ylabel("MPa")
    ax2.set_xlabel("x desde o apoio (m)")
    ax2.set_title("Serviço — por estágio (perda diferida e cargas finais "
                  "na seção composta)")
    ax2.legend(loc="upper left", ncol=2, fontsize=7.5)
    fig.tight_layout()
    return fig


def figura_esforcos(res: ResultadoAlveolar) -> Figure:
    """Md contra MRd e VSd contra VRd1/VRd2, do apoio ao meio do vão."""
    fig = Figure(figsize=(8.6, 6.8))
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212, sharex=ax1)
    fx = res.flexao
    ax1.fill_between(fx["x"], fx["MRd"], color=estilo.AZUL_CLARO, alpha=0.5,
                     lw=0, label="MRd")
    ax1.plot(fx["x"], fx["MRd"], color=estilo.AZUL, lw=1.2)
    ax1.plot(fx["x"], fx["Md"], color=estilo.LARANJA, lw=1.6, label="Md")
    ax1.axhline(fx["Mcr"], color=estilo.CINZA_MEDIO, lw=0.8, ls="--")
    ax1.text(0.995, fx["Mcr"], f"Mcr = {fx['Mcr']:.1f}",
             transform=ax1.get_yaxis_transform(), ha="right", va="bottom",
             fontsize=7.5, color=estilo.CINZA)
    ax1.set_ylabel("kN·m")
    ax1.set_title("Flexão — ELU (MRd cresce até lbpd, onde a cordoalha "
                  "ancora)", fontsize=10)
    ax1.legend(loc="upper left")
    cz = res.cortante
    ax2.plot(cz["x"], cz["VRd1"], color=estilo.AZUL, lw=1.4,
             label="VRd1 = Vc + Vp")
    ax2.plot(cz["x"], cz["VRd2"], color=estilo.CINZA_MEDIO, lw=1.0, ls="--",
             label="VRd2")
    ax2.plot(cz["x"], cz["VSd"], color=estilo.LARANJA, lw=1.6, label="VSd")
    ax2.set_ylabel("kN")
    ax2.set_xlabel("x desde o apoio (m)")
    ax2.set_title("Cortante (a partir de 0,5 h do apoio)")
    ax2.legend(loc="upper right", ncol=3)
    ax2.set_ylim(0, max(cz["VRd1"] + cz["VSd"]) * 1.25)
    fig.tight_layout()
    return fig


def figura_elevacao(res: ResultadoAlveolar) -> Figure:
    """Elevação do painel com a transferência e a deformada esquemática."""
    l = res.laje
    L = l.vao
    h = res.simples.h
    hc = l.capa / 100.0
    fig = Figure(figsize=(8.6, 3.6))
    ax = fig.add_subplot(111)
    ax.add_patch(Rectangle((0, 0), L, h, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.9))
    if hc > 0:
        ax.add_patch(Rectangle((0, h), L, hc, fc="#d9d3c5",
                               ec=estilo.CINZA, lw=0.9))
    yc = l.d_linha / 100.0
    lbpt, lbpd, lp = res.comp["lbpt"], res.comp["lbpd"], res.comp["lp"]
    for x0, x1 in ((0.0, L), ):
        ax.plot([x0, x1], [yc, yc], color=COR_ATIVA, lw=2.2)
    for xe, sinal in ((0.0, 1), (L, -1)):
        for comp, rot, y, cor in ((lbpt, "lbpt", -0.085, estilo.VERDE),
                                  (lp, "lp", -0.14, estilo.LARANJA),
                                  (lbpd, "lbpd", -0.195, estilo.AZUL)):
            xa, xb = xe, xe + sinal * comp
            ax.annotate("", (xa, y), (xb, y),
                        arrowprops=dict(arrowstyle="<->", lw=0.9, color=cor))
            ax.text((xa + xb) / 2.0, y - 0.012, f"{rot} = {comp:.2f} m",
                    ha="center", va="top", fontsize=7.5, color=cor)
    for x in (0.0, L):
        ax.add_patch(Rectangle((x - 0.05, -0.07), 0.1, 0.07, fc="#bdbdbd",
                               ec=estilo.CINZA, hatch="///", lw=0.7))
    if l.encapar > 0:
        for xe, sinal in ((0.0, 1), (L, -1)):
            ax.plot([xe, xe + sinal * l.encapar_comp], [yc + 0.02] * 2,
                    color=estilo.AMARELO, lw=2.4)
        ax.text(l.encapar_comp / 2.0, yc + 0.05,
                f"{l.encapar} encapada(s)", fontsize=7.5,
                color=estilo.AMARELO, ha="center")
    ax.annotate("", (L / 2.0, -0.32), (0.0, -0.32),
                arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(L / 4.0, -0.35, f"L/2 = {L / 2:.2f} m", ha="center", va="top",
            fontsize=8)
    ax.set_xlim(-0.4, L + 0.4)
    ax.set_ylim(-0.55, h + hc + 0.12)
    ax.set_aspect("auto")
    ax.axis("off")
    ax.set_title("Elevação — transferência e ancoragem (alturas fora de "
                 "escala)", fontsize=10)
    fig.tight_layout()
    return fig
