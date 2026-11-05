# -*- coding: utf-8 -*-
"""
dxf.py
Exportação do pavimento em DXF: planta de formas, planta de armação da face
inferior, planta de armação da face superior e tabela de posições.

O desenho sai em centímetros (INSUNITS = 5), na escala 1:1, para ser inserido
direto na prancha. As três plantas saem **lado a lado** no mesmo arquivo,
afastadas pela largura do pavimento mais uma folga -- é assim que a prancha de
laje é montada, e o CAD permite mover cada uma para a sua folha.

As camadas separam o que se sobrepõe no papel:

    FORMA / EIXO ..... contorno das lajes e eixos dos apoios
    SISTEMA .......... sentido do vão das lajes treliçada, alveolar e
                       nervurada atribuídas na planta (R09)
    VIGA ............. faixa de apoio de cada bordo, tracejada
    ARM_POSITIVA ..... armadura da face inferior, vermelha
    ARM_NEGATIVA ..... armadura da face superior, azul
    ARM_DISTRIB ...... armadura de distribuição, verde
    ARM_CONTORNO ..... armadura de contorno de borda, magenta
    TEXTO / COTAS .... rótulos e cotas, em amarelo
    CHAMADA .......... linhas de chamada dos rótulos, em cinza

As camadas de armadura saem com espessura maior que as de cota, para uma
linha de cota longa não se confundir com uma barra.

As duas plantas de armação saem sempre **esquemáticas** -- uma barra
representativa por posição, com o gancho "deitado" (um traço perpendicular
na ponta, não uma continuação reta da barra) e a cota da faixa onde ela se
repete -- em vez da grade cheia de dezenas de barras paralelas que a tela
mostra por padrão. Um círculo marca onde a barra cruza essa cota, e cada
trecho -- reto e gancho -- tem o próprio comprimento escrito ao lado. É a
planta que vai para a obra, e a grade cheia em papel A1 vira ruído; ver
``desenho.figura_armadura_positiva`` / ``figura_armadura_negativa`` para a
versão com a grade, útil na tela.
"""

from __future__ import annotations

import ezdxf
from ezdxf.enums import TextEntityAlignment

from . import graficos

#: Cores ACI.
VERMELHO, AMARELO, VERDE, AZUL, MAGENTA, CINZA_ACI, PRETO = 1, 2, 3, 5, 6, 9, 8

#: Cor, tipo de linha e espessura (1/100 mm) de cada camada.
CAMADAS = {
    "FORMA": (PRETO, "CONTINUOUS", 35),
    "EIXO": (AZUL, "CENTER", 13),
    "SISTEMA": (30, "CONTINUOUS", 18),
    "ARM_POSITIVA": (VERMELHO, "CONTINUOUS", 35),
    "ARM_NEGATIVA": (AZUL, "CONTINUOUS", 35),
    "ARM_DISTRIB": (VERDE, "CONTINUOUS", 25),
    "ARM_CONTORNO": (MAGENTA, "CONTINUOUS", 25),
    "TEXTO": (AMARELO, "CONTINUOUS", 13),
    "COTAS": (AMARELO, "CONTINUOUS", 13),
    "CHAMADA": (CINZA_ACI, "CONTINUOUS", 9),
    "ENGASTE": (AZUL, "CONTINUOUS", 18),
    "TABELA": (PRETO, "CONTINUOUS", 18),
    "VIGA": (CINZA_ACI, "DASHED", 18),
}

#: Camada de cada natureza de armadura.
CAMADA_DA_ARMADURA = {
    "positiva": "ARM_POSITIVA",
    "negativa": "ARM_NEGATIVA",
    "distribuição": "ARM_DISTRIB",
    "contorno": "ARM_CONTORNO",
}

#: Largura média de um caractere, em frações da altura do texto.
LARGURA_CARACTERE = 0.62

#: Altura dos textos do desenho, cm.
ALTURA_ROTULO = 9.0
ALTURA_TITULO = 18.0
ALTURA_TABELA = 8.0

_ALINHAMENTO = {
    "left": TextEntityAlignment.LEFT,
    "center": TextEntityAlignment.MIDDLE_CENTER,
    "right": TextEntityAlignment.RIGHT,
}


def _preparar(doc) -> None:
    doc.header["$INSUNITS"] = 5             # centímetros
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LWDISPLAY"] = 1
    for nome, (cor, tipo, espessura) in CAMADAS.items():
        if tipo not in doc.linetypes:
            tipo = "CONTINUOUS"
        doc.layers.add(name=nome, color=cor, linetype=tipo,
                       lineweight=espessura)
    if "LAJES" not in doc.dimstyles:
        estilo = doc.dimstyles.add("LAJES")
        estilo.dxf.dimtxt = 9.0
        estilo.dxf.dimasz = 6.0
        estilo.dxf.dimexe = 3.0
        estilo.dxf.dimexo = 3.0
        estilo.dxf.dimgap = 2.0
        estilo.dxf.dimdec = 0               # o desenho é em cm inteiros
        estilo.dxf.dimclrd = AMARELO
        estilo.dxf.dimclre = AMARELO
        estilo.dxf.dimclrt = AMARELO


def _texto(msp, texto: str, x: float, y: float, altura: float = ALTURA_ROTULO,
           camada: str = "TEXTO", rotacao: float = 0.0,
           ancora: str = "center") -> None:
    ent = msp.add_text(texto, height=altura,
                       dxfattribs={"layer": camada, "rotation": rotacao})
    ent.set_placement((x, y), align=_ALINHAMENTO.get(
        ancora, TextEntityAlignment.LEFT))


def largura_texto(texto: str, altura: float) -> float:
    """Largura estimada de um texto, nas unidades do desenho."""
    return LARGURA_CARACTERE * altura * len(texto)


# ---------------------------------------------------------------------------
# Peças do desenho
# ---------------------------------------------------------------------------

#: Rótulo sem acento do tipo de laje -- o texto do DXF é ASCII.
_TIPO_ASCII = {"trelicada": "Trelicada", "alveolar": "Alveolar",
               "nervurada_uni": "Nervurada uni", "nervurada_bi": "Nervurada bi"}


def _todas_as_lajes(res) -> list:
    """As lajes do desenho: as maciças e, depois delas, as especiais."""
    lajes = [rl.laje for rl in res.lajes]
    for e in getattr(res, "especiais", []):
        for nome in e.lajes:
            laje = res.pavimento.laje(nome)
            if laje is not None:
                lajes.append(laje)
    return lajes


def _sentido_do_vao(msp, laje, dx: float, dy: float) -> None:
    """Seta dupla ao longo do vão da nervura (ou do painel), deslocada do
    centro -- onde está o rótulo -- para um quarto da largura."""
    if laje.tipo == "nervurada_bi":
        return
    x0, y0, x1, y1 = (v * 100.0 for v in laje.retangulo)
    eixo = laje.direcao_global(laje.direcao)
    if eixo == "X":
        y = y0 + (y1 - y0) * 0.22 + dy
        a, b = (x0 + 25.0 + dx, y), (x1 - 25.0 + dx, y)
        s = 12.0
        pontas = [((a[0] + s, y + s / 2), a, (a[0] + s, y - s / 2)),
                  ((b[0] - s, y + s / 2), b, (b[0] - s, y - s / 2))]
    else:
        x = x0 + (x1 - x0) * 0.22 + dx
        a, b = (x, y0 + 25.0 + dy), (x, y1 - 25.0 + dy)
        s = 12.0
        pontas = [((x + s / 2, a[1] + s), a, (x - s / 2, a[1] + s)),
                  ((x + s / 2, b[1] - s), b, (x - s / 2, b[1] - s))]
    msp.add_line(a, b, dxfattribs={"layer": "SISTEMA"})
    for p1, p2, p3 in pontas:
        msp.add_lwpolyline([p1, p2, p3], dxfattribs={"layer": "SISTEMA"})


def _forma(msp, res, dx: float, dy: float, com_vinculo: bool = True,
           ocupados: list | None = None) -> None:
    """Contorno das lajes, nome, espessura e símbolo de vinculação.

    O rótulo do nome da laje entra em ``ocupados`` para que os rótulos de
    armadura, que nascem no mesmo centro, saibam desviar dele. Nas lajes
    especiais o rótulo diz também o sistema e o perfil, e uma seta marca o
    sentido do vão.
    """
    for laje in _todas_as_lajes(res):
        x0, y0, x1, y1 = (v * 100.0 for v in laje.retangulo)
        msp.add_lwpolyline(
            [(x0 + dx, y0 + dy), (x1 + dx, y0 + dy), (x1 + dx, y1 + dy),
             (x0 + dx, y1 + dy), (x0 + dx, y0 + dy)],
            dxfattribs={"layer": "FORMA"})
        rotulo = f"{laje.nome}  (h = {laje.h:g})"
        altura = ALTURA_ROTULO * 1.3
        cx, cy = (x0 + x1) / 2.0 + dx, (y0 + y1) / 2.0 + dy
        _texto(msp, rotulo, cx, cy, altura)
        if ocupados is not None:
            larg = largura_texto(rotulo, altura)
            ocupados.append((cx - larg / 2.0, cy - altura / 2.0,
                             cx + larg / 2.0, cy + altura / 2.0))
        if laje.especial:
            sistema = _TIPO_ASCII[laje.tipo] + (
                f" {laje.perfil}" if laje.perfil else "")
            if laje.tipo != "nervurada_bi":
                sistema += f", vao em {laje.direcao_global(laje.direcao)}"
            alt2 = ALTURA_ROTULO * 0.9
            cy2 = cy - altura * 1.6
            _texto(msp, sistema, cx, cy2, alt2, "SISTEMA")
            if ocupados is not None:
                larg = largura_texto(sistema, alt2)
                ocupados.append((cx - larg / 2.0, cy2 - alt2 / 2.0,
                                 cx + larg / 2.0, cy2 + alt2 / 2.0))
            _sentido_do_vao(msp, laje, dx, dy)
        if not com_vinculo:
            continue
        for bordo in (1, 2, 3, 4):
            b = laje.bordos[bordo - 1]
            bx0, by0, bx1, by1 = (v * 100.0 for v in
                                  laje.segmento_do_bordo(bordo))
            if b.vinculo != "engastado":
                continue
            # hachura do engaste: tracinhos para dentro da laje
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            mx, my = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
            ux, uy = cx - mx, cy - my
            norma = (ux * ux + uy * uy) ** 0.5 or 1.0
            ux, uy = ux / norma * 12.0, uy / norma * 12.0
            comprimento = ((bx1 - bx0) ** 2 + (by1 - by0) ** 2) ** 0.5
            n = max(int(comprimento / 25.0), 2)
            for k in range(n + 1):
                t = k / n
                px = bx0 + (bx1 - bx0) * t
                py = by0 + (by1 - by0) * t
                msp.add_line((px + dx, py + dy), (px + ux + dx, py + uy + dy),
                             dxfattribs={"layer": "ENGASTE"})


def _barras_da_posicao(pos) -> list[float]:
    """Coordenadas transversais das barras da posição, em cm."""
    if pos.quantidade <= 1:
        return [(pos.faixa_inicio + pos.faixa_fim) / 2.0]
    passo = (pos.faixa_fim - pos.faixa_inicio) / (pos.quantidade - 1)
    return [pos.faixa_inicio + k * passo for k in range(pos.quantidade)]


def _camada(pos) -> str:
    for chave, camada in CAMADA_DA_ARMADURA.items():
        if pos.tipo.startswith(chave):
            return camada
    return "ARM_POSITIVA"


def _vigas(msp, res, dx: float, dy: float) -> None:
    """Faixa de viga de cada bordo com apoio, centrada na linha do bordo --
    a mesma regra do desenho esquemático em matplotlib (ver
    ``graficos._vigas``): t/2 para dentro da laje, t/2 para fora, e nada no
    bordo livre. É o que deixa visível até onde a positiva reta pode ir sem
    aflorar na face externa da viga.
    """
    for laje in _todas_as_lajes(res):
        x0, y0, x1, y1 = (v * 100.0 for v in laje.retangulo)
        for bordo in (1, 2, 3, 4):
            b = laje.bordos[bordo - 1]
            if b.vinculo == "livre" or b.t <= 0.0:
                continue
            bx0, by0, bx1, by1 = (v * 100.0 for v in
                                  laje.segmento_do_bordo(bordo))
            t = b.t
            vertical = abs(bx1 - bx0) < 1e-6
            if vertical:
                cx0, cy0 = bx0 - t / 2.0, by0
                cx1, cy1 = bx0 + t / 2.0, by1
            else:
                cx0, cy0 = bx0, by0 - t / 2.0
                cx1, cy1 = bx1, by0 + t / 2.0
            msp.add_lwpolyline(
                [(cx0 + dx, cy0 + dy), (cx1 + dx, cy0 + dy),
                 (cx1 + dx, cy1 + dy), (cx0 + dx, cy1 + dy),
                 (cx0 + dx, cy0 + dy)], dxfattribs={"layer": "VIGA"})


def _gancho_perpendicular(msp, x: float, y: float, eixo: str,
                          comprimento: float, camada: str) -> None:
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
    if eixo == "X":
        msp.add_line((x, y), (x, y + comprimento), dxfattribs={"layer": camada})
    else:
        msp.add_line((x, y), (x + comprimento, y), dxfattribs={"layer": camada})


#: Raio do círculo que marca onde a barra cruza a cota da faixa, cm.
RAIO_MARCA = 4.0


def _texto_segmento(msp, x0: float, y0: float, texto: str, camada: str,
                    ocupados: list, rotacao: float = 0.0, dx: float = 0.0,
                    dy: float = 1.0) -> None:
    """Comprimento de um trecho (reto ou gancho), escrito perto dele.

    Nasce colado no trecho a que se refere -- é dali que vem a leitura
    rápida --, mas cede quando cai em cima de algo já desenhado (o nome da
    laje, no meio dela, é o caso mais comum): empurra na direção própria
    (``dx``/``dy``, para longe da barra) até achar espaço livre, e uma linha
    de chamada liga o texto de volta ao ponto de origem quando ele se move.
    """
    altura = ALTURA_ROTULO * 0.6
    largura = largura_texto(texto, altura)
    vertical = abs(rotacao) > 1e-6
    passo = altura * 1.6
    x, y = x0, y0
    for tentativa in range(30):
        if vertical:
            caixa = (x - altura / 2.0, y - largura / 2.0,
                     x + altura / 2.0, y + largura / 2.0)
        else:
            caixa = (x - largura / 2.0, y - altura / 2.0,
                     x + largura / 2.0, y + altura / 2.0)
        if not any(caixa[0] < o[2] and o[0] < caixa[2]
                   and caixa[1] < o[3] and o[1] < caixa[3] for o in ocupados):
            break
        deslocamento = passo * (tentativa + 1)
        x, y = x0 + dx * deslocamento, y0 + dy * deslocamento
    else:
        caixa = (x, y, x, y)
    ocupados.append(caixa)
    _texto(msp, texto, x, y, altura, camada, rotacao=rotacao)
    if abs(x - x0) > 1e-6 or abs(y - y0) > 1e-6:
        msp.add_line((x0, y0), (x, y), dxfattribs={"layer": "CHAMADA"})


def _armadura(msp, posicoes, dx: float, dy: float,
              ocupados: list) -> None:
    """Desenha uma barra representativa por posição -- sempre esquemático.

    Em vez da grade cheia (dezenas de barras paralelas), uma linha só --
    reta, do trecho reto (sem escalonar). O gancho, quando existe, é um
    traço perpendicular na ponta (ver ``_gancho_perpendicular``), não uma
    continuação reta da barra -- e cada trecho, reto ou gancho, tem o
    próprio comprimento escrito ao lado (``_texto_segmento``), então o
    rótulo geral da posição não precisa repetir o gancho por extenso. O
    ponto transversal em que a barra é desenhada não é sempre o meio da
    faixa (ver ``graficos.centro_faixa_pos``): duas lajes vizinhas com a
    mesma faixa, ambas centradas, pareceriam uma barra só atravessando as
    duas -- e é onde a barra cruza a cota da faixa que entra um círculo,
    amarrando esta posição à cota que descreve a faixa inteira; o rótulo
    geral parte dali. A prancha DXF é o desenho que sai para a obra, e é aí
    que a legibilidade de "onde entra e até onde cobre" importa mais que a
    densidade de traço.
    """
    for pos in posicoes:
        camada = _camada(pos)
        centro_faixa = graficos.centro_faixa_pos(pos)
        if pos.eixo == "X":
            msp.add_line((pos.inicio + dx, centro_faixa + dy),
                         (pos.fim + dx, centro_faixa + dy),
                         dxfattribs={"layer": camada})
            if pos.gancho_inicio > 0.0:
                _gancho_perpendicular(msp, pos.inicio + dx, centro_faixa + dy,
                                      "X", pos.gancho_inicio, camada)
                _texto_segmento(
                    msp, pos.inicio + dx, centro_faixa + dy +
                    pos.gancho_inicio + 3.0, f"{pos.gancho_inicio:.0f}",
                    camada, ocupados, rotacao=90.0, dx=0.0, dy=1.0)
            if pos.gancho_fim > 0.0:
                _gancho_perpendicular(msp, pos.fim + dx, centro_faixa + dy,
                                      "X", pos.gancho_fim, camada)
                _texto_segmento(
                    msp, pos.fim + dx, centro_faixa + dy + pos.gancho_fim +
                    3.0, f"{pos.gancho_fim:.0f}", camada, ocupados,
                    rotacao=90.0, dx=0.0, dy=1.0)
            _texto_segmento(msp, (pos.inicio + pos.fim) / 2.0 + dx,
                            centro_faixa + dy - 4.0,
                            f"{pos.trecho_reto:.0f}", camada, ocupados,
                            dx=0.0, dy=-1.0)
            xc = pos.fim + dx - (pos.fim - pos.inicio) * 0.12
            _cota(msp, xc, pos.faixa_inicio + dy, xc, pos.faixa_fim + dy,
                 f"{pos.faixa_fim - pos.faixa_inicio:.0f}", ocupados)
            msp.add_circle((xc, centro_faixa + dy), RAIO_MARCA,
                           dxfattribs={"layer": camada})
            origem = (xc, centro_faixa + dy)
        else:
            msp.add_line((centro_faixa + dx, pos.inicio + dy),
                         (centro_faixa + dx, pos.fim + dy),
                         dxfattribs={"layer": camada})
            if pos.gancho_inicio > 0.0:
                _gancho_perpendicular(msp, centro_faixa + dx, pos.inicio + dy,
                                      "Y", pos.gancho_inicio, camada)
                _texto_segmento(
                    msp, centro_faixa + dx + pos.gancho_inicio + 3.0,
                    pos.inicio + dy, f"{pos.gancho_inicio:.0f}", camada,
                    ocupados, dx=1.0, dy=0.0)
            if pos.gancho_fim > 0.0:
                _gancho_perpendicular(msp, centro_faixa + dx, pos.fim + dy,
                                      "Y", pos.gancho_fim, camada)
                _texto_segmento(
                    msp, centro_faixa + dx + pos.gancho_fim + 3.0,
                    pos.fim + dy, f"{pos.gancho_fim:.0f}", camada, ocupados,
                    dx=1.0, dy=0.0)
            _texto_segmento(msp, centro_faixa + dx - 4.0,
                            (pos.inicio + pos.fim) / 2.0 + dy,
                            f"{pos.trecho_reto:.0f}", camada, ocupados,
                            rotacao=90.0, dx=-1.0, dy=0.0)
            yc = pos.fim + dy - (pos.fim - pos.inicio) * 0.12
            _cota(msp, pos.faixa_inicio + dx, yc, pos.faixa_fim + dx, yc,
                 f"{pos.faixa_fim - pos.faixa_inicio:.0f}", ocupados)
            msp.add_circle((centro_faixa + dx, yc), RAIO_MARCA,
                           dxfattribs={"layer": camada})
            origem = (centro_faixa + dx, yc)
        _cotas_emenda(msp, pos, centro_faixa, dx, dy, ocupados)
        texto = (f"N{pos.numero}  {pos.quantidade} P{pos.phi:g} "
                 f"c/{pos.espacamento:g}  C={pos.comprimento:.0f}")
        if pos.emendas:
            texto += f"  ({pos.emendas}x EMENDA L0T={pos.l0t:.0f})"
        _rotular(msp, pos, texto, origem, ocupados)


def _cotas_emenda(msp, pos, centro_faixa: float, dx: float, dy: float,
                  ocupados: list) -> None:
    """Cota de cada emenda por traspasse da barra, na própria planta.

    A emenda entra como cota, não como uma segunda barra sobreposta -- ver
    ``desenho._cotas_emenda`` para o motivo. A cota fica afastada da barra
    para não se confundir com ela, e registra a própria caixa de texto em
    ``ocupados``, então o rótulo da posição desvia dela.
    """
    if not pos.estacoes_emenda or pos.l0t <= 0.0:
        return
    recuo = 14.0                                    # cm, afastamento da barra
    for est in pos.estacoes_emenda:
        texto = f"L0T={pos.l0t:.0f}"
        if pos.eixo == "X":
            y = centro_faixa + dy - recuo
            _cota(msp, est - pos.l0t + dx, y, est + dx, y, texto, ocupados)
        else:
            x = centro_faixa + dx - recuo
            _cota(msp, x, est - pos.l0t + dy, x, est + dy, texto, ocupados)


def _cota(msp, x0: float, y0: float, x1: float, y1: float, texto: str,
         ocupados: list) -> None:
    """Cota simples entre dois pontos alinhados (na horizontal ou vertical):
    a linha, um traço curto em cada ponta e o valor no meio.

    A caixa do texto entra em ``ocupados`` -- é fixa, não foge de ninguém
    como o rótulo da posição foge dela --, então o rótulo é sempre quem
    desvia da cota, nunca o contrário.
    """
    vertical = abs(x1 - x0) < 1e-6
    msp.add_line((x0, y0), (x1, y1), dxfattribs={"layer": "COTAS"})
    meio = 4.0
    for x, y in ((x0, y0), (x1, y1)):
        if vertical:
            msp.add_line((x - meio, y), (x + meio, y),
                        dxfattribs={"layer": "COTAS"})
        else:
            msp.add_line((x, y - meio), (x, y + meio),
                        dxfattribs={"layer": "COTAS"})
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    altura = ALTURA_ROTULO * 0.75
    tx = mx + (6.0 if vertical else 0.0)
    ty = my + (0.0 if vertical else 6.0)
    _texto(msp, texto, tx, ty, altura, "COTAS",
          rotacao=90.0 if vertical else 0.0)
    largura = largura_texto(texto, altura)
    if vertical:
        ocupados.append((tx - altura / 2.0, ty - largura / 2.0,
                         tx + altura / 2.0, ty + largura / 2.0))
    else:
        ocupados.append((tx - largura / 2.0, ty - altura / 2.0,
                         tx + largura / 2.0, ty + altura / 2.0))


def _rotular(msp, pos, texto: str, origem: tuple[float, float],
             ocupados: list) -> None:
    """Põe o rótulo da posição num lugar que ainda esteja livre.

    O rótulo nasce no círculo onde a barra cruza a cota da faixa (``origem``)
    -- é esse ponto que amarra a posição à sua faixa, e é dele que o rótulo
    parte. Se a caixa do texto cruzar a de um rótulo (ou de uma cota, ou de
    um texto de trecho) já posto, ele desce (ou anda, se for vertical) de
    meia altura por vez até achar lugar, e uma linha de chamada liga o texto
    de volta ao círculo. É a mesma ideia do desenho da viga: prancha
    ilegível é prancha que não se usa.
    """
    vertical = pos.eixo == "Y"
    x0, y0 = origem
    x, y = x0, y0
    largura = largura_texto(texto, ALTURA_ROTULO)
    passo = ALTURA_ROTULO * 1.8
    for tentativa in range(40):
        if vertical:
            caixa = (x - ALTURA_ROTULO / 2.0, y - largura / 2.0,
                     x + ALTURA_ROTULO / 2.0, y + largura / 2.0)
        else:
            caixa = (x - largura / 2.0, y - ALTURA_ROTULO / 2.0,
                     x + largura / 2.0, y + ALTURA_ROTULO / 2.0)
        if not any(caixa[0] < o[2] and o[0] < caixa[2]
                   and caixa[1] < o[3] and o[1] < caixa[3] for o in ocupados):
            break
        deslocamento = passo * ((tentativa // 2) + 1)
        sinal = 1.0 if tentativa % 2 == 0 else -1.0
        if vertical:
            x = x0 + sinal * deslocamento
        else:
            y = y0 + sinal * deslocamento
    else:
        caixa = (x, y, x, y)
    ocupados.append(caixa)
    _texto(msp, texto, x, y, ALTURA_ROTULO, "TEXTO",
           rotacao=90.0 if vertical else 0.0)
    if abs(x - x0) > 1e-6 or abs(y - y0) > 1e-6:
        msp.add_line((x0, y0), (x, y), dxfattribs={"layer": "CHAMADA"})


def _bloco_tabela(msp, x0: float, y0: float, titulo: str,
                  cabecalho: list[str], linhas: list[list[str]],
                  larguras: list[int]) -> float:
    """Desenha uma tabela com título e devolve a ordenada da última linha."""
    altura = ALTURA_TABELA * 2.0
    _texto(msp, titulo, x0, y0 + altura * 1.6, ALTURA_TITULO, "TEXTO",
           ancora="left")
    y = y0
    for linha in [cabecalho] + linhas:
        x = x0
        for valor, larg in zip(linha, larguras):
            msp.add_lwpolyline([(x, y), (x + larg, y), (x + larg, y - altura),
                                (x, y - altura), (x, y)],
                               dxfattribs={"layer": "TABELA"})
            _texto(msp, str(valor), x + larg / 2.0, y - altura / 2.0,
                   ALTURA_TABELA, "TEXTO")
            x += larg
        y -= altura
    return y


def _tabela_posicoes(msp, res, x0: float, y0: float) -> float:
    """Tabela de posições: número, bitola, espaçamento, quantidade, massa.

    A coluna de emenda entra aqui porque é da barra: quem lê a tabela para
    cortar o ferro precisa saber que aquela posição não sai de uma vara só.
    """
    cabecalho = ["Pos.", "Laje", "Tipo", "Qtd.", "P (mm)", "c/ (cm)",
                 "C (cm)", "Emendas", "L0T (cm)", "Total (m)", "Massa (kg)"]
    larguras = [46, 90, 116, 42, 52, 52, 52, 56, 56, 66, 70]

    linhas = [[f"N{p.numero}", p.laje, p.tipo, str(p.quantidade),
               f"{p.phi:g}", f"{p.espacamento:g}", f"{p.comprimento:.0f}",
               str(p.emendas) if p.emendas else "-",
               f"{p.l0t:.0f}" if p.emendas else "-",
               f"{p.comprimento_total:.1f}", f"{p.massa:.1f}"]
              for p in res.todas_posicoes]
    q = res.quantitativo
    linhas.append(["", "TOTAL", "", "", "", "", "", "", "", "",
                   f"{q.get('massa_total', 0.0):.1f}"])
    return _bloco_tabela(msp, x0, y0, "TABELA DE POSICOES", cabecalho,
                         linhas, larguras)


def _quadro_quantidades(msp, res, x0: float, y0: float) -> float:
    """Quadro de quantidades: aço, concreto e forma, no próprio DXF.

    É o quadro que vai para o orçamento, e por isso separa o que a tabela
    de posições não separa: o aço das barras (o que se mede na prancha), o
    aço a mais que o traspasse das emendas consome, a forma **inferior** e a
    forma de **fechamento** -- que têm preço e execução diferentes.
    """
    q = res.quantitativo
    cabecalho = ["Item", "Unid.", "Quantidade"]
    larguras = [300, 70, 100]
    linhas: list[list[str]] = []
    for phi, d in q.get("por_bitola", {}).items():
        linhas.append([f"Aco CA-50 P{phi:g} mm", "kg", f"{d['massa']:.1f}"])
    linhas += [
        ["Aco - barras (subtotal)", "kg", f"{q.get('massa_total', 0.0):.1f}"],
        ["Aco - traspasse das emendas (9.5.2)", "kg",
         f"{q.get('massa_emendas', 0.0):.1f}"],
        ["Aco - total com 10% de perdas", "kg",
         f"{q.get('massa_com_perdas', 0.0):.1f}"],
        ["Concreto", "m3", f"{q.get('volume_concreto', 0.0):.2f}"],
        ["Forma inferior (fundo, sem a faixa sobre viga)", "m2",
         f"{q.get('forma_inferior', 0.0):.2f}"],
        ["Forma de fechamento (bordo livre, altura h)", "m2",
         f"{q.get('forma_fechamento', 0.0):.2f}"],
        ["Forma - total", "m2", f"{q.get('forma_total', 0.0):.2f}"],
        ["Area de laje (vaos efetivos)", "m2",
         f"{q.get('area_total', 0.0):.2f}"],
        ["Taxa de aco", "kg/m2", f"{q.get('taxa_por_m2', 0.0):.2f}"],
    ]
    if q.get("especiais"):
        for e in q["especiais"]:
            sist = _TIPO_ASCII[e['tipo_chave']]
            linhas.append([f"Aco - {e['nome']} ({sist} {e['perfil']})", "kg",
                           f"{e['aco_kg']:.1f}"])
        linhas += [
            ["Aco - lajes especiais (subtotal)", "kg",
             f"{q.get('massa_especiais', 0.0):.1f}"],
            ["Aco - pavimento (macicas + especiais, sem perdas)", "kg",
             f"{q.get('massa_geral', 0.0):.1f}"],
            ["Concreto moldado no local - lajes especiais", "m3",
             f"{q.get('concreto_especiais', 0.0):.2f}"],
            ["Concreto pre-moldado - paineis alveolares", "m3",
             f"{q.get('premoldado_especiais', 0.0):.2f}"],
            ["Area das lajes especiais (vaos livres)", "m2",
             f"{q.get('area_especiais', 0.0):.2f}"],
            ["Taxa de aco do pavimento", "kg/m2",
             f"{q.get('taxa_geral_por_m2', 0.0):.2f}"],
        ]
    return _bloco_tabela(msp, x0, y0, "QUADRO DE QUANTIDADES", cabecalho,
                         linhas, larguras)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def exportar(res, caminho: str) -> str:
    """Grava o DXF do pavimento e devolve o caminho."""
    doc = ezdxf.new("R2010", setup=True)
    _preparar(doc)
    msp = doc.modelspace()

    x0, y0, x1, y1 = res.contorno()
    largura = (x1 - x0) * 100.0
    altura = (y1 - y0) * 100.0
    folga = max(largura * 0.18, 150.0)
    passo = largura + folga
    base_x = -x0 * 100.0
    base_y = -y0 * 100.0

    titulos = ("PLANTA DE FORMAS", "ARMADURA POSITIVA (FACE INFERIOR)",
               "ARMADURA NEGATIVA (FACE SUPERIOR)")
    for i, titulo in enumerate(titulos):
        dx = base_x + i * passo
        cx, cy = dx + largura / 2.0, base_y + altura + 60.0
        _texto(msp, titulo, cx, cy, ALTURA_TITULO, "TEXTO")
        # o título é obstáculo como qualquer outro texto: sem registrá-lo, um
        # rótulo de posição perto da borda de cima sobe procurando espaço
        # livre e vai parar dentro dele -- aparece em laje muito alongada,
        # onde a planta é baixa e o rótulo tem pouco para onde ir
        meia = largura_texto(titulo, ALTURA_TITULO) / 2.0
        ocupados: list = [(cx - meia, cy - ALTURA_TITULO / 2.0,
                           cx + meia, cy + ALTURA_TITULO / 2.0)]
        _forma(msp, res, dx, base_y, com_vinculo=(i == 0),
               ocupados=ocupados)
        if i == 1:
            _vigas(msp, res, dx, base_y)
            posicoes = [p for rl in res.lajes for p in rl.posicoes
                        if p.face == "inferior"]
            _armadura(msp, posicoes, dx, base_y, ocupados)
        elif i == 2:
            _vigas(msp, res, dx, base_y)
            posicoes = [p for rl in res.lajes for p in rl.posicoes
                        if p.face == "superior"]
            posicoes += list(res.posicoes_continuidade)
            _armadura(msp, posicoes, dx, base_y, ocupados)

    # tabela de posições e, abaixo dela, o quadro de quantidades: os dois
    # embaixo da planta de formas, na mesma coluna, como numa prancha
    fim = _tabela_posicoes(msp, res, base_x, base_y - 120.0)
    _quadro_quantidades(msp, res, base_x, fim - 120.0)
    doc.saveas(caminho)
    return caminho


def conferir_sobreposicoes(caminho: str) -> list[str]:
    """Lista pares de textos que se sobrepõem no DXF gravado.

    Rede de proteção do autoteste: qualquer mudança de posição de rótulo que
    volte a colidir aparece aqui. A largura de cada texto é estimada em 0,62
    vez a altura por caractere -- aproximação boa o bastante para pegar
    colisão real de rótulo, que é o que torna a prancha ilegível.
    """
    doc = ezdxf.readfile(caminho)
    caixas = []
    for e in doc.modelspace().query("TEXT"):
        altura, texto = e.dxf.height, e.dxf.text
        if not texto.strip():
            continue
        larg = largura_texto(texto, altura)
        vertical = abs(float(e.dxf.rotation or 0.0) - 90.0) < 1.0
        centrado = e.dxf.halign == 1 or e.dxf.valign == 2
        ponto = e.dxf.align_point if (e.dxf.halign or e.dxf.valign) \
            else e.dxf.insert
        if vertical:
            x0 = ponto.x - altura / 2.0
            y0 = ponto.y - larg / 2.0 if centrado else ponto.y
            caixas.append((x0, y0, x0 + altura, y0 + larg, texto))
        else:
            x0 = ponto.x - larg / 2.0 if centrado else ponto.x
            caixas.append((x0, ponto.y - altura / 2.0, x0 + larg,
                           ponto.y + altura / 2.0, texto))
    problemas = []
    for i, a in enumerate(caixas):
        for b in caixas[i + 1:]:
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                problemas.append(f"textos sobrepostos: {a[4]!r} x {b[4]!r}")
    return problemas
