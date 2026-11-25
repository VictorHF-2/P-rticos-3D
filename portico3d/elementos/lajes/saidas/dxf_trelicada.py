# -*- coding: utf-8 -*-
"""
dxf_trelicada.py
Prancha de armação da laje treliçada (e da nervurada unidirecional, que usa o
mesmo motor) em DXF -- no padrão do ``dxf.py`` das maciças: centímetros
(INSUNITS = 5), escala 1:1, camadas separadas e texto do corpo de 8 cm, para
sair legível a 1:50.

Por faixa (``ResultadoTrelicada``), três desenhos lado a lado e as tabelas
embaixo:

1. **Planta de forma**: o contorno da faixa, as vigas de apoio (tracejadas),
   a posição de cada vigota no intereixo, o enchimento entre elas, a seta do
   sentido das nervuras e as cotas dos vãos e do intereixo;
2. **Planta de armação**, esquemática como a das maciças -- uma barra
   representativa por posição, sobre uma nervura, com a cota da faixa de
   nervuras onde ela se repete: a armadura adicional (positiva) de cada vão,
   a negativa sobre os apoios intermediários (e dos balanços) e a
   distribuição da capa nas duas direções. O modelo não tem nervura
   transversal de travamento; quando a laje é nervurada moldada, os estribos
   entram só na tabela;
3. **Corte típico da nervura**, ampliado 5 vezes (escala 1:10 numa prancha a
   1:50), cotado em valores reais: vigota e treliça (designação), altura
   total, capa, largura da nervura, base, enchimento e intereixo.

Embaixo, a **tabela de posições** (N, Ø, aço, quantidade, comprimento
unitário e total, massa) e o **resumo do aço** por bitola -- o mesmo
``quantitativo["por_bitola"]`` das maciças, que :func:`por_bitola` monta e o
motor da treliçada guarda no resultado. As vigotas (treliças prontas) ficam
numa linha própria do resumo: não são barra de bitola.

Os rótulos e a tabela usam ``N1``, ``N2``... -- o Pórticos 3D renumera por
folha procurando ``N<número>`` --, e todo texto é ASCII.
"""

from __future__ import annotations

import math
import unicodedata

import ezdxf

from ..core.materiais import massa_linear
from ..core.trelicada import quantitativo_por_bitola, quantitativo_trelicas
from ..core.trelicada_modelo import TRELICAS
from . import dxf

#: Altura do texto do corpo e dos títulos, cm (8 cm a 1:50 = 1,6 mm).
ALTURA = 8.0
ALTURA_TITULO = 16.0
#: Ampliação do corte típico (1:10 numa prancha a 1:50).
AMPLIACAO_CORTE = 5.0
#: Espessura da base de concreto da vigota no desenho, cm (só desenho).
BASE_VIGOTA = 3.0

#: Camadas próprias da treliçada, além das do ``dxf.CAMADAS``.
CAMADAS_TRELICADA = {
    "VIGOTA": (30, "CONTINUOUS", 25),
    "TRELICA": (dxf.CINZA_ACI, "CONTINUOUS", 13),
    "ENCHIMENTO": (dxf.CINZA_ACI, "CONTINUOUS", 9),
    "CORTE": (dxf.PRETO, "CONTINUOUS", 35),
    "NERVURA": (dxf.CINZA_ACI, "DASHED", 9),
}

#: Todas as camadas que o desenho usa -- declaradas em :func:`preparar`.
CAMADAS = {**dxf.CAMADAS, **CAMADAS_TRELICADA}


def _ascii(texto: str) -> str:
    """O texto do DXF é ASCII: tira acentos e troca Ø por P."""
    texto = texto.replace("Ø", "P").replace("ø", "P").replace("×", "x")
    return unicodedata.normalize("NFKD", texto).encode(
        "ascii", "ignore").decode("ascii")


def preparar(doc) -> None:
    """Unidades, camadas e estilo de cota (o das maciças mais as camadas da
    treliçada). Serve a quem desenha a treliçada num documento próprio."""
    dxf._preparar(doc)
    for nome, (cor, tipo, espessura) in CAMADAS_TRELICADA.items():
        if nome not in doc.layers:
            doc.layers.add(name=nome, color=cor, linetype=tipo,
                           lineweight=espessura)


# ---------------------------------------------------------------------------
# Quantitativo
# ---------------------------------------------------------------------------

def por_bitola(res) -> dict:
    """O ``quantitativo["por_bitola"]`` da faixa (formato das maciças)."""
    return quantitativo_por_bitola(res.posicoes)


def trelicas(res) -> dict:
    """As vigotas treliçadas da faixa, fora do resumo por bitola."""
    return quantitativo_trelicas(res.posicoes, res.laje.trelica)


# ---------------------------------------------------------------------------
# Geometria da faixa
# ---------------------------------------------------------------------------

def _geometria(res) -> dict:
    """Posições em cm, com a origem na ponta esquerda da faixa."""
    lt = res.laje
    n = len(lt.vaos)
    t = [a.t for a in lt.apoios]
    x_ap = [lt.balanco_esq if lt.balanco_esq > 0 else t[0] / 2.0]
    for v in lt.vaos:
        x_ap.append(x_ap[-1] + v.L)
    x_fim = x_ap[-1] + (lt.balanco_dir if lt.balanco_dir > 0 else t[-1] / 2.0)
    largura = lt.largura_laje * 100.0
    inter = lt.intereixo
    n_ner = max(1, math.ceil(largura / inter - 1e-9))
    y_ner = [min(inter / 2.0 + i * inter, largura - lt.base / 2.0)
             for i in range(n_ner)]
    c_inf = res.geo.get("c_inf", 2.5)
    vigotas = []                       # (x0, x1) de cada vão
    for i, v in enumerate(lt.vaos):
        rv = res.vaos[i]
        e_l = rv.embute_esq if rv.embute_esq >= 0 else \
            min(lt.apoio_vigota, t[i] / 2.0)
        e_r = rv.embute_dir if rv.embute_dir >= 0 else \
            min(lt.apoio_vigota, t[i + 1] / 2.0)
        x0 = x_ap[i] + t[i] / 2.0 - e_l
        x1 = x_ap[i + 1] - t[i + 1] / 2.0 + e_r
        if i == 0 and lt.balanco_esq > 0:
            x0 = 0.0
        if i == n - 1 and lt.balanco_dir > 0:
            x1 = x_fim
        vigotas.append((x0, x1))
    return dict(x_ap=x_ap, t=t, x_fim=x_fim, largura=largura, inter=inter,
                n_ner=n_ner, y_ner=y_ner, c=c_inf, vigotas=vigotas)


# ---------------------------------------------------------------------------
# Peças
# ---------------------------------------------------------------------------

def _ret(msp, x0, y0, x1, y1, camada):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                       close=True, dxfattribs={"layer": camada})


def _caixa(x, y, texto, altura=ALTURA, ancora="center", vertical=False):
    larg = dxf.largura_texto(texto, altura)
    if vertical:
        return (x - altura / 2.0, y - larg / 2.0, x + altura / 2.0,
                y + larg / 2.0)
    if ancora == "left":
        return (x, y - altura / 2.0, x + larg, y + altura / 2.0)
    return (x - larg / 2.0, y - altura / 2.0, x + larg / 2.0,
            y + altura / 2.0)


def _livre(caixa, ocupados) -> bool:
    return not any(caixa[0] < o[2] and o[0] < caixa[2]
                   and caixa[1] < o[3] and o[1] < caixa[3] for o in ocupados)


def _texto_livre(msp, texto, x, y, ocupados, altura=ALTURA, camada="TEXTO",
                 vertical=False, chamada=True):
    """Texto centrado em (x, y) ou, se ocupado, deslocado até achar lugar,
    com linha de chamada até o ponto original."""
    texto = _ascii(texto)
    x0, y0 = x, y
    passo = altura * 1.6
    for k in range(60):
        caixa = _caixa(x, y, texto, altura, vertical=vertical)
        if _livre(caixa, ocupados):
            break
        d = passo * (k // 2 + 1) * (1 if k % 2 == 0 else -1)
        if vertical:
            x = x0 + d
        else:
            y = y0 + d
    ocupados.append(caixa)
    dxf._texto(msp, texto, x, y, altura, camada,
               rotacao=90.0 if vertical else 0.0)
    if chamada and (abs(x - x0) > 1e-6 or abs(y - y0) > 1e-6):
        msp.add_line((x0, y0), (x, y), dxfattribs={"layer": "CHAMADA"})


def _cota(msp, x0, y0, x1, y1, texto, ocupados, deslocamento=0.0):
    """Cota horizontal ou vertical, com o texto ao lado da linha."""
    vertical = abs(x1 - x0) < 1e-6
    msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "COTAS"})
    m = 3.0
    for x, y in ((x0, y0), (x1, y1)):
        if vertical:
            msp.add_line((x - m, y), (x + m, y), dxfattribs={"layer": "COTAS"})
        else:
            msp.add_line((x, y - m), (x, y + m), dxfattribs={"layer": "COTAS"})
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    alt = ALTURA * 0.85
    if vertical:
        _texto_livre(msp, texto, mx - 6.0 - deslocamento, my, ocupados, alt,
                     "COTAS", vertical=True, chamada=False)
    else:
        _texto_livre(msp, texto, mx, my + 6.0 + deslocamento, ocupados, alt,
                     "COTAS", chamada=False)


def _seta(msp, x0, y, x1, ocupados, texto):
    msp.add_line((x0, y), (x1, y), dxfattribs={"layer": "TEXTO"})
    msp.add_solid([(x1, y), (x1 - 14.0, y + 5.0), (x1 - 14.0, y - 5.0)],
                  dxfattribs={"layer": "TEXTO"})
    _texto_livre(msp, texto, (x0 + x1) / 2.0, y + 9.0, ocupados)


def _contorno_e_vigas(msp, g, dx, dy):
    _ret(msp, dx, dy, dx + g["x_fim"], dy + g["largura"], "FORMA")
    for xa, t in zip(g["x_ap"], g["t"]):
        _ret(msp, dx + xa - t / 2.0, dy - 10.0, dx + xa + t / 2.0,
             dy + g["largura"] + 10.0, "VIGA")
        msp.add_line((dx + xa, dy - 25.0), (dx + xa, dy + g["largura"] + 25.0),
                     dxfattribs={"layer": "EIXO"})


# ---------------------------------------------------------------------------
# 1. Planta de forma
# ---------------------------------------------------------------------------

def _planta_forma(msp, res, g, dx, dy, ocupados):
    lt = res.laje
    _contorno_e_vigas(msp, g, dx, dy)
    camada_ner = "VIGOTA"
    meia = (lt.bw if lt.moldada else lt.base) / 2.0
    for yc in g["y_ner"]:
        for x0, x1 in g["vigotas"]:
            _ret(msp, dx + x0, dy + yc - meia, dx + x1, dy + yc + meia,
                 camada_ner)
    # enchimento entre as nervuras, por vão
    for i, yc in enumerate(g["y_ner"][:-1]):
        y0, y1 = yc + meia, g["y_ner"][i + 1] - meia
        for x0, x1 in g["vigotas"]:
            _ret(msp, dx + x0 + 2.0, dy + y0, dx + x1 - 2.0, dy + y1,
                 "ENCHIMENTO")
    # textos
    W, L = g["largura"], g["x_fim"]
    titulo = (f"PLANTA DE FORMA - {lt.nome} ("
              + ("nervurada moldada no local" if lt.moldada else lt.trelica)
              + ")")
    _texto_livre(msp, titulo, dx + L / 2.0, dy + W + 45.0, ocupados,
                 ALTURA_TITULO)
    y_seta = dy + W / 2.0
    _seta(msp, dx + L * 0.30, y_seta, dx + L * 0.55, ocupados,
          "SENTIDO DAS NERVURAS")
    ench = (f"Enchimento: {lt.enchimento} {lt.largura_bloco:g} x "
            f"{lt.altura_enchimento:g} cm" if not lt.moldada else
            f"Forma: {lt.enchimento} {lt.largura_bloco:g} x "
            f"{lt.altura_enchimento:g} cm")
    _texto_livre(msp, ench, dx + L * 0.5, dy + W / 2.0 - 30.0, ocupados)
    if not lt.moldada:
        _texto_livre(msp, f"Vigotas {lt.trelica} a cada {g['inter']:g} cm",
                     dx + L * 0.5, dy + W / 2.0 - 50.0, ocupados)
    # cotas: vãos e balanços embaixo, intereixo e largura à esquerda
    yc = dy - 40.0
    pontos = ([0.0] if lt.balanco_esq > 0 else []) + list(g["x_ap"]) + \
        ([L] if lt.balanco_dir > 0 else [])
    for a, b in zip(pontos[:-1], pontos[1:]):
        _cota(msp, dx + a, yc, dx + b, yc, f"{b - a:.0f}", ocupados)
    if len(g["y_ner"]) >= 2:
        y0, y1 = g["y_ner"][0], g["y_ner"][1]
        _cota(msp, dx - 30.0, dy + y0, dx - 30.0, dy + y1,
              f"{y1 - y0:.0f}", ocupados)
    _cota(msp, dx - 60.0, dy, dx - 60.0, dy + W, f"{W:.0f}", ocupados)
    return L, W


# ---------------------------------------------------------------------------
# 2. Planta de armação
# ---------------------------------------------------------------------------

def _rotulo_posicao(p, extra: str = "") -> str:
    fio = f"{p.quantidade} P{p.phi:g}" if p.phi > 0 else \
        f"{p.quantidade} vigotas"
    return f"N{p.numero} {fio} C={p.comprimento:.0f}{extra}"


def _barra(msp, camada, x0, y0, x1, y1):
    msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": camada})


def _faixa(msp, x, y_ini, y_fim, y_barra, ocupados, texto):
    """Cota da faixa de nervuras onde a barra se repete, com o círculo no
    cruzamento com a barra representativa."""
    msp.add_line((x, y_ini), (x, y_fim), dxfattribs={"layer": "COTAS"})
    for y in (y_ini, y_fim):
        msp.add_line((x - 3.0, y), (x + 3.0, y), dxfattribs={"layer": "COTAS"})
    msp.add_circle((x, y_barra), 3.0, dxfattribs={"layer": "COTAS"})


def _planta_armacao(msp, res, g, dx, dy, ocupados) -> dict:
    """Desenha as barras e devolve ``{numero: (camada, x0, x1)}`` para as
    conferências."""
    lt = res.laje
    _contorno_e_vigas(msp, g, dx, dy)
    # eixo de cada nervura, em cinza: é onde as barras se repetem
    for yc in g["y_ner"]:
        msp.add_line((dx, dy + yc), (dx + g["x_fim"], dy + yc),
                     dxfattribs={"layer": "NERVURA"})
    W, L, c = g["largura"], g["x_fim"], g["c"]
    _texto_livre(msp, f"PLANTA DE ARMACAO - {lt.nome}", dx + L / 2.0,
                 dy + W + 45.0, ocupados, ALTURA_TITULO)
    ys = g["y_ner"]
    y_ini, y_fim = ys[0], ys[-1]
    # a positiva dos vãos pares e a dos ímpares em nervuras diferentes,
    # para as barras de vãos vizinhos não se encostarem sobre o apoio; a
    # negativa numa terceira
    linhas_pos = (ys[min(1, len(ys) - 1)], ys[min(3, len(ys) - 1)])
    linha_neg = ys[min(2, len(ys) - 1)] if len(ys) > 2 else ys[-1]
    desenhado: dict = {}
    pos_por_desc = {p.descricao: p for p in res.posicoes}

    # positivas (adicional da vigota ou barra da nervura moldada), por vão
    for i, (x0, x1) in enumerate(g["vigotas"]):
        p = (pos_por_desc.get(f"Adicional positiva (vão {i + 1})")
             or pos_por_desc.get(f"Positiva da nervura (vão {i + 1})"))
        vig = pos_por_desc.get(f"Vigota {lt.trelica} (vão {i + 1})")
        if p is not None:
            linha_pos = linhas_pos[i % 2]
            xa, xb = x0 + c, x1 - c
            _barra(msp, "ARM_POSITIVA", dx + xa, dy + linha_pos,
                   dx + xb, dy + linha_pos)
            xm = (xa + xb) / 2.0
            _faixa(msp, dx + xm, dy + y_ini, dy + y_fim, dy + linha_pos,
                   ocupados, "")
            _texto_livre(msp, _rotulo_posicao(p), dx + xm + 4.0,
                         dy + linha_pos + 10.0, ocupados)
            desenhado[p.numero] = ("ARM_POSITIVA", xa, xb)
        if vig is not None:
            xm = (x0 + x1) / 2.0
            yv = ys[0]
            _texto_livre(msp, _rotulo_posicao(vig, f" ({lt.trelica})"),
                         dx + xm, dy + yv - 14.0, ocupados)
            desenhado[vig.numero] = ("VIGOTA", x0, x1)

    # negativas sobre os apoios
    for j, ra in enumerate(res.apoios):
        p = pos_por_desc.get(f"Negativa no apoio {j + 1}")
        if p is None:
            continue
        xa = g["x_ap"][j]
        x0, x1 = xa - ra.extensao_esq, xa + ra.extensao_dir
        _barra(msp, "ARM_NEGATIVA", dx + x0, dy + linha_neg, dx + x1,
               dy + linha_neg)
        _faixa(msp, dx + xa, dy + y_ini, dy + y_fim, dy + linha_neg,
               ocupados, "")
        _texto_livre(msp, _rotulo_posicao(p), dx + xa, dy + linha_neg + 10.0,
                     ocupados)
        desenhado[p.numero] = ("ARM_NEGATIVA", x0, x1)

    # distribuição da capa: uma barra em cada direção
    s = res.distribuicao.get("s", 15.0)
    for p in res.posicoes:
        if p.descricao.startswith("Distribuição transversal"):
            xt = g["x_ap"][0] + 0.18 * (g["x_ap"][1] - g["x_ap"][0]) \
                if len(g["x_ap"]) > 1 else L / 3.0
            _barra(msp, "ARM_DISTRIB", dx + xt, dy + c, dx + xt, dy + W - c)
            _texto_livre(msp, _rotulo_posicao(p, f" c/{s:g}"),
                         dx + xt - 12.0, dy + W / 2.0, ocupados,
                         vertical=True)
            desenhado[p.numero] = ("ARM_DISTRIB", xt, xt)
        elif p.descricao.startswith("Distribuição longitudinal"):
            yl = W - c - 4.0
            _barra(msp, "ARM_DISTRIB", dx + c, dy + yl, dx + L - c, dy + yl)
            _texto_livre(msp, _rotulo_posicao(p, f" c/{s:g}"),
                         dx + L * 0.70, dy + yl - 12.0, ocupados)
            desenhado[p.numero] = ("ARM_DISTRIB", c, L - c)
        elif p.descricao.startswith("Estribos"):
            _texto_livre(msp, _rotulo_posicao(p, " (estribos, ver tabela)"),
                         dx + L * 0.5, dy - 30.0, ocupados)
            desenhado[p.numero] = ("TEXTO", 0.0, 0.0)
    return desenhado


# ---------------------------------------------------------------------------
# 3. Corte típico
# ---------------------------------------------------------------------------

def _corte(msp, res, dx, dy, ocupados):
    """Corte transversal de duas nervuras, ampliado ``AMPLIACAO_CORTE``."""
    lt = res.laje
    k = AMPLIACAO_CORTE
    inter, bw, base = lt.intereixo, lt.bw, lt.base
    he, capa, h = lt.altura_enchimento, lt.capa, lt.h
    c = res.geo.get("c_inf", 2.5)

    def P(x, y):
        return (dx + x * k, dy + y * k)

    x_l, x_r = -inter * 0.5, inter * 1.5
    msp.add_lwpolyline([P(x_l, he), P(x_r, he), P(x_r, h), P(x_l, h)],
                       close=True, dxfattribs={"layer": "CORTE"})
    alt_tr = TRELICAS.get(lt.trelica, (0, 0, 0, 0, 0))[0] / 10.0
    for xc in (0.0, inter):
        if lt.moldada:
            msp.add_lwpolyline([P(xc - bw / 2, 0), P(xc + bw / 2, 0),
                                P(xc + bw / 2, he), P(xc - bw / 2, he)],
                               close=True, dxfattribs={"layer": "CORTE"})
        else:
            msp.add_lwpolyline([P(xc - base / 2, 0), P(xc + base / 2, 0),
                                P(xc + base / 2, BASE_VIGOTA),
                                P(xc - base / 2, BASE_VIGOTA)], close=True,
                               dxfattribs={"layer": "VIGOTA"})
            msp.add_lwpolyline([P(xc - bw / 2, BASE_VIGOTA),
                                P(xc + bw / 2, BASE_VIGOTA),
                                P(xc + bw / 2, he), P(xc - bw / 2, he)],
                               close=True, dxfattribs={"layer": "CORTE"})
            # treliça: os dois banzos inferiores e o superior
            yb = 1.5
            for xs in (xc - base / 2 + 2.0, xc + base / 2 - 2.0):
                msp.add_line(P(xs, yb), P(xc, yb + alt_tr),
                             dxfattribs={"layer": "TRELICA"})
                msp.add_circle(P(xs, yb), 0.35 * k,
                               dxfattribs={"layer": "TRELICA"})
            msp.add_circle(P(xc, yb + alt_tr), 0.35 * k,
                           dxfattribs={"layer": "TRELICA"})
        # adicional positiva no pé da nervura
        rv = res.vaos[0]
        n_ad = rv.n_adicional
        for m in range(n_ad):
            xb = xc + (m - (n_ad - 1) / 2.0) * 1.6
            msp.add_circle(P(xb, c + rv.phi_adicional / 20.0),
                           max(rv.phi_adicional / 20.0, 0.3) * k,
                           dxfattribs={"layer": "ARM_POSITIVA"})
        # negativa no topo
        ra = max(res.apoios, key=lambda a: a.md)
        if ra.md > 1e-9:
            for m in range(ra.n_negativa):
                xb = xc + (m - (ra.n_negativa - 1) / 2.0) * 2.0
                msp.add_circle(P(xb, h - c - ra.phi_negativa / 20.0),
                               max(ra.phi_negativa / 20.0, 0.3) * k,
                               dxfattribs={"layer": "ARM_NEGATIVA"})
    # enchimento entre as nervuras (com o rebaixo sobre a aba da vigota)
    ap = 0.0 if lt.moldada else lt.apoio_enchimento
    b0 = 0.0 if lt.moldada else BASE_VIGOTA
    for xi in (-inter, 0.0, inter):
        x1, x2 = xi + bw / 2.0, xi + inter - bw / 2.0
        x1, x2 = max(x1, x_l), min(x2, x_r)
        if x2 - x1 < 1.0:
            continue
        pts = [(x1, b0), (x1 + ap, b0), (x1 + ap, 0.0), (x2 - ap, 0.0),
               (x2 - ap, b0), (x2, b0), (x2, he), (x1, he)]
        msp.add_lwpolyline([P(*q) for q in pts], close=True,
                           dxfattribs={"layer": "ENCHIMENTO"})
    # distribuição na capa
    s = res.distribuicao.get("s", 15.0)
    phi_d = res.distribuicao.get("phi", 5.0)
    xb = x_l + 3.0
    while xb < x_r - 2.0:
        msp.add_circle(P(xb, he + capa / 2.0), max(phi_d / 20.0, 0.25) * k,
                       dxfattribs={"layer": "ARM_DISTRIB"})
        xb += s
    # textos e cotas (em valores reais)
    _texto_livre(msp, f"CORTE TIPICO DA NERVURA - {lt.nome} (ESC. 1:10)",
                 dx + inter * 0.5 * k, dy + (h + 12.0) * k, ocupados,
                 ALTURA_TITULO)
    nome = "nervura moldada no local" if lt.moldada else \
        f"vigota {lt.trelica} (h = {alt_tr:g} cm)"
    _texto_livre(msp, nome, dx + 0.0, dy - 18.0, ocupados)
    _texto_livre(msp, f"{lt.enchimento}", dx + inter * 0.5 * k,
                 dy + he * 0.5 * k, ocupados)
    xe = dx + x_r * k + 12.0
    _cota(msp, xe, dy, xe, dy + h * k, f"h = {h:g}", ocupados)
    _cota(msp, xe + 40.0, dy + he * k, xe + 40.0, dy + h * k,
          f"capa {capa:g}", ocupados)
    _cota(msp, xe + 40.0, dy, xe + 40.0, dy + he * k, f"He {he:g}", ocupados)
    yb = dy - 42.0
    _cota(msp, dx + 0.0, yb, dx + inter * k, yb, f"intereixo {inter:g}",
          ocupados)
    yt = dy + (h * k) + 12.0
    _cota(msp, dx + (-bw / 2.0) * k, yt, dx + (bw / 2.0) * k, yt,
          f"bw {bw:g}", ocupados)
    if not lt.moldada:
        _cota(msp, dx + (inter - base / 2.0) * k, yb - 26.0,
              dx + (inter + base / 2.0) * k, yb - 26.0, f"base {base:g}",
              ocupados)
    _cota(msp, dx + (bw / 2.0) * k, dy + he * 0.3 * k,
          dx + (inter - bw / 2.0) * k, dy + he * 0.3 * k,
          f"Le {lt.largura_bloco:g}", ocupados)
    return (x_r - x_l) * k + 120.0, (h + 20.0) * k


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------

def _tabela(msp, x0, y0, titulo, cab, linhas, larguras, ocupados) -> float:
    alt = ALTURA * 2.0
    _texto_livre(msp, titulo, x0 + sum(larguras) / 2.0, y0 + alt, ocupados,
                 ALTURA * 1.4, chamada=False)
    y = y0
    for linha in [cab] + linhas:
        x = x0
        for valor, larg in zip(linha, larguras):
            _ret(msp, x, y, x + larg, y - alt, "TABELA")
            dxf._texto(msp, _ascii(str(valor)), x + larg / 2.0,
                       y - alt / 2.0, ALTURA, "TEXTO")
            x += larg
        y -= alt
    return y


def _tabela_posicoes(msp, res, x0, y0, ocupados) -> float:
    cab = ["Pos.", "Descricao", "Aco", "P (mm)", "Qtd.", "C (cm)",
           "Total (m)", "Massa (kg)"]
    larg = [44, 300, 56, 56, 50, 62, 70, 76]
    linhas = []
    for p in res.posicoes:
        linhas.append([f"N{p.numero}", p.descricao[:44], p.aco or "-",
                       f"{p.phi:g}" if p.phi > 0 else res.laje.trelica,
                       str(p.quantidade), f"{p.comprimento:.0f}",
                       f"{p.quantidade * p.comprimento / 100.0:.1f}",
                       f"{p.massa:.1f}"])
    total = sum(p.massa for p in res.posicoes)
    linhas.append(["", "TOTAL", "", "", "", "", "", f"{total:.1f}"])
    return _tabela(msp, x0, y0, f"TABELA DE POSICOES - {res.laje.nome}",
                   cab, linhas, larg, ocupados)


def _resumo_aco(msp, res, x0, y0, ocupados) -> float:
    cab = ["Item", "Comprimento (m)", "Massa (kg)"]
    larg = [300, 130, 110]
    linhas = []
    for phi, d in por_bitola(res).items():
        linhas.append([f"Aco P{phi:g} mm", f"{d['comprimento']:.1f}",
                       f"{d['massa']:.1f}"])
    for nome, d in trelicas(res).items():
        linhas.append([f"Vigotas {nome}", f"{d['comprimento']:.1f}",
                       f"{d['massa']:.1f}"])
    q = res.quantitativo
    linhas.append(["Total", "", f"{q.get('aco_kg', 0.0):.1f}"])
    linhas.append(["Concreto moldado no local (m3)", "",
                   f"{q.get('volume_concreto', 0.0):.2f}"])
    return _tabela(msp, x0, y0, "RESUMO DO ACO", cab, linhas, larg, ocupados)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def desenhar(msp, res, x0: float = 0.0, y0: float = 0.0,
             ocupados: list | None = None) -> tuple[float, float, dict]:
    """Desenha uma faixa no ``msp`` a partir de (x0, y0) -- canto inferior
    esquerdo da planta de forma. Devolve ``(largura, altura, desenhado)``,
    com o retângulo ocupado (cm) e as posições desenhadas por número."""
    ocupados = [] if ocupados is None else ocupados
    g = _geometria(res)
    L, W = g["x_fim"], g["largura"]
    folga = max(0.25 * L, 160.0)
    _planta_forma(msp, res, g, x0 + 80.0, y0, ocupados)
    xa = x0 + 80.0 + L + folga
    desenhado = _planta_armacao(msp, res, g, xa, y0, ocupados)
    xc = xa + L + folga
    larg_corte, alt_corte = _corte(msp, res, xc + res.laje.intereixo * 0.5
                                   * AMPLIACAO_CORTE, y0 + 60.0, ocupados)
    y_tab = y0 - 110.0
    fim = _tabela_posicoes(msp, res, x0 + 80.0, y_tab, ocupados)
    fim2 = _resumo_aco(msp, res, xa, y_tab, ocupados)
    largura = xc + larg_corte - x0
    altura = (y0 + max(W, alt_corte) + 80.0) - min(fim, fim2)
    return largura, altura, desenhado


def exportar(resultados, caminho: str) -> str:
    """Grava o DXF de uma ou mais faixas (empilhadas) e devolve o caminho."""
    if not isinstance(resultados, (list, tuple)):
        resultados = [resultados]
    doc = ezdxf.new("R2010", setup=True)
    preparar(doc)
    msp = doc.modelspace()
    ocupados: list = []
    y = 0.0
    for res in resultados:
        _larg, alt, _ = desenhar(msp, res, 0.0, y, ocupados)
        y -= alt + 200.0
    doc.saveas(caminho)
    return caminho


def conferir(res, caminho: str) -> list[str]:
    """Conferências do DXF de uma faixa: toda nervura com armadura no
    desenho, rótulos ``N<n>`` de todas as posições, tabela batendo com o
    quantitativo, camadas declaradas e textos sem sobreposição."""
    import re
    problemas: list[str] = []
    doc = ezdxf.readfile(caminho)
    msp = doc.modelspace()
    if doc.header.get("$INSUNITS") != 5:
        problemas.append("INSUNITS devia ser 5 (cm)")
    usadas = {e.dxf.layer for e in msp}
    faltam = sorted(c for c in usadas if c not in doc.layers)
    if faltam:
        problemas.append(f"camadas usadas sem declarar: {faltam}")
    textos = [e.dxf.text for e in msp.query("TEXT")]
    padrao = re.compile(r"(?<![A-Za-z0-9])N(\d+)(?![0-9])")
    rotulados = {int(m) for t in textos for m in padrao.findall(t)}
    for p in res.posicoes:
        if p.numero not in rotulados:
            problemas.append(f"N{p.numero} sem rótulo no desenho")
    # toda nervura (vão) com armadura positiva ou vigota, e todo apoio com
    # negativa calculada com a barra azul
    linhas_pos = [e for e in msp.query("LINE[layer=='ARM_POSITIVA']")]
    linhas_neg = [e for e in msp.query("LINE[layer=='ARM_NEGATIVA']")]
    for i, rv in enumerate(res.vaos):
        tem_barra = rv.n_adicional > 0
        if tem_barra and len(linhas_pos) < sum(
                1 for v in res.vaos[:i + 1] if v.n_adicional > 0):
            problemas.append(f"vão {i + 1}: positiva sem barra no desenho")
    n_neg = sum(1 for p in res.posicoes if p.descricao.startswith("Negativa"))
    if len(linhas_neg) < n_neg:
        problemas.append(f"{n_neg} negativas e {len(linhas_neg)} barras "
                         f"desenhadas")
    massa_tab = sum(p.massa for p in res.posicoes)
    massa_q = sum(d["massa"] for d in por_bitola(res).values()) + sum(
        d["massa"] for d in trelicas(res).values())
    if abs(massa_tab - massa_q) > 1e-6 or \
            abs(massa_tab - res.quantitativo.get("aco_kg", 0.0)) > 1e-6:
        problemas.append(f"tabela {massa_tab:.2f} kg x quantitativo "
                         f"{massa_q:.2f} kg x aco_kg "
                         f"{res.quantitativo.get('aco_kg', 0.0):.2f} kg")
    qp = res.quantitativo.get("por_bitola")
    if qp is not None and qp != por_bitola(res):
        problemas.append("quantitativo['por_bitola'] do motor difere do "
                         "desenho")
    for p in res.posicoes:
        if p.phi > 0 and abs(p.massa - p.quantidade * p.comprimento / 100.0
                             * massa_linear(p.phi)) > 1e-6:
            problemas.append(f"N{p.numero}: massa fora de qtd x C x kg/m")
    problemas += dxf.conferir_sobreposicoes(caminho)
    return problemas
