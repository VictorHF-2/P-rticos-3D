# -*- coding: utf-8 -*-
"""
graficos_trelicada.py
Figuras da laje treliçada: envoltória de esforços, seção transversal da
nervura e elevação da faixa com as armaduras.

Cores: a convenção da vista 3D (``vista3d.py``) -- armadura **superior em
vermelho, inferior em azul** --, e não a das plantas de armação da laje
maciça (lá, a positiva é vermelha). Aqui o desenho é em corte ou elevação e
o que salta aos olhos é a posição na espessura, como no modelo 3D.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon, Rectangle

from ..core.trelicada import ResultadoTrelicada
from ..core.trelicada_modelo import TRELICAS
from . import estilo

estilo.aplicar_estilo()

COR_SUP = estilo.VERMELHO
COR_INF = estilo.AZUL_MEDIO

#: Espessura da base da vigota no desenho, cm (a faixa de concreto
#: pré-moldado de 3 a 4 cm; só desenho -- o cálculo não a usa).
BASE_VIGOTA = 3.0


def _posicoes_apoios(res: ResultadoTrelicada) -> list[float]:
    lt = res.laje
    x = lt.balanco_esq / 100.0
    pos = [x]
    for v in lt.vaos:
        x += v.L / 100.0
        pos.append(x)
    return pos


def figura_esforcos(res: ResultadoTrelicada) -> Figure:
    """Envoltória de momento fletor e de força cortante, ELU, por nervura."""
    fig = Figure(figsize=(11.0, 7.0))
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212, sharex=ax1)
    env = res.env
    total = res.offsets[-1] + res.elementos[-1].L
    for k, e in enumerate(res.elementos):
        x = res.offsets[k] + env.x[k]
        ordem = np.argsort(x)
        x = x[ordem]
        ax1.fill_between(x, env.m_max[k][ordem], env.m_min[k][ordem],
                         color=estilo.AZUL_CLARO, alpha=0.65, lw=0)
        ax1.plot(x, env.m_max[k][ordem], color=estilo.AZUL, lw=1.1)
        ax1.plot(x, env.m_min[k][ordem], color=estilo.AZUL, lw=1.1)
        ax2.fill_between(x, env.v_max[k][ordem], env.v_min[k][ordem],
                         color=estilo.VERDE_CLARO, alpha=0.6, lw=0)
        ax2.plot(x, env.v_max[k][ordem], color=estilo.VERDE, lw=1.0)
        ax2.plot(x, env.v_min[k][ordem], color=estilo.VERDE, lw=1.0)
    for rv in res.vaos:
        k = rv.indice + (1 if res.laje.balanco_esq > 0 else 0)
        xm = res.offsets[k] + rv.x_md
        ax1.annotate(f"{rv.md:.2f}", (xm, rv.md), textcoords="offset points",
                     xytext=(0, 10), ha="center", fontsize=8,
                     color=estilo.AZUL)
    pos = _posicoes_apoios(res)
    for j, ra in enumerate(res.apoios):
        if ra.md > 1e-9:
            ax1.annotate(f"{-ra.md:.2f}", (pos[j], -ra.md),
                         textcoords="offset points", xytext=(0, -14),
                         ha="center", fontsize=8, color=estilo.AZUL)
    for ax in (ax1, ax2):
        ax.axhline(0.0, color=estilo.CINZA, lw=0.8)
        for x in pos:
            ax.axvline(x, color=estilo.CINZA_MEDIO, lw=0.6, ls=":")
        ax.set_xlim(-0.05 * total, 1.05 * total)
        ax.grid(True, alpha=0.4)
    ax1.invert_yaxis()                 # lado tracionado para baixo
    ax1.set_ylabel("kN·m por nervura")
    ax1.set_title("Envoltória de momento fletor — ELU (positivo para "
                  "baixo, lado tracionado)")
    ax2.set_ylabel("kN por nervura")
    ax2.set_xlabel("m")
    ax2.set_title("Envoltória de força cortante — ELU")
    for x in pos:
        ax1.plot([x], [0.0], marker="^", color=estilo.CINZA, ms=7,
                 clip_on=False)
    fig.tight_layout()
    return fig


def _secao_moldada(res: ResultadoTrelicada) -> Figure:
    """Seção da nervura moldada no local: duas nervuras, a mesa, as barras
    do primeiro vão (em uma ou duas camadas), o estribo e a negativa do
    apoio mais carregado."""
    lt = res.laje
    inter, bw, h = lt.intereixo, lt.bw, lt.h
    he, capa = lt.altura_enchimento, lt.capa
    c = res.geo["c_inf"]
    fig = Figure(figsize=(9.0, 4.8))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    x_l, x_r = -inter * 0.55, inter * 1.55
    ax.add_patch(Rectangle((x_l, he), x_r - x_l, capa, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.8))
    rv = res.vaos[0]
    est = [rc for rc in res.cortantes if rc.usou_estribos]
    for xc in (0.0, inter):
        ax.add_patch(Rectangle((xc - bw / 2.0, 0.0), bw, he,
                               fc=estilo.CONCRETO, ec=estilo.CINZA, lw=0.8))
        ax.add_patch(Rectangle(
            (xc - bw / 2.0 + c, c), bw - 2.0 * c, h - 2.0 * c, fc="none",
            ec=estilo.AMARELO if est else estilo.CINZA_CLARO, lw=1.0,
            ls="-" if est else ":"))
        for cam in rv.camadas:
            n = cam.n
            largura = min(bw - 2.0 * c - 0.4,
                          (n - 1) * (cam.phi / 10.0 + 2.0))
            xs = [xc] if n == 1 else list(np.linspace(
                xc - largura / 2.0, xc + largura / 2.0, n))
            for xb in xs:
                ax.add_patch(Circle((xb, cam.y), cam.phi / 20.0, fc=COR_INF,
                                    ec="k", lw=0.4, zorder=6))
        ra = max(res.apoios, key=lambda a: a.md)
        if ra.md > 1e-9 and ra.n_negativa > 0:
            n, phi = ra.n_negativa, ra.phi_negativa
            yn = h - c - phi / 20.0
            largura = min(bw - 1.0, (n - 1) * (phi / 10.0 + 1.2))
            xs = [xc] if n == 1 else list(np.linspace(
                xc - largura / 2.0, xc + largura / 2.0, n))
            for xb in xs:
                ax.add_patch(Circle((xb, yn), phi / 20.0, fc=COR_SUP,
                                    ec="k", lw=0.4, zorder=6))
    # malha da mesa
    s = res.distribuicao.get("s", 15.0)
    phi_d = res.distribuicao.get("phi", 6.3)
    for xb in np.arange(x_l + 3.0, x_r - 2.0, s):
        ax.add_patch(Circle((xb, he + capa / 2.0), phi_d / 20.0,
                            fc=estilo.VERDE, ec="k", lw=0.3, zorder=5))
    y0 = -4.0
    ax.annotate("", (-bw / 2.0, y0), (inter - bw / 2.0, y0),
                arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(inter / 2.0 - bw / 2.0, y0 - 1.6, f"intereixo = {inter:g} cm",
            ha="center", fontsize=9)
    xr = x_r + 3.0
    ax.annotate("", (xr, 0.0), (xr, h), arrowprops=dict(arrowstyle="<->",
                                                          lw=0.8))
    ax.text(xr + 1.2, h / 2.0, f"h = {h:g}", rotation=90, va="center",
            fontsize=9)
    ax.text(x_l + 2.0, he + capa / 2.0 + 1.0, f"mesa {capa:g}", fontsize=8,
            color=estilo.CINZA)
    ax.text(0.0, -1.8, f"bw = {bw:g}", ha="center", fontsize=8,
            color=estilo.CINZA)
    ax.text(inter / 2.0, he / 2.0, lt.enchimento, ha="center", va="center",
            fontsize=8, color=estilo.CINZA)
    ax.set_xlim(x_l - 3.0, xr + 6.0)
    ax.set_ylim(-8.0, h + 3.0)
    ax.axis("off")
    ax.set_title("Seção da nervura -- azul: positiva; vermelho: negativa; "
                 "amarelo: estribo; verde: malha da mesa", fontsize=10)
    fig.tight_layout()
    return fig


def figura_secao(res: ResultadoTrelicada) -> Figure:
    """Seção transversal: duas nervuras com o bloco de enchimento entre
    elas, a treliça, a adicional (do primeiro vão) e a negativa (do maior
    momento negativo)."""
    lt = res.laje
    if lt.moldada:
        return _secao_moldada(res)
    inter, bw, h = lt.intereixo, lt.bw, lt.h
    he, capa = lt.altura_enchimento, lt.capa
    fig = Figure(figsize=(9.0, 4.8))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    x_l, x_r = -inter * 0.55, inter * 1.55
    # capa
    ax.add_patch(Rectangle((x_l, he), x_r - x_l, capa, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.8))
    # enchimento: o bloco inteiro entre as nervuras e as pontas cortadas
    le = lt.largura_bloco
    for xa, xb in ((x_l, -bw / 2.0), (bw / 2.0, inter - bw / 2.0),
                   (inter + bw / 2.0, x_r)):
        ax.add_patch(Rectangle((xa, 0.0), xb - xa, he, fc="#f1efe9",
                               ec=estilo.CINZA_MEDIO, lw=0.7, hatch="////"))
    for xc in (0.0, inter):
        ax.add_patch(Rectangle((xc - bw / 2.0, 0.0), bw, he,
                               fc=estilo.CONCRETO, ec=estilo.CINZA, lw=0.8))
        ax.add_patch(Rectangle((xc - lt.base / 2.0, 0.0), lt.base,
                               BASE_VIGOTA, fc="#d2cdbf", ec=estilo.CINZA,
                               lw=0.8))
        # treliça (vista de frente: dois fios inferiores e o superior)
        h_tr, phi_sup, phi_diag, phi_inf, _ = TRELICAS[lt.trelica]
        c_inf = res.geo["c_inf"]
        xi = (bw - 2.0 * c_inf - phi_inf / 10.0) / 2.0 + 0.0
        xi = min(xi, bw / 2.0 - 0.4)
        yi = c_inf + phi_inf / 20.0
        ys = h_tr / 10.0
        for sinal in (-1, 1):
            ax.plot([xc + sinal * xi, xc], [yi, ys], color=estilo.CINZA,
                    lw=0.9)
            ax.add_patch(Circle((xc + sinal * xi, yi), phi_inf / 20.0,
                                fc=COR_INF, ec="k", lw=0.4, zorder=5))
        ax.add_patch(Circle((xc, ys), phi_sup / 20.0, fc=COR_SUP, ec="k",
                            lw=0.4, zorder=5))
        # adicional
        rv = res.vaos[0]
        if rv.n_adicional > 0:
            n = rv.n_adicional
            largura = min(bw - 1.0, (n - 1) * (rv.phi_adicional / 10.0 + 1.2))
            xs = [xc] if n == 1 else list(np.linspace(xc - largura / 2.0,
                                                      xc + largura / 2.0, n))
            for xb in xs:
                ax.add_patch(Circle((xb, c_inf + rv.phi_adicional / 20.0),
                                    rv.phi_adicional / 20.0, fc=COR_INF,
                                    ec="k", lw=0.4, zorder=6))
        # negativa do apoio mais carregado
        ra = max(res.apoios, key=lambda a: a.md)
        if ra.md > 1e-9 and ra.n_negativa > 0:
            n = ra.n_negativa
            phi = ra.phi_negativa
            yn = h - 1.5 - phi / 20.0
            largura = min(bw - 1.0, (n - 1) * (phi / 10.0 + 1.2))
            xs = [xc] if n == 1 else list(np.linspace(xc - largura / 2.0,
                                                      xc + largura / 2.0, n))
            for xb in xs:
                ax.add_patch(Circle((xb, yn), phi / 20.0, fc=COR_SUP,
                                    ec="k", lw=0.4, zorder=6))
    # cotas
    y0 = -4.0
    ax.annotate("", (-bw / 2.0, y0), (inter - bw / 2.0, y0),
                arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(inter / 2.0 - bw / 2.0, y0 - 1.6, f"intereixo = {inter:g} cm",
            ha="center", fontsize=9)
    xr = x_r + 3.0
    ax.annotate("", (xr, 0.0), (xr, h), arrowprops=dict(arrowstyle="<->",
                                                          lw=0.8))
    ax.text(xr + 1.2, h / 2.0, f"h = {h:g}", rotation=90, va="center",
            fontsize=9)
    ax.text(x_r - 1.0, he + capa / 2.0, f"capa {capa:g}", ha="right",
            va="center", fontsize=8)
    ax.text(0.0, -1.8 - 0.0, f"bw = {bw:g}", ha="center", fontsize=8,
            color=estilo.CINZA)
    ax.text(inter / 2.0, he / 2.0, f"{lt.enchimento}\n{le:g} × {he:g}",
            ha="center", va="center", fontsize=8, color=estilo.CINZA)
    ax.set_xlim(x_l - 3.0, xr + 6.0)
    ax.set_ylim(-8.0, h + 3.0)
    ax.axis("off")
    ax.set_title(f"Seção transversal — {lt.trelica}, {lt.enchimento} "
                 f"(vermelho: armadura superior; azul: inferior)", fontsize=10)
    fig.tight_layout()
    return fig


def figura_elevacao(res: ResultadoTrelicada) -> Figure:
    """Elevação da faixa: apoios, vigotas, adicionais e negativas."""
    lt = res.laje
    fig = Figure(figsize=(11.0, 4.2))
    ax = fig.add_subplot(111)
    pos = [x * 100.0 for x in _posicoes_apoios(res)]
    total = lt.balanco_esq + sum(v.L for v in lt.vaos) + lt.balanco_dir
    h = lt.h
    ax.add_patch(Rectangle((0.0, 0.0), total, h, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.8, alpha=0.8))
    alt_apoio = 28.0
    for j, ra in enumerate(res.apoios):
        ax.add_patch(Rectangle((pos[j] - ra.t / 2.0, -alt_apoio), ra.t,
                               alt_apoio, fc="#bdbdbd", ec=estilo.CINZA,
                               lw=0.8, hatch="///"))
        if ra.macico_adotado > 0.0:
            ax.add_patch(Rectangle((pos[j] - ra.macico_adotado, 0.0),
                                   2.0 * ra.macico_adotado, h,
                                   fc="#9a9486", ec="none", alpha=0.55))
    # vigotas e adicionais (embaixo)
    for i, v in enumerate(lt.vaos):
        x0, x1 = pos[i], pos[i + 1]
        rv = res.vaos[i]
        xa = x0 + lt.apoios[i].t / 2.0
        xb = x1 - lt.apoios[i + 1].t / 2.0
        if i == 0:
            xa = 0.0 if lt.balanco_esq > 0.0 else xa
        if i == len(lt.vaos) - 1 and lt.balanco_dir > 0.0:
            xb = total
        ax.plot([xa, xb], [2.0, 2.0], color=COR_INF, lw=2.4)
        ax.text((x0 + x1) / 2.0, -alt_apoio - 6.0,
                f"vão {i + 1}: L = {v.L:g} cm\n{rv.flexao.armadura}",
                ha="center", va="top", fontsize=8, color=COR_INF)
    # negativas (em cima)
    for j, ra in enumerate(res.apoios):
        if ra.md <= 1e-9 or ra.comprimento <= 0.0:
            continue
        x0, x1 = pos[j] - ra.extensao_esq, pos[j] + ra.extensao_dir
        ax.plot([x0, x1], [h - 2.0, h - 2.0], color=COR_SUP, lw=2.4)
        ax.text((x0 + x1) / 2.0, h + 4.0,
                f"{ra.n_negativa} Ø{ra.phi_negativa:g} — "
                f"{ra.comprimento:.0f} cm", ha="center", fontsize=8,
                color=COR_SUP)
    ax.set_xlim(-30.0, total + 30.0)
    ax.set_ylim(-alt_apoio - 30.0, h + 20.0)
    ax.set_aspect("auto")
    ax.set_xlabel("cm (verticais fora de escala)")
    ax.set_yticks([])
    ax.set_title("Elevação da faixa — vigotas (azul), negativas (vermelho) "
                 "e trechos maciços (cinza escuro)")
    fig.tight_layout()
    return fig
