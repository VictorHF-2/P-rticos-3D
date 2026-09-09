# -*- coding: utf-8 -*-
"""
planilha.py
Exportação dos resultados em .xlsx no padrão de planilhas da Ecoplan.

As abas de esforços, flexão e serviço não são um despejo de números: trazem a
memória de cálculo com **fórmulas vivas** do Excel, na sequência da apostila,
de modo que o projetista possa alterar um dado de entrada -- em azul -- e ver
tudo recalcular. É o que permite conferir o programa contra a planilha que ele
já usa, célula por célula.

Uma aba por laje nas contas passo a passo, e abas consolidadas para as bordas
comuns, as reações, o detalhamento, o quantitativo e os avisos.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from ..core import avisos as avisos_mod
from ..core.esforcos import BORDOS_DA_DIRECAO
from . import auditoria
from .estilo_planilha import (COR, NF, cabecalho, expressao, grandeza,
                              legenda, linha_tabela, normalizar_alturas, nota,
                              preparar_memoria, preparar_tabela, secao,
                              separador, titulo, veredito)


def _cel(linha: int, coluna: int = 3) -> str:
    """Referência absoluta de uma célula da coluna de valores."""
    return f"${get_column_letter(coluna)}${linha}"


#: Largura das colunas de tabela que convivem com o layout de memória na
#: mesma aba. O layout vertical usa B a F; as tabelas dessas abas vão além, e
#: sem estas larguras as células de número com unidade saem como "####".
LARGURAS_TABELA_NA_MEMORIA = {"D": 14.0, "E": 13.0, "F": 13.0, "G": 15.0,
                              "H": 15.0, "I": 15.0, "J": 17.0, "K": 15.0,
                              "L": 14.0, "M": 14.0}


def _alargar(ws, larguras: dict | None = None) -> None:
    """Amplia as colunas em que as tabelas da aba de memória escrevem."""
    for col, larg in (larguras or LARGURAS_TABELA_NA_MEMORIA).items():
        atual = ws.column_dimensions[col].width or 0.0
        ws.column_dimensions[col].width = max(atual, larg)


def _nome_aba(nome: str, sufixo: str = "") -> str:
    """Nome de aba do Excel: no máximo 31 caracteres e sem os proibidos."""
    limpo = "".join(c for c in nome if c not in "[]:*?/\\")
    base = f"{limpo}{(' ' + sufixo) if sufixo else ''}"
    return base[:31]


# ---------------------------------------------------------------------------
# Aba de dados
# ---------------------------------------------------------------------------

def _aba_dados(wb: Workbook, res) -> None:
    pav = res.pavimento
    cfg = pav.config
    ws = wb.create_sheet("DADOS")
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"{pav.nome.upper()} — DADOS DE ENTRADA")
    L = nota(ws, L, "ABNT NBR 6118 e Projeto de lajes maciças de concreto "
                    "armado (A. Campos Filho, DECIV/UFRGS, 2014)")
    L = separador(ws, L)

    L = secao(ws, L, "identificação")
    L = grandeza(ws, L, "Pavimento =", pav.nome, "(designação em projeto)",
                 NF["texto"], entrada=True)
    L = grandeza(ws, L, "Projeto =", pav.projeto or "-", "(obra)",
                 NF["texto"], entrada=True)
    L = grandeza(ws, L, "n de lajes =", len(res.lajes), "(no pavimento)",
                 NF["inteiro"])
    L = grandeza(ws, L, "área total =", res.area_total,
                 "(soma das áreas efetivas)", '0.00\\ "m²"')
    L = separador(ws, L)

    L = secao(ws, L, "materiais")
    L = grandeza(ws, L, "fck =", pav.concreto.fck, "(classe do concreto)",
                 NF["MPa"], entrada=True, referencia="8.2.1")
    L = grandeza(ws, L, "gamma_c =", pav.concreto.gamma_c,
                 "(ponderador do concreto)", NF["coef"], entrada=True,
                 referencia="12.4.1")
    L = grandeza(ws, L, "agregado =", pav.concreto.agregado,
                 "(define alfa_E)", NF["texto"], entrada=True,
                 referencia="8.2.8")
    L = grandeza(ws, L, "fcd =", pav.concreto.fcd, "(fck / gamma_c)",
                 NF["MPa"])
    L = grandeza(ws, L, "fctm =", pav.concreto.fctm,
                 "(resistência média à tração)", NF["MPa"],
                 referencia="8.2.5")
    L = grandeza(ws, L, "fctk,sup =", pav.concreto.fctk_sup,
                 "(1,3 fctm)", NF["MPa"], referencia="8.2.5")
    L = grandeza(ws, L, "Eci =", pav.concreto.Eci,
                 "(módulo tangente inicial)", NF["MPa"], referencia="8.2.8")
    L = grandeza(ws, L, "Ecs =", pav.concreto.Ecs,
                 "(módulo secante, alfa_i . Eci)", NF["MPa"],
                 referencia="8.2.8")
    L = grandeza(ws, L, "alfa_c =", pav.concreto.alfa_c,
                 "(bloco retangular)", NF["coef3"], referencia="17.2.2")
    L = grandeza(ws, L, "lambda =", pav.concreto.lambda_, "(y / x)",
                 NF["coef3"], referencia="17.2.2")
    L = grandeza(ws, L, "x/d limite =", pav.concreto.x_sobre_d_limite,
                 "(ductilidade no regime rígido-plástico)", NF["coef3"],
                 referencia="14.6.4.3")
    L = grandeza(ws, L, "aço =", pav.aco.categoria, "(categoria)",
                 NF["texto"], entrada=True)
    L = grandeza(ws, L, "fyd =", pav.aco.fyd, "(fyk / gamma_s)", NF["MPa"])
    L = separador(ws, L)

    L = secao(ws, L, "durabilidade")
    L = grandeza(ws, L, "CAA =", pav.ambiente.caa,
                 f"({pav.ambiente.descricao})", NF["texto"], entrada=True,
                 referencia="Tabela 6.1")
    L = grandeza(ws, L, "c inferior =", pav.ambiente.cobrimento_nominal,
                 "(cobrimento nominal da face inferior)", NF["cm"],
                 referencia="Tabela 7.2")
    L = grandeza(ws, L, "c superior =",
                 pav.ambiente.cobrimento_superior(cfg.bitola_minima_negativa),
                 "(face revestida: 15 mm, nunca menor que a bitola)",
                 NF["cm"], referencia="7.4.7.5")
    L = separador(ws, L)

    L = secao(ws, L, "critérios de cálculo")
    L = grandeza(ws, L, "gamma_g =", cfg.gamma_g, "(ações permanentes)",
                 NF["coef"], entrada=True, referencia="11.7.1")
    L = grandeza(ws, L, "gamma_q =", cfg.gamma_q, "(ações variáveis)",
                 NF["coef"], entrada=True, referencia="11.7.1")
    L = grandeza(ws, L, "psi_0 =", cfg.psi_0, "(variável secundária no ELU)",
                 NF["coef"], entrada=True, referencia="Tabela 11.2")
    L = grandeza(ws, L, "psi_2 =", cfg.psi_2, "(combinação quase permanente)",
                 NF["coef"], entrada=True, referencia="Tabela 11.2")
    L = grandeza(ws, L, "1 + alfa_f =", cfg.fator_fluencia,
                 "(flecha diferida, t0 = 1 mês)", NF["coef"], entrada=True,
                 referencia="17.3.2.1.2")
    L = grandeza(ws, L, "divisor da flecha =", cfg.divisor_flecha,
                 "(L / divisor; balanço usa "
                 f"{cfg.divisor_flecha_balanco})", NF["inteiro"],
                 entrada=True, referencia="Tabela 13.3")
    L = grandeza(ws, L, "compatibilização =", cfg.compatibilizacao,
                 "(momentos negativos das bordas comuns)", NF["texto"],
                 entrada=True, referencia="14.7.6.2")
    L = separador(ws, L)

    L = secao(ws, L, "geometria das lajes")
    L = cabecalho(ws, L, ["laje", "a (m)", "b (m)", "h (cm)", "a,ef", "b,ef",
                          "b/a", "bordo 1", "bordo 2", "bordo 3", "bordo 4"])
    for rl in res.lajes:
        laje = rl.laje
        L = linha_tabela(ws, L, [
            laje.nome, laje.a, laje.b, laje.h, laje.a_ef, laje.b_ef,
            laje.b_ef / laje.a_ef,
            *[laje.bordos[k].vinculo for k in range(4)]],
            [NF["texto"], NF["m"], NF["m"], NF["cm"], NF["m"], NF["m"],
             NF["coef3"], NF["texto"], NF["texto"], NF["texto"],
             NF["texto"]])
    _alargar(ws, {"D": 11.0, "E": 11.0, "F": 11.0, "G": 11.0, "H": 11.0,
                  "I": 14.0, "J": 14.0, "K": 14.0, "L": 14.0})
    L = separador(ws, L)
    L = legenda(ws, L, [
        ("a", "menor vão livre; b, o maior"),
        ("bordos", "numerados no contorno a partir de um bordo de "
                   "comprimento a, logo os bordos 1 e 3 medem a e os 2 e 4 "
                   "medem b"),
        ("azul", "dado de entrada: alterar recalcula as abas de memória")])


# ---------------------------------------------------------------------------
# Aba de memória por laje
# ---------------------------------------------------------------------------

def _aba_laje(wb: Workbook, res, rl) -> None:
    """Memória de cálculo de uma laje, com fórmulas vivas."""
    laje, esf, cls = rl.laje, rl.esforcos, rl.esforcos.classificacao
    pav = res.pavimento
    cfg = pav.config
    ws = wb.create_sheet(_nome_aba(laje.nome))
    preparar_memoria(ws)
    L = 2
    L = titulo(ws, L, f"LAJE {laje.nome.upper()} — MEMÓRIA DE CÁLCULO")
    L = nota(ws, L, cls.motivo)
    L = separador(ws, L)

    # -- geometria e cargas, as células de entrada -------------------------
    L = secao(ws, L, "geometria")
    lin_a = L
    L = grandeza(ws, L, "a =", laje.a_ef, "(menor vão efetivo)", NF["m"],
                 entrada=True, referencia="14.7.2.2")
    lin_b = L
    L = grandeza(ws, L, "b =", laje.b_ef, "(maior vão efetivo)", NF["m"],
                 entrada=True, referencia="14.7.2.2")
    lin_h = L
    L = grandeza(ws, L, "h =", laje.h, "(espessura)", NF["cm"], entrada=True,
                 referencia="13.2.4.1")
    lin_ab = L
    L = grandeza(ws, L, "a/b =", f"={_cel(lin_a)}/{_cel(lin_b)}",
                 "(relação entre os lados)", NF["coef3"])
    L = separador(ws, L)

    L = secao(ws, L, "cargas")
    lin_g = L
    L = grandeza(ws, L, "g =", laje.g_total,
                 "(permanente, com as paredes espalhadas)", '0.00\\ "kN/m²"',
                 entrada=True)
    lin_q = L
    L = grandeza(ws, L, "q =", laje.variavel, "(variável)",
                 '0.00\\ "kN/m²"', entrada=True, referencia="NBR 6120")
    lin_gg = L
    L = grandeza(ws, L, "gamma_g =", cfg.gamma_g, "(ponderador)", NF["coef"],
                 entrada=True)
    lin_gq = L
    L = grandeza(ws, L, "gamma_q =", cfg.gamma_q, "(ponderador)", NF["coef"],
                 entrada=True)
    lin_psi2 = L
    L = grandeza(ws, L, "psi_2 =", cfg.psi_2, "(quase permanente)",
                 NF["coef"], entrada=True)
    lin_pd = L
    L = grandeza(ws, L, "p_d =",
                 f"={_cel(lin_gg)}*{_cel(lin_g)}+{_cel(lin_gq)}*"
                 f"{_cel(lin_q)}", "(carga de cálculo)", '0.00\\ "kN/m²"')
    lin_pser = L
    L = grandeza(ws, L, "p_ser =",
                 f"={_cel(lin_g)}+{_cel(lin_psi2)}*{_cel(lin_q)}",
                 "(combinação quase permanente)", '0.00\\ "kN/m²"',
                 referencia="11.8.3.2")
    L = separador(ws, L)

    # -- esforços -----------------------------------------------------------
    if cls.em_cruz:
        L = secao(ws, L, "momentos no elu — linhas de ruptura (§3.2)")
        graus = laje.graus
        lin_i = []
        for k in range(4):
            lin_i.append(L)
            L = grandeza(ws, L, f"i{k + 1} =", graus[k],
                         f"(grau de engastamento do bordo {k + 1})",
                         NF["coef"], entrada=True, referencia="§3.2")
        lin_phi = L
        if esf.isotropa:
            L = grandeza(ws, L, "phi =", 1.0,
                         "(a/b >= 0,80: laje isótropa, ma = mb)", NF["coef3"],
                         referencia="§3.2 a.1")
        else:
            L = expressao(ws, L, "phi =",
                          "[(12 - i2 - i4)/(12 - i1 - i3)] . (a/b)^1,7")
            lin_phi = L
            L = grandeza(
                ws, L, "phi =",
                f"=((12-{_cel(lin_i[1])}-{_cel(lin_i[3])})/"
                f"(12-{_cel(lin_i[0])}-{_cel(lin_i[2])}))*"
                f"{_cel(lin_ab)}^1.7",
                "(ortotropia: mb = phi ma)", NF["coef3"],
                referencia="§3.2 a.2")
        L = expressao(ws, L, "a_r =", "2a / (raiz(1+i2) + raiz(1+i4))")
        lin_ar = L
        L = grandeza(ws, L, "a_r =",
                     f"=2*{_cel(lin_a)}/(SQRT(1+{_cel(lin_i[1])})+"
                     f"SQRT(1+{_cel(lin_i[3])}))", "(vão reduzido em a)",
                     NF["m"])
        L = expressao(ws, L, "b_r =", "2b / (raiz(1+i1) + raiz(1+i3))")
        lin_br = L
        L = grandeza(ws, L, "b_r =",
                     f"=2*{_cel(lin_b)}/(SQRT(1+{_cel(lin_i[0])})+"
                     f"SQRT(1+{_cel(lin_i[2])}))", "(vão reduzido em b)",
                     NF["m"])
        lin_alfa = L
        L = grandeza(ws, L, "alfa =", esf.alfa_parede,
                     "(parede paralela a a: p_a/(p b))", NF["coef3"],
                     entrada=True, referencia="§3.2 b")
        lin_beta = L
        L = grandeza(ws, L, "beta =", esf.beta_parede,
                     "(parede paralela a b: p_b/(p a))", NF["coef3"],
                     entrada=True, referencia="§3.2 b")
        lin_bre = L
        L = grandeza(ws, L, "b*_r =",
                     f"={_cel(lin_br)}/SQRT({_cel(lin_phi)})*"
                     f"SQRT((1+{_cel(lin_alfa)}+2*{_cel(lin_beta)})/"
                     f"(1+3*{_cel(lin_beta)}))",
                     "(vão reduzido corrigido)", NF["m"])
        lin_pe = L
        L = grandeza(ws, L, "p* =",
                     f"={_cel(lin_pd)}*(1+{_cel(lin_alfa)}+2*"
                     f"{_cel(lin_beta)})", "(carga equivalente)",
                     '0.00\\ "kN/m²"')
        lin_gn = L
        L = grandeza(ws, L, "gamma_n =", esf.gamma_n,
                     "(coeficiente adicional do balanço)", NF["coef"],
                     referencia="13.2.4.1")
        L = expressao(ws, L, "m =",
                      "(p*/8) . a_r b*_r / (1 + a_r/b*_r + b*_r/a_r)")
        lin_ma = L
        L = grandeza(ws, L, "m_a =",
                     f"={_cel(lin_gn)}*({_cel(lin_pe)}/8)*"
                     f"({_cel(lin_ar)}*{_cel(lin_bre)})/"
                     f"(1+{_cel(lin_ar)}/{_cel(lin_bre)}+"
                     f"{_cel(lin_bre)}/{_cel(lin_ar)})",
                     "(momento de cálculo na direção a)", '0.00\\ "kN·m/m"')
        lin_mb = L
        L = grandeza(ws, L, "m_b =", f"={_cel(lin_phi)}*{_cel(lin_ma)}",
                     "(momento de cálculo na direção b)", '0.00\\ "kN·m/m"')
        lin_direcao = {"a": lin_ma, "b": lin_mb}
        L = separador(ws, L)

        if esf.m_neg:
            L = secao(ws, L, "momentos negativos: m'k = ik . m da direção")
            L = cabecalho(ws, L, ["bordo", "direção", "i", "m' (kN·m/m)"])
            for k in sorted(esf.m_neg):
                direcao = "b" if k in BORDOS_DA_DIRECAO["b"] else "a"
                L = linha_tabela(ws, L, [
                    k, direcao, laje.bordos[k - 1].i,
                    f"={_cel(lin_i[k - 1])}*{_cel(lin_direcao[direcao])}"],
                    [NF["inteiro"], NF["texto"], NF["coef"],
                     '0.00\\ "kN·m/m"'])
            L = separador(ws, L)
    else:
        L = secao(ws, L, f"momentos no elu — uma direção ({cls.direcao}), "
                         f"esquema {cls.esquema}")
        L = cabecalho(ws, L, ["faixa", "bw vão (cm)", "bw eng. (cm)",
                              "p_d (kN/m²)", "m vão", "m engaste"])
        for f in esf.faixas:
            L = linha_tabela(ws, L, [
                f.nome, f.bw_vao, f.bw_eng, f.p_d, f.m_vao, f.m_eng],
                [NF["texto"], NF["cm"], NF["cm"], '0.00\\ "kN/m²"',
                 '0.00\\ "kN·m/m"', '0.00\\ "kN·m/m"'])
        L = separador(ws, L)

    # -- flexão -------------------------------------------------------------
    L = secao(ws, L, "flexão — faixa de 1 m (17.2.2)")
    lin_sigma = L
    L = grandeza(ws, L, "alfa_c fcd =", pav.concreto.sigma_cd,
                 "(tensão do bloco retangular)", NF["kNcm2"])
    lin_lam = L
    L = grandeza(ws, L, "lambda =", pav.concreto.lambda_, "(y / x)",
                 NF["coef3"])
    lin_fyd = L
    L = grandeza(ws, L, "fyd =", pav.aco.fyd_kNcm2, "(fyk / gamma_s)",
                 NF["kNcm2"])
    lin_xd = L
    L = grandeza(ws, L, "x/d limite =", pav.concreto.x_sobre_d_limite,
                 "(regime rígido-plástico)", NF["coef3"],
                 referencia="14.6.4.3")
    L = separador(ws, L)
    L = expressao(ws, L, "x =", "(d/lambda) [1 - raiz(1 - 2 md/(alfa_c fcd "
                                "b d²))]")
    L = expressao(ws, L, "As =", "alfa_c lambda fcd b x / fyd")
    L = cabecalho(ws, L, ["seção", "m_d", "d (cm)", "x (cm)", "x/d",
                          "As,calc", "As,mín", "As adotada", "veredito"])
    for f in rl.flexoes:
        lin = L
        L = linha_tabela(ws, L, [
            f.rotulo, f.md, f.d,
            f"=({_cel(lin, 4)}/{_cel(lin_lam)})*(1-SQRT(MAX(0,1-2*"
            f"{_cel(lin, 3)}*100/({_cel(lin_sigma)}*100*"
            f"{_cel(lin, 4)}^2))))",
            f"={_cel(lin, 5)}/{_cel(lin, 4)}",
            f"={_cel(lin_sigma)}*{_cel(lin_lam)}*100*{_cel(lin, 5)}/"
            f"{_cel(lin_fyd)}",
            f.As_minima,
            f"=MAX({_cel(lin, 7)},{_cel(lin, 8)})",
            f'=IF({_cel(lin, 6)}<={_cel(lin_xd)},"OK","NÃO OK — x/d")'],
            [NF["texto"], '0.00\\ "kN·m/m"', NF["cm"], NF["cm"],
             NF["coef3"], NF["cm2m"], NF["cm2m"], NF["cm2m"], NF["texto"]])
        from .estilo_planilha import aplicar_condicional
        aplicar_condicional(ws, f"{get_column_letter(10)}{lin}")
    L = separador(ws, L)

    # -- serviço ------------------------------------------------------------
    if rl.els is not None:
        e = rl.els
        L = secao(ws, L, "serviço — deformação (§1.6)")
        lin_fctm = L
        L = grandeza(ws, L, "fctm =", pav.concreto.fctm / 10.0,
                     "(resistência média à tração)", NF["kNcm2"],
                     referencia="8.2.5")
        L = expressao(ws, L, "m_r =", "0,25 fctm b h²")
        lin_mr = L
        L = grandeza(ws, L, "m_r =",
                     f"={_cel(lin_fctm)}*100*{_cel(lin_h)}^2/4/100",
                     "(momento de fissuração)", '0.00\\ "kN·m/m"')
        lin_ma_ser = L
        L = grandeza(ws, L, "m_a =", e.m_a,
                     "(momento de serviço da seção crítica)",
                     '0.00\\ "kN·m/m"')
        lin_ic = L
        L = grandeza(ws, L, "Ic =", f"=100*{_cel(lin_h)}^3/12",
                     "(inércia da seção bruta)", NF["cm4"])
        lin_ieq = L
        L = grandeza(ws, L, "Ieq =",
                     f"=IF({_cel(lin_ma_ser)}<={_cel(lin_mr)},"
                     f"{_cel(lin_ic)},0.3*{_cel(lin_ic)})",
                     "(Ic se não fissurada; 0,30 Ic se fissurada)",
                     NF["cm4"])
        lin_ecs = L
        L = grandeza(ws, L, "Ecs =", pav.concreto.Ecs / 10.0,
                     "(módulo secante)", NF["kNcm2"], referencia="8.2.8")
        lin_k = L
        L = grandeza(ws, L, "k =", e.k, "(coeficiente de flecha da "
                                        "vinculação)", NF["coef3"],
                     entrada=True, referencia="§1.6")
        lin_vao = L
        L = grandeza(ws, L, "L de referência =", e.vao * 100.0,
                     "(vão que governa a flecha)", NF["cm"])
        L = expressao(ws, L, "f(t=0) =", "k p_ser L⁴ / (Ecs Ieq)")
        lin_f0 = L
        L = grandeza(ws, L, "f(t=0) =",
                     f"={_cel(lin_k)}*({_cel(lin_pser)}/10000)*"
                     f"{_cel(lin_vao)}^4/({_cel(lin_ecs)}*{_cel(lin_ieq)})",
                     "(flecha imediata)", '0.000\\ "cm"')
        lin_fl = L
        L = grandeza(ws, L, "1 + alfa_f =", cfg.fator_fluencia,
                     "(fluência, t0 = 1 mês)", NF["coef"], entrada=True,
                     referencia="17.3.2.1.2")
        lin_finf = L
        L = grandeza(ws, L, "f(t=inf) =",
                     f"={_cel(lin_fl)}*{_cel(lin_f0)}",
                     "(flecha de longa duração)", '0.000\\ "cm"')
        lin_div = L
        L = grandeza(ws, L, "divisor =", e.divisor, "(limite L / divisor)",
                     NF["inteiro"], entrada=True, referencia="Tabela 13.3")
        lin_fadm = L
        L = grandeza(ws, L, "f,adm =",
                     f"={_cel(lin_vao)}/{_cel(lin_div)}",
                     "(flecha admissível)", '0.000\\ "cm"')
        L = veredito(ws, L, "veredito =",
                     f'=IF({_cel(lin_finf)}<={_cel(lin_fadm)},"OK",'
                     f'"NÃO OK — flecha excessiva")',
                     "(f de longa duração contra o limite)")
        L = separador(ws, L)

    # -- cortante -----------------------------------------------------------
    if rl.cortantes:
        L = secao(ws, L, "força cortante (19.4.1)")
        L = expressao(ws, L, "VRd1 =",
                      "[tau_Rd k (1,2 + 40 rho1) + 0,15 sigma_cp] bw d")
        L = cabecalho(ws, L, ["bordo", "VSd (kN/m)", "As1", "rho_1", "k",
                              "VRd1 (kN/m)", "veredito"])
        for c in rl.cortantes:
            lin = L
            L = linha_tabela(ws, L, [
                c.rotulo, c.v_sd, c.As1, c.rho_1, c.k, c.v_rd1,
                f'=IF({_cel(lin, 3)}<={_cel(lin, 7)},"OK",'
                f'"NÃO OK — pede armadura transversal")'],
                [NF["texto"], NF["kN"], NF["cm2m"], NF["coef3"], NF["coef3"],
                 NF["kN"], NF["texto"]])
            from .estilo_planilha import aplicar_condicional
            aplicar_condicional(ws, f"{get_column_letter(8)}{lin}")
        L = separador(ws, L)

    _alargar(ws)

    # -- reações ------------------------------------------------------------
    if rl.reacoes is not None:
        L = secao(ws, L, "reações de apoio (14.7.6.1)")
        L = cabecalho(ws, L, ["bordo", "vínculo", "L (m)", "parcela",
                              "v_g", "v_q", "v_k", "v_d", "fonte"])
        for r in rl.reacoes.bordos:
            L = linha_tabela(ws, L, [
                r.bordo, r.vinculo, r.comprimento, r.fracao, r.v_g, r.v_q,
                r.v_k, r.v_d, r.fonte],
                [NF["inteiro"], NF["texto"], NF["m"], NF["coef3"], NF["kN"],
                 NF["kN"], NF["kN"], NF["kN"], NF["texto"]])


# ---------------------------------------------------------------------------
# Abas consolidadas
# ---------------------------------------------------------------------------

def _aba_esforcos(wb: Workbook, res) -> None:
    ws = wb.create_sheet("ESFORÇOS")
    preparar_tabela(ws, [11, 15, 10, 8, 14, 14, 16, 16, 16, 16, 26,
                         10])
    L = 2
    L = titulo(ws, L, "MOMENTOS DE TODAS AS LAJES", 2, 13)
    L = nota(ws, L, "ELU em regime rígido-plástico (§3.2); ELS em regime "
                    "elástico (§3.1)", 2, 13)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["laje", "tipo", "caso", "phi", "p_d", "p_ser",
                          "m_a (ELU)", "m_b (ELU)", "m_a (ELS)", "m_b (ELS)",
                          "m' bordo 1..4", "gamma_n"])
    for rl in res.lajes:
        e = rl.esforcos
        negativos = " / ".join(f"{e.m_neg.get(k, 0.0):.2f}"
                               for k in (1, 2, 3, 4))
        L = linha_tabela(ws, L, [
            rl.nome, e.classificacao.tipo,
            e.classificacao.caso if e.classificacao.em_cruz
            else f"esq. {e.classificacao.esquema}",
            e.phi, e.p_d, e.p_ser, e.ma, e.mb, e.ma_ser, e.mb_ser,
            negativos, e.gamma_n],
            [NF["texto"], NF["texto"], NF["texto"], NF["coef3"],
             '0.00\\ "kN/m²"', '0.00\\ "kN/m²"', '0.00\\ "kN·m/m"',
             '0.00\\ "kN·m/m"', '0.00\\ "kN·m/m"', '0.00\\ "kN·m/m"',
             NF["texto"], NF["coef"]])


def _aba_bordas(wb: Workbook, res) -> None:
    comp = res.compatibilizacao
    ws = wb.create_sheet("BORDAS COMUNS")
    preparar_tabela(ws, [34, 16, 16, 16, 11, 15, 12, 14, 14])
    L = 2
    L = titulo(ws, L, "COMPATIBILIZAÇÃO DOS MOMENTOS NEGATIVOS", 2, 10)
    L = nota(ws, L, "Item 14.7.6.2 e §3.3: uma armadura por borda comum, "
                    "para o maior momento e a menor altura útil", 2, 10)
    L = separador(ws, L)
    if comp is None or not comp.bordas:
        L = nota(ws, L, "O pavimento não tem borda de continuidade.", 2, 10)
        return
    L = cabecalho(ws, L, ["borda comum", "m' lado A", "m' lado B",
                          "m' adotado", "d (cm)", "extensão (cm)",
                          "Ø (mm)", "c/ (cm)", "As,ef"])
    for b in comp.bordas:
        pos = next((p for p in res.posicoes_continuidade
                    if p.laje == f"{b.laje_a} / {b.laje_b}"), None)
        L = linha_tabela(ws, L, [
            b.rotulo, b.m_a, b.m_b, b.m_adotado, b.d_adotado, b.extensao,
            pos.phi if pos else None, pos.espacamento if pos else None,
            pos.As_efetiva if pos else None],
            [NF["texto"], '0.00\\ "kN·m/m"', '0.00\\ "kN·m/m"',
             '0.00\\ "kN·m/m"', NF["cm"], NF["cm"], NF["mm"],
             NF["espacamento"], NF["cm2m"]])


def _aba_detalhamento(wb: Workbook, res) -> None:
    ws = wb.create_sheet("DETALHAMENTO")
    preparar_tabela(ws, [8, 18, 16, 8, 11, 14, 11, 14, 14, 12, 13, 11, 11,
                         56])
    L = 2
    L = titulo(ws, L, "TABELA DE POSIÇÕES", 2, 15)
    L = nota(ws, L, "Bitola <= h/8 e espaçamento <= min(2h ; 20 cm) na "
                    "armadura principal; 33 cm na de distribuição (20.1)",
             2, 15)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["pos.", "laje", "tipo", "qtd.", "Ø (mm)",
                          "c/ (cm)", "C (cm)", "As,nec", "As,ef",
                          "total (m)", "massa (kg)", "emendas", "l0t (cm)",
                          "critério"])
    for p in res.todas_posicoes:
        L = linha_tabela(ws, L, [
            f"N{p.numero}", p.laje, p.tipo, p.quantidade, p.phi,
            p.espacamento, p.comprimento, p.As_necessaria, p.As_efetiva,
            p.comprimento_total, p.massa,
            p.emendas if p.emendas else "—",
            p.l0t if p.emendas else "—",
            p.rotulo + ("; " + "; ".join(p.observacoes)
                        if p.observacoes else "")],
            [NF["texto"], NF["texto"], NF["texto"], NF["inteiro"], NF["mm"],
             NF["espacamento"], NF["cm"], NF["cm2m"], NF["cm2m"], NF["m"],
             NF["kg"], NF["inteiro"] if p.emendas else NF["texto"],
             NF["cm"] if p.emendas else NF["texto"], NF["texto"]])

    if res.traspasses:
        L = separador(ws, L)
        L = titulo(ws, L, "EMENDA POR TRASPASSE (9.5.2)", 2, 15)
        L = nota(ws, L, "α0t da Tabela 9.4 supondo até 20 % das barras "
                        "emendadas na mesma seção; escalone as emendas na "
                        "prancha ou recalcule com α0t maior",
                 2, 15)
        L = cabecalho(ws, L, ["posição", "Ø (mm)", "C da barra (m)",
                              "vara (m)", "emendas/barra", "α0t",
                              "l0t (cm)"])
        for t in res.traspasses:
            L = linha_tabela(ws, L, [
                t.rotulo, t.phi, t.comprimento_barra / 100.0,
                t.comprimento_comercial / 100.0, t.numero_emendas,
                t.alfa_0t, t.l0t],
                [NF["texto"], NF["mm"], NF["m"], NF["m"], NF["inteiro"],
                 NF["coef"], NF["cm"]])


def _aba_reacoes(wb: Workbook, res) -> None:
    ws = wb.create_sheet("REAÇÕES")
    preparar_tabela(ws, [38, 10, 10, 12, 12, 12, 12])
    L = 2
    L = titulo(ws, L, "CARGA ENTREGUE ÀS VIGAS", 2, 8)
    L = nota(ws, L, "Nas bordas comuns as duas lajes descarregam no mesmo "
                    "trecho, e a viga recebe a soma", 2, 8)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["trecho", "L (m)", "contínua", "v_g (kN/m)",
                          "v_q (kN/m)", "v_k (kN/m)", "v_d (kN/m)"])
    for s in res.apoios:
        L = linha_tabela(ws, L, [
            s.rotulo, s.comprimento, "sim" if s.continuidade else "não",
            s.v_g, s.v_q, s.v_k, s.v_d],
            [NF["texto"], NF["m"], NF["texto"], NF["kN"], NF["kN"], NF["kN"],
             NF["kN"]])


def _aba_quantitativo(wb: Workbook, res) -> None:
    ws = wb.create_sheet("QUANTITATIVO")
    preparar_memoria(ws)
    q = res.quantitativo
    L = 2
    L = titulo(ws, L, "QUANTITATIVO DE AÇO E CONCRETO")
    L = separador(ws, L)
    L = secao(ws, L, "aço por bitola")
    L = cabecalho(ws, L, ["Ø (mm)", "posições", "comprimento (m)",
                          "massa (kg)", "emendas", "massa das emendas (kg)"])
    for phi, d in q["por_bitola"].items():
        L = linha_tabela(ws, L, [phi, d["posicoes"], d["comprimento"],
                                 d["massa"], d.get("emendas", 0),
                                 d.get("massa_emendas", 0.0)],
                         [NF["mm"], NF["inteiro"], NF["m"], NF["kg"],
                          NF["inteiro"], NF["kg"]])
    _alargar(ws, {"D": 18.0, "E": 16.0, "F": 14.0, "G": 22.0})

    L = separador(ws, L)
    L = secao(ws, L, "forma, por laje")
    L = nota(ws, L, "forma inferior = fundo menos a faixa de t/2 sobre cada "
                    "bordo apoiado (a viga tem forma própria ali); forma de "
                    "fechamento = face lateral de altura h só nos bordos "
                    "livres, onde o concreto vazaria")
    L = cabecalho(ws, L, ["laje", "retângulo (m²)", "forma inferior (m²)",
                          "bordos livres", "forma de fechamento (m²)"])
    formas = [rl.formas for rl in res.lajes if rl.formas is not None]
    for f in formas:
        L = linha_tabela(ws, L, [
            f.laje, f.area_bruta, f.inferior,
            ", ".join(str(b) for b in f.bordos_livres) or "—", f.fechamento],
            [NF["texto"], '0.00\\ "m²"', '0.00\\ "m²"', NF["texto"],
             '0.00\\ "m²"'])

    L = separador(ws, L)
    L = secao(ws, L, "resumo")
    L = grandeza(ws, L, "área de laje =", q["area_total"], "(vãos efetivos)",
                 '0.00\\ "m²"')
    L = grandeza(ws, L, "volume de concreto =", q["volume_concreto"],
                 "(área x espessura)", '0.00\\ "m³"')
    L = grandeza(ws, L, "forma inferior =", q.get("forma_inferior", 0.0),
                 "(fundo, sem a faixa sobre viga)", '0.00\\ "m²"')
    L = grandeza(ws, L, "forma de fechamento =",
                 q.get("forma_fechamento", 0.0),
                 "(bordo livre, altura h)", '0.00\\ "m²"')
    L = grandeza(ws, L, "forma total =", q.get("forma_total", 0.0),
                 "(inferior + fechamento)", '0.00\\ "m²"')
    L = grandeza(ws, L, "aço das barras =", q["massa_total"],
                 "(o que a prancha mede)", NF["kg"])
    L = grandeza(ws, L, "aço do traspasse =", q.get("massa_emendas", 0.0),
                 "(sobreposição das emendas, 9.5.2)", NF["kg"])
    L = grandeza(ws, L, "aço com perdas =", q["massa_com_perdas"],
                 "(barras + emendas + 10 % de pontas)", NF["kg"])
    L = grandeza(ws, L, "taxa =", q["taxa_por_m2"], "(por metro quadrado)",
                 '0.00\\ "kg/m²"')
    L = grandeza(ws, L, "taxa =", q["taxa_por_m3"], "(por metro cúbico)",
                 '0.0\\ "kg/m³"')
    L = grandeza(ws, L, "peso próprio médio =", q["peso_proprio_medio"],
                 "(volume x peso específico / área)", '0.00\\ "kN/m²"')


def _aba_verificacoes(wb: Workbook, res) -> None:
    ws = wb.create_sheet("VERIFICAÇÕES")
    preparar_tabela(ws, [12, 56, 16, 26, 28, 12])
    linhas = auditoria.roteiro(res)
    total, reprovadas, fora = auditoria.resumo(linhas)
    L = 2
    L = titulo(ws, L, "ROTEIRO DE VERIFICAÇÕES", 2, 7)
    L = nota(ws, L, f"{total} verificações normativas; {reprovadas} não "
                    f"fecharam"
                    + (f"; {fora} armadura(s) fora da faixa de bitola "
                       f"desejada, que é preferência e não exigência"
                       if fora else ""), 2, 7)
    L = separador(ws, L)
    L = cabecalho(ws, L, ["item", "verificação", "onde", "valor", "limite",
                          "veredito"])
    from .estilo_planilha import aplicar_condicional
    for v in linhas:
        lin = L
        L = linha_tabela(ws, L, [v.item, v.descricao, v.onde, v.valor,
                                 v.limite, v.veredito],
                         [NF["texto"]] * 6)
        aplicar_condicional(ws, f"{get_column_letter(7)}{lin}")


def _aba_avisos(wb: Workbook, res) -> None:
    ws = wb.create_sheet("AVISOS")
    preparar_tabela(ws, [16, 130])
    erros, obs = avisos_mod.separar(res.todos_avisos)
    L = 2
    L = titulo(ws, L, "PENDÊNCIAS E OBSERVAÇÕES", 2, 3)
    L = nota(ws, L, avisos_mod.resumo(res.todos_avisos), 2, 3)
    L = separador(ws, L)
    if erros:
        L = secao(ws, L, "erros de verificação", 2, 3, COR["elu"])
        L = cabecalho(ws, L, ["laje", "aviso"])
        for a in erros:
            L = linha_tabela(ws, L, [a.laje or "—", a.texto],
                             [NF["texto"], NF["texto"]],
                             cores=[COR["alerta"], COR["alerta"]])
        L = separador(ws, L)
    if obs:
        L = secao(ws, L, "observações construtivas", 2, 3, COR["els"])
        L = cabecalho(ws, L, ["laje", "observação"])
        for a in obs:
            L = linha_tabela(ws, L, [a.laje or "—", a.texto],
                             [NF["texto"], NF["texto"]])
    if not erros and not obs:
        L = nota(ws, L, "Nenhuma pendência.", 2, 3)


# ---------------------------------------------------------------------------
# Interface pública
# ---------------------------------------------------------------------------

def gerar(res, caminho: str) -> str:
    """Grava a planilha de resultados e devolve o caminho do arquivo."""
    wb = Workbook()
    wb.remove(wb.active)
    _aba_dados(wb, res)
    _aba_esforcos(wb, res)
    for rl in res.lajes:
        _aba_laje(wb, res, rl)
    _aba_bordas(wb, res)
    _aba_detalhamento(wb, res)
    _aba_reacoes(wb, res)
    _aba_quantitativo(wb, res)
    _aba_verificacoes(wb, res)
    _aba_avisos(wb, res)
    normalizar_alturas(wb)
    wb.save(caminho)
    return caminho
