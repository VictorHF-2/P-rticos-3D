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


class _Folha:
    """O modelspace com uma origem: tudo o que se desenha nela anda junto.

    O desenho de uma viga usa coordenadas próprias (a elevação começa em
    ``x = 0``). Para pôr várias vigas **lado a lado** num mesmo DXF basta
    deslocar cada uma, e deslocar na hora de desenhar -- e não depois, movendo
    entidades já criadas -- é o que mantém certas as cotas associativas: a
    ``DIMENSION`` guarda a geometria num bloco anônimo que mover a entidade
    não leva junto. A folha também mede o que foi desenhado, para a viga
    seguinte saber onde começar.
    """

    def __init__(self, msp, dx: float = 0.0, dy: float = 0.0) -> None:
        self.msp, self.dx, self.dy = msp, dx, dy
        self.x_min = float("inf")
        self.x_max = float("-inf")
        self.y_min = float("inf")
        self.y_max = float("-inf")

    def ponto(self, x: float, y: float, largura: float = 0.0,
              ancora: str = "left") -> tuple[float, float]:
        """Ponto na coordenada da folha, registrando o espaço que ocupa."""
        x, y = x + self.dx, y + self.dy
        if ancora == "center":
            esq, dir_ = x - largura / 2.0, x + largura / 2.0
        elif ancora == "right":
            esq, dir_ = x - largura, x
        else:
            esq, dir_ = x, x + largura
        self.x_min = min(self.x_min, esq)
        self.x_max = max(self.x_max, dir_)
        self.y_min = min(self.y_min, y)
        self.y_max = max(self.y_max, y)
        return x, y

    def add_lwpolyline(self, pontos, dxfattribs=None):
        return self.msp.add_lwpolyline(
            [self.ponto(*p[:2]) for p in pontos], dxfattribs=dxfattribs)

    def add_line(self, a, b, dxfattribs=None):
        return self.msp.add_line(self.ponto(*a[:2]), self.ponto(*b[:2]),
                                 dxfattribs=dxfattribs)

    def add_circle(self, centro, raio, dxfattribs=None):
        return self.msp.add_circle(self.ponto(*centro[:2]), raio,
                                   dxfattribs=dxfattribs)

    def add_text(self, texto, height, dxfattribs=None):
        return self.msp.add_text(texto, height=height,
                                 dxfattribs=dxfattribs)

    def add_linear_dim(self, base, p1, p2, **kw):
        return self.msp.add_linear_dim(
            base=self.ponto(*base[:2]), p1=self.ponto(*p1[:2]),
            p2=self.ponto(*p2[:2]), **kw)

    def add_radius_dim(self, center, mpoint, **kw):
        return self.msp.add_radius_dim(
            center=self.ponto(*center[:2]), mpoint=self.ponto(*mpoint[:2]),
            **kw)


def _polilinha(msp, pol: geometria.Polilinha, dx: float = 0.0,
               dy: float = 0.0) -> None:
    pts = [(p[0] + dx, p[1] + dy) for p in pol.pontos]
    if pol.fechada:
        pts.append(pts[0])
    msp.add_lwpolyline(pts, dxfattribs={"layer": pol.camada})


def _texto(msp, t: geometria.Texto, dx: float = 0.0, dy: float = 0.0) -> None:
    ent = msp.add_text(t.texto, height=t.altura,
                       dxfattribs={"layer": t.camada, "rotation": t.rotacao})
    # o texto girado em 90 graus ocupa a altura, não o comprimento, na
    # horizontal -- a folha só precisa saber até onde o desenho chega
    larg = 0.0 if t.rotacao else largura_texto(t.texto, t.altura)
    pos = msp.ponto(t.posicao[0] + dx, t.posicao[1] + dy, larg, t.ancora)
    ent.set_placement(
        pos, align=_ALINHAMENTO.get(t.ancora, TextEntityAlignment.LEFT))


#: folga, em cm, entre o fim de uma viga (a tabela de aço, à direita) e o
#: começo da seguinte. Do tamanho de uma seção transversal: o suficiente para o
#: olho separar as pranchas sem afastá-las a ponto de perder a vizinhança
FOLGA_ENTRE_VIGAS = 400.0
#: a mesma folga, entre uma fileira de vigas e a de baixo
FOLGA_ENTRE_FILEIRAS = 400.0


def exportar(res: ResultadoViga, caminho: str, secoes_m=None,
             mostrar_estribos: bool = True) -> str:
    """Grava o DXF do detalhamento e devolve o caminho do arquivo.

    ``secoes_m`` aceita abscissas ou pares ``(x, descrição)``.
    """
    return exportar_varias([(res, secoes_m, mostrar_estribos)], caminho)


def disposicao(medidas: list[tuple[float, float, float, float]],
               colunas: int = 0) -> list[tuple[float, float]]:
    """Onde pôr cada viga: o deslocamento ``(dx, dy)`` de cada uma.

    ``medidas`` traz ``(x_min, x_max, y_min, y_max)`` do desenho de cada viga
    na origem. ``colunas`` é quantas vigas cabem em cada fileira: ``0`` (ou
    mais que as vigas) é tudo **lado a lado**; ``1`` é **uma sob a outra**;
    um valor intermediário é uma **grade**. A primeira viga fica onde está
    (``dx = dy = 0``), as fileiras se alinham pela esquerda dela e, dentro de
    cada fileira, pela linha de base (o eixo ``y = 0`` de cada elevação).
    """
    n = len(medidas)
    por_fileira = colunas if colunas > 0 else n
    x_ini = medidas[0][0]
    saida: list[tuple[float, float]] = [(0.0, 0.0)] * n
    fundo_anterior = None
    dy = 0.0
    for inicio in range(0, n, por_fileira):
        ids = range(inicio, min(inicio + por_fileira, n))
        topo = max(medidas[k][3] for k in ids)
        fundo = min(medidas[k][2] for k in ids)
        if fundo_anterior is not None:
            dy = fundo_anterior - FOLGA_ENTRE_FILEIRAS - topo
        cursor = x_ini
        for k in ids:
            dx = cursor - medidas[k][0]
            saida[k] = (dx, dy)
            cursor = dx + medidas[k][1] + FOLGA_ENTRE_VIGAS
        fundo_anterior = fundo + dy
    return saida


def exportar_varias(itens, caminho: str, colunas: int = 0) -> str:
    """Grava num DXF só o detalhamento de várias vigas.

    ``itens`` é uma lista de ``(res, secoes_m, mostrar_estribos)``. Cada viga é
    o mesmo desenho que :func:`exportar` faz para uma só -- elevação, vista
    explodida, seções e tabela de aço --, deslocado para o seu lugar na
    disposição (ver :func:`disposicao`): por padrão **lado a lado**, cada uma à
    direita da anterior. Com uma viga o arquivo é idêntico ao de sempre.
    """
    itens = list(itens)
    if not itens:
        raise ValueError("Nenhuma viga para exportar.")
    doc = ezdxf.new("R2013", setup=True)
    _preparar(doc)
    msp = doc.modelspace()

    lugares = [(0.0, 0.0)] * len(itens)
    if len(itens) > 1:
        # o espaço que cada desenho ocupa só se sabe desenhando: um ensaio
        # num documento descartável mede cada um
        medidas = []
        for res, secoes_m, mostrar_estribos in itens:
            doc_ensaio = ezdxf.new("R2013", setup=True)
            _preparar(doc_ensaio)
            ensaio = _Folha(doc_ensaio.modelspace())
            _desenhar_viga(ensaio, res, secoes_m, mostrar_estribos)
            medidas.append((ensaio.x_min, ensaio.x_max,
                            ensaio.y_min, ensaio.y_max))
        lugares = disposicao(medidas, colunas)
    for (res, secoes_m, mostrar_estribos), (dx, dy) in zip(itens, lugares):
        _desenhar_viga(_Folha(msp, dx, dy), res, secoes_m, mostrar_estribos)

    doc.saveas(caminho)
    return caminho


def _desenhar_viga(msp, res: ResultadoViga, secoes_m,
                   mostrar_estribos: bool) -> None:
    """Desenha uma viga na ``_Folha`` ``msp`` (o desenho todo, sem gravar)."""
    from .desenho import normalizar_secoes

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
        if sec.estribo_mesa is not None:
            _polilinha(msp, sec.estribo_mesa, dx, dy)
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
        if e.dxf.halign == 2:                 # alinhado à direita: termina no ponto
            x0 = ponto.x - larg
        elif centrado:
            x0 = ponto.x - larg / 2.0
        else:
            x0 = ponto.x
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
