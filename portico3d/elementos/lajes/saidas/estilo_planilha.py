# -*- coding: utf-8 -*-
"""
estilo_planilha.py
Primitivas de formatação das planilhas no padrão Ecoplan: fonte Aptos em três
corpos, paleta de preenchimentos, réguas horizontais na memória de cálculo,
alturas de linha fixas e formatos numéricos com a unidade embutida.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.formatting.rule import Rule
from openpyxl.worksheet.worksheet import Worksheet

FONTE = "Aptos"

COR = {
    "titulo": "1F3864",
    "entrada": "0000FF",
    "vinculo": "008000",
    "alerta": "C00000",
    "auxiliar": "7F7F7F",
    "secao": "BFBFBF",
    "cabecalho": "D9D9D9",
    "corpo": "F2F2F2",
    "subcabecalho": "D9E2F3",
    "chave": "FFF2CC",
    "ressalva": "FDF1C7",
    "elu": "FBE5D6",
    "els": "E2EFDA",
}

NF = {
    "m": '0.000\\ "m"',
    "cm": '0.0\\ "cm"',
    "cm2": '0.0\\ "cm²"',
    "cm2m": '0.00\\ "cm²/m"',
    "cm4": '#,##0\\ "cm⁴"',
    "mm": '0.00\\ "mm"',
    "MPa": '0.00\\ "MPa"',
    "kNcm2": '0.0000\\ "kN/cm²"',
    "kN": '#,##0.0;-#,##0.0;-',
    "kNm": '#,##0.0;-#,##0.0;-',
    "kNm2": '#,##0\\ "kN·m²"',
    "kgm": '0.000\\ "kg/m"',
    "kg": '#,##0.0\\ "kg"',
    "bitola": '"ø "\\ 0.0"mm"',
    "espacamento": '"C/"0" cm"',
    "barras": '0\\ "barra(s)"',
    "ramos": '0\\ "ramo(s)"',
    "coef": '0.00',
    "coef3": '0.000',
    "grau": '0.0\\ "°"',
    "inteiro": '#,##0',
    "perc": '0.00%',
    "adm": '0.000',
    "texto": "@",
}

ALTURA = {"dados": 18.0, "separadora": 8.1, "cabecalho": 30.0}

_fina = Side(style="thin", color="BFBFBF")
_pont = Side(style="dotted", color="BFBFBF")
_media = Side(style="medium", color="BFBFBF")

REGUA = Border(top=_fina, bottom=_fina)
GRADE = Border(left=_fina, right=_fina, top=_fina, bottom=_fina)
LATERAIS = Border(left=_pont, right=_pont)
TITULO_BORDA = Border(bottom=_media)
CABECALHO_BORDA = Border(left=_fina, right=_fina, bottom=_pont)

CTR = Alignment(horizontal="center", vertical="center", wrap_text=True)
DIR = Alignment(horizontal="right", vertical="center")
ESQ = Alignment(horizontal="left", vertical="center", indent=1)

#: Colunas do layout de memória de cálculo.
COL_ROTULO, COL_VALOR, COL_VEREDITO, COL_DESCRICAO, COL_REF = 2, 3, 4, 5, 6
LARGURAS_MEMORIA = {"A": 3.71, "B": 20.43, "C": 30.14, "D": 11.29,
                    "E": 32.43, "F": 30.0, "G": 3.71}


def preparar_memoria(ws: Worksheet, larguras: dict | None = None) -> None:
    """Aplica ao layout vertical as larguras e o ocultamento das grades."""
    ws.sheet_view.showGridLines = False
    for col, larg in (larguras or LARGURAS_MEMORIA).items():
        ws.column_dimensions[col].width = larg


def preparar_tabela(ws: Worksheet, larguras: list[float],
                    col_inicial: int = 2) -> None:
    """Aplica as larguras de uma aba tabular, com respiro nas pontas."""
    from openpyxl.utils import get_column_letter

    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3.71
    for i, larg in enumerate(larguras):
        ws.column_dimensions[get_column_letter(col_inicial + i)].width = larg
    ws.column_dimensions[
        get_column_letter(col_inicial + len(larguras))].width = 3.71


def _fonte(corpo: int = 11, negrito: bool = False, italico: bool = False,
           cor: str | None = None) -> Font:
    return Font(name=FONTE, size=corpo, bold=negrito, italic=italico,
                color=cor)


def titulo(ws: Worksheet, linha: int, texto: str, col_ini: int = 2,
           col_fim: int = 6) -> int:
    """Título da aba: 12 negrito, mesclado, borda média embaixo."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    c = ws.cell(linha, col_ini, texto)
    c.font = _fonte(12, negrito=True, cor=COR["titulo"])
    c.alignment = CTR
    for col in range(col_ini, col_fim + 1):
        ws.cell(linha, col).border = TITULO_BORDA
    ws.merge_cells(start_row=linha, start_column=col_ini,
                   end_row=linha, end_column=col_fim)
    return linha + 1


def nota(ws: Worksheet, linha: int, texto: str, col_ini: int = 2,
         col_fim: int = 6) -> int:
    """Nota de escopo ou referência normativa: 10 itálico centralizado."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    c = ws.cell(linha, col_ini, texto)
    c.font = _fonte(10, italico=True)
    c.alignment = CTR
    ws.merge_cells(start_row=linha, start_column=col_ini,
                   end_row=linha, end_column=col_fim)
    return linha + 1


def secao(ws: Worksheet, linha: int, texto: str, col_ini: int = 2,
          col_fim: int = 6, cor: str | None = None) -> int:
    """Faixa de seção em caixa alta, fundo cinza, mesclada."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    c = ws.cell(linha, col_ini, texto.upper())
    c.font = _fonte(11, negrito=True)
    c.alignment = CTR
    c.fill = PatternFill("solid", fgColor=cor or COR["secao"])
    for col in range(col_ini, col_fim + 1):
        ws.cell(linha, col).fill = PatternFill(
            "solid", fgColor=cor or COR["secao"])
    ws.merge_cells(start_row=linha, start_column=col_ini,
                   end_row=linha, end_column=col_fim)
    return linha + 1


def separador(ws: Worksheet, linha: int) -> int:
    ws.row_dimensions[linha].height = ALTURA["separadora"]
    return linha + 1


def grandeza(ws: Worksheet, linha: int, rotulo: str, valor,
             descricao: str = "", formato: str | None = None,
             entrada: bool = False, referencia: str = "",
             cor: str | None = None) -> int:
    """Uma linha de grandeza: rótulo, valor, descrição e referência."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    r = ws.cell(linha, COL_ROTULO, rotulo)
    r.font = _fonte(11)
    r.alignment = DIR
    r.border = REGUA
    v = ws.cell(linha, COL_VALOR, valor)
    v.font = _fonte(11, cor=cor or (COR["entrada"] if entrada else None))
    v.alignment = ESQ
    v.border = REGUA
    if formato:
        v.number_format = formato
    ws.cell(linha, COL_VEREDITO).border = REGUA
    d = ws.cell(linha, COL_DESCRICAO, descricao)
    d.font = _fonte(10, italico=True)
    d.alignment = ESQ
    d.border = REGUA
    if referencia:
        ref = ws.cell(linha, COL_REF, referencia)
        ref.font = _fonte(10, italico=True, cor=COR["auxiliar"])
        ref.alignment = ESQ
        ref.border = Border(left=_pont, top=_fina, bottom=_fina)
    return linha + 1


def expressao(ws: Worksheet, linha: int, rotulo: str, texto: str) -> int:
    """Linha de expressão algébrica, em texto, acima da fórmula que a avalia."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    r = ws.cell(linha, COL_ROTULO, rotulo)
    r.font = _fonte(11)
    r.alignment = DIR
    r.border = REGUA
    v = ws.cell(linha, COL_VALOR, texto)
    v.font = _fonte(10, italico=True, cor=COR["auxiliar"])
    v.alignment = ESQ
    v.border = REGUA
    for col in (COL_VEREDITO, COL_DESCRICAO):
        ws.cell(linha, col).border = REGUA
    return linha + 1


def veredito(ws: Worksheet, linha: int, rotulo: str, formula: str,
             descricao: str = "") -> int:
    """Linha de veredito com formatação condicional OK / NÃO OK."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    r = ws.cell(linha, COL_ROTULO, rotulo)
    r.font = _fonte(11)
    r.alignment = DIR
    r.border = REGUA
    ws.cell(linha, COL_VALOR).border = REGUA
    c = ws.cell(linha, COL_VEREDITO, formula)
    c.font = _fonte(11, negrito=True)
    c.alignment = CTR
    c.border = REGUA
    d = ws.cell(linha, COL_DESCRICAO, descricao)
    d.font = _fonte(10, italico=True)
    d.alignment = ESQ
    d.border = REGUA
    aplicar_condicional(ws, c.coordinate)
    return linha + 1


def aplicar_condicional(ws: Worksheet, intervalo: str) -> None:
    """Negrito para OK, vermelho para 'não', amarelo para 'idealmente'."""
    regras = (
        ("OK", DifferentialStyle(font=Font(bold=True))),
        ("não", DifferentialStyle(font=Font(bold=True, color=COR["alerta"]))),
        ("idealmente", DifferentialStyle(
            font=Font(bold=True),
            fill=PatternFill("solid", fgColor=COR["ressalva"]))),
    )
    for texto, dxf in regras:
        ws.conditional_formatting.add(intervalo, Rule(
            type="containsText", operator="containsText", text=texto, dxf=dxf,
            formula=[f'NOT(ISERROR(SEARCH("{texto}",'
                     f'{intervalo.split(":")[0]})))']))


def cabecalho(ws: Worksheet, linha: int, titulos: list[str],
              col_inicial: int = 2) -> int:
    """Cabeçalho de tabela: caixa alta, 11 negrito, fundo cinza, altura 30."""
    ws.row_dimensions[linha].height = ALTURA["cabecalho"]
    for i, texto in enumerate(titulos):
        c = ws.cell(linha, col_inicial + i, str(texto).upper())
        c.font = _fonte(11, negrito=True)
        c.alignment = CTR
        c.fill = PatternFill("solid", fgColor=COR["cabecalho"])
        c.border = CABECALHO_BORDA
    return linha + 1


def linha_tabela(ws: Worksheet, linha: int, valores: list,
                 formatos: list[str | None] | None = None,
                 col_inicial: int = 2, cores: list[str | None] | None = None
                 ) -> int:
    """Uma linha do corpo de uma tabela tabular."""
    ws.row_dimensions[linha].height = ALTURA["dados"]
    for i, valor in enumerate(valores):
        c = ws.cell(linha, col_inicial + i, valor)
        c.font = _fonte(11, cor=(cores[i] if cores else None))
        c.alignment = ESQ if i == 0 else CTR
        c.fill = PatternFill("solid", fgColor=COR["corpo"])
        c.border = GRADE
        if formatos and i < len(formatos) and formatos[i]:
            c.number_format = formatos[i]
    return linha + 1


def legenda(ws: Worksheet, linha: int, itens: list[tuple[str, str]],
            col_ini: int = 2) -> int:
    """Bloco de legenda de símbolos, 10 itálico com marcador."""
    for i, (simbolo, texto) in enumerate(itens):
        ws.row_dimensions[linha].height = ALTURA["dados"]
        c = ws.cell(linha, col_ini, f"▪ {simbolo} -")
        c.font = _fonte(10, italico=True)
        c.alignment = DIR
        c.border = LATERAIS
        d = ws.cell(linha, col_ini + 1,
                    texto + (";" if i < len(itens) - 1 else "."))
        d.font = _fonte(10, italico=True)
        d.alignment = ESQ
        linha += 1
    return linha


def normalizar_alturas(wb) -> None:
    """Restaura as três alturas do padrão depois de um recálculo externo."""
    for ws in wb.worksheets:
        for _, d in ws.row_dimensions.items():
            if d.height is None:
                continue
            h = round(d.height, 1)
            d.height = 8.1 if h < 12 else (30.0 if h > 24 else 18.0)
