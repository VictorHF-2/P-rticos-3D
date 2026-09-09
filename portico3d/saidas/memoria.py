# -*- coding: utf-8 -*-
"""
memoria.py
A memória de cálculo do edifício, em Word.

Um documento só, com o que cada motor de elemento produziu **mais** o que só
existe no nível do edifício: os esforços do pórtico, a estabilidade global, as
reações e o confronto entre o dimensionamento e a envoltória.

## O que é daqui e o que é emprestado

O passo a passo de cada peça — a flexão barra a barra, a fissuração, a
ancoragem — já está escrito nos relatórios dos motores de elemento, e
reescrevê-lo aqui seria duplicar código que pode divergir. O que este
documento traz de cada peça é a **síntese verificável**: a solicitação, a
armadura adotada, o detalhamento com bitolas, comprimentos, ancoragem,
traspasse e esperas, e o veredito. Quem quiser o desenvolvimento algébrico de
uma viga gera o relatório dela pelo próprio programa de Vigas.

O que é daqui, e não existe em lugar nenhum senão aqui, são os capítulos de
esforços, estabilidade, reações e confronto.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

AZUL = None          # preenchido no primeiro uso, para não importar cedo


def _rgb():
    from docx.shared import RGBColor
    return RGBColor(0x1F, 0x38, 0x64)


def _configurar(doc) -> None:
    """Fonte Aptos e títulos em azul, como nos demais programas da pasta."""
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    estilo = doc.styles["Normal"]
    estilo.font.name = "Aptos"
    estilo.font.size = Pt(10)
    for nivel, corpo in ((1, 14), (2, 12), (3, 11)):
        h = doc.styles[f"Heading {nivel}"]
        h.font.name = "Aptos"
        h.font.size = Pt(corpo)
        h.font.color.rgb = _rgb()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.0)


def _p(doc, texto: str, italico: bool = False):
    p = doc.add_paragraph()
    r = p.add_run(texto)
    r.italic = italico
    return p


def _tabela(doc, cabecalho: list[str], linhas: list[list]) -> None:
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    if not linhas:
        _p(doc, "— nada a listar —", italico=True)
        return
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
                r.font.size = Pt(8)
    for linha in linhas:
        cels = t.add_row().cells
        for i, valor in enumerate(linha):
            cels[i].text = "-" if valor is None else str(valor)
            for p in cels[i].paragraphs:
                p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if i == 0
                               else WD_ALIGN_PARAGRAPH.CENTER)
                for r in p.runs:
                    r.font.size = Pt(8)
    doc.add_paragraph()


def _n(valor, casas: int = 2) -> str:
    if valor is None:
        return "-"
    try:
        return f"{float(valor):.{casas}f}"
    except (TypeError, ValueError):
        return str(valor)


# ---------------------------------------------------------------------------
# Capítulos
# ---------------------------------------------------------------------------

def _capa(doc, projeto) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("MEMÓRIA DE CÁLCULO ESTRUTURAL")
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = _rgb()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(projeto.modelo.nome or "pórtico espacial")
    r.font.size = Pt(14)

    doc.add_paragraph()
    _tabela(doc, ["", ""], [
        ["Análise", "método da rigidez direta, pórtico espacial de 12 "
                    "graus de liberdade por barra"],
        ["Norma", "ABNT NBR 6118 (concreto) e NBR 6123 (vento)"],
        ["Nós", len(projeto.modelo.nos)],
        ["Barras", len(projeto.modelo.barras)],
        ["Painéis de laje", len(projeto.modelo.lajes)],
        ["Combinações últimas", len(projeto.combinacoes)],
        ["Data", date.today().strftime("%d/%m/%Y")],
        ["Veredito", "PROJETO FECHA" if projeto.fecha
                     else "HÁ ELEMENTOS REPROVADOS — ver o capítulo 8"],
    ])
    doc.add_page_break()


def _metodologia(doc, projeto) -> None:
    doc.add_heading("1  Metodologia", level=1)
    _p(doc, "A estrutura é resolvida como pórtico espacial pelo método da "
            "rigidez direta. Cada barra tem dois nós e doze graus de "
            "liberdade, na formulação de Euler-Bernoulli ou de Timoshenko "
            "conforme a seção declare área de cisalhamento. As cargas "
            "distribuídas viram forças de engastamento perfeito por "
            "quadratura das funções de forma, e não por fórmula fechada, de "
            "modo que carga parcial e trapezoidal entrem exatas.")
    _p(doc, "As lajes são painéis: a carga de cada painel é repartida às "
            "vigas de contorno pelas charneiras plásticas, com a inclinação "
            "definida pelo vínculo de cada bordo. O peso próprio das barras é "
            "gerado a partir da seção e do peso específico do material.")

    doc.add_heading("1.1  Combinações", level=2)
    _p(doc, "As combinações últimas normais seguem a NBR 6118, com uma ação "
            "variável principal por vez e as demais reduzidas por ψ₀. O "
            "desaprumo global entra como ação lateral equivalente. A "
            "envoltória guarda, em cada estação de cada barra, o extremo de "
            "cada esforço **e os demais esforços que o acompanham** — é esse "
            "trio simultâneo (N, My, Mz) que o dimensionamento à flexão "
            "composta oblíqua exige, e não os máximos isolados de cada um.")

    doc.add_heading("1.2  Dimensionamento", level=2)
    _p(doc, "Cada tipo de peça é dimensionado pelo programa de elemento "
            "correspondente — Pilares, Vigas e Lajes —, cujo código é copiado "
            "para dentro deste programa e conferido byte a byte contra a "
            "origem. Nenhuma verificação normativa é reimplementada aqui.")
    _p(doc, "As vigas recebem do pórtico a rigidez à rotação dos pilares nos "
            "apoios (mola, e não rótula) e o peso próprio já computado. Como "
            "o motor de vigas combina apenas ações permanentes e variáveis "
            "verticais, o efeito das ações laterais é verificado à parte: a "
            "armadura detalhada é confrontada com a envoltória do pórtico "
            "ponto a ponto, em área de aço. É o capítulo 8.")


def _modelo(doc, projeto) -> None:
    m = projeto.modelo
    doc.add_heading("2  O modelo", level=1)

    doc.add_heading("2.1  Materiais", level=2)
    _tabela(doc, ["Material", "Tipo", "fck (MPa)", "E (MPa)", "ν",
                  "γ (kN/m³)"],
            [[n, mat.tipo, _n(mat.fck, 1) if mat.fck else "-",
              _n(mat.E / 1000.0, 0), _n(mat.poisson, 2),
              _n(mat.peso_especifico, 1)]
             for n, mat in m.materiais.items()])

    doc.add_heading("2.2  Seções", level=2)
    _tabela(doc, ["Seção", "Tipo", "b (m)", "h (m)", "A (m²)", "Iy (m⁴)",
                  "Iz (m⁴)", "J (m⁴)"],
            [[n, s.tipo, _n(s.b, 3), _n(s.h, 3), _n(s.A, 4), _n(s.Iy, 6),
              _n(s.Iz, 6), _n(s.J, 6)] for n, s in m.secoes.items()])

    doc.add_heading("2.3  Casos de carga", level=2)
    _tabela(doc, ["Caso", "Natureza", "Categoria", "Grupo"],
            [[n, c.natureza, c.categoria or "-", c.grupo or "-"]
             for n, c in m.casos.items()])

    doc.add_heading("2.4  Combinações últimas", level=2)
    _tabela(doc, ["Combinação", "Fatores"],
            [[c.nome, "  ".join(f"{k}×{v:g}" for k, v in c.fatores.items())]
             for c in projeto.combinacoes[:40]])
    if len(projeto.combinacoes) > 40:
        _p(doc, f"… e mais {len(projeto.combinacoes) - 40} combinações.",
           italico=True)


def _esforcos(doc, projeto) -> None:
    doc.add_heading("3  Esforços", level=1)
    _p(doc, "Envoltória das combinações últimas: o extremo de cada esforço "
            "ao longo de cada barra, com a combinação que o produziu. Só é "
            "listada a barra com solicitação relevante.")
    if not projeto.envoltorias:
        _p(doc, "A envoltória não pôde ser montada — ver os avisos.",
           italico=True)
        return

    linhas = []
    for nome, env in projeto.envoltorias.items():
        n = env.extremo("N", "min")
        my_min, my_max = env.extremo("My", "min"), env.extremo("My", "max")
        vz = env.extremo("Vz", "max")
        linhas.append([nome, _n(n.valor, 1), _n(my_min.valor, 1),
                       _n(my_max.valor, 1), _n(vz.valor, 1),
                       my_min.combinacao])
    linhas.sort(key=lambda r: -abs(float(r[2])))
    _tabela(doc, ["Barra", "N mín (kN)", "My mín", "My máx (kN·m)",
                  "Vz máx (kN)", "combinação de My mín"], linhas[:60])
    if len(linhas) > 60:
        _p(doc, f"… e mais {len(linhas) - 60} barras.", italico=True)


def _estabilidade(doc, projeto) -> None:
    doc.add_heading("4  Estabilidade global", level=1)
    if not projeto.estabilidade:
        _p(doc, "Sem ação lateral no modelo, não há γz a medir.",
           italico=True)
        return
    _p(doc, "γz é a razão entre o momento de tombamento de segunda ordem e o "
            "de primeira. Até 1,10 a estrutura é de nós fixos e a segunda "
            "ordem global pode ser dispensada; acima disso ela tem de ser "
            "considerada, e até 1,30 a majoração por 0,95·γz é admitida.")
    pior = max(projeto.estabilidade, key=lambda g: g.valor)
    _tabela(doc, ["Combinação", "direção", "M1 (kN·m)", "ΔM (kN·m)", "γz",
                  "classificação"],
            [[g.combinacao, f"({g.direcao[0]:g}, {g.direcao[1]:g})",
              _n(g.m1_tot_d, 1), _n(g.delta_m_tot_d, 1), _n(g.valor, 3),
              "nós fixos" if g.nos_fixos else "nós móveis"]
             for g in sorted(projeto.estabilidade,
                             key=lambda g: -g.valor)[:20]])
    _p(doc, f"O maior γz é {pior.valor:.3f}, em {pior.combinacao}: estrutura "
            f"de {'nós fixos' if pior.nos_fixos else 'nós móveis'}.")


def _reacoes(doc, projeto) -> None:
    doc.add_heading("5  Reações de apoio", level=1)
    _p(doc, "É a entrada da fundação. Os valores são da combinação de maior "
            "carga vertical.")
    if not projeto.resultados:
        _p(doc, "Sem resultados.", italico=True)
        return
    escolhido = None
    maior = -1.0
    for nome, r in projeto.resultados.items():
        try:
            total = sum(abs(float(v[2])) for v in r.reacoes().values())
        except Exception:                                # noqa: BLE001
            continue
        if total > maior:
            maior, escolhido = total, (nome, r)
    if escolhido is None:
        _p(doc, "Não foi possível extrair as reações.", italico=True)
        return
    nome, r = escolhido
    _p(doc, f"Combinação {nome}.")
    linhas = [[no] + [_n(v, 1) for v in valores]
              for no, valores in sorted(r.reacoes().items())]
    _tabela(doc, ["Nó", "Fx (kN)", "Fy (kN)", "Fz (kN)", "Mx (kN·m)",
                  "My", "Mz"], linhas)


def _pilares(doc, projeto) -> None:
    doc.add_heading("6  Pilares", level=1)
    if not projeto.pilares:
        _p(doc, "Nenhum lance verificado.", italico=True)
        return
    por_barra: dict[str, list] = {}
    for v in projeto.pilares:
        por_barra.setdefault(v.barra, []).append(v)

    linhas = []
    for barra, lista in sorted(por_barra.items()):
        bons = [v for v in lista if v.aprovado]
        melhor = max(bons, key=lambda v: v.esforcos.Nd, default=None)
        alvo = melhor or lista[0]
        arranjo = getattr(alvo.resultado, "arranjo", None)
        estribos = getattr(alvo.resultado, "estribos", None)
        ancoragem = getattr(alvo.resultado, "ancoragem", None)
        linhas.append([
            barra,
            _n(alvo.esforcos.Nd, 1),
            f"{arranjo.n_barras}Ø{arranjo.phi:g}" if arranjo else "-",
            f"{arranjo.As:.2f}" if arranjo else "-",
            estribos.descricao() if estribos else "-",
            _n(getattr(ancoragem, "lb_nec", None), 0),
            _n(getattr(ancoragem, "l0c", None), 0),
            "aprovado" if bons else "REPROVADO",
        ])
    _tabela(doc, ["Lance", "Nd (kN)", "armadura", "As (cm²)", "estribos",
                  "lb,nec (cm)", "espera l0c (cm)", "veredito"], linhas)
    _p(doc, "O comprimento de espera l0c é a emenda por traspasse de barras "
            "comprimidas do item 9.5.2.3, medida da face superior da laje: é "
            "o arranque que sobe para o lance seguinte.")

    reprovados = [b for b, l in por_barra.items()
                  if not any(v.aprovado for v in l)]
    if reprovados:
        doc.add_heading("6.1  Lances reprovados", level=2)
        _tabela(doc, ["Lance", "motivo"],
                [[b, (por_barra[b][0].motivos or ["sem motivo declarado"])[0]]
                 for b in reprovados])


def _vigas(doc, projeto) -> None:
    doc.add_heading("7  Vigas", level=1)
    if not projeto.vigas:
        _p(doc, "Nenhuma viga contínua com dois ou mais apoios de pilar.",
           italico=True)
        return
    _tabela(doc, ["Viga", "vãos (m)", "seção", "aço (kg)", "taxa (kg/m³)",
                  "veredito"],
            [[v.nome, " + ".join(f"{x:.2f}" for x in v.vaos),
              (f"{v.viga.tramos[0].secao.bw:.0f}×"
               f"{v.viga.tramos[0].secao.h:.0f}" if v.passou else "-"),
              _n(v.resultado.quantitativo.get("massa_total"), 1)
              if v.passou else "-",
              _n(v.resultado.quantitativo.get("taxa"), 1) if v.passou else "-",
              "aprovada" if v.aprovado else "REPROVADA"]
             for v in projeto.vigas])

    doc.add_heading("7.1  Detalhamento", level=2)
    _p(doc, "Posições longitudinais de cada viga, com bitola, quantidade, "
            "comprimento total já com os ganchos e o traspasse consumido em "
            "cada emenda.")
    for v in projeto.vigas:
        if not v.passou:
            continue
        doc.add_heading(f"7.1.{projeto.vigas.index(v) + 1}  {v.nome}",
                        level=3)
        linhas = []
        for p in v.resultado.posicoes:
            if p.tipo not in ("longitudinal", "porta", "estribo", "pele"):
                continue
            linhas.append([
                f"N{p.numero}", p.tipo, p.face, f"{p.n}Ø{p.phi:g}",
                _n(p.comprimento, 0),
                f"{p.x_ini:.2f}–{p.x_fim:.2f}",
                _n(p.s, 1) if p.s else "-",
                _n(p.traspasse, 0) if p.traspasse else "-",
            ])
        _tabela(doc, ["pos.", "tipo", "face", "bitola", "C (cm)",
                      "trecho (m)", "s (cm)", "traspasse (cm)"], linhas)


def _confronto(doc, projeto) -> None:
    doc.add_heading("8  Confronto com a envoltória do pórtico", level=1)
    _p(doc, "O motor de vigas combina apenas ações permanentes e variáveis "
            "verticais: ele não conhece vento nem desaprumo. Este capítulo "
            "confere, ponto a ponto, se a armadura detalhada cobre o que a "
            "envoltória do pórtico exige — em área de aço na face tracionada, "
            "que é o que se pode conferir em obra.")
    com_conferencia = [v for v in projeto.vigas if v.portico is not None]
    if not com_conferencia:
        _p(doc, "Nenhuma viga foi confrontada — a envoltória não estava "
                "disponível no momento do dimensionamento.", italico=True)
        return
    _tabela(doc, ["Viga", "x crítico (m)", "face", "M do pórtico (kN·m)",
                  "M do motor", "As exigido (cm²)", "As detalhado",
                  "razão", "veredito"],
            [[v.nome, _n(c.x_critico), c.face_critica or "-",
              _n(c.momento_portico, 1), _n(c.momento_motor, 1),
              _n(max(c.As_exigido_sup, c.As_exigido_inf)),
              _n(max(c.As_obtido_sup, c.As_obtido_inf)),
              "∞" if c.razao == float("inf") else _n(c.razao),
              "cobre" if c.cobre else "NÃO COBRE"]
             for v, c in ((v, v.portico) for v in com_conferencia)])
    faltando = [v for v in com_conferencia if not v.portico.cobre]
    if faltando:
        _p(doc, f"{len(faltando)} viga(s) não cobrem a envoltória do pórtico. "
                "A armadura detalhada é insuficiente para as combinações que "
                "incluem ação lateral, e o projeto não pode ser emitido "
                "assim.")


def _lajes(doc, projeto) -> None:
    doc.add_heading("9  Lajes", level=1)
    if not projeto.lajes:
        _p(doc, "Nenhum pavimento de laje.", italico=True)
        return
    for v in projeto.lajes:
        doc.add_heading(f"9.{projeto.lajes.index(v) + 1}  Cota "
                        f"{v.cota:g} m", level=2)
        if not v.passou:
            _p(doc, f"Não dimensionado: {v.erro}", italico=True)
            continue
        _tabela(doc, ["Laje", "vãos (m)", "h (cm)", "As,a (cm²/m)",
                      "As,b (cm²/m)"],
                [[r.nome, f"{la.a:.2f} × {la.b:.2f}", _n(la.h, 0),
                  _n(getattr(r, "As_a", None)), _n(getattr(r, "As_b", None))]
                 for r, la in ((r, v.pavimento.lajes[i])
                               for i, r in enumerate(v.resultado.lajes))])
        linhas = []
        for p in v.resultado.todas_posicoes:
            linhas.append([f"N{p.numero}", p.laje, p.tipo, p.face,
                           f"{p.quantidade}Ø{p.phi:g} c/{p.espacamento:g}",
                           _n(p.comprimento, 0)])
        _tabela(doc, ["pos.", "laje", "tipo", "face", "bitola",
                      "C (cm)"], linhas)


def _quantitativos(doc, projeto) -> None:
    from .quantitativos import consolidar

    doc.add_heading("10  Quantitativos", level=1)
    q = consolidar(projeto)
    _tabela(doc, ["Elemento", "aço (kg)", "aço com perdas (kg)",
                  "concreto (m³)", "fôrmas (m²)", "taxa (kg/m³)"],
            [[nome, _n(d["aco"], 1), _n(d["aco_perdas"], 1),
              _n(d["concreto"], 3), _n(d.get("formas", 0.0)),
              _n(d["aco"] / d["concreto"], 1) if d["concreto"] else "-"]
             for nome, d in q["por_elemento"].items()]
            + [["TOTAL", _n(q["aco"], 1), _n(q["aco_perdas"], 1),
                _n(q["concreto"], 3), _n(q["formas"]),
                _n(q["aco"] / q["concreto"], 1) if q["concreto"] else "-"]])
    _p(doc, "As massas nominais são as da Tabela 4 da NBR 7480, e as perdas "
            "adotadas, 10 %.")

    doc.add_heading("10.1  Critério das fôrmas", level=2)
    _p(doc, "Conta-se apenas a face que precisa conter o concreto, e por isso "
            "a área de fôrma não coincide com a área das peças:")
    _tabela(doc, ["Peça", "critério"], [
        ["Laje", "fundo descontada a faixa que se apoia sobre a viga — essa "
                 "faixa já é fôrma da viga, e contá-la duas vezes seria medir "
                 "a mesma chapa duas vezes —, mais o fechamento lateral só "
                 "nos bordos livres: onde o bordo apoia numa viga, a lateral "
                 "dela já sobe e fecha; onde é bordo comum com outra laje, o "
                 "concreto é contínuo e não há o que fechar"],
        ["Viga", "fundo integral, mais cada lateral com a altura h menos a "
                 "espessura da laje que encosta naquele lado. Viga entre dois "
                 "painéis desconta dos dois lados; viga de bordo, de um só. O "
                 "topo não leva fôrma: é por onde se concreta"],
        ["Pilar", "perímetro moldante vezes a altura do lance"],
    ])


def _avisos(doc, projeto) -> None:
    if not projeto.avisos:
        return
    doc.add_heading("11  Avisos", level=1)
    for aviso in projeto.avisos:
        _p(doc, f"• {aviso}")


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def gerar(projeto, caminho) -> Path:
    """Grava a memória de cálculo do edifício e devolve o caminho."""
    try:
        from docx import Document
    except ImportError as erro:                          # pragma: no cover
        raise RuntimeError(
            "para gravar a memória de cálculo é preciso o python-docx: "
            "py -m pip install python-docx") from erro

    doc = Document()
    _configurar(doc)
    _capa(doc, projeto)
    for capitulo in (_metodologia, _modelo, _esforcos, _estabilidade,
                     _reacoes, _pilares, _vigas, _confronto, _lajes,
                     _quantitativos, _avisos):
        capitulo(doc, projeto)

    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(destino))
    return destino
