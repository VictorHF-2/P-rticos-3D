# -*- coding: utf-8 -*-
"""
relatorio.py
Memória de cálculo em Word (.docx) do pavimento de lajes, com os dados de
entrada, a classificação, os esforços nos dois regimes, a compatibilização
das bordas comuns, o dimensionamento passo a passo, as verificações de
serviço, o cortante, o detalhamento, as reações e o quantitativo. Cada
resultado traz o item da NBR 6118 -- ou o parágrafo da apostila -- que o
justifica.

A conversão para PDF é feita pelo próprio Word, via COM, quando disponível.
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

from ..core import avisos as avisos_mod
from ..core.alveolar import linhas_protensao
from ..core.atribuicao import modelos_efetivos
from ..core.nervurada import dimensionar_nervurada
from ..core.alveolar import resolver as resolver_alveolar
from ..core.trelicada import dimensionar_trelicada
from ..core.esforcos import BORDOS_DA_DIRECAO
from . import (auditoria, desenho, graficos, graficos_alveolar,
               graficos_nervurada, graficos_trelicada, vista3d)

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
            larguras: list[float] | None = None,
            destaques: dict[int, RGBColor] | None = None) -> None:
    if not linhas:
        _paragrafo(doc, "(nada a listar)", italico=True, cor=CINZA)
        return
    t = doc.add_table(rows=1, cols=len(cabecalho))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, titulo in enumerate(cabecalho):
        cel = t.rows[0].cells[i]
        cel.text = ""
        r = cel.paragraphs[0].add_run(str(titulo))
        r.bold = True
        cel.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for k, linha in enumerate(linhas):
        cels = t.add_row().cells
        for i, valor in enumerate(linha):
            cels[i].text = ""
            r = cels[i].paragraphs[0].add_run(
                "" if valor is None else str(valor))
            cor = (destaques or {}).get(k)
            if cor is not None:
                r.font.color.rgb = cor
                r.bold = True
            cels[i].paragraphs[0].alignment = (
                WD_ALIGN_PARAGRAPH.LEFT if i == 0
                else WD_ALIGN_PARAGRAPH.CENTER)
    if larguras:
        for linha in t.rows:
            for i, larg in enumerate(larguras[:len(linha.cells)]):
                linha.cells[i].width = Cm(larg)


def _figura(doc: Document, fig, largura_cm: float = 16.0) -> None:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        caminho = f.name
    try:
        fig.savefig(caminho, dpi=180, bbox_inches="tight")
        doc.add_picture(caminho, width=Cm(largura_cm))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass


def _figura_arquivo(doc: Document, caminho: str,
                    largura_cm: float = 16.0) -> None:
    """Embute um PNG já gravado -- a vista 3D (``vista3d.renderizar_png``)
    não devolve uma figura matplotlib para ``_figura`` salvar, já grava o
    próprio arquivo fora de tela."""
    doc.add_picture(caminho, width=Cm(largura_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER


def _n(valor, casas: int = 2) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, str):
        return valor
    try:
        return f"{valor:,.{casas}f}".replace(",", "@").replace(".", ",") \
            .replace("@", ".")
    except (TypeError, ValueError):
        return str(valor)


def _bordo_texto(laje, bordo: int) -> str:
    b = laje.bordos[bordo - 1]
    texto = b.vinculo
    if b.vinculo == "engastado":
        texto += f" (i = {_n(b.grau)}"
        texto += f", {b.vizinha})" if b.vizinha else ")"
    return texto


# ---------------------------------------------------------------------------
# Capítulos
# ---------------------------------------------------------------------------

def _capa(doc: Document, res) -> None:
    pav = res.pavimento
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("MEMÓRIA DE CÁLCULO")
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = AZUL

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(
        "Lajes maciças, treliçadas, alveolares e nervuradas de concreto "
        "armado — ABNT NBR 6118" if res.especiais
        else "Lajes maciças de concreto armado — ABNT NBR 6118")
    r.font.size = Pt(12)
    r.font.color.rgb = CINZA

    doc.add_paragraph()
    _tabela(doc, ["Item", "Valor"], [
        ["Pavimento", pav.nome],
        ["Projeto", pav.projeto or "—"],
        ["Lajes", f"{len(res.lajes)} maciça(s)"
                  + (f" e {sum(len(e.lajes) for e in res.especiais)} "
                     f"especial(is)" if res.especiais else "")],
        ["Área total", f"{_n(res.area_total + res.area_especiais)} m²"],
        ["Bordas comuns", f"{len(pav.continuidades)}"],
        ["Concreto", f"{pav.concreto.classe} "
                     f"(agregado {pav.concreto.agregado})"],
        ["Aço", pav.aco.categoria],
        ["Agressividade ambiental",
         f"CAA {pav.ambiente.caa} — {pav.ambiente.descricao}"],
        ["Cobrimento inferior / superior",
         f"{_n(pav.ambiente.cobrimento_nominal, 1)} / "
         f"{_n(pav.ambiente.cobrimento_superior(pav.config.bitola_minima_negativa), 1)} cm"],
        ["Aço total", f"{_n(res.quantitativo.get('massa_geral', 0.0), 1)} kg "
                      f"({_n(res.quantitativo.get('taxa_geral_por_m2', 0.0))} "
                      f"kg/m²)"],
    ], larguras=[6.0, 10.0])

    erros = res.erros
    doc.add_paragraph()
    if erros:
        _paragrafo(doc, f"ATENÇÃO: {len(erros)} verificação(ões) não "
                        f"fecharam. Veja o capítulo de pendências.",
                   cor=VERMELHO)
    else:
        _paragrafo(doc, "Todas as verificações normativas fecharam.",
                   cor=VERDE)


def _metodologia(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Metodologia")
    _paragrafo(doc,
               "O cálculo segue a ABNT NBR 6118 e o roteiro de *Projeto de "
               "lajes maciças de concreto armado* (A. Campos Filho, "
               "DECIV/UFRGS, 2014), cujos parágrafos são citados como §.")
    _tabela(doc, ["Assunto", "Procedimento"],
            [[a, b] for a, b in auditoria.metodologia(res)],
            larguras=[4.2, 11.8])


def _dados(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Dados de entrada")
    pav = res.pavimento

    _titulo(doc, f"{n}.1 Geometria e vinculação", 2)
    _tabela(doc,
            ["Laje", "a (m)", "b (m)", "h (cm)", "a,ef", "b,ef", "b/a",
             "Bordo 1", "Bordo 2", "Bordo 3", "Bordo 4"],
            [[rl.nome, _n(rl.laje.a), _n(rl.laje.b), _n(rl.laje.h, 1),
              _n(rl.laje.a_ef), _n(rl.laje.b_ef),
              _n(rl.laje.b_ef / rl.laje.a_ef),
              *[_bordo_texto(rl.laje, k) for k in (1, 2, 3, 4)]]
             for rl in res.lajes])
    _paragrafo(doc,
               "Os bordos são numerados no contorno começando por um de "
               "comprimento a, de modo que os bordos 1 e 3 medem a e os "
               "bordos 2 e 4 medem b. Daí a correspondência entre bordo e "
               "direção: o bordo 1 apoia a faixa que vaza na direção b, e é "
               "por isso que o momento negativo dele é m'1 = -i1 mb.",
               italico=True, cor=CINZA)

    _titulo(doc, f"{n}.2 Composição de cargas", 2)
    for rl in res.lajes:
        _paragrafo(doc, f"{rl.nome}"
                        + (f" — {rl.laje.descricao}" if rl.laje.descricao
                           else ""))
        itens = rl.laje.resumo_cargas()
        linhas = [[nome, f"{_n(v)} kN/m²"] for nome, v in itens]
        g = rl.laje.g_total
        linhas.append(["Total permanente g", f"{_n(g)} kN/m²"])
        linhas.append(["Total variável q", f"{_n(rl.laje.variavel)} kN/m²"])
        linhas.append(["p = g + q", f"{_n(g + rl.laje.variavel)} kN/m²"])
        _tabela(doc, ["Parcela", "Valor"], linhas, larguras=[11.0, 4.0])

    _titulo(doc, f"{n}.3 Materiais", 2)
    _tabela(doc, ["Propriedade", "Valor"],
            [[k, _n(v, 4) if isinstance(v, float) and abs(v) < 1 else _n(v)]
             for k, v in pav.concreto.resumo().items()]
            + [[k, _n(v, 4) if isinstance(v, float) and abs(v) < 1
                else _n(v)] for k, v in pav.aco.resumo().items()],
            larguras=[7.0, 8.0])

    _titulo(doc, f"{n}.4 Critérios de cálculo", 2)
    cfg = pav.config
    _tabela(doc, ["Critério", "Valor"], [
        ["gamma_g / gamma_q", f"{_n(cfg.gamma_g)} / {_n(cfg.gamma_q)}"],
        ["psi_0 / psi_2", f"{_n(cfg.psi_0)} / {_n(cfg.psi_2)}"],
        ["(1 + alfa_f) da flecha diferida", _n(cfg.fator_fluencia)],
        ["Limite de flecha", f"L/{cfg.divisor_flecha} "
                             f"(L/{cfg.divisor_flecha_balanco} em balanço)"],
        ["Compatibilização das bordas comuns", cfg.compatibilizacao],
        ["Razão mínima m'/m no ELU", _n(cfg.razao_minima_borda_vao, 1)],
        ["Verificação do cortante (19.4)",
         "sim" if cfg.verificar_cisalhamento else "não"],
        ["Espaçamento máximo principal / distribuição",
         f"{_n(cfg.espacamento_maximo_principal, 0)} / "
         f"{_n(cfg.espacamento_maximo_distribuicao, 0)} cm"],
    ], larguras=[8.0, 7.0])

    _titulo(doc, f"{n}.5 Planta do pavimento", 2)
    _figura(doc, graficos.figura_planta(res))

    if res.especiais:
        _titulo(doc, f"{n}.6 Lajes treliçadas, alveolares e nervuradas", 2)
        _paragrafo(doc,
                   "Estas lajes foram atribuídas na planta: vão, apoios e "
                   "cargas vêm dos dados acima e da vinculação dos bordos; a "
                   "seção, a treliça, a protensão e os critérios, do perfil "
                   "escolhido. Os capítulos de cada sistema trazem o "
                   "cálculo.", italico=True, cor=CINZA)
        linhas = []
        for e in res.especiais:
            for nome in e.lajes:
                laje = pav.laje(nome)
                if laje is None:
                    continue
                vao = "—" if laje.tipo == "nervurada_bi" else \
                    f"em {laje.direcao_global(laje.direcao)}"
                linhas.append([laje.nome, laje.rotulo_tipo, e.perfil,
                               _n(laje.a), _n(laje.b), _n(laje.h, 1), vao,
                               *[_bordo_texto(laje, k) for k in (1, 2, 3, 4)]])
        _tabela(doc, ["Laje", "Tipo", "Perfil", "a (m)", "b (m)", "h (cm)",
                      "Vão", "Bordo 1", "Bordo 2", "Bordo 3", "Bordo 4"],
                linhas)


def _classificacao(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Classificação das lajes")
    _tabela(doc, ["Laje", "b/a", "Tipo", "Caso / esquema", "Motivo"],
            [[rl.nome, _n(rl.laje.b_ef / rl.laje.a_ef),
              rl.esforcos.classificacao.tipo,
              (f"caso {rl.esforcos.classificacao.caso}"
               if rl.esforcos.classificacao.em_cruz
               else f"esquema {rl.esforcos.classificacao.esquema}"),
              rl.esforcos.classificacao.motivo] for rl in res.lajes],
            larguras=[1.8, 1.4, 2.2, 2.4, 8.2])


def _esforcos(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Esforços solicitantes")
    _paragrafo(doc,
               "O estado limite último usa o regime rígido-plástico (§3.2) e "
               "o de serviço, o regime elástico (§3.1). São dois caminhos "
               "independentes: o primeiro dá a armadura, o segundo dá a "
               "flecha.")
    if res.mef is not None:
        _paragrafo(doc,
                   "As lajes armadas em cruz têm o estado limite último "
                   "calculado por elementos finitos de placa e Wood-Armer, "
                   "regime elástico (capítulo seguinte à compatibilização); "
                   "as armadas em uma direção ficam com o método das faixas. "
                   "O estado limite de serviço segue pelas tabelas elásticas "
                   "em todas.", italico=True, cor=CINZA)

    for rl in res.lajes:
        esf = rl.esforcos
        cls = esf.classificacao
        _titulo(doc, f"{n}.{res.lajes.index(rl) + 1} {rl.nome}", 2)

        if cls.em_cruz and esf.metodo == "mef":
            _esforcos_mef_da_laje(doc, res, rl)
        elif cls.em_cruz:
            _paragrafo(doc, "Regime rígido-plástico — método das linhas de "
                            "ruptura:")
            linhas = [
                ["a / b (vãos efetivos)",
                 f"{_n(rl.laje.a_ef)} / {_n(rl.laje.b_ef)} m"],
                ["a/b", _n(rl.laje.a_ef / rl.laje.b_ef, 3)],
                ["i1, i2, i3, i4",
                 " ; ".join(_n(v) for v in rl.laje.graus)],
                ["Coeficiente de ortotropia phi",
                 f"{_n(esf.phi, 4)} "
                 f"({'isótropa' if esf.isotropa else 'ortótropa'})"],
                ["a_r = 2a / (raiz(1+i2) + raiz(1+i4))", f"{_n(esf.ar, 3)} m"],
                ["b_r = 2b / (raiz(1+i1) + raiz(1+i3))", f"{_n(esf.br, 3)} m"],
            ]
            if esf.alfa_parede or esf.beta_parede:
                linhas += [
                    ["alfa (parede paralela a a)", _n(esf.alfa_parede, 4)],
                    ["beta (parede paralela a b)", _n(esf.beta_parede, 4)],
                ]
            linhas += [
                ["b*_r", f"{_n(esf.br_estrela, 3)} m"],
                ["p* de cálculo", f"{_n(esf.p_estrela)} kN/m²"],
                ["m = (p*/8) a_r b*_r / (1 + a_r/b*_r + b*_r/a_r)",
                 f"{_n(esf.ma / max(esf.gamma_n, 1e-9))} kN·m/m"],
            ]
            if esf.gamma_n > 1.0:
                linhas.append(["gamma_n (13.2.4.1)", _n(esf.gamma_n)])
            linhas += [
                ["m_a de cálculo", f"{_n(esf.ma)} kN·m/m"],
                ["m_b = phi m_a de cálculo", f"{_n(esf.mb)} kN·m/m"],
            ]
            _tabela(doc, ["Grandeza", "Valor"], linhas, larguras=[9.5, 5.5])
        else:
            _paragrafo(doc,
                       f"Laje armada em uma só direção ({cls.direcao}), "
                       f"esquema estrutural {cls.esquema}. Vão efetivo de "
                       f"{_n(esf.vao_referencia)} m.")
            _tabela(doc, ["Faixa", "bw vão (cm)", "bw engaste (cm)",
                          "p_d (kN/m²)", "m vão (kN·m/m)",
                          "m engaste (kN·m/m)"],
                    [[f.nome, _n(f.bw_vao, 0), _n(f.bw_eng, 0), _n(f.p_d),
                      _n(f.m_vao), _n(f.m_eng)] for f in esf.faixas])

        if esf.m_neg and esf.metodo != "mef":
            _paragrafo(doc, "Momentos negativos dos engastes "
                            "(m'k = -ik . m da direção que o bordo apoia):")
            _tabela(doc, ["Bordo", "Direção que apoia", "i",
                          "m' de cálculo (kN·m/m)", "m' elástico de serviço"],
                    [[str(k),
                      "b" if k in BORDOS_DA_DIRECAO["b"] else "a",
                      _n(rl.laje.bordos[k - 1].i),
                      _n(v), _n(esf.m_neg_ser.get(k, 0.0))]
                     for k, v in sorted(esf.m_neg.items())])

        _paragrafo(doc, "Regime elástico — combinação quase permanente de "
                        f"serviço (p_ser = {_n(esf.p_ser)} kN/m²):")
        linhas = [["Coeficiente " + k, _n(v, 4)]
                  for k, v in esf.alfas_elasticos.items()]
        linhas += [["m_a de serviço", f"{_n(esf.ma_ser)} kN·m/m"],
                   ["m_b de serviço", f"{_n(esf.mb_ser)} kN·m/m"],
                   ["k da flecha", _n(esf.k_flecha, 3)]]
        _tabela(doc, ["Grandeza", "Valor"], linhas, larguras=[9.5, 5.5])

    _figura(doc, graficos.figura_momentos(res))


def _esforcos_mef_da_laje(doc: Document, res, rl) -> None:
    """ELU de uma laje em cruz pelos elementos finitos: o que foi adotado e
    o que as linhas de ruptura dariam."""
    mef = res.mef
    lm = mef.laje(rl.nome)
    esf = rl.esforcos
    _paragrafo(doc, "Regime elástico — elementos finitos de placa e "
                    "Wood-Armer (capítulo próprio):")
    linhas = [r for r in mef.comparativo if r[0] == rl.nome]
    _tabela(doc, ["Esforço", "Linhas de ruptura", "MEF elástico (WA)",
                  "Adotado", "MEF sem Mxy"],
            [[item, _n(ch), _n(ef), _n(ado), _n(sem)]
             for (_, item, ch, ef, ado, sem, _c) in linhas],
            larguras=[6.0, 2.6, 2.8, 2.2, 2.4])
    _paragrafo(doc, f"Carga de cálculo p_d = {_n(lm.p_d)} kN/m²; "
                    f"deslocamento máximo elástico sob essa carga "
                    f"{_n(lm.w_max * 1000.0, 2)} mm; máximo |Mxy| "
                    f"{_n(lm.mxy_max)} kN·m/m"
                    + (f"; redistribuição δ = {_n(esf.delta_mef)} dos "
                       f"negativos" if esf.delta_mef < 1.0 else
                       "; sem redistribuição dos negativos") + ".",
               italico=True, cor=CINZA)


def _mef(doc: Document, res, n: int) -> None:
    """Capítulo da análise por elementos finitos e Wood-Armer (R10)."""
    mef = res.mef
    pav = res.pavimento
    _titulo(doc, f"{n}. Análise por elementos finitos e Wood-Armer")
    _paragrafo(doc, (
        "O pavimento das lajes maciças foi analisado como uma malha única de "
        "placa de Reissner-Mindlin, com o elemento MITC4 de Bathe-Dvorkin "
        "(sem travamento por cisalhamento), em regime elástico linear, com "
        "a carga de cálculo (γg g + γq q) e as paredes como carga linear. A "
        "viga é um apoio rígido (w = 0 e rotação tangente nula); o engaste "
        "em elemento rígido anula também a rotação normal; onde duas lajes "
        "dividem uma viga com a borda comum declarada, os nós são "
        "contínuos, de modo que a rotação e o momento negativo coincidem "
        "dos dois lados sem compatibilização à parte. As bordas vizinhas "
        "se encaixam na linha de centro da viga e as demais ficam a "
        "a_i = min(t/2 ; 0,3 h) do vão livre (14.7.2.2)."))
    _paragrafo(doc, (
        "O dimensionamento segue Wood (1968) e Armer (1968), na forma de "
        "Parsekian (1996): M*x = Mx + K|Mxy| e M*y = My + |Mxy|/K em cada "
        "face, com um M* negativo anulado e o outro recalculado. O momento "
        "negativo de cada bordo vem do equilíbrio dos nós (reação de momento "
        "do apoio, ou a força interna do painel na viga contínua), que "
        "converge muito mais depressa que a extrapolação dos pontos de Gauss "
        "-- numa placa quadrada engastada, 1,4 % contra 23 % de erro com "
        "elemento de 25 cm. A armadura de cada direção é a do pico da laje, "
        "e a de cada bordo engastado, o máximo ao longo dele."))
    _tabela(doc, ["Dado", "Valor"], [
        ["Elementos; nós", f"{mef.n_elementos}; {mef.n_nos}"],
        ["Elemento (lado máximo)", f"{_n(mef.tamanho * 100.0, 0)} cm"],
        ["Ecs; ν", f"{_n(pav.concreto.Ecs, 0)} MPa; 0,20"],
        ["K de Wood-Armer", _n(mef.k, 2)],
        ["Redistribuição δ dos negativos", _n(mef.delta, 2)],
        ["Volvente resistido pelo concreto (Mxyc)",
         "descontado (NB-1)" if mef.mxyc else "não descontado"],
        ["x/d limite da flexão",
         _n(pav.concreto.x_sobre_d_limite_redistribuido(mef.delta), 3)],
        ["Zona de canto", f"{_n(mef.zona_canto, 2)} do menor vão"],
        ["Alternância da sobrecarga (xadrez)",
         ("ligada: envoltória dos positivos entre a carga cheia e os dois "
          "xadrezes" if mef.cores else "desligada: carga cheia")],
    ], larguras=[8.0, 7.0])

    _titulo(doc, f"{n}.1 Comparação com as linhas de ruptura", 2)
    _paragrafo(doc, (
        "Momentos de cálculo, kN·m/m. A análise elástica não embute a "
        "redistribuição que as linhas de ruptura trazem por construção "
        "(graus de engastamento i = 1,5), e por isso dá negativos e "
        "positivos maiores; a coluna 'Adotado' já traz a redistribuição δ "
        "escolhida. Nas lajes armadas em uma direção o resultado do MEF só "
        "informa -- o dimensionamento fica com o método das faixas."))
    _tabela(doc, ["Laje", "Esforço", "Linhas de ruptura", "MEF elástico",
                  "MEF adotado", "MEF sem Mxy", "Método"],
            [[nome, item, _n(ch), _n(ef), _n(ado), _n(sem),
              "MEF" if cruz else "faixas"]
             for (nome, item, ch, ef, ado, sem, cruz) in mef.comparativo],
            larguras=[1.4, 5.0, 2.2, 2.2, 2.2, 2.2, 1.8])

    _titulo(doc, f"{n}.2 Armadura superior de canto", 2)
    _paragrafo(doc, (
        "Nos cantos de laje apoiada o momento volvente é máximo e as linhas "
        "de ruptura, que supõem o canto livre para levantar, não o "
        "enxergam. O momento superior de Wood-Armer na zona de canto dá a "
        "armadura das duas direções (face superior); a inferior de canto "
        "fica coberta pela positiva do vão. Não é detalhada em barras: a "
        "massa do quantitativo é uma estimativa (As por metro nas duas "
        "direções, sobre a zona, sem ancoragem)."))
    cantos = [[lm.nome, f"bordos {c.bordos[0]} e {c.bordos[1]}",
               _n(c.zona), _n(c.m_topo), _n(c.m_base), _n(c.mxy),
               (f"{_n(c.As)} cm²/m x e y; {_n(c.massa, 1)} kg"
                if c.exige and not c.erro else
                ("não exige (os dois bordos engastados)" if not c.exige
                 else c.erro))]
              for lm in mef.lajes.values() for c in lm.cantos]
    _tabela(doc, ["Laje", "Canto", "Zona (m)", "M* superior", "M* inferior",
                  "máx |Mxy|", "Armadura superior"],
            cantos or [["—"] * 7],
            larguras=[1.3, 2.4, 1.6, 2.0, 2.0, 2.0, 4.7])

    _titulo(doc, f"{n}.3 Mapas", 2)
    for grandeza in (graficos.GRANDEZAS_MEF[3], graficos.GRANDEZAS_MEF[4],
                     graficos.GRANDEZAS_MEF[5], graficos.GRANDEZAS_MEF[6],
                     graficos.GRANDEZAS_MEF[2]):
        _figura(doc, graficos.figura_mef(res, grandeza), 14.0)
    _paragrafo(doc, (
        "Hipóteses e limites: regime elástico linear, sem redistribuição "
        "além do δ declarado; apoio rígido (sem pilares nem vigas "
        "deformáveis, hipótese a favor da segurança para Mxy); carga "
        + ("variável alternada em xadrez para os positivos e cheia para "
           "negativos e cantos" if mef.cores else
           "variável cheia em todas as lajes")
        + "; ELS pelas tabelas elásticas; o "
        "volvente resistido pelo concreto (Mxyc) é critério da NB-1 e a "
        "NBR 6118:2026 não o prescreve."), italico=True, cor=CINZA)


def _compatibilizacao(doc: Document, res, n: int) -> None:
    comp = res.compatibilizacao
    _titulo(doc, f"{n}. Compatibilização das bordas comuns")
    _paragrafo(doc,
               "Cada laje foi calculada isolada e engastada nas bordas de "
               "continuidade. Duas lajes vizinhas chegam à mesma borda com "
               "momentos diferentes, e sobre ela vai uma armadura só: o "
               "item 14.7.6.2 permite adotar o maior dos dois momentos, e é "
               "isso que o programa faz, com a menor das duas alturas úteis "
               "(§3.3).")
    if comp is None or not comp.bordas:
        _paragrafo(doc, "O pavimento não tem borda de continuidade.",
                   italico=True, cor=CINZA)
        return
    _paragrafo(doc, f"Critério adotado: {comp.criterio}"
                    + (f", em {comp.iteracoes} passagem(ns)"
                       if comp.criterio == "iterativa" else "") + ".")
    _tabela(doc, ["Borda comum", "m' lado A", "m' lado B", "m' adotado",
                  "d adotado (cm)", "Extensão p/ lado (cm)",
                  "Desequilíbrio"],
            [[b.rotulo, _n(b.m_a), _n(b.m_b), _n(b.m_adotado),
              _n(b.d_adotado, 1), _n(b.extensao, 0),
              "um lado só" if b.unilateral else
              f"{_n(b.desequilibrio)} kN·m/m"] for b in comp.bordas],
            larguras=[4.6, 1.8, 1.8, 1.9, 1.7, 2.0, 2.2])
    if any(b.unilateral for b in comp.bordas):
        _paragrafo(doc, (
            "\"Um lado só\": a vizinha cobre menos de 2/3 do bordo de uma "
            "das lajes, e esse bordo foi calculado apoiado (Souza & Cunha, "
            "§3.7.2); a negativa da borda é a do lado engastado, ancorada "
            "por cima da viga na outra laje."), italico=True, cor=CINZA)


def _cantos(doc: Document, res, n: int) -> None:
    """Armadura superior de canto das linhas de ruptura (R11)."""
    from ..core.cantos import fator_bifurcacao
    _titulo(doc, f"{n}. Armadura superior de canto")
    _paragrafo(doc, (
        "O mecanismo de charneiras supõe os cantos presos. Num canto de dois "
        "bordos apoiados, sem armadura superior, o canto levanta e a "
        "ruptura bifurca antes do vértice: a carga de ruptura cai pelo "
        "fator k = 1/[1 - 0,45(1 - γ/π)²] = "
        f"{_n(fator_bifurcacao(), 3)} no canto reto (Souza & Cunha, §5.9). "
        "O canto recebe armadura superior nas duas direções para "
        "m' = m·cot²(γ/2) = m (o maior positivo de cálculo da laje), numa "
        "zona quadrada a partir do vértice de lado igual ao maior entre "
        "ℓ = √(6m/p)·[1/sen(γ/2) - 1] = 0,414·√(6m/p) e 0,2 do menor vão "
        "(NB-1/78). d = d da camada superior - 1 cm (as duas direções se "
        "cruzam). A NBR 6118:2026 não trata do assunto; é armadura de boa "
        "prática. A massa é estimativa (zona × (zona + 10φ), nas duas "
        "direções)."))
    destaques = {i: VERMELHO for i, c in enumerate(res.cantos) if c.erro}
    _tabela(doc, ["Canto", "m (kN·m/m)", "p_d (kN/m²)", "0,414√(6m/p)",
                  "0,2 ℓmenor", "Zona (m)", "d (cm)", "Armadura",
                  "Massa (kg)"],
            [[c.rotulo, _n(c.m_vao), _n(c.p_d), _n(c.zona_charneira),
              _n(c.zona_nb1), _n(c.zona), _n(c.d, 1), c.armadura,
              _n(c.massa, 1)] for c in res.cantos],
            larguras=[2.6, 1.5, 1.5, 1.6, 1.5, 1.4, 1.2, 3.4, 1.3],
            destaques=destaques)


def _flexao(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Dimensionamento à flexão (ELU)")
    _paragrafo(doc,
               "Faixa de b = 100 cm, armadura simples, diagrama retangular "
               "do item 17.2.2. O limite de x/d é o do item 14.6.4.3 para "
               "solicitações obtidas em regime rígido-plástico: "
               f"{_n(res.pavimento.concreto.x_sobre_d_limite)}.")
    for rl in res.lajes:
        _titulo(doc, f"{n}.{res.lajes.index(rl) + 1} {rl.nome}", 2)
        destaques = {i: VERMELHO for i, f in enumerate(rl.flexoes) if f.erro}
        _tabela(doc,
                ["Seção", "m_d (kN·m/m)", "d (cm)", "x (cm)", "x/d",
                 "As,calc", "As,mín", "As adotada", "Governa"],
                [[f.rotulo, _n(f.md), _n(f.d, 1), _n(f.x, 3),
                  _n(f.x_sobre_d, 3), _n(f.As_calculada), _n(f.As_minima),
                  _n(f.As), f.governa] for f in rl.flexoes],
                destaques=destaques)
        for f in rl.flexoes:
            if f.erro:
                _paragrafo(doc, f"{f.rotulo}: {f.erro}", cor=VERMELHO)
    _figura(doc, graficos.figura_armaduras(res))


def _concentradas(doc: Document, res, n: int) -> None:
    """Cargas concentradas: efeito nos momentos e punção (R11)."""
    _titulo(doc, f"{n}. Cargas concentradas e punção")
    _paragrafo(doc, (
        "Laje em cruz: o momento de cálculo é o maior entre a carga "
        "espalhada na área da laje com o fator 1,2 do efeito localizado "
        "(Souza & Cunha, eq. 1.11) e o momento da carga uniforme somado ao "
        "do leque de charneiras em volta da carga, m = P_d(1 - 2c/3r)/2π, "
        "com c = √((dx + h)(dy + h)/π) e r a distância ao apoio mais "
        "próximo. A flecha usa a carga espalhada multiplicada pelo fator da "
        "série de Navier (placa apoiada). Laje em uma direção: faixa "
        "colaborante bw da Tabela A.1.5, com a carga na posição mais "
        "desfavorável do vão. Nas reações das vigas as cargas entram "
        "espalhadas na laje."))
    linhas = []
    for rl in res.lajes:
        for e in rl.esforcos.concentradas:
            if e.bw_vao > 0.0:
                efeito = (f"bw = {_n(e.bw_vao, 0)} cm (vão), "
                          f"{_n(e.bw_eng, 0)} cm (engaste); m = "
                          f"{_n(e.m_vao)} / m' = {_n(e.m_eng)}")
            else:
                efeito = (f"c = {_n(e.c)} m, r = {_n(e.r)} m, leque m = "
                          f"{_n(e.m_leque)}; flecha × {_n(e.k_flecha)}")
            linhas.append([rl.nome, e.descricao,
                           f"{_n(e.u)} / {_n(e.v)}",
                           f"{e.du:g} × {e.dv:g}", _n(e.P_k, 1),
                           _n(e.P_d, 1), efeito])
    _tabela(doc, ["Laje", "Carga", "u / v (m)", "Área (cm)", "P_k (kN)",
                  "P_d (kN)", "Efeito (kN·m/m)"], linhas,
            larguras=[1.2, 2.6, 1.8, 1.8, 1.5, 1.5, 5.6])

    _titulo(doc, f"{n}.1 Punção (19.5)", 2)
    _paragrafo(doc, (
        "Contorno C: τSd = F_Sd/(u0 d) <= τRd2 = 0,27 αv fcd, αv = 1 - "
        "fck/250. Contorno C' a 2d: τSd = F_Sd/(u1 d) <= τRd1 = 0,13 ke "
        "(100 ρ fck)^(1/3), ke = 1 + √(20/d) <= 2 (d em cm), ρ = √(ρx ρy) "
        "<= 0,02 da armadura inferior adotada, d = (dx + dy)/2. Carga "
        "centrada, sem desconto da carga distribuída dentro do contorno. "
        "Sem armadura de punção."))
    pun = [pu for rl in res.lajes for pu in rl.puncoes]
    destaques = {i: VERMELHO for i, pu in enumerate(pun) if not pu.atende}
    _tabela(doc, ["Carga", "P_d (kN)", "d (cm)", "u0 (cm)", "τSd/τRd2 C",
                  "u1 (cm)", "ρ", "τSd/τRd1 C'", "Veredito"],
            [[pu.rotulo, _n(pu.P_d, 1), _n(pu.d, 1), _n(pu.u0, 0),
              f"{_n(pu.tau_sd0)} / {_n(pu.tau_rd2)}", _n(pu.u1, 0),
              _n(pu.rho, 4), f"{_n(pu.tau_sd1)} / {_n(pu.tau_rd1)}",
              ("OK" if pu.atende else "NÃO OK")
              + ("" if pu.verificada else " (só C)")] for pu in pun],
            larguras=[3.2, 1.4, 1.1, 1.2, 2.2, 1.2, 1.3, 2.2, 1.6],
            destaques=destaques)
    for pu in pun:
        if pu.observacao:
            _paragrafo(doc, f"{pu.rotulo}: {pu.observacao}.",
                       cor=VERMELHO if not pu.atende else CINZA)


def _servico(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Estado limite de serviço — deformação")
    _paragrafo(doc,
               "Flecha imediata por f = k p a⁴/(Ecs Ieq), com o k tabelado "
               "por vinculação (§1.6); Ieq igual à inércia bruta enquanto o "
               "momento de serviço não passa o de fissuração, e 0,30 Ic "
               "depois que passa; flecha diferida por "
               f"(1 + alfa_f) = {_n(res.pavimento.config.fator_fluencia)}.")
    destaques = {i: VERMELHO for i, rl in enumerate(res.lajes)
                 if rl.els is not None and not rl.els.atende}
    _tabela(doc,
            ["Laje", "p_ser", "m_a", "m_r", "Estádio", "Ieq (cm⁴/m)", "k",
             "f(t=0)", "f(t=∞)", "f,adm", "Veredito"],
            [[rl.nome, _n(rl.els.p_ser), _n(rl.els.m_a), _n(rl.els.m_r),
              rl.els.estadio, _n(rl.els.Ieq, 0), _n(rl.els.k, 3),
              _n(rl.els.f_imediata, 3), _n(rl.els.f_diferida, 3),
              _n(rl.els.f_admissivel, 3),
              "OK" if rl.els.atende else "NÃO OK"]
             for rl in res.lajes if rl.els is not None],
            destaques=destaques)
    _figura(doc, graficos.figura_flechas(res), 15.0)

    predim = [rl for rl in res.lajes if rl.predimensionamento is not None]
    if predim:
        _titulo(doc, f"{n}.1 Pré-dimensionamento da espessura (§1.6)", 2)
        for rl in predim:
            pd = rl.predimensionamento
            _paragrafo(doc, f"{rl.nome}: {pd.mensagem}")
            _tabela(doc, ["h (cm)", "f(t=∞) (cm)", "f,adm (cm)", "Veredito"],
                    [[_n(h, 1), _n(f, 3), _n(lim, 3), v]
                     for h, f, lim, v in pd.tentativas],
                    larguras=[2.5, 3.5, 3.5, 5.0])


def _cortante(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Força cortante (19.4)")
    _paragrafo(doc,
               "A apostila §1.7 dispensa a verificação nas lajes de edifício "
               "corrente, por serem pouco carregadas. O programa verifica "
               "sempre, porque a dispensa deixa de valer na laje espessa de "
               "vão curto, na de garagem e na que recebe parede pesada.")
    linhas, destaques = [], {}
    i = 0
    for rl in res.lajes:
        for c in rl.cortantes:
            linhas.append([c.rotulo, _n(c.v_sd_apoio, 1), _n(c.v_sd, 1),
                           _n(c.As1), _n(c.rho_1, 4), _n(c.k, 3),
                           _n(c.v_rd1, 1), _n(c.aproveitamento * 100.0, 0)
                           + " %", "OK" if c.atende else "NÃO OK"])
            if not c.atende:
                destaques[i] = VERMELHO
            i += 1
    _tabela(doc, ["Bordo", "VSd apoio", "VSd (a d)", "As1", "rho_1", "k",
                  "VRd1", "Aproveit.", "Veredito"], linhas,
            destaques=destaques)
    if any(c.precisa_armadura for rl in res.lajes for c in rl.cortantes):
        _paragrafo(doc, "Bordos que pedem armadura transversal (19.4.2):")
        _tabela(doc, ["Bordo", "Asw (cm²/m por metro)", "fywd (MPa)",
                      "VRd2 (kN/m)"],
                [[c.rotulo, _n(c.asw_por_m2), _n(c.fywd, 0), _n(c.v_rd2, 1)]
                 for rl in res.lajes for c in rl.cortantes
                 if c.precisa_armadura])
    if linhas:
        _figura(doc, graficos.figura_cortante(res), 15.0)


def _detalhamento(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Detalhamento")
    _paragrafo(doc,
               "Bitola limitada a h/8 e espaçamento a min(2h ; 20 cm) na "
               "armadura principal e a 33 cm na de distribuição (20.1). A "
               "armadura positiva vai inteira ao apoio, sem escalonamento, "
               "prolongada 4 cm além do eixo teórico.")
    _tabela(doc,
            ["Pos.", "Laje", "Tipo", "Qtd.", "Ø (mm)", "c/ (cm)", "C (cm)",
             "As,nec", "As,ef", "Total (m)", "Massa (kg)"],
            [[f"N{p.numero}", p.laje, p.tipo, p.quantidade, _n(p.phi, 1),
              _n(p.espacamento, 0), _n(p.comprimento, 0),
              _n(p.As_necessaria), _n(p.As_efetiva),
              _n(p.comprimento_total, 1), _n(p.massa, 1)]
             for p in res.todas_posicoes])

    _paragrafo(doc, "Observações de detalhamento por posição:")
    linhas = [[f"N{p.numero}", p.rotulo + (
        " — " + "; ".join(p.observacoes) if p.observacoes else "")]
        for p in res.todas_posicoes]
    _tabela(doc, ["Pos.", "Critério"], linhas, larguras=[1.6, 13.4])

    ancoragens = [a for rl in res.lajes for a in rl.ancoragens]
    if ancoragens:
        _titulo(doc, f"{n}.1 Ancoragem no apoio de extremidade", 2)
        _paragrafo(doc, (
            "A positiva ancora no apoio o que o item 18.3.2.4 pede, aplicado "
            "à laje por analogia com os elementos lineares: no apoio "
            "extremo (bordo apoiado), a força F = (aℓ/d)·VSd com aℓ = d "
            "(17.4.2.2-c), com comprimento não menor que r + 5,5 Ø nem que "
            "60 mm (18.3.2.4.1, r pela Tabela 9.1); no apoio intermediário "
            "(bordo engastado), 10 Ø (18.3.2.4-c). ℓb não fica abaixo de "
            "25 Ø (9.4.2.4). Em todo apoio a positiva passa pelo menos 4 cm "
            "além do eixo teórico (20.1): ela entra t − c a partir da face, "
            "e o eixo está a t/2."))
        _tabela(doc, ["Onde", "Ø", "lb", "lb,nec", "Disponível", "Gancho",
                      "Observação"],
                [[a.rotulo, _n(a.phi, 1), _n(a.lb, 1), _n(a.lb_nec, 1),
                  _n(a.disponivel, 1),
                  f"{_n(a.ponta_gancho, 0)} cm" if a.com_gancho else "—",
                  a.observacao] for a in ancoragens],
                larguras=[3.4, 0.9, 1.1, 1.3, 1.5, 1.3, 5.5])

    if res.traspasses:
        vara = res.pavimento.config.comprimento_comercial_barra / 100.0
        _titulo(doc, f"{n}.2 Emenda por traspasse (9.5.2)", 2)
        _paragrafo(doc,
                   f"A barra de aço vem em vara de comprimento comercial "
                   f"({_n(vara, 0)} m); a posição mais comprida que isso é "
                   f"emendada por traspasse, com l0t = α0t · lb,nec e os "
                   f"pisos de 15 Ø e 20 cm. O α0t da Tabela 9.4 adotado "
                   f"supõe até 20 % das barras emendadas na mesma seção — "
                   f"escalonar as emendas na prancha é o que sustenta essa "
                   f"hipótese; se mais de 20 % ficarem na mesma seção, o "
                   f"traspasse tem de ser recalculado com um α0t maior. A "
                   f"emenda está cotada na planta de armação, na abscissa "
                   f"em que a vara termina.")
        _tabela(doc, ["Posição", "Ø (mm)", "C da barra (m)", "Vara (m)",
                      "Emendas por barra", "α0t", "l0t (cm)"],
                [[t.rotulo, _n(t.phi, 1), _n(t.comprimento_barra / 100.0, 2),
                  _n(t.comprimento_comercial / 100.0, 0),
                  t.numero_emendas, _n(t.alfa_0t, 1), _n(t.l0t, 0)]
                 for t in res.traspasses],
                larguras=[3.6, 1.6, 2.6, 1.8, 2.6, 1.4, 1.8])

    _titulo(doc, f"{n}.3 Plantas de armação", 2)
    _figura(doc, desenho.figura_armadura_positiva(res))
    _figura(doc, desenho.figura_armadura_negativa(res))
    _titulo(doc, f"{n}.4 Modelo 3D", 2)
    _paragrafo(doc,
              "Laje em concreto translúcido, armadura superior em vermelho "
              "e inferior em azul, com o gancho a 90° no comprimento real "
              "calculado. Esta é uma captura da mesma cena que a tela "
              "mostra na aba Modelo 3D -- lá ela gira e identifica cada "
              "posição ao passar o mouse.")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        caminho_3d = f.name
    try:
        vista3d.renderizar_png(res, caminho_3d, tamanho=(1400, 1000))
        _figura_arquivo(doc, caminho_3d)
    except Exception as exc:                                # noqa: BLE001
        _paragrafo(doc, f"(vista 3D indisponível nesta instalação: {exc})")
    finally:
        try:
            os.unlink(caminho_3d)
        except OSError:
            pass


def _reacoes(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Reações de apoio")
    _paragrafo(doc,
               "Repartição pelas charneiras plásticas do item 14.7.6.1, "
               "aproximadas por retas a 45° entre apoios do mesmo tipo, 60° "
               "a partir do engastado e 90° a partir do bordo vizinho ao "
               "livre. É o que as vigas do contorno recebem.")
    fontes = [(rl.nome, rl.reacoes) for rl in res.lajes]
    if res.especiais:
        _paragrafo(doc,
                   "Nas lajes treliçadas e nervuradas unidirecionais a "
                   "reação vem da envoltória da faixa (limite superior), "
                   "dividida entre as lajes que dividem o apoio; no painel "
                   "alveolar, de V = w L / 2; e na nervurada bidirecional "
                   "pela mesma partição geométrica da laje maciça, com a "
                   "carga que a grelha carrega. Só os dois bordos das "
                   "pontas do vão recebem carga nos sistemas "
                   "unidirecionais.", italico=True, cor=CINZA)
        for e in res.especiais:
            fontes += list(e.reacoes.items())
    for nome, reac in fontes:
        if reac is None:
            continue
        _paragrafo(doc, f"{nome} — carga total de "
                        f"{_n(reac.carga_total, 1)} kN:")
        _tabela(doc, ["Bordo", "Vínculo", "L (m)", "Parcela", "Hahn",
                      "Fonte", "v_g", "v_q", "v_k", "v_d"],
                [[str(r.bordo), r.vinculo, _n(r.comprimento), _n(r.fracao, 4),
                  _n(r.fracao_hahn, 4) if r.fracao_hahn is not None else "—",
                  r.fonte, _n(r.v_g), _n(r.v_q), _n(r.v_k), _n(r.v_d)]
                 for r in reac.bordos])

    _titulo(doc, f"{n}.1 Carga por trecho de viga", 2)
    _paragrafo(doc,
               "Nas bordas comuns as duas lajes descarregam no mesmo trecho, "
               "e a viga recebe a soma.")
    _tabela(doc, ["Trecho", "L (m)", "Contínua", "v_g", "v_q", "v_k", "v_d"],
            [[s.rotulo, _n(s.comprimento), "sim" if s.continuidade else "não",
              _n(s.v_g), _n(s.v_q), _n(s.v_k), _n(s.v_d)]
             for s in res.apoios], larguras=[5.4, 1.4, 1.6, 1.6, 1.6, 1.6,
                                             1.6])
    _figura(doc, graficos.figura_reacoes(res))


def _quantitativo(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Quantitativo")
    q = res.quantitativo
    _titulo(doc, f"{n}.1 Aço", 2)
    _tabela(doc, ["Ø (mm)", "Posições", "Comprimento (m)", "Emendas",
                  "Massa (kg)", "Massa das emendas (kg)"],
            [[_n(phi, 1), d["posicoes"], _n(d["comprimento"], 1),
              d.get("emendas", 0) or "—", _n(d["massa"], 1),
              _n(d.get("massa_emendas", 0.0), 1)]
             for phi, d in q["por_bitola"].items()]
            + [["Total", "", "", "", _n(q["massa_total"], 1),
                _n(q.get("massa_emendas", 0.0), 1)]],
            larguras=[2.0, 2.0, 3.2, 2.0, 3.0, 3.8])

    _titulo(doc, f"{n}.2 Forma", 2)
    _paragrafo(doc,
               "A forma inferior é o fundo da laje descontada a faixa que se "
               "apoia sobre a viga (t/2 em cada bordo com apoio), porque essa "
               "faixa fica sobre o fundo da viga, que tem forma própria. A "
               "forma de fechamento é a face lateral, de altura h, só nos "
               "bordos livres: onde o bordo apoia numa viga, a lateral dela "
               "já fecha a concretagem, e na borda comum com outra laje não "
               "há o que fechar.")
    formas = [rl.formas for rl in res.lajes if rl.formas is not None]
    _tabela(doc, ["Laje", "Retângulo (m²)", "Forma inferior (m²)",
                  "Bordos livres", "Forma de fechamento (m²)"],
            [[f.laje, _n(f.area_bruta, 2), _n(f.inferior, 2),
              ", ".join(str(b) for b in f.bordos_livres) or "—",
              _n(f.fechamento, 2)] for f in formas]
            + [["Total", "", _n(q.get("forma_inferior", 0.0), 2), "",
                _n(q.get("forma_fechamento", 0.0), 2)]],
            larguras=[2.2, 3.0, 3.4, 2.6, 3.8])

    _titulo(doc, f"{n}.3 Resumo", 2)
    _tabela(doc, ["Grandeza", "Valor"], [
        ["Área de laje", f"{_n(q['area_total'])} m²"],
        ["Volume de concreto", f"{_n(q['volume_concreto'], 2)} m³"],
        ["Forma inferior", f"{_n(q.get('forma_inferior', 0.0), 2)} m²"],
        ["Forma de fechamento",
         f"{_n(q.get('forma_fechamento', 0.0), 2)} m²"],
        ["Forma, total", f"{_n(q.get('forma_total', 0.0), 2)} m²"],
        ["Aço das barras", f"{_n(q['massa_total'], 1)} kg"],
        ["Aço do traspasse das emendas",
         f"{_n(q.get('massa_emendas', 0.0), 1)} kg"],
        ["Aço, com 10 % de perdas",
         f"{_n(q['massa_com_perdas'], 1)} kg"],
        *([["Aço superior de canto (estimativa, fora das barras)",
            f"{_n(q.get('massa_canto_charneiras', 0.0) + q.get('massa_canto_mef', 0.0), 1)} kg"]]
          if q.get('massa_canto_charneiras', 0.0)
          + q.get('massa_canto_mef', 0.0) > 0 else []),
        ["Taxa de aço", f"{_n(q['taxa_por_m2'])} kg/m² "
                        f"({_n(q['taxa_por_m3'], 1)} kg/m³)"],
        ["Peso próprio médio", f"{_n(q['peso_proprio_medio'])} kN/m²"],
    ], larguras=[7.0, 8.0])

    if q.get("especiais"):
        _titulo(doc, f"{n}.4 Lajes treliçadas, alveolares e nervuradas", 2)
        _tabela(doc, ["Sistema", "Tipo", "Perfil", "Área (m²)", "Aço (kg)",
                      "Concreto no local (m³)", "Pré-moldado (m³)"],
                [[e["nome"], e["tipo"], e["perfil"], _n(e["area"], 2),
                  _n(e["aco_kg"], 1), _n(e["concreto_m3"], 2),
                  _n(e["premoldado_m3"], 2) if e["premoldado_m3"] else "—"]
                 for e in q["especiais"]]
                + [["Total", "", "", _n(q["area_especiais"], 2),
                    _n(q["massa_especiais"], 1),
                    _n(q["concreto_especiais"], 2),
                    _n(q["premoldado_especiais"], 2)
                    if q["premoldado_especiais"] else "—"]],
                larguras=[2.6, 2.6, 2.0, 2.2, 2.0, 3.0, 2.6])
        _tabela(doc, ["Grandeza", "Valor"], [
            ["Aço do pavimento (maciças + especiais, sem perdas)",
             f"{_n(q['massa_geral'], 1)} kg"],
            ["Área do pavimento", f"{_n(q['area_geral'], 2)} m²"],
            ["Taxa de aço do pavimento",
             f"{_n(q['taxa_geral_por_m2'])} kg/m²"],
        ], larguras=[9.0, 6.0])


def _trelicada(doc: Document, res, n: int) -> None:
    """Capítulo das faixas de laje treliçada (``core/trelicada.py``): a
    nervura contínua, com negativas e balanços, calculada à parte da laje
    maciça e com os mesmos materiais e critérios do pavimento."""
    _faixas(doc, res, n, modelos_efetivos(res.pavimento, res.especiais,
                                          "trelicada"),
            "Laje treliçada", False)


def _nervurada_uni(doc: Document, res, n: int) -> None:
    """Capítulo das faixas de laje nervurada unidirecional moldada no local
    -- o motor da treliçada sem vigota nem treliça."""
    _faixas(doc, res, n, modelos_efetivos(res.pavimento, res.especiais,
                                          "nervurada_uni"),
            "Laje nervurada unidirecional", True)


def _faixas(doc: Document, res, n: int, faixas: list, titulo: str,
            moldada: bool) -> None:
    pav = res.pavimento
    _titulo(doc, f"{n}. {titulo}")
    if moldada:
        _paragrafo(doc, (
            "A laje nervurada unidirecional moldada no local é calculada "
            "pela nervura, na direção das nervuras, desprezadas a rigidez "
            "transversal e a torção (NBR 6118, 14.7.7). Esforços pela "
            "equação dos três momentos com alternância da carga variável; "
            "flexão positiva em seção T com a largura colaborante do item "
            "14.6.2.2 e negativa com a compressão na nervura ou no trecho "
            "maciço; cortante como laje (19.4.1) quando o intereixo permite "
            "(13.2.4.2) e como viga com estribos (17.4.2, modelo I) nos "
            "demais casos; mesa verificada de 65 a 110 cm de intereixo; "
            "ancoragem pelos itens 9.4.2 e 18.3.2.4.1; flecha pela rigidez "
            "equivalente de Branson ponderada (17.3.2.1.1) e fissuração "
            "pelo item 17.3.3.2. O roteiro é o mesmo da laje treliçada, sem "
            "a vigota e a treliça; a referência de método é Nepomuceno "
            "(UFOP) e Bocchi Jr. (USP)."))
    else:
        _paragrafo(doc, (
        "A laje treliçada unidirecional é calculada pela nervura, na "
        "direção das vigotas, desprezadas a rigidez transversal e a torção "
        "(NBR 6118, 14.7.7). Esforços pela equação dos três momentos com "
        "alternância da carga variável; flexão positiva em seção T com a "
        "largura colaborante do item 14.6.2.2 e negativa com a compressão "
        "na nervura ou no trecho maciço; cortante como laje (19.4.1) com as "
        "diagonais da treliça como recurso (19.4.2); ancoragem pelos itens "
        "9.4.2 e 18.3.2.4.1; flecha pela rigidez equivalente de Branson "
        "ponderada (17.3.2.1.1) e fissuração pelo item 17.3.3.2. Referência "
        "de roteiro: material técnico da Estude Engenharia (partes 1 a 3) e "
        "Manual Técnico de Lajes Treliçadas da ArcelorMittal."))
    for k, lt in enumerate(faixas, start=1):
        r = dimensionar_trelicada(lt, pav.concreto, pav.ambiente, pav.config)
        _titulo(doc, f"{n}.{k} Faixa {lt.nome}", 2)
        _origem_na_planta(doc, res, lt)
        g = r.geo
        _tabela(doc, ["Dado", "Valor"], [
            ["Enchimento" if moldada else "Treliça / enchimento",
             f"{lt.enchimento} {lt.largura_bloco:g} × "
             f"{lt.altura_enchimento:g} cm" if moldada else
             f"{lt.trelica} / {lt.enchimento} {lt.largura_bloco:g} × "
             f"{lt.altura_enchimento:g} cm"],
            ["Mesa; altura total h" if moldada else "Capa; altura total h",
             f"{lt.capa:g} cm; {g['h']:g} cm"],
            ["bw; intereixo", f"{g['bw']:g} cm; {g['intereixo']:g} cm"],
            ["Peso próprio por nervura", f"{_n(g['pp'], 3)} kN/m"],
            ["Vãos (cm)", " + ".join(f"{v.L:g}" for v in lt.vaos)],
            ["Balanços (cm)", f"esq. {lt.balanco_esq:g}; dir. "
                              f"{lt.balanco_dir:g}"],
            ["Redistribuição δ", _n(lt.delta, 2)],
            ["Cobrimento inferior", f"{g['c_inf']:g} cm"],
            ["Estádio I da flecha", "homogeneizado" if
             lt.inercia_homogeneizada else "seção bruta (17.3.2.1.1)"],
        ])
        _titulo(doc, f"{n}.{k}.1 Dimensionamento das seções", 3)
        linhas = []
        for rv in r.vaos:
            f = rv.flexao
            linhas.append([f"Vão {rv.indice + 1} (+)", _n(f.md, 2),
                           _n(f.b_comp, 1), _n(f.d, 2), _n(f.x_d, 3),
                           _n(f.As_nec, 2), _n(f.As_adot, 2),
                           _n(f.mrd, 2), f.armadura])
        for ra in r.apoios:
            if ra.md <= 1e-9:
                continue
            f = ra.flexao
            linhas.append([f"Apoio {ra.indice + 1} (−)", _n(ra.md, 2),
                           _n(f.b_comp, 1), _n(f.d, 2), _n(f.x_d, 3),
                           _n(f.As_nec, 2), _n(f.As_adot, 2), _n(f.mrd, 2),
                           f.armadura])
        _tabela(doc, ["Seção", "Md (kN·m)", "b (cm)", "d (cm)", "x/d",
                      "As nec.", "As adot.", "MRd", "Armadura"], linhas)
        _titulo(doc, f"{n}.{k}.2 Verificações", 3)
        _tabela(doc, ["Verificação", "Local", "Solicitante", "Resistente",
                      "Situação", "Item"], r.verificacoes,
                destaques={i: VERMELHO for i, l in enumerate(r.verificacoes)
                           if l[4] != "OK"})
        _titulo(doc, f"{n}.{k}.3 Esforços e desenhos", 3)
        _figura(doc, graficos_trelicada.figura_esforcos(r))
        _figura(doc, graficos_trelicada.figura_secao(r), 13.0)
        _figura(doc, graficos_trelicada.figura_elevacao(r))
        _titulo(doc, f"{n}.{k}.4 Posições e quantitativo", 3)
        _tabela(doc, ["Pos.", "Descrição", "Peças", "Ø", "Aço",
                      "Comp. (cm)", "Massa (kg)"],
                [[f"N{p.numero}", p.descricao, p.quantidade,
                  _n(p.phi, 1) if p.phi else "—", p.aco,
                  _n(p.comprimento, 0), _n(p.massa, 2)]
                 for p in r.posicoes])
        q = r.quantitativo
        _paragrafo(doc, (
            f"{q['n_nervuras']} nervuras em {_n(q['area'], 2)} m²; "
            f"{_n(q['concreto_L_m2'], 1)} L/m² de concreto; "
            f"{_n(q['aco_kg'], 1)} kg de aço ({_n(q['aco_kg_m2'], 2)} "
            f"kg/m²). Armadura de distribuição na capa: "
            f"Ø{r.distribuicao['phi']:g} c/{r.distribuicao['s']:.0f}."))
        for classe, texto in r.avisos:
            _paragrafo(doc, f"{'Erro' if classe == 'erro' else 'Obs.'}: "
                            f"{texto}",
                       cor=VERMELHO if classe == "erro" else CINZA)
        _avisos_da_atribuicao(doc, res, lt, r)


def _origem_na_planta(doc: Document, res, modelo) -> None:
    """Quando o modelo vem da planta (R09), diz de onde: lajes e perfil."""
    for e in res.especiais:
        if e.modelo is modelo:
            _paragrafo(doc, (
                f"Atribuída na planta às lajes {', '.join(e.lajes)} "
                f"(perfil {e.perfil}): vãos, largura dos apoios e cargas "
                f"vieram da planta; seção, armaduras e critérios, do "
                f"perfil."), italico=True, cor=CINZA)
            return


def _avisos_da_atribuicao(doc: Document, res, modelo, r) -> None:
    """Observações que só existem porque o sistema veio da planta -- faixa
    contínua, vizinhança, engaste de ponta --, sem repetir as do motor."""
    for e in res.especiais:
        if e.modelo is not modelo:
            continue
        do_motor = {t for _, t in r.avisos}
        for a in e.avisos:
            if a.texto in do_motor:
                continue
            _paragrafo(doc, f"{'Erro' if a.erro else 'Obs.'}: {a.texto}",
                       cor=VERMELHO if a.erro else CINZA)
        return


def _alveolar(doc: Document, res, n: int) -> None:
    """Capítulo dos painéis de laje alveolar protendida
    (``core/alveolar.py``): calculados à parte da laje maciça, com o
    concreto pré-moldado e a armadura ativa do próprio painel."""
    pav = res.pavimento
    cfg = pav.config
    _titulo(doc, f"{n}. Laje alveolar")
    _paragrafo(doc, (
        "O painel alveolar é protendido por pré-tração, biapoiado, com ou "
        "sem capa estrutural. Verificam-se: as perdas de protensão (NBR "
        "6118, 9.6.3 e Anexo A, ou percentuais informados); os comprimentos "
        "de transferência, de regularização e de ancoragem (9.4.5 e "
        "9.6.2.3); as tensões no ato da protensão e em serviço, por "
        "estágio, nas combinações do nível de protensão (13.4.2, Tabela "
        "13.4); a contraflecha e a flecha total com fluência; a flexão no "
        "ELU por compatibilidade de deformações, com o pré-alongamento e o "
        "diagrama bilinear do aço de protensão; e o cortante do painel "
        "(VRd1 = Vc + Vp e VRd2), nas seções simples e composta. O roteiro "
        "é o de Gramalho (2013, cap. 5) e Ferro (2020, cap. 2). Os limites "
        "que vêm da NBR 14861 são os que esses trabalhos transcrevem -- a "
        "norma não foi consultada diretamente."))
    for k, l0 in enumerate(modelos_efetivos(pav, res.especiais, "alveolar"),
                           start=1):
        r = resolver_alveolar(l0, cfg.gamma_g, cfg.gamma_q)
        l = r.laje
        s = r.secao
        _titulo(doc, f"{n}.{k} Painel {l.nome}", 2)
        _origem_na_planta(doc, res, l0)
        _tabela(doc, ["Dado", "Valor"], [
            ["Vão teórico; altura; capa",
             f"{_n(l.vao, 2)} m; {_n(l.sec.h, 1)} cm; {_n(l.capa, 1)} cm"],
            ["Seção", l.sec.origem],
            ["fck; fckj; fck da capa",
             f"{l.fck:g}; {l.fckj:g}; {l.fck_capa:g} MPa"],
            ["Armadura ativa", f"{l.n_cordoalhas} Ø{l.phi:g} {l.aco}"
             + (" (escolhida pelo programa)" if l.automatica else "")],
            ["CG da armadura; σpi", f"{_n(l.d_linha, 1)} cm; "
                                     f"{_n(l.sigma_pi, 0)} MPa"],
            ["Cargas g2; q", f"{_n(l.g2, 2)}; {_n(l.q, 2)} kN/m²"],
            ["Nível de protensão", str(l.nivel_protensao)],
            ["γg; γq", f"{_n(l.gamma_g, 2)}; {_n(l.gamma_q, 2)}"],
        ])
        _titulo(doc, f"{n}.{k}.1 Seções", 3)
        a, c = s["simples"], s["composta"]
        _tabela(doc, ["Seção", "A (cm²)", "CG a partir da base (cm)",
                      "I (cm⁴)", "Wi (cm³)", "Ws (cm³)"], [
            ["Simples (painel)", _n(a["A"] * 1e4, 1), _n(a["yi"] * 100, 2),
             _n(a["I"] * 1e8, 0), _n(a["Wi"] * 1e6, 0), _n(a["Ws"] * 1e6, 0)],
            ["Composta (painel + capa)", _n(c["A"] * 1e4, 1),
             _n(c["yi"] * 100, 2), _n(c["I"] * 1e8, 0),
             _n(c["Wi"] * 1e6, 0), _n(c["Ws"] * 1e6, 0)]])
        _titulo(doc, f"{n}.{k}.2 Protensão e perdas", 3)
        _tabela(doc, ["Item", "Valor", "Observação"],
                linhas_protensao(r, _n))
        _titulo(doc, f"{n}.{k}.3 Verificações", 3)
        _tabela(doc, ["Verificação", "Local", "Solicitante", "Resistente",
                      "Situação", "Item"], r.verificacoes,
                destaques={i: VERMELHO for i, x in enumerate(r.verificacoes)
                           if x[4] != "OK"})
        f = r.flechas
        _tabela(doc, ["Flecha", "Valor (cm)"], [
            ["Protensão no ato", _n(f["protensao_ini"] * 100, 2)],
            ["Peso do painel no ato", _n(f["peso_ini"] * 100, 2)],
            ["Líquida no ato", _n(f["inicial"] * 100, 2)],
            ["Total no tempo infinito", _n(f["total"] * 100, 2)]])
        _titulo(doc, f"{n}.{k}.4 Desenhos e gráficos", 3)
        _figura(doc, graficos_alveolar.figura_secao(r), 14.0)
        _figura(doc, graficos_alveolar.figura_elevacao(r))
        _figura(doc, graficos_alveolar.figura_tensoes(r))
        _figura(doc, graficos_alveolar.figura_esforcos(r))
        q = r.quantitativo
        _paragrafo(doc, (
            f"Painel de {_n(q['peso_painel'], 1)} kN "
            f"({_n(q['volume_painel'], 3)} m³ de concreto), "
            f"{_n(q['massa_aco'], 1)} kg de cordoalha."))
        for classe, texto in r.avisos:
            rot = {"erro": "Erro", "aviso": "Atenção"}.get(classe, "Obs.")
            _paragrafo(doc, f"{rot}: {texto}",
                       cor=VERMELHO if classe == "erro" else CINZA)
        _avisos_da_atribuicao(doc, res, l0, r)


def _nervurada_bi(doc: Document, res, n: int) -> None:
    """Capítulo dos painéis de laje nervurada bidirecional
    (``core/nervurada.py``)."""
    pav = res.pavimento
    _titulo(doc, f"{n}. Laje nervurada bidirecional")
    _paragrafo(doc, (
        "O painel nervurado bidirecional moldado no local é analisado por "
        "dois caminhos -- placa equivalente (NBR 6118, 14.7.7, com os "
        "coeficientes elásticos das tabelas de placa) e grelha de barras de "
        "seção T, com três graus de liberdade por nó, como recomenda Bocchi "
        "Jr. (1995) -- e se adota o maior (ou o escolhido). Nervuras: flexão "
        "positiva em seção T e negativa nos bordos engastados; cortante "
        "como laje ou como viga com estribos conforme o intereixo "
        "(13.2.4.2); flecha pela grelha com a rigidez de Branson de cada "
        "direção; fissuração pela 17.3.3.2. Mesa: flexão como painel de "
        "laje maciça apoiado nas nervuras (65 a 110 cm), cortante da mesa e "
        "cisalhamento da ligação mesa-nervura. Os bordos são vigas "
        "indeslocáveis; não há faixa maciça modelada nem pilares."))
    for k, l0 in enumerate(modelos_efetivos(pav, res.especiais,
                                            "nervurada_bi"), start=1):
        r = dimensionar_nervurada(l0, pav.concreto, pav.ambiente, pav.config)
        l = r.laje
        _titulo(doc, f"{n}.{k} Painel {l.nome}", 2)
        _origem_na_planta(doc, res, l0)
        _tabela(doc, ["Dado", "Valor"], [
            ["Vãos lx; ly", f"{_n(l.lx, 2)} m; {_n(l.ly, 2)} m"],
            ["Bordos (x=0, x=lx, y=0, y=ly)", "; ".join(l.bordos)],
            ["Intereixo (real) em x; em y",
             f"{_n(l.esp_x, 1)} cm; {_n(l.esp_y, 1)} cm "
             f"({l.nx} × {l.ny} painéis de grelha)"],
            ["bw; hf; h", f"{l.bw:g} cm; {l.hf:g} cm; {l.h:g} cm"],
            ["Enchimento", l.enchimento],
            ["Peso próprio", f"{_n(r.cargas['pp']['total'], 2)} kN/m²"],
            ["g2; q", f"{_n(l.g2, 2)}; {_n(l.q, 2)} kN/m²"],
            ["p_d (ELU)", f"{_n(r.cargas['p_d'], 2)} kN/m²"],
            ["Método dos esforços; kf; kt",
             f"{l.metodo}; {_n(l.kf, 2)}; {_n(l.kt, 2)}"],
        ])
        _titulo(doc, f"{n}.{k}.1 Dimensionamento das seções", 3)
        linhas = []
        for d, rd in r.dirs.items():
            f = rd.flexao
            linhas.append([f"Positiva // {d}", _n(rd.md_placa, 2),
                           _n(rd.md_grelha, 2), _n(rd.md, 2),
                           _n(f.As_nec, 2), _n(f.As_adot, 2), _n(f.mrd, 2),
                           f.armadura])
            for kk, sn in rd.neg.items():
                linhas.append([f"Negativa bordo {kk + 1}", "", "",
                               _n(rd.md_neg[kk], 2), _n(sn.As_nec, 2),
                               _n(sn.As_adot, 2), _n(sn.mrd, 2),
                               sn.armadura])
        _tabela(doc, ["Seção", "Md placa", "Md grelha", "Md adotado",
                      "As nec.", "As adot.", "MRd", "Armadura"], linhas)
        _titulo(doc, f"{n}.{k}.2 Verificações", 3)
        _tabela(doc, ["Verificação", "Local", "Solicitante", "Resistente",
                      "Situação", "Item"], r.verificacoes,
                destaques={i: VERMELHO for i, x in enumerate(r.verificacoes)
                           if x[4] != "OK"})
        m = r.mesa
        _paragrafo(doc, (
            f"Mesa: m = {_n(m['m'], 2)} kN·m/m no painel de "
            f"{_n(l.esp_x, 0)} × {_n(l.esp_y, 0)} cm; malha Ø{m['phi']:g} "
            f"c/{m['s']:.0f} ({_n(m['As_adot'], 2)} cm²/m) nas duas "
            f"direções."))
        _titulo(doc, f"{n}.{k}.3 Desenhos", 3)
        _figura(doc, graficos_nervurada.figura_planta(r), 15.0)
        _figura(doc, graficos_nervurada.figura_secao(r), 14.0)
        _figura(doc, graficos_nervurada.figura_diagramas(r))
        _titulo(doc, f"{n}.{k}.4 Posições e quantitativo", 3)
        _tabela(doc, ["Pos.", "Descrição", "Peças", "Ø", "Aço",
                      "Comp. (cm)", "Massa (kg)"],
                [[f"N{p.numero}", p.descricao, p.quantidade,
                  _n(p.phi, 1) if p.phi else "—", p.aco,
                  _n(p.comprimento, 0), _n(p.massa, 2)]
                 for p in r.posicoes])
        q = r.quantitativo
        _paragrafo(doc, (
            f"{_n(q['area'], 2)} m²; {_n(q['concreto_L_m2'], 1)} L/m² de "
            f"concreto; {_n(q['aco_kg'], 1)} kg de aço "
            f"({_n(q['aco_kg_m2'], 2)} kg/m²)."))
        for classe, texto in r.avisos:
            _paragrafo(doc, f"{'Erro' if classe == 'erro' else 'Obs.'}: "
                            f"{texto}",
                       cor=VERMELHO if classe == "erro" else CINZA)
        _avisos_da_atribuicao(doc, res, l0, r)


def _roteiro(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Roteiro de verificações")
    linhas = auditoria.roteiro(res)
    total, reprovadas, fora = auditoria.resumo(linhas)
    _paragrafo(doc, f"{total} verificações normativas; {reprovadas} não "
                    f"fecharam.", cor=VERMELHO if reprovadas else VERDE)
    if fora:
        _paragrafo(doc,
                   f"Além delas, {fora} armadura(s) ficaram fora da faixa de "
                   f"bitola desejada. Não é reprovação: a faixa é preferência "
                   f"do projetista, e a laje está verificada em tudo o que a "
                   f"norma exige.", italico=True, cor=CINZA)
    # a preferência não atendida sai em cinza, e não em vermelho: ela não
    # reprova a laje
    destaques = {i: (CINZA if v.preferencia else VERMELHO)
                 for i, v in enumerate(linhas) if not v.atende}
    _tabela(doc, ["Item", "Verificação", "Onde", "Valor", "Limite",
                  "Veredito"],
            [[v.item, v.descricao, v.onde, v.valor, v.limite, v.veredito]
             for v in linhas], destaques=destaques,
            larguras=[1.6, 5.6, 1.8, 2.4, 2.6, 1.4])


def _pendencias(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Pendências e observações")
    erros, obs = avisos_mod.separar(res.todos_avisos)
    _paragrafo(doc, avisos_mod.resumo(res.todos_avisos))
    if erros:
        _titulo(doc, f"{n}.1 Erros de verificação", 2)
        for a in erros:
            _paragrafo(doc, f"• {a.texto}", cor=VERMELHO)
    if obs:
        _titulo(doc, f"{n}.{2 if erros else 1} Observações construtivas", 2)
        for a in obs:
            _paragrafo(doc, f"• {a.texto}", cor=CINZA)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def gerar(res, caminho: str) -> str:
    """Gera a memória de cálculo em .docx e devolve o caminho do arquivo."""
    doc = Document()
    _configurar(doc)
    _capa(doc, res)
    doc.add_page_break()
    n = 1
    _metodologia(doc, res, n); n += 1
    _dados(doc, res, n); n += 1
    _classificacao(doc, res, n); n += 1
    _esforcos(doc, res, n); n += 1
    _compatibilizacao(doc, res, n); n += 1
    if res.cantos:
        _cantos(doc, res, n); n += 1
    if res.mef is not None:
        _mef(doc, res, n); n += 1
    _flexao(doc, res, n); n += 1
    _servico(doc, res, n); n += 1
    if any(rl.cortantes for rl in res.lajes):
        _cortante(doc, res, n); n += 1
    if any(rl.laje.cargas_concentradas for rl in res.lajes):
        _concentradas(doc, res, n); n += 1
    _detalhamento(doc, res, n); n += 1
    _reacoes(doc, res, n); n += 1
    _quantitativo(doc, res, n); n += 1
    pav = res.pavimento
    if modelos_efetivos(pav, res.especiais, "trelicada"):
        _trelicada(doc, res, n); n += 1
    if modelos_efetivos(pav, res.especiais, "alveolar"):
        _alveolar(doc, res, n); n += 1
    if modelos_efetivos(pav, res.especiais, "nervurada_uni"):
        _nervurada_uni(doc, res, n); n += 1
    if modelos_efetivos(pav, res.especiais, "nervurada_bi"):
        _nervurada_bi(doc, res, n); n += 1
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
