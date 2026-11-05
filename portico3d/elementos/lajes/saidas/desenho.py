# -*- coding: utf-8 -*-
"""
desenho.py
Plantas de armação do pavimento, em matplotlib.

São **duas** plantas, e a separação não é estética: a armadura positiva vive
na face inferior e a negativa na superior, e desenhar as duas juntas produz um
emaranhado em que não se lê nem uma nem a outra. É assim que a prancha de
laje é feita -- uma planta de armadura positiva e uma de negativa.

Cada posição aparece como o conjunto de barras que ela representa, na abscissa
real, com o rótulo ``n Nx Ø c/s C=...`` puxado por linha de chamada. As barras
são desenhadas todas, e não uma representativa, porque é a densidade delas que
mostra o espaçamento -- e espaçamento errado é o erro mais comum na laje.

Convenção de cores das duas plantas e do DXF:

    positiva ......... vermelho
    negativa ......... azul
    distribuição ..... verde
    contorno ......... laranja

O modelo 3D interativo (``vista3d.py``, desde a R06) usa uma convenção
diferente, por pedido explícito -- ver o docstring de lá.
"""

from __future__ import annotations

import math

from matplotlib.figure import Figure
from matplotlib.patches import Circle, Rectangle

from . import estilo
from . import graficos

estilo.aplicar_estilo()

COR = {
    "positiva": estilo.VERMELHO,
    "negativa": estilo.AZUL,
    "distribuição": estilo.VERDE,
    "contorno": estilo.LARANJA,
}

#: Quantas barras o desenho traça, no máximo, por posição. Acima disso ele
#: desenha uma a cada ``k`` e diz no rótulo -- a prancha em A1 não resolve
#: 200 linhas a 7 cm, e a figura fica um borrão preto.
MAXIMO_BARRAS = 60


def _cor(pos) -> str:
    for chave, cor in COR.items():
        if pos.tipo.startswith(chave):
            return cor
    return estilo.CINZA


def _barras(pos) -> list[float]:
    """Coordenadas transversais das barras da posição, em cm."""
    if pos.quantidade <= 1:
        return [(pos.faixa_inicio + pos.faixa_fim) / 2.0]
    passo = ((pos.faixa_fim - pos.faixa_inicio) / (pos.quantidade - 1)
             if pos.quantidade > 1 else 0.0)
    return [pos.faixa_inicio + k * passo for k in range(pos.quantidade)]


def _desenhar_posicao(ax, pos, com_rotulo: bool = True) -> None:
    """Traça as barras de uma posição e o rótulo -- a grade cheia.

    Não desenha gancho: a representação fiel do gancho (e da viga que o
    justifica) é coisa do modo esquemático; aqui a grade mostra o que ela
    tem de mostrar, que é a densidade das barras.
    """
    cor = _cor(pos)
    coords = _barras(pos)
    salto = max(1, math.ceil(len(coords) / MAXIMO_BARRAS))
    traçadas = coords[::salto]
    for c in traçadas:
        if pos.eixo == "X":
            ax.plot([pos.inicio / 100.0, pos.fim / 100.0],
                    [c / 100.0, c / 100.0], color=cor, lw=0.85, zorder=6,
                    solid_capstyle="butt")
        else:
            ax.plot([c / 100.0, c / 100.0],
                    [pos.inicio / 100.0, pos.fim / 100.0], color=cor, lw=0.85,
                    zorder=6, solid_capstyle="butt")
    if not com_rotulo:
        return

    # rótulo no meio da faixa, deslocado para não cair sobre as barras
    meio = (pos.faixa_inicio + pos.faixa_fim) / 2.0 / 100.0
    centro = (pos.inicio + pos.fim) / 2.0 / 100.0
    texto = (f"N{pos.numero}  {pos.quantidade} Ø{pos.phi:g} "
             f"c/{pos.espacamento:g}  C={pos.comprimento:.0f}")
    if pos.tem_gancho:
        texto += "  [gancho]"
    if salto > 1:
        texto += f"  (1 de {salto} traçada)"
    if pos.eixo == "X":
        ax.text(centro, meio, texto, ha="center", va="center", fontsize=6.5,
                color=cor, zorder=10,
                bbox=dict(boxstyle="round,pad=0.22", facecolor="white",
                          edgecolor=cor, alpha=0.90, lw=0.6))
    else:
        ax.text(meio, centro, texto, ha="center", va="center", fontsize=6.5,
                color=cor, rotation=90, zorder=10,
                bbox=dict(boxstyle="round,pad=0.22", facecolor="white",
                          edgecolor=cor, alpha=0.90, lw=0.6))


def _fundo(ax, res, com_nomes: bool = True, com_vigas: bool = False) -> None:
    """Contorno das lajes, para as barras terem onde se apoiar.

    ``com_vigas`` acrescenta a faixa de cada apoio (ver
    :func:`graficos._vigas`): é o que deixa visível até onde a armadura reta
    pode ir sem aflorar na face externa da viga -- só faz sentido no
    esquemático, que é fiel a essa distância; a grade cheia não precisa
    dela.
    """
    for rl in res.lajes:
        x0, y0, x1, y1 = rl.laje.retangulo
        if com_vigas:
            graficos._vigas(ax, rl.laje)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                               facecolor=estilo.CONCRETO, edgecolor=estilo.CINZA,
                               lw=1.0, alpha=0.45, zorder=1))
        if com_nomes:
            ax.text(x0 + 0.12, y1 - 0.12, rl.nome, ha="left", va="top",
                    fontsize=8, color=estilo.CINZA, zorder=3,
                    fontweight="bold")
    # lajes treliçadas, alveolares e nervuradas: sem barras nesta prancha --
    # a armação delas está nas tabelas, na memória e na planilha --, mas o
    # contorno entra para a planta não ficar com buracos
    for e in getattr(res, "especiais", []):
        for nome in e.lajes:
            laje = res.pavimento.laje(nome)
            if laje is None:
                continue
            x0, y0, x1, y1 = laje.retangulo
            if com_vigas:
                graficos._vigas(ax, laje)
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0,
                                   facecolor=graficos.COR_TIPO[laje.tipo],
                                   edgecolor=estilo.CINZA, lw=1.0,
                                   alpha=0.45, zorder=1))
            if com_nomes:
                ax.text((x0 + x1) / 2.0, (y0 + y1) / 2.0,
                        f"{laje.nome}\n{graficos._texto_do_tipo(laje)}\n"
                        f"armação nas tabelas e na memória",
                        ha="center", va="center", fontsize=7.5,
                        color=estilo.CINZA, zorder=3)


def _preparar(res, titulo: str):
    x0, y0, x1, y1 = res.contorno()
    larg, alt = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    escala = min(11.0 / max(larg, alt), 1.8)
    fig = Figure(figsize=(max(larg * escala, 6.5) + 1.2,
                          max(alt * escala, 4.5) + 1.6))
    ax = fig.add_subplot(111)
    ax.set_xlim(x0 - 0.7, x1 + 0.7)
    ax.set_ylim(y0 - 0.7, y1 + 0.7)
    ax.set_aspect("equal")
    ax.set_title(titulo)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.grid(True, alpha=0.2)
    return fig, ax


# ---------------------------------------------------------------------------
# Plantas de armação
# ---------------------------------------------------------------------------

def _gancho_perpendicular(ax, x: float, y: float, eixo: str,
                          comprimento_cm: float, cor: str) -> None:
    """O gancho a 90°, representado **perpendicular** à barra -- "deitado"
    no plano da planta, com o comprimento real dele --, e não como se fosse
    mais barra reta na mesma direção. Uma dobra a 90° não é uma continuação
    reta: desenhá-la assim faz a barra parecer mais comprida do que é, e
    passar da viga que a hospeda.

    O traço sai **para um lado só** do ponto -- nunca centrado nele --,
    porque uma dobra real vira para um lado, não para os dois ao mesmo
    tempo; um traço centrado parece uma cruz, e nas duas pontas de uma
    mesma barra parece que ele "sai" da barra nas duas direções. As duas
    pontas de uma posição dobram para o mesmo lado, o que dá o formato de U
    (ou de grampo) da armadura negativa de verdade.
    """
    c = comprimento_cm / 100.0
    if eixo == "X":
        ax.plot([x, x], [y, y + c], color=cor, lw=1.8, zorder=6.5,
                solid_capstyle="butt")
    else:
        ax.plot([x, x + c], [y, y], color=cor, lw=1.8, zorder=6.5,
                solid_capstyle="butt")


def _texto_pendente(textos: list, x: float, y: float, texto: str, cor: str,
                    prioridade: int, fontsize: float = 6.5, ha: str = "center",
                    va: str = "center", rotation: float = 0.0,
                    bbox: bool = False, dx: float = 0.0, dy: float = 1.0,
                    chamada: tuple | None = None) -> None:
    """Registra um texto para ser desenhado depois, sem se sobrepor a mais
    nada -- ver :func:`_resolver_textos`. ``prioridade`` decide a ordem: os
    números de trecho (mais amarrados ao ponto que descrevem) entram antes
    dos rótulos de posição (mais livres para se afastar, porque já saem com
    linha de chamada). ``dx``/``dy`` é o sentido em que o texto é empurrado
    se colidir; ``chamada``, se dado, é o ponto da barra a que o texto se
    refere -- uma linha fina liga os dois quando o texto se afasta dele.
    """
    textos.append({
        "x": x, "y": y, "texto": texto, "cor": cor, "prioridade": prioridade,
        "fontsize": fontsize, "ha": ha, "va": va, "rotation": rotation,
        "bbox": bbox, "dx": dx, "dy": dy, "chamada": chamada,
    })


def _resolver_textos(fig: Figure, ax, textos: list) -> None:
    """Desenha os textos pendentes sem deixá-los se sobrepor.

    A largura de um texto é fixa em pontos de fonte, não em metros de
    planta -- estimá-la sem medir engana em pavimentos de tamanhos
    diferentes. Por isso o desenho é medido de verdade, uma vez, no
    renderizador: quem colide com um texto já posto empurra na direção
    própria (``dx``/``dy``) até achar espaço livre, e ganha uma linha de
    chamada fina até o ponto de origem quando se afasta dele -- a mesma
    ideia do croqui de detalhamento de vigas.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    if not textos:
        return
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    renderer = canvas.get_renderer()

    def caixa_de(artista) -> tuple[float, float, float, float]:
        bb = artista.get_window_extent(renderer=renderer)
        bb = bb.transformed(ax.transData.inverted())
        return (bb.x0, bb.y0, bb.x1, bb.y1)

    def sobrepoe(a, b) -> bool:
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    ocupadas: list[tuple[float, float, float, float]] = []
    for t in sorted(textos, key=lambda t: t["prioridade"]):
        artista = ax.text(
            t["x"], t["y"], t["texto"], fontsize=t["fontsize"],
            color=t["cor"], ha=t["ha"], va=t["va"], rotation=t["rotation"],
            zorder=10,
            bbox=(dict(boxstyle="round,pad=0.22", facecolor="white",
                      edgecolor=t["cor"], alpha=0.90, lw=0.6)
                 if t["bbox"] else None))
        x, y = t["x"], t["y"]
        atual = caixa_de(artista)
        passo = max(atual[3] - atual[1], atual[2] - atual[0]) * 0.5 + 0.02
        tentativas = 0
        while any(sobrepoe(atual, o) for o in ocupadas) and tentativas < 40:
            x += passo * t["dx"]
            y += passo * t["dy"]
            artista.set_position((x, y))
            atual = caixa_de(artista)
            tentativas += 1
        ocupadas.append(atual)
        if t["chamada"] is not None and \
                (abs(x - t["chamada"][0]) > 1e-6 or
                 abs(y - t["chamada"][1]) > 1e-6):
            ax.plot([t["chamada"][0], x], [t["chamada"][1], y],
                    color=estilo.CINZA_MEDIO, lw=0.5, zorder=9)

    # um texto empurrado por muita gente perto pode acabar fora dos limites
    # fixados por _preparar (que só conhece o contorno do pavimento, antes
    # de qualquer rótulo existir) -- os limites só crescem para caber, nunca
    # encolhem, e a margem final continua igual à de _preparar
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    xs = [c[0] for c in ocupadas] + [c[2] for c in ocupadas] + [x0, x1]
    ys = [c[1] for c in ocupadas] + [c[3] for c in ocupadas] + [y0, y1]
    ax.set_xlim(min(xs) - 0.1, max(xs) + 0.1)
    ax.set_ylim(min(ys) - 0.1, max(ys) + 0.1)


def _cotas_emenda(ax, pos, centro_faixa: float, cor: str,
                  textos: list) -> None:
    """Marca cada emenda por traspasse da barra, com o ``l0t`` cotado.

    A emenda é desenhada como **cota**, e não como uma segunda barra
    sobreposta: um pedaço de barra paralelo, ali, é lido como uma armadura a
    mais no arranjo -- foi a conclusão a que o croqui de vigas já tinha
    chegado. A cota diz o que interessa (onde a emenda cai e quanto de
    traspasse ela pede) sem inventar aço no desenho.

    A posição da emenda é a vara comercial contada a partir do início da
    barra (``pos.estacoes_emenda``, preenchida em
    ``dimensionar._conferir_traspasse``): é onde a barra teria de ser
    cortada. Onde escalonar as emendas é decisão de quem detalha a prancha,
    e o aviso construtivo diz isso.
    """
    if not pos.estacoes_emenda or pos.l0t <= 0.0:
        return
    recuo = 0.12                                    # m, afastamento da barra
    for est in pos.estacoes_emenda:
        fim_m = est / 100.0
        ini_m = (est - pos.l0t) / 100.0
        if pos.eixo == "X":
            y = centro_faixa - recuo
            ax.annotate("", xy=(ini_m, y), xytext=(fim_m, y),
                        arrowprops=dict(arrowstyle="<->", color=cor, lw=0.8),
                        zorder=5)
            _texto_pendente(textos, (ini_m + fim_m) / 2.0, y - 0.02,
                            f"l0t {pos.l0t:.0f}", cor, 1, fontsize=6,
                            ha="center", va="top", dx=0.0, dy=-1.0,
                            chamada=((ini_m + fim_m) / 2.0, y))
        else:
            x = centro_faixa - recuo
            ax.annotate("", xy=(x, ini_m), xytext=(x, fim_m),
                        arrowprops=dict(arrowstyle="<->", color=cor, lw=0.8),
                        zorder=5)
            _texto_pendente(textos, x - 0.02, (ini_m + fim_m) / 2.0,
                            f"l0t {pos.l0t:.0f}", cor, 1, fontsize=6,
                            rotation=90, ha="right", va="center",
                            dx=-1.0, dy=0.0,
                            chamada=(x, (ini_m + fim_m) / 2.0))


def _desenhar_posicao_esquematica(ax, pos, textos: list) -> None:
    """Uma barra só, representando a posição inteira -- e a faixa onde ela
    vale, cotada ao lado.

    É desenhada como uma **barra reta**: uma linha só, do trecho reto (sem
    escalonar). O gancho, quando existe, é um traço **perpendicular** na
    ponta (ver :func:`_gancho_perpendicular`) -- nunca uma continuação reta
    da barra, porque a dobra a 90° não estica a barra na mesma direção; ela
    dobra para dentro do apoio, e desenhá-la como reta faria a barra
    aparentar ir além da viga que a hospeda.

    Cada trecho -- o reto e cada gancho -- ganha o próprio comprimento
    escrito perto dele (a mesma ideia da vista explodida do croqui de
    vigas): como o comprimento de cada pedaço já está ali, o rótulo da
    posição não repete o gancho por extenso. Onde a barra cruza a cota da
    faixa (a seta que mostra a largura da faixa, ao lado) entra um círculo
    -- é o ponto que amarra esta posição, com o seu deslocamento transversal
    (:func:`graficos.centro_faixa_pos`), à cota que descreve a faixa inteira
    -- e é dali que o rótulo da posição puxa a linha de chamada.

    O ponto transversal em que a barra é desenhada não é sempre o meio da
    faixa (ver :func:`graficos.centro_faixa_pos`): duas lajes vizinhas com a
    mesma faixa, ambas centradas, pareceriam uma barra só atravessando as
    duas.

    Nenhum texto é desenhado diretamente aqui -- cada um entra em ``textos``
    e sai de fato em :func:`_resolver_textos`, depois que todas as posições
    da figura já contribuíram os deles, para que a resolução de sobreposição
    veja a figura inteira de uma vez.

    A grade real (as dezenas de barras paralelas) mostra a densidade, que é
    o que importa para conferir o espaçamento; o esquemático troca essa
    densidade por legibilidade, quando o que se quer é ver rápido *onde*
    cada posição entra e *até onde* ela cobre -- útil numa planta com muitas
    lajes, em que a grade cheia de todas elas ao mesmo tempo vira ruído.
    """
    cor = _cor(pos)
    ini, fim = pos.inicio / 100.0, pos.fim / 100.0
    f0, f1 = pos.faixa_inicio / 100.0, pos.faixa_fim / 100.0
    centro_faixa = graficos.centro_faixa_pos(pos) / 100.0
    largura_faixa = pos.faixa_fim - pos.faixa_inicio
    gi, gf = pos.gancho_inicio / 100.0, pos.gancho_fim / 100.0
    # a cota da faixa fica perto da ponta -fim-, um pouco recuada para não
    # colar na barra -- é ali, cruzando a barra, que entra o círculo
    recuo = (fim - ini) * 0.15

    if pos.eixo == "X":
        ax.plot([ini, fim], [centro_faixa, centro_faixa],
                color=cor, lw=1.8, zorder=6, solid_capstyle="butt")
        if pos.gancho_inicio > 0.0:
            _gancho_perpendicular(ax, ini, centro_faixa, "X",
                                  pos.gancho_inicio, cor)
            _texto_pendente(textos, ini, centro_faixa + gi,
                            f"{pos.gancho_inicio:.0f}", cor, 0, fontsize=6,
                            ha="center", va="bottom", rotation=90,
                            dx=0.0, dy=1.0, chamada=(ini, centro_faixa + gi))
        if pos.gancho_fim > 0.0:
            _gancho_perpendicular(ax, fim, centro_faixa, "X",
                                  pos.gancho_fim, cor)
            _texto_pendente(textos, fim, centro_faixa + gf,
                            f"{pos.gancho_fim:.0f}", cor, 0, fontsize=6,
                            ha="center", va="bottom", rotation=90,
                            dx=0.0, dy=1.0, chamada=(fim, centro_faixa + gf))
        _texto_pendente(textos, (ini + fim) / 2.0, centro_faixa - 0.03,
                        f"{pos.trecho_reto:.0f}", cor, 0, fontsize=6,
                        ha="center", va="top", rotation=0, dx=0.0, dy=-1.0,
                        chamada=((ini + fim) / 2.0, centro_faixa))

        xc = fim - recuo
        ax.annotate("", xy=(xc, f0), xytext=(xc, f1),
                    arrowprops=dict(arrowstyle="<->", color=cor, lw=0.8),
                    zorder=5)
        ax.add_patch(Circle((xc, centro_faixa), 0.035, facecolor=cor,
                            edgecolor=cor, zorder=7))
        _texto_pendente(textos, xc + 0.09, f1, f"{largura_faixa:.0f}", cor, 1,
                        fontsize=6, rotation=90, ha="left", va="center",
                        dx=0.0, dy=1.0, chamada=(xc, f1))
        ponto_circulo = (xc, centro_faixa)
        deslocado = (xc + 0.10, centro_faixa)
        rotulo_kw = dict(ha="left", va="center", rotation=0, dx=0.0, dy=1.0)
    else:
        ax.plot([centro_faixa, centro_faixa], [ini, fim],
                color=cor, lw=1.8, zorder=6, solid_capstyle="butt")
        if pos.gancho_inicio > 0.0:
            _gancho_perpendicular(ax, centro_faixa, ini, "Y",
                                  pos.gancho_inicio, cor)
            _texto_pendente(textos, centro_faixa + gi, ini,
                            f"{pos.gancho_inicio:.0f}", cor, 0, fontsize=6,
                            ha="left", va="center", rotation=0,
                            dx=1.0, dy=0.0, chamada=(centro_faixa + gi, ini))
        if pos.gancho_fim > 0.0:
            _gancho_perpendicular(ax, centro_faixa, fim, "Y",
                                  pos.gancho_fim, cor)
            _texto_pendente(textos, centro_faixa + gf, fim,
                            f"{pos.gancho_fim:.0f}", cor, 0, fontsize=6,
                            ha="left", va="center", rotation=0,
                            dx=1.0, dy=0.0, chamada=(centro_faixa + gf, fim))
        _texto_pendente(textos, centro_faixa - 0.03, (ini + fim) / 2.0,
                        f"{pos.trecho_reto:.0f}", cor, 0, fontsize=6,
                        ha="right", va="center", rotation=90, dx=-1.0, dy=0.0,
                        chamada=(centro_faixa, (ini + fim) / 2.0))

        yc = fim - recuo
        ax.annotate("", xy=(f0, yc), xytext=(f1, yc),
                    arrowprops=dict(arrowstyle="<->", color=cor, lw=0.8),
                    zorder=5)
        ax.add_patch(Circle((centro_faixa, yc), 0.035, facecolor=cor,
                            edgecolor=cor, zorder=7))
        _texto_pendente(textos, f1, yc + 0.09, f"{largura_faixa:.0f}", cor, 1,
                        fontsize=6, ha="center", va="bottom",
                        dx=0.0, dy=1.0, chamada=(f1, yc))
        ponto_circulo = (centro_faixa, yc)
        deslocado = (centro_faixa, yc + 0.10)
        rotulo_kw = dict(ha="left", va="center", rotation=90, dx=0.0, dy=1.0)

    _cotas_emenda(ax, pos, centro_faixa, cor, textos)

    texto = (f"N{pos.numero}  {pos.quantidade} Ø{pos.phi:g} "
             f"c/{pos.espacamento:g}  C={pos.comprimento:.0f}")
    if pos.emendas:
        texto += (f"  ({pos.emendas} emenda{'s' if pos.emendas > 1 else ''} "
                  f"l0t={pos.l0t:.0f})")
    _texto_pendente(textos, *deslocado, texto, cor, 2, fontsize=6.5,
                    bbox=True, chamada=ponto_circulo, **rotulo_kw)


def figura_armadura_positiva(res, esquematico: bool = False) -> Figure:
    """Planta da armadura da face inferior: positivas e distribuição.

    ``esquematico`` troca a grade de barras por uma seta e uma cota de faixa
    por posição -- ver :func:`_desenhar_posicao_esquematica`.
    """
    fig, ax = _preparar(res, "Planta de armação — face inferior (armadura "
                             "positiva e de distribuição)"
                             + (" — esquemático" if esquematico else ""))
    _fundo(ax, res, com_vigas=esquematico)
    textos: list = []
    for rl in res.lajes:
        for pos in rl.posicoes:
            if pos.face != "inferior":
                continue
            if esquematico:
                _desenhar_posicao_esquematica(ax, pos, textos)
            else:
                _desenhar_posicao(ax, pos)
    fig.tight_layout()
    _resolver_textos(fig, ax, textos)
    return fig


def figura_armadura_negativa(res, esquematico: bool = False) -> Figure:
    """Planta da armadura da face superior: negativas, contorno e continuidade.

    ``esquematico`` troca a grade de barras por uma seta e uma cota de faixa
    por posição -- ver :func:`_desenhar_posicao_esquematica`.
    """
    fig, ax = _preparar(res, "Planta de armação — face superior (armadura "
                             "negativa, de continuidade e de contorno)"
                             + (" — esquemático" if esquematico else ""))
    _fundo(ax, res, com_vigas=esquematico)
    textos: list = []

    def desenhar(pos) -> None:
        if esquematico:
            _desenhar_posicao_esquematica(ax, pos, textos)
        else:
            _desenhar_posicao(ax, pos)

    for rl in res.lajes:
        for pos in rl.posicoes:
            if pos.face != "superior":
                continue
            desenhar(pos)
    for pos in res.posicoes_continuidade:
        desenhar(pos)
    fig.tight_layout()
    _resolver_textos(fig, ax, textos)
    return fig
