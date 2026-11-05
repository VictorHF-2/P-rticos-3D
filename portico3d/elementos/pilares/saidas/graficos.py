# -*- coding: utf-8 -*-
"""
graficos.py
Figuras do pilar: seção armada, diagramas de interação, envoltória de momentos
resistentes, diagrama de excentricidades e esforços ao longo do lance.

Cada função devolve uma ``Figure`` do matplotlib, sem depender do PySide6.

Linguagem visual comum a todas (R05): vírgula decimal, eixos sem as bordas de
cima e da direita, uma cor e um marcador por situação de cálculo, identificadas
na **legenda** -- com o F.S. -- e não por rótulos soltos sobre os pontos, que
se sobrepunham sempre que duas situações caíam perto uma da outra.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Ellipse, Polygon

from ..core import seccional as sc
from ..core.dimensionar import ResultadoPilar
from . import estilo
from .estilo import num

TAMANHO = (11.0, 6.8)
TAMANHO_SECAO = (7.0, 7.0)
#: Acima disso as situações (varredura contínua da altura) viram pontos
#: pequenos sem legenda própria; só a governante é destacada.
MAX_SITUACOES_LEGENDA = 6


def _preparar(tamanho=TAMANHO) -> Figure:
    estilo.aplicar_estilo()
    fig = Figure(figsize=tamanho)
    fig.set_layout_engine("constrained", w_pad=0.08, h_pad=0.08)
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
                         edgecolor="#4a4f57", linewidth=1.3, zorder=1,
                         joinstyle="miter"))
    for furo in contornos[1:]:
        ax.add_patch(Polygon(furo, closed=True, facecolor="white",
                             edgecolor="#4a4f57", linewidth=1.1, zorder=2))


def _limpar_eixos(ax) -> None:
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for lado in ("top", "right", "bottom", "left"):
        ax.spines[lado].set_visible(False)


def _fs_por_situacao(res: ResultadoPilar) -> dict[str, float]:
    return {v.situacao.nome: v.fs for v in res.verificacoes}


def _estilo_situacoes(res: ResultadoPilar):
    """``(situação, cor, marcador, rótulo da legenda)`` de cada situação."""
    fs = _fs_por_situacao(res)
    muitas = len(res.situacoes) > MAX_SITUACOES_LEGENDA
    gov = res.governante.nome if res.governante is not None else None
    saida = []
    for i, s in enumerate(res.situacoes):
        cor = estilo.CORES_SITUACOES[i % len(estilo.CORES_SITUACOES)]
        marcador = estilo.MARCADOR.get(s.posicao, "o")
        if muitas and s.nome != gov:
            saida.append((s, estilo.CINZA_MEDIO, ".", None))
            continue
        f = fs.get(s.nome)
        rotulo = s.nome + (f"  —  F.S. = {num(f)}" if f is not None
                           and math.isfinite(f) else "")
        if muitas:
            rotulo += "  (governante)"
        saida.append((s, cor, marcador, rotulo))
    return saida


def _caixa(ax, texto: str, x: float, y: float, ha="left", va="top",
           transform=None, tamanho=8.5) -> None:
    """Quadro de texto com fundo branco e borda clara."""
    ax.text(x, y, texto, ha=ha, va=va, fontsize=tamanho,
            transform=transform or ax.transAxes, color="#1a1d21",
            bbox=dict(boxstyle="round,pad=0.45", facecolor="white",
                      edgecolor="#d7dbe1", linewidth=0.8, alpha=0.95),
            zorder=10)


# ---------------------------------------------------------------------------
# Seção armada
# ---------------------------------------------------------------------------

def figura_secao(res: ResultadoPilar) -> Figure:
    """Seção transversal com as barras, o estribo, as cotas e os eixos."""
    fig = _preparar(TAMANHO_SECAO)
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
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
                                linewidth=1.7, zorder=3))
        else:
            linha = geo.deslocar_para_dentro(secao.contornos()[0], recuo)
            ax.add_patch(Polygon(linha, closed=True, fill=False,
                                 edgecolor=estilo.AZUL_MEDIO, linewidth=1.7,
                                 zorder=3, joinstyle="round"))
        if arr is not None and arr.n_internas > 0:
            from ..core.arranjo import linha_do_furo
            tipo, furo = linha_do_furo(secao, recuo)
            if tipo == "circulo":
                ax.add_patch(Circle((0, 0), furo / 2.0, fill=False,
                                    edgecolor=estilo.AZUL_MEDIO,
                                    linewidth=1.7, zorder=3))
            else:
                ax.add_patch(Polygon(furo, closed=True, fill=False,
                                     edgecolor=estilo.AZUL_MEDIO,
                                     linewidth=1.7, zorder=3,
                                     joinstyle="round"))

    if arr is not None:
        for b in arr.barras:
            r = b.phi / 20.0
            ax.add_patch(Circle((b.x, b.y), r, facecolor=estilo.VERMELHO,
                                edgecolor=estilo.VERMELHO_ESCURO,
                                linewidth=0.6, zorder=4))
        _grampos(ax, res)

    x0, x1, y0, y1 = _limites(secao)
    dim = max(x1 - x0, y1 - y0)
    folga = 0.16 * dim
    ax.set_xlim(x0 - folga * 1.45, x1 + folga * 0.35)
    ax.set_ylim(y0 - folga * 1.45, y1 + folga * 0.35)
    _cotas(ax, secao, folga)
    _eixos_xy(ax, secao, dim)
    _limpar_eixos(ax)

    ax.set_title(f"{res.pilar.nome} — {secao.descricao()}", loc="left")
    linhas = []
    if arr is not None:
        try:
            taxa = f",  ρ = {num(res.taxa * 100)} %"
        except Exception:                                  # noqa: BLE001
            taxa = ""
        linhas.append(f"{arr.descricao_bitolas()} mm   "
                      f"As = {num(arr.As)} cm²{taxa}")
    if est is not None:
        linhas.append(f"Estribo {est.descricao()}")
    linhas.append(f"c = {num(_cobrimento(res), 1)} cm  "
                  f"(CAA {res.pilar.ambiente.caa})")
    # sob a figura, fora do desenho: o rótulo do eixo entra no layout
    ax.set_xlabel("\n".join(linhas), fontsize=9, color="#1a1d21",
                  labelpad=6, linespacing=1.5)
    return fig


def _eixos_xy(ax, secao, dim: float) -> None:
    """Indicador dos eixos x e y no canto -- os mesmos da entrada."""
    x0, _x1, y0, _y1 = _limites(secao)
    o = (x0 - 0.21 * dim, y0 - 0.21 * dim)
    t = 0.09 * dim
    for dx, dy, nome in ((t, 0, "x"), (0, t, "y")):
        ax.annotate("", (o[0] + dx, o[1] + dy), o,
                    arrowprops=dict(arrowstyle="-|>", color=estilo.AZUL,
                                    lw=1.1, mutation_scale=9))
        ax.text(o[0] + dx * 1.18 + (0.01 * dim if dy else 0),
                o[1] + dy * 1.18, nome, color=estilo.AZUL, fontsize=9,
                fontweight="bold", ha="center", va="center")


def _grampos(ax, res: ResultadoPilar) -> None:
    """Traça os grampos suplementares onde eles de fato ficam."""
    est = res.estribos
    arr = res.arranjo
    if est is None or arr is None or not (est.n_suplementares
                                           or est.grampos_internos):
        return
    secao = res.pilar.secao
    if secao.tipo != "retangular":
        # L, T, U e vazadas: um grampo reto por barra desprotegida,
        # perpendicular à face, atravessando a parede
        from ..core.estribos import posicoes_grampos
        for (x0, y0), (x1, y1) in posicoes_grampos(res.pilar, arr, est):
            ax.plot([x0, x1], [y0, y1], color=estilo.VERDE, linewidth=1.3,
                    linestyle=(0, (6, 2)), zorder=3)
        return
    from ..core.estribos import grampos_retangular
    for (x0, y0), (x1, y1) in grampos_retangular(secao, arr, est.phi):
        ax.plot([x0, x1], [y0, y1], color=estilo.VERDE, linewidth=1.3,
                linestyle=(0, (6, 2)), zorder=3)


def _limites(secao) -> tuple[float, float, float, float]:
    """Extensão real da seção, com a origem no CG: numa L, T ou U o CG não
    fica no centro da caixa, e ``±h/2`` cortava a figura."""
    pts = [p for c in secao.contornos() for p in c]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), max(xs), min(ys), max(ys))


def _cotas(ax, secao, folga: float) -> None:
    """Cota horizontal embaixo e vertical à esquerda, com linhas de chamada."""
    x0, x1, y0, y1 = _limites(secao)
    cor = "#5b6470"
    yc = y0 - folga * 0.42
    for x in (x0, x1):
        ax.plot([x, x], [y0 - folga * 0.08, yc - folga * 0.08], color=cor,
                lw=0.6)
    ax.annotate("", (x0, yc), (x1, yc),
                arrowprops=dict(arrowstyle="<|-|>", color=cor, lw=0.8,
                                mutation_scale=7))
    ax.text((x0 + x1) / 2.0, yc - folga * 0.10, f"{num(secao.hx, 0)} cm",
            ha="center",
            va="top", fontsize=9, color=cor)
    xc = x0 - folga * 0.42
    for y in (y0, y1):
        ax.plot([x0 - folga * 0.08, xc - folga * 0.08], [y, y], color=cor,
                lw=0.6)
    ax.annotate("", (xc, y0), (xc, y1),
                arrowprops=dict(arrowstyle="<|-|>", color=cor, lw=0.8,
                                mutation_scale=7))
    ax.text(xc - folga * 0.10, (y0 + y1) / 2.0, f"{num(secao.hy, 0)} cm",
            ha="right",
            va="center", rotation=90, fontsize=9, color=cor)


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
    marcas = _estilo_situacoes(res)
    v = res.verificacao_critica
    for ax, direcao in zip(eixos, ("x", "y")):
        pontos = sc.diagrama_interacao(res.secao_discreta, direcao, 60)
        N = np.array([p[0] for p in pontos])
        M = np.array([abs(p[1]) / 100.0 for p in pontos])
        # fecha a curva no eixo N: compressão e tração centradas
        Nf = np.concatenate([[N[0]], N, [N[-1]]])
        Mf = np.concatenate([[0.0], M, [0.0]])
        ax.fill_betweenx(Nf, 0, Mf, color=estilo.AZUL_CLARO, alpha=0.28,
                         linewidth=0)
        ax.plot(Mf, Nf, color=estilo.AZUL, linewidth=2.0,
                label="Envoltória resistente")
        ax.axhline(Nd, color=estilo.CINZA_MEDIO, linewidth=0.9,
                   linestyle=(0, (5, 3)))
        ax.text(0.99, Nd, f"Nd = {num(Nd, 0)} kN ", ha="right", va="bottom",
                fontsize=8.5, color="#5b6470",
                transform=ax.get_yaxis_transform())
        if v is not None:
            MRd = (v.MRd_xx if direcao == "x" else v.MRd_yy) / 100.0
            if MRd > 0:
                ax.plot([MRd], [Nd], marker="o", markersize=7,
                        markerfacecolor="white", markeredgecolor=estilo.AZUL,
                        markeredgewidth=1.6, zorder=6)
                ax.annotate(f"MRd = {num(MRd, 1)} kN·m", (MRd, Nd),
                            textcoords="offset points", xytext=(-6, -14),
                            ha="right", fontsize=8.5, color=estilo.AZUL)
        for s, cor, marcador, rotulo in marcas:
            Msd = abs(s.Mx if direcao == "x" else s.My) / 100.0
            ax.plot([Msd], [Nd], marker=marcador, markersize=7
                    if marcador != "." else 4, color=cor,
                    markeredgecolor="white", markeredgewidth=0.8, zorder=7,
                    linestyle="none",
                    label=rotulo if direcao == "x" else None)
        ax.set_xlabel(f"M{direcao}d (kN·m)")
        ax.set_title(f"Direção {direcao}  ·  h = "
                     f"{num(res.pilar.secao.altura(direcao), 0)} cm",
                     fontsize=10)
        ax.set_xlim(left=0)
        estilo.virgula(ax)
    eixos[0].set_ylabel("N (kN, compressão positiva)")
    fig.legend(*eixos[0].get_legend_handles_labels(), loc="outside lower center",
               ncol=min(4, len(marcas) + 1))
    fig.suptitle(f"{res.pilar.nome} — diagramas de interação à flexão "
                 f"composta normal")
    return fig


# ---------------------------------------------------------------------------
# Envoltória de momentos resistentes
# ---------------------------------------------------------------------------

def figura_envoltoria(res: ResultadoPilar) -> Figure:
    """Envoltória ``MRd,x`` x ``MRd,y`` para ``Nd``, e as situações.

    Três curvas se sobrepõem aqui:

    * a **envoltória de equilíbrio**, obtida girando a linha neutra e achando
      o momento resistente em cada direção -- é a fronteira verdadeira;
    * a **expressão do item 17.2.5**, ``(Mx/MRd,xx)^a + (My/MRd,yy)^a = 1``,
      a aproximação de projeto (informativa quando o critério não a exige);
    * a **envoltória mínima** de 1ª + 2ª ordem (Figuras 11.3 e 15.2), que a
      seção tem de conter por inteiro.
    """
    fig = _preparar((7.6, 7.2))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    if res.secao_discreta is None:
        return fig
    Nd = res.pilar.Nd
    pontos = sc.envoltoria_momentos(res.secao_discreta, Nd, 72)
    if pontos:
        px = [p[0] / 100.0 for p in pontos] + [pontos[0][0] / 100.0]
        py = [p[1] / 100.0 for p in pontos] + [pontos[0][1] / 100.0]
        ax.fill(px, py, color=estilo.AZUL_CLARO, alpha=0.25, linewidth=0)
        ax.plot(px, py, color=estilo.AZUL, linewidth=2.0,
                label="Envoltória de equilíbrio (ELU)")

    v = res.verificacao_critica
    if v is not None and v.MRd_xx > 0 and v.MRd_yy > 0:
        a = res.pilar.alfa_interacao
        t = np.linspace(0.0, math.pi / 2.0, 120)
        rx = (v.MRd_xx / 100.0) * np.cos(t) ** (2.0 / a)
        ry = (v.MRd_yy / 100.0) * np.sin(t) ** (2.0 / a)
        ex = np.concatenate([rx, -rx[::-1], -rx, rx[::-1]])
        ey = np.concatenate([ry, ry[::-1], -ry, -ry[::-1]])
        exigida = res.pilar.config.exigir_interacao_17_2_5
        ax.plot(ex, ey, color=estilo.LARANJA, linewidth=1.3,
                linestyle=(0, (5, 2)),
                label=f"Item 17.2.5 (α = {num(a, 1)})"
                      + ("" if exigida else " — informativa"))

    mm = res.momento_minimo
    if mm is not None and mm.pontos_elipse:
        pts = [(p[0] / 100.0, p[1] / 100.0) for p in mm.pontos_elipse]
        if all(x >= -1e-9 and y >= -1e-9 for x, y in pts):
            # seção simétrica: o programa só confere o primeiro quadrante
            pts = [(sx * x, sy * y) for x, y in pts
                   for sx in (1, -1) for sy in (1, -1)]
        pts.sort(key=lambda p: math.atan2(p[1], p[0]))
        mx = [p[0] for p in pts] + [pts[0][0]]
        my = [p[1] for p in pts] + [pts[0][1]]
        ax.plot(mx, my, color=estilo.VERDE, linewidth=1.4,
                linestyle=(0, (2, 2)),
                label=f"Envoltória mínima — F.S. = "
                      f"{num(min(mm.fs_x, mm.fs_y, mm.fs_elipse))}")

    for s, cor, marcador, rotulo in _estilo_situacoes(res):
        ax.plot([s.Mx / 100.0], [s.My / 100.0], marker=marcador,
                markersize=8 if marcador != "." else 4, color=cor,
                markeredgecolor="white", markeredgewidth=0.9, zorder=7,
                linestyle="none", label=rotulo)

    ax.axhline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
    ax.axvline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
    ax.set_xlabel("Mxd (kN·m)")
    ax.set_ylabel("Myd (kN·m)")
    estilo.virgula(ax)
    ax.set_title(f"{res.pilar.nome} — envoltória de momentos resistentes"
                 f"  ·  Nd = {num(Nd, 0)} kN", loc="left")
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center",
               ncol=2)
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
    fig = _preparar((7.6, 6.0))
    ax = fig.add_subplot(111)
    if res.secao_discreta is None or res.governante is None:
        return fig
    Nd = res.pilar.Nd
    g = res.governante
    alfa = math.atan2(g.My, g.Mx)
    pontos = sc.diagrama_m_n_theta(res.secao_discreta, Nd, alfa, pontos=24)
    if not pontos:
        ax.text(0.5, 0.5, "Nenhum estado de equilíbrio nessa direção\n"
                          "para esta força normal (item 5.5).",
               ha="center", va="center", transform=ax.transAxes)
        return fig

    k = [0.0] + [p.k for p in pontos]
    M = [0.0] + [p.M / 100.0 for p in pontos]
    ax.fill_between(k, 0.0, M, color=estilo.AZUL_CLARO, alpha=0.25,
                    linewidth=0)
    ax.plot(k, M, color=estilo.AZUL, linewidth=2.0, label="M resistente")
    ax.plot([k[-1]], [M[-1]], marker="o", markersize=8,
            color=estilo.VERMELHO, markeredgecolor="white", zorder=6,
            linestyle="none",
            label="ELU" + (f" — domínio {pontos[-1].dominio}"
                           if pontos[-1].dominio else ""))
    MSd = math.hypot(g.Mx, g.My) / 100.0
    if MSd > 0:
        ax.axhline(MSd, color=estilo.LARANJA, linewidth=1.2,
                   linestyle=(0, (5, 3)),
                   label=f"MSd da situação {g.nome}")
    texto = f"MRd = {num(M[-1], 1)} kN·m\nMSd = {num(MSd, 1)} kN·m"
    if MSd > 0:
        texto += f"\nMRd/MSd = {num(M[-1] / MSd)}"
    _caixa(ax, texto, 0.03, 0.97)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0, top=max(M) * 1.12)
    ax.set_xlabel("curvatura k (‰/cm)")
    ax.set_ylabel("|M| (kN·m)")
    estilo.virgula(ax)
    ax.set_title(f"{res.pilar.nome} — momento-curvatura  ·  Nd = "
                 f"{num(Nd, 0)} kN  ·  direção {math.degrees(alfa):.0f}°",
                 loc="left")
    ax.legend(loc="lower right")
    return fig


# ---------------------------------------------------------------------------
# Excentricidades e situações de cálculo
# ---------------------------------------------------------------------------

def figura_excentricidades(res: ResultadoPilar) -> Figure:
    """As situações de cálculo no plano ``(ex, ey)``.

    A figura mostra por que as situações existem: o momento mínimo do item
    11.3.3.4.3 é um piso das excentricidades -- a elipse da envoltória mínima
    (ou o retângulo, no método da planilha, que impõe o mínimo numa direção de
    cada vez) --, e a segunda ordem entra só na seção do meio.
    """
    fig = _preparar((7.6, 7.2))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    ex_min = res.esbeltez["x"].e1_min if res.esbeltez else 0.0
    ey_min = res.esbeltez["y"].e1_min if res.esbeltez else 0.0
    if res.pilar.config.momento_minimo_metodo == "envoltoria":
        ax.add_patch(Ellipse((0, 0), 2 * ex_min, 2 * ey_min, fill=True,
                             facecolor="#f3f8ef", edgecolor=estilo.VERDE,
                             linewidth=1.2, linestyle=(0, (4, 3)),
                             label="e₁,mín — envoltória mínima (11.3.3.4.3)"))
    else:
        ax.add_patch(Polygon([(-ex_min, -ey_min), (ex_min, -ey_min),
                              (ex_min, ey_min), (-ex_min, ey_min)],
                             closed=True, facecolor="#f3f8ef",
                             edgecolor=estilo.VERDE, linewidth=1.2,
                             linestyle=(0, (4, 3)),
                             label="e₁,mín por direção (11.3.3.4.3)"))
    g = res.governante
    if g is not None:
        ax.plot([0, g.ex], [0, g.ey], color=estilo.CINZA_MEDIO, linewidth=1.0,
                zorder=4)
    for s, cor, marcador, rotulo in _estilo_situacoes(res):
        if rotulo is not None:
            rotulo = (f"{s.nome}  ({num(s.ex)}; {num(s.ey)}) cm"
                      f"  |e| = {num(s.modulo)}")
        ax.plot([s.ex], [s.ey], marker=marcador,
                markersize=8 if marcador != "." else 4, color=cor,
                markeredgecolor="white", markeredgewidth=0.9, zorder=6,
                linestyle="none", label=rotulo)
    lim = 1.25 * max([ex_min, ey_min] + [abs(s.ex) for s in res.situacoes]
                     + [abs(s.ey) for s in res.situacoes] + [0.1])
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.axhline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
    ax.axvline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
    ax.set_xlabel("ex (cm)")
    ax.set_ylabel("ey (cm)")
    estilo.virgula(ax)
    ax.set_title(f"{res.pilar.nome} — situações de cálculo", loc="left")
    fig.legend(*ax.get_legend_handles_labels(), loc="outside lower center",
               ncol=1)
    return fig


# ---------------------------------------------------------------------------
# Esforços ao longo do lance
# ---------------------------------------------------------------------------

def figura_esforcos(res: ResultadoPilar) -> Figure:
    """Momentos ao longo do lance, **com sinal**, nas duas direções.

    * a linha fina é o momento de 1ª ordem, linear entre topo e base;
    * a grossa soma a 2ª ordem do pilar-padrão -- senoide de máximo no meio
      no lance biapoiado, cosseno de máximo na base no balanço --, no sentido
      do momento de maior módulo;
    * a faixa é o piso ±M1d,mín do item 11.3.3.4.3, verificado à parte pela
      envoltória mínima;
    * os marcadores são os momentos verificados no topo, no meio e na base,
      com o F.S. de cada cota.
    """
    fig = _preparar()
    gs = fig.add_gridspec(1, 3, width_ratios=[0.42, 1, 1])
    ax_n = fig.add_subplot(gs[0])
    eixos = [fig.add_subplot(gs[1], sharey=ax_n),
             fig.add_subplot(gs[2], sharey=ax_n)]
    L = res.pilar.lance.altura
    z = np.linspace(0.0, L, 201)
    f = res.pilar.fator_esforcos
    vz = res.verificacoes_z or {}
    Nd = res.pilar.Nd
    ax_n.fill_betweenx([0, L], 0, Nd, color=estilo.AZUL_CLARO, alpha=0.45,
                       linewidth=0)
    ax_n.plot([Nd, Nd], [0, L], color=estilo.AZUL, linewidth=2.0)
    ax_n.axvline(0, color="#a8aeb6", linewidth=0.8)
    ax_n.set_xlim(min(0.0, Nd) * 1.3 - 1e-9, max(0.0, Nd) * 1.3 + 1e-9)
    ax_n.set_ylim(-0.04 * L, 1.06 * L)
    ax_n.set_xlabel("Nsd (kN)")
    ax_n.set_ylabel("cota no lance (cm)")
    ax_n.set_title(f"Força normal\nNsd = {num(Nd, 0)} kN\n", fontsize=9.5)
    estilo.virgula(ax_n)
    for ax, direcao in zip(eixos, ("x", "y")):
        e = res.esbeltez[direcao]
        so = res.segunda_ordem[direcao]
        Mt = f * res.pilar.esforcos.topo(direcao) / 100.0
        Mb = f * res.pilar.momento_base(direcao) / 100.0
        M1 = Mb + (Mt - Mb) * z / L if L > 0 else np.zeros_like(z)
        if so.aplicavel and math.isfinite(so.e2) and L > 0:
            forma = (np.cos(math.pi * z / (2 * L)) if e.vinculo == 3
                     else np.sin(math.pi * z / L))
            M2 = e.sinal_A * abs(res.pilar.Nd) * so.e2 / 100.0 * forma
        else:
            M2 = np.zeros_like(z)
        Mmin = e.M1d_min / 100.0
        ax.axvspan(-Mmin, Mmin, color="#fbe5d6", alpha=0.55, linewidth=0,
                   label="±M₁d,mín (11.3.3.4.3)")
        for lado in (-Mmin, Mmin):
            ax.axvline(lado, color=estilo.LARANJA, linewidth=0.9,
                       linestyle=(0, (4, 3)))
        ax.axvline(0, color="#a8aeb6", linewidth=0.8)
        ax.plot(M1, z, color=estilo.AZUL_MEDIO, linewidth=1.3,
                label="M₁d — 1ª ordem")
        ax.plot(M1 + M2, z, color=estilo.AZUL, linewidth=2.2,
                label="M₁d + M₂d — com a 2ª ordem")
        ax.fill_betweenx(z, M1, M1 + M2, color=estilo.AZUL_CLARO, alpha=0.35,
                         linewidth=0)
        valores = [abs(Mmin), *np.abs(M1 + M2), *np.abs(M1)]
        # a seção intermediária do pilar-padrão (alfa_b M1d,A + Nd e2): meia
        # altura no lance biapoiado, a base no balanço -- não é o valor da
        # curva naquela cota, e por isso o marcador não cai sobre ela
        cota_meio = 0.0 if e.vinculo == 3 else L / 2.0
        for nome, cota in (("Topo", L), ("Meio", cota_meio), ("Base", 0.0)):
            v = vz.get(nome)
            if v is None:
                continue
            M = (v.situacao.Mx if direcao == "x" else v.situacao.My) / 100.0
            valores.append(abs(M))
            ax.plot([M], [cota], marker="D", markersize=6,
                    color=estilo.VERMELHO, markeredgecolor="white",
                    zorder=6, linestyle="none",
                    label="momento verificado (meio: αb·M₁d,A + Nd·e₂)"
                    if nome == "Topo" else None)
            texto = f"{nome}: {num(M, 1)} kN·m"
            if math.isfinite(v.fs):
                texto += f"  ·  F.S. {num(v.fs)}"
            dy = {"Topo": -11, "Meio": 9 if cota_meio < 0.1 * L else -3,
                  "Base": -3}[nome]
            ax.annotate(texto, (M, cota), textcoords="offset points",
                        xytext=(8, dy),
                        fontsize=8, color=estilo.VERMELHO,
                        bbox=dict(boxstyle="round,pad=0.25", fc="white",
                                  ec="none", alpha=0.85))
        lim = 1.35 * max(valores + [0.1])
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-0.04 * L, 1.06 * L)
        ax.set_xlabel(f"M{direcao}d (kN·m)")
        estilo.virgula(ax)
        titulo = (f"Direção {direcao}\nλ = {num(e.lam, 1)}  ·  "
                  f"λ₁ = {num(e.lam_1, 1)}  ·  αb = {num(e.alfa_b)}")
        sub = (f"2ª ordem: e₂ = {num(so.e2)} cm" if so.aplicavel
               else "2ª ordem dispensada")
        ax.set_title(f"{titulo}\n{sub}", fontsize=9.5)
    for ax in eixos:
        ax.tick_params(labelleft=False)
    fig.legend(*eixos[0].get_legend_handles_labels(),
               loc="outside lower center", ncol=2)
    fig.suptitle(f"{res.pilar.nome} — momentos de cálculo ao longo do lance")
    return fig


# ---------------------------------------------------------------------------
# Elevação esquemática
# ---------------------------------------------------------------------------

def figura_elevacao(res: ResultadoPilar) -> Figure:
    """Elevação do lance com os estribos e o comprimento de espera."""
    fig = _preparar((5.2, 8.0))
    ax = fig.add_subplot(111)
    ax.set_aspect("equal")
    secao = res.pilar.secao
    L = res.pilar.lance.altura
    b = secao.hx
    ax.add_patch(Polygon([(0, 0), (b, 0), (b, L), (0, L)], closed=True,
                         facecolor=estilo.CONCRETO, edgecolor="#4a4f57",
                         linewidth=1.3))
    escala = max(b, 0.12 * L)

    arr, est, ancor = res.arranjo, res.estribos, res.ancoragem
    c = _cobrimento(res)
    if est is not None and est.s > 0:
        n = max(int(L / est.s), 0)
        for i in range(n + 1):
            y = min(i * est.s, L)
            ax.plot([c, b - c], [y, y], color=estilo.AZUL_MEDIO,
                    linewidth=1.0, zorder=2)
    if arr is not None:
        for x in (c + arr.phi / 20.0, b - c - arr.phi / 20.0):
            ax.plot([x, x], [0, L], color=estilo.VERMELHO, linewidth=2.0,
                    zorder=3)
            if ancor is not None:
                ax.plot([x, x], [L, L + ancor.l0c], color=estilo.VERMELHO,
                        linewidth=2.0, linestyle=(0, (5, 3)), zorder=3)
    cor = "#5b6470"
    xd = b + 0.35 * escala
    if ancor is not None:
        ax.annotate("", (xd, L), (xd, L + ancor.l0c),
                    arrowprops=dict(arrowstyle="<|-|>", color=cor, lw=0.8,
                                    mutation_scale=7))
        ax.text(xd + 0.08 * escala, L + ancor.l0c / 2.0,
                f"espera  l₀{'t' if ancor.tracionada else 'c'} = "
                f"{num(ancor.l0c, 0)} cm", fontsize=8.5,
                va="center", color=cor)
    if est is not None:
        ax.text(xd + 0.08 * escala, L / 2.0,
                f"{est.niveis} estribos\n{est.descricao()}", fontsize=9,
                va="center", color=estilo.AZUL)
    if arr is not None:
        ax.text(xd + 0.08 * escala, L * 0.25,
                f"{arr.descricao_bitolas()} mm", fontsize=9, va="center",
                color=estilo.VERMELHO)
    xl = -0.35 * escala
    ax.annotate("", (xl, 0), (xl, L),
                arrowprops=dict(arrowstyle="<|-|>", color=cor, lw=0.8,
                                mutation_scale=7))
    ax.text(xl - 0.08 * escala, L / 2.0, f"lance = {num(L, 0)} cm",
            rotation=90, ha="right", va="center", fontsize=9, color=cor)
    topo = L + (ancor.l0c if ancor is not None else 0.0)
    ax.set_xlim(xl - 0.45 * escala, b + 2.6 * escala)
    ax.set_ylim(-0.04 * L, topo + 0.05 * L)
    _limpar_eixos(ax)
    ax.set_title(f"{res.pilar.nome} — elevação esquemática", loc="left")
    return fig


# ---------------------------------------------------------------------------
# Rigidez secante: momento x curvatura nas duas direções e sentidos
# ---------------------------------------------------------------------------

PONTOS_CURVA = 36


def curvas_momento_curvatura(res: ResultadoPilar, pontos: int = PONTOS_CURVA
                             ) -> dict:
    """As curvas M x 1/r da Figura 15.1 por direção e sentido.

    Para cada ``(direção, sentido)``: a curva de **deformabilidade** (pico
    1,10 fcd, normal Nd/γf3) e a de **cálculo** (0,85 ηc fcd, Nd), cada uma
    da curvatura zero até o limite de deformação, e o ponto B com o
    ``(EI)sec`` -- é a janela "Rigidez secante (EIsec)" do PCalc. Curvatura
    em ‰/m (10⁻³/m), momento em kN·m. ``{}`` sem seção armada ou com
    tração."""
    from ..core import momento_curvatura as mc
    secao = res.secao_discreta
    if secao is None or res.pilar.Nd <= 0.0:
        return {}
    Nd = abs(res.pilar.Nd) / res.pilar.gamma_n
    cfg = res.pilar.config
    fator = (1.0 + res.pilar.phi_fluencia * cfg.Nsg_sobre_Nd
             if cfg.considerar_fluencia and cfg.fluencia_metodo == "diagrama"
             else 1.0)
    sd = mc.secao_deformabilidade(secao, fator)
    saida = {}
    for d in ("x", "y"):
        for s in (1.0, -1.0):
            theta = mc.theta_da_direcao(d, s)
            curvas = {}
            for nome, sec, N in (("deformabilidade", sd, Nd / mc.GAMMA_F3),
                                 ("calculo", secao, Nd)):
                k_lim = mc._curvatura_limite(sec, theta, N, d)
                ks, Ms = [0.0], [0.0]
                for i in range(1, pontos + 1):
                    k = k_lim * i / pontos
                    M, _ = mc.momento_na_curvatura(sec, theta, k, N, d)
                    if math.isfinite(M):
                        ks.append(k)
                        Ms.append(M)
                # k em ‰/cm -> ‰/m (x 100); M em kN·cm -> kN·m
                curvas[nome] = (np.array(ks) * 100.0, np.array(Ms) / 100.0)
            rs = mc.rigidez_secante(secao, Nd, d, s, fator_fluencia=fator)
            saida[(d, s)] = dict(
                curvas=curvas,
                EI=rs.EI / 1e4 if rs else None,             # kN·m²
                MB=rs.M_B / 100.0 if rs else None,
                kB=rs.curvatura_B * 1e5 if rs else None,    # ‰/m
                MRd=rs.MRd / 100.0 if rs else None)
    return saida


def exportar_momento_curvatura(res: ResultadoPilar, caminho: str) -> str:
    """As curvas M x 1/r em texto (CSV com ponto e vírgula), como o
    "Diagrama N, M, 1/r (txt)" do PCalc."""
    dados = curvas_momento_curvatura(res)
    linhas = [f"# {res.pilar.nome} — diagramas M x 1/r, Nd = "
              f"{num(res.pilar.Nd, 1)} kN",
              "direcao;sentido;curva;1/r (permil/m);M (kN.m)"]
    for (d, s), v in dados.items():
        sinal = "+" if s > 0 else "-"
        for nome, (k, M) in v["curvas"].items():
            for ki, Mi in zip(k, M):
                linhas.append(f"{d};{sinal};{nome};{num(ki, 6)};{num(Mi, 3)}")
        if v["EI"] is not None:
            linhas.append(f"{d};{sinal};EIsec (kN.m2);;{num(v['EI'], 1)}")
    with open(caminho, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(linhas) + "\n")
    return caminho


def figura_rigidez_secante(res: ResultadoPilar) -> Figure:
    """Momento x curvatura (Figura 15.1) nas direções x e y, os dois
    sentidos no mesmo gráfico: curva de deformabilidade (1,10 fcd, Nd/γf3),
    curva de cálculo (0,85 ηc fcd) e a reta do ``(EI)sec`` até o ponto B."""
    fig = _preparar()
    dados = curvas_momento_curvatura(res)
    eixos = fig.subplots(1, 2)
    if not dados:
        for ax in eixos:
            ax.text(0.5, 0.5, "Sem seção armada ou com normal de tração.",
                    ha="center", va="center", transform=ax.transAxes)
        return fig
    for ax, d in zip(eixos, ("x", "y")):
        textos = []
        for s in (1.0, -1.0):
            v = dados[(d, s)]
            kd, Md = v["curvas"]["deformabilidade"]
            kc, Mc = v["curvas"]["calculo"]
            sinal = "+" if s > 0 else "−"
            ax.plot(s * kd, s * Md, color=estilo.AZUL, linewidth=2.0,
                    label="Curva com 1,10·fcd e Nd/γf3" if s > 0 else None)
            ax.plot(s * kc, s * Mc, color=estilo.LARANJA, linewidth=1.5,
                    linestyle=(0, (5, 2)),
                    label="Curva com 0,85·ηc·fcd (cálculo)" if s > 0 else None)
            if v["EI"] is not None:
                ax.plot([0, s * v["kB"]], [0, s * v["MB"]],
                        color=estilo.VERMELHO, linewidth=1.4,
                        label="(EI)sec — reta até B" if s > 0 else None)
                ax.plot([s * v["kB"]], [s * v["MB"]], marker="o",
                        markersize=6, color=estilo.VERMELHO,
                        markeredgecolor="white", zorder=6, linestyle="none")
                ax.axhline(s * v["MRd"], color=estilo.CINZA_MEDIO,
                           linewidth=0.8, linestyle=(0, (2, 2)))
                textos.append(f"EIsec,{sinal}{d} = {num(v['EI'], 0)} kN·m²")
            else:
                textos.append(f"EIsec,{sinal}{d}: a curva não alcança MRd/γf3")
        ax.axhline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
        ax.axvline(0, color="#a8aeb6", linewidth=0.7, zorder=0)
        _caixa(ax, "\n".join(textos), 0.03, 0.97)
        ax.set_xlabel("curvatura 1/r (‰/m = 10⁻³/m)")
        ax.set_ylabel(f"M{d}d (kN·m)")
        estilo.virgula(ax)
        ax.set_title(f"Direção {d}  ·  linha neutra paralela ao eixo {d}",
                     fontsize=10)
    fig.legend(*eixos[0].get_legend_handles_labels(),
               loc="outside lower center", ncol=3)
    fig.suptitle(f"{res.pilar.nome} — rigidez secante: momento × curvatura "
                 f"(Figura 15.1)  ·  Nd = {num(res.pilar.Nd, 0)} kN")
    return fig


# ---------------------------------------------------------------------------
# Deformação e tensão na seção (estado no ELU de uma cota)
# ---------------------------------------------------------------------------

def _cota_critica(res: ResultadoPilar):
    vz = res.verificacoes_z or {}
    if not vz:
        return None
    return min(vz, key=lambda k: vz[k].fs)


def figura_estado_secao(res: ResultadoPilar, cota=None) -> Figure:
    """Deformações e tensões na seção, no estado limite da cota pedida
    ("Topo", "Meio", "Base"; por padrão a de menor F.S.), na direção do
    momento solicitante -- os gráficos "Deformação" e "Tensão" do PCalc.

    À esquerda, a seção com a linha neutra, a zona comprimida colorida pela
    tensão do concreto e as barras (vermelho comprimida, azul tracionada);
    ao centro, ε ao longo do eixo u normal à linha neutra, com o ε de cada
    barra; à direita, σ do concreto (parábola-retângulo) e das barras."""
    from ..core import fibras
    from ..core import seccional as sc_mod
    fig = _preparar((13.5, 6.2))
    cota = cota or _cota_critica(res)
    ef = fibras.montar(res, cota) if cota else None
    if ef is None or ef.estado is None:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "Sem estado de equilíbrio para esta cota.",
                ha="center", va="center", transform=ax.transAxes)
        return fig
    plano, theta = ef.estado.plano, ef.estado.theta
    ct, st = math.cos(theta), math.sin(theta)
    contornos = res.pilar.secao.contornos()
    us = [x * ct + y * st for c in contornos for x, y in c]
    u0, u1 = min(us), max(us)
    gs = fig.add_gridspec(1, 4, width_ratios=[1.15, 1, 0.8, 0.8])
    ax_s = fig.add_subplot(gs[0])
    ax_e = fig.add_subplot(gs[1])
    ax_t = fig.add_subplot(gs[2], sharey=ax_e)
    ax_a = fig.add_subplot(gs[3], sharey=ax_e)

    # -- seção: zona comprimida pela tensão, barras, linha neutra
    ax_s.set_aspect("equal")
    _contorno(ax_s, res, cor="#f4f2ee")
    dim = max(res.pilar.secao.hx, res.pilar.secao.hy)
    # malha contínua da tensão do concreto, recortada pelo contorno (e pelos
    # furos) -- a zona comprimida como mancha, não como pontos soltos
    from matplotlib.path import Path
    x0, x1, y0, y1 = _limites(res.pilar.secao)
    gx, gy = np.meshgrid(np.linspace(x0, x1, 140), np.linspace(y0, y1, 140))
    pontos = np.column_stack([gx.ravel(), gy.ravel()])
    dentro = Path(contornos[0]).contains_points(pontos)
    for furo in contornos[1:]:
        dentro &= ~Path(furo).contains_points(pontos)
    eps_g = plano.eps_ref + plano.k * (gx * ct + gy * st - plano.u_ref)
    sig_g = np.asarray(sc_mod.tensao_concreto(res.pilar.concreto,
                                              eps_g.ravel())) * 10.0
    mascara = ~dentro | (eps_g.ravel() <= 0.0)
    sig_g = np.ma.array(sig_g, mask=mascara).reshape(gx.shape)
    ax_s.pcolormesh(gx, gy, sig_g, cmap="YlOrRd", vmin=0,
                    vmax=ef.fcd_ac * 10.0, shading="auto", zorder=2,
                    rasterized=True)
    for b in ef.barras:
        cor = estilo.VERMELHO if b.tensao > 0 else estilo.AZUL_MEDIO
        ax_s.add_patch(Circle((b.x, b.y), max(b.phi / 20.0, 0.4),
                              facecolor=cor, edgecolor="#1a1d21",
                              linewidth=0.7, zorder=4))
    if abs(plano.k) > 1e-12:
        un = plano.u_ref - plano.eps_ref / plano.k
        px, py = un * ct, un * st
        ax_s.plot([px - st * dim, px + st * dim],
                  [py + ct * dim, py - ct * dim], color="#1a1d21",
                  linewidth=1.2, linestyle=(0, (6, 3)), zorder=5)
    fo = 0.08 * dim
    ax_s.set_xlim(x0 - fo, x1 + fo)
    ax_s.set_ylim(y0 - fo, y1 + fo)
    _limpar_eixos(ax_s)
    ax_s.set_title(f"Seção  ·  domínio {plano.dominio}  ·  "
                   f"LN tracejada", fontsize=10)

    # -- deformação
    u = np.linspace(u0, u1, 80)
    eps = plano.eps_ref + plano.k * (u - plano.u_ref)
    ax_e.fill_betweenx(u, 0, eps, where=eps >= 0, color="#fbe5d6",
                       linewidth=0)
    ax_e.fill_betweenx(u, 0, eps, where=eps < 0, color="#deebf7",
                       linewidth=0)
    ax_e.plot(eps, u, color=estilo.AZUL, linewidth=1.8)
    ub = [b.x * ct + b.y * st for b in ef.barras]
    ax_e.plot([b.eps for b in ef.barras], ub, marker="o", linestyle="none",
              color=estilo.VERMELHO, markersize=5)
    ax_e.axvline(0, color="#a8aeb6", linewidth=0.8)
    ax_e.set_xlabel("deformação ε (‰, compressão +)")
    ax_e.set_ylabel("u (cm), normal à linha neutra")
    estilo.virgula(ax_e)
    eps_b = min(b.eps for b in ef.barras) if ef.barras else 0.0
    ax_e.set_title(f"Deformação  ·  εc = {num(max(eps))} ‰  ·  "
                   f"εs = {num(eps_b)} ‰", fontsize=10)

    # -- tensão
    sig = np.asarray(sc_mod.tensao_concreto(res.pilar.concreto, eps)) * 10.0
    ax_t.fill_betweenx(u, 0, sig, color="#fbe5d6", linewidth=0)
    ax_t.plot(sig, u, color=estilo.LARANJA, linewidth=1.8)
    ax_t.axvline(0, color="#a8aeb6", linewidth=0.8)
    ax_t.set_xlim(left=0, right=max(ef.fcd_ac * 10.0, float(max(sig))) * 1.15)
    ax_t.set_xlabel("σc (MPa)")
    estilo.virgula(ax_t)
    ax_t.tick_params(labelleft=False)
    ax_t.set_title(f"Tensão no concreto\nσc,máx = "
                   f"{num(ef.fcd_ac * 10.0, 1)} MPa", fontsize=10)
    sb = [b.tensao * 10.0 for b in ef.barras]
    for b, ui, si in zip(ef.barras, ub, sb):
        ax_a.plot([0, si], [ui, ui], color=estilo.VERMELHO if si > 0
                  else estilo.AZUL_MEDIO, linewidth=2.2)
    ax_a.plot(sb, ub, marker="o", linestyle="none", color="#1a1d21",
              markersize=3.5)
    fyd = ef.fyd * 10.0
    for lado in (-fyd, fyd):
        ax_a.axvline(lado, color=estilo.CINZA_MEDIO, linewidth=0.8,
                     linestyle=(0, (3, 3)))
    ax_a.axvline(0, color="#a8aeb6", linewidth=0.8)
    ax_a.set_xlim(-1.15 * fyd, 1.15 * fyd)
    ax_a.set_xlabel("σs (MPa)")
    estilo.virgula(ax_a)
    ax_a.tick_params(labelleft=False)
    ax_a.set_title(f"Tensão nas barras\n±fyd = {num(fyd, 0)} MPa",
                   fontsize=10)
    v = (res.verificacoes_z or {}).get(cota)
    fs_txt = (f"  ·  F.S. = {num(v.fs)}" if v is not None
              and math.isfinite(v.fs) else "")
    fig.suptitle(f"{res.pilar.nome} — deformações e tensões no ELU  ·  "
                 f"cota {cota}{fs_txt}")
    return fig
