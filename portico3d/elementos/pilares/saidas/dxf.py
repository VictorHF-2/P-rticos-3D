# -*- coding: utf-8 -*-
"""
dxf.py
Exportação do detalhamento em DXF: seção transversal armada, elevação do lance
e a tabela de posições, cotadas e em camadas separadas.

O desenho é gerado em centímetros (INSUNITS = 5), na escala 1:1, para ser
inserido diretamente na prancha.
"""

from __future__ import annotations

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..core import geometria as geo
from ..core.dimensionar import ResultadoPilar
from ..core.materiais import massa_linear

#: Cor ACI do amarelo, usada em textos e cotas.
AMARELO = 2
CINZA = 9

#: Cor, tipo de linha e espessura (1/100 mm) de cada camada. A armadura sai
#: mais grossa que cota e texto: é o que impede confundir uma linha de cota
#: longa com uma barra, já que ambas são retas no mesmo desenho.
CAMADAS = {
    "CONCRETO": (8, "CONTINUOUS", 25),
    "ARMADURA": (1, "CONTINUOUS", 50),
    "ESTRIBO": (3, "CONTINUOUS", 35),
    "GRAMPO": (4, "CONTINUOUS", 30),
    "ESPERA": (1, "DASHED", 35),
    "TEXTO": (AMARELO, "CONTINUOUS", 13),
    "COTAS": (AMARELO, "CONTINUOUS", 13),
    "EIXO": (5, "CENTER", 13),
    "CHAMADA": (CINZA, "CONTINUOUS", 9),
    "TABELA": (CINZA, "CONTINUOUS", 18),
}

_ALINHAMENTO = {
    "left": TextEntityAlignment.LEFT,
    "center": TextEntityAlignment.MIDDLE_CENTER,
    "right": TextEntityAlignment.RIGHT,
}

ALTURA_TEXTO = 2.0
ALTURA_TITULO = 3.5


def _preparar(doc) -> None:
    doc.header["$INSUNITS"] = 5           # centímetros
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = 1
    for nome, (cor, tipo, espessura) in CAMADAS.items():
        if tipo not in doc.linetypes:
            tipo = "CONTINUOUS"
        doc.layers.add(name=nome, color=cor, linetype=tipo,
                       lineweight=espessura)
    if "PILARES" not in doc.dimstyles:
        estilo = doc.dimstyles.add("PILARES")
        estilo.dxf.dimtxt = 2.5
        estilo.dxf.dimasz = 1.8
        estilo.dxf.dimexe = 1.0
        estilo.dxf.dimexo = 1.0
        estilo.dxf.dimgap = 0.8
        estilo.dxf.dimdec = 0
        estilo.dxf.dimclrd = AMARELO
        estilo.dxf.dimclre = AMARELO
        estilo.dxf.dimclrt = AMARELO


def _texto(msp, texto: str, x: float, y: float, altura: float = ALTURA_TEXTO,
           camada: str = "TEXTO", ancora: str = "left",
           rotacao: float = 0.0) -> None:
    ent = msp.add_text(texto, height=altura,
                       dxfattribs={"layer": camada, "rotation": rotacao})
    ent.set_placement((x, y),
                      align=_ALINHAMENTO.get(ancora,
                                             TextEntityAlignment.LEFT))


def _cota(msp, p1, p2, deslocamento: float, vertical: bool = False) -> None:
    if vertical:
        dim = msp.add_linear_dim(base=(p1[0] + deslocamento, p1[1]),
                                 p1=p1, p2=p2, angle=90,
                                 dimstyle="PILARES",
                                 dxfattribs={"layer": "COTAS"})
    else:
        dim = msp.add_linear_dim(base=(p1[0], p1[1] + deslocamento),
                                 p1=p1, p2=p2, dimstyle="PILARES",
                                 dxfattribs={"layer": "COTAS"})
    dim.render()


# ---------------------------------------------------------------------------
# Seção transversal
# ---------------------------------------------------------------------------

def _cobrimento(res: ResultadoPilar) -> float:
    """Cobrimento que de fato entrou no arranjo, cm."""
    if res.arranjo is not None and res.arranjo.cobrimento > 0:
        return res.arranjo.cobrimento
    return res.pilar.ambiente.cobrimento_adotado


def _secao(msp, res: ResultadoPilar, dx: float, dy: float) -> None:
    """Seção armada, com o estribo, os grampos e as cotas."""
    p = res.pilar
    secao = p.secao
    contornos = secao.contornos()
    for i, c in enumerate(contornos):
        pts = [(x + dx, y + dy) for x, y in c]
        pts.append(pts[0])
        msp.add_lwpolyline(pts, dxfattribs={"layer": "CONCRETO"})

    est = res.estribos
    arr = res.arranjo
    if est is not None:
        recuo = _cobrimento(res) + est.phi / 20.0
        if secao.tipo in ("circular", "circular vazada"):
            msp.add_circle((dx, dy), (secao.diametro - 2 * recuo) / 2.0,
                           dxfattribs={"layer": "ESTRIBO"})
        else:
            linha = geo.deslocar_para_dentro(contornos[0], recuo)
            pts = [(x + dx, y + dy) for x, y in linha]
            pts.append(pts[0])
            msp.add_lwpolyline(pts, dxfattribs={"layer": "ESTRIBO"})

    if arr is not None:
        for b in arr.barras:
            msp.add_circle((b.x + dx, b.y + dy), arr.phi / 20.0,
                           dxfattribs={"layer": "ARMADURA"})
        _grampos_dxf(msp, res, dx, dy)

    x0, x1 = -secao.hx / 2.0, secao.hx / 2.0
    y0, y1 = -secao.hy / 2.0, secao.hy / 2.0
    _cota(msp, (x0 + dx, y0 + dy), (x1 + dx, y0 + dy), -8.0)
    _cota(msp, (x0 + dx, y0 + dy), (x0 + dx, y1 + dy), -8.0, vertical=True)
    msp.add_line((x0 - 4 + dx, dy), (x1 + 4 + dx, dy),
                 dxfattribs={"layer": "EIXO"})
    msp.add_line((dx, y0 - 4 + dy), (dx, y1 + 4 + dy),
                 dxfattribs={"layer": "EIXO"})

    _texto(msp, f"{p.nome} — SEÇÃO {secao.descricao()}", dx, y1 + dy + 8.0,
           ALTURA_TITULO, ancora="center")
    rotulos = []
    if arr is not None:
        rotulos.append(f"N1 — {arr.n_barras} ø{arr.phi:g} c/ face")
    if est is not None:
        rotulos.append(f"N2 — estribo ø{est.phi:g} c/{est.s:g}")
        if est.n_suplementares:
            rotulos.append(f"N3 — {est.n_suplementares} grampo(s) "
                           f"ø{est.phi:g} c/{est.s:g}")
    rotulos.append(f"cobrimento {_cobrimento(res):g} cm "
                   f"(CAA {p.ambiente.caa})")
    for i, t in enumerate(rotulos):
        _texto(msp, t, x0 + dx, y0 + dy - 16.0 - i * 4.0)


def _grampos_dxf(msp, res: ResultadoPilar, dx: float, dy: float) -> None:
    est, arr = res.estribos, res.arranjo
    if est is None or arr is None or not est.n_suplementares:
        return
    secao = res.pilar.secao
    if secao.tipo != "retangular":
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
        msp.add_line((x + dx, -ly + dy), (x + dx, ly + dy),
                     dxfattribs={"layer": "GRAMPO"})
    for y in interiores_y[:est.suplementares_y]:
        msp.add_line((-lx + dx, y + dy), (lx + dx, y + dy),
                     dxfattribs={"layer": "GRAMPO"})


# ---------------------------------------------------------------------------
# Elevação
# ---------------------------------------------------------------------------

def _elevacao(msp, res: ResultadoPilar, dx: float, dy: float) -> None:
    p = res.pilar
    L = p.lance.altura
    b = p.secao.hx
    msp.add_lwpolyline([(dx, dy), (dx + b, dy), (dx + b, dy + L),
                        (dx, dy + L), (dx, dy)],
                       dxfattribs={"layer": "CONCRETO"})
    arr, est, anc = res.arranjo, res.estribos, res.ancoragem
    c = _cobrimento(res)
    if arr is not None:
        for x in (c + arr.phi / 20.0, b - c - arr.phi / 20.0):
            msp.add_line((dx + x, dy), (dx + x, dy + L),
                         dxfattribs={"layer": "ARMADURA"})
            if anc is not None:
                msp.add_line((dx + x, dy + L), (dx + x, dy + L + anc.l0c),
                             dxfattribs={"layer": "ESPERA"})
    if est is not None and est.s > 0:
        n = max(int(L / est.s), 0)
        for i in range(n + 1):
            y = min(i * est.s, L)
            msp.add_line((dx + c, dy + y), (dx + b - c, dy + y),
                         dxfattribs={"layer": "ESTRIBO"})
        _texto(msp, f"{est.niveis} N2 ø{est.phi:g} c/{est.s:g}",
               dx + b + 6.0, dy + L / 2.0)
    if anc is not None:
        _texto(msp, f"espera l0c = {anc.l0c:.0f}", dx + b + 6.0,
               dy + L + anc.l0c / 2.0)
    _cota(msp, (dx, dy), (dx, dy + L), -10.0, vertical=True)
    _texto(msp, f"{p.nome} — ELEVAÇÃO DO LANCE", dx + b / 2.0,
           dy + L + (anc.l0c if anc else 0.0) + 10.0, ALTURA_TITULO,
           ancora="center")


# ---------------------------------------------------------------------------
# Tabela de posições
# ---------------------------------------------------------------------------

def _tabela(msp, res: ResultadoPilar, dx: float, dy: float) -> None:
    p = res.pilar
    arr, est, anc = res.arranjo, res.estribos, res.ancoragem
    if arr is None:
        return
    comprimento = p.lance.altura + (anc.l0c if anc else 0.0)
    linhas = [["POS", "BITOLA", "QUANT", "COMPR (cm)", "TOTAL (cm)",
               "MASSA (kg)"]]
    linhas.append(["N1", f"ø{arr.phi:g}", str(arr.n_barras),
                   f"{comprimento:.0f}",
                   f"{arr.n_barras * comprimento:.0f}",
                   f"{arr.massa(comprimento):.1f}"])
    if est is not None:
        total = est.niveis * est.comprimento
        linhas.append(["N2", f"ø{est.phi:g}", str(est.niveis),
                       f"{est.comprimento:.0f}", f"{total:.0f}",
                       f"{massa_linear(est.phi) * total / 100.0:.1f}"])
        if est.n_suplementares:
            q = est.niveis * est.n_suplementares
            tot = q * est.comprimento_suplementar
            linhas.append(["N3", f"ø{est.phi:g}", str(q),
                           f"{est.comprimento_suplementar:.0f}",
                           f"{tot:.0f}",
                           f"{massa_linear(est.phi) * tot / 100.0:.1f}"])
    linhas.append(["", "", "", "", "TOTAL", f"{res.massa_total:.1f}"])

    larguras = [8.0, 12.0, 12.0, 18.0, 18.0, 18.0]
    altura = 6.0
    largura = sum(larguras)
    _texto(msp, "TABELA DE POSIÇÕES", dx + largura / 2.0,
           dy + altura + 4.0, ALTURA_TITULO, ancora="center")
    for i, linha in enumerate(linhas):
        y = dy - i * altura
        msp.add_lwpolyline([(dx, y), (dx + largura, y),
                            (dx + largura, y - altura), (dx, y - altura),
                            (dx, y)], dxfattribs={"layer": "TABELA"})
        x = dx
        for larg, valor in zip(larguras, linha):
            if x > dx:
                msp.add_line((x, y), (x, y - altura),
                             dxfattribs={"layer": "TABELA"})
            _texto(msp, str(valor), x + larg / 2.0, y - altura / 2.0,
                   ALTURA_TEXTO, ancora="center")
            x += larg


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def exportar(res: ResultadoPilar, caminho: str) -> str:
    """Grava o DXF do detalhamento e devolve o caminho do arquivo."""
    doc = ezdxf.new("R2010", setup=True)
    _preparar(doc)
    msp = doc.modelspace()

    secao = res.pilar.secao
    L = res.pilar.lance.altura
    _secao(msp, res, 0.0, 0.0)
    _elevacao(msp, res, secao.hx / 2.0 + 60.0, -L / 2.0)
    _tabela(msp, res, secao.hx / 2.0 + 60.0 + secao.hx + 60.0, L / 2.0)

    doc.saveas(caminho)
    return caminho


# ---------------------------------------------------------------------------
# Projeto: um arquivo com todas as peças
# ---------------------------------------------------------------------------

#: Folga entre um lance e o seguinte na prancha, cm.
FOLGA_ENTRE_PILARES = 120.0


def _quadro_projeto(msp, res_projeto, dx: float, dy: float) -> None:
    """O quadro de quantidades do projeto, desenhado na prancha.

    Concreto, formas e aço por lance, com os totais -- o mesmo conteúdo da
    planilha do projeto, para a prancha não depender de outro arquivo para
    ser lida.
    """
    Q = res_projeto.quantitativo
    linhas = [["PILAR", "SEÇÃO", "CONCR.", "VOL (m³)", "FORMAS (m²)",
               "AÇO (kg)"]]
    for q in Q.itens:
        linhas.append([q.nome, q.secao, q.concreto,
                       f"{q.volume_concreto:.3f}", f"{q.area_formas:.2f}",
                       f"{q.massa_aco:.1f}"])
    linhas.append(["TOTAL", f"{len(Q.itens)} lance(s)", "",
                   f"{Q.volume_concreto:.3f}", f"{Q.area_formas:.2f}",
                   f"{Q.massa_aco:.1f}"])
    for phi, massa in Q.aco_por_bitola.items():
        linhas.append(["", f"aço ø{phi:g} mm", "", "", "",
                       f"{massa:.1f}"])

    larguras = [14.0, 46.0, 14.0, 18.0, 22.0, 18.0]
    altura = 6.0
    largura = sum(larguras)
    _texto(msp, f"QUADRO DE QUANTIDADES — {res_projeto.projeto.nome}",
           dx + largura / 2.0, dy + altura + 4.0, ALTURA_TITULO,
           ancora="center")
    for i, linha in enumerate(linhas):
        y = dy - i * altura
        msp.add_lwpolyline([(dx, y), (dx + largura, y),
                            (dx + largura, y - altura), (dx, y - altura),
                            (dx, y)], dxfattribs={"layer": "TABELA"})
        x = dx
        for larg, valor in zip(larguras, linha):
            if x > dx:
                msp.add_line((x, y), (x, y - altura),
                             dxfattribs={"layer": "TABELA"})
            _texto(msp, str(valor), x + larg / 2.0, y - altura / 2.0,
                   ALTURA_TEXTO, ancora="center")
            x += larg


def exportar_projeto(res_projeto, caminho: str) -> str:
    """Grava **um** DXF com o detalhamento de todos os lances do projeto.

    Cada lance ocupa uma faixa vertical da prancha -- corte, elevação e
    tabela de posições, o mesmo conteúdo que :func:`exportar` produz para um
    pilar só --, e o quadro de quantidades consolidado fecha o desenho à
    direita. Os lances que não calcularam não entram: não há o que detalhar,
    e a planilha do projeto os relaciona nomeados.

    A largura de cada faixa sai da própria peça, de modo que um pilar largo
    não invade o vizinho; a folga entre faixas é fixa.
    """
    doc = ezdxf.new("R2010", setup=True)
    _preparar(doc)
    msp = doc.modelspace()

    x = 0.0
    for res in res_projeto.resultados:
        if res.arranjo is None:
            continue
        secao = res.pilar.secao
        L = res.pilar.lance.altura
        _texto(msp, f"PILAR {res.pilar.nome}", x + secao.hx / 2.0,
               secao.hy / 2.0 + 22.0, ALTURA_TITULO, ancora="center")
        _secao(msp, res, x + secao.hx / 2.0, 0.0)
        _elevacao(msp, res, x + secao.hx + 60.0, -L / 2.0)
        _tabela(msp, res, x + secao.hx + 60.0 + secao.hx + 60.0, L / 2.0)
        # a faixa é o que a peça de fato ocupou: corte, elevação e tabela
        x += secao.hx + 60.0 + secao.hx + 60.0 + 130.0 + FOLGA_ENTRE_PILARES

    if res_projeto.resultados:
        _quadro_projeto(msp, res_projeto, x, 0.0)

    doc.saveas(caminho)
    return caminho


def conferir(caminho: str) -> list[str]:
    """Relê o DXF gravado e confere que ele tem o que deveria ter.

    Um DXF que abre vazio no CAD é o pior desfecho possível: o arquivo existe,
    o programa não reclamou, e só se descobre na prancha. Esta função existe
    para o autoteste poder afirmar que há concreto, armadura e cota no
    desenho.
    """
    problemas: list[str] = []
    doc = ezdxf.readfile(caminho)
    msp = doc.modelspace()
    por_camada: dict[str, int] = {}
    for e in msp:
        camada = e.dxf.layer
        por_camada[camada] = por_camada.get(camada, 0) + 1
    for camada in ("CONCRETO", "ARMADURA", "ESTRIBO", "TEXTO"):
        if not por_camada.get(camada):
            problemas.append(f"o DXF não tem nenhuma entidade na camada "
                             f"{camada}")
    if not any(e.dxftype() == "DIMENSION" for e in msp):
        problemas.append("o DXF não tem nenhuma cota")
    return problemas
