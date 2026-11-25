# -*- coding: utf-8 -*-
"""
planilha.py
Exportação dos resultados em .xlsx no padrão de planilhas da Ecoplan.

A aba de solicitações não é um despejo de números: traz a memória de cálculo
com **fórmulas vivas** do Excel, na sequência da NBR 6118, de modo que o
projetista possa alterar um dado de entrada -- seção, comprimento de
flambagem, esforço -- e ver a esbeltez, o momento mínimo, a segunda ordem e as
quatro situações de cálculo recalcularem. Os valores de entrada aparecem em
azul.

As abas de dimensionamento e verificação trazem os resultados apurados pelo
programa, porque o motor seccional integra a seção fatiada e não cabe em
fórmula de célula. O que elas trazem, em compensação, é a rastreabilidade: o
caso do roteiro, o domínio, a linha neutra e as tensões de cada camada.
"""

from __future__ import annotations

import math

from openpyxl import Workbook

from . import auditoria
from ..core import avisos as avisos_mod
from ..core.dimensionar import ResultadoPilar
from ..core.flexocompressao import DESCRICAO_CASO
from ..core.modelo import VINCULOS
from .estilo_planilha import (COR, NF, cabecalho, expressao,
                              grandeza, legenda, linha_tabela,
                              normalizar_alturas, nota, preparar_memoria,
                              preparar_tabela, secao, separador, titulo,
                              veredito)
from ..core.formato import num


def _ok(passou: bool) -> str:
    """Texto de veredito da célula, no formato que a condicional reconhece.

    Sai como fórmula literal, e não como texto puro, para que a célula
    continue editável na planilha sem perder a formatação condicional de
    "OK" / "não atende" montada por :func:`estilo_planilha.veredito`.
    """
    return f'="{"OK" if passou else "não atende"}"'


class Memoria:
    """Escritor da aba de memória vertical, com rastreio de células.

    Guarda o endereço da célula de cada grandeza pelo nome, de modo que as
    fórmulas seguintes possam se referir a ela sem que ninguém precise contar
    linhas à mão -- que é como planilha de engenharia quebra ao ganhar uma
    linha nova no meio.
    """

    def __init__(self, ws, linha: int = 2) -> None:
        self.ws = ws
        self.linha = linha
        self.ref: dict[str, str] = {}

    def endereco(self, nome: str) -> str:
        return self.ref[nome]

    def valor(self, nome: str, rotulo: str, valor, descricao: str = "",
              formato: str | None = None, entrada: bool = False,
              referencia: str = "") -> str:
        self.linha = grandeza(self.ws, self.linha, rotulo, valor, descricao,
                              formato, entrada, referencia)
        endereco = f"$C${self.linha - 1}"
        if nome:
            self.ref[nome] = endereco
        return endereco

    def formula(self, nome: str, rotulo: str, expr: str, descricao: str = "",
                formato: str | None = None, referencia: str = "",
                algebra: str = "") -> str:
        if algebra:
            self.linha = expressao(self.ws, self.linha, "", algebra)
        return self.valor(nome, rotulo, expr, descricao, formato,
                          referencia=referencia)

    def veredito(self, rotulo: str, expr: str, descricao: str = "") -> None:
        self.linha = veredito(self.ws, self.linha, rotulo, expr, descricao)

    def secao(self, texto: str, cor: str | None = None) -> None:
        self.linha = separador(self.ws, self.linha)
        self.linha = secao(self.ws, self.linha, texto, cor=cor)

    def nota(self, texto: str) -> None:
        self.linha = nota(self.ws, self.linha, texto)

    def espaco(self) -> None:
        self.linha = separador(self.ws, self.linha)


# ---------------------------------------------------------------------------
# Aba de solicitações -- a cadeia viva
# ---------------------------------------------------------------------------

def _aba_solicitacoes(wb: Workbook, res: ResultadoPilar) -> None:
    p = res.pilar
    ws = wb.create_sheet("Solicitações")
    preparar_memoria(ws)
    linha = titulo(ws, 2, f"PILAR {p.nome} — SOLICITAÇÕES DE CÁLCULO")
    linha = nota(ws, linha, "ABNT NBR 6118 — itens 11.3.3.4.3, 15.8.1, "
                            "15.8.2, 15.8.3.3.2, 15.8.3.3.3 e 15.8.3.3.5")
    m = Memoria(ws, linha)

    m.secao("Dados de entrada")
    m.valor("hx", "hx =", p.secao.hx, "altura da seção na direção x",
            NF["cm"], entrada=True, referencia="13.2.3")
    m.valor("hy", "hy =", p.secao.hy, "altura da seção na direção y",
            NF["cm"], entrada=True, referencia="13.2.3")
    m.valor("Ac", "Ac =", p.secao.area, "área bruta de concreto",
            NF["cm2"], entrada=True, referencia="13.2.3")
    m.valor("ix", "ix =", p.secao.propriedades().ix,
            "raio de giração na direção x", NF["cm"], entrada=True)
    m.valor("iy", "iy =", p.secao.propriedades().iy,
            "raio de giração na direção y", NF["cm"], entrada=True)
    _comprimento_equivalente(m, res)
    m.valor("fck", "fck =", p.concreto.fck, "classe do concreto", NF["MPa"],
            entrada=True, referencia="8.2.4")
    m.valor("gamac", "γc =", p.concreto.gamma_c, "", NF["coef"],
            entrada=True, referencia="12.4.1")
    m.valor("Nd", "Nd =", p.esforcos.Nd,
            "força normal de cálculo, positiva em compressão", NF["kN"],
            entrada=True)
    for rotulo, nome, valor in (("M1d,t,x", "Mtx", p.esforcos.Mx_topo),
                                ("M1d,b,x", "Mbx", p.esforcos.Mx_base),
                                ("M1d,t,y", "Mty", p.esforcos.My_topo),
                                ("M1d,b,y", "Mby", p.esforcos.My_base)):
        m.valor(nome, f"{rotulo} =", valor,
                "momento de 1ª ordem no " + ("topo" if ",t," in rotulo
                                             else "base"),
                NF["kNm"], entrada=True)
    m.valor("gaman", "γn =", p.gamma_n,
            "coeficiente adicional da seção reduzida", NF["coef"],
            entrada=True, referencia="Tabela 13.1")
    m.valor("gamaf", "γf =", p.config.gamma_f,
            "1,0 quando os esforços de entrada já são de cálculo",
            NF["coef"], entrada=True)

    m.secao("Grandezas derivadas")
    m.formula("fcd", "fcd =", f"={m.endereco('fck')}/{m.endereco('gamac')}/10",
              "resistência de cálculo à compressão", NF["kNcm2"],
              referencia="12.3.3", algebra="fcd = fck/γc")
    m.formula("f", "γf·γn =",
              f"={m.endereco('gamaf')}*{m.endereco('gaman')}",
              "multiplicador dos esforços de entrada", NF["coef"])
    m.formula("Ndc", "Nd,cálc =", f"={m.endereco('Nd')}*{m.endereco('f')}",
              "força normal majorada", NF["kN"])
    m.formula("nu", "ν =",
              f"={m.endereco('Ndc')}/{m.endereco('gaman')}"
              f"/({m.endereco('Ac')}*{m.endereco('fcd')})",
              "força normal adimensional da 2ª ordem: sem γn, que majora "
              "os esforços finais (nota da Tabela 13.1)", NF["adm"],
              referencia="15.8.3.3.2", algebra="ν = Nd/(γn·Ac·fcd)")

    for d, (mt, mb, h, i, le) in (("x", ("Mtx", "Mbx", "hx", "ix", "lex")),
                                  ("y", ("Mty", "Mby", "hy", "iy", "ley"))):
        e = res.esbeltez[d]
        m.secao(f"Direção {d} — esbeltez e momento mínimo")
        m.formula(f"MA{d}", f"M1d,A,{d} =",
                  f"={m.endereco('f')}*MAX(ABS({m.endereco(mt)}),"
                  f"ABS({m.endereco(mb)}))",
                  "maior momento de 1ª ordem, em módulo", NF["kNm"],
                  referencia="15.8.2")
        m.formula(f"MB{d}", f"M1d,B,{d} =",
                  f"=IF({m.endereco(mt)}*{m.endereco(mb)}<0,-1,1)"
                  f"*{m.endereco('f')}*MIN(ABS({m.endereco(mt)}),"
                  f"ABS({m.endereco(mb)}))",
                  "momento do outro extremo, negativo em curvatura reversa",
                  NF["kNm"], referencia="15.8.2")
        m.formula(f"e1{d}", f"e1,{d} =",
                  f"={m.endereco(f'MA{d}')}/{m.endereco('Ndc')}",
                  "excentricidade de 1ª ordem", NF["cm"])
        m.formula(f"emin{d}", f"e1,mín,{d} =",
                  f"=1.5+0.03*{m.endereco(h)}",
                  "excentricidade mínima", NF["cm"],
                  referencia="11.3.3.4.3", algebra="e1,mín = 1,5 + 0,03·h")
        m.formula(f"Mmin{d}", f"M1d,mín,{d} =",
                  f"={m.endereco('Ndc')}*{m.endereco(f'emin{d}')}",
                  "momento mínimo de 1ª ordem", NF["kNm"],
                  referencia="11.3.3.4.3")
        vinc = p.lance.vinculo(d)
        m.valor(f"vinc{d}", f"vínculo em {d} =", VINCULOS[vinc],
                "condição de contorno do lance", NF["texto"], entrada=True,
                referencia="15.8.2")
        if vinc == 1:
            expr = (f"=IF({m.endereco(f'e1{d}')}<{m.endereco(f'emin{d}')},1,"
                    f"MIN(1,MAX(0.6+0.4*{m.endereco(f'MB{d}')}"
                    f"/{m.endereco(f'MA{d}')},0.4)))")
            alg = "αb = 0,60 + 0,40·MB/MA ≥ 0,40"
        elif vinc == 2:
            expr = "=1"
            alg = "αb = 1,0 (cargas transversais)"
        else:
            expr = f"={e.alfa_b}"
            alg = "αb = 1,0 (balanço, item 15.8.2-c da NBR 6118:2026)"
        m.formula(f"ab{d}", f"αb,{d} =", expr, "", NF["coef"],
                  referencia="15.8.2", algebra=alg)
        m.formula(f"lam{d}", f"λ{d} =",
                  f"={m.endereco(le)}/{m.endereco(i)}", "índice de esbeltez",
                  NF["coef"], referencia="15.8.1", algebra="λ = le/i")
        m.formula(f"lam1{d}", f"λ1,{d} =",
                  f"=MIN(90,MAX(35,(25+12.5*{m.endereco(f'e1{d}')}"
                  f"/{m.endereco(h)})/{m.endereco(f'ab{d}')}))",
                  "esbeltez limite", NF["coef"], referencia="15.8.2",
                  algebra="λ1 = (25 + 12,5·e1/h)/αb, 35 ≤ λ1 ≤ 90")
        m.valor(f"sempre{d}", f"2ª ordem sempre,{d} =",
                1 if p.config.sempre_2a_ordem else 0,
                "1 = imposta pelo projetista mesmo com λ ≤ λ1; 0 = só "
                "quando λ > λ1", NF["coef"], entrada=True,
                referencia="15.8.2")
        m.veredito(f"2ª ordem em {d}:",
                   f'=IF({m.endereco(f"lam{d}")}<={m.endereco(f"lam1{d}")},'
                   f'IF({m.endereco(f"sempre{d}")}=1,"imposta pelo projetista",'
                   f'"dispensada — OK"),"obrigatória")',
                   "item 15.8.2: dispensa quando λ ≤ λ1")
        m.veredito(f"λ{d} ≤ 200?",
                   f'=IF({m.endereco(f"lam{d}")}<=200,"OK",'
                   f'IF({m.endereco("Ndc")}<0.1*{m.endereco("fcd")}'
                   f'*{m.endereco("Ac")},"OK, pouco comprimido",'
                   f'"não atende — 15.8.1"))',
                   "acima de 200 só o elemento pouco comprimido "
                   "(Nd < 0,10 fcd Ac)")

        s2 = res.segunda_ordem[d]
        if p.config.momento_minimo_metodo == "planilha":
            m.formula(f"e1p{d}", f"e1,proj,{d} =",
                      f"={m.endereco(f'ab{d}')}*MAX({m.endereco(f'e1{d}')},"
                      f"{m.endereco(f'emin{d}')})",
                      "excentricidade de 1ª ordem de projeto, com αb e o "
                      "piso do mínimo", NF["cm"], referencia="15.8.3.3.2")
        else:
            m.formula(f"e1p{d}", f"e1,proj,{d} =",
                      f"={m.endereco(f'ab{d}')}*{m.endereco(f'e1{d}')}",
                      "excentricidade de 1ª ordem de projeto, com αb (o "
                      "mínimo é verificado à parte, pela envoltória mínima)",
                      NF["cm"], referencia="15.8.3.3.2")
        m.valor(f"ecc{d}", f"e_cc,{d} =", s2.e_cc if s2.aplicavel else 0.0,
                "fluência (15.8.4), calculada pelo programa; soma-se a e1 "
                "como efeito imediato" if p.config.considerar_fluencia
                else "fluência desligada nos critérios", NF["cm"],
                entrada=True, referencia="15.8.4")
        m.formula(f"e1a{d}", f"e1 + e_cc,{d} =",
                  f"={m.endereco(f'e1p{d}')}+{m.endereco(f'ecc{d}')}",
                  "excentricidade que a 2ª ordem amplifica", NF["cm"],
                  referencia="15.8.4")
        m.valor(f"g1{d}", f"γn1,{d} =", res.esbeltez[d].gamma_n1,
                "majora só a 2ª ordem quando λ > 140", NF["coef"],
                entrada=True, referencia="15.8.1")
        m.formula(f"curv{d}", f"(1/r){d} =",
                  f"=MIN(0.005/({m.endereco(h)}*({m.endereco('nu')}+0.5)),"
                  f"0.005/{m.endereco(h)})",
                  "curvatura da seção crítica", NF["coef3"],
                  referencia="15.8.3.3.2",
                  algebra="1/r = 0,005/[h(ν+0,5)] ≤ 0,005/h")
        m.formula(f"e2c{d}", f"e2,curv,{d} =",
                  f"={m.endereco(le)}^2*{m.endereco(f'curv{d}')}/10",
                  "2ª ordem pela curvatura aproximada", NF["cm"],
                  referencia="15.8.3.3.2", algebra="e2 = le²/10 · 1/r")
        m.formula(f"B{d}", f"B{d} =",
                  f"={m.endereco(h)}/5-{m.endereco(le)}^2"
                  f"/(1600*{m.endereco(h)})-{m.endereco(f'e1a{d}')}",
                  "coeficiente da quadrática da rigidez", NF["coef"],
                  referencia="15.8.3.3.3",
                  algebra="e² + (h/5 − le²/1600h − e1)·e − h·e1/5 = 0")
        m.formula(f"C{d}", f"C{d} =",
                  f"=-{m.endereco(h)}*{m.endereco(f'e1a{d}')}/5", "",
                  NF["coef"], referencia="15.8.3.3.3")
        m.formula(f"ed{d}", f"ed,{d} =",
                  f"=(-{m.endereco(f'B{d}')}+SQRT({m.endereco(f'B{d}')}^2"
                  f"-4*{m.endereco(f'C{d}')}))/2",
                  "excentricidade total pela rigidez aproximada", NF["cm"],
                  referencia="15.8.3.3.3")
        m.formula(f"e2r{d}", f"e2,rig,{d} =",
                  f"=MAX({m.endereco(f'ed{d}')}"
                  f"-{m.endereco(f'e1a{d}')},0)",
                  "2ª ordem pela rigidez aproximada", NF["cm"],
                  referencia="15.8.3.3.3")
        criterio = p.config.metodo_2a_ordem
        if criterio in ("diagrama", "geral"):
            # sem fórmula viva: a rigidez sai da relação momento-curvatura da
            # seção armada (Figura 15.1), que a planilha não integra
            m.valor(f"e2{d}", f"e2,{d} =", s2.e2 if s2.aplicavel else 0.0,
                    f"calculado pelo programa -- {s2.metodo}; inclui e_cc e "
                    f"γn1. Não é fórmula viva", NF["cm"], entrada=True,
                    referencia="15.8.3.3.4" if criterio == "diagrama"
                    else "15.8.3.2")
        else:
            if criterio == "curvatura":
                expr2 = f"={m.endereco(f'e2c{d}')}"
            elif criterio == "rigidez":
                expr2 = f"={m.endereco(f'e2r{d}')}"
            else:
                expr2 = (f"=MIN({m.endereco(f'e2c{d}')},"
                         f"{m.endereco(f'e2r{d}')})")
            m.formula(f"e2{d}", f"e2,{d} =",
                      f"=IF(OR({m.endereco(f'lam{d}')}>{m.endereco(f'lam1{d}')},"
                      f"{m.endereco(f'sempre{d}')}=1),"
                      f"{m.endereco(f'g1{d}')}*{expr2[1:]}"
                      f"+{m.endereco(f'ecc{d}')},0)",
                      f"adotado pelo critério '{criterio}', com γn1 e e_cc",
                      NF["cm"], referencia="15.8.3.3")

    _situacoes_vivas(m, res)
    normalizar_alturas(wb)


def _comprimento_equivalente(m: Memoria, res: ResultadoPilar) -> None:
    """Escreve ``le`` na aba: como fórmula viva quando ele é calculado.

    Informado, ``le`` entra como dado de entrada, em azul. Calculado, entra
    como a própria expressão do item 15.8.2 -- ``MIN(l0 + h; l)`` --, com
    ``l`` e as alturas das vigas acima dele. Assim, mexer no pé-direito na
    planilha recalcula a esbeltez inteira, que é o ponto de a aba ser viva.
    """
    p = res.pilar
    if p.lance.le_x > 0 and p.lance.le_y > 0:
        m.valor("lex", "le,x =", p.lance.le_x,
                "comprimento equivalente informado", NF["cm"],
                entrada=True, referencia="15.8.2")
        m.valor("ley", "le,y =", p.lance.le_y,
                "comprimento equivalente informado", NF["cm"],
                entrada=True, referencia="15.8.2")
        return

    m.valor("l", "l =", p.lance.l,
            "distância entre os eixos das vigas", NF["cm"], entrada=True,
            referencia="15.8.2")
    for d in ("x", "y"):
        m.valor(f"vt{d}", f"viga de topo em {d} =", p.lance.viga_topo(d),
                "altura da viga que trava essa direção", NF["cm"],
                entrada=True)
        m.valor(f"vb{d}", f"viga de base em {d} =", p.lance.viga_base(d),
                "", NF["cm"], entrada=True)
    for d, h in (("x", "hx"), ("y", "hy")):
        m.formula(f"l0{d}", f"l0,{d} =",
                  f"={m.endereco('l')}-({m.endereco(f'vt{d}')}"
                  f"+{m.endereco(f'vb{d}')})/2",
                  "distância livre entre as faces internas das vigas",
                  NF["cm"], referencia="15.8.2")
        if p.lance.le_informado(d) > 0:
            m.valor(f"le{d}", f"le,{d} =", p.lance.le_informado(d),
                    "informado pelo projetista", NF["cm"], entrada=True,
                    referencia="15.8.2")
        elif p.lance.vinculo(d) == 3:
            m.formula(f"le{d}", f"le,{d} =", f"=2*{m.endereco('l')}",
                      "em balanço", NF["cm"], referencia="15.8.2",
                      algebra="le = 2 l")
        else:
            m.formula(f"le{d}", f"le,{d} =",
                      f"=MIN({m.endereco(f'l0{d}')}+{m.endereco(h)},"
                      f"{m.endereco('l')})",
                      "comprimento equivalente de flambagem", NF["cm"],
                      referencia="15.8.2", algebra="le = min(l0 + h; l)")


def _situacoes_vivas(m: Memoria, res: ResultadoPilar) -> None:
    """As situações de cálculo, com fórmulas -- as do critério adotado."""
    p = res.pilar
    if p.config.metodo_2a_ordem == "geral":
        m.secao("Situações de cálculo — método geral (15.8.3.2)", COR["elu"])
        m.nota("Uma situação por seção da barra discretizada, com os "
               "momentos totais (1ª + 2ª ordem) da análise não linear. "
               "Calculadas pelo programa; não são fórmulas vivas.")
        for s_ in res.situacoes:
            m.valor("", f"Mx — {s_.nome} =", s_.Mx,
                    f"kN·cm, como o resto da aba — {s_.descricao}",
                    NF["kNm"], entrada=True)
            m.valor("", f"My — {s_.nome} =", s_.My, "kN·cm", NF["kNm"],
                    entrada=True)
        return
    if p.config.momento_minimo_metodo != "planilha":
        _situacoes_envoltoria(m, res)
        return
    m.secao("Situações de cálculo", COR["elu"])
    m.nota("Extremidades A e B sem 2ª ordem; seção intermediária com αb e "
           "e2. O momento mínimo é imposto numa direção de cada vez "
           "(item 11.3.3.4.3).")
    combinar = p.config.combinar_2a_ordem_biaxial
    e2x = m.endereco("e2x") if combinar else m.endereco("e2x")
    e2y = m.endereco("e2y") if combinar else m.endereco("e2y")

    definicoes = [
        ("Situação 1", f"=MAX({m.endereco('e1x')},{m.endereco('eminx')})",
         f"={m.endereco('e1y')}", "extremo, mínimo em x"),
        ("Situação 2", f"={m.endereco('e1x')}",
         f"=MAX({m.endereco('e1y')},{m.endereco('eminy')})",
         "extremo, mínimo em y"),
    ]
    if combinar:
        definicoes += [
            ("Situação 3",
             f"={m.endereco('e1px')}+{e2x}",
             f"={m.endereco('aby')}*{m.endereco('e1y')[1:]}+{e2y}",
             "meio, mínimo em x, 2ª ordem nas duas direções"),
            ("Situação 4",
             f"={m.endereco('abx')}*{m.endereco('e1x')[1:]}+{e2x}",
             f"={m.endereco('e1py')}+{e2y}",
             "meio, mínimo em y, 2ª ordem nas duas direções"),
        ]
    else:
        definicoes += [
            ("Situação 3", f"={m.endereco('e1px')}+{e2x}",
             f"={m.endereco('aby')}*{m.endereco('e1y')[1:]}",
             "meio, mínimo e 2ª ordem em x (critério da planilha)"),
            ("Situação 4", f"={m.endereco('abx')}*{m.endereco('e1x')[1:]}",
             f"={m.endereco('e1py')}+{e2y}",
             "meio, mínimo e 2ª ordem em y (critério da planilha)"),
        ]

    enderecos: list[tuple[str, str]] = []
    for nome, fx, fy, descricao in definicoes:
        chave = nome.replace("Situação ", "S")
        ex = m.formula(f"ex{chave}", f"ex — {nome} =", fx, descricao,
                       NF["cm"])
        ey = m.formula(f"ey{chave}", f"ey — {nome} =", fy, "", NF["cm"])
        m.formula(f"e{chave}", f"|e| — {nome} =",
                  f"=SQRT({ex}^2+{ey}^2)", "excentricidade resultante",
                  NF["cm"])
        m.formula(f"Mx{chave}", f"Mx — {nome} =",
                  f"=MAX({m.endereco('Ndc')}*ABS({ex}),"
                  f"{m.endereco('Mminx')})",
                  "momento de cálculo, com o piso do mínimo", NF["kNm"])
        m.formula(f"My{chave}", f"My — {nome} =",
                  f"=MAX({m.endereco('Ndc')}*ABS({ey}),"
                  f"{m.endereco('Mminy')})", "", NF["kNm"])
        enderecos.append((chave, m.endereco(f"e{chave}")))
        m.espaco()

    modulos = ",".join(a for _, a in enderecos)
    m.formula("emax", "|e| governante =", f"=MAX({modulos})",
              "maior excentricidade resultante", NF["cm"])
    m.nota("A situação de maior |e| orienta a escolha da armadura; a "
           "verificação, porém, é feita contra todas as quatro.")


def _situacoes_envoltoria(m: Memoria, res: ResultadoPilar) -> None:
    """Situações do critério da envoltória mínima: o momento real, sem piso
    -- o mínimo é verificado à parte (item 3.1 da apostila)."""
    p = res.pilar
    m.secao("Situações de cálculo", COR["elu"])
    m.nota("Momento real, sem o piso do mínimo, que é verificado à parte pela "
           "envoltória mínima (aba Verificação). Valores em módulo; o "
           "programa leva o sentido físico de M1d,A, que importa com "
           "armadura assimétrica.")
    ab = {d: m.endereco(f"ab{d}") for d in "xy"}
    e1 = {d: m.endereco(f"e1{d}") for d in "xy"}
    e2 = {d: m.endereco(f"e2{d}") for d in "xy"}
    if p.config.combinar_2a_ordem_biaxial:
        definicoes = [
            ("Extremo", f"={e1['x']}", f"={e1['y']}",
             "extremo do pilar, momento real de 1ª ordem"),
            ("Meio", f"={ab['x']}*{e1['x']}+{e2['x']}",
             f"={ab['y']}*{e1['y']}+{e2['y']}",
             "meio do pilar, 2ª ordem nas duas direções"),
        ]
    else:
        definicoes = [
            ("Extremo", f"={e1['x']}", f"={e1['y']}",
             "extremo do pilar, momento real de 1ª ordem"),
            ("Meio (x)", f"={ab['x']}*{e1['x']}+{e2['x']}",
             f"={ab['y']}*{e1['y']}", "meio do pilar, 2ª ordem em x"),
            ("Meio (y)", f"={ab['x']}*{e1['x']}",
             f"={ab['y']}*{e1['y']}+{e2['y']}",
             "meio do pilar, 2ª ordem em y"),
        ]
    enderecos = []
    for i, (nome, fx, fy, descricao) in enumerate(definicoes):
        chave = f"E{i}"
        ex = m.formula(f"ex{chave}", f"ex — {nome} =", fx, descricao,
                       NF["cm"])
        ey = m.formula(f"ey{chave}", f"ey — {nome} =", fy, "", NF["cm"])
        m.formula(f"e{chave}", f"|e| — {nome} =", f"=SQRT({ex}^2+{ey}^2)",
                  "excentricidade resultante", NF["cm"])
        m.formula(f"Mx{chave}", f"Mx — {nome} =",
                  f"={m.endereco('Ndc')}*ABS({ex})",
                  "momento de cálculo, kN·cm", NF["kNm"])
        m.formula(f"My{chave}", f"My — {nome} =",
                  f"={m.endereco('Ndc')}*ABS({ey})", "kN·cm", NF["kNm"])
        enderecos.append(m.endereco(f"e{chave}"))
        m.espaco()
    m.formula("emax", "|e| governante =", f"=MAX({','.join(enderecos)})",
              "maior excentricidade resultante", NF["cm"])


# ---------------------------------------------------------------------------
# Demais abas
# ---------------------------------------------------------------------------

def _aba_dimensionamento(wb: Workbook, res: ResultadoPilar) -> None:
    if not res.dim_fechado:
        return
    p = res.pilar
    for d in ("x", "y"):
        dim = res.dim_fechado.get(d)
        if dim is None:
            continue
        ws = wb.create_sheet(f"Dim,{d}{d}")
        preparar_memoria(ws)
        linha = titulo(ws, 2, f"PILAR {p.nome} — FLEXO-COMPRESSÃO NA "
                              f"DIREÇÃO {d.upper()}")
        linha = nota(ws, linha, "Roteiro dos casos fechados FC1–FC4 / "
                                "FT1–FT4 — modelo de duas camadas, diagrama "
                                "retangular do item 17.2.2")
        m = Memoria(ws, linha)
        cl = dim.classificacao
        h = p.secao.altura(d)
        b = p.secao.altura("y" if d == "x" else "x")
        d_linha = res.arranjo.d_linha_x if res.arranjo else 0.0

        m.secao("Geometria e materiais")
        m.valor("", "b =", b, "largura perpendicular à flexão", NF["cm"],
                entrada=True)
        m.valor("", "h =", h, "altura na direção da flexão", NF["cm"],
                entrada=True)
        m.valor("", "d' =", d_linha, "face ao eixo da camada de barras",
                NF["cm"], entrada=True)
        m.valor("", "d =", h - d_linha, "altura útil", NF["cm"])
        m.valor("", "αc =", p.concreto.alfa_c, "", NF["coef"],
                referencia="17.2.2")
        m.valor("", "ηc =", p.concreto.eta_c, "fragilidade do concreto",
                NF["coef"], referencia="8.2.10.1")
        m.valor("", "αc·ηc =", p.concreto.fator_bloco,
                "tensão do bloco retangular / fcd", NF["coef"],
                referencia="17.2.2")
        m.valor("", "λ (bloco) =", p.concreto.lambda_bloco, "", NF["coef"],
                referencia="17.2.2")
        m.valor("", "fcd =", p.concreto.fcd_kNcm2, "", NF["kNcm2"])
        m.valor("", "fyd =", p.aco.fyd_kNcm2, "", NF["kNcm2"])
        m.valor("", "εyd =", p.aco.eps_yd_mil, "deformação de escoamento",
                NF["coef3"])

        m.secao("Esforços e excentricidades")
        m.valor("", "Nd =", dim.Nd, "", NF["kN"])
        m.valor("", "Md =", abs(dim.Md), "situação mais desfavorável",
                NF["kNm"])
        m.valor("", "e0 = Md/Nd =", cl.e0, "excentricidade da resultante",
                NF["cm"])
        m.valor("", "e1 =", cl.e1, "de Nd até a camada As1", NF["cm"])
        m.valor("", "e2 =", cl.e2, "de Nd até a camada As2", NF["cm"])
        m.valor("", "e2,GP =", cl.e2_GP, "fronteira da grande excentricidade",
                NF["cm"])
        m.valor("", "e2,PC =", cl.e2_PC, "fronteira da compressão composta",
                NF["cm"])
        m.valor("", "e2,23 =", cl.e2_23, "fronteira dos casos simétricos 2/3",
                NF["cm"])
        m.valor("", "e2,34 =", cl.e2_34, "fronteira dos casos simétricos 3/4",
                NF["cm"])

        m.secao("Resultado")
        m.valor("", "Caso =", dim.caso, DESCRICAO_CASO.get(dim.caso, ""),
                NF["texto"])
        m.valor("", "x =", dim.x, f"linha neutra — domínio {dim.dominio}",
                NF["cm"])
        m.valor("", "σ1 =", dim.sigma1, "tensão na camada As1", NF["kNcm2"])
        m.valor("", "σ2 =", dim.sigma2, "tensão na camada As2", NF["kNcm2"])
        m.valor("", "As1 =", dim.As1, "", NF["cm2"])
        m.valor("", "As2 =", dim.As2, "", NF["cm2"])
        m.espaco()
        m.linha = legenda(ws, m.linha, [
            ("As1", "camada da face afastada da resultante, tracionada na "
                    "grande excentricidade"),
            ("As2", "camada da face para a qual a resultante é excêntrica"),
            ("x", "profundidade da linha neutra medida da fibra mais "
                  "comprimida"),
        ])


def _aba_verificacao(wb: Workbook, res: ResultadoPilar) -> None:
    p = res.pilar
    ws = wb.create_sheet("Verificação")
    preparar_tabela(ws, [14.0, 13.0, 13.0, 13.0, 13.0, 11.0, 13.0])
    linha = titulo(ws, 2, f"PILAR {p.nome} — FLEXÃO COMPOSTA OBLÍQUA",
                   col_fim=8)
    linha = nota(ws, linha, f"Item 17.2.5 — (MSd,x/MRd,xx)^α + "
                            f"(MSd,y/MRd,yy)^α ≤ 1, com α = "
                            f"{num(p.alfa_interacao)}", col_fim=8)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Situação", "MSd,x (kN·m)",
                                  "MRd,xx (kN·m)", "MSd,y (kN·m)",
                                  "MRd,yy (kN·m)", "Interação (%)", "Veredito"])
    for v in res.verificacoes:
        linha = linha_tabela(ws, linha, [
            v.situacao.nome, v.situacao.Mx / 100.0, v.MRd_xx / 100.0,
            v.situacao.My / 100.0, v.MRd_yy / 100.0, v.interacao,
            "OK" if v.ok_interacao else
            ("informativa" if not v.interacao_exigida else "não atende")],
            [None, NF["kNm"], NF["kNm"], NF["kNm"], NF["kNm"], NF["perc"],
             None])
    nr = res.normal
    if nr is not None:
        linha = separador(ws, linha)
        linha = secao(ws, linha, "Força normal resistente — esmagamento "
                                 "(17.2.2 g), retas a e b)", col_fim=8)
        linha = nota(ws, linha,
                     f"Compressão uniforme a εc2 = {num(nr.eps_c2, 2)} ‰: "
                     f"concreto a {num(nr.sigma_cd * 10, 2)} MPa (0,85·ηc·fcd) "
                     f"em Ac, mais o aço a {num(nr.sigma_s * 10, 0)} MPa "
                     f"descontado o concreto que ele ocupa. Tração: As·fyd.",
                     col_fim=8)
        linha = cabecalho(ws, linha, ["Nd (kN)", "Concreto (kN)",
                                      "Aço (kN)", "NRd,máx (kN)",
                                      "NRd,mín (kN)", "F.S.", "Veredito"])
        linha = linha_tabela(ws, linha, [
            nr.Nd, nr.N_concreto, nr.N_aco, nr.NRd_max, nr.NRd_min,
            nr.fs if math.isfinite(nr.fs) else "∞",
            "OK" if nr.ok else ("esmagamento" if nr.compressao
                                else "não atende")],
            [NF["kN"], NF["kN"], NF["kN"], NF["kN"], NF["kN"], NF["coef3"],
             None])
    linha = separador(ws, linha)
    linha = secao(ws, linha, "Envoltória de momentos resistentes", col_fim=8)
    linha = nota(ws, linha,
                 "Item 15.8.3.3.5 — a composição dos momentos solicitantes "
                 "tem de cair dentro da envoltória de MRd obtida do "
                 "equilíbrio da seção, sem expoente aproximado.", col_fim=8)
    linha = cabecalho(ws, linha, ["Situação", "MSd (kN·m)",
                                  "MRd na direção (kN·m)", "MSd/MRd (%)",
                                  "F.S.", "Domínio", "Veredito"])
    for v in res.verificacoes:
        if v.envoltoria_inatingivel:
            linha = linha_tabela(ws, linha, [
                v.situacao.nome, v.MSd / 100.0,
                "nenhuma LN alcança essa direção", "—", 0.0, "—",
                "não atende"],
                [None, NF["kNm"], None, None, NF["coef3"], None, None])
            continue
        if v.MRd_envoltoria <= 0:
            continue
        mrd = (f"[{num(v.MRd_envoltoria_inferior / 100.0, 1)}; "
               f"{num(v.MRd_envoltoria / 100.0, 1)}]"
               if v.MRd_envoltoria_inferior > 0 else v.MRd_envoltoria / 100.0)
        linha = linha_tabela(ws, linha, [
            v.situacao.nome, v.MSd / 100.0, mrd,
            v.razao_envoltoria, v.fs if math.isfinite(v.fs) else "—",
            v.dominio, "OK" if v.ok_envoltoria else "não atende"],
            [None, NF["kNm"], None, NF["perc"], NF["coef3"], None, None])

    linha = separador(ws, linha)
    linha = secao(ws, linha, "Fator de segurança por cota do lance",
                  col_fim=8)
    linha = nota(ws, linha,
                 "Topo e base com o momento real de cada ponta; meio, a "
                 "pior das situações intermediárias já verificadas.",
                 col_fim=8)
    linha = cabecalho(ws, linha, ["Cota", "MSd (kN·m)",
                                  "MRd envoltória (kN·m)", "F.S.", "Domínio",
                                  "Veredito"])
    for nome_z, v in res.verificacoes_z.items():
        linha = linha_tabela(ws, linha, [
            nome_z, v.MSd / 100.0, v.MRd_envoltoria / 100.0,
            v.fs if math.isfinite(v.fs) else "—", v.dominio,
            "OK" if v.ok else "não atende"],
            [None, NF["kNm"], NF["kNm"], NF["coef3"], None, None])

    mm = res.momento_minimo
    if mm is not None:
        linha = separador(ws, linha)
        linha = secao(ws, linha,
                      "Momento mínimo — envoltória isolada (11.3.3.4.3)",
                      col_fim=8)
        linha = nota(ws, linha,
                     "Item 3.1 da apostila: duas análises isoladas à flexão "
                     "composta normal, uma por direção, independentes do "
                     "momento real -- Md,tot,mín contra o MRd daquela "
                     "direção apenas.", col_fim=8)
        linha = cabecalho(ws, linha, ["Direção", "Md,tot,mín (kN·m)",
                                      "MRd na direção (kN·m)", "F.S.",
                                      "Veredito"])
        for d, Msd, MRd, ok, valor in (
                (mm.rotulos[0], mm.Msd_x, mm.MRd_x, mm.ok_x, mm.fs_x),
                (mm.rotulos[1], mm.Msd_y, mm.MRd_y, mm.ok_y, mm.fs_y)):
            linha = linha_tabela(ws, linha, [
                d, Msd / 100.0, MRd / 100.0,
                valor if math.isfinite(valor) else "∞",
                "OK" if ok else "não atende"],
                [None, NF["kNm"], NF["kNm"], NF["coef3"], None])

    sv = res.servico
    if sv is not None and sv.aplicavel:
        linha = separador(ws, linha)
        linha = secao(ws, linha,
                      "Serviço — abertura de fissuras (ELS-W, 17.3.3.2)",
                      col_fim=8)
        linha = nota(ws, linha,
                     f"Combinação frequente, estádio II com αe = "
                     f"{num(sv.alfa_e)}; wk = min(wk1; wk2) da barra "
                     f"tracionada mais exigida, contra "
                     f"{num(sv.wk_limite, 2)} mm ({sv.origem_limite}).",
                     col_fim=8)
        linha = cabecalho(ws, linha, ["Cota", "Nk (kN)", "Mk,x (kN·m)",
                                      "Mk,y (kN·m)", "σs máx (MPa)",
                                      "wk (mm)", "Veredito"])
        for c in sv.cotas:
            ok = c.convergiu and c.wk_max <= sv.wk_limite + 1e-9
            linha = linha_tabela(ws, linha, [
                c.nome, c.N, c.Mx / 100.0, c.My / 100.0, c.sigma_s_max,
                c.wk_max, "OK" if ok else "não atende"],
                [None, NF["kNm"], NF["kNm"], NF["kNm"], NF["MPa"],
                 NF["mm"], None])

    if res.conferencias:
        linha = separador(ws, linha)
        linha = secao(ws, linha, "Conferência entre os dois motores",
                      col_fim=8)
        linha = cabecalho(ws, linha, ["Grandeza", "Casos fechados",
                                      "Motor seccional", "Divergência",
                                      "Na tolerância"])
        for c in res.conferencias:
            linha = linha_tabela(ws, linha, [
                c.grandeza, c.fechado, c.seccional, c.divergencia,
                "OK" if c.ok else "divergem"],
                [None, NF["kNm"], NF["kNm"], NF["perc"], None])


def _aba_detalhamento(wb: Workbook, res: ResultadoPilar) -> None:
    p = res.pilar
    a = res.arranjo
    if a is None:
        return
    from ..core import arranjo as arr_mod
    from ..core import estribos as est_mod
    ws = wb.create_sheet("Detalhamento")
    preparar_memoria(ws)
    linha = titulo(ws, 2, f"PILAR {p.nome} — DETALHAMENTO")
    linha = nota(ws, linha, "ABNT NBR 6118 — itens 18.4.2, 18.4.3, 18.2.4 "
                            "e 9.5.2.3")
    m = Memoria(ws, linha)
    m.secao("Armadura longitudinal")
    m.valor("", "Bitola =", a.phi, a.descricao_bitolas()
            if len(a.por_bitola()) > 1 else "", NF["bitola"],
            referencia="18.4.2.1")
    phi_max = arr_mod.bitola_maxima(p.secao)
    m.veredito("10 mm ≤ ø ≤ h/8?", _ok(10.0 <= a.phi_min and a.phi <= phi_max),
               f"máximo: {num(phi_max, 1)} mm")
    m.valor("", "Nº de barras =", a.n_barras, "", NF["barras"])
    if p.secao.tipo.startswith("retangular"):
        m.valor("", "nx (face horizontal) =", a.nx, "", NF["inteiro"])
        m.valor("", "ny (face vertical) =", a.ny, "", NF["inteiro"])
    m.valor("", "As efetiva =", a.As, "", NF["cm2"])
    if res.dim_fechado:
        m.valor("", "As necessária =", res.As_necessaria,
                "roteiro de duas camadas (informativo)", NF["cm2"])
    m.valor("", "As mínima =", res.As_minima, "", NF["cm2"],
            referencia="17.3.5.3.1")
    m.valor("", "ρ =", res.taxa, "taxa geométrica", NF["perc"],
            referencia="17.3.5.3")
    from ..core.materiais import RHO_MAXIMO, rho_minimo
    rmin = rho_minimo(res.nu, p.concreto, p.aco)
    m.veredito("ρ,mín ≤ ρ ≤ 4 % (8 % na emenda)?",
               _ok(rmin <= res.taxa <= RHO_MAXIMO),
               f"ρ,mín = {num(rmin * 100, 3)} %")
    s_min = arr_mod.espacamento_livre_minimo(a.phi, p.ambiente.dmax_agregado)
    m.valor("", "Espaçamento livre =", a.espacamento_livre, "", NF["cm"],
            referencia="18.4.2.2")
    m.veredito("s ≥ s,mín?", _ok(a.espacamento_livre >= s_min - 1e-6),
               f"s,mín = max(2 cm; ø; 1,2 d_máx) = {num(s_min, 1)} cm")
    s_max = arr_mod.espacamento_eixos_maximo(p.secao)
    m.valor("", "Espaçamento entre eixos =", a.espacamento_eixos, "",
            NF["cm"], referencia="18.4.2.2")
    m.veredito("s ≤ s,máx?", _ok(a.espacamento_eixos <= s_max + 1e-6),
               f"s,máx = min(2·menor dimensão; 40 cm) = {num(s_max, 1)} cm")

    e = res.estribos
    if e is not None:
        m.secao("Armadura transversal")
        m.valor("", "Bitola do estribo =", e.phi, "", NF["bitola"],
                referencia="18.4.3")
        phi_t_min = est_mod.bitola_minima(a.phi)
        m.veredito("øt ≥ max(5 mm; øl/4)?", _ok(e.phi >= phi_t_min - 1e-9),
                   f"mínimo: {num(phi_t_min, 2)} mm")
        m.valor("", "Espaçamento =", e.s, "", NF["cm"], referencia="18.4.3")
        m.veredito("s ≤ s,máx?", _ok(e.s <= e.s_maximo + 1e-9),
                   f"s,máx = {num(e.s_maximo, 1)} cm — governa: {e.motivo_s}")
        m.valor("", "Estribos no lance =", e.niveis, "", NF["inteiro"])
        m.valor("", "Comprimento do estribo =", e.comprimento, "", NF["cm"])
        m.valor("", "Alcance 20 øt =", e.alcance,
                "proteção do estribo poligonal", NF["cm"],
                referencia="18.2.4")
        m.valor("", "Grampos por nível =", e.n_suplementares, "",
                NF["inteiro"], referencia="18.2.4")

    anc = res.ancoragem
    if anc is not None:
        m.secao("Ancoragem e comprimento de espera")
        m.valor("", "fbd =", anc.fbd, "", NF["kNcm2"], referencia="9.3.2.1")
        m.valor("", "lb =", anc.lb, "comprimento básico", NF["cm"],
                referencia="9.4.2.4")
        m.valor("", "lb,nec =", anc.lb_nec, "", NF["cm"],
                referencia="9.4.2.5")
        if anc.tracionada:
            m.valor("", "α0t =", anc.alfa_0t,
                    "mais de 50 % das barras emendadas na seção", NF["coef"],
                    referencia="Tabela 9.4")
        m.valor("", f"{anc.simbolo} =", anc.l0c,
                "emenda de barras tracionadas" if anc.tracionada
                else "comprimento de espera", NF["cm"], referencia=anc.item)
        m.valor("", f"{anc.simbolo},mín =", anc.l0c_min,
                "max(0,3 α0t lb; 15 ø; 20 cm)" if anc.tracionada
                else "max(0,6 lb; 15 ø; 20 cm)", NF["cm"], referencia=anc.item)

    m.secao("Quantitativo do lance")
    comprimento = p.lance.altura + (anc.l0c if anc else 0.0)
    m.valor("", "Comprimento das barras =", comprimento,
            "lance mais o comprimento de espera", NF["cm"])
    m.valor("", "Massa longitudinal =", a.massa(comprimento), "", NF["kg"])
    if e is not None:
        m.valor("", "Massa transversal =", e.massa, "", NF["kg"])
    m.valor("", "Massa total de aço =", res.massa_total, "", NF["kg"])


def _aba_avisos(wb: Workbook, res: ResultadoPilar) -> None:
    ws = wb.create_sheet("Avisos")
    preparar_tabela(ws, [16.0, 100.0])
    linha = titulo(ws, 2, f"PILAR {res.pilar.nome} — AVISOS", col_fim=3)
    linha = nota(ws, linha,
                 "Erro é verificação não atendida ou dado inconsistente; "
                 "construtivo é decisão de detalhamento declarada.",
                 col_fim=3)
    linha = separador(ws, linha)
    erros, construtivos = avisos_mod.separar(res.avisos)
    linha = cabecalho(ws, linha, ["Nível", "Aviso"])
    if not erros and not construtivos:
        linha = linha_tabela(ws, linha, ["—", "Nenhum aviso emitido."])
    for a in erros:
        linha = linha_tabela(ws, linha, ["Erro", str(a)],
                             cores=[COR["alerta"], COR["alerta"]])
    for a in construtivos:
        linha = linha_tabela(ws, linha, ["Construtivo", str(a)])


def _aba_auditoria(wb: Workbook, res: ResultadoPilar) -> None:
    ws = wb.create_sheet("Auditoria")
    preparar_tabela(ws, [12.0, 34.0, 44.0, 44.0, 16.0])
    linha = titulo(ws, 2, f"PILAR {res.pilar.nome} — ROTEIRO DE "
                          f"VERIFICAÇÕES", col_fim=6)
    verificacoes = auditoria.roteiro(res)
    resumo = auditoria.resumo(verificacoes)
    linha = nota(ws, linha, "   ".join(f"{k}: {v}"
                                       for k, v in resumo.items()),
                 col_fim=6)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Item", "Verificação", "Critério",
                                  "Resultado", "Situação"])
    for v in verificacoes:
        cor = (COR["alerta"] if v.situacao == auditoria.NAO_ATENDIDO
               else None)
        linha = linha_tabela(ws, linha,
                             [v.item, v.descricao, v.criterio, v.resultado,
                              v.situacao], cores=[cor] * 5)


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------

def _aba_quantitativo(wb: Workbook, res: ResultadoPilar) -> None:
    """Quantitativo do lance: concreto, formas e aço por bitola."""
    from ..core import quantitativos as qt
    q = qt.calcular(res)
    p = res.pilar
    ws = wb.create_sheet("Quantitativo")
    preparar_tabela(ws, [26.0, 16.0, 16.0, 30.0])
    linha = titulo(ws, 2, f"PILAR {p.nome} — QUANTITATIVO DO LANCE",
                   col_fim=5)
    linha = nota(ws, linha,
                 "Formas: só as faces laterais, as que contêm o concreto "
                 "fresco -- todo o perímetro vertical, inclusive o dos "
                 "vazios. As faces horizontais ficam fora: a de baixo apoia "
                 "no que já foi concretado e a de cima é por onde se lança. "
                 "Cruzamentos com vigas e lajes não são descontados.",
                 col_fim=5)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Grandeza", "Quantidade", "Unidade",
                                  "Como sai"])
    for rotulo, valor, unidade, origem, fmt in (
            ("Volume de concreto", q.volume_concreto, "m³",
             f"Ac × h = {num(p.secao.area, 0)} cm² × {num(q.altura, 0)} cm",
             NF["m3"]),
            ("Área de formas", q.area_formas, "m²",
             f"perímetro × h = {num(q.perimetro, 1)} cm × {num(q.altura, 0)} cm",
             NF["m2"]),
            ("Massa de aço", q.massa_aco, "kg",
             "longitudinal (lance + espera) + transversal", NF["kg"]),
            ("Taxa de aço", q.taxa_aco, "kg/m³",
             "massa de aço / volume de concreto", NF["kgm3"])):
        linha = linha_tabela(ws, linha, [rotulo, valor, unidade, origem],
                             [None, fmt, None, None])

    linha = separador(ws, linha)
    linha = secao(ws, linha, "Aço por bitola", col_fim=5)
    linha = nota(ws, linha,
                 f"Comprimento de corte da barra longitudinal = "
                 f"{num(q.comprimento_barra, 0)} cm: o lance mais o comprimento "
                 f"de espera l0c, que é como a barra é comprada.", col_fim=5)
    linha = cabecalho(ws, linha, ["Bitola", "Massa", "", ""])
    for phi, massa in sorted(q.aco.items()):
        linha = linha_tabela(ws, linha, [f"ø{num(phi)} mm", massa, "kg", ""],
                             [None, NF["kg"], None, None])
    linha = linha_tabela(ws, linha, ["Total", q.massa_aco, "kg", ""],
                         [None, NF["kg"], None, None])


def _aba_combinacoes(wb: Workbook, res: ResultadoPilar) -> None:
    """Uma linha por combinação de esforços, todas com a mesma armadura."""
    ws = wb.create_sheet("Combinações")
    preparar_tabela(ws, [18.0, 12.0, 12.0, 12.0, 12.0, 12.0, 11.0, 11.0, 14.0])
    linha = titulo(ws, 2, f"{res.pilar.nome.upper()} — COMBINAÇÕES DE ESFORÇOS",
                   col_fim=10)
    linha = nota(ws, linha,
                 f"Todas verificadas com a mesma armadura "
                 f"({res.arranjo.descricao() if res.arranjo else '-'}). As "
                 f"outras abas detalham a que governa: "
                 f"{res.combinacao_governante}.", col_fim=10)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Combinação", "Nd (kN)", "Mx topo (kN·m)",
                                  "Mx base (kN·m)", "My topo (kN·m)",
                                  "My base (kN·m)", "F.S. mín.",
                                  "F.S. do mínimo", "Veredito"])
    for c in res.combinacoes:
        linha = linha_tabela(ws, linha, [
            c.nome + (" (governa)" if c.governante else ""), c.Nd,
            c.Mx_topo, c.Mx_base, c.My_topo, c.My_base,
            c.fs if math.isfinite(c.fs) else None,
            c.fs_minimo if math.isfinite(c.fs_minimo) else None,
            "OK" if c.ok else "não atende"],
            [None, NF["kN"], NF["kNm"], NF["kNm"], NF["kNm"], NF["kNm"],
             NF["coef"], NF["coef"], None])


def gerar(res: ResultadoPilar, caminho: str) -> str:
    """Grava a planilha de resultados e devolve o caminho do arquivo."""
    wb = Workbook()
    wb.remove(wb.active)
    _aba_solicitacoes(wb, res)
    if res.combinacoes:
        _aba_combinacoes(wb, res)
    _aba_dimensionamento(wb, res)
    _aba_verificacao(wb, res)
    _aba_detalhamento(wb, res)
    _aba_quantitativo(wb, res)
    _aba_auditoria(wb, res)
    _aba_avisos(wb, res)
    normalizar_alturas(wb)
    wb.save(caminho)
    return caminho


# ---------------------------------------------------------------------------
# Projeto: quadro de quantidades consolidado
# ---------------------------------------------------------------------------

def _aba_quadro(wb: Workbook, res_projeto) -> None:
    """O quadro de quantidades do projeto: uma linha por lance e os totais."""
    Q = res_projeto.quantitativo
    proj = res_projeto.projeto
    ws = wb.create_sheet("Quadro de quantidades")
    preparar_tabela(ws, [10.0, 26.0, 10.0, 12.0, 14.0, 14.0, 14.0, 14.0])
    linha = titulo(ws, 2, f"{proj.nome.upper()} — QUADRO DE QUANTIDADES",
                   col_fim=9)
    if proj.responsavel:
        linha = nota(ws, linha, f"Responsável técnico: {proj.responsavel}",
                     col_fim=9)
    linha = nota(ws, linha,
                 "Formas: apenas as faces laterais, as que contêm o concreto "
                 "fresco (todo o perímetro vertical, inclusive o dos vazios). "
                 "Cruzamentos com vigas e lajes não são descontados. Aço "
                 "longitudinal medido no lance mais o comprimento de espera.",
                 col_fim=9)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Pilar", "Seção", "Concreto", "h (cm)",
                                  "Volume", "Formas", "Aço", "Taxa"])
    for q in Q.itens:
        linha = linha_tabela(ws, linha, [
            q.nome, q.secao, q.concreto, q.altura, q.volume_concreto,
            q.area_formas, q.massa_aco, q.taxa_aco],
            [None, None, None, NF["inteiro"], NF["m3"], NF["m2"], NF["kg"],
             NF["kgm3"]])
    linha = linha_tabela(ws, linha, [
        "TOTAL", f"{len(Q.itens)} lance(s)", "", "",
        Q.volume_concreto, Q.area_formas, Q.massa_aco, Q.taxa_aco],
        [None, None, None, None, NF["m3"], NF["m2"], NF["kg"], NF["kgm3"]])

    linha = separador(ws, linha)
    linha = secao(ws, linha, "Aço por bitola — a lista de compra", col_fim=9)
    linha = cabecalho(ws, linha, ["Bitola", "Massa", "", "", "", "", "", ""])
    for phi, massa in Q.aco_por_bitola.items():
        linha = linha_tabela(ws, linha,
                             [f"ø{num(phi)} mm", massa, "", "", "", "", "", ""],
                             [None, NF["kg"]])
    linha = linha_tabela(ws, linha,
                         ["Total", Q.massa_aco, "", "", "", "", "", ""],
                         [None, NF["kg"]])

    linha = separador(ws, linha)
    linha = secao(ws, linha, "Concreto por classe", col_fim=9)
    linha = nota(ws, linha,
                 "Classes diferentes não se somam na compra: um total único "
                 "esconderia o traço.", col_fim=9)
    linha = cabecalho(ws, linha, ["Classe", "Volume", "", "", "", "", "", ""])
    for classe, volume in Q.concreto_por_classe.items():
        linha = linha_tabela(ws, linha,
                             [classe, volume, "", "", "", "", "", ""],
                             [None, NF["m3"]])


def _aba_resumo_projeto(wb: Workbook, res_projeto) -> None:
    """Um lance por linha: armadura, F.S. crítico e veredito."""
    ws = wb.create_sheet("Resumo do projeto")
    preparar_tabela(ws, [10.0, 24.0, 10.0, 22.0, 18.0, 12.0, 26.0])
    linha = titulo(ws, 2,
                   f"{res_projeto.projeto.nome.upper()} — RESUMO POR LANCE",
                   col_fim=8)
    linha = separador(ws, linha)
    linha = cabecalho(ws, linha, ["Pilar", "Seção", "Concreto", "Armadura",
                                  "Estribo", "F.S. mín.", "Veredito"])
    for r in res_projeto.resultados:
        fs = min((v.fs for v in r.verificacoes_z.values()), default=0.0)
        linha = linha_tabela(ws, linha, [
            r.pilar.nome, r.pilar.secao.descricao(),
            r.pilar.concreto.descricao(),
            r.arranjo.descricao() if r.arranjo else "—",
            r.estribos.descricao() if r.estribos else "—",
            fs if math.isfinite(fs) else "∞",
            "OK" if r.ok else f"{len(r.erros)} não atendida(s)"],
            [None, None, None, None, None, NF["coef"], None])
    for nome, erro in res_projeto.falhas.items():
        linha = linha_tabela(ws, linha,
                             [nome, "—", "—", "—", "—", "—",
                              f"não calculou: {erro}"])


def gerar_projeto(res_projeto, caminho: str) -> str:
    """Grava a planilha do **projeto**: quadro de quantidades e resumo.

    A memória de cálculo de cada lance continua saindo em planilha própria,
    por :func:`gerar` -- esta é a do conjunto, que é o que vai para orçamento
    e para compra.
    """
    wb = Workbook()
    wb.remove(wb.active)
    _aba_quadro(wb, res_projeto)
    _aba_resumo_projeto(wb, res_projeto)
    normalizar_alturas(wb)
    wb.save(caminho)
    return caminho
