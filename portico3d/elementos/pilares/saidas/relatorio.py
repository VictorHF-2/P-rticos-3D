# -*- coding: utf-8 -*-
"""
relatorio.py
Memória de cálculo em Word (.docx), com os dados de entrada, a esbeltez, os
efeitos locais de segunda ordem, as situações de cálculo, o dimensionamento da
seção passo a passo, o detalhamento e o roteiro de verificações. Cada
resultado traz o item da NBR 6118 que o justifica.

A conversão para PDF é feita pelo próprio Word, via COM, quando disponível.
"""

from __future__ import annotations

import math
import os
import tempfile

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from . import auditoria, graficos
from .. import EDICAO_NORMA, __version__
from ..core import avisos as avisos_mod
from ..core.dimensionar import ResultadoPilar
from ..core.flexocompressao import DESCRICAO_CASO
from ..core.materiais import DESCRICAO_COMBINACAO
from ..core.modelo import VINCULOS

AZUL = RGBColor(0x1F, 0x4E, 0x79)
CINZA = RGBColor(0x59, 0x59, 0x59)
VERMELHO = RGBColor(0xA5, 0x23, 0x2F)


# ---------------------------------------------------------------------------
# Primitivas
# ---------------------------------------------------------------------------

def _configurar(doc: Document) -> None:
    estilo = doc.styles["Normal"]
    estilo.font.name = "Aptos"
    estilo.font.size = Pt(10)
    for i, tamanho in ((1, 14), (2, 12), (3, 11)):
        h = doc.styles[f"Heading {i}"]
        h.font.name = "Aptos"
        h.font.size = Pt(tamanho)
        h.font.color.rgb = AZUL
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.0)


def _titulo(doc: Document, texto: str, nivel: int = 1) -> None:
    doc.add_heading(texto, level=nivel)


def _paragrafo(doc: Document, texto: str, italico: bool = False,
               cor: RGBColor | None = None) -> None:
    p = doc.add_paragraph()
    r = p.add_run(texto)
    r.italic = italico
    if cor is not None:
        r.font.color.rgb = cor


def _tabela(doc: Document, cabecalho: list[str], linhas: list[list],
            larguras: list[float] | None = None) -> None:
    t = doc.add_table(rows=1, cols=len(cabecalho))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, texto in enumerate(cabecalho):
        cel = t.rows[0].cells[i]
        cel.text = str(texto)
        for p in cel.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(9)
    for linha in linhas:
        cels = t.add_row().cells
        for i, valor in enumerate(linha):
            cels[i].text = "" if valor is None else str(valor)
            for p in cels[i].paragraphs:
                p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if i == 0
                               else WD_ALIGN_PARAGRAPH.CENTER)
                for r in p.runs:
                    r.font.size = Pt(9)
    if larguras:
        for linha in t.rows:
            for cel, larg in zip(linha.cells, larguras):
                cel.width = Cm(larg)
    doc.add_paragraph()


def _figura(doc: Document, fig, largura_cm: float = 15.0) -> None:
    caminho = os.path.join(tempfile.gettempdir(), f"pilar_fig_{id(fig)}.png")
    fig.savefig(caminho, dpi=160, bbox_inches="tight")
    doc.add_picture(caminho, width=Cm(largura_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    try:
        os.remove(caminho)
    except OSError:
        pass


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
# Seções do relatório
# ---------------------------------------------------------------------------

def _capa(doc: Document, res: ResultadoPilar) -> None:
    p = res.pilar
    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run("MEMÓRIA DE CÁLCULO\nDIMENSIONAMENTO DE PILAR DE "
                    "CONCRETO ARMADO")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = AZUL
    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run("ABNT NBR 6118 — Projeto de estruturas de concreto")
    r.italic = True
    r.font.color.rgb = CINZA
    # Quem lê a memória meses depois precisa saber qual revisão do programa e
    # qual edição da norma produziram estes números: a numeração dos itens
    # citados adiante muda de 2014 para 2026.
    par = doc.add_paragraph()
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run(f"Programa Pilares {__version__} — {EDICAO_NORMA}")
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = CINZA
    doc.add_paragraph()
    linhas = [
        ["Pilar", p.nome],
        ["Projeto", p.projeto or "-"],
        ["Seção transversal", p.secao.descricao()],
        ["Área de concreto", f"{_n(p.secao.area, 0)} cm²"],
        ["Comprimento do lance", f"{_n(p.lance.altura, 0)} cm"],
        ["Concreto", f"C{_n(p.concreto.fck, 0)} "
                     f"(fcd = {_n(p.concreto.fcd)} MPa)"],
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
    _tabela(doc, ["Item", "Descrição"], linhas, [5.0, 11.0])


def _metodologia(doc: Document, res: ResultadoPilar, n: int) -> None:
    """Como o cálculo foi feito, e o que ficou fora dele."""
    p = res.pilar
    cfg = p.config
    _titulo(doc, f"{n}. Metodologia e escopo")
    _paragrafo(doc,
               "O cálculo segue a ABNT NBR 6118 e trata um **lance isolado** "
               "de pilar, de seção e armadura constantes ao longo do eixo, "
               "com os esforços de primeira ordem conhecidos no topo e na "
               "base. Os esforços globais de segunda ordem, o desaprumo e as "
               "combinações de ações são anteriores a este cálculo e entram "
               "nos valores de Nd e M1d informados.")
    _titulo(doc, f"{n}.1 Cadeia de cálculo", 2)
    _tabela(doc, ["Etapa", "Item da NBR 6118", "O que foi feito"], [
        ["Esbeltez", "15.8.1 e 15.8.2",
         "λ = le/i em cada direção, comparada com λ₁ = (25 + 12,5 e₁/h)/α_b"],
        ["Momento mínimo", "11.3.3.4.3",
         "e₁,mín = 1,5 + 0,03 h, aplicada como piso do momento de 1ª ordem, "
         "separadamente em cada direção"],
        ["Força cortante", "17.4.2.2 e 17.4.1.1.2-c",
         "modelo I quando Vd é informada; a alínea c) diz quando o estribo "
         "construtivo do 18.4.3 basta"],
        ["Segunda ordem local", "15.8.3.3.2 e 15.8.3.3.3",
         f"pilar-padrão com curvatura e com rigidez aproximadas; critério "
         f"adotado: {cfg.metodo_2a_ordem}"],
        ["Situações de cálculo", "15.8.3.3.5",
         "extremidades A e B e seção intermediária, com a composição dos "
         "momentos nas duas direções"],
        ["Dimensionamento", "17.2.2",
         "roteiro dos casos fechados FC1–FC4 / FT1–FT4 (seção retangular) e "
         "motor seccional por integração do diagrama parábola-retângulo"],
        ["Verificação oblíqua", "17.2.5",
         f"(MSd,x/MRd,xx)^α + (MSd,y/MRd,yy)^α ≤ 1, com α = "
         f"{_n(res.pilar.alfa_interacao)}, mais a envoltória de equilíbrio"],
        ["Detalhamento", "18.4.2, 18.4.3 e 18.2.4",
         "bitolas, taxas, espaçamentos, estribos e proteção contra "
         "flambagem das barras"],
        ["Ancoragem", "9.4.2 e 9.5.2.3",
         "comprimento de ancoragem básico e comprimento de espera"],
    ], [3.2, 3.0, 9.0])

    _titulo(doc, f"{n}.2 Os dois motores de cálculo, e qual deles vale", 2)
    _paragrafo(doc,
               "A seção é resolvida por dois caminhos independentes, de "
               "propósito.")
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
               "O primeiro dá a armadura de partida; o segundo dá o "
               "veredito. Onde os dois divergem, a divergência é declarada "
               "no quadro de conferência, e prevalece o motor seccional.",
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
    _tabela(doc, ["Grandeza", "Item", "Valor e origem"], linhas,
            [4.2, 2.4, 9.4])

    _titulo(doc, f"{n}.4 O que este cálculo não verifica", 2)
    _paragrafo(doc,
               "Estabilidade global (itens 15.6 e 15.7), imperfeições "
               "geométricas globais (11.3.3.4.1), combinações de ações "
               "(16.2.3), torção (17.5) e fadiga (seção 23). A força "
               "cortante (17.4) é verificada pelo modelo I quando "
               "informada, e declarada como não aplicável quando não. "
               "O roteiro de verificações ao final relaciona cada uma delas "
               "como não verificada, com o motivo.")


def _dados(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Dados de entrada")
    _titulo(doc, f"{n}.1 Seção e materiais", 2)
    prop = p.secao.propriedades()
    _tabela(doc, ["Grandeza", "Valor", "Referência"], [
        ["Tipo de seção", p.secao.tipo, "—"],
        ["hx (direção x)", f"{_n(p.secao.hx)} cm", "—"],
        ["hy (direção y)", f"{_n(p.secao.hy)} cm", "—"],
        ["Área bruta Ac", f"{_n(prop.area, 0)} cm²", "13.2.3"],
        ["Raio de giração ix", f"{_n(prop.ix)} cm", "15.8.2"],
        ["Raio de giração iy", f"{_n(prop.iy)} cm", "15.8.2"],
        ["Menor dimensão", f"{_n(p.secao.menor_dimensao)} cm", "13.2.3"],
        ["Coeficiente adicional γn", _n(p.gamma_n), "Tabela 13.1"],
        ["fck", f"{_n(p.concreto.fck, 0)} MPa", "8.2.4"],
        ["fcd", f"{_n(p.concreto.fcd)} MPa "
                f"({_n(p.concreto.fcd_kNcm2, 4)} kN/cm²)", "12.3.3"],
        ["α_c", _n(p.concreto.alfa_c), "17.2.2"],
        ["λ (altura do bloco)", _n(p.concreto.lambda_bloco), "17.2.2"],
        ["ε_c2", f"{_n(p.concreto.eps_c2_mil)} ‰", "8.2.10.1"],
        ["ε_cu", f"{_n(p.concreto.eps_cu_mil)} ‰", "8.2.10.1"],
        ["Aço longitudinal", p.aco.categoria, "8.3"],
        ["fyd", f"{_n(p.aco.fyd)} MPa "
                f"({_n(p.aco.fyd_kNcm2)} kN/cm²)", "8.3.6"],
        ["ε_yd", f"{_n(p.aco.eps_yd_mil, 4)} ‰", "8.3.6"],
        ["Es", f"{_n(p.aco.Es, 0)} MPa", "8.3.5"],
    ], [5.5, 5.5, 5.0])

    _titulo(doc, f"{n}.2 Esforços de primeira ordem e vinculação", 2)
    f = p.fator_esforcos
    e = p.esforcos
    _tabela(doc, ["Grandeza", "Entrada", "De cálculo (× γf γn)"], [
        ["Nd", f"{_n(e.Nd, 1)} kN", f"{_n(p.Nd, 1)} kN"],
        ["M1d,x no topo", f"{_n(e.Mx_topo, 1)} kN·cm",
         f"{_n(f * e.Mx_topo, 1)} kN·cm"],
        ["M1d,x na base", f"{_n(e.Mx_base, 1)} kN·cm",
         f"{_n(f * e.Mx_base, 1)} kN·cm"],
        ["M1d,y no topo", f"{_n(e.My_topo, 1)} kN·cm",
         f"{_n(f * e.My_topo, 1)} kN·cm"],
        ["M1d,y na base", f"{_n(e.My_base, 1)} kN·cm",
         f"{_n(f * e.My_base, 1)} kN·cm"],
    ], [5.5, 5.5, 5.0])
    _tabela(doc, ["Direção", "le (cm)", "Origem do le", "Vinculação",
                  "M1d,A (kN·cm)", "M1d,B (kN·cm)"], [
        [d, _n(p.le(d), 0), p.le_memoria(d), VINCULOS[p.lance.vinculo(d)],
         _n(p.M1d_A(d), 1), _n(p.M1d_B(d), 1)] for d in ("x", "y")
    ], [1.6, 1.8, 5.2, 3.6, 2.4, 2.4])
    _paragrafo(doc,
               "M1d,A é o maior momento de primeira ordem em módulo e M1d,B "
               "o do outro extremo, positivo quando traciona a mesma face "
               "que M1d,A e negativo em caso contrário (item 15.8.2). É o "
               "sinal de M1d,B que distingue a curvatura simples da reversa "
               "e, por ele, define o α_b.", italico=True)
    _figura(doc, graficos.figura_secao(res), 12.0)


def _esbeltez(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Esbeltez e dispensa dos efeitos de 2ª ordem")
    linhas = []
    for d in ("x", "y"):
        e = res.esbeltez[d]
        linhas.append([
            d, _n(e.h), _n(e.i), _n(e.le, 0), _n(e.lam, 1), _n(e.e1, 3),
            _n(e.e1_min), _n(e.alfa_b), _n(e.lam_1, 1), e.veredito])
    _tabela(doc, ["Dir.", "h (cm)", "i (cm)", "le (cm)", "λ", "e₁ (cm)",
                  "e₁,mín (cm)", "α_b", "λ₁", "Conclusão"], linhas,
            [1.4, 1.6, 1.6, 1.6, 1.4, 1.6, 1.8, 1.2, 1.4, 3.4])
    _paragrafo(doc,
               "λ = le/i, forma geral que vale para qualquer seção. Na seção "
               "retangular ela coincide com λ = 3,46 le/h, porque "
               "i = h/√12 e √12 = 3,4641.", italico=True)
    _paragrafo(doc,
               "λ₁ = (25 + 12,5 e₁/h)/α_b, com 35 ≤ λ₁ ≤ 90 (item 15.8.2). "
               "Quando o momento de primeira ordem fica abaixo do momento "
               "mínimo, α_b = 1,0.", italico=True)


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
    _tabela(doc, ["Dir.", "ν", "1/r (cm⁻¹)", "e₂ curvatura (cm)",
                  "e₂ rigidez (cm)", "e₂ adotado (cm)", "Método"], linhas,
            [1.4, 1.6, 2.2, 2.6, 2.6, 2.6, 3.0])
    _paragrafo(doc,
               "Curvatura aproximada (15.8.3.3.2): e₂ = le²/10 · 1/r, com "
               "1/r = 0,005/[h(ν + 0,5)] ≤ 0,005/h e ν = Nd/(Ac fcd).",
               italico=True)
    _paragrafo(doc,
               "Rigidez aproximada (15.8.3.3.3): raiz da quadrática "
               "5h·M² + (h²Nd − Nd le²/320 − 5h α_b M1d,A)·M − "
               "Nd h² α_b M1d,A = 0. Dividida por 5hNd² e escrita em "
               "excentricidades, ela vira e² + (h/5 − le²/1600h − e₁)e − "
               "h e₁/5 = 0, forma em que a normal sai da conta.",
               italico=True)
    cfg = res.pilar.config
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
    _figura(doc, graficos.figura_esforcos(res), 16.0)


def _situacoes(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Situações de cálculo")
    _paragrafo(doc,
               "O item 11.3.3.4.3 admite que, em flexão composta oblíqua, o "
               "momento mínimo seja respeitado separadamente em cada "
               "direção. Daí saem as situações de extremidade. Na seção "
               "intermediária entram o α_b e a segunda ordem.")
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
    _tabela(doc, ["Situação", "Descrição", "ex (cm)", "ey (cm)", "|e| (cm)",
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
    _figura(doc, graficos.figura_excentricidades(res), 12.0)


def _dimensionamento(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Dimensionamento da seção")
    if res.dim_fechado:
        _titulo(doc, f"{n}.1 Roteiro dos casos fechados", 2)
        for d in ("x", "y"):
            dim = res.dim_fechado.get(d)
            if dim is None:
                continue
            cl = dim.classificacao
            _paragrafo(doc, f"Direção {d} — flexão segundo h = "
                            f"{_n(p.secao.altura(d))} cm")
            _tabela(doc, ["Grandeza", "Valor", "Significado"], [
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

    _titulo(doc, f"{n}.2 Armadura mínima e adotada", 2)
    from ..core.materiais import rho_minimo
    rmin = rho_minimo(res.nu, p.concreto, p.aco)
    linhas = [
        ["ν = Nd/(Ac fcd)", _n(res.nu, 4), "17.3.5.3.1"],
        ["ρ,mín = 0,15 ν fcd/fyd ≥ 0,4 %", f"{_n(rmin * 100, 3)} %",
         "17.3.5.3.1"],
        ["As,mín", f"{_n(res.As_minima)} cm²", "17.3.5.3.1"],
        ["As necessária (casos fechados)", f"{_n(res.As_necessaria)} cm²",
         "17.2.2"],
    ]
    if res.arranjo is not None:
        linhas += [
            ["Arranjo adotado", res.arranjo.descricao(), "18.4.2.2"],
            ["As efetiva", f"{_n(res.arranjo.As)} cm²", "—"],
            ["ρ efetiva", f"{_n(res.taxa * 100, 3)} %", "17.3.5.3"],
            ["d′ (face ao eixo da barra)",
             f"{_n(res.arranjo.d_linha_x)} cm", "—"],
        ]
    _tabela(doc, ["Grandeza", "Valor", "Item"], linhas, [7.0, 5.0, 3.0])


def _verificacao(doc: Document, res: ResultadoPilar, n: int) -> None:
    p = res.pilar
    _titulo(doc, f"{n}. Verificação à flexão composta oblíqua")
    _paragrafo(doc,
               f"Expressão de interação do item 17.2.5, com α = "
               f"{_n(p.alfa_interacao)}. MRd,xx e MRd,yy são os "
               f"momentos resistentes em flexão composta normal, com a mesma "
               f"força normal e o arranjo de barras adotado.")
    linhas = []
    for v in res.verificacoes:
        linhas.append([
            v.situacao.nome, _n(v.situacao.Mx / 100, 1), _n(v.MRd_xx / 100, 1),
            _n(v.situacao.My / 100, 1), _n(v.MRd_yy / 100, 1),
            _pct(v.interacao),
            "OK" if v.ok_interacao else "NÃO ATENDE"])
    _tabela(doc, ["Situação", "MSd,x (kN·m)", "MRd,xx (kN·m)",
                  "MSd,y (kN·m)", "MRd,yy (kN·m)", "Interação (%)", "Veredito"],
            linhas, [2.4, 2.3, 2.4, 2.3, 2.4, 1.8, 2.2])

    _titulo(doc, f"{n}.1 Envoltória de momentos resistentes", 2)
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
        _tabela(doc, ["Situação", "MSd (kN·m)", "MRd na direção (kN·m)",
                      "MSd/MRd (%)", "F.S.", "Domínio", "Veredito"], linhas,
                [2.3, 2.3, 3.2, 1.9, 1.6, 1.8, 2.2])
    _figura(doc, graficos.figura_envoltoria(res), 12.0)
    _figura(doc, graficos.figura_interacao(res), 16.0)

    _titulo(doc, f"{n}.2 Fator de segurança por cota do lance", 2)
    _paragrafo(doc,
               "F.S. = MRd/MSd na direção do momento solicitante, lido em "
               "três cotas físicas do lance: topo e base com o momento "
               "real de cada ponta -- e não o M1d,A, o maior módulo entre "
               "os dois, que decide o α_b --, e o meio com a pior das "
               "situações intermediárias já verificadas acima.")
    linhas = []
    for nome_z, v in res.verificacoes_z.items():
        linhas.append([
            nome_z, _n(v.MSd / 100, 1), _n(v.MRd_envoltoria / 100, 1),
            "—" if math.isinf(v.fs) else _n(v.fs, 2), v.dominio,
            "OK" if v.ok else "NÃO ATENDE"])
    _tabela(doc, ["Cota", "MSd (kN·m)", "MRd envoltória (kN·m)", "F.S.",
                  "Domínio", "Veredito"], linhas,
            [2.0, 2.6, 3.4, 1.8, 2.0, 2.4])

    mm = res.momento_minimo
    if mm is not None:
        _titulo(doc, f"{n}.3 Momento mínimo — envoltória isolada "
                     f"(item 11.3.3.4.3)", 2)
        _paragrafo(doc,
                   "O item 3.1 da apostila de referência verifica o momento "
                   "mínimo à parte, e não como piso do momento real: duas "
                   "análises isoladas à flexão composta normal, uma por "
                   "direção, com Md,tot,mín = M1d,mín amplificado pela 2ª "
                   "ordem onde a esbeltez a exige (com α_b = 1), confrontado "
                   "com o momento resistente naquela direção apenas.")
        _tabela(doc, ["Direção", "Md,tot,mín (kN·m)",
                      "MRd na direção (kN·m)", "F.S.", "Veredito"],
                [["x", _n(mm.Msd_x / 100, 1), _n(mm.MRd_x / 100, 1),
                  "∞" if math.isinf(mm.fs_x) else _n(mm.fs_x, 2),
                  "OK" if mm.ok_x else "NÃO ATENDE"],
                 ["y", _n(mm.Msd_y / 100, 1), _n(mm.MRd_y / 100, 1),
                  "∞" if math.isinf(mm.fs_y) else _n(mm.fs_y, 2),
                  "OK" if mm.ok_y else "NÃO ATENDE"]],
                [2.0, 3.0, 3.4, 1.8, 2.4])

    if res.conferencias:
        _titulo(doc, f"{n}.4 Conferência entre os dois motores", 2)
        _tabela(doc, ["Grandeza", "Casos fechados", "Motor seccional",
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
    _tabela(doc, ["Grandeza", "Valor", "Limite", "Item"], [
        ["Bitola", f"ø{_n(a.phi, 1)} mm",
         f"10 a {_n(arr_mod.bitola_maxima(p.secao), 1)} mm", "18.4.2.1"],
        ["Número de barras", str(a.n_barras), "—", "18.4.2.2"],
        ["Barras por face em x", str(a.nx), "—", "—"],
        ["Barras por face em y", str(a.ny), "—", "—"],
        ["As efetiva", f"{_n(a.As)} cm²",
         f"≥ {_n(res.As_necessaria)} cm²", "17.2.2"],
        ["Espaçamento livre", f"{_n(a.espacamento_livre)} cm",
         f"≥ {_n(s_min)} cm", "18.4.2.2"],
        ["Espaçamento entre eixos", f"{_n(a.espacamento_eixos)} cm",
         f"≤ {_n(arr_mod.espacamento_eixos_maximo(p.secao))} cm", "18.4.2.2"],
    ], [4.2, 3.4, 4.4, 2.0])

    e = res.estribos
    if e is not None:
        _titulo(doc, f"{n}.2 Armadura transversal", 2)
        from ..core import estribos as est_mod
        _tabela(doc, ["Grandeza", "Valor", "Limite", "Item"], [
            ["Bitola do estribo", f"ø{_n(e.phi, 1)} mm",
             f"≥ {_n(est_mod.bitola_minima(a.phi))} mm", "18.4.3"],
            ["Espaçamento", f"{_n(e.s)} cm",
             f"≤ {_n(e.s_maximo)} cm ({e.motivo_s})", "18.4.3"],
            ["Estribos no lance", str(e.niveis), "—", "18.4.3"],
            ["Comprimento do estribo", f"{_n(e.comprimento)} cm", "—", "—"],
            ["Alcance da proteção 20 ø_t", f"{_n(e.alcance)} cm", "—",
             "18.2.4"],
            ["Grampos suplementares por nível", str(e.n_suplementares),
             "—", "18.2.4"],
        ], [4.6, 3.2, 4.4, 1.8])

    cis = [c for c in (res.cisalhamento or {}).values() if c.Vd > 0.0]
    if cis:
        _titulo(doc, f"{n}.2.1 Força cortante — item 17.4, modelo I", 3)
        _paragrafo(doc,
                   "Bielas a 45°, com a parcela complementar Vc constante "
                   "(item 17.4.2.2). O item 17.4.1.1.2-c) dispensa a "
                   "armadura transversal **de cisalhamento** no pilar "
                   "predominantemente comprimido enquanto VSd ≤ Vc e a seção "
                   "não fissura em estádio I; quando essa dispensa vale, o "
                   "estribo continua sendo o do item 18.4.3, e é isso que a "
                   "última linha de cada direção declara.")
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
        _tabela(doc, ["Grandeza", "Valor", "Limite ou origem", "Item"],
                linhas, [5.0, 3.2, 5.0, 1.8])

    anc = res.ancoragem
    if anc is not None:
        _titulo(doc, f"{n}.3 Ancoragem e comprimento de espera", 2)
        _tabela(doc, ["Grandeza", "Valor", "Item"], [
            ["fbd", f"{_n(anc.fbd, 4)} kN/cm²", "9.3.2.1"],
            ["lb básico", f"{_n(anc.lb, 1)} cm", "9.4.2.4"],
            ["lb necessário", f"{_n(anc.lb_nec, 1)} cm", "9.4.2.5"],
            ["l0c (espera)", f"{_n(anc.l0c, 1)} cm", "9.5.2.3"],
            ["l0c mínimo", f"{_n(anc.l0c_min, 1)} cm", "9.5.2.3"],
        ], [5.0, 5.0, 5.0])
        _paragrafo(doc,
                   "l0c = lb · As,calc/As,ef, com piso no maior entre "
                   "0,6 lb, 15 ø e 20 cm. É medido a partir da face superior "
                   "do lance, e a emenda dobra a taxa de armadura naquele "
                   "trecho — o que o item 17.3.5.3.2 conta dentro dos 8 %.",
                   italico=True)

    _titulo(doc, f"{n}.4 Quantitativo do lance", 2)
    massa_long = a.massa(p.lance.altura + (anc.l0c if anc else 0.0))
    _tabela(doc, ["Peça", "Descrição", "Comprimento unitário",
                  "Quantidade", "Massa (kg)"], [
        ["Longitudinal", f"{a.n_barras} ø{_n(a.phi, 1)} mm",
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
    _tabela(doc, ["Insumo", "Quantidade", "Unidade", "Como sai"], [
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
    _figura(doc, graficos.figura_elevacao(res), 9.0)


def _roteiro(doc: Document, res: ResultadoPilar, n: int) -> None:
    _titulo(doc, f"{n}. Roteiro de verificações")
    verificacoes = auditoria.roteiro(res)
    resumo = auditoria.resumo(verificacoes)
    _paragrafo(doc, "  ".join(f"{k}: {v}" for k, v in resumo.items()),
               italico=True)
    _tabela(doc, ["Item", "Verificação", "Critério", "Resultado",
                  "Situação"],
            [[v.item, v.descricao, v.criterio, v.resultado, v.situacao]
             for v in verificacoes],
            [1.8, 3.4, 4.2, 4.2, 2.4])


def _pendencias(doc: Document, res: ResultadoPilar, n: int) -> None:
    erros, construtivos = avisos_mod.separar(res.avisos)
    _titulo(doc, f"{n}. Observações e pendências")
    if erros:
        _titulo(doc, f"{n}.1 Verificações não atendidas", 2)
        for a in erros:
            _paragrafo(doc, f"• {a}", cor=VERMELHO)
    else:
        _paragrafo(doc, "Nenhuma verificação foi reprovada.")
    if construtivos:
        _titulo(doc, f"{n}.2 Decisões de detalhamento e ressalvas", 2)
        for a in construtivos:
            _paragrafo(doc, f"• {a}")


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------

def gerar(res: ResultadoPilar, caminho: str) -> str:
    """Gera a memória de cálculo em .docx e devolve o caminho do arquivo."""
    doc = Document()
    _configurar(doc)
    _capa(doc, res)
    doc.add_page_break()
    n = 1
    _metodologia(doc, res, n); n += 1
    _dados(doc, res, n); n += 1
    _esbeltez(doc, res, n); n += 1
    _segunda_ordem(doc, res, n); n += 1
    _situacoes(doc, res, n); n += 1
    _dimensionamento(doc, res, n); n += 1
    _verificacao(doc, res, n); n += 1
    _detalhamento(doc, res, n); n += 1
    _roteiro(doc, res, n); n += 1
    _pendencias(doc, res, n)
    doc.save(caminho)
    return caminho


def exportar_pdf(caminho_docx: str, caminho_pdf: str | None = None) -> str:
    """Converte o .docx em PDF pelo Word (COM). Requer Word instalado."""
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
        doc = word.Documents.Open(caminho_docx, ReadOnly=True)
        doc.SaveAs(caminho_pdf, FileFormat=17)     # wdFormatPDF
        doc.Close(False)
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()
    return caminho_pdf
