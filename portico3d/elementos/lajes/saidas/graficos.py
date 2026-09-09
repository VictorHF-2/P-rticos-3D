# -*- coding: utf-8 -*-
"""
graficos.py
Figuras do pavimento em matplotlib: planta de formas, mapa de momentos,
charneiras plásticas com as reações de apoio, flechas e armaduras.

A planta é o desenho que organiza tudo. Nela cada laje aparece com o nome, a
espessura, os vãos e o **símbolo de vinculação de cada bordo** -- e é esse
símbolo que faz o desenho valer: a vinculação é a entrada que mais muda o
resultado e a que é mais fácil de errar lançando, então ela precisa estar
visível, e não escondida numa tabela.

Convenção dos símbolos, a mesma dos desenhos de laje:

    engastado ... hachura dupla junto ao bordo
    apoiado ..... linha simples
    livre ....... linha tracejada
"""

from __future__ import annotations

import math
import zlib

import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from ..core.esforcos import BORDOS_DA_DIRECAO
from . import estilo

estilo.aplicar_estilo()

#: Cores por natureza de armadura, a mesma convenção em toda a saída.
COR_POSITIVA = estilo.VERMELHO
COR_NEGATIVA = estilo.AZUL
COR_DISTRIBUICAO = estilo.VERDE
COR_CONTORNO = estilo.LARANJA

#: Peso de cada vínculo na partição das charneiras (ver core.reacoes).
PESO_VINCULO = {"livre": 0.0, "apoiado": 1.0, "engastado": math.sqrt(3.0)}


def _dimensoes(res) -> tuple[float, float, float]:
    """Largura, altura e escala boa para a figura do pavimento."""
    x0, y0, x1, y1 = res.contorno()
    larg, alt = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    lado = max(larg, alt)
    escala = min(11.0 / lado, 1.6)
    return larg, alt, escala


def _preparar(res, titulo: str, margem: float = 1.1):
    """Cria a figura e o eixo já no aspecto e nos limites do pavimento."""
    larg, alt, escala = _dimensoes(res)
    fig = Figure(figsize=(max(larg * escala, 6.0) + 1.6,
                          max(alt * escala, 4.0) + 1.8))
    ax = fig.add_subplot(111)
    x0, y0, x1, y1 = res.contorno()
    ax.set_xlim(x0 - margem, x1 + margem)
    ax.set_ylim(y0 - margem, y1 + margem)
    ax.set_aspect("equal")
    ax.set_title(titulo)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.grid(True, alpha=0.25)
    return fig, ax


def _simbolo_bordo(ax, laje, bordo: int) -> None:
    """Desenha o símbolo de vinculação do bordo."""
    x0, y0, x1, y1 = laje.segmento_do_bordo(bordo)
    b = laje.bordos[bordo - 1]
    vertical = abs(x1 - x0) < 1e-9
    # para dentro da laje
    cx, cy = (laje.retangulo[0] + laje.retangulo[2]) / 2.0, \
             (laje.retangulo[1] + laje.retangulo[3]) / 2.0
    if vertical:
        dentro = 1.0 if cx > x0 else -1.0
        nx, ny = dentro, 0.0
    else:
        dentro = 1.0 if cy > y0 else -1.0
        nx, ny = 0.0, dentro

    if b.vinculo == "livre":
        ax.plot([x0, x1], [y0, y1], color=estilo.CINZA, lw=1.4, ls=(0, (4, 3)),
                zorder=5)
        return
    ax.plot([x0, x1], [y0, y1], color=estilo.CINZA, lw=1.6, zorder=5)
    if b.vinculo != "engastado":
        return
    # hachura do engaste: tracinhos curtos para dentro
    n = max(int(math.hypot(x1 - x0, y1 - y0) / 0.22), 3)
    d = 0.11
    for k in range(n + 1):
        t = k / n
        px, py = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        ax.plot([px, px + nx * d], [py, py + ny * d], color=estilo.AZUL,
                lw=0.7, zorder=5)


def centro_faixa_pos(pos) -> float:
    """Onde, dentro da faixa de repetição, o esquemático desenha a barra
    representativa de uma posição -- não é sempre o meio.

    Duas lajes vizinhas empilhadas costumam ter a mesma faixa (a mesma
    largura, no mesmo lugar): se as duas desenhassem a barra exatamente no
    meio, ela cairia no mesmo ponto e a figura mostraria uma barra só
    atravessando as duas, em vez de duas armaduras independentes. O
    deslocamento depende do **nome da laje**, não da posição em si, para
    que vão a e vão b da mesma laje não precisem se desencontrar -- só
    lajes diferentes precisam.
    """
    f0, f1 = pos.faixa_inicio, pos.faixa_fim
    # crc32 (e não hash() nativo, que a randomização de string do Python
    # muda a cada processo) espalha nomes parecidos -- "L1" e "L2" não
    # podem sair quase no mesmo lugar, e uma soma de caracteres faz isso
    digest = zlib.crc32(pos.laje.encode("utf-8"))
    fracao = 0.32 + 0.36 * (digest % 1000) / 1000.0
    return f0 + (f1 - f0) * fracao


def _vigas(ax, laje) -> None:
    """Desenha a faixa de viga que sustenta cada bordo com apoio real.

    A viga fica sempre **centrada** na linha do bordo, com ``t/2`` para
    dentro da laje e ``t/2`` para fora -- é assim tanto numa borda comum
    entre duas lajes (onde as duas ocupam ``t/2`` cada, e
    :meth:`~lajes.core.modelo.Pavimento.aplicar_continuidades` sincroniza a
    largura dos dois lados) quanto num apoio de verdade sem laje vizinha: a
    viga fica meio embutida sob a laje e meio para fora dela, do jeito que
    ela é construída de fato, e não encostada só por fora. Só o bordo livre
    fica sem viga.
    """
    for bordo in (1, 2, 3, 4):
        b = laje.bordos[bordo - 1]
        if b.vinculo == "livre":
            continue
        bx0, by0, bx1, by1 = laje.segmento_do_bordo(bordo)
        t = b.t / 100.0
        if t <= 0.0:
            continue
        vertical = abs(bx1 - bx0) < 1e-9
        if vertical:
            canto = (bx0 - t / 2.0, by0)
            largura, altura = t, by1 - by0
        else:
            canto = (bx0, by0 - t / 2.0)
            largura, altura = bx1 - bx0, t
        ax.add_patch(Rectangle(canto, largura, altura,
                               facecolor=estilo.CINZA_CLARO,
                               edgecolor=estilo.CINZA, lw=0.6, hatch="////",
                               alpha=0.9, zorder=1.2))


def _rotulo_laje(ax, laje, esf=None, extra: str = "") -> None:
    x0, y0, x1, y1 = laje.retangulo
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    texto = f"{laje.nome}\nh = {laje.h:g} cm"
    if esf is not None:
        cls = esf.classificacao
        if cls.em_cruz:
            texto += f"\ncruz — caso {cls.caso}"
        else:
            texto += f"\n1 direção ({cls.direcao})"
    if extra:
        texto += f"\n{extra}"
    ax.text(cx, cy, texto, ha="center", va="center", fontsize=8.5,
            color=estilo.AZUL, zorder=8,
            bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                      edgecolor=estilo.AZUL_CLARO, alpha=0.9, lw=0.7))


def _cotas(ax, laje) -> None:
    """Cota os dois vãos livres da laje, **por dentro** do retângulo.

    Por dentro, e não por fora, porque num pavimento as lajes se encostam:
    a cota lançada para fora de uma cai dentro da vizinha e as duas se
    embaralham. Dentro, cada cota fica na laje a que se refere.
    """
    x0, y0, x1, y1 = laje.retangulo
    recuo = min(0.26, (y1 - y0) / 8.0, (x1 - x0) / 8.0)
    ax.annotate("", xy=(x0, y0 + recuo), xytext=(x1, y0 + recuo),
                arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                lw=0.7, shrinkA=0, shrinkB=0))
    ax.text((x0 + x1) / 2.0, y0 + recuo + 0.05, f"{x1 - x0:.2f}",
            ha="center", va="bottom", fontsize=7.5, color=estilo.CINZA)
    ax.annotate("", xy=(x0 + recuo, y0), xytext=(x0 + recuo, y1),
                arrowprops=dict(arrowstyle="<->", color=estilo.CINZA,
                                lw=0.7, shrinkA=0, shrinkB=0))
    ax.text(x0 + recuo + 0.05, (y0 + y1) / 2.0, f"{y1 - y0:.2f}", ha="left",
            va="center", fontsize=7.5, color=estilo.CINZA, rotation=90)


def _legenda(fig, ax, itens) -> None:
    """Põe a legenda fora do eixo e reserva a faixa dela na figura."""
    ax.legend(handles=itens, loc="upper left", bbox_to_anchor=(1.02, 1.0),
              fontsize=8, borderaxespad=0.0)
    fig.tight_layout(rect=(0.0, 0.0, 0.82, 1.0))


# ---------------------------------------------------------------------------
# Planta de formas
# ---------------------------------------------------------------------------

def figura_planta(res) -> Figure:
    """Planta do pavimento com vinculação, espessura e vãos."""
    fig, ax = _preparar(res, f"Planta do pavimento — "
                             f"{res.pavimento.nome}")
    for rl in res.lajes:
        laje = rl.laje
        x0, y0, x1, y1 = laje.retangulo
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               facecolor=estilo.CONCRETO, edgecolor="none",
                               alpha=0.65, zorder=1))
        for bordo in (1, 2, 3, 4):
            _simbolo_bordo(ax, laje, bordo)
            # número do bordo, por dentro
            bx0, by0, bx1, by1 = laje.segmento_do_bordo(bordo)
            mx, my = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            dx, dy = (cx - mx), (cy - my)
            norma = math.hypot(dx, dy) or 1.0
            ax.text(mx + dx / norma * 0.30, my + dy / norma * 0.30,
                    str(bordo), ha="center", va="center", fontsize=7,
                    color=estilo.CINZA_MEDIO, zorder=7)
        _rotulo_laje(ax, laje, rl.esforcos,
                     f"p = {rl.esforcos.g + rl.esforcos.q:.2f} kN/m²")
        _cotas(ax, laje)

    from matplotlib.lines import Line2D
    _legenda(fig, ax, [
        Line2D([], [], color=estilo.CINZA, lw=1.6, label="bordo apoiado"),
        Line2D([], [], color=estilo.AZUL, lw=1.6, label="bordo engastado"),
        Line2D([], [], color=estilo.CINZA, lw=1.4, ls=(0, (4, 3)),
               label="bordo livre")])
    return fig


class _Previa:
    """Adaptador que faz um ``Pavimento`` passar por resultado na planta.

    A pré-visualização da entrada precisa da planta antes de haver cálculo.
    Em vez de duplicar o desenho, este adaptador expõe do pavimento só o que
    :func:`figura_planta` consome: as lajes e o contorno.
    """

    class _Item:
        def __init__(self, laje) -> None:
            self.laje = laje
            self.nome = laje.nome
            self.esforcos = None

    def __init__(self, pav) -> None:
        self.pavimento = pav
        self.lajes = [self._Item(l) for l in pav.lajes]

    def contorno(self) -> tuple[float, float, float, float]:
        if not self.lajes:
            return (0.0, 0.0, 1.0, 1.0)
        cantos = [i.laje.retangulo for i in self.lajes]
        return (min(c[0] for c in cantos), min(c[1] for c in cantos),
                max(c[2] for c in cantos), max(c[3] for c in cantos))


def figura_planta_simples(pav, mostrar_vigas: bool = False) -> Figure:
    """Planta do pavimento a partir só dos dados de entrada.

    Serve à pré-visualização da tela de entrada: mostra a posição, a
    espessura, os vãos e a vinculação de cada laje antes de qualquer cálculo,
    que é justamente quando o erro de lançamento é mais barato de corrigir.

    Com ``mostrar_vigas``, desenha também a faixa de viga de cada bordo com
    apoio real (ver :func:`_vigas`) -- útil na aba de vinculação, onde é a
    largura do apoio que está sendo lançada.
    """
    previa = _Previa(pav)
    fig, ax = _preparar(previa, f"Planta lançada — {pav.nome}")
    for item in previa.lajes:
        laje = item.laje
        x0, y0, x1, y1 = laje.retangulo
        if mostrar_vigas:
            _vigas(ax, laje)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               facecolor=estilo.CONCRETO, edgecolor="none",
                               alpha=0.65, zorder=1))
        for bordo in (1, 2, 3, 4):
            _simbolo_bordo(ax, laje, bordo)
        _rotulo_laje(ax, laje, None,
                     f"{laje.a:g} x {laje.b:g} m\n"
                     f"g = {laje.g_total:.2f} / q = {laje.variavel:.2f} kN/m²")
        _cotas(ax, laje)
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    itens = [
        Line2D([], [], color=estilo.CINZA, lw=1.6, label="bordo apoiado"),
        Line2D([], [], color=estilo.AZUL, lw=1.6, label="bordo engastado"),
        Line2D([], [], color=estilo.CINZA, lw=1.4, ls=(0, (4, 3)),
               label="bordo livre")]
    if mostrar_vigas:
        itens.append(Patch(facecolor=estilo.CINZA_CLARO,
                           edgecolor=estilo.CINZA, hatch="////",
                           label="viga de apoio"))
    _legenda(fig, ax, itens)
    return fig


# ---------------------------------------------------------------------------
# Momentos
# ---------------------------------------------------------------------------

def _curva_diagrama(u, v0: float, vp: float, v1: float):
    """Duas parábolas mansas, uma por meio-vão, com derivada nula no pico.

    Um único polinômio do segundo grau pelos três pontos (0, v0), (0.5, vp) e
    (1, v1) pode abrir um lóbulo espúrio quando o pico central está perto de
    um dos extremos -- é exatamente o caso do balanço, em que o momento de
    vão é zero e a curva por um polinômio único bojava para o lado errado
    entre o apoio livre e o meio. Duas parábolas com tangente horizontal no
    pico -- o ponto de cortante nulo de um vão real -- ficam monótonas em
    cada metade, passam pelos três pontos e se encontram sem quina.
    """
    v = np.empty_like(u)
    esquerda = u <= 0.5
    t = np.clip(u[esquerda] / 0.5, 0.0, 1.0)
    v[esquerda] = v0 + (vp - v0) * t * (2.0 - t)
    t = np.clip((u[~esquerda] - 0.5) / 0.5, 0.0, 1.0)
    v[~esquerda] = vp + (v1 - vp) * t * t
    return v


def _valores_de_borda(laje, esf, comp, direcao: str) -> tuple[float, float]:
    """Momento com sinal nas duas extremidades da direção, para o diagrama.

    Positivo no vão, negativo no engaste -- convenção de diagrama de
    esforços. Bordo apoiado ou livre não tem momento fletor de projeto ali, e
    entra como zero. No bordo engastado, usa o momento **compatibilizado**
    quando a borda é comum com outra laje: é o mesmo valor que a laje vizinha
    usa na extremidade dela, e é isso que deixa as duas curvas se encostarem
    sem degrau onde a geometria alinhar.
    """
    saida = []
    for bordo in BORDOS_DA_DIRECAO[direcao]:
        b = laje.bordos[bordo - 1]
        if b.vinculo != "engastado":
            saida.append(0.0)
            continue
        adotado = comp.momento_do_bordo(laje.nome, bordo) if comp else None
        m = adotado if adotado is not None else esf.m_neg.get(bordo, 0.0)
        saida.append(-m)
    return saida[0], saida[1]


def _desenhar_diagrama(ax, laje, direcao: str, v0: float, vp: float,
                       v1: float, escala: float) -> None:
    """Diagrama esquemático de momento ao longo da direção, como uma faixa
    que atravessa o centro da laje -- vermelho onde é o vão (positivo), azul
    onde é o engaste (negativo), a mesma convenção dos rótulos de texto.

    A faixa corre pelo eixo global da direção (X para quem tem ``b`` nesse
    eixo, Y para o outro): é a mesma convenção de ``direcao_global`` usada no
    detalhamento, para que a curva realmente atravesse a laje de bordo a
    bordo naquela direção.
    """
    if escala <= 0.0:
        return
    x0, y0, x1, y1 = laje.retangulo
    eixo = laje.direcao_global(direcao)
    u = np.linspace(0.0, 1.0, 121)
    v = _curva_diagrama(u, v0, vp, v1)
    pos = np.where(v >= 0.0, v, np.nan)
    neg = np.where(v < 0.0, v, np.nan)
    if eixo == "X":
        cy = (y0 + y1) / 2.0
        xs = x0 + u * (x1 - x0)
        ax.plot([x0, x1], [cy, cy], color=estilo.CINZA, lw=0.5, alpha=0.35,
                zorder=4)
        for valores, cor in ((pos, COR_POSITIVA), (neg, COR_NEGATIVA)):
            ys = cy + valores * escala
            ax.plot(xs, ys, color=cor, lw=1.3, zorder=6)
            ax.fill_between(xs, cy, ys, color=cor, alpha=0.14, zorder=4)
    else:
        cx = (x0 + x1) / 2.0
        ys = y0 + u * (y1 - y0)
        ax.plot([cx, cx], [y0, y1], color=estilo.CINZA, lw=0.5, alpha=0.35,
                zorder=4)
        for valores, cor in ((pos, COR_POSITIVA), (neg, COR_NEGATIVA)):
            xs = cx + valores * escala
            ax.plot(xs, ys, color=cor, lw=1.3, zorder=6)
            ax.fill_betweenx(ys, cx, xs, color=cor, alpha=0.14, zorder=4)


def figura_momentos(res) -> Figure:
    """Mapa dos momentos de cálculo, com o diagrama esquemático de cada
    direção sobreposto à planta -- vermelho no vão, azul no engaste."""
    fig, ax = _preparar(res, "Momentos de cálculo (kN·m/m) — regime "
                             "rígido-plástico no ELU")
    comp = res.compatibilizacao

    # Uma escala só para o pavimento inteiro -- é o que faz as curvas de duas
    # lajes vizinhas terem a mesma altura por kN·m/m e, onde a borda comum
    # usa o momento compatibilizado (mesmo valor dos dois lados) e as duas
    # faixas centrais coincidem em y ou x, se encostarem sem degrau.
    diagramas: dict[str, list[tuple[str, float, float, float]]] = {}
    todos_valores: list[float] = []
    for rl in res.lajes:
        laje, esf = rl.laje, rl.esforcos
        direcoes = ("a", "b") if esf.classificacao.em_cruz             else (esf.classificacao.direcao,)
        entradas = []
        for direcao in direcoes:
            v0, v1 = _valores_de_borda(laje, esf, comp, direcao)
            vp = esf.momento_da_direcao(direcao)
            entradas.append((direcao, v0, vp, v1))
            todos_valores.extend((abs(v0), abs(vp), abs(v1)))
        diagramas[rl.nome] = entradas
    maior_momento = max(todos_valores, default=0.0)
    menor_vao = min((rl.laje.a for rl in res.lajes), default=1.0)
    # o pico maior ocupa, no máximo, 35 % do menor vão do pavimento -- amplo
    # o bastante para ler a forma, contido o bastante para não invadir a
    # laje vizinha na direção perpendicular
    escala = 0.35 * menor_vao / maior_momento if maior_momento > 1e-9 else 0.0

    for rl in res.lajes:
        laje, esf = rl.laje, rl.esforcos
        x0, y0, x1, y1 = laje.retangulo
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               facecolor=estilo.CONCRETO, edgecolor=estilo.CINZA,
                               lw=0.8, alpha=0.5, zorder=1))
        for direcao, v0, vp, v1 in diagramas[rl.nome]:
            _desenhar_diagrama(ax, laje, direcao, v0, vp, v1, escala)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if esf.classificacao.em_cruz:
            texto = (f"{laje.nome}\n"
                     f"m$_a$ = {esf.ma:.2f}\nm$_b$ = {esf.mb:.2f}")
        else:
            m = esf.momento_da_direcao(esf.classificacao.direcao)
            texto = f"{laje.nome}\nm = {m:.2f}"
        ax.text(cx, cy, texto, ha="center", va="center", fontsize=8.5,
                color=COR_POSITIVA, zorder=8,
                bbox=dict(boxstyle="round,pad=0.30", facecolor="white",
                          edgecolor=COR_POSITIVA, alpha=0.92, lw=0.7))
        for bordo in (1, 2, 3, 4):
            m = esf.m_neg.get(bordo)
            if not m:
                continue
            adotado = comp.momento_do_bordo(laje.nome, bordo) if comp else None
            bx0, by0, bx1, by1 = laje.segmento_do_bordo(bordo)
            mx, my = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            dx, dy = (cx - mx), (cy - my)
            norma = math.hypot(dx, dy) or 1.0
            rotulo = f"{m:.2f}"
            if adotado is not None and abs(adotado - m) > 0.005:
                rotulo = f"{m:.2f}→{adotado:.2f}"
            ax.text(mx + dx / norma * 0.55, my + dy / norma * 0.55, rotulo,
                    ha="center", va="center", fontsize=7.5, color=COR_NEGATIVA,
                    zorder=8,
                    bbox=dict(boxstyle="round,pad=0.20", facecolor="white",
                              edgecolor=COR_NEGATIVA, alpha=0.92, lw=0.6))
    from matplotlib.lines import Line2D
    _legenda(fig, ax, [
        Line2D([], [], color=COR_POSITIVA, lw=2, label="momento no vão"),
        Line2D([], [], color=COR_NEGATIVA, lw=2,
               label="momento no engaste\n(seta = compatibilizado)"),
        Line2D([], [], color=estilo.CINZA, lw=0.7,
               label="diagrama esquemático nas\ndireções a e b — escala "
                     "única\ndo pavimento; contínuo entre\nlajes vizinhas "
                     "onde a planta\nalinhar")])
    return fig


# ---------------------------------------------------------------------------
# Charneiras e reações
# ---------------------------------------------------------------------------

def _malha_charneiras(laje, n: int = 240):
    """Campo de índices do bordo que ganha cada ponto da laje.

    A malha usa os **vãos livres**, e não os efetivos: ela é para desenhar
    sobre o retângulo da planta, que é o dos vãos livres. As reações, que são
    número e não desenho, saem do vão efetivo em ``core.reacoes``.
    """
    pesos = [PESO_VINCULO[b.vinculo] for b in laje.bordos]
    a, b = laje.a, laje.b
    u = (np.arange(n) + 0.5) * b / n          # ao longo do maior vão
    v = (np.arange(n) + 0.5) * a / n
    U, V = np.meshgrid(u, v, indexing="ij")
    dist = [U, V, b - U, a - V]               # bordos 1, 2, 3, 4
    razoes = []
    for k in range(4):
        w = pesos[k]
        razoes.append(dist[k] / w if w > 0 else np.full_like(U, np.inf))
    quem = np.argmin(np.stack(razoes), axis=0).astype(float)
    return U, V, quem


def figura_reacoes(res) -> Figure:
    """Charneiras plásticas de cada laje e as reações que elas produzem."""
    fig, ax = _preparar(res, "Charneiras plásticas (45°/60°/90°) e reações "
                             "de apoio (kN/m, características)")
    for rl in res.lajes:
        laje = rl.laje
        x0, y0, x1, y1 = laje.retangulo
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               facecolor=estilo.CONCRETO, edgecolor=estilo.CINZA,
                               lw=0.8, alpha=0.45, zorder=1))
        U, V, quem = _malha_charneiras(laje)
        # local -> global: u corre no maior vão
        if laje.orientacao == "X":
            X, Y = x0 + U, y0 + V
        else:
            X, Y = x0 + V, y0 + U
        try:
            ax.contour(X, Y, quem, levels=[0.5, 1.5, 2.5],
                       colors=[estilo.LARANJA], linewidths=0.9, zorder=4)
        except (ValueError, TypeError):
            pass
        _rotulo_laje(ax, laje)
        if rl.reacoes is None:
            continue
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        for r in rl.reacoes.bordos:
            if r.vinculo == "livre":
                continue
            bx0, by0, bx1, by1 = laje.segmento_do_bordo(r.bordo)
            mx, my = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            dx, dy = (cx - mx), (cy - my)
            norma = math.hypot(dx, dy) or 1.0
            # rótulo por dentro da laje: por fora ele encosta no da vizinha
            ax.text(mx + dx / norma * 0.42, my + dy / norma * 0.42,
                    f"{r.v_k:.1f}", ha="center", va="center", fontsize=7.5,
                    color=estilo.VERDE, zorder=9,
                    bbox=dict(boxstyle="round,pad=0.18", facecolor="white",
                              edgecolor=estilo.VERDE, alpha=0.92, lw=0.6))
    from matplotlib.lines import Line2D
    _legenda(fig, ax, [
        Line2D([], [], color=estilo.LARANJA, lw=1.2, label="charneira"),
        Line2D([], [], color=estilo.VERDE, lw=2,
               label="reação no bordo (kN/m)")])
    return fig


# ---------------------------------------------------------------------------
# Serviço e armaduras
# ---------------------------------------------------------------------------

def figura_flechas(res) -> Figure:
    """Flecha de longa duração de cada laje contra o limite."""
    fig = Figure(figsize=(max(7.0, 1.1 * len(res.lajes) + 4.0), 4.2))
    ax = fig.add_subplot(111)
    nomes = [rl.nome for rl in res.lajes]
    flechas = [rl.els.f_diferida if rl.els else 0.0 for rl in res.lajes]
    limites = [rl.els.f_admissivel if rl.els else 0.0 for rl in res.lajes]
    x = np.arange(len(nomes))
    cores = [estilo.VERMELHO if f > lim + 1e-9 else estilo.AZUL_MEDIO
             for f, lim in zip(flechas, limites)]
    ax.bar(x - 0.19, flechas, 0.36, color=cores, label="f(t=∞)")
    ax.bar(x + 0.19, limites, 0.36, color=estilo.CINZA_CLARO,
           edgecolor=estilo.CINZA, label="limite (Tabela 13.3)")
    for i, (f, lim) in enumerate(zip(flechas, limites)):
        ax.text(i - 0.19, f, f"{f:.2f}", ha="center", va="bottom",
                fontsize=7.5)
        ax.text(i + 0.19, lim, f"{lim:.2f}", ha="center", va="bottom",
                fontsize=7.5, color=estilo.CINZA)
    ax.set_xticks(x)
    ax.set_xticklabels(nomes)
    ax.set_ylabel("flecha (cm)")
    ax.set_title("Deformação — flecha de longa duração contra o limite")
    ax.legend()
    fig.tight_layout()
    return fig


def figura_armaduras(res) -> Figure:
    """Armadura necessária × adotada, seção por seção."""
    rotulos: list[str] = []
    necessaria: list[float] = []
    adotada: list[float] = []
    for rl in res.lajes:
        for p in rl.posicoes:
            rotulos.append(f"{rl.nome}\nN{p.numero}")
            necessaria.append(p.As_necessaria)
            adotada.append(p.As_efetiva)
    for p in res.posicoes_continuidade:
        rotulos.append(f"cont.\nN{p.numero}")
        necessaria.append(p.As_necessaria)
        adotada.append(p.As_efetiva)

    fig = Figure(figsize=(max(8.0, 0.52 * len(rotulos) + 3.0), 4.6))
    ax = fig.add_subplot(111)
    if not rotulos:
        ax.text(0.5, 0.5, "sem posições de armadura", ha="center",
                va="center", transform=ax.transAxes)
        return fig
    x = np.arange(len(rotulos))
    ax.bar(x - 0.19, necessaria, 0.36, color=estilo.CINZA_MEDIO,
           label="necessária")
    ax.bar(x + 0.19, adotada, 0.36, color=estilo.AZUL_MEDIO, label="adotada")
    ax.set_xticks(x)
    ax.set_xticklabels(rotulos, fontsize=7)
    ax.set_ylabel("A$_s$ (cm²/m)")
    ax.set_title("Armadura necessária × adotada")
    ax.legend()
    fig.tight_layout()
    return fig


def figura_cortante(res) -> Figure:
    """VSd × VRd1 em cada bordo verificado (19.4.1)."""
    rotulos, vsd, vrd = [], [], []
    for rl in res.lajes:
        for c in rl.cortantes:
            rotulos.append(c.rotulo.replace(", bordo ", "\nb"))
            vsd.append(c.v_sd)
            vrd.append(c.v_rd1)
    fig = Figure(figsize=(max(8.0, 0.52 * len(rotulos) + 3.0), 4.4))
    ax = fig.add_subplot(111)
    if not rotulos:
        ax.text(0.5, 0.5, "verificação de cortante desligada", ha="center",
                va="center", transform=ax.transAxes)
        return fig
    x = np.arange(len(rotulos))
    cores = [estilo.VERMELHO if s > r + 1e-9 else estilo.AZUL_MEDIO
             for s, r in zip(vsd, vrd)]
    ax.bar(x - 0.19, vsd, 0.36, color=cores, label="V$_{Sd}$")
    ax.bar(x + 0.19, vrd, 0.36, color=estilo.VERDE_CLARO,
           edgecolor=estilo.VERDE, label="V$_{Rd1}$ (19.4.1)")
    ax.set_xticks(x)
    ax.set_xticklabels(rotulos, fontsize=7)
    ax.set_ylabel("kN/m")
    ax.set_title("Força cortante — laje sem armadura transversal (19.4.1)")
    ax.legend()
    fig.tight_layout()
    return fig
