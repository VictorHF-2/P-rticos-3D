# -*- coding: utf-8 -*-
"""
relatorio.py
Memória de cálculo em Word (.docx), com os dados de entrada, a análise, o
dimensionamento passo a passo, as verificações de serviço e o detalhamento.
Cada resultado traz o item da NBR 6118 que o justifica.

A conversão para PDF é feita pelo próprio Word, via COM, quando disponível.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .. import __norma__, __version__
from . import auditoria
from ..core import alinhamento as al
from ..core.dimensionar import ResultadoViga
from ..core import avisos as avisos_mod
from . import desenho, graficos

AZUL = RGBColor(0x1F, 0x4E, 0x79)
CINZA = RGBColor(0x59, 0x59, 0x59)
VERMELHO = RGBColor(0xA5, 0x23, 0x2F)
VERDE = RGBColor(0x2E, 0x7D, 0x4F)


# ---------------------------------------------------------------------------
# Utilidades de formatação
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
    # a memória de várias vigas põe cada viga sob um título de nível 1, e os
    # capítulos dela descem um degrau: o nível 4 só existe aí
    h4 = doc.styles["Heading 4"]
    h4.font.name = "Aptos"
    h4.font.size = Pt(10.5)
    h4.font.color.rgb = AZUL


def _titulo(doc: Document, texto: str, nivel: int = 1) -> None:
    """Título; ``doc._nivel_extra`` desce o nível quando há uma viga por cima."""
    extra = getattr(doc, "_nivel_extra", 0)
    if extra:
        # sob uma viga a numeração é "2.1", "2.8.1": sem o ponto final que os
        # capítulos de uma viga só levam ("8.", "8.1.")
        texto = re.sub(r"^(\d+(?:\.\d+)+)\. ", r"\1 ", texto)
    doc.add_heading(texto, level=nivel + extra)


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


def _figura(doc: Document, fig, largura_cm: float = 16.0) -> None:
    caminho = os.path.join(tempfile.gettempdir(),
                           f"viga_fig_{id(fig)}.png")
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
    if isinstance(valor, (int,)) and not isinstance(valor, bool):
        return str(valor)
    try:
        return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",") \
            .replace("@", ".")
    except (TypeError, ValueError):
        return str(valor)


# ---------------------------------------------------------------------------
# Seções do relatório
# ---------------------------------------------------------------------------

def _capa(doc: Document, res: ResultadoViga) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("MEMÓRIA DE CÁLCULO\nDIMENSIONAMENTO DE VIGA DE CONCRETO "
                  "ARMADO")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = AZUL
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("ABNT NBR 6118 — Projeto de estruturas de concreto")
    r.italic = True
    r.font.color.rgb = CINZA
    doc.add_paragraph()
    _tabela(doc, ["Emissão", "Descrição"], _identificacao_da_emissao(doc),
            [5.0, 11.0])
    _ficha(doc, res)


def _ficha(doc: Document, res: ResultadoViga) -> None:
    """A tabela de identificação de uma viga (capa, ou abertura da viga)."""
    viga = res.viga
    _tabela(doc, ["Item", "Descrição"], [
        ["Viga", viga.nome],
        ["Projeto", viga.projeto or "-"],
        ["Nº de tramos", len(viga.tramos)],
        ["Comprimento total", f"{_n(viga.comprimento)} m"],
        ["Concreto", f"{viga.concreto.classe} "
                     f"(fck = {_n(viga.concreto.fck, 0)} MPa)"],
        ["Aço", viga.aco.categoria],
        ["Agressividade ambiental", f"CAA {viga.ambiente.caa} — "
                                    f"{viga.ambiente.descricao}"],
        ["Cobrimento nominal", f"{_n(viga.ambiente.cobrimento_nominal)} cm"],
        ["Situação geral", "TODAS AS VERIFICAÇÕES ATENDIDAS" if res.ok
         else "HÁ VERIFICAÇÕES NÃO ATENDIDAS — VER O ROTEIRO DE "
              "VERIFICAÇÕES E AS OBSERVAÇÕES"],
    ] + ([["Observações", viga.observacoes]] if viga.observacoes else [])
      + [["Dados de entrada (identificação)", viga.impressao_digital()]],
        [5.0, 11.0])


def _carimbo(emitido_em: datetime) -> str:
    return emitido_em.strftime("%d/%m/%Y %H:%M")


def _identificacao_da_emissao(doc: Document) -> list[list]:
    """Linhas de identificação da emissão: quando, por qual programa, de quê."""
    ident = getattr(doc, "_identificacao", None) or {}
    emitido = ident.get("emitido_em")
    return ([["Emitida em", _carimbo(emitido)]] if emitido else []) + [
        ["Programa", f"Vigas {__version__} — {__norma__}"],
        ["Arquivo de entrada", ident.get("arquivo") or
         "projeto ainda não salvo em arquivo"]]


def _rodape(doc: Document, emitido_em: datetime) -> None:
    """Rodapé de todas as páginas: programa, norma, data e número da página."""
    par = doc.sections[0].footer.paragraphs[0]
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run(f"Vigas {__version__} — {__norma__} — emitida em "
                    f"{_carimbo(emitido_em)} — página ")
    r.font.size = Pt(8)
    r.font.color.rgb = CINZA
    campo = OxmlElement("w:fldSimple")
    campo.set(qn("w:instr"), "PAGE")
    r_campo = OxmlElement("w:r")
    texto = OxmlElement("w:t")
    texto.text = "1"
    r_campo.append(texto)
    campo.append(r_campo)
    par._p.append(campo)


def _bloco_de_conferencia(doc: Document) -> None:
    """Última página: quem elaborou, quem conferiu e o responsável técnico.

    O programa é ferramenta de cálculo, e a responsabilidade pelo projeto é de
    quem assina. O bloco fica em branco para ser preenchido e assinado; o texto
    acima dele diz o que a assinatura cobre.
    """
    doc.add_page_break()
    _titulo(doc, "Conferência e responsabilidade técnica", 1)
    _paragrafo(doc,
               "Esta memória foi gerada por programa de cálculo a partir dos "
               "dados de entrada identificados na capa. Os resultados devem "
               "ser conferidos por engenheiro habilitado, responsável técnico "
               "pelo projeto, que responde pela adoção dos dados, pelos "
               "critérios de projeto e pelos itens que o roteiro de "
               "verificações marca como “Não verificado”, os quais o programa "
               "não cobre.")
    doc.add_paragraph()
    _tabela(doc, ["Papel", "Nome", "Data", "Assinatura"], [
        ["Elaborado por", "", "", ""],
        ["Conferido por", "", "", ""],
        ["Responsável técnico", "", "", ""],
    ], [4.0, 6.0, 2.6, 3.4])
    _tabela(doc, ["Registro profissional", "Número"], [
        ["CREA / CAU", ""],
        ["ART / RRT", ""],
    ], [6.0, 10.0])
    _paragrafo(doc, "Itens conferidos fora do programa e observações da "
                    "conferência:", cor=CINZA)
    for _ in range(4):
        doc.add_paragraph("_" * 86)


#: critérios de cálculo que a metodologia cita com número, e que podem diferir
#: de uma viga para outra: (rótulo da tabela, atributo de ``Config``)
_CRITERIOS_CITADOS = (("γg", "gamma_g"), ("γq", "gamma_q"), ("ψ1", "psi1"),
                      ("ψ2", "psi2"), ("Alternância", "alternancia"),
                      ("Modelo de cisalhamento", "modelo_cisalhamento"))


def _metodologia(doc: Document, resultados, n: int) -> None:
    """Como o cálculo foi feito, e o que ficou fora dele.

    Este capítulo existe para a memória se sustentar sozinha: quem a lê depois
    tem de saber com que modelo, com que combinações e com que simplificações
    os números foram obtidos -- e, sobretudo, o que **não** foi verificado.

    ``resultados`` é a lista das vigas da memória. Num documento de várias
    vigas a metodologia sai **uma vez só**: os critérios que as vigas
    compartilham vão no texto; os que variam de uma para outra são remetidos a
    uma tabela no fim do capítulo, e nunca se escolhe o de uma delas em
    silêncio.
    """
    if isinstance(resultados, ResultadoViga):
        resultados = [resultados]
    varias = len(resultados) > 1
    res = resultados[0]
    viga = res.viga
    tabela_ref = f"na tabela {n}.5"

    def valor(atributo: str, formato=lambda v: v) -> str:
        """O valor do critério, ou a remissão à tabela se as vigas divergem."""
        valores = {getattr(r.viga.config, atributo) for r in resultados}
        if len(valores) == 1:
            return str(formato(next(iter(valores))))
        return f"o de cada viga ({tabela_ref})"

    alternancias = {r.viga.config.alternancia for r in resultados}
    if alternancias == {True}:
        texto_alternancia = (
            ", varrida de forma exaustiva em todos os tramos de cada viga."
            if varias else
            f", varrida de forma exaustiva nos {len(viga.tramos)} tramos.")
    elif alternancias == {False}:
        texto_alternancia = (", que está desligada nos critérios — todos os "
                             "tramos são carregados simultaneamente.")
    else:
        texto_alternancia = (", ligada ou desligada nos critérios de cada "
                             f"viga ({tabela_ref}).")

    _titulo(doc, f"{n}. Metodologia", 1)
    _paragrafo(doc, "O dimensionamento segue a ABNT NBR 6118 — Projeto de "
                    "estruturas de concreto. Cada resultado deste documento "
                    "cita o item da norma que o gerou, e "
                    + ("o roteiro de verificações de cada viga traz as "
                       "verificações completas, com a situação de cada uma."
                       if varias else
                       "o capítulo final traz o roteiro completo das "
                       "verificações, com a situação de cada uma.")
               + (f" Esta metodologia vale para as {len(resultados)} vigas "
                  f"e não se repete: a partir do capítulo seguinte, os "
                  f"resultados, os gráficos e o detalhamento vêm agrupados "
                  f"viga a viga." if varias else ""))

    _titulo(doc, f"{n}.1 Modelo de análise", 2)
    _paragrafo(doc,
               "A viga é resolvida como barra contínua pelo método da rigidez "
               "direta, com elementos de Euler-Bernoulli e malha de 2,5 cm. Os "
               "apoios são vínculos pontuais no eixo do pilar: o deslocamento "
               "vertical é impedido em todos, e a rotação também nos "
               "engastes. O vão de cálculo é a distância entre eixos de apoio, "
               "que é maior ou igual ao vão efetivo do item 14.6.2.4 — "
               "calcular entre eixos é, portanto, a favor da segurança.")
    _paragrafo(doc,
               "No estado-limite último a rigidez é a da seção bruta de "
               "concreto. No estado-limite de serviço a viga é reanalisada com "
               "a rigidez equivalente de Branson de cada tramo (17.3.2.1.1), "
               "calculada com a armadura efetivamente adotada. A torção, "
               "quando existe, é distribuída pela rigidez elástica à torção "
               "dos tramos, com os apoios impedidos de girar em torno do eixo.")

    _titulo(doc, f"{n}.2 Ações e combinações", 2)
    _paragrafo(doc,
               f"As ações permanentes recebem o mesmo coeficiente em toda a "
               f"viga (γg = {valor('gamma_g', lambda v: _n(v, 1))}), como "
               f"exige o item 11.7.1 — "
               f"ações de mesma origem não se fracionam. O que varia de tramo "
               f"para tramo é apenas a ação variável "
               f"(γq = {valor('gamma_q', lambda v: _n(v, 1))}), pela "
               f"alternância de carregamento do item 14.6.7"
               + texto_alternancia)
    _paragrafo(doc,
               f"As envoltórias de esforços vêm de todas as combinações "
               f"últimas normais da Tabela 11.3. As verificações de serviço "
               f"usam a combinação quase permanente (ψ2 = "
               f"{valor('psi2', lambda v: _n(v, 1))}) para a flecha e a "
               f"frequente (ψ1 = {valor('psi1', lambda v: _n(v, 1))}) para a "
               f"abertura de fissuras, conforme "
               f"11.8.3. "
               + ("A lista de todas as combinações consideradas fecha o "
                  "capítulo de cada viga." if varias else
                  "O anexo final lista todas as combinações consideradas."))

    _titulo(doc, f"{n}.3 Sequência do dimensionamento", 2)
    _paragrafo(doc,
               "1) Flexão no ELU pelo diagrama retangular equivalente "
               "(17.2.2), com a altura útil iterada até fechar com o "
               "centróide das barras adotadas — trocar a bitola muda o "
               "centróide, que muda a armadura necessária. 2) Cortante pelo "
               f"Modelo de Cálculo {valor('modelo_cisalhamento')} (17.4.2), com a "
               "redução junto ao apoio do item 17.4.1.2.1. 3) Torção, quando "
               "há torçor, pela treliça espacial generalizada (17.5), somada "
               "à armadura de flexão e à transversal. 4) Serviço: flecha por "
               "Branson com o coeficiente αf do 17.3.2.1.2 e abertura de "
               "fissuras pelas duas expressões do 17.3.3.2. 5) Detalhamento: "
               "escalonamento com o diagrama decalado de aℓ, ancoragem, "
               "ganchos, emendas por traspasse e estribos.")
    _paragrafo(doc,
               "As barras são interrompidas aos pares, uma de cada lado do "
               "eixo, porque a armadura de uma face é simétrica; cada par "
               "recebe o comprimento da sua barra mais interna. As camadas "
               "seguem o item 18.3.2.2: a primeira leva o que couber na "
               "largura e as de dentro, no máximo o número de ramos do "
               "estribo, para que cada barra fique amarrada.")

    _titulo(doc, f"{n}.4 Simplificações e limites do modelo", 2)
    _paragrafo(doc, "Declaradas para que a auditoria saiba onde o modelo "
                    "termina:", cor=CINZA)
    _tabela(doc, ["Tema", "O que o cálculo faz"], [
        ["Apoios extremos",
         "modelados como rótulas. Os momentos mínimos de solidariedade "
         "viga–pilar (14.6.6.1) não são calculados"],
        ["Estabilidade lateral",
         "não verificada (15.10); conferir à parte em viga alta e estreita"],
        ["Cortante junto ao apoio",
         "reduzido só para carga distribuída, alínea (a) do 17.4.1.2.1. Carga "
         "concentrada a menos de 2d não é reduzida — a favor da segurança"],
        ["Seção do tramo", "constante em cada tramo"],
        ["Mudança de seção",
         "o alinhamento declarado decide que face atravessa o apoio e que "
         "face é ancorada com gancho. Pela largura, todas as barras do tramo "
         "mais largo são ancoradas — o modelo não distingue a barra do canto "
         "alinhado da do canto que recua"],
        ["Torção", "sem alternância: γg e γq com todos os tramos carregados"],
        ["Aberturas e furos", "não modelados (13.2.5 e 21.3)"],
        ["Pilares", "não dimensionados; entram como largura de apoio"],
    ], [4.5, 11.5])
    _paragrafo(doc, ("O roteiro de verificações de cada viga marca cada um "
                     "destes pontos como “Não verificado”, para que nenhuma "
                     "omissão fique implícita." if varias else
                     "O capítulo seguinte de roteiro marca cada um destes "
                     "pontos como “Não verificado”, para que nenhuma omissão "
                     "fique implícita."), cor=CINZA)

    if varias:
        _titulo(doc, f"{n}.5 Critérios adotados em cada viga", 2)
        _paragrafo(doc, "Os critérios de cálculo que o texto acima cita com "
                        "número, viga a viga:", cor=CINZA)
        _tabela(doc, ["Viga"] + [rotulo for rotulo, _ in _CRITERIOS_CITADOS],
                [[r.viga.nome] + [
                    _n(getattr(r.viga.config, a), 1)
                    if isinstance(getattr(r.viga.config, a), float)
                    else _n(getattr(r.viga.config, a))
                    for _, a in _CRITERIOS_CITADOS] for r in resultados])


def _dados(doc: Document, res: ResultadoViga, n: int) -> None:
    viga = res.viga
    cfg = viga.config
    _titulo(doc, f"{n}. Dados de entrada", 1)

    _titulo(doc, f"{n}.1 Geometria", 2)
    linhas = []
    for i, t in enumerate(viga.tramos):
        linhas.append([f"Tramo {i + 1}", f"{_n(t.L)} m", t.secao.descricao(),
                       f"{_n(viga.vao_livre(i))} m",
                       f"{_n(viga.vao_efetivo(i))} m"])
    _tabela(doc, ["Tramo", "Vão de cálculo", "Seção", "Vão livre",
                  "Vão efetivo (14.6.2.4)"], linhas)

    # a largura colaborante é dado do projetista, mas o teto que sai dos
    # vínculos é conta do programa, e só aparecia quando estourava: a memória
    # não mostrava por que bf = 100 cm tinha sido aceita
    mesas = [(i, t) for i, t in enumerate(viga.tramos)
             if t.secao.tipo != "retangular" and t.secao.bf > t.secao.bw + 1e-9]
    if mesas:
        _paragrafo(doc, "Largura colaborante da mesa (14.6.2.2): bf = bw + b1 + "
                        "b3, com b1 ≤ 0,1·a e b3 ≤ 0,1·a, sendo a a distância "
                        "entre pontos de momento nulo, tomada pelos vínculos "
                        "de cada tramo. Os limites b1 ≤ 0,5·b2 e b3 ≤ b4 "
                        "dependem do espaçamento entre as vigas e da laje em "
                        "balanço, que o programa não conhece, e ficam com o "
                        "projetista.")
        linhas = []
        for i, t in mesas:
            fator, caso, a_cm, teto = viga.teto_da_mesa(i)
            linhas.append([f"Tramo {i + 1}", caso,
                           f"{_n(fator, 2)}·l = {_n(a_cm, 0)} cm",
                           f"{_n(teto, 0)} cm", f"{_n(t.secao.bf, 0)} cm",
                           "OK" if t.secao.bf <= teto + 1e-6 else "NÃO OK"])
        _tabela(doc, ["Tramo", "Vínculos", "a", "bw + 2·0,1·a",
                      "bf adotada", "Situação"], linhas)

    linhas = [[f"Apoio {i + 1}", a.tipo, f"{_n(a.largura, 0)} cm",
               f"{_n(viga.x_apoios[i])} m"]
              for i, a in enumerate(viga.apoios)]
    _tabela(doc, ["Apoio", "Tipo", "Largura", "Posição"], linhas)

    _titulo(doc, f"{n}.2 Materiais", 2)
    c, a = viga.concreto, viga.aco
    _tabela(doc, ["Propriedade", "Valor", "Item da norma"], [
        ["fck", f"{_n(c.fck, 0)} MPa", "8.2.4"],
        ["fcd = fck/γc", f"{_n(c.fcd)} MPa", "12.3.3"],
        ["fctm", f"{_n(c.fctm)} MPa", "8.2.5"],
        ["fctk,inf", f"{_n(c.fctk_inf)} MPa", "8.2.5"],
        ["Eci", f"{_n(c.Eci, 0)} MPa", "8.2.8"],
        ["Ecs", f"{_n(c.Ecs, 0)} MPa", "8.2.8"],
        ["λ (bloco retangular)", _n(c.lambda_, 3), "17.2.2"],
        ["αc", _n(c.alfa_c, 3), "17.2.2"],
        ["ηc", _n(c.eta_c, 3), "17.2.2"],
        ["αc·ηc·fcd", f"{_n(c.sigma_cd, 4)} kN/cm²", "17.2.2"],
        ["εcu", _n(c.eps_cu * 1000, 3) + " ‰", "8.2.10.1"],
        ["αv2 = 1 − fck/250", _n(c.alfa_v2, 3), "17.4.2.2"],
        [f"fyk ({a.categoria})", f"{_n(a.fyk, 0)} MPa", "8.3.6"],
        ["fyd = fyk/γs", f"{_n(a.fyd)} MPa", "8.3.6"],
        ["Es", f"{_n(a.Es, 0)} MPa", "8.3.5"],
        ["εyd", _n(a.eps_yd * 1000, 3) + " ‰", "8.3.6"],
        ["η1 (conformação superficial)", _n(a.eta_1, 2), "9.3.2.1"],
    ], [6.0, 5.0, 5.0])

    _titulo(doc, f"{n}.3 Carregamentos", 2)
    linhas = []
    for cd in viga.todas_distribuidas():
        tipo = "permanente" if cd.acao == "g" else "variável"
        valor = (f"{_n(cd.q1)} kN/m" if cd.q1 == cd.q2
                 else f"{_n(cd.q1)} a {_n(cd.q2)} kN/m")
        linhas.append([cd.descricao or "distribuída", tipo, valor,
                       f"{_n(cd.x_ini)} a {_n(cd.x_fim)} m"])
    for p in viga.concentradas:
        linhas.append([p.descricao or "concentrada",
                       "permanente" if p.acao == "g" else "variável",
                       f"{_n(p.P)} kN", f"x = {_n(p.x)} m"])
    for mo in viga.momentos:
        linhas.append([mo.descricao or "momento",
                       "permanente" if mo.acao == "g" else "variável",
                       f"{_n(mo.M)} kN·m", f"x = {_n(mo.x)} m"])
    for tq in viga.torcores:
        # distribuído é kN·m/m num trecho; concentrado é kN·m num ponto. A
        # tabela imprimia os dois como concentrados em x, e um torçor de
        # 6 kN·m/m ao longo de 4,5 m lia-se como 6 kN·m na ponta da viga
        distribuido = tq.x_fim is not None
        linhas.append([tq.descricao or "torçor",
                       "permanente" if tq.acao == "g" else "variável",
                       f"{_n(tq.T)} kN·m/m" if distribuido
                       else f"{_n(tq.T)} kN·m",
                       f"{_n(tq.x)} a {_n(tq.x_fim)} m (distribuído)"
                       if distribuido else f"x = {_n(tq.x)} m"])
    _tabela(doc, ["Carga", "Ação", "Valor", "Trecho"], linhas)

    _titulo(doc, f"{n}.4 Critérios adotados", 2)
    _tabela(doc, ["Critério", "Valor", "Observação"], [
        ["γg / γq", f"{_n(cfg.gamma_g, 1)} / {_n(cfg.gamma_q, 1)}",
         "Tabela 11.1"],
        ["ψ0 / ψ1 / ψ2", f"{_n(cfg.psi0, 1)} / {_n(cfg.psi1, 1)} / "
                         f"{_n(cfg.psi2, 1)}", "Tabela 11.2"],
        ["Alternância de carga acidental", cfg.alternancia, "14.6.7.2"],
        ["Modelo de cisalhamento",
         f"Modelo {cfg.modelo_cisalhamento}" +
         (f" (θ = {_n(cfg.theta, 0)}°)" if cfg.modelo_cisalhamento == 2 else ""),
         "17.4.2"],
        ["Inclinação dos estribos", f"{_n(cfg.alpha_estribo, 0)}°", "17.4.1.1"],
        ["Redistribuição δ", _n(cfg.redistribuicao, 2), "14.6.4.3"],
        ["Diagrama arredondado sobre o apoio (ΔM = R·t/8)",
         cfg.arredondar_momento_apoio, "14.6.3"],
        ["Redução do cortante junto ao apoio", cfg.reducao_apoio,
         "17.4.1.2.1"],
        ["Peso próprio considerado", cfg.peso_proprio,
         f"γconc = {_n(viga.concreto.peso_especifico, 0)} kN/m³"],
    ], [6.5, 4.5, 5.0])


def _analise(doc: Document, res: ResultadoViga, n: int) -> None:
    _titulo(doc, f"{n}. Análise estrutural", 1)
    _paragrafo(doc, "A viga foi resolvida pelo método da rigidez direta, com "
                    "elementos de barra de Euler-Bernoulli e a rigidez da "
                    "seção bruta de concreto (item 14.6.2). As envoltórias "
                    "abaixo reúnem todas as combinações últimas, incluindo os "
                    "padrões alternados de carga acidental.")
    _figura(doc, graficos.figura_esquema(res))
    _figura(doc, graficos.figura_esforcos(res))

    _titulo(doc, f"{n}.1 Reações de apoio", 2)
    _tabela(doc, ["Apoio", "x (m)", "R máx (kN)", "R mín (kN)",
                  "M máx (kN·m)", "M mín (kN·m)"],
            [[f"A{r['apoio']}", _n(r["x"]), _n(r["R_max"]), _n(r["R_min"]),
              _n(r["M_max"]), _n(r["M_min"])] for r in res.reacoes])

    _titulo(doc, f"{n}.2 Momentos de dimensionamento", 2)
    linhas = []
    for mp in res.momentos_projeto:
        nome = (f"Vão {mp.indice + 1}" if mp.regiao == "vao"
                else f"Apoio {mp.indice + 1}")
        linhas.append([nome, _n(mp.x), _n(mp.M_bruto), _n(mp.M),
                       mp.observacao or "-"])
    _tabela(doc, ["Região", "x (m)", "M da envoltória", "M de projeto",
                  "Observação"], linhas, [3.0, 2.0, 3.0, 3.0, 5.0])


def _flexao(doc: Document, res: ResultadoViga, n: int) -> None:
    _titulo(doc, f"{n}. Dimensionamento à flexão (ELU)", 1)
    _paragrafo(doc, "Diagrama retangular equivalente do item 17.2.2, com a "
                    "posição da linha neutra limitada pelo item 14.6.4.3. A "
                    "armadura mínima segue a Tabela 17.3 e a máxima, o item "
                    "17.3.5.2.4.")

    com_torcao = any(r.As_torcao > 1e-6 for r in res.regioes)
    linhas = []
    for r in res.regioes:
        f = r.flexao
        if r.construtiva:
            linha = [r.nome, "-", "-", "-", "-", "-", "construtiva"]
            if com_torcao:
                linha.append("-")
            linhas.append(linha + [r.arranjo.descricao,
                                   _n(r.arranjo.As_ef)])
            continue
        linha = [r.nome, _n(r.M), _n(r.d, 1), _n(f.x_d, 3),
                 _n(r.x_d_adotada, 3), f.dominio, _n(max(f.As, f.As_min))]
        if com_torcao:
            linha.append(_n(r.As_torcao))
        linhas.append(linha + [r.arranjo.descricao, _n(r.arranjo.As_ef)])
    cabecalho = ["Região", "Md (kN·m)", "d (cm)", "x/d", "x/d adotada",
                 "Domínio", "As flexão (cm²)"]
    larguras = [2.4, 2.0, 1.5, 1.4, 1.5, 1.5, 1.9]
    if com_torcao:
        cabecalho.append("+ As torção (cm²)")
        larguras.append(1.9)
    cabecalho += ["Adotado", "As,ef (cm²)"]
    larguras += [2.4, 1.8]
    _tabela(doc, cabecalho, linhas, larguras)
    # o limite do 14.6.4.3 vale para a seção que vai na peça: a coluna
    # "x/d" é a do As necessário, a "x/d adotada" a das barras adotadas com a
    # armadura comprimida que atravessa a seção ancorada dos dois lados
    _paragrafo(doc, "x/d é a posição da linha neutra com a armadura "
                    "necessária; x/d adotada, com a armadura adotada e as "
                    "barras da face oposta que atravessam a seção ancoradas "
                    "por lb (9.4.2.5) dos dois lados, trabalhando comprimidas. "
                    "É esta que o limite de ductilidade do item 14.6.4.3 "
                    "verifica.", italico=True)
    if com_torcao:
        _paragrafo(doc, "A coluna de torção é a parcela da armadura "
                        "longitudinal Asl que cabe àquela face na distribuição "
                        "pelo perímetro da seção vazada equivalente "
                        "(17.5.1.6); ela foi somada à armadura de flexão antes "
                        "da escolha das barras. O restante de Asl saiu como "
                        "barras laterais, listadas no detalhamento.",
                   italico=True)

    sub = 0
    for r in res.regioes:
        if r.construtiva:
            continue
        sub += 1
        _titulo(doc, f"{n}.{sub} {r.nome}", 2)
        f = r.flexao
        linhas = [[k, _n(v, 4) if isinstance(v, float) else str(v)]
                  for k, v in f.memoria.items()]
        _tabela(doc, ["Grandeza", "Valor"], linhas, [8.0, 6.0])
        if f.armadura_dupla:
            _paragrafo(doc, "A seção exigiu armadura dupla. A área de "
                            "concreto deslocada pelas barras comprimidas foi "
                            "descontada da tensão da armadura comprimida "
                            "(convenção brasileira).", italico=True)
        arranjo = r.arranjo
        _paragrafo(doc, f"Armadura adotada: {arranjo.descricao} = "
                        f"{_n(arranjo.As_ef)} cm² em "
                        f"{len(arranjo.camadas)} camada(s); d = "
                        f"{_n(arranjo.d, 1)} cm; espaçamento livre horizontal "
                        f"mínimo de {_n(arranjo.ah)} cm (18.3.2.2).")
        if r.ancoragem:
            a = r.ancoragem
            _paragrafo(doc, f"Ancoragem: fbd = {_n(a.fbd, 4)} kN/cm² "
                            f"({'boa' if a.boa_aderencia else 'má'} aderência, "
                            f"9.3.1); lb = {_n(a.lb, 1)} cm; lb,nec = "
                            f"{_n(a.lb_nec, 1)} cm (9.4.2.4).")


def _cisalhamento(doc: Document, res: ResultadoViga, n: int) -> None:
    _titulo(doc, f"{n}. Dimensionamento ao cisalhamento (ELU)", 1)
    cfg = res.viga.config
    _paragrafo(doc, f"Modelo de cálculo {cfg.modelo_cisalhamento} do item "
                    f"17.4.2. A armadura mínima corresponde a ρsw,min = "
                    f"0,2·fctm/fywk (17.4.1.1.1) e o espaçamento máximo segue "
                    f"o item 18.3.3.2.")

    linhas = []
    for i in range(len(res.viga.tramos)):
        pior = max((c for c in res.cortantes
                    if res.viga.x_apoios[i] <= c.x <= res.viga.x_apoios[i + 1]),
                   key=lambda c: c.Vsd, default=None)
        if pior is None:
            continue
        linhas.append([f"Tramo {i + 1}", _n(pior.Vsd), _n(pior.VRd2),
                       _n(pior.razao_biela, 2), _n(pior.Vc), _n(pior.Vsw),
                       _n(pior.asw), _n(pior.asw_min), pior.veredito])
    _tabela(doc, ["Tramo", "Vsd (kN)", "VRd2 (kN)", "Vsd/VRd2", "Vc (kN)",
                  "Vsw (kN)", "Asw/s (cm²/m)", "mín (cm²/m)", "Biela"], linhas)

    _titulo(doc, f"{n}.1 Distribuição dos estribos", 2)
    linhas = [[f"Tramo {z.tramo + 1}", f"{_n(z.x_ini)} a {_n(z.x_fim)}",
               f"Ø{_n(z.phi, 1)}", f"{_n(z.s, 1)} cm", z.n_ramos,
               _n(z.asw_req), _n(z.asw_ef), z.n_estribos]
              for z in res.zonas_estribo]
    _tabela(doc, ["Tramo", "Trecho (m)", "Bitola", "Espaçamento", "Ramos",
                  "Asw/s nec.", "Asw/s ef.", "Quantidade"], linhas)


def _torcao(doc: Document, res: ResultadoViga, n: int) -> None:
    if not res.torcoes:
        return
    _titulo(doc, f"{n}. Dimensionamento à torção (ELU)", 1)
    pior = max(res.torcoes, key=lambda t: t.interacao)
    g = pior.geometria
    _paragrafo(doc, "Treliça espacial generalizada do item 17.5, com a seção "
                    "vazada equivalente e a verificação conjunta da biela "
                    "(17.7.2.2). O diagrama de torçores está no item da "
                    "análise, junto com os de momento e cortante; a armadura "
                    "transversal de torção já está somada à de cisalhamento "
                    "na distribuição dos estribos.")

    linhas = []
    for i in range(len(res.viga.tramos)):
        a, b = res.viga.x_apoios[i], res.viga.x_apoios[i + 1]
        ts = [t for t in res.torcoes if a <= t.x <= b]
        if not ts:
            continue
        pt = max(ts, key=lambda t: t.interacao)
        linhas.append([f"Tramo {i + 1}", _n(pt.x), _n(pt.Tsd), _n(pt.TRd2),
                       _n(pt.interacao, 3), _n(pt.a90), _n(pt.a_transversal),
                       _n(pt.Asl), pt.veredito])
    _tabela(doc, ["Tramo", "x crítico (m)", "Tsd (kN·m)", "TRd2 (kN·m)",
                  "Tsd/TRd2 + Vsd/VRd2", "A90/s (cm²/m)",
                  "Asw/s total (cm²/m)", "Asl (cm²)", "Biela"], linhas)
    _tabela(doc, ["Grandeza", "Valor", "Item"], [
        ["Seção crítica", f"x = {_n(pior.x)} m", "-"],
        ["Tsd", f"{_n(pior.Tsd)} kN·m", "-"],
        ["he", f"{_n(g.he)} cm", "17.5.1.4.1"],
        ["Ae", f"{_n(g.Ae)} cm²", "17.5.1.4.1"],
        ["ue", f"{_n(g.ue)} cm", "17.5.1.4.1"],
        ["TRd2", f"{_n(pior.TRd2)} kN·m", "17.5.1.5"],
        ["Tsd/TRd2 + Vsd/VRd2", _n(pior.interacao, 3), "17.7.2.2"],
        ["A90/s (um ramo)", f"{_n(pior.a90)} cm²/m", "17.5.1.6"],
        ["Asl (longitudinal)", f"{_n(pior.Asl)} cm²", "17.5.1.6"],
        ["Armadura transversal total", f"{_n(pior.a_transversal)} cm²/m",
         "17.7.2.2"],
        ["Situação da biela", pior.veredito, "17.7.2.2"],
    ], [6.0, 5.0, 4.0])


def _servico(doc: Document, res: ResultadoViga, n: int) -> None:
    _titulo(doc, f"{n}. Verificações de serviço (ELS)", 1)
    if res.flechas:
        _titulo(doc, f"{n}.1 Deformação excessiva", 2)
        _paragrafo(doc, "Rigidez equivalente de Branson (17.3.2.1.1) com o "
                        "momento da combinação quase permanente, e flecha "
                        "diferida pelo coeficiente αf do item 17.3.2.1.2. Os "
                        "limites são os da Tabela 13.3.")
        linhas = [[f"Tramo {f.tramo + 1}", _n(f.I_eq / f.I_bruta, 3),
                   _n(f.I_II / f.I_bruta, 3), _n(f.Mr), f.origem_inercia,
                   _n(f.alfa_f, 2), _n(f.f_imediata),
                   _n(f.f_diferida), _n(f.f_total), _n(f.limite_visual),
                   _n(f.f_apos_alvenaria), _n(f.limite_alvenaria),
                   f.parede, f.veredito]
                  for f in res.flechas]
        _tabela(doc, ["Tramo", "Ieq/Ic", "III/Ic", "Mr (kN·m)", "Origem da inércia",
                      "αf",
                      "f imediata (cm)", "f diferida (cm)", "f total (cm)",
                      "L/250 (cm)", "f posterior (cm)", "limite (cm)",
                      "Apoiado", "Situação"], linhas)
        vibra = [f for f in res.flechas if f.limite_vibracao > 0.0]
        if vibra:
            _paragrafo(doc, "Vibrações sentidas no piso (Tabela 13.3): a "
                            "flecha das ações variáveis é comparada com "
                            "L/350.", cor=CINZA)
            _tabela(doc, ["Tramo", "f das ações variáveis (cm)",
                          "limite (cm)", "Situação"],
                    [[f"Tramo {f.tramo + 1}", _n(f.f_variavel),
                      _n(f.limite_vibracao),
                      "OK" if f.ok_vibracao else "NÃO OK"] for f in vibra])
        piso = [f for f in res.flechas if f.limite_piso_total > 0.0]
        if piso:
            _paragrafo(doc, "Pavimentos que devem permanecer planos "
                            "(Tabela 13.3): L/350 no total e L/600 no "
                            "deslocamento posterior à construção do piso.",
                       cor=CINZA)
            _tabela(doc, ["Tramo", "f total (cm)", "L/350 (cm)",
                          "f posterior (cm)", "L/600 (cm)", "Situação"],
                    [[f"Tramo {f.tramo + 1}", _n(f.f_total),
                      _n(f.limite_piso_total), _n(f.f_apos_alvenaria),
                      _n(f.limite_piso_apos),
                      "OK" if f.ok_piso else "NÃO OK"] for f in piso])

    fiss = [r for r in res.regioes if r.fissuracao is not None]
    if fiss:
        _titulo(doc, f"{n}.2 Abertura de fissuras", 2)
        _paragrafo(doc, "Expressões do item 17.3.3.2, com a tensão da "
                        "armadura no Estádio II sob a combinação frequente. O "
                        "limite vem da Tabela 13.4 para a classe de "
                        "agressividade adotada.")
        linhas = [[r.nome, _n(r.fissuracao.M_servico), _n(r.fissuracao.x_II),
                   _n(r.fissuracao.sigma_s), _n(r.fissuracao.Acri),
                   _n(r.fissuracao.rho_ri, 4),
                   _n(r.fissuracao.wk_1, 3), _n(r.fissuracao.wk_2, 3),
                   _n(r.fissuracao.wk, 3), _n(r.fissuracao.wk_limite, 2),
                   r.fissuracao.veredito] for r in fiss]
        _tabela(doc, ["Região", "M serv. (kN·m)", "xII (cm)", "σs (kN/cm²)",
                      "Acri (cm²)", "ρri", "wk1 (mm)", "wk2 (mm)", "wk (mm)", "limite",
                      "Situação"], linhas)


def _detalhamento(doc: Document, res: ResultadoViga, n: int,
                  secoes_m=None) -> None:
    _titulo(doc, f"{n}. Detalhamento", 1)
    _paragrafo(doc, "As barras longitudinais foram escalonadas a partir do "
                    "diagrama de armadura necessária decalado de aℓ "
                    "(17.4.2.2), com o prolongamento de lb,nec além da seção "
                    "em que deixam de ser necessárias (9.4.1.2).")
    _figura(doc, graficos.figura_armaduras(res))
    _figura(doc, desenho.figura_elevacao(res), largura_cm=17.0)
    _figura(doc, desenho.figura_secoes(res, secoes_m), largura_cm=17.0)

    _titulo(doc, f"{n}.1 Resumo das posições", 2)
    linhas = [[f"N{p.numero}", p.tipo, p.texto_quantidade,
               f"Ø{_n(p.phi, 1)}", p.face,
               _n(p.comprimento, 0), _n(p.comprimento_total, 1), _n(p.massa),
               p.descricao] for p in res.posicoes]
    _tabela(doc, ["Pos.", "Tipo", "Qtd", "Bitola", "Face", "C (cm)",
                  "Total (m)", "Massa (kg)", "Descrição"], linhas,
            [1.3, 2.2, 1.0, 1.4, 1.8, 1.5, 1.6, 1.6, 4.0])

    sub = 2
    if res.apoios_extremos:
        _apoios_extremos(doc, res, f"{n}.{sub}")
        sub += 1
    if res.ancoragens_negativas or res.ancoragens_torcao:
        _ancoragens_nos_extremos(doc, res, f"{n}.{sub}")
        sub += 1
    if res.grampos:
        _grampos(doc, res, f"{n}.{sub}")
        sub += 1
    _trechos(doc, res, f"{n}.{sub}")
    if any(t.mudancas for t in res.viga.tramos):
        sub += 1
    if al.juntas(res.viga):
        _juntas(doc, res, f"{n}.{sub}")
        sub += 1

    _titulo(doc, f"{n}.{sub} Resumo de aço", 2)
    q = res.quantitativo
    linhas = [[f"Ø{_n(phi, 1)} mm", d["barras"], _n(d["comprimento"], 1),
               _n(d["massa"])] for phi, d in q["por_bitola"].items()]
    linhas.append(["TOTAL", "", "", _n(q["massa_total"])])
    linhas.append(["TOTAL + 10 % de perdas", "", "",
                   _n(q["massa_com_perdas"])])
    _tabela(doc, ["Bitola", "Nº de barras", "Comprimento (m)", "Massa (kg)"],
            linhas)

    _titulo(doc, f"{n}.{sub + 1} Consumo de concreto e formas", 2)
    _paragrafo(doc, q["hipotese_forma"])
    linhas = [[f"Trecho {d['trecho']} (tramo {d['tramo']})", d["secao"],
               _n(d["L"], 2), _n(d["volume"], 3), _n(d["forma"], 2)]
              for d in q["por_trecho"]]
    linhas.append(["TOTAL", "", _n(q["comprimento"], 2),
                   _n(q["concreto_m3"], 3), _n(q["forma_m2"], 2)])
    _tabela(doc, ["Trecho", "Seção", "Comprimento (m)", "Volume (m³)",
                  "Forma (m²)"], linhas)
    _paragrafo(
        doc,
        f"Taxa de aço: {_n(q['taxa_aco'], 1)} kg/m³. "
        f"{_n(q['forma_m2'] / q['concreto_m3'], 1) if q['concreto_m3'] > 0 else '-'}"
        f" m² de forma por m³ de concreto.")


def _fadiga(doc: Document, res: ResultadoViga, n: int) -> None:
    """Capítulo da fadiga, só quando o critério está ligado (23.5)."""
    _titulo(doc, f"{n}. Estado-limite último de fadiga", 1)
    _paragrafo(doc, "Item 23.5 da NBR 6118. A solicitação é a da combinação "
                    "frequente (23.5.2) e as tensões são calculadas no Estádio "
                    "II com αe = 10, γf = 1,0, γc = 1,4 e "
                    "γs = 1,0 (23.5.3). A variação de tensão é medida "
                    "entre a combinação frequente e a parcela permanente. No "
                    "cortante, a contribuição do concreto é reduzida à metade "
                    "no Modelo I; no Modelo II corrige-se a inclinação da "
                    "biela.", cor=CINZA)
    if res.fadigas:
        _titulo(doc, f"{n}.1 Flexão", 2)
        _tabela(doc, ["Região", "Δσs (MPa)", "Δfsd,fad (MPa)",
                      "ηc,grad·σc (MPa)", "fcd,fad (MPa)", "Situação"],
                [[f.regiao, _n(f.delta_sigma_s, 0), _n(f.delta_fsd_fad, 0),
                  _n(f.eta_grad * f.sigma_c_max, 1), _n(f.fcd_fad, 1),
                  f.veredito] for f in res.fadigas])
    if res.fadigas_estribo:
        _titulo(doc, f"{n}.2 Armadura transversal", 2)
        _tabela(doc, ["x (m)", "V freq. (kN)", "V perm. (kN)", "Vc red. (kN)",
                      "Δσsw (MPa)", "Δfsd,fad (MPa)", "Situação"],
                [[_n(f.x), _n(f.V_frequente, 1), _n(f.V_permanente, 1),
                  _n(f.Vc_reduzido, 1), _n(f.delta_sigma_s, 0),
                  _n(f.delta_fsd_fad, 0), f.veredito]
                 for f in res.fadigas_estribo])


def _grampos(doc: Document, res: ResultadoViga, sub: str) -> None:
    """Grampos que completam a ancoragem onde o apoio não dá comprimento.

    Sem esta tabela o grampo apareceria só no quantitativo, como uma bitola
    fina que ninguém sabe de onde veio.
    """
    if not res.grampos:
        return
    _titulo(doc, f"{sub} Grampos de ancoragem nas extremidades", 2)
    _paragrafo(doc,
               "Onde o trecho reto do apoio não desenvolve o lb,nec exigido "
               "pelo item 18.3.2.4.1 — nem com o gancho de extremidade —, a "
               "ancoragem é completada por grampos: barras em U que abraçam a "
               "armadura longitudinal e levam para dentro da viga a parcela de "
               "força que o trecho reto não ancorou. O trecho reto responde por "
               "(lb,disp − Ø,grampo)/lanc da força; o grampo assume o resto. "
               "Cada grampo conta com duas pernas, e lb1 é medido da face do "
               "pilar até a ponta do grampo.", cor=CINZA)
    _tabela(doc, ["Apoio", "Face", "lanc (cm)", "lb,disp (cm)",
                  "Parcela do grampo", "Fsd (kN)", "As (cm²)", "Grampos",
                  "Ø,máx (mm)", "lb1 (cm)", "Situação"],
            [[f"Apoio {g.apoio}", g.face, _n(g.lanc, 1), _n(g.lb_disp, 1),
              f"{g.fracao * 100:.0f} %", _n(g.Fsd, 1), _n(g.As),
              f"{g.n} Ø{g.phi:g}", _n(g.phi_max, 1), _n(g.lb1, 0),
              "OK" if g.ok else "NÃO OK"] for g in res.grampos],
            [1.5, 1.4, 1.5, 1.7, 1.9, 1.4, 1.4, 1.6, 1.6, 1.4, 1.6])
    ruins = [g for g in res.grampos if not g.ok]
    if ruins:
        _paragrafo(doc,
                   "A bitola do grampo tem teto: (lb,disp/lanc)·Ø da armadura. "
                   "Acima dele nem o grampo ancora, e o apoio precisa crescer "
                   "ou a bitola da armadura precisa cair. Apoios nessa "
                   "situação: "
                   + ", ".join(f"Apoio {g.apoio}" for g in ruins) + ".",
                   cor=VERMELHO)
    _paragrafo(doc,
               "Divergências declaradas em relação à planilha de referência da "
               "qual este método foi extraído: (a) na ancoragem positiva, a "
               "planilha abandona o lb,nec quando o cobrimento lateral é maior "
               "ou igual a 7 cm e há gancho, deixando só os pisos geométricos; "
               "este cálculo mantém máx(lb,nec, r + 5,5 Ø, 60 mm), que é a "
               "leitura literal do 18.3.2.4.1; (b) a planilha calcula fct,m "
               "acima de C50 por 2,12·ln(1 + 0,11·fck), forma que a norma não "
               "traz — aqui vale 2,12·ln[1 + 0,1(fck + 8)].", cor=CINZA)


def _trechos(doc: Document, res: ResultadoViga, sub: str) -> None:
    """Os trechos prismáticos, quando algum tramo tem mais de um."""
    viga = res.viga
    if not any(t.mudancas for t in viga.tramos):
        return
    _titulo(doc, f"{sub} Trechos de seção constante", 2)
    _paragrafo(doc,
               "Um tramo com mudança de seção interna é dividido em trechos "
               "prismáticos, e cada trecho é dimensionado com a sua seção e "
               "com o momento máximo dentro dele. A rigidez do modelo também "
               "varia por trecho, com nó da malha em cada degrau. O tramo "
               "continua sendo a unidade de vão — é dele que se fala na flecha "
               "e no vão efetivo; o trecho é a unidade de geometria.", cor=CINZA)
    _tabela(doc, ["Trecho", "Tramo", "x inicial (m)", "x final (m)",
                  "Seção", "Alinhamento com o anterior"],
            [[f"T{t.k + 1}", f"{t.tramo + 1}", _n(t.x_ini, 2),
              _n(t.x_fim, 2), t.secao.descricao(),
              t.alinhamento or "mesma seção"] for t in viga.trechos],
            [1.6, 1.4, 2.4, 2.4, 3.2, 5.0])
    _paragrafo(doc,
               "No degrau interno não há pilar: o corte da seção acontece "
               "exatamente na abscissa declarada, e a armadura de cada lado "
               "recua o cobrimento para dentro do seu próprio concreto antes "
               "de dobrar. A regra do alinhamento é a mesma dos apoios — onde "
               "a face é contínua a barra passa, onde ela termina a barra "
               "ancora com gancho (18.3.2.4.1).", cor=CINZA)


def _juntas(doc: Document, res: ResultadoViga, sub: str) -> None:
    """Juntas de mudança de seção: o que atravessa e o que ancora.

    Sem esta tabela o desenho traria ganchos no meio da viga sem nada que os
    explicasse. O que decide cada linha é o alinhamento declarado na geometria,
    e não a seção em si: a mesma mudança de 50 para 70 cm ancora a face
    inferior se estiver alinhada pelo topo, e a superior se estiver pelo fundo.
    """
    juntas = al.juntas(res.viga)
    if not juntas:
        return
    viga = res.viga
    _titulo(doc, f"{sub} Juntas de mudança de seção", 2)
    _paragrafo(doc,
               "Onde a face é contínua a armadura atravessa o apoio e segue "
               "normalmente; onde a face termina, a barra do tramo de seção "
               "maior é cortada no eixo do apoio e ancorada com gancho, como "
               "armadura de extremidade (18.3.2.4.1). A barra que vem da seção "
               "menor entra na maior sem gancho: o nível dela existe dentro "
               "daquela seção. As duas não formam emenda — estão em níveis "
               "diferentes —, e por isso o traspasse não é exigido na junta.",
               cor=CINZA)
    linhas = []
    for j in juntas:
        esq = viga.trechos[j.trecho_esq].secao
        dirt = viga.trechos[j.trecho_dir].secao
        for face in al.FACES:
            lados = j.lado_com_gancho(face)
            if not lados:
                situacao = "atravessa — armadura contínua"
            elif len(lados) > 1:
                situacao = "ancora nos dois lados"
            else:
                tramo = (j.tramo_esq if "esquerda" in lados
                         else j.tramo_dir) + 1
                situacao = f"ancora o tramo {tramo}"
            linhas.append([f"Apoio {j.k + 1}",
                           f"{esq.descricao()} → {dirt.descricao()}",
                           j.alinhamento, face, situacao])
    _tabela(doc, ["Apoio", "Seções", "Alinhamento", "Face", "Situação"],
            linhas, [1.6, 4.0, 2.6, 2.0, 5.8])
    _paragrafo(doc,
               "A armadura negativa de um apoio é dimensionada com a seção "
               "menos favorável entre as duas vizinhas — a de menor altura, "
               "que dá o menor braço de alavanca —, para servir aos dois "
               "tramos. Onde a face superior é interrompida, a transferência "
               "do esforço através da junta não se dá pelas barras e precisa "
               "de solução própria; a aba de avisos registra o caso como erro "
               "quando aquela face é tracionada por cálculo.", cor=CINZA)


def _ancoragens_nos_extremos(doc: Document, res: ResultadoViga,
                             sub: str) -> None:
    """Ancoragem da negativa e da longitudinal de torção nos extremos.

    O 18.3.2.4-d manda ancorar a armadura negativa dos apoios extremos pelo
    18.3.2.4.1, e a barra de torção tem de ancorar pelo 9.4.1. Nenhuma das
    duas aparecia na memória: a tabela de apoios extremos é só a da positiva.
    """
    _titulo(doc, f"{sub} Ancoragem da armadura negativa e da longitudinal de "
                 f"torção nos apoios de extremidade", 2)
    if res.ancoragens_negativas:
        _paragrafo(doc, "Armadura negativa (18.3.2.4-d e 18.3.2.4.1): "
                        "ancoragem a partir da face do apoio, com o maior "
                        "entre lb,nec (9.4.2.5, barra em má aderência), "
                        "(r + 5,5 Ø) e 60 mm. Quando o trecho reto não basta "
                        "num engaste, a barra desce no elemento de apoio: "
                        "contam os trechos retos (o horizontal até a curva e "
                        "a perna depois dela), sem o arco e sem o α = 0,7 do "
                        "gancho, e a curva, num nó de pórtico, tem o diâmetro "
                        "do 18.2.2 reduzido pela tensão no início dela.",
                   cor=CINZA)
        _tabela(doc, ["Apoio", "Barra", "As calc / ef (cm²)", "lb,nec (cm)",
                      "exigido (cm)", "face à ponta (cm)", "Solução",
                      "Situação"],
                [[f"Apoio {a.apoio}", f"Ø{a.phi:g}",
                  f"{_n(a.As_calc)} / {_n(a.As_ef)}", _n(a.lb_nec, 1),
                  _n(a.exigido, 1), _n(a.l_reto, 1), a.solucao,
                  "OK" if a.ok else "NÃO OK"]
                 for a in res.ancoragens_negativas])
        # a geometria da descida, para a solução poder ser conferida no nó: o
        # comprimento "da face à ponta" inclui a curva, e lido como reto ele
        # fazia parecer que a dobra não cabia no apoio
        descem = [a for a in res.ancoragens_negativas if a.raio_eixo > 0]
        if descem:
            _paragrafo(doc, "Geometria da barra que desce no engaste: o "
                            "comprimento da face à ponta inclui a curva; o "
                            "trecho reto é o que sobra antes dela. A perna é "
                            "a dimensão externa, medida do topo da barra, e "
                            "o pilar tem de comportar o que ela entra abaixo "
                            "da viga, mais o cobrimento na ponta. A "
                            "interferência com a armadura do pilar não é "
                            "verificada.", cor=CINZA)
            _tabela(doc, ["Apoio", "Barra", "pino D (18.2.2)",
                          "raio no eixo", "reto até a curva", "perna",
                          "ancorado (retos)", "abaixo da viga",
                          "pilar exigido", "pilar informado"],
                    [[f"Apoio {a.apoio}", f"Ø{a.phi:g}",
                      f"{_n(a.diametro_curva, 1)} cm",
                      f"{_n(a.raio_eixo, 1)} cm",
                      f"{_n(a.reto_ate_curva, 1)} cm",
                      f"{_n(a.perna, 1)} cm", f"{_n(a.desenvolvido, 1)} cm",
                      f"{_n(a.abaixo_da_viga, 1)} cm",
                      f"{_n(a.pilar_exigido, 1)} cm",
                      f"{_n(a.pilar_informado, 0)} cm"
                      if a.pilar_informado > 0 else "não informado"]
                     for a in descem])
    if res.ancoragens_torcao:
        _paragrafo(doc, "Armadura longitudinal de torção (17.5.1.6): a NBR "
                        "não tem item próprio, e vale o 9.4.1 -- a força da "
                        "barra tem de passar ao concreto. Mede-se como no "
                        "18.3.2.4.1, a partir da face do apoio, com a barra em "
                        "má aderência; o gancho admite α = 0,7 (9.4.2.5) "
                        "quando o cobrimento normal ao seu plano dá 3 Ø.",
                   cor=CINZA)
        _tabela(doc, ["Apoio", "Posição", "As calc / ef (cm²)",
                      "lb,nec reta (cm)", "exigido (cm)", "disponível (cm)",
                      "Solução", "Situação"],
                [[f"Apoio {a.apoio}", f"N{a.posicao.numero} Ø{a.phi:g}",
                  f"{_n(a.As_calc)} / {_n(a.As_ef)}", _n(a.lb_nec, 1),
                  _n(a.exigido, 1), _n(a.l_disponivel, 1), a.solucao,
                  "OK" if a.ok else "NÃO OK"]
                 for a in res.ancoragens_torcao])


def _apoios_extremos(doc: Document, res: ResultadoViga, sub: str) -> None:
    """Ancoragem da armadura positiva nos apoios de extremidade (18.3.2.4.1).

    Os números desta verificação eram calculados e não saíam em lugar nenhum:
    só o aviso aparecia, quando falhava.
    """
    if not res.apoios_extremos:
        return
    _titulo(doc, f"{sub} Ancoragem nos apoios de extremidade", 2)
    _paragrafo(doc, "O item 18.3.2.4.1 exige ancorar, a partir da face do "
                    "apoio, o maior valor entre lb,nec (9.4.2.5), (r + 5,5 Ø) "
                    "com o raio de dobramento da Tabela 9.1 e 60 mm. A força "
                    "a ancorar é Rsd = (aℓ/d)·Vsd.", cor=CINZA)
    aco = res.viga.aco
    # as bitolas que efetivamente dobram: é delas que o raio interessa
    phis = sorted({p.phi for p in res.posicoes
                   if p.tipo in ("longitudinal", "porta")
                   and (p.dobra_ini > 1e-9 or p.dobra_fim > 1e-9)})
    _tabela(doc, ["Apoio", "Rsd (kN)", "As nec. (cm²)", "As ef. (cm²)",
                  "lb,nec (cm)", "r + 5,5Ø (cm)", "exigido (cm)",
                  "disponível (cm)", "Situação"],
            [[f"Apoio {a.apoio}", _n(a.Rsd, 1), _n(a.As_necessaria),
              _n(a.As_efetiva), _n(a.lb_calculado, 1), _n(a.piso_gancho, 1),
              _n(a.lb_nec, 1), _n(a.l_disponivel, 1),
              "OK" if a.ok else "NÃO OK"] for a in res.apoios_extremos])
    if phis:
        _paragrafo(doc, "Geometria da dobra das barras ancoradas nas "
                        "extremidades:", cor=CINZA)
        _tabela(doc, ["Bitola", "Pino D (Tabela 9.1)", "Raio no eixo",
                      "Ponta reta 8 Ø (9.4.2.3-c)", "Altura do gancho"],
                [[f"Ø{phi:g} mm", f"{aco.diametro_dobramento(phi):.1f} cm",
                  f"{aco.raio_dobramento_eixo(phi):.1f} cm",
                  f"{aco.ponta_reta_gancho(phi):.1f} cm",
                  f"{aco.altura_gancho_90(phi):.1f} cm"]
                 for phi in phis],
                [2.0, 3.4, 2.6, 4.2, 3.2])
        _paragrafo(doc, "A altura do gancho é o raio de dobramento medido no "
                        "eixo da barra mais a ponta reta de 8 Ø: os 8 Ø do "
                        "item 9.4.2.3-c são a **ponta**, que só começa depois "
                        "da dobra. Medida na face externa, esta expressão "
                        "reproduz a tabela de alturas de gancho de Araújo. O "
                        "desenho traça a dobra como arco desse raio; as cotas "
                        "são as dimensões externas, com a curvatura omitida, "
                        "como manda a prática de detalhamento.", cor=CINZA)


def _roteiro(doc: Document, res: ResultadoViga, n: int) -> None:
    """Roteiro auditável: item da norma, exigência, situação e o número."""
    _titulo(doc, f"{n}. Roteiro de verificações", 1)
    verificacoes = auditoria.roteiro(res)
    contagem = auditoria.resumo(verificacoes)
    _paragrafo(doc,
               "**Atendido** é verificação com aprovação; **Aplicado** é "
               "prescrição imposta por construção, que o cálculo não pode "
               "violar (uma armadura mínima, um espaçamento máximo); **Não "
               "aplicável** é item que não incide nesta viga; e **Não "
               "verificado** é item que este cálculo não cobre — e que precisa "
               "de conferência à parte.")
    _paragrafo(doc,
               "  ".join(f"{k}: {v}" for k, v in sorted(contagem.items())),
               italico=True)
    _tabela(doc, ["Item", "Exigência", "Situação", "Observação"],
            [[x.item, x.exigencia, x.situacao, x.observacao]
             for x in verificacoes], [2.0, 5.0, 2.2, 6.8])
    nao_atendidos = [x for x in verificacoes
                     if x.situacao == auditoria.NAO_ATENDIDO]
    if nao_atendidos:
        _paragrafo(doc,
                   "Há verificação não atendida: "
                   + "; ".join(f"{x.item} ({x.exigencia})"
                               for x in nao_atendidos)
                   + ". A viga, como está, precisa ser revista antes da "
                     "emissão.", cor=VERMELHO)
    nao_verificados = [x for x in verificacoes
                       if x.situacao == auditoria.NAO_VERIFICADO]
    if nao_verificados:
        _paragrafo(doc,
                   f"{len(nao_verificados)} itens marcados como não "
                   f"verificados exigem conferência fora deste documento.",
                   cor=CINZA)


def _pendencias(doc: Document, res: ResultadoViga, n: int) -> None:
    _titulo(doc, f"{n}. Observações e pendências", 1)
    _paragrafo(doc, "Complementa o roteiro do capítulo anterior: ali estão as "
                    "verificações e a situação de cada uma; aqui, o texto de "
                    "cada aviso que o cálculo emitiu.", cor=CINZA)
    erros, construtivos = avisos_mod.separar(res.avisos)

    _titulo(doc, f"{n}.1. Erros de verificação", 2)
    if not erros:
        _paragrafo(doc, "Nenhum: todas as verificações da NBR 6118 "
                        "consideradas neste cálculo foram atendidas.",
                   cor=VERDE)
    else:
        _paragrafo(doc, "Alguma verificação não foi atendida ou um dado de "
                        "entrada está inconsistente. A viga, como está, "
                        "precisa ser revista.", cor=VERMELHO)
        for a in erros:
            p = doc.add_paragraph(style="List Bullet")
            r = p.add_run(a)
            r.font.size = Pt(9.5)
            r.font.color.rgb = VERMELHO

    _titulo(doc, f"{n}.2. Avisos construtivos", 2)
    if not construtivos:
        _paragrafo(doc, "Nenhum.", cor=CINZA)
        return
    _paragrafo(doc, "Decisões de detalhamento adotadas pelo programa e aqui "
                    "declaradas; não indicam erro.", cor=CINZA)
    for a in construtivos:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(a)
        r.font.size = Pt(9.5)
        r.font.color.rgb = CINZA


def _combinacoes(doc: Document, res: ResultadoViga,
                 titulo: str = "Anexo A — Combinações consideradas") -> None:
    _titulo(doc, titulo, 1)
    elu = [c.nome for c in res.combinacoes if c.tipo == "ELU"]
    _paragrafo(doc, f"Foram varridas {len(res.combinacoes)} combinações, "
                    f"sendo {len(elu)} últimas. As demais são de serviço "
                    f"(raras, frequentes e quase permanentes).")
    for nome in elu[:60]:
        doc.add_paragraph(nome, style="List Bullet")
    if len(elu) > 60:
        _paragrafo(doc, f"... e mais {len(elu) - 60} combinações últimas.",
                   italico=True)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def _capitulos_da_viga(doc: Document, res: ResultadoViga, secoes_m,
                      primeiro: int = 1, prefixo: str = "") -> None:
    """Os capítulos de resultado de uma viga, do dado de entrada ao roteiro.

    Numa memória de uma viga só os capítulos são ``2``, ``3``... (o 1 é a
    metodologia) e ``prefixo`` fica vazio; numa de várias, ``prefixo="3."`` os
    faz ``3.1``, ``3.2``... sob o título da viga. Os capítulos usam o número só
    dentro de texto, então o inteiro e o texto servem.
    """
    k = primeiro

    def numero():
        return f"{prefixo}{k}" if prefixo else k

    _dados(doc, res, numero()); k += 1
    _analise(doc, res, numero()); k += 1
    _flexao(doc, res, numero()); k += 1
    _cisalhamento(doc, res, numero()); k += 1
    if res.torcoes:
        _torcao(doc, res, numero()); k += 1
    _servico(doc, res, numero()); k += 1
    _detalhamento(doc, res, numero(), secoes_m); k += 1
    if res.fadigas or res.fadigas_estribo:
        _fadiga(doc, res, numero())
        k += 1
    _roteiro(doc, res, numero()); k += 1
    _pendencias(doc, res, numero()); k += 1
    _combinacoes(doc, res, f"{prefixo}{k} Combinações consideradas"
                 if prefixo else "Anexo A — Combinações consideradas")


def gerar(res: ResultadoViga, caminho: str, secoes_m=None, arquivo: str = "",
          emitido_em: datetime | None = None) -> str:
    """Gera a memória de cálculo em .docx e devolve o caminho do arquivo."""
    return gerar_varias([(res, secoes_m)], caminho, arquivo=arquivo,
                        emitido_em=emitido_em)


def _capa_projeto(doc: Document, resultados, nome: str) -> None:
    """Capa da memória de várias vigas: o conjunto, e uma linha por viga."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("MEMÓRIA DE CÁLCULO\nDIMENSIONAMENTO DE VIGAS DE CONCRETO "
                  "ARMADO")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = AZUL
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("ABNT NBR 6118 — Projeto de estruturas de concreto")
    r.italic = True
    r.font.color.rgb = CINZA
    doc.add_paragraph()
    obras = sorted({r.viga.projeto for r in resultados if r.viga.projeto})
    aco = sum(r.quantitativo["massa_total"] for r in resultados)
    aco_perdas = sum(r.quantitativo["massa_com_perdas"] for r in resultados)
    concreto = sum(r.quantitativo["concreto_m3"] for r in resultados)
    _tabela(doc, ["Item", "Descrição"], [
        ["Projeto", nome or " / ".join(obras) or "-"],
    ] + _identificacao_da_emissao(doc) + [
        ["Nº de vigas", len(resultados)],
        ["Aço total", f"{_n(aco, 1)} kg ({_n(aco_perdas, 1)} kg com 10 % "
                      f"de perdas)"],
        ["Concreto total", f"{_n(concreto, 3)} m³"],
        ["Situação geral", "TODAS AS VERIFICAÇÕES ATENDIDAS EM TODAS AS VIGAS"
         if all(r.ok for r in resultados)
         else "HÁ VERIFICAÇÕES NÃO ATENDIDAS — VER O ROTEIRO DE CADA VIGA"],
    ], [5.0, 11.0])
    _titulo(doc, "Vigas desta memória", 2)
    _tabela(doc, ["Capítulo", "Viga", "Tramos", "Comprimento (m)",
                  "Concreto", "Aço (kg)", "Situação", "Dados (identif.)"],
            [[f"{k + 2}", r.viga.nome, len(r.viga.tramos),
              _n(r.viga.comprimento), r.viga.concreto.classe,
              _n(r.quantitativo["massa_total"], 1),
              "Atende" if r.ok else "Não atende", r.viga.impressao_digital()]
             for k, r in enumerate(resultados)],
            [1.6, 2.6, 1.4, 2.2, 1.6, 1.8, 2.0, 3.0])
    _paragrafo(doc, "O capítulo 1 traz a metodologia, que vale para todas as "
                    "vigas. Cada viga tem em seguida o seu capítulo, com dados "
                    "de entrada, esforços, dimensionamento, verificações, "
                    "detalhamento e roteiro.", cor=CINZA)


def gerar_varias(itens, caminho: str, nome_projeto: str = "",
                 arquivo: str = "", emitido_em: datetime | None = None) -> str:
    """Gera uma memória de cálculo de uma ou várias vigas em .docx.

    ``itens`` é uma lista de ``(res, secoes_m)``. Com uma viga o documento é o
    de sempre. Com várias, a **metodologia aparece uma vez** (capítulo 1) e os
    resultados vêm **agrupados por viga**: o capítulo 2 é todo da primeira
    viga -- dados, esforços, flexão, cisalhamento, serviço, detalhamento,
    roteiro, combinações --, o 3 é todo da segunda, e assim por diante. Nada
    de uma viga se mistura com o da seguinte.

    ``arquivo`` é o nome do arquivo de projeto de onde vêm os dados, e
    ``emitido_em`` a data da emissão (agora, se omitida). Os dois, mais a versão
    do programa e a impressão digital dos dados de cada viga, identificam o
    documento na capa; o rodapé repete o programa e a data, e a última página
    traz o bloco de conferência e responsabilidade técnica.
    """
    itens = list(itens)
    if not itens:
        raise ValueError("Nenhuma viga para a memória de cálculo.")
    resultados = [res for res, _ in itens]
    emitido_em = emitido_em or datetime.now()
    doc = Document()
    _configurar(doc)
    doc._identificacao = {"emitido_em": emitido_em, "arquivo": arquivo}
    _rodape(doc, emitido_em)
    doc.core_properties.author = f"Vigas {__version__}"
    doc.core_properties.created = emitido_em
    doc.core_properties.title = "Memória de cálculo de vigas de concreto armado"
    if len(itens) == 1:
        res, secoes_m = itens[0]
        _capa(doc, res)
        doc.add_page_break()
        _metodologia(doc, res, 1)
        _capitulos_da_viga(doc, res, secoes_m, primeiro=2)
        _bloco_de_conferencia(doc)
        doc.save(caminho)
        return caminho

    _capa_projeto(doc, resultados, nome_projeto)
    doc.add_page_break()
    _metodologia(doc, resultados, 1)
    for k, (res, secoes_m) in enumerate(itens):
        doc.add_page_break()
        numero = k + 2
        _titulo(doc, f"{numero}. Viga {res.viga.nome}", 1)
        _ficha(doc, res)
        doc._nivel_extra = 1               # os capítulos descem sob a viga
        try:
            _capitulos_da_viga(doc, res, secoes_m, prefixo=f"{numero}.")
        finally:
            doc._nivel_extra = 0
    _bloco_de_conferencia(doc)
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
