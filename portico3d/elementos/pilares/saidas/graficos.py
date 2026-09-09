# -*- coding: utf-8 -*-
"""
graficos.py
Figuras do pilar: seção armada, diagramas de interação, envoltória de momentos
resistentes, diagrama de excentricidades e esforços ao longo do lance.

Cada função devolve uma ``Figure`` do matplotlib, sem depender do PySide6.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon

from ..core import seccional as sc
from ..core.dimensionar import ResultadoPilar
from . import estilo

TAMANHO = (11.0, 7.5)
TAMANHO_SECAO = (7.5, 7.5)


def _preparar(tamanho=TAMANHO) -> Figure:
    estilo.aplicar_estilo()
    fig = Figure(figsize=tamanho)
    fig.set_layout_engine("constrained")
    return fig


def _cobrimento(res: ResultadoPilar) -> float:
    """Cobrimento que de fato entrou no arranjo, cm.

    Antes de haver arranjo, o do ambiente -- que só conhece a Tabela 7.2 e o
    agregado. Depois, o do arranjo, que já respeita a bitola das barras
    (item 7.4.7.5) e pode ser maior.
    """
    if res.arranjo is not None and res.arranjo.cobrimento > 0:
        return res.arranjo.cobrimento
    return res.pilar.ambiente.cobrimento_adotado


def _contorno(ax, res: ResultadoPilar, cor=estilo.CONCRETO) -> None:
    """Desenha o concreto da seção, com o furo em branco quando existe."""
    contornos = res.pilar.secao.contornos()
    ax.add_patch(Polygon(contornos[0], closed=True, facecolor=cor,
                         edgecolor=estilo.CINZA, linewidth=1.2, zorder=1))
    for furo in contornos[1:]:
        ax.add_patch(Polygon(furo, closed=True, facecolor="white",
                             edgecolor=estilo.CINZA, linewidth=1.0, zorder=2))


# ---------------------------------------------------------------------------
# Seção armada
# ---------------------------------------------------------------------------

def figura_secao(res: ResultadoPilar) -> Figure:
    """Seção transversal com as barras, o estribo e as cotas."""
    fig = _preparar(TAMANHO_SECAO)
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.grid(False)
    secao = res.pilar.secao
    _contorno(ax, res)

    arr = res.arranjo
    est = res.estribos
    if est is not None:
        from ..core import geometria as geo
        recuo = _cobrimento(res) + est.phi / 20.0
        if secao.tipo in ("circular", "circular vazada"):
            ax.add_patch(Circle((0, 0), (secao.diametro - 2 * recuo) / 2.0,
                                fill=False, edgecolor=estilo.AZUL_MEDIO,
                                linewidth=1.6, zorder=3))
        else:
            linha = geo.deslocar_para_dentro(secao.contornos()[0], recuo)
            ax.add_patch(Polygon(linha, closed=True, fill=False,
                                 edgecolor=estilo.AZUL_MEDIO, linewidth=1.6,
                                 zorder=3))

    if arr is not None:
        r = arr.phi / 20.0
        for b in arr.barras:
            ax.add_patch(Circle((b.x, b.y), r, facecolor=estilo.VERMELHO,
                                edgecolor="none", zorder=4))
        _grampos(ax, res)

    x0, x1, y0, y1 = _limites(secao)
    folga = 0.18 * max(x1 - x0, y1 - y0)
    ax.set_xlim(x0 - folga, x1 + folga)
    ax.set_ylim(y0 - folga * 1.4, y1 + folga)
    _cotas(ax, secao, folga)

    titulo = f"{res.pilar.nome} — {secao.descricao()}"
    ax.set_title(titulo)
    legenda = []
    if arr is not None:
        legenda.append(f"{arr.n_barras} ø{arr.phi:g} mm  "
                       f"(As = {arr.As:.2f} cm²,  ρ = {res.taxa * 100:.2f} %)")
    if est is not None:
        legenda.append(f"Estribo {est.descricao()}")
    legenda.append(f"c = {_cobrimento(res):g} cm  "
                   f"(CAA {res.pilar.ambiente.caa})")
    ax.set_xlabel("\n".join(legenda))
    ax.set_xticks([])
    ax.set_yticks([])
    for lado in ("top", "right", "bottom", "left"):
        ax.spines[lado].set_visible(False)
    return fig


def _grampos(ax, res: ResultadoPilar) -> None:
    """Traça os grampos suplementares onde eles de fato ficam."""
    est = res.estribos
    arr = res.arranjo
    if est is None or arr is None or not est.n_suplementares:
        return
    secao = res.pilar.secao
    if secao.tipo != "retangular":
        # Nas seções compostas o grampo suplementar é contado, não posicionado:
        # ele tanto pode ser um tirante reto atravessando a alma quanto um
        # estribo interno fechado, e a escolha é do detalhamento. Desenhar um
        # palpite seria pior que não desenhar.
        return
    lx = secao.hx / 2.0 - arr.recuo
    ly = secao.hy / 2.0 - arr.recuo
    interiores_x = sorted({round(b.x, 4) for b in arr.barras
                           if abs(abs(b.y) - ly) < 1e-3
                           and abs(abs(b.x) - lx) > 1e-3})
    interiores_y = sorted({round(b.y, 4) for b in arr.barras
                           if abs(abs(b.x) - lx) < 1e-3
                           and abs(abs(b.y) - ly) > 1e-3})
    for x in interiores_x[:est.suplementares_x]:
        ax.plot([x, x], [-ly, ly], color=estilo.VERDE, linewidth=1.3,
                linestyle=(0, (6, 2)), zorder=3)
    for y in interiores_y[:est.suplementares_y]:
        ax.plot([-lx, lx], [y, y], color=estilo.VERDE, linewidth=1.3,
                linestyle=(0, (6, 2)), zorder=3)


def _limites(secao) -> tuple[float, float, float, float]:
    return (-secao.hx / 2.0, secao.hx / 2.0, -secao.hy / 2.0, secao.hy / 2.0)


def _cotas(ax, secao, folga: float) -> None:
    """Cota horizontal embaixo e vertical à esquerda."""
    x0, x1, y0, y1 = _limites(secao)
    yc = y0 - folga * 0.65
    ax.annotate("", (x0, yc), (x1, yc),
                arrowprops=dict(arrowstyle="<->", color=estilo.CINZA, lw=0.9))
    ax.text(0, yc - folga * 0.18, f"{secao.hx:g} cm", ha="center", va="top",
            fontsize=9, color=estilo.CINZA)
    xc = x0 - folga * 0.65
    ax.annotate("", (xc, y0), (xc, y1),
                arrowprops=dict(arrowstyle="<->", color=estilo.CINZA, lw=0.9))
    ax.text(xc - folga * 0.12, 0, f"{secao.hy:g} cm", ha="right", va="center",
            rotation=90, fontsize=9, color=estilo.CINZA)


# ---------------------------------------------------------------------------
# Diagrama de interação N-M
# ---------------------------------------------------------------------------

def figura_interacao(res: ResultadoPilar) -> Figure:
    """Diagramas ``N`` x ``M`` nas duas direções, com as situações marcadas.

    A curva é a fronteira do ELU da seção **com a armadura escolhida**: cada
    ponto é um plano de deformações limite. O ponto solicitante dentro dela
    passa; fora, não. É a leitura que o diagrama de interação sempre teve, e
    aqui ela vale porque a curva sai do equilíbrio, não de ábaco.
    """
    fig = _preparar()
    if res.secao_discreta is None:
        return fig
    Nd = res.pilar.Nd
    eixos = fig.subplots(1, 2, sharey=True)
    for ax, direcao in zip(eixos, ("x", "y")):
        pontos = sc.diagrama_interacao(res.secao_discreta, direcao, 60)
        N = np.array([p[0] for p in pontos])
        M = np.array([abs(p[1]) / 100.0 for p in pontos])
        ax.plot(M, N, color=estilo.AZUL, linewidth=1.8,
                label="Envoltória resistente")
        ax.fill_betweenx(N, 0, M, color=estilo.AZUL_CLARO, alpha=0.35)
        ax.axhline(Nd, color=estilo.CINZA_MEDIO, linewidth=0.9,
                   linestyle="--")
        ax.text(M.max() * 0.98, Nd, f"  Nd = {Nd:.0f} kN", ha="right",
                va="bottom", fontsize=8, color=estilo.CINZA)
        for s in res.situacoes:
            Msd = abs(s.Mx if direcao == "x" else s.My) / 100.0
            ax.plot([Msd], [Nd], marker="o", markersize=6,
                    color=estilo.LARANJA, zorder=5)
            ax.annotate(s.nome.replace("Situação ", "S"), (Msd, Nd),
                        textcoords="offset points", xytext=(6, 8),
                        fontsize=8, color=estilo.LARANJA)
        ax.set_xlabel(f"M{direcao}{direcao} (kN·m)")
        ax.set_title(f"direção {direcao}  "
                     f"(h = {res.pilar.secao.altura(direcao):g} cm)",
                     fontsize=9)
        ax.set_xlim(left=0)
    eixos[0].set_ylabel("N (kN, compressão positiva)")
    eixos[0].legend(loc="upper right")
    fig.suptitle(f"{res.pilar.nome} — diagramas de interação à flexão "
                 f"composta normal", fontweight="bold")
    return fig


# ---------------------------------------------------------------------------
# Envoltória de momentos resistentes
# ---------------------------------------------------------------------------

def figura_envoltoria(res: ResultadoPilar) -> Figure:
    """Envoltória ``MRd,x`` x ``MRd,y`` para ``Nd``, e as situações.

    Duas curvas se sobrepõem aqui, e a diferença entre elas é o assunto da
    figura:

    * a **envoltória de equilíbrio**, obtida girando a linha neutra e achando
      o momento resistente em cada direção -- é a fronteira verdadeira;
    * a **elipse do item 17.2.5**, ``(Mx/MRd,xx)^a + (My/MRd,yy)^a = 1``, que
      é a aproximação de projeto.

    Onde a elipse fica **fora** da envoltória, a expressão aproximada está
    contra a segurança, e é a envoltória que vale.
    """
    fig = _preparar(TAMANHO_SECAO)
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    if res.secao_discreta is None:
        return fig
    Nd = res.pilar.Nd
    pontos = sc.envoltoria_momentos(res.secao_discreta, Nd, 72)
    if pontos:
        px = [p[0] / 100.0 for p in pontos] + [pontos[0][0] / 100.0]
        py = [p[1] / 100.0 for p in pontos] + [pontos[0][1] / 100.0]
        ax.plot(px, py, color=estilo.AZUL, linewidth=1.8,
                label="Envoltória de equilíbrio")
        ax.fill(px, py, color=estilo.AZUL_CLARO, alpha=0.30)

    v = res.verificacao_critica
    if v is not None and v.MRd_xx > 0 and v.MRd_yy > 0:
        a = res.pilar.alfa_interacao
        t = np.linspace(0.0, math.pi / 2.0, 120)
        rx = (v.MRd_xx / 100.0) * np.cos(t) ** (2.0 / a)
        ry = (v.MRd_yy / 100.0) * np.sin(t) ** (2.0 / a)
        ex = np.concatenate([rx, -rx[::-1], -rx, rx[::-1]])
        ey = np.concatenate([ry, ry[::-1], -ry, -ry[::-1]])
        ax.plot(ex, ey, color=estilo.LARANJA, linewidth=1.3,
                linestyle=(0, (5, 2)),
                label=f"Expressão do item 17.2.5 (α = {a:g})")

    for s in res.situacoes:
        ax.plot([s.Mx / 100.0], [s.My / 100.0], marker="o", markersize=7,
                color=estilo.VERMELHO, zorder=6)
        ax.annotate(s.nome.replace("Situação ", "S"),
                    (s.Mx / 100.0, s.My / 100.0), textcoords="offset points",
                    xytext=(7, 7), fontsize=9, color=estilo.VERMELHO)

    ax.axhline(0, color=estilo.CINZA_MEDIO, linewidth=0.7)
    ax.axvline(0, color=estilo.CINZA_MEDIO, linewidth=0.7)
    ax.set_xlabel("Mx (kN·m)")
    ax.set_ylabel("My (kN·m)")
    ax.set_title(f"{res.pilar.nome} — envoltória de momentos resistentes "
                 f"para Nd = {Nd:.0f} kN")
    ax.legend(loc="upper right", fontsize=8)
    return fig


# ---------------------------------------------------------------------------
# Momento-curvatura
# ---------------------------------------------------------------------------

def figura_momento_curvatura(res: ResultadoPilar) -> Figure:
    """Diagrama momento-curvatura (M-N-θ) da situação governante.

    Fixados a normal e a direção do momento da situação de maior
    excentricidade, varre-se a curvatura da seção do zero até o ELU e
    observa-se como o momento resistente cresce -- é o item 5.6 de
    CADAMURO JÚNIOR (1997): convexo, contínuo e partindo perto da origem numa
    seção duplamente simétrica; numa seção assimétrica o formato pode ser
    menos regular, e a curva aqui só segue o ramo que contém a origem.

    Não é uma verificação normativa -- a norma não pede este diagrama --, é
    uma ferramenta de diagnóstico: mostra o quanto de reserva de curvatura a
    seção tem além do que a situação de cálculo exige, e onde o ELU (a marca
    vermelha) realmente está.
    """
    fig = _preparar(TAMANHO_SECAO)
    ax = fig.add_subplot(111)
    if res.secao_discreta is None or res.governante is None:
        return fig
    Nd = res.pilar.Nd
    alfa = math.atan2(res.governante.My, res.governante.Mx)
    pontos = sc.diagrama_m_n_theta(res.secao_discreta, Nd, alfa, pontos=24)
    if not pontos:
        ax.text(0.5, 0.5, "Nenhum estado de equilíbrio nessa direção\n"
                          "para esta força normal (item 5.5).",
               ha="center", va="center", transform=ax.transAxes)
        return fig

    k = [p.k for p in pontos]
    M = [p.M / 100.0 for p in pontos]
    ax.plot([0.0] + k, [0.0] + M, color=estilo.AZUL, linewidth=1.8)
    ax.fill_between([0.0] + k, 0.0, [0.0] + M, color=estilo.AZUL_CLARO,
                    alpha=0.30)
    ax.plot([k[-1]], [M[-1]], marker="o", markersize=8,
            color=estilo.VERMELHO, zorder=5)
    ax.annotate(f"ELU — domínio {pontos[-1].dominio}\n"
                f"M = {M[-1]:.1f} kN·m", (k[-1], M[-1]),
                textcoords="offset points", xytext=(-10, 8), ha="right",
                fontsize=8, color=estilo.VERMELHO)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("curvatura k (‰/cm)")
    ax.set_ylabel("|M| (kN·m)")
    ax.set_title(f"{res.pilar.nome} — momento-curvatura para "
                 f"Nd = {Nd:.0f} kN\ndireção do momento: "
                 f"{math.degrees(alfa):.0f}° ({res.governante.nome})")
    return fig


# ---------------------------------------------------------------------------
# Excentricidades e situações de cálculo
# ---------------------------------------------------------------------------

def figura_excentricidades(res: ResultadoPilar) -> Figure:
    """As quatro situações de cálculo no plano ``(ex, ey)``.

    A figura mostra por que as situações existem: o momento mínimo do item
    11.3.3.4.3 é verificado **numa direção de cada vez**, e a segunda ordem
    entra só na seção do meio. Cada ponto é um par de excentricidades a
    verificar, e o retângulo tracejado é o piso das excentricidades mínimas.
    """
    fig = _preparar(TAMANHO_SECAO)
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ex_min = res.esbeltez["x"].e1_min if res.esbeltez else 0.0
    ey_min = res.esbeltez["y"].e1_min if res.esbeltez else 0.0
    ax.add_patch(Polygon([(-ex_min, -ey_min), (ex_min, -ey_min),
                          (ex_min, ey_min), (-ex_min, ey_min)], closed=True,
                         fill=False, edgecolor=estilo.CINZA_MEDIO,
                         linewidth=1.0, linestyle=(0, (4, 3)),
                         label="excentricidades mínimas (11.3.3.4.3)"))
    cores = {"extremo": estilo.AZUL, "meio": estilo.LARANJA}
    vistos: set[str] = set()
    for s in res.situacoes:
        rotulo = ("extremidades A e B" if s.posicao == "extremo"
                  else "seção intermediária")
        ax.plot([s.ex], [s.ey], marker="o", markersize=8,
                color=cores[s.posicao], zorder=5,
                label=rotulo if rotulo not in vistos else None)
        vistos.add(rotulo)
        ax.annotate(f"{s.nome}\n({s.ex:.2f}; {s.ey:.2f})", (s.ex, s.ey),
                    textcoords="offset points", xytext=(9, 6), fontsize=8)
    g = res.governante
    if g is not None:
        ax.plot([0, g.ex], [0, g.ey], color=estilo.VERMELHO, linewidth=1.4)
        ax.annotate(f"|e| = {g.modulo:.2f} cm", (g.ex / 2, g.ey / 2),
                    textcoords="offset points", xytext=(6, -14), fontsize=8,
                    color=estilo.VERMELHO)
    ax.axhline(0, color=estilo.CINZA_MEDIO, linewidth=0.7)
    ax.axvline(0, color=estilo.CINZA_MEDIO, linewidth=0.7)
    ax.set_xlabel("ex (cm)")
    ax.set_ylabel("ey (cm)")
    ax.set_title(f"{res.pilar.nome} — situações de cálculo")
    ax.legend(loc="best", fontsize=8)
    return fig


# ---------------------------------------------------------------------------
# Esforços ao longo do lance
# ---------------------------------------------------------------------------

def figura_esforcos(res: ResultadoPilar) -> Figure:
    """Momentos de primeira ordem, mínimo e total ao longo do lance.

    Os diagramas estão em **módulo**, e de propósito. O de primeira ordem é
    linear entre topo e base e troca de sinal quando a curvatura é reversa; o
    momento mínimo do item 11.3.3.4.3 é um piso em módulo, e a segunda ordem
    do pilar-padrão é uma senoide de máximo no meio. Plotados com sinal, o
    piso mínimo produziria um salto artificial exatamente onde o diagrama de
    primeira ordem cruza o zero -- salto que não existe na peça e que só
    atrapalha a leitura. Em módulo, a envoltória de projeto é o que ela é: o
    maior valor que a seção precisa resistir em cada cota.
    """
    fig = _preparar()
    eixos = fig.subplots(1, 2, sharey=True)
    L = res.pilar.lance.altura
    z = np.linspace(0.0, L, 201)
    f = res.pilar.fator_esforcos
    for ax, direcao in zip(eixos, ("x", "y")):
        e = res.esbeltez[direcao]
        so = res.segunda_ordem[direcao]
        Mt = f * res.pilar.esforcos.topo(direcao)
        Mb = f * res.pilar.momento_base(direcao)
        M1 = Mb + (Mt - Mb) * z / L if L > 0 else np.zeros_like(z)
        M2 = (abs(res.pilar.Nd) * so.e2 * np.sin(math.pi * z / L)
              if so.aplicavel else np.zeros_like(z))
        # No meio, o que atua é alfa_b vezes o momento de 1ª ordem mais a
        # 2ª ordem; nos extremos, o próprio momento de 1ª ordem. A senoide
        # da 2ª ordem já leva a distribuição de um para o outro.
        envoltoria = np.maximum(
            np.maximum(np.abs(M1), e.alfa_b * abs(e.M1d_A)) + M2,
            e.M1d_min)

        ax.plot(np.abs(M1) / 100.0, z, color=estilo.AZUL_MEDIO, linewidth=1.4,
                label="|M₁d| de primeira ordem")
        ax.plot(envoltoria / 100.0, z, color=estilo.AZUL, linewidth=2.2,
                label="envoltória de projeto")
        ax.fill_betweenx(z, np.abs(M1) / 100.0, envoltoria / 100.0,
                         color=estilo.AZUL_CLARO, alpha=0.30)
        ax.axvline(e.M1d_min / 100.0, color=estilo.LARANJA, linewidth=1.1,
                   linestyle=(0, (4, 3)))
        ax.text(e.M1d_min / 100.0, L * 0.03,
                f"  M₁d,mín = {e.M1d_min / 100.0:.1f} kN·m", fontsize=8,
                color=estilo.LARANJA)
        ax.set_xlabel(f"|M{direcao}| (kN·m)")
        ax.set_xlim(left=0)
        ax.set_title(f"direção {direcao}:  λ = {e.lam:.1f}   "
                     f"λ₁ = {e.lam_1:.1f}   α_b = {e.alfa_b:.2f}\n"
                     f"{e.veredito}"
                     + (f" — e₂ = {so.e2:.2f} cm" if so.aplicavel else ""),
                     fontsize=9)
    eixos[0].set_ylabel("cota no lance (cm)")
    eixos[0].legend(loc="lower right", fontsize=8)
    fig.suptitle(f"{res.pilar.nome} — momentos ao longo do lance",
                 fontweight="bold")
    return fig


# ---------------------------------------------------------------------------
# Elevação esquemática
# ---------------------------------------------------------------------------

def figura_elevacao(res: ResultadoPilar) -> Figure:
    """Elevação do lance com os estribos e o comprimento de espera."""
    fig = _preparar((6.0, 9.0))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ax.grid(False)
    secao = res.pilar.secao
    L = res.pilar.lance.altura
    b = secao.hx
    ax.add_patch(Polygon([(0, 0), (b, 0), (b, L), (0, L)], closed=True,
                         facecolor=estilo.CONCRETO, edgecolor=estilo.CINZA,
                         linewidth=1.2))

    arr, est, ancor = res.arranjo, res.estribos, res.ancoragem
    if arr is not None:
        c = _cobrimento(res)
        for x in (c + arr.phi / 20.0, b - c - arr.phi / 20.0):
            ax.plot([x, x], [0, L], color=estilo.VERMELHO, linewidth=2.0,
                    zorder=3)
            if ancor is not None:
                ax.plot([x, x], [L, L + ancor.l0c], color=estilo.VERMELHO,
                        linewidth=2.0, linestyle=(0, (5, 3)), zorder=3)
    if est is not None and est.s > 0:
        c = _cobrimento(res)
        n = max(int(L / est.s), 0)
        for i in range(n + 1):
            y = min(i * est.s, L)
            ax.plot([c, b - c], [y, y], color=estilo.AZUL_MEDIO,
                    linewidth=1.0, zorder=2)
        if ancor is not None:
            ax.annotate("", (b + 8, L), (b + 8, L + ancor.l0c),
                        arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                        lw=0.9))
            ax.text(b + 10, L + ancor.l0c / 2.0,
                    f"espera\nl0c = {ancor.l0c:.0f} cm", fontsize=8,
                    va="center", color=estilo.CINZA)
        ax.text(b + 10, L / 2.0,
                f"{est.niveis} estribos\n{est.descricao()}", fontsize=9,
                va="center", color=estilo.AZUL)

    ax.annotate("", (-10, 0), (-10, L),
                arrowprops=dict(arrowstyle="<->", color=estilo.CINZA, lw=0.9))
    ax.text(-12, L / 2.0, f"lance = {L:.0f} cm", rotation=90, ha="right",
            va="center", fontsize=9, color=estilo.CINZA)
    ax.set_xlim(-40, b + 60)
    ax.set_ylim(-0.06 * L, L * 1.25)
    ax.set_xticks([])
    ax.set_yticks([])
    for lado in ("top", "right", "bottom", "left"):
        ax.spines[lado].set_visible(False)
    ax.set_title(f"{res.pilar.nome} — elevação esquemática")
    return fig
