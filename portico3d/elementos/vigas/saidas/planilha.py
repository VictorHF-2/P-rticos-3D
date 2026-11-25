# -*- coding: utf-8 -*-
"""
planilha.py
Exportação dos resultados em .xlsx no padrão de planilhas da Ecoplan.

As abas de flexão e de cisalhamento não são um despejo de números: trazem a
memória de cálculo com fórmulas vivas do Excel, na sequência da NBR 6118, de
modo que o projetista possa alterar um dado de entrada e ver o resultado
recalcular -- os valores de entrada aparecem em azul.
"""

from __future__ import annotations

from datetime import datetime

from openpyxl import Workbook

from .. import __norma__, __version__
from ..core import avisos as avisos_mod
from ..core.dimensionar import ResultadoViga
from .estilo_planilha import (COR, NF, cabecalho, expressao, grandeza,
                              legenda, linha_tabela, normalizar_alturas, nota,
                              preparar_memoria, preparar_tabela, secao,
                              separador, titulo, veredito)


def _celula(linha: int, coluna: int = 3) -> str:
    """Referência absoluta de uma célula da coluna de valores."""
    from openpyxl.utils import get_column_letter
    return f"${get_column_letter(coluna)}${linha}"


# ---------------------------------------------------------------------------
# Aba de dados
# ---------------------------------------------------------------------------

def _aba_dados(wb: Workbook, res: ResultadoViga,
               emitido_em: datetime | None = None) -> None:
    viga = res.viga
    cfg = viga.config
    ws = wb.create_sheet("DADOS")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {viga.nome} — DADOS DE ENTRADA")
    L = nota(ws, L, "ABNT NBR 6118 — Projeto de estruturas de concreto: "
                    "procedimento")
    L = separador(ws, L)

    L = secao(ws, L, "identificação")
    L = grandeza(ws, L, "Viga =", viga.nome, "(designação em projeto)",
                 NF["texto"], entrada=True)
    L = grandeza(ws, L, "Projeto =", viga.projeto or "-", "(obra)",
                 NF["texto"], entrada=True)
    L = grandeza(ws, L, "Programa =", f"Vigas {__version__}",
                 f"({__norma__})", NF["texto"])
    if emitido_em is not None:
        L = grandeza(ws, L, "Emitida em =", emitido_em.strftime("%d/%m/%Y %H:%M"),
                     "(data da emissão desta planilha)", NF["texto"])
    L = grandeza(ws, L, "Dados =", viga.impressao_digital(),
                 "(identificação dos dados de entrada; igual à da memória)",
                 NF["texto"])
    L = separador(ws, L)

    L = secao(ws, L, "geometria")
    for i, t in enumerate(viga.tramos):
        L = grandeza(ws, L, f"L{i + 1} =", t.L, f"(vão teórico do tramo "
                     f"{i + 1})", NF["m"], entrada=True)
        L = grandeza(ws, L, f"seção {i + 1} =", t.secao.descricao(),
                     "(seção transversal do tramo)", NF["texto"], entrada=True)
        L = grandeza(ws, L, "Ic =", t.secao.inercia,
                     "(inércia da seção bruta)", NF["cm4"])
    for i, a in enumerate(viga.apoios):
        L = grandeza(ws, L, f"apoio {i + 1} =", a.tipo,
                     f"(largura de {a.largura:g} cm)", NF["texto"],
                     entrada=True)
    L = separador(ws, L)

    L = secao(ws, L, "materiais")
    c, aco = viga.concreto, viga.aco
    L = grandeza(ws, L, "fck =", c.fck, "(resistência característica do "
                 "concreto)", NF["MPa"], entrada=True, referencia="NBR 6118, 8.2.4")
    L = grandeza(ws, L, "γc =", c.gamma_c, "(coeficiente de ponderação do "
                 "concreto)", NF["coef"], entrada=True, referencia="Tabela 12.1")
    L = grandeza(ws, L, "fcd =", c.fcd, "(resistência de cálculo à "
                 "compressão)", NF["MPa"], referencia="12.3.3")
    L = grandeza(ws, L, "fctm =", c.fctm, "(resistência média à tração)",
                 NF["MPa"], referencia="8.2.5")
    L = grandeza(ws, L, "fctk,inf =", c.fctk_inf, "(resistência à tração "
                 "inferior)", NF["MPa"], referencia="8.2.5")
    L = grandeza(ws, L, "Ecs =", c.Ecs, "(módulo de elasticidade secante)",
                 NF["MPa"], referencia="8.2.8")
    L = grandeza(ws, L, "εcu =", c.eps_cu, "(deformação última do concreto)",
                 NF["adm"], referencia="8.2.10.1")
    L = grandeza(ws, L, "aço =", aco.categoria, "(categoria do aço)",
                 NF["texto"], entrada=True, referencia="NBR 7480:2024")
    L = grandeza(ws, L, "fyd =", aco.fyd, "(resistência de cálculo do aço)",
                 NF["MPa"], referencia="8.3.6")
    L = grandeza(ws, L, "Es =", aco.Es, "(módulo de elasticidade do aço)",
                 NF["MPa"], referencia="8.3.5")
    L = separador(ws, L)

    L = secao(ws, L, "durabilidade")
    L = grandeza(ws, L, "CAA =", viga.ambiente.caa,
                 f"({viga.ambiente.descricao.lower()})", NF["texto"],
                 entrada=True, referencia="Tabela 6.1")
    L = grandeza(ws, L, "cnom =", viga.ambiente.cobrimento_nominal,
                 "(cobrimento nominal)", NF["cm"], referencia="Tabela 7.2")
    L = grandeza(ws, L, "wk,lim =", viga.ambiente.wk_limite,
                 "(abertura limite de fissuras)", NF["mm"],
                 referencia="Tabela 13.4")
    L = separador(ws, L)

    L = secao(ws, L, "carregamentos")
    for cd in viga.todas_distribuidas():
        acao = "permanente" if cd.acao == "g" else "variável"
        L = grandeza(ws, L, "q =", cd.q1,
                     f"({cd.descricao or 'carga distribuída'} — {acao}, de "
                     f"{cd.x_ini:g} a {cd.x_fim:g} m)", NF["kN"],
                     entrada=cd.acao != "g")
    for p in viga.concentradas:
        acao = "permanente" if p.acao == "g" else "variável"
        L = grandeza(ws, L, "P =", p.P,
                     f"({p.descricao or 'carga concentrada'} — {acao}, "
                     f"x = {p.x:g} m)", NF["kN"], entrada=True)
    L = separador(ws, L)

    L = secao(ws, L, "critérios adotados")
    L = grandeza(ws, L, "γg =", cfg.gamma_g, "(ponderação das ações "
                 "permanentes)", NF["coef"], entrada=True,
                 referencia="Tabela 11.1")
    L = grandeza(ws, L, "γq =", cfg.gamma_q, "(ponderação das ações "
                 "variáveis)", NF["coef"], entrada=True)
    L = grandeza(ws, L, "ψ1 / ψ2 =", f"{cfg.psi1:g} / {cfg.psi2:g}",
                 "(fatores de combinação de serviço)", NF["texto"],
                 entrada=True, referencia="Tabela 11.2")
    L = grandeza(ws, L, "modelo =", cfg.modelo_cisalhamento,
                 "(modelo de cálculo ao cisalhamento)", NF["inteiro"],
                 entrada=True, referencia="17.4.2")
    L = grandeza(ws, L, "θ =", cfg.theta, "(inclinação da biela)", NF["grau"],
                 entrada=True)
    L = grandeza(ws, L, "δ =", cfg.redistribuicao,
                 "(coeficiente de redistribuição)", NF["coef"], entrada=True,
                 referencia="14.6.4.3")
    L = separador(ws, L)
    legenda(ws, L, [
        ("azul", "valor de entrada, alterável pelo projetista"),
        ("preto", "valor calculado pelo programa"),
        ("ELU", "estado limite último"),
        ("ELS", "estado limite de serviço"),
    ])


# ---------------------------------------------------------------------------
# Aba de esforços
# ---------------------------------------------------------------------------

def _aba_esforcos(wb: Workbook, res: ResultadoViga) -> None:
    ws = wb.create_sheet("ESFORÇOS")
    preparar_tabela(ws, [16.0, 10.71, 14.0, 14.0, 40.0])
    L = 2
    L = titulo(ws, L, "ENVOLTÓRIAS E MOMENTOS DE DIMENSIONAMENTO", 2, 6)
    L = nota(ws, L, "Análise elástica pelo método da rigidez, com alternância "
                    "de carga acidental (item 14.6.7 da NBR 6118)", 2, 6)
    L = separador(ws, L)

    L = secao(ws, L, "momentos de dimensionamento — ELU", 2, 6)
    L = cabecalho(ws, L, ["Região", "x", "M da envoltória", "M de projeto",
                          "Observação"])
    for mp in res.momentos_projeto:
        nome = (f"Vão {mp.indice + 1}" if mp.regiao == "vao"
                else f"Apoio {mp.indice + 1}")
        L = linha_tabela(ws, L, [nome, mp.x, mp.M_bruto, mp.M,
                                 mp.observacao or "—"],
                         [None, NF["m"], NF["kNm"], NF["kNm"], None])
    L = separador(ws, L)

    L = secao(ws, L, "reações de apoio", 2, 6)
    L = cabecalho(ws, L, ["Apoio", "x", "R máxima", "R mínima",
                          "Momento de reação"])
    for r in res.reacoes:
        L = linha_tabela(ws, L, [f"A{r['apoio']}", r["x"], r["R_max"],
                                 r["R_min"], r["M_min"]],
                         [None, NF["m"], NF["kN"], NF["kN"], NF["kNm"]])
    L = separador(ws, L)

    L = secao(ws, L, "cortantes de projeto por tramo", 2, 6)
    L = cabecalho(ws, L, ["Tramo", "Vsd máx", "VRd2", "Vsd/VRd2", "Situação "
                          "da biela"])
    for i in range(len(res.viga.tramos)):
        a, b = res.viga.x_apoios[i], res.viga.x_apoios[i + 1]
        cs = [c for c in res.cortantes if a <= c.x <= b]
        if not cs:
            continue
        pior = max(cs, key=lambda c: c.Vsd)
        L = linha_tabela(ws, L, [f"Tramo {i + 1}", pior.Vsd, pior.VRd2,
                                 pior.razao_biela, pior.veredito],
                         [None, NF["kN"], NF["kN"], NF["coef3"], None],
                         cores=[None, None, None, None,
                                None if pior.biela_ok else COR["alerta"]])


# ---------------------------------------------------------------------------
# Aba de flexão (memória com fórmulas vivas)
# ---------------------------------------------------------------------------

def _bloco_flexao(ws, L: int, res: ResultadoViga, reg) -> int:
    viga = res.viga
    f = reg.flexao
    cob = viga.ambiente.cobrimento_nominal
    L = secao(ws, L, f"{reg.nome} — armadura {reg.face}")
    L = nota(ws, L, "(Conforme os itens 17.2.2, 17.3.5.2 e 14.6.4.3 da "
                    "NBR 6118)")

    l_md = L
    L = grandeza(ws, L, "Md =", abs(reg.M), "(momento de cálculo)", NF["kNm"],
                 entrada=True)
    l_bw = L
    L = grandeza(ws, L, "bw =", reg.secao.bw, "(largura da alma)", NF["cm"],
                 entrada=True)
    l_h = L
    L = grandeza(ws, L, "h =", reg.secao.h, "(altura da seção)", NF["cm"],
                 entrada=True)
    l_d = L
    L = grandeza(ws, L, "d =", reg.d, "(altura útil)", NF["cm"])
    l_dl = L
    L = grandeza(ws, L, "d' =", f.d_linha,
                 "(distância do centro da armadura comprimida à face)",
                 NF["cm"])
    l_fck = L
    L = grandeza(ws, L, "fck =", viga.concreto.fck, "(classe do concreto)",
                 NF["MPa"], entrada=True)
    l_gc = L
    L = grandeza(ws, L, "γc =", viga.concreto.gamma_c, "(ponderação do "
                 "concreto)", NF["coef"], entrada=True)
    l_fyd = L
    L = grandeza(ws, L, "fyd =", viga.aco.fyd_kNcm2, "(resistência de "
                 "cálculo do aço)", NF["kNcm2"])
    L = separador(ws, L)

    md, bw, h, d, dl = (_celula(l_md), _celula(l_bw), _celula(l_h),
                        _celula(l_d), _celula(l_dl))
    fck, gc, fyd = _celula(l_fck), _celula(l_gc), _celula(l_fyd)

    L = expressao(ws, L, "λ =", "0,8 para fck ≤ 50 MPa; 0,8 − (fck − 50)/400 "
                                "acima disso")
    l_lam = L
    L = grandeza(ws, L, "λ =", f"=IF({fck}<=50,0.8,0.8-({fck}-50)/400)",
                 "(relação y/x do bloco retangular)", NF["coef3"],
                 referencia="17.2.2")
    L = expressao(ws, L, "αc =", "0,85 para fck ≤ 50 MPa; "
                                 "0,85·(1 − (fck − 50)/200) acima disso")
    l_ac = L
    L = grandeza(ws, L, "αc =",
                 f"=IF({fck}<=50,0.85,0.85*(1-({fck}-50)/200))",
                 "(redução da tensão do bloco)", NF["coef3"],
                 referencia="17.2.2")
    l_nc = L
    L = grandeza(ws, L, "ηc =", f"=IF({fck}<=40,1,(40/{fck})^(1/3))",
                 "(fragilidade do concreto de alta resistência)", NF["coef3"],
                 referencia="17.2.2")
    L = expressao(ws, L, "σcd =", "αc · ηc · fck / γc")
    l_sig = L
    L = grandeza(ws, L, "σcd =",
                 f"={_celula(l_ac)}*{_celula(l_nc)}*{fck}/{gc}/10",
                 "(tensão do bloco retangular)", NF["kNcm2"])
    l_ecu = L
    L = grandeza(ws, L, "εcu =",
                 f"=IF({fck}<=50,0.0035,0.0026+0.035*((90-{fck})/100)^4)",
                 "(deformação última do concreto)", NF["adm"],
                 referencia="8.2.10.1")
    l_eyd = L
    L = grandeza(ws, L, "εyd =", f"={fyd}/21000", "(deformação de escoamento "
                 "do aço)", NF["adm"])
    l_x34 = L
    L = grandeza(ws, L, "x34/d =",
                 f"={_celula(l_ecu)}/({_celula(l_ecu)}+{_celula(l_eyd)})",
                 "(limite do domínio 3/4)", NF["coef3"])
    l_xlim = L
    L = grandeza(ws, L, "xlim/d =",
                 f"=MIN({_celula(l_x34)},IF({fck}<=50,0.45,0.35))",
                 "(limite de ductilidade adotado)", NF["coef3"],
                 referencia="14.6.4.3")
    l_ymax = L
    L = grandeza(ws, L, "ymax =",
                 f"={_celula(l_xlim)}*{d}*{_celula(l_lam)}",
                 "(altura máxima do bloco comprimido)", NF["cm"])
    L = expressao(ws, L, "Md,max =", "bw · ymax · σcd · (d − ymax/2)")
    l_mdmax = L
    L = grandeza(ws, L, "Md,max =",
                 f"={bw}*{_celula(l_ymax)}*{_celula(l_sig)}*"
                 f"({d}-{_celula(l_ymax)}/2)/100",
                 "(momento máximo com armadura simples)", NF["kNm"])
    L = expressao(ws, L, "y =", "d − √(d² − 2·Md/(bw·σcd))")
    l_y = L
    L = grandeza(ws, L, "y =",
                 f"=IF({md}>{_celula(l_mdmax)},{_celula(l_ymax)},"
                 f"{d}-SQRT({d}^2-200*{md}/{bw}/{_celula(l_sig)}))",
                 "(altura do bloco comprimido)", NF["cm"])
    l_xd = L
    L = grandeza(ws, L, "x/d =", f"={_celula(l_y)}/{_celula(l_lam)}/{d}",
                 "(posição relativa da linha neutra)", NF["coef3"])
    L = separador(ws, L)

    L = secao(ws, L, "armaduras")
    l_dm = L
    L = grandeza(ws, L, "ΔMd =", f"=MAX(0,{md}-{_celula(l_mdmax)})",
                 "(parcela resistida pela armadura dupla)", NF["kNm"])
    L = expressao(ws, L, "As =", "(bw · y · σcd + ΔMd/(d − d')) / fyd")
    l_as = L
    L = grandeza(ws, L, "As =",
                 f"=({bw}*{_celula(l_y)}*{_celula(l_sig)}+100*{_celula(l_dm)}"
                 f"/({d}-{dl}))/{fyd}",
                 "(armadura de tração calculada)", NF["cm2"])
    l_asmin = L
    L = grandeza(ws, L, "As,min =", f"={f.As_min / (reg.secao.area):.6f}*"
                 f"{bw}*{h}", "(armadura mínima)", NF["cm2"],
                 referencia="Tabela 17.3")
    l_asmax = L
    L = grandeza(ws, L, "As,max =", f"=0.04*{bw}*{h}",
                 "(armadura máxima)", NF["cm2"], referencia="17.3.5.2.4")
    l_asad = L
    L = grandeza(ws, L, "As,adotada =",
                 f"=MAX({_celula(l_as)},{_celula(l_asmin)})",
                 "(armadura de projeto)", NF["cm2"])
    if f.armadura_dupla:
        L = grandeza(ws, L, "σ's =", f.sigma2_liq,
                     "(tensão líquida da armadura comprimida)", NF["kNcm2"])
        L = grandeza(ws, L, "A's =", reg.flexao.As_linha,
                     "(armadura comprimida)", NF["cm2"])
    L = separador(ws, L)

    L = secao(ws, L, "verificações")
    L = veredito(ws, L, "x/d ≤ xlim/d ∴",
                 f'=IF({_celula(l_xd)}<={_celula(l_xlim)},"OK",'
                 f'"NÃO OK! Aumentar a altura ou usar armadura dupla.")',
                 "(ductilidade — 14.6.4.3)")
    L = veredito(ws, L, "As + A's ≤ As,max ∴",
                 f'=IF({_celula(l_asad)}<={_celula(l_asmax)},"OK",'
                 f'"NÃO OK! Excede 4 % de Ac.")',
                 "(armadura máxima — 17.3.5.2.4)")
    L = separador(ws, L)

    L = secao(ws, L, "detalhamento")
    arr = reg.arranjo
    l_n = L
    L = grandeza(ws, L, "nº de barras =", arr.n, "(quantidade adotada)",
                 NF["barras"], entrada=True)
    l_phi = L
    L = grandeza(ws, L, "Ø =", arr.phi, "(bitola adotada)", NF["bitola"],
                 entrada=True)
    l_asef = L
    L = grandeza(ws, L, "As,ef =",
                 f"={_celula(l_n)}*PI()*({_celula(l_phi)}/20)^2",
                 "(armadura efetivamente disposta)", NF["cm2"])
    L = grandeza(ws, L, "camadas =", len(arr.camadas),
                 f"({' + '.join(str(c) for c in arr.camadas)} barras)",
                 NF["inteiro"])
    L = grandeza(ws, L, "ah,min =", arr.ah, "(espaçamento livre horizontal "
                 "mínimo)", NF["cm"], referencia="18.3.2.2")
    L = veredito(ws, L, "As,ef ≥ As,adotada ∴",
                 f'=IF({_celula(l_asef)}>={_celula(l_asad)},"OK",'
                 f'"NÃO OK! Aumentar a bitola ou o número de barras.")')
    if reg.ancoragem:
        a = reg.ancoragem
        L = grandeza(ws, L, "fbd =", a.fbd,
                     f"({'boa' if a.boa_aderencia else 'má'} situação de "
                     f"aderência)", NF["kNcm2"], referencia="9.3.2.1")
        L = grandeza(ws, L, "lb =", a.lb, "(ancoragem básica)", NF["cm"],
                     referencia="9.4.2.4")
        L = grandeza(ws, L, "lb,nec =", a.lb_nec, "(ancoragem necessária)",
                     NF["cm"], referencia="9.4.2.5")
    L = separador(ws, L)
    L = grandeza(ws, L, "cnom =", cob, "(cobrimento nominal adotado)",
                 NF["cm"], referencia="Tabela 7.2")
    return separador(ws, L)


def _aba_flexao(wb: Workbook, res: ResultadoViga) -> None:
    ws = wb.create_sheet("FLEXÃO")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {res.viga.nome} — DIMENSIONAMENTO À FLEXÃO (ELU)")
    L = nota(ws, L, "Diagrama retangular equivalente; as células em azul são "
                    "de entrada e as demais recalculam a partir delas")
    L = separador(ws, L)
    for reg in res.regioes:
        if reg.construtiva:
            continue
        L = _bloco_flexao(ws, L, res, reg)


# ---------------------------------------------------------------------------
# Aba de cisalhamento
# ---------------------------------------------------------------------------

def _aba_cisalhamento(wb: Workbook, res: ResultadoViga) -> None:
    viga = res.viga
    cfg = viga.config
    ws = wb.create_sheet("CISALHAMENTO")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {viga.nome} — DIMENSIONAMENTO AO CISALHAMENTO")
    L = nota(ws, L, f"Modelo de cálculo {cfg.modelo_cisalhamento} do item "
                    f"17.4.2 da NBR 6118")
    L = separador(ws, L)

    for i in range(len(viga.tramos)):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        cs = [c for c in res.cortantes if a <= c.x <= b]
        if not cs:
            continue
        pior = max(cs, key=lambda c: c.Vsd)
        secao_t = viga.tramos[i].secao
        L = secao(ws, L, f"tramo {i + 1}")
        L = nota(ws, L, "(Conforme os itens 17.4.2 e 18.3.3.2 da NBR 6118)")
        l_v = L
        L = grandeza(ws, L, "Vsd =", pior.Vsd, "(cortante de cálculo na seção "
                     f"mais solicitada, x = {pior.x:.2f} m)", NF["kN"],
                     entrada=True)
        l_bw = L
        L = grandeza(ws, L, "bw =", secao_t.bw, "(largura da alma)", NF["cm"],
                     entrada=True)
        l_d = L
        L = grandeza(ws, L, "d =", pior.d, "(altura útil)", NF["cm"])
        l_fck = L
        L = grandeza(ws, L, "fck =", viga.concreto.fck, "(classe do "
                     "concreto)", NF["MPa"], entrada=True)
        l_fywd = L
        L = grandeza(ws, L, "fywd =", min(viga.aco.fyd_kNcm2, 43.5),
                     "(resistência da armadura transversal, limitada a "
                     "435 MPa)", NF["kNcm2"], referencia="17.4.2.2")
        L = separador(ws, L)

        v, bw, d = _celula(l_v), _celula(l_bw), _celula(l_d)
        fck, fywd = _celula(l_fck), _celula(l_fywd)
        L = expressao(ws, L, "αv2 =", "1 − fck / 250")
        l_av2 = L
        L = grandeza(ws, L, "αv2 =", f"=1-{fck}/250",
                     "(efetividade da biela)", NF["coef3"],
                     referencia="17.4.2.2")
        l_sb = L
        L = grandeza(ws, L, "αv2·fcd =",
                     f"={_celula(l_av2)}*{fck}/{viga.concreto.gamma_c}/10",
                     "(tensão limite da biela)", NF["kNcm2"])
        L = expressao(ws, L, "VRd2 =", "0,27 · αv2 · fcd · bw · d "
                                       "(Modelo I, biela a 45°)")
        l_vrd2 = L
        if cfg.modelo_cisalhamento == 1:
            formula = f"=0.27*{_celula(l_sb)}*{bw}*{d}"
        else:
            import math
            th = math.radians(cfg.theta)
            k = (0.54 * math.sin(th) ** 2 * (1 / math.tan(th)))
            formula = f"={k:.6f}*{_celula(l_sb)}*{bw}*{d}"
        L = grandeza(ws, L, "VRd2 =", formula, "(resistência da biela)",
                     NF["kN"], referencia="17.4.2.2")
        l_fctm = L
        L = grandeza(ws, L, "fctm =",
                     f"=IF({fck}>50,2.12*LN(1+0.11*{fck})/10,"
                     f"0.03*{fck}^(2/3))",
                     "(resistência média à tração)", NF["kNcm2"],
                     referencia="8.2.5")
        l_fctd = L
        L = grandeza(ws, L, "fctd =",
                     f"=0.7*{_celula(l_fctm)}/{viga.concreto.gamma_c}",
                     "(resistência de cálculo à tração)", NF["kNcm2"])
        l_vc = L
        L = grandeza(ws, L, "Vc =", f"=0.6*{_celula(l_fctd)}*{bw}*{d}",
                     "(parcela dos mecanismos complementares)", NF["kN"],
                     referencia="17.4.2.2")
        l_vsw = L
        L = grandeza(ws, L, "Vsw =", f"=MAX(0,{v}-{_celula(l_vc)})",
                     "(parcela resistida pelos estribos)", NF["kN"])
        L = expressao(ws, L, "Asw/s =", "Vsw / (0,9 · d · fywd) · 100")
        L = grandeza(ws, L, "Asw/s =",
                     f"={_celula(l_vsw)}/0.9/{d}/{fywd}*100",
                     "(armadura transversal calculada)", NF["cm2m"])
        L = expressao(ws, L, "Asw/s,min =", "0,2 · fctm / fywk · bw · 100")
        L = grandeza(ws, L, "Asw/s,min =",
                     f"=0.2*{_celula(l_fctm)}/{min(viga.aco.fyk, 500) / 10}*"
                     f"{bw}*100",
                     "(armadura transversal mínima)", NF["cm2m"],
                     referencia="17.4.1.1.1")
        L = grandeza(ws, L, "smax =",
                     f"=IF({v}/{_celula(l_vrd2)}<=2/3,MIN(0.6*{d},30),"
                     f"MIN(0.3*{d},20))",
                     "(espaçamento longitudinal máximo)", NF["cm"],
                     referencia="18.3.3.2")
        L = separador(ws, L)

        L = veredito(ws, L, "Vsd ≤ VRd2 ∴",
                     f'=IF({v}<={_celula(l_vrd2)},"OK",'
                     f'"NÃO OK! A biela esmaga: aumentar bw, h ou fck.")',
                     "(esmagamento da biela — 17.4.2.2)")
        zonas = [z for z in res.zonas_estribo if z.tramo == i]
        for z in zonas:
            L = grandeza(ws, L, "estribos =",
                         f"{z.n_estribos} Ø{z.phi:g} c/{z.s:g} cm",
                         f"(trecho de {z.x_ini:.2f} a {z.x_fim:.2f} m — "
                         f"Asw/s efetiva de {z.asw_ef:.2f} cm²/m)",
                         NF["texto"])
        L = separador(ws, L)


# ---------------------------------------------------------------------------
# Abas de serviço, detalhamento e quantitativo
# ---------------------------------------------------------------------------

def _aba_fadiga(wb: Workbook, res: ResultadoViga) -> None:
    """Estado-limite último de fadiga, quando o critério está ligado (23.5)."""
    if not res.fadigas and not res.fadigas_estribo:
        return
    viga = res.viga
    ws = wb.create_sheet("FADIGA")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {viga.nome} — ESTADO-LIMITE ÚLTIMO DE FADIGA")
    L = nota(ws, L, "Item 23.5 da NBR 6118: solicitação da combinação "
                    "frequente (23.5.2), tensões no Estádio II com alpha_e = "
                    "10, gamma_f = 1,0, gamma_c = 1,4 e gamma_s = 1,0 "
                    "(23.5.3)")
    L = separador(ws, L)

    for f in res.fadigas:
        L = secao(ws, L, f"{f.regiao} — flexão")
        L = grandeza(ws, L, "M frequente =", f.M_frequente,
                     "(combinação frequente, 23.5.2)", NF["kNm"],
                     entrada=True)
        L = grandeza(ws, L, "M permanente =", f.M_permanente,
                     "(parcela que não oscila)", NF["kNm"], entrada=True)
        L = grandeza(ws, L, "x II =", f.x_II,
                     "(linha neutra no Estádio II)", NF["cm"])
        L = grandeza(ws, L, "sigma s,máx =", f.sigma_s_max,
                     "(tensão na armadura, combinação frequente)", NF["MPa"])
        L = grandeza(ws, L, "sigma s,mín =", f.sigma_s_min,
                     "(tensão na armadura, só permanente)", NF["MPa"])
        l_ds = L
        L = grandeza(ws, L, "Delta sigma s =", f.delta_sigma_s,
                     "(variação de tensão na armadura)", NF["MPa"])
        l_lim = L
        L = grandeza(ws, L, "Delta fsd,fad =", f.delta_fsd_fad,
                     f"(Tabela 23.2, Ø{f.phi:g} mm)", NF["MPa"])
        L = veredito(ws, L, "Delta sigma s ≤ Delta fsd,fad ∴",
                     f'=IF({_celula(l_ds)}<={_celula(l_lim)},"OK",'
                     f'"NÃO OK! Aumentar a armadura ou reduzir a bitola.")',
                     "(fadiga da armadura — 23.5.5)")
        L = grandeza(ws, L, "eta c,grad =", f.eta_grad,
                     "(gradiente das tensões de compressão, 23.5.4.1)",
                     NF["adm"])
        L = grandeza(ws, L, "sigma c1 =", f.sigma_c1,
                     "(compressão a 30 cm da face, Figura 23.1)", NF["MPa"])
        L = grandeza(ws, L, "sigma c2 =", f.sigma_c_max,
                     "(compressão máxima na face)", NF["MPa"])
        l_sc = L
        L = grandeza(ws, L, "eta.sigma c,máx =", f.eta_grad * f.sigma_c_max,
                     "(compressão majorada pelo gradiente)", NF["MPa"])
        l_fcd = L
        L = grandeza(ws, L, "fcd,fad =", f.fcd_fad,
                     "(0,45 fcd, item 23.5.4.1)", NF["MPa"])
        L = veredito(ws, L, "eta.sigma c,máx ≤ fcd,fad ∴",
                     f'=IF({_celula(l_sc)}<={_celula(l_fcd)},"OK",'
                     f'"NÃO OK! Aumentar a seção ou o fck.")',
                     "(fadiga do concreto comprimido — 23.5.4.1)")
        if not f.fissurada:
            l_sct = L
            L = grandeza(ws, L, "sigma ct,máx =", f.sigma_ct_max,
                         "(seção não fissurada: a tração é verificada)",
                         NF["MPa"])
            l_fct = L
            L = grandeza(ws, L, "fctd,fad =", f.fctd_fad,
                         "(0,3 fctd, item 23.5.4.2)", NF["MPa"])
            L = veredito(ws, L, "sigma ct,máx ≤ fctd,fad ∴",
                         f'=IF({_celula(l_sct)}<={_celula(l_fct)},"OK",'
                         f'"NÃO OK! A seção fissura sob carga cíclica.")',
                         "(fadiga do concreto tracionado — 23.5.4.2)")
        L = separador(ws, L)

    for f in res.fadigas_estribo:
        L = secao(ws, L, f"estribo em x = {f.x:.2f} m")
        L = nota(ws, L, "O item 23.5.3 reduz a contribuição do concreto: Vc à "
                        "metade no Modelo I; no Modelo II corrige-se a biela "
                        "por tg theta,cor = raiz(tg theta)")
        L = grandeza(ws, L, "V frequente =", f.V_frequente,
                     "(cortante da combinação frequente)", NF["kN"],
                     entrada=True)
        L = grandeza(ws, L, "V permanente =", f.V_permanente,
                     "(parcela que não oscila)", NF["kN"], entrada=True)
        L = grandeza(ws, L, "Vc reduzido =", f.Vc_reduzido,
                     "(contribuição do concreto para fadiga)", NF["kN"])
        L = grandeza(ws, L, "theta =", f.theta,
                     "(inclinação da biela adotada)", NF["grau"])
        L = grandeza(ws, L, "Asw/s =", f.asw, "(armadura efetiva)",
                     NF["cm2m"])
        l_dsw = L
        L = grandeza(ws, L, "Delta sigma sw =", f.delta_sigma_s,
                     "(variação de tensão no estribo)", NF["MPa"])
        l_lsw = L
        L = grandeza(ws, L, "Delta fsd,fad =", f.delta_fsd_fad,
                     "(Tabela 23.2, barra dobrada)", NF["MPa"])
        L = veredito(ws, L, "Delta sigma sw ≤ Delta fsd,fad ∴",
                     f'=IF({_celula(l_dsw)}<={_celula(l_lsw)},"OK",'
                     f'"NÃO OK! Reduzir o espaçamento do estribo.")',
                     "(fadiga do estribo — 23.5.5)")
        L = separador(ws, L)


def _aba_ancoragem(wb: Workbook, res: ResultadoViga) -> None:
    """Ancoragem nos apoios de extremidade (18.3.2.4.1).

    Estes números eram calculados e não saíam em nenhuma saída: só o aviso
    aparecia, e só quando a ancoragem não cabia.
    """
    if not res.apoios_extremos:
        return
    ws = wb.create_sheet("ANCORAGEM")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {res.viga.nome} — ANCORAGEM NOS APOIOS DE "
                      f"EXTREMIDADE")
    L = separador(ws, L)
    L = nota(ws, L, "O item 18.3.2.4.1 exige, a partir da face do apoio, o "
                    "maior valor entre lb,nec (9.4.2.5), (r + 5,5 Ø) com o "
                    "raio da Tabela 9.1 e 60 mm")
    for a in res.apoios_extremos:
        L = secao(ws, L, f"apoio {a.apoio}")
        L = grandeza(ws, L, "Rsd =", a.Rsd,
                     "(força a ancorar, (al/d).Vsd)", NF["kN"], entrada=True)
        L = grandeza(ws, L, "As,nec =", a.As_necessaria,
                     "(armadura necessária para Rsd)", NF["cm2"])
        L = grandeza(ws, L, "As,ef =", a.As_efetiva,
                     "(armadura efetiva que chega ao apoio)", NF["cm2"])
        l_lbc = L
        L = grandeza(ws, L, "lb,nec =", a.lb_calculado,
                     "(item 9.4.2.5)", NF["cm"])
        l_piso = L
        L = grandeza(ws, L, "r + 5,5 Ø =", a.piso_gancho,
                     "(piso da Tabela 9.1)", NF["cm"])
        l_exig = L
        L = grandeza(ws, L, "exigido =", a.lb_nec,
                     f"(maior entre lb,nec, r + 5,5Ø e "
                     f"{anc_piso():g} cm)", NF["cm"])
        l_disp = L
        L = grandeza(ws, L, "disponível =", a.l_disponivel,
                     "(largura do apoio menos o cobrimento)", NF["cm"])
        L = veredito(ws, L, "exigido ≤ disponível ∴",
                     f'=IF({_celula(l_exig)}<={_celula(l_disp)},"OK",'
                     f'"NÃO OK! Alargar o pilar ou reduzir a bitola.")',
                     "(ancoragem no apoio — 18.3.2.4.1)")
        _ = (l_lbc, l_piso)
        L = separador(ws, L)


def anc_piso() -> float:
    """Piso absoluto da ancoragem no apoio, cm (18.3.2.4.1)."""
    from ..core.ancoragem import PISO_ANCORAGEM_APOIO
    return PISO_ANCORAGEM_APOIO


def _aba_avisos(wb: Workbook, res: ResultadoViga) -> None:
    """Avisos do cálculo, separados em erros e observações construtivas.

    A classificação já existia na tela e na memória; faltava na planilha, que
    era a única saída em que os dois se misturavam.
    """
    ws = wb.create_sheet("AVISOS")
    preparar_memoria(ws)
    erros, construtivos = avisos_mod.separar(res.avisos)
    L = 2
    L = titulo(ws, L, f"VIGA {res.viga.nome} — AVISOS DO CÁLCULO")
    L = nota(ws, L, "Erro de verificação: alguma verificação não foi atendida "
                    "ou um dado de entrada está inconsistente. Aviso "
                    "construtivo: decisão de detalhamento declarada pelo "
                    "programa, sem indicar erro")
    L = separador(ws, L)

    L = secao(ws, L, f"erros de verificação ({len(erros)})")
    if not erros:
        L = nota(ws, L, "Nenhum: todas as verificações consideradas foram "
                        "atendidas.")
    else:
        for a in erros:
            L = nota(ws, L, f"ERRO — {a}")
    L = separador(ws, L)

    L = secao(ws, L, f"avisos construtivos ({len(construtivos)})")
    if not construtivos:
        L = nota(ws, L, "Nenhum.")
    else:
        for a in construtivos:
            L = nota(ws, L, str(a))


def _aba_torcao(wb: Workbook, res: ResultadoViga) -> None:
    """Memória da torção, um bloco por tramo, quando houver torçor."""
    if not res.torcoes:
        return
    viga = res.viga
    ws = wb.create_sheet("TORÇÃO")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"VIGA {viga.nome} — DIMENSIONAMENTO À TORÇÃO (ELU)")
    L = nota(ws, L, "Treliça espacial generalizada do item 17.5 da NBR 6118, "
                    "com verificação conjunta da biela pelo item 17.7.2.2")
    L = separador(ws, L)

    for i in range(len(viga.tramos)):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        ts = [t for t in res.torcoes if a <= t.x <= b]
        if not ts:
            continue
        t = max(ts, key=lambda t: t.interacao)
        g = t.geometria
        L = secao(ws, L, f"tramo {i + 1}")
        L = nota(ws, L, "(Conforme os itens 17.5.1 e 17.7.2.2 da NBR 6118)")
        L = grandeza(ws, L, "Tsd =", t.Tsd, f"(torçor de cálculo na seção "
                     f"crítica, x = {t.x:.2f} m)", NF["kNm"], entrada=True)
        L = grandeza(ws, L, "Vsd =", t.Vsd, "(cortante concomitante)",
                     NF["kN"])
        L = grandeza(ws, L, "he =", g.he, "(espessura da parede equivalente)",
                     NF["cm"], referencia="17.5.1.4.1")
        L = grandeza(ws, L, "c2 =", g.c2, "(distância do eixo da parede à "
                     "face)", NF["cm"], referencia="17.5.1.4.1")
        L = grandeza(ws, L, "Ae =", g.Ae, "(área limitada pela linha média "
                     "da parede)", NF["cm2"], referencia="17.5.1.4.1")
        L = grandeza(ws, L, "ue =", g.ue, "(perímetro de Ae)", NF["cm"])
        L = grandeza(ws, L, "θ =", t.theta, "(inclinação da biela)",
                     NF["grau"], entrada=True)
        L = grandeza(ws, L, "TRd2 =", t.TRd2, "(resistência da biela à "
                     "torção)", NF["kNm"], referencia="17.5.1.5")
        L = grandeza(ws, L, "A90/s =", t.a90, "(armadura transversal de "
                     "torção, um ramo)", NF["cm2m"], referencia="17.5.1.6")
        L = grandeza(ws, L, "A90/s,mín =", t.a90_min, "(mínima)", NF["cm2m"],
                     referencia="17.5.1.6")
        L = grandeza(ws, L, "Asl =", t.Asl, "(armadura longitudinal de "
                     "torção, distribuída no perímetro)", NF["cm2"],
                     referencia="17.5.1.6")
        L = grandeza(ws, L, "Asw/s total =", t.a_transversal,
                     "(2.A90/s + Asw/s do cortante)", NF["cm2m"],
                     referencia="17.7.2.2")
        L = veredito(ws, L, "Tsd/TRd2 + Vsd/VRd2 ≤ 1 ∴",
                     f'=IF({t.interacao:.6f}<=1,"OK",'
                     f'"NÃO OK! A biela esmaga: aumentar a seção.")',
                     f"(interação = {t.interacao:.3f} — 17.7.2.2)")
        L = separador(ws, L)


def _aba_els(wb: Workbook, res: ResultadoViga) -> None:
    if not res.flechas and not any(r.fissuracao for r in res.regioes):
        return
    ws = wb.create_sheet("ELS")
    preparar_tabela(ws, [12.0, 11.0, 9.0, 13.0, 12.0, 12.0, 13.0, 12.0, 30.0])
    L = 2
    L = titulo(ws, L, "VERIFICAÇÕES DE SERVIÇO", 2, 10)
    L = nota(ws, L, "Deformação excessiva (17.3.2) e abertura de fissuras "
                    "(17.3.3) — limites das Tabelas 13.3 e 13.4", 2, 10)
    L = separador(ws, L)

    if res.flechas:
        L = secao(ws, L, "deformação excessiva — combinação quase permanente",
                  2, 10, COR["els"])
        L = cabecalho(ws, L, ["Tramo", "Ieq/Ic", "αf", "f imediata",
                              "f total", "L/250", "f após alvenaria",
                              "L/500", "Situação"])
        for f in res.flechas:
            L = linha_tabela(ws, L, [
                f"Tramo {f.tramo + 1}", f.I_eq / f.I_bruta, f.alfa_f,
                f.f_imediata, f.f_total, f.limite_visual,
                f.f_apos_alvenaria, f.limite_alvenaria, f.veredito],
                [None, NF["coef3"], NF["coef"], NF["cm"], NF["cm"], NF["cm"],
                 NF["cm"], NF["cm"], None],
                cores=[None] * 8 + [None if f.ok_visual and f.ok_alvenaria
                                    else COR["alerta"]])
        L = separador(ws, L)

    fiss = [r for r in res.regioes if r.fissuracao is not None]
    if fiss:
        L = secao(ws, L, "abertura de fissuras — combinação frequente", 2, 10,
                  COR["els"])
        L = cabecalho(ws, L, ["Região", "M de serviço", "xII", "σs", "ρri",
                              "wk1", "wk2", "wk", "wk limite / situação"])
        for r in fiss:
            w = r.fissuracao
            L = linha_tabela(ws, L, [
                r.nome, w.M_servico, w.x_II, w.sigma_s, w.rho_ri, w.wk_1,
                w.wk_2, w.wk, f"{w.wk_limite:.2f} mm — {w.veredito}"],
                [None, NF["kNm"], NF["cm"], NF["kNcm2"], NF["adm"], NF["mm"],
                 NF["mm"], NF["mm"], None],
                cores=[None] * 8 + [None if w.ok else COR["alerta"]])


def _aba_detalhamento(wb: Workbook, res: ResultadoViga) -> None:
    ws = wb.create_sheet("DETALHAMENTO")
    preparar_tabela(ws, [7.0, 14.0, 8.71, 10.71, 11.0, 10.71, 10.71, 11.0,
                         11.0, 40.0])
    L = 2
    L = titulo(ws, L, "RESUMO DAS POSIÇÕES DE ARMADURA", 2, 11)
    L = nota(ws, L, "Escalonamento com decalagem aℓ (17.4.2.2) e ancoragem "
                    "lb,nec (9.4.2.5)", 2, 11)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Pos.", "Tipo", "Qtd", "Bitola", "Face",
                          "x inicial", "x final", "Comprimento",
                          "Comprimento total", "Descrição"])
    for p in res.posicoes:
        L = linha_tabela(ws, L, [
            f"N{p.numero}", p.tipo, p.texto_quantidade, p.phi, p.face,
            p.x_ini, p.x_fim,
            p.comprimento, p.comprimento_total, p.descricao],
            [None, None, None, NF["bitola"], None, NF["m"], NF["m"],
             NF["cm"], NF["m"], None])


def _aba_quantitativo(wb: Workbook, res: ResultadoViga) -> None:
    ws = wb.create_sheet("QUANTITATIVO")
    preparar_tabela(ws, [14.0, 14.0, 16.0, 14.0, 16.0])
    L = 2
    L = titulo(ws, L, "QUANTITATIVO DE AÇO", 2, 6)
    L = nota(ws, L, "Massas nominais da Tabela 4 da NBR 7480:2024", 2, 6)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Bitola", "Nº de barras", "Comprimento total",
                          "Massa", "Massa + 10 % de perdas"])
    q = res.quantitativo
    for phi, d in q["por_bitola"].items():
        L = linha_tabela(ws, L, [phi, d["barras"], d["comprimento"],
                                 d["massa"], d["massa"] * 1.10],
                         [NF["bitola"], NF["inteiro"], NF["m"], NF["kg"],
                          NF["kg"]])
    L = linha_tabela(ws, L, ["TOTAL", "", "", q["massa_total"],
                             q["massa_com_perdas"]],
                     [None, None, None, NF["kg"], NF["kg"]])
    L = separador(ws, L)
    L = secao(ws, L, "consumo de concreto e formas", 2, 6)
    L = nota(ws, L, q["hipotese_forma"], 2, 6)
    L = cabecalho(ws, L, ["Trecho", "Seção", "Comprimento", "Volume",
                          "Área de forma"])
    # por TRECHO, não por tramo: é o trecho que tem seção constante. Somar
    # pelo tramo usa a seção do início dele em toda a extensão e erra o
    # volume onde há mudança de seção dentro do vão
    for d in q["por_trecho"]:
        L = linha_tabela(
            ws, L,
            [f"Trecho {d['trecho']} (tramo {d['tramo']})", d["secao"],
             d["L"], d["volume"], d["forma"]],
            [None, None, NF["m"], '0.000\\ "m³"', '0.00\\ "m²"'])
    L = linha_tabela(ws, L, ["TOTAL", "", q["comprimento"], q["concreto_m3"],
                             q["forma_m2"]],
                     [None, None, NF["m"], '0.000\\ "m³"', '0.00\\ "m²"'])
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Indicador", "Valor", "", "", ""])
    L = linha_tabela(ws, L, ["Taxa de aço", f"{q['taxa_aco']:.1f} kg/m³",
                             "", "", ""])
    L = linha_tabela(ws, L, ["Forma por m³ de concreto",
                             f"{q['forma_m2'] / q['concreto_m3']:.1f} m²/m³"
                             if q["concreto_m3"] > 0 else "-", "", "", ""])


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def _abas_da_viga(wb: Workbook, res: ResultadoViga,
                  emitido_em: datetime | None = None) -> None:
    """As abas de uma viga, na ordem de sempre."""
    _aba_dados(wb, res, emitido_em)
    _aba_esforcos(wb, res)
    _aba_flexao(wb, res)
    _aba_cisalhamento(wb, res)
    _aba_torcao(wb, res)
    _aba_fadiga(wb, res)
    _aba_ancoragem(wb, res)
    _aba_els(wb, res)
    _aba_detalhamento(wb, res)
    from .aberturas import aba_planilha     # furos na alma (13.2.5, 21.3)
    aba_planilha(wb, res)
    _aba_quantitativo(wb, res)
    _aba_avisos(wb, res)


def gerar(res: ResultadoViga, caminho: str,
          emitido_em: datetime | None = None) -> str:
    """Grava a planilha de resultados e devolve o caminho do arquivo."""
    return gerar_varias([res], caminho, emitido_em)


#: o Excel limita o nome da aba a 31 caracteres e proíbe estes
_PROIBIDOS_NA_ABA = set("[]:*?/\\")
#: a maior aba é "CISALHAMENTO" (12) mais o espaço: sobram 18 para a viga
_LARGURA_PREFIXO = 18
#: uma cor de etiqueta por viga, para o olho achar onde cada uma começa
_CORES_ABA = ("1F4E79", "2E7D4F", "9A6A00", "7B3F98", "A5232F", "00798C")


def _prefixos_das_abas(resultados) -> list[str]:
    """Um prefixo curto, válido e único por viga: ``V1``, ``V2``..."""
    usados: set[str] = set()
    saida = []
    for k, res in enumerate(resultados):
        base = "".join(c for c in res.viga.nome if c not in _PROIBIDOS_NA_ABA)
        base = base.strip()[:_LARGURA_PREFIXO].strip() or f"Viga {k + 1}"
        nome = base
        if nome.lower() in usados:           # o Excel ignora a caixa
            sufixo = f"~{k + 1}"
            nome = base[:_LARGURA_PREFIXO - len(sufixo)] + sufixo
        usados.add(nome.lower())
        saida.append(nome)
    return saida


def _aba_resumo(wb: Workbook, resultados, prefixos: list[str]) -> None:
    """Todas as vigas lado a lado: uma coluna por viga, uma linha por número.

    É a aba que responde "como as vigas se comparam" sem abrir cada uma. As
    grandezas aditivas (aço, concreto, forma) ganham uma coluna de total com
    fórmula viva do Excel.
    """
    n = len(resultados)
    ws = wb.create_sheet("RESUMO", 0)
    preparar_tabela(ws, [30.0] + [15.0] * n + [15.0])
    ultima = 2 + n                    # coluna do total (B é o indicador)
    L = 2
    L = titulo(ws, L, "RESUMO DAS VIGAS — LADO A LADO", 2, ultima)
    L = nota(ws, L, "Uma coluna por viga; os detalhes de cada uma estão nas "
                    "abas com o nome dela.", 2, ultima)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["Indicador"] + [r.viga.nome for r in resultados]
                  + ["Total"])
    from openpyxl.utils import get_column_letter
    c0, c1 = get_column_letter(3), get_column_letter(2 + n)

    def linha(rotulo, valor, formato=None, soma=False):
        nonlocal L
        valores = [rotulo] + [valor(r) for r in resultados]
        formatos = [None] + [formato] * n
        if soma:
            valores.append(f"=SUM({c0}{L}:{c1}{L})")
            formatos.append(formato)
        else:
            valores.append("")
            formatos.append(None)
        L = linha_tabela(ws, L, valores, formatos)

    linha("Aba", lambda r: prefixos[resultados.index(r)])
    linha("Projeto", lambda r: r.viga.projeto or "-")
    linha("Tramos", lambda r: len(r.viga.tramos), NF["inteiro"])
    linha("Comprimento (m)", lambda r: r.viga.comprimento, NF["m"])
    linha("Concreto", lambda r: r.viga.concreto.classe)
    linha("Aço", lambda r: r.viga.aco.categoria)
    linha("Agressividade (CAA)", lambda r: r.viga.ambiente.caa)
    linha("Posições de armadura", lambda r: len(r.posicoes), NF["inteiro"],
          soma=True)
    linha("Aço (kg)", lambda r: r.quantitativo["massa_total"], NF["kg"],
          soma=True)
    linha("Aço + 10 % de perdas (kg)",
          lambda r: r.quantitativo["massa_com_perdas"], NF["kg"], soma=True)
    linha("Concreto (m³)", lambda r: r.quantitativo["concreto_m3"],
          '0.000\\ "m³"', soma=True)
    linha("Forma (m²)", lambda r: r.quantitativo["forma_m2"],
          '0.00\\ "m²"', soma=True)
    linha("Taxa de aço (kg/m³)", lambda r: r.quantitativo["taxa_aco"],
          NF["kg"])
    linha("Situação",
          lambda r: "ATENDE" if r.ok else "NÃO ATENDE — VER AVISOS")


def gerar_varias(resultados, caminho: str,
                 emitido_em: datetime | None = None) -> str:
    """Grava num .xlsx só as vigas de ``resultados``.

    Com uma viga é a planilha de sempre, aba por aba. Com várias, entra uma aba
    ``RESUMO`` (as vigas lado a lado) e as abas de cada viga vêm em grupo, com
    o nome dela como prefixo e uma cor de etiqueta própria: ``V1 DADOS``,
    ``V1 FLEXÃO``, ... ``V2 DADOS``.
    """
    resultados = list(resultados)
    if not resultados:
        raise ValueError("Nenhuma viga para exportar.")
    emitido_em = emitido_em or datetime.now()
    wb = Workbook()
    wb.remove(wb.active)
    varias = len(resultados) > 1
    prefixos = _prefixos_das_abas(resultados) if varias else []
    for k, res in enumerate(resultados):
        antes = len(wb.worksheets)
        _abas_da_viga(wb, res, emitido_em)
        if varias:
            for ws in wb.worksheets[antes:]:
                ws.title = f"{prefixos[k]} {ws.title}"
                ws.sheet_properties.tabColor = _CORES_ABA[k % len(_CORES_ABA)]
    if varias:
        _aba_resumo(wb, resultados, prefixos)
    normalizar_alturas(wb)
    wb.save(caminho)
    return caminho
