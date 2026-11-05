# -*- coding: utf-8 -*-
"""
dimensionar.py
Orquestra o cálculo completo da viga: análise, envoltórias, dimensionamento
à flexão, ao cisalhamento e à torção, verificações de serviço, escolha das
barras e montagem do detalhamento.

É o único módulo que conhece todos os demais; a interface gráfica e os
módulos de saída consomem apenas o :class:`ResultadoViga` daqui.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

import numpy as np

from . import alinhamento as al
from . import ancoragem as anc
from . import cisalhamento as ci
from . import fadiga as fad
from . import combinacoes as cb
from . import detalhamento as det
from . import els
from . import flexao as fl
from . import ganchos as gk
from . import grampos as gr
from . import torcao as to
from .analise import Estrutura, combinar, resolver, resolver_torcao
from .materiais import BITOLAS_BARRAS, Aco, area_barra
from .modelo import Secao, Viga
from . import avisos as av


# ---------------------------------------------------------------------------
# Estruturas de resultado
# ---------------------------------------------------------------------------

@dataclass
class Regiao:
    """Uma região de armadura longitudinal: um vão ou um apoio."""

    tipo: str                 # 'vao' ou 'apoio'
    indice: int
    nome: str
    x: float                  # m
    x_ini: float              # m, início da região de influência
    x_fim: float              # m
    face: str                 # face tracionada
    M: float                  # kN.m de projeto
    secao: Secao
    flexao: fl.ResultadoFlexao
    arranjo: det.Arranjo
    arranjo_comprimido: det.Arranjo | None
    d: float
    construtiva: bool = False
    #: trecho prismático da região; -1 no apoio, cuja seção sai de
    #: ``Viga.secao_de_apoio`` e pode ser a de qualquer um dos dois lados
    trecho: int = -1
    As_torcao: float = 0.0
    ancoragem: anc.Ancoragem | None = None
    fissuracao: els.ResultadoFissuracao | None = None
    cortes: list[det.CorteBarra] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    #: x/d da seção adotada, com a armadura comprimida presente e ancorada
    #: (14.6.4.3); preenchido no detalhamento
    x_d_adotada: float = 0.0
    As_comprimida_presente: float = 0.0
    comprimidas_presentes: list[int] = field(default_factory=list)


@dataclass
class ResultadoViga:
    """Resultado completo do cálculo de uma viga."""

    viga: Viga
    estrutura: Estrutura
    envoltoria: cb.Envoltoria
    combinacoes: list[cb.Combinacao]
    momentos_projeto: list[cb.MomentoProjeto]
    regioes: list[Regiao]
    x: np.ndarray
    As_req_inf: np.ndarray
    As_req_sup: np.ndarray
    Vsd_projeto: np.ndarray
    asw_req: np.ndarray
    cortantes: list[ci.ResultadoCortante]
    zonas_estribo: list[det.ZonaEstribo]
    torcoes: list[to.ResultadoTorcao] = field(default_factory=list)
    T_diagrama: tuple | None = None
    flechas: list[els.ResultadoFlecha] = field(default_factory=list)
    apoios_extremos: list[anc.ApoioExtremo] = field(default_factory=list)
    #: ancoragem da armadura negativa nos apoios de extremidade (18.3.2.4-d)
    ancoragens_negativas: list[anc.AncoragemNegativa] = field(
        default_factory=list)
    #: ancoragem da armadura longitudinal de torção nos apoios de extremidade
    ancoragens_torcao: list[anc.AncoragemTorcao] = field(default_factory=list)
    #: bitola que a verificação de ductilidade da seção adotada pede para uma
    #: região no passe seguinte (uso interno de `dimensionar`)
    pedidos_de_bitola: dict = field(default_factory=dict)
    grampos: list[gr.Grampos] = field(default_factory=list)
    fadigas: list[fad.ResultadoFadiga] = field(default_factory=list)
    fadigas_estribo: list[fad.ResultadoFadigaEstribo] = field(
        default_factory=list)
    posicoes: list[det.Posicao] = field(default_factory=list)
    quantitativo: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    reacoes: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Verdadeiro se nenhuma verificação normativa foi reprovada."""
        if any(not c.biela_ok for c in self.cortantes):
            return False
        if any(not t.biela_ok for t in self.torcoes):
            return False
        if any(not f.ok_visual or not f.ok_alvenaria for f in self.flechas):
            return False
        if any(r.fissuracao is not None and not r.fissuracao.ok
               for r in self.regioes):
            return False
        if any(not f.ok for f in self.fadigas):
            return False
        if any(not f.ok for f in self.fadigas_estribo):
            return False
        if any(not g.ok for g in self.grampos):
            return False
        if any(not a.ok for a in self.apoios_extremos
               if not any(g.apoio == a.apoio and g.ok
                          for g in self.grampos)):
            return False
        # e qualquer aviso classificado como erro: a lista acima é mantida à
        # mão e não acompanha verificação nova. Foi assim que uma viga com
        # gancho impossível (Ø32 em seção de 30 cm) saiu com "todas as
        # verificações atendidas" na memória
        return not any(av.nivel_de(a) == av.ERRO for a in self.avisos)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _tipo_gancho(viga: Viga, nome_regiao: str = "") -> str:
    """Tipo de gancho da região; na falta dela, o dos critérios gerais.

    O critério antigo ``ancoragem_gancho`` continua valendo como o desligamento
    geral -- ele existe em projetos já gravados, e é exatamente o que a opção
    "Sem gancho" do tipo passou a expressar. Desligado, nenhuma barra ganha
    gancho e a ancoragem tem de caber reta.
    """
    cfg = viga.config
    escolha = (cfg.ganchos_flexao or {}).get(nome_regiao, "")
    escolha = escolha or cfg.tipo_gancho
    if not cfg.ancoragem_gancho or escolha == gk.SEM_GANCHO:
        return gk.SEM_GANCHO
    return gk.normalizar(escolha)


def _phi_imposta(viga: Viga, nome_regiao: str) -> float:
    """Bitola imposta para a região, mm; 0 quando o programa escolhe.

    A imposição por região vem da tabela de resultados: o usuário troca a
    bitola e o dimensionamento se refaz com ela. Na falta dela vale a bitola
    fixa geral dos critérios.
    """
    cfg = viga.config
    valor = cfg.bitolas_flexao.get(nome_regiao, 0.0) if cfg.bitolas_flexao \
        else 0.0
    return float(valor) or cfg.phi_longitudinal


def _cobrimento(viga: Viga) -> float:
    return viga.ambiente.cobrimento_nominal


def _d_estimado(secao: Secao, viga: Viga) -> float:
    c = _cobrimento(viga)
    return secao.h - (c + viga.config.phi_estribo / 10.0 + 1.0)


def _nome_de_vao(viga: Viga, mp) -> str:
    """Nome da região de vão: "Vão 2", ou "Vão 2a"/"Vão 2b" quando partido.

    O sufixo só aparece onde existe mais de um trecho, para que a viga
    prismática -- o caso corrente -- continue com os nomes que o usuário já
    conhece, e para que a bitola e o gancho impostos pelo nome não se perdessem
    ao abrir um projeto antigo.
    """
    do_tramo = viga.trechos_do_tramo(mp.indice)
    base = f"Vão {mp.indice + 1}"
    if len(do_tramo) < 2:
        return base
    ordem = [t.k for t in do_tramo].index(mp.trecho)
    return f"{base}{chr(ord('a') + ordem)}"


def _regioes_de_influencia(viga: Viga) -> dict:
    """Trecho de viga associado a cada vão e a cada apoio.

    A região de um apoio vai até a metade de cada vão vizinho -- exceto quando
    o vizinho é um balanço: aí o momento negativo cresce até o engaste e a
    armadura tem de percorrer o balanço inteiro, até a extremidade livre.
    """
    xs = viga.x_apoios
    limites = {}
    # a região de um vão é o **trecho prismático**, não o vão inteiro: a
    # armadura dimensionada com a seção de um pedaço não tem por que se
    # estender sobre o pedaço de outra seção
    for i in range(len(viga.tramos)):
        for t in viga.trechos_do_tramo(i):
            limites[("vao", i, t.k)] = (t.x_ini, t.x_fim)
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        if k == 0:
            a = xs[0]
        elif viga.apoios[k - 1].tipo == "livre":
            a = xs[k - 1]                       # balanço à esquerda
        else:
            a = xs[k - 1] + (xs[k] - xs[k - 1]) * 0.5
        if k == len(xs) - 1:
            b = xs[-1]
        elif viga.apoios[k + 1].tipo == "livre":
            b = xs[k + 1]                       # balanço à direita
        else:
            b = xs[k] + (xs[k + 1] - xs[k]) * 0.5
        limites[("apoio", k)] = (a, b)
    return limites


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

def dimensionar(viga: Viga) -> ResultadoViga:
    """Executa o cálculo completo e devolve o resultado consolidado.

    A altura útil depende da bitola do estribo, e a bitola do estribo só se
    conhece depois do cortante, da torção e da costura -- que dependem da
    altura útil. O primeiro passe usa o estribo previsto nos critérios
    (``phi_estribo``); se uma região sai com estribo mais grosso, o cálculo é
    refeito com a bitola final **daquela região** na altura útil. Antes o d
    ficava com o estribo previsto: na V05 do pacote de conferência, d = 45,875
    cm com Ø5 quando o estribo adotado era Ø6,3 (d = 45,745 cm).
    """
    usados: dict[str, float] = {}
    forcados: dict[str, float] = {}
    res = _dimensionar(viga, usados, forcados)
    for _ in range(4):
        novos = {nome: phi for nome, phi in _estribo_das_regioes(res).items()
                 if phi > max(usados.get(nome, 0.0),
                              viga.config.phi_estribo) + 1e-9}
        # a ductilidade da seção adotada pode pedir outra bitola numa região
        # (ver `_verificar_ductilidade_adotada`); cada pedido entra uma vez
        novos_f = {nome: phi for nome, phi in res.pedidos_de_bitola.items()
                   if nome not in forcados}
        if not novos and not novos_f:
            break
        usados.update(novos)
        forcados.update(novos_f)
        res = _dimensionar(viga, usados, forcados)
    return res


def _estribo_das_regioes(res: "ResultadoViga") -> dict[str, float]:
    """Bitola do estribo mais grosso que abraça cada região calculada, mm."""
    saida: dict[str, float] = {}
    for r in res.regioes:
        if r.construtiva:
            continue
        phis = [z.phi for z in res.zonas_estribo
                if z.x_fim > r.x_ini + 1e-9 and z.x_ini < r.x_fim - 1e-9]
        if phis:
            saida[r.nome] = max(phis)
    return saida


def _dimensionar(viga: Viga, phi_t_regiao: dict[str, float],
                 phi_flexao: dict[str, float] | None = None) -> ResultadoViga:
    """Um passe do cálculo, com a bitola de estribo de cada região na altura
    útil (``phi_t_regiao``, por nome; ausente = a prevista nos critérios) e,
    em ``phi_flexao``, a bitola longitudinal que a ductilidade pediu."""
    phi_flexao = phi_flexao or {}
    avisos = list(viga.validar())
    cfg = viga.config
    conc, aco = viga.concreto, viga.aco
    cob = _cobrimento(viga)
    phi_t = cfg.phi_estribo

    _verificar_viga_parede(viga, avisos)

    # -- 1. análise e envoltórias ------------------------------------------
    est = resolver(viga)
    combs = cb.gerar_combinacoes(viga)
    env, sols_elu = cb.calcular(est, combs, tipos=("ELU",))
    momentos = cb.momentos_de_projeto(viga, env, sols_elu)
    limites = _regioes_de_influencia(viga)

    # -- 2. flexão, com iteração da altura útil -----------------------------
    regioes: list[Regiao] = []
    for mp in momentos:
        secao = (viga.secao_de_apoio(mp.indice) if mp.regiao == "apoio"
                 else viga.trechos[mp.trecho].secao)
        face = "inferior" if mp.M >= 0 else "superior"
        a, b = (limites[("apoio", mp.indice)] if mp.regiao == "apoio"
                else limites[("vao", mp.indice, mp.trecho)])
        # a região de apoio não nasce com trecho: quem o diz é a seção que
        # governa a armadura negativa, e é ela que define o **nível** da barra
        if mp.regiao == "apoio":
            mp.trecho = viga.trecho_de_apoio(mp.indice)
        nome = (_nome_de_vao(viga, mp) if mp.regiao == "vao"
                else f"Apoio {mp.indice + 1}")
        if mp.regiao == "vao" and mp.M <= 1e-6:
            # tramo sem momento positivo (balanço): só armadura construtiva
            regioes.append(_regiao_construtiva(viga, mp, secao, nome, a, b))
            continue
        # o centróide das barras define d, d define As e As define quantas
        # barras entram: é um laço fechado, e trocar a bitola o reabre. Iterar
        # até o d parar de mudar é o que garante que As e d saiam coerentes
        # o estribo que abraça esta região: o previsto, ou o final do passe
        # anterior quando saiu mais grosso (ver `dimensionar`)
        phi_t_r = max(phi_t, phi_t_regiao.get(nome, 0.0))
        d = _d_estimado(secao, viga) - (phi_t_r - phi_t) / 10.0
        d_linha = cob + phi_t_r / 10.0 + 1.0
        phi_regiao = _phi_imposta(viga, nome) or phi_flexao.get(nome, 0.0)
        res = arr = arr_c = None
        convergiu = False
        for _ in range(8):
            res = fl.dimensionar(secao, conc, aco, mp.M, d_linha,
                                 secao.h - d, delta=cfg.redistribuicao)
            arr = det.escolher_barras(
                secao, res.As_adotado, cob, phi_t_r, cfg.d_agregado,
                cfg.phi_min_longitudinal, cfg.phi_max_longitudinal,
                phi_regiao, n_ramos=cfg.n_ramos)
            if abs(arr.d - d) < 0.05:
                d = arr.d
                convergiu = True
                break
            d = arr.d
        if not convergiu:
            # sem convergir, o As calculado ficaria com um d diferente do
            # arranjo adotado. Fecha-se a conta com o d do arranjo e, se a
            # armadura efetiva não cobrir, escolhem-se as barras outra vez
            res = fl.dimensionar(secao, conc, aco, mp.M, d_linha,
                                 secao.h - arr.d, delta=cfg.redistribuicao)
            if arr.As_ef < res.As_adotado - 1e-6:
                arr = det.escolher_barras(
                    secao, res.As_adotado, cob, phi_t_r, cfg.d_agregado,
                    cfg.phi_min_longitudinal, cfg.phi_max_longitudinal,
                    phi_regiao, n_ramos=cfg.n_ramos)
            avisos.append(av.construtivo(
                f"{nome}: a altura útil e a armadura não convergiram em 8 "
                f"iterações (d oscilando em torno de {arr.d:.1f} cm). Adotados "
                f"d = {arr.d:.1f} cm e {arr.descricao}, com As,ef = "
                f"{arr.As_ef:.2f} cm² contra {res.As_adotado:.2f} cm² "
                f"necessários — confira se a bitola imposta cabe na seção."))
            d = arr.d
        arr_c = None
        if res.armadura_dupla and res.As_linha > 0:
            arr_c = det.escolher_barras(
                secao, res.As_linha, cob, phi_t_r, cfg.d_agregado,
                cfg.phi_min_longitudinal, cfg.phi_max_longitudinal,
                phi_regiao, n_ramos=cfg.n_ramos)
        regioes.append(Regiao(
            tipo=mp.regiao, indice=mp.indice, nome=nome, x=mp.x, x_ini=a,
            x_fim=b, face=face, M=mp.M, secao=secao, flexao=res, arranjo=arr,
            arranjo_comprimido=arr_c, d=arr.d, trecho=mp.trecho,
            avisos=list(res.avisos) + list(arr.avisos)))
        res.memoria["barras por camada (18.3.2.2)"] = arr.n_por_camada
        res.memoria["camadas adotadas"] = " + ".join(map(str, arr.camadas))
        res.memoria["ah mínimo (cm)"] = arr.ah
        res.memoria["av mínimo (cm)"] = arr.av

    _verificar_taxa_maxima(regioes, avisos)
    _verificar_resultante(viga, regioes, avisos)

    # -- 3. diagramas de armadura necessária --------------------------------
    x = env.x
    d_inf = np.array([_d_face(viga, regioes, xi, "inferior") for xi in x])
    d_sup = np.array([_d_face(viga, regioes, xi, "superior") for xi in x])
    As_inf = _As_ao_longo(viga, x, env.M_max, d_inf, "inferior")
    As_sup = _As_ao_longo(viga, x, env.M_min, d_sup, "superior")
    # o item 18.3.2.4-c) manda prolongar até o apoio uma fração da armadura do
    # vão, e o piso entra no diagrama para o escalonamento cobri-lo
    As_inf = _prolongar_ate_o_apoio(viga, regioes, x, As_inf, momentos, avisos)

    # -- 4. cisalhamento ----------------------------------------------------
    V_env = np.maximum(np.abs(env.V_max), np.abs(env.V_min))
    d_medio = float(np.median(d_inf))
    V_proj = ci.cortante_de_projeto(V_env, x, viga, d_medio) if \
        cfg.reducao_apoio else V_env

    cortantes: list[ci.ResultadoCortante] = []
    asw_req = np.zeros_like(x)
    s_max_arr = np.zeros_like(x)
    for i, xi in enumerate(x):
        secao = viga.secao_em(xi)
        # o estribo tem o seu próprio aço: a armadura mínima do
        # 17.4.1.1.1 é inversamente proporcional ao fywk dele
        r = ci.verificar(secao, conc, viga.aco_estribo, V_proj[i],
                         d_inf[i],
                         cfg.modelo_cisalhamento, cfg.theta,
                         cfg.alpha_estribo, x=xi)
        asw_req[i] = r.asw_adotado
        s_max_arr[i] = r.s_max
        cortantes.append(r)

    # o espaçamento entre ramos sucessivos (18.3.3.2) limita quantos ramos o
    # estribo pode ter: com dois ramos numa viga larga, a distância entre eles
    # estoura st,max e nenhum aviso saía porque st,max não era lido
    n_ramos_ef = cfg.n_ramos
    exigido = 2
    pior_st = None
    for xi, r in zip(x, cortantes):
        n = ci.ramos_minimos(viga.secao_em(xi), cob, phi_t, r.st_max)
        if n > exigido:
            exigido, pior_st = n, (xi, r.st_max, viga.secao_em(xi).bw)
    if exigido > cfg.n_ramos:
        n_ramos_ef = exigido
        xi, st, bw = pior_st
        avisos.append(av.construtivo(
            f"Estribo elevado de {cfg.n_ramos} para {exigido} ramos: em "
            f"x = {xi:.2f} m a seção tem bw = {bw:g} cm e o item 18.3.3.2 "
            f"limita o espaçamento entre ramos sucessivos a "
            f"st,máx = {st:.1f} cm."))

    largas = [(xi, viga.secao_em(xi), di) for xi, di in zip(x, d_inf)
              if ci.exige_modelo_de_laje(viga.secao_em(xi), di)]
    if largas:
        xi, secao_larga, di = largas[0]
        avisos.append(av.erro(
            f"Em x = {xi:.2f} m a seção tem bw = {secao_larga.bw:g} cm e "
            f"d = {di:.1f} cm, ou seja bw > 5d: o item 17.4.1.1.2 (a) tira "
            f"esse elemento do modelo de viga — ele deve ser verificado como "
            f"laje (item 19.4), e a armadura transversal mínima do 17.4.1.1.1 "
            f"não se aplica. O dimensionamento a seguir usa o modelo de viga."))

    if any(not c.biela_ok for c in cortantes):
        pior = max(cortantes, key=lambda c: c.razao_biela)
        avisos.append(av.erro(f"Biela comprimida esmaga em x = {pior.x:.2f} m "
                      f"(Vsd/VRd2 = {pior.razao_biela:.2f})."))

    # -- 5. torção ----------------------------------------------------------
    torcoes: list[to.ResultadoTorcao] = []
    T_diag = None
    asl_lateral: list[tuple[int, float]] = []
    if viga.torcores and not cfg.considerar_torcao:
        # nunca deixar o torçor lançado sumir em silêncio
        if cfg.torcao_equilibrio:
            avisos.append(av.erro(
                f"Há {len(viga.torcores)} torçor(es) lançado(s) e a torção foi "
                f"declarada **necessária ao equilíbrio**, mas a verificação "
                f"está desligada nos critérios: o item 17.5.1.2 exige armadura "
                f"de torção sempre que ela for necessária ao equilíbrio. "
                f"Religue a verificação ou declare a torção como de "
                f"compatibilidade."))
        else:
            _torcao_de_compatibilidade(viga, x, asw_req, cortantes, cob,
                                       phi_t, avisos)
    if cfg.considerar_torcao and viga.torcores:
        xt, Tg, Tq = resolver_torcao(viga)
        Tsd = cfg.gamma_g * np.abs(Tg) + cfg.gamma_q * np.abs(Tq)
        T_diag = (xt, cfg.gamma_g * Tg + cfg.gamma_q * Tq)
        # o eixo da barra de canto fica a cob + Ø estribo + Ø/2 da face; com o
        # estribo final mais grosso que o previsto, vale o mais grosso
        c1 = cob + max([phi_t, *phi_t_regiao.values()]) / 10.0 + 1.0
        # a armadura mínima de torção (17.5.1.6) vale para a seção que resiste
        # a torção; onde Tsd é nulo não há o que resistir, e impor o mínimo ali
        # espalharia armadura de torção pela viga inteira
        limiar = max(1e-6, 1e-3 * float(np.max(Tsd)))
        smax_reduzido = False
        asl_face = np.zeros_like(x)
        asl_lat = np.zeros_like(x)
        for i, xi in enumerate(x):
            Ti = float(np.interp(xi, xt, Tsd))
            if Ti <= limiar:
                continue
            secao = viga.secao_em(xi)
            r = cortantes[i]
            # o estribo de torção é estribo, e a barra longitudinal de
            # torção é barra longitudinal: `to.verificar` recebe os dois aços
            rt = to.verificar(secao, conc, aco, Ti, V_proj[i], r.VRd2,
                              r.asw_adotado, r.asw_min, c1, cfg.theta,
                              x=xi, aco_estribo=viga.aco_estribo)
            asw_req[i] = max(asw_req[i], rt.a_transversal)
            # o 18.3.3.2 liga o espaçamento máximo a Vd/VRd2, só. Com torção a
            # biela trabalha para os dois esforços, e a prática dos textos de
            # referência (Araújo) é tomar a soma Tsd/TRd2 + Vsd/VRd2 como
            # gatilho do 0,67: acima dele, 0,3·d ≤ 20 cm
            if rt.interacao > 0.67 and min(0.3 * r.d, 20.0) < s_max_arr[i]:
                s_max_arr[i] = min(0.3 * r.d, 20.0)
                r.s_max = float(s_max_arr[i])
                smax_reduzido = True
            torcoes.append(rt)
            fr_face, fr_lat = _fracoes_perimetro(secao, rt)
            asl_face[i] = rt.Asl * fr_face
            asl_lat[i] = rt.Asl * fr_lat
        if smax_reduzido:
            avisos.append(av.construtivo(
                "Espaçamento máximo dos estribos reduzido para 0,3·d ≤ 20 cm "
                "onde Tsd/TRd2 + Vsd/VRd2 > 0,67. A NBR 6118 (18.3.3.2) só "
                "considera o cortante nesse limite; a soma com a torção é "
                "critério de projeto, adotado por prudência."))
        if any(not t.biela_ok for t in torcoes):
            avisos.append(av.erro("A biela esmaga sob torção combinada com "
                                  "cortante (17.7.2.2); aumente a seção."))
        if torcoes and not cfg.gancho_estribo:
            avisos.append(av.erro(
                "Há torção e o estribo está sem gancho nos critérios: o item "
                "18.3.4 exige estribos de torção fechados, com as "
                "extremidades ancoradas por ganchos a 135°. Ligue o gancho "
                "do estribo."))
        # os avisos da própria verificação (geometria da seção vazada
        # equivalente, por exemplo) ficavam retidos no ResultadoTorcao. São
        # agrupados por mensagem: repetidos a cada seção da malha, seriam
        # centenas de linhas iguais
        faixas: dict[str, list[float]] = {}
        for t in torcoes:
            for m in t.avisos:
                if "biela esmaga" in m:
                    continue
                faixas.setdefault(m, []).append(t.x)
        for m, xs in faixas.items():
            avisos.append(av.prefixar(
                m, f"Torção de x = {min(xs):.2f} m a {max(xs):.2f} m: "))
        # a armadura longitudinal de torção também tem de sair no aço: entra
        # somada à flexão nas faces e como barras laterais no restante
        if torcoes:
            As_inf, As_sup, asl_lateral = _somar_asl_longitudinal(
                viga, regioes, x, asl_face, asl_lat, As_inf, As_sup, avisos,
                phi_t_regiao, phi_flexao)

    # -- 6. estribos --------------------------------------------------------
    zonas: list[det.ZonaEstribo] = []
    xs_apoios = viga.x_apoios
    # o laço percorre **trechos**, não tramos: o estribo é uma peça, e o
    # comprimento dela sai da seção. Uma faixa que atravessasse a mudança de
    # seção especificaria um estribo de 206 cm no pedaço em que a viga tem
    # 60 cm de altura -- ele não cabe, e era o que saía
    for tr in viga.trechos:
        a, b = tr.x_ini, tr.x_fim
        # os estribos cobrem a viga inteira, inclusive o trecho que entra nos
        # pilares de extremidade -- não existe trecho de viga sem estribo
        if tr.k == 0:
            a = viga.x_inicio_fisico
        if tr.k == len(viga.trechos) - 1:
            b = viga.x_fim_fisico
        m = (x >= a - 1e-9) & (x <= b + 1e-9)
        asw_max = float(np.max(asw_req[m])) if m.any() else 0.0
        # a bitola imposta continua sendo **por tramo**: é assim que o usuário
        # a escolhe na tabela, e um tramo partido em dois trechos recebe a
        # mesma escolha nos dois
        imposta = float(cfg.bitolas_estribo.get(str(tr.tramo), 0.0) or 0.0)
        phi_e = imposta or det.escolher_estribo(
            asw_max, float(np.min(s_max_arr[m])), tr.secao.bw,
            n_ramos_ef, phi_t)
        zonas += det.detalhar_estribos(x, asw_req, s_max_arr, phi_e,
                                       n_ramos_ef, a, b, tramo=tr.tramo,
                                       trecho=tr.k)

    if cfg.uniformizar_estribos:
        antes = len(zonas)
        zonas = det.uniformizar(zonas)
        if antes > len(zonas):
            avisos.append(av.construtivo(
                f"Distribuição de estribos uniformizada: as {antes} faixas do "
                f"escalonamento viraram {len(zonas)}, uma por trecho de seção "
                f"constante, cada uma com a distribuição mais conservadora do "
                f"seu trecho. Custa aço e simplifica a conferência na obra. Um "
                f"trecho e não um tramo porque o estribo é outra peça de cada "
                f"lado de uma mudança de seção."))

    # faixas vizinhas da mesma peça com espaçamento praticamente igual são uma
    # só. Roda **depois** da uniformização: é ela que faz "uma distribuição por
    # trecho" virar "uma por tramo" onde a seção não muda, e que apaga a divisa
    # entre dois trechos de seção igual -- divisa que não é divisa de nada
    antes_fusao = len(zonas)
    zonas = det.fundir_faixas_proximas(
        zonas, lambda k: viga.trechos[min(k, len(viga.trechos) - 1)].secao)
    if antes_fusao > len(zonas):
        avisos.append(av.construtivo(
            f"Distribuição de estribos: {antes_fusao} faixas viraram "
            f"{len(zonas)}. Faixas vizinhas da mesma peça com espaçamento a "
            f"menos de {(det.TOLERANCIA_FUSAO_FAIXA - 1) * 100:.0f} % de "
            f"diferença foram unidas na mais apertada — uma faixa a mais no "
            f"desenho por 1 cm de espaçamento não se paga, e a divisa entre "
            f"dois trechos de seção igual não é divisa de nada."))

    # a bitola imposta pelo usuário pode não dar conta: o espaçamento
    # comercial tem piso, e sem esta conferência o trecho sairia com armadura
    # abaixo da necessária, em silêncio
    for z in zonas:
        if z.asw_ef < z.asw_req - 1e-6:
            avisos.append(av.erro(
                f"Tramo {z.tramo + 1}, trecho de {z.x_ini:.2f} a "
                f"{z.x_fim:.2f} m: o estribo Ø{z.phi:g} c/{z.s:g} dá "
                f"{z.asw_ef:.2f} cm²/m e são necessários {z.asw_req:.2f}. "
                f"Aumente a bitola do estribo ou a seção."))

    # -- 7. ELS -------------------------------------------------------------
    flechas: list[els.ResultadoFlecha] = []
    if cfg.verificar_els:
        flechas = _verificar_flechas(viga, est, combs, regioes, avisos)
        _verificar_fissuracao(viga, est, combs, regioes)

    fadigas: list[fad.ResultadoFadiga] = []
    fadigas_estribo: list[fad.ResultadoFadigaEstribo] = []
    if cfg.verificar_fadiga:
        fadigas, fadigas_estribo = _verificar_fadiga(
            viga, est, combs, regioes, zonas, x, cortantes, avisos)

    # -- 8. detalhamento ----------------------------------------------------
    # com a distribuição uniformizada, a bitola do estribo pode ter de subir
    # para absorver a costura da emenda -- e ela precisa estar decidida **antes**
    # de montar as barras de canto e os ganchos. A barra de canto é
    # dimensionada pela bitola do estribo (18.3.3.2), e o gancho dela pela sua
    # própria bitola: decidir depois obrigava a refazer porta-estribo, emenda e
    # gancho em cascata, e cada refazimento abria o seguinte. Um pré-passe
    # descartável descobre a exigência; o passe real monta tudo uma vez, já com
    # a bitola final
    if cfg.uniformizar_estribos:
        _antecipar_reforco_da_costura(viga, regioes, zonas, x, As_inf, As_sup,
                                      cortantes, asl_lateral)
    else:
        # sem uniformizar, a costura entra nas faixas só onde há emenda, com um
        # espaçamento padrão: pedaços de estribo extra de outra posição, com
        # contagem e espaçamento diferentes em cada terço, sobrepostos a um
        # estribo que corre o vão inteiro, não são detalhamento que se entregue
        faixas_de_costura = _antecipar_costura_nas_faixas(
            viga, regioes, zonas, x, As_inf, As_sup, cortantes, asl_lateral)
        if faixas_de_costura:
            phi_c, s_c = faixas_de_costura[0][2], faixas_de_costura[0][3]
            trechos = "; ".join(f"x = {xa:.2f} a {xb:.2f} m"
                                for xa, xb, *_ in faixas_de_costura)
            avisos.append(av.construtivo(
                f"Costura das emendas por traspasse (9.5.2.4.1) absorvida pela "
                f"distribuição dos estribos: Ø{phi_c:g} c/{s_c:g} no traspasse "
                f"de cada emenda ({trechos}), todos com o mesmo espaçamento. "
                f"Os estribos desses trechos são da mesma posição do restante "
                f"do tramo, e não estribos extra de outra posição."))

    apoios_extremos: list[anc.ApoioExtremo] = []
    grampos_ancoragem: list[gr.Grampos] = []
    posicoes = _montar_posicoes(viga, regioes, zonas, x, As_inf, As_sup,
                                cortantes, avisos, asl_lateral,
                                apoios_extremos, grampos_ancoragem)
    ancoragens_negativas = _ancorar_negativa_nos_extremos(
        viga, regioes, posicoes, avisos)
    ancoragens_torcao = _ancorar_torcao_nos_extremos(viga, posicoes, avisos)
    _comprimentos_com_ganchos(viga, posicoes)       # a perna pode ter crescido
    _repartir_barras_longas(viga, posicoes, avisos, x, As_inf, As_sup)
    _costurar_emendas(viga, posicoes, zonas, avisos)
    _armar_suspensao(viga, posicoes, zonas, avisos)
    _verificar_cobrimento(viga, posicoes, zonas, avisos)
    # estribos idênticos são uma posição só, e a numeração fecha sem buraco
    antigos = {id(p): p.numero for p in posicoes}
    posicoes = det.agrupar_transversais(posicoes)
    det.renumerar(posicoes)
    _atualizar_referencias(posicoes, antigos, avisos, regioes)
    pedidos_de_bitola = _verificar_ductilidade_adotada(viga, regioes,
                                                       posicoes, avisos)
    avisos += [av.erro(p) for p in conferir_continuidade(viga, posicoes, aco)]
    avisos += [av.erro(p) for p in conferir_ganchos(viga, posicoes)]
    quant = _quantitativo(viga, posicoes)

    reacoes = []
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        reacoes.append({
            "apoio": k + 1, "x": xs_apoios[k], "tipo": ap.tipo,
            "R_max": float(env.reacoes_max[k]), "R_min": float(env.reacoes_min[k]),
            "M_max": float(env.momentos_apoio_max[k]),
            "M_min": float(env.momentos_apoio_min[k])})

    for r in regioes:
        avisos += [av.prefixar(a, f"{r.nome}: ") for a in r.avisos]

    return ResultadoViga(
        viga=viga, estrutura=est, envoltoria=env, combinacoes=combs,
        momentos_projeto=momentos, regioes=regioes, x=x, As_req_inf=As_inf,
        As_req_sup=As_sup, Vsd_projeto=V_proj, asw_req=asw_req,
        cortantes=cortantes, zonas_estribo=zonas, torcoes=torcoes,
        T_diagrama=T_diag, flechas=flechas, posicoes=posicoes,
        quantitativo=quant, avisos=avisos, reacoes=reacoes,
        fadigas=fadigas, fadigas_estribo=fadigas_estribo,
        apoios_extremos=apoios_extremos, grampos=grampos_ancoragem,
        ancoragens_negativas=ancoragens_negativas,
        ancoragens_torcao=ancoragens_torcao,
        pedidos_de_bitola=pedidos_de_bitola)


# ---------------------------------------------------------------------------
# Diagramas de armadura
# ---------------------------------------------------------------------------

def _regiao_construtiva(viga: Viga, mp: cb.MomentoProjeto, secao: Secao,
                        nome: str, a: float, b: float) -> Regiao:
    """Região sem momento de tração na face: apenas barras construtivas."""
    cfg = viga.config
    cob = _cobrimento(viga)
    # sem momento na face, a barra existe só para fechar o canto do estribo
    arr = det.montar_arranjo(secao, 0.0,
                             _phi_imposta(viga, nome)
                             or det.PHI_PORTA_ESTRIBO, cob,
                             cfg.phi_estribo, cfg.d_agregado,
                             n_min=det.CANTOS_POR_FACE, n_ramos=cfg.n_ramos)
    res = fl.dimensionar(secao, viga.concreto, viga.aco, 1e-6,
                         cob + cfg.phi_estribo / 10.0 + 1.0,
                         secao.h - arr.d, delta=cfg.redistribuicao)
    return Regiao(
        tipo=mp.regiao, indice=mp.indice, nome=nome, x=mp.x, x_ini=a, x_fim=b,
        face="inferior", M=0.0, secao=secao, flexao=res, arranjo=arr,
        arranjo_comprimido=None, d=arr.d, construtiva=True,
        trecho=mp.trecho,
        avisos=[av.construtivo(
            "Tramo sem momento positivo: adotadas apenas barras construtivas "
            "(porta-estribos) na face inferior.")])


def _d_face(viga: Viga, regioes: list[Regiao], xi: float, face: str) -> float:
    """Altura útil adotada em ``xi`` para a face pedida."""
    candidatas = [r for r in regioes
                  if r.face == face and r.x_ini - 1e-9 <= xi <= r.x_fim + 1e-9]
    if candidatas:
        return min(r.d for r in candidatas)
    secao = viga.secao_em(xi)
    return _d_estimado(secao, viga)


def _prolongar_ate_o_apoio(viga: Viga, regioes: list[Regiao],
                           x: np.ndarray, As_inf: np.ndarray,
                           momentos, avisos: list[str]) -> np.ndarray:
    """Piso de armadura positiva nos apoios -- item 18.3.2.4-c).

    O item manda prolongar até o apoio, **extremo ou intermediário**, uma
    fração da armadura de tração do vão correspondente ao máximo momento
    positivo do tramo:

        As,apoio >= 1/3 As,vão, se Mapoio for nulo ou negativo com
                                |Mapoio| <= 0,5 Mvão;
        As,apoio >= 1/4 As,vão, se Mapoio for negativo com
                                |Mapoio| >  0,5 Mvão.

    A imposição entra como **piso no diagrama de armadura necessária**, e não
    como remendo nas barras já escalonadas: é o diagrama que o escalonamento
    cobre, então elevá-lo perto do apoio faz o próprio escalonamento prolongar
    as barras, com a decalagem e a ancoragem que ele já sabe aplicar. Corrigir
    depois, mexendo nas barras, obrigaria a refazer decalagem, traspasse e
    gancho -- a cascata que já se pagou caro em outra parte deste programa.

    O piso vale na **seção do apoio**; do lado de dentro do vão o diagrama
    volta ao que o momento pede, e o escalonamento resolve a transição.
    """
    if As_inf.size == 0:
        return As_inf
    saida = As_inf.copy()
    xs = viga.x_apoios
    for k, ap in enumerate(viga.apoios):
        if ap.tipo == "livre":
            continue
        # o vão que governa é o de maior momento positivo entre os vizinhos:
        # é dele que sai a "armadura de tração do vão" do item
        vizinhos = [r for r in regioes if r.tipo == "vao"
                    and k in (r.indice, r.indice + 1)]
        if not vizinhos:
            continue
        governa = max(vizinhos, key=lambda r: r.arranjo.As_ef)
        As_vao = governa.arranjo.As_ef
        M_vao = abs(governa.M)
        M_apoio = abs(next((r.M for r in regioes if r.tipo == "apoio"
                            and r.indice == k and r.face == "superior"), 0.0))
        fracao = 1.0 / 4.0 if M_apoio > 0.5 * M_vao + 1e-9 else 1.0 / 3.0
        piso = fracao * As_vao
        meia = ap.largura / 200.0
        m = (x >= xs[k] - meia - 1e-9) & (x <= xs[k] + meia + 1e-9)
        if not m.any():
            m = np.array([abs(xi - xs[k]) < 1e-6 for xi in x])
        if not m.any() or float(saida[m].min()) >= piso - 1e-9:
            continue
        saida[m] = np.maximum(saida[m], piso)
        avisos.append(av.construtivo(
            f"Apoio {k + 1}: exigida no apoio a armadura positiva de "
            f"{piso:.2f} cm², {'1/4' if fracao < 0.3 else '1/3'} da armadura "
            f"do vão ({As_vao:.2f} cm² em {governa.nome}), como exige o item "
            f"18.3.2.4-c) — o momento no apoio "
            f"{'passa de' if fracao < 0.3 else 'não passa de'} metade do "
            f"momento do vão ({M_apoio:.1f} contra {M_vao:.1f} kN.m). O "
            f"diagrama de armadura pedia menos naquela seção, e o piso do "
            f"item foi imposto antes do escalonamento."))
    return saida


def _As_ao_longo(viga: Viga, x: np.ndarray, M: np.ndarray, d: np.ndarray,
                 face: str) -> np.ndarray:
    """Área de aço necessária em cada seção, cm² (sem o mínimo)."""
    conc, aco, cfg = viga.concreto, viga.aco, viga.config
    cob = viga.ambiente.cobrimento_nominal
    d_linha = cob + cfg.phi_estribo / 10.0 + 1.0
    As = np.zeros_like(x)
    for i, xi in enumerate(x):
        Mi = M[i]
        if (face == "inferior" and Mi <= 0) or (face == "superior" and Mi >= 0):
            continue
        secao = viga.secao_em(xi)
        try:
            r = fl.dimensionar(secao, conc, aco, Mi, d_linha,
                               secao.h - d[i], delta=cfg.redistribuicao)
            As[i] = r.As
        except ValueError:
            As[i] = float("nan")
    return As


# ---------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------

def _verificar_flechas(viga: Viga, est: Estrutura, combs: list[cb.Combinacao],
                       regioes: list[Regiao], avisos: list[str]
                       ) -> list[els.ResultadoFlecha]:
    """Flecha de cada tramo com a rigidez equivalente de Branson."""
    cfg = viga.config
    conc, aco = viga.concreto, viga.aco
    alpha_e = aco.Es / conc.Ecs

    # momento de serviço (quase permanente) e inércia equivalente por tramo
    _, _, sols_qp = cb.envoltoria_servico(est, "ELS-qp", combs)
    x = est.x
    M_qp_max = np.max(np.array([s.M for s in sols_qp]), axis=0)
    M_qp_min = np.min(np.array([s.M for s in sols_qp]), axis=0)

    I_eq: list[float] = []
    dados: list[tuple] = []
    for i, tramo in enumerate(viga.tramos):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        m = (x >= a - 1e-9) & (x <= b + 1e-9)
        Ma_pos = float(np.max(M_qp_max[m])) if m.any() else 0.0
        Ma_neg = float(np.min(M_qp_min[m])) if m.any() else 0.0
        # O item 17.3.2.1.1 diz qual é o Ma da rigidez equivalente: "o momento
        # fletor na seção crítica do vão considerado, ou seja, o **momento
        # máximo no vão** para vigas biapoiadas ou contínuas e **momento no
        # apoio para balanços**". Não é o maior dos dois: num tramo contínuo o
        # momento do apoio quase sempre supera o do vão, e usá-lo traria para a
        # conta a armadura do apoio, que é maior -- a seção sairia mais rígida e
        # a flecha, menor. O erro seria sistemático e para o lado inseguro.
        e_balanco = (viga.apoios[i].tipo == "livre"
                     or viga.apoios[i + 1].tipo == "livre")
        no_apoio = e_balanco or Ma_pos <= 1e-9
        if no_apoio:
            # balanço, ou tramo inteiro sob momento negativo -- aí não existe
            # "máximo no vão" e a seção crítica é mesmo a do apoio
            face, Ma = "superior", abs(Ma_neg)
            candidatas = [r for r in regioes if r.tipo == "apoio"
                          and r.indice in (i, i + 1)]
            reg = max(candidatas, key=lambda r: abs(r.M)) if candidatas else None
        else:
            face, Ma = "inferior", Ma_pos
            reg = next((r for r in regioes if r.tipo == "vao"
                        and r.indice == i and not r.construtiva), None)
        As = reg.arranjo.As_ef if reg else 0.0
        d = reg.d if reg else _d_estimado(tramo.secao, viga)
        As_c = reg.arranjo_comprimido.As_ef if reg and reg.arranjo_comprimido \
            else 0.0
        e2 = els.estadio_ii(tramo.secao, alpha_e, As, d, As_c,
                            viga.ambiente.cobrimento_nominal + 1.5, face)
        Mr = els.momento_fissuracao(tramo.secao, conc, face)
        Ieq, _ = els.inercia_equivalente(tramo.secao, conc, Ma, Mr, e2.I)
        I_eq.append(Ieq)
        dados.append((Ma, e2.I, As_c, d, face))

    # reanálise com a rigidez equivalente
    est_els = resolver(viga, inercias=I_eq)
    f_qp, f_qp_neg, _ = cb.envoltoria_servico(est_els, "ELS-qp", combs)
    # parcela permanente isolada (para o deslocamento após a alvenaria)
    nt = len(viga.tramos)
    f_g = combinar(est_els, np.ones(nt), np.zeros(nt)).flecha
    # parcela variável isolada, para a linha de vibrações da Tabela 13.3
    f_q = combinar(est_els, np.zeros(nt), cfg.psi1 * np.ones(nt)).flecha

    resultados: list[els.ResultadoFlecha] = []
    for i, tramo in enumerate(viga.tramos):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        m = (est_els.x >= a - 1e-9) & (est_els.x <= b + 1e-9)
        balanco = (viga.apoios[i].tipo == "livre"
                   or viga.apoios[i + 1].tipo == "livre")
        f_i = _extremo_com_sinal(f_qp[m], f_qp_neg[m]) * 100.0     # cm
        f_perm = _extremo_com_sinal(f_g[m], f_g[m]) * 100.0
        Ma, I_II, As_c, d, face = dados[i]
        rho_linha = As_c / (tramo.secao.bw * d) if d > 0 else 0.0
        resultados.append(els.avaliar_flecha(
            tramo=i, vao_m=tramo.L, balanco=balanco, secao=tramo.secao,
            concreto=conc, Ma=Ma, I_II=I_II, f_imediata_cm=f_i,
            f_permanente_cm=f_perm, rho_linha=rho_linha, t=cfg.tempo_meses,
            t0=cfg.t0_meses, lim_visual=cfg.limite_flecha_visual,
            lim_alvenaria=cfg.limite_flecha_alvenaria, face=face,
            parede=cfg.parede_apoiada,
            f_variavel_cm=_extremo_com_sinal(f_q[m], f_q[m]) * 100.0,
            lim_vibracao=(cfg.limite_flecha_vibracao
                          if cfg.verificar_vibracao else 0.0),
            lim_piso_total=(cfg.limite_piso_total
                            if cfg.verificar_piso_plano else 0.0),
            lim_piso_apos=(cfg.limite_piso_apos
                           if cfg.verificar_piso_plano else 0.0)))
        avisos += [av.prefixar(a, f"Tramo {i + 1}: ")
                   for a in resultados[-1].avisos]
    return resultados


def _extremo_com_sinal(a: np.ndarray, b: np.ndarray) -> float:
    """Valor de maior módulo entre os extremos das duas envoltórias."""
    if a.size == 0:
        return 0.0
    valores = (float(np.max(a)), float(np.min(b)))
    return max(valores, key=abs)


def _verificar_fissuracao(viga: Viga, est: Estrutura,
                          combs: list[cb.Combinacao],
                          regioes: list[Regiao]) -> None:
    """Preenche a verificação de fissuras de cada região."""
    conc, aco = viga.concreto, viga.aco
    sols = [combinar(est, c.fg, c.fq, c.nome)
            for c in combs if c.tipo == "ELS-frequente"]
    if not sols:
        return
    M_max = np.max(np.array([s.M for s in sols]), axis=0)
    M_min = np.min(np.array([s.M for s in sols]), axis=0)
    for r in regioes:
        if r.construtiva:
            continue
        M = float(np.interp(r.x, est.x, M_max if r.face == "inferior"
                            else M_min))
        As_c = r.arranjo_comprimido.As_ef if r.arranjo_comprimido else 0.0
        r.fissuracao = els.abertura_fissuras(
            r.secao, conc, aco, M, r.arranjo.As_ef, r.d, r.arranjo.phi,
            r.arranjo.n, viga.ambiente.wk_limite, r.nome, As_c,
            viga.ambiente.cobrimento_nominal + 1.5, r.face,
            r.arranjo.camadas, av_camadas=r.arranjo.av)
        r.avisos += r.fissuracao.avisos


# ---------------------------------------------------------------------------
# Posições de armadura
# ---------------------------------------------------------------------------

def _montar_posicoes(viga: Viga, regioes: list[Regiao],
                     zonas: list[det.ZonaEstribo], x: np.ndarray,
                     As_inf: np.ndarray, As_sup: np.ndarray,
                     cortantes: list[ci.ResultadoCortante],
                     avisos: list[str],
                     asl_lateral: list[tuple[int, float]] | None = None,
                     apoios_extremos: list | None = None,
                     grampos_ancoragem: list | None = None
                     ) -> list[det.Posicao]:
    """Monta as posições de armadura a partir do escalonamento."""
    cfg = viga.config
    if apoios_extremos is None:
        apoios_extremos = []
    if grampos_ancoragem is None:
        grampos_ancoragem = []
    conc, aco = viga.concreto, viga.aco
    cob = viga.ambiente.cobrimento_nominal
    xs = viga.x_apoios
    posicoes: list[det.Posicao] = []
    numero = 1
    # a bitola do estribo é conhecida desde já: a barra que fecha o canto dele
    # não pode ser mais fina (18.3.3.2), e isso vale também para a armadura
    # construtiva de uma face sem momento de tração, que nasce com a bitola de
    # porta-estribo. Antes ela saía Ø6,3 fixa e brigava com um estribo Ø8
    phi_estribo_max = max((z.phi for z in zonas), default=cfg.phi_estribo)

    # a ancoragem dos apoios extremos é resolvida **antes** de montar as
    # barras: é dela que sai o grampo, e é o grampo que define onde a barra
    # pode terminar. Só precisa das regiões e dos cortantes, que já existem
    _verificar_apoios_extremos(viga, regioes, cortantes, avisos,
                               apoios_extremos, grampos_ancoragem)
    # os grampos entram como posição: sem isso não pesam no quantitativo nem
    # aparecem no desenho, e grampo que não sai na lista de aço não é comprado
    for g in grampos_ancoragem:
        if g.n <= 0:
            continue
        k = g.apoio - 1
        x_ap = viga.x_apoios[k]
        # o grampo abraça a **parte reta do gancho**, e para alcançá-la ele
        # começa onde a barra começa: no cobrimento da extremidade da viga. A
        # ponta dele fica em "face do pilar + lb1" -- lb1 é medido da face,
        # como a cota da figura de referência mostra. A perna, portanto, é
        # maior que lb1: ela inclui o trecho dentro do pilar
        for_dentro = 1.0 if k == 0 else -1.0
        x_face = x_ap + for_dentro * viga.apoios[k].largura / 200.0
        x_ponta = x_face + for_dentro * g.lb1 / 100.0
        xi_util, xf_util = _limites_uteis(viga)
        x_inicio = xi_util if k == 0 else xf_util
        i_trecho = viga.trecho_em(x_face)
        vao = _vao_do_grampo(viga, i_trecho)
        perna = abs(x_ponta - x_inicio) * 100.0
        posicoes.append(det.Posicao(
            numero=numero, tipo="grampo", n=g.n, phi=g.phi, face="alma",
            n_ramos_efetivo=gr.PERNAS,
            x_ini=min(x_inicio, x_ponta), x_fim=max(x_inicio, x_ponta),
            perna=perna, papel="ancoragem", espelhado=(k != 0),
            # o U consome as duas pernas **e** a dobra que as fecha na largura
            comprimento=gr.PERNAS * perna + vao,
            descricao=f"Grampos de ancoragem do apoio {g.apoio} "
                      f"(face {g.face}; lb1 = {g.lb1:.0f} cm da face do pilar "
                      f"à ponta)",
            tramo=min(g.apoio - 1, len(viga.tramos) - 1)))
        numero += 1

    recuos = _recuos_do_grampo(viga, grampos_ancoragem)

    Vsd = np.array([c.Vsd for c in cortantes])
    Vc = np.array([c.Vc for c in cortantes])

    for r in sorted(regioes, key=lambda r: (r.face != "inferior", r.x)):
        secao = r.secao
        # decalagem com o cortante máximo da região
        m = (x >= r.x_ini - 1e-9) & (x <= r.x_fim + 1e-9)
        i_pior = int(np.argmax(Vsd * m)) if m.any() else 0
        a_l, _ = anc.decalagem(r.d, Vsd[i_pior], Vc[i_pior],
                              cfg.modelo_cisalhamento, cfg.theta,
                              cfg.alpha_estribo)
        anco = anc.ancorar(conc, aco, r.arranjo.phi, r.flexao.As_adotado,
                           r.arranjo.As_ef, r.face, secao.h)
        r.ancoragem = anco
        if r.flexao is not None:
            # a ancoragem é calculada depois da flexão; estes valores não
            # apareciam em saída nenhuma
            r.flexao.memoria["lb básico (múltiplos de phi)"] = anco.lb_em_phi
            r.flexao.memoria["lb,mín (cm)"] = anco.lb_min
            r.flexao.memoria["As calculada na ancoragem (cm²)"] = anco.As_calc

        if r.construtiva:
            x_min, x_max, dobra_i, dobra_f = _limites_barra_vao(viga, r, anco, recuos)
            posicoes.append(det.Posicao(
                numero=numero, tipo="porta", n=r.arranjo.n,
                phi=r.arranjo.phi,
                face=r.face, x_ini=x_min, x_fim=x_max,
                comprimento=(x_max - x_min) * 100.0 + dobra_i + dobra_f,
                dobra_ini=dobra_i, dobra_fim=dobra_f,
                descricao=f"{r.nome} - barras construtivas",
                # existe só para fechar o canto do estribo: sem momento de
                # tração na face, ela não carrega força calculada, e a bitola
                # pode subir se o estribo engrossar (18.3.3.2)
                so_canto=True, trecho=r.trecho,
                tipo_gancho=_tipo_gancho(viga, r.nome),
                tramo=viga.trechos[r.trecho].tramo))
            numero += 1
            continue

        if r.tipo == "vao":
            x_min, x_max, dobra_i, dobra_f = _limites_barra_vao(viga, r, anco, recuos)
            As_ref = As_inf
        else:
            x_min, x_max, dobra_i, dobra_f = _limites_barra_apoio(viga, r, anco, recuos)
            As_ref = As_sup

        cortes = det.escalonar(
            x, np.nan_to_num(np.maximum(As_ref, 0.0)), r.arranjo, a_l,
            anco.lb_nec, r.x_ini, r.x_fim, x_min, x_max,
            manter_ate_apoio=2 if r.tipo == "vao" else 2)
        r.cortes = cortes
        # as camadas vêm do arranjo (18.3.2.2): a primeira leva o que couber na
        # largura, as de dentro no máximo o número de ramos do estribo. Antes a
        # camada era contada pela ordem dos grupos com a capacidade da primeira,
        # e as barras iam parar em camadas que não existiam no arranjo
        vagas = list(r.arranjo.camadas) or [r.arranjo.n]
        camada_atual = 0
        for n_barras, xa, xb in det.agrupar_cortes(cortes):
            # a dobra só vale para as barras que chegam à extremidade
            d_ini = dobra_i if abs(xa - x_min) < 1e-6 else 0.0
            d_fim = dobra_f if abs(xb - x_max) < 1e-6 else 0.0
            comp = (xb - xa) * 100.0 + d_ini + d_fim
            restam = n_barras
            while restam > 0:
                while (camada_atual < len(vagas)
                       and vagas[camada_atual] <= 0):
                    camada_atual += 1
                if camada_atual >= len(vagas):        # arranjo cheio
                    vagas.append(restam)
                nesta = min(restam, vagas[camada_atual])
                vagas[camada_atual] -= nesta
                restam -= nesta
                posicoes.append(det.Posicao(
                    numero=numero, tipo="longitudinal", n=nesta,
                    phi=r.arranjo.phi, face=r.face, x_ini=xa, x_fim=xb,
                    comprimento=comp, dobra_ini=d_ini, dobra_fim=d_fim,
                    camada=camada_atual + 1,
                    descricao=f"{r.nome} - {r.face}",
                    tipo_gancho=_tipo_gancho(viga, r.nome),
                    # o trecho da barra é o da seção que a dimensionou, e não o
                    # da esquerda por convenção: é ele que diz o nível e a
                    # largura. Sem gravá-lo, uma barra dimensionada com a seção
                    # de um trecho e prolongada pelo escalonamento até o outro
                    # era atribuída ao trecho do seu ponto médio -- e aí não
                    # era cortada na junta, porque o lado saía errado
                    trecho=r.trecho, so_canto=r.construtiva,
                    tramo=viga.trechos[r.trecho].tramo))
                numero += 1

        if r.arranjo_comprimido is not None:
            arrc = r.arranjo_comprimido
            face_c = "superior" if r.face == "inferior" else "inferior"
            posicoes.append(det.Posicao(
                numero=numero, tipo="longitudinal", n=arrc.n, phi=arrc.phi,
                face=face_c, x_ini=r.x_ini, x_fim=r.x_fim,
                comprimento=(r.x_fim - r.x_ini) * 100.0 + 2 * anco.lb_nec,
                comprimida=True,
                descricao=f"{r.nome} - armadura comprimida",
                tipo_gancho=_tipo_gancho(viga, r.nome),
                trecho=r.trecho, tramo=viga.trechos[r.trecho].tramo))
            numero += 1

    # estribos. O 18.3.4 exige que o estribo de torção seja fechado, com as
    # extremidades ancoradas por ganchos a 135°; a ponta reta de 5 Ø (>= 5 cm)
    # que o comprimento conta é a do gancho a 135° (9.4.6.1), e o desenho não
    # mostrava o ângulo. Num tramo com torção ele é dito na posição
    com_torcao = {i for i, _ in (asl_lateral or [])}
    for z in zonas:
        descricao = f"Estribos do tramo {z.tramo + 1}"
        if z.tramo in com_torcao and cfg.gancho_estribo:
            descricao += (" — fechados, ganchos a 135° com ponta reta de "
                          "5 Ø ≥ 5 cm (18.3.4 e 9.4.6.1)")
        comp = _comprimento_estribo(
            viga.trechos[min(z.trecho, len(viga.trechos) - 1)].secao, cob,
            z.phi,
                                    cfg.pernas_amarracao_estribo, z.n_ramos,
                                    cfg.gancho_estribo)
        posicoes.append(det.Posicao(
            numero=numero, tipo="estribo", n_ramos_efetivo=z.n_ramos,
            n=z.n_estribos, phi=z.phi,
            face="alma", x_ini=z.x_ini, x_fim=z.x_fim, comprimento=comp,
            s=z.s, descricao=descricao, tramo=z.tramo))
        numero += 1

    # estribo da MESA: numa seção com mesa o estribo é detalhado em duas peças
    # conjuntas -- o laço vertical que abraça a alma (acima, igual ao da viga
    # retangular) e um laço horizontal que abraça a mesa. Os dois na mesma
    # bitola e no mesmo espaçamento: a alma continua dimensionada para o Vsd
    # inteiro, e o da mesa acompanha, não a reparte.
    #
    # É critério de detalhamento de projeto, não prescrição da norma: o item
    # 18.3.7 fixa só o mínimo de 1,5 cm²/m atravessando o plano de ligação
    # (ver `_armar_ligacao_mesa`, que passou a ser o complemento de quando o
    # laço da mesa não alcança esse mínimo sozinho).
    for z in zonas:
        secao_z = viga.trechos[min(z.trecho, len(viga.trechos) - 1)].secao
        if secao_z.tipo == "retangular" or secao_z.bf <= secao_z.bw + 1e-9:
            continue
        comp_mesa = _comprimento_estribo(
            Secao(bw=secao_z.bf, h=secao_z.hf), cob, z.phi,
            cfg.pernas_amarracao_estribo, 2, cfg.gancho_estribo)
        posicoes.append(det.Posicao(
            numero=numero, tipo="estribo", papel="mesa", n_ramos_efetivo=2,
            n=z.n_estribos, phi=z.phi,
            face="alma", x_ini=z.x_ini, x_fim=z.x_fim, comprimento=comp_mesa,
            s=z.s, trecho=z.trecho, tramo=z.tramo,
            descricao=(f"Estribos da mesa do tramo {z.tramo + 1} — laço de "
                       f"{secao_z.bf:g}x{secao_z.hf:g} cm abraçando a mesa, "
                       f"na bitola e no espaçamento do estribo da alma")))
        numero += 1

    # porta-estribos dos CANTOS DO LAÇO DA MESA. As pontas da mesa ficam fora
    # da largura da alma, então nenhuma armadura calculada passa por elas: os
    # quatro cantos do laço ficariam sem barra para se apoiar. A bitola
    # acompanha a do estribo, porque o item 18.3.3.2 não admite barra de canto
    # mais fina que o estribo que ela trava. Um por trecho, não por faixa: a
    # barra corre o trecho inteiro, o que muda de faixa é o estribo
    for tr in viga.trechos:
        if tr.secao.tipo == "retangular" or tr.secao.bf <= tr.secao.bw + 1e-9:
            continue
        do_trecho = [z for z in zonas if z.trecho == tr.k]
        if not do_trecho:
            continue
        phi_canto = max(det.PHI_PORTA_ESTRIBO,
                        max(z.phi for z in do_trecho))
        posicoes.append(det.Posicao(
            numero=numero, tipo="porta_mesa", n=4, phi=phi_canto, face="mesa",
            x_ini=tr.x_ini, x_fim=tr.x_fim,
            comprimento=(tr.x_fim - tr.x_ini) * 100.0,
            so_canto=True, trecho=tr.k, tramo=tr.tramo,
            descricao=(f"Porta-estribos dos cantos do laço da mesa, trecho "
                       f"{tr.k + 1} — as pontas da mesa não têm armadura "
                       f"calculada passando por elas (18.3.3.2)")))
        numero += 1

    # ancoragem da armadura positiva nos apoios de extremidade (18.3.2.4)
    # porta-estribos onde alguma face fica sem armadura
    novas, numero = _armar_ligacao_mesa(viga, posicoes, numero, avisos)
    novas, numero = _porta_estribos(viga, posicoes, numero, phi_estribo_max,
                                    regioes, (x, As_inf, As_sup))
    posicoes += novas

    # juntas de tramos desalinhados: corta e ancora antes de emendar, senão a
    # emenda se apoiaria em barras que o corte vai encurtar
    novas, numero = _ganchos_nas_juntas(viga, regioes, posicoes, numero,
                                        avisos)
    posicoes += novas

    # traspasse entre posições consecutivas da mesma face
    _emendar_faces(viga, posicoes, avisos)

    # gancho em toda barra que chega a uma extremidade da viga
    _ganchos_nas_extremidades(viga, posicoes)

    # o comprimento da barra tem de ser o **desenvolvido**: a extensão vertical
    # da dobra serve para cotar, não para cortar. Num gancho semicircular a
    # diferença é quase o dobro (9,6 cm de altura contra 18,3 de aço)
    _comprimentos_com_ganchos(viga, posicoes)

    # barras laterais da armadura longitudinal de torção (17.5.1.6)
    for i_tramo, asl in (asl_lateral or []):
        tramo = viga.tramos[i_tramo]
        a, b = _extensao_da_lateral_de_torcao(viga, i_tramo)
        # a bitola imposta é a mesma tabela que a armadura de pele lê logo
        # abaixo: as duas ocupam a mesma face, e a tabela de resultados
        # oferece uma escolha só, "a armadura lateral deste tramo"
        imposta = float((cfg.bitolas_pele or {}).get(str(i_tramo), 0.0) or 0.0)
        phi_l = imposta or max(cfg.phi_min_longitudinal, det.PHI_PORTA_ESTRIBO)
        # duas faces laterais, no mínimo uma barra por face
        n_face = max(1, int(math.ceil(asl / 2.0 / area_barra(phi_l))))
        posicoes.append(det.Posicao(
            numero=numero, tipo="pele", n=2 * n_face, n_faces=2, phi=phi_l,
            face="alma", x_ini=a, x_fim=b, comprimento=(b - a) * 100.0,
            descricao=f"Armadura lateral de torção do tramo {i_tramo + 1} "
                      f"({asl:.2f} cm² distribuídos nas duas faces — 17.5.1.6)",
            tramo=i_tramo, As_torcao=asl))
        numero += 1

    # armadura de pele
    for i, tramo in enumerate(viga.tramos):
        a, b = xs[i], xs[i + 1]
        a_pele, _ = els.armadura_pele(tramo.secao, aco)
        if a_pele <= 0:
            continue
        imposta = float((cfg.bitolas_pele or {}).get(str(i), 0.0) or 0.0)
        phi_p = imposta or max(8.0, phi_estribo_max)
        secao = tramo.secao
        y0 = cob + 10.0
        y1 = max(secao.h - cob - 10.0, y0)
        # o item 17.3.5.2.3 pede espaçamento não maior que 20 cm; antes o
        # número de barras saía só da área, e numa alma alta ficava esparso
        n_area = int(math.ceil(a_pele * (secao.h / 100.0) / area_barra(phi_p)))
        d_pele = _d_face(viga, regioes, (a + b) / 2.0, "inferior")
        limite_esp = els.espacamento_pele(d_pele)
        n_esp = int(math.ceil((y1 - y0) / limite_esp)) + 1
        n_por_face = max(2, n_area, n_esp)
        alturas = ([(y0 + y1) / 2.0] if n_por_face == 1 else
                   [y0 + (y1 - y0) * k / (n_por_face - 1)
                    for k in range(n_por_face)])
        # arredondado aqui, e não em cada lugar que o escreve: a descrição
        # dizia 18 cm onde o rótulo dizia 17,7
        espacamento = round((y1 - y0) / (n_por_face - 1)
                            if n_por_face > 1 else 0.0, 1)
        # a pele do tramo é **uma** posição, com as barras das duas faces:
        # é uma armadura só, distribuída simetricamente, e a prancha a escreve
        # como "n por face x 2 faces". Antes ela era partida em duas posições
        # pela situação de aderência do item 9.3.1, o que dava dois N para a
        # mesma armadura e obrigava o montador a somar para saber quantas
        # barras a face leva
        posicoes.append(det.Posicao(
            numero=numero, tipo="pele", n=2 * n_por_face, n_faces=2,
            phi=phi_p, face="alma", x_ini=a, x_fim=b,
            comprimento=(b - a) * 100.0, s=round(espacamento, 1),
            faixa_altura=(min(alturas), max(alturas)),
            descricao=(f"Armadura de pele do tramo {i + 1} "
                       f"({a_pele:.2f} cm²/m por face, {n_por_face} por face "
                       f"a cada {espacamento:g} cm)"),
            tramo=i))
        numero += 1
        if n_esp > n_area:
            avisos_pele = (f"Armadura de pele do tramo {i + 1}: "
                           f"{n_por_face} barras por face, número imposto "
                           f"pelo espaçamento máximo de "
                           f"{limite_esp:.1f} cm (17.3.5.2.3 e 18.3.5: "
                           f"d/3 e 20 cm), e não pela área "
                           f"({n_area} bastariam).")
            if avisos_pele not in avisos:
                avisos.append(av.construtivo(avisos_pele))

    return posicoes


def _emendar_faces(viga: Viga, posicoes: list[det.Posicao],
                   avisos: list[str]) -> None:
    """Garante traspasse entre as posições que se sucedem em cada face.

    Duas barras que se encontram de topo não formam uma armadura contínua: onde
    uma acaba e a outra começa, tem de haver sobreposição de l0t (9.5.2.2.1) --
    inclusive quando as bitolas são diferentes, caso em que governa a maior
    delas. A costura é feita **sempre alongando** uma das barras; a armadura
    calculada nunca é encurtada para acomodar a emenda.
    """
    xi, xf = _limites_uteis(viga, _recuos_nas_posicoes(viga, posicoes))
    for face in ("inferior", "superior"):
        grupo = [p for p in posicoes if p.face == face
                 and p.tipo in ("longitudinal", "porta")]
        if len(grupo) < 2:
            continue
        cadeia = _cadeia_de_cobertura(grupo, xf)
        for A, B in zip(cadeia, cadeia[1:]):
            if travadas_na_junta(A, B):
                continue
            phi = max(A.phi, B.phi)          # governa a bitola maior
            h = viga.secao_em((A.x_fim + B.x_ini) / 2.0).h
            l0t = _traspasse_necessario(
                viga, phi, face, h, A.comprimida and B.comprimida) / 100.0
            falta = l0t - (A.x_fim - B.x_ini)
            if falta <= 1e-6:
                _registrar_emenda(A, B, l0t)
                continue
            # alonga a de menor bitola: é a que consome menos aço
            if A.phi <= B.phi:
                folga = xf - A.x_fim
                usado = min(falta, max(folga, 0.0))
                _alongar(A, direita=True, quanto=usado)
                if falta - usado > 1e-6:
                    _alongar(B, direita=False, quanto=falta - usado,
                             limite=xi)
            else:
                folga = B.x_ini - xi
                usado = min(falta, max(folga, 0.0))
                _alongar(B, direita=False, quanto=usado, limite=xi)
                if falta - usado > 1e-6:
                    _alongar(A, direita=True, quanto=falta - usado)
            _registrar_emenda(A, B, l0t)
            avisos.append(av.construtivo(
                f"N{A.numero} e N{B.numero} ({face}) se sucedem na mesma face: "
                f"a emenda foi prolongada para o traspasse de {l0t * 100:.0f} cm "
                f"exigido pela bitola Ø{phi:g} (9.5.2.2.1)."))


def travadas_na_junta(A: det.Posicao, B: det.Posicao) -> bool:
    """Duas barras separadas por uma junta desalinhada não formam emenda.

    Elas não estão de topo por falta de comprimento: estão em **níveis
    diferentes** da seção, cada uma ancorada no seu gancho. Cobrar traspasse
    delas seria cobrar o impossível, e alongar uma para alcançar a outra
    desfaria o gancho.
    """
    return ((A.trava_fim is not None and abs(A.x_fim - A.trava_fim) < 1e-6)
            or (B.trava_ini is not None
                and abs(B.x_ini - B.trava_ini) < 1e-6))


def _ganchos_nas_juntas(viga: Viga, regioes: list[Regiao],
                        posicoes: list[det.Posicao], numero: int,
                        avisos: list[str]
                        ) -> tuple[list[det.Posicao], int]:
    """Fecha com gancho as barras que morrem numa junta de seção desalinhada.

    Onde a face é contínua a barra atravessa o apoio e segue; onde ela termina,
    a barra do tramo maior é cortada na junta e ancorada como se estivesse numa
    extremidade da viga (18.3.2.4.1). A barra do tramo menor não é tocada: o
    nível dela existe dentro da seção maior, então ela entra normalmente.

    Cortar a barra do tramo maior deixaria o outro lado do apoio descoberto, e
    por isso cada corte gera uma barra companheira, que cobre o trecho perdido
    no tramo menor e avança sobre a junta o comprimento de ancoragem. As duas
    não formam emenda -- estão em níveis diferentes -- e a trava registrada em
    cada uma impede que o traspasse as prolongue por cima do degrau.
    """
    novas: list[det.Posicao] = []
    juntas = al.juntas(viga)
    if not juntas:
        return novas, numero

    cob = _cobrimento(viga)
    for junta in juntas:
        esq = viga.trechos[junta.trecho_esq].secao
        dir_ = viga.trechos[junta.trecho_dir].secao
        onde = _onde_e_a_junta(junta)
        avisos.append(av.construtivo(
            f"{onde}: a seção muda de {esq.descricao()} para "
            f"{dir_.descricao()} com alinhamento “{junta.alinhamento}” — "
            f"{al.descrever(esq, dir_, junta.alinhamento)}."))
        for face in al.FACES:
            lados = junta.lado_com_gancho(face)
            if not lados:
                avisos.append(av.construtivo(
                    f"{onde}: a face {face} atravessa a junta sem "
                    f"interrupção — a armadura desta face é contínua nos "
                    f"dois sentidos."))
                continue
            motivos = "; ".join(sorted({d.motivo for d in junta.fora
                                        if d.face == face}))
            numero, cortadas, so_construtivo = _cortar_na_junta(
                viga, junta, face, lados, posicoes, numero, cob, novas)
            if "esquerda" in lados and "direita" in lados:
                quem = "as barras dos dois lados param na junta"
            else:
                para, passa = (("esquerda", "direita")
                               if "esquerda" in lados
                               else ("direita", "esquerda"))
                quem = (f"as barras do lado {para} param na junta; as da "
                        f"{passa} seguem normalmente para dentro da seção "
                        f"maior")
            texto = (
                f"{onde}: a face {face} não atravessa a junta ({motivos}). "
                f"{quem}. {cortadas} barra(s) foram partidas no degrau e "
                f"ancoradas com gancho, como armadura de extremidade "
                f"(18.3.2.4.1).")
            if _face_tracionada_na_junta(regioes, junta, face):
                avisos.append(av.erro(
                    texto + " Esta face é tracionada por cálculo neste apoio: "
                    "interrompida, ela não transfere o esforço através da "
                    "junta pelas barras, e a transferência tem de ser "
                    "resolvida à parte — ancoragem no pilar, consolo ou "
                    "mudança do alinhamento."))
            else:
                avisos.append(av.construtivo(texto))
            if cortadas and so_construtivo:
                avisos.append(av.erro(
                    f"{onde}, face {face}: o critério “ancoragem "
                    f"com gancho” está desligado, então a perna na junta saiu "
                    f"apenas construtiva (8 Ø). A barra morre ali e precisa "
                    f"de ancoragem: ligue o critério ou alinhe os tramos por "
                    f"esta face."))
    return novas, numero


def _onde_e_a_junta(junta: al.Junta) -> str:
    """Frase que localiza a junta, para os avisos.

    A junta interna não tem apoio para citar, e dizer "Apoio 0" seria pior que
    não dizer nada. Uma função só para os seis avisos que precisam disto: eles
    diziam "Apoio {k+1}" cada um por sua conta, e com a junta interna todos os
    seis passariam a mentir juntos.
    """
    if junta.interna:
        return (f"Tramo {junta.tramo_esq + 1}, mudança de seção em "
                f"x = {junta.x:.2f} m")
    return f"Apoio {junta.k + 1}"


def _face_tracionada_na_junta(regioes: list[Regiao], junta: al.Junta,
                              face: str) -> bool:
    """Há armadura de cálculo (não construtiva) nesta face, nesta junta?

    No apoio a pergunta é sobre a região daquele apoio. Na junta interna não há
    região de apoio: a pergunta é se alguma região de vão que **cobre** aquele
    x traciona a face por cálculo. Sem este segundo caso, uma mudança de seção
    no meio do vão interrompendo a face tracionada passaria calada -- e é ali
    que ela é mais grave, porque no meio do vão a face inferior é justamente a
    que trabalha.
    """
    if not junta.interna:
        return any(r.tipo == "apoio" and r.indice == junta.k
                   and r.face == face and not r.construtiva for r in regioes)
    # o teste é **estritamente interior**: a região que termina exatamente na
    # junta pertence ao outro lado dela, e contá-la fazia toda mudança de seção
    # interna acusar erro -- a região do vão sempre encosta no degrau, por
    # construção, já que é o degrau que a delimita
    return any(r.face == face and not r.construtiva
               and r.x_ini + 1e-6 < junta.x < r.x_fim - 1e-6
               for r in regioes)


def _cobertura_em(posicoes: list[det.Posicao], face: str, x: float,
                  viga: Viga | None = None) -> int:
    """Quantas barras daquela face passam por ``x``, **no nível daquela face**.

    Sem ``viga`` conta por face, como antes. Com ela, exige que a barra esteja
    no nível da face do trecho em que ``x`` cai -- é a diferença entre "passa
    por aqui" e "cobre o canto do estribo daqui".
    """
    def serve(q) -> bool:
        if q.face != face or q.tipo not in ("longitudinal", "porta"):
            return False
        if not (q.x_ini - 1e-9 <= x <= q.x_fim + 1e-9):
            return False
        if viga is None:
            return True
        return al.no_nivel_da_face(viga, q, al.trecho_em(viga, x), face)

    return sum(q.n for q in posicoes if serve(q))


def _cortar_na_junta(viga: Viga, junta: al.Junta, face: str,
                     lados: set[str], posicoes: list[det.Posicao],
                     numero: int, cob: float,
                     novas: list[det.Posicao]) -> tuple[int, int, bool]:
    """Ancora na junta as barras que morrem ali, e repõe o que faltar.

    Duas coisas decidem o que acontece com cada barra:

    **O nível.** ``p.tramo`` diz em que seção a barra foi dimensionada, logo a
    que altura ela está. Se esse nível existe na seção adiante, ela passa; se
    não existe, ela é ancorada. Olhar a metade da junta em que a barra está
    daria a resposta errada: a armadura negativa de um apoio nasce atribuída ao
    tramo da esquerda e ocupa os dois lados.

    **A face do pilar.** A barra não pára no eixo do apoio, e sim na face do
    pilar oposta ao tramo dominante, descontado o cobrimento -- é até lá que o
    tramo de seção maior se apoia. Barra que já terminava antes disso é
    **prolongada** até essa face; a dobra vem depois dela.

    A barra companheira, que repõe o trecho amputado no tramo vizinho, só nasce
    quando faz falta: se além do degrau a face continua com os cantos do
    estribo cobertos, o pedaço cortado era apenas a cauda de ancoragem que
    entrava no apoio, e criar barra ali produziria aquele toco de 30 cm sem
    função nenhuma.
    """
    meia = junta.largura / 200.0
    cortadas = 0
    so_construtivo = False
    amputadas: list[tuple[det.Posicao, str, float, float, float]] = []

    for p in list(posicoes):
        if p.face != face or p.tipo not in ("longitudinal", "porta"):
            continue
        # o que decide não é de que **lado** a barra está, e sim se ela está no
        # **nível** da face que morre. Uma barra do trecho de 50 atravessa o
        # trecho elevado de 75 a 25 cm do fundo dele e volta a um trecho de 50
        # adiante: ela está do lado esquerdo da segunda junta, mas o nível que
        # morre ali é o fundo do trecho de 75, não o dela. Testando o lado, ela
        # era cortada e ganchada no meio do vão, sem razão
        t_p = al.trecho_da(viga, p)
        for lado in sorted(lados):
            t_morre = (junta.trecho_esq if lado == "esquerda"
                       else junta.trecho_dir)
            # de que lado a barra **pertence**: é o trecho que a dimensionou
            if (t_p <= junta.trecho_esq) != (lado == "esquerda"):
                continue
            # e no nível de quê. As duas condições são necessárias, e cada uma
            # sozinha erra num caso diferente: só o lado corta a barra de um
            # trecho de 50 que apenas atravessa um trecho elevado de 75 e
            # continua num de 50 adiante, num nível que não morre ali; só o
            # nível corta as barras dos **dois** lados numa mudança apenas de
            # largura, onde as cotas verticais coincidem e quem morre é o lado
            if not al.no_nivel_da_face(viga, p, t_morre, face):
                continue
            # só as barras que chegam à junta por aquele lado
            if lado == "esquerda" and p.x_fim < junta.x - meia - 1e-6:
                continue
            if lado == "direita" and p.x_ini > junta.x + meia + 1e-6:
                continue
            break
        else:
            continue                          # o nível existe adiante: passa

        # cada lado recua o cobrimento para dentro do seu próprio concreto
        x_corte = junta.x_gancho_de(t_morre, cob)
        # o gancho é dobrado dentro do concreto **do lado que morre**: é a
        # seção dele que tem de acomodar a perna
        secao = viga.trechos[t_morre].secao
        anco = anc.ancorar(viga.concreto, viga.aco, p.phi, 1.0, 1.0, face,
                           secao.h, gancho=True, cobrimento_normal=cob)
        perna = _gancho_apoio(secao, cob, p.phi, anco.lb_nec, junta.largura,
                              viga.config.ancoragem_gancho, viga.aco,
                              _tipo_gancho(viga),
                              viga.config.reduzir_ancoragem_com_gancho)
        if perna <= 0.0:
            so_construtivo = True
        gancho = max(perna, _gancho_livre(
            secao, cob, p.phi, viga.aco,
            p.tipo_gancho or _tipo_gancho(viga)))

        if lado == "esquerda":
            amputadas.append((p, lado, x_corte, p.x_fim, p.dobra_fim))
            p.x_fim = x_corte
            p.dobra_fim = max(p.dobra_fim, gancho)
            p.trava_fim = x_corte
        else:
            amputadas.append((p, lado, p.x_ini, x_corte, p.dobra_ini))
            p.x_ini = x_corte
            p.dobra_ini = max(p.dobra_ini, gancho)
            p.trava_ini = x_corte
        p.comprimento = ((p.x_fim - p.x_ini) * 100.0
                         + p.dobra_ini + p.dobra_fim)
        p.descricao = (f"{p.descricao} — ancorada no degrau de "
                       f"{_onde_e_a_junta(junta)}")
        cortadas += 1

    # -- o que ficou descoberto do outro lado do degrau --------------------
    for lado in sorted(lados):
        # a companheira vive no trecho vizinho e atravessa o degrau para
        # ancorar. Se o vizinho também morre aqui, nada atravessa: cada lado
        # fica com as suas barras ancoradas, e uma barra do nível de um trecho
        # avançando sobre o outro sairia fora da seção de lá
        vizinho = "direita" if lado == "esquerda" else "esquerda"
        if vizinho in lados:
            continue
        t_vizinho = (junta.trecho_dir if lado == "esquerda"
                     else junta.trecho_esq)
        i_vizinho = viga.trechos[t_vizinho].tramo
        # sonda dentro do tramo vizinho, logo depois do degrau
        sonda = (junta.x_face + 0.02 if lado == "esquerda"
                 else junta.x_face - 0.02)
        if _cobertura_em(posicoes + novas, face, sonda,
                         viga) >= det.CANTOS_POR_FACE:
            continue                          # a face segue coberta: nada a repor
        candidatas = [t for t in amputadas if t[1] == lado
                      and (t[3] - t[2]) > 1e-6]
        if not candidatas:
            continue
        p, _, ini, fim, dobra = max(candidatas, key=lambda t: t[3] - t[2])
        secao_viz = viga.trechos[t_vizinho].secao
        anco_viz = anc.ancorar(viga.concreto, viga.aco, p.phi, 1.0, 1.0, face,
                              secao_viz.h, gancho=False,
                              cobrimento_normal=cob)
        # o avanço é medido do **degrau**, não do corte: medido do corte, a
        # companheira atravessava a face e ia parar dentro do concreto do
        # outro tramo, no nível errado e fora da seção de lá
        avanco = min(anco_viz.lb_nec / 100.0, max(fim - ini, 0.0))
        borda = junta.x_face
        if lado == "esquerda":
            nova = det.Posicao(
                numero=numero, tipo=p.tipo, n=p.n, phi=p.phi, face=face,
                x_ini=borda - avanco, x_fim=max(fim, borda), comprimento=0.0,
                dobra_ini=0.0, dobra_fim=dobra, camada=p.camada,
                comprimida=p.comprimida, tramo=i_vizinho,
                trecho=t_vizinho,
                trava_ini=borda - avanco,
                descricao=f"Continuidade da face {face} no tramo "
                          f"{i_vizinho + 1}, além da junta de "
                          f"{_onde_e_a_junta(junta)}")
        else:
            nova = det.Posicao(
                numero=numero, tipo=p.tipo, n=p.n, phi=p.phi, face=face,
                x_ini=min(ini, borda), x_fim=borda + avanco, comprimento=0.0,
                dobra_ini=dobra, dobra_fim=0.0, camada=p.camada,
                comprimida=p.comprimida, tramo=i_vizinho,
                trecho=t_vizinho,
                trava_fim=borda + avanco,
                descricao=f"Continuidade da face {face} no tramo "
                          f"{i_vizinho + 1}, antes da junta do apoio "
                          f"{junta.k + 1}")
        nova.comprimento = ((nova.x_fim - nova.x_ini) * 100.0
                            + nova.dobra_ini + nova.dobra_fim)
        novas.append(nova)
        numero += 1
    return numero, cortadas, so_construtivo


def _cadeia_de_cobertura(grupo: list[det.Posicao], x_fim: float
                         ) -> list[det.Posicao]:
    """Sequência de posições que garante a continuidade da face.

    É a cobertura do intervalo da viga pelas barras mais longas: são elas que
    seguram os cantos do estribo de ponta a ponta. As barras internas do
    escalonamento não entram, porque a continuidade já está garantida pelas
    barras da cadeia -- alongá-las seria desperdício.
    """
    ordenadas = sorted(grupo, key=lambda p: (p.x_ini, -p.x_fim))
    cadeia = [ordenadas[0]]
    while cadeia[-1].x_fim < x_fim - 1e-6:
        atual = cadeia[-1]
        alcancam = [p for p in ordenadas
                    if p.x_ini <= atual.x_fim + 1e-6 and p.x_fim > atual.x_fim]
        if alcancam:
            proxima = max(alcancam, key=lambda p: p.x_fim)
        else:                                # há um vazio: pega a próxima
            adiante = [p for p in ordenadas if p.x_ini > atual.x_fim]
            if not adiante:
                break
            proxima = min(adiante, key=lambda p: (p.x_ini, -p.x_fim))
        if proxima is atual or proxima.x_fim <= atual.x_fim:
            break
        cadeia.append(proxima)
    return cadeia


def _alongar(p: det.Posicao, direita: bool, quanto: float,
             limite: float | None = None) -> None:
    """Estende a barra e atualiza o comprimento; nunca a encurta.

    A trava da junta é limite duro: prolongar a barra além dela a colocaria
    fora da seção do tramo vizinho, e é exatamente isso que o gancho da junta
    existe para evitar. Emenda que precise desse trecho tem de ser resolvida de
    outra forma, não avançando sobre o degrau.
    """
    if quanto <= 1e-9:
        return
    if direita:
        p.x_fim += quanto
        if p.trava_fim is not None:
            p.x_fim = min(p.x_fim, p.trava_fim)
    else:
        p.x_ini -= quanto
        if limite is not None:
            p.x_ini = max(p.x_ini, limite)
        if p.trava_ini is not None:
            p.x_ini = max(p.x_ini, p.trava_ini)
    p.comprimento = ((p.x_fim - p.x_ini) * 100.0
                     + p.dobra_ini + p.dobra_fim)


def _registrar_emenda(A: det.Posicao, B: det.Posicao, l0t: float) -> None:
    """Anota o trecho de sobreposição, para o desenho poder cotá-lo."""
    inicio = max((B.x_ini - A.x_ini) * 100.0, 0.0)
    A.emendas_vizinhas.append((inicio, l0t * 100.0, B.numero))


def _fracoes_perimetro(secao: Secao, rt: to.ResultadoTorcao
                       ) -> tuple[float, float]:
    """Fração de Asl que cabe a uma face horizontal e às duas laterais.

    O item 17.5.1.6 distribui Asl ao longo do perímetro ue da seção vazada
    equivalente, então cada lado leva a fração do seu comprimento.
    """
    c2 = rt.geometria.c2
    lado_h = max(secao.bw - 2.0 * c2, 1e-6)        # faces inferior e superior
    lado_v = max(secao.h - 2.0 * c2, 1e-6)         # faces laterais
    ue = 2.0 * (lado_h + lado_v)
    return lado_h / ue, 2.0 * lado_v / ue


def _somar_asl_longitudinal(viga: Viga, regioes: list[Regiao], x: np.ndarray,
                            asl_face: np.ndarray, asl_lat: np.ndarray,
                            As_inf: np.ndarray, As_sup: np.ndarray,
                            avisos: list[str],
                            phi_t_regiao: dict[str, float] | None = None,
                            phi_flexao: dict[str, float] | None = None
                            ) -> tuple[np.ndarray, np.ndarray, list[tuple]]:
    """Soma ao aço a armadura longitudinal de torção (17.5.1.6).

    Recebe a parcela de Asl de cada face **já avaliada na grade da viga**, com
    zero onde não há torção -- é isso que impede a armadura de torção de um
    tramo aparecer nos outros. A parcela das faces superior e inferior soma à
    armadura de flexão daquelas faces (é a mesma barra resistindo aos dois
    efeitos) e a das faces laterais vira barra lateral, na altura da alma.

    Devolve os diagramas de armadura necessária já acrescidos e a lista de
    (tramo, Asl_lateral em cm²) para o detalhamento montar as barras laterais.
    """
    cfg = viga.config
    As_inf = np.nan_to_num(As_inf) + asl_face
    As_sup = np.nan_to_num(As_sup) + asl_face

    # redimensiona as barras das regiões com o acréscimo da torção
    cob = _cobrimento(viga)
    for r in regioes:
        if r.construtiva:
            continue
        m = (x >= r.x_ini - 1e-9) & (x <= r.x_fim + 1e-9)
        if not m.any():
            continue
        r.As_torcao = float(np.max(asl_face[m]))
        if r.As_torcao <= 1e-6:
            continue
        # o acréscimo troca as barras, as barras trocam o d, e o As de flexão
        # tem de ser refeito com esse d: a memória mostrava a flexão com o d
        # do arranjo antigo (46,1 cm) ao lado do arranjo novo (45,9 cm)
        phi_t_r = max(cfg.phi_estribo, (phi_t_regiao or {}).get(r.nome, 0.0))
        d_linha = cob + phi_t_r / 10.0 + 1.0
        flexao = r.flexao
        for _ in range(8):
            alvo = flexao.As_adotado + r.As_torcao
            arranjo = det.escolher_barras(
                r.secao, alvo, cob, phi_t_r, cfg.d_agregado,
                cfg.phi_min_longitudinal, cfg.phi_max_longitudinal,
                _phi_imposta(viga, r.nome)
                or (phi_flexao or {}).get(r.nome, 0.0), n_ramos=cfg.n_ramos)
            flexao = fl.dimensionar(r.secao, viga.concreto, viga.aco, r.M,
                                    d_linha, r.secao.h - arranjo.d,
                                    delta=cfg.redistribuicao)
            if flexao.As_adotado + r.As_torcao <= arranjo.As_ef + 1e-9:
                break
        alvo = flexao.As_adotado + r.As_torcao
        flexao.memoria["barras por camada (18.3.2.2)"] = arranjo.n_por_camada
        flexao.memoria["camadas adotadas"] = " + ".join(map(str,
                                                            arranjo.camadas))
        flexao.memoria["ah mínimo (cm)"] = arranjo.ah
        flexao.memoria["av mínimo (cm)"] = arranjo.av
        r.flexao, r.arranjo = flexao, arranjo
        r.d = r.arranjo.d
        r.avisos.append(av.construtivo(
            f"Somados {r.As_torcao:.2f} cm² da armadura longitudinal de "
            f"torção à armadura de flexão desta face (17.5.1.6): "
            f"{r.flexao.As_adotado:.2f} + {r.As_torcao:.2f} = {alvo:.2f} cm²."))

    laterais: list[tuple[int, float]] = []
    for i in range(len(viga.tramos)):
        a, b = viga.x_apoios[i], viga.x_apoios[i + 1]
        m = (x >= a - 1e-9) & (x <= b + 1e-9)
        if not m.any():
            continue
        valor = float(np.max(asl_lat[m]))
        if valor > 1e-6:      # tramo sem torçor não recebe barra lateral
            laterais.append((i, valor))
    if laterais:
        avisos.append(av.construtivo(
            "Armadura longitudinal de torção distribuída no perímetro "
            "(17.5.1.6): a parcela das faces superior e inferior foi somada à "
            "flexão e a das faces laterais saiu como barras laterais."))
    return As_inf, As_sup, laterais


def _verificar_apoios_extremos(viga: Viga, regioes: list[Regiao],
                               cortantes: list[ci.ResultadoCortante],
                               avisos: list[str],
                               apoios_extremos: list | None = None,
                               grampos_ancoragem: list | None = None
                               ) -> None:
    """Confere se a armadura positiva ancora nos apoios de extremidade.

    O item 18.3.2.4.1 exige ancorar a força Rsd = (aℓ/d).Vsd na região do
    apoio; quando o comprimento reto disponível não basta, é o gancho que
    resolve -- e é isso que o detalhamento desenha.
    """
    conc, aco, cfg = viga.concreto, viga.aco, viga.config
    cob = viga.ambiente.cobrimento_nominal
    if apoios_extremos is None:
        apoios_extremos = []
    if grampos_ancoragem is None:
        grampos_ancoragem = []
    # lista de pares, e não dicionário: em viga de um só tramo as duas
    # entradas têm a mesma chave (o tramo 0), e o dicionário descartava um dos
    # apoios extremos -- só o da direita era verificado
    extremos = [(0, 0),
                (len(viga.tramos) - 1, len(viga.apoios) - 1)]
    for i_tramo, k_apoio in dict.fromkeys(extremos):
        ap = viga.apoios[k_apoio]
        if ap.tipo == "livre":
            continue
        reg = next((r for r in regioes if r.tipo == "vao"
                    and r.indice == i_tramo and not r.construtiva), None)
        # `reg.ancoragem` é preenchida no laço das barras, que agora roda
        # **depois** desta verificação -- ela precisa vir antes porque é dela
        # que sai o grampo, e é o grampo que define onde a barra pode terminar.
        # Tudo o que se usa aqui (d, arranjo, seção) já existe na região
        if reg is None:
            continue
        x_apoio = viga.x_apoios[k_apoio]
        proximos = [c for c in cortantes
                    if abs(c.x - x_apoio) <= max(reg.d / 100.0, 0.3)]
        if not proximos:
            continue
        pior = max(proximos, key=lambda c: c.Vsd)
        a_l, _ = anc.decalagem(reg.d, pior.Vsd, pior.Vc,
                              cfg.modelo_cisalhamento, cfg.theta,
                              cfg.alpha_estribo)
        # o gancho de extremidade é dobrado no plano vertical: o cobrimento
        # no plano normal a ele é o lateral, da face da viga ao eixo da barra
        cob_lateral = cob + cfg.phi_estribo / 10.0
        verif = anc.apoio_extremo(conc, aco, pior.Vsd, a_l, reg.d,
                                  reg.arranjo.phi, reg.arranjo.As_ef,
                                  ap.largura, cob,
                                  gancho=cfg.reduzir_ancoragem_com_gancho,
                                  cobrimento_normal=cob_lateral)
        verif.apoio = k_apoio + 1
        apoios_extremos.append(verif)
        # os avisos de `apoio_extremo` -- a recusa do α = 0,7 por cobrimento
        # insuficiente (9.4.2.5) e o piso do 18.3.2.4.1 que governou -- eram
        # gravados no resultado e não eram lidos por ninguém: o campo existia,
        # a aba de avisos não os mostrava e a memória não os citava
        avisos += [av.prefixar(a, f"Apoio {k_apoio + 1}: ")
                   for a in verif.avisos]

        # escolher "Sem gancho" onde a ancoragem reta não cabe é retirar um
        # recurso do apoio, e a escolha tem de ser dita: sem isso o usuário
        # desligava o gancho e os grampos resolviam em silêncio
        tipo = _tipo_gancho(viga, reg.nome)
        if not verif.ok and tipo == gk.SEM_GANCHO:
            altura = gk.altura(aco.raio_dobramento_eixo(reg.arranjo.phi),
                               reg.arranjo.phi, gk.PADRAO)
            avisos.append(av.erro(
                f"Apoio {k_apoio + 1}: “{reg.nome}” está sem gancho e a "
                f"ancoragem reta não cabe (lb,nec = {verif.lb_nec:.0f} cm "
                f"contra {verif.l_disponivel:.0f} cm da face do apoio ao fim "
                f"da barra). Sem o gancho a barra perde o recurso do item "
                f"9.4.2.5 e o fecho da ponta; um gancho a 90° em "
                f"Ø{reg.arranjo.phi:g} pediria {altura:.0f} cm de altura, e o "
                f"semicircular menos. Escolha um tipo de gancho, alargue o "
                f"apoio ou reduza a bitola."))
        if verif.ok:
            continue
        # o apoio não dá comprimento: antes de reprovar, tenta o grampo, que é
        # a saída construtiva usual -- uma barra em U que abraça a armadura e
        # leva para dentro da viga a parcela que o trecho reto não ancorou
        g = None
        if cfg.usar_grampos:
            g = gr.dimensionar(conc, aco, reg.arranjo.phi,
                               verif.As_necessaria, verif.l_disponivel,
                               verif.lb_nec, "inferior", reg.secao.h,
                               cfg.phi_grampo)
            if not g.ok:
                alternativa = gr.menor_bitola_que_cabe(
                    conc, aco, reg.arranjo.phi, verif.As_necessaria,
                    verif.l_disponivel, verif.lb_nec, "inferior",
                    reg.secao.h)
                if alternativa is not None:
                    avisos.append(av.construtivo(
                        f"Apoio {k_apoio + 1}: o grampo Ø{cfg.phi_grampo:g} "
                        f"dos critérios passa do teto de "
                        f"Ø{g.phi_max:.1f} mm; adotado Ø{alternativa.phi:g}, "
                        f"a bitola comercial mais fina que ainda ancora."))
                    g = alternativa
            g.apoio = k_apoio + 1
            grampos_ancoragem.append(g)
            avisos += [av.prefixar(a, f"Apoio {k_apoio + 1}: ")
                       for a in g.avisos]
        if g is not None and g.ok and g.n > 0:
            avisos.append(av.construtivo(
                f"Apoio {k_apoio + 1}: a ancoragem reta não cabe "
                f"(lb,nec = {verif.lb_nec:.0f} cm contra "
                f"{verif.l_disponivel:.0f} cm disponíveis) e foi completada "
                f"por grampos (18.3.2.4.1)."))
        else:
            avisos.append(av.erro(
                f"Apoio {k_apoio + 1}: a ancoragem da armadura positiva não "
                f"cabe nem com gancho (lb,nec = {verif.lb_nec:.0f} cm contra "
                f"{verif.l_disponivel:.0f} cm disponíveis)"
                + (" e o grampo também não resolve. " if cfg.usar_grampos
                   else ", e o critério de grampos está desligado. ")
                + "Alargue o pilar ou reduza a bitola (18.3.2.4.1)."))


def _ganchos_nas_extremidades(viga: Viga,
                              posicoes: list[det.Posicao]) -> None:
    """Fecha com gancho toda barra que termina numa extremidade da viga.

    Vale também para as barras de montagem: elas não recebem esforço, mas
    precisam do gancho para ficarem presas e para o estribo não abrir na ponta.
    Nesses casos o gancho é construtivo (8 phi, mínimo 10 cm) -- quem depende de
    ancoragem já teve a perna dimensionada em :func:`_gancho_apoio`.
    """
    cob = _cobrimento(viga)
    xi, xf = _limites_uteis(viga, _recuos_nas_posicoes(viga, posicoes))
    for p in posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        secao = al.secao_da(viga, p)
        # o tipo é o da própria barra, e não o geral: a região que escolheu
        # "Sem gancho" não pode ganhar um gancho construtivo por outra via
        gancho = _gancho_livre(secao, cob, p.phi, viga.aco,
                               p.tipo_gancho or _tipo_gancho(viga))
        mudou = False
        if abs(p.x_ini - xi) < 1e-6 and p.dobra_ini <= 0.0:
            p.dobra_ini = gancho
            mudou = True
        if abs(p.x_fim - xf) < 1e-6 and p.dobra_fim <= 0.0:
            p.dobra_fim = gancho
            mudou = True
        if mudou:
            p.comprimento = ((p.x_fim - p.x_ini) * 100.0
                             + p.dobra_ini + p.dobra_fim)


def _comprimentos_com_ganchos(viga: Viga,
                              posicoes: list[det.Posicao]) -> None:
    """Refaz o comprimento das barras contando o gancho pelo desenvolvido.

    A extensão vertical da dobra é a **dimensão externa**, que é o que se cota
    no desenho. O aço consumido é outro número: o arco ``r.θ`` mais a ponta
    reta. Nos ganchos a 90° os dois quase coincidem, e por isso o erro passava
    despercebido; no semicircular a altura é 2r e o desenvolvido é
    ``π.r + 2 Ø`` -- quase o dobro. Como o comprimento alimenta a massa, o
    quantitativo saía curto.

    Roda depois dos ganchos estarem todos postos e antes do reparte em peças
    comerciais, que se apoia no comprimento.
    """
    tipo_geral = _tipo_gancho(viga)
    aco = viga.aco
    for p in posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        # quem não nasceu de uma região (porta-estribo, companheira de junta)
        # herda o critério geral
        if not p.tipo_gancho:
            p.tipo_gancho = tipo_geral
        if p.dobra_ini <= 1e-9 and p.dobra_fim <= 1e-9:
            continue
        if p.tipo_gancho == gk.SEM_GANCHO:
            continue
        raio = p.raio_da_dobra(aco)
        altura = gk.altura(raio, p.phi, p.tipo_gancho)
        extra = 0.0
        for dobra in (p.dobra_ini, p.dobra_fim):
            if dobra <= 1e-9:
                continue
            if dobra < altura - 1e-6:
                # perna truncada pela seção: só o que existe conta, e a
                # conferência do 9.4.2.3 já reprovou
                extra += dobra
                continue
            # a ponta reta é a que a perna adotada exige: mesma regra que o
            # desenho usa, para os dois não divergirem
            ponta = gk.ponta_para_altura(raio, p.phi, p.tipo_gancho, dobra)
            extra += gk.comprimento_desenvolvido(raio, p.phi, p.tipo_gancho,
                                                 ponta)
        p.comprimento = (p.x_fim - p.x_ini) * 100.0 + extra


def conferir_ganchos(viga: Viga, posicoes: list[det.Posicao]) -> list[str]:
    """Confere as pernas de gancho contra o item 9.4.2.3 e contra a seção.

    O gancho a 90° exige ponta reta de **8 Ø** (9.4.2.3-c), e a perna também
    tem de caber na altura útil da seção. As funções que dimensionam a perna
    aplicavam o teto geométrico por ``min(h - 2c, ...)`` **por fora** do piso de
    8 Ø, e assim o teto atropelava o piso sem dizer nada: uma Ø32 numa viga de
    30 cm com cobrimento de 5 cm saía com perna de 20 cm, contra os 25,6 cm
    exigidos, e o desenho mostrava um gancho que não existe.

    A conferência roda no detalhamento pronto, como a da continuidade: não
    depende de qual das funções dimensionou a perna, e por isso nenhuma delas
    pode escapar dela.
    """
    cob = _cobrimento(viga)
    problemas: list[str] = []
    vistos: set[tuple] = set()
    for p in posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        pernas = [d for d in (p.dobra_ini, p.dobra_fim) if d > 1e-9]
        if not pernas:
            continue
        secao = al.secao_da(viga, p)
        tipo = p.tipo_gancho or _tipo_gancho(viga)
        if tipo == gk.SEM_GANCHO:
            continue
        raio = viga.aco.raio_dobramento_eixo(p.phi)
        exigida = gk.altura(raio, p.phi, tipo)
        ponta = gk.ponta_reta(p.phi, tipo)
        disponivel = secao.h - 2.0 * cob
        pino = viga.aco.diametro_dobramento(p.phi)
        chave = (round(p.phi, 3), round(secao.h, 3), round(min(pernas), 3))
        if min(pernas) >= exigida - 1e-6 or chave in vistos:
            continue
        vistos.add(chave)
        if exigida > disponivel + 1e-6:
            problemas.append(
                f"N{p.numero}: o gancho de Ø{p.phi:g} não cabe na seção de "
                f"{secao.h:g} cm. O gancho “{tipo}” precisa de "
                f"{exigida:.1f} cm — dobra de {gk.angulo(tipo):g}° com raio de "
                f"{raio:.1f} cm no eixo (pino D = {pino:.1f} cm, Tabela 9.1) "
                f"mais a ponta reta de {ponta:.1f} cm (9.4.2.3) — e a seção só "
                f"oferece h - 2c = {disponivel:.1f} cm. Reduza a bitola, "
                f"aumente a altura, ou troque o tipo de gancho: o "
                f"semicircular é o mais baixo dos três.")
        else:
            problemas.append(
                f"N{p.numero}: perna de gancho de {min(pernas):.1f} cm em "
                f"Ø{p.phi:g}, menor que os {exigida:.1f} cm que o gancho "
                f"“{tipo}” exige — dobra de {gk.angulo(tipo):g}° com raio "
                f"{raio:.1f} cm no eixo mais a ponta reta de {ponta:.1f} cm "
                f"(9.4.2.3).")
    # 9.4.2.1-c: acima de Ø32 a norma não recomenda gancho
    grossas = sorted({p.phi for p in posicoes
                      if p.tipo in ("longitudinal", "porta") and p.phi > 32.0
                      and (p.dobra_ini > 1e-9 or p.dobra_fim > 1e-9)})
    for phi in grossas:
        problemas.append(
            f"Gancho em barra Ø{phi:g}: o item 9.4.2.1-c não recomenda gancho "
            f"para Ø > 32 mm. Ancore por prolongamento retilíneo, por barras "
            f"transversais soldadas (9.4.2.2) ou reduza a bitola.")
    return problemas


def conferir_continuidade(viga: Viga, posicoes: list[det.Posicao],
                          aco=None) -> list[str]:
    """Confere, no detalhamento pronto, a continuidade de cada face.

    Duas exigências que o desenho tem de cumprir e que nenhuma fórmula garante
    sozinha: cada face precisa de barra nos seus dois cantos em toda a extensão
    da viga, e cada junta entre barras consecutivas precisa da sobreposição de
    l0t. A conferência roda ao fim do dimensionamento; qualquer falha vira
    aviso, em vez de sair calada no desenho.
    """
    aco = aco or viga.aco
    xi, xf = _limites_uteis(viga, _recuos_nas_posicoes(viga, posicoes))
    grade = np.linspace(xi, xf, 2001)
    problemas: list[str] = []

    for face in ("inferior", "superior"):
        grupo = [p for p in posicoes if p.face == face
                 and p.tipo in ("longitudinal", "porta")]
        contagem = np.zeros(grade.size, dtype=int)
        for p in grupo:
            dentro = (grade >= p.x_ini - 1e-9) & (grade <= p.x_fim + 1e-9)
            contagem += dentro * p.n
        if (contagem < det.CANTOS_POR_FACE).any():
            i = int(np.argmin(contagem))
            problemas.append(
                f"Face {face}: em x = {grade[i]:.2f} m há apenas "
                f"{contagem[i]} barra(s), menos que os "
                f"{det.CANTOS_POR_FACE} cantos do estribo.")
        for p in grupo:
            # quem escolheu "Sem gancho" já foi avisado do que isso custa, no
            # apoio onde custa; repetir aqui só multiplicaria o mesmo erro
            if p.tipo_gancho == gk.SEM_GANCHO:
                continue
            if abs(p.x_ini - xi) < 1e-6 and p.dobra_ini <= 0.0:
                problemas.append(
                    f"N{p.numero} chega à extremidade esquerda sem gancho.")
            if abs(p.x_fim - xf) < 1e-6 and p.dobra_fim <= 0.0:
                problemas.append(
                    f"N{p.numero} chega à extremidade direita sem gancho.")
        if len(grupo) < 2:
            continue
        cadeia = _cadeia_de_cobertura(grupo, xf)
        for A, B in zip(cadeia, cadeia[1:]):
            if travadas_na_junta(A, B):
                continue                     # níveis diferentes: não é emenda
            phi = max(A.phi, B.phi)
            h = viga.secao_em((A.x_fim + B.x_ini) / 2.0).h
            l0t = _traspasse_necessario(
                viga, phi, face, h, A.comprimida and B.comprimida) / 100.0
            if A.x_fim - B.x_ini < l0t - 1e-6:
                problemas.append(
                    f"Face {face}: N{A.numero} e N{B.numero} se sobrepõem "
                    f"{(A.x_fim - B.x_ini) * 100:.0f} cm, menos que o "
                    f"traspasse de {l0t * 100:.0f} cm (9.5.2.2.1).")
    return problemas


def _traspasse_necessario(viga: Viga, phi: float, face: str, h: float,
                          comprimida: bool = False,
                          altura_barra: float | None = None) -> float:
    """Traspasse exigido por uma emenda, cm -- regra única.

    ``l0c`` do item 9.5.2.3 quando as duas barras estão comprimidas, ``l0t`` do
    9.5.2.2.1 no resto, com a situação de aderência da altura da barra (9.3.1)
    quando ela é conhecida. Esta função existe porque a regra estava repetida
    em três lugares -- quem monta a emenda, quem reparte a barra longa e quem
    confere a continuidade -- e a primeira divergência entre eles fez o
    conferidor reprovar um detalhamento correto.
    """
    conc, aco = viga.concreto, viga.aco
    if comprimida:
        return anc.traspasse_compressao(conc, aco, phi, 1.0, 1.0, face, h)
    return anc.traspasse(conc, aco, phi, 1.0, 1.0, face, h,
                         altura_barra=altura_barra)


def _recuos_do_grampo(viga: Viga, grampos: list) -> tuple[float, float]:
    """Quanto as barras recuam em cada extremidade por causa do grampo, m.

    O grampo é o elemento **mais externo** da ponta: ele abraça as pernas das
    barras por fora, como um estribo horizontal, e é nele que o cobrimento é
    medido. A barra, portanto, começa uma bitola de grampo adiante do que
    começaria sem ele. Sem esse recuo a barra e o grampo ocupariam o mesmo
    espaço, e o cobrimento sairia menor que o nominal.

    A decisão de haver grampo é monótona: se a ancoragem reta não cabe sem o
    recuo, muito menos cabe com ele. Por isso basta uma passada -- decidir com
    o comprimento cheio e depois recuar --, sem iterar.
    """
    n = len(viga.apoios)
    recuo_ini = recuo_fim = 0.0
    for g in grampos:
        if g.n <= 0:
            continue
        if g.apoio == 1:
            recuo_ini = max(recuo_ini, g.phi / 1000.0)
        if g.apoio == n:
            recuo_fim = max(recuo_fim, g.phi / 1000.0)
    return recuo_ini, recuo_fim


def _recuos_nas_posicoes(viga: Viga,
                         posicoes: list[det.Posicao]) -> tuple[float, float]:
    """Recuo imposto pelo grampo em cada extremidade, m, lido do detalhamento.

    Serve às funções que recebem só as posições -- a conferência de
    continuidade, os ganchos das pontas -- e que não têm acesso à lista de
    grampos. O grampo de ancoragem está no detalhamento, e a bitola dele é o
    recuo.
    """
    xi0, xf0 = viga.x_inicio_fisico, viga.x_fim_fisico
    recuo_ini = recuo_fim = 0.0
    for p in posicoes:
        if p.tipo != "grampo" or p.papel != "ancoragem":
            continue
        if abs(p.x_ini - xi0) < 0.20:
            recuo_ini = max(recuo_ini, p.phi / 1000.0)
        if abs(p.x_fim - xf0) < 0.20:
            recuo_fim = max(recuo_fim, p.phi / 1000.0)
    return recuo_ini, recuo_fim


def _limites_uteis(viga: Viga,
                   recuos: tuple[float, float] = (0.0, 0.0)
                   ) -> tuple[float, float]:
    """Extremos em que uma barra pode terminar, m.

    As faces menos o cobrimento e, onde há grampo, menos a bitola dele: o
    grampo fica por fora e o cobrimento é medido nele.
    """
    cob = _cobrimento(viga) / 100.0
    return (viga.x_inicio_fisico + cob + recuos[0],
            viga.x_fim_fisico - cob - recuos[1])


def regioes_com_gancho(res) -> set[str]:
    """Nomes das regiões cujas barras chegam a uma extremidade da viga.

    Só essas recebem gancho -- é nas extremidades que a barra termina sem
    concreto adiante. Existe para a interface **não** oferecer a escolha do
    tipo de gancho onde ela não tem efeito: oferecê-la em toda região convida
    o usuário a aplicar um gancho que não vai a lugar nenhum.

    O critério é a geometria da barra, e não o gancho que ela tem hoje: assim a
    escolha continua disponível numa região posta em "Sem gancho".
    """
    viga = res.viga
    xi, xf = _limites_uteis(viga, _recuos_do_grampo(viga, res.grampos))
    nomes: set[str] = set()
    for p in res.posicoes:
        if p.tipo not in ("longitudinal", "porta"):
            continue
        if p.x_ini > xi + 1e-6 and p.x_fim < xf - 1e-6:
            continue
        nomes.add(p.descricao.split(" - ")[0].strip())
    return nomes


def _vao_do_grampo(viga: Viga, i_trecho: int) -> float:
    """Distância entre as pernas de um grampo, cm.

    O grampo é um U no plano horizontal, abraçando as barras longitudinais
    dentro da gaiola: as pernas correm ao longo da viga e a dobra fecha na
    largura, por dentro do estribo.
    """
    secao = viga.trechos[min(i_trecho, len(viga.trechos) - 1)].secao
    cob = _cobrimento(viga)
    return max(secao.bw - 2.0 * cob - viga.config.phi_estribo / 10.0, 2.0)


#: seção transversal mínima da armadura de ligação mesa-alma, cm²/m (18.3.7)
LIGACAO_MESA_ALMA_MINIMA = 1.5


def _area_do_estribo_de_mesa(posicoes: list[det.Posicao], trecho) -> float:
    """Armadura que o laço da mesa já põe atravessando o plano de ligação,
    cm²/m -- a menor das faixas que cobrem o trecho.

    Os dois ramos verticais do laço cruzam o plano de ligação, então cada
    estribo da mesa contribui com **duas** seções de barra. Toma-se a menor
    das faixas porque o mínimo do item 18.3.7 é local: um trecho com o
    espaçamento aberto num pedaço não é salvo pelo pedaço mais fechado.
    """
    areas = [2.0 * area_barra(p.phi) / p.s * 100.0
             for p in posicoes
             if p.tipo == "estribo" and p.papel == "mesa" and p.s > 0
             and p.x_ini < trecho.x_fim - 1e-9
             and trecho.x_ini < p.x_fim - 1e-9]
    return min(areas) if areas else 0.0


def _armar_ligacao_mesa(viga: Viga, posicoes: list[det.Posicao], numero: int,
                        avisos: list[str]) -> tuple[list[det.Posicao], int]:
    """Armadura de ligação entre mesa e alma -- item 18.3.7.

    "Os planos de ligação entre mesas e almas [...] devem ser verificados com
    relação aos efeitos tangenciais decorrentes das variações de tensões
    normais ao longo do comprimento da viga [...] A seção transversal mínima
    dessa armadura, estendendo-se por toda a largura útil e adequadamente
    ancorada, deve ser de 1,5 cm² por metro."

    O programa aplica o **mínimo** do item, que é o que ele pode fazer sem
    conhecer a laje: a norma admite contar "as armaduras de flexão da laje,
    existentes no plano de ligação", e o programa não conhece essa laje. Por
    isso a peça sai declarada como o mínimo a somar ao que a laje já leva, e o
    aviso o diz -- quem tem a armadura da laje desconta.

    A verificação do **efeito tangencial** em si não é feita: ela depende da
    variação de Msd ao longo do vão na mesa colaborante, e fica registrada como
    limitação.
    """
    novas: list[det.Posicao] = []
    for tr in viga.trechos:
        if tr.secao.tipo == "retangular" or tr.secao.bf <= tr.secao.bw + 1e-9:
            continue
        L = tr.x_fim - tr.x_ini
        if L <= 1e-6:
            continue
        # o laço da mesa já atravessa o plano de ligação com os seus DOIS
        # ramos verticais; onde ele sozinho passa dos 1,5 cm²/m, não há o que
        # complementar -- acrescentar a barra reta aqui contaria o mesmo aço
        # duas vezes
        if _area_do_estribo_de_mesa(posicoes, tr) >= LIGACAO_MESA_ALMA_MINIMA:
            continue
        # barra reta atravessando o plano de ligação, uma por metro de viga em
        # cada lado da alma que tem mesa
        phi = 6.3
        area = area_barra(phi)
        s_cm = min(20.0, area / LIGACAO_MESA_ALMA_MINIMA * 100.0)
        n = max(2, int(math.ceil(L * 100.0 / s_cm)) + 1)
        largura_util = (tr.secao.bf - tr.secao.bw) / 2.0 + tr.secao.bw
        novas.append(det.Posicao(
            numero=numero, tipo="ligacao", n=n, phi=phi, face="alma",
            x_ini=tr.x_ini, x_fim=tr.x_fim,
            comprimento=largura_util,
            s=round(s_cm, 1), trecho=tr.k, tramo=tr.tramo,
            n_ramos_efetivo=1,
            faixas=[(tr.x_ini, tr.x_fim, round(s_cm, 1), n)],
            descricao=f"Ligação mesa-alma do trecho {tr.k + 1} — mínimo de "
                      f"{LIGACAO_MESA_ALMA_MINIMA:g} cm²/m do item 18.3.7"))
        numero += 1
    if novas:
        avisos.append(av.construtivo(
            f"Seção com mesa: acrescentada a armadura de ligação mesa-alma do "
            f"item 18.3.7, {LIGACAO_MESA_ALMA_MINIMA:g} cm²/m atravessando o "
            f"plano de ligação ({len(novas)} posição(ões)). O item admite "
            f"contar a armadura de flexão da laje existente nesse plano, que o "
            f"programa não conhece: se a laje já leva parte dela, desconte. A "
            f"verificação do efeito tangencial em si — que depende da variação "
            f"de Msd ao longo da mesa — não é feita."))
        posicoes.extend(novas)
    return novas, numero


def _porta_estribos(viga: Viga, posicoes: list[det.Posicao], numero: int,
                    phi_estribo: float = 0.0,
                    regioes: list[Regiao] | None = None,
                    demanda: tuple | None = None
                    ) -> tuple[list[det.Posicao], int]:
    """Completa os cantos do estribo onde a face não tem armadura.

    Todo estribo precisa de barra em cada um dos seus quatro cantos, para
    manter a forma e servir de apoio à amarração. Onde o escalonamento deixa
    uma face com menos de duas barras, entram porta-estribos -- um por canto
    descoberto --, prolongados de um traspasse além do trecho descoberto, para
    emendar com a armadura calculada.

    A bitola é a de porta-estribo (Ø6,3 mm), elevada à do estribo quando este
    for mais grosso: o item 18.3.3.2 exige que a barra de amarração do canto
    não seja mais fina que o próprio estribo.

    A varredura é por **(face, trecho)**, e não por face. Uma barra do trecho
    vizinho que atravessa a junta passa por cima daquele x sem estar no nível
    daquela face, e contá-la como cobertura deixava o canto do estribo vazio:
    numa junta 60 -> 85 alinhada pelo topo, o fundo do trecho de 85 ficava sem
    barra nenhuma nos 32 cm entre o degrau e o início da armadura de vão.

    ``demanda`` -- ``(x, As_inf, As_sup)`` -- é a armadura necessária de cada
    face. Onde a face não tem barra calculada mas tem demanda, que é o caso da
    parcela de torção (17.5.1.6) numa face sem momento, o porta-estribo deixa
    de ser só de canto e é dimensionado por ela: na V05 do pacote de
    conferência a face superior pedia 0,66 cm² de torção e recebia 2 Ø6,3 =
    0,62 cm², por um porta-estribo que não lia o diagrama.
    """
    conc, aco = viga.concreto, viga.aco
    regioes = regioes or []
    por_face: dict[str, int] = {}
    phi_porta = max(det.PHI_PORTA_ESTRIBO, phi_estribo)
    xi_viga, xf_viga = _limites_uteis(viga)
    novas: list[det.Posicao] = []

    for face in ("inferior", "superior"):
        for tr in viga.trechos:
            # o trecho responde pelo seu próprio pedaço de viga, estendido até
            # a extremidade física nos dois trechos das pontas
            xi = xi_viga if tr.k == 0 else tr.x_ini
            xf = xf_viga if tr.k == len(viga.trechos) - 1 else tr.x_fim
            if xf - xi < 1e-9:
                continue
            grade = np.linspace(xi, xf, 1501)
            contagem = np.zeros(grade.size, dtype=int)
            area = np.zeros(grade.size)
            for p in posicoes:
                if p.face != face or p.tipo not in ("longitudinal", "porta"):
                    continue
                if not al.no_nivel_da_face(viga, p, tr.k, face):
                    continue
                dentro = ((grade >= p.x_ini - 1e-9)
                          & (grade <= p.x_fim + 1e-9))
                contagem += dentro * p.n
                area += dentro * p.n * area_barra(p.phi)
            faltam = np.maximum(det.CANTOS_POR_FACE - contagem, 0)
            if not faltam.any():
                continue

            l0t = anc.traspasse(conc, aco, phi_porta, 1.0, 1.0,
                                face, tr.secao.h) / 100.0
            for n_falta, a, b in _trechos_iguais(grade, faltam):
                # trechos de uma ou duas células são ruído da discretização; o
                # descarte por comprimento curto vale para a barra já
                # prolongada, senão um vazio real de 20 cm dentro do apoio
                # passaria batido
                if n_falta <= 0 or (b - a) < 3.0 * (grade[1] - grade[0]):
                    continue
                # a demanda que as barras calculadas presentes não cobrem
                falta_As = 0.0
                if demanda is not None:
                    xg, As_i, As_s = demanda
                    As_d = np.nan_to_num(As_s if face == "superior" else As_i)
                    m = (xg >= a - 1e-9) & (xg <= b + 1e-9)
                    if m.any():
                        falta_As = float(np.max(
                            As_d[m] - np.interp(xg[m], grade, area)))
                phi_p, n_p = phi_porta, int(n_falta)
                if falta_As > 1e-6:
                    teto = max(viga.config.phi_max_longitudinal, phi_porta)
                    candidatas = [f for f in BITOLAS_BARRAS
                                  if phi_porta - 1e-9 <= f <= teto + 1e-9]
                    phi_p = next((f for f in candidatas
                                  if n_p * area_barra(f) >= falta_As - 1e-9),
                                 candidatas[-1])
                    n_p = max(n_p, math.ceil(falta_As / area_barra(phi_p)
                                             - 1e-9))
                    l0t = anc.traspasse(conc, aco, phi_p, 1.0, 1.0,
                                        face, tr.secao.h) / 100.0
                x0 = max(a - l0t, xi)
                x1 = min(b + l0t, xf)
                if (x1 - x0) < 0.20:
                    continue
                # nome próprio, para o porta-estribo ter linha na tabela e
                # escolher o seu gancho. Antes ele herdava o tipo da região que
                # cobria o trecho, e trocar o gancho de um vão mexia em duas
                # armaduras diferentes -- acoplamento que não tem razão de ser
                por_face[face] = por_face.get(face, 0) + 1
                nome_porta = f"Porta-estribos {face} {por_face[face]}"
                descricao = (f"{nome_porta} - completa os cantos do estribo "
                             f"onde não há armadura calculada")
                if falta_As > 1e-6:
                    descricao += (f" e leva a armadura longitudinal de torção "
                                  f"desta face ({falta_As:.2f} cm², 17.5.1.6)")
                novas.append(det.Posicao(
                    numero=numero, tipo="porta", n=n_p,
                    phi=phi_p, face=face, x_ini=x0, x_fim=x1,
                    comprimento=(x1 - x0) * 100.0,
                    camada=1, trecho=tr.k, tramo=tr.tramo,
                    # com demanda, a barra carrega força calculada: não é mais
                    # só de canto, e não pode ser engrossada por conveniência
                    so_canto=falta_As <= 1e-6,
                    As_torcao=max(falta_As, 0.0),
                    tipo_gancho=_tipo_gancho(viga, nome_porta),
                    descricao=descricao))
                numero += 1
    return novas, numero

def _trechos_iguais(x: np.ndarray, valores: np.ndarray
                    ) -> list[tuple[int, float, float]]:
    """Agrupa a grade em trechos contíguos de valor constante."""
    trechos: list[tuple[int, float, float]] = []
    inicio = 0
    for i in range(1, valores.size + 1):
        if i == valores.size or valores[i] != valores[inicio]:
            trechos.append((int(valores[inicio]), float(x[inicio]),
                            float(x[i - 1])))
            inicio = i
    return trechos


def _gancho_apoio(secao: Secao, cob: float, phi_mm: float, lb_nec: float,
                  largura_apoio: float, permitido: bool = True,
                  aco: Aco | None = None, tipo: str = gk.PADRAO,
                  reduzir: bool = False) -> float:
    """Perna vertical do gancho de extremidade, cm.

    Com gancho, o item 9.4.2.5 reduz a ancoragem a 0,7.lb,nec; o trecho reto
    dentro do pilar cobre parte disso e a perna vertical completa o restante.
    Fica limitada a 8 phi por baixo e à altura útil da seção por cima.

    ``permitido`` vem do critério de projeto: desligado, a barra sai reta e a
    ancoragem tem de caber no apoio -- o desenho não pode mostrar um gancho
    que o cálculo não usou.
    """
    if not permitido or tipo == gk.SEM_GANCHO:
        return 0.0
    # a geometria do tipo escolhido dá o piso: dobra mais ponta reta de 2 Ø,
    # 4 Ø ou 8 Ø conforme o item 9.4.2.3
    raio = aco.raio_dobramento_eixo(phi_mm)
    piso = gk.altura(raio, phi_mm, tipo)
    # com a ancoragem dimensionada como reta o gancho não completa comprimento
    # nenhum: ele é reserva de segurança, e a perna é só a do tipo. Só quando o
    # projeto opta pelo α = 0,7 do item 9.4.2.5 é que a perna cresce para
    # cobrir o que o trecho reto do apoio não deu
    falta = 0.0
    if reduzir:
        reto = max(largura_apoio - 2.0 * cob, 0.0)
        falta = max(0.7 * lb_nec - reto, 0.0)
    return min(secao.h - 2.0 * cob, max(piso, falta))


#: piso construtivo da altura do gancho de ponta livre, cm. Não é da norma:
#: é a perna mínima que a prática pede para a barra não ficar solta
PISO_GANCHO_CONSTRUTIVO = 10.0


def _gancho_livre(secao: Secao, cob: float, phi_mm: float,
                  aco: Aco | None = None, tipo: str = gk.PADRAO) -> float:
    """Gancho na ponta livre de balanço: construtivo, pois ali M = 0.

    Construtivo não quer dizer sem geometria: a dobra e a ponta reta do tipo
    escolhido existem do mesmo jeito, e é por isso que o piso é a altura do
    gancho.
    """
    if tipo == gk.SEM_GANCHO:
        return 0.0
    if aco is None:
        return min(secao.h - 2.0 * cob, max(8.0 * phi_mm / 10.0, 10.0))
    # o piso construtivo é de **altura**, e altura de gancho é geometria: o
    # que se alonga para alcançá-lo é a ponta reta. Impor 10 cm à perna deixava
    # o cálculo com 10 e o desenho com a geometria do tipo -- num Ø6,3
    # semicircular, 3,8 cm --, e trocar o tipo não mudava a perna
    raio = aco.raio_dobramento_eixo(phi_mm)
    ponta = gk.ponta_para_altura(raio, phi_mm, tipo, PISO_GANCHO_CONSTRUTIVO)
    return min(secao.h - 2.0 * cob, gk.altura(raio, phi_mm, tipo, ponta))


def _limites_barra_vao(viga: Viga, r: Regiao, anco: anc.Ancoragem,
                       recuos: tuple[float, float] = (0.0, 0.0)
                       ) -> tuple[float, float, float, float]:
    """Extremos e dobras das barras positivas de um vão."""
    cob = viga.ambiente.cobrimento_nominal
    xs = viga.x_apoios
    i = r.indice
    dobra_i = dobra_f = 0.0

    ap_e, ap_d = viga.apoios[i], viga.apoios[i + 1]
    if ap_e.tipo == "livre":
        x_min = xs[i] + cob / 100.0
    elif i == 0:
        x_min = xs[i] - ap_e.largura / 200.0 + cob / 100.0 + recuos[0]
        if 0.7 * anco.lb_nec > ap_e.largura - 2 * cob:
            dobra_i = _gancho_apoio(r.secao, cob, anco.phi, anco.lb_nec,
                                    ap_e.largura,
                                    viga.config.ancoragem_gancho,
                                    viga.aco, _tipo_gancho(viga, r.nome),
                                    viga.config.reduzir_ancoragem_com_gancho)
    else:
        x_min = xs[i] - ap_e.largura / 200.0 - 10.0 * anco.phi / 1000.0
    if ap_d.tipo == "livre":
        x_max = xs[i + 1] - cob / 100.0
    elif i == len(viga.tramos) - 1:
        x_max = xs[i + 1] + ap_d.largura / 200.0 - cob / 100.0 - recuos[1]
        if 0.7 * anco.lb_nec > ap_d.largura - 2 * cob:
            dobra_f = _gancho_apoio(r.secao, cob, anco.phi, anco.lb_nec,
                                    ap_d.largura,
                                    viga.config.ancoragem_gancho,
                                    viga.aco, _tipo_gancho(viga, r.nome),
                                    viga.config.reduzir_ancoragem_com_gancho)
    else:
        x_max = xs[i + 1] + ap_d.largura / 200.0 + 10.0 * anco.phi / 1000.0
    return x_min, x_max, dobra_i, dobra_f


def _limites_barra_apoio(viga: Viga, r: Regiao, anco: anc.Ancoragem,
                         recuos: tuple[float, float] = (0.0, 0.0)
                         ) -> tuple[float, float, float, float]:
    """Extremos e dobras das barras negativas de um apoio.

    A barra ganha dobra vertical em três situações: apoio de extremidade (onde
    ela precisa ancorar dentro do pilar) e ponta livre de balanço, à esquerda
    ou à direita, onde o desenho fecha a barra na face da extremidade.
    """
    cob = viga.ambiente.cobrimento_nominal
    xs = viga.x_apoios
    k = r.indice
    n = len(viga.apoios)
    dobra_i = dobra_f = 0.0
    x_min = r.x_ini
    x_max = r.x_fim

    if k == 0:
        x_min = (xs[0] - viga.apoios[0].largura / 200.0 + cob / 100.0
                 + recuos[0])
        dobra_i = _gancho_apoio(r.secao, cob, anco.phi, anco.lb_nec,
                                viga.apoios[0].largura,
                                viga.config.ancoragem_gancho, viga.aco,
                              _tipo_gancho(viga),
                              viga.config.reduzir_ancoragem_com_gancho)
    elif viga.apoios[k - 1].tipo == "livre":       # balanço à esquerda
        x_min = xs[k - 1] + cob / 100.0
        dobra_i = _gancho_livre(r.secao, cob, anco.phi, viga.aco,
                              _tipo_gancho(viga))

    if k == n - 1:
        x_max = (xs[-1] + viga.apoios[-1].largura / 200.0 - cob / 100.0
                 - recuos[1])
        dobra_f = _gancho_apoio(r.secao, cob, anco.phi, anco.lb_nec,
                                viga.apoios[-1].largura,
                                viga.config.ancoragem_gancho, viga.aco,
                              _tipo_gancho(viga),
                              viga.config.reduzir_ancoragem_com_gancho)
    elif viga.apoios[k + 1].tipo == "livre":       # balanço à direita
        x_max = xs[k + 1] - cob / 100.0
        dobra_f = _gancho_livre(r.secao, cob, anco.phi, viga.aco,
                              _tipo_gancho(viga))
    return x_min, x_max, dobra_i, dobra_f


def _extensao_da_lateral_de_torcao(viga: Viga, i: int) -> tuple[float, float]:
    """Extremos da barra lateral de torção do tramo ``i``, m.

    Ia de eixo a eixo dos apoios: 12,5 cm além da face de um apoio de 25 cm,
    justamente onde o torçor é máximo. Agora vai até a extremidade física
    (menos o cobrimento) nos apoios de extremidade, e atravessa o apoio
    interno até um lb além da face oposta -- onde ela ancora no tramo vizinho
    ou traspassa com a lateral dele.
    """
    cob = _cobrimento(viga)
    xs = viga.x_apoios
    lb = anc.ancorar(viga.concreto, viga.aco,
                     max(viga.config.phi_min_longitudinal,
                         det.PHI_PORTA_ESTRIBO), 1.0, 1.0, "superior",
                     viga.tramos[i].secao.h).lb / 100.0
    if i == 0:
        a = viga.x_inicio_fisico + cob / 100.0
    else:
        a = max(xs[i] - viga.apoios[i].largura / 200.0 - lb,
                viga.x_inicio_fisico + cob / 100.0)
    if i == len(viga.tramos) - 1:
        b = viga.x_fim_fisico - cob / 100.0
    else:
        b = min(xs[i + 1] + viga.apoios[i + 1].largura / 200.0 + lb,
                viga.x_fim_fisico - cob / 100.0)
    return a, b


def _ancorar_torcao_nos_extremos(viga: Viga, posicoes: list[det.Posicao],
                                 avisos: list[str]
                                 ) -> list[anc.AncoragemTorcao]:
    """Ancoragem da armadura longitudinal de torção nos apoios extremos.

    A NBR não tem item próprio para isso: vale o 9.4.1 -- toda barra tem de
    ser ancorada de forma que a sua força passe integralmente ao concreto -- e,
    por analogia, o 18.3.2.4.1, medido a partir da face do apoio. Com torçor
    distribuído o torçor é máximo justamente no apoio, e a barra lateral que
    terminava 12,5 cm além da face não ancorava nada.

    Barra lateral: reta, ou com gancho a 90° no plano horizontal quando a reta
    não cabe (o cobrimento normal ao plano do gancho é a distância vertical às
    outras barras, folgada, e o 9.4.2.5 admite α = 0,7). Porta-estribo que
    leva torção: o gancho vertical que ele já tem, com o α = 0,7 só se o
    cobrimento lateral der 3 Ø. Não cabendo, é erro.
    """
    conc, aco, cfg = viga.concreto, viga.aco, viga.config
    cob = viga.ambiente.cobrimento_nominal
    xs = viga.x_apoios
    saida: list[anc.AncoragemTorcao] = []
    for k in sorted({0, len(viga.apoios) - 1}):
        ap = viga.apoios[k]
        if ap.tipo == "livre":
            continue
        esquerda = k == 0
        x_face = xs[k] + (ap.largura / 200.0 if esquerda
                          else -ap.largura / 200.0)
        for p in posicoes:
            if p.As_torcao <= 1e-6 or p.tipo not in ("pele", "porta"):
                continue
            ponta = p.x_ini if esquerda else p.x_fim
            if (ponta > x_face + 1e-6) if esquerda else (ponta < x_face - 1e-6):
                continue
            secao = al.secao_da(viga, p)
            l_disp = abs(x_face - ponta) * 100.0
            As_ef = p.n * area_barra(p.phi)
            As_calc = min(p.As_torcao, As_ef)
            face = "superior" if p.tipo == "pele" else p.face
            reta = anc.ancorar(conc, aco, p.phi, As_calc, As_ef, face,
                               secao.h)
            piso = max(aco.raio_dobramento(p.phi) + 5.5 * p.phi / 10.0,
                       anc.PISO_ANCORAGEM_APOIO)
            exigido = max(reta.lb_nec, piso)
            solucao, ok = "reta", l_disp >= exigido - 1e-9
            if not ok:
                if p.tipo == "pele":
                    normal = secao.h / 2.0
                    tem_gancho = cfg.ancoragem_gancho
                else:
                    normal = cob + cfg.phi_estribo / 10.0
                    perna = p.dobra_ini if esquerda else p.dobra_fim
                    tem_gancho = (perna > 1e-9 and (p.tipo_gancho
                                                    or _tipo_gancho(viga))
                                  != gk.SEM_GANCHO)
                if tem_gancho:
                    g = anc.ancorar(conc, aco, p.phi, As_calc, As_ef, face,
                                    secao.h, gancho=True,
                                    cobrimento_normal=normal)
                    exigido = max(g.lb_nec, piso)
                    ok = l_disp >= exigido - 1e-9
                    if ok and p.tipo == "pele":
                        solucao = "gancho a 90° no plano horizontal"
                        p.comprimento += aco.altura_gancho_90(p.phi)
                        p.descricao += (f" — gancho a 90° no plano horizontal "
                                        f"no apoio {k + 1}")
                    elif ok:
                        solucao = "com gancho"
            if not ok:
                solucao = "não cabe"
                # a bitola mais grossa que caberia, com a mesma área: barra
                # fina ancora em menos comprimento
                cabe = None
                for f in sorted((f for f in BITOLAS_BARRAS
                                 if det.PHI_PORTA_ESTRIBO - 1e-9 <= f < p.phi),
                                reverse=True):
                    n_f = max(p.n, 2 * math.ceil(As_calc / 2.0
                                                 / area_barra(f) - 1e-9))
                    g_f = anc.ancorar(conc, aco, f, As_calc,
                                      n_f * area_barra(f), face, secao.h,
                                      gancho=True, cobrimento_normal=normal
                                      if p.tipo == "pele" else 0.0)
                    if max(g_f.lb_nec, piso) <= l_disp + 1e-9:
                        cabe = (f, n_f)
                        break
                sugestao = (f" Com {cabe[1]} Ø{cabe[0]:g} (bitola imposta da "
                            f"armadura lateral do tramo) a ancoragem caberia."
                            if cabe and p.tipo == "pele" else "")
                avisos.append(av.erro(
                    f"Apoio {k + 1}: a armadura longitudinal de torção "
                    f"N{p.numero} (Ø{p.phi:g}) não ancora no apoio de "
                    f"extremidade: exige {exigido:.0f} cm a partir da face "
                    f"(9.4.1, medido como no 18.3.2.4.1, com a barra em má "
                    f"aderência) e há {l_disp:.0f} cm. Alargue o apoio ou "
                    f"reduza a bitola.{sugestao}"))
            saida.append(anc.AncoragemTorcao(
                apoio=k + 1, posicao=p, phi=p.phi, As_calc=As_calc,
                As_ef=As_ef, lb_nec=reta.lb_nec, exigido=exigido,
                l_disponivel=l_disp, ok=ok, solucao=solucao))
    return saida


def _ancorar_negativa_nos_extremos(viga: Viga, regioes: list[Regiao],
                                   posicoes: list[det.Posicao],
                                   avisos: list[str]
                                   ) -> list[anc.AncoragemNegativa]:
    """Ancora a armadura negativa nos apoios de extremidade (18.3.2.4-d).

    O item 18.3.2.4-d manda ancorar "conforme 18.3.2.4.1" a armadura de
    momento negativo dos apoios extremos: a partir da **face** do apoio, o
    maior entre lb,nec, (r + 5,5 Ø) e 60 mm. Só a armadura positiva era
    verificada; a negativa do engaste da V10 do pacote de conferência (2 Ø20)
    terminava num gancho de 25 cm, com 26 cm retos contra ~107 cm de lb,nec.

    * Se o trecho reto (com o gancho, quando o 9.4.2.5 admite α = 0,7) basta,
      fica como está.
    * Se não basta e o apoio é **engaste**, a barra desce no apoio (pilar ou
      parede): a perna vertical cresce até que os trechos retos somem lb,nec
      de ancoragem **reta** -- a perna longa não é o gancho padronizado, e por
      isso o α = 0,7 não entra. A curva fica num nó de pórtico, e o 18.2.2
      pede ali diâmetro de 15 Ø (CA-50), reduzível na proporção da tensão da
      barra no início da curva, nunca abaixo do pino do gancho.
    * Se não basta e o apoio não é engaste, é erro: não há onde descer.

    A barra é tomada inteira em má aderência, também na perna vertical, que
    está em boa (9.3.1) -- a favor da segurança.
    """
    cfg = viga.config
    conc, aco = viga.concreto, viga.aco
    cob = viga.ambiente.cobrimento_nominal
    xs = viga.x_apoios
    saida: list[anc.AncoragemNegativa] = []
    for k in sorted({0, len(viga.apoios) - 1}):
        ap = viga.apoios[k]
        if ap.tipo == "livre":
            continue
        reg = next((r for r in regioes if r.tipo == "apoio" and r.indice == k
                    and not r.construtiva), None)
        if reg is None:
            continue
        esquerda = k == 0
        x_face = xs[k] + (ap.largura / 200.0 if esquerda
                          else -ap.largura / 200.0)
        barras = [p for p in posicoes
                  if p.tipo == "longitudinal" and p.face == "superior"
                  and p.descricao.startswith(reg.nome)
                  and ((p.x_ini <= x_face + 1e-6) if esquerda
                       else (p.x_fim >= x_face - 1e-6))]
        if not barras:
            continue
        phi = max(p.phi for p in barras)
        As_ef = sum(p.n * area_barra(p.phi) for p in barras)
        As_calc = min(reg.flexao.As_adotado, As_ef)
        ponta = min(p.x_ini for p in barras) if esquerda else max(
            p.x_fim for p in barras)
        l_reto = abs(x_face - ponta) * 100.0
        reta = anc.ancorar(conc, aco, phi, As_calc, As_ef, "superior",
                           reg.secao.h)
        piso = max(aco.raio_dobramento(phi) + 5.5 * phi / 10.0,
                   anc.PISO_ANCORAGEM_APOIO)
        exigido = max(reta.lb_nec, piso)
        perna_atual = max((p.dobra_ini if esquerda else p.dobra_fim)
                          for p in barras)
        tipo = barras[0].tipo_gancho or _tipo_gancho(viga, reg.nome)
        com_gancho = perna_atual > 1e-9 and tipo != gk.SEM_GANCHO
        exigido_gancho = exigido
        if com_gancho:
            # o gancho no plano vertical: o cobrimento normal a ele é o lateral
            g = anc.ancorar(conc, aco, phi, As_calc, As_ef, "superior",
                            reg.secao.h, gancho=True,
                            cobrimento_normal=cob + cfg.phi_estribo / 10.0)
            exigido_gancho = max(g.lb_nec, piso)
        pino = aco.diametro_dobramento(phi)
        if l_reto >= exigido_gancho - 1e-9:
            saida.append(anc.AncoragemNegativa(
                apoio=k + 1, phi=phi, As_calc=As_calc, As_ef=As_ef,
                lb_nec=reta.lb_nec, piso=piso, exigido=exigido_gancho,
                l_reto=l_reto, diametro_curva=pino, perna=perna_atual,
                desenvolvido=l_reto, ok=True,
                solucao=("trecho reto e gancho" if com_gancho
                         else "trecho reto")))
            continue
        if ap.tipo != "engaste" or not cfg.ancoragem_gancho \
                or tipo == gk.SEM_GANCHO:
            saida.append(anc.AncoragemNegativa(
                apoio=k + 1, phi=phi, As_calc=As_calc, As_ef=As_ef,
                lb_nec=reta.lb_nec, piso=piso, exigido=exigido_gancho,
                l_reto=l_reto, diametro_curva=pino, perna=perna_atual,
                desenvolvido=l_reto, ok=False, solucao="não cabe"))
            motivo = ("o apoio não é engaste, e não há onde a barra descer"
                      if ap.tipo != "engaste" else
                      "o gancho está desligado nos critérios")
            avisos.append(av.erro(
                f"Apoio {k + 1}: a armadura negativa ({reg.nome}, Ø{phi:g}) "
                f"não ancora no apoio de extremidade (18.3.2.4-d e "
                f"18.3.2.4.1): exige {exigido_gancho:.0f} cm a partir da face "
                f"e há {l_reto:.0f} cm retos; {motivo}. Alargue o apoio, "
                f"reduza a bitola ou detalhe a ancoragem no elemento de "
                f"apoio."))
            continue
        # a barra desce no apoio. A curva é de nó de pórtico (18.2.2), com o
        # diâmetro reduzido na proporção da tensão que sobra no início dela
        sigma_face = As_calc / As_ef
        fator_no = anc.DIAMETRO_CURVA_NO_DE_PORTICO[aco.categoria]
        diametro = pino
        for _ in range(4):
            antes_da_curva = max(l_reto - diametro / 2.0 - phi / 10.0, 0.0)
            sigma_curva = sigma_face * max(0.0, 1.0 - antes_da_curva
                                           / max(reta.lb, 1e-9))
            diametro = max(pino, fator_no * phi / 10.0 * sigma_curva)
        r_eixo = diametro / 2.0 + phi / 20.0
        # os 26 cm "retos" da V10 vão da face do apoio à face externa da perna;
        # a curva come r + Ø/2 deles. O que sobra antes dela é o trecho reto
        # de fato, e se não sobra nada a curva não cabe no apoio
        horizontal = l_reto - r_eixo - phi / 20.0
        perna = max(perna_atual, exigido - max(horizontal, 0.0)
                    + r_eixo + phi / 20.0)
        desenvolvido = max(horizontal, 0.0) + perna - r_eixo - phi / 20.0
        # quanto a perna entra abaixo da face inferior da viga: a perna é a
        # dimensão externa, medida da face de cima da barra
        topo_da_barra = reg.secao.h - cob - cfg.phi_estribo / 10.0
        abaixo = max(perna - topo_da_barra, 0.0)
        # o pilar tem de comportar a perna com o cobrimento na ponta
        pilar_exigido = abaixo + cob if abaixo > 1e-9 else 0.0
        pilar = ap.altura_pilar_abaixo
        problemas = []
        if horizontal < -1e-9:
            problemas.append(
                f"a curva (pino D ≥ {diametro:.0f} cm, raio {r_eixo:.1f} cm "
                f"no eixo) não cabe nos {l_reto:.0f} cm do apoio")
        if pilar > 1e-9 and pilar < pilar_exigido - 1e-9:
            problemas.append(
                f"a perna entra {abaixo:.0f} cm abaixo da viga e o pilar tem "
                f"{pilar:.0f} cm (são precisos {pilar_exigido:.0f} cm, com o "
                f"cobrimento na ponta)")
        for p in barras:
            if esquerda:
                p.dobra_ini = perna
            else:
                p.dobra_fim = perna
            p.raio_dobra = max(p.raio_dobra, r_eixo)
            p.descricao += (f" — desce {perna:.0f} cm no apoio {k + 1} "
                            f"(ancoragem da negativa, 18.3.2.4-d; curva com "
                            f"pino D ≥ {diametro:.0f} cm, 18.2.2)")
        ok = not problemas
        saida.append(anc.AncoragemNegativa(
            apoio=k + 1, phi=phi, As_calc=As_calc, As_ef=As_ef,
            lb_nec=reta.lb_nec, piso=piso, exigido=exigido,
            l_reto=l_reto, diametro_curva=diametro, perna=perna,
            desenvolvido=desenvolvido, ok=ok,
            solucao=f"desce {perna:.0f} cm no apoio" if ok else "não cabe",
            reto_ate_curva=max(horizontal, 0.0), raio_eixo=r_eixo,
            abaixo_da_viga=abaixo, pilar_exigido=pilar_exigido,
            pilar_informado=pilar))
        if problemas:
            avisos.append(av.erro(
                f"Apoio {k + 1}: a armadura negativa ({reg.nome}, Ø{phi:g}) "
                f"precisa descer {perna:.0f} cm no engaste para ancorar "
                f"(18.3.2.4-d e 18.3.2.4.1), mas " + " e ".join(problemas)
                + ". Alargue ou aprofunde o apoio, reduza a bitola ou detalhe "
                  "o nó à mão."))
            continue
        if pilar > 1e-9:
            condicao = (f"O pilar informado tem {pilar:.0f} cm abaixo da viga, "
                        f"e a perna precisa de {pilar_exigido:.0f} cm.")
        else:
            condicao = (f"A altura do pilar abaixo da viga não foi informada: "
                        f"ela tem de ser de pelo menos {pilar_exigido:.0f} cm "
                        f"(a perna entra {abaixo:.0f} cm abaixo da viga, mais "
                        f"o cobrimento) — confira, ou informe-a no apoio.")
        avisos.append(av.construtivo(
            f"Apoio {k + 1}: a armadura negativa ({reg.nome}, Ø{phi:g}) não "
            f"ancora nos {l_reto:.0f} cm do engaste (exige {exigido:.0f} cm a "
            f"partir da face, 18.3.2.4-d e 18.3.2.4.1) e desce {perna:.0f} cm "
            f"no pilar. A curva fica num nó de pórtico: pino D ≥ "
            f"{diametro:.0f} cm (18.2.2, reduzido pela tensão no início da "
            f"curva), raio de {r_eixo:.1f} cm no eixo, com {horizontal:.0f} cm "
            f"retos antes dela. {condicao} A interferência com a armadura do "
            f"pilar não é verificada."))
    return saida


def _verificar_ductilidade_adotada(viga: Viga, regioes: list[Regiao],
                                   posicoes: list[det.Posicao],
                                   avisos: list[str]) -> dict[str, float]:
    """x/d da seção **adotada**, com a armadura comprimida presente (14.6.4.3).

    O limite de x/d era comparado com a armadura necessária. A seção real tem
    a armadura adotada -- na V04 do pacote de conferência, 3 Ø25 = 14,73 cm²
    onde bastavam 10,71 --, e mais armadura tracionada aprofunda a linha
    neutra: x/d = 0,35 com o As necessário e 0,48 com o adotado, acima de 0,45.
    Em compensação, as barras da face oposta que atravessam a seção trabalham
    comprimidas e a trazem de volta, **se estiverem ancoradas**: a força numa
    barra comprimida vem da aderência dos dois lados da seção, e por isso cada
    uma só conta com lb de ancoragem (reta, sem gancho, 9.4.2.5) para cada lado.

    Grava em cada região ``x_d_adotada`` e a armadura comprimida contada.
    Devolve ``{região: bitola}`` para as que não passam e têm um arranjo que
    passaria: o cálculo é refeito com essa bitola (ver :func:`dimensionar`). A
    que não tem saída é erro.
    """
    conc, aco, cfg = viga.concreto, viga.aco, viga.config
    cob = _cobrimento(viga)
    pedidos: dict[str, float] = {}
    for r in regioes:
        if r.construtiva or r.flexao is None:
            continue
        oposta = "superior" if r.face == "inferior" else "inferior"
        comprimidas = []
        for p in posicoes:
            if p.tipo not in ("longitudinal", "porta") or p.face != oposta:
                continue
            lb = anc.ancorar(conc, aco, p.phi, 1.0, 1.0, p.face,
                             r.secao.h).lb / 100.0
            if p.x_ini <= r.x - lb + 1e-9 and p.x_fim >= r.x + lb - 1e-9:
                comprimidas.append(p)
        As_linha = sum(p.n * area_barra(p.phi) for p in comprimidas)
        d_linha = (cob + cfg.phi_estribo / 10.0
                   + max((p.phi for p in comprimidas), default=0.0) / 20.0)
        lim = r.flexao.x_lim_d

        def x_d(As: float, d: float) -> float:
            return fl.linha_neutra(r.secao, conc, aco, As, d, As_linha,
                                   d_linha, r.face) / d

        r.x_d_adotada = x_d(r.arranjo.As_ef, r.d)
        r.As_comprimida_presente = As_linha
        r.comprimidas_presentes = [p.numero for p in comprimidas]
        r.flexao.memoria["x/d da seção adotada"] = r.x_d_adotada
        r.flexao.memoria["As' presente e ancorada (cm²)"] = As_linha
        if r.x_d_adotada <= lim + 1e-6:
            continue
        # um arranjo com menos sobra de área: a bitola que, com a mesma
        # armadura comprimida, devolve x/d ao limite com o menor As efetivo
        # Cada candidato é refeito com o seu próprio d: mais camadas baixam o
        # d e pedem mais aço. No máximo duas camadas e 12 barras -- sem esse
        # teto a busca achava 17 Ø10 em oito camadas
        melhor = None
        if not _phi_imposta(viga, r.nome):
            d_linha_f = cob + cfg.phi_estribo / 10.0 + 1.0
            for phi in BITOLAS_BARRAS:
                if not (cfg.phi_min_longitudinal - 1e-9 <= phi
                        <= cfg.phi_max_longitudinal + 1e-9):
                    continue
                arr = det.escolher_barras(
                    r.secao, r.flexao.As_adotado + r.As_torcao, cob,
                    cfg.phi_estribo, cfg.d_agregado, phi_fixo=phi,
                    n_ramos=cfg.n_ramos)
                pedido = float("inf")
                for _ in range(4):
                    if len(arr.camadas) > 2:
                        break
                    try:
                        pedido = fl.dimensionar(
                            r.secao, conc, aco, r.M, d_linha_f,
                            r.secao.h - arr.d,
                            delta=cfg.redistribuicao).As_adotado + r.As_torcao
                    except ValueError:        # d curto demais: não serve
                        pedido = float("inf")
                        break
                    if arr.As_ef >= pedido - 1e-9:
                        break
                    arr = det.escolher_barras(
                        r.secao, pedido, cob, cfg.phi_estribo,
                        cfg.d_agregado, phi_fixo=phi, n_ramos=cfg.n_ramos)
                if (not arr.cabe or arr.n > 12 or len(arr.camadas) > 2
                        or arr.As_ef < pedido - 1e-9):
                    continue
                if x_d(arr.As_ef, arr.d) <= lim - 1e-3 and (
                        melhor is None
                        or (len(arr.camadas), round(arr.As_ef, 6))
                        < (len(melhor.camadas), round(melhor.As_ef, 6))):
                    melhor = arr
        if melhor is not None and abs(melhor.phi - r.arranjo.phi) > 1e-9:
            pedidos[r.nome] = melhor.phi
            continue
        avisos.append(av.erro(
            f"{r.nome}: x/d = {r.x_d_adotada:.3f} na seção adotada "
            f"({r.arranjo.descricao}, As = {r.arranjo.As_ef:.2f} cm², com "
            f"{As_linha:.2f} cm² de armadura comprimida ancorada), acima do "
            f"limite de {lim:.2f} do item 14.6.4.3. O x/d do As necessário "
            f"({r.flexao.memoria.get('x/d', 0.0):.3f}) não basta: a "
            f"ductilidade é a da armadura que vai na peça. Reduza a sobra de "
            f"armadura, acrescente armadura comprimida ancorada ou aumente a "
            f"seção."))
    return pedidos


def _repartir_barras_longas(viga: Viga, posicoes: list[det.Posicao],
                            avisos: list[str], x: np.ndarray,
                            As_inf: np.ndarray, As_sup: np.ndarray) -> None:
    """Divide as barras maiores que o vergalhão comercial em peças emendadas.

    A emenda é por traspasse (9.5.2.2.1); sem informação sobre o escalonamento
    das emendas adota-se 50 % das barras emendadas na mesma seção, o que dá
    alfa_0t = 1,8 -- a favor da segurança.

    A posição de cada emenda **não** é o meio da barra: o item 9.5.2.1 pede
    emenda em região de menor solicitação, e o meio do vão é justamente onde a
    armadura positiva trabalha mais. Dentro da janela em que as peças ainda
    caibam nos 12 m comerciais, escolhe-se o ponto de menor área de aço
    necessária para aquela face.
    """
    for p in posicoes:
        if p.tipo == "estribo" or p.comprimento <= anc.COMPRIMENTO_COMERCIAL:
            continue
        secao = al.secao_da(viga, p)
        # a barra de pele usa a aderência da sua própria altura (9.3.1).
        # Sendo a pele uma posição só, o traspasse é o da **pior** barra do
        # conjunto: elas levam todas o mesmo comprimento, e dimensionar pela
        # média deixaria a de baixo curta. A pele só existe em viga com
        # h > 60 cm, onde a aderência melhora com a altura -- a pior é a mais
        # baixa
        altura = (min(p.faixa_altura)
                  if p.tipo == "pele" and any(p.faixa_altura) else None)
        l0t = _traspasse_necessario(viga, p.phi, p.face, secao.h,
                                    p.comprimida, altura)
        n_pecas, comp_peca = anc.repartir_barra(p.comprimento, l0t)
        demanda = As_sup if p.face == "superior" else As_inf
        emendas, pecas = _posicionar_emendas(p, n_pecas, l0t, x, demanda)
        p.n_pecas = n_pecas
        p.comprimento_peca = comp_peca
        p.traspasse = l0t
        p.emendas_x = emendas
        p.pecas = pecas
        locais = ", ".join(
            f"{(p.x_ini + e / 100.0):.2f} m" for e in emendas)
        avisos.append(av.construtivo(
            f"N{p.numero}: barra de {p.comprimento / 100:.2f} m supera o "
            f"vergalhão comercial de {anc.COMPRIMENTO_COMERCIAL / 100:g} m; "
            f"dividida em {n_pecas} peças "
            f"({' + '.join(f'{c:.0f}' for c in pecas)} cm) com traspasse de "
            f"{l0t:.0f} cm iniciando em {locais} (9.5.2.2.1)."))


def _posicionar_emendas(p: det.Posicao, n_pecas: int, l0t: float,
                        x: np.ndarray, demanda: np.ndarray
                        ) -> tuple[list[float], list[float]]:
    """Escolhe onde emendar e devolve (inícios dos traspasses, comprimentos).

    As distâncias saem em cm a partir da extremidade esquerda da barra. As
    peças podem ter comprimentos diferentes -- é o que permite fugir da região
    mais solicitada sem estourar os 12 m.
    """
    C = p.comprimento
    maximo = anc.COMPRIMENTO_COMERCIAL
    util = maximo - l0t
    inicios: list[float] = []
    s = 0.0                                   # início da peça corrente
    for i in range(n_pecas - 1):
        restantes = n_pecas - i - 1           # peças depois desta emenda
        limite_inf = max(s + l0t, C - maximo - (restantes - 1) * util)
        limite_sup = min(s + util, C - l0t)
        if limite_sup <= limite_inf:
            inicio = max(limite_inf, 0.0)
        else:
            inicio = _minimo_demanda(p, limite_inf, limite_sup, l0t, x, demanda)
        inicios.append(inicio)
        s = inicio
    pecas: list[float] = []
    for k in range(n_pecas):
        ini = 0.0 if k == 0 else inicios[k - 1]
        fim = C if k == n_pecas - 1 else inicios[k] + l0t
        pecas.append(fim - ini)
    return inicios, pecas


def _minimo_demanda(p: det.Posicao, inf: float, sup: float, l0t: float,
                    x: np.ndarray, demanda: np.ndarray) -> float:
    """Ponto da janela [inf, sup] em que a face pede menos armadura."""
    candidatos = np.linspace(inf, sup, 40)
    melhor, melhor_custo = candidatos[0], float("inf")
    for c in candidatos:
        # avalia no meio do traspasse, que é onde a emenda de fato trabalha
        xi = p.x_ini + (c + l0t / 2.0) / 100.0
        custo = float(np.interp(xi, x, np.nan_to_num(demanda)))
        if custo < melhor_custo - 1e-9:
            melhor, melhor_custo = c, custo
    return float(melhor)


def _comprimento_estribo(secao: Secao, cob: float, phi_mm: float,
                         pernas: float = 0.0, n_ramos: int = 2,
                         gancho_estribo: bool = True) -> float:
    """Comprimento do estribo de uma seção, cm.

    Soma o perímetro interno, os dois ganchos de 5 Ø (mínimo 5 cm) e as
    ``pernas`` das dobras de amarração, que o item 9.4.6.1 exige para o
    estribo abraçar a armadura longitudinal e que não aparecem na medida
    geométrica do perímetro. Acima de dois ramos, cada ramo interno entra como
    um grampo de altura útil com os seus próprios ganchos -- senão o
    quantitativo ignoraria o aço dos ramos que o item 18.3.3.2 obrigou a
    acrescentar.
    """
    b = secao.bw - 2.0 * cob
    h = secao.h - 2.0 * cob
    # sem gancho, o item 9.4.6.2 exige fechar o estribo por barra transversal
    # soldada; o perímetro é o mesmo, o que sai são as duas pontas
    gancho = max(5.0 * phi_mm / 10.0, 5.0) if gancho_estribo else 0.0
    comp = 2.0 * (b + h) + 2.0 * gancho + pernas
    if n_ramos > 2:
        comp += (n_ramos - 2) * (h + 2.0 * gancho + pernas / 2.0)
    return comp


# ---------------------------------------------------------------------------
# Quantitativo
# ---------------------------------------------------------------------------

def _torcao_de_compatibilidade(viga: Viga, x: np.ndarray,
                               asw_req: np.ndarray,
                               cortantes: list[ci.ResultadoCortante],
                               cob: float, phi_t: float,
                               avisos: list[str]) -> None:
    """Desprezar a torção de compatibilidade tem preço (17.5.1.2).

    O item permite desprezá-la "desde que o elemento tenha capacidade adequada
    de adaptação plástica" e, para garanti-la, manda **respeitar a armadura
    mínima de torção e limitar a força cortante a Vsd <= 0,7 VRd2** no trecho
    torcido. Antes o programa apenas reclamava; agora cumpre as duas
    contrapartidas.
    """
    conc, aco = viga.concreto, viga.aco
    c1 = cob + phi_t / 10.0 + 1.0
    trechos = [(min(t.x, getattr(t, "x_fim", t.x) or t.x),
                max(t.x, getattr(t, "x_fim", t.x) or t.x))
               for t in viga.torcores]
    acrescimo = 0.0
    excedidas: list[tuple[float, float]] = []
    for i, xi in enumerate(x):
        if not any(a - 1e-9 <= xi <= b + 1e-9 for a, b in trechos):
            continue
        secao = viga.secao_em(xi)
        minimo = to.armadura_minima_transversal(secao, conc, aco, c1)
        alvo = minimo + cortantes[i].asw_min
        if alvo > asw_req[i]:
            acrescimo = max(acrescimo, alvo - asw_req[i])
            asw_req[i] = alvo
        r = cortantes[i]
        if r.Vsd > 0.7 * r.VRd2:
            excedidas.append((xi, r.Vsd / r.VRd2))
    avisos.append(av.construtivo(
        f"Torção de compatibilidade desprezada (17.5.1.2): em troca, o trecho "
        f"torcido recebeu a armadura mínima de torção somada à de cisalhamento"
        f"{f' (+{acrescimo:.2f} cm²/m no ponto mais exigido)' if acrescimo else ''}"
        f" e o cortante foi limitado a 0,7·VRd2."))
    if excedidas:
        xi, razao = max(excedidas, key=lambda t: t[1])
        avisos.append(av.erro(
            f"Torção de compatibilidade desprezada, mas em x = {xi:.2f} m "
            f"Vsd/VRd2 = {razao:.2f} passa de 0,70: o item 17.5.1.2 só admite "
            f"desprezá-la com Vsd <= 0,7·VRd2. Dimensione a torção ou aumente "
            f"a seção."))


def _verificar_resultante(viga: Viga, regioes: list[Regiao],
                          avisos: list[str]) -> None:
    """Item 17.2.4.1: as forças podem ser concentradas no CG da armadura?

    O programa calcula ``d`` a partir do centro de gravidade das barras, o que
    é a hipótese que este item autoriza -- e o item a autoriza **sob condição**.
    Onde a condição não vale, o ``d`` do CG deixa de representar o conjunto e a
    seção teria de ser verificada camada a camada, o que está fora do que o
    programa faz: por isso sai erro, e não aviso construtivo.
    """
    for r in regioes:
        h = r.secao.h
        for arr, papel in ((r.arranjo, "tracionada"),
                           (r.arranjo_comprimido, "comprimida")):
            if arr is None:
                continue
            ok, dist = det.resultante_concentrada(arr, h)
            if ok:
                continue
            avisos.append(av.erro(
                f"{r.nome}: a armadura {papel} ({arr.descricao}) tem o centro "
                f"de gravidade a {dist:.1f} cm da camada mais afastada, acima "
                f"dos 10 % de h = {0.1 * h:.1f} cm que o item 17.2.4.1 admite "
                f"para concentrar as forças no CG. Com tantas camadas nesta "
                f"altura, o d do centro de gravidade não representa o "
                f"conjunto: aumente a altura, reduza a bitola ou verifique a "
                f"seção camada a camada fora do programa."))


def _verificar_taxa_maxima(regioes: list[Regiao],
                           avisos: list[str]) -> None:
    """4 % de Ac sobre a armadura **adotada** (17.3.5.2.4).

    A verificação da flexão compara a armadura *calculada*; o que vai para a
    viga é a *adotada*, sempre maior. O item exclui a zona de emendas, onde a
    área local dobra -- por isso a conferência é sobre a armadura corrida.
    """
    for r in regioes:
        As = r.arranjo.As_ef
        As_linha = r.arranjo_comprimido.As_ef if r.arranjo_comprimido else 0.0
        limite = 0.04 * r.secao.area
        if As + As_linha > limite + 1e-9:
            avisos.append(av.erro(
                f"{r.nome}: a armadura adotada As + A's = "
                f"{As + As_linha:.2f} cm² passa de 4 % de Ac = "
                f"{limite:.2f} cm² (17.3.5.2.4, medido fora da zona de "
                f"emendas). Aumente a seção ou o fck."))


def _armar_suspensao(viga: Viga, posicoes: list[det.Posicao],
                     zonas: list[det.ZonaEstribo],
                     avisos: list[str]) -> None:
    """Armadura de suspensão sob carga indireta (18.3.6).

    Onde outra viga se apoia nesta -- ou fica nela pendurada --, a carga não
    entra pelo banzo comprimido e tem de ser "pendurada" por armadura própria,
    **somada** à de cisalhamento. São dois casos, e a conta de um não serve
    para o outro:

    * **viga apoiada, não pendurada** (o caso corrente): o item manda pôr ao
      menos 75 % do tirante ``Vd/fyd`` na viga de apoio, numa extensão máxima
      de ``h`` da viga de apoio centrada no cruzamento. Os 25 % restantes ficam
      na viga apoiada, que não é modelada aqui;

    * **viga pendurada** -- "quando a face inferior da viga apoiada está abaixo
      da face inferior da viga de apoio". A norma não a detalha, e o critério
      corrente (Fusco) é ``As,susp,1 = Vd/fyd`` **inteiro**, para levar a força
      da borda inferior da viga apoiada até a borda superior da viga de apoio,
      **mais** ``As,susp,2 = Vd/2fyd`` de reforço da região que recebe a força.
      São 150 % do tirante, o dobro do outro caso, e **nada** vai para a viga
      apoiada -- ela é que está pendurada.

    Tratar pendurada como apoiada armaria metade do necessário, e é por isso
    que a distinção é entrada de dados e não padrão.
    """
    indiretas = [c for c in viga.concentradas if getattr(c, "indireta", False)]
    if not indiretas or not zonas:
        return
    cfg = viga.config
    cob = _cobrimento(viga)
    aco = viga.aco
    numero = max((p.numero for p in posicoes), default=0)
    novas: list[det.Posicao] = []
    for c in indiretas:
        gamma = cfg.gamma_g if c.acao == "g" else cfg.gamma_q
        Fsd = gamma * abs(c.P)
        As_tirante = Fsd / aco.fyd_kNcm2
        pendurada = bool(getattr(c, "pendurada", False))
        # 100 % para suspender + 50 % de reforço, contra 75 % da viga apoiada
        As_viga = (1.5 if pendurada else 0.75) * As_tirante
        secao = viga.secao_em(c.x)
        zona = _zona_em(zonas, c.x)
        if zona is None:
            continue
        extensao = secao.h                      # h da viga de apoio, cm
        por_estribo = zona.n_ramos * area_barra(zona.phi)
        n_estribos = max(1, math.ceil(As_viga / por_estribo - 1e-9))
        s_susp = min(zona.s, extensao / max(n_estribos, 1))
        numero += 1
        novas.append(det.Posicao(
            numero=numero, tipo="suspensao", n=n_estribos, phi=zona.phi,
            n_ramos_efetivo=cfg.n_ramos,
            face="alma", x_ini=c.x - extensao / 200.0,
            x_fim=c.x + extensao / 200.0,
            comprimento=_comprimento_estribo(
                secao, cob, zona.phi, cfg.pernas_amarracao_estribo,
                zona.n_ramos, cfg.gancho_estribo),
            s=round(s_susp, 1), tramo=zona.tramo,
            descricao=(
                f"Armadura de suspensão da carga indireta de {abs(c.P):g} kN "
                f"em x = {c.x:.2f} m — "
                + (f"viga pendurada: 100 % do tirante para suspender mais "
                   f"50 % de reforço ({As_viga:.2f} de {As_tirante:.2f} cm²)"
                   if pendurada else
                   f"75 % do tirante ({As_viga:.2f} de {As_tirante:.2f} cm²)")
                + f" em {extensao:.0f} cm centrados no cruzamento "
                  f"(18.3.6)")))
    if novas:
        posicoes.extend(novas)
        n_pend = sum(1 for c in indiretas
                     if bool(getattr(c, "pendurada", False)))
        avisos.append(av.construtivo(
            f"Acrescentada armadura de suspensão em {len(novas)} carga(s) "
            f"indireta(s): o item 18.3.6 exige que a carga trazida por outra "
            f"viga seja pendurada por armadura própria, somada à de "
            f"cisalhamento, com pelo menos 75 % do tirante nesta viga. Os 25 % "
            f"restantes vão na viga apoiada, fora deste modelo."))
        if n_pend:
            avisos.append(av.construtivo(
                f"{n_pend} carga(s) marcada(s) como viga pendurada — face "
                f"inferior da viga apoiada abaixo da desta. Nesse caso a "
                f"armadura é 150 % do tirante (100 % para suspender a força "
                f"até o banzo comprimido, mais 50 % de reforço da região), "
                f"toda nesta viga, e os ramos verticais dos estribos têm de "
                f"ir da borda inferior da viga apoiada até a borda superior "
                f"desta — o comprimento tabelado aqui é o do estribo desta "
                f"viga e precisa ser alongado no desenho."))


def _verificar_fadiga(viga: Viga, est: Estrutura,
                      combs: list[cb.Combinacao], regioes: list[Regiao],
                      zonas: list[det.ZonaEstribo], x: np.ndarray,
                      cortantes: list[ci.ResultadoCortante],
                      avisos: list[str]
                      ) -> tuple[list[fad.ResultadoFadiga],
                                 list[fad.ResultadoFadigaEstribo]]:
    """Estado-limite último de fadiga (23.5).

    A solicitação é a da combinação frequente (23.5.2) e a variação de tensão
    sai da diferença entre ela e a parcela permanente -- é a parcela variável
    que oscila. O psi1 pode ser o da obra (rodoviária, ferroviária, ponte
    rolante); em branco, usa o psi1 geral dos critérios.
    """
    cfg = viga.config
    conc, aco = viga.concreto, viga.aco
    nt = len(viga.tramos)
    psi1 = cfg.psi1_fadiga or cfg.psi1
    marinho = viga.ambiente.caa == "IV"

    freq = [combinar(est, c.fg, psi1 / cfg.psi1 * c.fq if cfg.psi1 else c.fq,
                     c.nome)
            for c in combs if c.tipo == "ELS-frequente"]
    if not freq:
        return [], []
    M_max = np.max(np.array([f.M for f in freq]), axis=0)
    M_min = np.min(np.array([f.M for f in freq]), axis=0)
    V_freq = np.max(np.array([np.abs(f.V) for f in freq]), axis=0)
    perm = combinar(est, np.ones(nt), np.zeros(nt))
    # o estribo foi dimensionado com o cortante já reduzido junto ao apoio
    # (17.4.1.2.1); comparar a fadiga com o cortante bruto daria tensão acima
    # do escoamento em serviço, o que é sinal de comparação inconsistente
    V_perm = np.abs(np.interp(x, est.x, perm.V))
    if cfg.reducao_apoio:
        d_medio = float(np.median([c.d for c in cortantes])) if cortantes             else 0.0
        V_freq = ci.cortante_de_projeto(V_freq, x, viga, d_medio)
        V_perm = ci.cortante_de_projeto(V_perm, x, viga, d_medio)

    resultados: list[fad.ResultadoFadiga] = []
    for r in regioes:
        if r.construtiva:
            continue
        M_f = float(np.interp(r.x, est.x, M_max if r.face == "inferior"
                              else M_min))
        M_g = float(np.interp(r.x, est.x, perm.M))
        As_c = r.arranjo_comprimido.As_ef if r.arranjo_comprimido else 0.0
        rf = fad.verificar_secao(
            r.secao, conc, aco, M_f, M_g, r.arranjo.As_ef, r.d,
            r.arranjo.phi, r.nome, As_c, _cobrimento(viga) + 1.5, r.face,
            marinho)
        resultados.append(rf)
        r.avisos += rf.avisos

    # -- estribos, na seção mais solicitada de cada faixa ------------------
    estribos: list[fad.ResultadoFadigaEstribo] = []
    for z in zonas:
        m = (x >= z.x_ini - 1e-9) & (x <= z.x_fim + 1e-9)
        if not m.any():
            continue
        i = int(np.argmax(np.where(m, V_freq, -np.inf)))
        r = cortantes[i]
        rf = fad.verificar_estribo(
            V_frequente=float(V_freq[i]),
            V_permanente=float(V_perm[i]),
            Vc=r.Vc0, asw_cm2_m=z.asw_ef, d=r.d, phi_estribo=z.phi, aco=aco,
            modelo=cfg.modelo_cisalhamento, theta=cfg.theta,
            alpha=cfg.alpha_estribo, x=float(x[i]), marinho=marinho)
        estribos.append(rf)
        avisos += rf.avisos
    return resultados, estribos


def _verificar_viga_parede(viga: Viga, avisos: list[str]) -> None:
    """Alerta quando o tramo cai na definição de viga-parede (22.4.1).

    São vigas-parede as de ``l/h < 2`` biapoiadas e ``l/h < 3`` contínuas. Elas
    são ineficientes à flexão e ao cisalhamento e pedem modelo de bielas e
    tirantes (22.4.3) -- o dimensionamento de viga que este programa faz não
    se aplica.
    """
    for i in range(len(viga.tramos)):
        if not viga.eh_viga_parede(i):
            continue
        avisos.append(av.erro(
            f"Tramo {i + 1}: l/h = {viga.relacao_vao_altura(i):.2f} é menor "
            f"que {viga.limite_viga_parede(i):g} — o item 22.4.1 classifica "
            f"este tramo como **viga-parede**. O modelo de viga usado aqui "
            f"não se aplica: o dimensionamento deve seguir o item 22.4, com "
            f"modelo de bielas e tirantes."))


def _verificar_cobrimento(viga: Viga, posicoes: list[det.Posicao],
                          zonas: list[det.ZonaEstribo],
                          avisos: list[str]) -> None:
    """Condições de cobrimento e de bitola que não vêm da Tabela 7.2.

    O cobrimento nominal tem de ser pelo menos o diâmetro da barra (7.4.7.5) e
    o agregado graúdo não pode passar de 1,2 vez o cobrimento (7.4.7.6). Além
    disso, o item 18.3.3.2 exige que a barra longitudinal nos cantos do estribo
    não seja mais fina que o próprio estribo.
    """
    cob = _cobrimento(viga)
    cfg = viga.config
    phis = sorted({p.phi for p in posicoes if p.tipo != "estribo"})
    for phi in phis:
        if cob < phi / 10.0 - 1e-9:
            avisos.append(av.erro(
                f"Cobrimento nominal de {cob:.1f} cm menor que a bitola "
                f"Ø{phi:g} = {phi / 10.0:.2f} cm: o item 7.4.7.5 exige "
                f"c,nom >= Ø da barra. Aumente o cobrimento ou reduza a "
                f"bitola."))
            break
    if cfg.d_agregado > 1.2 * cob + 1e-9:
        avisos.append(av.erro(
            f"Agregado de {cfg.d_agregado:.1f} cm com cobrimento de "
            f"{cob:.1f} cm: o item 7.4.7.6 limita d,máx a 1,2·c,nom = "
            f"{1.2 * cob:.1f} cm."))
    # o item 18.3.3.2 é **local** e é sobre **o canto**: o que ele exige é que
    # o canto do estribo se apoie numa barra não mais fina que ele. Duas
    # leituras erradas já passaram por aqui: comparar a menor bitola da viga
    # com o maior estribo da viga acusava conflito entre um estribo Ø8 de um
    # tramo e um porta-estribo Ø6,3 de outro, que nunca se tocam; e exigir que
    # **toda** barra da camada externa fosse grossa acusava a cauda de
    # ancoragem de uma barra fina que entra 20 cm na faixa vizinha ao lado de
    # uma barra grossa que já cumpre o papel. Basta uma barra que sirva
    for z in zonas or []:
        for face in ("inferior", "superior"):
            no_canto = [q for q in posicoes
                        if q.face == face and q.camada == 1
                        and q.tipo in ("longitudinal", "porta")
                        and q.x_ini < z.x_fim - 1e-9
                        and q.x_fim > z.x_ini + 1e-9]
            if not no_canto:
                continue
            grade = np.linspace(z.x_ini, z.x_fim, 41)
            for xq in grade:
                presentes = [q for q in no_canto
                             if q.x_ini - 1e-9 <= xq <= q.x_fim + 1e-9]
                if not presentes:
                    continue          # falta de barra é outro item, e o
                                      # porta-estribo cuida dela
                melhor = max(presentes, key=lambda q: q.phi)
                if melhor.phi >= z.phi - 1e-9:
                    continue
                avisos.append(av.erro(
                    f"Face {face} em x = {xq:.2f} m: a barra mais grossa do "
                    f"canto é N{melhor.numero} Ø{melhor.phi:g} e o estribo da "
                    f"faixa é Ø{z.phi:g}. O item 18.3.3.2 exige que a barra do "
                    f"canto do estribo tenha diâmetro pelo menos igual ao "
                    f"dele."))
                break
            else:
                continue
            break


def _uniforme_que_costura(phi_atual: float, s_atual: float, terco: float,
                          As_req: float, phi_max: float = 1e9
                          ) -> tuple[float, float]:
    """(bitola, espaçamento) de uma distribuição **uniforme** que já costura.

    Devolve o par mais econômico que atende, num terço de ``terco`` cm, à área
    ``As_req`` de um ramo por estribo e ao espaçamento máximo de 15 cm da
    Figura 9.5, sem descer abaixo do espaçamento mínimo prático. Nunca afrouxa
    o que já existe: o espaçamento devolvido é no máximo o atual e a bitola no
    mínimo a atual.

    Entre os pares que atendem escolhe-se o de **menos aço por metro**,
    ``As_ramo / s``, e não o primeiro que couber. A diferença é grande porque a
    distribuição vale o vão inteiro: para costurar uma emenda de Ø20 num terço
    de 36 cm, Ø6,3 c/7,5 e Ø8 c/12 atendem os dois, mas ao longo de 4 m de viga
    o primeiro custa 57 estribos e o segundo 35.

    O espaçamento sai da grade comercial (``detalhamento.ESPACAMENTOS``),
    arredondado **para baixo**: um ``c/7,22`` calculado não é espaçamento de
    obra, e a faixa vizinha do mesmo desenho traz sempre valor de grade.

    ``phi_max`` é o teto imposto pela **barra do canto**: o item 18.3.3.2 exige
    que ela não seja mais fina que o estribo, e uma barra de flexão calculada
    não se engrossa para acomodar o estribo. Acima do teto só resta fechar o
    espaçamento, e é o que a função faz.
    """
    candidatas = [f for f in det.BITOLAS_ESTRIBOS
                  if phi_atual <= f <= phi_max + 1e-9] or [phi_atual]
    melhor = None
    for phi in candidatas:
        s_nec = _espacamento_que_costura(phi, s_atual, terco, As_req)
        if s_nec is None:
            continue
        custo = area_barra(phi) / s_nec          # aço por metro de viga
        if melhor is None or custo < melhor[0] - 1e-12:
            melhor = (custo, phi, s_nec)
    if melhor is None:
        return phi_atual, s_atual
    return melhor[1], melhor[2]


def _espacamento_que_costura(phi: float, s_atual: float, terco: float,
                             As_req: float) -> float | None:
    """Espaçamento de grade com que o estribo Ø``phi`` costura o terço.

    ``terco`` em cm e ``As_req`` em cm² (de um ramo por estribo). O terço tem de
    ter estribos em número que dê espaçamento de no máximo 15 cm (Figura 9.5) e
    área que resista à força da barra emendada. Nunca afrouxa (no máximo
    ``s_atual``) e sai da grade comercial, arredondado para baixo. ``None`` se
    nem o espaçamento prático mínimo basta com essa bitola.
    """
    n_esp = max(2, math.floor(terco / 15.0 + 1e-9) + 1)
    n = max(n_esp, math.ceil(max(As_req, 0.0) / area_barra(phi) - 1e-9), 2)
    # o teto de 15 cm é da Figura 9.5, e vale **entre os estribos**: a conta por
    # contagem (n estribos espalhados pelo terço) dava c/19 num terço de 57 cm
    # -- quatro estribos, mas três vãos de 19 --, que não é o espaçamento que a
    # figura diz e que as duas rotas da costura têm de respeitar igualmente
    s_calc = min(terco / (n - 1), s_atual, ESPACAMENTO_MAXIMO_DA_COSTURA)
    praticos = [v for v in det.ESPACAMENTOS
                if ESPACAMENTO_MINIMO_ESTRIBO - 1e-9 <= v <= s_calc + 1e-9]
    return praticos[-1] if praticos else None


def _teto_da_bitola(viga: Viga, posicoes: list[det.Posicao],
                    zona: det.ZonaEstribo) -> float:
    """Bitola máxima que o estribo daquela faixa pode assumir, mm.

    Dois tetos, e vale o menor:

    * a **barra do canto** calculada (18.3.3.2), que não se engrossa por
      conveniência do estribo;
    * a **bitola imposta pelo usuário** para aquele tramo, quando existe.
      Imposta quer dizer imposta: se o projeto escolheu Ø5, o reforço da
      costura fecha o espaçamento e não sobe a bitola. Sem este teto a escolha
      do usuário era desfeita a cada cálculo -- ele trocava para Ø5, o reforço
      devolvia Ø8, e a tabela mostrava Ø8 sem explicar por quê.
    """
    imposta = float((viga.config.bitolas_estribo or {})
                    .get(str(zona.tramo), 0.0) or 0.0)
    return min(_phi_canto_calculada(posicoes, zona.x_ini, zona.x_fim),
               imposta or 1e9)


def _phi_canto_calculada(posicoes: list[det.Posicao], xa: float,
                         xb: float) -> float:
    """Menor bitola de armadura **calculada** que faz canto de estribo ali.

    É o teto do item 18.3.3.2 para engrossar o estribo: a barra do canto não
    pode ser mais fina que ele, e uma barra de flexão dimensionada não se
    engrossa por conveniência do estribo. O porta-estribo, sim -- ele existe só
    para fechar o canto, e o programa já o dimensiona pela bitola do estribo.
    """
    phis = [q.phi for q in posicoes
            if q.tipo == "longitudinal" and q.camada == 1 and not q.so_canto
            and q.x_ini < xb - 1e-9 and q.x_fim > xa + 1e-9]
    return min(phis) if phis else 1e9


def _engrossar_porta_estribos(posicoes: list[det.Posicao], xa: float,
                              xb: float, phi: float) -> int:
    """Leva a bitola das barras de canto daquele trecho a pelo menos ``phi``.

    "Barra de canto" aqui é a que existe **só** para fechar o canto do estribo
    -- o porta-estribo e a armadura de uma região sem momento de tração naquela
    face, ambas marcadas com ``so_canto``. As duas nascem com a bitola de
    porta-estribo e não carregam força calculada, então engrossá-las é
    detalhamento, não redimensionamento.

    O item 18.3.3.2 exige que a barra do canto do estribo não seja mais fina
    que ele. ``_porta_estribos`` já aplica a regra, mas roda **antes** de a
    faixa ser reforçada para absorver a costura -- então o reforço tem de
    reaplicá-la, senão a viga sai com estribo Ø8 amarrado em porta-estribo
    Ø6,3 e o próprio programa acusa o erro (foi o que aconteceu).
    """
    mudados = 0
    for q in posicoes:
        if (not q.so_canto or q.camada != 1 or q.phi >= phi - 1e-9
                or q.x_ini >= xb - 1e-9 or q.x_fim <= xa + 1e-9):
            continue
        q.phi = phi
        q.descricao += f" — bitola elevada a Ø{phi:g} pelo estribo (18.3.3.2)"
        mudados += 1
    return mudados


def _reforcar_faixa(viga: Viga, zona: det.ZonaEstribo,
                    posicoes: list[det.Posicao], phi: float, s_novo: float,
                    cob: float) -> None:
    """Aplica (phi, s) à faixa e à posição de estribo que a desenha.

    A faixa e a posição são duas representações da mesma armadura -- uma para o
    cálculo, outra para o desenho e o quantitativo. Mexer numa e esquecer a
    outra faria a prancha mostrar um espaçamento e a lista de aço contar outro,
    que é a classe de defeito desta revisão inteira.
    """
    cfg = viga.config
    antes_phi, antes_s = zona.phi, zona.s
    zona.phi, zona.s = phi, s_novo
    zona.asw_ef = det.asw_efetiva(phi, s_novo, zona.n_ramos)
    zona.n_estribos = max(
        2, math.ceil((zona.x_fim - zona.x_ini) * 100.0 / s_novo) + 1)
    for q in posicoes:
        if (q.tipo != "estribo" or abs(q.x_ini - zona.x_ini) > 1e-6
                or abs(q.x_fim - zona.x_fim) > 1e-6
                or abs(q.phi - antes_phi) > 1e-9 or abs(q.s - antes_s) > 1e-9):
            continue
        q.phi = phi
        q.s = s_novo
        q.n = zona.n_estribos
        q.comprimento = _comprimento_estribo(
            al.secao_em(viga, (zona.x_ini + zona.x_fim) / 2.0), cob, phi,
            cfg.pernas_amarracao_estribo, zona.n_ramos, cfg.gancho_estribo)
        return


def _emendas_de(posicao) -> list[tuple[float, float]]:
    """As emendas de uma posição como ``(x global em m, l0t em cm)``."""
    saida = [(posicao.x_ini + e / 100.0, posicao.traspasse)
             for e in posicao.emendas_x]
    saida += [(posicao.x_ini + e / 100.0, l0t)
              for e, l0t, _viz in posicao.emendas_vizinhas]
    return [(xe, l0t) for xe, l0t in saida if l0t > 0.0]


def _tercos_da_emenda(x_emenda: float, l0t: float):
    """Os dois terços extremos do traspasse: ``(rótulo, (xa, xb))`` em m.

    A Figura 9.5 concentra a costura nos terços **extremos**, e cada um é
    avaliado contra os estribos que caem nele -- não contra a faixa do meio do
    traspasse. Num traspasse que atravessa o apoio, a faixa do meio é a do
    tramo vizinho: uniformizar o tramo adensava os estribos e a costura não
    desaparecia, porque a conta continuava lendo o espaçamento do outro lado.
    """
    terco = l0t / 3.0
    return (("inicial", (x_emenda, x_emenda + terco / 100.0)),
            ("final", (x_emenda + (l0t - terco) / 100.0,
                       x_emenda + l0t / 100.0)))


def _exigencias_de_costura(viga: Viga, posicoes: list[det.Posicao],
                           zonas: list[det.ZonaEstribo]
                           ) -> dict[int, tuple[float, float, str]]:
    """Reforço que cada tramo precisa para absorver a costura das emendas.

    ``{tramo: (bitola, espaçamento, motivo)}``, já com a mais exigente das
    emendas do tramo. Só faz sentido com a distribuição uniformizada, e existe
    como função separada porque é consultada **duas vezes**: no pré-passe, para
    decidir a bitola do estribo antes de montar as barras de canto, e no passe
    real, como rede de proteção. Duas cópias da regra divergiriam.
    """
    exige: dict[int, tuple[float, float, str]] = {}
    for p in posicoes:
        if p.tipo not in ("longitudinal", "porta", "pele"):
            continue
        for x_emenda, l0t in _emendas_de(p):
            terco = l0t / 3.0
            for _lado, (xa, xb) in _tercos_da_emenda(x_emenda, l0t):
                n_tem, area_tem, s_tem = _estribos_no_intervalo(zonas, xa, xb)
                if s_tem == 0.0:                  # fora de toda faixa
                    continue
                if (area_barra(p.phi) / 2.0 - area_tem <= 1e-9
                        and s_tem <= 15.0 + 1e-9):
                    continue
                zona = _zona_em(zonas, (xa + xb) / 2.0)
                phi_u, s_u = _uniforme_que_costura(
                    zona.phi, zona.s, terco, area_barra(p.phi) / 2.0,
                    _teto_da_bitola(viga, posicoes, zona))
                antigo = exige.get(zona.tramo)
                novo = (phi_u, s_u,
                        f"a emenda de N{p.numero} (Ø{p.phi:g}) em "
                        f"x = {x_emenda:.2f} m")
                if (antigo is None or phi_u > antigo[0]
                        or (phi_u == antigo[0] and s_u < antigo[1])):
                    exige[zona.tramo] = novo
    return exige


def _construtivas_pela_bitola_do_estribo(
        viga: Viga, regioes: list[Regiao],
        zonas: list[det.ZonaEstribo]) -> None:
    """Refaz o arranjo das regiões construtivas com a bitola do estribo final.

    A barra de uma face sem momento de tração existe só para fechar o canto do
    estribo, e o item 18.3.3.2 não admite que seja mais fina que ele. Trocar a
    bitola **na posição** não bastava: a ancoragem, o gancho e o traspasse dela
    saem do arranjo da região, e a viga ficava com uma barra Ø8 carregando a
    perna de gancho de uma Ø6,3 -- 6,9 cm onde o item 9.4.2.3 pede 8,8.

    Uma função, chamada pelo pré-passe depois de a bitola do estribo estar
    decidida. No escalonamento não é chamada: ali a bitola do estribo já estava
    conhecida quando as regiões foram montadas.
    """
    cfg = viga.config
    cob = _cobrimento(viga)
    for r in regioes:
        if not r.construtiva:
            continue
        phi_zona = max((z.phi for z in zonas
                        if z.x_ini < r.x_fim - 1e-9
                        and z.x_fim > r.x_ini + 1e-9),
                       default=cfg.phi_estribo)
        if r.arranjo.phi >= phi_zona - 1e-9:
            continue
        r.arranjo = det.montar_arranjo(
            r.secao, 0.0, phi_zona, cob, phi_zona, cfg.d_agregado,
            n_min=det.CANTOS_POR_FACE, n_ramos=cfg.n_ramos)
        r.d = r.arranjo.d


def _antecipar_reforco_da_costura(viga: Viga, regioes: list[Regiao],
                                  zonas: list[det.ZonaEstribo],
                                  x: np.ndarray, As_inf: np.ndarray,
                                  As_sup: np.ndarray,
                                  cortantes: list[ci.ResultadoCortante],
                                  asl_lateral) -> None:
    """Decide a bitola e o espaçamento finais das faixas uniformizadas.

    Monta um detalhamento **descartável** só para descobrir onde estão as
    emendas e de que bitola são as barras emendadas -- dados que não dependem
    do estribo -- e aplica às faixas o reforço que a costura do item 9.5.2.4.1
    exige. Nada do detalhamento descartável é aproveitado: os avisos vão para
    uma lista jogada fora, e as posições também.

    A rodada custa um segundo detalhamento, e evita quatro remendos em cascata:
    a barra de canto sai já com a bitola do estribo final, o traspasse dela já
    com o comprimento dessa bitola, e o gancho dela já com a perna que essa
    bitola pede.

    Só é chamada com a distribuição uniformizada. No escalonamento a costura
    continua saindo como estribos extra nos terços do traspasse, que é o que a
    Figura 9.5 desenha.
    """
    cob = _cobrimento(viga)
    # é um ponto fixo, e por isso itera: engrossar o estribo engrossa a barra
    # que fecha o canto dele (18.3.3.2), e uma barra mais grossa emenda num
    # traspasse mais longo, que pode pedir mais costura. A sequência é monótona
    # -- a bitola só sobe e o espaçamento só fecha --, então converge; três
    # rodadas bastam com folga, e o laço para assim que nada muda
    for _ in range(4):
        descarte: list[str] = []
        provisorias = _montar_posicoes(viga, regioes, zonas, x, As_inf,
                                       As_sup, cortantes, descarte,
                                       asl_lateral, [], [])
        _repartir_barras_longas(viga, provisorias, descarte, x, As_inf, As_sup)
        antes = [(z.phi, z.s) for z in zonas]
        for tramo, (phi_u, s_u, _motivo) in sorted(
                _exigencias_de_costura(viga, provisorias, zonas).items()):
            for z in [w for w in zonas if w.tramo == tramo]:
                _reforcar_faixa(viga, z, [], phi_u, s_u, cob)
        _construtivas_pela_bitola_do_estribo(viga, regioes, zonas)
        if [(z.phi, z.s) for z in zonas] == antes:
            return


#: espaçamento máximo do estribo de costura no traspasse, em cm (Figura 9.5)
ESPACAMENTO_MAXIMO_DA_COSTURA = 15.0

#: dois traspassos de emendas vizinhas cujas faixas distam menos que isto, em m,
#: viram uma faixa só: um c/20 de 30 cm entre dois c/8 não é distribuição de obra
DISTANCIA_PARA_FUNDIR_FAIXAS = 0.40


def _par_unico_de_costura(exigencias: list[dict]) -> tuple[float, float] | None:
    """O ``(bitola, espaçamento)`` único que atende a todas as exigências.

    Cada exigência traz ``tercos`` -- ``[(terco, As, s_atual)]`` --, a bitola
    mínima (a da faixa) e a máxima (o teto da barra de canto e da bitola
    imposta). Vale a **menor bitola** que atende a todos os terços, com o
    espaçamento do mais exigente: o estribo da faixa é uma posição só, e subir
    de bitola no traspasse cria outra posição no meio do tramo. Escolher a
    bitola de uma emenda e o espaçamento de outra, o que uma primeira versão
    fazia, dava Ø8 c/8 onde Ø5 c/8 atende todas.
    """
    phi_min = max(e["phi_min"] for e in exigencias)
    phi_max = min(e["phi_max"] for e in exigencias)
    for phi in [f for f in det.BITOLAS_ESTRIBOS
                if phi_min - 1e-9 <= f <= phi_max + 1e-9]:
        espacamentos = [_espacamento_que_costura(phi, s_atual, terco, As)
                        for e in exigencias
                        for terco, As, s_atual in e["tercos"]]
        if all(v is not None for v in espacamentos):
            return phi, min(espacamentos)
    return None


def _faixas_de_costura(viga: Viga, posicoes: list[det.Posicao],
                       zonas: list[det.ZonaEstribo]
                       ) -> list[tuple[float, float, float, float, str]]:
    """Trechos de estribo que têm de ser adensados para costurar as emendas.

    Devolve ``[(xa, xb, bitola, espaçamento, motivo)]``, em m e cm, **já
    padronizados**: uma faixa por emenda -- o traspasse inteiro, e não só os
    dois terços extremos, para o desenho não ter um c/20 de um terço entre dois
    c/8 --, todas as de um tramo com o **mesmo par (bitola, espaçamento)**, o
    de menos aço que atende a todas, e faixas que se encostam fundidas numa só.
    Era o que faltava: cada terço virava um grupo de estribos extra de outra
    posição, com contagem e espaçamento próprios (``1 N11 c/15``,
    ``2 N11 c/8,3``, ``3 N11 c/9,1``) por cima do estribo que corria o vão
    inteiro.
    """
    por_tramo: dict[int, list[dict]] = {}
    alguma_falha = False
    for p in posicoes:
        if p.tipo not in ("longitudinal", "porta", "pele"):
            continue
        for x_emenda, l0t in _emendas_de(p):
            terco = l0t / 3.0
            tercos = []
            zona_ref = None
            for _lado, (xa, xb) in _tercos_da_emenda(x_emenda, l0t):
                n_tem, area_tem, s_tem = _estribos_no_intervalo(zonas, xa, xb)
                if s_tem == 0.0:                  # fora de toda faixa
                    continue
                zona = _zona_em(zonas, (xa + xb) / 2.0)
                # o mesmo critério dos estribos extra (`_bitola_da_costura`):
                # o terço está costurado quando tem estribos em número que dê
                # o espaçamento da Figura 9.5 e a área da barra emendada
                n_esp = max(2, math.floor(terco / 15.0 + 1e-9) + 1)
                falha = not (area_barra(p.phi) / 2.0 - area_tem <= 1e-9
                             and n_tem >= n_esp)
                s_zona = zona.s
                if falha:
                    alguma_falha = True
                    if zona.costura:
                        # já está numa faixa de costura e ainda falta: a conta
                        # de dimensionamento supõe um estribo na ponta do
                        # terço, e a faixa pode cair defasada; fecha-se um
                        # degrau da grade, e só então o terço fecha
                        abaixo = [v for v in det.ESPACAMENTOS
                                  if v < zona.s - 1e-9]
                        s_zona = abaixo[-1] if abaixo else zona.s
                elif not zona.costura:
                    continue
                # o terço que já está numa faixa de costura e passa entra na
                # conta mesmo assim: o par (bitola, espaçamento) de um tramo é
                # um só, e fechar uma faixa sozinha desfaria a padronização
                zona_ref = zona_ref or zona
                tercos.append((terco, area_barra(p.phi) / 2.0, s_zona))
            if not tercos:
                continue
            por_tramo.setdefault(zona_ref.tramo, []).append({
                "xa": x_emenda, "xb": x_emenda + l0t / 100.0,
                "tercos": tercos, "phi_min": zona_ref.phi,
                "phi_max": _teto_da_bitola(viga, posicoes, zona_ref),
                "motivo": f"a emenda de N{p.numero} (Ø{p.phi:g}) em "
                          f"x = {x_emenda:.2f} m"})

    if not alguma_falha:
        return []
    faixas: list[tuple[float, float, float, float, str]] = []
    for exigencias in por_tramo.values():
        par = _par_unico_de_costura(exigencias)
        if par is None:
            # nenhum par atende a todas: cada emenda busca o seu; a que nem
            # assim resolve (bitola imposta) fica para os estribos extra
            grupos = [([e], _par_unico_de_costura([e])) for e in exigencias]
        else:
            grupos = [(exigencias, par)]
        for membros, par_g in grupos:
            if par_g is None:
                continue
            fundidas: list[list] = []
            for e in sorted(membros, key=lambda m: m["xa"]):
                if (fundidas and e["xa"] - fundidas[-1][1]
                        <= DISTANCIA_PARA_FUNDIR_FAIXAS):
                    fundidas[-1][1] = max(fundidas[-1][1], e["xb"])
                    fundidas[-1][4] += "; " + e["motivo"]
                else:
                    fundidas.append([e["xa"], e["xb"], par_g[0], par_g[1],
                                     e["motivo"]])
            faixas += [tuple(f) for f in fundidas]
    return sorted(faixas)


def _dividir_faixas(zonas: list[det.ZonaEstribo],
                    faixas: list[tuple[float, float, float, float, str]]
                    ) -> list[det.ZonaEstribo]:
    """Zonas de estribo com as faixas de costura embutidas.

    Cada zona que a faixa atravessa se parte em até três: o que vem antes, a
    faixa adensada e o que vem depois. Nunca se afrouxa: o espaçamento da faixa
    é o menor entre o de costura e o da zona, e a bitola a maior. Uma zona que
    a faixa não aperta fica inteira (partir em três pedaços iguais só
    fragmentaria o desenho), e no fim as zonas vizinhas iguais voltam a ser uma.
    """
    saida = list(zonas)
    for xa, xb, phi, s, _motivo in faixas:
        novas: list[det.ZonaEstribo] = []
        for z in saida:
            a, b = max(xa, z.x_ini), min(xb, z.x_fim)
            if b - a <= 1e-9 or (min(z.s, s) >= z.s - 1e-9
                                 and max(z.phi, phi) <= z.phi + 1e-9):
                novas.append(z)
                continue
            partes = []
            if a - z.x_ini > 1e-9:
                partes.append((z.x_ini, a, z.phi, z.s))
            partes.append((a, b, max(z.phi, phi), min(z.s, s)))
            if z.x_fim - b > 1e-9:
                partes.append((b, z.x_fim, z.phi, z.s))
            for x0, x1, ph, esp in partes:
                # a contagem é a de toda zona (as duas pontas incluídas): é
                # ela que o desenho usa para espaçar, e descontar o estribo da
                # fronteira abria o passo desenhado acima do c/ da cota --
                # um terço de emenda ficava com um estribo a menos
                novas.append(replace(
                    z, x_ini=x0, x_fim=x1, phi=ph, s=esp,
                    asw_ef=det.asw_efetiva(ph, esp, z.n_ramos),
                    n_estribos=max(2, math.ceil((x1 - x0) * 100.0 / esp) + 1),
                    costura=z.costura or (a, b) == (x0, x1)
                    and (ph, esp) != (z.phi, z.s)))
        saida = novas
    # zonas vizinhas com a mesma peça e o mesmo espaçamento são uma faixa só
    fundidas: list[det.ZonaEstribo] = []
    for z in sorted(saida, key=lambda w: w.x_ini):
        if (fundidas and abs(fundidas[-1].x_fim - z.x_ini) < 1e-9
                and fundidas[-1].phi == z.phi and fundidas[-1].s == z.s
                and fundidas[-1].n_ramos == z.n_ramos
                and fundidas[-1].tramo == z.tramo
                and fundidas[-1].trecho == z.trecho):
            ant = fundidas[-1]
            fundidas[-1] = replace(
                ant, x_fim=z.x_fim, asw_req=max(ant.asw_req, z.asw_req),
                costura=ant.costura or z.costura,
                n_estribos=max(2, math.ceil(
                    (z.x_fim - ant.x_ini) * 100.0 / ant.s) + 1))
        else:
            fundidas.append(z)
    return fundidas


def _antecipar_costura_nas_faixas(
        viga: Viga, regioes: list[Regiao], zonas: list[det.ZonaEstribo],
        x: np.ndarray, As_inf: np.ndarray, As_sup: np.ndarray,
        cortantes: list[ci.ResultadoCortante], asl_lateral
        ) -> list[tuple[float, float, float, float, str]]:
    """Embute na distribuição de estribos a costura das emendas (9.5.2.4.1).

    Como no caso uniformizado, monta um detalhamento descartável para saber
    onde estão as emendas e de que bitola são as barras emendadas, e aplica o
    reforço às **faixas** -- mas só nos traspassos, com um par (bitola,
    espaçamento) padrão, em vez de reforçar o tramo inteiro. Modifica ``zonas``
    no lugar e devolve as faixas aplicadas, para o aviso. O que não se resolve
    assim (bitola imposta que não deixa) continua saindo como estribo extra em
    :func:`_costurar_emendas`.
    """
    aplicadas: list[tuple[float, float, float, float, str]] = []
    for _ in range(8):
        descarte: list[str] = []
        provisorias = _montar_posicoes(viga, regioes, zonas, x, As_inf,
                                       As_sup, cortantes, descarte,
                                       asl_lateral, [], [])
        _repartir_barras_longas(viga, provisorias, descarte, x, As_inf, As_sup)
        faixas = _faixas_de_costura(viga, provisorias, zonas)
        if not faixas:
            break
        divididas = _dividir_faixas(zonas, faixas)
        if divididas == zonas:
            break                     # o que sobra fica para os estribos extra
        zonas[:] = divididas
        aplicadas = faixas
        _construtivas_pela_bitola_do_estribo(viga, regioes, zonas)
    return aplicadas


#: referência a uma posição dentro de um texto ("N12"), sem pegar "kN" ou "MN"
_REFERENCIA_A_POSICAO = re.compile(r"(?<![\w/])N(\d+)\b")


def _atualizar_referencias(posicoes: list[det.Posicao], antigos: dict,
                           avisos: list, regioes: list[Regiao]) -> None:
    """Reescreve "N<número>" nos textos com a numeração final.

    As descrições e os avisos são escritos enquanto a viga é montada, com a
    numeração provisória; o agrupamento dos estribos e a renumeração vêm
    depois. Sem esta passada a memória dizia "Costura da emenda de N15"
    quando N15, já renumerada, era a própria costura -- e a barra emendada
    era outra. ``antigos`` leva ``id(posição)`` ao número provisório; um
    número que não sobreviveu ao agrupamento fica como estava.
    """
    novo = {antigos[id(p)]: p.numero for p in posicoes if id(p) in antigos}
    if all(a == b for a, b in novo.items()):
        return

    def trocar(texto: str) -> str:
        return _REFERENCIA_A_POSICAO.sub(
            lambda m: f"N{novo.get(int(m.group(1)), int(m.group(1)))}", texto)

    for p in posicoes:
        p.descricao = trocar(p.descricao)

    def trocar_avisos(lista: list) -> None:
        for i, a in enumerate(lista):
            t = trocar(a)
            if t != a:
                lista[i] = av.Aviso(t, av.nivel_de(a))

    trocar_avisos(avisos)
    for r in regioes:
        trocar_avisos(r.avisos)


def _costurar_emendas(viga: Viga, posicoes: list[det.Posicao],
                      zonas: list[det.ZonaEstribo], avisos: list[str]) -> None:
    """Armadura transversal nas emendas por traspasse (9.5.2.4.1).

    Com Ø >= 16 mm ou 25 % ou mais das barras emendadas na mesma seção -- e o
    programa adota 50 % (alfa_0t = 1,8) --, a armadura transversal da emenda
    tem de resistir à força de **uma barra emendada**, ser concentrada nos
    terços extremos do traspasse e ter espaçamento não maior que 15 cm
    (Figura 9.5). Contam-se os ramos paralelos ao plano da emenda: para barras
    na mesma camada de uma face, é o ramo do estribo junto àquela face, um por
    estribo -- contagem conservadora, que ignora o ramo da face oposta.
    """
    if not zonas:
        return
    novas: list[det.Posicao] = []
    numero = max((p.numero for p in posicoes), default=0)
    cob = _cobrimento(viga)
    cfg = viga.config
    resolvidas = 0
    # com a distribuição uniformizada, a costura é **absorvida pela própria
    # faixa**: pedir uma distribuição por tramo e receber grupinhos de estribos
    # de outra bitola e outro espaçamento no meio dele desfaz exatamente o que
    # a uniformização promete. Aqui só se coleta a exigência; o reforço é
    # aplicado depois, uma vez por faixa, com o pior terço de todas as emendas
    # com a distribuição uniformizada a costura é **absorvida pela própria
    # faixa**: pedir uma distribuição por tramo e receber grupinhos de estribos
    # de outra bitola e outro espaçamento no meio dele desfaz exatamente o que
    # a uniformização promete. A exigência é a mesma que o pré-passe já aplicou
    # às faixas; aqui ela é reaplicada como rede de proteção, e normalmente não
    # muda nada
    exige = (_exigencias_de_costura(viga, posicoes, zonas)
             if cfg.uniformizar_estribos else {})
    for p in list(posicoes):
        if p.tipo not in ("longitudinal", "porta", "pele"):
            continue
        if cfg.uniformizar_estribos:
            continue
        for x_emenda, l0t in _emendas_de(p):
            terco = l0t / 3.0
            n_esp = max(2, math.floor(terco / 15.0 + 1e-9) + 1)
            for lado, (xa, xb) in _tercos_da_emenda(x_emenda, l0t):
                n_tem, area_tem, s_tem = _estribos_no_intervalo(zonas, xa, xb)
                if s_tem == 0.0:                  # fora de toda faixa
                    continue
                zona = _zona_em(zonas, (xa + xb) / 2.0)
                # área exigida no terço: metade da força de uma barra emendada
                # (Figura 9.5), contando um ramo por estribo
                falta = area_barra(p.phi) / 2.0 - area_tem
                if falta <= 1e-9 and s_tem <= 15.0 + 1e-9:
                    resolvidas += 1
                    continue
                phi_c, faltam = _bitola_da_costura(
                    falta, zona.phi, terco, n_tem, n_esp)
                if faltam == 0:
                    resolvidas += 1
                    continue
                numero += 1
                s_costura = min(15.0, terco / max(n_tem + faltam - 1, 1))
                # o texto diz o que faltou: com a área atendida, o que manda é
                # o espaçamento de 15 cm da Figura 9.5, e dizer só "dão 0,79
                # dos 0,16 cm² exigidos" fazia o estribo extra parecer sem razão
                exigida = area_barra(p.phi) / 2.0
                if falta <= 1e-9:
                    razao = (f"a área ({area_tem:.2f} cm² contra "
                             f"{exigida:.2f} cm²) está atendida, mas os "
                             f"{n_tem} estribo(s) existentes no terço ficam a "
                             f"{s_tem:g} cm, acima dos 15 cm da Figura 9.5")
                else:
                    razao = (f"os {n_tem} estribo(s) existentes no terço dão "
                             f"{area_tem:.2f} cm² dos {exigida:.2f} cm² "
                             f"exigidos")
                novas.append(det.Posicao(
                    numero=numero, tipo="costura", n=faltam, phi=phi_c,
                    n_ramos_efetivo=zona.n_ramos,
                    face="alma", x_ini=xa, x_fim=xb,
                    comprimento=_comprimento_estribo(
                        viga.secao_em((xa + xb) / 2.0), cob, phi_c,
                        cfg.pernas_amarracao_estribo, zona.n_ramos,
                        cfg.gancho_estribo),
                    s=round(s_costura, 1), tramo=zona.tramo,
                    descricao=(f"Costura da emenda de N{p.numero} "
                               f"(Ø{p.phi:g}) em x = {x_emenda:.2f} m — "
                               f"{faltam} estribo(s) extra no terço {lado} do "
                               f"traspasse de {l0t:.0f} cm (9.5.2.4.1); "
                               f"{razao}")))
    _avisar_teto_da_costura(viga, posicoes, zonas, avisos)
    for tramo, (phi_u, s_u, motivo) in sorted(exige.items()):
        faixas = [z for z in zonas if z.tramo == tramo]
        if not faixas:
            continue
        antes = (faixas[0].phi, faixas[0].s)
        for z in faixas:
            _reforcar_faixa(viga, z, posicoes, phi_u, s_u, cob)
        if (phi_u, s_u) == antes:
            resolvidas += 1
            continue
        engrossados = _engrossar_porta_estribos(
            posicoes, min(z.x_ini for z in faixas),
            max(z.x_fim for z in faixas), phi_u)
        if engrossados:
            # engrossar a barra alonga o traspasse dela (l0t cresce com Ø), e
            # o traspasse que existia deixa de bastar. Refazer a emenda das
            # faces é o que restabelece a continuidade -- sem isto a viga saía
            # com "N4 e N5 se sobrepõem 43 cm, menos que o traspasse de 43 cm"
            novos: list[str] = []
            _emendar_faces(viga, posicoes, novos)
            avisos.extend(a for a in novos if a not in avisos)
        avisos.append(av.construtivo(
            f"Tramo {tramo + 1}: a distribuição uniformizada foi reforçada de "
            f"Ø{antes[0]:g} c/{antes[1]:g} para Ø{phi_u:g} c/{s_u:g} para "
            f"absorver a costura da emenda exigida por {motivo} (9.5.2.4.1). "
            f"Com a distribuição uniformizada a costura entra na própria "
            f"faixa, e não como estribos soltos de outra bitola no meio do "
            f"tramo — é o que a uniformização promete, e custa aço."
            + (f" {engrossados} porta-estribo(s) do tramo tiveram a bitola "
               f"elevada a Ø{phi_u:g}, porque o item 18.3.3.2 não admite barra "
               f"de canto mais fina que o estribo." if engrossados else "")))
    if novas:
        avisos.append(av.construtivo(
            f"Acrescentados {sum(p.n for p in novas)} estribos de costura em "
            f"{len(novas)} emenda(s): o item 9.5.2.4.1 exige armadura "
            f"transversal capaz de resistir à força de uma barra emendada, "
            f"concentrada nos terços extremos do traspasse e com espaçamento "
            f"não maior que 15 cm."))
        posicoes.extend(novas)
    if resolvidas:
        avisos.append(av.construtivo(
            f"Em {resolvidas} emenda(s) os estribos já existentes atendem à "
            f"armadura transversal do item 9.5.2.4.1; nada foi acrescentado."))


#: espaçamento mínimo prático entre estribos, cm -- o item 18.3.3.2 o define
#: qualitativamente ("suficiente para permitir a passagem do vibrador")
ESPACAMENTO_MINIMO_ESTRIBO = 7.0


def _avisar_teto_da_costura(viga: Viga, posicoes: list[det.Posicao],
                            zonas: list[det.ZonaEstribo],
                            avisos: list[str]) -> None:
    """Avisa quando a bitola imposta não permite absorver a costura.

    Respeitar a escolha do usuário é o certo, e ficar calado sobre a
    consequência não é: se com a bitola imposta e o espaçamento mínimo a
    costura do item 9.5.2.4.1 continua faltando, ele precisa saber que a saída
    é liberar a bitola ou aceitar a costura como estribos extra.
    """
    if not viga.config.uniformizar_estribos:
        return
    for tramo, (phi_u, s_u, motivo) in sorted(
            _exigencias_de_costura(viga, posicoes, zonas).items()):
        faixas = [z for z in zonas if z.tramo == tramo]
        if not faixas:
            continue
        imposta = float((viga.config.bitolas_estribo or {})
                        .get(str(tramo), 0.0) or 0.0)
        if not imposta or (phi_u, s_u) != (faixas[0].phi, faixas[0].s):
            continue
        # a exigência sobreviveu ao reforço: o teto travou tudo o que havia
        avisos.append(av.erro(
            f"Tramo {tramo + 1}: com a bitola de estribo imposta em "
            f"Ø{imposta:g} e o espaçamento em c/{faixas[0].s:g}, a costura da "
            f"emenda exigida por {motivo} não é atendida (9.5.2.4.1). O "
            f"espaçamento já está no mínimo prático de "
            f"{ESPACAMENTO_MINIMO_ESTRIBO:g} cm, e a bitola não sobe porque "
            f"foi imposta. Libere a bitola do tramo, mude a posição da emenda "
            f"ou desligue a uniformização e aceite a costura como estribos "
            f"extra nos terços do traspasse."))


def _estribos_no_intervalo(zonas: list[det.ZonaEstribo], xa: float,
                           xb: float) -> tuple[int, float, float]:
    """Estribos existentes entre ``xa`` e ``xb`` (m): (nº, área, maior s).

    Conta os estribos **onde o desenho os põe**: cada faixa espaça os seus
    ``n_estribos`` de ponta a ponta, e o que cai dentro do intervalo é o que
    está lá. A conta anterior supunha um estribo na ponta do intervalo, e um
    terço de 25 cm numa faixa c/20 saía com dois estribos quando a obra
    encontrava um -- o item 9.5.2.4.1 fica por conta de quem lê o desenho.

    Percorre **todas** as faixas que intersectam o intervalo, e não uma só. A
    diferença aparece justamente onde a emenda importa: o item 9.5.2.1 manda
    emendar em região de menor solicitação, que numa viga contínua é perto do
    apoio -- e ali o traspasse atravessa a divisa entre dois tramos, com
    espaçamento diferente de cada lado. O estribo da divisa é um só, o de maior área.

    A área é de **um ramo por estribo**, contagem conservadora que ignora o
    ramo da face oposta, como o resto do item já faz. O maior ``s`` volta junto
    porque é ele que decide o limite de 15 cm da Figura 9.5: um intervalo
    coberto por duas faixas está atendido só se a mais aberta das duas atender.
    Intervalo fora de toda faixa devolve ``(0, 0, 0)``; intervalo coberto sem
    nenhum estribo dentro devolve ``n = 0`` com o ``s`` da faixa.
    """
    postos: dict[int, float] = {}
    s_max = 0.0
    coberto = False
    for z in zonas:
        a, b = max(xa, z.x_ini), min(xb, z.x_fim)
        if b - a < -1e-9:
            continue
        coberto = True
        n_z = max(2, z.n_estribos)
        passo = (z.x_fim - z.x_ini) / (n_z - 1)
        for k in range(n_z):
            x = z.x_ini + k * passo
            if xa - 1e-6 <= x <= xb + 1e-6:
                # na divisa das faixas o estribo é um só, o da mais forte: as
                # duas contam o estribo da divisa no quantitativo, e o que
                # fica na obra é o que resiste mais
                chave = round(x * 1e4)
                postos[chave] = max(postos.get(chave, 0.0), area_barra(z.phi))
                s_max = max(s_max, z.s)
    if not coberto:
        z = _zona_em(zonas, (xa + xb) / 2.0)
        if z is None:
            return 0, 0.0, 0.0
        return 0, 0.0, z.s
    if not postos:
        z = _zona_em(zonas, (xa + xb) / 2.0)
        return 0, 0.0, z.s if z is not None else 0.0
    return len(postos), sum(postos.values()), s_max


def _bitola_da_costura(falta: float, phi_ref: float, terco: float,
                       n_tem: int, n_esp: int) -> tuple[float, int]:
    """Bitola e nº de estribos extra por terço da emenda.

    Adensar o estribo fino até cobrir a área exigida produzia espaçamentos de
    5 cm, que não passam vibrador. Sobe-se a bitola até que o espaçamento
    resultante fique acima do mínimo prático.
    """
    candidatas = [phi for phi in det.BITOLAS_ESTRIBOS if phi >= phi_ref]
    for phi in candidatas or [phi_ref]:
        n_area = max(0, math.ceil(max(falta, 0.0) / area_barra(phi) - 1e-9))
        faltam = max(n_area, n_esp - n_tem)
        if faltam <= 0:
            return phi, 0
        s = terco / max(n_tem + faltam - 1, 1)
        if s >= ESPACAMENTO_MINIMO_ESTRIBO - 1e-9 or phi == candidatas[-1]:
            return phi, faltam
    return phi_ref, 0


def _zona_em(zonas: list[det.ZonaEstribo], x: float):
    """Zona de estribos que contém a abscissa ``x`` (m)."""
    for z in zonas:
        if z.x_ini - 1e-6 <= x <= z.x_fim + 1e-6:
            return z
    return min(zonas, key=lambda z: min(abs(z.x_ini - x), abs(z.x_fim - x)),
               default=None)


def _quantitativo(viga: Viga, posicoes: list[det.Posicao]) -> dict:
    """Resumo de aço por bitola, mais concreto e formas.

    O aço sai das posições; o **concreto** e as **formas** saem da geometria,
    somados trecho a trecho -- é o trecho que tem seção constante, então é
    nele que a área da seção e o perímetro de forma são um número só. Numa
    viga de seção variável somar pelo tramo daria o volume errado.

    Medição **de eixo a eixo dos apoios**, sem descontar o cruzamento com
    pilares ou vigas: é a hipótese de elemento isolado, e é declarada na
    saída. Num quantitativo de obra o volume do nó costuma ser lançado no
    pilar, e aí este número é ligeiramente a favor da segurança.
    """
    por_bitola: dict[float, dict] = {}
    for p in posicoes:
        d = por_bitola.setdefault(p.phi, {"comprimento": 0.0, "massa": 0.0,
                                          "barras": 0})
        d["comprimento"] += p.comprimento_total
        d["massa"] += p.massa
        d["barras"] += p.n
    total = sum(d["massa"] for d in por_bitola.values())

    # concreto e formas, trecho a trecho
    volume = 0.0                      # m³
    forma = 0.0                       # m²
    por_trecho: list[dict] = []
    for t in viga.trechos:
        v = t.secao.area * t.L * 1e-4          # cm² . m -> m³
        f = t.secao.perimetro_forma * t.L * 1e-2   # cm . m -> m²
        volume += v
        forma += f
        por_trecho.append({
            "trecho": t.k + 1, "tramo": t.tramo + 1, "L": t.L,
            "secao": t.secao.descricao(),
            "area": t.secao.area, "perimetro_forma": t.secao.perimetro_forma,
            "volume": v, "forma": f})

    comprimento = sum(t.L for t in viga.trechos)
    tem_mesa = any(t.secao.tipo != "retangular" for t in viga.trechos)
    return {
        "por_bitola": dict(sorted(por_bitola.items())),
        "massa_total": total,
        "massa_com_perdas": total * 1.10,
        "comprimento": comprimento,
        "concreto_m3": volume,
        "forma_m2": forma,
        "por_trecho": por_trecho,
        #: kg de aço por m³ de concreto -- indicador de consumo
        "taxa_aco": total / volume if volume > 0 else 0.0,
        "hipotese_forma": (
            "Elemento isolado: forma no fundo e nas laterais, topo aberto "
            "(face de lançamento). Medição de eixo a eixo dos apoios, sem "
            "desconto de cruzamentos."
            + (" A viga tem seção com mesa: se a mesa for a laje, essa "
               "parcela da forma pertence à laje e deve ser descontada."
               if tem_mesa else "")),
    }
