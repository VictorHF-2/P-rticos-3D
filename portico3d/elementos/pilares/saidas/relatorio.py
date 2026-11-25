# -*- coding: utf-8 -*-
"""
relatorio.py
Memória de cálculo em Word (.docx), com os dados de entrada, a esbeltez, os
efeitos locais de segunda ordem, as situações de cálculo, o dimensionamento da
seção passo a passo, o detalhamento e o roteiro de verificações. Cada
resultado traz o item da NBR 6118 que o justifica.

Apresentação no padrão ABNT de relatório técnico (NBR 10719, com as regras
gerais da NBR 14724):

* folha A4, margens de 3 cm (superior e esquerda) e 2 cm (inferior e
  direita), Times New Roman 12 no texto e 10 em tabelas, legendas e fontes,
  entrelinha 1,5 no texto e simples no resto, parágrafo com recuo de 1,25 cm;
* elementos pré-textuais: folha de rosto, resumo com palavras-chave (NBR
  6028), lista de figuras, lista de tabelas e sumário (NBR 6027), sem número
  de página impresso;
* seções com numeração progressiva sem ponto (NBR 6024) -- primária em
  negrito e maiúsculas, começando em página nova; secundária em maiúsculas;
  terciária em negrito --, e página numerada no canto superior direito;
* tabelas (normas de apresentação tabular do IBGE, a que a NBR 14724
  remete) e figuras com o título numerado acima e a fonte abaixo; tabelas
  sem traços verticais, cabeçalho e linhas alternadas em tons de cinza;
* fórmulas como equações do Word (OMML, :mod:`.omml`), centradas e
  numeradas à direita;
* referências no padrão da NBR 6023 e citações autor-data;
* anexos com título "ANEXO A – ..." centralizado.

O sumário e as listas são campos do Word: :func:`atualizar_campos` (e
:func:`exportar_pdf`) os preenchem pelo próprio Word, via COM; sem o Word,
eles se preenchem ao abrir o arquivo (o documento pede a atualização).
"""

from __future__ import annotations

import datetime
import math
import os
import re
import tempfile

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import auditoria, graficos
from . import omml as mm_
from .omml import fr, func, par, r as mr, raiz, sub, subsup, sup
from .. import EDICAO_NORMA, VERSAO_COMPLETA
from ..core import avisos as avisos_mod
from ..core.dimensionar import ResultadoPilar
from ..core.flexocompressao import DESCRICAO_CASO
from ..core.materiais import DESCRICAO_COMBINACAO
from ..core.modelo import VINCULOS

PRETO = RGBColor(0, 0, 0)
#: Mantidos para quem marca um trecho como alerta: na apresentação ABNT o
#: texto é todo preto, e o alerta sai em negrito.
AZUL = CINZA = VERMELHO = PRETO

#: Tons de cinza das tabelas: cabeçalho e linhas alternadas do corpo.
CINZA_CABECALHO = "D9D9D9"
CINZA_ALTERNADO = "F2F2F2"

#: Fonte da memória. Times New Roman está em todo Windows; a Aptos da R05
#: original não vem instalada em toda máquina, e o Word sem ela caía em Times
#: só no corpo, com os títulos em outra fonte.
FONTE_MEMORIA = "Times New Roman"
#: NBR 14724: 12 no texto; menor e uniforme (10) em tabelas, legendas,
#: fontes, notas e paginação.
CORPO = Pt(12)
MENOR = Pt(10)
RECUO_PARAGRAFO = Cm(1.25)
#: Largura útil do texto, cm: 21 − 3 − 2.
LARGURA_TEXTO = 16.0

#: Fonte padrão das tabelas e figuras calculadas aqui.
FONTE_CALCULO = "Fonte: calculado pelo programa Pilares."
FONTE_NORMA = "Fonte: ABNT NBR 6118:2026."


# ---------------------------------------------------------------------------
# Página e estilos
# ---------------------------------------------------------------------------

def _fonte_fixa(estilo, nome: str = FONTE_MEMORIA) -> None:
    """Fonte explícita nos quatro scripts do estilo, sem herdar do tema: só
    ``font.name`` deixa o ``asciiTheme`` do modelo decidir."""
    rpr = estilo.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for att in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        rf.attrib.pop(qn(f"w:{att}"), None)
    for att in ("ascii", "hAnsi", "eastAsia", "cs"):
        rf.set(qn(f"w:{att}"), nome)


def _configurar(doc: Document) -> None:
    for nome in ("Normal", "Heading 1", "Heading 2", "Heading 3", "Title",
                 "Caption", "List Bullet", "List Number"):
        try:
            _fonte_fixa(doc.styles[nome])
        except KeyError:
            pass
    normal = doc.styles["Normal"]
    normal.font.size = CORPO
    normal.font.color.rgb = PRETO
    pf = normal.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.first_line_indent = RECUO_PARAGRAFO
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    # NBR 6024: primária em negrito e maiúsculas; secundária em
    # maiúsculas; terciária em negrito -- todas em 12, alinhadas à
    # esquerda, separadas do texto por um espaço de entrelinha 1,5
    for nivel, negrito, caixa_alta in ((1, True, True), (2, False, True),
                                       (3, True, False)):
        h = doc.styles[f"Heading {nivel}"]
        h.font.size = CORPO
        h.font.color.rgb = PRETO
        h.font.bold = negrito
        h.font.italic = False
        h.font.all_caps = caixa_alta
        hp = h.paragraph_format
        hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        hp.first_line_indent = Cm(0)
        hp.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
        hp.space_before = Pt(0 if nivel == 1 else 18)
        hp.space_after = Pt(18)
        hp.keep_with_next = True
        hp.page_break_before = nivel == 1
    legenda = doc.styles["Caption"]
    legenda.font.size = MENOR
    legenda.font.bold = False
    legenda.font.italic = False
    legenda.font.color.rgb = PRETO
    lp = legenda.paragraph_format
    lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lp.first_line_indent = Cm(0)
    lp.line_spacing_rule = WD_LINE_SPACING.SINGLE
    lp.space_before = Pt(12)
    lp.space_after = Pt(3)
    lp.keep_with_next = True
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.top_margin = Cm(3.0)
    sec.right_margin = sec.bottom_margin = Cm(2.0)
    sec.header_distance = Cm(2.0)
    sec.footer_distance = Cm(1.25)
    # o sumário e as listas são campos: o Word os atualiza ao abrir, se
    # ninguém (atualizar_campos) os tiver atualizado antes
    ajustes = doc.settings.element
    atualizar = ajustes.find(qn("w:updateFields"))
    if atualizar is None:
        atualizar = OxmlElement("w:updateFields")
        ajustes.append(atualizar)
    atualizar.set(qn("w:val"), "true")
    doc._contadores = {"Tabela": 0, "Figura": 0, "Equação": 0}


def _secao_textual(doc: Document) -> None:
    """Quebra de seção para a parte textual: a partir daqui a página é
    numerada no canto superior direito (NBR 14724, 5.3). A contagem segue a
    das páginas pré-textuais, que não mostram o número."""
    nova = doc.add_section(WD_SECTION.NEW_PAGE)
    cab = nova.header
    cab.is_linked_to_previous = False
    p = cab.paragraphs[0] if cab.paragraphs else cab.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.first_line_indent = Cm(0)
    _campo(p, "PAGE", "1", MENOR)
    doc.sections[0].header.is_linked_to_previous = False


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------

_MARCAS = re.compile(r"(\*\*|_\{[^}]*\}|\^\{[^}]*\})")

_SUBSCRITOS = str.maketrans("₀₁₂₃₄₅₆₇₈₉ₓ", "0123456789x")

#: Grandezas que, escritas em texto corrido ("MRd,xx", "fcd", "λ₁"), saem
#: com o índice de verdade -- a mesma notação das equações. Só símbolos sem
#: ambiguidade com palavras do português ("As" sozinho, por exemplo, fica
#: de fora; "As,mín" entra).
_SIMBOLOS = [
    # índices já marcados com sublinhado simples: e_cc, N_Sg, M_Sg/N_Sg
    (re.compile(r"(?<![\w{])([A-Za-z])_([A-Za-z][A-Za-z0-9]*)\b"),
     r"\1_{\2}"),
    # dígitos subscritos Unicode: λ₁, e₁,mín, e₂
    (re.compile(r"([A-Za-zλαγεηθψσρ])([₀-₉ₓ]+)((?:,mín|,máx|,p)?)"),
     lambda m: f"{m.group(1)}_{{{m.group(2).translate(_SUBSCRITOS)}"
               f"{m.group(3)}}}"),
    (re.compile(r"\bM(Sd|Rd|Sg|1d|d|k|0)((?:,[A-Za-zíá0-9]+)*)"),
     r"M_{\1\2}"),
    (re.compile(r"\bN(Rd|Sd|Sg|sg|d|k|e)((?:,[A-Za-zíá]+)*)\b"), r"N_{\1\2}"),
    (re.compile(r"\bV(Sd|Rd2|Rd3|c0|c|sw|d)\b"), r"V_{\1}"),
    (re.compile(r"\bf(ck|cd|yd|yk|ctk|ct,m|ctm|bd|sd,fad)\b"), r"f_{\1}"),
    (re.compile(r"\bΔf(sd,fad)"), r"Δf_{\1}"),
    (re.compile(r"(?<![A-Za-z])ε(c2|cu|yd)\b"), r"ε_{\1}"),
    (re.compile(r"(?<![A-Za-z])γ(n1|f3|c|s|f|n|g|q|εq)\b"), r"γ_{\1}"),
    (re.compile(r"(?<![A-Za-z])α(b|c|e|0t)\b"), r"α_{\1}"),
    (re.compile(r"(?<![A-Za-z])η(c|1)\b"), r"η_{\1}"),
    (re.compile(r"(?<![A-Za-z])σ(s|c|cd)((?:,máx)?)\b"), r"σ_{\1\2}"),
    (re.compile(r"(?<![A-Za-z])ρ(r|,mín)"),
     lambda m: "ρ_{" + m.group(1).lstrip(",") + "}"),
    (re.compile(r"(?<![A-Za-z])ψ(0j|0ε|1,fad|2j|0|1|2)"), r"ψ_{\1}"),
    (re.compile(r"(?<![A-Za-z])θ1\b"), r"θ_{1}"),
    (re.compile(r"\bA(s,mín|s,calc|s,ef|sw|cr|c)\b"), r"A_{\1}"),
    (re.compile(r"\bE(s|c)\b"), r"E_{\1}"),
    (re.compile(r"\bw(k1|k2|k)\b"), r"w_{\1}"),
    (re.compile(r"\bl(b,nec|b|0c|0t|e,[xy]|e)(?=[\s,=²)/·.;:]|$)"),
     r"l_{\1}"),
    (re.compile(r"\bF(d|gk|q1k|qjk|εqk)\b"), r"F_{\1}"),
    (re.compile(r"\(EI\)sec\b"), r"(EI)_{sec}"),
]


def _simbolos(texto: str) -> str:
    """Põe índice de verdade nas grandezas escritas em texto corrido. O que
    já está marcado (``_{…}``) não é tocado."""
    pedacos = re.split(r"(_\{[^}]*\}|\^\{[^}]*\})", texto)
    for i in range(0, len(pedacos), 2):
        t = pedacos[i]
        for padrao, troca_ in _SIMBOLOS:
            t = padrao.sub(troca_, t)
        pedacos[i] = t
    return "".join(pedacos)


def _runs(p, texto: str, italico: bool = False, negrito: bool = False,
          tamanho=None) -> None:
    """Escreve ``texto`` no parágrafo com as marcas: ``**negrito**``,
    ``_{índice}`` e ``^{expoente}`` -- os símbolos das grandezas com índice
    de verdade (f_{cd}, M_{Sd,x}), e não letras do mesmo tamanho."""
    em_negrito = False
    for pedaco in _MARCAS.split(_simbolos(texto)):
        if not pedaco:
            continue
        if pedaco == "**":
            em_negrito = not em_negrito
            continue
        run = None
        if pedaco.startswith("_{"):
            run = p.add_run(pedaco[2:-1])
            run.font.subscript = True
        elif pedaco.startswith("^{"):
            run = p.add_run(pedaco[2:-1])
            run.font.superscript = True
        else:
            run = p.add_run(pedaco)
        run.italic = italico
        run.bold = negrito or em_negrito
        if tamanho is not None:
            run.font.size = tamanho


def _titulo(doc: Document, texto: str, nivel: int = 1) -> None:
    """Título de seção com indicativo numérico (NBR 6024): o nível sai da
    própria numeração -- "3" é primária, "3.1" secundária, "A.2" (dentro de
    um anexo) secundária --, e o ponto depois do número cai."""
    m = re.match(r"^([0-9A-Z]+(?:\.[0-9]+)*)\.?\s+(.*)$", texto)
    if m:
        numero, resto = m.groups()
        nivel = min(numero.count(".") + 1, 3)
        texto = f"{numero} {resto}"
    doc.add_heading(texto, level=nivel)


def _titulo_sem_numero(doc: Document, texto: str, sumario: bool = False,
                       nova_pagina: bool = True) -> None:
    """Título sem indicativo numérico (resumo, listas, sumário, referências,
    anexos): centralizado, em negrito e maiúsculas. ``sumario`` o põe no
    sumário (referências e anexos entram; os pré-textuais não)."""
    if nova_pagina and doc.paragraphs:
        doc.add_page_break()
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.first_line_indent = Cm(0)
    pf.space_after = Pt(18)
    pf.keep_with_next = True
    _runs(p, texto.upper(), negrito=True)
    if sumario:
        ppr = p._p.get_or_add_pPr()
        nivel = OxmlElement("w:outlineLvl")
        nivel.set(qn("w:val"), "0")
        ppr.append(nivel)


def _paragrafo(doc: Document, texto: str, italico: bool = False,
               cor: RGBColor | None = None) -> None:
    """Parágrafo do texto. Um ``cor`` (os alertas de antes) vira negrito:
    na apresentação ABNT o texto é preto."""
    p = doc.add_paragraph()
    _runs(p, texto, italico=italico, negrito=cor is not None)


def _alineas(doc: Document, itens: list[str], negrito: bool = False) -> None:
    """Enumeração em alíneas (NBR 6024, 4.2): a), b), c)…, com recuo."""
    for i, texto in enumerate(itens):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.first_line_indent = Cm(-0.75)
        pf.left_indent = Cm(2.0)
        _runs(p, f"{_letra_alinea(i)}) {texto}", negrito=negrito)


def _letra_alinea(i: int) -> str:
    return _letra_anexo(i).lower()


def _campo(p, instrucao: str, texto_atual: str = "", tamanho=None) -> None:
    """Campo do Word (complexo): ``instrucao`` e o resultado já calculado,
    para o documento ler certo mesmo antes de o Word atualizar."""
    def run_com(el):
        run = p.add_run()
        if tamanho is not None:
            run.font.size = tamanho
        run._r.append(el)
        return run
    inicio = OxmlElement("w:fldChar")
    inicio.set(qn("w:fldCharType"), "begin")
    run_com(inicio)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instrucao} "
    run_com(instr)
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run_com(sep)
    run = p.add_run(texto_atual)
    if tamanho is not None:
        run.font.size = tamanho
    fim = OxmlElement("w:fldChar")
    fim.set(qn("w:fldCharType"), "end")
    run_com(fim)


def _legenda(doc: Document, tipo: str, titulo: str) -> None:
    """Título de tabela ou figura, acima dela: "Tabela 3 – Título", com o
    número num campo SEQ (é dele que a lista de tabelas sai)."""
    doc._contadores[tipo] += 1
    p = doc.add_paragraph(style="Caption")
    _runs(p, f"{tipo} ", tamanho=MENOR)
    _campo(p, f"SEQ {tipo} \\* ARABIC", str(doc._contadores[tipo]), MENOR)
    _runs(p, f" – {titulo}", tamanho=MENOR)


def _fonte(doc: Document, texto: str) -> None:
    """A fonte, logo abaixo da tabela ou da figura (NBR 14724, 5.8 e 5.9)."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.first_line_indent = Cm(0)
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.space_before = Pt(3)
    pf.space_after = Pt(12)
    _runs(p, texto, tamanho=MENOR)


def _sombrear(celula, cor: str) -> None:
    tcpr = celula._tc.get_or_add_tcPr()
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:val"), "clear")
    sombra.set(qn("w:color"), "auto")
    sombra.set(qn("w:fill"), cor)
    tcpr.append(sombra)


def _bordas(tabela, cabecalho) -> None:
    """Traços horizontais só: em cima, embaixo e sob o cabeçalho, sem traço
    vertical nem entre as linhas do corpo (apresentação tabular do IBGE)."""
    tblpr = tabela._tbl.tblPr
    bordas = OxmlElement("w:tblBorders")
    for lado, estilo in (("top", "single"), ("bottom", "single"),
                         ("left", "nil"), ("right", "nil"),
                         ("insideH", "nil"), ("insideV", "nil")):
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), estilo)
        if estilo == "single":
            b.set(qn("w:sz"), "8")
            b.set(qn("w:space"), "0")
            b.set(qn("w:color"), "000000")
        bordas.append(b)
    tblpr.append(bordas)
    for celula in cabecalho.cells:
        tcpr = celula._tc.get_or_add_tcPr()
        cb = OxmlElement("w:tcBorders")
        b = OxmlElement("w:bottom")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "000000")
        cb.append(b)
        tcpr.append(cb)


def _celula(celula, texto: str, alinhamento, negrito: bool = False) -> None:
    celula.text = ""
    p = celula.paragraphs[0]
    pf = p.paragraph_format
    pf.alignment = alinhamento
    pf.first_line_indent = Cm(0)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.space_before = Pt(1)
    pf.space_after = Pt(1)
    _runs(p, texto, negrito=negrito, tamanho=MENOR)


def _tabela(doc: Document, titulo: str, cabecalho: list[str],
            linhas: list[list], larguras: list[float] | None = None,
            fonte: str = FONTE_CALCULO) -> None:
    """Tabela com título acima e fonte abaixo, em tons de cinza: cabeçalho
    D9D9D9 em negrito e linhas do corpo alternando branco e F2F2F2."""
    _legenda(doc, "Tabela", titulo)
    t = doc.add_table(rows=1, cols=len(cabecalho))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    cab = t.rows[0]
    for i, texto in enumerate(cabecalho):
        _celula(cab.cells[i], str(texto), WD_ALIGN_PARAGRAPH.CENTER, True)
        _sombrear(cab.cells[i], CINZA_CABECALHO)
    # o cabeçalho se repete no alto de cada página
    trpr = cab._tr.get_or_add_trPr()
    repete = OxmlElement("w:tblHeader")
    repete.set(qn("w:val"), "true")
    trpr.append(repete)
    for k, linha in enumerate(linhas):
        cels = t.add_row().cells
        for i, valor in enumerate(linha):
            _celula(cels[i], "" if valor is None else str(valor),
                    WD_ALIGN_PARAGRAPH.LEFT if i == 0
                    else WD_ALIGN_PARAGRAPH.CENTER)
            if k % 2 == 1:
                _sombrear(cels[i], CINZA_ALTERNADO)
    _bordas(t, cab)
    if larguras:
        escala = min(1.0, LARGURA_TEXTO / sum(larguras))
        for linha in t.rows:
            for cel, larg in zip(linha.cells, larguras):
                cel.width = Cm(larg * escala)
    _fonte(doc, fonte)


def _figura(doc: Document, titulo: str, fig, largura_cm: float = 15.0,
            fonte: str = FONTE_CALCULO) -> None:
    """Figura com título acima e fonte abaixo (NBR 14724, 5.8)."""
    _legenda(doc, "Figura", titulo)
    caminho = os.path.join(tempfile.gettempdir(), f"pilar_fig_{id(fig)}.png")
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    doc.add_picture(caminho, width=Cm(min(largura_cm, LARGURA_TEXTO)))
    p = doc.paragraphs[-1]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    p.paragraph_format.keep_with_next = True
    _fonte(doc, fonte)
    try:
        os.remove(caminho)
    except OSError:
        pass


def _equacao(doc: Document, conteudo, numerar: bool = True) -> None:
    """Equação do Word em modo de exibição (frações em tamanho cheio),
    centrada, com o número entre parênteses alinhado à direita.

    Uma equação em modo de exibição ocupa o parágrafo inteiro e não aceita
    tabulação ao lado: a equação e o número vão numa tabela de uma linha,
    sem bordas -- o arranjo usual para equação numerada no Word.
    """
    t = doc.add_table(rows=1, cols=3)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    tblpr = t._tbl.tblPr
    bordas = OxmlElement("w:tblBorders")
    for lado in ("top", "bottom", "left", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), "nil")
        bordas.append(b)
    tblpr.append(bordas)
    margem, numero = 1.4, 1.4
    larguras = (margem, LARGURA_TEXTO - margem - numero, numero)
    for cel, larg in zip(t.rows[0].cells, larguras):
        cel.width = Cm(larg)
        pf = cel.paragraphs[0].paragraph_format
        pf.first_line_indent = Cm(0)
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.space_before = Pt(4)
        pf.space_after = Pt(4)
    meio = t.rows[0].cells[1].paragraphs[0]
    meio.alignment = WD_ALIGN_PARAGRAPH.CENTER
    bloco = OxmlElement("m:oMathPara")
    pr = OxmlElement("m:oMathParaPr")
    jc = OxmlElement("m:jc")
    jc.set(qn("m:val"), "center")
    pr.append(jc)
    bloco.append(pr)
    bloco.append(mm_.equacao(conteudo))
    meio._p.append(bloco)
    direita = t.rows[0].cells[2]
    direita.vertical_alignment = 1                     # centro
    pd = direita.paragraphs[0]
    pd.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if numerar:
        doc._contadores["Equação"] += 1
        pd.add_run(f"({doc._contadores['Equação']})")


def _sumario(doc: Document, titulo: str, instrucao: str,
             recado: str) -> None:
    """Sumário ou lista (campo TOC), em página própria."""
    _titulo_sem_numero(doc, titulo)
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0)
    _campo(p, instrucao, recado)


def _n(valor, casas: int = 2) -> str:
    if valor is None:
        return "-"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, int):
        return str(valor)
    try:
        return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",") \
            .replace("@", ".")
    except (TypeError, ValueError):
        return str(valor)


def _pct(razao: float) -> str:
    """Razão limitada a 1 (interação 17.2.5, MSd/MRd) como percentual da
    capacidade usada -- 0,89 vira "89 %". Espelha o F.S. (>= 1 aprova) com
    um formato visualmente distinto (<= 100 % aprova), para não confundir
    as duas famílias de número na mesma tabela."""
    if razao == float("inf"):
        return "∞"
    return f"{_n(razao * 100.0, 0)} %"


# ---------------------------------------------------------------------------
# Elementos pré-textuais
# ---------------------------------------------------------------------------

def _folha_de_rosto(doc: Document, res: ResultadoPilar) -> None:
    """Folha de rosto (NBR 10719): responsável, título, subtítulo, natureza
    do documento e ano."""
    p = res.pilar

    def linha(texto, negrito=False, espaco_depois=0, tamanho=None):
        par_ = doc.add_paragraph()
        pf = par_.paragraph_format
        pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.first_line_indent = Cm(0)
        pf.space_after = Pt(espaco_depois)
        _runs(par_, texto, negrito=negrito, tamanho=tamanho)
        return par_

    linha((p.projeto or "Projeto estrutural").upper(), negrito=True)
    for _ in range(8):
        linha("")
    linha("MEMÓRIA DE CÁLCULO: DIMENSIONAMENTO DE PILAR DE CONCRETO ARMADO",
          negrito=True, espaco_depois=6)
    linha(f"Pilar {p.nome} — seção {p.secao.descricao()}")
    if p.config.compat_pcalc:                                # COMPAT-PCALC
        linha("")
        linha(f"MODO COMPATÍVEL COM O PCALC 1.4 "
              f"({p.config.compat_pcalc.upper()}): reproduz o procedimento "
              f"do PCalc e não é a verificação pela NBR 6118:2026. Somente "
              f"para conferência.", negrito=True)
    for _ in range(4):
        linha("")
    natureza = doc.add_paragraph()
    pf = natureza.paragraph_format
    pf.left_indent = Cm(8.0)
    pf.first_line_indent = Cm(0)
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    _runs(natureza,
          f"Memória de cálculo do lance de pilar {p.nome}, dimensionado e "
          f"verificado segundo a ABNT NBR 6118:2026 — Projeto de estruturas "
          f"de concreto. Documento gerado pelo programa Pilares "
          f"{VERSAO_COMPLETA}.", tamanho=MENOR)
    for _ in range(10):
        linha("")
    linha(str(datetime.date.today().year))


def _resumo_abnt(doc: Document, res: ResultadoPilar) -> None:
    """Resumo em parágrafo único, seguido das palavras-chave (NBR 6028)."""
    p = res.pilar
    _titulo_sem_numero(doc, "Resumo")
    metodo = _METODOS_2A.get(p.config.metodo_2a_ordem,
                             ("", p.config.metodo_2a_ordem))[1]
    if p.config.metodo_2a_ordem == "pior":
        metodo = ("todos os métodos aplicáveis da norma, valendo o mais "
                  "desfavorável")
    fs_sit = [v.fs for v in res.verificacoes if math.isfinite(v.fs)]
    if res.ok:
        veredito = ("Todas as verificações foram atendidas"
                    + (f", com fator de segurança mínimo de "
                       f"{_n(min(fs_sit), 2)}" if fs_sit else "") + ".")
    else:
        veredito = (f"{len(res.erros)} verificação(ões) não foram "
                    f"atendidas e estão relacionadas na seção de "
                    f"observações e pendências.")
    combinacoes = (f", em {len(res.combinacoes)} combinações verificadas com "
                   f"a mesma armadura" if res.combinacoes else "")
    armadura = (f"A armadura adotada é {res.arranjo.descricao()}"
                + (f", com estribos {res.estribos.descricao()}"
                   if res.estribos else "")
                + f" (taxa de {_n(res.taxa * 100)} %)."
                if res.arranjo is not None else
                "Nenhum arranjo de barras atendeu às verificações.")
    texto = (
        f"Esta memória apresenta o dimensionamento e a verificação do lance "
        f"de pilar {p.nome}"
        + (f", do projeto {p.projeto}," if p.projeto else "")
        + f" de seção {p.secao.descricao()}, em concreto "
        f"C{_n(p.concreto.fck, 0)} e aço {p.aco.categoria}, com "
        f"{_n(p.lance.altura, 0)} cm de lance, segundo a ABNT NBR 6118:2026. "
        f"A força normal de cálculo é N_{{d}} = {_n(p.Nd, 1)} kN"
        f"{combinacoes}. Os efeitos locais de segunda ordem foram avaliados "
        f"pelo critério: {metodo}; a seção foi verificada à flexão composta oblíqua "
        f"pela envoltória de momentos resistentes, além do momento mínimo, "
        f"do detalhamento e dos estados-limites aplicáveis. {armadura} "
        f"{veredito}")
    par_ = doc.add_paragraph()
    par_.paragraph_format.first_line_indent = Cm(0)
    par_.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    _runs(par_, texto)
    chave = doc.add_paragraph()
    chave.paragraph_format.first_line_indent = Cm(0)
    chave.paragraph_format.space_before = Pt(12)
    _runs(chave, "**Palavras-chave:** pilar; concreto armado; flexão "
                 "composta oblíqua; efeitos locais de segunda ordem; ABNT NBR "
                 "6118.")


def _identificacao(doc: Document, res: ResultadoPilar, n: int) -> None:
    """Primeira seção do texto: a ficha do lance e o resultado."""
    p = res.pilar
    _titulo(doc, f"{n}. Identificação do lance")
    _paragrafo(doc,
               "A Tabela 1 reúne a identificação do lance, os materiais, a "
               "armadura adotada e a situação geral das verificações, "
               "detalhadas nas seções seguintes.")
    linhas = [
        ["Pilar", p.nome],
        ["Projeto", p.projeto or "-"],
        ["Seção transversal", p.secao.descricao()],
        ["Área de concreto", f"{_n(p.secao.area, 0)} cm²"],
        ["Comprimento do lance", f"{_n(p.lance.altura, 0)} cm"],
        ["Concreto", f"C{_n(p.concreto.fck, 0)} "
                     f"(f_{{cd}} = {_n(p.concreto.fcd)} MPa)"],
        ["Aço longitudinal", p.aco.categoria],
        ["Aço transversal", p.aco_estribo.categoria],
        ["Agressividade ambiental", p.ambiente.descricao()],
        ["Cobrimento adotado",
         f"{_n(res.arranjo.cobrimento if res.arranjo else p.ambiente.cobrimento_adotado)} cm"],
    ]
    if res.arranjo is not None:
        linhas.append(["Armadura longitudinal", res.arranjo.descricao()])
    if res.estribos is not None:
        linhas.append(["Armadura transversal", res.estribos.descricao()])
    linhas.append(["Taxa de armadura", f"{_n(res.taxa * 100)} %"])
    linhas.append(["Situação geral",
                   "TODAS AS VERIFICAÇÕES ATENDIDAS" if res.ok
                   else "HÁ VERIFICAÇÕES NÃO ATENDIDAS — VER O ROTEIRO DE "
                        "VERIFICAÇÕES E AS OBSERVAÇÕES"])
    if p.observacoes:
        linhas.append(["Observações", p.observacoes])
    _tabela(doc, "Identificação e resultado do lance", ["Item", "Descrição"],
            linhas, [5.0, 11.0])


def _referencias(doc: Document, res: ResultadoPilar) -> None:
    """Referências (NBR 6023): só as citadas nesta memória, em ordem
    alfabética, alinhadas à esquerda e em espaço simples."""
    p = res.pilar
    refs = [
        "ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. **NBR 6118**: projeto de "
        "estruturas de concreto. Rio de Janeiro: ABNT, 2026.",
    ]
    if p.config.obra_ponte:
        refs.append("ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. **NBR 7187**: "
                    "projeto de pontes, viadutos e passarelas de concreto. Rio "
                    "de Janeiro: ABNT, 2022.")
    if res.fadiga is not None and res.fadiga.obra:
        refs.append("ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. **NBR 8681**: "
                    "ações e segurança nas estruturas: procedimento. Rio de "
                    "Janeiro: ABNT, 2025.")
    # 9062: cobrimento com controle rigoroso, e a parede mínima do pilar
    # vazado (6.2.1/6.2.2), complemento normativo adotado em 13/11/2026
    if p.ambiente.controle_rigoroso or p.secao.eh_vazada:
        refs.append("ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. **NBR 9062**: "
                    "projeto e execução de estruturas de concreto pré-moldado. "
                    "Rio de Janeiro: ABNT, 2017.")
    refs += [
        "CAMPOS FILHO, A. **Projeto de pilares de concreto armado**. Porto "
        "Alegre: Universidade Federal do Rio Grande do Sul, Escola de "
        "Engenharia, Departamento de Engenharia Civil, 2014. Apostila.",
        "CARDOSO JÚNIOR, S. D. **Sistema computacional para análise não "
        "linear de pilares de concreto armado**. 2014. Monografia "
        "(Especialização) – Escola Politécnica, Universidade de São Paulo, "
        "São Paulo, 2014.",
    ]
    _titulo_sem_numero(doc, "Referências", sumario=True)
    for ref in refs:
        par_ = doc.add_paragraph()
        pf = par_.paragraph_format
        pf.first_line_indent = Cm(0)
        pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
        pf.space_after = Pt(12)
        _runs(par_, ref)


# ---------------------------------------------------------------------------
# Seções do relatório
# ---------------------------------------------------------------------------

_METODOS_2A = {
    "menor": ("15.8.3.3.2 e 15.8.3.3.3",
              "pilar-padrão com curvatura e com rigidez aproximadas; adotado o "
              "menor dos dois"),
    "curvatura": ("15.8.3.3.2", "pilar-padrão com curvatura aproximada"),
    "rigidez": ("15.8.3.3.3", "pilar-padrão com rigidez κ aproximada"),
    "diagrama": ("15.8.3.3.4 e 15.3.1",
                 "pilar-padrão acoplado a diagramas M, N, 1/r: rigidez "
                 "secante (EI)sec da Figura 15.1, da seção armada"),
    "geral": ("15.8.3.2 e 15.3.1",
              "método geral: barra discretizada, relação momento-curvatura "
              "real em cada seção e não linearidade geométrica"),
}


def _linha_segunda_ordem(cfg) -> list[str]:
    item, texto = _METODOS_2A[cfg.metodo_2a_ordem]
    if cfg.considerar_fluencia:
        texto += ("; fluência pela e_cc do 15.8.4" if cfg.fluencia_metodo
                  == "ecc" or cfg.metodo_2a_ordem not in ("diagrama", "geral")
                  else "; fluência pela curva de deformabilidade esticada "
                       "(εc2 e εcu × (1 + φ·Nsg/Nd))")
    if cfg.sempre_2a_ordem:
        texto += ("; considerada sempre, mesmo com λ ≤ λ1 (critério de "
                  "projeto a favor da segurança -- o 15.8.2 só a dispensa)")
    return ["Segunda ordem local", item, texto]


def _metodologia(doc: Document, res: ResultadoPilar, n: int) -> None:
    """Como o cálculo foi feito, e o que ficou fora dele."""
    p = res.pilar
    cfg = p.config
    _titulo(doc, f"{n}. Metodologia e escopo")
    _paragrafo(doc,
               "O cálculo segue a ABNT NBR 6118:2026 (ASSOCIAÇÃO BRASILEIRA "
               "DE NORMAS TÉCNICAS, 2026), cujos itens são citados ao longo "
               "do texto, e trata um **lance isolado** "
               "de pilar, de seção e armadura constantes ao longo do eixo, "
               "com os esforços de primeira ordem conhecidos no topo e na "
               "base. Os esforços globais de segunda ordem, o desaprumo e as "
               "combinações de ações são anteriores a este cálculo e entram "
               "nos valores de Nd e M1d informados -- com uma exceção: num "
               "pilar isolado em balanço não há modelo global, e o programa "
               "soma ao momento de base o desaprumo do item 11.3.3.4.1 "
               "(θ1 = 1/200), salvo se o critério estiver desligado.")
    _titulo(doc, f"{n}.1 Cadeia de cálculo", 2)
    _tabela(doc, 'Cadeia de cálculo e itens da NBR 6118', ["Etapa", "Item da NBR 6118", "O que foi feito"], [
        ["Esbeltez", "15.8.1 e 15.8.2",
         "λ = le/i em cada direção, comparada com λ₁ = (25 + 12,5 e₁/h)/αb"],
        ["Momento mínimo", "11.3.3.4.3",
         ("e₁,mín = 1,5 + 0,03 h; envoltória mínima com 2ª ordem (Figuras "
          "11.3 e 15.2) verificada à parte, contra a envoltória resistente"
          if cfg.momento_minimo_metodo == "envoltoria" else
          "e₁,mín = 1,5 + 0,03 h, aplicada como piso do momento de 1ª "
          "ordem, separadamente em cada direção")],
        ["Força cortante", "17.4.2.2 e 17.4.1.1.2-c",
         "modelo I quando Vd é informada; a alínea c) diz quando o estribo "
         "construtivo do 18.4.3 basta"],
        _linha_segunda_ordem(cfg),
        ["Situações de cálculo", "15.8.3.3.5",
         "extremidades A e B e seção intermediária, com a composição dos "
         "momentos nas duas direções"],
        ["Dimensionamento", "17.2.2",
         "motor seccional por integração do diagrama parábola-retângulo"
         + (" (o roteiro dos casos fechados FC1–FC4 / FT1–FT4 entra como "
            "informação e conferência)" if res.dim_fechado else "")],
        ["Verificação oblíqua", "17.2.5",
         (f"(MSd,x/MRd,xx)^α + (MSd,y/MRd,yy)^α ≤ 1, com α = "
          f"{_n(res.pilar.alfa_interacao)}, mais a envoltória de equilíbrio"
          if res.pilar.config.exigir_interacao_17_2_5 else
          "envoltória de equilíbrio (exata); a expressão aproximada do "
          f"17.2.5 (α = {_n(res.pilar.alfa_interacao)}) fica informativa")],
        ["Detalhamento", "18.4.2, 18.4.3 e 18.2.4",
         "bitolas, taxas, espaçamentos, estribos e proteção contra "
         "flambagem das barras"],
        ["Ancoragem", "9.4.2 e 9.5.2.3",
         "comprimento de ancoragem básico e comprimento de espera"],
    ], [3.2, 3.0, 9.0], fonte="Fonte: ABNT NBR 6118:2026; programa Pilares.")

    _titulo(doc, f"{n}.2 Os dois motores de cálculo, e qual deles vale", 2)
    _paragrafo(doc,
               "A seção pode ser resolvida por dois caminhos independentes. "
               "Neste cálculo o roteiro dos casos fechados está "
               + ("ligado, como informação e conferência."
                  if res.dim_fechado else
                  "desligado: o dimensionamento e o veredito são só do "
                  "motor seccional."))
    _paragrafo(doc,
               "O primeiro é o roteiro dos casos fechados, que classifica o "
               "par (Nd, Md) em um de oito casos e resolve a armadura por "
               "expressão algébrica, com o diagrama retangular simplificado "
               "do item 17.2.2 e o modelo de duas camadas. É o método da "
               "bibliografia e é conferível à mão — mas ignora as barras "
               "intermediárias das faces, que na peça resistem à força "
               "normal, e vale só para a seção retangular.")
    _paragrafo(doc,
               "O segundo é o motor seccional: integra o diagrama "
               "parábola-retângulo do item 8.2.10.1 sobre o contorno real da "
               "seção, fatiado paralelamente à linha neutra, e soma cada "
               "barra com a deformação que ela tem na posição em que está. "
               "Resolve qualquer contorno poligonal e a flexão oblíqua sem "
               "aproximação de expoente.")
    _paragrafo(doc,
               "Quem aprova e reprova é o motor seccional. O roteiro "
               "fechado, quando ligado, é informativo: onde os dois "
               "divergem, a divergência é declarada no quadro de "
               "conferência, e prevalece o motor seccional.",
               italico=True)

    _titulo(doc, f"{n}.3 O que o programa buscou em tabela", 2)
    _paragrafo(doc,
               "Estas grandezas não foram digitadas: o programa as obteve da "
               "própria norma, a partir de dados que já tinha. Cada uma pode "
               "ser sobreposta por um valor imposto, e a coluna de origem "
               "diz qual foi o caso.")
    linhas = [
        ["Comprimento equivalente le", "15.8.2",
         f"x: {_n(p.le('x'), 0)} cm — {p.le_memoria('x')}"],
        ["", "", f"y: {_n(p.le('y'), 0)} cm — {p.le_memoria('y')}"],
        ["Coeficientes γc e γs", "Tabela 12.1",
         (f"combinações {DESCRICAO_COMBINACAO[cfg.combinacao].lower()}: "
          f"γc = {_n(p.concreto.gamma_c)}, γs = {_n(p.aco.gamma_s)}")
         if cfg.ponderacao_automatica
         else f"impostos: γc = {_n(p.concreto.gamma_c)}, "
              f"γs = {_n(p.aco.gamma_s)}"],
        ["Expoente α da interação", "17.2.5",
         f"α = {_n(p.alfa_interacao)} — "
         + ("adotado pelo tipo de seção" if p.alfa_automatico
            else "imposto pelo projetista")],
        ["Cobrimento nominal", "7.4.7",
         f"{_n(res.arranjo.cobrimento if res.arranjo else p.ambiente.cobrimento_adotado)} cm — governa "
         f"{p.ambiente.governante(res.arranjo.phi if res.arranjo else 0.0, res.arranjo.phi_estribo if res.arranjo else 0.0)}"],
    ]
    if cfg.considerar_fluencia:
        linhas.append(
            ["Coeficiente de fluência φ", "Tabela 8.1",
             f"φ = {_n(p.phi_fluencia)} — umidade "
             f"{_n(cfg.umidade_ambiente, 0)} %, 2Ac/u = "
             f"{_n(p.espessura_ficticia, 1)} cm, t₀ = "
             f"{_n(cfg.idade_carregamento, 0)} dias"])
    _tabela(doc, 'Grandezas que o programa obteve da norma', ["Grandeza", "Item", "Valor e origem"], linhas,
            [4.2, 2.4, 9.4])

    _titulo(doc, f"{n}.4 O que este cálculo não verifica", 2)
    _paragrafo(doc,
               "Estabilidade global (itens 15.6 e 15.7), imperfeições "
               "geométricas globais (11.3.3.4.1) e torção (17.5). As "
               "combinações de ações (11.8) só são geradas quando as ações "
               "características são informadas; senão os esforços de "
               "entrada são tomados como de cálculo. A fadiga (seção 23) e a abertura "
               "de fissuras (17.3.3) são verificadas só quando ativadas nos "
               "critérios. A força "
               "cortante (17.4) é verificada pelo modelo I quando "
               "informada, e declarada como não aplicável quando não. "
               "O roteiro de verificações ao final relaciona cada uma delas "
               "como não verificada, com o motivo.")


def _dados(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Dados de entrada")
    _titulo(doc, f"{n}.1 Seção e materiais", 2)
    prop = p.secao.propriedades()
    _tabela(doc, 'Seção transversal e materiais', ["Grandeza", "Valor", "Referência"], [
        ["Tipo de seção", p.secao.tipo, "—"],
        ["h_{x} (direção x)", f"{_n(p.secao.hx)} cm", "—"],
        ["h_{y} (direção y)", f"{_n(p.secao.hy)} cm", "—"],
        ["Área bruta A_{c}", f"{_n(prop.area, 0)} cm²", "13.2.3"],
        ["Raio de giração i_{x}", f"{_n(prop.ix)} cm", "15.8.2"],
        ["Raio de giração i_{y}", f"{_n(prop.iy)} cm", "15.8.2"],
        ["Menor dimensão", f"{_n(p.secao.menor_dimensao)} cm", "13.2.3"],
        ["Coeficiente adicional γ_{n}", _n(p.gamma_n), "Tabela 13.1"],
        ["f_{ck}", f"{_n(p.concreto.fck, 0)} MPa", "8.2.4"],
        ["f_{cd}", f"{_n(p.concreto.fcd)} MPa "
                f"({_n(p.concreto.fcd_kNcm2, 4)} kN/cm²)", "12.3.3"],
        ["α_{c} (bloco retangular)", _n(p.concreto.alfa_c), "17.2.2"],
        ["η_{c} (fragilidade)", _n(p.concreto.eta_c, 3), "8.2.10.1"],
        ["Pico do parábola-retângulo", f"0,85·ηc·fcd = "
                f"{_n(p.concreto.fator_pico, 3)}·fcd", "8.2.10.1"],
        ["λ (altura do bloco)", _n(p.concreto.lambda_bloco), "17.2.2"],
        ["ε_{c2}", f"{_n(p.concreto.eps_c2_mil)} ‰", "8.2.10.1"],
        ["ε_{cu}", f"{_n(p.concreto.eps_cu_mil)} ‰", "8.2.10.1"],
        ["Aço longitudinal", p.aco.categoria, "8.3"],
        ["f_{yd}", f"{_n(p.aco.fyd)} MPa "
                f"({_n(p.aco.fyd_kNcm2)} kN/cm²)", "8.3.6"],
        ["ε_{yd}", f"{_n(p.aco.eps_yd_mil, 4)} ‰", "8.3.6"],
        ["E_{s}", f"{_n(p.aco.Es, 0)} MPa", "8.3.5"],
    ], [5.5, 5.5, 5.0])

    _titulo(doc, f"{n}.2 Esforços de primeira ordem e vinculação", 2)
    f = p.fator_esforcos
    e = p.esforcos
    _tabela(doc, 'Esforços de primeira ordem', ["Grandeza", "Entrada", "De cálculo (× γ_{f} γ_{n})"], [
        ["N_{d}", f"{_n(e.Nd, 1)} kN", f"{_n(p.Nd, 1)} kN"],
        ["M_{1d,x} no topo", f"{_n(e.Mx_topo / 100, 2)} kN·m",
         f"{_n(f * e.Mx_topo / 100, 2)} kN·m"],
        ["M_{1d,x} na base", f"{_n(e.Mx_base / 100, 2)} kN·m",
         f"{_n(f * e.Mx_base / 100, 2)} kN·m"],
        ["M_{1d,y} no topo", f"{_n(e.My_topo / 100, 2)} kN·m",
         f"{_n(f * e.My_topo / 100, 2)} kN·m"],
        ["M_{1d,y} na base", f"{_n(e.My_base / 100, 2)} kN·m",
         f"{_n(f * e.My_base / 100, 2)} kN·m"],
    ], [5.5, 5.5, 5.0])
    _tabela(doc, 'Comprimento equivalente e vinculação', ["Dir.", "l_{e} (cm)", "Origem do l_{e}", "Vinculação",
                  "M_{1d,A} (kN·m)", "M_{1d,B} (kN·m)"], [
        [d, _n(p.le(d), 0), p.le_memoria(d), VINCULOS[p.lance.vinculo(d)],
         _n(p.M1d_A(d) / 100, 2), _n(p.M1d_B(d) / 100, 2)] for d in ("x", "y")
    ], [1.6, 1.8, 5.2, 3.6, 2.4, 2.4])
    _paragrafo(doc,
               "M1d,A é o maior momento de primeira ordem em módulo e M1d,B "
               "o do outro extremo, positivo quando traciona a mesma face "
               "que M1d,A e negativo em caso contrário (item 15.8.2). É o "
               "sinal de M1d,B que distingue a curvatura simples da reversa "
               "e, por ele, define o αb.", italico=True)
    _figura(doc, 'Seção transversal armada', graficos.figura_secao(res), 12.0)


def _esbeltez(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Esbeltez e dispensa dos efeitos de 2ª ordem")
    linhas = []
    for d in ("x", "y"):
        e = res.esbeltez[d]
        linhas.append([
            d, _n(e.h), _n(e.i), _n(e.le, 0), _n(e.lam, 1), _n(e.e1),
            _n(e.e1_min), _n(e.alfa_b), _n(e.lam_1, 1), e.veredito])
    _tabela(doc, 'Índice de esbeltez e dispensa dos efeitos de 2ª ordem', ["Dir.", "h (cm)", "i (cm)", "l_{e} (cm)", "λ", "e_{1} (cm)",
                  "e_{1,mín} (cm)", "α_{b}", "λ_{1}", "Conclusão"], linhas,
            [1.4, 1.6, 1.6, 1.6, 1.4, 1.6, 1.8, 1.2, 1.4, 3.4])
    _paragrafo(doc,
               "O índice de esbeltez é dado pela primeira equação abaixo, "
               "forma geral que vale para qualquer seção; na seção retangular "
               "ela coincide com λ = 3,46 l_{e}/h, porque i = h/√12. A "
               "esbeltez limite do item 15.8.2 é a da segunda, com "
               "35 ≤ λ_{1} ≤ 90; quando o "
               "momento de primeira ordem fica abaixo do momento mínimo, "
               "α_{b} = 1,0.")
    _equacao(doc, ["λ = ", fr(sub("l", "e"), "i")])
    _equacao(doc, [sub("λ", "1"), " = ",
                   fr(["25 + 12,5 ", fr(sub("e", "1"), "h")], sub("α", "b"))])
    ep = res.esbeltez["x"].principal
    if ep is not None:
        _titulo(doc, f"{n}.1 Eixos principais de inércia", 2)
        so = res.segunda_ordem
        _paragrafo(doc,
                   f"A seção {res.pilar.secao.tipo} não tem eixo de simetria: "
                   f"Ix = {_n(ep.Ix, 0)} cm⁴, Iy = {_n(ep.Iy, 0)} cm⁴ e "
                   f"Ixy = {_n(ep.Ixy, 0)} cm⁴. Os eixos principais ficam a "
                   f"tan 2φ = 2 Ixy/(Ix − Iy), com I1 = {_n(ep.I1, 0)} cm⁴ e "
                   f"I2 = {_n(ep.I2, 0)} cm⁴. A flambagem se dá segundo eles, "
                   f"e é neles que a esbeltez, a dispensa do 15.8.2, os limites "
                   f"do 15.8.1 e a 2ª ordem do pilar-padrão são calculados "
                   f"(15.8.3.3.5: \"nas duas direções principais\"). Os "
                   f"momentos de 1ª ordem de topo e de base entram projetados "
                   f"em cada direção (M = Mx·cos φ + My·sen φ); a 2ª ordem de "
                   f"cada uma volta para x e y como vetor, e2 = Σ s·e2,p·u_p, "
                   f"com s o sentido de M1d,A na direção.")
        linhas = []
        for d in ep.direcoes:
            linhas.append([
                d.rotulo, _n(d.I, 0), _n(d.i), _n(d.h, 1), _n(d.le, 0),
                _n(d.lam, 1), _n(d.e1), _n(d.e1_min), _n(d.alfa_b),
                _n(d.lam_1, 1),
                "considerar" if d.considerar_2a_ordem else "dispensada",
                _n(d.e2) if d.considerar_2a_ordem else "—"])
        _tabela(doc, 'Esbeltez segundo os eixos principais de inércia', ["Direção", "I (cm⁴)", "i (cm)", "h (cm)", "le (cm)",
                      "λ", "e₁ (cm)", "e₁,mín (cm)", "αb", "λ₁", "2ª ordem",
                      "e₂ (cm)"], linhas,
                [1.8, 1.5, 1.1, 1.2, 1.2, 1.0, 1.2, 1.4, 1.0, 1.0, 1.7, 1.2])
        _paragrafo(doc,
                   f"Projetada em x e y: e2,x = {_n(so['x'].e2)} cm e "
                   f"e2,y = {_n(so['y'].e2)} cm (com o sinal relativo ao de "
                   f"e₁ em cada eixo). O momento mínimo também é verificado "
                   f"com a elipse nas direções principais (11.3.3.4.3).",
                   italico=True)


def _segunda_ordem(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Efeitos locais de segunda ordem")
    linhas = []
    for d in ("x", "y"):
        s = res.segunda_ordem[d]
        if not s.aplicavel:
            linhas.append([d, _n(s.nu, 3), "—", "—", "—", "—",
                           s.metodo])
            continue
        linhas.append([d, _n(s.nu, 3), _n(s.curvatura, 6),
                       _n(s.e2_curvatura), _n(s.e2_rigidez),
                       _n(s.e2), s.metodo])
    _tabela(doc, 'Efeitos locais de 2ª ordem', ["Dir.", "ν", "1/r (cm⁻¹)", "e₂ curvatura (cm)",
                  "e₂ rigidez (cm)", "e₂ adotado (cm)", "Método"], linhas,
            [1.4, 1.6, 2.2, 2.6, 2.6, 2.6, 3.0])
    _paragrafo(doc,
               "Pelo pilar-padrão com curvatura aproximada (15.8.3.3.2), a "
               "excentricidade de 2ª ordem e a curvatura da seção crítica são "
               "as das Equações a seguir, com a força normal adimensional ν:")
    _equacao(doc, [sub("e", "2"), " = ", fr(sup(sub("l", "e"), "2"), "10"),
                   " ∙ ", fr("1", "r")])
    _equacao(doc, [fr("1", "r"), " = ",
                   fr("0,005", ["h", par(["ν + 0,5"])]), " ≤ ",
                   fr("0,005", "h"), ",   ν = ",
                   fr(sub("N", "d"), [sub("A", "c"), " ", sub("f", "cd")])])
    _paragrafo(doc,
               "Pelo pilar-padrão com rigidez κ aproximada (15.8.3.3.3), o "
               "momento total M_{Sd,tot} é a raiz positiva da equação de 2º "
               "grau abaixo. Dividida por 5hN_{d}^{2} e escrita em "
               "excentricidades, ela vira e^{2} + (h/5 − l_{e}^{2}/1600h − "
               "e_{1})e − h e_{1}/5 = 0, forma em que a normal sai da conta.")
    _equacao(doc, ["5h ", sup("M", "2"), " + ",
                   par([sup("h", "2"), " ", sub("N", "d"), " − ",
                        fr([sub("N", "d"), " ", sup(sub("l", "e"), "2")],
                           "320"),
                        " − 5h ", sub("α", "b"), " ", sub("M", "1d,A")]),
                   " ", "M", " − ", sub("N", "d"), " ", sup("h", "2"), " ",
                   sub("α", "b"), " ", sub("M", "1d,A"), " = 0"])
    cfg = res.pilar.config
    from ..core.segunda_ordem import metodo_efetivo
    if metodo_efetivo(res.pilar) == "diagrama":
        _diagrama_mn1r(doc, res)
    elif cfg.metodo_2a_ordem == "geral":
        _metodo_geral(doc, res)
    g1 = {d: res.esbeltez[d].gamma_n1 for d in ("x", "y")}
    if any(v > 1.0 for v in g1.values()):
        _paragrafo(doc,
                   "λ > 140: os efeitos locais de 2ª ordem foram majorados "
                   "pelo coeficiente da equação abaixo (item 15.8.1) — "
                   + "; ".join(f"{d}: {_n(v, 3)}" for d, v in g1.items())
                   + ".")
        _equacao(doc, [sub("γ", "n1"), " = 1 + ", fr("λ − 140", "140")])
    if cfg.considerar_fluencia:
        origem = ("obtido da Tabela 8.1 por interpolação"
                  if cfg.phi_fluencia <= 0 else "imposto pelo projetista")
        _paragrafo(doc,
                   f"Fluência considerada pelo item 15.8.4, com "
                   f"N_Sg/Nd = {_n(cfg.Nsg_sobre_Nd)} e φ = "
                   f"{_n(res.pilar.phi_fluencia)} — {origem}, para umidade "
                   f"média de {_n(cfg.umidade_ambiente, 0)} %, espessura "
                   f"fictícia 2Ac/u = {_n(res.pilar.espessura_ficticia, 1)} "
                   f"cm e carregamento aos "
                   f"{_n(cfg.idade_carregamento, 0)} dias.")
        if (cfg.fluencia_metodo == "diagrama"
                and cfg.metodo_2a_ordem in ("diagrama", "geral")):
            _paragrafo(doc,
                       f"A fluência entra pela curva de deformabilidade: "
                       f"εc2 e εcu multiplicados por 1 + φ·Nsg/Nd = "
                       f"{_n(1 + res.pilar.phi_fluencia * cfg.Nsg_sobre_Nd, 3)}"
                       f". A norma descreve a forma aproximada da e_cc "
                       f"(15.8.4); esta é a alternativa do programa, "
                       f"declarada.", italico=True)
        else:
            ecc = "; ".join(f"{d}: {_n(res.segunda_ordem[d].e_cc, 3)} cm"
                            for d in ("x", "y"))
            _equacao(doc, [sub("e", "cc"), " = ",
                           par([fr(sub("M", "Sg"), sub("N", "Sg")), " + ",
                                sub("e", "a")]),
                           par([func("exp", par(fr(["φ ", sub("N", "Sg")],
                                                   [sub("N", "e"), " − ",
                                                    sub("N", "Sg")]))),
                                " − 1"], "[", "]")])
            _paragrafo(doc,
                       f"A excentricidade de fluência da equação acima é "
                       f"somada à de 1ª ordem e amplificada pela 2ª ordem como "
                       f"efeito imediato (15.8.4) — {ecc}. M_{{Sg}}/N_{{Sg}} é "
                       f"aproximado pelo e_{{1}} de cálculo e N_{{Sg}} não "
                       f"leva γ_{{n}}.")
    _figura(doc, 'Momentos de cálculo ao longo do lance', graficos.figura_esforcos(res), 16.0)


def _diagrama_mn1r(doc: Document, res: ResultadoPilar) -> None:
    """Pilar-padrão acoplado a diagramas M, N, 1/r (15.8.3.3.4)."""
    p = res.pilar
    _paragrafo(doc,
               "Pilar-padrão acoplado a diagramas M, N, 1/r (15.8.3.3.4): a "
               "curvatura da seção crítica sai da relação momento-curvatura "
               "da seção armada (Figura 15.1) — curva de deformabilidade com "
               "pico 1,10·fcd e normal Nd/γf3 (γf3 = 1,1), reta AB até "
               "M = MRd/γf3, cuja inclinação é a rigidez secante (EI)sec. Com "
               "a deformada senoidal, o momento total é o da equação "
               "abaixo"
               + (", com a formulação de segurança do 15.3.1 (critério de "
                  "projeto): a amplificação é calculada com Nd/γf3 e o "
                  "resultado majorado de γf3 = 1,1, o que dá Nd·(e1 + e2) com "
                  "o e2 da normal reduzida."
                  if p.config.alivio_gamma_f3_diagrama else
                  ", com Nd inteiro na amplificação (sem o alívio opcional "
                  "do 15.3.1)."))
    _equacao(doc, [sub("M", "Sd,tot"), " = ",
                   fr([sub("α", "b"), " ", sub("M", "1d,A")],
                      ["1 − ", fr([sub("N", "d"), " ", sup(sub("l", "e"), "2")],
                                  ["10 ", sub(par("EI"), "sec")])])])
    linhas = []
    for d in ("x", "y"):
        s, e = res.segunda_ordem[d], res.esbeltez[d]
        if not s.aplicavel or s.EI_sec <= 0:
            linhas.append([d, "—", "—", "—", s.metodo])
            continue
        from ..core.segunda_ordem import normal_amplificacao
        Nd = normal_amplificacao(p, abs(p.Nd) / p.gamma_n)
        x = Nd * e.le ** 2 / (10.0 * s.EI_sec)
        linhas.append([d, _n(s.EI_sec / 1e4, 1), _n(x, 3),
                       _n(1.0 / (1.0 - x), 3) if x < 1 else "instável",
                       _n(s.e2, 3)])
    _tabela(doc, 'Rigidez secante e amplificação dos momentos', ["Dir.", "(EI)sec (kN·m²)",
                  ("(Nd/γf3)·le²/(10·(EI)sec)" if p.config.alivio_gamma_f3_diagrama
                   else "Nd·le²/(10·(EI)sec)"),
                  "Amplificação", "e₂ (cm)"], linhas,
            [1.4, 3.2, 3.6, 2.8, 2.6])
    _figura(doc, 'Rigidez secante: momento × curvatura (Figura 15.1 da NBR 6118)', graficos.figura_rigidez_secante(res), 16.0)


def _metodo_geral(doc: Document, res: ResultadoPilar) -> None:
    """Método geral (15.8.3.2): a tabela por seção da barra."""
    p = res.pilar
    cfg = p.config
    g = res.segunda_ordem["x"].geral
    _paragrafo(doc,
               f"Método geral (15.8.3.2): barra discretizada em "
               f"{cfg.metodo_geral_secoes} seções; em cada uma, a curvatura "
               f"sai do estado de deformação que equilibra (N, Mx, My) na "
               f"curva de deformabilidade (pico 1,10·fcd, Nd/γf3) — "
               + ("a curva real" if cfg.metodo_geral_rigidez == "curva"
                  else "a reta AB, rigidez secante (EI)sec constante")
               + (", com as duas direções acopladas (flexão oblíqua)"
                  if cfg.metodo_geral_acoplado
                  else ", uma direção de cada vez")
               + "; a flecha sai da dupla integração das curvaturas e o "
                 "processo se repete até a flecha parar. Os momentos são "
                 "majorados de γf3 (15.3.1).", italico=True)
    _paragrafo(doc,
               "Condições de contorno: pilar vinculado nas duas pontas como "
               "barra biarticulada de comprimento le em cada direção, com os "
               "momentos de extremidade da entrada; pilar em balanço como "
               "barra engastada na base e livre no topo, com o comprimento "
               "do lance. É a mesma idealização do comprimento equivalente "
               "dos métodos aproximados.", italico=True)
    if g is None or not g.convergiu:
        _paragrafo(doc, f"**A análise não convergiu**: "
                        f"{g.motivo if g else 'sem resultado'}.")
        return
    L = p.lance.altura
    linhas = []
    for i, t in enumerate(g.z):
        linhas.append([str(i + 1), _n(t * L, 0), _n(g.Mx[i] / 100.0, 1),
                       _n(g.My[i] / 100.0, 1), _n(g.ax[i], 3),
                       _n(g.ay[i], 3)])
    _tabela(doc, 'Método geral: momentos e deslocamentos ao longo da barra', ["Seção", "z (cm)", "Mx (kN·m)", "My (kN·m)",
                  "aₓ (cm)", "a_y (cm)"], linhas,
            [1.4, 2.0, 2.6, 2.6, 2.4, 2.4])
    _paragrafo(doc,
               f"Convergiu em {g.iteracoes} iterações. z medido a partir da "
               f"base; a é o deslocamento lateral do eixo na análise com "
               f"Nd/γf3.", italico=True)


def _situacoes(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Situações de cálculo")
    if res.pilar.config.metodo_2a_ordem == "geral":
        _paragrafo(doc,
                   "Pelo método geral, cada seção da barra discretizada é "
                   "uma situação de cálculo, com os momentos totais (1ª e 2ª "
                   "ordem) da análise não linear nas duas direções -- a "
                   "verificação percorre a altura inteira, e não só as três "
                   "seções do item 15.8.3.3.5.", italico=True)
    _paragrafo(doc,
               "O item 11.3.3.4.3 admite que, em flexão composta oblíqua, o "
               "momento mínimo seja respeitado separadamente em cada "
               "direção. Daí saem as situações de extremidade. Na seção "
               "intermediária entram o αb e a segunda ordem.")
    if res.pilar.config.combinar_2a_ordem_biaxial:
        _paragrafo(doc,
                   "Critério adotado: na seção intermediária os efeitos de "
                   "segunda ordem das duas direções atuam concomitantemente, "
                   "como pede o item 15.8.3.3.5 — 'num ponto intermediário "
                   "onde se admite atuar concomitantemente os momentos "
                   "Md,tot nas duas direções (x e y)'.", italico=True)
    else:
        _paragrafo(doc,
                   "Critério adotado: na seção intermediária a segunda ordem "
                   "entra apenas na direção cujo mínimo está sendo imposto. "
                   "É o critério da planilha de referência, e é menos "
                   "oneroso que a combinação simultânea do item 15.8.3.3.5.",
                   italico=True)
    linhas = []
    for s in res.situacoes:
        marca = " ←" if s is res.governante else ""
        linhas.append([s.nome + marca, s.descricao, _n(s.ex), _n(s.ey),
                       _n(s.modulo), _n(s.Mx / 100.0, 1),
                       _n(s.My / 100.0, 1)])
    _tabela(doc, 'Situações de cálculo', ["Situação", "Descrição", "ex (cm)", "ey (cm)", "|e| (cm)",
                  "Mx (kN·m)", "My (kN·m)"], linhas,
            [2.4, 5.0, 1.7, 1.7, 1.7, 1.9, 1.9])
    if res.governante is not None:
        _paragrafo(doc,
                   f"A situação assinalada é a de maior excentricidade "
                   f"resultante, |e| = {_n(res.governante.modulo)} cm, e é a "
                   f"que orienta a escolha da armadura. A verificação, "
                   f"porém, é feita contra **todas** as situações: como as "
                   f"duas direções têm alturas diferentes, o maior módulo "
                   f"não é necessariamente o caso mais desfavorável.",
                   italico=True)
    _figura(doc, 'Excentricidades das situações de cálculo', graficos.figura_excentricidades(res), 12.0)


def _dimensionamento(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Dimensionamento da seção")
    k = 1                     # numeração contínua: o roteiro só existe na retangular
    if res.dim_fechado:
        _titulo(doc, f"{n}.{k} Roteiro dos casos fechados", 2)
        k += 1
        for d in ("x", "y"):
            dim = res.dim_fechado.get(d)
            if dim is None:
                continue
            cl = dim.classificacao
            _paragrafo(doc, f"Direção {d} — flexão segundo h = "
                            f"{_n(p.secao.altura(d))} cm")
            _tabela(doc, f"Roteiro dos casos fechados — direção {d}", ["Grandeza", "Valor", "Significado"], [
                ["Nd", f"{_n(dim.Nd, 1)} kN", "força normal de cálculo"],
                ["Md", f"{_n(abs(dim.Md) / 100, 1)} kN·m",
                 "momento de cálculo da situação mais desfavorável"],
                ["e₀ = Md/Nd", f"{_n(cl.e0)} cm",
                 "excentricidade da resultante"],
                ["(d − d′)/2", f"{_n((cl.e1 + cl.e2) / 2.0)} cm",
                 "meia distância entre as camadas"],
                ["e₁", f"{_n(cl.e1)} cm", "de Nd até a camada As1"],
                ["e₂", f"{_n(cl.e2)} cm", "de Nd até a camada As2"],
                ["e₂,GP", f"{_n(cl.e2_GP)} cm",
                 "fronteira da grande excentricidade"],
                ["e₂,PC", f"{_n(cl.e2_PC)} cm",
                 "fronteira da compressão composta"],
                ["Caso", f"{dim.caso}", DESCRICAO_CASO.get(dim.caso, "")],
                ["x", f"{_n(dim.x)} cm",
                 f"linha neutra, domínio {dim.dominio}"],
                ["σ₁", f"{_n(dim.sigma1)} kN/cm²",
                 "tensão na camada As1 (compressão positiva)"],
                ["σ₂", f"{_n(dim.sigma2)} kN/cm²", "tensão na camada As2"],
                ["As por camada", f"{_n(max(dim.As1, dim.As2))} cm²",
                 "armadura calculada de cada face"],
            ], [4.2, 3.6, 8.2])

    _titulo(doc, f"{n}.{k} Armadura mínima e adotada", 2)
    _equacao(doc, [sub("ρ", "mín"), " = 0,15 ν ",
                   fr(sub("f", "cd"), sub("f", "yd")), " ≥ 0,4 %"])
    from ..core.materiais import rho_minimo
    rmin = rho_minimo(res.nu, p.concreto, p.aco)
    linhas = [
        ["ν = Nd/(Ac fcd)", _n(res.nu, 4), "17.3.5.3.1"],
        ["ρ,mín = 0,15 ν fcd/fyd ≥ 0,4 %", f"{_n(rmin * 100, 3)} %",
         "17.3.5.3.1"],
        ["As,mín", f"{_n(res.As_minima)} cm²", "17.3.5.3.1"],
    ] + ([["As necessária (casos fechados)", f"{_n(res.As_necessaria)} cm²",
            "17.2.2"]] if res.dim_fechado else [])
    if res.arranjo is not None:
        linhas += [
            ["Arranjo adotado", res.arranjo.descricao(), "18.4.2.2"],
            ["As efetiva", f"{_n(res.arranjo.As)} cm²", "—"],
            ["ρ efetiva", f"{_n(res.taxa * 100, 3)} %", "17.3.5.3"],
            ["d′ (face ao eixo da barra)",
             f"{_n(res.arranjo.d_linha_x)} cm", "—"],
        ]
    _tabela(doc, 'Armadura mínima e armadura adotada', ["Grandeza", "Valor", "Item"], linhas, [7.0, 5.0, 3.0])


def _combinacoes(doc: Document, res: ResultadoPilar, n: int) -> None:
    """As combinações de esforços, verificadas com a mesma armadura."""
    if res.metodos_pior:
        from pilares.core.dimensionar import ROTULOS_METODO
        _titulo(doc, f"{n}. Métodos de 2ª ordem — caso mais conservador")
        _paragrafo(doc,
                   "Critério de projeto: todos os métodos de 2ª ordem que a "
                   "norma admite para este lance rodaram — "
                   + ", ".join(ROTULOS_METODO[m] for m in res.metodos_pior)
                   + " (curvatura e rigidez κ até λ = 90 com armadura "
                   "simétrica, a rigidez só na seção retangular; M, N, 1/r até "
                   "λ = 140; método geral sempre) —, em cada combinação, com "
                   "a mesma armadura. Vale o pior: a reprovada de menor "
                   f"margem ou, sem reprovada, a de menor F.S. — aqui, "
                   f"{res.combinacao_governante}. As seções seguintes "
                   f"detalham esse caso; a tabela traz todos.")
    else:
        _titulo(doc, f"{n}. Combinações de esforços")
        _paragrafo(doc,
                   f"{len(res.combinacoes)} combinações de cálculo verificadas "
                   f"com a mesma armadura "
                   f"({res.arranjo.descricao() if res.arranjo else '-'})"
                   f". As seções seguintes desta memória detalham a que "
                   f"governa, {res.combinacao_governante}: a reprovada de "
                   f"menor margem ou, sem reprovada, a de menor fator de "
                   f"segurança.")
    linhas = []
    for c in res.combinacoes:
        linhas.append([
            c.nome + (" (governa)" if c.governante else ""), _n(c.Nd, 1),
            f"{_n(c.Mx_topo, 1)} / {_n(c.Mx_base, 1)}",
            f"{_n(c.My_topo, 1)} / {_n(c.My_base, 1)}",
            _n(c.fs) if math.isfinite(c.fs) else "∞",
            _n(c.fs_minimo) if math.isfinite(c.fs_minimo) else "∞",
            "OK" if c.ok else "NÃO ATENDE"])
    _tabela(doc, 'Combinações de esforços verificadas', ["Combinação", "Nd (kN)", "Mx topo / base (kN·m)",
                  "My topo / base (kN·m)", "F.S. mín.", "F.S. do mínimo",
                  "Veredito"], linhas)
    formulas = [(c.nome, c.descricao) for c in res.combinacoes if c.descricao]
    if formulas:
        _paragrafo(doc, "Composição de cada combinação (ações características, "
                        "Tabela 11.3):", italico=True)
        for nome, f in formulas:
            _paragrafo(doc, f"{nome}: Fd = {f}")


def _acoes(doc: Document, res: ResultadoPilar, n: int) -> None:
    """As ações características e de onde as combinações saíram."""
    from pilares.core.acoes import GAMMA_F
    p = res.pilar
    _titulo(doc, f"{n}. Ações e combinações (11.7 e 11.8)")
    gd, gf, gq, geq = GAMMA_F.get(p.config.combinacao, GAMMA_F["normais"])
    _equacao(doc, [sub("F", "d"), " = ", sub("γ", "g"), " ", sub("F", "gk"),
                   " + ", sub("γ", "q"), " ",
                   par([sub("F", "q1k"), " + Σ ", sub("ψ", "0j"), " ",
                        sub("F", "qjk")]),
                   " + ", sub("γ", "εq"), " ", sub("ψ", "0ε"), " ",
                   sub("F", "εqk")])
    _paragrafo(doc,
               f"Os esforços de cálculo saíram das ações características "
               f"abaixo, pelas combinações últimas "
               f"{p.config.combinacao} da Tabela 11.3 (equação acima), cada ação variável "
               f"direta como principal por vez, mais a combinação só com as "
               f"permanentes. Coeficientes da Tabela 11.1: γg = {_n(gd)}"
               + (f" (favorável {_n(gf)}, também gerada)"
                  if p.config.acoes_permanente_favoravel else "")
               + f", γq = {_n(gq)}, γεq (temperatura) = {_n(geq)}; ψ da "
               f"Tabela 11.2. As direções do vento formam um grupo "
               f"excludente e entram nos dois sentidos; a temperatura é "
               f"sempre secundária. Para cada combinação última, a fluência "
               f"usa NSg/Nd e MSg/Md da quase permanente de mesmo arranjo "
               f"(Fgk + Σ ψ2j·Fqjk)"
               + (" e o ELS-W, a frequente (Fgk + ψ1·Fq1k + Σ ψ2j·Fqjk)."
                  if p.config.acoes_servico else "."))
    linhas = []
    for a in p.acoes:
        p0, p1, p2 = a.psi
        e = a.esforcos
        linhas.append([
            a.nome, a.categoria,
            "—" if a.permanente else f"{_n(p0)} / {_n(p1)} / {_n(p2)}",
            _n(e.Nd, 1), f"{_n(e.Mx_topo / 100, 1)} / {_n(e.Mx_base / 100, 1)}",
            f"{_n(e.My_topo / 100, 1)} / {_n(e.My_base / 100, 1)}"])
    _tabela(doc, 'Ações características', ["Ação", "Categoria", "ψ0 / ψ1 / ψ2", "Nk (kN)",
                  "Mk,x topo / base (kN·m)", "Mk,y topo / base (kN·m)"],
            linhas, [2.4, 1.8, 2.6, 2.0, 3.6, 3.6])
    if not res.combinacoes and p.descricao_combinacao:
        _paragrafo(doc, f"Uma combinação só: {p.nome_combinacao}: Fd = "
                        f"{p.descricao_combinacao}.")


def _verificacao(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Verificação à flexão composta oblíqua")
    _equacao(doc, [sup(par(fr(sub("M", "Sd,x"), sub("M", "Rd,xx"))), "α"),
                   " + ",
                   sup(par(fr(sub("M", "Sd,y"), sub("M", "Rd,yy"))), "α"),
                   " ≤ 1"])
    _paragrafo(doc,
               f"Expressão de interação do item 17.2.5, com α = "
               f"{_n(p.alfa_interacao)}. MRd,xx e MRd,yy são os "
               f"momentos resistentes em flexão composta normal, com a mesma "
               f"força normal e o arranjo de barras adotado."
               + ("" if p.config.exigir_interacao_17_2_5 else
                  " Critério de projeto: a expressão é uma aproximação que a "
                  "norma permite adotar; a aprovação fica com a envoltória de "
                  "equilíbrio, verificação exata, e a interação acima de "
                  "100 % sai como informativa."))
    linhas = []
    for v in res.verificacoes:
        linhas.append([
            v.situacao.nome, _n(v.situacao.Mx / 100, 1), _n(v.MRd_xx / 100, 1),
            _n(v.situacao.My / 100, 1), _n(v.MRd_yy / 100, 1),
            _pct(v.interacao),
            "OK" if v.ok_interacao else
            ("INFORMATIVA" if not v.interacao_exigida else "NÃO ATENDE")])
    _tabela(doc, 'Verificação pela expressão de interação do item 17.2.5', ["Situação", "M_{Sd,x} (kN·m)", "M_{Rd,xx} (kN·m)",
                  "M_{Sd,y} (kN·m)", "M_{Rd,yy} (kN·m)", "Interação (%)", "Veredito"],
            linhas, [2.1, 2.2, 2.3, 2.2, 2.3, 2.3, 2.2])

    nr = res.normal
    if nr is not None:
        _paragrafo(doc,
                   f"Força normal resistente (item 17.2.2 g), retas a e b). "
                   f"Em compressão uniforme a εc2 = {_n(nr.eps_c2)} ‰, o "
                   f"concreto trabalha na tensão de pico 0,85·ηc·fcd = "
                   f"{_n(nr.sigma_cd * 10)} MPa (17.2.2 e)) e cada barra a "
                   f"{_n(nr.sigma_s * 10, 0)} MPa (17.2.2 f)), descontada a "
                   f"área de concreto que ela ocupa: NRd,máx = "
                   f"{_n(nr.sigma_cd * 10)} MPa × {_n(nr.area_concreto, 1)} cm² "
                   f"+ {_n(nr.area_aco)} cm² × ({_n(nr.sigma_s * 10, 0)} − "
                   f"{_n(nr.sigma_cd * 10)}) MPa = {_n(nr.N_concreto, 1)} + "
                   f"{_n(nr.N_aco, 1)} = {_n(nr.NRd_max, 1)} kN. Em tração, "
                   f"NRd,mín = −As·fyd = {_n(nr.NRd_min, 1)} kN. "
                   + (f"Nd = {_n(nr.Nd, 1)} kN ≤ NRd,máx ∴ não há esmagamento "
                      f"(F.S. = {_n(nr.fs, 2)})."
                      if nr.ok and nr.compressao else
                      f"Nd = {_n(nr.Nd, 1)} kN ≥ NRd,mín ∴ atende "
                      f"(F.S. = {_n(nr.fs, 2)})." if nr.ok else
                      f"Nd = {_n(nr.Nd, 1)} kN > NRd,máx ∴ ESMAGAMENTO DO "
                      f"CONCRETO: nenhum plano de deformação equilibra essa "
                      f"normal, e os momentos resistentes abaixo saem nulos."
                      if nr.compressao else
                      f"|Nd| = {_n(-nr.Nd, 1)} kN > As·fyd ∴ NÃO ATENDE."))
    _titulo(doc, f"{n}.1 Envoltória de momentos resistentes", 2)
    _equacao(doc, ["F.S. = ", fr(sub("M", "Rd"), sub("M", "Sd"))])
    _paragrafo(doc,
               "O item 15.8.3.3.5 pede que a composição dos momentos "
               "solicitantes caia dentro da envoltória de momentos "
               "resistentes. A envoltória abaixo sai do equilíbrio da seção: "
               "para cada direção da linha neutra, a profundidade que "
               "equilibra Nd e o par (MRd,x, MRd,y) que dela resulta. Não há "
               "expoente aproximado nela.")
    linhas = []
    for v in res.verificacoes:
        if v.envoltoria_inatingivel:
            linhas.append([
                v.situacao.nome, _n(v.MSd / 100, 1),
                "nenhuma LN alcança essa direção", "—", "0,00", "—",
                "NÃO ATENDE"])
            continue
        if v.MRd_envoltoria <= 0:
            continue
        mrd = (f"[{_n(v.MRd_envoltoria_inferior / 100, 1)}; "
               f"{_n(v.MRd_envoltoria / 100, 1)}]"
               if v.MRd_envoltoria_inferior > 0
               else _n(v.MRd_envoltoria / 100, 1))
        linhas.append([
            v.situacao.nome, _n(v.MSd / 100, 1), mrd,
            _pct(v.razao_envoltoria),
            "—" if math.isinf(v.fs) else _n(v.fs, 2), v.dominio,
            "OK" if v.ok_envoltoria else "NÃO ATENDE"])
    if linhas:
        _tabela(doc, 'Verificação pela envoltória de momentos resistentes', ["Situação", "M_{Sd} (kN·m)", "M_{Rd} na direção (kN·m)",
                      "M_{Sd}/M_{Rd} (%)", "F.S.", "Domínio", "Veredito"], linhas,
                [2.3, 2.3, 3.2, 1.9, 1.6, 1.8, 2.2])
    _figura(doc, 'Envoltória de momentos resistentes e momentos solicitantes', graficos.figura_envoltoria(res), 12.0)
    _figura(doc, 'Diagramas de interação à flexão composta normal', graficos.figura_interacao(res), 16.0)
    _paragrafo(doc,
               "Estado de deformação e de tensões na cota crítica (a de "
               "menor F.S.), no plano que equilibra (NSd, MSd) com a "
               "armadura adotada: deformação ao longo da seção, tensão no "
               "concreto (parábola-retângulo, σc ≤ αc·fcd) e tensão em cada "
               "barra (|σs| ≤ fyd).", italico=True)
    _figura(doc, 'Deformação e tensões na seção da cota crítica', graficos.figura_estado_secao(res), 16.0)

    _titulo(doc, f"{n}.2 Fator de segurança por cota do lance", 2)
    _paragrafo(doc,
               "F.S. = MRd/MSd na direção do momento solicitante, lido em "
               "três cotas físicas do lance: topo e base com o momento "
               "real de cada ponta -- e não o M1d,A, o maior módulo entre "
               "os dois, que decide o αb --, e o meio com a pior das "
               "situações intermediárias já verificadas acima. No meio, os "
               "momentos totais (1ª e 2ª ordens) das duas direções atuam "
               "concomitantemente, como o item 15.8.3.3.5 admite para a "
               "seção intermediária; com momentos de 1ª ordem abaixo do "
               "mínimo, αb = 1,0 (15.8.2 d)), o que pode exigir a 2ª ordem "
               "numa direção em que a fórmula do diagrama a dispensaria. "
               "Programas que tiram αb sempre da fórmula -- o PCalc "
               "(CARDOSO JÚNIOR, 2014), por exemplo -- dão aí um F.S. do "
               "meio maior.")
    linhas = []
    for nome_z, v in res.verificacoes_z.items():
        linhas.append([
            nome_z, _n(v.MSd / 100, 1), _n(v.MRd_envoltoria / 100, 1),
            "—" if math.isinf(v.fs) else _n(v.fs, 2), v.dominio,
            "OK" if v.ok else "NÃO ATENDE"])
    _tabela(doc, 'Fator de segurança por cota do lance', ["Cota", "M_{Sd} (kN·m)", "M_{Rd} envoltória (kN·m)", "F.S.",
                  "Domínio", "Veredito"], linhas,
            [2.0, 2.6, 3.4, 1.8, 2.0, 2.4])

    mm = res.momento_minimo
    k = 3
    if mm is not None:
        _titulo(doc, f"{n}.{k} Momento mínimo — envoltória isolada "
                     f"(item 11.3.3.4.3)", 2)
        k += 1
        _paragrafo(doc,
                   "Campos Filho (2014, item 3.1) verifica o momento "
                   "mínimo à parte, e não como piso do momento real: duas "
                   "análises isoladas à flexão composta normal, uma por "
                   "direção, com Md,tot,mín = M1d,mín amplificado pela 2ª "
                   "ordem onde a esbeltez a exige (com αb = 1), confrontado "
                   "com o momento resistente naquela direção apenas.")
        _equacao(doc, [sub("M", "1d,mín"), " = ", sub("N", "d"), " ",
                       par("0,015 + 0,03 h"), "   (h em metros)"])
        _tabela(doc, 'Momento mínimo: envoltória isolada', ["Direção", "M_{d,tot,mín} (kN·m)",
                      "M_{Rd} na direção (kN·m)", "F.S.", "Veredito"],
                [[mm.rotulos[0], _n(mm.Msd_x / 100, 1), _n(mm.MRd_x / 100, 1),
                  "∞" if math.isinf(mm.fs_x) else _n(mm.fs_x, 2),
                  "OK" if mm.ok_x else "NÃO ATENDE"],
                 [mm.rotulos[1], _n(mm.Msd_y / 100, 1), _n(mm.MRd_y / 100, 1),
                  "∞" if math.isinf(mm.fs_y) else _n(mm.fs_y, 2),
                  "OK" if mm.ok_y else "NÃO ATENDE"]],
                [2.0, 3.0, 3.4, 1.8, 2.4])
        if mm.pontos_elipse:
            _paragrafo(doc,
                       "A norma (15.3.2) admite as duas análises acima, nas "
                       "direções principais, mas as Figuras 11.3 e 15.2 "
                       "definem a envoltória mínima como uma elipse. Por "
                       f"isso foram conferidos também {len(mm.pontos_elipse)} "
                       "ponto(s) intermediários, em que os dois mínimos agem "
                       "juntos, em flexão oblíqua, pela envoltória de "
                       f"equilíbrio: menor margem MRd/MSd = "
                       f"{_n(mm.fs_elipse, 2)} "
                       f"({'atende' if mm.ok_elipse else 'NÃO ATENDE'}).")

    if res.conferencias:
        _titulo(doc, f"{n}.{k} Conferência entre os dois motores", 2)
        _tabela(doc, 'Conferência entre os dois motores de cálculo', ["Grandeza", "Casos fechados", "Motor seccional",
                      "Divergência", "Dentro da tolerância"],
                [[c.grandeza, _n(c.fechado, 1), _n(c.seccional, 1),
                  f"{_n(c.divergencia * 100, 1)} %",
                  "sim" if c.ok else "não"] for c in res.conferencias],
                [4.4, 3.0, 3.0, 2.6, 3.0])
        _paragrafo(doc,
                   "As duas contas não têm de coincidir. O roteiro fechado "
                   "usa o diagrama retangular simplificado e o modelo de "
                   "duas camadas; o motor seccional usa o parábola-retângulo "
                   "e todas as barras. A divergência cresce quando a seção "
                   "fica quase toda comprimida — é onde o bloco retangular "
                   "mais se afasta — e quando há barras intermediárias nas "
                   "faces, que o modelo de duas camadas não enxerga. "
                   "Prevalece o motor seccional.", italico=True)


def _servico(doc: Document, res: ResultadoPilar, n: int) -> None:
    """ELS-W: abertura de fissuras na combinação frequente (17.3.3.2)."""
    _titulo(doc, f"{n}. Estado-limite de serviço — abertura de fissuras")
    s = res.servico
    if s is None or not s.aplicavel:
        _paragrafo(doc,
                   "Não verificado: " + (s.motivo if s is not None else
                                         "sem resultado") + ". A NBR 6118 "
                   "(Tabela 13.4) exige, no concreto armado, o ELS-W na "
                   "combinação frequente; informe os esforços de serviço "
                   "para que ele seja verificado.", cor=VERMELHO)
        return
    _paragrafo(doc,
               f"As aberturas w_{{k1}} e w_{{k2}} das equações abaixo vêm "
               f"do item 17.3.3.2; vale a menor. "
               f"Combinação frequente de serviço, esforços informados pelo "
               f"projetista, nas cotas de topo e base. Seção no estádio II "
               f"(concreto tracionado desprezado, αe = Es/Ec = "
               f"{_n(s.alfa_e, 1)}). Para cada barra tracionada, wk é o menor "
               f"entre wk1 = ø/(12,5 η1) · σs/Es · 3σs/fct,m e "
               f"wk2 = ø/(12,5 η1) · σs/Es · (4/ρr + 45), com η1 = "
               f"{_n(s.eta1)} (Tabela 8.2), fct,m = {_n(s.fctm)} MPa e ρr = "
               f"As/Acr; Acr é o quadrado de lado 15 ø centrado na barra, "
               f"dentro do concreto e repartido com as barras vizinhas "
               f"(Figura 17.4). Limite: wk ≤ {_n(s.wk_limite, 2)} mm "
               f"({s.origem_limite}).", italico=True)
    # um elemento XML só pode estar num lugar: cada equação monta o seu
    def comum():
        return [fr("ø", ["12,5 ", sub("η", "1")]), " ",
                fr(sub("σ", "s"), sub("E", "s")), " "]
    _equacao(doc, [sub("w", "k1"), " = ", *comum(),
                   fr(["3 ", sub("σ", "s")], sub("f", "ct,m"))])
    _equacao(doc, [sub("w", "k2"), " = ", *comum(),
                   par([fr("4", sub("ρ", "r")), " + 45"])])
    linhas = []
    for c in s.cotas:
        b = c.critica
        linhas.append([
            c.nome, _n(c.N, 1), _n(c.Mx / 100, 1), _n(c.My / 100, 1),
            _n(c.sigma_c_max, 1), _n(c.sigma_s_max, 0),
            _n(b.Acr, 1) if b else "—", _n(b.rho_r, 4) if b else "—",
            _n(b.wk1, 3) if b else "—", _n(b.wk2, 3) if b else "—",
            _n(c.wk_max, 3),
            "OK" if c.convergiu and c.wk_max <= s.wk_limite + 1e-9
            else "NÃO ATENDE"])
    _tabela(doc, 'Abertura de fissuras (ELS-W)', ["Cota", "Nk (kN)", "Mk,x (kN·m)", "Mk,y (kN·m)",
                  "σc máx (MPa)", "σs máx (MPa)", "Acr (cm²)", "ρr",
                  "wk1 (mm)", "wk2 (mm)", "wk (mm)", "Veredito"], linhas,
            [1.3, 1.5, 1.5, 1.5, 1.4, 1.4, 1.3, 1.3, 1.2, 1.2, 1.2, 1.6])
    gov = s.governante
    if gov is None or gov.critica is None:
        _paragrafo(doc,
                   "Nas duas cotas a seção fica inteiramente comprimida em "
                   "serviço: sem barra tracionada não há fissura de flexão, e "
                   "a abertura de fissuras fica atendida por consequência do "
                   "cálculo — a NBR 6118 não traz dispensa explícita para "
                   "pilar.", italico=True)
    if s.tabela_17_2 is not None:
        phi_max, s_max = s.tabela_17_2
        _paragrafo(doc,
                   f"Conferência pela Tabela 17.2 (controle sem cálculo de "
                   f"wk, ~0,3 mm), para a maior tensão de tração "
                   f"σs = {_n(max(c.sigma_s_max for c in s.cotas), 0)} MPa: "
                   f"ø ≤ {_n(phi_max)} mm e s ≤ "
                   f"{_n(s_max) + ' cm' if s_max else '—'}. Informativa: o "
                   f"veredito é o do cálculo de wk.", italico=True)


def _fadiga(doc: Document, res: ResultadoPilar, n: int) -> None:
    """ELU de fadiga do pilar de ponte (23.5; NBR 8681, Tabela 7)."""
    f = res.fadiga
    _titulo(doc, f"{n}. Estado-limite último de fadiga")
    if not f.aplicavel:
        _paragrafo(doc, ("Dispensada: " if "ψ1,fad = 0" in f.motivo
                         else "Não verificada: ") + f.motivo + ".")
        return
    _paragrafo(doc,
               f"Verificações das Equações abaixo. "
               f"Combinação frequente de fadiga (23.5.2): g + ψ1,fad · q, com "
               f"ψ1,fad = {_n(f.psi1, 1)} (NBR 8681:2025, Tabela 7) e a carga "
               f"móvel nas posições de máximo e de mínimo. Estádio II com "
               f"αe = 10 e γf = 1,0 (23.5.3). Armadura: Δσs ≤ Δfsd,fad da "
               f"Tabela 23.2 para 2 × 10⁶ ciclos (23.5.5). Concreto: "
               f"σc,máx ≤ 0,45 fcd = {_n(f.fcd_fad, 1)} MPa, com ηc = 1 do lado "
               f"seguro (23.5.4.1).", italico=True)
    _equacao(doc, [sub("Δσ", "s"), " ≤ ", sub("Δf", "sd,fad"), ",   ",
                   sub("σ", "c,máx"), " ≤ 0,45 ", sub("f", "cd")])
    linhas = []
    for c in f.cotas:
        b = c.barra_critica
        ok = c.convergiu and b[3] <= b[4] + 1e-9 and c.sigma_c_max <= f.fcd_fad + 1e-9
        linhas.append([c.nome, _n(b[3], 0), _n(b[4], 0), _n(c.sigma_c_max, 1),
                       _n(f.fcd_fad, 1), "OK" if ok else "NÃO ATENDE"])
    _tabela(doc, 'Estado-limite último de fadiga', ["Cota", "Δσs máx (MPa)", "Δfsd,fad (MPa)", "σc máx (MPa)",
                  "0,45 fcd (MPa)", "Veredito"], linhas,
            [2.0, 2.8, 2.8, 2.6, 2.6, 2.4])


def _detalhamento(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Detalhamento")
    a = res.arranjo
    if a is None:
        _paragrafo(doc, "Nenhum arranjo de barras foi escolhido.",
                   cor=VERMELHO)
        return
    from ..core import arranjo as arr_mod
    _titulo(doc, f"{n}.1 Armadura longitudinal", 2)
    s_min = arr_mod.espacamento_livre_minimo(a.phi, p.ambiente.dmax_agregado)
    _tabela(doc, 'Armadura longitudinal', ["Grandeza", "Valor", "Limite", "Item"], [
        ["Bitola", f"{a.descricao_bitolas()} mm",
         f"10 a {_n(arr_mod.bitola_maxima(p.secao), 1)} mm", "18.4.2.1"],
        ["Número de barras", str(a.n_barras), "—", "18.4.2.2"],
    ] + ([
        ["Barras por face em x", str(a.nx), "—", "—"],
        ["Barras por face em y", str(a.ny), "—", "—"],
    ] if p.secao.tipo.startswith("retangular") else []) + [
        ["As efetiva", f"{_n(a.As)} cm²",
         f"≥ {_n(res.As_minima)} cm² (As,mín)", "17.3.5.3.1"],
        ["Espaçamento livre", f"{_n(a.espacamento_livre)} cm",
         f"≥ {_n(s_min)} cm", "18.4.2.2"],
        ["Espaçamento entre eixos", f"{_n(a.espacamento_eixos)} cm",
         f"≤ {_n(arr_mod.espacamento_eixos_maximo(p.secao))} cm", "18.4.2.2"],
    ], [4.2, 3.4, 4.4, 2.0])

    e = res.estribos
    k = 2
    if e is not None:
        _titulo(doc, f"{n}.{k} Armadura transversal", 2)
        from ..core import estribos as est_mod
        _tabela(doc, 'Armadura transversal', ["Grandeza", "Valor", "Limite", "Item"], [
            ["Bitola do estribo", f"ø{_n(e.phi, 1)} mm",
             f"≥ {_n(est_mod.bitola_minima(a.phi))} mm", "18.4.3"],
            ["Espaçamento", f"{_n(e.s)} cm",
             f"≤ {_n(e.s_maximo)} cm ({e.motivo_s})", "18.4.3"],
            ["Estribos no lance", str(e.niveis), "—", "18.4.3"],
            ["Comprimento do estribo", f"{_n(e.comprimento)} cm", "—", "—"],
            ["Alcance da proteção 20 øt", f"{_n(e.alcance)} cm", "—",
             "18.2.4"],
            ["Grampos suplementares por nível", str(e.n_suplementares),
             "—", "18.2.4"],
        ], [4.6, 3.2, 4.4, 1.8])

    cis = [c for c in (res.cisalhamento or {}).values() if c.Vd > 0.0]
    if cis:
        _titulo(doc, f"{n}.{k}.1 Força cortante — item 17.4, modelo I", 3)
        _paragrafo(doc,
                   "Bielas a 45°, com a parcela complementar Vc constante "
                   "(item 17.4.2.2). O item 17.4.1.1.2-c) dispensa a "
                   "armadura transversal **de cisalhamento** no pilar "
                   "predominantemente comprimido enquanto VSd ≤ Vc e a seção "
                   "não fissura em estádio I; quando essa dispensa vale, o "
                   "estribo continua sendo o do item 18.4.3, e é isso que a "
                   "última linha de cada direção declara.")
        _paragrafo(doc,
                   "Altura útil d: da borda comprimida ao centroide de todas "
                   "as barras da metade tracionada da seção, medida nos dois "
                   "sentidos, valendo o menor. É um critério conservador: na "
                   "lógica de viga d vai só até a camada da face tracionada "
                   "(d = h − d′ com uma camada), mas no pilar a metade "
                   "tracionada inclui as barras intermediárias das faces "
                   "laterais, mais próximas do centro, e elas encurtam o d. "
                   "Um d menor reduz VRd2, Vc0 e Vsw. A norma não define a "
                   "armadura de tração do pilar em flexão composta, e o "
                   "programa fica com a leitura que dá menos resistência. "
                   "bw é a menor largura de material entre as barras extremas "
                   "da direção.", italico=True)
        linhas = []
        for c in cis:
            linhas += [
                [f"VSd, direção {c.direcao}", f"{_n(c.Vd, 1)} kN", "—",
                 "17.4.2.1"],
                [f"bw × d, direção {c.direcao}",
                 f"{_n(c.bw, 1)} × {_n(c.d, 1)} cm", "—", "17.4.2.2"],
                [f"VRd2, direção {c.direcao}", f"{_n(c.VRd2, 1)} kN",
                 f"{_pct(c.razao_biela)} usado", "17.4.2.2-a"],
                [f"Vc0 e Vc, direção {c.direcao}",
                 f"{_n(c.Vc0, 1)} → {_n(c.Vc, 1)} kN",
                 f"M0 = {_n(c.M0 / 100.0, 1)} kN·m", "17.4.2.2-b"],
                [f"Vsw, direção {c.direcao}", f"{_n(c.Vsw, 1)} kN",
                 f"Asw/s = {_n(c.Asw_s, 4)} cm²/cm", "17.4.2.2-b"],
                [f"VRd3 = Vc + Vsw, direção {c.direcao}",
                 f"{_n(c.VRd3, 1)} kN", f"{_pct(c.razao_tracao)} usado",
                 "17.4.2.2-b"],
                [f"Armadura mínima, direção {c.direcao}",
                 "dispensada" if c.dispensa_minima else "exigida",
                 f"tração em estádio I = {_n(c.tracao_estadio_1)} MPa "
                 f"(fctk = {_n(c.fctk)} MPa)", "17.4.1.1.2-c"],
            ]
            if not c.dispensa_minima:
                linhas.append(
                    [f"Espaçamento pela cortante, direção {c.direcao}",
                     f"{_n(c.s)} cm", f"≤ {_n(c.s_maximo)} cm", "18.3.3.2"])
        _tabela(doc, 'Força cortante pelo modelo de cálculo I', ["Grandeza", "Valor", "Limite ou origem", "Item"],
                linhas, [5.0, 3.2, 5.0, 1.8])

    if e is not None:
        k += 1
    anc = res.ancoragem
    if anc is not None:
        _titulo(doc, f"{n}.{k} Ancoragem e comprimento de espera", 2)
        k += 1
        if anc.tracionada:
            _equacao(doc, [sub("l", "0t"), " = ", sub("α", "0t"), " ",
                           sub("l", "b,nec")])
        else:
            _equacao(doc, [sub("l", "0c"), " = ", sub("l", "b"), " ",
                           fr(sub("A", "s,calc"), sub("A", "s,ef"))])
        _tabela(doc, 'Ancoragem e comprimento de espera', ["Grandeza", "Valor", "Item"], [
            ["fbd", f"{_n(anc.fbd, 4)} kN/cm²", "9.3.2.1"],
            ["lb básico", f"{_n(anc.lb, 1)} cm", "9.4.2.4"],
            ["lb necessário", f"{_n(anc.lb_nec, 1)} cm", "9.4.2.5"],
        ] + ([
            ["α0t (Tabela 9.4)", _n(anc.alfa_0t, 1), "9.5.2.2.1"],
        ] if anc.tracionada else []) + [
            [f"{anc.simbolo} (espera)", f"{_n(anc.l0c, 1)} cm", anc.item],
            [f"{anc.simbolo} mínimo", f"{_n(anc.l0c_min, 1)} cm", anc.item],
        ], [5.0, 5.0, 5.0])
        if anc.tracionada:
            _paragrafo(doc,
                       f"Há barra tracionada nas solicitações de cálculo "
                       f"({anc.motivo}). Por critério de projeto, **todas** as "
                       f"barras levam a emenda de barras tracionadas, "
                       f"l0t = α0t · lb,nec com piso no maior entre "
                       f"0,3 α0t lb, 15 ø e 20 cm (item 9.5.2.2.1); com todas "
                       f"comprimidas seria l0c = {_n(anc.l0c_compressao, 1)} cm.",
                       italico=True)
        else:
            _paragrafo(doc,
                       "Nenhuma barra fica tracionada nas solicitações de "
                       "cálculo: l0c = lb · As,calc/As,ef, com piso no maior "
                       "entre 0,6 lb, 15 ø e 20 cm (item 9.5.2.3).",
                       italico=True)
        _paragrafo(doc,
                   "O comprimento de espera é medido a partir da face "
                   "superior do lance, e a emenda dobra a taxa de armadura "
                   "naquele trecho — o que o item 17.3.5.3.2 conta dentro "
                   "dos 8 %.", italico=True)

    _titulo(doc, f"{n}.{k} Quantitativo do lance", 2)
    massa_long = a.massa(p.lance.altura + (anc.l0c if anc else 0.0))
    _tabela(doc, 'Quantitativo de aço do lance', ["Peça", "Descrição", "Comprimento unitário",
                  "Quantidade", "Massa (kg)"], [
        ["Longitudinal", f"{a.descricao_bitolas()} mm",
         f"{_n(p.lance.altura + (anc.l0c if anc else 0.0), 0)} cm",
         str(a.n_barras), _n(massa_long, 1)],
        ["Estribo", f"ø{_n(e.phi, 1)} mm" if e else "—",
         f"{_n(e.comprimento, 0)} cm" if e else "—",
         str(e.niveis) if e else "—", _n(e.massa, 1) if e else "—"],
    ], [3.0, 4.0, 3.6, 2.4, 2.6])
    _paragrafo(doc, f"Massa total de aço do lance: "
                    f"{_n(res.massa_total, 1)} kg.")

    from ..core import quantitativos as qt
    q = qt.calcular(res)
    _tabela(doc, 'Quantitativo de materiais do lance', ["Insumo", "Quantidade", "Unidade", "Como sai"], [
        ["Concreto", _n(q.volume_concreto, 3), "m³",
         f"Ac × h = {_n(p.secao.area, 0)} cm² × {_n(q.altura, 0)} cm"],
        ["Formas", _n(q.area_formas, 2), "m²",
         f"perímetro × h = {_n(q.perimetro, 1)} cm × {_n(q.altura, 0)} cm"],
        ["Aço", _n(q.massa_aco, 1), "kg", "longitudinal + transversal"],
        ["Taxa de aço", _n(q.taxa_aco, 0), "kg/m³", "aço / concreto"],
    ], [3.0, 2.6, 2.0, 8.0])
    _paragrafo(doc,
               "Formas: apenas as faces laterais, as que contêm o concreto "
               "fresco — todo o perímetro vertical, inclusive o dos vazios. "
               "As faces horizontais ficam fora: a de baixo apoia no que já "
               "foi concretado e a de cima é por onde se lança o concreto. "
               "Cruzamentos com vigas e lajes não são descontados.",
               italico=True)
    _figura(doc, 'Elevação esquemática do lance', graficos.figura_elevacao(res), 9.0)


def _roteiro(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Roteiro de verificações")
    verificacoes = auditoria.roteiro(res)
    resumo = auditoria.resumo(verificacoes)
    _paragrafo(doc, "  ".join(f"{k}: {v}" for k, v in resumo.items()),
               italico=True)
    _tabela(doc, 'Roteiro de verificações', ["Item", "Verificação", "Critério", "Resultado",
                  "Situação"],
            [[v.item, v.descricao, v.criterio, v.resultado, v.situacao]
             for v in verificacoes],
            [1.8, 3.4, 4.2, 4.2, 2.4])


def _pendencias(doc: Document, res: ResultadoPilar, n: int) -> None:
    erros, construtivos = avisos_mod.separar(res.avisos)
    _titulo(doc, f"{n}. Observações e pendências")
    if erros:
        _titulo(doc, f"{n}.1 Verificações não atendidas", 2)
        _alineas(doc, erros, negrito=True)
    else:
        _paragrafo(doc, "Nenhuma verificação foi reprovada.")
    if construtivos:
        _titulo(doc, f"{n}.2 Decisões de detalhamento e ressalvas", 2)
        _alineas(doc, construtivos)


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------

def _anexo_combinacao(doc: Document, r: ResultadoPilar, letra: str) -> None:
    """Uma combinação (ou método) que não governa, detalhada como anexo: as
    mesmas seções da principal, da esbeltez à verificação, com a mesma
    armadura."""
    _titulo_sem_numero(doc, f"Anexo {letra} – {r.pilar.nome_combinacao}",
                       sumario=True)
    situacao = "atende" if r.ok else "NÃO ATENDE"
    _paragrafo(doc,
               f"Combinação {r.pilar.nome_combinacao}"
               + (f" (Fd = {r.pilar.descricao_combinacao})"
                  if r.pilar.descricao_combinacao else "")
               + f", com a mesma armadura "
               f"({r.arranjo.descricao() if r.arranjo else '-'}): {situacao}"
               + (f", menor F.S. = {_n(min(v.fs for v in r.verificacoes), 2)}"
                  if r.verificacoes else "") + ".")
    n = 1
    for secao in (_esbeltez, _segunda_ordem, _situacoes, _verificacao):
        secao(doc, r, f"{letra}.{n}")
        n += 1
    if r.erros:
        _titulo(doc, f"{letra}.{n} Verificações não atendidas", 2)
        _alineas(doc, [a.split("] ", 1)[-1] for a in r.erros], negrito=True)


def gerar(res: ResultadoPilar, caminho: str,
          todas_combinacoes: bool = False) -> str:
    """Gera a memória de cálculo em .docx e devolve o caminho do arquivo.

    ``todas_combinacoes``: além da que governa (o corpo da memória), cada
    uma das outras combinações -- ou métodos, no caso mais conservador --
    sai detalhada num anexo, com as mesmas seções da esbeltez à
    verificação."""
    doc = Document()
    _configurar(doc)
    # pré-textuais (NBR 10719): sem número de página impresso
    _folha_de_rosto(doc, res)
    _resumo_abnt(doc, res)
    _sumario(doc, "Lista de figuras", 'TOC \\h \\z \\c "Figura"',
             "Atualize o campo (F9) para gerar a lista de figuras.")
    _sumario(doc, "Lista de tabelas", 'TOC \\h \\z \\c "Tabela"',
             "Atualize o campo (F9) para gerar a lista de tabelas.")
    _sumario(doc, "Sumário", 'TOC \\o "1-3" \\h \\z \\u',
             "Atualize o campo (F9) para gerar o sumário.")
    # textuais: página numerada no canto superior direito
    _secao_textual(doc)
    n = 1
    _identificacao(doc, res, n); n += 1
    _metodologia(doc, res, n); n += 1
    _dados(doc, res, n); n += 1
    if res.pilar.acoes:
        _acoes(doc, res, n); n += 1
    if res.combinacoes:
        _combinacoes(doc, res, n); n += 1
    _esbeltez(doc, res, n); n += 1
    _segunda_ordem(doc, res, n); n += 1
    _situacoes(doc, res, n); n += 1
    _dimensionamento(doc, res, n); n += 1
    _verificacao(doc, res, n); n += 1
    _servico(doc, res, n); n += 1
    if res.fadiga is not None and res.fadiga.obra:
        _fadiga(doc, res, n); n += 1
    _detalhamento(doc, res, n); n += 1
    _roteiro(doc, res, n); n += 1
    _pendencias(doc, res, n)
    # pós-textuais
    _referencias(doc, res)
    if todas_combinacoes and res.resultados_combinacoes:
        outras = [r for r in res.resultados_combinacoes if r is not res]
        for i, r in enumerate(outras):
            _anexo_combinacao(doc, r, _letra_anexo(i))
    doc.save(caminho)
    return caminho


def _letra_anexo(i: int) -> str:
    """A, B, ..., Z, AA, AB, ..."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _atualizar_no_word(doc_word) -> None:
    """Atualiza os campos (sumário, listas, SEQ, PAGE) de um documento
    aberto no Word: duas passadas, porque a primeira atualização do sumário
    pode mudar a paginação que ele mesmo mostra."""
    for _ in range(2):
        doc_word.Fields.Update()
        for i in range(1, doc_word.TablesOfContents.Count + 1):
            doc_word.TablesOfContents(i).Update()
        for i in range(1, doc_word.TablesOfFigures.Count + 1):
            doc_word.TablesOfFigures(i).Update()


def atualizar_campos(caminho_docx: str) -> bool:
    """Preenche o sumário e as listas pelo próprio Word (COM) e tira do
    arquivo o pedido de atualização ao abrir. Sem o Word, devolve ``False``
    e o arquivo fica como está -- o Word do usuário atualiza ao abrir."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    caminho_docx = os.path.abspath(caminho_docx)
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        d = word.Documents.Open(caminho_docx)
        _atualizar_no_word(d)
        d.Save()
        d.Close(False)
    except Exception:                                   # noqa: BLE001
        return False
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:                           # noqa: BLE001
                pass
        pythoncom.CoUninitialize()
    # já atualizado: o arquivo não precisa mais pedir ao abrir
    d = Document(caminho_docx)
    el = d.settings.element.find(qn("w:updateFields"))
    if el is not None:
        d.settings.element.remove(el)
        d.save(caminho_docx)
    return True


def exportar_pdf(caminho_docx: str, caminho_pdf: str | None = None) -> str:
    """Converte o .docx em PDF pelo Word (COM), com o sumário e as listas
    atualizados. Requer Word instalado."""
    import pythoncom
    import win32com.client

    caminho_docx = os.path.abspath(caminho_docx)
    if caminho_pdf is None:
        caminho_pdf = os.path.splitext(caminho_docx)[0] + ".pdf"
    caminho_pdf = os.path.abspath(caminho_pdf)
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(caminho_docx, ReadOnly=True)
        _atualizar_no_word(doc)
        doc.SaveAs(caminho_pdf, FileFormat=17)     # wdFormatPDF
        doc.Close(False)
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()
    return caminho_pdf
