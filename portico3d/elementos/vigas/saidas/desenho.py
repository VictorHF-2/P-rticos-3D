# -*- coding: utf-8 -*-
"""
desenho.py
Croqui de detalhamento em matplotlib: elevação da viga com as armaduras
escalonadas e os estribos, e as seções transversais pedidas.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon

from ..core.dimensionar import ResultadoViga
from . import estilo, geometria

#: Cor de cada camada de desenho: armadura superior azul, inferior vermelha.
CORES = {
    "ZONA": estilo.AMARELO,
    "ARMADURA_SUP": estilo.AZUL,
    "ARMADURA_INF": estilo.VERMELHO,
    "PELE": estilo.LARANJA,
    "ESTRIBO": estilo.VERDE,
    "TEXTO": estilo.CINZA_MEDIO,
    "CONCRETO": estilo.CINZA,
    "APOIO": estilo.CINZA,
}

ESPESSURAS = {"ARMADURA_SUP": 1.8, "ARMADURA_INF": 1.8, "PELE": 1.2,
              "ESTRIBO": 1.0, "TEXTO": 0.5}

#: No croqui o texto tem tamanho de fonte fixo e ocupa mais espaço de desenho
#: que os 5 cm assumidos pela geometria; a folga evita rótulos colados.
FOLGA_ROTULO_CROQUI = 3.4


def _desenhar_polilinha(ax, pol: geometria.Polilinha, fator_v: float = 1.0,
                        **kw) -> None:
    pts = np.array(pol.pontos, dtype=float).copy()
    pts[:, 1] *= fator_v
    if pol.fechada:
        ax.add_patch(Polygon(pts, closed=True, **kw))
    else:
        ax.plot(pts[:, 0], pts[:, 1], **kw)


def figura_elevacao(res: ResultadoViga, mostrar_estribos: bool = True,
                    fator_vertical: float = 0.0,
                    mostrar_explodida: bool = True) -> Figure:
    """Elevação da viga com o detalhamento das armaduras.

    O desenho sai em **escala real** (1:1 nos dois eixos, como o DXF).
    ``fator_vertical`` maior que 1 exagera só a altura da elevação, para quem
    quiser separar as barras de uma viga muito baixa; a vista explodida é
    sempre 1:1, porque é dela que sai a forma do ferro. Com
    ``mostrar_explodida`` a figura ganha, abaixo da viga, a vista das armaduras
    separadas e cotadas.
    """
    estilo.aplicar_estilo()
    el = geometria.montar_elevacao(res, mostrar_estribos,
                                   folga_rotulo=FOLGA_ROTULO_CROQUI)
    largura_cm = el.x_max - el.x_min
    if fator_vertical <= 0:
        fator_vertical = 1.0            # escala real
    fv = fator_vertical

    y_base_elevacao = el.y_min
    altura_explodida = 0.0
    postas: list = []
    if mostrar_explodida:
        barras = geometria.montar_explodida(res)
        postas, altura_explodida = geometria.dispor_explodidas(barras)

    # os limites do desenho são conhecidos antes da figura, e a altura dela sai
    # da proporção real entre eles: só assim o eixo de aspecto igual preenche a
    # largura toda em vez de sobrar faixa em branco dos lados
    y_topo_explodida = y_base_elevacao * fv - 95.0
    y_max = (el.h_max + 120.0) * fv
    if postas:
        y_min = (y_topo_explodida + min(dy for _, _, dy in postas)
                 - geometria.ALTURA_ROTULO - 20.0)
    else:
        y_min = y_base_elevacao * fv
    largura_desenho = largura_cm + 120.0
    altura_desenho = y_max - y_min
    fig = Figure(figsize=(16.0, float(np.clip(
        16.0 * altura_desenho / largura_desenho, 4.0, 26.0))))
    ax = fig.add_subplot(111)

    for pol in el.contorno:
        _desenhar_polilinha(ax, pol, fv, facecolor=estilo.CONCRETO,
                            edgecolor=estilo.CINZA, lw=1.0, zorder=1)
    for pol in el.apoios:
        _desenhar_polilinha(ax, pol, fv, facecolor="#cfd4da",
                            edgecolor=estilo.CINZA, lw=0.8, zorder=0)
    for pol in el.estribos:
        cor = CORES.get(pol.camada, estilo.CINZA_MEDIO)
        _desenhar_polilinha(ax, pol, fv, color=cor,
                            lw=0.6 if pol.camada == "ESTRIBO" else 0.5,
                            zorder=2)
    for pol in el.zonas:                    # limites das faixas de estribos
        _desenhar_polilinha(ax, pol, fv, color=estilo.AMARELO, lw=0.9,
                            ls=(0, (4, 2)), zorder=4)
    for xa, xb, y, rotulo in el.cotas_estribo:
        _cotar(ax, xa, xb, y * fv, rotulo, cor=estilo.AMARELO)
    for pol in el.barras:
        cor = CORES.get(pol.camada, estilo.CINZA_MEDIO)
        lw = ESPESSURAS.get(pol.camada, 0.5)
        _desenhar_polilinha(ax, pol, fv, color=cor, lw=lw, zorder=3,
                            solid_capstyle="round")
    for xa, xb, y, rotulo in el.cotas:
        ax.annotate("", xy=(xa, y * fv), xytext=(xb, y * fv),
                    arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                    lw=0.8))
        ax.text((xa + xb) / 2.0, y * fv + 3.0 * fv, rotulo, ha="center",
                va="bottom", fontsize=8, color=estilo.CINZA)

    if postas:
        y_topo = y_topo_explodida
        ax.text(el.x_min, y_topo + 46.0,
                "ARMADURAS EXPLODIDAS — cada barra sob a sua posição na "
                "viga; comprimentos em cm, escala 1:1",
                fontsize=9, fontweight="bold", color=estilo.CINZA)
        # linhas de chamada dos eixos: amarram a vista explodida à elevação
        for x_eixo, nome in el.eixos:
            ax.plot([x_eixo, x_eixo], [y_min, 0.0], color=estilo.CINZA_CLARO,
                    lw=0.7, ls="-.", zorder=0)
            ax.text(x_eixo, y_min - 8.0, nome, ha="center", va="top",
                    fontsize=7.5, color=estilo.CINZA_MEDIO)
        for barra, x_barra, dy in postas:
            _desenhar_barra_explodida(ax, barra, x_barra, y_topo + dy)

    ax.set_xlim(el.x_min - 60, el.x_max + 60)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal")
    ax.axis("off")
    escala = ("escala 1:1" if abs(fv - 1.0) < 1e-6 else
              f"altura da elevação exagerada {fv:.1f}x; explodida 1:1")
    ax.set_title(f"Detalhamento — {res.viga.nome}   (cotas em cm; {escala})",
                 fontsize=11, fontweight="bold")
    # os rótulos entram por último, depois de limites e layout definidos: a
    # colocação mede a largura real da fonte, e qualquer ajuste posterior da
    # caixa dos eixos mudaria a escala em que essa medida foi tomada
    fig.tight_layout()
    _colocar_textos(fig, ax, el.textos, fv)
    return fig


def _colocar_textos(fig, ax, textos: list[geometria.Texto], fv: float) -> None:
    """Desenha os rótulos da elevação sem deixá-los se sobrepor.

    A largura de cada rótulo é **medida** no renderizador -- estimá-la pela
    altura do texto não funciona no croqui, onde a fonte tem tamanho fixo e a
    escala do desenho varia com o vão. Quem colide desce um degrau, e a linha
    de chamada é traçada até a posição final.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    canvas = FigureCanvasAgg(fig)
    canvas.draw()          # sem desenhar uma vez, as métricas do texto mentem
    renderer = canvas.get_renderer()
    passo = geometria.ALTURA_ROTULO_ELEVACAO * 2.4 * fv

    def caixa_de(artista) -> tuple[float, float, float, float]:
        bb = artista.get_window_extent(renderer=renderer)
        bb = bb.transformed(ax.transData.inverted())
        return (bb.x0, bb.y0, bb.x1, bb.y1)

    # o que já está desenhado (cotas de vão, títulos) também é obstáculo
    ocupadas: list[tuple[float, float, float, float]] = [
        caixa_de(art) for art in list(ax.texts) if art.get_text().strip()]

    for t in sorted(textos, key=lambda t: (t.chamada is None, t.posicao[0])):
        x, y = t.posicao[0], t.posicao[1] * fv
        alinhamento = {"center": "center", "left": "left"}.get(t.ancora, "left")
        artista = ax.text(x, y, t.texto, fontsize=6.5, ha=alinhamento,
                          va="center", color=estilo.CINZA, zorder=4)
        if t.chamada is None:
            continue
        acima = t.posicao[1] > 0.0
        for _ in range(24):
            atual = caixa_de(artista)
            # o degrau precisa ser maior que o próprio texto, senão empurrar
            # uma linha ainda deixa as caixas encostadas
            passo = max(passo, (atual[3] - atual[1]) * 1.15)
            if not any(atual[0] < o[2] and o[0] < atual[2]
                       and atual[1] < o[3] and o[1] < atual[3]
                       for o in ocupadas):
                break
            y += passo if acima else -passo
            artista.set_y(y)
        ocupadas.append(atual)
        ax.plot([t.chamada[0], x], [t.chamada[1] * fv, y],
                color=estilo.CINZA_MEDIO, lw=0.5, zorder=3)


def _desenhar_barra_explodida(ax, barra: geometria.BarraExplodida, x0: float,
                              y0: float, fv: float = 1.0) -> None:
    """Desenha uma barra da vista explodida, com as cotas de cada trecho.

    Sempre em escala 1:1, mesmo quando a elevação acima está com a altura
    exagerada: é aqui que a forma da barra -- estribo, ganchos, dobras -- tem
    de sair fiel para o ferreiro.
    """
    cor = CORES.get(barra.camada, estilo.CINZA)
    pts = np.array(barra.pontos, dtype=float).copy()
    pts[:, 0] += x0
    pts[:, 1] = pts[:, 1] * fv + y0
    if barra.fechada:
        pts = np.vstack([pts, pts[0]])
    ax.plot(pts[:, 0], pts[:, 1], color=cor, lw=2.0, zorder=5,
            solid_capstyle="round")

    # a lista de segmentos já vem sem medidas repetidas, de `montar_explodida`
    for (a, b, comp) in barra.segmentos:
        if comp < 8.0:          # gancho curto: a cota não caberia legível
            continue
        ax_, ay = a[0] + x0, a[1] * fv + y0
        bx, by = b[0] + x0, b[1] * fv + y0
        mx, my = (ax_ + bx) / 2.0, (ay + by) / 2.0
        nx, ny = geometria.direcao_cota(barra, a, b)
        ax.annotate(f"{comp:.0f}", (mx, my), textcoords="offset points",
                    xytext=(nx * 9.0, ny * 9.0),
                    ha="left" if nx > 0.1 else ("right" if nx < -0.1
                                                else "center"),
                    va="center", fontsize=6.5, color=estilo.CINZA_MEDIO,
                    zorder=6)

    # cota de raio das dobras: seta do centro do arco até o arco, com "R" --
    # é a dimensão que a bancada usa para escolher o pino
    for (centro, meio, raio) in barra.raios:
        cx, cy = centro[0] + x0, centro[1] * fv + y0
        mx, my = meio[0] + x0, meio[1] * fv + y0
        ax.annotate(f"R {raio:.1f}", (mx, my), xytext=(cx, cy),
                    textcoords="data", ha="center", va="center",
                    fontsize=6.5, color=estilo.CINZA_MEDIO, zorder=7,
                    arrowprops={"arrowstyle": "->", "lw": 0.5,
                                "color": estilo.CINZA_MEDIO,
                                "shrinkA": 0.0, "shrinkB": 0.0})

    # traspasses: só a cota entre as extremidades das duas barras. Desenhar a
    # peça sobreposta confundia -- parecia uma barra a mais no arranjo
    for (a, b, l0t, rotulo) in barra.emendas:
        ax_, bx = a[0] + x0, b[0] + x0
        y_barra = a[1] * fv + y0
        y_cota = y_barra - 9.0
        for x_marca in (ax_, bx):
            ax.plot([x_marca, x_marca], [y_cota - 2.0, y_barra],
                    color=estilo.CINZA_MEDIO, lw=0.5, zorder=6)
        _cotar(ax, ax_, bx, y_cota, rotulo, cor=estilo.CINZA, acima=False)

    # cota de locação: distância do eixo de apoio de referência
    if barra.referencia is not None:
        x_ref, nome, dist = barra.referencia
        y_cota = y0 + barra.altura * fv + 13.0
        if abs(dist) > 8.0:
            _cotar(ax, x_ref, x0, y_cota, f"{nome} + {abs(dist):.0f}",
                   cor=estilo.CINZA_MEDIO)
        else:
            ax.annotate(f"no eixo de {nome}", (x0, y_cota),
                        textcoords="offset points", xytext=(3, 0),
                        ha="left", va="center", fontsize=6,
                        color=estilo.CINZA_MEDIO, zorder=6)

    # no contorno fechado (estribo) a cota do lado de baixo já ocupa o espaço
    # imediatamente abaixo da barra; o rótulo desce mais para não encostar
    recuo = 34.0 if barra.fechada else 21.0
    ax.text(x0 + barra.largura / 2.0, y0 - recuo, barra.rotulo,
            ha="center", va="top", fontsize=7, color=cor, zorder=6)


def _cotar(ax, xa: float, xb: float, y: float, texto: str,
           cor: str = estilo.CINZA, acima: bool = True) -> None:
    """Linha de cota horizontal com setas nas pontas e o valor no meio."""
    if abs(xb - xa) < 1e-6:
        return
    ax.annotate("", xy=(xa, y), xytext=(xb, y),
                arrowprops=dict(arrowstyle="<->", color=cor, lw=0.6,
                                shrinkA=0, shrinkB=0), zorder=6)
    ax.text((xa + xb) / 2.0, y + (2.0 if acima else -2.0), texto,
            ha="center", va="bottom" if acima else "top", fontsize=6,
            color=cor, zorder=6)


def figura_secoes(res: ResultadoViga, posicoes_m=None) -> Figure:
    """Seções transversais nas abscissas pedidas (em metros).

    ``posicoes_m`` aceita uma lista de abscissas ou de pares
    ``(x, descrição)``, como sai da lista de seções da interface.
    """
    estilo.aplicar_estilo()
    pedidas = normalizar_secoes(res, posicoes_m)
    secoes = [geometria.montar_secao(res, x, f"{nome}  (x = {x:.2f} m)")
              for x, nome in pedidas]
    n = max(len(secoes), 1)
    fig = Figure(figsize=(min(3.1 * n, 14.0), 4.4))
    axes = fig.subplots(1, n, squeeze=False)[0]

    for ax, sec in zip(axes, secoes):
        _desenhar_polilinha(ax, sec.contorno, 1.0, facecolor=estilo.CONCRETO,
                            edgecolor=estilo.CINZA, lw=1.2, zorder=1)
        _desenhar_polilinha(ax, sec.estribo, 1.0, facecolor="none",
                            edgecolor=estilo.VERDE, lw=1.4, zorder=2)
        for c in sec.barras:
            cor = CORES.get(c.camada, estilo.VERMELHO)
            ax.add_patch(Circle(c.centro, max(c.raio, 0.28), facecolor=cor,
                                edgecolor=cor, zorder=3))
        for t in sec.textos:
            # a âncora do texto era ignorada e tudo saía centrado: o rótulo
            # lateral da camada interna acabava por cima das barras
            ax.text(t.posicao[0], t.posicao[1], t.texto, fontsize=7,
                    ha=t.ancora if t.ancora in ("left", "right") else "center",
                    va="center", color=estilo.CINZA, zorder=4)
        meia = max(sec.largura, sec.altura) * 0.75
        cx = sec.largura / 2.0
        ax.set_xlim(cx - meia, cx + meia)
        ax.set_ylim(-14, sec.altura + 12)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(sec.nome, fontsize=9)
    fig.tight_layout()
    return fig


def secoes_sugeridas_nomeadas(res: ResultadoViga) -> list[tuple[float, str]]:
    """Seções naturais com a descrição da região: meio dos vãos e apoios."""
    nomes: dict[float, str] = {}
    for r in res.regioes:
        x = round((r.x_ini + r.x_fim) / 2.0 if (r.tipo == "vao"
                                               and r.construtiva) else r.x, 3)
        nomes.setdefault(x, r.nome)
    if not nomes:
        nomes = {round(res.viga.comprimento / 2.0, 3): "Meio do vão"}
    return [(x, nomes[x]) for x in sorted(nomes)]


def secoes_sugeridas(res: ResultadoViga) -> list[float]:
    """Abscissas naturais para as seções: meio de cada vão e cada apoio."""
    return [x for x, _ in secoes_sugeridas_nomeadas(res)]


def normalizar_secoes(res: ResultadoViga, secoes) -> list[tuple[float, str]]:
    """Uniformiza a lista de seções em pares ``(x em m, descrição)``.

    Aceita ``None`` (usa as sugeridas), uma lista de abscissas ou uma lista de
    pares -- é o que permite a lista editável da interface levar a descrição
    escrita pelo usuário até o croqui, o DXF e a memória de cálculo.
    """
    if not secoes:
        return secoes_sugeridas_nomeadas(res)
    saida: list[tuple[float, str]] = []
    for i, item in enumerate(secoes):
        if isinstance(item, (tuple, list)):
            x, nome = float(item[0]), str(item[1] or "").strip()
        else:
            x, nome = float(item), ""
        saida.append((x, nome or f"Seção {i + 1}"))
    return saida
