# -*- coding: utf-8 -*-
"""
graficos.py
Diagramas de esforços, deformada e armaduras. Cada função devolve uma
``Figure`` do matplotlib, sem depender do PySide6.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from ..core import alinhamento as al
from ..core import cisalhamento as ci
from ..core import flexao as fl
from ..core.analise import combinar
from ..core.dimensionar import ResultadoViga
from . import estilo

TAMANHO = (11.0, 7.5)


def _marcar_apoios(eixo, res: ResultadoViga, y: float = 0.0) -> None:
    """Desenha os apoios e as linhas verticais dos eixos."""
    viga = res.viga
    for i, (x, ap) in enumerate(zip(viga.x_apoios, viga.apoios)):
        if ap.tipo == "livre":
            continue
        eixo.axvline(x, color=estilo.CINZA_MEDIO, lw=0.7, ls=":", zorder=0)


def _rotular_extremos(eixo, x, y, formato="%.1f", n=1, cor=None,
                      acima=True) -> None:
    """Anota o valor extremo de uma curva."""
    if len(x) == 0:
        return
    i = int(np.argmax(y)) if acima else int(np.argmin(y))
    eixo.annotate(formato % y[i], (x[i], y[i]), textcoords="offset points",
                  xytext=(0, 6 if acima else -12), ha="center", fontsize=8,
                  color=cor or estilo.CINZA, fontweight="bold")


# ---------------------------------------------------------------------------
# Esquema estático
# ---------------------------------------------------------------------------

#: fração da altura de referência ocupada pela faixa da maior carga
FAIXA_MAXIMA = 0.85
#: altura mínima de uma faixa, para que a menor carga ainda se leia
FAIXA_MINIMA = 0.20


def _rect(x, y, w, h, cor, borda=None, lw=0.9, zorder=1, hachura=None,
          alpha=1.0):
    from matplotlib.patches import Rectangle
    return Rectangle((x, y), w, h, facecolor=cor,
                     edgecolor=borda or estilo.CINZA, lw=lw, zorder=zorder,
                     hatch=hachura, alpha=alpha)


def plt_rect(x, y, w, h, cor):
    """Mantida por compatibilidade com quem já a importava."""
    return _rect(x, y, w, h, cor)


def _terreno(ax, x0: float, x1: float, y: float, u: float) -> None:
    """Linha de base hachurada, como o engaste em desenho de estrutura."""
    ax.plot([x0, x1], [y, y], color=estilo.CINZA, lw=1.6, zorder=4,
            solid_capstyle="butt")
    n = max(3, int((x1 - x0) / (0.055 * u * 6.0)) + 1)
    passo = (x1 - x0) / n
    for k in range(n):
        xa = x0 + k * passo
        ax.plot([xa, xa + passo * 0.75], [y, y - 0.16 * u],
                color=estilo.CINZA_MEDIO, lw=0.9, zorder=4)


def _desenhar_apoios(ax, viga, u: float, y_base: float, y_terreno: float
                     ) -> None:
    """Pilares com a largura real e o engaste como parede hachurada."""
    # o esquema tem escala vertical exagerada; abaixo de ~1,5 % do vão o pilar
    # sai como um fio e deixa de se ler como pilar
    minima = 0.015 * max(viga.comprimento, 1.0)
    for i, (x, ap) in enumerate(zip(viga.x_apoios, viga.apoios)):
        if ap.tipo == "livre":
            continue
        larg = max(ap.largura / 100.0, minima)
        if ap.tipo == "engaste":
            # parede hachurada, atravessando a altura da viga: o hachurado é o
            # que distingue o engaste do apoio simples num relance
            lado = -1.0 if i == 0 else 1.0
            ax.add_patch(_rect(x if lado > 0 else x - larg, y_terreno, larg,
                               -y_terreno + 0.35 * u, estilo.CINZA_CLARO,
                               borda=estilo.CINZA, zorder=2, hachura="////"))
            _terreno(ax, x - larg * 1.4, x + larg * 1.4, y_terreno, u)
        else:
            ax.add_patch(_rect(x - larg / 2.0, y_terreno, larg,
                               y_base - y_terreno, estilo.CINZA_CLARO,
                               borda=estilo.CINZA, zorder=2))
            _terreno(ax, x - larg * 1.5, x + larg * 1.5, y_terreno, u)
        ax.plot([x, x], [y_terreno - 0.30 * u, 1.15 * u], color=estilo.AZUL,
                lw=0.7, ls=(0, (7, 3, 1, 3)), zorder=0, alpha=0.55)
        ax.text(x, y_terreno - 0.40 * u, f"P{i + 1}",
                ha="center", va="top", fontsize=8, color=estilo.AZUL,
                fontweight="bold")


def _cotar_vaos(ax, viga, u: float, y: float) -> None:
    """Linha de cotas entre eixos de apoio, abaixo dos pilares."""
    for i, t in enumerate(viga.tramos):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        ax.annotate("", xy=(a, y), xytext=(b, y),
                    arrowprops=dict(arrowstyle="<|-|>", color=estilo.CINZA,
                                    lw=0.8, shrinkA=0, shrinkB=0,
                                    mutation_scale=8))
        for xe in (a, b):
            ax.plot([xe, xe], [y - 0.10 * u, y + 0.10 * u],
                    color=estilo.CINZA, lw=0.8)
        ax.text((a + b) / 2.0, y + 0.08 * u, f"{t.L:g} m", ha="center",
                va="bottom", fontsize=7.5, color=estilo.CINZA)


def _empilhar(faixas: list[tuple[float, float, float]], x0: float, x1: float
              ) -> float:
    """Base de uma nova faixa: acima de toda faixa que a cruze em x.

    É o que separa cargas simultâneas em camadas legíveis, em vez de deixá-las
    desenhadas uma dentro da outra.
    """
    base = 0.0
    for a, b, topo in faixas:
        if x0 < b - 1e-9 and a < x1 - 1e-9:
            base = max(base, topo)
    return base


def figura_esquema(fonte, mostrar_cargas: bool = True,
                   tamanho: tuple[float, float] = (11.0, 3.0),
                   titulo: str = "") -> Figure:
    """Esquema estático da viga: geometria, apoios e carregamentos.

    Aceita tanto um :class:`ResultadoViga` quanto uma :class:`Viga` -- assim a
    mesma figura serve de pré-visualização enquanto o usuário monta os dados,
    antes de existir qualquer cálculo.

    As cargas distribuídas são **empilhadas**: cada trecho carregado ganha uma
    faixa própria, apoiada no topo das faixas que o cruzam. Duas cargas no
    mesmo trecho (permanente e variável, por exemplo) aparecem uma sobre a
    outra, com a soma legível, em vez de uma escondendo a outra.
    """
    estilo.aplicar_estilo()
    viga = fonte.viga if hasattr(fonte, "viga") else fonte
    fig = Figure(figsize=tamanho)
    ax = fig.add_subplot(111)
    # o esquema desenhava todos os tramos com o topo em y = 0, o que supõe
    # alinhamento pelo topo mesmo quando o projeto declara outro; com as bases
    # do alinhamento o degrau da junta aparece como vai ser executado
    trechos = viga.trechos
    bases = [b / 100.0 for b in al.bases_verticais(viga)]
    topos = [b + t.secao.h / 100.0 for b, t in zip(bases, trechos)]
    topo_max = max(topos)
    h_max = topo_max - min(bases)
    u = max(h_max, 0.25)                     # unidade vertical de referência

    # o degrau cai na face do pilar oposta ao trecho de seção maior, como no
    # detalhamento: é esse trecho que se apoia na largura toda do pilar. Na
    # junta interna não há pilar, e o degrau é a própria abscissa da mudança
    ini = {t.k: t.x_ini for t in trechos}
    fim = {t.k: t.x_fim for t in trechos}
    for j in al.juntas(viga):
        fim[j.trecho_esq] = j.x_face
        ini[j.trecho_dir] = j.x_face

    # -- viga ---------------------------------------------------------------
    for i, t in enumerate(trechos):
        a = ini[i]
        b = fim[i]
        h = t.secao.h / 100.0
        y0 = bases[i] - topo_max             # fundo deste trecho
        ax.add_patch(_rect(a, y0, b - a, h, estilo.CONCRETO,
                           borda=estilo.CINZA, lw=1.1, zorder=3))
        if t.secao.tipo != "retangular":
            # a mesa aparece como um ressalto, para a seção T se ler -- no
            # topo na T e no fundo na T invertida, que é onde ela está
            hf = t.secao.hf / 100.0
            y_mesa = y0 if t.secao.tipo == "T invertida" else y0 + h - hf
            ax.add_patch(_rect(a, y_mesa, b - a, hf, estilo.CINZA_CLARO,
                               borda=estilo.CINZA, lw=0.8, zorder=4,
                               alpha=0.8))
        ax.text((a + b) / 2.0, y0 + h / 2.0, t.secao.descricao(),
                ha="center", va="center", fontsize=7.5, color=estilo.CINZA,
                zorder=5)

    y_base = min(bases) - topo_max
    y_terreno = y_base - 1.15 * u
    _desenhar_apoios(ax, viga, u, y_base, y_terreno)
    _cotar_vaos(ax, viga, u, y_terreno - 1.45 * u)
    y_min = y_terreno - 1.90 * u

    # -- cargas -------------------------------------------------------------
    distribuidas = viga.todas_distribuidas() if mostrar_cargas else []
    concentradas = viga.concentradas if mostrar_cargas else []
    momentos = viga.momentos if mostrar_cargas else []
    q_max = max([max(abs(c.q1), abs(c.q2)) for c in distribuidas] or [1.0])

    faixas: list[tuple[float, float, float]] = []
    y_topo = 0.0
    # as permanentes primeiro, e as maiores por baixo: a pilha fica estável
    ordem = sorted(distribuidas,
                   key=lambda c: (c.acao != "g",
                                  -max(abs(c.q1), abs(c.q2)), c.x_ini))
    for c in ordem:
        cor = estilo.CINZA if c.acao == "g" else estilo.LARANJA
        preenche = estilo.CINZA_CLARO if c.acao == "g" else estilo.LARANJA_CLARO
        base = _empilhar(faixas, c.x_ini, c.x_fim)
        def alt(q: float) -> float:
            return u * (FAIXA_MINIMA + (FAIXA_MAXIMA - FAIXA_MINIMA)
                        * abs(q) / q_max)
        a1, a2 = alt(c.q1), alt(c.q2)
        ax.fill([c.x_ini, c.x_fim, c.x_fim, c.x_ini],
                [base, base, base + a2, base + a1], facecolor=preenche,
                edgecolor="none", alpha=0.55, zorder=2)
        ax.plot([c.x_ini, c.x_fim], [base + a1, base + a2], color=cor, lw=1.4,
                zorder=3)
        ax.plot([c.x_ini, c.x_fim], [base, base], color=cor, lw=0.9, zorder=3)
        n_setas = int(np.clip(round((c.x_fim - c.x_ini) / 0.45), 3, 26))
        for k in range(n_setas + 1):
            f = k / n_setas
            x = c.x_ini + (c.x_fim - c.x_ini) * f
            ax.annotate("", xy=(x, base + 0.06 * u),
                        xytext=(x, base + a1 + (a2 - a1) * f),
                        arrowprops=dict(arrowstyle="-|>", color=cor, lw=0.7,
                                        shrinkA=0, shrinkB=0,
                                        mutation_scale=6), zorder=3)
        for xe in (c.x_ini, c.x_fim):
            ax.plot([xe, xe], [base, base + (a1 if xe == c.x_ini else a2)],
                    color=cor, lw=1.0, zorder=3)
        rotulo = (f"{c.q1:g}" if c.q1 == c.q2 else f"{c.q1:g} a {c.q2:g}")
        # o rótulo foge da vertical de uma carga concentrada: a seta dela
        # atravessa todas as faixas e cortava o texto ao meio
        vao_c = c.x_fim - c.x_ini
        xr = (c.x_ini + c.x_fim) / 2.0
        for f in (0.5, 0.28, 0.72, 0.14, 0.86):
            xr = c.x_ini + vao_c * f
            if all(abs(p.x - xr) > 0.06 * vao_c for p in concentradas):
                break
        ax.text(xr, base + max(a1, a2) + 0.07 * u, f"{rotulo} kN/m",
                ha="center", va="bottom", fontsize=7.5, color=cor, zorder=6)
        topo = base + max(a1, a2) + 0.52 * u
        faixas.append((c.x_ini, c.x_fim, topo))
        y_topo = max(y_topo, topo)

    # concentradas e momentos ficam acima de toda a pilha, em dois níveis
    y_carga = y_topo + 0.25 * u
    for k, p in enumerate(sorted(concentradas, key=lambda p: p.x)):
        cor = estilo.CINZA if p.acao == "g" else estilo.LARANJA
        y_seta = y_carga + (0.0 if k % 2 == 0 else 0.75 * u)
        ax.annotate("", xy=(p.x, 0.02 * u), xytext=(p.x, y_seta + 0.55 * u),
                    arrowprops=dict(arrowstyle="-|>", color=cor, lw=1.8,
                                    shrinkA=0, shrinkB=0, mutation_scale=13),
                    zorder=6)
        ax.text(p.x, y_seta + 0.62 * u, f"{p.P:g} kN", ha="center",
                va="bottom", fontsize=8, color=cor, fontweight="bold",
                zorder=7)
        y_topo = max(y_topo, y_seta + 1.05 * u)
    # o momento aplicado sai como arco de seta. O arco é traçado ponto a
    # ponto com o raio em x tirado da largura do desenho e o raio em y da
    # unidade vertical: o esquema tem escala distorcida, e um arco de raio
    # único viraria uma elipse achatada
    rx = 0.018 * max(viga.x_fim_fisico - viga.x_inicio_fisico, 1.0)
    for k, mo in enumerate(sorted(momentos, key=lambda m: m.x)):
        cor = estilo.CINZA if mo.acao == "g" else estilo.LARANJA
        yc = y_carga + 0.45 * u + (0.0 if k % 2 == 0 else 0.95 * u)
        ry = 0.40 * u
        sentido = 1.0 if mo.M >= 0 else -1.0
        ang = np.radians(np.linspace(-125.0, 125.0, 60)) * sentido
        ax.plot(mo.x + rx * np.sin(ang), yc + ry * np.cos(ang), color=cor,
                lw=1.6, zorder=6)
        ax.annotate("", xy=(mo.x + rx * np.sin(ang[-1]),
                            yc + ry * np.cos(ang[-1])),
                    xytext=(mo.x + rx * np.sin(ang[-6]),
                            yc + ry * np.cos(ang[-6])),
                    arrowprops=dict(arrowstyle="-|>", color=cor, lw=1.6,
                                    shrinkA=0, shrinkB=0, mutation_scale=13),
                    zorder=6)
        ax.plot([mo.x, mo.x], [0.0, yc - ry], color=cor, lw=0.8, ls=":",
                zorder=5)
        ax.text(mo.x, yc + ry + 0.12 * u, f"{mo.M:g} kN·m", ha="center",
                va="bottom", fontsize=7.5, color=cor, zorder=7)
        y_topo = max(y_topo, yc + ry + 0.55 * u)

    if mostrar_cargas and (distribuidas or concentradas or momentos):
        from matplotlib.lines import Line2D
        chaves = []
        if any(c.acao == "g" for c in distribuidas) or \
                any(p.acao == "g" for p in concentradas):
            chaves.append(Line2D([], [], color=estilo.CINZA, lw=2,
                                 label="permanente (G)"))
        if any(c.acao == "q" for c in distribuidas) or \
                any(p.acao == "q" for p in concentradas):
            chaves.append(Line2D([], [], color=estilo.LARANJA, lw=2,
                                 label="variável (Q)"))
        if chaves:
            # acima do quadro, ao lado do título: em escala real a figura
            # encurta e uma legenda dentro do desenho cobria as cargas
            ax.legend(handles=chaves, loc="lower right",
                      bbox_to_anchor=(1.0, 1.005), ncol=len(chaves),
                      fontsize=7.5, frameon=False, borderpad=0.2,
                      handlelength=1.6, columnspacing=1.4)

    folga = max((viga.x_fim_fisico - viga.x_inicio_fisico) * 0.03, 0.25)
    ax.set_xlim(viga.x_inicio_fisico - folga, viga.x_fim_fisico + folga)
    ax.set_ylim(y_min, max(y_topo + 0.45 * u, 1.2 * u))
    # escala real nos dois eixos: com aspecto livre a viga mantinha a mesma
    # altura aparente qualquer que fosse o vão, e acrescentar um tramo mudava
    # a escala do desenho sem avisar
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for lado in ("top", "right", "left", "bottom"):
        ax.spines[lado].set_visible(False)
    ax.set_title(titulo or f"Esquema estático — {viga.nome}", fontsize=10)
    # com aspecto igual, a altura da figura tem de acompanhar a proporção real
    # do desenho; presa no valor pedido, sobrava faixa em branco acima e abaixo
    # de uma viga longa. ``tamanho`` passa a valer como a largura.
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    razao = (x1 - x0) / max(y1 - y0, 1e-6)
    altura_pol = float(np.clip(tamanho[0] / razao + 0.55, 1.7, 8.5))
    fig.set_size_inches(tamanho[0], altura_pol)
    # o texto é medido em pontos e o desenho, em metros: numa viga longa a
    # figura encurta e as letras passam a ocupar espaço demais. O corpo
    # acompanha a altura da figura, senão os rótulos voltam a se tocar
    k = float(np.clip(altura_pol / 3.6, 0.62, 1.0))
    if k < 0.999:
        for t in ax.texts:
            t.set_fontsize(t.get_fontsize() * k)
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                t.set_fontsize(t.get_fontsize() * k)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Envoltórias de esforços
# ---------------------------------------------------------------------------

def _legenda_acima(ax) -> None:
    """Legenda fora do quadro, entre o título e o diagrama.

    Dentro do quadro ela cobria os rótulos dos valores de projeto: a envoltória
    preenche os dois semiplanos, então não existe canto livre. Fora do quadro o
    diagrama fica inteiro visível, que é o que se lê.
    """
    n = len(ax.get_legend_handles_labels()[1])
    ncol = min(3, n)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=ncol,
              frameon=False, fontsize=7.5, borderaxespad=0.2,
              handlelength=2.4, columnspacing=1.6)
    # o título tem de subir tantas linhas quantas a legenda ocupar, senão a
    # legenda de 4 entradas em 3 colunas sobe uma linha e bate nele
    linhas = -(-n // ncol) if ncol else 1
    ax.set_title(ax.get_title(), pad=12 * linhas + 12)


def patamares_minimos(res: ResultadoViga):
    """Esforços abaixo dos quais a armadura mínima já basta, tramo a tramo.

    Devolve ``(M+, M-, V)`` como vetores na grade da envoltória, constantes em
    cada tramo -- a seção e a altura útil mudam de tramo para tramo, então o
    patamar é uma escada, não uma reta única.

    ``M+`` e ``M-`` são os momentos que a armadura mínima de cada face resiste
    (17.3.5.2.1); ``V`` é o cortante de cálculo que a armadura transversal
    mínima atende (17.4.1.1.1). Abaixo desses valores o diagrama não pede
    armadura acima da mínima -- é a fronteira que diz onde o escalonamento tem
    o que cortar e onde o estribo é o construtivo.
    """
    viga, cfg = res.viga, res.viga.config
    conc, aco = viga.concreto, viga.aco
    x = res.envoltoria.x
    m_pos = np.full_like(x, np.nan)
    m_neg = np.full_like(x, np.nan)
    v_lim = np.full_like(x, np.nan)
    for i, tramo in enumerate(viga.tramos):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        # intervalo semiaberto: no eixo de apoio compartilhado o patamar é o do
        # tramo seguinte, e o degrau cai exatamente sobre o apoio
        ultimo = i == len(viga.tramos) - 1
        m = (x >= a - 1e-9) & ((x <= b + 1e-9) if ultimo else (x < b - 1e-9))
        if not m.any():
            continue
        secao = tramo.secao
        ds = [c.d for c in res.cortantes if a - 1e-9 <= c.x <= b + 1e-9]
        d = float(np.median(ds)) if ds else 0.9 * secao.h
        # a face superior é governada pelas regiões de apoio do tramo
        apoios = [r.d for r in res.regioes
                  if r.tipo == "apoio" and r.indice in (i, i + 1)
                  and not r.construtiva]
        d_sup = float(np.median(apoios)) if apoios else d
        m_pos[m] = fl.momento_minimo(secao, conc, aco, d, "inferior")
        m_neg[m] = -fl.momento_minimo(secao, conc, aco, d_sup, "superior")
        # o patamar do estribo sai do aço **transversal**: a armadura
        # mínima do 17.4.1.1.1 é inversamente proporcional ao fywk dele
        v_lim[m] = ci.V_minimo_projeto(secao, conc, viga.aco_estribo, d,
                                       cfg.modelo_cisalhamento, cfg.theta,
                                       cfg.alpha_estribo)
    return m_pos, m_neg, v_lim


def figura_esforcos(res: ResultadoViga) -> Figure:
    """Envoltórias de momento fletor, força cortante, torçor e a deformada."""
    estilo.aplicar_estilo()
    env = res.envoltoria
    tem_torcao = res.T_diagrama is not None
    n_linhas = 4 if tem_torcao else 3
    fig = Figure(figsize=(TAMANHO[0], TAMANHO[1] * n_linhas / 3.0))
    axes = fig.subplots(n_linhas, 1, sharex=True)

    # -- momentos -----------------------------------------------------------
    ax = axes[0]
    ax.fill_between(env.x, env.M_max, 0, where=env.M_max > 0,
                    color=estilo.AZUL_CLARO, alpha=0.8, lw=0)
    ax.fill_between(env.x, env.M_min, 0, where=env.M_min < 0,
                    color=estilo.LARANJA_CLARO, alpha=0.8, lw=0)
    ax.plot(env.x, env.M_max, color=estilo.AZUL, lw=1.2,
            label="M máximo da envoltória (traciona a face inferior)")
    ax.plot(env.x, env.M_min, color=estilo.LARANJA, lw=1.2,
            label="M mínimo da envoltória (traciona a face superior)")
    ax.axhline(0, color=estilo.CINZA, lw=1.0)
    # abaixo do patamar a armadura mínima já basta (17.3.5.2.1)
    m_pos, m_neg, v_lim = patamares_minimos(res)
    ax.plot(env.x, m_pos, color=estilo.CINZA_MEDIO, lw=1.0, ls=(0, (6, 3)),
            label="M resistido por As,mín (17.3.5.2.1)")
    ax.plot(env.x, m_neg, color=estilo.CINZA_MEDIO, lw=1.0, ls=(0, (6, 3)))
    ax.invert_yaxis()
    ax.set_ylabel("M (kN.m)")
    ax.set_title("Envoltória de momentos fletores — ELU")
    _legenda_acima(ax)
    for mp in res.momentos_projeto:
        ax.annotate(f"{mp.M:.1f}", (mp.x, mp.M), textcoords="offset points",
                    xytext=(0, -10 if mp.M > 0 else 8), ha="center",
                    fontsize=7.5, fontweight="bold",
                    color=estilo.AZUL if mp.M > 0 else estilo.LARANJA)
    _marcar_apoios(ax, res)

    # -- cortantes ----------------------------------------------------------
    ax = axes[1]
    ax.fill_between(env.x, env.V_max, 0, color=estilo.VERDE_CLARO, alpha=0.7,
                    lw=0)
    ax.fill_between(env.x, env.V_min, 0, color=estilo.VERDE_CLARO, alpha=0.7,
                    lw=0)
    ax.plot(env.x, env.V_max, color=estilo.VERDE, lw=1.2,
            label="V máximo da envoltória")
    ax.plot(env.x, env.V_min, color=estilo.VERDE_CLARO, lw=1.6,
            label="V mínimo da envoltória")
    if res.viga.config.reducao_apoio:
        # o cortante de projeto só difere da envoltória junto aos apoios:
        # desenha apenas esses trechos, com o sinal do ramo que governa
        V_abs = np.maximum(np.abs(env.V_max), np.abs(env.V_min))
        sinal = np.sign(np.where(np.abs(env.V_max) >= np.abs(env.V_min),
                                 env.V_max, env.V_min))
        reduzido = np.where(np.abs(res.Vsd_projeto - V_abs) > 0.5,
                            sinal * res.Vsd_projeto, np.nan)
        if np.isfinite(reduzido).any():
            ax.plot(env.x, reduzido, color=estilo.VERMELHO, lw=1.6, ls="--",
                    label="Vsd de projeto junto ao apoio (17.4.1.2.1)")
    ax.axhline(0, color=estilo.CINZA, lw=1.0)
    # abaixo do patamar o estribo mínimo já basta (17.4.1.1.1)
    ax.plot(env.x, v_lim, color=estilo.CINZA_MEDIO, lw=1.0, ls=(0, (6, 3)),
            label="Vsd atendido por asw,mín (17.4.1.1.1)")
    ax.plot(env.x, -v_lim, color=estilo.CINZA_MEDIO, lw=1.0, ls=(0, (6, 3)))
    ax.set_ylabel("V (kN)")
    ax.set_title("Envoltória de forças cortantes — ELU")
    _legenda_acima(ax)
    _rotular_extremos(ax, env.x, env.V_max, cor=estilo.VERDE)
    _rotular_extremos(ax, env.x, env.V_min, cor=estilo.VERDE, acima=False)
    _marcar_apoios(ax, res)

    # -- torçores -----------------------------------------------------------
    if tem_torcao:
        ax = axes[2]
        xt, T = res.T_diagrama
        ax.fill_between(xt, T, 0, color=estilo.LARANJA_CLARO, alpha=0.7, lw=0)
        ax.plot(xt, T, color=estilo.LARANJA, lw=1.2,
                label="Tsd de cálculo (γg·Tg + γq·Tq)")
        if res.torcoes:
            pior = max(res.torcoes, key=lambda t: t.interacao)
            ax.axhline(pior.TRd2, color=estilo.VERMELHO, lw=1.0, ls="--",
                       label=f"TRd2 = {pior.TRd2:.1f} kN·m (17.5.1.5)")
            ax.axhline(-pior.TRd2, color=estilo.VERMELHO, lw=1.0, ls="--")
            _rotular_extremos(ax, xt, np.abs(T), cor=estilo.LARANJA)
        ax.axhline(0, color=estilo.CINZA, lw=1.0)
        ax.set_ylabel("T (kN.m)")
        ax.set_title("Diagrama de momentos torçores — ELU")
        ax.legend(loc="upper right", ncol=2)
        _marcar_apoios(ax, res)

    # -- deformada ----------------------------------------------------------
    ax = axes[-1]
    nt = len(res.viga.tramos)
    sol = combinar(res.estrutura, np.ones(nt),
                   np.full(nt, res.viga.config.psi2), "ELS quase permanente")
    ax.fill_between(sol.x, sol.flecha * 1000.0, 0, color=estilo.AZUL_CLARO,
                    alpha=0.5, lw=0)
    ax.plot(sol.x, sol.flecha * 1000.0, color=estilo.AZUL, lw=1.2)
    ax.axhline(0, color=estilo.CINZA, lw=1.0)
    ax.invert_yaxis()
    ax.set_ylabel("flecha elástica (mm)")
    ax.set_xlabel("x (m)")
    ax.set_title("Deformada elástica — combinação quase permanente "
                 "(inércia bruta)")
    _marcar_apoios(ax, res)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Armaduras
# ---------------------------------------------------------------------------

def figura_armaduras(res: ResultadoViga) -> Figure:
    """Área de aço necessária x adotada e armadura transversal."""
    estilo.aplicar_estilo()
    fig = Figure(figsize=TAMANHO)
    axes = fig.subplots(2, 1, sharex=True)

    # -- armadura longitudinal ---------------------------------------------
    # a armadura é desenhada do lado da face em que fica na viga: a inferior
    # abaixo do eixo e a superior acima, como no detalhamento
    ax = axes[0]
    x = res.x
    # mesma convenção de cor do detalhamento: inferior vermelha, superior azul
    ax.fill_between(x, -np.nan_to_num(res.As_req_inf), 0,
                    color=estilo.VERMELHO, alpha=0.25, lw=0,
                    label="As necessária — armadura inferior (positiva)")
    ax.fill_between(x, np.nan_to_num(res.As_req_sup), 0,
                    color=estilo.AZUL, alpha=0.25, lw=0,
                    label="As necessária — armadura superior (negativa)")

    from ..core.materiais import area_barra
    niveis = {"inferior": 0, "superior": 0}
    for p in res.posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        A = p.n * area_barra(p.phi)
        abaixo = p.face == "inferior"
        y = -A if abaixo else A
        cor = estilo.VERMELHO if abaixo else estilo.AZUL
        ax.plot([p.x_ini, p.x_fim], [y, y], color=cor, lw=2.0,
                solid_capstyle="butt")
        ax.plot([p.x_ini, p.x_ini], [0, y], color=cor, lw=0.6, ls=":")
        ax.plot([p.x_fim, p.x_fim], [0, y], color=cor, lw=0.6, ls=":")
        # rótulos escalonados em quatro níveis e três posições ao longo da
        # barra: com muitas barras na mesma face, dois níveis não bastavam
        indice = niveis[p.face]
        niveis[p.face] += 1
        desloc = (-1 if abaixo else 1) * (4.0 + 9.5 * (indice % 4))
        fracao = (0.5, 0.3, 0.7)[indice % 3]
        ax.annotate(f"N{p.numero}: {p.texto_quantidade}Ø{p.phi:g}",
                    (p.x_ini + (p.x_fim - p.x_ini) * fracao, y),
                    textcoords="offset points",
                    xytext=(0, desloc), ha="center",
                    va="top" if abaixo else "bottom", fontsize=7, color=cor)

    ax.axhline(0, color=estilo.CINZA, lw=1.0)
    ax.set_ylabel("As (cm²)  —  inferior abaixo, superior acima")
    ax.set_title("Armadura longitudinal — necessária x adotada "
                 "(escalonamento com decalagem)")
    ax.legend(loc="upper right", ncol=2)
    _marcar_apoios(ax, res)

    # -- armadura transversal ----------------------------------------------
    ax = axes[1]
    ax.fill_between(x, res.asw_req, 0, color=estilo.VERDE_CLARO, alpha=0.7,
                    lw=0, label="Asw/s necessária")
    for z in res.zonas_estribo:
        ax.plot([z.x_ini, z.x_fim], [z.asw_ef, z.asw_ef], color=estilo.VERDE,
                lw=2.2, solid_capstyle="butt")
        ax.text((z.x_ini + z.x_fim) / 2, z.asw_ef,
                f"Ø{z.phi:g} c/{z.s:g}", ha="center", va="bottom",
                fontsize=7.5, color=estilo.VERDE)
    ax.set_ylabel("Asw/s (cm²/m)")
    ax.set_xlabel("x (m)")
    if res.torcoes:
        # com torção a curva de Asw/s já vem somada; mostrar a parcela de
        # cortante em separado deixa claro quanto a torção acrescentou
        x_t = np.array([t.x for t in res.torcoes])
        so_cortante = np.array([t.asw_cortante for t in res.torcoes])
        ax.plot(x_t, so_cortante, color=estilo.VERDE, lw=1.0, ls="--",
                label="parcela de cortante (sem torção)")
    ax.set_title("Armadura transversal — necessária x adotada"
                 + (" (cortante + torção)" if res.torcoes else ""))
    ax.legend(loc="upper right")
    _marcar_apoios(ax, res)

    fig.tight_layout()
    return fig
