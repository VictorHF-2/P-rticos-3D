# -*- coding: utf-8 -*-
"""
dxf.py
Exportação do detalhamento em DXF: elevação da viga com as armaduras e as
seções transversais pedidas pelo usuário, cotadas e em camadas separadas.

O desenho é gerado em centímetros (INSUNITS = 5), na escala 1:1, para ser
inserido diretamente na prancha.
"""

from __future__ import annotations

import ezdxf
from ezdxf.enums import TextEntityAlignment

from ..core.dimensionar import ResultadoViga
from . import geometria

#: Cor ACI do amarelo, usada em textos e cotas.
AMARELO = 2
CINZA = 9

#: Cor, tipo de linha e espessura (1/100 mm) de cada camada. A armadura sai
#: mais grossa que cota e texto: é o que impede confundir uma linha de cota
#: longa com uma barra, já que ambas são horizontais.
CAMADAS = {
    "CONCRETO": (8, "CONTINUOUS", 25),
    "APOIO": (9, "CONTINUOUS", 18),
    "ARMADURA_SUP": (5, "CONTINUOUS", 50),
    "ARMADURA_INF": (1, "CONTINUOUS", 50),
    "PELE": (6, "CONTINUOUS", 35),
    "ESTRIBO": (3, "CONTINUOUS", 25),
    "TEXTO": (AMARELO, "CONTINUOUS", 13),
    "COTAS": (AMARELO, "CONTINUOUS", 13),
    "EIXO": (5, "CENTER", 13),
    # a linha de chamada do rótulo cruza as cotas dos estribos; em cinza
    # próprio ela deixa de competir com o amarelo das cotas e do texto
    "CHAMADA": (CINZA, "CONTINUOUS", 9),
    # o limite da faixa é a linha de chamada da cota do trecho: mesma cor
    "ZONA": (AMARELO, "DASHED", 18),
}

_ALINHAMENTO = {
    "left": TextEntityAlignment.LEFT,
    "center": TextEntityAlignment.MIDDLE_CENTER,
    "right": TextEntityAlignment.RIGHT,
}


def _preparar(doc) -> None:
    doc.header["$INSUNITS"] = 5           # centímetros
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = 1           # mostra as espessuras no CAD
    for nome, (cor, tipo, espessura) in CAMADAS.items():
        if tipo not in doc.linetypes:
            tipo = "CONTINUOUS"
        doc.layers.add(name=nome, color=cor, linetype=tipo,
                       lineweight=espessura)
    if "VIGAS" not in doc.dimstyles:
        estilo = doc.dimstyles.add("VIGAS")
        estilo.dxf.dimtxt = 6.0
        estilo.dxf.dimasz = 4.0
        estilo.dxf.dimexe = 2.0
        estilo.dxf.dimexo = 2.0
        estilo.dxf.dimgap = 1.5
        estilo.dxf.dimdec = 0        # o desenho é em cm inteiros
        # a geometria interna da cota nasce na camada 0; sem fixar a cor aqui,
        # linha e chamada saem brancas mesmo com a DIMENSION na camada COTAS
        estilo.dxf.dimclrd = AMARELO      # linha de cota
        estilo.dxf.dimclre = AMARELO      # linhas de chamada
        estilo.dxf.dimclrt = AMARELO      # texto


def _polilinha(msp, pol: geometria.Polilinha, dx: float = 0.0,
               dy: float = 0.0) -> None:
    pts = [(p[0] + dx, p[1] + dy) for p in pol.pontos]
    if pol.fechada:
        pts.append(pts[0])
    msp.add_lwpolyline(pts, dxfattribs={"layer": pol.camada})


def _texto(msp, t: geometria.Texto, dx: float = 0.0, dy: float = 0.0) -> None:
    ent = msp.add_text(t.texto, height=t.altura,
                       dxfattribs={"layer": t.camada, "rotation": t.rotacao})
    ent.set_placement((t.posicao[0] + dx, t.posicao[1] + dy),
                      align=_ALINHAMENTO.get(t.ancora, TextEntityAlignment.LEFT))


def exportar(res: ResultadoViga, caminho: str, secoes_m=None,
             mostrar_estribos: bool = True) -> str:
    """Grava o DXF do detalhamento e devolve o caminho do arquivo.

    ``secoes_m`` aceita abscissas ou pares ``(x, descrição)``.
    """
    from .desenho import normalizar_secoes

    doc = ezdxf.new("R2013", setup=True)
    _preparar(doc)
    msp = doc.modelspace()

    el = geometria.montar_elevacao(res, mostrar_estribos)
    for pol in el.contorno + el.apoios + el.estribos + el.barras + el.zonas:
        _polilinha(msp, pol)

    # cotas das faixas de estribos: o rótulo vai dentro da própria cota, então
    # o trecho que cada espaçamento cobre fica explícito
    for xa, xb, y, rotulo in el.cotas_estribo:
        dim = msp.add_linear_dim(base=(0.0, y), p1=(xa, y), p2=(xb, y),
                                 text=f"{rotulo} <>", dimstyle="VIGAS",
                                 dxfattribs={"layer": "COTAS"})
        dim.render()
    for t in el.textos:
        _texto(msp, t)
        if t.chamada is not None:
            msp.add_line(t.chamada, (t.posicao[0], t.posicao[1]),
                         dxfattribs={"layer": "CHAMADA"})

    # cotas dos vãos
    for xa, xb, y, _rotulo in el.cotas:
        dim = msp.add_linear_dim(base=(0, y), p1=(xa, 0), p2=(xb, 0),
                                 dimstyle="VIGAS",
                                 dxfattribs={"layer": "COTAS"})
        dim.render()

    # eixos dos apoios -- desenhados depois, quando a altura da vista
    # explodida já for conhecida, para atravessarem o desenho todo

    # título
    _texto(msp, geometria.Texto(
        f"VIGA {res.viga.nome} - DETALHAMENTO (cotas em cm)",
        ((el.x_min + el.x_max) / 2.0, el.h_max + 115.0), altura=10.0,
        ancora="center"))

    # vista explodida das armaduras, logo abaixo da viga
    barras = geometria.montar_explodida(res)
    postas, altura_explodida = geometria.dispor_explodidas(barras)
    y_explodida = el.y_min - 75.0
    if postas:
        _texto(msp, geometria.Texto(
            "ARMADURAS EXPLODIDAS - CADA BARRA SOB A SUA POSICAO NA VIGA "
            "- COMPRIMENTOS EM cm",
            (el.x_min, y_explodida + 30.0), altura=9.0, ancora="left"))
        for barra, x_barra, dy in postas:
            _barra_explodida(msp, barra, x_barra, y_explodida + dy)

    # eixos dos apoios, atravessando a elevação e a vista explodida
    y_eixo = y_explodida - altura_explodida - 30.0
    for x_eixo, nome in el.eixos:
        msp.add_line((x_eixo, y_eixo), (x_eixo, el.h_max + 25.0),
                     dxfattribs={"layer": "EIXO"})
        _texto(msp, geometria.Texto(nome, (x_eixo, y_eixo - 12.0), altura=6.0,
                                    camada="EIXO", ancora="center"))

    # seções transversais, alinhadas abaixo da vista explodida
    pedidas = normalizar_secoes(res, secoes_m)
    y_base = y_explodida - altura_explodida - 280.0
    x_atual = el.x_min
    for i, (xm, nome) in enumerate(pedidas):
        sec = geometria.montar_secao(res, xm, nome.upper())
        # o passo é o maior entre a seção e o seu rótulo mais largo: a seção de
        # 20 cm com um rótulo de 80 caracteres ocupa 280 cm de papel, e um
        # passo fixo punha o rótulo de uma dentro do da vizinha
        rotulos = [largura_texto(t.texto, t.altura) for t in sec.textos]
        rotulos.append(largura_texto(f"{sec.nome}  (x = {xm:.2f} m)", 5.5))
        largura = max(sec.largura + 60.0, 185.0, max(rotulos) + 30.0)
        dx = x_atual - min(p[0] for p in sec.contorno.pontos)
        dy = y_base
        _polilinha(msp, sec.contorno, dx, dy)
        _polilinha(msp, sec.estribo, dx, dy)
        for c in sec.barras:
            msp.add_circle((c.centro[0] + dx, c.centro[1] + dy),
                           max(c.raio, 0.4), dxfattribs={"layer": c.camada})
        for t in sec.textos:
            _texto(msp, t, dx, dy)
        _texto(msp, geometria.Texto(
            f"{sec.nome}  (x = {xm:.2f} m)",
            (sec.largura / 2.0, sec.altura + 20.0), altura=5.5,
            ancora="center"), dx, dy)
        x_atual += largura

    _tabela_posicoes(msp, res, el.x_max + 80.0, el.h_max)

    doc.saveas(caminho)
    return caminho


#: largura de um caractere, em frações da altura do texto. Aproximação boa o
#: bastante para pegar colisão real de rótulo, que é o que torna a prancha
#: ilegível
LARGURA_CARACTERE = 0.62


def largura_texto(texto: str, altura: float) -> float:
    """Largura estimada de um texto, nas unidades do desenho.

    Uma função, usada por quem **posiciona** e por quem **confere**. Eram duas
    contas para a mesma coisa, e a que posicionava não sabia que os rótulos
    tinham crescido: com a seção variável o rótulo da seção passou a dizer de
    que tramo vem cada barra, ficou três vezes mais longo, e as seções vizinhas
    se sobrepuseram.
    """
    return LARGURA_CARACTERE * altura * len(texto)


def conferir_sobreposicoes(caminho: str) -> list[str]:
    """Lista pares de textos que se sobrepõem no DXF gravado.

    A largura de cada texto é estimada em 0,62 vez a altura por caractere --
    aproximação boa o bastante para pegar colisão real de rótulo, que é o que
    torna a prancha ilegível. Serve de rede de proteção no autoteste: qualquer
    mudança de posição de rótulo que volte a colidir aparece aqui.
    """
    doc = ezdxf.readfile(caminho)
    caixas = []
    for e in doc.modelspace().query("TEXT"):
        altura, texto = e.dxf.height, e.dxf.text
        if not texto.strip():
            continue
        larg = largura_texto(texto, altura)
        centrado = e.dxf.halign == 1 or e.dxf.valign == 2
        ponto = e.dxf.align_point if (e.dxf.halign or e.dxf.valign)             else e.dxf.insert
        x0 = ponto.x - larg / 2.0 if centrado else ponto.x
        caixas.append((x0, ponto.y - altura / 2.0, x0 + larg,
                       ponto.y + altura / 2.0, texto))
    problemas = []
    for i, a in enumerate(caixas):
        for b in caixas[i + 1:]:
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                problemas.append(f"textos sobrepostos: {a[4]!r} x {b[4]!r}")
    return problemas


def _barra_explodida(msp, barra: geometria.BarraExplodida, x0: float,
                     y0: float) -> None:
    """Desenha uma barra isolada, cotada trecho a trecho, na escala 1:1."""

    pts = [(p[0] + x0, p[1] + y0) for p in barra.pontos]
    msp.add_lwpolyline(pts + ([pts[0]] if barra.fechada else []),
                       dxfattribs={"layer": barra.camada})

    # a lista de segmentos já vem sem medidas repetidas, de `montar_explodida`
    # A cota vai no primeiro nível em que não encosta em nenhuma já posta --
    # mesma ideia do `rotular` da elevação. Um afastamento fixo bastava
    # enquanto os segmentos eram longos; em dois segmentos curtos vizinhos, como
    # o lado de 12 cm de um estribo e a ponta de 5 cm do gancho dele, as duas
    # cotas caíam a 3,5 cm uma da outra e se tocavam
    postos: list[tuple[float, float, float, float]] = []
    for (a, b, comp) in barra.segmentos:
        ax_, ay = a[0] + x0, a[1] + y0
        bx, by = b[0] + x0, b[1] + y0
        dx, dy = bx - ax_, by - ay
        nx, ny = geometria.direcao_cota(barra, a, b)
        texto = f"{comp:.0f}"
        vertical = abs(dx) < abs(dy)
        lg = largura_texto(texto, 4.5)
        larg, alt = (4.5, lg) if vertical else (lg, 4.5)
        for nivel in range(4):
            cx = (ax_ + bx) / 2.0 + nx * (7.0 + 6.0 * nivel)
            cy = (ay + by) / 2.0 + ny * (7.0 + 6.0 * nivel)
            caixa = (cx - larg / 2.0, cy - alt / 2.0,
                     cx + larg / 2.0, cy + alt / 2.0)
            if not any(caixa[0] < q[2] and q[0] < caixa[2]
                       and caixa[1] < q[3] and q[1] < caixa[3]
                       for q in postos):
                break
        postos.append(caixa)
        _texto(msp, geometria.Texto(
            texto, (cx, cy), altura=4.5, camada="COTAS", ancora="center",
            rotacao=90.0 if vertical else 0.0))

    # cota de raio das dobras: DIMENSION de raio, associativa, do centro do
    # arco ao arco. Como texto no identificador o raio competia com o
    # comprimento e não apontava para nada
    for (centro, meio, _raio) in barra.raios:
        dim = msp.add_radius_dim(
            center=(centro[0] + x0, centro[1] + y0),
            mpoint=(meio[0] + x0, meio[1] + y0),
            dimstyle="VIGAS", dxfattribs={"layer": "COTAS"})
        dim.render()

    # traspasse: apenas a cota entre as extremidades das duas barras
    for (a, b, l0t, rotulo) in barra.emendas:
        xa, xb = a[0] + x0, b[0] + x0
        y_barra = a[1] + y0
        y_cota = y_barra - 14.0
        # cota associativa: mede o próprio trecho de sobreposição
        dim = msp.add_linear_dim(base=(0.0, y_cota), p1=(xa, y_barra),
                                 p2=(xb, y_barra), dimstyle="VIGAS",
                                 dxfattribs={"layer": "COTAS"})
        dim.render()

    # cota de locação da barra a partir do eixo de apoio de referência
    if barra.referencia is not None:
        x_ref, nome, dist = barra.referencia
        y_cota = y0 + barra.altura + 16.0
        if abs(dist) > 8.0:
            dim = msp.add_linear_dim(base=(0.0, y_cota),
                                     p1=(min(x_ref, x0), y_cota),
                                     p2=(max(x_ref, x0), y_cota),
                                     text=f"{nome}+{abs(dist):.0f}",
                                     dimstyle="VIGAS",
                                     dxfattribs={"layer": "COTAS"})
            dim.render()
        else:
            _texto(msp, geometria.Texto(
                f"NO EIXO DE {nome}", (x0 + 3.0, y_cota), altura=4.0,
                camada="COTAS", ancora="left"))

    recuo = 32.0 if barra.fechada else 20.0
    _texto(msp, geometria.Texto(
        barra.rotulo, (x0 + barra.largura / 2.0, y0 - recuo), altura=5.5,
        camada="TEXTO", ancora="center"))


def _tabela_posicoes(msp, res: ResultadoViga, x0: float, y0: float) -> None:
    """Escreve o resumo de aço ao lado do desenho."""
    linhas = [("POS", "QUANT", "BITOLA", "COMPR. (cm)", "TOTAL (m)")]
    for p in res.posicoes:
        linhas.append((f"N{p.numero}", p.texto_quantidade, f"Ø{p.phi:g}",
                       f"{p.comprimento:.0f}", f"{p.comprimento_total:.1f}"))
    q = res.quantitativo
    linhas.append(("", "", "", "TOTAL", f"{q['massa_total']:.1f} kg"))
    linhas.append(("", "", "", "COM 10 % DE PERDAS",
                   f"{q['massa_com_perdas']:.1f} kg"))
    linhas.append(("", "", "", "", ""))
    linhas.append(("", "", "", "CONCRETO", f"{q['concreto_m3']:.3f} m3"))
    linhas.append(("", "", "", "FORMAS", f"{q['forma_m2']:.2f} m2"))
    linhas.append(("", "", "", "TAXA DE ACO", f"{q['taxa_aco']:.1f} kg/m3"))

    alturas = 10.0
    colunas = (0.0, 32.0, 66.0, 108.0, 178.0)
    for i, linha in enumerate(linhas):
        y = y0 - i * alturas
        for c, texto in zip(colunas, linha):
            _texto(msp, geometria.Texto(texto, (x0 + c, y), altura=5.0,
                                        ancora="left"))
