# -*- coding: utf-8 -*-
"""
graficos_nervurada.py
Figuras da laje nervurada bidirecional: planta com as nervuras, os momentos
da grelha e a deformada; seção da nervura com as armaduras; diagramas ao
longo da nervura central.

Cores: a convenção do 3D e da treliçada -- armadura superior em vermelho,
inferior em azul.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle

from ..core.nervurada import ResultadoNervuradaBi
from . import estilo

estilo.aplicar_estilo()

COR_SUP = estilo.VERMELHO
COR_INF = estilo.AZUL_MEDIO


def figura_planta(res: ResultadoNervuradaBi) -> Figure:
    """Planta: nervuras, bordos (apoiado × engastado), momento positivo
    máximo de cada nervura (ELU, grelha) e a flecha em serviço."""
    l = res.laje
    sol = res.grelha
    fig = Figure(figsize=(8.8, 6.6))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    lx, ly = l.lx, l.ly
    ax.add_patch(Rectangle((0, 0), lx, ly, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.8))
    # deformada de serviço, em cm
    sel = res.grelha_els or sol
    w = sel.w * 100.0
    xs = np.linspace(0, lx, l.nx + 1)
    ys = np.linspace(0, ly, l.ny + 1)
    im = ax.imshow(w, extent=(0, lx, 0, ly), origin="lower", cmap="Blues",
                   alpha=0.55, interpolation="bilinear", zorder=1)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.set_label("flecha imediata (cm)", fontsize=8)
    bw = l.bw / 100.0
    for j in range(1, l.ny):
        y = ys[j]
        ax.add_patch(Rectangle((0, y - bw / 2), lx, bw, fc=estilo.AZUL,
                               ec="none", alpha=0.85, zorder=3))
    for i in range(1, l.nx):
        x = xs[i]
        ax.add_patch(Rectangle((x - bw / 2, 0), bw, ly, fc=estilo.AZUL,
                               ec="none", alpha=0.85, zorder=3))
    # bordos
    estilos = {"apoiado": dict(color=estilo.CINZA, lw=2.0, ls="-"),
               "engastado": dict(color=COR_SUP, lw=4.0, ls="-")}
    seg = [((0, 0), (0, ly)), ((lx, 0), (lx, ly)), ((0, 0), (lx, 0)),
           ((0, ly), (lx, ly))]
    for b, ((x0, y0), (x1, y1)) in zip(l.bordos, seg):
        ax.plot([x0, x1], [y0, y1], zorder=5, **estilos[b])
    # momentos máximos por nervura (ELU, grelha)
    for j in range(1, l.ny):
        m = float(sol.mx[j].max())
        ax.text(lx / 2.0, ys[j] + 0.05 * min(lx, ly) / 6.0, f"{m:.1f}",
                ha="center", va="bottom", fontsize=7.5, color="white",
                zorder=6, bbox=dict(boxstyle="round,pad=0.12", fc=estilo.AZUL,
                                    ec="none", alpha=0.9))
    for i in range(1, l.nx):
        m = float(sol.my[i].max())
        ax.text(xs[i] + 0.04 * min(lx, ly) / 6.0, ly * 0.12, f"{m:.1f}",
                ha="left", va="center", fontsize=7.5, color="white",
                rotation=90, zorder=6,
                bbox=dict(boxstyle="round,pad=0.12", fc=estilo.AZUL_MEDIO,
                          ec="none", alpha=0.9))
    ax.set_xlim(-0.3, lx + 0.3)
    ax.set_ylim(-0.3, ly + 0.3)
    ax.set_xlabel(f"x (m) — nervuras // y a cada {l.esp_x:.0f} cm")
    ax.set_ylabel(f"y (m) — nervuras // x a cada {l.esp_y:.0f} cm")
    ax.set_title("Planta — momento máximo por nervura (kN·m, ELU, grelha); "
                 "bordo engastado em vermelho", fontsize=9.5)
    ax.grid(False)
    fig.tight_layout()
    return fig


def figura_secao(res: ResultadoNervuradaBi) -> Figure:
    """Duas nervuras da direção x em corte, com as armaduras."""
    l = res.laje
    rd = res.dirs["x"]
    esp, bw, h, hf = l.esp_y, l.bw, l.h, l.hf
    c = res.geo["c"]
    fig = Figure(figsize=(8.4, 4.6))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    x_l, x_r = -esp * 0.6, esp * 1.6
    ax.add_patch(Rectangle((x_l, h - hf), x_r - x_l, hf, fc=estilo.CONCRETO,
                           ec=estilo.CINZA, lw=0.8))
    for xc in (0.0, esp):
        ax.add_patch(Rectangle((xc - bw / 2, 0), bw, h - hf,
                               fc=estilo.CONCRETO, ec=estilo.CINZA, lw=0.8))
        # estribo
        phi_e = rd.phi_est or l.phi_estribo
        ce = c
        ax.add_patch(Rectangle((xc - bw / 2 + ce, ce), bw - 2 * ce,
                               h - 2 * ce, fc="none",
                               ec=estilo.AMARELO if rd.estribos.startswith(
                                   "estribos") else estilo.CINZA_CLARO,
                               lw=1.0, ls="-" if rd.estribos.startswith(
                                   "estribos") else ":"))
        # camadas inferiores
        for cam in rd.camadas:
            n = cam.n
            largura = min(bw - 2 * ce - 0.4, (n - 1) * (cam.phi / 10.0 + 2.0))
            xs = [xc] if n == 1 else list(np.linspace(
                xc - largura / 2.0, xc + largura / 2.0, n))
            for xb in xs:
                ax.add_patch(Circle((xb, cam.y), cam.phi / 20.0, fc=COR_INF,
                                    ec="k", lw=0.4, zorder=6))
        # negativa do bordo engastado, se houver
        for k, (n_b, phi_b) in rd.n_neg.items():
            yn = h - c - phi_b / 20.0 - 0.0
            largura = min(bw - 1.0, (n_b - 1) * (phi_b / 10.0 + 1.2))
            xs = [xc] if n_b == 1 else list(np.linspace(
                xc - largura / 2.0, xc + largura / 2.0, n_b))
            for xb in xs:
                ax.add_patch(Circle((xb, yn), phi_b / 20.0, fc=COR_SUP,
                                    ec="k", lw=0.4, zorder=6))
            break
    # malha da mesa
    m = res.mesa
    for xb in np.arange(x_l + 3.0, x_r - 2.0, m["s"]):
        ax.add_patch(Circle((xb, h - hf / 2.0), m["phi"] / 20.0,
                            fc=estilo.VERDE, ec="k", lw=0.3, zorder=5))
    y0 = -4.0
    ax.annotate("", (0, y0), (esp, y0), arrowprops=dict(arrowstyle="<->",
                                                         lw=0.8))
    ax.text(esp / 2.0, y0 - 2.0, f"intereixo = {esp:.0f} cm", ha="center",
            fontsize=9)
    xr = x_r + 3.0
    ax.annotate("", (xr, 0), (xr, h), arrowprops=dict(arrowstyle="<->",
                                                       lw=0.8))
    ax.text(xr + 1.2, h / 2.0, f"h = {h:g}", rotation=90, va="center",
            fontsize=9)
    ax.text(x_l + 2.0, h - hf / 2.0 + 1.2, f"mesa {hf:g}", fontsize=8,
            color=estilo.CINZA)
    ax.text(0.0, -1.6, f"bw = {bw:g}", ha="center", fontsize=8,
            color=estilo.CINZA)
    ax.text(esp / 2.0, (h - hf) / 2.0, l.enchimento, ha="center",
            va="center", fontsize=8, color=estilo.CINZA)
    ax.set_xlim(x_l - 3.0, xr + 6.0)
    ax.set_ylim(-8.0, h + 3.0)
    ax.axis("off")
    ax.set_title(f"Seção das nervuras // x — {rd.flexao.armadura}; "
                 f"{rd.estribos} (azul: positiva, vermelho: negativa, "
                 f"verde: malha da mesa)", fontsize=9)
    fig.tight_layout()
    return fig


def figura_diagramas(res: ResultadoNervuradaBi) -> Figure:
    """Momento e cortante ao longo da nervura central (direção x)."""
    l = res.laje
    sol = res.grelha
    fig = Figure(figsize=(8.6, 6.4))
    ax1 = fig.add_subplot(211)
    ax2 = fig.add_subplot(212, sharex=ax1)
    j = max(1, l.ny // 2)
    xs = np.linspace(0, l.lx, l.nx + 1)
    m = sol.mx[j]
    ax1.plot(xs, m, color=estilo.AZUL, lw=1.6, marker="o", ms=3,
             label="grelha")
    rd = res.dirs["x"]
    ax1.axhline(rd.md_placa, color=estilo.LARANJA, ls="--", lw=1.0,
                label=f"placa equivalente ({rd.md_placa:.1f})")
    ax1.axhline(0.0, color=estilo.CINZA, lw=0.7)
    ax1.invert_yaxis()
    ax1.set_ylabel("kN·m por nervura (ELU)")
    ax1.set_title(f"Momento fletor — nervura central // x (linha {j}); "
                  f"positivo para baixo", fontsize=10)
    ax1.legend(loc="lower center", ncol=2)
    v = sol.vx[j]
    xm = 0.5 * (xs[:-1] + xs[1:])
    ax2.step(xs, np.append(v, v[-1]), where="post", color=estilo.VERDE,
             lw=1.4)
    ax2.set_ylabel("|V| por nervura (kN)")
    ax2.set_xlabel("x (m)")
    ax2.set_title("Força cortante por trecho (cargas nos nós)", fontsize=10)
    fig.tight_layout()
    return fig
