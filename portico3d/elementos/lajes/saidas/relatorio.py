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
from ..core.esforcos import BORDOS_DA_DIRECAO
from . import auditoria, desenho, graficos

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
    r = p.add_run("Lajes maciças de concreto armado — ABNT NBR 6118")
    r.font.size = Pt(12)
    r.font.color.rgb = CINZA

    doc.add_paragraph()
    _tabela(doc, ["Item", "Valor"], [
        ["Pavimento", pav.nome],
        ["Projeto", pav.projeto or "—"],
        ["Lajes", f"{len(res.lajes)}"],
        ["Área total", f"{_n(res.area_total)} m²"],
        ["Bordas comuns", f"{len(pav.continuidades)}"],
        ["Concreto", f"{pav.concreto.classe} "
                     f"(agregado {pav.concreto.agregado})"],
        ["Aço", pav.aco.categoria],
        ["Agressividade ambiental",
         f"CAA {pav.ambiente.caa} — {pav.ambiente.descricao}"],
        ["Cobrimento inferior / superior",
         f"{_n(pav.ambiente.cobrimento_nominal, 1)} / "
         f"{_n(pav.ambiente.cobrimento_superior(pav.config.bitola_minima_negativa), 1)} cm"],
        ["Aço total", f"{_n(res.quantitativo.get('massa_total', 0.0), 1)} kg "
                      f"({_n(res.quantitativo.get('taxa_por_m2', 0.0))} "
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

    for rl in res.lajes:
        esf = rl.esforcos
        cls = esf.classificacao
        _titulo(doc, f"{n}.{res.lajes.index(rl) + 1} {rl.nome}", 2)

        if cls.em_cruz:
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

        if esf.m_neg:
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
              f"{_n(b.desequilibrio)} kN·m/m"] for b in comp.bordas],
            larguras=[4.6, 1.8, 1.8, 1.9, 1.7, 2.0, 2.2])


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
    _titulo(doc, f"{n}.4 Cortes", 2)
    _figura(doc, desenho.figura_cortes(res))


def _reacoes(doc: Document, res, n: int) -> None:
    _titulo(doc, f"{n}. Reações de apoio")
    _paragrafo(doc,
               "Repartição pelas charneiras plásticas do item 14.7.6.1, "
               "aproximadas por retas a 45° entre apoios do mesmo tipo, 60° "
               "a partir do engastado e 90° a partir do bordo vizinho ao "
               "livre. É o que as vigas do contorno recebem.")
    for rl in res.lajes:
        if rl.reacoes is None:
            continue
        _paragrafo(doc, f"{rl.nome} — carga total de "
                        f"{_n(rl.reacoes.carga_total, 1)} kN:")
        _tabela(doc, ["Bordo", "Vínculo", "L (m)", "Parcela", "Hahn",
                      "Fonte", "v_g", "v_q", "v_k", "v_d"],
                [[str(r.bordo), r.vinculo, _n(r.comprimento), _n(r.fracao, 4),
                  _n(r.fracao_hahn, 4) if r.fracao_hahn is not None else "—",
                  r.fonte, _n(r.v_g), _n(r.v_q), _n(r.v_k), _n(r.v_d)]
                 for r in rl.reacoes.bordos])

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
        ["Taxa de aço", f"{_n(q['taxa_por_m2'])} kg/m² "
                        f"({_n(q['taxa_por_m3'], 1)} kg/m³)"],
        ["Peso próprio médio", f"{_n(q['peso_proprio_medio'])} kN/m²"],
    ], larguras=[7.0, 8.0])


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
    _flexao(doc, res, n); n += 1
    _servico(doc, res, n); n += 1
    if any(rl.cortantes for rl in res.lajes):
        _cortante(doc, res, n); n += 1
    _detalhamento(doc, res, n); n += 1
    _reacoes(doc, res, n); n += 1
    _quantitativo(doc, res, n); n += 1
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
